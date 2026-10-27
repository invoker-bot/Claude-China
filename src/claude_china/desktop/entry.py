"""Entry point for the standalone desktop application."""

import argparse
from contextlib import contextmanager
import ctypes
import json
from pathlib import Path
import sys
import tempfile

from .. import __version__


def _guard_output(value, stream):
    """The Node preload consumes UTF-8 even when Windows uses a legacy code page."""
    if stream is None:
        return
    binary = getattr(stream, "buffer", None)
    if binary is None:
        print(value, file=stream)
    else:
        binary.write((value + "\n").encode("utf-8"))
        binary.flush()


@contextmanager
def _installer_mutex():
    """Let Inno Setup ask the user to quit before upgrade or uninstall."""
    if sys.platform != "win32":
        yield
        return
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_bool
    handle = kernel.CreateMutexW(None, False, "Local\\ClaudeChina.DesktopLauncher")
    if not handle:
        raise ctypes.WinError()
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Claude China desktop launcher")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--apply-update", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--takeover-launch", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--takeover-register", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--takeover-uninstall", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--terminal-session", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--disable", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--network-guard-request", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--network-guard-digest", help=argparse.SUPPRESS)
    parser.add_argument("--network-guard-check-browser", help=argparse.SUPPRESS)
    parser.add_argument("--router-runtime-probe", help=argparse.SUPPRESS)
    parser.add_argument("--router-runtime-target", help=argparse.SUPPRESS)
    parser.add_argument("--router-guardian-request", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--router-guardian-digest", help=argparse.SUPPRESS)
    parser.add_argument("--router-guardian-restore", help=argparse.SUPPRESS)
    parser.add_argument("--router-guardian-owner", help=argparse.SUPPRESS)
    parser.add_argument("--router-guardian-parent", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--router-guardian-parent-created", type=float, help=argparse.SUPPRESS)
    parser.add_argument("target_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.router_guardian_request:
        from .router_guardian import run_request
        return run_request(args.router_guardian_request, args.router_guardian_digest)
    if args.router_guardian_restore:
        from .router_guardian import restore_elevated
        return restore_elevated(args.router_guardian_restore, args.router_guardian_owner,
                                args.router_guardian_parent, args.router_guardian_parent_created)
    if args.router_runtime_probe:
        from . import config, router
        from .platforms import get_backend
        try:
            backend = get_backend()
            if backend is None or args.router_runtime_probe not in router.HOSTS:
                raise ValueError()
            target = args.router_runtime_target or args.router_runtime_probe
            if target not in (*router.HOSTS, 'playwright'):
                raise ValueError()
            data = config.load_desktop_config()
            router.check_ready(target, data, backend, allow_router_guard=True)
            report = router.inspect(args.router_runtime_probe, backend)
            router.check_ready(target, data, backend, allow_router_guard=True)
        except router.RouterError:
            report = {'status': 'unsupported'}
        except Exception:
            report = {'status': 'unknown'}
        _guard_output(json.dumps(report, ensure_ascii=True), sys.stdout)
        return 0
    if args.network_guard_check_browser:
        from .playwright_guard import check_browser
        from .egress import GuardError
        try:
            policy = check_browser(args.network_guard_check_browser)
            _guard_output(json.dumps({"mode": policy.get("mode", "proxy") if policy else None}), sys.stdout)
            return 0
        except GuardError as exc:
            _guard_output(str(exc), sys.stderr)
            return 1
        except Exception:
            _guard_output("无法验证 Playwright 网络防护，已阻止浏览器启动。", sys.stderr)
            return 1
    if args.network_guard_request:
        from .platforms.windows_wfp import apply_request
        return apply_request(args.network_guard_request, args.network_guard_digest)
    if args.terminal_session:
        from .terminal_host import run_session
        return run_session(args.terminal_session)
    if args.takeover_launch:
        from .takeover import run_broker
        target_args = args.target_args[1:] if args.target_args[:1] == ['--'] else args.target_args
        return run_broker(args.takeover_launch, target_args)
    if args.takeover_register or args.takeover_uninstall:
        from . import takeover_windows
        try:
            if args.takeover_uninstall:
                from . import egress
                egress.uninstall()
                return takeover_windows.uninstall()
            takeover_windows.apply_registration(args.takeover_register, not args.disable)
            return 0
        except Exception:
            return 1
    if args.apply_update:
        from .update_install import apply_update
        return apply_update(args.apply_update)
    from .app import run_gui

    if args.smoke_test:
        from . import config, terminal_history, usage
        from .. import config as cli_config
        report = args.smoke_test.resolve()
        previous = config.DESKTOP_CONFIG_FILE
        previous_cli = cli_config.CONFIG_FILE
        previous_history_home = terminal_history.profile_home
        previous_usage_sources = usage.discover_sources
        # Exercise the packaged GUI without reading or changing real profiles.
        with tempfile.TemporaryDirectory(prefix="claude-china-smoke-") as directory:
            try:
                config.DESKTOP_CONFIG_FILE = Path(directory) / "desktop.yaml"
                config.save_desktop_config({"language": "zh-CN"})
                cli_config.CONFIG_FILE = Path(directory) / "config.yaml"
                terminal_history.profile_home = lambda record: Path(directory) / ('history-' + record['type'])
                usage.discover_sources = lambda: [{'tool': 'claude', 'root': str(Path(directory) / 'usage-fixture')}]
                run_gui(smoke_report=report)
            finally:
                config.DESKTOP_CONFIG_FILE = previous
                cli_config.CONFIG_FILE = previous_cli
                terminal_history.profile_home = previous_history_home
                usage.discover_sources = previous_usage_sources
        return 0 if report.is_file() and json.loads(report.read_text())["ok"] else 1
    with _installer_mutex():
        run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
