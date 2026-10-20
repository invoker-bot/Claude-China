"""Shared settings location and one-time import from pre-claudec releases."""

import os
from pathlib import Path
import tempfile
from typing import Optional

import yaml


def config_dir() -> Path:
    return Path.home() / ".claudec"


def legacy_config_file(destination: Path) -> Optional[Path]:
    # Explicit paths (including packaged smoke tests) must stay isolated.
    if destination.parent == config_dir() and destination.name in ("config.yaml", "desktop.yaml"):
        return Path.home() / ".code-ai" / destination.name
    return None


def ensure_config_file(destination: Path, defaults: dict) -> None:
    """Import a missing settings file without replacing a newer configuration.

    Preserve the legacy file, comments and credential paths. Only these two YAML
    files are imported: locks, active update jobs and shortcut icon caches must
    remain in place for older processes that may still be using them.
    """
    if destination.exists():
        return
    content = None
    legacy = legacy_config_file(destination)
    if legacy is not None:
        try:
            content = legacy.read_bytes()
        except FileNotFoundError:
            pass
    if content is None:
        content = yaml.safe_dump(defaults, sort_keys=False, allow_unicode=True).encode("utf-8")

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}-", suffix=".tmp", dir=destination.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Both operations publish a complete file and fail if another launch
            # has already initialized it. POSIX rename would overwrite that file.
            if os.name == "nt":
                os.rename(temporary, destination)
            else:
                os.link(temporary, destination)
        except FileExistsError:
            pass
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
