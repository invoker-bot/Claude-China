from dataclasses import dataclass, asdict, field
from typing import List, Optional, Union

VALID_TYPES = ("claude", "grok", "codex")

# Used when `claudec add` leaves the API base URL blank.
OFFICIAL_BASE_URLS = {
    "claude": "https://api.anthropic.com",
    "grok": "https://api.x.ai/v1",
    "codex": "https://api.openai.com/v1",
}

# Public xAI API hosts. These are the CLI's own API-key default, not a
# cli-chat-proxy override, so they must not be exported as
# GROK_CLI_CHAT_PROXY_BASE_URL.
GROK_BUILTIN_API_URLS = frozenset({
    OFFICIAL_BASE_URLS["grok"],
    "https://api.x.ai",
})


def is_builtin_grok_api(url: str) -> bool:
    return (url or "").strip().rstrip("/") in GROK_BUILTIN_API_URLS

# default_args is stored in either form the user wrote it: a YAML list, or a
# single command-line string parsed at use-site via shlex.split.
DefaultArgs = Optional[Union[List[str], str]]


@dataclass
class BaseProfile:
    """Common fields for all profiles"""
    name: str
    type: str                            # "claude" | "grok" | "codex"
    proxy: Optional[str] = None          # e.g., "http://127.0.0.1:7890"
    default_args: DefaultArgs = None     # appended after CLI extra_args at launch


@dataclass
class ApiProfile(BaseProfile):
    """API mode: authenticate with a token/key and an optional endpoint."""
    base_url: str = ""
    token: Optional[str] = None      # Claude only
    api_key: Optional[str] = None    # Grok/Codex only


@dataclass
class LoginProfile(BaseProfile):
    """Login mode: authenticate via an isolated credentials directory."""
    credentials_path: str = ""       # Path to existing OAuth credentials
    manual_browser_login: bool = False


def profile_from_dict(data: dict) -> BaseProfile:
    """Convert dict to appropriate profile dataclass"""
    name = data.get("name", "")
    ptype = data.get("type", "")
    mode = data.get("mode", "api")  # Default to api for backward compatibility
    proxy = data.get("proxy")
    default_args = data.get("default_args")

    if ptype in VALID_TYPES and mode == "login":
        manual_browser_login = data.get("manual_browser_login", False)
        if not isinstance(manual_browser_login, bool):
            raise ValueError("manual_browser_login must be true or false")
        if manual_browser_login and ptype != "claude":
            raise ValueError("manual_browser_login currently supports Claude Code only")
        return LoginProfile(
            name=name,
            type=ptype,
            credentials_path=data.get("credentials_path", ""),
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
        if not data["manual_browser_login"]:
            data.pop("manual_browser_login")
    else:
        data["mode"] = "api"

    # Remove None values for cleaner YAML
    return {k: v for k, v in data.items() if v is not None}
