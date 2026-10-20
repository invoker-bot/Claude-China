import yaml

from .config_paths import config_dir, ensure_config_file
from .models import profile_from_dict, profile_to_dict, BaseProfile

CONFIG_DIR = config_dir()
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load_config():
    ensure_config_file(CONFIG_FILE, {"profiles": {}})
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "profiles" not in data:
        data = {"profiles": {}}
    migrated = False
    profiles = data.get("profiles", {})
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        if "name" not in profile:
            profile["name"] = name
            migrated = True
        if "mode" not in profile:
            profile["mode"] = "api"
            migrated = True
    if migrated:
        save_config(data)
    return data


def save_config(data):
    CONFIG_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def init_config():
    save_config({"profiles": {}})


def get_profile_object(config, name: str) -> BaseProfile:
    """Get a profile object from config by name."""
    if name not in config.get("profiles", {}):
        raise ValueError(f"Profile '{name}' not found in config")
    profile_dict = config["profiles"][name]
    return profile_from_dict(profile_dict)
