"""Protect managed CLI processes without restricting a shared Node runtime."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from ..config_paths import config_dir
from . import config as cfg, egress, playwright_guard

CLI_GUARD = "CLAUDEC_CLI_GUARD"


def runtime_dir():
    return config_dir() / "guarded-cli"


def _digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guarded_node(source, create=False):
    """Use a dedicated executable path so unrelated Node processes are unaffected."""
    try:
        source = Path(source).resolve(strict=True)
        fingerprint = _digest(source)
        target = runtime_dir() / fingerprint / "node.exe"
        if target.is_file() and not target.is_symlink() and _digest(target) == fingerprint:
            return target.resolve()
        if not create:
            raise egress.GuardError("CLI 运行时已变化，请重新应用网络防护。")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".node-", delete=False) as dest:
                temporary = Path(dest.name)
                with source.open("rb") as src:
                    shutil.copyfileobj(src, dest, 1024 * 1024)
                dest.flush()
                os.fsync(dest.fileno())
            if _digest(temporary) != fingerprint:
                raise egress.GuardError("CLI 运行时在复制期间发生变化，请重试。")
            os.replace(temporary, target)
            return target.resolve(strict=True)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except egress.GuardError:
        raise
    except OSError:
        raise egress.GuardError("无法准备受保护的 CLI 运行时。") from None


def _codex_binaries(entry):
    package = Path(entry).resolve().parent.parent
    roots = [package / "node_modules" / "@openai" / "codex-win32-x64",
             package.parent / "codex-win32-x64", package]
    for root in roots:
        binary = root / "vendor" / "x86_64-pc-windows-msvc" / "bin" / "codex.exe"
        if binary.is_file():
            yield binary.resolve()


def _grok_binaries():
    from .. import config as cli_config

    homes = {Path.home() / ".grok"}
    for profile in cli_config.load_config().get("profiles", {}).values():
        if isinstance(profile, dict) and profile.get("type") == "grok" and profile.get("credentials_path"):
            homes.add(Path(profile["credentials_path"]).expanduser())
    for home in homes:
        binary = home / "bin" / "grok.exe"
        if binary.is_file():
            yield binary.resolve()


def discover(create=False):
    """Find current CLI executables and the private Node wrapper, without credentials."""
    from .terminal_host import resolve_cli_argv

    targets = set()
    for kind in ("claude", "codex", "grok"):
        try:
            argv = resolve_cli_argv(kind)
        except ValueError:
            continue
        if not argv:
            continue
        program = Path(argv[0])
        if program.name.lower() == "node.exe":
            targets.add(str(guarded_node(program, create=create)))
            if kind == "codex" and len(argv) > 1:
                targets.update(str(path) for path in _codex_binaries(argv[1]))
            if kind == "grok":
                targets.update(str(path) for path in _grok_binaries())
        elif program.suffix.lower() == ".exe" and program.is_file():
            targets.add(str(program.resolve()))
    if not targets:
        raise egress.GuardError("未找到可保护的 CLI，请先安装 CLI。")
    return sorted(targets, key=str.casefold)


def enabled(data):
    return (egress._intent("playwright", data) and "network_guard_include_cli" in data
            and data["network_guard_include_cli"] is not False)


def prepare(argv, env, data=None):
    """Fail closed and route managed CLI processes through their registered TUN."""
    data = cfg.load_desktop_config() if data is None else data
    if not enabled(data):
        result = dict(env)
        result.pop(CLI_GUARD, None)
        return list(argv), result
    if not argv:
        raise egress.GuardError("CLI 启动路径无效，已阻止启动。")
    required_hook = "--require=" + json.dumps(playwright_guard.HOOK.resolve().as_posix())
    if not env.get(playwright_guard.HELPER) or required_hook not in env.get("NODE_OPTIONS", ""):
        raise egress.GuardError("CLI 启动检查未加载，已阻止启动。")
    target = Path(argv[0])
    if target.name.lower() == "node.exe":
        target = guarded_node(target)
    policy = playwright_guard.check_browser(str(target))
    if not policy or policy.get("mode") != "tun":
        raise egress.GuardError("CLI 网络防护需要已连接的 TUN 隧道。")
    result = {key: value for key, value in env.items()
              if key.lower() not in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")}
    result.update({CLI_GUARD: "1", "NO_PROXY": "*", "no_proxy": "*"})
    return [str(target)] + list(argv[1:]), result
