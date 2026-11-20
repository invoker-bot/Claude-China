import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from .launcher import clear_managed_environment, find_command
from .providers import get_provider


@dataclass(frozen=True)
class NpmInstallation:
    kind: str
    command: str
    package_root: str
    version: str


def find_npm_installation(kind) -> Optional[NpmInstallation]:
    provider = get_provider(kind)
    if not provider.npm_package:
        return None
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not npm:
        return None
    try:
        result = subprocess.run([npm, "prefix", "-g"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=10)
        prefix = result.stdout.strip()
        if result.returncode or not prefix:
            return None
        if sys.platform == "win32":
            command = Path(prefix) / (provider.command + ".cmd")
            modules = Path(prefix) / "node_modules"
        else:
            command = Path(prefix) / "bin" / provider.command
            modules = Path(prefix) / "lib" / "node_modules"
        package_root = modules / Path(provider.npm_package)
        if not command.is_file():
            return None
        metadata = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
        if (metadata.get("name") != provider.npm_package
                or not isinstance(metadata.get("version"), str)):
            return None
        return NpmInstallation(kind, str(command), str(package_root), metadata["version"])
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None


def version_from_output(output):
    match = re.search(r"(?<![\w.])\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", output or "")
    return match.group(0) if match else None


def running_npm_processes(kind):
    installation = find_npm_installation(kind)
    if not installation:
        return []
    import psutil
    root = os.path.normcase(os.path.realpath(installation.package_root))
    prefix = root + os.sep
    running = []
    for process in psutil.process_iter(["pid", "exe", "cmdline"]):
        values = [process.info.get("exe") or ""] + list(process.info.get("cmdline") or [])
        for value in values:
            try:
                candidate = os.path.normcase(os.path.realpath(value.strip('"')))
            except (OSError, ValueError, TypeError):
                continue
            if candidate.startswith(prefix):
                running.append(process.pid)
                break
    return sorted(set(running))


def ensure_not_running(kind):
    running = running_npm_processes(kind)
    if not running:
        return
    provider = get_provider(kind)
    detail = (" Stop its background/app-server processes; use 'codex app-server daemon stop' "
              "when the managed daemon is running." if kind == "codex" else " Stop its background processes.")
    raise RuntimeError(
        f"{provider.display} is running from the npm package. Close its terminal sessions before upgrading."
        + detail
    )


def check_npm_installation(kind, command, output, required=True):
    provider = get_provider(kind)
    installation = find_npm_installation(kind)
    if installation is None:
        if required:
            raise RuntimeError(f"Cannot find {provider.display} in the active npm prefix after upgrading.")
        return None
    if command and os.path.normcase(os.path.realpath(command)) != os.path.normcase(
            os.path.realpath(installation.command)):
        raise RuntimeError(
            f"{provider.display} is shadowed by another installation at '{command}'; "
            f"expected '{installation.command}'."
        )
    actual = version_from_output(output)
    if actual is None:
        raise RuntimeError(f"Cannot parse the {provider.display} version: {output}")
    if actual != installation.version:
        raise RuntimeError(
            f"{provider.display} executable is {actual}; expected npm package {installation.version}. "
            "Close its running sessions and retry the upgrade."
        )
    return installation


def validate_native_package(kind):
    if kind != "codex":
        return
    from .desktop.cli_guard import _codex_binaries
    from .desktop.terminal_host import resolve_cli_argv
    argv = resolve_cli_argv(kind)
    if len(argv) < 2:
        return
    if not any(path.is_file() for path in _codex_binaries(argv[1])):
        raise RuntimeError(
            "Codex CLI is missing its Windows platform package or native executable. "
            "Repair it with 'claudec upgrade codex'."
        )


def verify_installation(kind, env=None):
    from .diagnostics import command_version
    provider = get_provider(kind)
    validate_native_package(kind)
    output = command_version(kind, env)
    if provider.npm_package:
        check_npm_installation(kind, find_command(kind), output)
    return output
