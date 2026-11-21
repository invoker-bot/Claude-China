"""Authenticate Codex API profiles without reusing a ChatGPT login."""

import json
from pathlib import Path
import subprocess

from .config_paths import codex_api_home, settings_lock
from .providers import get_provider
from .desktop import process


def prepare_environment(profile, env):
    key = profile.api_key
    if not key or any(char.isspace() or char == "\0" for char in key):
        raise ValueError("Codex API profile requires a non-empty, single-line api_key")
    env["CODEX_HOME"] = str(codex_api_home(profile.name).resolve())


def _overrides(profile):
    values = {
        "model_provider": "openai",
        "forced_login_method": "api",
        "cli_auth_credentials_store": "file",
        "openai_base_url": profile.base_url or get_provider("codex").official_base_url,
    }
    return [arg for key, value in values.items()
            for arg in ("-c", key + "=" + json.dumps(value, ensure_ascii=False))]


def _launch_args(arguments, overrides):
    arguments = list(arguments)
    boundary = arguments.index("--") if "--" in arguments else len(arguments)
    for arg in arguments[:boundary]:
        if arg.split("=", 1)[0] in ("--oss", "--local-provider", "--remote", "--remote-auth-token-env"):
            raise ValueError("Codex API profiles require the local OpenAI-compatible provider; "
                             "remove local-model or remote-server options")
    # Keep explicit prompt arguments after -- intact. Last -c wins over defaults.
    return arguments[:boundary] + overrides + arguments[boundary:]


def _matches_key(path, key):
    try:
        with path.open("r", encoding="utf-8") as stream:
            auth = json.load(stream)
    except (OSError, ValueError):
        return False
    return (isinstance(auth, dict) and auth.get("auth_mode") in (None, "apikey")
            and auth.get("OPENAI_API_KEY") == key and not auth.get("tokens"))


def _run(command, env, cwd, key=None):
    options = {"env": env, "cwd": cwd, "capture_output": True, "text": True,
               "encoding": "utf-8", "errors": "replace", "timeout": 30,
               "creationflags": process.CREATE_NO_WINDOW}
    if key is None:
        options["stdin"] = process.DEVNULL
    else:
        options["input"] = key + "\n"
    try:
        result = process.run(command, **options)
    except (OSError, subprocess.SubprocessError):
        # Codex output and exception objects may include credentials. Keep both
        # private, including timeout stdout/stderr and operating-system errors.
        raise ValueError("Codex API authentication check failed; check the CLI installation "
                         "and retry. The session was not started") from None
    if result.returncode:
        output = result.stdout + "\n" + result.stderr
        if any(line.lstrip().startswith("Error loading configuration:") for line in output.splitlines()):
            config_path = Path(env["CODEX_HOME"]) / "config.toml"
            raise ValueError(f"Codex could not load its configuration. Check file permissions and TOML syntax "
                             f"for {config_path} and any project Codex configuration. The session was not started")
    return result


def prepare_command(profile, command, arguments, env, cwd=None):
    """Return a pinned command only after local API credentials are confirmed.

    login --with-api-key persists credentials locally; it does not establish
    whether the server accepts the key or whether the API account has credit.
    """
    overrides = _overrides(profile)
    arguments = _launch_args(arguments, overrides)
    home = codex_api_home(profile.name).resolve()
    if not env.get("CODEX_HOME") or Path(env["CODEX_HOME"]).resolve() != home:
        raise ValueError("Codex API credentials directory does not match the selected profile")
    auth_path = home / "auth.json"
    try:
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Codex also locks auth.json while committing credentials. Use a
        # launcher-owned lock so the child can acquire its own credential lock.
        with settings_lock(home / ".claudec-api-login"):
            if not _matches_key(auth_path, profile.api_key):
                result = _run(list(command) + ["login", "--with-api-key"] + overrides,
                              env, cwd, key=profile.api_key)
                if result.returncode or not _matches_key(auth_path, profile.api_key):
                    raise ValueError("Codex API key login failed; check the profile and CLI configuration. "
                                     "The session was not started")
            status = _run(list(command) + ["login", "status"] + overrides, env, cwd)
            lines = (status.stdout + "\n" + status.stderr).splitlines()
            api_status = any(line.strip().startswith(("Logged in using an API key", "API key configured"))
                             for line in lines)
            if (status.returncode or not api_status
                    or not _matches_key(auth_path, profile.api_key)):
                raise ValueError("Codex did not confirm API key authentication. "
                                 "The session was not started")
    except OSError:
        raise ValueError("Cannot prepare the Codex API credentials directory. "
                         "The session was not started") from None
    return list(command) + arguments
