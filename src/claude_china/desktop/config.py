from typing import Optional
from threading import RLock
import os
import tempfile

import yaml

from ..config_paths import config_dir, ensure_config_file

DESKTOP_CONFIG_FILE = config_dir() / "desktop.yaml"
# pywebview dispatches API calls on separate threads. All desktop preference
# read/modify/write transactions share this lock, including terminal favorites.
CONFIG_LOCK = RLock()

DEFAULTS = {
    "language": "system",
    "check_system_proxy": True,
    "auto_proxy_env": False,
    "safety_check": True,
    "safety_block_unknown": True,
    "env_vars": {},   # 通用 (common) — every app launch
    "apps": {},       # per-app: {<id>: {"path": str, "env_vars": {...}}}
}


def load_desktop_config() -> dict:
    """Load desktop.yaml, importing legacy settings or creating first-use defaults."""
    with CONFIG_LOCK:
        return _load_desktop_config()


def _load_desktop_config() -> dict:
    ensure_config_file(DESKTOP_CONFIG_FILE, DEFAULTS)
    with open(DESKTOP_CONFIG_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Coerce, don't just default: a hand-written `apps:` / `env_vars:` with no
    # value parses to None, and setdefault is a no-op when the key already
    # exists. Normalizing here keeps the write path (_app_block) from crashing.
    if not isinstance(data.get("env_vars"), dict):
        data["env_vars"] = {}
    if not isinstance(data.get("apps"), dict):
        data["apps"] = {}
    data.setdefault("check_system_proxy", True)
    data.setdefault("auto_proxy_env", False)
    data.setdefault("safety_check", True)
    data.setdefault("safety_block_unknown", True)
    data.setdefault("language", "system")
    return data


def get_language(data: dict) -> str:
    value = data.get("language", "system")
    return value if isinstance(value, str) and value in ("system", "zh-CN", "zh-TW", "en") else "system"


def launch_settings_changed(before: dict, after: dict) -> bool:
    """Display language does not invalidate an in-flight environment check."""
    return ({key: value for key, value in before.items() if key != "language"}
            != {key: value for key, value in after.items() if key != "language"})


def save_desktop_config(data: dict) -> None:
    with CONFIG_LOCK:
        DESKTOP_CONFIG_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=DESKTOP_CONFIG_FILE.parent,
                                             prefix='.desktop-', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                yaml.dump(data, stream, default_flow_style=False, sort_keys=False, allow_unicode=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, DESKTOP_CONFIG_FILE)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


def get_check_system_proxy(data: dict) -> bool:
    return bool(data.get("check_system_proxy", True))


def set_check_system_proxy(data: dict, value: bool) -> None:
    data["check_system_proxy"] = bool(value)


def get_auto_proxy_env(data: dict) -> bool:
    return bool(data.get("auto_proxy_env", False))


def set_auto_proxy_env(data: dict, value: bool) -> None:
    data["auto_proxy_env"] = bool(value)


def get_common_env(data: dict) -> dict:
    return dict(data.get("env_vars") or {})


def get_safety_settings(data: dict) -> dict:
    # Invalid handwritten values must not accidentally disable protection.
    return {"enabled": data.get("safety_check") is not False,
            "block_unknown": data.get("safety_block_unknown") is not False,
            "router_mode": data.get("safety_router_mode") is True}


def set_safety_settings(data: dict, payload: dict) -> None:
    for field, key in (("enabled", "safety_check"), ("block_unknown", "safety_block_unknown")):
        if field in payload:
            data[key] = payload[field] is not False
    if "router_mode" in payload:
        data["safety_router_mode"] = payload["router_mode"] is True


def set_common_env(data: dict, env: dict) -> None:
    data["env_vars"] = dict(env)


def _app_block(data: dict, app_id: str) -> dict:
    return data.setdefault("apps", {}).setdefault(app_id, {})


def get_app_env(data: dict, app_id: str) -> dict:
    block = (data.get("apps") or {}).get(app_id) or {}
    return dict(block.get("env_vars") or {})


def set_app_env(data: dict, app_id: str, env: dict) -> None:
    _app_block(data, app_id)["env_vars"] = dict(env)


def get_app_path(data: dict, app_id: str) -> Optional[str]:
    block = (data.get("apps") or {}).get(app_id) or {}
    return block.get("path")


def set_app_path(data: dict, app_id: str, path: str) -> None:
    _app_block(data, app_id)["path"] = path
