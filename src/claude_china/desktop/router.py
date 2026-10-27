"""Pre-launch measurements for a network routed by an upstream router.

These probes describe this process at one instant; they cannot enforce the
router's policy or prove what another application's browser and DNS use.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.client
import ipaddress
import os
import re
import socket
import ssl
import sys

from . import egress, process, safety, stun

HOSTS = {
    "claude": ("claude.ai", "api.anthropic.com"),
    "codex": ("chatgpt.com", "api.openai.com"),
    "grok-bot": ("grok.com", "api.x.ai"),
}
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


class _FamilyConnection(http.client.HTTPSConnection):
    def __init__(self, host, family):
        context = ssl.create_default_context()
        import certifi
        context.load_verify_locations(cafile=certifi.where())
        super().__init__(host, timeout=4, context=context)
        self.family = socket.AF_INET if family == 4 else socket.AF_INET6

    def connect(self):
        addresses = socket.getaddrinfo(self.host, self.port, self.family, socket.SOCK_STREAM)
        for family, kind, proto, _, address in addresses[:3]:
            sock = socket.socket(family, kind, proto)
            try:
                sock.settimeout(self.timeout)
                sock.connect(address)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except (OSError, ssl.SSLError):
                sock.close()
        raise OSError("service unreachable")


def trace_host(host, family):
    """Obtain the service's Cloudflare-observed exit, without proxy or redirects."""
    connection = _FamilyConnection(host, family)
    try:
        connection.request("GET", "/cdn-cgi/trace", headers={"User-Agent": "Claude-China-Environment-Check"})
        response = connection.getresponse()
        raw = response.read(8193)
        if response.status != 200 or len(raw) > 8192:
            raise ValueError("invalid trace response")
        values = dict(line.split("=", 1) for line in raw.decode("utf-8").splitlines() if "=" in line)
        address = ipaddress.ip_address(values.get("ip", ""))
        country = values.get("loc", "")
        if address.version != family or not address.is_global or country not in safety.ISO_COUNTRIES:
            raise ValueError("invalid trace fields")
        return {"ip": str(address), "country_code": country}
    finally:
        connection.close()


def stun_exit(family):
    """A same-address-family UDP probe; it is not a browser WebRTC test."""
    af = socket.AF_INET if family == 4 else socket.AF_INET6
    for host, port in stun.DEFAULT_SERVERS:
        try:
            addresses = socket.getaddrinfo(host, port, af, socket.SOCK_DGRAM)
        except OSError:
            continue
        for sock_family, kind, proto, _, address in addresses[:2]:
            try:
                with socket.socket(sock_family, kind, proto) as sock:
                    sock.settimeout(2)
                    sock.connect(address)
                    transaction = os.urandom(12)
                    sock.send(stun.build_request(transaction))
                    result = stun.parse_response(sock.recv(2048), transaction)
                    mapped = ipaddress.ip_address(result["ip"])
                    if mapped.version == family and mapped.is_global:
                        return str(mapped)
            except (OSError, ValueError):
                continue
    raise RouterError("无法取得 UDP 出口。")


def parse_dns_txt(value):
    fields = dict(re.findall(r'(?i)\b(remote_ip|country_code|asn)\s*:\s*([0-9A-Za-z:.]+)', value))
    address = ipaddress.ip_address(fields.get("remote_ip", ""))
    country = fields.get("country_code", "").upper()
    asn = int(fields.get("asn", ""))
    if not address.is_global or country not in safety.ISO_COUNTRIES or asn <= 0:
        raise ValueError("invalid DNS probe response")
    return {"ip": str(address), "country_code": country, "asn": asn}


def dns_probe():
    """Ask the system resolver for Cloudflare's resolver-observed TXT record.

    The resolver can cache the answer; browser DoH and per-domain DNS rules can
    use other resolvers. Treat this single sample as advisory, not leak proof.
    """
    result = process.run(["nslookup", "-type=TXT", "whoami.cloudflare.net"],
                         capture_output=True, timeout=6, check=True,
                         creationflags=process.CREATE_NO_WINDOW)
    return parse_dns_txt(result.stdout.decode("utf-8", errors="replace"))


def ipv6_default_route():
    """Distinguish no IPv6 default route from a failed Windows route query."""
    if sys.platform != "win32":
        return None
    script = ("$ErrorActionPreference='Stop'; "
              "$routes = @(Get-NetRoute -ErrorAction Stop | Where-Object { $_.DestinationPrefix -eq '::/0' }); "
              "if ($routes.Count -gt 0) { 'yes' } else { 'no' }")
    try:
        result = process.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, timeout=6, check=True,
                             creationflags=process.CREATE_NO_WINDOW)
        value = result.stdout.decode("utf-8", errors="replace").strip()
        return {"yes": True, "no": False}.get(value)
    except Exception:
        return None


def _probe(function, *args):
    try:
        return function(*args)
    except Exception:
        return None


def inspect(app_id, backend):
    """Compare each service and UDP exit; unavailable critical probes stay unknown."""
    hosts = HOSTS.get(app_id, ())
    report = {"app_id": app_id, "route": "路由器直连（启动时检测）",
              "checked_at": datetime.now(timezone.utc).isoformat(), "network": {},
              "environment": safety.local_environment(), **safety.assess_region(app_id, ""),
              "router": {"services": [], "udp4": {"status": "unknown"},
                         "udp6": {"status": "unknown"}, "dns": "unknown", "browser_webrtc": "unknown"}}
    if not hosts:
        return report
    try:
        ipv6_default = backend.privacy_snapshot().get("ipv6", {}).get("default")
    except Exception:
        ipv6_default = None
    if ipv6_default is None:
        ipv6_default = ipv6_default_route()
    families = (4, 6) if ipv6_default is True else (4,)
    with ThreadPoolExecutor(max_workers=7) as pool:
        traces = {(host, family): pool.submit(_probe, trace_host, host, family)
                  for family in families for host in hosts}
        udp = {family: pool.submit(_probe, stun_exit, family) for family in families}
        dns = pool.submit(_probe, dns_probe)
        values = {key: future.result() for key, future in traces.items()}
        udp_values = {family: future.result() for family, future in udp.items()}
        dns_value = dns.result()
    if isinstance(dns_value, dict) and dns_value.get("country_code"):
        report["router"]["dns"] = {**dns_value, "status": "warning" if dns_value["country_code"] in safety.BLOCKED_REGIONS else "observed"}
    unknown = ipv6_default is None
    mismatch = False
    unsupported = False
    for family in families:
        samples = []
        for host in hosts:
            value = values[(host, family)]
            item = {"host": host, "family": family, "status": "unknown"}
            if isinstance(value, dict) and value.get("ip") and value.get("country_code"):
                item.update(value, status="ok")
                samples.append(value)
                if safety.assess_region(app_id, value["country_code"])["status"] != "supported":
                    unsupported = True
                if not report["network"]:
                    report["network"] = {"ip": value["ip"], "country_code": value["country_code"]}
            else:
                unknown = True
            report["router"]["services"].append(item)
        if len({sample["ip"] for sample in samples}) > 1:
            mismatch = True
        mapped = udp_values[family]
        item = report["router"]["udp" + str(family)]
        if mapped and samples:
            item.update(ip=mapped, status="match" if all(v["ip"] == mapped for v in samples) else "mismatch")
            mismatch = mismatch or item["status"] == "mismatch"
        else:
            unknown = True
    if ipv6_default is False:
        report["router"]["udp6"]["status"] = "unavailable"
    if unsupported:
        report.update(status="unsupported", reason="服务出口位于禁止地区，已阻止启动。")
    elif mismatch:
        report.update(status="unsupported", reason="服务或 UDP 出口不一致，请检查路由器分流。")
    elif unknown:
        report.update(status="unknown", reason="无法完整确认服务、UDP 或 IPv6 出口。")
    else:
        report.update(status="supported", reason="本次服务与 UDP 出口一致；DNS 和浏览器 WebRTC 尚未验证。")
    return report


def allowed(report, settings):
    return safety.launch_allowed(report, settings)
