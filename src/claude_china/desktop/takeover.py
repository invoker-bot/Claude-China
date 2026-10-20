"""Grok Bot launch preflight shared by normal entries and update restarts."""

import json
import os
from pathlib import Path
import re
import time

from .apps import get_app
from .bridge import LauncherBridge
from .platforms.base import AppStatus
from .platforms.windows import WindowsBackend


def checked_target(value):
    target = Path(value).resolve(strict=True)
    if not target.is_file() or target.name.lower() != 'grok bot.exe':
        raise ValueError('全局接管目前仅支持 Grok Bot.exe。')
    return target


class _PreflightBackend(WindowsBackend):
    def __init__(self, target):
        self.target = str(target)
        self.environment = None

    def detect(self, app, override_path=None):
        if app.id != 'grok-bot':
            raise ValueError('Only Grok Bot is supported')
        return AppStatus(app.id, found=True, direct=True,
                         launch_target=self.target, match_root=self.target)

    def stop(self, status):
        # Deep links, ordinary launches and updater restarts must not stop apps.
        pass

    def launch(self, status, env):
        self.environment = dict(env)


ORIGINAL_ENV = 'CLAUDEC_TAKEOVER_ORIGINAL_ENV'


def prepare_launch(target, inherited=None):
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
    backend = _PreflightBackend(checked_target(target))
    result = LauncherBridge(backend, [get_app('grok-bot')], base_env=base).launch_app('grok-bot')
    if backend.environment is not None:
        original = {key: base.get(key) for key, value in backend.environment.items()
                    if value != base.get(key) and key != ORIGINAL_ENV}
        # Only prior values of overwritten variables travel with the process.
        # They are never written to diagnostics or the registration manifest.
        backend.environment[ORIGINAL_ENV] = json.dumps(original, ensure_ascii=True)
    return result, backend.environment


def validate_manifest(manifest, argv):
    if (manifest.get('schema') != 1 or manifest.get('app_id') != 'grok-bot'
            or not re.fullmatch(r'[a-f0-9]{32}', manifest.get('owner', ''))):
        raise ValueError('无效的 Grok Bot 接管配置。')
    target = checked_target(manifest['target'])
    if not argv or Path(argv[0]).resolve() != target:
        raise ValueError('接管入口与注册路径不一致，已取消启动。')
    return target


def run_broker(manifest_path, argv):
    from .takeover_native import launch_with_hook
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
        result, env = prepare_launch(target)
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
        ctypes.windll.user32.MessageBoxW(None, record['error'], 'Claude China · 启动已取消', 0x10)
        return 1
    try:
        code = psutil.Process(record['target_pid']).wait()
    except psutil.NoSuchProcess:
        code = 1
    record.update(exit_code=code, exited_at=time.time())
    path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    return code
