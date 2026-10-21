"""Keep the desktop launcher available from the system tray."""

import logging
import sys
import threading

from .animation import IconAnimation


class LauncherTray:
    def __init__(self, window, icon_path):
        self._window = window
        self._icon_path = icon_path
        self._icon = None
        self._image = None
        self._animation = None
        self._commands = None
        self._translate = lambda source: source
        self._ready = False
        self._stopped = False
        self._state_lock = threading.Lock()
        self._quitting = threading.Event()
        window.events.closing += self._on_closing

    def start(self) -> None:
        try:
            self._start()
        except Exception:
            logging.getLogger(__name__).exception(
                "System tray unavailable; closing the window will exit the launcher."
            )
            self._ready = False
            if self._icon is not None:
                try:
                    self._icon.stop()
                except Exception:
                    pass
                self._icon = None
            if self._animation is not None:
                self._animation.close()
                self._animation = None
            if self._image is not None:
                self._image.close()
                self._image = None

    def _start(self) -> None:
        # Optional desktop dependencies must not be imported by CLI-only users.
        import pystray
        from PIL import Image

        with Image.open(self._icon_path) as source:
            self._image = source.copy()
        self._image.thumbnail((64, 64))
        try:
            self._animation = IconAnimation(self._image, self._update_frame)
        except Exception:
            logging.getLogger(__name__).debug(
                "Icon animation unavailable; using the static icon", exc_info=True,
            )
        options = {}
        if sys.platform == "darwin":
            from AppKit import NSApplication

            options["darwin_nsapplication"] = NSApplication.sharedApplication()
        self._icon = pystray.Icon(
            "claudec-launcher", self._image, "Claude China",
            menu=self._menu(), **options,
        )
        # pywebview owns the native main loop, including Cocoa's main thread.
        self._icon.run_detached(setup=self._setup)

    def _menu(self):
        import pystray

        tr = self._translate
        items = [pystray.MenuItem(tr("打开 Claude China"), self._show_window, default=True)]
        if self._commands is not None:
            items.extend([
                pystray.MenuItem(tr("设置…"), self._settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(tr("检查更新…"), self._updates),
                pystray.MenuItem(tr("发布页面"), self._release_page),
            ])
        items.extend([pystray.Menu.SEPARATOR, pystray.MenuItem(tr("退出"), self._quit)])
        return pystray.Menu(*items)

    def refresh_language(self):
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._refresh_language)
        else:
            self._refresh_language()

    def _refresh_language(self):
        with self._state_lock:
            if self._icon is not None and not self._stopped:
                self._icon.menu = self._menu()
                self._icon.update_menu()

    def _setup(self, icon) -> None:
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._on_ready, icon)
        else:
            self._on_ready(icon)

    def _on_ready(self, icon) -> None:
        ready = False
        try:
            with self._state_lock:
                if not self._stopped:
                    icon.visible = True
                    self._ready = True
                    ready = True
        except Exception:
            logging.getLogger(__name__).exception(
                "System tray unavailable; closing the window will exit the launcher."
            )
            return
        if ready:
            self.play_activity()
            return
        # Also handles shutdown racing with the asynchronous tray setup.
        icon.stop()

    def play_activity(self) -> None:
        with self._state_lock:
            enabled = self._ready and not self._stopped and not self._quitting.is_set()
        if enabled and self._animation is not None:
            try:
                self._animation.play()
            except Exception:
                logging.getLogger(__name__).debug(
                    "Could not start icon animation", exc_info=True,
                )

    def _update_frame(self, frame) -> None:
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._apply_frame, frame)
        else:
            self._apply_frame(frame)

    def _apply_frame(self, frame) -> None:
        with self._state_lock:
            # Cocoa may still have queued frames when the window quits.
            if self._ready and not self._stopped and not self._quitting.is_set():
                try:
                    self._icon.icon = frame
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Could not update tray animation frame", exc_info=True,
                    )

    def _on_closing(self):
        # A Linux notification host can be absent even when the tray library
        # reports success (e.g. GNOME without AppIndicator support).
        if self._quitting.is_set() or sys.platform == "linux":
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
            self.play_activity()

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

    def _settings(self, icon, item) -> None:
        self._commands.settings()

    def _updates(self, icon, item) -> None:
        self._commands.updates()

    def _release_page(self, icon, item) -> None:
        self._commands.release_page()

    def stop(self) -> None:
        with self._state_lock:
            if self._stopped:
                return
            self._stopped = True
            self._ready = False
        try:
            if self._animation is not None:
                self._animation.close()
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
