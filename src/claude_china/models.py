from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Union
from urllib.parse import urlsplit

from .providers import PROVIDERS, get_provider

VALID_TYPES = tuple(provider.id for provider in PROVIDERS)
OFFICIAL_BASE_URLS = {provider.id: provider.official_base_url for provider in PROVIDERS}

# Public xAI API hosts. These are the CLI's own API-key default, not a
# cli-chat-proxy override, so they must not be exported as
# GROK_CLI_CHAT_PROXY_BASE_URL.
GROK_BUILTIN_API_URLS = frozenset({
    OFFICIAL_BASE_URLS["grok"],
    "https://api.x.ai",
})


def is_builtin_grok_api(url: str) -> bool:
    return (url or "").strip().rstrip("/") in GROK_BUILTIN_API_URLS


def _validate_url(value, field, schemes):
    if not value:
        return
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in schemes or not parsed.hostname or any(char.isspace() for char in value):
            raise ValueError
        parsed.port
    except ValueError:
        raise ValueError(f"{field} must be a valid {'/'.join(schemes)} URL") from None


# default_args is stored in either form the user wrote it: a YAML list, or a
# single command-line string parsed at use-site via shlex.split.
DefaultArgs = Optional[Union[List[str], str]]


@dataclass
class BaseProfile:
    """Common fields for all profiles"""
    name: str
    type: str                            # Registered CLI provider id
    proxy: Optional[str] = None          # e.g., "http://127.0.0.1:7890"
    default_args: DefaultArgs = None     # appended after CLI extra_args at launch


@dataclass
class ApiProfile(BaseProfile):
    """API mode: authenticate with a token/key and an optional endpoint."""
    base_url: str = ""
    token: Optional[str] = None      # Claude only
    api_key: Optional[str] = None    # Non-Claude API providers


@dataclass
class LoginProfile(BaseProfile):
    """Login mode: authenticate via an isolated credentials directory."""
    credentials_path: str = ""       # Path to existing OAuth credentials
    manual_browser_login: Optional[bool] = None

    @property
    def uses_manual_browser_login(self) -> bool:
        return self.type == "claude" and self.manual_browser_login is not False


def profile_from_dict(data: dict) -> BaseProfile:
    """Convert dict to appropriate profile dataclass"""
    if not isinstance(data, dict):
        raise ValueError("Profile must be a mapping")
    name = data.get("name", "")
    ptype = data.get("type", "")
    mode = data.get("mode", "api")  # Default to api for backward compatibility
    if ptype not in VALID_TYPES:
        raise ValueError(f"Unknown profile type '{ptype}'")
    if mode not in ("api", "login"):
        raise ValueError(f"Unknown profile mode '{mode}'")
    if mode not in get_provider(ptype).auth_modes:
        raise ValueError(f"{ptype} does not support {mode} mode")
    for key in ("name", "proxy", "base_url", "token", "api_key", "credentials_path"):
        if data.get(key) is not None and not isinstance(data.get(key), str):
            raise ValueError(f"{key} must be a string")
    _validate_url(data.get("base_url"), "base_url", ("http", "https"))
    _validate_url(data.get("proxy"), "proxy", ("http", "https", "socks5", "socks5h"))
    proxy = data.get("proxy")
    default_args = data.get("default_args")

    if mode == "login":
        credentials_path = data.get("credentials_path", "")
        if credentials_path and not Path(credentials_path).expanduser().is_absolute():
            raise ValueError("credentials_path must be absolute or start with ~")
        manual_browser_login = data.get("manual_browser_login")
        if manual_browser_login is not None and not isinstance(manual_browser_login, bool):
            raise ValueError("manual_browser_login must be true or false")
        if manual_browser_login and ptype != "claude":
            raise ValueError("manual_browser_login currently supports Claude Code only")
        return LoginProfile(
            name=name,
            type=ptype,
            credentials_path=credentials_path,
            manual_browser_login=manual_browser_login,
            proxy=proxy,
            default_args=default_args,
        )
    else:
        # API mode (default for all types)
        return ApiProfile(
            name=name,
            type=ptype,
            base_url=data.get("base_url", ""),
            token=data.get("token"),
            api_key=data.get("api_key"),
            proxy=proxy,
            default_args=default_args,
        )


def profile_to_dict(profile: BaseProfile) -> dict:
    """Convert profile dataclass to dict"""
    data = asdict(profile)

    # Add mode field
    if isinstance(profile, LoginProfile):
        data["mode"] = "login"
    else:
        data["mode"] = "api"

    # Remove None values for cleaner YAML
    return {k: v for k, v in data.items() if v is not None}
