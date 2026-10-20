import pathlib
import sys

from .apps import APP_REGISTRY
from .bridge import LauncherBridge
from .platforms import get_backend
from .platforms.windows_shell import launcher_icon_path, set_process_app_id as _set_windows_app_id
from .single_instance import DesktopInstance
from .tray import LauncherTray
from .updates import UpdateManager


def _ui_asset_path(name: str) -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent / "ui" / name


def _ui_url() -> str:
    # Resolve the UI relative to this module's own file so it works whether the
    # package is installed as a wheel, run from source, or used in a worktree
    # (importlib.resources("claude_china.desktop") can resolve to a different installed
    # copy that lacks the desktop subpackage — the source-vs-installed gotcha).
    # Return a file:// URI so pywebview renders the page and resolves the relative
    # style.css / app.js links across platforms.
    index = _ui_asset_path("index.html")
    return index.as_uri()


def _window_icon_path() -> str:
    if sys.platform == "win32":
        return launcher_icon_path()
    return str(_ui_asset_path("icon.png"))


def run_gui(smoke_report=None):
    """Open the launcher window. Imports webview lazily (optional [desktop] extra)."""
    backend = get_backend()
    if backend is None:
        print("Claude China desktop supports Windows, macOS and Linux.")
        return

    with DesktopInstance() as instance:
        if not instance.acquire_or_activate():
            return

        if sys.platform == "win32":
            # Set before pywebview/pystray create any native windows. Otherwise
            # the taskbar can reuse the Python host's identity and cached icon.
            _set_windows_app_id()

        import webview  # lazy: only needed to actually show the GUI

        bridge = LauncherBridge(backend, APP_REGISTRY)
        # The page fits the window to its content once loaded (bridge.fit_window);
        # this is just a close first guess so the window does not visibly jump.
        window = webview.create_window(
            "Claude China", url=_ui_url(), js_api=bridge, width=600, height=340,
            **({"hidden": True} if smoke_report else {}),
        )
        try:
            screen_height = int(webview.screens[0].height)
        except Exception:  # headless / unknown screen: fit_window skips clamping
            screen_height = None
        bridge._attach_window(window, webview.OPEN_DIALOG, screen_height=screen_height)
        tray = LauncherTray(window, _ui_asset_path("icon.png"))
        bridge._activity = tray.play_activity
        updater = UpdateManager(lambda: tray._quit(None, None))
        bridge._updater = updater
        try:
            tray.start()
            callback = instance.listen
            arguments = (window, tray.play_activity)
            if smoke_report:
                from .smoke import verify_window
                callback = verify_window
                arguments = (window, tray, smoke_report)
            webview.start(
                func=callback, args=arguments, icon=_window_icon_path(),
            )
        finally:
            updater.shutdown()
            tray.stop()
