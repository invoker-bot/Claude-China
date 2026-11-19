import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from src.claude_china import antigravity, cli, config, launcher
from src.claude_china.desktop import config as desktop_config
from src.claude_china.desktop.terminals import TerminalService
from src.claude_china.desktop.terminal_history import new_session_args
from src.claude_china.models import ApiProfile, profile_from_dict
from src.claude_china.profiles import add_profile
from src.claude_china.providers import get_provider


def profile(**values):
    values.setdefault('base_url', 'https://gemini.example.test')
    values.setdefault('api_key', 'gemini-test-key')
    return ApiProfile(name='google', type='antigravity', **values)


def enable_api():
    antigravity.settings_path().parent.mkdir(parents=True, exist_ok=True)
    antigravity.settings_path().write_text('{"modelProvider":"gemini"}', encoding='utf-8')


def test_provider_uses_official_command_and_only_api_mode():
    provider = get_provider('antigravity')
    assert provider.command == 'agy'
    assert provider.auth_modes == ('api',)
    assert not provider.npm_package and provider.native_upgrade
    with pytest.raises(ValueError, match='does not support login'):
        profile_from_dict({'name': 'bad', 'type': provider.id, 'mode': 'login'})


def test_api_environment_requires_key_and_explicit_provider_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path)
    with pytest.raises(ValueError, match='modelProvider'):
        launcher.prepare_environment(profile(), base_env={})
    enable_api()
    with pytest.raises(ValueError, match='missing api_key'):
        launcher.prepare_environment(profile(api_key=None), base_env={})
    env = launcher.prepare_environment(profile(), base_env={
        'GEMINI_API_KEY': 'stale-key', 'GOOGLE_GEMINI_BASE_URL': 'https://stale.example.test',
        'AGY_ADC_AUTH': 'true', 'ANTHROPIC_AUTH_TOKEN': 'must-not-leak',
    })
    assert env['GEMINI_API_KEY'] == 'gemini-test-key'
    assert env['GOOGLE_GEMINI_BASE_URL'] == 'https://gemini.example.test'
    assert 'AGY_ADC_AUTH' not in env and 'ANTHROPIC_AUTH_TOKEN' not in env


def test_blank_endpoint_uses_cli_default(tmp_path, monkeypatch):
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path)
    enable_api()
    env = launcher.prepare_environment(profile(base_url=''), base_env={})
    assert 'GOOGLE_GEMINI_BASE_URL' not in env


def test_configure_preserves_unrelated_settings_and_rejects_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path)
    path = antigravity.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'theme': 'dark', 'permissions': {'allow': ['Read']}}), encoding='utf-8')
    assert antigravity.configure_gemini_api() == path
    assert json.loads(path.read_text(encoding='utf-8')) == {
        'theme': 'dark', 'permissions': {'allow': ['Read']}, 'modelProvider': 'gemini',
    }
    path.write_text('{broken', encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='invalid'):
        antigravity.configure_gemini_api()
    assert path.read_bytes() == before


def test_interactive_add_configures_antigravity_without_login_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path)
    inputs = iter(['google', 'antigravity', '', 'api-secret', '', '--model flash'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(inputs))
    data = add_profile({'profiles': {}})
    record = data['profiles']['google']
    assert record['mode'] == 'api' and record['api_key'] == 'api-secret'
    assert record['base_url'] == ''
    assert json.loads(antigravity.settings_path().read_text(encoding='utf-8'))['modelProvider'] == 'gemini'


def test_configure_command_is_explicit_and_does_not_print_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path)
    result = CliRunner().invoke(cli.app, ['configure', 'antigravity'])
    assert result.exit_code == 0
    assert 'modelProvider' not in result.stdout
    assert json.loads(antigravity.settings_path().read_text(encoding='utf-8'))['modelProvider'] == 'gemini'


def test_desktop_profile_save_and_launch_preparation_share_api_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    monkeypatch.setattr(desktop_config, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    monkeypatch.setattr('src.claude_china.desktop.terminals.resolve_cli_argv', lambda kind: ['fixture-agy'])
    monkeypatch.setattr('src.claude_china.desktop.safety.inspect_environment', Mock(return_value={'status': 'supported'}))
    service = TerminalService(Mock())
    saved = service.save_profile({
        'name': 'google', 'type': 'antigravity', 'mode': 'api', 'base_url': '',
        'secret': 'desktop-secret', 'proxy': '', 'default_args': ['--model', 'flash'],
    })
    assert saved['has_secret'] and saved['supported']
    argv, env = service.prepare('google', str(tmp_path))
    assert argv == ['fixture-agy', '--model', 'flash']
    assert env['GEMINI_API_KEY'] == 'desktop-secret'
    assert service.history('google')['sessions'] == []
    assert service.history('google')['warnings']


def test_launch_forwards_arguments_to_agy_with_prepared_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(desktop_config, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    desktop_config.save_desktop_config({'safety_check': False})
    enable_api()
    monkeypatch.setattr(launcher.sys, 'platform', 'linux')
    monkeypatch.setattr(launcher, 'find_command', lambda kind: '/usr/local/bin/agy')
    with patch.object(launcher.os, 'execvpe') as execute:
        launcher.launch({
            'name': 'google', 'type': 'antigravity', 'mode': 'api',
            'api_key': 'launch-key', 'default_args': ['--model', 'flash'],
        }, ['--mode', 'plan'])
    assert execute.call_args.args[:2] == (
        '/usr/local/bin/agy', ['/usr/local/bin/agy', '--mode', 'plan', '--model', 'flash'],
    )
    assert execute.call_args.args[2]['GEMINI_API_KEY'] == 'launch-key'


def test_agy_defaults_cannot_switch_workspace_or_conversation_in_managed_terminal():
    for arguments in [['--conversation', 'id'], ['--remote-agent'], ['--project', 'other'], ['--new-project']]:
        with pytest.raises(ValueError, match='默认参数'):
            new_session_args('antigravity', arguments)
    assert new_session_args('antigravity', ['--mode', 'plan']) == ['--mode', 'plan']


def test_working_tree_cli_launches_real_fake_agy_process_end_to_end(tmp_path):
    root = Path(__file__).resolve().parents[1]
    home = tmp_path / 'home'
    home.mkdir()
    binary_dir = tmp_path / 'bin'
    binary_dir.mkdir()
    output = tmp_path / 'received.json'
    recorder = tmp_path / 'fake_agy.py'
    recorder.write_text(
        'import json, os, sys\n'
        'from pathlib import Path\n'
        'Path(os.environ["FAKE_AGY_OUTPUT"]).write_text(json.dumps({\n'
        '  "argv": sys.argv[1:], "key": os.environ.get("GEMINI_API_KEY"),\n'
        '  "endpoint": os.environ.get("GOOGLE_GEMINI_BASE_URL"),\n'
        '  "stale": os.environ.get("ANTHROPIC_AUTH_TOKEN")}), encoding="utf-8")\n'
        'print("fake agy completed")\n',
        encoding='utf-8',
    )
    if os.name == 'nt':
        command = binary_dir / 'agy.cmd'
        command.write_text(f'@echo off\r\n"{sys.executable}" "{recorder}" %*\r\n', encoding='utf-8')
    else:
        command = binary_dir / 'agy'
        command.write_text(f'#!{sys.executable}\n' + recorder.read_text(encoding='utf-8'), encoding='utf-8')
        command.chmod(0o755)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(('CLAUDEC_', 'ANTHROPIC_', 'OPENAI_', 'GEMINI_', 'GOOGLE_GEMINI_', 'AGY_')):
            env.pop(key, None)
    env.update(HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(tmp_path / 'local'),
               PYTHONPATH=str(root / 'src'), PATH=str(binary_dir) + os.pathsep + env.get('PATH', ''),
               FAKE_AGY_OUTPUT=str(output), PYTHONIOENCODING='utf-8')
    base = [sys.executable, '-m', 'claude_china.cli']
    added = subprocess.run(base + ['add', '--name', 'google', '--type', 'antigravity',
                                   '--base-url', 'https://gemini.example.test', '--default-args', '--model flash',
                                   '--secret-stdin'], input='process-secret\n', text=True, capture_output=True,
                           cwd=root, env=env, timeout=30)
    assert added.returncode == 0, added.stderr
    assert 'process-secret' not in added.stdout + added.stderr
    shown = subprocess.run(base + ['show', 'google'], text=True, capture_output=True,
                           cwd=root, env=env, timeout=30)
    assert shown.returncode == 0 and 'process-secret' not in shown.stdout and '********' in shown.stdout
    doctor = subprocess.run(base + ['doctor', 'google'], text=True, capture_output=True,
                            cwd=root, env=env, timeout=30)
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    env['ANTHROPIC_AUTH_TOKEN'] = 'must-not-leak'
    launched = subprocess.run(base + ['run', 'google', '--mode', 'plan'], text=True, capture_output=True,
                              cwd=root, env=env, timeout=30)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    assert 'fake agy completed' in launched.stdout
    received = json.loads(output.read_text(encoding='utf-8'))
    assert received == {'argv': ['--mode', 'plan', '--model', 'flash'], 'key': 'process-secret',
                        'endpoint': 'https://gemini.example.test', 'stale': None}


def test_settings_keep_google_upstream_directory_after_provider_rename(tmp_path, monkeypatch):
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path)
    assert antigravity.settings_path() == tmp_path / '.gemini' / 'antigravity-cli' / 'settings.json'
