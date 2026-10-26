import json
from unittest.mock import Mock

import pytest

from src.claude_china.desktop import privacy


class FakeBackend:
    def __init__(self, *, proxy=True, tun=False, supported=True, policies=None,
                 https_proxy="http://user:secret@127.0.0.1:7890",
                 apply_result=None, restore_result=None):
        self._proxy = proxy
        self._tun = tun
        self._supported = supported
        self._policies = policies or {}
        self._https_proxy = https_proxy
        self._apply_result = apply_result or {
            "applied": True, "already": False,
            "previous": {"exists": False, "value": None}, "created_key": True,
        }
        self._restore_result = restore_result or {"restored": True}
        self.applied = []
        self.restored = []

    def proxy_enabled(self):
        return self._proxy

    def system_http_proxy(self):
        return self._https_proxy

    def privacy_snapshot(self):
        return {
            "supported": self._supported,
            "tun": self._tun,
            "ipv6": {"default": False, "tunnel": None},
            "policies": self._policies,
        }

    def apply_webrtc_policy(self, browser, value):
        self.applied.append((browser, value))
        return self._apply_result

    def restore_webrtc_policy(self, record):
        self.restored.append(record)
        return self._restore_result


@pytest.fixture(autouse=True)
def isolated_repairs(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "REPAIRS_FILE", tmp_path / ".claudec" / "privacy-repairs.json")


def _https(ip="1.1.1.1"):
    return lambda proxy: {"ip": ip, "country_code": "SG", "country": "Singapore"}


def _udp(ip="1.1.1.1"):
    return lambda: {"ip": ip, "server": "stun.example.test:3478"}


def test_system_proxy_with_matching_https_and_udp_is_reported_as_consistent():
    report = privacy.inspect(FakeBackend(), env={}, https_lookup=_https(), udp_lookup=_udp())
    assert report["mode"] == "system_proxy"
    assert report["consistent"] is True
    assert report["level"] == "ok"
    assert report["https"]["ip"] == "1.1.1.1"
    assert report["udp"]["ip"] == "1.1.1.1"


def test_system_proxy_with_different_udp_exit_warns_about_webrtc_bypass():
    report = privacy.inspect(FakeBackend(), env={}, https_lookup=_https("1.1.1.1"), udp_lookup=_udp("8.8.8.8"))
    assert report["consistent"] is False
    assert report["level"] == "warn"
    assert any("WebRTC" in reason and "绕过" in reason for reason in report["reasons"])


def test_tun_mode_needs_no_browser_policy_and_is_ok():
    report = privacy.inspect(FakeBackend(proxy=False, tun=True), env={},
                             https_lookup=_https("1.1.1.1"), udp_lookup=_udp("1.1.1.1"))
    assert report["mode"] == "tun"
    assert report["level"] == "ok"
    assert any("TUN" in reason for reason in report["reasons"])


def test_env_only_proxy_warns_that_windows_browsers_ignore_it():
    report = privacy.inspect(FakeBackend(proxy=False, tun=False), env={"HTTPS_PROXY": "http://127.0.0.1:7890"},
                             https_lookup=_https("1.1.1.1"), udp_lookup=_udp("8.8.8.8"))
    assert report["mode"] == "env_proxy"
    assert report["level"] == "warn"
    assert any("浏览器" in reason and "直连" in reason for reason in report["reasons"])


def test_direct_connection_is_not_a_proxy_bypass():
    report = privacy.inspect(FakeBackend(proxy=False, tun=False), env={},
                             https_lookup=_https("1.1.1.1"), udp_lookup=_udp("1.1.1.1"))
    assert report["mode"] == "direct"
    assert report["level"] == "ok"


def test_missing_udp_probe_is_unknown_not_a_false_ok():
    def fail():
        raise OSError("offline")
    report = privacy.inspect(FakeBackend(), env={}, https_lookup=_https(), udp_lookup=fail)
    assert report["consistent"] is None
    assert report["level"] == "unknown"
    assert any("UDP" in reason for reason in report["reasons"])


def test_policy_state_is_reported_for_both_browsers():
    report = privacy.inspect(FakeBackend(policies={
        "chrome": {"value": "disable_non_proxied_udp", "source": "user", "state": "disabled", "editable": True},
        "edge": {"value": None, "source": None, "state": "unset", "editable": True},
    }), env={}, https_lookup=_https(), udp_lookup=_udp())
    assert report["policies"]["browsers"]["chrome"]["state"] == "disabled"
    assert report["policies"]["browsers"]["edge"]["state"] == "unset"


def test_machine_policy_is_reported_as_managed():
    report = privacy.inspect(FakeBackend(policies={
        "edge": {"value": "default", "source": "machine", "state": "default", "editable": False},
    }), env={}, https_lookup=_https(), udp_lookup=_udp())
    assert report["policies"]["browsers"]["edge"]["source"] == "machine"
    assert any("组织管理" in reason for reason in report["reasons"])


def test_non_tunnel_ipv6_route_raises_a_warning():
    backend = FakeBackend()
    backend.privacy_snapshot = lambda: {
        "supported": True, "tun": False,
        "ipv6": {"default": True, "tunnel": False},
        "policies": {},
    }
    report = privacy.inspect(backend, env={}, https_lookup=_https(), udp_lookup=_udp())
    assert report["level"] == "warn"
    assert any("IPv6" in reason for reason in report["reasons"])


def test_direct_mode_does_not_warn_about_ipv6_proxy_bypass():
    backend = FakeBackend(proxy=False)
    backend.privacy_snapshot = lambda: {
        "supported": True, "tun": False,
        "ipv6": {"default": True, "tunnel": False},
        "policies": {},
    }
    report = privacy.inspect(backend, env={}, https_lookup=_https(), udp_lookup=_udp())
    assert report["mode"] == "direct"
    assert report["level"] == "ok"
    assert not any("IPv6" in reason for reason in report["reasons"])


def test_proxy_credentials_never_appear_in_the_report():
    report = privacy.inspect(FakeBackend(), env={}, https_lookup=_https(), udp_lookup=_udp())
    assert "secret" not in json.dumps(report)


def test_apply_refuses_tun_mode():
    with pytest.raises(privacy.PrivacyError, match="TUN"):
        privacy.apply(FakeBackend(tun=True), "edge", env={})


def test_apply_refuses_environment_only_proxy():
    with pytest.raises(privacy.PrivacyError, match="环境变量"):
        privacy.apply(FakeBackend(proxy=False), "edge", env={"HTTPS_PROXY": "http://127.0.0.1:7890"})


def test_apply_refuses_direct_connection():
    with pytest.raises(privacy.PrivacyError, match="未检测到系统代理"):
        privacy.apply(FakeBackend(proxy=False), "edge", env={})


def test_apply_records_previous_value_and_restore_reads_it():
    backend = FakeBackend()
    result = privacy.apply(backend, "edge", env={})
    assert result["applied"] is True
    assert backend.applied == [("edge", privacy.POLICY_VALUE)]
    record = privacy.list_repairs()[0]
    assert record["browser"] == "edge"
    assert record["previous"] == {"exists": False, "value": None}

    restored = privacy.restore(backend, "edge")
    assert restored == {"browser": "edge", "restored": True}
    assert backend.restored[0]["value"] == privacy.POLICY_VALUE
    assert privacy.list_repairs() == []


def test_apply_is_idempotent_when_policy_already_matches():
    backend = FakeBackend(apply_result={
        "applied": False, "already": True,
        "previous": {"exists": True, "value": privacy.POLICY_VALUE}, "created_key": False,
    })
    result = privacy.apply(backend, "chrome", env={})
    assert result["already"] is True
    assert privacy.list_repairs() == []


def test_restore_conflict_keeps_the_manifest():
    backend = FakeBackend(restore_result={"restored": False, "conflict": True, "current": "default"})
    privacy.apply(backend, "edge", env={})
    with pytest.raises(privacy.PrivacyError, match="未覆盖"):
        privacy.restore(backend, "edge")
    assert len(privacy.list_repairs()) == 1


def test_restore_without_manifest_is_rejected():
    with pytest.raises(privacy.PrivacyError, match="没有可还原"):
        privacy.restore(FakeBackend(), "edge")


@pytest.mark.parametrize("payload", [b"{", b"\xff\xfe\x00"])
def test_corrupt_manifest_is_reported_not_ignored(payload):
    privacy.REPAIRS_FILE.parent.mkdir(parents=True)
    privacy.REPAIRS_FILE.write_bytes(payload)
    with pytest.raises(privacy.PrivacyError, match="损坏"):
        privacy.list_repairs()


def test_corrupt_manifest_blocks_apply_before_touching_the_registry():
    privacy.REPAIRS_FILE.parent.mkdir(parents=True)
    privacy.REPAIRS_FILE.write_text("{", encoding="utf-8")
    backend = FakeBackend()
    with pytest.raises(privacy.PrivacyError, match="损坏"):
        privacy.apply(backend, "edge", env={})
    assert backend.applied == []


def test_manifest_write_failure_rolls_back_the_policy(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(privacy, "_save_repairs", Mock(side_effect=OSError("disk full")))
    with pytest.raises(privacy.PrivacyError, match="已尝试撤销"):
        privacy.apply(backend, "edge", env={})
    assert backend.applied == [("edge", privacy.POLICY_VALUE)]
    assert backend.restored and backend.restored[0]["value"] == privacy.POLICY_VALUE


def test_unsupported_platform_cannot_apply():
    with pytest.raises(privacy.PrivacyError, match="暂不支持"):
        privacy.apply(FakeBackend(supported=False), "edge", env={})


def test_unknown_report_has_safe_shape():
    report = privacy.unknown_report("失败")
    assert report["level"] == "unknown"
    assert report["reasons"] == ["失败"]
    assert set(report["policies"]["browsers"]) == {"chrome", "edge"}
