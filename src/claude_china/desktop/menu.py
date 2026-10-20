"""Shared native menu and tray commands. Desktop dependencies stay lazy."""

import json
import logging
import sys
import threading


class DesktopMenu:
    def __init__(self, window, tray, updater):
        self._window = window
        self._tray = tray
        self._updater = updater
        self._macos_quit_bound = False

    def show(self):
        self._tray._show_window(None, None)

    def quit(self):
        self._tray._quit(None, None)

    def settings(self):
        self._open("settings")

    def updates(self):
        self._open("updates")

    def about(self):
        self._open("about")

    def release_page(self):
        self._updater.open_release()

    def _open(self, panel):
        # Tray callbacks can run on Cocoa's main thread. evaluate_js waits for
        # that thread, so dispatch on a worker instead of blocking the GUI.
        threading.Thread(target=self._dispatch, args=(panel,), daemon=True).start()

    def _dispatch(self, panel):
        try:
            if self._tray._quitting.is_set():
                return
            self.show()
            if not self._window.events.loaded.wait(30) or self._tray._quitting.is_set():
                return
            self._window.evaluate_js("window.openLauncherPanel(%s)" % json.dumps(panel))
        except Exception:
            logging.getLogger(__name__).exception("Could not open desktop menu panel")

    def native_menu(self):
        from webview.menu import Menu, MenuAction, MenuSeparator

        if sys.platform == "darwin":
            return [
                Menu("__app__", [MenuAction("设置…", self.settings),
                                 MenuAction("检查更新…", self.updates)]),
                Menu("窗口", [MenuAction("打开 Claude China", self.show)]),
                Menu("帮助", [MenuAction("发布页面", self.release_page)]),
            ]
        return [
            Menu("应用", [MenuAction("打开 Claude China", self.show),
                          MenuAction("设置…", self.settings), MenuSeparator(),
                          MenuAction("退出", self.quit)]),
            Menu("帮助", [MenuAction("检查更新…", self.updates),
                          MenuAction("发布页面", self.release_page), MenuSeparator(),
                          MenuAction("关于 Claude China", self.about)]),
        ]

    def bind_platform_menu(self):
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._bind_macos_quit)

    def _bind_macos_quit(self):
        from AppKit import NSApplication

        app_menu = NSApplication.sharedApplication().mainMenu().itemAtIndex_(0).submenu()
        for item in app_menu.itemArray():
            if item.action() in ("terminate:", b"terminate:"):
                # pywebview's default Quit calls the window closing handler,
                # which otherwise hides to tray and vetoes Cmd+Q.
                item.setTarget_(self)
                item.setAction_("quitFromMenu:")
                self._macos_quit_bound = True
                break

    def quitFromMenu_(self, sender):
        threading.Thread(target=self.quit, daemon=True).start()
