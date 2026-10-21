from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from claude_china import config as cli_config
from claude_china.desktop import config, safety, terminals


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    monkeypatch.setattr(config, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    cli_config.save_config({'profiles': {}, 'other': {'keep': True}})
    config.save_desktop_config(dict(config.DEFAULTS, check_system_proxy=False))
    backend = Mock()
    backend.system_http_proxy.return_value = 'http://127.0.0.1:1234'
    monkeypatch.setattr(safety, 'inspect_environment', Mock(return_value={'status': 'supported', 'reason': 'fixture'}))
    monkeypatch.setattr(terminals, 'resolve_cli_argv', lambda kind: ['fixture-' + kind])
    return terminals.TerminalService(backend)


def api_profile(name='work', **values):
    return dict(name=name, type='claude', mode='api', base_url='https://api.example.test',
                secret='private-test-token', proxy='', default_args=['--model', 'model with spaces'], **values)


def test_create_read_edit_rename_copy_delete_share_cli_store_without_exposing_secret(service):
    service.save_profile(api_profile())
    listed = service.list_profiles()
    assert len(listed) == 1
    assert 'private-test-token' not in json.dumps(listed)
    detail = service.get_profile('work')
    assert detail['has_secret'] and 'secret' not in detail
    edited = dict(detail, name='renamed', secret='')
    service.save_profile(edited, original_name='work', revision=detail['revision'])
    data = cli_config.load_config()
    assert 'work' not in data['profiles']
    assert data['profiles']['renamed']['token'] == 'private-test-token'
    assert data['other'] == {'keep': True}
    current = service.get_profile('renamed')
    copied = service.copy_profile('renamed', current['revision'])
    assert cli_config.load_config()['profiles'][copied['name']]['token'] == 'private-test-token'
    service.delete_profile('renamed', current['revision'])
    assert set(cli_config.load_config()['profiles']) == {copied['name']}


def test_stale_edit_and_delete_cannot_overwrite_cli_changes(service):
    service.save_profile(api_profile())
    old = service.get_profile('work')
    data = cli_config.load_config()
    data['profiles']['work']['token'] = 'changed-by-cli'
    cli_config.save_config(data)
    for action in [lambda: service.save_profile(dict(old, secret=''), 'work', old['revision']),
                   lambda: service.delete_profile('work', old['revision']),
                   lambda: service.copy_profile('work', old['revision'])]:
        with pytest.raises(ValueError, match='变化'):
            action()
    assert cli_config.load_config()['profiles']['work']['token'] == 'changed-by-cli'


def test_duplicate_and_invalid_profiles_do_not_change_file(service):
    service.save_profile(api_profile())
    before = cli_config.CONFIG_FILE.read_bytes()
    for changes in [{}, {'name': ''}, {'type': 'unknown'}, {'mode': 'shell'},
                    {'name': 'new', 'default_args': {'bad': True}},
                    {'name': 'new', 'proxy': 'socks://127.0.0.1:bad'},
                    {'name': 'new', 'base_url': 'javascript:alert(1)'}]:
        with pytest.raises(ValueError):
            service.save_profile(dict(api_profile(), **changes))
        assert cli_config.CONFIG_FILE.read_bytes() == before


def test_clear_secret_and_switch_login_remove_old_credentials_without_touching_directory(service, tmp_path):
    service.save_profile(api_profile())
    detail = service.get_profile('work')
    service.save_profile(dict(detail, clear_secret=True), 'work', detail['revision'])
    assert not service.get_profile('work')['has_secret']
    credentials = tmp_path / 'login account'
    credentials.mkdir()
    marker = credentials / 'auth.json'
    marker.write_text('keep')
    detail = service.get_profile('work')
    service.save_profile(dict(detail, mode='login', credentials_path=str(credentials)), 'work', detail['revision'])
    stored = cli_config.load_config()['profiles']['work']
    assert 'token' not in stored and 'api_key' not in stored
    service.delete_profile('work', service.get_profile('work')['revision'])
    assert marker.read_text() == 'keep'


def test_launch_preparation_uses_profile_and_default_args_without_cross_profile_leaks(service, monkeypatch, tmp_path):
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-leak')
    service.save_profile(api_profile())
    data = config.load_desktop_config()
    data.update(auto_proxy_env=True)
    config.save_desktop_config(data)
    argv, env = service.prepare('work', str(tmp_path))
    assert argv == ['fixture-claude', '--model', 'model with spaces']
    assert env['ANTHROPIC_AUTH_TOKEN'] == 'private-test-token'
    assert 'OPENAI_API_KEY' not in env
    assert env['HTTP_PROXY'] == env['HTTPS_PROXY'] == 'http://127.0.0.1:1234'
    service.backend.stop.assert_not_called()
    service.backend.launch.assert_not_called()


@pytest.mark.parametrize('status', ['unknown', 'unsupported'])
def test_cli_launch_obeys_strict_environment_check(service, tmp_path, monkeypatch, status):
    service.save_profile(api_profile())
    monkeypatch.setattr(safety, 'inspect_environment', Mock(return_value={'status': status, 'reason': 'fixture'}))
    with pytest.raises(ValueError, match='安全检查'):
        service.prepare('work', str(tmp_path))


def test_project_directory_and_history_are_validated_and_do_not_overwrite_other_settings(service, tmp_path):
    with pytest.raises(ValueError):
        service.remember_directory(str(tmp_path / 'missing'))
    directory = tmp_path / "project & ' quotes"
    directory.mkdir()
    service.remember_directory(str(directory))
    service.remember_directory(str(directory))
    state = service.workspace()
    assert state['directory'] == str(directory.resolve())
    assert state['recent_directories'] == [str(directory.resolve())]
    assert config.load_desktop_config()['safety_block_unknown'] is True


def test_invalid_system_proxy_blocks_even_when_profile_has_its_own_proxy(service, tmp_path):
    from claude_china.desktop.proxy import SystemProxyError
    service.save_profile(dict(api_profile(), proxy='http://127.0.0.1:5678'))
    data = config.load_desktop_config()
    data['auto_proxy_env'] = True
    config.save_desktop_config(data)
    service.backend.system_http_proxy.side_effect = SystemProxyError('invalid proxy')
    with pytest.raises(ValueError, match='invalid proxy'):
        service.prepare('work', str(tmp_path))


def test_profile_change_during_safety_check_cancels_launch(service, tmp_path, monkeypatch):
    service.save_profile(api_profile())
    def check(*args):
        data = cli_config.load_config()
        data['profiles']['work']['token'] = 'changed-during-check'
        cli_config.save_config(data)
        return {'status': 'supported'}
    monkeypatch.setattr(safety, 'inspect_environment', check)
    with pytest.raises(ValueError, match='配置发生变化'):
        service.prepare('work', str(tmp_path))


def test_failed_preflight_never_opens_terminal_and_failed_terminal_removes_job(service, tmp_path, monkeypatch):
    from claude_china.desktop import terminal_host
    job_dir = tmp_path / 'jobs'
    monkeypatch.setattr(terminal_host, 'jobs_dir', lambda: job_dir)
    open_terminal = Mock(side_effect=OSError('cannot create terminal'))
    monkeypatch.setattr(terminal_host, 'open_terminal', open_terminal)
    service.save_profile(api_profile())
    monkeypatch.setattr(safety, 'inspect_environment', lambda *args: {'status': 'unknown'})
    with pytest.raises(ValueError):
        service.launch('work', str(tmp_path))
    open_terminal.assert_not_called()
    with pytest.raises(OSError):
        service.launch(None, str(tmp_path))
    open_terminal.assert_called_once()
    assert not list(job_dir.iterdir())


def test_atomic_profile_write_keeps_previous_config_when_replace_fails(service, monkeypatch):
    service.save_profile(api_profile())
    before = cli_config.CONFIG_FILE.read_bytes()
    monkeypatch.setattr(cli_config.os, 'replace', Mock(side_effect=OSError('fixture')))
    with pytest.raises(OSError):
        service.save_profile(api_profile(name='second'))
    assert cli_config.CONFIG_FILE.read_bytes() == before
    assert not list(cli_config.CONFIG_FILE.parent.glob('.config-*.tmp'))
