import sys
import types
from unittest.mock import Mock

import pytest

from src.claude_china.desktop import menu as menu_mod


@pytest.fixture
def menu_types(monkeypatch):
    class Menu:
        def __init__(self, title, items):
            self.title, self.items = title, items

    class MenuAction:
        def __init__(self, title, function):
            self.title, self.function = title, function

    monkeypatch.setitem(sys.modules, "webview.menu", types.SimpleNamespace(
        Menu=Menu, MenuAction=MenuAction, MenuSeparator=type("MenuSeparator", (), {}),
    ))


@pytest.fixture
def commands():
    return menu_mod.DesktopMenu(Mock(), Mock(), Mock())


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_windows_and_linux_do_not_add_a_native_window_menu(
    commands, menu_types, monkeypatch, platform,
):
    monkeypatch.setattr(menu_mod, "sys", types.SimpleNamespace(platform=platform))
    assert commands.native_menu() == []


def test_macos_places_settings_and_updates_in_the_application_menu(
    commands, menu_types, monkeypatch,
):
    monkeypatch.setattr(menu_mod, "sys", types.SimpleNamespace(platform="darwin"))
    menus = commands.native_menu()
    assert menus[0].title == "__app__"
    assert [item.title for item in menus[0].items] == ["设置…", "检查更新…"]
    # Cocoa supplies About and Quit with the standard application shortcuts.
    assert all(item.title != "退出" for menu in menus for item in menu.items
               if hasattr(item, "title"))


def test_menu_restores_hidden_window_before_dispatching_to_page(commands):
    commands._tray._quitting.is_set.return_value = False
    calls = []
    commands._tray._show_window.side_effect = lambda *args: calls.append("show")
    commands._window.evaluate_js.side_effect = lambda script: calls.append(script)
    commands._dispatch("updates")
    assert calls == ["show", 'window.openLauncherPanel("updates")']
    commands._updater.check.assert_not_called()
    commands._updater.install.assert_not_called()


def test_menu_does_not_reopen_window_during_shutdown(commands):
    commands._tray._quitting.is_set.return_value = True
    commands._dispatch("updates")
    commands._window.evaluate_js.assert_not_called()
    commands._tray._show_window.assert_not_called()


def test_menu_callback_does_not_block_native_event_loop(commands, monkeypatch):
    pending = []
    monkeypatch.setattr(menu_mod.threading, "Thread",
                        lambda target, args, **kwargs:
                        Mock(start=lambda: pending.append((target, args))))
    commands.updates()
    assert pending == [(commands._dispatch, ("updates",))]
    commands._window.evaluate_js.assert_not_called()


@pytest.mark.parametrize("selector", ["terminate:", b"terminate:"])
def test_macos_quit_keeps_cmd_q_but_bypasses_close_to_tray(commands, monkeypatch, selector):
    quit_item = Mock()
    quit_item.action.return_value = selector
    about_item = Mock()
    about_item.action.return_value = "orderFrontStandardAboutPanel:"
    app = Mock()
    app.mainMenu.return_value.itemAtIndex_.return_value.submenu.return_value.itemArray.return_value = [
        about_item, quit_item,
    ]
    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(
        NSApplication=types.SimpleNamespace(sharedApplication=lambda: app),
    ))
    commands._bind_macos_quit()
    quit_item.setTarget_.assert_called_once_with(commands)
    quit_item.setAction_.assert_called_once_with("quitFromMenu:")
    quit_item.setKeyEquivalent_.assert_not_called()
    about_item.setTarget_.assert_not_called()
    assert commands._macos_quit_bound

