"""Read-only local privacy settings and a narrowly scoped, reversible fix."""

from datetime import datetime, timezone
import json
import os
import tempfile

from ..config_paths import config_dir
from . import config
from .proxy import http_proxy_url

POLICY_NAME = "WebRtcIPHandlingPolicy"
POLICY_VALUE = "disable_non_proxied_udp"
BROWSERS = ("chrome", "edge")
REPAIRS_FILE = config_dir() / "privacy-repairs.json"


class PrivacyError(ValueError):
    """A safe, user-facing diagnostic; never include proxy credentials."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _env_proxy(env):
    """Return the single valid HTTP(S) proxy carried by the environment."""
    seen = set()
    for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        value = env.get(key)
        if not value:
            continue
        try:
            seen.add(http_proxy_url(value))
        except Exception:
            return {"present": True, "url": None, "valid": False}
    if len(seen) > 1:
        return {"present": True, "url": None, "valid": False}
    return {"present": bool(seen), "url": next(iter(seen), None), "valid": True}


def _snapshot(backend):
    try:
        value = backend.privacy_snapshot()
    except Exception:
        value = None
    if not isinstance(value, dict):
        value = {}
    ipv6 = value.get("ipv6")
    if not isinstance(ipv6, dict):
        ipv6 = {"default": None, "tunnel": None}
    policies = value.get("policies")
    if not isinstance(policies, dict):
        policies = {}
    return {
        "supported": bool(value.get("supported")),
        "tun": value.get("tun") if value.get("tun") in (True, False) else None,
        "ipv6": {
            "default": ipv6.get("default") if ipv6.get("default") in (True, False) else None,
            "tunnel": ipv6.get("tunnel") if ipv6.get("tunnel") in (True, False) else None,
        },
        "policies": policies,
    }


def _proxy_mode(backend, snapshot, env_proxy):
    if snapshot["tun"] is True:
        return "tun"
    try:
        system = bool(backend.proxy_enabled())
    except Exception:
        system = False
    if system:
        return "system_proxy"
    if env_proxy["present"]:
        return "env_proxy"
    if snapshot["tun"] is False:
        return "direct"
    return "unknown"


def _policy_state(value):
    if value is None:
        return "unset"
    return {
        "disable_non_proxied_udp": "disabled",
        "default_public_interface_only": "public_only",
        "default_public_and_private_interfaces": "exposed",
        "default": "default",
    }.get(value, "custom")


def _normalize_policies(raw):
    browsers = {}
    for browser in BROWSERS:
        item = raw.get(browser) if isinstance(raw, dict) else None
        if not isinstance(item, dict):
            item = {}
        value = item.get("value")
        browsers[browser] = {
            "value": value if isinstance(value, str) and value else None,
            "source": item.get("source") if item.get("source") in ("user", "machine") else None,
            "state": item.get("state") if isinstance(item.get("state"), str) else _policy_state(value),
            "editable": bool(item.get("editable")),
        }
    return browsers


def inspect(backend, env=None):
    """Report local settings only; never probe HTTPS, DNS, UDP or WebRTC."""
    environment = dict(os.environ if env is None else env)
    snapshot = _snapshot(backend)
    mode = _proxy_mode(backend, snapshot, _env_proxy(environment))
    level = "unknown"
    reasons = ["仅检查本机设置，未验证浏览器 WebRTC、UDP 或 DNS 出口。"]
    if mode == "env_proxy":
        level = "warn"
        reasons.append("代理只配置在环境变量中，Windows 浏览器不会使用它；浏览器实际仍为直连。")
    policies = {"supported": snapshot["supported"],
                "browsers": _normalize_policies(snapshot["policies"])}
    if not policies["supported"]:
        reasons.append("当前平台暂不支持读取浏览器 WebRTC 策略。")
    else:
        machine = [browser for browser, item in policies["browsers"].items()
                   if item["source"] == "machine"]
        if machine:
            reasons.append("浏览器策略由组织管理：" + "、".join(machine) + "。")
    ipv6 = snapshot["ipv6"]
    if (ipv6["default"] is True and ipv6["tunnel"] is False
            and mode in ("system_proxy", "tun", "unknown")):
        reasons.append("检测到非隧道 IPv6 默认路由；WebRTC 可能通过 IPv6 绕过代理。")
        level = "warn"
    return {"checked_at": _now(), "level": level, "mode": mode,
            "https": {"ok": False}, "udp": {"ok": False}, "consistent": None,
            "policies": policies, "ipv6": ipv6, "reasons": reasons}


def unknown_report(reason="检查失败，请重试。"):
    return {"checked_at": _now(), "level": "unknown", "mode": "unknown",
            "https": {"ok": False}, "udp": {"ok": False}, "consistent": None,
            "policies": {"supported": False, "browsers": _normalize_policies({})},
            "ipv6": {"default": None, "tunnel": None}, "reasons": [reason]}


def _load_repairs():
    with config.CONFIG_LOCK:
        try:
            raw = REPAIRS_FILE.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except UnicodeError:
            raise PrivacyError("修复记录损坏，无法还原。") from None
        except OSError:
            raise PrivacyError("无法读取修复记录。") from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise PrivacyError("修复记录损坏，无法还原。") from None
    items = data.get("repairs") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items
            if isinstance(item, dict) and item.get("browser") in BROWSERS
            and isinstance(item.get("value"), str) and item.get("value")]


def _save_repairs(repairs):
    payload = {"version": 1, "repairs": repairs}
    with config.CONFIG_LOCK:
        REPAIRS_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=REPAIRS_FILE.parent,
                prefix=".privacy-", suffix=".tmp", delete=False,
            ) as stream:
                temporary = stream.name
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, REPAIRS_FILE)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


def list_repairs():
    return _load_repairs()


def apply(backend, browser, env=None):
    """Apply the single supported policy, recording the previous value."""
    if browser not in BROWSERS:
        raise PrivacyError("不支持的浏览器。")
    snapshot = _snapshot(backend)
    if not snapshot["supported"]:
        raise PrivacyError("当前平台暂不支持修改浏览器策略。")
    environment = dict(os.environ if env is None else env)
    mode = _proxy_mode(backend, snapshot, _env_proxy(environment))
    if mode == "tun":
        raise PrivacyError("TUN 模式下无需禁用 WebRTC。")
    if mode == "env_proxy":
        raise PrivacyError("代理只配置在环境变量中，Windows 浏览器不会使用；请先开启系统代理或 TUN。")
    if mode != "system_proxy":
        raise PrivacyError("未检测到系统代理；浏览器 WebRTC 不会绕过代理，无需修改。")

    # Refuse before touching the registry when the existing manifest cannot be
    # read: a policy without a restore record would be irreversible in the UI.
    existing = _load_repairs()
    try:
        result = backend.apply_webrtc_policy(browser, POLICY_VALUE)
    except PrivacyError:
        raise
    except ValueError as exc:
        raise PrivacyError(str(exc)) from None
    except Exception:
        raise PrivacyError("无法应用浏览器策略，请检查权限后重试。") from None
    if result.get("already"):
        return {"browser": browser, "already": True, "applied": False, "record": None}

    record = {
        "browser": browser,
        "value": POLICY_VALUE,
        "previous": result.get("previous") or {"exists": False, "value": None},
        "created_key": bool(result.get("created_key")),
        "applied_at": _now(),
    }
    repairs = [item for item in existing if item.get("browser") != browser]
    repairs.append(record)
    try:
        _save_repairs(repairs)
    except Exception:
        try:
            backend.restore_webrtc_policy(record)
        except Exception:
            pass
        raise PrivacyError("无法记录修复状态，已尝试撤销。") from None
    return {"browser": browser, "already": False, "applied": True, "record": record}


def restore(backend, browser):
    """Restore only the value this application wrote; never clobber a conflict."""
    if browser not in BROWSERS:
        raise PrivacyError("不支持的浏览器。")
    repairs = _load_repairs()
    record = next((item for item in repairs if item.get("browser") == browser), None)
    if record is None:
        raise PrivacyError("没有可还原的记录。")
    try:
        result = backend.restore_webrtc_policy(record)
    except ValueError as exc:
        raise PrivacyError(str(exc)) from None
    except Exception:
        raise PrivacyError("还原失败，请重试。") from None
    if not result.get("restored"):
        raise PrivacyError("当前策略已被其他设置修改，未覆盖。")
    _save_repairs([item for item in repairs if item.get("browser") != browser])
    return {"browser": browser, "restored": True}
