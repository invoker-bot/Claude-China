from pathlib import Path

import pytest

from tools import build_desktop


def test_windows_verification_does_not_inherit_powershell7_module_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(build_desktop, "WORK", tmp_path)
    monkeypatch.setattr(build_desktop.os, "environ", {
        "ISCC_EXE": "ISCC.exe", "PSMODULEPATH": "/powershell7/modules",
    })
    (tmp_path / "MicrosoftEdgeWebview2Setup.exe").write_bytes(b"fixture")
    calls = []
    monkeypatch.setattr(build_desktop, "command", lambda args, **kwargs: calls.append((args, kwargs)))
    build_desktop.windows_installer()
    assert "PSMODULEPATH" not in calls[0][1]["env"]
    assert calls[0][1]["env"]["CLAUDE_WEBVIEW_BOOTSTRAPPER"].endswith(".exe")


def test_build_cleanup_refuses_directories_outside_build_outputs(tmp_path):
    sentinel = tmp_path / "config.yaml"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError, match="non-build directory"):
        build_desktop.reset_directory(tmp_path)
    assert sentinel.read_text() == "preserve"


def test_pyproject_and_application_versions_match():
    # The source supports Python 3.9, where tomllib is not in the standard library.
    import re
    project = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert re.search(r'^version = "([^"]+)"', project, re.MULTILINE)[1] == build_desktop.VERSION
