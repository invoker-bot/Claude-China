from contextlib import contextmanager
from pathlib import Path
import shutil
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from src.claude_china.desktop.apps import APP_REGISTRY
from src.claude_china.desktop.bridge import LauncherBridge
from src.claude_china.desktop.platforms.base import AppStatus


@contextmanager
def temp_desktop_config():
    root = Path.cwd() / ".test-artifacts" / str(uuid4())
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root / "desktop.yaml"
    finally:
        shutil.rmtree(root, ignore_errors=True)


class FakeBackend:
    def __init__(self, found=True, proxy=True, running=False):
        self.found = found
        self.proxy = proxy
        self.running = running
        self.launched = None
        self.stopped = None
        self.calls = []

    def detect(self, app, override):
        return AppStatus(app.id, found=self.found, direct=False,
                         launch_target="t", match_root="r")

    def launch(self, status, env):
        self.calls.append("launch")
        self.launched = (status, env)

    def is_running(self, status):
        return self.running

    def stop(self, status):
        self.calls.append("stop")
        self.stopped = status

    def proxy_enabled(self):
        return self.proxy

    def pick_path_filter(self):
        return ("*",)

    def create_shortcut(self):
        return "x"

    def remove_shortcut(self):
        return []


def test_list_apps_reports_claude_and_codex(monkeypatch):
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            b = LauncherBridge(FakeBackend(found=True), APP_REGISTRY)
            apps = b.list_apps()
            assert [a["id"] for a in apps] == ["claude", "codex"]
            assert all(a["found"] for a in apps)
            assert all(a["running"] is False for a in apps)


def test_launch_blocked_when_proxy_off():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            be = FakeBackend(found=True, proxy=False)
            b = LauncherBridge(be, APP_REGISTRY)
            result = b.launch_app("claude")
            assert result["ok"] is False
            assert "系统代理" in result["error"]
            assert be.launched is None


def test_launch_blocked_when_not_found():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            be = FakeBackend(found=False, proxy=True)
            b = LauncherBridge(be, APP_REGISTRY)
            result = b.launch_app("claude")
            assert result["ok"] is False
            assert be.launched is None


def test_launch_merges_env_with_per_app_winning():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            from src.claude_china.desktop import config as cfg
            data = cfg.load_desktop_config()
            cfg.set_common_env(data, {"SHARED": "common", "C_ONLY": "1"})
            cfg.set_app_env(data, "claude", {"SHARED": "app", "A_ONLY": "2"})
            cfg.save_desktop_config(data)

            be = FakeBackend(found=True, proxy=True)
            b = LauncherBridge(be, APP_REGISTRY)
            result = b.launch_app("claude")
            assert result["ok"] is True
            _status, env = be.launched
            assert env["SHARED"] == "app"     # 专有 wins
            assert env["C_ONLY"] == "1"
            assert env["A_ONLY"] == "2"


def test_launch_stops_running_app_before_starting():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            be = FakeBackend(found=True, proxy=True, running=True)
            b = LauncherBridge(be, APP_REGISTRY)
            result = b.launch_app("claude")
            assert result["ok"] is True
            assert be.calls == ["stop", "launch"]
            assert be.stopped is not None
            assert be.launched is not None


def test_stop_app_not_found_returns_error():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            b = LauncherBridge(FakeBackend(found=False), APP_REGISTRY)
            assert b.stop_app("claude")["ok"] is False


def test_settings_round_trip():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            b = LauncherBridge(FakeBackend(), APP_REGISTRY)
            b.save_settings({"check_system_proxy": False, "env_vars": {"K": "V"}})
            s = b.get_settings()
            assert s["check_system_proxy"] is False
            assert s["env_vars"] == {"K": "V"}
            b.save_app_settings("codex", {"env_vars": {"X": "Y"}})
            a = b.get_app_settings("codex")
            assert a["env_vars"] == {"X": "Y"}


@pytest.mark.parametrize("action,args", [
    ("launch_app", ("claude",)),
    ("stop_app", ("claude",)),
    ("save_settings", ({"check_system_proxy": False},)),
    ("save_app_settings", ("claude", {"env_vars": {}})),
    ("pick_app_path", ("claude",)),
])
def test_user_actions_signal_icon_activity_without_animating_queries(
    tmp_path, monkeypatch, action, args,
):
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
                        tmp_path / "desktop.yaml")
    bridge = LauncherBridge(FakeBackend())
    bridge._activity = Mock()
    getattr(bridge, action)(*args)
    bridge._activity.assert_called_once_with()

    bridge.list_apps()
    bridge.get_settings()
    bridge.get_app_settings("claude")
    bridge.fit_window({})
    bridge._activity.assert_called_once_with()


def test_animation_failure_cannot_prevent_an_app_from_launching(tmp_path, monkeypatch):
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
                        tmp_path / "desktop.yaml")
    backend = FakeBackend()
    bridge = LauncherBridge(backend)
    bridge._activity = Mock(side_effect=OSError("tray unavailable"))

    assert bridge.launch_app("claude") == {"ok": True}
    assert backend.calls == ["stop", "launch"]


class FakeWindow:
    """Records pywebview Window calls; sizes/positions are logical px."""

    def __init__(self, width=680, height=356, x=100, y=100):
        self.width, self.height, self.x, self.y = width, height, x, y
        self.resized = []
        self.moved = []

    def resize(self, width, height):
        self.resized.append((width, height))
        self.width, self.height = width, height

    def move(self, x, y):
        self.moved.append((x, y))
        self.x, self.y = x, y


def _bridge_with_window(window, screen_height=None):
    bridge = LauncherBridge(FakeBackend())
    bridge._attach_window(window, 20, screen_height=screen_height)
    return bridge


def test_fit_window_applies_content_delta_to_outer_height():
    win = FakeWindow(width=680, height=356)
    bridge = _bridge_with_window(win)

    r = bridge.fit_window({"inner": 318, "wanted": 620})

    # +302 CSS px of content -> +302 on the outer window; width untouched.
    assert r == {"ok": True, "height": 658}
    assert win.resized == [(680, 658)]
    assert win.moved == []


def test_fit_window_ignores_one_pixel_dpi_rounding_jitter():
    win = FakeWindow(height=356)
    bridge = _bridge_with_window(win)

    assert bridge.fit_window({"inner": 318, "wanted": 319}) == {"ok": True, "height": 356}
    assert win.resized == []


def test_fit_window_clamps_to_screen_and_nudges_window_up():
    win = FakeWindow(height=356, y=700)
    bridge = _bridge_with_window(win, screen_height=1080)

    r = bridge.fit_window({"inner": 318, "wanted": 2000})

    limit = 1080 - LauncherBridge._SCREEN_MARGIN
    assert r == {"ok": True, "height": limit}
    assert win.moved == [(100, 0)]
    assert win.resized == [(680, limit)]


def test_fit_window_rejects_bad_payloads_and_missing_window():
    bridge = LauncherBridge(FakeBackend())
    assert bridge.fit_window({"inner": 318, "wanted": 620}) == {"ok": False}

    bridge = _bridge_with_window(FakeWindow())
    assert bridge.fit_window(None) == {"ok": False}
    assert bridge.fit_window({"inner": "x", "wanted": 1}) == {"ok": False}
    assert bridge.fit_window({"inner": 0, "wanted": 1}) == {"ok": False}
