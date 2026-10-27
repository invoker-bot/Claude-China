from typer.testing import CliRunner

from claude_china import cli, config


def test_login_browser_command_changes_only_the_selected_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.save_config({'profiles': {
        'one': {'name': 'one', 'type': 'claude', 'mode': 'login', 'credentials_path': '~/one'},
        'two': {'name': 'two', 'type': 'claude', 'mode': 'login', 'credentials_path': '~/two'},
    }})
    runner = CliRunner()
    assert runner.invoke(cli.app, ['login-browser', 'one', 'manual']).exit_code == 0
    profiles = config.load_config()['profiles']
    assert profiles['one']['manual_browser_login'] is True
    assert 'manual_browser_login' not in profiles['two']
    assert runner.invoke(cli.app, ['login-browser', 'one', 'auto']).exit_code == 0
    assert 'manual_browser_login' not in config.load_config()['profiles']['one']


def test_login_browser_command_rejects_unknown_modes_and_unsupported_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    original = {'profiles': {'api': {'name': 'api', 'type': 'claude', 'mode': 'api'},
                             'grok': {'name': 'grok', 'type': 'grok', 'mode': 'login'}}}
    config.save_config(original)
    runner = CliRunner()
    for args in [['login-browser', 'api', 'manual'], ['login-browser', 'grok', 'manual'],
                 ['login-browser', 'missing', 'manual'], ['login-browser', 'api', 'invalid']]:
        assert runner.invoke(cli.app, args).exit_code != 0
        assert config.load_config() == original
