from unittest.mock import Mock

import pytest

from claude_china import launcher
from claude_china.desktop import config, egress, router
from claude_china.desktop.apps import get_app
from claude_china.desktop.bridge import LauncherBridge
from claude_china.desktop.platforms.base import AppStatus


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    data = {"safety_router_mode": True, "safety_check": False, "check_system_proxy": True,
            "auto_proxy_env": True, "env_vars": {"HTTPS_PROXY": "http://127.0.0.1:9"}}
    config.save_desktop_config(data)
    backend = Mock()
    backend.detect.return_value = AppStatus("claude", True, True, "app", "app")
    backend.proxy_enabled.return_value = False
    monkeypatch.setattr(egress, "tun_enabled", lambda *args: False)
    monkeypatch.setattr(egress, "ensure", lambda *args, **kwargs: {"enabled": False})
    monkeypatch.setattr(router, "check_ready", Mock())
    monkeypatch.setattr(router, "inspect", Mock(return_value={"status": "supported", "reason": "ok"}))
    return LauncherBridge(backend, apps=[get_app("claude")], base_env={"all_proxy": "stale"}), backend


def test_desktop_router_mode_checks_even_when_region_check_disabled_and_removes_proxy(desktop):
    bridge, backend = desktop
    result = bridge.launch_app("claude")
    assert result["ok"]
    assert router.inspect.called
    env = backend.launch.call_args.args[1]
    assert not any(key.lower() in ("http_proxy", "https_proxy", "all_proxy") for key in env)
    assert env["NO_PROXY"] == "*"
    backend.system_http_proxy.assert_not_called()


def test_desktop_router_failed_check_does_not_launch_or_stop_existing_app(desktop, monkeypatch):
    bridge, backend = desktop
    monkeypatch.setattr(router, "inspect", lambda *args: {"status": "unsupported", "reason": "mismatch"})
    assert not bridge.launch_app("claude")["ok"]
    backend.stop.assert_not_called()
    backend.launch.assert_not_called()


def test_router_mode_can_be_selected_when_tun_is_required_in_other_modes(desktop):
    bridge, _ = desktop
    data = config.load_desktop_config()
    data['safety_require_tun'] = True
    config.save_desktop_config(data)
    assert bridge.launch_app('claude')['ok'] is True


def test_manual_check_does_not_allow_router_with_existing_guard_even_if_unknown_allowed(desktop, monkeypatch):
    bridge, _ = desktop
    data = config.load_desktop_config()
    data['safety_block_unknown'] = False
    config.save_desktop_config(data)
    monkeypatch.setattr(router, 'check_ready', Mock(side_effect=router.RouterError('restore first')))
    report = bridge.check_safety('claude')
    assert report['allowed'] is False
    assert report['status'] == 'unsupported'


def test_standalone_cli_router_mode_checks_and_clears_proxy(monkeypatch):
    from claude_china.desktop import platforms, playwright_guard
    data = {"safety_router_mode": True, "safety_check": False}
    monkeypatch.setattr(config, "load_desktop_config", lambda: data)
    monkeypatch.setattr(platforms, "get_backend", lambda: Mock())
    monkeypatch.setattr(router, "check_ready", Mock())
    monkeypatch.setattr(router, "inspect", Mock(return_value={"status": "supported", "reason": "ok"}))
    monkeypatch.setattr(launcher, "find_command", lambda _: "claude")
    monkeypatch.setattr(playwright_guard, "prepare_environment", lambda env: env)
    exec_fn = Mock(side_effect=SystemExit(0))
    monkeypatch.setattr(launcher.os, "execvpe", exec_fn)
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    with pytest.raises(SystemExit):
        launcher.launch({"name": "fixture", "type": "claude", "mode": "login", "credentials_path": "~/.fixture"}, [])
    assert router.inspect.called
    env = exec_fn.call_args.args[2]
    assert "HTTPS_PROXY" not in env and env["NO_PROXY"] == "*"


def test_standalone_cli_router_rejects_unknown_by_default(monkeypatch):
    from claude_china.desktop import platforms
    data = {"safety_router_mode": True}
    monkeypatch.setattr(config, "load_desktop_config", lambda: data)
    monkeypatch.setattr(platforms, "get_backend", lambda: Mock())
    monkeypatch.setattr(router, "check_ready", Mock())
    monkeypatch.setattr(router, "inspect", lambda *args: {"status": "unknown", "reason": "no UDP"})
    monkeypatch.setattr(launcher, "find_command", lambda _: "claude")
    exec_fn = Mock()
    monkeypatch.setattr(launcher.os, "execvpe", exec_fn)
    with pytest.raises(SystemExit):
        launcher.launch({"name": "fixture", "type": "claude", "mode": "login", "credentials_path": "~/.fixture"}, [])
    exec_fn.assert_not_called()


def test_cli_can_switch_network_mode_without_deleting_existing_settings(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from claude_china.cli import app
    monkeypatch.setattr(config, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    config.save_desktop_config({"env_vars": {"OTHER": "value"}})
    runner = CliRunner()
    assert runner.invoke(app, ["network-mode", "router"]).exit_code == 0
    assert config.get_safety_settings(config.load_desktop_config())["router_mode"]
    assert config.load_desktop_config()["env_vars"] == {"OTHER": "value"}
    assert runner.invoke(app, ["network-mode", "default"]).exit_code == 0
    assert not config.get_safety_settings(config.load_desktop_config())["router_mode"]
    assert runner.invoke(app, ["network-mode", "invalid"]).exit_code != 0
