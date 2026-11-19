from concurrent.futures import ThreadPoolExecutor

import pytest
from typer.testing import CliRunner

from src.claude_china import cli, config
from src.claude_china.models import profile_from_dict
from src.claude_china.profiles import _secret_input, add_profile, show_profile


def test_show_masks_credentials_unless_explicitly_revealed(capsys):
    data = {'profiles': {'work': {
        'name': 'work', 'type': 'claude', 'mode': 'api',
        'base_url': 'https://api.example.test', 'token': 'secret-token',
    }}}
    show_profile(data, 'work')
    output = capsys.readouterr().out
    assert 'secret-token' not in output
    assert 'Token: ********' in output
    show_profile(data, 'work', reveal=True)
    assert 'Token: secret-token' in capsys.readouterr().out


def test_show_command_requires_reveal_for_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.save_config({'profiles': {'work': {
        'name': 'work', 'type': 'codex', 'mode': 'api', 'api_key': 'private-key',
    }}})
    runner = CliRunner()
    result = runner.invoke(cli.app, ['show', 'work'])
    assert result.exit_code == 0
    assert 'private-key' not in result.stdout and '********' in result.stdout
    result = runner.invoke(cli.app, ['show', 'work', '--reveal'])
    assert result.exit_code == 0 and 'private-key' in result.stdout


def test_interactive_secret_uses_hidden_prompt_on_a_terminal(monkeypatch):
    monkeypatch.setattr('src.claude_china.profiles.sys.stdin.isatty', lambda: True)
    hidden = pytest.MonkeyPatch()
    hidden.setattr('src.claude_china.profiles.getpass.getpass', lambda prompt: 'hidden-key')
    hidden.setattr('builtins.input', lambda prompt: pytest.fail('secret must not use echoing input'))
    try:
        assert _secret_input('API key: ') == 'hidden-key'
    finally:
        hidden.undo()


@pytest.mark.parametrize('record', [
    {'name': 'bad', 'type': 'claude', 'mode': 'logni'},
    {'name': 'bad', 'type': 'unknown', 'mode': 'api'},
    {'name': 'bad', 'type': 'claude', 'mode': 'api', 'api_key': 42},
])
def test_invalid_profile_schema_fails_closed(record):
    with pytest.raises(ValueError):
        profile_from_dict(record)


def test_invalid_stored_profile_is_reported_instead_of_silently_rewritten(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.CONFIG_FILE.write_text(
        "profiles:\n  bad:\n    name: bad\n    type: claude\n    mode: logni\n",
        encoding='utf-8',
    )
    before = config.CONFIG_FILE.read_bytes()
    with pytest.raises(ValueError, match='mode'):
        config.load_config()
    assert config.CONFIG_FILE.read_bytes() == before


def test_transactions_serialize_complete_read_modify_write_cycles(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.save_config({'profiles': {}})

    def add(index):
        with config.transaction() as data:
            data['profiles'][f'profile-{index}'] = {
                'name': f'profile-{index}', 'type': 'claude', 'mode': 'api',
            }

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(add, range(24)))
    assert len(config.load_config()['profiles']) == 24


def test_non_mapping_yaml_is_rejected_without_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.CONFIG_FILE.write_text('- not-a-profile-store\n', encoding='utf-8')
    before = config.CONFIG_FILE.read_bytes()
    with pytest.raises(ValueError, match='mapping'):
        config.load_config()
    assert config.CONFIG_FILE.read_bytes() == before


def test_missing_profiles_mapping_is_migrated_without_dropping_root_extensions(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.CONFIG_FILE.write_text('extension:\n  keep: true\n', encoding='utf-8')
    assert config.load_config() == {'extension': {'keep': True}, 'profiles': {}}
    assert config.load_config()['extension'] == {'keep': True}
