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


def test_freezer_uses_checkout_ui_even_when_an_older_distribution_is_installed(monkeypatch):
    import runpy
    import sys
    import types
    from unittest.mock import Mock
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda name: [(f"/old-site-packages/{name}", name)]
    hooks.copy_metadata = lambda name: []
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    analysis = Mock(return_value=types.SimpleNamespace(
        pure=[], binaries=[], datas=[], scripts=[], exclude_system_libraries=Mock(),
    ))
    packaging = build_desktop.PACKAGING
    runpy.run_path(str(packaging / "claude-china.spec"), init_globals={
        "SPECPATH": str(packaging), "Analysis": analysis,
        "PYZ": Mock(), "EXE": Mock(), "COLLECT": Mock(), "BUNDLE": Mock(),
    })
    data = analysis.call_args.kwargs["datas"]
    assert (str(build_desktop.ROOT / "src/claude_china/desktop/ui"), "claude_china/desktop/ui") in data
    assert ("/old-site-packages/claude_china", "claude_china") not in data
