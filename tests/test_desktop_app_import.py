import inspect
import sys
import types

import pytest

import src.claude_china.desktop.app as app_mod
from src.claude_china.desktop.platforms.base import AppStatus


def test_app_module_imports_without_webview():
    # app.py must be importable with no [desktop] extra installed:
    # webview is imported only inside run_gui().
    assert hasattr(app_mod, "run_gui")


def test_ui_assets_are_packaged():
    # Anchor on the module's own location (robust regardless of how the
    # editable install registers subpackages); reads the real source tree.
    from pathlib import Path
    ui = Path(app_mod.__file__).parent / "ui"
    assert (ui / "index.html").is_file()
    assert (ui / "style.css").is_file()
    assert (ui / "app.js").is_file()


def test_ui_lists_launch_and_stop_actions_without_status_push_hook():
    from pathlib import Path
    script = (Path(app_mod.__file__).parent / "ui" / "app.js").read_text(encoding="utf-8")

    assert 'onAction(a.id, "launch")' in script
    assert 'onAction(a.id, "stop")' in script
    assert "window.updateStatus" not in script


def test_ui_url_is_file_uri():
    # pywebview must receive a file:// URI (not a bare OS path) so the window
    # actually renders and relative asset links resolve.
    url = app_mod._ui_url()
    assert url.startswith("file://")
    assert url.endswith("/index.html")


def _pywebview_exposed_functions(obj):
    exposed_objects = []
    functions = set()

    def walk(current, base_name=""):
        obj_id = id(current)
        if obj_id in exposed_objects:
            return
        exposed_objects.append(obj_id)

        for name in dir(current):
            if name.startswith("_"):
                continue
            full_name = f"{base_name}.{name}" if base_name else name
            attr = getattr(current, name)
            if not getattr(attr, "_serializable", True):
                continue
            if inspect.ismethod(attr) or inspect.isfunction(attr):
                functions.add(full_name)
            elif inspect.isclass(attr) or (
                isinstance(attr, object) and not callable(attr) and hasattr(attr, "__module__")
            ):
                walk(attr, full_name)

    walk(obj)
    return functions


class _FakeBackend:
    def detect(self, app, override):
        return AppStatus(app.id, found=True, direct=False, launch_target="t", match_root="r")

    def launch(self, status, env):
        pass

    def is_running(self, status):
        return False

    def stop(self, status):
        pass

    def proxy_enabled(self):
        return True

    def pick_path_filter(self):
        return ("*",)


class _FakeWindow:
    class _Event:
        def __init__(self):
            self.items = []

        def __iadd__(self, item):
            self.items.append(item)
            return self

    def __init__(self):
        self.events = types.SimpleNamespace(shown=self._Event(), closing=self._Event())

    def create_file_dialog(self, *args, **kwargs):
        return []


@pytest.fixture
def fake_tray(monkeypatch):
    calls = []
    monkeypatch.setattr(app_mod, "_set_windows_app_id", lambda: None)

    class FakeTray:
        def __init__(self, window, icon_path):
            calls.append(("create", window, icon_path))

        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

        def play_activity(self):
            calls.append("activity")

    monkeypatch.setattr(app_mod, "LauncherTray", FakeTray, raising=False)
    return calls


def test_run_gui_keeps_tray_until_gui_exits(monkeypatch, tmp_path, fake_tray):
    window = _FakeWindow()

    def start(**kwargs):
        assert fake_tray[-1] == "start"
        assert callable(kwargs["func"])
        fake_tray.append("gui")

    monkeypatch.setattr(app_mod, "get_backend", lambda: _FakeBackend())
    monkeypatch.setattr(
        "src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml",
    )
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(
        create_window=lambda *args, **kwargs: window, OPEN_DIALOG=20, start=start,
    ))

    app_mod.run_gui()

    assert fake_tray[0][0:2] == ("create", window)
    assert fake_tray[0][2].name == "icon.png"
    assert fake_tray[1:] == ["start", "gui", "stop"]


def test_windows_identity_is_set_before_creating_any_window(monkeypatch, tmp_path, fake_tray):
    calls = []
    monkeypatch.setattr(app_mod, "_set_windows_app_id",
                        lambda: calls.append("identity"), raising=False)
    monkeypatch.setattr(app_mod, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(app_mod, "get_backend", lambda: _FakeBackend())
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
                        tmp_path / "desktop.yaml")

    def create_window(*args, **kwargs):
        assert calls == ["identity"]
        calls.append("window")
        return _FakeWindow()

    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(
        create_window=create_window, OPEN_DIALOG=20, start=lambda **kwargs: None,
    ))
    app_mod.run_gui()
    assert calls == ["identity", "window"]


def test_macos_does_not_initialize_windows_shell(monkeypatch, tmp_path, fake_tray):
    def fail():
        pytest.fail("macOS must not call a Windows Shell API")

    captured = {}
    monkeypatch.setattr(app_mod, "_set_windows_app_id", fail)
    monkeypatch.setattr(app_mod, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(app_mod, "get_backend", lambda: _FakeBackend())
    monkeypatch.setattr("src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
                        tmp_path / "desktop.yaml")
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(
        create_window=lambda *args, **kwargs: _FakeWindow(),
        OPEN_DIALOG=20, start=lambda **kwargs: captured.update(kwargs),
    ))
    app_mod.run_gui()
    assert captured["icon"].endswith("icon.png")


def test_repeated_run_activates_existing_window_without_creating_another(monkeypatch, tmp_path):
    calls = []

    class ExistingInstance:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append("closed")

        def acquire_or_activate(self):
            calls.append("activated")
            return False

    def create_window(*args, **kwargs):
        pytest.fail("a repeated launch must not create a second window")

    monkeypatch.setattr(app_mod, "DesktopInstance", ExistingInstance, raising=False)
    monkeypatch.setattr(app_mod, "get_backend", lambda: _FakeBackend())
    monkeypatch.setattr(
        "src.claude_china.desktop.config.DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml",
    )
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(
        create_window=create_window,
    ))

    app_mod.run_gui()

    assert calls == ["activated", "closed"]


def test_run_gui_exposes_only_js_api_methods_to_pywebview(monkeypatch, tmp_path, fake_tray):
    captured = {}
    fake_window = _FakeWindow()

    def create_window(title, url, js_api, width, height):
        assert title == "Claude China"
        captured["js_api"] = js_api
        return fake_window

    fake_webview = types.SimpleNamespace(
        OPEN_DIALOG=20,
        create_window=create_window,
        start=lambda **kwargs: captured.update(start_kwargs=kwargs),
    )

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(app_mod, "get_backend", lambda: _FakeBackend())
    monkeypatch.setattr(
        "src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
        tmp_path / "desktop.yaml",
    )
    monkeypatch.setattr(app_mod, "sys", types.SimpleNamespace(platform="win32"))

    app_mod.run_gui()

    from pathlib import Path
    icon = Path(captured["start_kwargs"]["icon"])
    if app_mod.sys.platform == "win32":
        assert icon.name.startswith("launcher-")
        assert icon.suffix == ".ico"
        assert icon.read_bytes() == app_mod._ui_asset_path("icon.ico").read_bytes()
    else:
        assert icon == app_mod._ui_asset_path("icon.png")
    # No `shown` handler may touch the native window. pywebview dispatches shown
    # callbacks on a background thread; mutating a WinForms control (e.g.
    # native.Icon) off the GUI/STA thread issues a cross-thread SendMessage that
    # deadlocks the message pump -> the window hangs "Not Responding". The titlebar
    # icon is set safely via start(icon=) (asserted above), so no handler is needed.
    assert len(fake_window.events.shown.items) == 0
    assert _pywebview_exposed_functions(captured["js_api"]) == {
        "fit_window",
        "get_update_status",
        "check_for_updates",
        "download_update",
        "cancel_update",
        "install_update",
        "open_release_page",
        "get_app_settings",
        "get_settings",
        "launch_app",
        "list_apps",
        "pick_app_path",
        "save_app_settings",
        "save_settings",
        "stop_app",
    }
    # Keep the native animation callback private from the JavaScript API.
    assert captured["js_api"]._activity == captured["start_kwargs"]["args"][1]


def test_run_gui_does_not_start_background_status_poll(monkeypatch, tmp_path, fake_tray):
    captured = {"threads": []}
    fake_window = _FakeWindow()

    def create_window(_title, url, js_api, width, height):
        return fake_window

    class Thread:
        def __init__(self, *args, **kwargs):
            captured["threads"].append((args, kwargs))

        def start(self):
            raise AssertionError("run_gui must not start a background poll thread")

    fake_webview = types.SimpleNamespace(
        OPEN_DIALOG=20,
        create_window=create_window,
        start=lambda **kwargs: captured.update(start_kwargs=kwargs),
    )

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(app_mod, "get_backend", lambda: _FakeBackend())
    monkeypatch.setattr(app_mod, "threading", types.SimpleNamespace(Thread=Thread), raising=False)
    monkeypatch.setattr(
        "src.claude_china.desktop.config.DESKTOP_CONFIG_FILE",
        tmp_path / "desktop.yaml",
    )

    app_mod.run_gui()

    assert captured["threads"] == []
