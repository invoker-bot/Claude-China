import json
import os
from pathlib import Path
import tempfile

from .config_paths import settings_lock


MAX_SETTINGS_BYTES = 1024 * 1024


def settings_path():
    return Path.home() / ".gemini" / "antigravity-cli" / "settings.json"


def read_settings():
    path = settings_path()
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        return {}
    if len(raw) > MAX_SETTINGS_BYTES:
        raise ValueError("Antigravity CLI settings are too large to read safely")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError(f"Antigravity CLI settings are invalid: {path}") from None
    if not isinstance(data, dict):
        raise ValueError(f"Antigravity CLI settings must be a JSON object: {path}")
    return data


def configure_gemini_api():
    path = settings_path()
    with settings_lock(path):
        data = read_settings()
        data["modelProvider"] = "gemini"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".settings-", suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return path


def validate_gemini_api():
    path = settings_path()
    if read_settings().get("modelProvider") != "gemini":
        raise ValueError(
            f"Antigravity CLI API profiles require modelProvider=gemini in {path}. "
            "Run 'claudec configure antigravity' or save the profile in the desktop app."
        )
