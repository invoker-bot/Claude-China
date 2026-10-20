from contextlib import contextmanager
from pathlib import Path
import shutil
from unittest.mock import patch
from uuid import uuid4

from src.claude_china.desktop import config as cfg


@contextmanager
def temp_desktop_config():
    root = Path.cwd() / ".test-artifacts" / str(uuid4())
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root / "desktop.yaml"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_load_creates_defaults_when_missing():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            assert not f.exists()
            data = cfg.load_desktop_config()
            assert f.exists()
            assert data["check_system_proxy"] is True
            assert data["auto_proxy_env"] is False
            assert data["env_vars"] == {}
            assert data["apps"] == {}


def test_round_trip_common_and_app_settings():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            data = cfg.load_desktop_config()
            cfg.set_check_system_proxy(data, False)
            cfg.set_auto_proxy_env(data, True)
            cfg.set_common_env(data, {"HTTP_PROXY": "http://127.0.0.1:7890"})
            cfg.set_app_env(data, "claude", {"ANTHROPIC_LOG": "debug"})
            cfg.set_app_path(data, "codex", "/Applications/Codex.app")
            cfg.save_desktop_config(data)

            reloaded = cfg.load_desktop_config()
            assert cfg.get_check_system_proxy(reloaded) is False
            assert cfg.get_auto_proxy_env(reloaded) is True
            assert cfg.get_common_env(reloaded) == {"HTTP_PROXY": "http://127.0.0.1:7890"}
            assert cfg.get_app_env(reloaded, "claude") == {"ANTHROPIC_LOG": "debug"}
            assert cfg.get_app_path(reloaded, "codex") == "/Applications/Codex.app"


def test_getters_default_for_unknown_app():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            data = cfg.load_desktop_config()
            assert cfg.get_app_env(data, "ghost") == {}
            assert cfg.get_app_path(data, "ghost") is None


def test_load_coerces_null_valued_keys():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            # Hand-written YAML with bare keys -> parsed as None by PyYAML.
            f.write_text("check_system_proxy: false\napps:\nenv_vars:\n", encoding="utf-8")
            data = cfg.load_desktop_config()
            assert data["apps"] == {}
            assert data["env_vars"] == {}
            # The write path must not crash on the coerced values.
            assert cfg.get_auto_proxy_env(data) is False
            cfg.set_app_env(data, "claude", {"K": "V"})
            assert cfg.get_app_env(data, "claude") == {"K": "V"}


def test_set_app_env_preserves_existing_app_path():
    with temp_desktop_config() as f:
        with patch("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f):
            data = cfg.load_desktop_config()
            cfg.set_app_path(data, "codex", "/Applications/Codex.app")
            cfg.set_app_env(data, "codex", {"X": "Y"})
            # Setting env must not wipe the previously-set path (and vice versa).
            assert cfg.get_app_path(data, "codex") == "/Applications/Codex.app"
            assert cfg.get_app_env(data, "codex") == {"X": "Y"}
