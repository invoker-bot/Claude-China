import os
import shlex
import sys
import shutil
import subprocess
from typing import List

from .models import profile_from_dict, ApiProfile, LoginProfile, is_builtin_grok_api
from .grok import find_npm_installation

ENV_MAP = {
    "claude": {
        "env": {"ANTHROPIC_BASE_URL": "base_url", "ANTHROPIC_AUTH_TOKEN": "token"},
        "cmd": "claude",
    },
    "grok": {
        "env": {
            "GROK_CLI_CHAT_PROXY_BASE_URL": "base_url",
            "XAI_API_KEY": "api_key",
        },
        "cmd": "grok",
    },
    "codex": {
        "env": {"OPENAI_BASE_URL": "base_url", "OPENAI_API_KEY": "api_key"},
        "cmd": "codex",
    },
}

CONFIG_DIR_ENV_VARS = {
    "claude": "CLAUDE_CONFIG_DIR",
    "grok": "GROK_HOME",
    "codex": "CODEX_HOME",
}

PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
)

MANAGED_ENV_VARS = frozenset(
    env_var
    for spec in ENV_MAP.values()
    for env_var in spec["env"]
) | frozenset(CONFIG_DIR_ENV_VARS.values()) | frozenset(PROXY_ENV_VARS)


def clear_managed_environment(env):
    """Remove environment variables managed by this tool."""
    for env_var in MANAGED_ENV_VARS:
        env.pop(env_var, None)


def prepare_environment(profile):
    """Prepare environment variables based on profile type and mode"""
    env = os.environ.copy()
    clear_managed_environment(env)
    ptype = profile.type

    if ptype not in ENV_MAP:
        raise ValueError(f"Unknown profile type '{ptype}'")

    spec = ENV_MAP[ptype]

    # Handle authentication based on profile type
    if isinstance(profile, LoginProfile):
        # Expand ~ to home directory
        credentials_path = os.path.expanduser(profile.credentials_path)
        # Set the appropriate config dir env var based on profile type
        # Each supported CLI exposes an environment variable for its home dir.
        config_dir_var = CONFIG_DIR_ENV_VARS.get(ptype)
        if config_dir_var:
            if not credentials_path:
                raise ValueError(f"Login profile '{profile.name or ptype}' is missing credentials_path")
            os.makedirs(credentials_path, exist_ok=True)
            # For codex: ensure config.toml exists with default openai provider
            # to prevent inheriting custom providers from ~/.codex/config.toml
            if ptype == "codex":
                config_toml = os.path.join(credentials_path, "config.toml")
                if not os.path.exists(config_toml):
                    with open(config_toml, "w", encoding="utf-8") as f:
                        f.write('model_provider = "openai"\n')
            env[config_dir_var] = credentials_path
    elif isinstance(profile, ApiProfile):
        # API mode: set API environment variables.
        # Grok's public API is already the CLI default for API-key auth.
        # GROK_CLI_CHAT_PROXY_BASE_URL replaces the separate cli-chat-proxy
        # host, so an official api.x.ai URL must not be exported as that proxy.
        for env_var, config_key in spec["env"].items():
            value = getattr(profile, config_key, None)
            if not value:
                continue
            if env_var == "GROK_CLI_CHAT_PROXY_BASE_URL" and is_builtin_grok_api(value):
                continue
            env[env_var] = value

    # Handle proxy (all modes)
    if profile.proxy:
        for env_var in PROXY_ENV_VARS:
            env[env_var] = profile.proxy

    # On Windows, enable PowerShell tool for Claude Code
    if sys.platform == "win32" and ptype == "claude":
        env.setdefault("CLAUDE_CODE_USE_POWERSHELL_TOOL", "1")

    return env


def resolve_default_args(value) -> List[str]:
    """Normalize a profile's `default_args` field into List[str].

    Accepts:
      - None / "" / []  -> []
      - List[str]       -> returned as-is
      - str             -> shlex.split(value, posix=True)

    Raises TypeError on unsupported shapes so config bugs surface loudly.
    """
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        return shlex.split(value, posix=True)
    raise TypeError(
        f"default_args must be a list or string, got {type(value).__name__}"
    )


def merge_launch_args(
    extra_args: List[str],
    default_args,
    use_default_args: bool = True,
) -> List[str]:
    """Combine command-line extra_args with the profile's default_args.

    Design decision (Q3 = B): command-line args come first, profile defaults
    are appended last so they always win for "last-occurrence-wins" flags
    like `--model`. When use_default_args is False, defaults are skipped
    entirely (escape hatch via `--no-default-args`).

    Args:
        extra_args:        Args passed on the command line (already a list).
        default_args:      Raw value from profile (None | list | str).
        use_default_args:  When False, ignore default_args completely.

    Returns:
        Final argv list to pass to the underlying CLI.

    Helpful: call resolve_default_args() to normalize default_args first.
    """
    if not use_default_args:
        return list(extra_args)
    return list(extra_args) + resolve_default_args(default_args)


def launch(profile_dict, extra_args, use_default_args=True):
    # Convert dict to dataclass
    profile = profile_from_dict(profile_dict)
    ptype = profile.type

    if ptype not in ENV_MAP:
        print(f"Error: unknown profile type '{ptype}'.")
        sys.exit(1)

    spec = ENV_MAP[ptype]
    cmd = spec["cmd"]

    # On Windows, npm global commands are .cmd files
    if sys.platform == "win32":
        cmd_path = shutil.which(f"{cmd}.cmd") or shutil.which(cmd)
    else:
        cmd_path = shutil.which(cmd)

    if ptype == "grok":
        installation = find_npm_installation()
        if installation:
            cmd_path = installation.command

    if not cmd_path:
        print(f"Error: '{cmd}' not found in PATH. Install it first.")
        sys.exit(1)

    # Prepare environment
    env = prepare_environment(profile)

    final_args = merge_launch_args(extra_args, profile.default_args, use_default_args)
    full_cmd = [cmd_path] + final_args

    if sys.platform == "win32":
        # On Windows, ensure UTF-8 console encoding (fixes mojibake/encoding issues
        # in PowerShell when launching AI editors like claude, codex, grok).
        # PowerShell defaults to UTF-16LE; we wrap the launch in PowerShell
        # to set OutputEncoding to UTF8 so the child process inherits a UTF-8 console.
        ps_script = (
            '$OutputEncoding = [console]::OutputEncoding = [Text.Encoding]::UTF8; '
            f'& {shlex.join(full_cmd)}'
        )
        ps_cmd = f'powershell.exe -NoProfile -Command "{ps_script}"'
        try:
            result = subprocess.run(ps_cmd, env=env, shell=True)
            sys.exit(result.returncode)
        except KeyboardInterrupt:
            sys.exit(130)
    else:
        # On Unix, update os.environ and use execvp
        os.environ.update(env)
        os.execvp(cmd_path, full_cmd)
