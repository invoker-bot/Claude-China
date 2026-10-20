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


def test_list_apps_reports_claude_codex_and_grok_bot(monkeypatch):
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            b = LauncherBridge(FakeBackend(found=True), APP_REGISTRY)
            apps = b.list_apps()
            assert [a["id"] for a in apps] == ["claude", "codex", "grok-bot"]
            assert all(a["found"] for a in apps)
            assert all(a["running"] is False for a in apps)


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
def test_launch_blocked_when_proxy_off(app_id):
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            be = FakeBackend(found=True, proxy=False)
            b = LauncherBridge(be, APP_REGISTRY)
            result = b.launch_app(app_id)
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


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
def test_launch_merges_env_with_per_app_winning(app_id):
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            from src.claude_china.desktop import config as cfg
            data = cfg.load_desktop_config()
            cfg.set_common_env(data, {"SHARED": "common", "C_ONLY": "1"})
            cfg.set_app_env(data, app_id, {"SHARED": "app", "A_ONLY": "2"})
            cfg.save_desktop_config(data)

            be = FakeBackend(found=True, proxy=True)
            b = LauncherBridge(be, APP_REGISTRY)
            result = b.launch_app(app_id)
            assert result["ok"] is True
            _status, env = be.launched
            assert env["SHARED"] == "app"     # 专有 wins
            assert env["C_ONLY"] == "1"
            assert env["A_ONLY"] == "2"
            assert _status.app_id == app_id


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
def test_launch_stops_running_app_before_starting(app_id):
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            be = FakeBackend(found=True, proxy=True, running=True)
            b = LauncherBridge(be, APP_REGISTRY)
            result = b.launch_app(app_id)
            assert result["ok"] is True
            assert be.calls == ["stop", "launch"]
            assert be.stopped is not None
            assert be.launched is not None
            assert be.stopped.app_id == app_id


def test_grok_bot_settings_are_independent_of_other_apps(tmp_path, monkeypatch):
    from src.claude_china.desktop import config as cfg

    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    bridge = LauncherBridge(FakeBackend())
    bridge.save_app_settings("claude", {"env_vars": {"TEST_APP": "claude"}})
    bridge.save_app_settings("grok-bot", {"env_vars": {"HTTPS_PROXY": "http://localhost:7890"}})
    assert bridge.get_app_settings("grok-bot")["env_vars"] == {
        "HTTPS_PROXY": "http://localhost:7890",
    }
    assert bridge.get_app_settings("claude")["env_vars"] == {"TEST_APP": "claude"}
    assert bridge.get_app_settings("codex")["env_vars"] == {}


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


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
def test_auto_proxy_env_uses_current_proxy_on_each_launch(tmp_path, monkeypatch, app_id):
    from src.claude_china.desktop import config as cfg

    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    monkeypatch.setenv("HTTP_PROXY", "http://stale:1111")
    monkeypatch.setenv("https_proxy", "http://stale:2222")
    backend = FakeBackend()
    backend.system_http_proxy = Mock(side_effect=["http://localhost:7890", "http://localhost:7891"])
    bridge = LauncherBridge(backend)
    bridge.save_settings({"auto_proxy_env": True, "env_vars": {}})
    assert bridge.get_settings()["auto_proxy_env"] is True
    for port in (7890, 7891):
        assert bridge.launch_app(app_id)["ok"] is True
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            assert backend.launched[1][key] == f"http://localhost:{port}"
    # The derived endpoint is never persisted or written to the parent env.
    assert "7891" not in cfg.DESKTOP_CONFIG_FILE.read_text(encoding="utf-8")
    import os
    assert os.environ["HTTP_PROXY"] == "http://stale:1111"


def test_auto_proxy_env_explicit_common_and_app_overrides_win(tmp_path, monkeypatch):
    from src.claude_china.desktop import config as cfg

    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    backend = FakeBackend()
    backend.system_http_proxy = Mock(return_value="http://localhost:7890")
    bridge = LauncherBridge(backend)
    bridge.save_settings({"auto_proxy_env": True, "env_vars": {
        "HTTP_PROXY": "http://common:8080", "HTTPS_PROXY": "http://common:8080",
        "NO_PROXY": "localhost", "UNCHANGED": "common",
    }})
    bridge.save_app_settings("claude", {"env_vars": {"https_proxy": "http://app:9999"}})
    assert bridge.launch_app("claude")["ok"] is True
    env = backend.launched[1]
    assert env["HTTP_PROXY"] == env["http_proxy"] == "http://common:8080"
    assert env["HTTPS_PROXY"] == env["https_proxy"] == "http://app:9999"
    assert env["NO_PROXY"] == "localhost"
    assert env["UNCHANGED"] == "common"


@pytest.mark.parametrize("check_proxy", [True, False])
@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
def test_invalid_auto_proxy_blocks_restart_before_stopping_app(tmp_path, monkeypatch, check_proxy, app_id):
    from src.claude_china.desktop import config as cfg

    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    backend = FakeBackend(running=True)
    backend.system_http_proxy = Mock(side_effect=ValueError("bad proxy with secret password"))
    bridge = LauncherBridge(backend)
    bridge.save_settings({"check_system_proxy": check_proxy, "auto_proxy_env": True,
                          "env_vars": {"HTTP_PROXY": "http://manual:7890"}})
    result = bridge.launch_app(app_id)
    assert result["ok"] is False
    assert "系统代理" in result["error"]
    assert "取消启动" in result["error"]
    assert "secret" not in result["error"]
    assert backend.calls == []


def test_disabled_auto_proxy_never_reads_system_endpoint(tmp_path, monkeypatch):
    from src.claude_china.desktop import config as cfg

    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    backend = FakeBackend(proxy=False)
    backend.system_http_proxy = Mock(side_effect=AssertionError("must not read"))
    bridge = LauncherBridge(backend)
    bridge.save_settings({"check_system_proxy": False, "auto_proxy_env": False,
                          "env_vars": {"HTTPS_PROXY": "http://manual:7890"}})
    assert bridge.launch_app("claude")["ok"] is True
    assert backend.launched[1]["HTTPS_PROXY"] == "http://manual:7890"
    backend.system_http_proxy.assert_not_called()


def test_picking_path_can_leave_saved_settings_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
                        tmp_path / "desktop.yaml")
    bridge = LauncherBridge(FakeBackend())
    window = Mock()
    window.create_file_dialog.return_value = [str(tmp_path / "Grok Bot.exe")]
    bridge._attach_window(window, 20)
    before = bridge.get_app_settings("grok-bot")

    result = bridge.pick_app_path("grok-bot", persist=False)

    assert result == {"ok": True, "path": str(tmp_path / "Grok Bot.exe")}
    assert bridge.get_app_settings("grok-bot") == before


def test_save_app_path_and_environment_together_and_restore_auto_detection(tmp_path, monkeypatch):
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
                        tmp_path / "desktop.yaml")
    backend = FakeBackend()
    backend.detect = Mock(wraps=backend.detect)
    bridge = LauncherBridge(backend)
    path = str(tmp_path / "Grok Bot.exe")

    bridge.save_app_settings("grok-bot", {"path": path, "env_vars": {"APP_TEST": "1"}})
    assert bridge.get_app_settings("grok-bot") == {
        "path": path, "env_vars": {"APP_TEST": "1"},
    }
    assert backend.detect.call_args.args[1] == path
    bridge.save_app_settings("grok-bot", {"env_vars": {"APP_TEST": "2"}})
    assert bridge.get_app_settings("grok-bot")["path"] == path
    bridge.save_app_settings("grok-bot", {"path": "", "env_vars": {}})
    assert bridge.get_app_settings("grok-bot") == {"path": "", "env_vars": {}}
    assert not backend.detect.call_args.args[1]


def test_explicit_refresh_redetects_newly_installed_apps(tmp_path, monkeypatch):
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
                        tmp_path / "desktop.yaml")
    backend = FakeBackend(found=False)
    bridge = LauncherBridge(backend)
    assert not any(app["found"] for app in bridge.list_apps())
    backend.found = True
    assert all(app["found"] for app in bridge.list_apps(refresh=True))


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
