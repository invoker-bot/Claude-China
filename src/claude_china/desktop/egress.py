"""Persistent, opt-in per-application proxy enforcement (Windows WFP).

WebRTC stays enabled. An installed guard permits only TCP to the pinned HTTP
proxy endpoint; all other outbound connections from covered binaries fail.
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


def _set_intent(app_id, enabled):
    with cfg.CONFIG_LOCK:
        data = cfg.load_desktop_config()
        values = data.get("network_guard")
        if not isinstance(values, dict):
            values = {}
        data["network_guard"] = {**values, app_id: bool(enabled)}
        cfg.save_desktop_config(data)


def _policy(backend, status):
    endpoint = proxy_endpoint(backend.system_http_proxy())
    route = backend.safety_proxy()
    if (not isinstance(route, dict) or not route.get("proxy")
            or proxy_endpoint(route["proxy"]) != endpoint):
        raise GuardError("网络防护需要 HTTP 与 HTTPS 使用同一个固定系统代理，请关闭 PAC 自动代理。")
    targets = backend.network_guard_targets(status)
    if not isinstance(targets, list) or not targets or len(targets) > 128:
        raise GuardError("无法确定应用的网络进程路径，未启用防护。")
    if any(not isinstance(path, str) or not os.path.isabs(path) or not path.lower().endswith(".exe")
           for path in targets):
        raise GuardError("应用网络进程路径无效，未启用防护。")
    return {"executables": sorted(set(targets), key=str.casefold), "proxy": endpoint}


def status(app_id, backend=None, detected=None, data=None, for_launch=False):
    get_app(app_id)
    intent = _intent(app_id, data)
    state = {"supported": supported(), "enabled": intent, "verified": False,
             "can_restore": intent, "can_apply": False, "proxy": None,
             "executables": [], "message": "系统网络防护目前仅支持 Windows。"}
    if not state["supported"]:
        return state
    try:
        store = _store()
        policies = store.read()
        policy = policies.get(app_id)
        state.update(enabled=bool(policy) or state["enabled"],
                     can_restore=bool(policy) or state["can_restore"])
        if policy:
            state.update(proxy=policy["proxy"], executables=policy["executables"])
        if for_launch and not state["enabled"]:
            return state
        desired = _policy(backend, detected) if backend and detected and detected.found else None
        state["can_apply"] = desired is not None
        if policy and desired == policy and store.verify(policies):
            state.update(verified=True, message="已保护此应用：仅允许连接指定代理，代理断开时禁止直连；WebRTC 保持启用。")
        elif state["enabled"]:
            state["message"] = "防护规则缺失，或代理、应用路径发生变化；启动已锁定，请重新应用或还原防护。"
        else:
            state["message"] = "尚未启用系统网络防护。"
    except Exception:
        state["message"] = "无法验证网络防护或固定代理地址；已启用的应用将禁止启动，仍可还原防护。"
    return state


def apply(app_id, backend, detected):
    get_app(app_id)
    if not supported():
        raise GuardError("系统网络防护目前仅支持 Windows。")
    if not detected.found:
        raise GuardError("未检测到应用，请先配置路径。")
    with _LOCK:
        try:
            policy = _policy(backend, detected)
            before = _store().read()
            policies = {**before, app_id: policy}
            _write(policies, before)
            try:
                _set_intent(app_id, True)
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
    get_app(app_id)
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
                data = cfg.load_desktop_config()
                values = data.get("network_guard")
                data["network_guard"] = {key: False for key in values} if isinstance(values, dict) else {}
                cfg.save_desktop_config(data)
        except Exception:
            if before:
                _write(before, {})
            raise GuardError("无法保存网络防护还原状态，已中止卸载。") from None
    return 0
