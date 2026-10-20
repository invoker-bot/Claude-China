from pathlib import Path

from typer.testing import CliRunner

from src.claude_china import __version__, config
from src.claude_china.cli import app
from src.claude_china.desktop import config as desktop_config
from src.claude_china.desktop.platforms import macos, windows


def test_cli_reports_claudec_and_claude_china():
    runner = CliRunner()
    version = runner.invoke(app, ["--version"], prog_name="claudec")
    assert version.exit_code == 0
    assert version.stdout.strip() == f"claudec {__version__}"
    help_result = runner.invoke(app, ["--help"], prog_name="claudec")
    assert help_result.exit_code == 0
    assert "Claude China" in help_result.stdout


def test_configuration_uses_claudec_directory():
    assert config.CONFIG_DIR == Path.home() / ".claudec"
    assert desktop_config.DESKTOP_CONFIG_FILE == config.CONFIG_DIR / "desktop.yaml"


def test_windows_install_cleanup_removes_old_and_new_shortcuts_only(tmp_path, monkeypatch):
    monkeypatch.setattr(windows.os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    folders = [tmp_path / "Desktop", tmp_path / "AppData/Microsoft/Windows/Start Menu/Programs"]
    shortcuts = []
    for folder in folders:
        folder.mkdir(parents=True)
        for name in ("AI Launcher", "Claude China"):
            link = folder / f"{name}.lnk"
            link.write_bytes(b"test shortcut")
            shortcuts.append(link)
        (folder / "Claude.lnk").write_bytes(b"unrelated app")

    removed = windows.WindowsBackend().remove_shortcut()
    assert {Path(p) for p in removed} == set(shortcuts)
    assert all(not p.exists() for p in shortcuts)
    assert all((folder / "Claude.lnk").exists() for folder in folders)


def test_macos_install_cleanup_removes_old_and_new_shortcuts_only(tmp_path, monkeypatch):
    monkeypatch.setattr(macos.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    shortcuts = [desktop / f"{name}.app" for name in ("AI Launcher", "Claude China")]
    for path in shortcuts:
        path.mkdir()
    (desktop / "Claude.app").mkdir()

    removed = macos.MacBackend().remove_shortcut()
    assert {Path(p) for p in removed} == set(shortcuts)
    assert all(not p.exists() for p in shortcuts)
    assert (desktop / "Claude.app").is_dir()
