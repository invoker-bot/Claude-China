import ctypes
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from src.claude_china.desktop.platforms import windows_shell as shell


def test_icon_cache_changes_path_when_artwork_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(shell.cfg, "DESKTOP_CONFIG_FILE", tmp_path / "settings" / "desktop.yaml")
    source = tmp_path / "icon.ico"
    source.write_bytes(b"old artwork")
    old = Path(shell.launcher_icon_path(source))
    assert old.read_bytes() == source.read_bytes()
    assert Path(shell.launcher_icon_path(source)) == old

    source.write_bytes(b"new artwork")
    current = Path(shell.launcher_icon_path(source))
    assert current != old
    assert current.read_bytes() == b"new artwork"
    # Existing pinned shortcuts may still refer to a previous version.
    assert old.read_bytes() == b"old artwork"


def test_process_identity_uses_stable_app_id_and_checks_hresult(monkeypatch):
    native = Mock()
    native.SetCurrentProcessExplicitAppUserModelID.return_value = 0
    monkeypatch.setattr(shell, "_dll", lambda name: native)
    shell.set_process_app_id()
    native.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(shell.APP_USER_MODEL_ID)
    native.SetCurrentProcessExplicitAppUserModelID.return_value = -2147467259
    with pytest.raises(OSError):
        shell.set_process_app_id()


@pytest.mark.parametrize("apartment", [0, 1, -2147417850])
def test_failed_shortcut_commit_releases_resources_without_uninitializing_foreign_apartment(
    monkeypatch, apartment,
):
    ole, native = Mock(), Mock()
    ole.CoInitializeEx.return_value = apartment

    def open_store(path, context, flags, iid, output):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = 1234
        return 0

    native.SHGetPropertyStoreFromParsingName.side_effect = open_store
    methods = {6: Mock(return_value=0), 7: Mock(return_value=-2147467259), 2: Mock()}
    monkeypatch.setattr(shell, "_dll", lambda name: ole if name == "ole32" else native)
    monkeypatch.setattr(shell, "_com_method", lambda store, index, *args, **kwargs: methods[index])

    with pytest.raises(OSError):
        shell.set_shortcut_app_id("example.lnk")
    methods[2].assert_called_once()
    assert ole.CoUninitialize.call_count == (1 if apartment >= 0 else 0)
    native.SHChangeNotify.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows shortcut property store")
def test_native_shortcut_matches_process_identity_and_versioned_icon(tmp_path, monkeypatch):
    from src.claude_china.desktop.platforms.windows import WindowsBackend

    monkeypatch.setattr(shell.cfg, "DESKTOP_CONFIG_FILE", tmp_path / "settings" / "desktop.yaml")
    backend = WindowsBackend()
    shortcut = tmp_path / "launcher's $icon.lnk"
    icon = backend._icon_path()
    backend._write_lnk(str(shortcut), sys.executable, "-m claude_china.cli desktop run", icon)

    # Read back through a separate native Shell client, not our writer.
    quote = backend._ps_quote
    script = (
        "$ws = New-Object -ComObject WScript.Shell\n"
        f"$lnk = $ws.CreateShortcut({quote(shortcut)})\n"
        "$shell = New-Object -ComObject Shell.Application\n"
        f"$item = $shell.NameSpace({quote(tmp_path)}).ParseName({quote(shortcut.name)})\n"
        "@{ appId=$item.ExtendedProperty('System.AppUserModel.ID'); "
        "icon=$lnk.IconLocation; target=$lnk.TargetPath; arguments=$lnk.Arguments } "
        "| ConvertTo-Json -Compress\n"
    )
    result = json.loads(subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", script],
        text=True, creationflags=0x08000000,
    ))
    assert result["appId"] == shell.APP_USER_MODEL_ID
    assert result["icon"] == icon + ",0"
    assert Path(result["target"]) == Path(sys.executable)
    assert result["arguments"] == "-m claude_china.cli desktop run"
