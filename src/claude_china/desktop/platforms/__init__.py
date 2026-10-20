"""Platform backends for the desktop launcher."""
import sys


def get_backend():
    """Return the PlatformBackend for the current OS, or None if unsupported.

    Backends are imported lazily so OS-only imports (e.g. winreg) never load on
    the wrong platform.
    """
    if sys.platform == "win32":
        from .windows import WindowsBackend
        return WindowsBackend()
    if sys.platform == "darwin":
        from .macos import MacBackend
        return MacBackend()
    if sys.platform == "linux":
        from .linux import LinuxBackend
        return LinuxBackend()
    return None
