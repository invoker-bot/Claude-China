from src.claude_china.desktop.apps import get_app
from src.claude_china.desktop.platforms import macos


def test_parse_scutil_enabled():
    text = (
        "<dictionary> {\n"
        "  HTTPEnable : 1\n"
        "  HTTPProxy : 127.0.0.1\n"
        "}\n"
    )
    assert macos.MacBackend._parse_scutil(text) is True


def test_parse_scutil_https_only():
    text = "  HTTPEnable : 0\n  HTTPSEnable : 1\n"
    assert macos.MacBackend._parse_scutil(text) is True


def test_parse_scutil_disabled():
    text = "  HTTPEnable : 0\n  HTTPSEnable : 0\n"
    assert macos.MacBackend._parse_scutil(text) is False


def test_proxy_enabled_uses_scutil_output(monkeypatch):
    be = macos.MacBackend()
    monkeypatch.setattr(be, "_scutil_output", lambda: "HTTPEnable : 1\n")
    assert be.proxy_enabled() is True


def test_detect_brokered_via_find_bundle(monkeypatch):
    be = macos.MacBackend()
    monkeypatch.setattr(be, "_find_bundle", lambda app: "/Applications/Claude.app")
    st = be.detect(get_app("claude"), None)
    assert st.found is True
    assert st.direct is False
    assert st.launch_target == "/Applications/Claude.app"
    assert st.match_root == "/Applications/Claude.app"


def test_detect_not_found(monkeypatch):
    be = macos.MacBackend()
    monkeypatch.setattr(be, "_find_bundle", lambda app: "")
    st = be.detect(get_app("codex"), None)
    assert st.found is False


def test_detect_override_direct(monkeypatch, tmp_path):
    bundle = tmp_path / "Codex.app"
    bundle.mkdir()
    be = macos.MacBackend()
    monkeypatch.setattr(be, "_bundle_binary", lambda b: str(bundle / "Contents/MacOS/Codex"))
    st = be.detect(get_app("codex"), str(bundle))
    assert st.found is True
    assert st.direct is True
    assert st.launch_target == str(bundle / "Contents/MacOS/Codex")
    assert st.match_root == str(bundle)


from src.claude_china.desktop.platforms import base as base_mod
from src.claude_china.desktop.platforms.base import AppStatus


def test_launch_brokered_uses_open_a(monkeypatch):
    calls = {}
    monkeypatch.setattr(macos.subprocess, "Popen",
                        lambda argv, env=None: calls.update(argv=argv, env=env))
    be = macos.MacBackend()
    st = AppStatus("claude", found=True, direct=False,
                   launch_target="/Applications/Claude.app", match_root="/Applications/Claude.app")
    be.launch(st, {"A": "1"})
    assert calls["argv"] == ["open", "-a", "/Applications/Claude.app"]
    assert calls["env"] == {"A": "1"}


def test_launch_direct_runs_binary(monkeypatch):
    calls = {}
    monkeypatch.setattr(macos.subprocess, "Popen",
                        lambda argv, env=None: calls.update(argv=argv, env=env))
    be = macos.MacBackend()
    st = AppStatus("claude", found=True, direct=True,
                   launch_target="/Applications/Claude.app/Contents/MacOS/Claude",
                   match_root="/Applications/Claude.app")
    be.launch(st, {})
    assert calls["argv"] == ["/Applications/Claude.app/Contents/MacOS/Claude"]


def test_is_running_and_stop_delegate_to_base(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        base_mod, "any_process_under",
        lambda roots, ignored_names=None: seen.setdefault("run", (roots, ignored_names)) or True,
    )
    monkeypatch.setattr(base_mod, "stop_processes_under", lambda roots: seen.setdefault("stop", roots))
    be = macos.MacBackend()
    st = AppStatus("claude", found=True, match_root="/Applications/Claude.app")
    assert be.is_running(st) is True
    be.stop(st)
    assert seen["run"] == (["/Applications/Claude.app"], {"browser_crashpad_handler"})
    assert seen["stop"] == ["/Applications/Claude.app"]


def test_create_shortcut_idempotent_when_exists(monkeypatch, tmp_path):
    home = tmp_path
    (home / "Desktop").mkdir()
    appdir = home / "Desktop" / "Claude China.app"
    appdir.mkdir()
    monkeypatch.setattr(macos.os.path, "expanduser",
                        lambda p: p.replace("~", str(home)))

    def boom(*a, **k):
        raise AssertionError("should not shell out when shortcut exists")
    monkeypatch.setattr(macos.subprocess, "run", boom)

    be = macos.MacBackend()
    assert be.create_shortcut() == str(appdir)


def test_remove_shortcut(monkeypatch, tmp_path):
    home = tmp_path
    (home / "Desktop").mkdir()
    appdir = home / "Desktop" / "Claude China.app"
    appdir.mkdir()
    monkeypatch.setattr(macos.os.path, "expanduser",
                        lambda p: p.replace("~", str(home)))
    be = macos.MacBackend()
    removed = be.remove_shortcut()
    assert str(appdir) in removed
    assert not appdir.exists()
    assert be.remove_shortcut() == []


def test_create_shortcut_quotes_python_path_for_shell(monkeypatch, tmp_path):
    # A sys.executable path with a space must be shell-quoted so the macOS
    # `do shell script` /bin/sh layer doesn't word-split it.
    home = tmp_path
    (home / "Desktop").mkdir()
    monkeypatch.setattr(macos.os.path, "expanduser",
                        lambda p: p.replace("~", str(home)))
    monkeypatch.setattr(macos.sys, "executable", "/Users/My Name/venv/bin/python3")

    captured = {}
    monkeypatch.setattr(macos.subprocess, "run",
                        lambda argv, check=False: captured.update(argv=argv))

    be = macos.MacBackend()
    be.create_shortcut()

    # osacompile argv is ["osacompile", "-o", app_path, "-e", script]
    script = captured["argv"][-1]
    assert "'/Users/My Name/venv/bin/python3'" in script   # POSIX single-quoted
    assert script.startswith("do shell script ")


def test_create_shortcut_copies_packaged_icon(monkeypatch, tmp_path):
    home = tmp_path
    (home / "Desktop").mkdir()
    monkeypatch.setattr(macos.os.path, "expanduser",
                        lambda p: p.replace("~", str(home)))

    def fake_run(argv, check=False):
        app_path = argv[argv.index("-o") + 1]
        (tmp_path / "Desktop" / "Claude China.app" /
         "Contents" / "Resources").mkdir(parents=True)
        assert app_path == str(tmp_path / "Desktop" / "Claude China.app")

    monkeypatch.setattr(macos.subprocess, "run", fake_run)

    be = macos.MacBackend()
    app_path = be.create_shortcut()

    applet_icon = tmp_path / "Desktop" / "Claude China.app" / "Contents" / "Resources" / "applet.icns"
    source_icon = macos.importlib.resources.files("claude_china.desktop").joinpath("ui", "icon.icns")
    assert app_path == str(tmp_path / "Desktop" / "Claude China.app")
    assert applet_icon.read_bytes() == source_icon.read_bytes()


def test_shortcut_bundle_uses_claude_china_name_and_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(macos.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    appdir = tmp_path / "Desktop" / "Claude China.app"
    plist = appdir / "Contents" / "Info.plist"

    def compile_applet(argv, check=False):
        assert argv[2] == str(appdir)
        assert "-m claude_china.cli desktop run" in argv[-1]
        plist.parent.mkdir(parents=True)
        with plist.open("wb") as stream:
            macos.plistlib.dump({"CFBundleExecutable": "applet"}, stream)

    monkeypatch.setattr(macos.subprocess, "run", compile_applet)
    assert macos.MacBackend().create_shortcut() == str(appdir)
    with plist.open("rb") as stream:
        info = macos.plistlib.load(stream)
    assert info["CFBundleName"] == info["CFBundleDisplayName"] == "Claude China"
    assert info["CFBundleIdentifier"] == "com.claudechina.launcher"
    assert info["CFBundleExecutable"] == "applet"
