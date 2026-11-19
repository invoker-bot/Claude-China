import pytest

from src.claude_china.desktop.apps import AppSpec, APP_REGISTRY, get_app


def test_registry_has_four_known_apps():
    ids = [a.id for a in APP_REGISTRY]
    assert ids == ["claude", "codex", "grok-bot", "antigravity"]


def test_registry_entries_are_appspec_with_identifiers():
    claude = get_app("claude")
    assert isinstance(claude, AppSpec)
    assert claude.display == "Claude"
    assert claude.win_aumid == "Claude_pzs8sxrjxfjjc!Claude"
    assert claude.win_package_family == "Claude_pzs8sxrjxfjjc"
    assert claude.mac_bundle_name == "Claude.app"
    assert claude.mac_bundle_id == "com.anthropic.claudefordesktop"


def test_get_app_unknown_raises():
    with pytest.raises(KeyError):
        get_app("nope")
    with pytest.raises(KeyError):
        get_app("chatgpt")


def test_antigravity_app_registration_uses_desktop_not_cli_identity():
    app = get_app('antigravity')
    assert app.display == 'Antigravity'
    assert app.win_executable == 'Antigravity.exe'
    assert app.mac_bundle_name == 'Antigravity.app'
    assert app.linux_commands == ('Antigravity', 'antigravity')


def test_windows_detects_standard_antigravity_installation(tmp_path, monkeypatch):
    from src.claude_china.desktop.platforms import windows
    binary = tmp_path / 'Programs' / 'Antigravity' / 'Antigravity.exe'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'desktop executable')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(windows, 'winreg', None)
    status = windows.WindowsBackend().detect(get_app('antigravity'))
    assert status.found and status.direct and status.launch_target == str(binary)


def test_linux_detects_antigravity_desktop_command(tmp_path, monkeypatch):
    from src.claude_china.desktop.platforms import linux
    binary = tmp_path / 'Antigravity'
    binary.write_bytes(b'desktop executable')
    monkeypatch.setattr(linux.os, 'access', lambda path, mode: True)
    monkeypatch.setattr(linux.shutil, 'which', lambda command: str(binary) if command == 'Antigravity' else None)
    status = linux.LinuxBackend().detect(get_app('antigravity'))
    assert status.found and status.direct and status.launch_target == str(binary.resolve())
