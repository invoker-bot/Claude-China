from contextlib import contextmanager
import os
import tempfile

import yaml

from .config_paths import config_dir, ensure_config_file, settings_lock
from .models import profile_from_dict, profile_to_dict, BaseProfile

CONFIG_DIR = config_dir()
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load_config():
    ensure_config_file(CONFIG_FILE, {"profiles": {}})
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        data = {"profiles": {}}
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a mapping")
    migrated = False
    if "profiles" not in data:
        data["profiles"] = {}
        migrated = True
    if not isinstance(data.get("profiles"), dict):
        raise ValueError("Configuration must contain a profiles mapping")
    profiles = data.get("profiles", {})
    for name, profile in profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Profile names must be non-empty strings")
        if not isinstance(profile, dict):
            raise ValueError(f"Profile '{name}' must be a mapping")
        if "name" not in profile:
            profile["name"] = name
            migrated = True
        if "mode" not in profile:
            profile["mode"] = "api"
            migrated = True
        if profile.get("type") == "antigravity-cli":
            profile["type"] = "antigravity"
            migrated = True
        profile_from_dict(profile)
    if migrated:
        save_config(data)
    return data


def _save_config(data):
    CONFIG_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=CONFIG_FILE.parent,
                                         prefix='.config-', suffix='.tmp', delete=False) as f:
            temporary = f.name
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, CONFIG_FILE)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save_config(data):
    with settings_lock(CONFIG_FILE):
        _save_config(data)


@contextmanager
def transaction():
    with settings_lock(CONFIG_FILE):
        data = load_config()
        yield data
        _save_config(data)


def init_config():
    save_config({"profiles": {}})


def get_profile_object(config, name: str) -> BaseProfile:
    """Get a profile object from config by name."""
    if name not in config.get("profiles", {}):
        raise ValueError(f"Profile '{name}' not found in config")
    profile_dict = config["profiles"][name]
    return profile_from_dict(profile_dict)
