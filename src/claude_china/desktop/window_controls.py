"""Window commands for the integrated Windows/Linux header; no eager GUI imports."""

import logging
import math
import sys


class WindowControls:
    _EDGES = ("w", "e", "n", "nw", "ne", "s", "sw", "se")

    def __init__(self, window):
        self._window = window
        self._maximized = False
        self._prepare_maximize = None
        self._read_maximized = None
        self._native_resize = None
        self._drag_origin = None
        self._native_frame_callback = None
        window.events.maximized += self._on_maximized
        window.events.restored += self._on_restored

    def state(self):
        return {"custom_titlebar": bool(self._window.frameless),
                "maximized": self._maximized}

    def _on_maximized(self):
        self._maximized = True

    def _on_restored(self):
        # Restoring a minimized, maximized window can still leave it maximized.
        if self._read_maximized:
            self._read_maximized()
        else:
            self._maximized = False

    def action(self, action):
        try:
            if action == "minimize":
                self._window.minimize()
            elif action == "maximize":
                if self._maximized:
                    self._window.restore()
                    self._maximized = False
                else:
                    if self._prepare_maximize:
                        self._prepare_maximize()
                    self._window.maximize()
                    self._maximized = True
            elif action == "close":
                # destroy() raises the normal closing event: tray policy still
                # decides whether to hide or exit, including unavailable trays.
                self._window.destroy()
            else:
                return {"ok": False}
            return {"ok": True, **self.state()}
        except Exception:
            logging.getLogger(__name__).exception("Window command failed")
            return {"ok": False}

    def resize(self, edge):
        if (not isinstance(edge, str) or edge not in self._EDGES
                or not self._window.frameless or self._maximized or not self._native_resize):
            return {"ok": False}
        self._native_resize(edge)
        return {"ok": True}

    def move(self, dx, dy, start=False):
        if (not self._window.frameless or self._maximized
                or not isinstance(dx, (int, float)) or not isinstance(dy, (int, float))
                or not math.isfinite(dx) or not math.isfinite(dy)):
            return {"ok": False}
        if start:
            self._drag_origin = (self._window.x, self._window.y)
        if self._drag_origin is None:
            return {"ok": False}
        x, y = self._drag_origin
        self._window.move(round(x + dx), round(y + dy))
        return {"ok": True}

    def configure(self):
        """Called after the native window exists, always marshal GUI mutations."""
        if not self._window.frameless:
            return
        # start(func=) can run before pywebview publishes window.native.
        if not self._window.events.loaded.wait(30):
            return
        if sys.platform == "win32":
            self._configure_windows()
        elif sys.platform == "linux":
            self._configure_linux()

    def _configure_windows(self):
        import ctypes
        from System import Action
        from System.Drawing import Rectangle
        from System.Windows.Forms import FormWindowState, Padding, Screen

        native = self._window.native
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ReleaseCapture.argtypes = []
        user32.ReleaseCapture.restype = ctypes.c_bool
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_size_t, ctypes.c_ssize_t]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        # Retain the OS sizing style without its visible non-client border.
        # FormBorderStyle.None alone makes DefWindowProc ignore SC_SIZE.
        comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p,
                                           ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
                                           ctypes.c_size_t, ctypes.c_size_t)
        comctl32.SetWindowSubclass.argtypes = [ctypes.c_void_p, callback_type,
                                              ctypes.c_size_t, ctypes.c_size_t]
        comctl32.SetWindowSubclass.restype = ctypes.c_bool
        comctl32.RemoveWindowSubclass.argtypes = [ctypes.c_void_p, callback_type, ctypes.c_size_t]
        comctl32.RemoveWindowSubclass.restype = ctypes.c_bool
        comctl32.DefSubclassProc.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                            ctypes.c_size_t, ctypes.c_ssize_t]
        comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_uint]
        user32.SetWindowPos.restype = ctypes.c_bool
        class Rect(ctypes.Structure):
            _fields_ = [(name, ctypes.c_long) for name in ("left", "top", "right", "bottom")]

        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(Rect)]
        user32.GetWindowRect.restype = ctypes.c_bool
        user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
        user32.GetDpiForWindow.restype = ctypes.c_uint

        def frame_proc(hwnd, message, wparam, lparam, subclass_id, reference):
            if message == 0x0083:  # WM_NCCALCSIZE: the page occupies the whole window.
                return 0
            if message == 0x0084 and native.WindowState == FormWindowState.Normal:
                # The small native inset catches edge gestures synchronously,
                # before the asynchronous JS bridge can lose a fast mouse drag.
                rect = Rect()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                x, y = ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short(lparam >> 16).value
                grip = max(4, round(4 * user32.GetDpiForWindow(hwnd) / 96))
                horizontal = "w" if x < rect.left + grip else "e" if x >= rect.right - grip else ""
                vertical = "n" if y < rect.top + grip else "s" if y >= rect.bottom - grip else ""
                edge = vertical + horizontal
                if edge in self._EDGES:
                    return 10 + self._EDGES.index(edge)
            if message == 0x0082:  # WM_NCDESTROY: detach before the HWND is released.
                comctl32.RemoveWindowSubclass(hwnd, self._native_frame_callback, subclass_id)
            return comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

        self._native_frame_callback = callback_type(frame_proc)

        def configure_frame():
            hwnd = native.Handle.ToInt64()
            if not comctl32.SetWindowSubclass(hwnd, self._native_frame_callback, 1, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            style = user32.GetWindowLongPtrW(hwnd, -16)
            user32.SetWindowLongPtrW(hwnd, -16, (style | 0x000F0000) & ~0x00C00000)
            native.Padding = Padding(max(4, round(4 * user32.GetDpiForWindow(hwnd) / 96)))
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)

        native.Invoke(Action(configure_frame))

        def prepare():
            def apply():
                screen = Screen.FromControl(native)
                work, bounds = screen.WorkingArea, screen.Bounds
                # Borderless WinForms otherwise covers the Windows taskbar.
                native.MaximizedBounds = Rectangle(work.X - bounds.X, work.Y - bounds.Y,
                                                   work.Width, work.Height)
            native.Invoke(Action(apply))

        def read_maximized():
            def read():
                self._maximized = native.WindowState == FormWindowState.Maximized
            native.Invoke(Action(read))

        def resize(edge):
            def begin():
                user32.ReleaseCapture()
                # Let Windows run its normal modal sizing loop, including DPI,
                # minimum dimensions and pointer capture outside the webview.
                user32.SendMessageW(native.Handle.ToInt64(), 0x0112,
                                    0xF000 | (self._EDGES.index(edge) + 1), 0)
            native.BeginInvoke(Action(begin))

        self._prepare_maximize = prepare
        self._read_maximized = read_maximized
        self._native_resize = resize

    def _configure_linux(self):
        from gi.repository import Gdk, GLib, Gtk

        native = self._window.native
        edges = dict(zip(self._EDGES, (
            Gdk.WindowEdge.WEST, Gdk.WindowEdge.EAST, Gdk.WindowEdge.NORTH,
            Gdk.WindowEdge.NORTH_WEST, Gdk.WindowEdge.NORTH_EAST,
            Gdk.WindowEdge.SOUTH, Gdk.WindowEdge.SOUTH_WEST, Gdk.WindowEdge.SOUTH_EAST,
        )))

        def read_maximized():
            def read():
                self._maximized = native.is_maximized()
                return False
            GLib.idle_add(read)

        def resize(edge):
            def begin():
                pointer = Gdk.Display.get_default().get_default_seat().get_pointer()
                _, x, y = pointer.get_position()
                native.begin_resize_drag(edges[edge], 1, x, y, Gtk.get_current_event_time())
                return False
            GLib.idle_add(begin)

        self._read_maximized = read_maximized
        self._native_resize = resize
