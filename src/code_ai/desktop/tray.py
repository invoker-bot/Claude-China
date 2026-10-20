"""Keep the desktop launcher available from the system tray."""

import logging
import sys
import threading


class LauncherTray:
    def __init__(self, window, icon_path):
        self._window = window
        self._icon_path = icon_path
        self._icon = None
        self._image = None
        self._ready = False
        self._stopped = False
        self._state_lock = threading.Lock()
        self._quitting = threading.Event()
        window.events.closing += self._on_closing

    def start(self) -> None:
        # Optional desktop dependencies must not be imported by CLI-only users.
        import pystray
        from PIL import Image

        with Image.open(self._icon_path) as source:
            self._image = source.copy()
        options = {}
        if sys.platform == "darwin":
            from AppKit import NSApplication

            options["darwin_nsapplication"] = NSApplication.sharedApplication()
        self._icon = pystray.Icon(
            "code-ai-launcher", self._image, "AI Launcher",
            menu=pystray.Menu(
                pystray.MenuItem("打开 AI Launcher", self._show_window, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            ),
            **options,
        )
        # pywebview owns the native main loop, including Cocoa's main thread.
        self._icon.run_detached(setup=self._setup)

    def _setup(self, icon) -> None:
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._on_ready, icon)
        else:
            self._on_ready(icon)

    def _on_ready(self, icon) -> None:
        try:
            with self._state_lock:
                if not self._stopped:
                    icon.visible = True
                    self._ready = True
                    return
        except Exception:
            logging.getLogger(__name__).exception(
                "System tray unavailable; closing the window will exit the launcher."
            )
            return
        # Also handles shutdown racing with the asynchronous tray setup.
        icon.stop()

    def _on_closing(self):
        if self._quitting.is_set():
            return True
        with self._state_lock:
            can_hide = self._ready and not self._stopped
        if can_hide:
            self._window.hide()
            return False
        # Never strand the user with a hidden window and no working tray icon.
        return True

    def _show_window(self, icon, item) -> None:
        if not self._quitting.is_set():
            self._window.restore()
            self._window.show()

    def _quit(self, icon, item) -> None:
        if self._quitting.is_set():
            return
        self._quitting.set()
        try:
            self._window.destroy()
        except Exception:
            self._quitting.clear()
            raise
        # run_gui's finally block removes the icon after the GUI loop exits.

    def stop(self) -> None:
        with self._state_lock:
            if self._stopped:
                return
            self._stopped = True
            self._ready = False
        try:
            if self._icon is not None:
                try:
                    self._icon.visible = False
                finally:
                    # stop may join the setup thread; do not hold its state lock.
                    self._icon.stop()
        finally:
            self._window.events.closing -= self._on_closing
            if self._image is not None:
                self._image.close()
