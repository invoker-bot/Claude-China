import sys
import types

import pytest
from typer.testing import CliRunner

from src.claude_china.cli import app

runner = CliRunner()
RELEASES = "https://github.com/invoker-bot/Claude-China/releases/latest"


def test_install_redirects_to_release_without_loading_desktop_dependencies(monkeypatch):
    def unexpected_backend():
        pytest.fail("install must not create Python shortcuts")

    monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", unexpected_backend)
    result = runner.invoke(app, ["desktop", "install"])
    assert result.exit_code == 1
    assert RELEASES in result.output
    assert "installer" in result.output


@pytest.mark.parametrize("args", [[], ["--keep-config"], ["--purge"]])
def test_uninstall_redirects_to_os_and_preserves_settings(monkeypatch, tmp_path, args):
    settings = tmp_path / "desktop.yaml"
    settings.write_text("check_system_proxy: true\n")
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", settings)

    def unexpected_backend():
        pytest.fail("CLI uninstall must not remove installer-owned files")

    monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", unexpected_backend)
    result = runner.invoke(app, ["desktop", "uninstall"] + args)
    assert result.exit_code == 1
    assert "Installed apps" in result.output
    assert "Trash" in result.output
    assert "package manager" in result.output
    assert settings.read_text() == "check_system_proxy: true\n"


def test_download_prints_release_location_without_desktop_extra():
    result = runner.invoke(app, ["desktop", "download"])
    assert result.exit_code == 0
    assert RELEASES in result.output


@pytest.mark.parametrize("missing_module", ["webview", "pystray", "PIL"])
def test_run_missing_extra_prints_release_and_developer_hint(monkeypatch, missing_module):
    for module in ("webview", "psutil", "pystray"):
        monkeypatch.setitem(sys.modules, module, types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=object()))
    monkeypatch.setattr("src.claude_china.desktop.platforms.get_backend", lambda: object())
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == missing_module:
            raise ImportError("missing desktop dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = runner.invoke(app, ["desktop", "run"])
    assert result.exit_code == 1
    assert RELEASES in result.output
    assert "claude-china[desktop]" in result.output
