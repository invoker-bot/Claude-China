"""Entry point for the standalone desktop application."""

import argparse
from contextlib import contextmanager
import ctypes
import json
from pathlib import Path
import sys
import tempfile

from .. import __version__


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
    parser.add_argument("target_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
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
        from . import config, terminal_history
        from .. import config as cli_config
        report = args.smoke_test.resolve()
        previous = config.DESKTOP_CONFIG_FILE
        previous_cli = cli_config.CONFIG_FILE
        previous_history_home = terminal_history.profile_home
        # Exercise the packaged GUI without reading or changing real profiles.
        with tempfile.TemporaryDirectory(prefix="claude-china-smoke-") as directory:
            try:
                config.DESKTOP_CONFIG_FILE = Path(directory) / "desktop.yaml"
                cli_config.CONFIG_FILE = Path(directory) / "config.yaml"
                terminal_history.profile_home = lambda record: Path(directory) / ('history-' + record['type'])
                run_gui(smoke_report=report)
            finally:
                config.DESKTOP_CONFIG_FILE = previous
                cli_config.CONFIG_FILE = previous_cli
                terminal_history.profile_home = previous_history_home
        return 0 if report.is_file() and json.loads(report.read_text())["ok"] else 1
    with _installer_mutex():
        run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
