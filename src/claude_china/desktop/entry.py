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
    args = parser.parse_args(argv)
    from .app import run_gui

    if args.smoke_test:
        from . import config
        report = args.smoke_test.resolve()
        previous = config.DESKTOP_CONFIG_FILE
        # Exercise the packaged GUI without reading or changing real profiles.
        with tempfile.TemporaryDirectory(prefix="claude-china-smoke-") as directory:
            try:
                config.DESKTOP_CONFIG_FILE = Path(directory) / "desktop.yaml"
                run_gui(smoke_report=report)
            finally:
                config.DESKTOP_CONFIG_FILE = previous
        return 0 if report.is_file() and json.loads(report.read_text())["ok"] else 1
    with _installer_mutex():
        run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
