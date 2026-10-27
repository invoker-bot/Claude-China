"""Persistent, opt-in per-application proxy or tunnel enforcement (Windows WFP).

WebRTC stays enabled. Covered binaries can use only the pinned HTTP proxy or
the selected TUN interface; other outbound connections fail closed.
"""

from copy import deepcopy
import ipaddress
import os
import sys
import threading
from urllib.parse import urlsplit

from . import config as cfg
from .apps import get_app
from .proxy import http_proxy_url

_LOCK = threading.RLock()


def _target(app_id):
    if app_id != "playwright":
        get_app(app_id)


class GuardError(ValueError):
    """Safe diagnostic that never includes credentials or OS command output."""


def supported():
    return sys.platform == "win32"


def proxy_endpoint(value):
    try:
        parsed = urlsplit(http_proxy_url(value))
        if parsed.hostname == "localhost":
            addresses = ["127.0.0.1", "::1"]
        else:
            address = ipaddress.ip_address(parsed.hostname)
            if address.is_unspecified or address.is_multicast or address.is_link_local or "%" in str(address):
                raise ValueError
            addresses = [str(address)]
        return {"addresses": addresses, "port": parsed.port}
    except Exception:
        raise GuardError("网络防护需要固定 IP 或 localhost 的 HTTP 代理地址，请先配置系统代理。") from None


def _store():
    from .platforms.windows_wfp import Store
    return Store()


def _write(policies, expected=None):
    from .platforms.windows_wfp import write_policies
    write_policies(policies, expected)


def _intent(app_id, data=None):
    values = (cfg.load_desktop_config() if data is None else data).get("network_guard") or {}
    if not isinstance(values, dict):
        return True  # Invalid handwritten intent must not disable protection.
    return app_id in values and values[app_id] is not False


def _set_intent(app_id, enabled, updates=None):
    with cfg.CONFIG_LOCK:
        data = cfg.load_desktop_config()
        values = data.get("network_guard")
        if not isinstance(values, dict):
            values = {}
        data["network_guard"] = {**values, app_id: bool(enabled)}
        if updates:
            data.update(updates)
        cfg.save_desktop_config(data)


def _policy(backend, status, mode="proxy", tunnel_guid=None, custom_paths=None,
            include_cli=None, create_cli=False):
    if status.app_id == "playwright":
        from .playwright_guard import discover, discovery_environment
        data = cfg.load_desktop_config()
        paths = data.get("network_guard_browser_paths", []) if custom_paths is None else custom_paths
        targets = discover(discovery_environment(), extra=paths)
        if include_cli is None:
            include_cli = data.get("network_guard_include_cli") is True
        if include_cli:
            if mode != "tun":
                raise GuardError("CLI 网络防护需要指定 TUN 隧道。")
            from . import cli_guard
            targets += cli_guard.discover(create=create_cli)
    else:
        targets = backend.network_guard_targets(status)
    if not isinstance(targets, list) or not targets or len(targets) > 128:
        raise GuardError("未找到可保护的程序；请先安装 Playwright 浏览器或配置应用路径。")
    targets = sorted(set(targets), key=str.casefold)
    if mode == "tun":
        records = backend.network_guard_tunnels()
        current = next((item for item in records if item.get("guid") == tunnel_guid), None)
        if not current or not current.get("up") or not current.get("addresses"):
            raise GuardError("请选择已连接并分配地址的 TUN 隧道。")
        tunnel = {key: current[key] for key in ("guid", "luid", "index", "name", "addresses")}
        return {"mode": "tun", "executables": targets, "tunnel": tunnel}
    if mode != "proxy":
        raise GuardError("不支持的网络防护模式。")
    endpoint = proxy_endpoint(backend.system_http_proxy())
    route = backend.safety_proxy()
    if (not isinstance(route, dict) or not route.get("proxy")
            or proxy_endpoint(route["proxy"]) != endpoint):
        raise GuardError("网络防护需要 HTTP 与 HTTPS 使用同一个固定系统代理，请关闭 PAC 自动代理。")
    if any(not isinstance(path, str) or not os.path.isabs(path) or not path.lower().endswith(".exe")
           for path in targets):
        raise GuardError("应用网络进程路径无效，未启用防护。")
    return {"executables": sorted(set(targets), key=str.casefold), "proxy": endpoint}


def status(app_id, backend=None, detected=None, data=None, for_launch=False):
    _target(app_id)
    intent = _intent(app_id, data)
    state = {"supported": supported(), "enabled": intent, "verified": False,
             "can_restore": intent, "can_apply": False, "proxy": None,
             "executables": [], "message": "系统网络防护目前仅支持 Windows。"}
    state.update(mode="tun" if app_id == "playwright" else "proxy", tunnel=None, tunnels=[])
    state["found"] = bool(detected and detected.found)
    if app_id == "playwright":
        from .playwright_guard import discover, discovery_environment
        data = cfg.load_desktop_config()
        state["browser_paths"] = data.get("network_guard_browser_paths", [])
        state["include_cli"] = data.get("network_guard_include_cli") is True
        try:
            state["browser_count"] = len(discover(discovery_environment(), extra=state["browser_paths"]))
        except (OSError, GuardError, ValueError):
            state["browser_count"] = 0
    if not state["supported"]:
        return state
    try:
        store = _store()
        policies = store.read()
        policy = policies.get(app_id)
        if not for_launch:
            records = backend.network_guard_tunnels() if backend else []
            state["tunnels"] = records if isinstance(records, list) else []
        state.update(enabled=bool(policy) or state["enabled"],
                     can_restore=bool(policy) or state["can_restore"])
        if policy:
            state.update(proxy=policy.get("proxy"), executables=policy["executables"],
                         mode=policy.get("mode", "proxy"), tunnel=policy.get("tunnel"))
        if for_launch and not state["enabled"]:
            return state
        desired = _policy(backend, detected, state["mode"], (state["tunnel"] or {}).get("guid")) if backend and detected and detected.found else None
        state["can_apply"] = desired is not None
        if policy and desired == policy and store.verify(policies):
            state.update(verified=True, message="已保护此应用：仅允许连接指定代理，代理断开时禁止直连；WebRTC 保持启用。")
            if state["mode"] == "tun":
                state["message"] = "已保护此应用：TCP/UDP 仅允许通过指定 TUN 隧道，断开时禁止直连；WebRTC 保持启用。"
        elif state["enabled"]:
            state["message"] = "防护规则缺失，或代理、应用路径发生变化；启动已锁定，请重新应用或还原防护。"
        else:
            state["message"] = "尚未启用系统网络防护。"
    except Exception:
        state["message"] = "无法验证网络防护或固定代理地址；已启用的应用将禁止启动，仍可还原防护。"
    return state


def apply(app_id, backend, detected, options=None):
    _target(app_id)
    if not supported():
        raise GuardError("系统网络防护目前仅支持 Windows。")
    if not detected.found:
        raise GuardError("未检测到应用，请先配置路径。")
    with _LOCK:
        try:
            before = _store().read()
            options = options or {}
            saved = before.get(app_id, {})
            mode = options.get("mode", saved.get("mode", "tun" if app_id == "playwright" else "proxy"))
            guid = options.get("tunnel_guid", saved.get("tunnel", {}).get("guid"))
            include_cli = options.get("include_cli")
            if include_cli is not None and not isinstance(include_cli, bool):
                raise GuardError("CLI 网络防护设置无效。")
            policy = _policy(backend, detected, mode, guid, options.get("browser_paths"),
                             include_cli, create_cli=True)
            policies = {**before, app_id: policy}
            _write(policies, before)
            try:
                updates = {}
                if app_id == "playwright":
                    if "browser_paths" in options:
                        updates["network_guard_browser_paths"] = list(options["browser_paths"])
                    if include_cli is not None:
                        updates["network_guard_include_cli"] = include_cli
                _set_intent(app_id, True, updates)
            except Exception:
                _write(before, policies)
                raise GuardError("无法保存防护设置，已撤销本次修改。") from None
            # A readback failure must keep launch locked, even when filters
            # were installed successfully. Restore stays available in the UI.
            if not _store().verify(policies):
                raise GuardError("系统未确认防护规则生效，请重新应用防护。")
        except GuardError:
            raise
        except Exception:
            raise GuardError("无法应用系统网络防护，请检查管理员授权与 Windows 网络筛选服务。") from None
    return status(app_id, backend, detected)


def restore(app_id):
    _target(app_id)
    if not supported():
        raise GuardError("系统网络防护目前仅支持 Windows。")
    with _LOCK:
        try:
            policies = _store().read()
            before = deepcopy(policies)
            policies.pop(app_id, None)
            _write(policies, before)
            try:
                _set_intent(app_id, False)
            except Exception:
                _write(before, policies)
                raise GuardError("无法保存还原设置，已恢复原有防护。") from None
        except GuardError:
            raise
        except Exception:
            raise GuardError("无法还原系统网络防护，请检查管理员授权后重试。") from None


def ensure(app_id, backend, detected, data=None):
    """Launch-time verification remains mandatory even if region checks are off."""
    if not _intent(app_id, data):
        return {"enabled": False, "verified": False}
    state = status(app_id, backend, detected, data=data, for_launch=True)
    if state["enabled"] and not state["verified"]:
        raise GuardError(state["message"])
    return state


def tun_enabled(app_id, data):
    if not _intent(app_id, data):
        return False
    try:
        return _store().read().get(app_id, {}).get("mode") == "tun"
    except Exception:
        raise GuardError("无法验证系统网络防护，已取消启动。") from None


def uninstall():
    """Remove only this user's owned provider before deleting the launcher."""
    if not supported():
        return 0
    with _LOCK:
        before = _store().read()
        if before:
            _write({}, before)
        try:
            with cfg.CONFIG_LOCK:
                if cfg.DESKTOP_CONFIG_FILE.exists():
                    data = cfg.load_desktop_config()
                    values = data.get("network_guard")
                    if isinstance(values, dict) and any(value is not False for value in values.values()):
                        data["network_guard"] = {key: False for key in values}
                        cfg.save_desktop_config(data)
                    elif values and not isinstance(values, dict):
                        data["network_guard"] = {}
                        cfg.save_desktop_config(data)
        except Exception:
            if before:
                _write(before, {})
            raise GuardError("无法保存网络防护还原状态，已中止卸载。") from None
    return 0
