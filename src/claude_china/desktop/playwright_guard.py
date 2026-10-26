"""Protect cached Playwright browsers and gate new browser EXEs before spawn.

Playwright's Node driver is used by Node, Python, Java and .NET bindings.
NODE_OPTIONS loads our small spawn gate in the inherited CLI environment.
"""

import json
import os
from pathlib import Path
import re
import sys

from . import config as cfg, egress

TARGET = "playwright"
HELPER = "CLAUDEC_BROWSER_GUARD_HELPER"
HOOK = Path(__file__).parent / "ui" / "playwright-guard.cjs"


def discovery_environment(data=None):
    data = cfg.load_desktop_config() if data is None else data
    return {**os.environ, **{str(key): str(value) for key, value in cfg.get_common_env(data).items()}}


def discover(env=None, extra=None):
    env = os.environ if env is None else env
    configured = env.get("PLAYWRIGHT_BROWSERS_PATH")
    roots = []
    if configured and configured != "0":
        roots.append(Path(configured).expanduser())
    else:
        local = env.get("LOCALAPPDATA")
        if local:
            roots.append(Path(local) / "ms-playwright")
    targets = set()
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for release in root.iterdir():
            if (not release.is_dir() or release.is_symlink()
                    or not re.match(r"^(?:chromium|chromium_headless_shell|firefox|webkit)[-_]", release.name)):
                continue
            for directory, folders, files in os.walk(release, followlinks=False):
                folders[:] = [name for name in folders if not Path(directory, name).is_symlink()
                              and not getattr(os.path, "isjunction", lambda _: False)(str(Path(directory, name)))]
                for name in files:
                    path = Path(directory, name)
                    if name.lower().endswith(".exe") and not path.is_symlink():
                        targets.add(str(path.resolve(strict=True)))
    for value in extra or []:
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != ".exe":
            raise egress.GuardError("请选择已安装的 Playwright 浏览器 EXE。")
        targets.add(str(path))
    return sorted(targets, key=str.casefold)


def tunnel_live(tunnel):
    from .platforms.windows_tun import live
    return live(tunnel)


def check_browser(executable, store=None):
    store = egress._store() if store is None else store
    policies = store.read()
    policy = policies.get(TARGET)
    if not policy:
        if egress._intent(TARGET):
            raise egress.GuardError("Playwright 防护规则缺失，已阻止浏览器启动。")
        return
    try:
        target = os.path.normcase(str(Path(executable).resolve(strict=True)))
    except OSError:
        raise egress.GuardError("Playwright 浏览器路径无效，已阻止启动。") from None
    registered = {os.path.normcase(str(Path(path).resolve())) for path in policy["executables"]}
    if target not in registered:
        raise egress.GuardError("此 Playwright 浏览器尚未登记防护；请重新应用网络防护后重试。")
    if policy.get("mode") == "tun" and not tunnel_live(policy["tunnel"]):
        raise egress.GuardError("指定 TUN 隧道已断开或身份变化，已阻止浏览器启动。")
    if not store.verify(policies):
        raise egress.GuardError("无法验证 Playwright 防护规则，已阻止浏览器启动。")
    return policy


def prepare_environment(env, data=None):
    result = dict(env)
    # Remove only our own preload, preserving unrelated Node options.
    own_option = "--require=" + json.dumps(HOOK.resolve().as_posix())
    previous = result.get("NODE_OPTIONS", "").replace(own_option, "").strip()
    result.pop(HELPER, None)
    if previous:
        result["NODE_OPTIONS"] = previous
    else:
        result.pop("NODE_OPTIONS", None)
    if not egress._intent(TARGET, data):
        return result
    if not egress.supported():
        raise egress.GuardError("Playwright TUN 防护目前仅支持 Windows。")
    policies = egress._store().read()
    policy = policies.get(TARGET)
    if not policy or not egress._store().verify(policies):
        raise egress.GuardError("无法验证 Playwright 防护规则，已阻止 CLI 启动。")
    if policy.get("mode") == "tun" and not tunnel_live(policy["tunnel"]):
        raise egress.GuardError("指定 TUN 隧道已断开或身份变化，已阻止 CLI 启动。")
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command += ["-m", "claude_china.desktop.entry"]
    command.append("--network-guard-check-browser")
    result[HELPER] = json.dumps(command)
    result["NODE_OPTIONS"] = (previous + " --require=" + json.dumps(HOOK.resolve().as_posix())).strip()
    return result
