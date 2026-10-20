import sys
import threading
import types
from unittest.mock import Mock

import pytest

from src.claude_china.desktop import tray as tray_mod


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self


class FakeWindow:
    def __init__(self):
        self.events = types.SimpleNamespace(closing=FakeEvent())
        self.hidden = False
        self.destroyed = False
        self.calls = []

    def close(self):
        if any(handler() is False for handler in self.events.closing.handlers):
            return
        self.destroyed = True

    def hide(self):
        self.calls.append("hide")
        self.hidden = True

    def restore(self):
        self.calls.append("restore")

    def show(self):
        self.calls.append("show")
        self.hidden = False

    def destroy(self):
        self.calls.append("destroy")
        self.close()


@pytest.fixture
def tray_environment(monkeypatch):
    class MenuItem:
        def __init__(self, text, action, default=False):
            self.text = text
            self.action = action
            self.default = default

        def __call__(self, icon):
            self.action(icon, self)

    class Menu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class Icon:
        def __init__(self, name, image, title, menu, **kwargs):
            self.name = name
            self.image = image
            self.title = title
            self.menu = menu
            self.options = kwargs
            self.visible = False
            self.stopped = False
            self.setup = None

        def run_detached(self, setup):
            self.setup = setup

        def ready(self):
            self.setup(self)

        def stop(self):
            self.stopped = True

    image = Mock()
    source = Mock()
    source.copy.return_value = image
    source.__enter__ = Mock(return_value=source)
    source.__exit__ = Mock(return_value=False)
    factory = Mock(side_effect=Icon)
    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace(
        Icon=factory, Menu=Menu, MenuItem=MenuItem,
    ))
    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(
        Image=types.SimpleNamespace(open=Mock(return_value=source)),
    ))
    monkeypatch.setattr(tray_mod, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(tray_mod, "IconAnimation", Mock(), raising=False)
    return factory, image


@pytest.fixture
def running_tray(tray_environment):
    window = FakeWindow()
    tray = tray_mod.LauncherTray(window, "icon.png")
    tray.start()
    icon = tray._icon
    icon.ready()
    try:
        yield tray, window, icon
    finally:
        tray.stop()


def test_close_hides_window_but_keeps_launcher_and_tray_alive(running_tray):
    tray, window, icon = running_tray

    window.close()

    assert window.hidden
    assert not window.destroyed
    assert icon.visible
    assert not icon.stopped


def test_linux_close_exits_even_without_a_notification_host(running_tray, monkeypatch):
    tray, window, icon = running_tray
    monkeypatch.setattr(tray_mod, "sys", types.SimpleNamespace(platform="linux"))
    window.close()
    assert window.destroyed
    assert not window.hidden


def test_missing_tray_dependency_keeps_gui_usable(tray_environment, monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", None)
    window = FakeWindow()
    tray = tray_mod.LauncherTray(window, "icon.png")
    tray.start()
    window.close()
    assert window.destroyed
    tray.stop()


def test_default_tray_action_restores_hidden_window(running_tray):
    tray, window, icon = running_tray
    window.close()
    show = next(item for item in icon.menu.items if getattr(item, "default", False))

    show(icon)

    assert icon.title == "Claude China"
    assert show.text == "打开 Claude China"
    assert window.calls == ["hide", "restore", "show"]
    assert not window.hidden
    assert not window.destroyed


def test_tray_animates_on_start_and_open_then_stops_on_shutdown(running_tray):
    tray, window, icon = running_tray
    tray._animation.play.assert_called_once_with()

    tray._show_window(icon, None)
    assert tray._animation.play.call_count == 2
    tray.stop()
    tray.play_activity()
    assert tray._animation.play.call_count == 2
    tray._animation.close.assert_called_once_with()


def test_animation_never_replaces_the_icon_after_quit(running_tray):
    tray, _, icon = running_tray
    frame = object()
    tray._apply_frame(frame)
    assert icon.icon is frame

    tray._quit(icon, None)
    tray._apply_frame(object())
    tray.play_activity()
    assert icon.icon is frame
    tray._animation.play.assert_called_once_with()


def test_macos_frames_are_dispatched_to_main_thread_and_ignored_after_stop(
    running_tray, monkeypatch,
):
    tray, _, icon = running_tray
    monkeypatch.setattr(tray_mod.sys, "platform", "darwin")
    call_after = Mock()
    monkeypatch.setitem(sys.modules, "PyObjCTools", types.SimpleNamespace(
        AppHelper=types.SimpleNamespace(callAfter=call_after),
    ))
    frame = object()
    tray._update_frame(frame)
    call_after.assert_called_once_with(tray._apply_frame, frame)
    assert not hasattr(icon, "icon")

    tray.stop()
    callback, *args = call_after.call_args.args
    callback(*args)
    assert not hasattr(icon, "icon")


def test_hidden_launcher_still_receives_single_instance_activation(running_tray, tmp_path):
    from src.claude_china.desktop.single_instance import DesktopInstance

    tray, window, icon = running_tray
    path = tmp_path / "desktop.lock"
    with DesktopInstance(path) as owner:
        assert owner.acquire_or_activate()
        listener = threading.Thread(target=owner.listen, args=(window,), daemon=True)
        listener.start()
        try:
            window.close()
            assert window.hidden
            with DesktopInstance(path) as duplicate:
                assert not duplicate.acquire_or_activate()
            assert not window.hidden
            assert not window.destroyed
            assert icon.visible
        finally:
            owner.close()
            listener.join(timeout=3)
    assert not listener.is_alive()


def test_exit_menu_allows_real_close_even_when_window_is_hidden(running_tray):
    tray, window, icon = running_tray
    window.close()
    quit_item = next(item for item in icon.menu.items if getattr(item, "text", "") == "退出")

    quit_item(icon)

    assert window.destroyed
    assert window.calls == ["hide", "destroy"]


def test_repeated_exit_and_open_during_exit_do_not_reenter_window(running_tray):
    tray, window, icon = running_tray
    tray._quit(icon, None)
    tray._quit(icon, None)
    tray._show_window(icon, None)

    assert window.calls == ["destroy"]


def test_window_can_close_normally_before_tray_is_available(tray_environment):
    window = FakeWindow()
    tray = tray_mod.LauncherTray(window, "icon.png")
    try:
        tray.start()
        window.close()
        assert window.destroyed
        assert not window.hidden
    finally:
        tray.stop()


def test_shutdown_before_tray_setup_does_not_leave_an_orphan_icon(tray_environment):
    window = FakeWindow()
    tray = tray_mod.LauncherTray(window, "icon.png")
    tray.start()
    icon = tray._icon

    tray.stop()
    icon.ready()
    tray.stop()

    assert not icon.visible
    assert icon.stopped
    assert window.events.closing.handlers == []


def test_stop_removes_icon_releases_image_and_unhooks_close(running_tray, tray_environment):
    tray, window, icon = running_tray
    _, image = tray_environment

    tray.stop()

    assert not icon.visible
    assert icon.stopped
    image.close.assert_called_once_with()
    assert window.events.closing.handlers == []


def test_stop_still_cleans_up_if_native_icon_removal_fails(
    running_tray, tray_environment, monkeypatch,
):
    tray, window, icon = running_tray
    _, image = tray_environment

    def fail_to_hide(self, visible):
        raise OSError("notification area unavailable")

    monkeypatch.setattr(type(icon), "visible", property(lambda self: True, fail_to_hide),
                        raising=False)
    with pytest.raises(OSError, match="notification area unavailable"):
        tray.stop()

    assert icon.stopped
    image.close.assert_called_once_with()
    assert window.events.closing.handlers == []


def test_failed_exit_leaves_window_and_tray_usable(running_tray, monkeypatch):
    tray, window, icon = running_tray
    with monkeypatch.context() as patch:
        patch.setattr(window, "destroy", Mock(side_effect=RuntimeError("not closed")))
        with pytest.raises(RuntimeError, match="not closed"):
            tray._quit(icon, None)

    window.close()
    tray._show_window(icon, None)
    assert not window.destroyed
    assert not window.hidden
    assert not icon.stopped


def test_tray_setup_failure_keeps_window_closable(tray_environment, monkeypatch, caplog):
    window = FakeWindow()
    tray = tray_mod.LauncherTray(window, "icon.png")
    tray.start()
    icon = tray._icon

    def fail_to_show(self, visible):
        if visible:
            raise OSError("tray unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(type(icon), "visible", property(lambda self: False, fail_to_show),
                          raising=False)
            icon.ready()
            window.close()
            assert window.destroyed
            assert not window.hidden
            assert "System tray unavailable" in caplog.text
    finally:
        tray.stop()


def test_macos_tray_shares_native_application_with_webview(tray_environment, monkeypatch):
    application = object()
    monkeypatch.setattr(tray_mod.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(
        NSApplication=types.SimpleNamespace(sharedApplication=lambda: application),
    ))
    call_after = Mock()
    monkeypatch.setitem(sys.modules, "PyObjCTools", types.SimpleNamespace(
        AppHelper=types.SimpleNamespace(callAfter=call_after),
    ))
    tray = tray_mod.LauncherTray(FakeWindow(), "icon.png")
    try:
        tray.start()
        assert tray._icon.options == {"darwin_nsapplication": application}
        tray._icon.ready()
        call_after.assert_called_once_with(tray._on_ready, tray._icon)
        assert not tray._icon.visible
    finally:
        tray.stop()
