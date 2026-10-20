import os
from dataclasses import dataclass
from typing import Iterable, List, Protocol, runtime_checkable

# Lazy, cached psutil handle. NEVER import psutil at module top — that would
# force the [desktop] extra on every code path (install/uninstall, tests).
# Tests override this attribute directly: monkeypatch.setattr(base, "psutil", fake)
psutil = None


def _psutil():
    global psutil
    if psutil is None:
        import psutil as _real
        psutil = _real
    return psutil


@dataclass
class AppStatus:
    """Resolved launch/monitor info for one app on the current OS."""
    app_id: str
    found: bool = False
    direct: bool = False        # True = custom path (reliable env); False = OS broker
    launch_target: str = ""     # AUMID (win broker) | bundle (mac broker) | binary (direct)
    match_root: str = ""        # path prefix used to identify this app's processes

    @property
    def display_state(self) -> str:
        if not self.found:
            return "not_found"
        return "direct" if self.direct else "brokered"


def _matches(exe: str, root: str) -> bool:
    if not exe or not root:
        return False
    e = os.path.normcase(os.path.abspath(exe)).replace("\\", "/")
    r = os.path.normcase(os.path.abspath(root)).replace("\\", "/").rstrip("/")
    return e == r or e.startswith(r + "/")


def _ignored_exe_names(names: Iterable[str] = None) -> set:
    return {os.path.normcase(n) for n in (names or []) if n}


def _ignored_exe(exe: str, ignored_names: set) -> bool:
    name = exe.replace("\\", "/").rsplit("/", 1)[-1] if exe else ""
    return bool(name and os.path.normcase(name) in ignored_names)


def any_process_under(roots: List[str], ignored_names: Iterable[str] = None) -> bool:
    """True if any running process's exe lives under one of `roots`."""
    p = _psutil()
    real_roots = [r for r in roots if r]
    ignored = _ignored_exe_names(ignored_names)
    if not real_roots:
        return False
    for proc in p.process_iter(["exe"]):
        exe = proc.info.get("exe") or ""
        if _ignored_exe(exe, ignored):
            continue
        if any(_matches(exe, r) for r in real_roots):
            return True
    return False


def stop_processes_under(
    roots: List[str],
    timeout: float = 3.0,
    ignored_names: Iterable[str] = None,
) -> int:
    """Terminate (then kill stragglers) every process under `roots` + children.

    Returns the number of processes targeted. Steam-style whole-app stop.
    """
    p = _psutil()
    real_roots = [r for r in roots if r]
    ignored = _ignored_exe_names(ignored_names)
    if not real_roots:
        return 0

    victims = []
    for proc in p.process_iter(["exe"]):
        exe = proc.info.get("exe") or ""
        if _ignored_exe(exe, ignored):
            continue
        if any(_matches(exe, r) for r in real_roots):
            victims.append(proc)

    targets = list(victims)
    for proc in victims:
        try:
            targets.extend(proc.children(recursive=True))
        except Exception:
            pass

    for proc in targets:
        try:
            proc.terminate()
        except Exception:
            pass

    try:
        _gone, alive = p.wait_procs(targets, timeout=timeout)
    except Exception:
        alive = targets
    for proc in alive:
        try:
            proc.kill()
        except Exception:
            pass
    return len(targets)


@runtime_checkable
class PlatformBackend(Protocol):
    """Cross-OS contract. One implementation per supported platform."""
    def detect(self, app, override_path) -> "AppStatus":
        ...

    def launch(self, status: AppStatus, env: dict) -> None:
        ...

    def is_running(self, status: AppStatus) -> bool:
        ...

    def stop(self, status: AppStatus) -> None:
        ...

    def proxy_enabled(self) -> bool:
        ...

    def pick_path_filter(self) -> tuple:
        ...

    def create_shortcut(self) -> str:
        ...

    def remove_shortcut(self) -> list:
        ...
