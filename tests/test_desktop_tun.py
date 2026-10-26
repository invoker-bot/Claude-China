from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.claude_china.desktop import config as cfg, egress, playwright_guard
from src.claude_china.desktop.apps import get_app
from src.claude_china.desktop.bridge import LauncherBridge
from src.claude_china.desktop.platforms.base import AppStatus
from src.claude_china.desktop.platforms.windows_wfp import validate

TUNNEL = {"guid": "769f00ba-f302-4549-a337-7d2f44f8e8b1", "luid": 123456,
          "index": 42, "name": "Test TUN", "addresses": ["198.18.44.1", "2001:db8:44::1"]}
REAL_DISCOVER = playwright_guard.discover


class Store:
    def __init__(self):
        self.policies = {}

    def read(self):
        return deepcopy(self.policies)

    def verify(self, policies):
        return policies == self.policies


@pytest.fixture
def guard(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    cfg.save_desktop_config({"safety_check": False, "check_system_proxy": True})
    exe = tmp_path / "App.exe"
    exe.write_bytes(b"MZ")
    browser = tmp_path / "chrome.exe"
    browser.write_bytes(b"MZ")
    backend = Mock()
    backend.detect.return_value = AppStatus("claude", True, True, str(exe), str(exe))
    backend.network_guard_targets.return_value = [str(exe)]
    backend.network_guard_tunnels.return_value = [{**TUNNEL, "up": True}]
    store = Store()
    monkeypatch.setattr(egress, "supported", lambda: True)
    monkeypatch.setattr(egress, "_store", lambda: store)
    monkeypatch.setattr(egress, "_write", lambda policies, expected=None: setattr(store, "policies", deepcopy(policies)))
    monkeypatch.setattr(playwright_guard, "discover", lambda *args, **kwargs: [str(browser)])
    monkeypatch.setattr(playwright_guard, "tunnel_live", lambda tunnel: True)
    bridge = LauncherBridge(backend, apps=[get_app("claude")], base_env={})
    return bridge, backend, store, exe, browser


def options():
    return {"mode": "tun", "tunnel_guid": TUNNEL["guid"]}


def test_tun_does_not_require_system_http_proxy_and_preserves_udp(guard):
    bridge, backend, store, _, _ = guard
    backend.system_http_proxy.side_effect = AssertionError("TUN must not need an HTTP proxy")
    backend.proxy_enabled.return_value = False
    result = bridge.apply_network_guard("claude", options())
    assert result["ok"] and result["state"]["verified"]
    assert store.policies["claude"]["mode"] == "tun"
    assert store.policies["claude"]["tunnel"] == TUNNEL
    assert bridge.launch_app("claude")["ok"]
    backend.apply_webrtc_policy.assert_not_called()


def test_playwright_is_an_independent_protected_target(guard):
    bridge, _, store, _, browser = guard
    result = bridge.apply_network_guard("playwright", options())
    assert result["ok"] and result["state"]["verified"]
    assert store.policies["playwright"]["executables"] == [str(browser)]
    assert cfg.load_desktop_config()["network_guard"]["playwright"] is True


@pytest.mark.parametrize("change", ["down", "luid", "address", "missing"])
def test_tunnel_change_does_not_remove_guard_or_allow_launch(guard, change):
    bridge, backend, store, _, _ = guard
    assert bridge.apply_network_guard("claude", options())["ok"]
    current = {**TUNNEL, "up": True}
    if change == "down":
        current["up"] = False
    elif change == "luid":
        current["luid"] += 1
    elif change == "address":
        current["addresses"] = ["198.18.55.1"]
    backend.network_guard_tunnels.return_value = [] if change == "missing" else [current]
    assert bridge.launch_app("claude")["ok"] is False
    assert store.policies["claude"]["tunnel"] == TUNNEL
    backend.launch.assert_not_called()


def test_tun_restore_works_after_adapter_and_browser_are_removed(guard):
    bridge, backend, store, _, _ = guard
    assert bridge.apply_network_guard("playwright", options())["ok"]
    backend.network_guard_tunnels.return_value = []
    assert bridge.restore_network_guard("playwright")["ok"]
    assert not store.policies


def test_new_browser_is_denied_before_launch_and_existing_one_is_allowed(guard):
    bridge, _, _, _, browser = guard
    assert bridge.apply_network_guard("playwright", options())["ok"]
    playwright_guard.check_browser(str(browser))
    with pytest.raises(egress.GuardError):
        playwright_guard.check_browser(str(browser.with_name("new-chrome.exe")))


def test_browser_launch_gate_fails_closed_if_tunnel_goes_down(guard, monkeypatch):
    bridge, _, _, _, browser = guard
    assert bridge.apply_network_guard("playwright", options())["ok"]
    monkeypatch.setattr(playwright_guard, "tunnel_live", lambda tunnel: False)
    with pytest.raises(egress.GuardError):
        playwright_guard.check_browser(str(browser))


def test_browser_helper_reports_errors_as_utf8_with_legacy_windows_stream(guard, monkeypatch):
    import io
    import sys
    from src.claude_china.desktop import entry

    bridge, _, _, _, browser = guard
    assert bridge.apply_network_guard("playwright", options())["ok"]
    monkeypatch.setattr(playwright_guard, "tunnel_live", lambda tunnel: False)
    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding="cp936", write_through=True)
    monkeypatch.setattr(sys, "stderr", stream)
    assert entry.main(["--network-guard-check-browser", str(browser)]) == 1
    assert "隧道已断开" in output.getvalue().decode("utf-8")


def test_cli_hook_preserves_existing_node_options_and_is_idempotent(guard):
    bridge, _, _, _, _ = guard
    assert bridge.apply_network_guard("playwright", options())["ok"]
    env = {"NODE_OPTIONS": "--max-old-space-size=2048", "USER_VALUE": "keep"}
    first = playwright_guard.prepare_environment(env)
    second = playwright_guard.prepare_environment(first)
    assert first == second
    assert "--max-old-space-size=2048" in first["NODE_OPTIONS"]
    assert "playwright-guard.cjs" in first["NODE_OPTIONS"]
    assert first["USER_VALUE"] == "keep"
    assert "CLAUDEC_BROWSER_GUARD_HELPER" in first


def test_wfp_accepts_tunnel_policy_but_rejects_unpinned_or_loopback_tunnel(guard):
    _, _, _, _, browser = guard
    policy = {"playwright": {"mode": "tun", "executables": [str(browser)], "tunnel": deepcopy(TUNNEL)}}
    validate(policy)
    for key, value in [("luid", 0), ("index", 0), ("addresses", []), ("addresses", ["0.0.0.0"]),
                       ("addresses", ["127.0.0.1"]), ("guid", "not-a-guid")]:
        invalid = deepcopy(policy)
        invalid["playwright"]["tunnel"][key] = value
        with pytest.raises(ValueError):
            validate(invalid)


def test_cli_hook_is_removed_after_one_click_restore(guard):
    bridge, _, _, _, _ = guard
    assert bridge.apply_network_guard("playwright", options())["ok"]
    env = playwright_guard.prepare_environment({"NODE_OPTIONS": "--trace-warnings"})
    assert bridge.restore_network_guard("playwright")["ok"]
    restored = playwright_guard.prepare_environment(env)
    assert restored == {"NODE_OPTIONS": "--trace-warnings"}


def test_discovery_uses_custom_cache_and_does_not_scan_unrelated_programs(tmp_path):
    root = tmp_path / "pw-cache"
    browser = root / "chromium-123" / "chrome-win64" / "chrome.exe"
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"MZ")
    unrelated = tmp_path / "OtherApp.exe"
    unrelated.write_bytes(b"MZ")
    # Use the implementation, rather than the fixture's injected discovery.
    assert playwright_guard.discover({"PLAYWRIGHT_BROWSERS_PATH": str(root)}) == [str(browser.resolve())]


def test_guard_discovers_the_cache_used_by_common_cli_settings(guard, tmp_path, monkeypatch):
    bridge, _, store, _, _ = guard
    browser = tmp_path / "custom-cache" / "chromium-123" / "chrome-win64" / "chrome.exe"
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"MZ")
    data = cfg.load_desktop_config()
    data["env_vars"] = {"PLAYWRIGHT_BROWSERS_PATH": str(browser.parents[2])}
    cfg.save_desktop_config(data)
    monkeypatch.setattr(playwright_guard, "discover", REAL_DISCOVER)
    assert bridge.apply_network_guard("playwright", options())["ok"]
    assert store.policies["playwright"]["executables"] == [str(browser.resolve())]


def test_cli_entry_passes_browser_guard_to_the_cli_child(guard, monkeypatch):
    from src.claude_china import launcher
    from types import SimpleNamespace
    bridge, _, _, _, _ = guard
    assert bridge.apply_network_guard("playwright", options())["ok"]
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "find_command", lambda *_: "claude.cmd")
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(launcher.subprocess, "run", run)
    with pytest.raises(SystemExit):
        launcher.launch({"type": "claude", "mode": "api", "name": "test", "base_url": None, "token": None}, [])
    env = run.call_args.kwargs["env"]
    assert "playwright-guard.cjs" in env["NODE_OPTIONS"]
    assert "CLAUDEC_BROWSER_GUARD_HELPER" in env


def test_administratively_disabled_interface_is_never_live(monkeypatch):
    import ctypes as C
    from types import SimpleNamespace
    from src.claude_china.desktop.platforms import windows_tun
    from src.claude_china.desktop.platforms.windows_wfp import U64

    def convert(key, output):
        C.cast(output, C.POINTER(U64)).contents.value = 123456
        return 0

    def entry(pointer):
        row = C.cast(pointer, C.POINTER(windows_tun.IfRow)).contents
        row.index = 42
        row.oper_status = 1  # The driver's operational status can lag disable.
        row.admin_status = 2
        return 0

    monkeypatch.setattr(windows_tun.C, "WinDLL", lambda *args, **kwargs: SimpleNamespace(
        ConvertInterfaceGuidToLuid=convert, GetIfEntry2=entry), raising=False)
    assert windows_tun.interface(TUNNEL["guid"])["up"] is False
