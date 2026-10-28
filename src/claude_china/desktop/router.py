"""Pre-launch country checks for an upstream router."""

from datetime import datetime, timezone

from . import egress, safety

APPS = frozenset(safety.SERVICE_DOMAINS)
PROXY_KEYS = frozenset(("http_proxy", "https_proxy", "all_proxy", "no_proxy"))


class RouterError(ValueError):
    """A safe diagnostic without credentials or raw network errors."""


def direct_environment(env):
    result = {key: value for key, value in env.items() if key.lower() not in PROXY_KEYS}
    result.update({"NO_PROXY": "*", "no_proxy": "*"})
    return result


def check_ready(target, data, backend, allow_router_guard=False):
    # A system proxy may be used by Electron/Chromium despite cleared env vars.
    try:
        system = backend.safety_proxy()
        if not isinstance(system, dict) or system.get("proxy"):
            raise RouterError("路由器模式要求关闭本机系统代理，请先关闭后重试。")
    except RouterError:
        raise
    except Exception:
        raise RouterError("无法确认系统代理状态，请关闭自动代理后重试。") from None
    if not egress.supported():
        return
    try:
        if egress._intent(target, data) or target in egress._store().read():
            raise RouterError("该对象仍有系统网络防护，请先在安全检查中还原网络防护。")
        if target in ('claude', 'playwright'):
            from . import router_guardian
            state = router_guardian.status(target)
            if state['enabled'] and (not allow_router_guard or state.get('state') != 'healthy'):
                raise RouterError("该对象仍有路由器运行防护，请先在安全检查中还原。")
    except RouterError:
        raise
    except Exception:
        raise RouterError("无法验证现有系统网络防护，请先检查或还原防护。") from None


def inspect(app_id, backend):
    """Query one independent country service without contacting target services."""
    report = {"app_id": app_id, "route": "路由器直连（启动时检测）",
              "checked_at": datetime.now(timezone.utc).isoformat(), "network": {},
              "environment": safety.local_environment(), **safety.assess_region(app_id, ""),
              "router": {"browser_webrtc": "unknown"}}
    if app_id not in APPS:
        return report
    try:
        report["network"] = safety.lookup_ip(None)
        report.update(safety.assess_region(app_id, report["network"]["country_code"]))
    except Exception:
        report.update(status="unknown", reason="无法确认出口国家或地区。")
    return report


def allowed(report, settings):
    return safety.launch_allowed(report, settings)
