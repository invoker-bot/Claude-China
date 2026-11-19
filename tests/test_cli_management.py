import json
from unittest.mock import Mock

from typer.testing import CliRunner

from src.claude_china import antigravity, cli, config, diagnostics


def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.save_config({'profiles': {}})
    return CliRunner()


def test_noninteractive_add_reads_secret_from_stdin_without_echoing(tmp_path, monkeypatch):
    runner = isolated_config(tmp_path, monkeypatch)
    result = runner.invoke(cli.app, [
        'add', '--name', 'work', '--type', 'codex', '--base-url', 'https://api.example.test/v1',
        '--proxy', 'http://127.0.0.1:7890', '--default-args', '--model gpt-test', '--secret-stdin',
    ], input='stdin-secret\n')
    assert result.exit_code == 0, result.output
    assert 'stdin-secret' not in result.stdout
    record = config.load_config()['profiles']['work']
    assert record['api_key'] == 'stdin-secret'
    assert record['default_args'] == '--model gpt-test'
    assert record['base_url'] == 'https://api.example.test/v1'


def test_noninteractive_antigravity_add_applies_explicit_api_setup(tmp_path, monkeypatch):
    runner = isolated_config(tmp_path, monkeypatch)
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path / 'home')
    result = runner.invoke(cli.app, [
        'add', '--name', 'google', '--type', 'antigravity', '--secret-stdin',
    ], input='gemini-secret\n')
    assert result.exit_code == 0, result.output
    record = config.load_config()['profiles']['google']
    assert record['base_url'] == '' and record['api_key'] == 'gemini-secret'
    settings = json.loads(antigravity.settings_path().read_text(encoding='utf-8'))
    assert settings['modelProvider'] == 'gemini'


def test_duplicate_or_invalid_noninteractive_add_leaves_store_unchanged(tmp_path, monkeypatch):
    runner = isolated_config(tmp_path, monkeypatch)
    before = config.CONFIG_FILE.read_bytes()
    for arguments in [
        ['add', '--type', 'claude'],
        ['add', '--name', 'bad', '--type', 'unknown'],
        ['add', '--name', 'bad', '--type', 'claude', '--base-url', 'javascript:bad'],
        ['add', '--name', 'bad', '--type', 'antigravity', '--mode', 'login'],
    ]:
        result = runner.invoke(cli.app, arguments)
        assert result.exit_code != 0
        assert config.CONFIG_FILE.read_bytes() == before


def test_edit_renames_and_updates_without_losing_saved_secret(tmp_path, monkeypatch):
    runner = isolated_config(tmp_path, monkeypatch)
    config.save_config({'profiles': {'work': {
        'name': 'work', 'type': 'claude', 'mode': 'api', 'base_url': 'https://old.example.test',
        'token': 'keep-secret', 'proxy': 'http://old.example.test:8080', 'extension': 'preserve',
    }}})
    result = runner.invoke(cli.app, [
        'edit', 'work', '--name', 'renamed', '--base-url', 'https://new.example.test',
        '--default-args', '--model new', '--clear-proxy',
    ])
    assert result.exit_code == 0, result.output
    profiles = config.load_config()['profiles']
    assert 'work' not in profiles
    record = profiles['renamed']
    assert record['token'] == 'keep-secret' and record['extension'] == 'preserve'
    assert record['base_url'] == 'https://new.example.test'
    assert record['default_args'] == '--model new' and 'proxy' not in record
    result = runner.invoke(cli.app, ['edit', 'renamed', '--secret-stdin'], input='new-secret\n')
    assert result.exit_code == 0 and 'new-secret' not in result.stdout
    assert config.load_config()['profiles']['renamed']['token'] == 'new-secret'
    assert runner.invoke(cli.app, ['edit', 'renamed', '--clear-secret']).exit_code == 0
    assert 'token' not in config.load_config()['profiles']['renamed']


def test_edit_authentication_mode_removes_incompatible_fields(tmp_path, monkeypatch):
    runner = isolated_config(tmp_path, monkeypatch)
    config.save_config({'profiles': {'work': {
        'name': 'work', 'type': 'codex', 'mode': 'api', 'base_url': 'https://api.example.test',
        'api_key': 'secret',
    }}})
    result = runner.invoke(cli.app, ['edit', 'work', '--mode', 'login'])
    assert result.exit_code == 0, result.output
    record = config.load_config()['profiles']['work']
    assert record['mode'] == 'login' and record['credentials_path']
    assert 'api_key' not in record and 'base_url' not in record
    result = runner.invoke(cli.app, ['edit', 'work', '--mode', 'api'])
    assert result.exit_code == 0
    record = config.load_config()['profiles']['work']
    assert record['mode'] == 'api' and 'credentials_path' not in record


def test_edit_rejects_noop_conflicts_and_incompatible_options(tmp_path, monkeypatch):
    runner = isolated_config(tmp_path, monkeypatch)
    config.save_config({'profiles': {'work': {'name': 'work', 'type': 'claude', 'mode': 'api'}}})
    before = config.CONFIG_FILE.read_bytes()
    for arguments in [
        ['edit', 'work'],
        ['edit', 'work', '--secret-stdin', '--clear-secret'],
        ['edit', 'work', '--proxy', 'http://localhost:7890', '--clear-proxy'],
        ['edit', 'work', '--mode', 'login', '--base-url', 'https://api.example.test'],
    ]:
        assert runner.invoke(cli.app, arguments).exit_code != 0
        assert config.CONFIG_FILE.read_bytes() == before


def test_doctor_checks_profile_and_never_prints_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.save_config({'profiles': {'work': {
        'name': 'work', 'type': 'codex', 'mode': 'api', 'api_key': 'doctor-secret',
    }}})
    monkeypatch.setattr(diagnostics, 'find_command', lambda kind: '/usr/bin/codex')
    report = diagnostics.collect('work')
    assert report['ok'] and report['tools'][0]['id'] == 'codex'
    assert 'doctor-secret' not in str(report)
    result = CliRunner().invoke(cli.app, ['doctor', 'work'])
    assert result.exit_code == 0 and 'doctor-secret' not in result.stdout
    assert "Profile 'work'" in result.stdout


def test_doctor_reports_missing_command_and_antigravity_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    monkeypatch.setattr(antigravity.Path, 'home', lambda: tmp_path / 'home')
    config.save_config({'profiles': {'google': {
        'name': 'google', 'type': 'antigravity', 'mode': 'api', 'api_key': 'secret',
    }}})
    monkeypatch.setattr(diagnostics, 'find_command', lambda kind: None)
    report = diagnostics.collect('google')
    assert not report['ok']
    messages = report['profiles'][0]['errors']
    assert any('agy' in message for message in messages)
    assert any('modelProvider' in message for message in messages)
    result = CliRunner().invoke(cli.app, ['doctor', 'google'])
    assert result.exit_code == 1 and 'secret' not in result.stdout


def test_doctor_optional_version_check_uses_real_command_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.save_config({'profiles': {}})
    monkeypatch.setattr(diagnostics, 'find_command', lambda kind: '/bin/cli')
    monkeypatch.setattr(diagnostics, 'command_version', lambda kind: kind + ' 1.2.3')
    report = diagnostics.collect(versions=True)
    assert report['ok'] and len(report['tools']) == 4
    assert all(tool['version'].endswith('1.2.3') for tool in report['tools'])
