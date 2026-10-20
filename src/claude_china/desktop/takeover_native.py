"""Windows x64 launch with an in-memory child-process compatibility hook."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys

from .process import external_environment, _system_libraries


def hook_path():
    if getattr(sys, 'frozen', False):
        return Path(__file__).parent / 'native' / 'claudec-child-hook.dll'
    return Path(__file__).resolve().parents[3] / 'build/desktop/native/claudec-child-hook.dll'


def launch_with_hook(argv, env, cwd, dll=None):
    if sys.platform != 'win32' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise OSError('全局接管需要 Windows x64。')
    import _winapi

    path = Path(dll or hook_path()).resolve(strict=True)
    native = ctypes.WinDLL(str(path), use_last_error=True)
    native.Inject.argtypes = [wintypes.HANDLE, ctypes.c_char_p]
    native.Inject.restype = wintypes.BOOL
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.DebugActiveProcessStop.argtypes = [wintypes.DWORD]
    kernel.DebugActiveProcessStop.restype = wintypes.BOOL
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    environment = external_environment(env)
    environment['CLAUDEC_TAKEOVER_TARGET'] = str(Path(argv[0]).resolve(strict=True))
    # The import table is changed in the new process only. Vendor files and
    # signatures on disk remain untouched. Failed injection never resumes it.
    with _system_libraries():
        process, thread, pid, _ = _winapi.CreateProcess(
            argv[0], subprocess.list2cmdline(argv), None, None, True,
            0x2 | 0x4 | 0x400, environment, cwd, subprocess.STARTUPINFO())
    try:
        if not native.Inject(process, str(path).encode('mbcs')):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.DebugActiveProcessStop(pid):
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel.ResumeThread(thread) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return pid
    except BaseException:
        _winapi.TerminateProcess(process, 1)
        raise
    finally:
        _winapi.CloseHandle(thread)
        _winapi.CloseHandle(process)
