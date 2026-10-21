"""Shared native menu and tray commands. Desktop dependencies stay lazy."""

import json
import logging
import sys
import threading


class DesktopMenu:
    def __init__(self, window, tray, updater, translator=None):
        self._window = window
        self._tray = tray
        self._updater = updater
        self._macos_quit_bound = False
        self._translate = translator or (lambda source: source)
        self._menu_labels = []

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
        # Windows/Linux use the page navigation and tray. A native menu adds
        # a second toolbar that does not follow the launcher's dark theme.
        if sys.platform != "darwin":
            return []

        from webview.menu import Menu, MenuAction

        def label(item, source):
            self._menu_labels.append((item, source))
            item.title = self._translate(source)
            return item

        self._menu_labels = []
        return [Menu("__app__", [label(MenuAction("", self.settings), "设置…"),
                                 label(MenuAction("", self.updates), "检查更新…")]),
                label(Menu("", [label(MenuAction("", self.show), "打开 Claude China")]), "窗口"),
                label(Menu("", [label(MenuAction("", self.release_page), "发布页面")]), "帮助")]

    def refresh_language(self):
        for item, source in self._menu_labels:
            item.title = self._translate(source)
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._translate_macos_menu)

    def _translate_macos_menu(self):
        # Relabel in place: retain Cocoa actions, targets and keyboard shortcuts.
        from AppKit import NSApplication
        from .localization import NATIVE_MESSAGES, catalogs

        sources = set(NATIVE_MESSAGES.values()) | {source for _, source in self._menu_labels}
        aliases = {source: source for source in sources}
        for catalog in catalogs().values():
            aliases.update({catalog[source]: source for source in sources if source in catalog})

        def relabel(menu):
            for item in menu.itemArray():
                title = item.title()
                action = item.action()
                if isinstance(action, bytes):
                    action = action.decode('ascii')
                if title in aliases:
                    item.setTitle_(self._translate(aliases[title]))
                elif action in ('orderFrontStandardAboutPanel:', 'hide:', 'quitFromMenu:'):
                    for alias, source in aliases.items():
                        if source in ('关于', '隐藏', '退出') and title.startswith(alias + ' '):
                            item.setTitle_(self._translate(source) + title[len(alias):])
                            break
                if item.hasSubmenu():
                    submenu = item.submenu()
                    if submenu.title() in aliases:
                        submenu.setTitle_(self._translate(aliases[submenu.title()]))
                    # System-provided Services are owned by macOS, not our catalog.
                    if aliases.get(title) != '服务':
                        relabel(submenu)

        relabel(NSApplication.sharedApplication().mainMenu())

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
