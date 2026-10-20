"""Strict conversion of a static system HTTP proxy to a launch environment URL."""

import ipaddress
import re
from urllib.parse import urlsplit


class SystemProxyError(ValueError):
    """A safe, user-facing error; never include a raw URL or credentials."""


def _host(value):
    try:
        if ":" in value:
            return "[" + str(ipaddress.IPv6Address(value)) + "]"
        hostname = value.encode("idna").decode("ascii").lower()
        labels = hostname.rstrip(".").split(".")
        if len(hostname) > 253 or not all(re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
            raise ValueError
        if re.fullmatch(r"[0-9.]+", hostname):
            ipaddress.IPv4Address(hostname)
        return hostname
    except (ValueError, UnicodeError):
        raise SystemProxyError("系统代理的主机地址无效。") from None


def http_proxy_url(value):
    """Accept host[:port] or http:// URLs, including bracketed IPv6.

    HTTP's default port is 80. PAC, SOCKS, HTTPS-to-proxy and URL paths are
    deliberately unsupported, rather than silently treated as direct access.
    """
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SystemProxyError("系统代理地址为空或包含无效字符。")
    value = value.strip()
    if not value or any(c.isspace() for c in value) or any(c in value for c in "\\?#"):
        raise SystemProxyError("系统代理地址格式无效，请使用 HTTP 代理地址。")
    try:
        parsed = urlsplit(value if "://" in value else "http://" + value)
        if parsed.scheme != "http":
            raise SystemProxyError("自动添加仅支持 HTTP 代理，不支持 SOCKS、HTTPS 代理或 PAC 脚本。")
        if parsed.path not in ("", "/") or not parsed.hostname:
            raise ValueError
        port = parsed.port
        if parsed.netloc.endswith(":") or port == 0:
            raise ValueError
        userinfo, separator, _ = parsed.netloc.rpartition("@")
        if separator and not re.fullmatch(r"(?:[A-Za-z0-9._~!$&'()*+,;=:-]|%[0-9A-Fa-f]{2})+", userinfo):
            raise ValueError
        host = _host(parsed.hostname)
    except SystemProxyError:
        raise
    except ValueError:
        raise SystemProxyError("系统代理格式无效，请检查主机地址和端口（1–65535）。") from None
    return "http://" + (userinfo + "@" if separator else "") + host + ":" + str(port or 80)


def http_proxy_address(host, port):
    """Convert separate OS host/port fields without accepting URLs as hosts."""
    if not isinstance(host, str) or not host or not re.fullmatch(r"[0-9]+", str(port)):
        raise SystemProxyError("系统 HTTP 代理缺少有效的主机地址或端口。")
    if host.startswith("[") and host.endswith("]") and ":" in host:
        host = host[1:-1]
    return http_proxy_url(_host(host) + ":" + str(port))
