from unittest.mock import Mock

import pytest

from claude_china import launcher
from claude_china.desktop import config, egress, router, router_guardian
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
    backend.network_guard_targets.return_value = ['C:/fixture/Claude.exe']
    monkeypatch.setattr(egress, "tun_enabled", lambda *args: False)
    monkeypatch.setattr(egress, "ensure", lambda *args, **kwargs: {"enabled": False})
    monkeypatch.setattr(router, "check_ready", Mock())
    monkeypatch.setattr(router, "inspect", Mock(return_value={"status": "supported", "reason": "ok"}))
    monkeypatch.setattr(router_guardian, 'start', Mock(return_value={'target': 'claude'}))
    return LauncherBridge(backend, apps=[get_app("claude")], base_env={"all_proxy": "stale"}), backend


def test_desktop_router_mode_checks_even_when_region_check_disabled_and_removes_proxy(desktop):
    bridge, backend = desktop
    result = bridge.launch_app("claude")
    assert result["ok"]
    assert router.inspect.called
    assert router_guardian.start.called
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


def test_desktop_router_requires_guardian_before_touching_running_app(desktop, monkeypatch):
    bridge, backend = desktop
    monkeypatch.setattr(router_guardian, 'start', Mock(side_effect=router_guardian.GuardError('authorization failed')))
    result = bridge.launch_app('claude')
    assert not result['ok']
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


def test_network_guard_status_reports_router_block_and_restore(desktop, monkeypatch):
    bridge, _ = desktop
    monkeypatch.setattr(egress, 'supported', lambda: True)
    monkeypatch.setattr(egress, 'status', lambda *args, **kwargs: {'supported': True, 'enabled': False,
                         'can_restore': False, 'can_apply': True, 'tunnels': [], 'found': True})
    state = {'enabled': True, 'state': 'blocked', 'policy': {'executables': ['C:/fixture/Claude.exe']}}
    monkeypatch.setattr(router_guardian, 'status', lambda target: state)
    restore = Mock(side_effect=lambda target: state.update(enabled=False, state='none'))
    monkeypatch.setattr(router_guardian, 'restore', restore)
    result = bridge.get_network_guard('claude')['state']
    assert result['router_state'] == 'blocked' and result['can_restore'] and not result['can_apply']
    assert bridge.restore_network_guard('claude')['ok']
    restore.assert_called_once_with('claude')


def test_standalone_cli_router_mode_checks_and_clears_proxy(monkeypatch):
    from claude_china.desktop import platforms, playwright_guard, terminal_host
    data = {"safety_router_mode": True, "safety_check": False}
    monkeypatch.setattr(config, "load_desktop_config", lambda: data)
    monkeypatch.setattr(platforms, "get_backend", lambda: Mock())
    monkeypatch.setattr(router, "check_ready", Mock())
    monkeypatch.setattr(router, "inspect", Mock(return_value={"status": "supported", "reason": "ok"}))
    monkeypatch.setattr(launcher, "find_command", lambda _: "claude")
    monkeypatch.setattr(playwright_guard, "prepare_environment", lambda env, **kwargs: env)
    monkeypatch.setattr(terminal_host, 'resolve_cli_argv', lambda _: ['claude.exe'])
    monkeypatch.setattr(router_guardian, 'cli_targets', lambda argv, env, data: (argv, ['claude.exe']))
    monkeypatch.setattr(router_guardian, 'start', Mock(return_value={'target': 'playwright'}))
    monkeypatch.setattr(playwright_guard, 'prepare_router_environment', lambda env: {**env, 'GUARDED': '1'})
    execute = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(launcher.subprocess, 'run', execute)
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    with pytest.raises(SystemExit):
        launcher.launch({"name": "fixture", "type": "claude", "mode": "login", "credentials_path": "~/.fixture"}, [])
    assert router.inspect.called
    assert router_guardian.start.called
    env = execute.call_args.kwargs['env']
    assert "HTTPS_PROXY" not in env and env["NO_PROXY"] == "*" and env['GUARDED'] == '1'


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


def test_standalone_cli_does_not_start_without_runtime_guard(monkeypatch):
    from claude_china.desktop import platforms, playwright_guard, terminal_host
    data = {'safety_router_mode': True}
    monkeypatch.setattr(config, 'load_desktop_config', lambda: data)
    monkeypatch.setattr(platforms, 'get_backend', lambda: Mock())
    monkeypatch.setattr(router, 'check_ready', Mock())
    monkeypatch.setattr(router, 'inspect', lambda *args: {'status': 'supported', 'reason': 'ok'})
    monkeypatch.setattr(launcher, 'find_command', lambda _: 'claude')
    monkeypatch.setattr(playwright_guard, 'prepare_environment', lambda env, **kwargs: env)
    monkeypatch.setattr(terminal_host, 'resolve_cli_argv', lambda _: ['claude.exe'])
    monkeypatch.setattr(router_guardian, 'cli_targets', lambda argv, env, data: (argv, ['claude.exe']))
    monkeypatch.setattr(router_guardian, 'start', Mock(side_effect=router_guardian.GuardError('blocked')))
    monkeypatch.setattr(launcher.sys, 'platform', 'win32')
    execute = Mock()
    monkeypatch.setattr(launcher.subprocess, 'run', execute)
    with pytest.raises(SystemExit):
        launcher.launch({'name': 'fixture', 'type': 'claude', 'mode': 'login', 'credentials_path': '~/.fixture'}, [])
    execute.assert_not_called()


def test_cli_can_switch_network_mode_without_deleting_existing_settings(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from claude_china.cli import app
    monkeypatch.setattr(config, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    config.save_desktop_config({"env_vars": {"OTHER": "value"}})
    runner = CliRunner()
    result = runner.invoke(app, ["network-mode", "router"])
    assert result.exit_code == 0
    assert "managed Claude" in result.output and "Windows" in result.output
    assert "cannot block direct connections after the router fails" not in result.output
    assert config.get_safety_settings(config.load_desktop_config())["router_mode"]
    assert config.load_desktop_config()["env_vars"] == {"OTHER": "value"}
    assert runner.invoke(app, ["network-mode", "default"]).exit_code == 0
    assert not config.get_safety_settings(config.load_desktop_config())["router_mode"]
    assert runner.invoke(app, ["network-mode", "invalid"]).exit_code != 0
