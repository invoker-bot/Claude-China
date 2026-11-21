from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest
from prompt_toolkit.application import Application
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner

from src.claude_china import cli, config, secret_prompt
from src.claude_china.models import profile_from_dict
from src.claude_china.profiles import _secret_input, show_profile


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


def test_secret_counts_pastes_backspace_and_clear_before_enter(monkeypatch):
    monkeypatch.setattr('src.claude_china.profiles.sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('src.claude_china.profiles.sys.stderr.isatty', lambda: True)
    output = DummyOutput()
    writes = []
    monkeypatch.setattr(output, 'write', writes.append)
    monkeypatch.setattr(secret_prompt, 'create_output', lambda stdout: output)
    value = 'XQZ' * 32
    paste = f'\x1b[200~{value}\x1b[201~'
    steps = iter([paste, paste, '\x7f', '\x15', paste, '\r'])
    frames = []

    with create_pipe_input() as keyboard:
        def after_render(app):
            if not app.is_done:
                row = app.renderer.last_rendered_screen.data_buffer[0]
                frames.append(''.join(row[x].char for x in range(output.get_size().columns)).rstrip())
                keyboard.send_text(next(steps, '\r'))

        monkeypatch.setattr(secret_prompt, 'Application',
                            partial(Application, input=keyboard, after_render=after_render))
        assert _secret_input('API key: ') == value

    assert frames == [f'API key: {count} chars (Ctrl+U to clear)'
                      for count in [0, 96, 192, 191, 0, 96]]
    assert not set(value).intersection(''.join(writes))


def test_terminal_secret_falls_back_to_hidden_input_when_stderr_is_redirected(monkeypatch):
    monkeypatch.setattr('src.claude_china.profiles.sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('src.claude_china.profiles.sys.stderr.isatty', lambda: False)
    monkeypatch.setattr('src.claude_china.profiles.getpass.getpass', lambda prompt: 'hidden-key')
    monkeypatch.setattr('builtins.input', lambda prompt: pytest.fail('secret must not use echoing input'))
    assert _secret_input('API key: ') == 'hidden-key'


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
