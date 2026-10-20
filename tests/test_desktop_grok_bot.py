import plistlib
from unittest.mock import Mock

import pytest

from src.claude_china.desktop.apps import get_app
from src.claude_china.desktop.platforms import base, linux, macos, windows


@pytest.fixture
def windows_installation(tmp_path, monkeypatch):
    local = tmp_path / "Local AppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(windows, "winreg", None)
    binary = local / "Programs" / "Grok Bot" / "Grok Bot.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"desktop executable")
    backend = windows.WindowsBackend()
    monkeypatch.setattr(backend, "_query_packages", Mock(
        side_effect=AssertionError("Grok Bot must not be detected as an MSIX app"),
    ))
    return backend, binary


def test_windows_detects_standard_grok_bot_installation(windows_installation):
    backend, binary = windows_installation
    status = backend.detect(get_app("grok-bot"))
    assert status.found and status.direct
    assert status.launch_target == str(binary)
    assert status.match_root == str(binary)


def test_windows_grok_bot_override_takes_priority(windows_installation, tmp_path):
    backend, _ = windows_installation
    override = tmp_path / "portable" / "Grok Bot.exe"
    override.parent.mkdir()
    override.write_bytes(b"portable")
    status = backend.detect(get_app("grok-bot"), str(override))
    assert status.found and status.direct
    assert status.launch_target == str(override)
    assert status.match_root == str(override)


class InstallRegistry:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, root, values):
        self.root = root
        self.values = values
        self.closed = []

    def OpenKey(self, root, subkey):
        expected = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\8db316bb-b3e2-5dd2-9554-ecccb62be362"
        if root != self.root or subkey != expected:
            raise FileNotFoundError()
        return "grok-bot-install"

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError()
        return self.values[name], 1

    def CloseKey(self, key):
        self.closed.append(key)


@pytest.mark.parametrize("root", ["HKCU", "HKLM"])
@pytest.mark.parametrize("value_name", ["InstallLocation", "DisplayIcon"])
def test_windows_finds_custom_registered_grok_bot(
    windows_installation, tmp_path, monkeypatch, root, value_name,
):
    backend, _ = windows_installation
    binary = tmp_path / "Custom Apps, Inc" / "Grok Bot.exe"
    binary.parent.mkdir()
    binary.write_bytes(b"custom desktop executable")
    value = str(binary.parent) if value_name == "InstallLocation" else f'"{binary}",0'
    registry = InstallRegistry(root, {value_name: value})
    monkeypatch.setattr(windows, "winreg", registry)
    status = backend.detect(get_app("grok-bot"))
    assert status.launch_target == str(binary)
    assert status.match_root == str(binary)
    assert registry.closed == ["grok-bot-install"]


def test_windows_ignores_uninstaller_in_registry_icon(windows_installation, tmp_path, monkeypatch):
    backend, binary = windows_installation
    uninstaller = tmp_path / "Uninstall Grok Bot.exe"
    uninstaller.write_bytes(b"uninstaller")
    registry = InstallRegistry("HKCU", {"DisplayIcon": f'"{uninstaller}",0'})
    monkeypatch.setattr(windows, "winreg", registry)
    assert backend.detect(get_app("grok-bot")).launch_target == str(binary)


def test_windows_grok_cli_does_not_count_as_desktop_installation(
    windows_installation, tmp_path, monkeypatch,
):
    backend, binary = windows_installation
    binary.unlink()
    cli = tmp_path / "bin" / "grok.exe"
    cli.parent.mkdir()
    cli.write_bytes(b"terminal cli")
    monkeypatch.setenv("PATH", str(cli.parent))
    assert not backend.detect(get_app("grok-bot")).found


def test_grok_bot_windows_launch_preserves_path_and_environment(windows_installation, monkeypatch):
    backend, binary = windows_installation
    launch = Mock()
    monkeypatch.setattr(windows.subprocess, "Popen", launch)
    env = {"HTTPS_PROXY": "http://localhost:7890", "TEST_APP": "grok-bot"}
    backend.launch(backend.detect(get_app("grok-bot")), env)
    launch.assert_called_once_with([str(binary)], env=env, creationflags=windows._NO_WINDOW)


def test_grok_bot_monitor_and_stop_target_only_desktop_executable(windows_installation, monkeypatch):
    backend, binary = windows_installation
    status = backend.detect(get_app("grok-bot"))
    monitor = Mock(return_value=True)
    stop = Mock()
    monkeypatch.setattr(base, "any_process_under", monitor)
    monkeypatch.setattr(base, "stop_processes_under", stop)
    assert backend.is_running(status)
    backend.stop(status)
    monitor.assert_called_once_with([str(binary)], ignored_names=None)
    stop.assert_called_once_with([str(binary)], ignored_names=None)
    assert not base._matches(str(binary.parent / "grok.exe"), status.match_root)
    assert not base._matches(str(binary.parent / "Uninstall Grok Bot.exe"), status.match_root)


def test_macos_finds_grok_bot_by_bundle_name_without_invented_bundle_id(tmp_path, monkeypatch):
    bundle = tmp_path / "Grok Bot.app"
    bundle.mkdir()
    lookup = Mock(return_value=str(bundle) + "\n")
    monkeypatch.setattr(macos.subprocess, "check_output", lookup)
    assert macos.MacBackend()._find_bundle(get_app("grok-bot")) == str(bundle)
    query = lookup.call_args.args[0]
    assert query[0] == "mdfind"
    assert "kMDItemFSName == 'Grok Bot.app'" in query[1]
    assert "com.apple.application-bundle" in query[1]


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
def test_macos_detected_bundle_launches_binary_to_pass_environment(tmp_path, monkeypatch, app_id):
    app = get_app(app_id)
    bundle = tmp_path / app.mac_bundle_name
    contents = bundle / "Contents"
    binary = contents / "MacOS" / app.display
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"desktop executable")
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleExecutable": app.display}, stream)
    backend = macos.MacBackend()
    monkeypatch.setattr(backend, "_find_bundle", lambda app: str(bundle))
    launch = Mock()
    monkeypatch.setattr(macos.subprocess, "Popen", launch)
    status = backend.detect(app)
    assert status.found and status.direct
    assert status.launch_target == str(binary)
    assert status.match_root == str(bundle)
    env = {"HTTPS_PROXY": "http://localhost:7890"}
    backend.launch(status, env)
    launch.assert_called_once_with([str(binary)], env=env)


def test_linux_finds_installed_grok_bot_without_detecting_grok_cli(tmp_path, monkeypatch):
    binary = tmp_path / "Grok Bot" / "grok-bot"
    binary.parent.mkdir()
    binary.write_bytes(b"desktop executable")
    which = Mock(return_value=str(binary))
    monkeypatch.setattr(linux.shutil, "which", which)
    monkeypatch.setattr(linux.os, "access", lambda path, mode: True)
    status = linux.LinuxBackend().detect(get_app("grok-bot"))
    assert status.found and status.direct
    assert status.launch_target == str(binary.resolve())
    assert status.match_root == str(binary.resolve())
    which.assert_called_once_with("grok-bot")


def test_linux_grok_bot_override_wins(tmp_path, monkeypatch):
    image = tmp_path / "Portable Grok Bot"
    image.write_bytes(b"appimage")
    which = Mock(side_effect=AssertionError("Explicit path takes precedence"))
    monkeypatch.setattr(linux.shutil, "which", which)
    monkeypatch.setattr(linux.os, "access", lambda path, mode: True)
    status = linux.LinuxBackend().detect(get_app("grok-bot"), str(image))
    assert status.found and status.direct
    assert status.launch_target == str(image.resolve())
    assert status.match_root == str(image.resolve())


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
def test_linux_never_looks_up_terminal_cli_for_desktop(app_id, monkeypatch):
    def which(command):
        assert command == "grok-bot"
        return None

    monkeypatch.setattr(linux.shutil, "which", which)
    assert not linux.LinuxBackend().detect(get_app(app_id)).found
