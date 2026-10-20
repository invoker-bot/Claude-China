import json
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from src.claude_china.desktop import config as cfg
from src.claude_china.desktop import safety
from src.claude_china.desktop.bridge import LauncherBridge
from src.claude_china.desktop.platforms.base import AppStatus


@pytest.fixture
def backend():
    backend = Mock()
    backend.proxy_enabled.return_value = False
    backend.safety_proxy.return_value = {"proxy": None}
    backend.detect.side_effect = lambda app, override: AppStatus(app.id, True, True, "app", "app")
    return backend


@pytest.fixture
def bridge(tmp_path, monkeypatch, backend):
    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    monkeypatch.setattr("src.claude_china.desktop.bridge.os", SimpleNamespace(environ={}))
    bridge = LauncherBridge(backend)
    bridge.save_settings({"check_system_proxy": False, "env_vars": {}})
    return bridge


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
@pytest.mark.parametrize("country", ["CN", "HK", "MO", "RU", "IR", "KP"])
def test_shared_policy_blocks_every_explicitly_restricted_region(app_id, country):
    report = safety.assess_region(app_id, country)
    assert report["status"] == "unsupported"
    assert "禁止" in report["reason"]


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
@pytest.mark.parametrize("country", ["JP", "SG", "US", "TW", "UA"])
def test_shared_policy_allows_other_identified_regions_without_claiming_official_support(app_id, country):
    report = safety.assess_region(app_id, country)
    assert report["status"] == "supported"
    assert report["policy"]["kind"] == "blocked_regions"
    assert "官方支持" not in report["reason"]
    assert "source" not in report and "reviewed_on" not in report


@pytest.mark.parametrize("app_id", ["claude", "codex", "grok-bot"])
@pytest.mark.parametrize("country", ["ZZ", "", None])
def test_shared_policy_keeps_unidentified_regions_unknown(app_id, country):
    assert safety.assess_region(app_id, country)["status"] == "unknown"


def test_unrecognized_app_cannot_be_authorized_by_shared_policy():
    assert safety.assess_region("unregistered-app", "US")["status"] == "unknown"


def test_settings_publish_the_same_blocked_regions_used_by_the_gate(bridge):
    policy = bridge.get_safety_settings()["policy"]
    assert {item["code"] for item in policy["blocked_regions"]} == {"CN", "HK", "MO", "RU", "IR", "KP"}
    assert policy["kind"] == "blocked_regions"


def test_local_language_and_timezone_are_information_not_a_block(backend, monkeypatch):
    local = {"timezone": "Asia/Shanghai", "language": "zh-CN", "region": "CN"}
    monkeypatch.setattr(safety, "local_environment", lambda: local)
    monkeypatch.setattr(safety, "lookup_ip", lambda proxy: {
        "ip": "1.1.1.1", "country_code": "SG", "country": "Singapore"})
    report = safety.inspect_environment("claude", {}, backend, AppStatus("claude", True, True))
    assert report["status"] == "supported"
    assert report["environment"] == local


def test_bad_proxy_is_never_silently_replaced_with_direct_connection(backend, monkeypatch):
    probe = Mock()
    monkeypatch.setattr(safety, "lookup_ip", probe)
    report = safety.inspect_environment("claude", {"HTTPS_PROXY": "socks5://secret:password@host:123"},
                                        backend, AppStatus("claude", True, True))
    assert report["status"] == "unknown"
    assert "secret" not in json.dumps(report)
    assert "password" not in json.dumps(report)
    probe.assert_not_called()


@pytest.mark.parametrize("env", [
    {"HTTPS_PROXY": "http://one:80", "https_proxy": "http://two:80"},
    {"HTTP_PROXY": "http://one:80", "HTTPS_PROXY": "http://two:80"},
    {"HTTPS_PROXY": "http://one:80", "NO_PROXY": "*.anthropic.com"},
    {"HTTPS_PROXY": "http://one:80", "no_proxy": "*"},
])
def test_ambiguous_routes_fail_closed(backend, env):
    with pytest.raises(safety.SafetyCheckError):
        safety.select_route(env, backend, AppStatus("claude", True, True))


def test_explicit_empty_proxy_cannot_be_treated_as_system_proxy(backend):
    backend.safety_proxy.return_value = {"proxy": "http://localhost:7890"}
    with pytest.raises(safety.SafetyCheckError):
        safety.select_route({"HTTPS_PROXY": ""}, backend, AppStatus("claude", True, True))


def test_public_ip_bypass_with_port_is_not_mistaken_for_unrelated_domain():
    with pytest.raises(safety.SafetyCheckError):
        safety.validate_bypass("8.8.8.8:443", "claude")


def test_matching_system_and_environment_proxy_uses_single_route(backend):
    backend.proxy_enabled.return_value = True
    backend.system_http_proxy.return_value = "http://127.0.0.1:7890"
    backend.safety_proxy.return_value = {"proxy": "http://127.0.0.1:7890"}
    route = safety.select_route({"HTTPS_PROXY": "http://127.0.0.1:7890", "NO_PROXY": "localhost,127.0.0.1"},
                                backend, AppStatus("claude", True, False))
    assert route["proxy"] == "http://127.0.0.1:7890"


@pytest.mark.parametrize("second_ip,expected", [("1.1.1.1", "supported"), ("8.8.8.8", "unknown")])
def test_loopback_aliases_are_probed_and_must_agree(backend, monkeypatch, second_ip, expected):
    backend.safety_proxy.return_value = {"proxy": "http://127.0.0.1:7890"}
    probe = Mock(side_effect=[{"ip": "1.1.1.1", "country_code": "SG"}, {"ip": second_ip, "country_code": "SG"}])
    monkeypatch.setattr(safety, "lookup_ip", probe)
    report = safety.inspect_environment("claude", {"HTTPS_PROXY": "http://localhost:7890"},
                                        backend, AppStatus("claude", True, False))
    assert report["status"] == expected
    assert probe.call_count == 2


def test_brokered_app_cannot_rely_on_environment_proxy(backend):
    with pytest.raises(safety.SafetyCheckError):
        safety.select_route({"HTTPS_PROXY": "http://localhost:7890"}, backend,
                            AppStatus("codex", True, False))


@pytest.mark.parametrize("bypass", ["127.*;10.*;172.16.*;192.168.*;<local>",
                                     "localhost,.example.com,*.internal.example,10.0.0.0/8"])
def test_local_and_unrelated_bypasses_do_not_block_public_service_probe(backend, bypass):
    route = safety.select_route({"HTTPS_PROXY": "http://localhost:7890", "NO_PROXY": bypass},
                                backend, AppStatus("claude", True, True))
    assert route["proxy"] == "http://localhost:7890"


def test_network_failure_redacts_details(backend, monkeypatch):
    monkeypatch.setattr(safety, "lookup_ip", Mock(side_effect=OSError("secret-token@proxy")))
    result = safety.inspect_environment("claude", {}, backend, AppStatus("claude", True, True))
    assert result["status"] == "unknown"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("status", ["unsupported", "unknown"])
def test_safety_failure_preserves_running_app(bridge, backend, monkeypatch, status):
    monkeypatch.setattr(safety, "inspect_environment", lambda *args: {
        "app_id": "claude", "status": status, "reason": "地区检查未通过"})
    result = bridge.launch_app("claude")
    assert result["ok"] is False
    assert result["safety"]["status"] == status
    assert "地区检查未通过" in result["error"]
    backend.stop.assert_not_called()
    backend.launch.assert_not_called()


def test_supported_launch_is_rechecked_on_every_restart(bridge, backend, monkeypatch):
    probe = Mock(side_effect=[{"status": "supported"}, {"status": "unsupported", "reason": "地区不支持"}])
    monkeypatch.setattr(safety, "inspect_environment", probe)
    assert bridge.launch_app("claude")["ok"] is True
    assert bridge.launch_app("claude")["ok"] is False
    assert probe.call_count == 2
    assert backend.launch.call_count == backend.stop.call_count == 1


def test_disabled_guard_does_not_send_network_request(bridge, backend, monkeypatch):
    probe = Mock(side_effect=AssertionError("must not query"))
    monkeypatch.setattr(safety, "inspect_environment", probe)
    bridge.save_safety_settings({"enabled": False, "block_unknown": True})
    assert bridge.launch_app("claude")["ok"] is True
    probe.assert_not_called()


def test_relaxed_guard_still_blocks_known_unsupported_regions(bridge, monkeypatch):
    bridge.save_safety_settings({"enabled": True, "block_unknown": False})
    monkeypatch.setattr(safety, "inspect_environment", lambda *args: {"status": "unknown"})
    assert bridge.launch_app("claude")["ok"] is True
    monkeypatch.setattr(safety, "inspect_environment", lambda *args: {"status": "unsupported", "reason": "不支持"})
    assert bridge.launch_app("claude")["ok"] is False


def test_config_change_during_check_prevents_stale_authorization(bridge, backend, monkeypatch):
    def check(*args):
        bridge.save_app_settings("claude", {"env_vars": {"HTTPS_PROXY": "http://new:80"}})
        return {"status": "supported"}
    monkeypatch.setattr(safety, "inspect_environment", check)
    assert bridge.launch_app("claude")["ok"] is False
    backend.stop.assert_not_called()


def test_check_receives_exact_merged_launch_environment(bridge, backend, monkeypatch):
    bridge.save_settings({"check_system_proxy": False, "env_vars": {"HTTPS_PROXY": "http://common:80"}})
    bridge.save_app_settings("claude", {"env_vars": {"HTTPS_PROXY": "http://app:80"}})
    probe = Mock(return_value={"status": "supported"})
    monkeypatch.setattr(safety, "inspect_environment", probe)
    assert bridge.launch_app("claude")["ok"] is True
    assert probe.call_args.args[1] == backend.launch.call_args.args[1]
    assert probe.call_args.args[1]["HTTPS_PROXY"] == "http://app:80"


def test_safety_settings_default_strict_and_persist_without_ip(bridge):
    assert bridge.get_safety_settings()["enabled"] is True
    assert bridge.get_safety_settings()["block_unknown"] is True
    bridge.save_safety_settings({"enabled": True, "block_unknown": False})
    assert bridge.get_safety_settings()["block_unknown"] is False
    text = cfg.DESKTOP_CONFIG_FILE.read_text(encoding="utf-8")
    assert "country_code" not in text and "timezone" not in text


@pytest.mark.parametrize("body", [
    {"success": False, "message": "private IP"},
    {"success": True, "ip": "127.0.0.1", "country_code": "US"},
    {"success": True, "ip": "1.1.1.1", "country_code": "XX"},
    {"success": "true", "ip": "1.1.1.1", "country_code": "US"},
])
def test_untrusted_ip_response_cannot_authorize_launch(monkeypatch, body):
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = json.dumps(body).encode()
    monkeypatch.setattr(safety.http.client, "HTTPSConnection", Mock(return_value=connection))
    with pytest.raises(safety.SafetyCheckError):
        safety.lookup_ip(None)
    connection.close.assert_called_once()


def test_https_lookup_tunnels_and_never_sends_proxy_password_to_service(monkeypatch):
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = json.dumps({"success": True, "ip": "1.1.1.1", "country_code": "SG"}).encode()
    factory = Mock(return_value=connection)
    monkeypatch.setattr(safety.http.client, "HTTPSConnection", factory)
    result = safety.lookup_ip("http://user:pass@localhost:7890")
    assert result["country_code"] == "SG"
    assert factory.call_args.args == ("localhost", 7890)
    assert connection.set_tunnel.call_args.args == ("ipwho.is", 443)
    assert "Proxy-Authorization" in connection.set_tunnel.call_args.kwargs["headers"]
    assert "pass" not in repr(connection.request.call_args)
    assert "Proxy-Authorization" not in connection.request.call_args.kwargs["headers"]


@pytest.mark.parametrize("status,body", [(302, b"{}"), (429, b"{}"), (200, b"x" * 16385), (200, b"invalid")])
def test_lookup_rejects_redirects_limits_and_malformed_payload(monkeypatch, status, body):
    connection = Mock()
    response = connection.getresponse.return_value
    response.status, response.read.return_value = status, body
    monkeypatch.setattr(safety.http.client, "HTTPSConnection", Mock(return_value=connection))
    with pytest.raises(safety.SafetyCheckError):
        safety.lookup_ip(None)

