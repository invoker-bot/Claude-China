import os
from pathlib import Path
import subprocess

from .antigravity import validate_gemini_api
from .config import load_config
from .launcher import clear_managed_environment, find_command
from .models import profile_from_dict
from .providers import PROVIDERS, get_provider


def command_version(kind, env=None):
    from .desktop.terminal_host import resolve_cli_argv
    environment = dict(os.environ if env is None else env)
    clear_managed_environment(environment)
    try:
        argv = resolve_cli_argv(kind) + ["--version"]
        result = subprocess.run(argv, env=environment, capture_output=True, text=True, timeout=30)
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode or not output:
            raise ValueError
        return output.splitlines()[0][:200]
    except Exception:
        raise RuntimeError(f"Cannot verify the installed {get_provider(kind).display} command") from None


def collect(profile_name=None, versions=False):
    data = load_config()
    records = data.get("profiles", {})
    if profile_name is not None and profile_name not in records:
        raise ValueError(f"Profile '{profile_name}' not found")
    if profile_name is not None:
        records = {profile_name: records[profile_name]}
    provider_ids = list(dict.fromkeys(record["type"] for record in records.values())) if profile_name else [
        provider.id for provider in PROVIDERS
    ]
    tools = []
    failures = False
    for kind in provider_ids:
        provider = get_provider(kind)
        command = find_command(kind)
        item = {"id": kind, "display": provider.display, "installed": bool(command),
                "path": command or "", "version": "", "package_version": "",
                "consistent": None, "warning": "", "error": ""}
        if command:
            from .upgrades import validate_native_package
            try:
                validate_native_package(kind)
            except RuntimeError as exc:
                item["error"] = str(exc)
                failures = True
        if versions and command and not item["error"]:
            try:
                item["version"] = command_version(kind)
                if provider.npm_package:
                    from .upgrades import check_npm_installation
                    installation = check_npm_installation(kind, command, item["version"], required=False)
                    if installation is None:
                        item["warning"] = "No npm package was found in the active prefix; using an unmanaged command."
                    else:
                        item["package_version"] = installation.version
                        item["consistent"] = True
            except RuntimeError as exc:
                item["error"] = str(exc)
                failures = True
        tools.append(item)
    profiles = []
    for name, record in records.items():
        profile = profile_from_dict(record)
        provider = get_provider(profile.type)
        errors, warnings = [], []
        if not find_command(profile.type):
            errors.append(f"{provider.command} was not found on PATH")
        if record.get("mode", "api") == "login":
            if not profile.credentials_path:
                errors.append("credentials_path is missing")
            elif not Path(profile.credentials_path).expanduser().is_dir():
                warnings.append("the credentials directory will be created on launch")
        else:
            secret = getattr(profile, provider.secret_field, None)
            if not secret:
                message = "no API secret is saved"
                if provider.settings_provider:
                    errors.append(message)
                else:
                    warnings.append(message)
            if provider.settings_provider:
                try:
                    validate_gemini_api()
                except ValueError as exc:
                    errors.append(str(exc))
        profiles.append({"name": name, "type": profile.type, "errors": errors, "warnings": warnings,
                         "ok": not errors})
        failures = failures or bool(errors)
    return {"ok": not failures, "tools": tools, "profiles": profiles}
