import ctypes
from pathlib import Path
import sys


class _Guid(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_ulong), ("data2", ctypes.c_ushort),
                ("data3", ctypes.c_ushort), ("data4", ctypes.c_ubyte * 8)]


class _NotifyIconData(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("window", ctypes.c_void_p),
                ("id", ctypes.c_uint), ("flags", ctypes.c_uint),
                ("callback_message", ctypes.c_uint), ("icon", ctypes.c_void_p),
                ("tip", ctypes.c_wchar * 128), ("state", ctypes.c_ulong),
                ("state_mask", ctypes.c_ulong), ("info", ctypes.c_wchar * 256),
                ("timeout_or_version", ctypes.c_uint), ("info_title", ctypes.c_wchar * 64),
                ("info_flags", ctypes.c_ulong), ("item_guid", _Guid),
                ("balloon_icon", ctypes.c_void_p)]


class WindowsNotification:
    def __init__(self, title, message):
        self.title = title[:63]
        self.message = message[:255]
        self.window = None
        self.icon = None
        self.owns_icon = False
        self.added = False
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.shell32.Shell_NotifyIconW.argtypes = [ctypes.c_ulong, ctypes.POINTER(_NotifyIconData)]
        self.shell32.Shell_NotifyIconW.restype = ctypes.c_int
        self.user32.CreateWindowExW.restype = ctypes.c_void_p
        self.user32.LoadImageW.restype = ctypes.c_void_p
        self.user32.LoadIconW.restype = ctypes.c_void_p
        self.user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        self.user32.DestroyIcon.argtypes = [ctypes.c_void_p]

    def _change(self, action, data):
        data.size = ctypes.sizeof(_NotifyIconData)
        if not self.shell32.Shell_NotifyIconW(action, ctypes.byref(data)):
            raise ctypes.WinError(ctypes.get_last_error())

    def show(self):
        self.window = self.user32.CreateWindowExW(0, "Static", "Claude China notification",
                                                  0, 0, 0, 0, 0, ctypes.c_void_p(-3), 0, None, 0)
        if not self.window:
            raise ctypes.WinError(ctypes.get_last_error())
        icon_path = Path(__file__).parent / "ui" / "icon.ico"
        self.icon = self.user32.LoadImageW(None, str(icon_path), 1, 0, 0, 0x10 | 0x40)
        self.owns_icon = bool(self.icon)
        if not self.icon:
            self.icon = self.user32.LoadIconW(None, 32515)
        data = _NotifyIconData(window=self.window, id=1, flags=0x02 | 0x04,
                               icon=self.icon, tip="Claude China")
        self._change(0, data)
        self.added = True
        data = _NotifyIconData(window=self.window, id=1, flags=0x10,
                               info=self.message, info_title=self.title, info_flags=0x02)
        self._change(1, data)

    def close(self):
        if self.added:
            try:
                data = _NotifyIconData(window=self.window, id=1, flags=0x10,
                                       info="", info_title="", info_flags=0)
                self._change(1, data)
            except Exception:
                pass
            try:
                self._change(2, _NotifyIconData(window=self.window, id=1))
            except Exception:
                pass
            self.added = False
        if self.window:
            self.user32.DestroyWindow(self.window)
            self.window = None
        if self.owns_icon:
            self.user32.DestroyIcon(self.icon)
            self.owns_icon = False
        self.icon = None


_active = None


def show_network_warning(reason):
    global _active
    dismiss_network_warning()
    if sys.platform != "win32":
        return
    notification = None
    try:
        outcome = ("无法验证网络阻断状态，请立即检查网络防护。" if reason.startswith("网络异常，无法验证")
                   else "受保护应用的网络已阻断，窗口和会话保留。网络与防护状态恢复后，此提示和本次阻断会自动解除。")
        notification = WindowsNotification("Claude China · 网络防护", reason + "\n" + outcome)
        notification.show()
        _active = notification
    except Exception:
        if notification is not None:
            notification.close()
        _active = None


def dismiss_network_warning():
    global _active
    if _active is not None:
        try:
            _active.close()
        except Exception:
            pass
        _active = None
