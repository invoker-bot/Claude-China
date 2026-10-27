from unittest.mock import Mock

import pytest

from claude_china.desktop import config, egress, router


@pytest.fixture
def backend():
    value = Mock()
    value.safety_proxy.return_value = {"proxy": None}
    value.privacy_snapshot.return_value = {"ipv6": {"default": False}}
    return value


@pytest.fixture
def probes(monkeypatch):
    monkeypatch.setattr(router, "trace_host", lambda host, family: {
        "ip": "8.8.8.8", "country_code": "US"})
    monkeypatch.setattr(router, "stun_exit", lambda family: "8.8.8.8")
    monkeypatch.setattr(router, "dns_probe", lambda: None)


def test_router_mode_is_opt_in_and_round_trips():
    data = {}
    assert config.get_safety_settings(data)["router_mode"] is False
    config.set_safety_settings(data, {"router_mode": True})
    assert config.get_safety_settings(data)["router_mode"] is True
    config.set_safety_settings(data, {"router_mode": False})
    assert config.get_safety_settings(data)["router_mode"] is False


def test_matching_service_and_udp_exits_allow_launch_but_do_not_claim_dns_or_webrtc(backend, probes):
    report = router.inspect("claude", backend)
    assert report["status"] == "supported"
    assert {v["host"] for v in report["router"]["services"]} == {"claude.ai", "api.anthropic.com"}
    assert report["router"]["udp4"]["status"] == "match"
    assert report["router"]["dns"] == "unknown"
    assert report["router"]["browser_webrtc"] == "unknown"


def test_dns_probe_parses_observed_resolver_without_treating_it_as_browser_proof():
    result = router.parse_dns_txt('"remote_ip: 8.8.8.8"\n"asn: 15169"\n"country_code: US"')
    assert result == {"ip": "8.8.8.8", "country_code": "US", "asn": 15169}
    with pytest.raises(ValueError):
        router.parse_dns_txt('"remote_ip: 192.168.1.1"\n"country_code: CN"')


def test_dns_resolver_in_blocked_region_is_reported_as_warning(backend, probes, monkeypatch):
    monkeypatch.setattr(router, "dns_probe", lambda: {"ip": "8.8.8.8", "country_code": "CN", "asn": 1})
    report = router.inspect("claude", backend)
    assert report["router"]["dns"]["status"] == "warning"
    assert report["status"] == "supported"


def test_router_blocks_service_route_mismatch_even_when_unknown_is_allowed(backend, probes, monkeypatch):
    monkeypatch.setattr(router, "trace_host", lambda host, family: {
        "ip": "8.8.8.8" if host == "claude.ai" else "1.1.1.1", "country_code": "US"})
    report = router.inspect("claude", backend)
    assert report["status"] == "unsupported"
    assert not router.allowed(report, {"block_unknown": False})


def test_router_blocks_udp_mismatch_and_unsupported_region(backend, probes, monkeypatch):
    monkeypatch.setattr(router, "stun_exit", lambda family: "1.1.1.1")
    assert router.inspect("claude", backend)["status"] == "unsupported"
    monkeypatch.setattr(router, "stun_exit", lambda family: "8.8.8.8")
    monkeypatch.setattr(router, "trace_host", lambda host, family: {"ip": "8.8.8.8", "country_code": "CN"})
    assert router.inspect("claude", backend)["status"] == "unsupported"


def test_unavailable_udp_is_unknown_and_strict_setting_blocks(backend, probes, monkeypatch):
    def fail(family):
        raise OSError("untrusted detail")
    monkeypatch.setattr(router, "stun_exit", fail)
    report = router.inspect("claude", backend)
    assert report["status"] == "unknown"
    assert "untrusted detail" not in str(report)
    assert not router.allowed(report, {"block_unknown": True})
    assert router.allowed(report, {"block_unknown": False})


def test_ipv6_is_probed_when_default_route_exists(backend, probes, monkeypatch):
    backend.privacy_snapshot.return_value = {"ipv6": {"default": True}}
    monkeypatch.setattr(router, "trace_host", lambda host, family: {
        "ip": "8.8.8.8" if family == 4 else "2606:4700:4700::1111", "country_code": "US"})
    monkeypatch.setattr(router, "stun_exit", lambda family: "8.8.8.8" if family == 4 else "2001:4860:4860::8888")
    report = router.inspect("claude", backend)
    assert report["router"]["udp6"]["status"] == "mismatch"
    assert report["status"] == "unsupported"


def test_unknown_ipv6_snapshot_can_be_resolved_as_no_default_route(backend, probes, monkeypatch):
    backend.privacy_snapshot.return_value = {"ipv6": {"default": None}}
    monkeypatch.setattr(router, "ipv6_default_route", lambda: False)
    report = router.inspect("claude", backend)
    assert report["router"]["udp6"]["status"] == "unavailable"
    assert report["status"] == "supported"


def test_router_rejects_enabled_system_proxy_or_existing_wfp(backend, monkeypatch):
    backend.safety_proxy.return_value = {"proxy": "http://127.0.0.1:7890"}
    with pytest.raises(router.RouterError, match="系统代理"):
        router.check_ready("claude", {}, backend)
    backend.safety_proxy.return_value = {"proxy": None}
    monkeypatch.setattr(egress, "supported", lambda: True)
    monkeypatch.setattr(egress, "_store", lambda: Mock(read=lambda: {"claude": {"mode": "tun"}}))
    with pytest.raises(router.RouterError, match="还原"):
        router.check_ready("claude", {}, backend)


def test_router_drops_all_proxy_variables_without_changing_input():
    original = {"Http_Proxy": "one", "HTTPS_PROXY": "two", "ALL_PROXY": "three", "no_proxy": "localhost", "KEEP": "x"}
    result = router.direct_environment(original)
    assert result == {"KEEP": "x", "NO_PROXY": "*", "no_proxy": "*"}
    assert len(original) == 5
