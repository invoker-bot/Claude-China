import os

import pytest

from src.claude_china.desktop.apps import get_app
from src.claude_china.desktop.platforms import windows


@pytest.fixture(autouse=True)
def isolated_icon_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
                        tmp_path / ".claudec" / "desktop.yaml")


def test_detect_override_path_wins(tmp_path):
    exe = tmp_path / "Claude.exe"
    exe.write_text("x")
    be = windows.WindowsBackend()
    st = be.detect(get_app("claude"), str(exe))
    assert st.found is True
    assert st.direct is True
    assert st.launch_target == str(exe)
    assert st.match_root == str(exe)


def test_detect_brokered_by_package_family(monkeypatch):
    be = windows.WindowsBackend()
    monkeypatch.setattr(be, "_query_packages", lambda: [
        {"Name": "Claude", "PackageFamilyName": "Claude_pzs8sxrjxfjjc",
         "InstallLocation": r"C:\Program Files\WindowsApps\Claude_1.0_x64__pzs8sxrjxfjjc"},
    ])
    st = be.detect(get_app("claude"), None)
    assert st.found is True
    assert st.direct is False
    assert st.launch_target == "Claude_pzs8sxrjxfjjc!Claude"
    assert st.match_root == r"C:\Program Files\WindowsApps\Claude_1.0_x64__pzs8sxrjxfjjc"


def test_detect_not_found(monkeypatch):
    be = windows.WindowsBackend()
    monkeypatch.setattr(be, "_query_packages", lambda: [])
    st = be.detect(get_app("codex"), None)
    assert st.found is False


def test_query_packages_passes_no_window(monkeypatch):
    captured = {}
    monkeypatch.setattr(windows.subprocess, "check_output",
                        lambda argv, **kw: captured.update(kw) or "[]")
    be = windows.WindowsBackend()
    assert be._query_packages() == []
    assert captured.get("creationflags") == windows._NO_WINDOW


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, value):
        self._value = value

    def OpenKey(self, root, sub):
        return "key"

    def QueryValueEx(self, key, name):
        return (self._value, 4)

    def CloseKey(self, key):
        pass


def test_proxy_enabled_true(monkeypatch):
    be = windows.WindowsBackend()
    monkeypatch.setattr(windows, "winreg", FakeWinreg(1))
    assert be.proxy_enabled() is True


def test_proxy_enabled_false_when_zero(monkeypatch):
    be = windows.WindowsBackend()
    monkeypatch.setattr(windows, "winreg", FakeWinreg(0))
    assert be.proxy_enabled() is False


def test_proxy_enabled_false_when_no_winreg(monkeypatch):
    be = windows.WindowsBackend()
    monkeypatch.setattr(windows, "winreg", None)
    assert be.proxy_enabled() is False


from src.claude_china.desktop.platforms import base as base_mod
from src.claude_china.desktop.platforms.base import AppStatus


class FakeProc:
    def __init__(self, exe):
        self.info = {"exe": exe}


class FakePsutil:
    def __init__(self, procs):
        self._procs = procs

    def process_iter(self, attrs=None):
        return list(self._procs)


def test_launch_brokered_falls_back_to_explorer_when_root_missing(monkeypatch):
    # match_root is not a real directory, so _resolve_exe returns None and
    # launch falls back to the OS broker (explorer shell:AppsFolder). This is
    # the fallback path, not an "always brokered" invariant — direct-exe launch
    # is preferred whenever the install dir/manifest resolve (see
    # test_launch_brokered_prefers_real_exe_so_env_propagates).
    calls = {}
    monkeypatch.setattr(windows.subprocess, "Popen",
                        lambda argv, env=None, creationflags=0: calls.update(
                            argv=argv, env=env, creationflags=creationflags))
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="Claude_pzs8sxrjxfjjc!Claude", match_root="C:\\x")
    be.launch(st, {"A": "1"})
    assert calls["argv"] == ["explorer.exe", "shell:AppsFolder\\Claude_pzs8sxrjxfjjc!Claude"]
    assert calls["env"] == {"A": "1"}
    assert calls["creationflags"] == windows._NO_WINDOW


def test_launch_direct_runs_exe(monkeypatch):
    calls = {}
    monkeypatch.setattr(windows.subprocess, "Popen",
                        lambda argv, env=None, creationflags=0: calls.update(
                            argv=argv, env=env, creationflags=creationflags))
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=True,
                   launch_target=r"C:\Apps\Claude.exe", match_root=r"C:\Apps\Claude.exe")
    be.launch(st, {})
    assert calls["argv"] == [r"C:\Apps\Claude.exe"]
    assert calls["creationflags"] == windows._NO_WINDOW


def test_is_running_and_stop_delegate_to_base(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        base_mod, "any_process_under",
        lambda roots, ignored_names=None: seen.setdefault("run", (roots, ignored_names)) or True,
    )
    monkeypatch.setattr(
        base_mod, "stop_processes_under",
        lambda roots, ignored_names=None: seen.setdefault("stop", (roots, ignored_names)),
    )
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, match_root=r"C:\Apps\Claude")
    assert be.is_running(st) is True
    be.stop(st)
    assert seen["run"] == ([r"C:\Apps\Claude"], ("cowork-svc.exe",))
    assert seen["stop"] == ([r"C:\Apps\Claude"], ("cowork-svc.exe",))


def test_is_running_ignores_claude_background_service(monkeypatch):
    root = r"C:\Program Files\WindowsApps\Claude_1.0_x64__pzs8sxrjxfjjc"
    proc = FakeProc(root + r"\app\resources\cowork-svc.exe")
    monkeypatch.setattr(base_mod, "psutil", FakePsutil([proc]))

    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="Claude_pzs8sxrjxfjjc!Claude", match_root=root)

    assert be.is_running(st) is False


def test_create_shortcut_idempotent_when_exists(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "Claude China.lnk").write_text("x")
    monkeypatch.setattr(windows.os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))

    def boom(*a, **k):
        raise AssertionError("should not shell out when shortcut exists")
    monkeypatch.setattr(windows.subprocess, "run", boom)

    be = windows.WindowsBackend()
    path = be.create_shortcut()
    assert path == str(desktop / "Claude China.lnk")


def test_remove_shortcut_reports_paths(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    lnk = desktop / "Claude China.lnk"
    lnk.write_text("x")
    monkeypatch.setattr(windows.os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    monkeypatch.delenv("APPDATA", raising=False)

    be = windows.WindowsBackend()
    removed = be.remove_shortcut()
    assert str(lnk) in removed
    assert not lnk.exists()
    # second call: nothing to remove
    assert be.remove_shortcut() == []


def test_create_shortcut_quotes_paths_for_powershell(monkeypatch, tmp_path):
    # Fresh (non-existent) shortcut path with a PowerShell-hostile '$' in it:
    # the generated script must single-quote it, not double-quote it.
    home = tmp_path / "dev$x"
    home.mkdir()
    monkeypatch.setattr(windows.os.path, "expanduser",
                        lambda p: str(home) if p == "~" else p)
    monkeypatch.delenv("APPDATA", raising=False)
    # No icon on disk -> IconLocation line omitted.
    monkeypatch.setattr(windows.WindowsBackend, "_icon_path", lambda self: r"C:\nope\icon.ico")

    captured = {}
    monkeypatch.setattr(windows.subprocess, "run",
                        lambda argv, check=False, creationflags=0: captured.update(
                            argv=argv, creationflags=creationflags))

    be = windows.WindowsBackend()
    path = be.create_shortcut()

    expected_lnk = str(home / "Desktop" / "Claude China.lnk")
    assert path == expected_lnk
    script = captured["argv"][-1]
    # The hostile path is single-quoted (literal), never double-quoted.
    assert f"CreateShortcut('{expected_lnk}')" in script
    assert f'CreateShortcut("{expected_lnk}")' not in script
    assert "$s.TargetPath = '" in script
    assert captured["creationflags"] == windows._NO_WINDOW


@pytest.mark.parametrize("env_name", ["CLAUDEC_DESKTOP_PYTHON", "CODE_AI_DESKTOP_PYTHON"])
def test_create_shortcut_uses_desktop_python_env(monkeypatch, tmp_path, env_name):
    home = tmp_path / "home"
    home.mkdir()
    pyhome = tmp_path / "py312"
    pyhome.mkdir()
    python = pyhome / "python.exe"
    pythonw = pyhome / "pythonw.exe"
    python.write_text("x")
    pythonw.write_text("x")
    monkeypatch.delenv("CLAUDEC_DESKTOP_PYTHON", raising=False)
    monkeypatch.delenv("CODE_AI_DESKTOP_PYTHON", raising=False)
    monkeypatch.setenv(env_name, str(python))
    monkeypatch.setattr(windows.os.path, "expanduser",
                        lambda p: str(home) if p == "~" else p)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(windows.WindowsBackend, "_icon_path", lambda self: r"C:\nope\icon.ico")

    captured = {}
    monkeypatch.setattr(windows.subprocess, "run",
                        lambda argv, check=False, creationflags=0: captured.update(
                            argv=argv, creationflags=creationflags))

    be = windows.WindowsBackend()
    be.create_shortcut()

    script = captured["argv"][-1]
    assert f"$s.TargetPath = '{pythonw}'" in script


def _make_fake_msix(tmp_path, app_id="Claude", exe_rel="app\\Claude.exe"):
    """Create a fake MSIX InstallLocation: an AppxManifest.xml + on-disk exe.

    Mirrors a real package: <Application Id=... Executable=...> under a default
    appx namespace, with the executable physically present so resolution checks
    os.path.exists.
    """
    parts = exe_rel.replace("\\", "/").split("/")
    exe_dir = tmp_path.joinpath(*parts[:-1]) if len(parts) > 1 else tmp_path
    exe_dir.mkdir(parents=True, exist_ok=True)
    exe = tmp_path.joinpath(*parts)
    exe.write_text("x")
    manifest = tmp_path / "AppxManifest.xml"
    manifest.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">\n'
        '  <Applications>\n'
        f'    <Application Id="{app_id}" Executable="{exe_rel}" />\n'
        '  </Applications>\n'
        '</Package>\n',
        encoding="utf-8",
    )
    return str(exe)


def test_resolve_exe_reads_manifest(tmp_path):
    exe = _make_fake_msix(tmp_path, app_id="Claude", exe_rel="app\\Claude.exe")
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="Claude_pzs8sxrjxfjjc!Claude",
                   match_root=str(tmp_path))
    assert be._resolve_exe(st) == exe


def test_resolve_exe_handles_forward_slash_executable(tmp_path):
    # Codex's real manifest uses a forward slash: "app/Codex.exe".
    exe = _make_fake_msix(tmp_path, app_id="App", exe_rel="app/Codex.exe")
    be = windows.WindowsBackend()
    st = AppStatus("codex", found=True, direct=False,
                   launch_target="OpenAI.Codex_2p2nqsd0c76g0!App",
                   match_root=str(tmp_path))
    assert be._resolve_exe(st) == exe


def test_resolve_exe_none_when_install_root_absent(tmp_path):
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="Claude_pzs8sxrjxfjjc!Claude",
                   match_root=str(tmp_path / "does-not-exist"))
    assert be._resolve_exe(st) is None


def test_resolve_exe_none_when_exe_missing(tmp_path):
    # Manifest present but the referenced executable is not on disk.
    manifest = tmp_path / "AppxManifest.xml"
    manifest.write_text(
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        '<Applications><Application Id="Claude" Executable="app\\Claude.exe"/></Applications>'
        '</Package>',
        encoding="utf-8",
    )
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="Claude_pzs8sxrjxfjjc!Claude",
                   match_root=str(tmp_path))
    assert be._resolve_exe(st) is None


def test_resolve_exe_rejects_dtd_manifest(tmp_path):
    # Defense-in-depth: a manifest carrying a DOCTYPE/entity (the XXE /
    # billion-laughs vector) must be refused, so resolution returns None and
    # the launch falls back to the broker rather than parsing hostile XML.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "Claude.exe").write_text("x")
    (tmp_path / "AppxManifest.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE Package [<!ENTITY a "AA"><!ENTITY b "&a;&a;">]>\n'
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        '<Applications><Application Id="Claude" Executable="app\\Claude.exe"/></Applications>'
        '</Package>',
        encoding="utf-8",
    )
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="Claude_pzs8sxrjxfjjc!Claude",
                   match_root=str(tmp_path))
    assert be._resolve_exe(st) is None


def test_launch_brokered_prefers_real_exe_so_env_propagates(monkeypatch, tmp_path):
    # The core bug fix: a brokered (MSIX) app must launch via its real exe as a
    # child process so injected env actually reaches it — NOT via explorer.exe,
    # whose shell activation runs the app under a broker that strips the env.
    exe = _make_fake_msix(tmp_path, app_id="Claude", exe_rel="app\\Claude.exe")
    calls = {}
    monkeypatch.setattr(windows.subprocess, "Popen",
                        lambda argv, env=None, creationflags=0: calls.update(
                            argv=argv, env=env, creationflags=creationflags))
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="Claude_pzs8sxrjxfjjc!Claude",
                   match_root=str(tmp_path))
    be.launch(st, {"INJECTED": "1"})
    assert calls["argv"] == [exe]
    assert calls["env"] == {"INJECTED": "1"}
    assert calls["creationflags"] == windows._NO_WINDOW


def test_launch_codex_uses_broker_to_preserve_msix_context(monkeypatch, tmp_path):
    _make_fake_msix(tmp_path, app_id="App", exe_rel="app\\Codex.exe")
    calls = {}
    monkeypatch.setattr(windows.subprocess, "Popen",
                        lambda argv, env=None, creationflags=0: calls.update(
                            argv=argv, env=env, creationflags=creationflags))
    be = windows.WindowsBackend()
    st = AppStatus("codex", found=True, direct=False,
                   launch_target="OpenAI.Codex_2p2nqsd0c76g0!App",
                   match_root=str(tmp_path))
    be.launch(st, {"INJECTED": "1"})
    assert calls["argv"] == [
        "explorer.exe",
        "shell:AppsFolder\\OpenAI.Codex_2p2nqsd0c76g0!App",
    ]
    assert calls["env"] == {"INJECTED": "1"}
    assert calls["creationflags"] == windows._NO_WINDOW


def test_launch_brokered_falls_back_to_explorer_on_popen_oserror(monkeypatch, tmp_path):
    # The exe resolves, but launching it raises OSError (e.g. a TOCTOU delete
    # or permission denial between the isfile check and Popen). launch must
    # swallow that and fall back to the broker rather than propagate.
    exe = _make_fake_msix(tmp_path, app_id="Claude", exe_rel="app\\Claude.exe")
    popen_calls = []

    def fake_popen(argv, env=None, creationflags=0):
        popen_calls.append(argv)
        if argv[0] == exe:
            raise OSError("permission denied")

    monkeypatch.setattr(windows.subprocess, "Popen", fake_popen)
    be = windows.WindowsBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="Claude_pzs8sxrjxfjjc!Claude",
                   match_root=str(tmp_path))
    be.launch(st, {"A": "1"})
    assert popen_calls[0] == [exe]  # tried the real exe first
    assert popen_calls[-1] == ["explorer.exe", "shell:AppsFolder\\Claude_pzs8sxrjxfjjc!Claude"]


def test_create_shortcut_sets_packaged_icon(monkeypatch, tmp_path):
    home = tmp_path
    (home / "Desktop").mkdir()
    monkeypatch.setattr(windows.os.path, "expanduser",
                        lambda p: str(home) if p == "~" else p)
    monkeypatch.delenv("APPDATA", raising=False)

    captured = {}
    monkeypatch.setattr(windows.subprocess, "run",
                        lambda argv, check=False, creationflags=0: captured.update(
                            argv=argv, creationflags=creationflags))

    be = windows.WindowsBackend()
    be.create_shortcut()

    script = captured["argv"][-1]
    assert "$s.IconLocation = " in script
    assert be._icon_path() in script
