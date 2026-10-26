from unittest.mock import Mock

import pytest

from src.claude_china.desktop import config as cfg
from src.claude_china.desktop import privacy
from src.claude_china.desktop.bridge import LauncherBridge


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    monkeypatch.setattr(privacy, "REPAIRS_FILE", tmp_path / "privacy-repairs.json")
    return LauncherBridge(Mock(), apps=[], base_env={})


def test_check_privacy_returns_report_and_repairs(bridge, monkeypatch):
    report = {"level": "warn", "mode": "system_proxy", "reasons": []}
    monkeypatch.setattr(privacy, "inspect", lambda *args: report)
    monkeypatch.setattr(privacy, "list_repairs", lambda: [{"browser": "edge"}])
    result = bridge.check_privacy()
    assert result == {"ok": True, "report": report, "repairs": [{"browser": "edge"}]}


def test_check_privacy_survives_inspection_failure(bridge, monkeypatch):
    monkeypatch.setattr(privacy, "inspect", Mock(side_effect=OSError("secret")))
    monkeypatch.setattr(privacy, "list_repairs", lambda: [])
    result = bridge.check_privacy()
    assert result["ok"] is True
    assert result["report"]["level"] == "unknown"
    assert "secret" not in str(result)


def test_check_privacy_reports_corrupt_manifest_without_failing(bridge, monkeypatch):
    monkeypatch.setattr(privacy, "inspect", lambda *args: {"level": "ok"})
    monkeypatch.setattr(privacy, "list_repairs",
                        Mock(side_effect=privacy.PrivacyError("修复记录损坏，无法还原。")))
    result = bridge.check_privacy()
    assert result["ok"] is True
    assert result["repairs"] == []
    assert "损坏" in result["warning"]


def test_apply_privacy_fix_returns_safe_error(bridge, monkeypatch):
    monkeypatch.setattr(privacy, "apply",
                        Mock(side_effect=privacy.PrivacyError("TUN 模式下无需禁用 WebRTC。")))
    result = bridge.apply_privacy_fix("edge")
    assert result == {"ok": False, "error": "TUN 模式下无需禁用 WebRTC。"}


def test_apply_privacy_fix_hides_unexpected_exceptions(bridge, monkeypatch):
    monkeypatch.setattr(privacy, "apply", Mock(side_effect=OSError("token=secret")))
    result = bridge.apply_privacy_fix("edge")
    assert result["ok"] is False
    assert "secret" not in result["error"]


def test_apply_privacy_fix_returns_refreshed_repairs(bridge, monkeypatch):
    monkeypatch.setattr(privacy, "apply", lambda *args: {"applied": True, "record": {"browser": "edge"}})
    monkeypatch.setattr(privacy, "list_repairs", lambda: [{"browser": "edge"}])
    result = bridge.apply_privacy_fix("edge")
    assert result["ok"] is True
    assert result["result"]["applied"] is True
    assert result["repairs"] == [{"browser": "edge"}]


def test_restore_privacy_fix_maps_conflict(bridge, monkeypatch):
    monkeypatch.setattr(privacy, "restore",
                        Mock(side_effect=privacy.PrivacyError("当前策略已被其他设置修改，未覆盖。")))
    result = bridge.restore_privacy_fix("edge")
    assert result["ok"] is False
    assert "未覆盖" in result["error"]


def test_get_privacy_repairs_reports_manifest_failure(bridge, monkeypatch):
    monkeypatch.setattr(privacy, "list_repairs",
                        Mock(side_effect=privacy.PrivacyError("修复记录损坏，无法还原。")))
    assert bridge.get_privacy_repairs() == {"ok": False, "error": "修复记录损坏，无法还原。"}
