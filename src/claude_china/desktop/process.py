"""Run external apps without inheriting the frozen launcher's private libraries."""

from contextlib import contextmanager
import ctypes
import os
import subprocess as _subprocess
import sys
import threading

DEVNULL = _subprocess.DEVNULL
CREATE_NO_WINDOW = getattr(_subprocess, "CREATE_NO_WINDOW", 0)
SubprocessError = _subprocess.SubprocessError
_dll_lock = threading.RLock()


def external_environment(env=None) -> dict:
    result = dict(os.environ if env is None else env)
    if not getattr(sys, "frozen", False):
        return result
    for key in ("LD_LIBRARY_PATH", "LIBPATH"):
        original = result.pop(key + "_ORIG", None)
        if original is not None:
            result[key] = original
        else:
            result.pop(key, None)
    bundle = os.path.normcase(os.path.abspath(sys._MEIPASS))
    # PyInstaller rewrites this GTK cache into a temporary file outside the
    # bundle, so a bundle-prefix filter alone cannot detect it.
    result.pop("GDK_PIXBUF_MODULE_FILE", None)
    for key in ("PATH", "DYLD_LIBRARY_PATH", "GI_TYPELIB_PATH", "GIO_EXTRA_MODULES",
                "GTK_DATA_PREFIX", "GTK_EXE_PREFIX", "GTK_PATH", "PANGO_LIBDIR",
                "PANGO_SYSCONFDIR", "GSETTINGS_SCHEMA_DIR", "XDG_DATA_DIRS",
                "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        if key not in result:
            continue
        parts = []
        for part in result[key].split(os.pathsep):
            normalized = os.path.normcase(os.path.abspath(part))
            if normalized != bundle and not normalized.startswith(bundle + os.sep):
                parts.append(part)
        if parts:
            result[key] = os.pathsep.join(parts)
        else:
            result.pop(key, None)
    for key in list(result):
        if key.startswith("_PYI_"):
            result.pop(key)
    return result


def _set_dll_directory(path):
    setter = ctypes.windll.kernel32.SetDllDirectoryW
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_int
    if not setter(path):
        raise ctypes.WinError()


@contextmanager
def _system_libraries():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield
        return
    with _dll_lock:
        _set_dll_directory(None)
        try:
            yield
        finally:
            _set_dll_directory(sys._MEIPASS)


def _call(function, *args, **kwargs):
    kwargs["env"] = external_environment(kwargs.get("env"))
    with _system_libraries():
        return function(*args, **kwargs)


def Popen(*args, **kwargs):
    return _call(_subprocess.Popen, *args, **kwargs)


def run(*args, **kwargs):
    return _call(_subprocess.run, *args, **kwargs)


def check_output(*args, **kwargs):
    return _call(_subprocess.check_output, *args, **kwargs)
