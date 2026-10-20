import types

import pytest


def test_frozen_children_receive_original_library_search_path(monkeypatch, tmp_path):
    from src.claude_china.desktop import process
    bundle = str(tmp_path / "_internal")
    external = str(tmp_path / "system")
    monkeypatch.setattr(process, "sys", types.SimpleNamespace(frozen=True, _MEIPASS=bundle, platform="linux"))
    inherited = {
        "LD_LIBRARY_PATH": bundle,
        "LD_LIBRARY_PATH_ORIG": external,
        "PATH": process.os.pathsep.join([bundle, external]),
        "GI_TYPELIB_PATH": bundle,
        "GTK_DATA_PREFIX": bundle,
        "PANGO_LIBDIR": bundle,
        "GDK_PIXBUF_MODULE_FILE": str(tmp_path / "rewritten-loaders.cache"),
        "_PYI_APPLICATION_HOME_DIR": bundle,
        "HTTPS_PROXY": "http://localhost:7890",
    }
    result = process.external_environment(inherited)
    assert result["LD_LIBRARY_PATH"] == external
    assert result["PATH"] == external
    assert "GI_TYPELIB_PATH" not in result
    assert "GTK_DATA_PREFIX" not in result
    assert "PANGO_LIBDIR" not in result
    assert "GDK_PIXBUF_MODULE_FILE" not in result
    assert "_PYI_APPLICATION_HOME_DIR" not in result
    assert result["HTTPS_PROXY"] == inherited["HTTPS_PROXY"]
    assert inherited["LD_LIBRARY_PATH"] == bundle


def test_frozen_children_drop_library_path_without_original(monkeypatch, tmp_path):
    from src.claude_china.desktop import process
    bundle = str(tmp_path)
    monkeypatch.setattr(process, "sys", types.SimpleNamespace(frozen=True, _MEIPASS=bundle, platform="linux"))
    assert "LD_LIBRARY_PATH" not in process.external_environment({"LD_LIBRARY_PATH": bundle})


def test_source_launch_keeps_environment(monkeypatch):
    from src.claude_china.desktop import process
    monkeypatch.setattr(process, "sys", types.SimpleNamespace(platform="linux"))
    original = {"LD_LIBRARY_PATH": "/custom", "A": "B"}
    assert process.external_environment(original) == original


def test_windows_restores_dll_directory_when_child_launch_fails(monkeypatch, tmp_path):
    from src.claude_china.desktop import process
    bundle = str(tmp_path)
    monkeypatch.setattr(process, "sys", types.SimpleNamespace(frozen=True, _MEIPASS=bundle, platform="win32"))
    calls = []
    monkeypatch.setattr(process, "_set_dll_directory", lambda path: calls.append(path))

    def fail(*args, **kwargs):
        assert calls == [None]
        raise OSError("cannot launch")

    monkeypatch.setattr(process._subprocess, "Popen", fail)
    with pytest.raises(OSError, match="cannot launch"):
        process.Popen(["external.exe"], env={"A": "B"})
    assert calls == [None, bundle]
