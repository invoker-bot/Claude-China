"""Desktop management of the CLI's real profiles, without returning credentials."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
from urllib.parse import urlsplit

from .. import config as cli_config
from ..launcher import prepare_environment, resolve_default_args, PROXY_ENV_VARS
from ..models import VALID_TYPES, OFFICIAL_BASE_URLS, profile_from_dict, profile_to_dict
from . import config, safety, terminal_history
from .env import merge_env
from .platforms.base import AppStatus
from .proxy import SystemProxyError
from .terminal_host import resolve_cli_argv

_STORE_LOCK = threading.RLock()
TOOL_NAMES = {'claude': 'Claude Code', 'codex': 'Codex CLI', 'grok': 'Grok CLI'}


def _revision(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _text(value, label, required=False):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError(label + '格式无效。')
    if required and not value.strip():
        raise ValueError('请填写' + label + '。')
    return value.strip()


def directory_path(value):
    value = _text(value, '项目目录', required=True)
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError('项目目录不存在，请选择一个现有文件夹。')
    return str(path.resolve())


def _directories(values, limit):
    if not isinstance(values, list):
        return []
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str) or any(ord(c) < 32 for c in value):
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            continue
        directory = str(path.resolve())
        key = os.path.normcase(directory)
        if key not in seen:
            result.append(directory)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _url(value, label, schemes=('http', 'https')):
    value = _text(value, label)
    if value:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in schemes or not parsed.hostname or any(c.isspace() for c in value):
                raise ValueError()
            parsed.port
        except ValueError:
            raise ValueError(label + '格式无效。') from None
    return value


def _read():
    data = cli_config.load_config()
    if not isinstance(data, dict) or not isinstance(data.get('profiles'), dict):
        raise ValueError('CLI 配置文件格式无效，请先修复配置。')
    return data


def _existing(data, name, revision=None):
    record = data['profiles'].get(name)
    if not isinstance(record, dict):
        raise ValueError('配置已不存在，请刷新列表。')
    if revision is not None and _revision(record) != revision:
        raise ValueError('此配置已发生变化，请重新打开后再操作。')
    return record


def _public(name, record, detail=False):
    kind, mode = record.get('type', ''), record.get('mode', 'api')
    result = {'name': name, 'type': kind, 'mode': mode, 'revision': _revision(record),
              'has_secret': bool(record.get('token') or record.get('api_key')),
              'supported': kind in VALID_TYPES and mode in ('api', 'login')}
    if detail:
        result.update(base_url=record.get('base_url', ''), proxy=record.get('proxy', ''),
                      credentials_path=record.get('credentials_path', ''),
                      manual_browser_login=record.get('manual_browser_login') is True,
                      default_args=resolve_default_args(record.get('default_args')))
    else:
        try:
            parsed = urlsplit(record.get('base_url') or OFFICIAL_BASE_URLS.get(kind, ''))
            result['endpoint'] = parsed.hostname or ''
        except ValueError:
            result['endpoint'] = ''
    return result


class TerminalService:
    def __init__(self, backend):
        self.backend = backend

    def list_profiles(self):
        with _STORE_LOCK:
            return [_public(name, record) for name, record in _read()['profiles'].items()
                    if isinstance(record, dict)]

    def get_profile(self, name):
        with _STORE_LOCK:
            return _public(name, _existing(_read(), name), detail=True)

    def save_profile(self, payload, original_name=None, revision=None):
        if not isinstance(payload, dict):
            raise ValueError('无效的配置。')
        name = _text(payload.get('name'), '配置名称', required=True)
        if len(name) > 80:
            raise ValueError('配置名称不能超过 80 个字符。')
        kind, mode = payload.get('type'), payload.get('mode')
        if kind not in VALID_TYPES or mode not in ('api', 'login'):
            raise ValueError('请选择支持的 CLI 工具和认证方式。')
        arguments = payload.get('default_args', [])
        if not isinstance(arguments, list) or any(not isinstance(v, str) or '\0' in v for v in arguments):
            raise ValueError('默认参数必须是字符串数组。')
        proxy = _url(payload.get('proxy') or '', '代理地址', ('http', 'https', 'socks5', 'socks5h'))
        with _STORE_LOCK:
            data = _read()
            old = _existing(data, original_name, revision or '') if original_name is not None else {}
            if name in data['profiles'] and name != original_name:
                raise ValueError('配置名称已存在，请使用其他名称。')
            value = {'name': name, 'type': kind, 'mode': mode, 'proxy': proxy or None,
                     'default_args': arguments}
            if mode == 'login':
                credentials = _text(payload.get('credentials_path'), '登录配置目录', required=True)
                if not Path(credentials).expanduser().is_absolute():
                    raise ValueError('登录配置目录必须使用绝对路径或 ~ 开头的路径。')
                value['credentials_path'] = credentials
                unchanged = old.get('type') == kind and old.get('mode', 'api') == mode
                manual = payload.get('manual_browser_login', old.get('manual_browser_login', False) if unchanged else False)
                if not isinstance(manual, bool) or (manual and kind != 'claude'):
                    raise ValueError('手动浏览器登录目前仅支持 Claude Code。')
                value['manual_browser_login'] = manual
            else:
                value['base_url'] = _url(payload.get('base_url') or OFFICIAL_BASE_URLS[kind], 'API 地址')
                key = 'token' if kind == 'claude' else 'api_key'
                secret = payload.get('secret', '')
                if not isinstance(secret, str) or '\0' in secret or '\n' in secret or '\r' in secret:
                    raise ValueError('密钥格式无效。')
                unchanged = old.get('type') == kind and old.get('mode', 'api') == mode
                value[key] = None if payload.get('clear_secret') else secret or (old.get(key) if unchanged else None)
            record = profile_to_dict(profile_from_dict(value))
            # Keep extension fields written by CLI versions this UI does not know.
            fields = {'name', 'type', 'mode', 'proxy', 'default_args', 'base_url', 'token', 'api_key', 'credentials_path',
                      'manual_browser_login'}
            record = {**{k: v for k, v in old.items() if k not in fields}, **record}
            if original_name is not None:
                del data['profiles'][original_name]
            data['profiles'][name] = record
            cli_config.save_config(data)
            return _public(name, record, detail=True)

    def copy_profile(self, name, revision):
        from .localization import display_message
        with _STORE_LOCK:
            data = _read()
            record = deepcopy(_existing(data, name, revision))
            base = name[:65] + ' ' + display_message('副本')
            new_name, number = base, 2
            while new_name in data['profiles']:
                new_name, number = base + ' ' + str(number), number + 1
            record['name'] = new_name
            data['profiles'][new_name] = record
            cli_config.save_config(data)
            return _public(new_name, record)

    def delete_profile(self, name, revision):
        with _STORE_LOCK:
            data = _read()
            _existing(data, name, revision)
            del data['profiles'][name]
            cli_config.save_config(data)

    def workspace(self):
        prefs = config.load_desktop_config().get('terminals', {})
        prefs = prefs if isinstance(prefs, dict) else {}
        recent = _directories(prefs.get('recent_directories'), 20)
        favorites = _directories(prefs.get('favorite_directories'), 50)
        favorite_keys = {os.path.normcase(p) for p in favorites}
        projects = _directories(favorites + recent, 70)
        return {'directory': prefs.get('directory') or str(Path.home()),
                'recent_directories': recent, 'favorite_directories': favorites,
                'last_profile': prefs.get('last_profile'),
                'projects': [{'directory': p, 'name': Path(p).name or p,
                              'favorite': os.path.normcase(p) in favorite_keys, 'available': Path(p).is_dir()}
                             for p in projects],
                'tools': [{'id': kind, 'display': TOOL_NAMES[kind],
                           'installed': bool(shutil.which(kind + '.cmd') or shutil.which(kind)) if sys.platform == 'win32' else bool(shutil.which(kind))}
                          for kind in VALID_TYPES]}

    def remember_directory(self, directory, profile=None):
        directory = directory_path(directory)
        with _STORE_LOCK, config.CONFIG_LOCK:
            data = config.load_desktop_config()
            recent = self.workspace()['recent_directories']
            prefs = data.get('terminals')
            prefs = prefs if isinstance(prefs, dict) else {}
            prefs.update(directory=directory, recent_directories=_directories([directory] + recent, 20))
            if profile is not None:
                prefs['last_profile'] = profile
            data['terminals'] = prefs
            config.save_desktop_config(data)
        return directory

    def set_favorite(self, directory, favorite):
        if not isinstance(favorite, bool):
            raise ValueError('无效的收藏操作。')
        # Removing a favorite must also work after its folder was moved/deleted.
        if favorite:
            directory = directory_path(directory)
        else:
            paths = _directories([directory], 1)
            if not paths:
                raise ValueError('项目目录格式无效。')
            directory = paths[0]
        with _STORE_LOCK, config.CONFIG_LOCK:
            data = config.load_desktop_config()
            prefs = data.get('terminals')
            prefs = prefs if isinstance(prefs, dict) else {}
            current = _directories(prefs.get('favorite_directories'), 50)
            current = [p for p in current if os.path.normcase(p) != os.path.normcase(directory)]
            if favorite:
                if len(current) >= 50:
                    raise ValueError('最多收藏 50 个项目，请先取消其他收藏。')
                current.insert(0, directory)
            prefs['favorite_directories'] = current
            data['terminals'] = prefs
            config.save_desktop_config(data)

    def history(self, name):
        record = deepcopy(_existing(_read(), name))
        if not _public(name, record)['supported']:
            raise ValueError('此 CLI 配置类型暂不支持，请先编辑配置。')
        return terminal_history.list_sessions(record['type'], terminal_history.profile_home(record))

    def _session(self, record, session_id):
        terminal_history.resume_args(record['type'], session_id, [])
        history = terminal_history.list_sessions(record['type'], terminal_history.profile_home(record))
        session = next((s for s in history['sessions'] if s['id'] == session_id), None)
        if session is None:
            raise ValueError('此配置下找不到该会话，请刷新历史记录后重试。')
        return session

    def resume_session(self, name, session_id):
        record = _existing(_read(), name)
        if not _public(name, record)['supported']:
            raise ValueError('此 CLI 配置类型暂不支持。')
        session = self._session(record, session_id)
        self.launch(name, session['directory'], session_id=session_id)

    def prepare(self, name, directory, session_id=None):
        directory = directory_path(directory)
        record = deepcopy(_existing(_read(), name))
        if not _public(name, record)['supported']:
            raise ValueError('此 CLI 配置类型暂不支持，请先编辑配置。')
        arguments = resolve_default_args(record.get('default_args'))
        if session_id is not None:
            session = self._session(record, session_id)
            if directory_path(session['directory']) != directory:
                raise ValueError('会话的项目目录已发生变化，请刷新历史记录。')
            arguments = terminal_history.resume_args(record['type'], session_id, arguments)
        else:
            arguments = terminal_history.new_session_args(record['type'], arguments)
        argv = resolve_cli_argv(record['type']) + arguments
        data = config.load_desktop_config()
        from . import cli_guard, egress, playwright_guard
        tun_mode = egress.tun_enabled("playwright", data)
        if not tun_mode and config.get_check_system_proxy(data) and not self.backend.proxy_enabled():
            raise ValueError('系统代理未开启，已取消启动。')
        proxy = None
        if not tun_mode and config.get_auto_proxy_env(data):
            try:
                proxy = self.backend.system_http_proxy()
            except SystemProxyError as exc:
                raise ValueError(str(exc) + ' 已取消启动。') from None
            except Exception:
                raise ValueError('无法读取系统 HTTP 代理，已取消启动。') from None
        env = prepare_environment(profile_from_dict(record),
                                  base_env=merge_env(os.environ, config.get_common_env(data)))
        if proxy and not record.get('proxy'):
            env.update({key: proxy for key in PROXY_ENV_VARS})
        env = playwright_guard.prepare_environment(env, data=data)
        argv, env = cli_guard.prepare(argv, env, data=data)
        settings = config.get_safety_settings(data)
        if settings['enabled']:
            app_id = 'grok-bot' if record['type'] == 'grok' else record['type']
            try:
                status = AppStatus(app_id, True, True, argv[0], argv[0])
                if cli_guard.enabled(data):
                    tunnel = (egress._store().read().get('playwright') or {}).get('tunnel')
                    if not tunnel:
                        raise egress.GuardError('无法验证 CLI 的 TUN 隧道。')
                    report = safety.inspect_environment(app_id, env, self.backend, status, tunnel=tunnel)
                else:
                    report = safety.inspect_environment(app_id, env, self.backend, status)
            except Exception:
                report = {'status': 'unknown', 'reason': '无法确认环境。'}
            if not safety.launch_allowed(report, settings):
                raise ValueError('安全检查未通过：' + report.get('reason', '无法确认环境。'))
        if config.launch_settings_changed(data, config.load_desktop_config()) or _existing(_read(), name) != record:
            raise ValueError('检测期间配置发生变化，请重新启动。')
        return argv, env

    def launch(self, name, directory, session_id=None):
        from . import terminal_host
        directory = directory_path(directory)
        if session_id is not None and name is None:
            raise ValueError('恢复会话需要选择 CLI 配置。')
        if name is not None:
            if session_id is None:
                self.prepare(name, directory)
            else:
                self.prepare(name, directory, session_id=session_id)
        path = terminal_host.create_job(name, directory, session_id=session_id)
        try:
            terminal_host.open_terminal(path, directory)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self.remember_directory(directory, profile=name)
