"""Minimal STUN binding client for the local UDP egress check.

The desktop privacy check compares the HTTPS exit IP with the IP a STUN
server sees over UDP. WebRTC uses the same UDP path, so a mismatch is a
useful heuristic for "the browser may bypass the HTTP proxy". This is not a
WebRTC implementation and must not be presented as a browser-level test.
"""

import ipaddress
import os
import socket
import struct

MAGIC_COOKIE = 0x2112A442
BINDING_REQUEST = 0x0001
BINDING_SUCCESS = 0x0101
BINDING_ERROR = 0x0111
ATTR_XOR_MAPPED_ADDRESS = 0x0020
ATTR_MAPPED_ADDRESS = 0x0001

# Two independent servers keep the check useful when one is blocked. The
# query is opt-in from the UI; it sends a single UDP packet per server.
DEFAULT_SERVERS = (
    ("stun.cloudflare.com", 3478),
    ("stun.l.google.com", 19302),
)


class StunError(ValueError):
    """A safe diagnostic; never include host credentials or raw payloads."""


def build_request(transaction_id):
    if not isinstance(transaction_id, (bytes, bytearray)) or len(transaction_id) != 12:
        raise StunError("invalid STUN transaction id")
    return struct.pack("!HHI", BINDING_REQUEST, 0, MAGIC_COOKIE) + bytes(transaction_id)


def parse_response(data, transaction_id):
    """Return {"ip": str, "port": int} from a binding success response."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 20:
        raise StunError("truncated STUN response")
    if len(transaction_id) != 12:
        raise StunError("invalid STUN transaction id")
    message_type, message_length, cookie = struct.unpack("!HHI", data[:8])
    if cookie != MAGIC_COOKIE or data[8:20] != transaction_id:
        raise StunError("STUN response does not match the request")
    if message_type == BINDING_ERROR:
        raise StunError("STUN server returned an error")
    if message_type != BINDING_SUCCESS:
        raise StunError("unexpected STUN message type")
    end = 20 + message_length
    if end > len(data):
        raise StunError("truncated STUN attributes")
    offset = 20
    while offset + 4 <= end:
        attribute_type, attribute_length = struct.unpack("!HH", data[offset:offset + 4])
        offset += 4
        value_end = offset + attribute_length
        if value_end > end:
            raise StunError("truncated STUN attribute")
        value = data[offset:value_end]
        offset += (attribute_length + 3) & ~3
        if attribute_type == ATTR_XOR_MAPPED_ADDRESS:
            return _decode_xor_mapped(value, transaction_id)
        if attribute_type == ATTR_MAPPED_ADDRESS:
            return _decode_mapped(value)
    raise StunError("STUN response has no mapped address")


def _decode_xor_mapped(value, transaction_id):
    if len(value) < 4:
        raise StunError("truncated XOR-MAPPED-ADDRESS")
    family = value[1]
    port = struct.unpack("!H", value[2:4])[0] ^ (MAGIC_COOKIE >> 16)
    if family == 0x01:
        if len(value) < 8:
            raise StunError("truncated IPv4 XOR-MAPPED-ADDRESS")
        raw = struct.unpack("!I", value[4:8])[0] ^ MAGIC_COOKIE
        return {"ip": str(ipaddress.IPv4Address(raw)), "port": port}
    if family == 0x02:
        if len(value) < 20:
            raise StunError("truncated IPv6 XOR-MAPPED-ADDRESS")
        mask = struct.pack("!I", MAGIC_COOKIE) + bytes(transaction_id)
        raw = bytes(left ^ right for left, right in zip(value[4:20], mask))
        return {"ip": str(ipaddress.IPv6Address(raw)), "port": port}
    raise StunError("unsupported STUN address family")


def _decode_mapped(value):
    if len(value) < 4:
        raise StunError("truncated MAPPED-ADDRESS")
    family = value[1]
    port = struct.unpack("!H", value[2:4])[0]
    if family == 0x01:
        if len(value) < 8:
            raise StunError("truncated IPv4 MAPPED-ADDRESS")
        return {"ip": str(ipaddress.IPv4Address(value[4:8])), "port": port}
    if family == 0x02:
        if len(value) < 20:
            raise StunError("truncated IPv6 MAPPED-ADDRESS")
        return {"ip": str(ipaddress.IPv6Address(value[4:20])), "port": port}
    raise StunError("unsupported STUN address family")


def query(server, port=3478, timeout=2.0):
    """Send one binding request and return the mapped address."""
    transaction_id = os.urandom(12)
    request = build_request(transaction_id)
    try:
        addresses = socket.getaddrinfo(server, port, socket.AF_UNSPEC, socket.SOCK_DGRAM)
    except OSError:
        raise StunError("STUN server could not be resolved") from None
    last_error = None
    for family, _type, _proto, _canon, sockaddr in addresses:
        sock = None
        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(request, sockaddr)
            data, _peer = sock.recvfrom(2048)
            result = parse_response(data, transaction_id)
            result["server"] = f"{server}:{port}"
            return result
        except (OSError, StunError) as exc:
            last_error = exc
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
    raise StunError("STUN query failed") from last_error


def query_any(servers=None, timeout=2.0):
    """Try each server in order; return the first mapped address."""
    for server, port in (servers or DEFAULT_SERVERS):
        try:
            return query(server, port, timeout=timeout)
        except (OSError, StunError):
            continue
    raise StunError("no STUN server responded")
