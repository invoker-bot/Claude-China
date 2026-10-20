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


def _activate_native_settings(window):
    """Activate a real menu item on its GUI thread, including GTK action wiring."""
    done = threading.Event()
    errors = []

    def activate():
        try:
            if sys.platform == "win32":
                menu = next(control for control in window.native.Controls
                            if control.GetType().Name == "MenuStrip")
                next(item for item in menu.Items[0].DropDownItems
                     if item.Text == "设置…").PerformClick()
            elif sys.platform == "darwin":
                from AppKit import NSApplication
                app = NSApplication.sharedApplication()
                menu = app.mainMenu().itemAtIndex_(0).submenu()
                item = next(item for item in menu.itemArray() if item.title() == "设置…")
                if not app.sendAction_to_from_(item.action(), item.target(), item):
                    raise RuntimeError("macOS did not dispatch the Settings menu action")
            else:
                app = window.native.get_application()

                def find_action(model):
                    for i in range(model.get_n_items()):
                        label = model.get_item_attribute_value(i, "label", None)
                        if label and label.get_string() == "设置…":
                            return model.get_item_attribute_value(i, "action", None).get_string()
                        for link in ("submenu", "section"):
                            child = model.get_item_link(i, link)
                            if child:
                                action = find_action(child)
                                if action:
                                    return action
                    return None

                action = find_action(app.get_menubar())
                if not action or not action.startswith("app."):
                    raise RuntimeError("GTK Settings menu action is missing")
                app.activate_action(action[4:], None)
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    if sys.platform == "win32":
        from System import Action
        window.native.Invoke(Action(activate))
    elif sys.platform == "darwin":
        from PyObjCTools import AppHelper
        AppHelper.callAfter(activate)
    else:
        from gi.repository import GLib
        GLib.idle_add(activate)
    if not done.wait(10):
        raise RuntimeError("Native menu action timed out")
    if errors:
        raise errors[0]
    _wait_js(window, "document.getElementById('editor-common').classList.contains('is-open')")


def verify_window(window, tray, report):
    result = {"ok": False, "version": __version__, "platform": sys.platform,
              "frozen": bool(getattr(sys, "frozen", False)), "pid": os.getpid()}
    try:
        if not window.events.loaded.wait(30):
            raise RuntimeError("The bundled UI did not load within 30 seconds")
        _wait_js(window, "typeof READY !== 'undefined' && READY")
        result.update(window.evaluate_js("""({
            title: document.title,
            cards: document.querySelectorAll('.bay--app').length,
            apps: Array.from(document.querySelectorAll('.bay--app'), bay => bay.id),
            icon_loaded: document.getElementById('brand-mark').naturalWidth > 0,
            stylesheet: document.styleSheets.length > 0,
            update_hidden: document.getElementById('launcher-overlay').hidden,
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
        window.evaluate_js("document.getElementById('gear-grok-bot').click()")
        _wait_js(window, "document.getElementById('editor-grok-bot').classList.contains('is-open')")
        result["grok_bot_settings"] = window.evaluate_js(
            "document.getElementById('gear-grok-bot').getAttribute('aria-expanded') === 'true'"
            " && !document.getElementById('editor-grok-bot').inert"
            " && !!document.getElementById('env-grok-bot')"
            " && !!document.getElementById('pick-grok-bot')"
            " && !document.getElementById('launcher-overlay').hidden"
            " && document.getElementById('nav-grok-bot').getAttribute('aria-current') === 'page'")
        window.evaluate_js("document.getElementById('cancel-grok-bot').click()")
        # Exercise the shared menu dispatch against the actual packaged webview,
        # without a network request or changing any saved settings.
        tray._commands._dispatch("update-status")
        result["menu_dialog"] = window.evaluate_js(
            "!document.getElementById('launcher-overlay').hidden"
            " && !document.getElementById('update-panel').hidden")
        window.evaluate_js("closeDialog()")
        _activate_native_settings(window)
        result["native_menu_action"] = True
        window.evaluate_js("document.getElementById('proxy').checked = !SETTINGS.check_system_proxy")
        tray._commands._dispatch("settings")
        result["menu_preserves_edits"] = window.evaluate_js(
            "document.getElementById('editor-common').classList.contains('is-open')"
            " && document.getElementById('proxy').checked !== SETTINGS.check_system_proxy")
        window.evaluate_js("document.getElementById('nav-grok-bot').click()")
        window.evaluate_js("document.getElementById('nav-common').click()")
        result["category_preserves_edits"] = window.evaluate_js(
            "document.getElementById('editor-common').classList.contains('is-open')"
            " && hasUnsavedSettings()"
            " && document.getElementById('proxy').checked !== SETTINGS.check_system_proxy")
        tray._commands._dispatch("update-status")
        _wait_js(window, "!openingUpdates")
        # A prepared update must not bypass the unsaved-settings guard just
        # because it was opened from a native menu instead of the page.
        window.evaluate_js("renderUpdate({...UPDATE, phase: 'ready', can_install: true}); updateAction()")
        result["restart_guard"] = window.evaluate_js(
            "!document.getElementById('update-warning').hidden")
        window.evaluate_js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
        result["escape_preserves_edits"] = window.evaluate_js(
            "document.getElementById('launcher-overlay').hidden"
            " && hasUnsavedSettings()"
            " && document.getElementById('proxy').checked !== SETTINGS.check_system_proxy")
        tray._commands._dispatch("settings")
        result["reopen_preserves_edits"] = window.evaluate_js(
            "document.getElementById('editor-common').classList.contains('is-open')"
            " && document.getElementById('proxy').checked !== SETTINGS.check_system_proxy")
        window.evaluate_js("document.getElementById('cancel-common').click()")
        result["cancel_restores_settings"] = window.evaluate_js(
            "document.getElementById('launcher-overlay').hidden"
            " && !hasUnsavedSettings()"
            " && document.getElementById('proxy').checked === SETTINGS.check_system_proxy")
        if not all(result[key] for key in (
            "grok_bot_settings", "menu_dialog", "menu_preserves_edits",
            "category_preserves_edits", "restart_guard", "escape_preserves_edits",
            "reopen_preserves_edits", "cancel_restores_settings",
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
