from unittest.mock import Mock

import pytest

from claude_china.desktop import egress, privacy, router, router_runtime, safety, stun
from claude_china.desktop.bridge import LauncherBridge
from claude_china.desktop.platforms.base import AppStatus


def _connection(monkeypatch, body=b'ip=8.8.8.8\nloc=US\n'):
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = body
    factory = Mock(return_value=connection)
    monkeypatch.setattr(safety.http.client, 'HTTPSConnection', factory)
    return factory, connection


@pytest.mark.parametrize('app_id', ['claude', 'codex', 'grok-bot'])
def test_router_uses_one_independent_country_request_without_service_udp_or_dns(monkeypatch, app_id):
    factory, connection = _connection(monkeypatch)
    for name in ('trace_host', 'stun_exit', 'dns_probe'):
        if hasattr(router, name):
            monkeypatch.setattr(router, name, Mock(side_effect=AssertionError('unexpected probe')))
    monkeypatch.setattr(stun, 'query_any', Mock(side_effect=AssertionError('unexpected UDP')))
    backend = Mock()
    report = router.inspect(app_id, backend)
    assert report['status'] == 'supported'
    assert report['network']['country_code'] == 'US'
    assert report['router']['browser_webrtc'] == 'unknown'
    factory.assert_called_once()
    assert factory.call_args.args[0] == 'www.cloudflare.com'
    assert connection.request.call_count == 1
    assert connection.request.call_args.args[:2] == ('GET', '/cdn-cgi/trace')
    backend.privacy_snapshot.assert_not_called()


def test_tun_uses_one_country_request_on_the_chosen_interface(monkeypatch):
    factory, connection = _connection(monkeypatch)
    monkeypatch.setattr('claude_china.desktop.playwright_guard.tunnel_live', lambda tunnel: True)
    tunnel = {'addresses': ['198.18.44.1']}
    report = safety.inspect_environment('claude', {}, Mock(), AppStatus('claude'), tunnel=tunnel)
    assert report['status'] == 'supported'
    assert report['network']['country_code'] == 'US'
    assert factory.call_count == connection.request.call_count == 1
    assert factory.call_args.args[0] == 'www.cloudflare.com'
    assert factory.call_args.kwargs['source_address'] == ('198.18.44.1', 0)


@pytest.mark.parametrize('tun', [False, True])
def test_privacy_status_uses_only_local_state_without_network_probes(monkeypatch, tun):
    monkeypatch.setattr(safety, 'lookup_ip', Mock(side_effect=AssertionError('unexpected HTTPS')))
    monkeypatch.setattr(stun, 'query_any', Mock(side_effect=AssertionError('unexpected UDP')))
    backend = Mock()
    backend.privacy_snapshot.return_value = {'supported': True, 'tun': tun, 'policies': {}, 'ipv6': {}}
    backend.proxy_enabled.return_value = not tun
    report = privacy.inspect(backend, env={})
    safety.lookup_ip.assert_not_called()
    stun.query_any.assert_not_called()
    assert report['consistent'] is None
    assert report['https']['ok'] is report['udp']['ok'] is False
    assert not any('一致' in reason and '未发现' in reason for reason in report['reasons'])


def test_desktop_tun_country_check_uses_the_configured_tunnel(monkeypatch):
    tunnel = {'guid': 'test', 'addresses': ['198.18.44.1']}
    monkeypatch.setattr(egress, 'tun_enabled', lambda app, data: True)
    monkeypatch.setattr(egress, '_store', lambda: Mock(read=lambda: {'claude': {'tunnel': tunnel}}))
    lookup = Mock(return_value={'status': 'supported'})
    monkeypatch.setattr(safety, 'inspect_environment', lookup)
    bridge = LauncherBridge(Mock())
    bridge._check_safety('claude', {}, AppStatus('claude'), {'block_unknown': True})
    assert lookup.call_args.kwargs['tunnel'] == tunnel


def test_router_runtime_does_not_block_same_country_ip_changes():
    def report(ip):
        return {'status': 'supported', 'network': {'ip': ip, 'country_code': 'US'},
                'router': {'services': [{'status': 'ok', 'host': 'unused', 'family': 4, 'ip': ip}]}}
    assert router_runtime.failure(report('8.8.8.8'), report('1.1.1.1'), {'block_unknown': True}) is None


@pytest.mark.parametrize('status,strict,has_tunnel,changed,should_run', [
    ('supported', True, True, False, True), ('unsupported', True, True, False, False),
    ('unknown', True, True, False, False), ('unknown', False, True, False, True),
    ('supported', False, False, False, False), ('supported', True, True, True, False),
])
def test_standalone_tun_cli_checks_country_before_launch(monkeypatch, status, strict, has_tunnel, changed, should_run):
    from claude_china import launcher
    from claude_china.desktop import cli_guard, config, platforms, playwright_guard, terminal_host

    data = {'safety_router_mode': False, 'safety_check': True, 'safety_block_unknown': strict}
    tunnel = {'guid': 'test', 'addresses': ['198.18.44.1']}
    config_values = iter([data, {**data, 'safety_check': False}]) if changed else None
    monkeypatch.setattr(config, 'load_desktop_config', lambda: next(config_values) if changed else data)
    monkeypatch.setattr(launcher, 'find_command', lambda _: 'claude.exe')
    monkeypatch.setattr(launcher.sys, 'platform', 'win32')
    monkeypatch.setattr(playwright_guard, 'prepare_environment', lambda env, **kwargs: env)
    monkeypatch.setattr(cli_guard, 'enabled', lambda data: True)
    monkeypatch.setattr(cli_guard, 'prepare', lambda argv, env, *args, **kwargs: (argv, env))
    monkeypatch.setattr(terminal_host, 'resolve_cli_argv', lambda _: ['claude.exe'])
    policies = {'playwright': {'tunnel': tunnel}} if has_tunnel else {}
    monkeypatch.setattr(egress, '_store', lambda: Mock(read=lambda: policies))
    monkeypatch.setattr(platforms, 'get_backend', lambda: Mock())
    check = Mock(return_value={'status': status, 'reason': 'fixture'})
    monkeypatch.setattr(safety, 'inspect_environment', check)
    execute = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(launcher.subprocess, 'run', execute)
    with pytest.raises(SystemExit):
        launcher.launch({'name': 'fixture', 'type': 'claude', 'mode': 'login',
                         'credentials_path': '~/.fixture'}, [])
    assert check.call_count == int(has_tunnel)
    if has_tunnel:
        assert check.call_args.kwargs['tunnel'] == tunnel
    assert execute.called is should_run


@pytest.mark.parametrize('body', [b'ip=127.0.0.1\nloc=US\n', b'ip=8.8.8.8\nloc=XX\n', b'garbage'])
def test_invalid_country_response_is_unknown_and_blocked_in_strict_mode(monkeypatch, body):
    _connection(monkeypatch, body)
    report = router.inspect('claude', Mock())
    assert report['status'] == 'unknown'
    assert not router.allowed(report, {'block_unknown': True})
