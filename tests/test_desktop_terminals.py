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


def test_language_change_during_check_does_not_cancel_terminal_launch(service, tmp_path, monkeypatch):
    service.save_profile(api_profile())

    def inspect(*args, **kwargs):
        data = config.load_desktop_config()
        data['language'] = 'en'
        config.save_desktop_config(data)
        return {'status': 'supported', 'reason': 'fixture'}

    monkeypatch.setattr(safety, 'inspect_environment', inspect)
    argv, env = service.prepare('work', str(tmp_path))
    assert argv[0] == 'fixture-claude'
    assert env['ANTHROPIC_AUTH_TOKEN'] == 'private-test-token'


def test_managed_terminal_passes_argv_and_environment_through_cli_guard(service, tmp_path, monkeypatch):
    from claude_china.desktop import cli_guard

    service.save_profile(api_profile())
    guarded = Mock(side_effect=lambda argv, env, data: (['protected-cli'] + argv[1:], {**env, 'GUARDED': 'yes'}))
    monkeypatch.setattr(cli_guard, 'prepare', guarded)
    argv, env = service.prepare('work', str(tmp_path))
    assert guarded.called and argv[0] == 'protected-cli' and env['GUARDED'] == 'yes'


def test_guarded_terminal_checks_region_using_its_tunnel(service, tmp_path, monkeypatch):
    from claude_china.desktop import cli_guard, egress, playwright_guard

    service.save_profile(api_profile())
    tunnel = {'name': 'fixture', 'addresses': ['198.18.1.1']}
    monkeypatch.setattr(cli_guard, 'enabled', lambda data: True)
    monkeypatch.setattr(cli_guard, 'prepare', lambda argv, env, data: (argv, env))
    monkeypatch.setattr(egress, 'tun_enabled', lambda *args: True)
    monkeypatch.setattr(egress, '_store', lambda: type('Store', (), {'read': lambda self: {'playwright': {'tunnel': tunnel}}})())
    monkeypatch.setattr(playwright_guard, 'prepare_environment', lambda env, data: env)
    inspect = Mock(return_value={'status': 'supported', 'reason': 'fixture'})
    monkeypatch.setattr(safety, 'inspect_environment', inspect)
    service.prepare('work', str(tmp_path))
    assert inspect.call_args.kwargs['tunnel'] == tunnel


def test_copy_profile_localizes_only_generated_suffix(service):
    data = config.load_desktop_config()
    data['language'] = 'en'
    config.save_desktop_config(data)
    original = service.save_profile(api_profile(name='设置 {0}'))
    copied = service.copy_profile(original['name'], original['revision'])
    again = service.copy_profile(original['name'], original['revision'])
    assert copied['name'] == '设置 {0} copy'
    assert again['name'] == '设置 {0} copy 2'


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


def test_favorites_survive_launch_history_and_can_remove_missing_project(service, tmp_path):
    favorite = tmp_path / 'favorite'
    favorite.mkdir()
    service.set_favorite(str(favorite), True)
    service.remember_directory(str(tmp_path))
    service.set_favorite(str(favorite), True)
    assert service.workspace()['favorite_directories'] == [str(favorite)]
    favorite.rmdir()
    project = next(p for p in service.workspace()['projects'] if p['directory'] == str(favorite))
    assert project['favorite'] and not project['available']
    service.set_favorite(str(favorite), False)
    assert service.workspace()['favorite_directories'] == []
    assert config.load_desktop_config()['safety_block_unknown'] is True


def test_resume_uses_profile_home_and_rechecks_before_worker_execution(service, tmp_path, monkeypatch):
    from claude_china.desktop import terminal_history, terminal_host
    session_id = '019a1111-2222-7333-8444-555555555555'
    home = tmp_path / 'history'
    path = home / 'projects/encoded' / (session_id + '.jsonl')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'type': 'user', 'sessionId': session_id, 'cwd': str(tmp_path)}) + '\n')
    monkeypatch.setattr(terminal_history, 'profile_home', lambda record: home)
    monkeypatch.setattr(terminal_host, 'jobs_dir', lambda: tmp_path / 'jobs')
    open_terminal = Mock()
    monkeypatch.setattr(terminal_host, 'open_terminal', open_terminal)
    service.save_profile(api_profile())
    assert service.history('work')['sessions'][0]['id'] == session_id
    argv, env = service.prepare('work', str(tmp_path), session_id=session_id)
    assert argv == ['fixture-claude', '--resume', session_id, '--model', 'model with spaces']
    assert env['ANTHROPIC_AUTH_TOKEN'] == 'private-test-token'
    service.resume_session('work', session_id)
    job = json.loads(open_terminal.call_args.args[0].read_text())
    assert job['session_id'] == session_id and 'private-test-token' not in json.dumps(job)
    assert service.workspace()['last_profile'] == 'work'
    path.unlink()
    with pytest.raises(ValueError, match='会话'):
        service.prepare('work', str(tmp_path), session_id=session_id)


def test_resume_cannot_bypass_environment_checks(service, tmp_path, monkeypatch):
    from claude_china.desktop import terminal_history, terminal_host
    session_id = '019a1111-2222-7333-8444-555555555555'
    monkeypatch.setattr(terminal_history, 'list_sessions', lambda *args: {'sessions': [
        {'id': session_id, 'directory': str(tmp_path), 'available': True}], 'warnings': [], 'truncated': False})
    service.save_profile(api_profile())
    monkeypatch.setattr(safety, 'inspect_environment', lambda *args: {'status': 'unknown'})
    opened = Mock()
    monkeypatch.setattr(terminal_host, 'open_terminal', opened)
    with pytest.raises(ValueError, match='安全检查'):
        service.resume_session('work', session_id)
    opened.assert_not_called()


def test_failed_terminal_open_does_not_add_successful_project_history(service, tmp_path, monkeypatch):
    from claude_china.desktop import terminal_host
    monkeypatch.setattr(terminal_host, 'jobs_dir', lambda: tmp_path / 'jobs')
    monkeypatch.setattr(terminal_host, 'open_terminal', Mock(side_effect=OSError('fixture')))
    with pytest.raises(OSError):
        service.launch(None, str(tmp_path))
    assert service.workspace()['recent_directories'] == []


def test_new_session_rejects_defaults_that_would_resume_an_old_session(service, tmp_path):
    service.save_profile(dict(api_profile(), default_args=['--continue']))
    with pytest.raises(ValueError, match='默认参数'):
        service.prepare('work', str(tmp_path))


def test_resume_worker_runs_fake_cli_with_cwd_profile_environment_and_literal_id(service, tmp_path, monkeypatch):
    import sys
    from claude_china.desktop import terminal_host, terminal_history, platforms
    session_id = '019a1111-2222-7333-8444-555555555555'
    service.save_profile(dict(api_profile(), type='grok', default_args=['--model', 'literal model']))
    monkeypatch.setenv('OPENAI_API_KEY', 'other-account-must-not-leak')
    monkeypatch.setattr(terminal_history, 'list_sessions', lambda *args: {'sessions': [
        {'id': session_id, 'directory': str(tmp_path), 'available': True}], 'warnings': [], 'truncated': False})
    monkeypatch.setattr(platforms, 'get_backend', lambda: service.backend)
    monkeypatch.setattr(terminal_host, 'jobs_dir', lambda: tmp_path / 'jobs')
    recorder = tmp_path / 'fake_cli.py'
    recorder.write_text('import json, os, sys\nfrom pathlib import Path\n'
                        'Path("received.json").write_text(json.dumps({"argv":sys.argv[1:],"cwd":os.getcwd(),'
                        '"key":os.environ.get("XAI_API_KEY"),"leaked":os.environ.get("OPENAI_API_KEY")}))\n')
    monkeypatch.setattr(terminals, 'resolve_cli_argv', lambda kind: [sys.executable, str(recorder)])
    job = terminal_host.create_job('work', str(tmp_path), session_id=session_id)
    assert terminal_host.run_session(job) == 0
    received = json.loads((tmp_path / 'received.json').read_text())
    assert received == {'argv': ['--resume', session_id, '--model', 'literal model'], 'cwd': str(tmp_path),
                        'key': 'private-test-token', 'leaked': None}
