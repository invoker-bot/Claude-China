"""Read-only environment checks and a fail-closed regional launch guard."""

import base64
from datetime import date, datetime, timezone
import http.client
import ipaddress
import json
import re
import ssl
from urllib.parse import unquote, urlsplit

from .proxy import http_proxy_url
from .regions import CLAUDE_COUNTRIES, CODEX_COUNTRIES, ISO_COUNTRIES, MAX_AGE_DAYS, REVIEWED_ON, SOURCES
from .safety_local import local_environment

IP_HOST = "ipwho.is"
IP_PATH = "/?fields=success,ip,country,country_code,region"
MAX_RESPONSE = 16384
SERVICE_DOMAINS = {
    "claude": ("claude.ai", "claude.com", "anthropic.com"),
    "codex": ("chatgpt.com", "openai.com", "oaistatic.com", "oaiusercontent.com"),
    "grok-bot": ("grok.com", "x.ai", "x.com"),
}


class SafetyCheckError(ValueError):
    """Safe diagnostics only; never include URLs, credentials or raw errors."""


def assess_region(app_id, country_code, today=None):
    result = {"status": "unknown", "source": SOURCES.get(app_id, ""),
              "reviewed_on": REVIEWED_ON.isoformat()}
    age = ((today or date.today()) - REVIEWED_ON).days
    if not 0 <= age <= MAX_AGE_DAYS:
        result["reason"] = "地区规则已过期或系统日期异常，请更新启动器并核对系统日期。"
    elif app_id not in ("claude", "codex"):
        result["reason"] = "尚无可核验的 Grok Bot 官方地区清单，无法确认支持范围。"
    elif country_code not in ISO_COUNTRIES:
        result["reason"] = "无法识别出口 IP 的国家或地区。"
    elif country_code == "UA":
        result["reason"] = "该国家存在地区限制，仅凭国家级 IP 定位无法确认。"
    else:
        supported = country_code in (CLAUDE_COUNTRIES if app_id == "claude" else CODEX_COUNTRIES)
        result.update(status="supported" if supported else "unsupported",
                      reason="检测出口位于官方支持地区。" if supported else "检测出口不在官方支持地区清单中。")
    return result


def validate_bypass(value, app_id):
    # A country probe cannot establish the app's route when remote hosts can
    # bypass it. Local networks and unrelated domains do not affect the known
    # service domains. Unknown wildcard syntax is not guessed at.
    for host in re.split(r"[,;\s]+", value or ""):
        host = host.lower()
        if host.lower() in ("", "<local>", "localhost", "*.localhost", "127.0.0.1", "::1", "[::1]"):
            continue
        try:
            address = host
            if re.fullmatch(r"(?:\d{1,3}\.){1,3}\*", host):
                parts = host[:-2].split(".")
                address = ".".join(parts + ["0"] * (4 - len(parts))) + "/" + str(8 * len(parts))
            network = ipaddress.ip_network(address, strict=False)
            if network.is_loopback or network.is_private:
                continue
        except ValueError:
            domain = re.sub(r":\d+$", "", host).removeprefix("*.").lstrip(".")
            if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", domain) and not re.fullmatch(r"[0-9.]+", domain):
                if not any(domain == root or domain.endswith("." + root) or root.endswith("." + domain)
                           for root in SERVICE_DOMAINS.get(app_id, ())):
                    continue
        raise SafetyCheckError("代理排除列表可能影响应用服务域名，无法确认应用与检测请求使用同一出口。")


def select_route(env, backend, status):
    """Resolve a single static HTTPS route, rejecting ambiguity rather than guessing."""
    endpoints = set()
    explicitly_direct = False
    try:
        for key in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
            if env.get(key):
                endpoints.add(http_proxy_url(env[key]))
            elif key in env:
                explicitly_direct = True
        for key in ("no_proxy", "NO_PROXY"):
            validate_bypass(env.get(key, ""), status.app_id)
        system = backend.safety_proxy()
        system_proxy = http_proxy_url(system["proxy"]) if system.get("proxy") else None
        validate_bypass(system.get("bypass", ""), status.app_id)
    except SafetyCheckError:
        raise
    except Exception:
        raise SafetyCheckError("无法确认 HTTPS 代理出口；请检查系统代理与环境变量，PAC 或非 HTTP 代理暂不支持。") from None
    if not status.direct and endpoints and not system_proxy:
        raise SafetyCheckError("系统托管的应用可能不继承代理环境变量，无法确认其出口与检测请求一致。")
    if system_proxy:
        endpoints.add(system_proxy)
    if explicitly_direct and endpoints:
        raise SafetyCheckError("部分代理变量为空，可能绕过系统代理，无法确认单一出口。")
    if len(endpoints) > 1:
        aliases = [urlsplit(endpoint) for endpoint in endpoints]
        if (not all(parsed.hostname in ("localhost", "127.0.0.1", "::1") for parsed in aliases)
                or len({(parsed.port, parsed.username, parsed.password) for parsed in aliases}) != 1):
            raise SafetyCheckError("系统代理与环境变量存在多个不同入口，无法确认应用使用的出口。")
    proxy = system_proxy or next(iter(endpoints), None)
    return {"proxy": proxy, "aliases": sorted(endpoints - {proxy}),
            "label": "系统 HTTP 代理" if system_proxy else "环境变量 HTTP 代理" if proxy else "当前网络直连"}


def lookup_ip(proxy):
    """Bounded HTTPS request; no implicit env proxy, redirect or direct fallback."""
    connection = None
    try:
        context = ssl.create_default_context()
        # Frozen macOS apps cannot rely on the build machine's OpenSSL CA path.
        # Supplement (rather than replace) the OS trust store with bundled roots.
        import certifi
        context.load_verify_locations(cafile=certifi.where())
        if proxy:
            parsed = urlsplit(http_proxy_url(proxy))
            connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=8, context=context)
            headers = {}
            if parsed.username is not None:
                credentials = unquote(parsed.username) + ":" + unquote(parsed.password or "")
                headers["Proxy-Authorization"] = "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("ascii")
            connection.set_tunnel(IP_HOST, 443, headers=headers)
        else:
            connection = http.client.HTTPSConnection(IP_HOST, 443, timeout=8, context=context)
        connection.request("GET", IP_PATH, headers={"Accept": "application/json", "User-Agent": "Claude-China-Environment-Check"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError
        body = json.loads(raw)
        ip = ipaddress.ip_address(body.get("ip", ""))
        country = body.get("country_code")
        if body.get("success") is not True or not ip.is_global or country not in ISO_COUNTRIES:
            raise ValueError
        return {"ip": str(ip), "country_code": country,
                "country": str(body.get("country", country))[:120],
                "region": str(body.get("region", ""))[:120]}
    except Exception:
        raise SafetyCheckError("IP 地区查询失败或结果无效，请检查网络后重试。") from None
    finally:
        if connection:
            connection.close()


def inspect_environment(app_id, env, backend, status):
    report = {"app_id": app_id, "environment": local_environment(), "network": {},
              "route": "尚未确认", "checked_at": datetime.now(timezone.utc).isoformat(),
              **assess_region(app_id, "")}
    try:
        route = select_route(env, backend, status)
        report["route"] = route["label"]
        report["network"] = lookup_ip(route["proxy"])
        # localhost may resolve to a different IPv4/IPv6 listener. Do not assume
        # that equal port numbers mean an equal network exit.
        for alias in route["aliases"]:
            other = lookup_ip(alias)
            if any(other[key] != report["network"][key] for key in ("ip", "country_code")):
                raise SafetyCheckError("本地代理地址的检测出口不一致，无法确认地区支持状态。")
        # A changed OS proxy must not authorize a launch using a stale probe.
        if select_route(env, backend, status) != route:
            raise SafetyCheckError("检测期间系统代理发生变化，请重新检查。")
        report.update(assess_region(app_id, report["network"]["country_code"]))
    except SafetyCheckError as exc:
        report.update(status="unknown", reason=str(exc))
    except Exception:
        report.update(status="unknown", reason="环境检查失败，无法确认地区支持状态。")
    return report


def launch_allowed(report, settings):
    return report.get("status") == "supported" or (
        report.get("status") == "unknown" and not settings["block_unknown"])
