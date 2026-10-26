import json

import pytest

from src.claude_china.desktop.platforms import windows


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    REG_SZ = 1

    def __init__(self):
        self.keys = {}

    @staticmethod
    def _key(root, path):
        return (root, path)

    def OpenKey(self, root, path):
        key = self._key(root, path)
        if key not in self.keys:
            raise FileNotFoundError(path)
        return key

    def CreateKey(self, root, path):
        key = self._key(root, path)
        self.keys.setdefault(key, {})
        return key

    def QueryValueEx(self, key, name):
        if name not in self.keys[key]:
            raise FileNotFoundError(name)
        return self.keys[key][name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.keys[key][name] = value

    def DeleteValue(self, key, name):
        if name not in self.keys[key]:
            raise FileNotFoundError(name)
        del self.keys[key][name]

    def DeleteKey(self, root, path):
        key = self._key(root, path)
        if key not in self.keys:
            raise FileNotFoundError(path)
        if self.keys[key]:
            raise OSError("key is not empty")
        del self.keys[key]

    def CloseKey(self, key):
        pass


@pytest.fixture
def registry(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(windows, "winreg", fake)
    return fake, windows.WindowsBackend()


def _policy_key(registry, hive, browser):
    return (hive, windows._WEBRTC_POLICY_PATHS[browser])


def test_apply_creates_a_per_user_policy_and_records_previous_state(registry):
    fake, backend = registry
    result = backend.apply_webrtc_policy("edge", windows._WEBRTC_POLICY_VALUE)
    assert result["applied"] is True
    assert result["already"] is False
    assert result["created_key"] is True
    assert result["previous"] == {"exists": False, "value": None}
    assert fake.keys[_policy_key(fake, "HKCU", "edge")][windows._WEBRTC_POLICY_NAME] == windows._WEBRTC_POLICY_VALUE
    state = backend._read_policy_state("edge")
    assert state["state"] == "disabled"
    assert state["source"] == "user"
    assert state["editable"] is True


def test_restore_removes_the_value_and_the_key_we_created(registry):
    fake, backend = registry
    backend.apply_webrtc_policy("chrome", windows._WEBRTC_POLICY_VALUE)
    result = backend.restore_webrtc_policy({
        "browser": "chrome", "value": windows._WEBRTC_POLICY_VALUE,
        "previous": {"exists": False, "value": None}, "created_key": True,
    })
    assert result == {"restored": True, "conflict": False}
    assert _policy_key(fake, "HKCU", "chrome") not in fake.keys


def test_restore_refuses_to_clobber_a_changed_value(registry):
    fake, backend = registry
    backend.apply_webrtc_policy("edge", windows._WEBRTC_POLICY_VALUE)
    fake.keys[_policy_key(fake, "HKCU", "edge")][windows._WEBRTC_POLICY_NAME] = "default"
    result = backend.restore_webrtc_policy({
        "browser": "edge", "value": windows._WEBRTC_POLICY_VALUE,
        "previous": {"exists": False, "value": None}, "created_key": True,
    })
    assert result == {"restored": False, "conflict": True, "current": "default"}
    assert fake.keys[_policy_key(fake, "HKCU", "edge")][windows._WEBRTC_POLICY_NAME] == "default"


def test_restore_writes_back_an_existing_previous_value(registry):
    fake, backend = registry
    fake.keys[_policy_key(fake, "HKCU", "edge")] = {
        windows._WEBRTC_POLICY_NAME: windows._WEBRTC_POLICY_VALUE}
    result = backend.restore_webrtc_policy({
        "browser": "edge", "value": windows._WEBRTC_POLICY_VALUE,
        "previous": {"exists": True, "value": "default"}, "created_key": False,
    })
    assert result == {"restored": True, "conflict": False}
    assert fake.keys[_policy_key(fake, "HKCU", "edge")][windows._WEBRTC_POLICY_NAME] == "default"


def test_machine_policy_is_not_overwritten(registry):
    fake, backend = registry
    fake.keys[_policy_key(fake, "HKLM", "edge")] = {
        windows._WEBRTC_POLICY_NAME: "default_public_interface_only"}
    with pytest.raises(ValueError, match="组织"):
        backend.apply_webrtc_policy("edge", windows._WEBRTC_POLICY_VALUE)
    assert _policy_key(fake, "HKCU", "edge") not in fake.keys


def test_an_existing_different_user_policy_is_a_conflict(registry):
    fake, backend = registry
    fake.keys[_policy_key(fake, "HKCU", "edge")] = {windows._WEBRTC_POLICY_NAME: "default"}
    with pytest.raises(ValueError, match="已存在"):
        backend.apply_webrtc_policy("edge", windows._WEBRTC_POLICY_VALUE)


def test_already_matching_policy_is_idempotent(registry):
    fake, backend = registry
    fake.keys[_policy_key(fake, "HKCU", "chrome")] = {
        windows._WEBRTC_POLICY_NAME: windows._WEBRTC_POLICY_VALUE}
    result = backend.apply_webrtc_policy("chrome", windows._WEBRTC_POLICY_VALUE)
    assert result["already"] is True
    assert result["applied"] is False


def test_unknown_browser_is_rejected(registry):
    _, backend = registry
    with pytest.raises(ValueError, match="不支持"):
        backend.apply_webrtc_policy("firefox", windows._WEBRTC_POLICY_VALUE)


def test_privacy_snapshot_reports_tunnel_ipv6_and_policies(registry, monkeypatch):
    fake, backend = registry
    routes = {
        "0.0.0.0/0": {"Name": "WireGuard Tunnel", "Description": "WireGuard Tunnel"},
        "::/0": {"Name": "Ethernet", "Description": "Intel Ethernet"},
    }
    monkeypatch.setattr(backend, "_default_route", lambda prefix: routes[prefix])
    fake.keys[_policy_key(fake, "HKCU", "chrome")] = {
        windows._WEBRTC_POLICY_NAME: windows._WEBRTC_POLICY_VALUE}
    snapshot = backend.privacy_snapshot()
    assert snapshot["supported"] is True
    assert snapshot["tun"] is True
    assert snapshot["ipv6"] == {"default": True, "tunnel": False}
    assert snapshot["policies"]["chrome"]["state"] == "disabled"
    assert snapshot["policies"]["edge"]["state"] == "unset"


@pytest.mark.parametrize("name,expected", [
    ("WireGuard Tunnel", True),
    ("Clash Verge", True),
    ("Mihomo", True),
    ("TAP-Windows Adapter V9", True),
    ("Tailscale", True),
    ("Intel(R) Ethernet", False),
    ("Hyper-V Virtual Ethernet Adapter", False),
    ("VMware Virtual Ethernet Adapter", False),
])
def test_tunnel_detection_uses_adapter_names(name, expected):
    assert windows.WindowsBackend._is_tunnel({"Name": name, "Description": name}) is expected


def test_default_route_parses_powershell_json(monkeypatch):
    captured = {}
    monkeypatch.setattr(windows.subprocess, "check_output",
                        lambda argv, **kw: captured.update(argv=argv, **kw) or json.dumps(
                            {"Name": "WireGuard Tunnel", "Description": "WireGuard"}))
    route = windows.WindowsBackend()._default_route("0.0.0.0/0")
    assert route["Name"] == "WireGuard Tunnel"
    assert "'0.0.0.0/0'" in captured["argv"][-1]


def test_default_route_returns_none_on_empty_or_bad_output(monkeypatch):
    monkeypatch.setattr(windows.subprocess, "check_output", lambda *a, **k: "")
    assert windows.WindowsBackend()._default_route("0.0.0.0/0") is None
    monkeypatch.setattr(windows.subprocess, "check_output", lambda *a, **k: "not-json")
    assert windows.WindowsBackend()._default_route("::/0") is None


def test_non_windows_registry_cannot_apply(monkeypatch):
    monkeypatch.setattr(windows, "winreg", None)
    backend = windows.WindowsBackend()
    assert backend.privacy_snapshot()["supported"] is False
    with pytest.raises(ValueError, match="暂不支持"):
        backend.apply_webrtc_policy("edge", windows._WEBRTC_POLICY_VALUE)
