"""Experimental Grok Bot launch gate. Not installed or enabled by the product.

The IFEO experiment is deliberately limited to one exact Grok Bot executable.
Use --manifest FILE -- TARGET [ARGS...] as its debugger command. The separate
PowerShell helper owns the temporary registration and rollback. Diagnostics
contain decisions and process IDs, never environment values or launch arguments.
"""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claude_china.desktop.apps import get_app
from claude_china.desktop.bridge import LauncherBridge
from claude_china.desktop.platforms.base import AppStatus
from claude_china.desktop.platforms.windows import WindowsBackend
from claude_china.desktop.process import external_environment


def launch_detached_debugger(argv, env, cwd):
    """Create suspended under a debugger, detach, then allow first execution.

    DEBUG_ONLY_THIS_PROCESS prevents recursive IFEO redirection of this launch;
    descendants still use normal Windows creation. Whether the changed process
    identity is compatible with Electron children is a measured result, not an
    assumption. Never temporarily remove the IFEO key to avoid recursion.
    """
    if sys.platform != "win32":
        raise OSError("This probe requires Windows")
    import _winapi

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.DebugActiveProcessStop.argtypes = [wintypes.DWORD]
    kernel.DebugActiveProcessStop.restype = wintypes.BOOL
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    # Keep default kill-on-debugger-exit until detach succeeds. On any failure
    # the suspended process is terminated; no unchecked launch fallback exists.
    flags = 0x00000002 | 0x00000004 | 0x00000400  # DEBUG_ONLY_THIS_PROCESS, SUSPENDED, UNICODE
    process, thread, pid, _tid = _winapi.CreateProcess(
        argv[0], subprocess.list2cmdline(argv), None, None, False, flags,
        external_environment(env), cwd, subprocess.STARTUPINFO(),
    )
    try:
        if not kernel.DebugActiveProcessStop(pid):
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel.ResumeThread(thread) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return pid
    except BaseException:
        _winapi.TerminateProcess(process, 1)
        raise
    finally:
        _winapi.CloseHandle(thread)
        _winapi.CloseHandle(process)


class _ProbeBackend(WindowsBackend):
    def __init__(self, target, argv, spawn, isolated_profile, marker):
        self.target = str(target)
        self.argv = list(argv)
        self.spawn = spawn
        self.isolated_profile = isolated_profile
        self.marker = marker
        self.pid = None

    def detect(self, app, override_path=None):
        if app.id != "grok-bot":
            raise ValueError("Only Grok Bot is in scope")
        return AppStatus(app.id, found=Path(self.target).is_file(), direct=True,
                         launch_target=self.target, match_root=self.target)

    def stop(self, status):
        # An original shortcut or deep link must not kill an existing app.
        pass

    def launch(self, status, env):
        env = dict(env)
        if self.marker:
            env["CLAUDEC_TAKEOVER_PROBE"] = self.marker
        if self.isolated_profile:
            env["SAND_USER_DATA_DIR"] = str(self.isolated_profile)
        try:
            self.pid = self.spawn(self.argv, env, os.getcwd())
        except Exception:
            raise RuntimeError("启动接管实验未能创建进程，已取消启动。") from None


def gated_launch(target, argv, *, launch=launch_detached_debugger,
                 isolated_profile=None, test_allow=False, marker=None):
    """Reuse real launcher preflight without changing settings or stopping apps."""
    target = Path(target).resolve(strict=True)
    if target.name.lower() != "grok bot.exe":
        raise ValueError("Only Grok Bot is in scope")
    if not argv or Path(argv[0]).resolve() != target:
        raise ValueError("Unexpected takeover target")
    if test_allow and not isolated_profile:
        raise ValueError("An isolated profile is required for a test override")
    backend = _ProbeBackend(target, argv, launch, isolated_profile, marker)
    bridge = LauncherBridge(backend, [get_app("grok-bot")])
    if test_allow:
        # Explicit, experiment-only permission. Never persisted to desktop.yaml.
        bridge._check_safety = lambda *args: {
            "status": "test_override", "allowed": True,
            "reason": "Explicitly permitted isolated mechanism test; not regional approval.",
        }
    result = bridge.launch_app("grok-bot")
    result.update(pid=backend.pid, test_override=bool(test_allow))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("target_args", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    manifest = json.loads(options.manifest.read_text(encoding="utf-8-sig"))
    target_args = options.target_args
    if target_args[:1] == ["--"]:
        target_args = target_args[1:]
    audit = options.manifest.parent / "events"
    audit.mkdir(exist_ok=True)
    event = {"broker_pid": os.getpid(), "parent_pid": os.getppid(), "time": time.time(),
             "cwd_preserved": os.getcwd() == manifest.get("expected_cwd", os.getcwd()),
             "child_type": next((arg.split("=", 1)[1] for arg in target_args
                                 if arg.startswith("--type=")), "main")}
    try:
        if sys.platform != "win32":
            raise RuntimeError("Windows required")
        if ctypes.windll.shell32.IsUserAnAdmin():
            raise RuntimeError("Do not run the target elevated")
        if time.time() >= manifest["expires_at"]:
            raise RuntimeError("Experiment expired; restore the registration")
        result = gated_launch(manifest["target"], target_args,
                              isolated_profile=manifest.get("isolated_profile"),
                              test_allow=manifest.get("test_allow") is True,
                              marker=manifest.get("marker"))
        event.update(ok=result["ok"], target_pid=result["pid"],
                     test_override=result["test_override"],
                     decision=result.get("safety", {}).get("status", "blocked"),
                     error=result.get("error", ""))
    except Exception as exc:
        event.update(ok=False, error="Takeover probe failed closed", error_type=type(exc).__name__)
    (audit / (str(os.getpid()) + ".json")).write_text(
        json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if event.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
