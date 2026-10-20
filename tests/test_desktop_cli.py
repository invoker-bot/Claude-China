from contextlib import contextmanager
from pathlib import Path
import shutil
import sys
import types
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from src.claude_china.cli import app

runner = CliRunner()


@contextmanager
def temp_desktop_config():
    root = Path.cwd() / ".test-artifacts" / str(uuid4())
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root / "desktop.yaml"
    finally:
        shutil.rmtree(root, ignore_errors=True)


class FakeBackend:
    def __init__(self, removed=None):
        self.removed = [] if removed is None else removed
        self.calls = []

    def create_shortcut(self):
        self.calls.append("create")
        return "/path/Claude China.lnk"

    def remove_shortcut(self):
        self.calls.append("remove")
        return self.removed


def fake_desktop_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=object()))


def test_install_creates_shortcut(monkeypatch):
    fake_desktop_extra(monkeypatch)
    monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", lambda: FakeBackend())
    result = runner.invoke(app, ["desktop", "install"])
    assert result.exit_code == 0
    assert "Claude China.lnk" in result.output


def test_install_recreates_existing_shortcut(monkeypatch):
    fake_desktop_extra(monkeypatch)
    backend = FakeBackend(removed=["/path/Claude China.lnk"])
    monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", lambda: backend)

    result = runner.invoke(app, ["desktop", "install"])

    assert result.exit_code == 0
    assert backend.calls == ["remove", "create"]
    assert "Removed existing shortcut" in result.output
    assert "Shortcut ready" in result.output


def test_install_missing_extra_prints_hint_and_does_not_create_shortcut(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", lambda: backend)
    # Force the optional-extra import check to fail.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("no webview")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = runner.invoke(app, ["desktop", "install"])
    assert result.exit_code == 1
    assert "claude-china[desktop]" in result.output
    assert backend.calls == []


def test_install_unsupported_platform(monkeypatch):
    monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", lambda: None)
    result = runner.invoke(app, ["desktop", "install"])
    assert result.exit_code == 1
    assert "Windows and macOS only" in result.output


def test_uninstall_removes_shortcut_and_keeps_config(monkeypatch):
    with temp_desktop_config() as f:
        f.write_text("check_system_proxy: true\n")
        monkeypatch.setattr(
            "src.claude_china.desktop.platforms.get_backend",
            lambda: FakeBackend(removed=["/path/Claude China.lnk"]),
        )
        monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f)
        result = runner.invoke(app, ["desktop", "uninstall", "--keep-config"])
        assert result.exit_code == 0
        assert "Removed" in result.output
        assert f.exists()


def test_uninstall_purge_deletes_config(monkeypatch):
    with temp_desktop_config() as f:
        f.write_text("check_system_proxy: true\n")
        monkeypatch.setattr(
            "src.claude_china.desktop.platforms.get_backend",
            lambda: FakeBackend(removed=["/path/Claude China.lnk"]),
        )
        monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f)
        result = runner.invoke(app, ["desktop", "uninstall", "--purge"])
        assert result.exit_code == 0
        assert not f.exists()


def test_uninstall_nothing_to_remove(monkeypatch):
    class EmptyBackend(FakeBackend):
        def remove_shortcut(self):
            return []

    with temp_desktop_config() as f:
        monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", lambda: EmptyBackend())
        monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", f)
        result = runner.invoke(app, ["desktop", "uninstall", "--keep-config"])
        assert result.exit_code == 0
        assert "nothing to remove" in result.output


@pytest.mark.parametrize("missing_module", ["webview", "pystray", "PIL"])
def test_run_missing_extra_prints_hint(monkeypatch, missing_module):
    fake_desktop_extra(monkeypatch)
    monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", lambda: FakeBackend())
    # Force the optional-extra import check to fail.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == missing_module:
            raise ImportError("missing desktop dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = runner.invoke(app, ["desktop", "run"])
    assert result.exit_code == 1
    assert "claude-china[desktop]" in result.output
