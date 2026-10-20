"""Windows launcher identity shared by the process and its shortcuts."""

import ctypes
import hashlib
from pathlib import Path
import tempfile
from uuid import UUID

from .. import config as cfg


APP_USER_MODEL_ID = "ClaudeChina.DesktopLauncher"


def launcher_icon_path(source=None) -> str:
    """Give changed artwork a new Shell cache key, without removing old pins' icons."""
    source = Path(source) if source is not None else (
        Path(__file__).resolve().parents[1] / "ui" / "icon.ico"
    )
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:16]
    directory = cfg.DESKTOP_CONFIG_FILE.parent / "icons"
    icon = directory / f"launcher-{digest}.ico"
    if icon.is_file() and icon.read_bytes() == data:
        return str(icon)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".ico", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(icon)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(icon)


def _dll(name):
    # Importing this module must also work on macOS and without desktop extras.
    return ctypes.WinDLL(name)


def _check_hresult(result):
    if result < 0:
        raise OSError(f"Windows Shell operation failed (HRESULT 0x{result & 0xFFFFFFFF:08X})")


def set_process_app_id() -> None:
    shell = _dll("shell32")
    function = shell.SetCurrentProcessExplicitAppUserModelID
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_int32
    _check_hresult(function(APP_USER_MODEL_ID))


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(UUID(value).bytes_le)


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _StringPropVariant(ctypes.Structure):
    # VT_LPWSTR only. The final pointer reserves the rest of the PROPVARIANT
    # union: the complete structure is 24 bytes on Win64 and 16 on Win32.
    _fields_ = [
        ("vt", ctypes.c_uint16), ("reserved", ctypes.c_uint16 * 3),
        ("value", ctypes.c_wchar_p), ("padding", ctypes.c_void_p),
    ]


def _com_method(store, index, *argtypes, result=ctypes.c_int32):
    table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *argtypes)(table[index])


def set_shortcut_app_id(path) -> None:
    """Persist System.AppUserModel.ID without changing the shortcut's command."""
    ole = _dll("ole32")
    shell = _dll("shell32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_int32
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    # An existing MTA is also usable; it does not belong to us to uninitialize.
    if initialized != -2147417850:  # RPC_E_CHANGED_MODE
        _check_hresult(initialized)
    store = ctypes.c_void_p()
    try:
        get_store = shell.SHGetPropertyStoreFromParsingName
        get_store.argtypes = [
            ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
        ]
        get_store.restype = ctypes.c_int32
        iid = _GUID.parse("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")  # IPropertyStore
        _check_hresult(get_store(str(path), None, 2, ctypes.byref(iid), ctypes.byref(store)))
        key = _PropertyKey(_GUID.parse("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"), 5)
        value = _StringPropVariant(vt=31, value=APP_USER_MODEL_ID)  # VT_LPWSTR
        # SetValue copies our Python-owned string; do not PropVariantClear it.
        set_value = _com_method(
            store, 6, ctypes.POINTER(_PropertyKey), ctypes.POINTER(_StringPropVariant),
        )
        _check_hresult(set_value(store, ctypes.byref(key), ctypes.byref(value)))
        _check_hresult(_com_method(store, 7)(store))  # Commit
    finally:
        if store.value:
            _com_method(store, 2, result=ctypes.c_uint32)(store)  # Release
        if initialized >= 0:
            ole.CoUninitialize()

    # Refresh only this shortcut, not the user's global icon cache or Explorer.
    notify = shell.SHChangeNotify
    notify.argtypes = [ctypes.c_int32, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_void_p]
    notify.restype = None
    notify(0x2000, 0x0005, str(path), None)  # SHCNE_UPDATEITEM, SHCNF_PATHW
