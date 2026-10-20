"""Collect local display metadata without changing settings or sending it online."""

import ctypes
from datetime import datetime
import locale
import os
from pathlib import Path
import sys

from . import process as subprocess


def _windows_locale():
    kernel = ctypes.windll.kernel32
    language = ctypes.create_unicode_buffer(85)
    region = ctypes.create_unicode_buffer(16)
    kernel.GetUserDefaultLocaleName(language, len(language))
    # GEOCLASS_NATION=16, GEO_ISO2=4. Region is independent of display language.
    geo_id = kernel.GetUserGeoID(16)
    kernel.GetGeoInfoW(geo_id, 4, region, len(region), 0)
    ui_language = locale.windows_locale.get(kernel.GetUserDefaultUILanguage(), "")
    return ui_language.replace("_", "-") or language.value, region.value


def _mac_locale():
    value = subprocess.check_output(["defaults", "read", "-g", "AppleLocale"],
                                    text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    value = value.split("@")[0]
    return value.replace("_", "-"), value.rsplit("_", 1)[-1] if "_" in value else ""


def local_environment():
    now = datetime.now().astimezone()
    result = {"timezone": now.tzname() or "未知", "utc_offset": now.strftime("%z"),
              "language": "未知", "region": "未知", "platform": sys.platform}
    try:
        if sys.platform == "win32":
            result["language"], result["region"] = _windows_locale()
        elif sys.platform == "darwin":
            result["language"], result["region"] = _mac_locale()
        else:
            language = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or locale.getlocale()[0] or ""
            language = language.split(".")[0].split("@")[0]
            result["language"] = language.replace("_", "-")
            result["region"] = language.rsplit("_", 1)[-1] if "_" in language else ""
        if sys.platform != "win32":
            target = str(Path("/etc/localtime").resolve())
            if "/zoneinfo/" in target:
                result["timezone"] = target.split("/zoneinfo/", 1)[1]
    except Exception:
        pass
    return {key: value or "未知" for key, value in result.items()}
