"""Privileged Windows router watchdog; healthy permits are session-scoped."""

import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

from ..config_paths import config_dir
from . import router_runtime

TARGETS = ('claude', 'playwright')
REQUEST_NAME = re.compile(r'claudec-router-watch-[a-z0-9_]{8,64}')


class GuardError(ValueError):
    """A user-facing diagnostic without raw OS errors or profile credentials."""


def scope(target):
    if target not in TARGETS:
        raise ValueError('不支持此路由器防护对象。')
    return 'router:' + target


def status(target):
    """Read the persistent deny and temporary permits without elevation."""
    if target not in TARGETS or sys.platform != 'win32':
        return {'enabled': False, 'state': 'unavailable'}
    from .platforms.windows_wfp import Engine
    try:
        with Engine(scope=scope(target)) as engine:
            policies = engine.read()
            if not policies:
                return {'enabled': False, 'state': 'none'}
            policy = policies.get(target)
            if not policy or policy.get('mode') != 'router':
                return {'enabled': True, 'state': 'unknown'}
            active = engine.router_permits_present(policies)
            result = {'enabled': True, 'state': 'unknown', 'active': active, 'policy': policy}
            try:
                if engine.verify(policies):
                    if not active:
                        result['state'] = 'blocked'
                    elif engine.verify_router_permits(policies):
                        result['state'] = 'healthy'
            except Exception:
                pass
            return result
    except Exception:
        return {'enabled': True, 'state': 'unknown'}


def _control_file(target):
    scope(target)
    return config_dir() / 'router-watch' / (target + '.json')


def _request_directory(path):
    request = Path(path)
    if not request.is_absolute() or request.name != 'request.json':
        raise GuardError('无效的路由器防护请求。')
    directory = request.parent
    temp_root = Path(tempfile.gettempdir()).resolve()
    if (directory.is_symlink() or getattr(os.path, 'isjunction', lambda _: False)(str(directory))
            or directory.resolve().parent != temp_root or not REQUEST_NAME.fullmatch(directory.name)
            or request.is_symlink()):
        raise GuardError('无效的路由器防护请求。')
    return directory


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.router-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _signal(directory, name, payload):
    # Publish atomically without following or overwriting a user-created file.
    path = directory / name
    descriptor, temporary = tempfile.mkstemp(prefix='.signal-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=True)
        os.rename(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _kernel():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    return kernel


def cli_targets(argv, env, data):
    """Use a private Node wrapper and discover local Playwright executables."""
    from . import cli_guard, playwright_guard
    if not argv:
        raise GuardError('无法确认 Claude CLI 程序路径。')
    try:
        command = list(argv)
        path = Path(command[0]).resolve(strict=True)
        if path.name.lower() == 'node.exe':
            path = cli_guard.guarded_node(path, create=True)
        command[0] = str(path)
        browsers = playwright_guard.discover(env, extra=data.get('network_guard_browser_paths') or [])
        paths = sorted({str(path), *browsers}, key=str.casefold)
        return command, paths
    except Exception:
        raise GuardError('无法确认 Claude 或 Playwright 的程序路径。') from None


def start(target, executables, baseline, settings):
    """Authorize and verify a guardian before launching the protected target."""
    if sys.platform != 'win32':
        raise GuardError('路由器运行防护目前仅支持 Windows。')
    from .platforms import windows_wfp
    import psutil
    scope(target)
    paths = sorted(set(str(Path(value).resolve(strict=True)) for value in executables), key=str.casefold)
    policies = {target: {'mode': 'router', 'executables': paths}}
    windows_wfp.validate(policies)
    if any(not Path(value).is_file() for value in paths):
        raise GuardError('无法确认受保护程序，请重新启动。')
    if status(target)['enabled']:
        raise GuardError('该对象已有路由器防护，请结束已有会话或先还原。')
    directory = Path(tempfile.mkdtemp(prefix='claudec-router-watch-'))
    request = directory / 'request.json'
    data = {'schema': 1, 'owner': windows_wfp.current_sid(), 'target': target,
            'paths': paths, 'baseline': baseline, 'block_unknown': settings.get('block_unknown') is not False,
            'parent_pid': os.getpid(), 'parent_created': psutil.Process().create_time()}
    raw = json.dumps(data, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    request.write_bytes(raw)
    handle = None
    try:
        handle = windows_wfp._open_elevated(['--router-guardian-request', str(request),
                                              '--router-guardian-digest', hashlib.sha256(raw).hexdigest()])
        kernel = _kernel()
        deadline = time.monotonic() + 90
        ready = directory / 'ready.json'
        while time.monotonic() < deadline:
            if ready.exists():
                payload = json.loads(ready.read_text(encoding='utf-8'))
                if not payload.get('ok'):
                    raise GuardError('无法启动路由器运行防护，请检查管理员授权。')
                if status(target)['state'] != 'healthy':
                    raise GuardError('无法验证路由器运行防护，请重试或还原。')
                _atomic_json(_control_file(target), {'directory': str(directory), 'target': target})
                return {'target': target, 'directory': str(directory)}
            if kernel.WaitForSingleObject(handle, 0) == 0:
                raise GuardError('路由器运行防护未能启动，请检查管理员授权。')
            time.sleep(.1)
        raise GuardError('路由器运行防护授权超时，已取消启动。')
    except Exception as exc:
        try:
            (directory / 'stop').touch(exist_ok=True)
        except OSError:
            pass
        if isinstance(exc, GuardError):
            raise
        raise GuardError('无法启动路由器运行防护，请检查管理员授权。') from None
    finally:
        if handle:
            _kernel().CloseHandle(handle)


def _read_control(target):
    try:
        value = json.loads(_control_file(target).read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('target') != target:
            raise ValueError()
        directory = _request_directory(Path(value['directory']) / 'request.json')
        return directory
    except (OSError, ValueError, KeyError, TypeError):
        raise GuardError('无法找到运行防护控制信息，请检查网络防护。') from None


def stop_session(session):
    directory = _request_directory(Path(session['directory']) / 'request.json')
    (directory / 'stop').touch(exist_ok=True)


def restore_elevated(target, owner, parent_pid, parent_created):
    """Remove this user's stopped router guard; never touch other providers."""
    if sys.platform != 'win32' or not ctypes.windll.shell32.IsUserAnAdmin():
        return 1
    try:
        from .platforms.windows_wfp import Engine, process_sid
        import psutil
        if (not re.fullmatch(r'S-1-(?:\d+-)+\d+', owner or '')
                or type(parent_pid) is not int or parent_pid <= 0
                or type(parent_created) not in (int, float) or not math.isfinite(parent_created)):
            return 1
        parent = psutil.Process(parent_pid)
        if abs(parent.create_time() - parent_created) >= .01 or process_sid(parent_pid) != owner:
            return 1
        with Engine(owner, scope=scope(target)) as engine:
            policies = engine.read()
            if not policies:
                return 0
            if engine.router_permits_present(policies):
                return 1  # Ask the live guardian to stop first.
            engine.replace({}, expected=policies)
            return 0 if not engine.read() else 1
    except Exception:
        return 1


def restore(target):
    """Restore only this target, signalling a live guardian before elevation."""
    state = status(target)
    if not state['enabled']:
        return
    if state['state'] == 'unknown' and 'active' not in state:
        raise GuardError('无法确认路由器网络防护状态，未执行还原。')
    if state['state'] == 'healthy' or state.get('active') is True:
        directory = _read_control(target)
        (directory / 'stop').touch(exist_ok=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = status(target)
            if not state['enabled']:
                _control_file(target).unlink(missing_ok=True)
                return
            if state['state'] == 'unknown' and 'active' not in state:
                raise GuardError('无法确认路由器网络防护状态，未执行还原。')
            if state['state'] == 'blocked' or state.get('active') is False:
                break
            time.sleep(.2)
        else:
            raise GuardError('运行防护尚未停止，请重试还原。')
    from .platforms import windows_wfp
    import psutil
    try:
        windows_wfp._elevate(['--router-guardian-restore', target,
                              '--router-guardian-owner', windows_wfp.current_sid(),
                              '--router-guardian-parent', str(os.getpid()),
                              '--router-guardian-parent-created', repr(psutil.Process().create_time())])
        if status(target)['enabled']:
            raise GuardError('无法确认路由器网络防护已还原。')
        _control_file(target).unlink(missing_ok=True)
    except GuardError:
        raise
    except Exception:
        raise GuardError('无法还原路由器网络防护，请检查管理员授权。') from None


def _live_paths(paths):
    import psutil
    expected = {os.path.normcase(str(Path(path))) for path in paths}
    for item in psutil.process_iter(['exe']):
        try:
            exe = item.info.get('exe') or ''
            if Path(exe).name.lower() == 'cowork-svc.exe':
                continue
            if exe and os.path.normcase(str(Path(exe))) in expected:
                return True
        except (psutil.Error, OSError):
            continue
    return False


def _lifecycle(stop, lost, directory, paths, parent_pid, parent_created):
    import psutil
    started = time.monotonic()
    seen = False
    absent_since = None
    while not stop.wait(.5):
        if (directory / 'stop').exists():
            stop.set()
            return
        try:
            parent = psutil.Process(parent_pid)
            parent_alive = parent.is_running() and abs(parent.create_time() - parent_created) < .01
        except psutil.Error:
            parent_alive = False
        try:
            live = _live_paths(paths)
        except Exception:
            lost.set()
            stop.set()
            return
        seen = seen or live
        now = time.monotonic()
        if live:
            absent_since = None
        elif seen:
            if absent_since is None:
                absent_since = now
            elif now - absent_since >= 5:
                stop.set()
                return
        if not seen and not parent_alive:
            # The guardian keeps persistent denies if its launcher disappears
            # before a target can be identified.
            lost.set()
            stop.set()
            return
        if not seen and now - started > 45:
            lost.set()
            stop.set()
            return


def _alert(reason):
    try:
        outcome = ('无法验证网络阻断状态，请立即检查网络防护。' if reason.startswith('网络异常，无法验证')
                   else 'Claude 的网络已阻断，窗口和会话保留。请在安全检查中还原网络防护。')
        ctypes.windll.user32.MessageBoxW(None,
            reason + '\n' + outcome,
            'Claude China · 网络防护', 0x1010)
    except Exception:
        pass


def run_request(path, digest):
    """Elevated helper for one bounded, digest-pinned router watchdog request."""
    if sys.platform != 'win32' or not ctypes.windll.shell32.IsUserAnAdmin():
        return 1
    directory = None
    signalled = False
    try:
        directory = _request_directory(path)
        with open(path, 'rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or not re.fullmatch(r'[a-f0-9]{64}', digest or '') or hashlib.sha256(raw).hexdigest() != digest:
            raise GuardError('无效的路由器防护请求。')
        data = json.loads(raw)
        Path(path).unlink(missing_ok=True)
        target = data['target']
        scope(target)
        owner = data['owner']
        if data.get('schema') != 1 or not re.fullmatch(r'S-1-(?:\d+-)+\d+', owner):
            raise GuardError('无效的路由器防护请求。')
        if (type(data.get('parent_pid')) is not int or data['parent_pid'] <= 0
                or type(data.get('parent_created')) not in (int, float)
                or not math.isfinite(data['parent_created'])):
            raise GuardError('无效的路由器防护请求。')
        from .platforms.windows_wfp import Engine, current_sid, process_sid, validate
        import psutil
        parent = psutil.Process(data['parent_pid'])
        if (abs(parent.create_time() - data['parent_created']) >= .01
                or process_sid(data['parent_pid']) != owner or current_sid() != owner):
            raise GuardError('无法确认防护请求所属用户。')
        policies = {target: {'mode': 'router', 'executables': data['paths']}}
        validate(policies)
        if any(not Path(value).is_file() for value in data['paths']):
            raise GuardError('无法确认受保护程序。')
        settings = {'block_unknown': data.get('block_unknown') is not False}
        initial = data.get('baseline')
        current = router_runtime.sample('claude', target)
        if router_runtime.failure(initial, current, settings):
            raise GuardError('启动期间 Claude 网络发生变化。')
        stop, lost = threading.Event(), threading.Event()
        def ready():
            nonlocal signalled
            _signal(directory, 'ready.json', {'ok': True})
            signalled = True
            threading.Thread(target=_lifecycle, args=(stop, lost, directory, data['paths'], data['parent_pid'],
                                                     data['parent_created']), daemon=True).start()
        def watch(persistent, dynamic):
            def probe():
                if not persistent.verify(policies) or not dynamic.verify_router_permits(policies):
                    return {'status': 'unsupported'}
                return router_runtime.sample('claude', target)
            reason = router_runtime.watch(initial, settings, probe, lambda reason: None, stop)
            return reason or (router_runtime.NETWORK_FAILED if lost.is_set() else None)
        guard_session(policies, lambda dynamic=False: Engine(owner, scope=scope(target), dynamic=dynamic),
                      watch, ready, _alert)
        return 0
    except Exception:
        if directory is not None and not signalled:
            try:
                _signal(directory, 'ready.json', {'ok': False})
            except OSError:
                pass
        return 1


def guard_session(policies, engine_factory, watch, ready, alert):
    """Install persistent denies and remove temporary permits on bad health.

    A clean exit restores the persistent policy. A failed check, watcher error,
    or process crash keeps the deny filters, without terminating the target.
    """
    started = False
    reason = None
    with engine_factory(False) as persistent:
        if persistent.read():
            raise ValueError('现有路由器网络防护需要先还原。')
        persistent.replace(policies, expected={})
        try:
            if not persistent.verify(policies):
                raise ValueError('无法验证路由器网络防护。')
            with engine_factory(True) as dynamic:
                dynamic.add_router_permits(policies)
                if not dynamic.verify_router_permits(policies):
                    raise ValueError('无法验证路由器网络放行规则。')
                ready()
                started = True
                try:
                    reason = watch(persistent, dynamic)
                except Exception:
                    reason = '运行期间无法确认 Claude 网络安全。'
            if reason:
                try:
                    verified = persistent.verify(policies)
                except Exception:
                    verified = False
                if verified:
                    alert(reason)
                    return 'blocked'
                alert('网络异常，无法验证阻断规则；请立即检查网络防护。')
                return 'unverified'
            persistent.replace({}, expected=policies)
            return 'restored'
        except Exception:
            if not started:
                persistent.replace({}, expected=policies)
            raise
