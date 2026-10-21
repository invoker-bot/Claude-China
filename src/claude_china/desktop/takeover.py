"""Per-application preflight shared by launch interceptors on each platform."""

import json
import os
from pathlib import Path
import re
import sys
import time

from .apps import get_app
from .bridge import LauncherBridge
from .platforms import get_backend
from .platforms.base import AppStatus


WINDOWS_EXECUTABLES = {'claude': 'Claude.exe', 'codex': 'Codex.exe', 'grok-bot': 'Grok Bot.exe'}


def checked_target(value, app_id='grok-bot', must_exist=True):
    """Validate Windows image identity without accepting a different app's CLI."""
    expected = WINDOWS_EXECUTABLES.get(app_id)
    if not expected:
        raise ValueError('未知的接管应用。')
    if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
        raise ValueError('接管路径必须是绝对路径。')
    target = Path(value).resolve(strict=must_exist)
    if target.name.lower() != expected.lower() or (must_exist and not target.is_file()):
        raise ValueError(f'此接管配置只接受 {expected}。')
    return target


class _PreflightBackend:
    def __init__(self, target, app_id, backend):
        self.target = str(target)
        self.app_id = app_id
        self.backend = backend
        self.environment = None

    def detect(self, app, override_path=None):
        if app.id != self.app_id:
            raise ValueError('接管应用与检查配置不一致。')
        return AppStatus(app.id, found=True, direct=True,
                         launch_target=self.target, match_root=self.target)

    def proxy_enabled(self):
        return self.backend.proxy_enabled()

    def system_http_proxy(self):
        return self.backend.system_http_proxy()

    def safety_proxy(self):
        return self.backend.safety_proxy()

    def stop(self, status):
        # Deep links, ordinary launches and updater restarts must not stop apps.
        pass

    def launch(self, status, env):
        self.environment = dict(env)


ORIGINAL_ENV = 'CLAUDEC_TAKEOVER_ORIGINAL_ENV'


def prepare_launch(target, inherited=None, app_id='grok-bot', backend=None):
    app = get_app(app_id)
    target = Path(target).resolve(strict=True)
    if not target.is_file():
        raise ValueError('未找到应用的可执行文件。')
    backend = backend if backend is not None else get_backend()
    if backend is None:
        raise ValueError('当前系统尚不支持启动检查。')
    base = dict(os.environ if inherited is None else inherited)
    previous = json.loads(base.pop(ORIGINAL_ENV, '{}'))
    if not isinstance(previous, dict) or any(not isinstance(k, str) or (v is not None and not isinstance(v, str))
                                             for k, v in previous.items()):
        raise ValueError('接管环境记录无效。')
    for key, value in previous.items():
        base.pop(key, None)
        if value is not None:
            base[key] = value
    base.pop('CLAUDEC_TAKEOVER_TARGET', None)
    preflight = _PreflightBackend(target, app_id, backend)
    result = LauncherBridge(preflight, [app], base_env=base).launch_app(app_id)
    if preflight.environment is not None:
        original = {key: base.get(key) for key, value in preflight.environment.items()
                    if value != base.get(key) and key != ORIGINAL_ENV}
        # Only prior values of overwritten variables travel with the process.
        # They are never written to diagnostics or the registration manifest.
        preflight.environment[ORIGINAL_ENV] = json.dumps(original, ensure_ascii=True)
    return result, preflight.environment


def validate_manifest(manifest, argv, must_exist=True):
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1
            or manifest.get('app_id') not in WINDOWS_EXECUTABLES
            or not isinstance(manifest.get('owner'), str)
            or not re.fullmatch(r'[a-f0-9]{32}', manifest['owner'])):
        raise ValueError('无效的应用接管配置。')
    target = checked_target(manifest.get('target'), manifest['app_id'], must_exist=must_exist)
    if not argv or Path(argv[0]).resolve() != target:
        raise ValueError('接管入口与注册路径不一致，已取消启动。')
    return target


def get_status(app_id, status):
    """Capabilities are explicit: launcher checks are not global interception."""
    get_app(app_id)
    if sys.platform == 'win32':
        from .takeover_windows import get_status as windows_status
        return windows_status(app_id, status)
    message = {
        'darwin': 'macOS 原入口和更新重启接管尚未实现；目前仅从本启动器启动时执行检查。',
        'linux': 'Linux 原入口和更新重启接管尚未实现；目前仅从本启动器启动时执行检查。',
    }.get(sys.platform, '当前操作系统尚不支持全局接管。')
    return {'app_id': app_id, 'supported': False, 'enabled': False,
            'can_disable': False, 'mode': 'unavailable', 'message': message}


def set_enabled(app_id, enabled, status):
    get_app(app_id)
    if not isinstance(enabled, bool):
        raise ValueError('无效的接管设置。')
    capability = get_status(app_id, status)
    if sys.platform != 'win32' or (enabled and not capability['supported']):
        raise ValueError(capability['message'])
    from .takeover_windows import set_enabled as windows_enable
    return windows_enable(enabled, status.launch_target, app_id=app_id)


def run_broker(manifest_path, argv):
    from .takeover_native import launch_with_hook
    from .takeover_windows import supported_target
    import psutil

    manifest_path = Path(manifest_path).resolve(strict=True)
    record = {'time': time.time(), 'broker_pid': os.getpid(), 'ok': False}
    result = {'ok': False, 'error': '全局接管失败，已取消启动。'}
    try:
        import ctypes
        if ctypes.windll.shell32.IsUserAnAdmin():
            raise ValueError('接管入口不允许以管理员身份启动应用。')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        target = validate_manifest(manifest, argv)
        supported_target(target, manifest['app_id'])
        record['app_id'] = manifest['app_id']
        result, env = prepare_launch(target, app_id=manifest['app_id'])
        record['decision'] = result.get('safety', {}).get('status', 'disabled')
        if result['ok']:
            # Rebuilt for every launch, including update restarts. Nothing is
            # injected into the user's global/session environment.
            pid = launch_with_hook(argv, env, os.getcwd())
            record.update(ok=True, target_pid=pid)
    except Exception:
        result = {'ok': False, 'error': '全局接管未能安全创建进程，请在启动器中检查接管状态。'}
    record['error'] = result.get('error', '')
    logs = manifest_path.parent / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f'{time.time_ns()}-{os.getpid()}.json'
    path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    for old in sorted(logs.glob('*.json'))[:-50]:
        try:
            old.unlink()
        except OSError:
            pass
    if not record['ok']:
        import ctypes
        from .localization import display_message
        ctypes.windll.user32.MessageBoxW(None, display_message(record['error']),
                                       display_message('Claude China · 启动已取消'), 0x10)
        return 1
    try:
        code = psutil.Process(record['target_pid']).wait()
    except psutil.NoSuchProcess:
        code = 1
    record.update(exit_code=code, exited_at=time.time())
    path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    return code
