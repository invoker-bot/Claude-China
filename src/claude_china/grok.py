"""Locate and verify the Grok installation managed by npm."""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GrokInstallation:
    command: str
    version: str


def find_npm_installation() -> Optional[GrokInstallation]:
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not npm:
        return None
    try:
        result = subprocess.run(
            [npm, "prefix", "-g"], capture_output=True, text=True, timeout=10,
        )
        prefix = result.stdout.strip()
        if result.returncode or not prefix:
            return None
        if sys.platform == "win32":
            command = os.path.join(prefix, "grok.cmd")
            modules = os.path.join(prefix, "node_modules")
        else:
            command = os.path.join(prefix, "bin", "grok")
            modules = os.path.join(prefix, "lib", "node_modules")
        if not os.path.isfile(command):
            return None
        package_file = os.path.join(modules, "@xai-official", "grok", "package.json")
        with open(package_file, encoding="utf-8") as package:
            metadata = json.load(package)
        if (not isinstance(metadata, dict)
                or metadata.get("name") != "@xai-official/grok"
                or not isinstance(metadata.get("version"), str)):
            return None
        return GrokInstallation(command, metadata["version"])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def home_binary(home: str) -> str:
    name = "grok.exe" if sys.platform == "win32" else "grok"
    return os.path.join(home, "bin", name)


def check_version(command: str, env: dict, expected: str) -> None:
    try:
        result = subprocess.run(
            [command, "--version"], env=env,
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Cannot verify Grok CLI at '{command}': {exc}") from exc
    match = re.search(r"\bgrok\s+(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)", result.stdout)
    if result.returncode or not match:
        raise RuntimeError(f"Cannot verify Grok CLI version at '{command}'.")
    actual = match.group(1)
    if actual != expected:
        raise RuntimeError(f"Grok CLI at '{command}' is {actual}; expected {expected}.")
