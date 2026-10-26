import ipaddress
import socket
import struct

import pytest

from src.claude_china.desktop import stun


def _xor_response(transaction_id, ip, port=54321):
    address = ipaddress.ip_address(ip)
    if address.version == 4:
        family = 1
        raw = struct.pack("!I", int(address) ^ stun.MAGIC_COOKIE)
    else:
        family = 2
        mask = struct.pack("!I", stun.MAGIC_COOKIE) + transaction_id
        raw = bytes(left ^ right for left, right in zip(address.packed, mask))
    value = b"\x00" + bytes([family]) + struct.pack("!H", port ^ (stun.MAGIC_COOKIE >> 16)) + raw
    attribute = struct.pack("!HH", stun.ATTR_XOR_MAPPED_ADDRESS, len(value)) + value
    return struct.pack("!HHI", stun.BINDING_SUCCESS, len(attribute), stun.MAGIC_COOKIE) + transaction_id + attribute


def _mapped_response(transaction_id, ip, port=1234):
    address = ipaddress.ip_address(ip)
    family = 1 if address.version == 4 else 2
    value = b"\x00" + bytes([family]) + struct.pack("!H", port) + address.packed
    attribute = struct.pack("!HH", stun.ATTR_MAPPED_ADDRESS, len(value)) + value
    return struct.pack("!HHI", stun.BINDING_SUCCESS, len(attribute), stun.MAGIC_COOKIE) + transaction_id + attribute


def test_build_request_has_binding_header_and_transaction_id():
    transaction_id = b"123456789012"
    request = stun.build_request(transaction_id)
    assert len(request) == 20
    assert struct.unpack("!HHI", request[:8]) == (stun.BINDING_REQUEST, 0, stun.MAGIC_COOKIE)
    assert request[8:] == transaction_id


@pytest.mark.parametrize("transaction_id", [b"", b"short", b"x" * 13, None, "x" * 12])
def test_build_request_rejects_invalid_transaction_id(transaction_id):
    with pytest.raises(stun.StunError):
        stun.build_request(transaction_id)


@pytest.mark.parametrize("ip", ["203.0.113.7", "198.51.100.9"])
def test_parse_xor_mapped_ipv4(ip):
    transaction_id = b"abcdefghijkl"
    assert stun.parse_response(_xor_response(transaction_id, ip), transaction_id) == {
        "ip": ip, "port": 54321}


def test_parse_xor_mapped_ipv6():
    transaction_id = b"abcdefghijkl"
    ip = "2001:db8::42"
    assert stun.parse_response(_xor_response(transaction_id, ip), transaction_id) == {
        "ip": ip, "port": 54321}


def test_parse_plain_mapped_address_fallback():
    transaction_id = b"abcdefghijkl"
    assert stun.parse_response(_mapped_response(transaction_id, "203.0.113.8"), transaction_id) == {
        "ip": "203.0.113.8", "port": 1234}


@pytest.mark.parametrize("payload", [
    b"",
    b"\x00" * 19,
    struct.pack("!HHI", stun.BINDING_SUCCESS, 0, 0xDEADBEEF) + b"abcdefghijkl",
    struct.pack("!HHI", stun.BINDING_SUCCESS, 0, stun.MAGIC_COOKIE) + b"aaaaaaaaaaaa",
    struct.pack("!HHI", stun.BINDING_ERROR, 0, stun.MAGIC_COOKIE) + b"abcdefghijkl",
    struct.pack("!HHI", stun.BINDING_SUCCESS, 0, stun.MAGIC_COOKIE) + b"abcdefghijkl",
])
def test_parse_rejects_malformed_or_mismatched_responses(payload):
    with pytest.raises(stun.StunError):
        stun.parse_response(payload, b"abcdefghijkl")


def test_query_sends_one_packet_and_returns_mapped_address(monkeypatch):
    sent = {}

    class FakeSocket:
        def __init__(self, family, kind):
            self.family, self.kind = family, kind

        def settimeout(self, value):
            sent["timeout"] = value

        def sendto(self, payload, address):
            sent["payload"] = payload
            sent["address"] = address

        def recvfrom(self, size):
            transaction_id = sent["payload"][8:20]
            return _xor_response(transaction_id, "203.0.113.10"), ("203.0.113.10", 3478)

        def close(self):
            sent["closed"] = True

    monkeypatch.setattr(stun.socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_DGRAM, 6, "", ("203.0.113.10", 3478)),
    ])
    monkeypatch.setattr(stun.socket, "socket", FakeSocket)
    result = stun.query("stun.example.test", 3478, timeout=1.5)
    assert result["ip"] == "203.0.113.10"
    assert result["server"] == "stun.example.test:3478"
    assert sent["timeout"] == 1.5
    assert sent["closed"] is True


def test_query_any_falls_back_to_the_next_server(monkeypatch):
    calls = []

    def fake_query(server, port, timeout=2.0):
        calls.append(server)
        if server == "first":
            raise stun.StunError("blocked")
        return {"ip": "203.0.113.11", "server": f"{server}:{port}"}

    monkeypatch.setattr(stun, "query", fake_query)
    assert stun.query_any((("first", 1), ("second", 2)))["ip"] == "203.0.113.11"
    assert calls == ["first", "second"]


def test_query_any_reports_failure_without_network_details(monkeypatch):
    monkeypatch.setattr(stun, "query", lambda *args, **kwargs: (_ for _ in ()).throw(stun.StunError("secret")))
    with pytest.raises(stun.StunError) as error:
        stun.query_any((("first", 1),))
    assert "secret" not in str(error.value)
