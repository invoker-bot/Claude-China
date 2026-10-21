"""Packaged GUI verification, used by the release build on each target OS."""

import json
import os
import sys
import threading
import time

from .. import __version__
from .apps import APP_REGISTRY


def _wait_js(window, expression):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if window.evaluate_js(expression):
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for packaged UI: " + expression)


def _verify_platform_menu(window):
    """Check the native menu policy on the GUI thread; exercise macOS Settings."""
    done = threading.Event()
    errors = []

    def verify():
        try:
            if sys.platform == "win32":
                if any(control.GetType().Name == "MenuStrip"
                       for control in window.native.Controls):
                    raise RuntimeError("Windows must not show a native menu bar")
            elif sys.platform == "darwin":
                from AppKit import NSApplication
                app = NSApplication.sharedApplication()
                menu = app.mainMenu().itemAtIndex_(0).submenu()
                item = next(item for item in menu.itemArray() if item.title() == "设置…")
                if not app.sendAction_to_from_(item.action(), item.target(), item):
                    raise RuntimeError("macOS did not dispatch the Settings menu action")
            else:
                app = window.native.get_application()
                if app.get_menubar() is not None:
                    raise RuntimeError("Linux must not show a native menu bar")
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    if sys.platform == "win32":
        from System import Action
        window.native.Invoke(Action(verify))
    elif sys.platform == "darwin":
        from PyObjCTools import AppHelper
        AppHelper.callAfter(verify)
    else:
        from gi.repository import GLib
        GLib.idle_add(verify)
    if not done.wait(10):
        raise RuntimeError("Native menu verification timed out")
    if errors:
        raise errors[0]
    if sys.platform == "darwin":
        _wait_js(window, "document.getElementById('editor-common').classList.contains('is-open')")


def _verify_settings_tabs(window):
    """Settings behaves like a peer page and preserves drafts across navigation."""
    window.evaluate_js("document.getElementById('open-settings').click()")
    if not window.evaluate_js("""
        document.getElementById('open-settings').getAttribute('aria-current') === 'page'
        && !document.getElementById('home-button').inert
        && !document.getElementById('terminals-button').inert
        && document.getElementById('launcher-main').hidden
        && !document.querySelector('#launcher-overlay, #dialog-close')
    """):
        raise RuntimeError('Settings still opens a blocking dialog instead of a main navigation page')
    window.evaluate_js("document.getElementById('auto-proxy-env').click(); document.getElementById('nav-safety').click()")
    window.evaluate_js("document.getElementById('terminals-button').click()")
    _wait_js(window, "!TERMINAL_LOADING && !document.getElementById('terminals-main').hidden")
    window.evaluate_js("document.getElementById('home-button').click(); document.getElementById('open-settings').click()")
    if not window.evaluate_js("""
        !document.getElementById('settings-main').hidden
        && !document.getElementById('editor-safety').hidden
        && document.getElementById('auto-proxy-env').checked !== SETTINGS.auto_proxy_env
        && hasUnsavedSettings()
    """):
        raise RuntimeError('Tab navigation lost the settings category or unsaved draft')
    window.evaluate_js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    if not window.evaluate_js("!document.getElementById('settings-main').hidden"):
        raise RuntimeError('Escape still dismisses the settings page as a dialog')
    window.evaluate_js("document.getElementById('nav-common').click(); document.getElementById('cancel-common').click()")
    if not window.evaluate_js("!hasUnsavedSettings() && !document.getElementById('settings-main').hidden"):
        raise RuntimeError('Cancel must restore settings without leaving the page')
    window.evaluate_js("document.getElementById('home-button').click()")


def _verify_terminal_profiles(window):
    """Use the smoke entry point's isolated store, never real CLI credentials."""
    from .. import config as cli_config
    window.evaluate_js("document.getElementById('terminals-button').click()")
    _wait_js(window, "!TERMINAL_LOADING && !document.getElementById('terminals-main').hidden")
    if cli_config.load_config()['profiles']:
        raise RuntimeError('Terminal smoke store was not isolated')
    window.evaluate_js("document.getElementById('new-cli-profile').click()")
    window.evaluate_js("""
        document.getElementById('cli-name').value = 'smoke-terminal';
        document.getElementById('cli-secret').value = 'isolated-smoke-credential';
        document.getElementById('cli-profile-form').requestSubmit();
    """)
    _wait_js(window, "!CLI_SAVING && !TERMINAL_LOADING && TERMINALS.profiles.length === 1")
    window.evaluate_js("document.querySelector('[data-cli-action=edit]').click()")
    _wait_js(window, "document.getElementById('cli-profile-dialog').open")
    if not window.evaluate_js("document.getElementById('cli-secret').value === ''"):
        raise RuntimeError('The profile editor exposed a stored credential')
    window.evaluate_js("""
        document.getElementById('cli-name').value = 'smoke-renamed';
        document.getElementById('cli-profile-form').requestSubmit();
    """)
    _wait_js(window, "!CLI_SAVING && !TERMINAL_LOADING && TERMINALS.profiles[0].name === 'smoke-renamed'")
    profile = cli_config.load_config()['profiles']['smoke-renamed']
    if profile.get('token') != 'isolated-smoke-credential':
        raise RuntimeError('Editing a CLI profile lost the stored credential')
    window.evaluate_js("document.querySelector('[data-cli-action=copy]').click()")
    _wait_js(window, "!TERMINAL_LOADING && TERMINALS.profiles.length === 2")
    window.evaluate_js("document.querySelectorAll('[data-cli-action=delete]')[1].click()")
    _wait_js(window, "document.getElementById('cli-profile-dialog').open")
    window.evaluate_js("document.getElementById('cli-profile-form').requestSubmit()")
    _wait_js(window, "!CLI_SAVING && !TERMINAL_LOADING && TERMINALS.profiles.length === 1")
    if len(cli_config.load_config()['profiles']) != 1:
        raise RuntimeError('The desktop and CLI profile stores diverged')
    window.evaluate_js("document.getElementById('home-button').click()")
    if not window.evaluate_js("!document.getElementById('launcher-main').hidden"):
        raise RuntimeError('Cannot return from My Terminals to My Apps')


def verify_window(window, tray, report):
    result = {"ok": False, "version": __version__, "platform": sys.platform,
              "frozen": bool(getattr(sys, "frozen", False)), "pid": os.getpid()}
    try:
        if not window.events.loaded.wait(30):
            raise RuntimeError("The bundled UI did not load within 30 seconds")
        _wait_js(window, "typeof READY !== 'undefined' && READY")
        _verify_settings_tabs(window)
        result["settings_tab_navigation"] = True
        _wait_js(window, """Array.from(document.querySelectorAll('.bay--app')).every(bay => {
            const appId = bay.id.slice(4);
            const logos = document.querySelectorAll(
                `#${bay.id} .app-symbol img, #nav-${appId} .nav-app-symbol img`);
            return logos.length === 2 && Array.from(logos).every(img =>
                img.getAttribute('src') === `${appId}.png` && img.naturalWidth > 0
                && getComputedStyle(img).filter === 'none');
        })""")
        result.update(window.evaluate_js("""({
            title: document.title,
            cards: document.querySelectorAll('.bay--app').length,
            apps: Array.from(document.querySelectorAll('.bay--app'), bay => bay.id),
            icon_loaded: document.getElementById('brand-mark').naturalWidth > 0,
            app_icons_loaded: true,
            stylesheet: document.styleSheets.length > 0,
            update_hidden: document.getElementById('settings-main').hidden,
            update_version: document.getElementById('update-version').textContent,
            update_action: document.getElementById('update-action').textContent
        })"""))
        if (result["title"] != "Claude China" or result["cards"] != len(APP_REGISTRY)
                or result["apps"] != ["bay-" + app.id for app in APP_REGISTRY]
                or not result["icon_loaded"] or not result["stylesheet"]
                or not result["update_hidden"]
                or result["update_version"] != "v" + __version__
                or result["update_action"] != "检查更新"):
            raise RuntimeError("The packaged UI is incomplete")
        result["integrated_titlebar"] = window.evaluate_js(
            "document.body.classList.contains('custom-titlebar')"
            " && !document.getElementById('window-controls').hidden")
        if result["integrated_titlebar"] != (sys.platform != "darwin"):
            raise RuntimeError("Wrong platform titlebar policy")
        if sys.platform == "win32":
            import ctypes
            from System import Action
            from System.Windows.Forms import FormWindowState

            frame = []
            def inspect_frame():
                get_style = ctypes.WinDLL("user32").GetWindowLongPtrW
                get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
                get_style.restype = ctypes.c_ssize_t
                style = get_style(window.native.Handle.ToInt64(), -16)
                frame.append(bool(style & 0x00040000) and not bool(style & 0x00C00000)
                             and window.native.Padding.Left > 0)
            window.native.Invoke(Action(inspect_frame))
            if frame != [True]:
                raise RuntimeError("Borderless Windows frame lost native edge resizing")
            result["native_resize_frame"] = True

            def check_native(expected):
                state = []
                window.native.Invoke(Action(lambda: state.append(window.native.WindowState)))
                if state != [expected]:
                    raise RuntimeError("Window button did not change the native window state")

            window.evaluate_js("document.getElementById('window-maximize').click()")
            _wait_js(window, "!windowActionPending && document.body.classList.contains('is-maximized')")
            check_native(FormWindowState.Maximized)
            window.evaluate_js("document.getElementById('window-maximize').click()")
            _wait_js(window, "!windowActionPending && !document.body.classList.contains('is-maximized')")
            check_native(FormWindowState.Normal)
            window.evaluate_js("document.getElementById('window-minimize').click()")
            _wait_js(window, "!windowActionPending")
            check_native(FormWindowState.Minimized)
            window.restore()
            window.hide()
            result["native_window_buttons"] = True
        window.evaluate_js("document.getElementById('gear-grok-bot').click()")
        _wait_js(window, "document.getElementById('editor-grok-bot').classList.contains('is-open')")
        result["grok_bot_settings"] = window.evaluate_js(
            "document.getElementById('open-settings').getAttribute('aria-current') === 'page'"
            " && !document.getElementById('editor-grok-bot').inert"
            " && !!document.getElementById('env-grok-bot')"
            " && !!document.getElementById('pick-grok-bot')"
            " && !document.getElementById('settings-main').hidden"
            " && document.getElementById('nav-grok-bot').getAttribute('aria-current') === 'page'")
        window.evaluate_js("document.getElementById('cancel-grok-bot').click()")
        # Exercise the shared menu dispatch against the actual packaged webview,
        # without a network request or changing any saved settings.
        tray._commands._dispatch("update-status")
        result["menu_settings_page"] = window.evaluate_js(
            "!document.getElementById('settings-main').hidden"
            " && !document.getElementById('update-panel').hidden")
        window.evaluate_js("setMainView('apps')")
        _verify_platform_menu(window)
        result["platform_menu"] = True
        if sys.platform != "darwin":
            window.evaluate_js("document.getElementById('gear-common').click()")
            _wait_js(window, "document.getElementById('editor-common').classList.contains('is-open')")
        result["settings_entry"] = True
        if sys.platform != "darwin":
            result["window_controls_with_settings"] = window.evaluate_js("""(() => {
                const button = document.getElementById('window-close');
                const bounds = button.getBoundingClientRect();
                return !button.closest('[inert]') && button.contains(document.elementFromPoint(
                    bounds.x + bounds.width / 2, bounds.y + bounds.height / 2));
            })()""")
            if not result["window_controls_with_settings"]:
                raise RuntimeError("Settings blocks the native window controls")
        # Toggle ONLY the new setting, so a missing draft field cannot be
        # masked by changes to the older check-system-proxy switch.
        window.evaluate_js("document.getElementById('auto-proxy-env').click()")
        result["auto_proxy_default_off"] = window.evaluate_js(
            "SETTINGS.auto_proxy_env === false && document.getElementById('auto-proxy-env').checked")
        tray._commands._dispatch("settings")
        result["menu_preserves_edits"] = window.evaluate_js(
            "document.getElementById('editor-common').classList.contains('is-open')"
            " && document.getElementById('auto-proxy-env').checked !== SETTINGS.auto_proxy_env")
        window.evaluate_js("document.getElementById('nav-grok-bot').click()")
        window.evaluate_js("document.getElementById('nav-common').click()")
        result["category_preserves_edits"] = window.evaluate_js(
            "document.getElementById('editor-common').classList.contains('is-open')"
            " && hasUnsavedSettings()"
            " && document.getElementById('auto-proxy-env').checked !== SETTINGS.auto_proxy_env")
        tray._commands._dispatch("update-status")
        _wait_js(window, "!openingUpdates")
        # A prepared update must not bypass the unsaved-settings guard just
        # because it was opened from a native menu instead of the page.
        window.evaluate_js("renderUpdate({...UPDATE, phase: 'ready', can_install: true}); updateAction()")
        result["restart_guard"] = window.evaluate_js(
            "!document.getElementById('update-warning').hidden")
        window.evaluate_js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
        result["escape_keeps_settings_page"] = window.evaluate_js(
            "!document.getElementById('settings-main').hidden"
            " && hasUnsavedSettings()"
            " && document.getElementById('auto-proxy-env').checked !== SETTINGS.auto_proxy_env")
        tray._commands._dispatch("settings")
        result["reopen_preserves_edits"] = window.evaluate_js(
            "document.getElementById('editor-common').classList.contains('is-open')"
            " && document.getElementById('auto-proxy-env').checked !== SETTINGS.auto_proxy_env")
        window.evaluate_js("document.getElementById('cancel-common').click()")
        result["cancel_restores_settings"] = window.evaluate_js(
            "!document.getElementById('settings-main').hidden"
            " && !hasUnsavedSettings()"
            " && document.getElementById('auto-proxy-env').checked === SETTINGS.auto_proxy_env")
        tray._commands._dispatch("settings")
        window.evaluate_js("document.getElementById('auto-proxy-env').click(); document.getElementById('save-settings').click()")
        _wait_js(window, "SETTINGS.auto_proxy_env === true && !hasUnsavedSettings()")
        from . import config
        result["auto_proxy_saved"] = config.get_auto_proxy_env(config.load_desktop_config())
        window.evaluate_js("setMainView('apps')")
        tray._commands._dispatch("settings")
        # GTK's evaluate_javascript length counts characters instead of UTF-8
        # bytes in pywebview 6.2.1; keep injected scripts ASCII on that backend.
        result["auto_proxy_reopened"] = window.evaluate_js(
            "document.getElementById('auto-proxy-env').checked"
            " && document.getElementById('common-summary').textContent.includes("
            + json.dumps("自动添加代理环境变量") + ")")
        window.evaluate_js("document.getElementById('nav-safety').click()")
        result["safety_settings"] = window.evaluate_js(
            "!document.getElementById('editor-safety').hidden"
            " && document.getElementById('safety-enabled').checked"
            " && document.getElementById('safety-strict').checked"
            " && document.querySelectorAll('#safety-local dd').length === 3"
            " && document.getElementById('safety-blocked-regions').textContent.includes('HK')"
            " && document.getElementById('safety-blocked-regions').textContent.includes('MO')"
            " && document.getElementById('safety-blocked-regions').textContent.includes('KP')"
            " && document.getElementById('safety-app').options.length === 3")
        window.evaluate_js("document.getElementById('safety-strict').click(); setMainView('terminals'); showSettings('safety')")
        result["safety_draft_preserved"] = window.evaluate_js(
            "hasUnsavedSettings() && !document.getElementById('safety-strict').checked")
        window.evaluate_js("document.getElementById('cancel-safety').click(); showSettings('safety')")
        result["safety_cancel_restored"] = window.evaluate_js(
            "!hasUnsavedSettings() && document.getElementById('safety-strict').checked")
        window.evaluate_js("document.getElementById('safety-strict').click(); document.getElementById('save-safety').click()")
        _wait_js(window, "!SAFETY_SETTINGS.block_unknown && !hasUnsavedSettings()")
        result["safety_saved"] = not config.get_safety_settings(config.load_desktop_config())["block_unknown"]
        # Render a deterministic blocked result; GUI smoke never calls an IP
        # service or launches/stops any of the user's real apps.
        window.evaluate_js("rememberSafetyReport('claude', {status:'unsupported', reason:'Test blocked region', network:{country_code:'CN'}})")
        result["safety_blocked_display"] = window.evaluate_js(
            "document.getElementById('safety-result').dataset.status === 'unsupported'")
        _verify_terminal_profiles(window)
        result["terminal_profile_crud"] = True
        if not all(result[key] for key in (
            "grok_bot_settings", "menu_settings_page", "menu_preserves_edits",
            "category_preserves_edits", "restart_guard", "escape_keeps_settings_page",
            "reopen_preserves_edits", "cancel_restores_settings",
            "auto_proxy_default_off", "auto_proxy_saved", "auto_proxy_reopened",
            "safety_settings", "safety_draft_preserved", "safety_cancel_restored",
            "safety_saved", "safety_blocked_display",
        )):
            raise RuntimeError("Native menu commands did not reach the packaged UI")
        if sys.platform == "darwin":
            result["native_quit_bound"] = tray._commands._macos_quit_bound
            if not result["native_quit_bound"]:
                raise RuntimeError("The macOS Quit menu still hides the window instead of exiting")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        tray._quit(None, None)
