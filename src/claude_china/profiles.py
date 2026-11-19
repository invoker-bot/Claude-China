import getpass
import sys

from .models import OFFICIAL_BASE_URLS, VALID_TYPES, profile_from_dict
from .providers import get_provider


def _secret_input(prompt):
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return input(prompt)


def _secret_display(value, reveal):
    if not value:
        return "N/A"
    return value if reveal else "********"


def list_profiles(config):
    profiles = config.get("profiles", {})

    if not profiles:
        print("No profiles configured.")
        return

    print(f"{'Name':<20} {'Type':<10} {'Mode':<8} {'Base URL/Credentials':<42} {'Proxy':<20}")
    print("-" * 100)

    for name, p in profiles.items():
        profile = profile_from_dict(p)
        ptype = profile.type
        mode = p.get("mode", "api")

        # Determine what to display in the Base URL/Credentials column
        if mode == "login":
            url_or_creds = p.get("credentials_path", "")
        else:  # api mode
            url_or_creds = p.get("base_url", "")

        # Truncate long strings
        if len(url_or_creds) > 40:
            url_or_creds = url_or_creds[:37] + "..."

        # Get proxy or display "-"
        proxy_display = profile.proxy if profile.proxy else "-"
        if len(proxy_display) > 20:
            proxy_display = proxy_display[:17] + "..."

        print(f"{name:<20} {ptype:<10} {mode:<8} {url_or_creds:<42} {proxy_display:<20}")


def add_profile(config):
    name = input("Profile name: ").strip()
    if not name:
        print("Error: name cannot be empty.")
        sys.exit(1)
    if len(name) > 80 or any(ord(char) < 32 for char in name):
        print("Error: name must be at most 80 printable characters.")
        sys.exit(1)
    if name in config.get("profiles", {}):
        print(f"Error: profile '{name}' already exists.")
        sys.exit(1)

    ptype = input(f"Type ({'/'.join(VALID_TYPES)}): ").strip().lower()
    if ptype not in VALID_TYPES:
        print(f"Error: type must be one of {VALID_TYPES}.")
        sys.exit(1)

    profile_data = {
        "name": name,
        "type": ptype,
    }

    # Provider capabilities determine which modes the prompt offers.
    if ptype in VALID_TYPES:
        modes = get_provider(ptype).auth_modes
        if len(modes) == 1:
            mode = modes[0]
        else:
            mode = input("Mode (api/login) [api]: ").strip().lower() or "api"
        if mode not in modes:
            print(f"Error: mode must be one of {modes}.")
            sys.exit(1)
        profile_data["mode"] = mode

        if mode == "login":
            credentials_path = input("Credentials path (optional, auto-generate if empty): ").strip()
            if not credentials_path:
                credentials_path = f"~/.{ptype}-profiles/{name}"
            profile_data["credentials_path"] = credentials_path
        else:  # api mode
            official = OFFICIAL_BASE_URLS[ptype]
            base_url = input(f"Base URL [{official or 'CLI default'}]: ").strip() or official
            profile_data["base_url"] = base_url
            secret_field = get_provider(ptype).secret_field
            prompt = "Auth token: " if secret_field == "token" else "API key: "
            profile_data[secret_field] = _secret_input(prompt).strip()

    # Optional proxy for all types
    proxy = input("Proxy (optional, e.g., http://127.0.0.1:7890): ").strip()
    if proxy:
        profile_data["proxy"] = proxy

    # Optional default launch args for all types. Stored as a single string;
    # launcher will shlex.split it at run time.
    default_args = input(
        "Default args (optional, e.g., --model claude-opus-4-5): "
    ).strip()
    if default_args:
        profile_data["default_args"] = default_args

    profile_from_dict(profile_data)
    config.setdefault("profiles", {})[name] = profile_data
    if get_provider(ptype).settings_provider:
        from .antigravity import configure_gemini_api
        configure_gemini_api()
    return config


def create_profile_data(name, ptype, mode="api", base_url=None, secret="",
                        credentials_path=None, proxy=None, default_args=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("Profile name cannot be empty")
    if len(name) > 80 or any(ord(char) < 32 for char in name):
        raise ValueError("Profile name must be at most 80 printable characters")
    provider = get_provider(ptype)
    if mode not in provider.auth_modes:
        raise ValueError(f"{ptype} does not support {mode} mode")
    record = {"name": name, "type": ptype, "mode": mode}
    if proxy:
        record["proxy"] = proxy
    if default_args:
        record["default_args"] = default_args
    if mode == "login":
        if secret:
            raise ValueError("Login profiles do not accept an API secret")
        record["credentials_path"] = credentials_path or f"~/.{ptype}-profiles/{name}"
    else:
        record["base_url"] = provider.official_base_url if base_url is None else base_url
        record[provider.secret_field] = secret or ""
    profile_from_dict(record)
    return record


def update_profile_data(record, changes):
    updated = dict(record)
    provider = get_provider(updated.get("type", ""))
    old_mode = updated.get("mode", "api")
    mode = changes.get("mode") or old_mode
    if mode not in provider.auth_modes:
        raise ValueError(f"{provider.id} does not support {mode} mode")
    if mode == "login" and (changes.get("base_url") is not None or changes.get("secret") is not None):
        raise ValueError("Login profiles do not accept API endpoint or secret options")
    if mode == "api" and changes.get("credentials_path") is not None:
        raise ValueError("API profiles do not accept a credentials directory")
    name = changes.get("name")
    if name is not None:
        name = name.strip()
        if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
            raise ValueError("Profile name must be at most 80 printable characters")
        updated["name"] = name
    if mode != old_mode:
        for key in ("base_url", "token", "api_key", "credentials_path", "manual_browser_login"):
            updated.pop(key, None)
        updated["mode"] = mode
        if mode == "login":
            updated["credentials_path"] = f"~/.{provider.id}-profiles/{updated['name']}"
        else:
            updated["base_url"] = provider.official_base_url
    for key in ("base_url", "credentials_path"):
        if changes.get(key) is not None:
            updated[key] = changes[key]
    if changes.get("clear_proxy"):
        updated.pop("proxy", None)
    elif changes.get("proxy") is not None:
        if changes["proxy"]:
            updated["proxy"] = changes["proxy"]
        else:
            updated.pop("proxy", None)
    if changes.get("clear_default_args"):
        updated.pop("default_args", None)
    elif changes.get("default_args") is not None:
        if changes["default_args"]:
            updated["default_args"] = changes["default_args"]
        else:
            updated.pop("default_args", None)
    if changes.get("clear_secret"):
        updated.pop("token", None)
        updated.pop("api_key", None)
    elif changes.get("secret") is not None:
        updated.pop("token" if provider.secret_field == "api_key" else "api_key", None)
        updated[provider.secret_field] = changes["secret"]
    profile_from_dict(updated)
    return updated


def show_profile(config, name, reveal=False):
    profiles = config.get("profiles", {})
    if name not in profiles:
        print(f"Error: profile '{name}' not found.")
        sys.exit(1)

    profile_dict = profiles[name]
    profile = profile_from_dict(profile_dict)

    print(f"Profile: {name}")
    print(f"Type: {profile.type}")

    # Display authentication mode and its relevant fields.
    if profile.type in VALID_TYPES:
        mode = profile_dict.get("mode", "api")
        print(f"Mode: {mode}")

        if mode == "login":
            credentials_path = profile_dict.get("credentials_path", "N/A")
            print(f"Credentials Path: {credentials_path}")
            if profile.type == "claude":
                print(f"Login browser: {'manual' if profile.uses_manual_browser_login else 'auto'}")
        else:  # api mode
            base_url = profile_dict.get("base_url", "N/A")
            secret_field = get_provider(profile.type).secret_field
            label = "Token" if secret_field == "token" else "API Key"
            secret = profile_dict.get(secret_field)
            print(f"Base URL: {base_url}")
            print(f"{label}: {_secret_display(secret, reveal)}")

    # Display proxy if set
    if profile.proxy:
        print(f"Proxy: {profile.proxy}")

    # Display default_args if set (preserve original list/string form)
    if profile.default_args:
        print(f"Default args: {profile.default_args}")


def remove_profile(config, name):
    if name not in config.get("profiles", {}):
        print(f"Error: profile '{name}' not found.")
        sys.exit(1)
    del config["profiles"][name]
    print(f"Removed profile '{name}'.")
    return config
