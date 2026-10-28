from unittest.mock import Mock

import pytest

from claude_china.desktop import config, egress, router


@pytest.fixture
def backend():
    value = Mock()
    value.safety_proxy.return_value = {"proxy": None}
    value.privacy_snapshot.return_value = {"ipv6": {"default": False}}
    return value


def test_router_mode_is_opt_in_and_round_trips():
    data = {}
    assert config.get_safety_settings(data)["router_mode"] is False
    config.set_safety_settings(data, {"router_mode": True})
    assert config.get_safety_settings(data)["router_mode"] is True
    config.set_safety_settings(data, {"router_mode": False})
    assert config.get_safety_settings(data)["router_mode"] is False


@pytest.mark.parametrize("country,expected", [("US", "supported"), ("CN", "unsupported"), ("XX", "unknown")])
def test_router_applies_country_rule_to_the_single_result(backend, monkeypatch, country, expected):
    from claude_china.desktop import safety
    lookup = Mock(return_value={"ip": "8.8.8.8", "country_code": country})
    monkeypatch.setattr(safety, "lookup_ip", lookup)
    report = router.inspect("claude", backend)
    assert report["status"] == expected
    lookup.assert_called_once_with(None)
    assert report["router"]["browser_webrtc"] == "unknown"


def test_router_failed_country_lookup_is_unknown_and_respects_strict_mode(backend, monkeypatch):
    from claude_china.desktop import safety
    monkeypatch.setattr(safety, "lookup_ip", Mock(side_effect=OSError("private details")))
    report = router.inspect("claude", backend)
    assert report["status"] == "unknown"
    assert "private details" not in str(report)
    assert not router.allowed(report, {"block_unknown": True})
    assert router.allowed(report, {"block_unknown": False})


def test_router_rejects_enabled_system_proxy_or_existing_wfp(backend, monkeypatch):
    backend.safety_proxy.return_value = {"proxy": "http://127.0.0.1:7890"}
    with pytest.raises(router.RouterError, match="系统代理"):
        router.check_ready("claude", {}, backend)
    backend.safety_proxy.return_value = {"proxy": None}
    monkeypatch.setattr(egress, "supported", lambda: True)
    monkeypatch.setattr(egress, "_store", lambda: Mock(read=lambda: {"claude": {"mode": "tun"}}))
    with pytest.raises(router.RouterError, match="还原"):
        router.check_ready("claude", {}, backend)


def test_router_rejects_existing_runtime_guard_until_restored(backend, monkeypatch):
    from claude_china.desktop import router_guardian
    monkeypatch.setattr(egress, 'supported', lambda: True)
    monkeypatch.setattr(egress, '_store', lambda: Mock(read=lambda: {}))
    monkeypatch.setattr(router_guardian, 'status', lambda target: {'enabled': True, 'state': 'blocked'})
    with pytest.raises(router.RouterError, match='还原'):
        router.check_ready('claude', {}, backend)
    with pytest.raises(router.RouterError, match='还原'):
        router.check_ready('claude', {}, backend, allow_router_guard=True)
    monkeypatch.setattr(router_guardian, 'status', lambda target: {'enabled': True, 'state': 'healthy'})
    router.check_ready('claude', {}, backend, allow_router_guard=True)


def test_router_drops_all_proxy_variables_without_changing_input():
    original = {"Http_Proxy": "one", "HTTPS_PROXY": "two", "ALL_PROXY": "three", "no_proxy": "localhost", "KEEP": "x"}
    result = router.direct_environment(original)
    assert result == {"KEEP": "x", "NO_PROXY": "*", "no_proxy": "*"}
    assert len(original) == 5
