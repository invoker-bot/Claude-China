"""Shared settings location and one-time import from pre-claudec releases."""

import os
from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
from typing import Optional

import yaml


def config_dir() -> Path:
    return Path.home() / ".claudec"


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCK_STATE = threading.local()


def _thread_lock(key):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


@contextmanager
def settings_lock(destination):
    destination = Path(destination)
    key = os.path.normcase(os.path.abspath(str(destination)))
    with _thread_lock(key):
        depths = getattr(_LOCK_STATE, "depths", None)
        if depths is None:
            depths = _LOCK_STATE.depths = {}
        if key in depths:
            depths[key] += 1
            try:
                yield
            finally:
                depths[key] -= 1
            return
        depths[key] = 1
        try:
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            lock_path = destination.with_name(destination.name + ".lock")
            with open(lock_path, "a+b") as stream:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0, os.SEEK_END)
                    if not stream.tell():
                        stream.write(b"\0")
                        stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    stream.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            depths.pop(key, None)


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
