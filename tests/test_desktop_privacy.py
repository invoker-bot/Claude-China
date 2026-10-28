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


@pytest.mark.parametrize("proxy,tun,env,expected", [
    (True, False, {}, "system_proxy"),
    (False, True, {}, "tun"),
    (False, False, {"HTTPS_PROXY": "http://127.0.0.1:7890"}, "env_proxy"),
    (False, False, {}, "direct"),
])
def test_local_report_identifies_mode_without_claiming_webrtc_verification(proxy, tun, env, expected):
    report = privacy.inspect(FakeBackend(proxy=proxy, tun=tun), env=env)
    assert report["mode"] == expected
    assert report["consistent"] is None
    assert report["level"] == ("warn" if expected == "env_proxy" else "unknown")
    assert any("未验证" in reason for reason in report["reasons"])


def test_policy_state_and_machine_management_are_reported():
    report = privacy.inspect(FakeBackend(policies={
        "chrome": {"value": "disable_non_proxied_udp", "source": "user", "state": "disabled", "editable": True},
        "edge": {"value": "default", "source": "machine", "state": "default", "editable": False},
    }), env={})
    assert report["policies"]["browsers"]["chrome"]["state"] == "disabled"
    assert report["policies"]["browsers"]["edge"]["source"] == "machine"
    assert any("组织管理" in reason for reason in report["reasons"])
    assert "secret" not in json.dumps(report)


def test_non_tunnel_ipv6_route_warns_without_making_a_network_probe():
    backend = FakeBackend()
    backend.privacy_snapshot = lambda: {
        "supported": True, "tun": False,
        "ipv6": {"default": True, "tunnel": False}, "policies": {},
    }
    report = privacy.inspect(backend, env={})
    assert report["level"] == "warn"
    assert any("IPv6" in reason for reason in report["reasons"])


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
