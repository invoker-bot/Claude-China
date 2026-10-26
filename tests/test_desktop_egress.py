"""The guard must fail closed without disabling WebRTC or changing other apps."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.claude_china.desktop import config as cfg, egress
from src.claude_china.desktop.apps import get_app
from src.claude_china.desktop.bridge import LauncherBridge
from src.claude_china.desktop.platforms.base import AppStatus


class MemoryStore:
    def __init__(self):
        self.policies = {}
        self.fail = False

    def read(self):
        return deepcopy(self.policies)

    def replace(self, policies):
        if self.fail:
            raise OSError("transaction failed: secret")
        self.policies = deepcopy(policies)

    def verify(self, policies):
        return self.policies == policies


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    app_dir = tmp_path / "Claude"
    app_dir.mkdir()
    executable = app_dir / "Claude.exe"
    executable.write_bytes(b"MZ")
    status = AppStatus("claude", True, True, str(executable), str(executable))
    backend = Mock()
    backend.detect.return_value = status
    backend.system_http_proxy.return_value = "http://127.0.0.1:7890"
    backend.safety_proxy.return_value = {"proxy": "http://127.0.0.1:7890"}
    backend.network_guard_targets.return_value = [str(executable)]
    store = MemoryStore()
    monkeypatch.setattr(egress, "supported", lambda: True)
    monkeypatch.setattr(egress, "_store", lambda: store)
    monkeypatch.setattr(egress, "_write", lambda policies, expected=None: store.replace(policies))
    bridge = LauncherBridge(backend, apps=[get_app("claude")], base_env={})
    cfg.save_desktop_config({"safety_check": False, "check_system_proxy": False})
    return bridge, backend, store, status


@pytest.mark.parametrize("proxy, addresses, port", [
    ("http://127.0.0.1:7890", ["127.0.0.1"], 7890),
    ("http://[::1]:8080", ["::1"], 8080),
    ("http://localhost:7890", ["127.0.0.1", "::1"], 7890),
    ("http://user:password@192.0.2.5:3128", ["192.0.2.5"], 3128),
])
def test_pin_only_proxy_addresses_and_port_without_storing_credentials(proxy, addresses, port):
    result = egress.proxy_endpoint(proxy)
    assert result == {"addresses": addresses, "port": port}
    assert "password" not in str(result)


@pytest.mark.parametrize("proxy", ["http://proxy.example:7890", "socks5://127.0.0.1:1080",
                                       "http://0.0.0.0:7890", "http://[::]:7890",
                                       "http://224.0.0.1:7890", "http://127.0.0.1:0"])
def test_ambiguous_or_invalid_proxy_fails_closed(proxy):
    with pytest.raises(egress.GuardError):
        egress.proxy_endpoint(proxy)


def test_apply_preserves_webrtc_and_persists_guard_intent(setup):
    bridge, backend, store, status = setup
    result = bridge.apply_network_guard("claude")
    assert result["ok"] is True
    assert result["state"]["enabled"] is True
    assert result["state"]["verified"] is True
    assert store.policies["claude"]["executables"] == [status.launch_target]
    assert cfg.load_desktop_config()["network_guard"]["claude"] is True
    backend.apply_webrtc_policy.assert_not_called()


def test_restore_works_with_proxy_removed_and_keeps_other_apps(setup):
    bridge, backend, store, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    store.policies["codex"] = deepcopy(store.policies["claude"])
    other = deepcopy(store.policies["codex"])
    backend.system_http_proxy.side_effect = OSError("proxy no longer exists")
    result = bridge.restore_network_guard("claude")
    assert result["ok"]
    assert "claude" not in store.policies
    assert store.policies["codex"] == other
    assert not cfg.load_desktop_config()["network_guard"].get("claude")


def test_failed_transaction_does_not_claim_enabled_or_save_intent(setup):
    bridge, _, store, _ = setup
    store.fail = True
    result = bridge.apply_network_guard("claude")
    assert result["ok"] is False
    assert "secret" not in str(result)
    assert not store.policies
    assert not cfg.load_desktop_config().get("network_guard")


def test_failed_settings_write_rolls_back_new_policy(setup, monkeypatch):
    bridge, _, store, _ = setup
    monkeypatch.setattr(cfg, "save_desktop_config", Mock(side_effect=OSError("disk full")))
    assert bridge.apply_network_guard("claude")["ok"] is False
    assert not store.policies


def test_guard_is_checked_before_stopping_or_starting_even_when_region_check_is_off(setup):
    bridge, backend, store, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    store.policies.clear()  # A removed OS rule must not become permission to launch.
    result = bridge.launch_app("claude")
    assert result["ok"] is False
    backend.launch.assert_not_called()
    backend.stop.assert_not_called()


@pytest.mark.parametrize("change", ["proxy", "target", "filters"])
def test_changed_endpoint_binary_or_missing_filter_blocks_launch(setup, change):
    bridge, backend, store, status = setup
    assert bridge.apply_network_guard("claude")["ok"]
    if change == "proxy":
        backend.system_http_proxy.return_value = "http://127.0.0.1:9999"
    elif change == "target":
        backend.network_guard_targets.return_value = [str(Path(status.launch_target).with_name("new.exe"))]
    else:
        store.verify = lambda _: False
    result = bridge.launch_app("claude")
    assert result["ok"] is False
    backend.launch.assert_not_called()


def test_guard_allows_verified_launch_without_injecting_browser_switches(setup):
    bridge, backend, _, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    assert bridge.launch_app("claude")["ok"]
    backend.launch.assert_called_once()
    assert backend.launch.call_args.args[1]["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    backend.apply_webrtc_policy.assert_not_called()


def test_proxy_disconnection_blocks_launch_and_leaves_os_guard_installed(setup):
    bridge, backend, store, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    backend.system_http_proxy.side_effect = OSError("token=secret")
    result = bridge.launch_app("claude")
    assert result["ok"] is False
    assert "secret" not in str(result)
    assert "claude" in store.policies
    backend.launch.assert_not_called()


def test_status_failure_is_not_reported_as_disabled(setup, monkeypatch):
    bridge, _, _, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    monkeypatch.setattr(egress, "_store", Mock(side_effect=OSError("secret")))
    result = bridge.get_network_guard("claude")
    assert result["state"]["enabled"]
    assert not result["state"]["verified"]
    assert result["state"]["can_restore"]
    assert "secret" not in str(result)


def test_unsupported_platform_is_explicit_and_cannot_apply(setup, monkeypatch):
    bridge, _, store, _ = setup
    monkeypatch.setattr(egress, "supported", lambda: False)
    assert bridge.get_network_guard("claude")["state"]["supported"] is False
    assert bridge.apply_network_guard("claude")["ok"] is False
    assert not store.policies


def test_all_bundled_executables_are_covered_but_neighbor_apps_are_not(tmp_path):
    from src.claude_china.desktop.platforms.windows import WindowsBackend
    root = tmp_path / "Claude"
    root.mkdir()
    main = root / "Claude.exe"
    helper = root / "resources" / "network" / "helper.exe"
    helper.parent.mkdir(parents=True)
    main.write_bytes(b"MZ")
    helper.write_bytes(b"MZ")
    neighbor = tmp_path / "Other.exe"
    neighbor.write_bytes(b"MZ")
    status = AppStatus("claude", True, True, str(main), str(main))
    assert WindowsBackend().network_guard_targets(status) == sorted([str(main), str(helper)], key=str.casefold)


def test_wfp_rejects_global_scope_or_unbounded_proxy_before_os_calls(tmp_path):
    from src.claude_china.desktop.platforms.windows_wfp import validate
    with pytest.raises(ValueError):
        validate({"claude": {"executables": ["*"], "proxy": {"addresses": ["127.0.0.1"], "port": 7890}}})
    with pytest.raises(ValueError):
        validate({"claude": {"executables": [str(tmp_path / "App.exe")],
                              "proxy": {"addresses": ["0.0.0.0/0"], "port": 7890}}})


def test_privileged_entry_does_not_start_the_gui(monkeypatch, tmp_path):
    from src.claude_china.desktop import entry
    from src.claude_china.desktop.platforms import windows_wfp
    action = Mock(return_value=0)
    monkeypatch.setattr(windows_wfp, "apply_request", action)
    request = tmp_path / "request.json"
    assert entry.main(["--network-guard-request", str(request), "--network-guard-digest", "digest"]) == 0
    action.assert_called_once_with(request, "digest")


def test_uninstall_clears_owned_guard_and_keeps_user_settings(setup):
    bridge, _, store, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    assert egress.uninstall() == 0
    assert store.policies == {}
    data = cfg.load_desktop_config()
    assert data["network_guard"]["claude"] is False
    assert data["safety_check"] is False


def test_restore_settings_failure_reinstalls_previous_guard(setup, monkeypatch):
    bridge, _, store, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    previous = deepcopy(store.policies)
    monkeypatch.setattr(cfg, "save_desktop_config", Mock(side_effect=OSError("disk full")))
    assert bridge.restore_network_guard("claude")["ok"] is False
    assert store.policies == previous


def test_restore_after_vendor_app_is_removed(setup):
    bridge, backend, store, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    backend.detect.return_value = AppStatus("claude", found=False)
    assert bridge.restore_network_guard("claude")["ok"]
    assert not store.policies


def test_one_binary_cannot_inherit_another_apps_proxy_exception(tmp_path):
    from src.claude_china.desktop.platforms.windows_wfp import validate
    first = {"executables": [str(tmp_path / "shared.exe")],
             "proxy": {"addresses": ["127.0.0.1"], "port": 7890}}
    second = deepcopy(first)
    second["proxy"]["port"] = 9999
    with pytest.raises(ValueError):
        validate({"claude": first, "codex": second})


@pytest.mark.parametrize("route", [None, "http://127.0.0.1:9999"])
def test_ambiguous_or_different_https_system_proxy_cannot_claim_protected(setup, route):
    bridge, backend, store, _ = setup
    backend.safety_proxy.return_value = {"proxy": route}
    assert bridge.apply_network_guard("claude")["ok"] is False
    assert not store.policies


def test_unverified_install_keeps_launch_locked_and_restore_available(setup):
    bridge, backend, store, _ = setup
    store.verify = lambda _: False
    assert bridge.apply_network_guard("claude")["ok"] is False
    assert cfg.load_desktop_config()["network_guard"]["claude"] is True
    assert bridge.launch_app("claude")["ok"] is False
    backend.launch.assert_not_called()
    assert bridge.get_network_guard("claude")["state"]["can_restore"]


def test_protected_launch_replaces_proxy_and_bypass_variables_in_any_case(setup):
    bridge, backend, _, _ = setup
    assert bridge.apply_network_guard("claude")["ok"]
    data = cfg.load_desktop_config()
    data["env_vars"] = {"HtTp_PrOxY": "http://old:9999", "No_PrOxY": "*", "ALL_PROXY": "socks5://old:1080"}
    cfg.save_desktop_config(data)
    assert bridge.launch_app("claude")["ok"]
    env = backend.launch.call_args.args[1]
    assert not any(key.lower() in ("no_proxy", "all_proxy") for key in env)
    assert all(value == "http://127.0.0.1:7890" for key, value in env.items()
               if key.lower() in ("http_proxy", "https_proxy"))
