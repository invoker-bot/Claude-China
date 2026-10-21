import base64
import json
import os
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

from claude_china.desktop import terminal_host


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    root = tmp_path / 'jobs'
    monkeypatch.setattr(terminal_host, 'jobs_dir', lambda: root)
    return root


def test_job_has_no_credentials_is_single_use_and_expires(jobs, tmp_path, monkeypatch):
    path = terminal_host.create_job('work', str(tmp_path))
    assert set(json.loads(path.read_text())) == {'schema', 'profile', 'directory', 'expires_at'}
    assert terminal_host.consume_job(path)['profile'] == 'work'
    assert not path.exists()
    with pytest.raises(ValueError):
        terminal_host.consume_job(path)
    path = terminal_host.create_job('work', str(tmp_path))
    monkeypatch.setattr(terminal_host.time, 'time', lambda: 10**15)
    with pytest.raises(ValueError, match='过期'):
        terminal_host.consume_job(path)


def test_job_rejects_arbitrary_file_and_does_not_remove_it(jobs, tmp_path):
    other = tmp_path / 'private.json'
    other.write_text('{}')
    with pytest.raises(ValueError):
        terminal_host.consume_job(other)
    assert other.exists()


def test_windows_terminal_command_never_contains_profile_secret(jobs, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(terminal_host.shutil, 'which', lambda name: 'powershell.exe')
    create = Mock()
    monkeypatch.setattr(terminal_host.process, 'Popen', create)
    path = terminal_host.create_job("a profile's name", str(tmp_path))
    terminal_host.open_terminal(path, str(tmp_path))
    args = create.call_args.args[0]
    assert args[0] == 'powershell.exe' and '-NoExit' in args
    script = base64.b64decode(args[-1]).decode('utf-16-le')
    assert 'Start-Process' in script and '-Wait' in script and '-NoNewWindow' in script
    assert str(path) in script
    assert "a profile's name" not in script
    assert not create.call_args.kwargs.get('shell')


def test_linux_terminal_passes_job_and_directory_as_arguments(jobs, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(terminal_host.shutil, 'which', lambda name: '/usr/bin/' + name if name == 'x-terminal-emulator' else None)
    create = Mock()
    monkeypatch.setattr(terminal_host.process, 'Popen', create)
    directory = tmp_path / 'project; touch NOT_ALLOWED'
    directory.mkdir()
    path = terminal_host.create_job(None, str(directory))
    terminal_host.open_terminal(path, str(directory))
    args = create.call_args.args[0]
    assert args[:2] == ['/usr/bin/x-terminal-emulator', '-e']
    assert str(directory) in args and str(path) in args
    assert str(directory) not in args[4]


def test_macos_uses_fixed_applescript_with_quoted_command_as_data(jobs, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(terminal_host.process, 'run', run)
    directory = tmp_path / "project's folder"
    directory.mkdir()
    path = terminal_host.create_job(None, str(directory))
    terminal_host.open_terminal(path, str(directory))
    args = run.call_args.args[0]
    assert args[0] == 'osascript'
    assert 'on run argv' in args[2]
    assert str(directory) not in args[2]
    assert 'do script' in args[2]
    assert "'\"'\"'" in args[-1]


def test_windows_npm_shim_resolves_to_node_argv_without_cmd_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    shim = tmp_path / 'claude.cmd'
    shim.touch()
    package = tmp_path / 'node_modules/@anthropic-ai/claude-code'
    package.mkdir(parents=True)
    (package / 'cli.js').touch()
    (package / 'package.json').write_text(json.dumps({'bin': {'claude': 'cli.js'}}))
    monkeypatch.setattr(terminal_host, 'find_command', lambda kind: str(shim))
    monkeypatch.setattr(terminal_host.shutil, 'which', lambda name: str(tmp_path / 'node.exe'))
    assert terminal_host.resolve_cli_argv('claude') == [str(tmp_path / 'node.exe'), str(package / 'cli.js')]


def test_session_reloads_profile_and_passes_literal_arguments_and_environment(jobs, tmp_path, monkeypatch):
    from claude_china.desktop import terminals
    args = ['fixture', 'space value', 'a&b', "O\'Brien", '$(touch marker)', '%PATH%']
    env = {'ANTHROPIC_AUTH_TOKEN': 'private-fixture'}
    prepare = Mock(return_value=(args, env))
    monkeypatch.setattr(terminals.TerminalService, 'prepare', prepare)
    execute = Mock(return_value=Mock(returncode=17))
    monkeypatch.setattr(terminal_host.process, 'run', execute)
    job = terminal_host.create_job('work', str(tmp_path))
    assert terminal_host.run_session(job) == 17
    prepare.assert_called_once_with('work', str(tmp_path))
    assert execute.call_args.args[0] == args
    assert execute.call_args.kwargs['env'] == env
    assert not execute.call_args.kwargs.get('shell')
    assert not job.exists()


def test_terminal_session_dispatches_before_gui_and_never_restarts_running_apps(jobs, tmp_path, monkeypatch):
    from claude_china.desktop import entry
    run = Mock(return_value=17)
    monkeypatch.setattr(terminal_host, 'run_session', run)
    path = terminal_host.create_job('work', str(tmp_path))
    assert entry.main(['--terminal-session', str(path)]) == 17
    run.assert_called_once_with(path)


def test_worker_rechecks_environment_and_never_runs_cli_when_check_fails(jobs, tmp_path, monkeypatch):
    from claude_china.desktop import terminals
    monkeypatch.setattr(terminals.TerminalService, 'prepare', Mock(side_effect=ValueError('blocked')))
    execute = Mock()
    monkeypatch.setattr(terminal_host.process, 'run', execute)
    job = terminal_host.create_job('work', str(tmp_path))
    assert terminal_host.run_session(job) == 1
    execute.assert_not_called()
    assert not job.exists()
