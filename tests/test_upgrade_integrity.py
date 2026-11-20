from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.claude_china import cli, config, diagnostics, upgrades
from src.claude_china.providers import get_provider


@pytest.mark.parametrize('platform', ['win32', 'linux'])
def test_find_npm_installation_uses_active_prefix_and_package_metadata(tmp_path, monkeypatch, platform):
    provider = get_provider('codex')
    prefix = tmp_path / 'prefix'
    command = prefix / ('codex.cmd' if platform == 'win32' else 'bin/codex')
    package = prefix / ('node_modules' if platform == 'win32' else 'lib/node_modules') / '@openai/codex'
    command.parent.mkdir(parents=True)
    command.write_text('fixture', encoding='utf-8')
    package.mkdir(parents=True)
    (package / 'package.json').write_text('{"name":"@openai/codex","version":"0.170.0"}', encoding='utf-8')
    monkeypatch.setattr(upgrades.sys, 'platform', platform)
    monkeypatch.setattr(upgrades.shutil, 'which', lambda name: 'npm-fixture')
    result = SimpleNamespace(returncode=0, stdout=str(prefix) + '\n')
    monkeypatch.setattr(upgrades.subprocess, 'run', lambda *args, **kwargs: result)
    installation = upgrades.find_npm_installation('codex')
    assert installation.command == str(command)
    assert installation.package_root == str(package)
    assert installation.version == '0.170.0'


def test_version_mismatch_is_an_upgrade_failure(monkeypatch):
    installation = upgrades.NpmInstallation('codex', '/npm/codex', '/npm/package', '0.170.0')
    monkeypatch.setattr(upgrades, 'find_npm_installation', lambda kind: installation)
    monkeypatch.setattr(upgrades, 'find_command', lambda kind: installation.command)
    with pytest.raises(RuntimeError, match='0.167.1.*0.170.0'):
        upgrades.check_npm_installation('codex', installation.command, 'codex-cli 0.167.1')


def test_path_shadowing_is_reported_even_when_versions_match(monkeypatch):
    installation = upgrades.NpmInstallation('claude', '/npm/claude', '/npm/package', '2.1.328')
    monkeypatch.setattr(upgrades, 'find_npm_installation', lambda kind: installation)
    with pytest.raises(RuntimeError, match='shadowed'):
        upgrades.check_npm_installation('claude', '/other/claude', '2.1.328 (Claude Code)')


@pytest.mark.parametrize('output,expected', [
    ('2.1.328 (Claude Code)', '2.1.328'),
    ('codex-cli 0.170.0', '0.170.0'),
    ('grok 1.0.89 (28be5bb1bf65)', '1.0.89'),
    ('agy 1.4.4-beta.1', '1.4.4-beta.1'),
    ('not a version', None),
])
def test_version_output_parsing(output, expected):
    assert upgrades.version_from_output(output) == expected


def test_native_cli_does_not_require_npm_metadata(monkeypatch):
    monkeypatch.setattr(diagnostics, 'command_version', lambda kind, env: 'agy 1.4.4')
    assert upgrades.verify_installation('antigravity', {}) == 'agy 1.4.4'


def test_running_npm_processes_block_before_npm_install(monkeypatch, tmp_path):
    installation = upgrades.NpmInstallation('codex', str(tmp_path / 'codex'), str(tmp_path), '0.170.0')
    monkeypatch.setattr(upgrades, 'find_npm_installation', lambda kind: installation)
    processes = [SimpleNamespace(pid=42, info={'pid': 42, 'exe': str(tmp_path / 'vendor/codex.exe'), 'cmdline': []})]
    import psutil
    monkeypatch.setattr(psutil, 'process_iter', lambda *args, **kwargs: processes)
    with pytest.raises(RuntimeError, match='daemon stop'):
        upgrades.ensure_not_running('codex')

    called = Mock()
    monkeypatch.setattr(cli, '_run_npm', called)
    monkeypatch.setattr(upgrades, 'ensure_not_running', Mock(side_effect=RuntimeError('running')))
    with pytest.raises(RuntimeError, match='running'):
        cli._upgrade_selected([get_provider('codex')], {})
    called.assert_not_called()


def test_doctor_versions_reports_codex_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', tmp_path / 'config.yaml')
    config.save_config({'profiles': {}})
    monkeypatch.setattr(diagnostics, 'find_command', lambda kind: '/npm/' + kind)
    outputs = {'claude': '2.1.328', 'grok': 'grok 1.0.89', 'codex': 'codex-cli 0.167.1', 'antigravity': 'agy 1.0.0'}
    monkeypatch.setattr(diagnostics, 'command_version', lambda kind: outputs[kind])

    def installation(kind):
        if kind == 'codex':
            return upgrades.NpmInstallation(kind, '/npm/codex', '/npm/package', '0.170.0')
        return None

    monkeypatch.setattr(upgrades, 'find_npm_installation', installation)
    monkeypatch.setattr(upgrades, 'validate_native_package', lambda kind: None)
    report = diagnostics.collect(versions=True)
    codex = next(tool for tool in report['tools'] if tool['id'] == 'codex')
    assert not report['ok'] and codex['consistent'] is None
    assert codex['package_version'] == ''
    assert '0.167.1' in codex['error'] and '0.170.0' in codex['error']


def test_missing_codex_platform_binary_has_specific_repair_diagnostic(tmp_path, monkeypatch):
    from src.claude_china.desktop import cli_guard, terminal_host
    monkeypatch.setattr(terminal_host, 'resolve_cli_argv', lambda kind: ['node.exe', str(tmp_path / 'bin/codex.js')])
    monkeypatch.setattr(cli_guard, '_codex_binaries', lambda entry: [tmp_path / 'missing/codex.exe'])
    with pytest.raises(RuntimeError, match='platform package'):
        upgrades.validate_native_package('codex')


def test_existing_codex_platform_binary_passes(tmp_path, monkeypatch):
    from src.claude_china.desktop import cli_guard, terminal_host
    binary = tmp_path / 'vendor/codex.exe'
    binary.parent.mkdir()
    binary.write_bytes(b'fixture')
    monkeypatch.setattr(terminal_host, 'resolve_cli_argv', lambda kind: ['node.exe', str(tmp_path / 'bin/codex.js')])
    monkeypatch.setattr(cli_guard, '_codex_binaries', lambda entry: [binary])
    upgrades.validate_native_package('codex')
