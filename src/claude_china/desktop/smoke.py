"""Packaged GUI verification, used by the release build on each target OS."""

import json
import sys
import time

from .. import __version__


def verify_window(window, tray, report):
    result = {"ok": False, "version": __version__, "platform": sys.platform,
              "frozen": bool(getattr(sys, "frozen", False))}
    try:
        if not window.events.loaded.wait(30):
            raise RuntimeError("The bundled UI did not load within 30 seconds")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if window.evaluate_js("typeof READY !== 'undefined' && READY"):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("The UI did not finish calling the Python bridge")
        result.update(window.evaluate_js("""({
            title: document.title,
            cards: document.querySelectorAll('.bay--app').length,
            icon_loaded: document.getElementById('brand-mark').naturalWidth > 0,
            stylesheet: document.styleSheets.length > 0
        })"""))
        if (result["title"] != "Claude China" or result["cards"] != 2
                or not result["icon_loaded"] or not result["stylesheet"]):
            raise RuntimeError("The packaged UI is incomplete")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        tray._quit(None, None)
