import types
from unittest.mock import Mock

import pytest

from src.claude_china.desktop.window_controls import WindowControls


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, callback):
        self.handlers.append(callback)
        return self

    def fire(self):
        for callback in self.handlers:
            callback()


def make_controls():
    window = Mock()
    window.frameless = True
    window.events = types.SimpleNamespace(maximized=Event(), restored=Event())
    controls = WindowControls(window)
    return controls, window


def test_maximize_toggle_and_external_restore_stay_in_sync():
    controls, window = make_controls()
    assert controls.state() == {"custom_titlebar": True, "maximized": False}
    assert controls.action("maximize")["maximized"] is True
    window.maximize.assert_called_once_with()
    assert controls.action("maximize")["maximized"] is False
    window.restore.assert_called_once_with()
    window.events.maximized.fire()
    assert controls.state()["maximized"] is True
    window.events.restored.fire()
    assert controls.state()["maximized"] is False


def test_minimize_does_not_change_maximized_state():
    controls, window = make_controls()
    window.events.maximized.fire()
    controls.action("minimize")
    window.minimize.assert_called_once_with()
    assert controls.state()["maximized"] is True


def test_close_uses_the_existing_native_closing_and_tray_policy():
    controls, window = make_controls()
    assert controls.action("close")["ok"] is True
    window.destroy.assert_called_once_with()
    window.hide.assert_not_called()


@pytest.mark.parametrize("action", ["quit", "destroy", "__dict__", None, {}])
def test_unknown_window_actions_cannot_call_arbitrary_methods(action):
    controls, window = make_controls()
    assert controls.action(action)["ok"] is False
    assert window.method_calls == []


def test_resize_rejects_invalid_edges_and_maximized_windows():
    controls, window = make_controls()
    assert controls.resize("invalid")["ok"] is False
    assert controls.resize({})["ok"] is False
    window.events.maximized.fire()
    assert controls.resize("se")["ok"] is False
    assert window.method_calls == []


def test_native_titlebar_does_not_enable_duplicate_controls():
    controls, window = make_controls()
    window.frameless = False
    assert controls.state()["custom_titlebar"] is False
    assert controls.resize("se")["ok"] is False


def test_drag_uses_origin_instead_of_accumulating_deltas():
    controls, window = make_controls()
    window.x, window.y = 100, 80
    assert controls.move(20, 10)["ok"] is False
    assert controls.move(20, 10, start=True)["ok"] is True
    window.move.assert_called_with(120, 90)
    window.x, window.y = 120, 90
    controls.move(60, 30)
    window.move.assert_called_with(160, 110)
    assert controls.move(float("nan"), 0)["ok"] is False
    window.events.maximized.fire()
    assert controls.move(10, 10, start=True)["ok"] is False


def test_configure_waits_for_native_window_to_exist():
    controls, window = make_controls()
    window.events.loaded = Mock()
    window.events.loaded.wait.return_value = False
    controls.configure()
    window.events.loaded.wait.assert_called_once_with(30)
    assert controls._native_resize is None
