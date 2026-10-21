from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from claude_china.desktop import config, safety, takeover
from claude_china.desktop.platforms.windows import WindowsBackend


@pytest.fixture
def guard(tmp_path, monkeypatch):
    target = tmp_path / 'Grok Bot.exe'
    target.write_bytes(b'fixture')
    data = deepcopy(config.DEFAULTS)
    data.update(check_system_proxy=False, env_vars={'TAKEOVER_TEST': 'common'})
    data['apps'] = {'grok-bot': {'env_vars': {'TAKEOVER_TEST': 'app'}}}
    monkeypatch.setattr(config, 'load_desktop_config', lambda: deepcopy(data))
    check = Mock(return_value={'status': 'supported', 'reason': 'fixture'})
    monkeypatch.setattr(safety, 'inspect_environment', check)
    return target, data, check


@pytest.mark.parametrize('status', ['unsupported', 'unknown'])
def test_takeover_never_prepares_environment_when_guard_blocks(guard, status):
    target, _, check = guard
    check.return_value = {'status': status, 'reason': 'fixture'}
    result, env = takeover.prepare_launch(target)
    assert not result['ok']
    assert env is None


def test_takeover_rechecks_and_reloads_settings_on_every_restart(guard):
    target, data, check = guard
    first, env = takeover.prepare_launch(target)
    assert first['ok'] and env['TAKEOVER_TEST'] == 'app'
    data['apps']['grok-bot']['env_vars']['TAKEOVER_TEST'] = 'updated'
    second, env = takeover.prepare_launch(target)
    assert second['ok'] and env['TAKEOVER_TEST'] == 'updated'
    check.return_value = {'status': 'unsupported', 'reason': 'fixture'}
    blocked, env = takeover.prepare_launch(target)
    assert not blocked['ok'] and env is None
    assert check.call_count == 3


def test_restart_removes_old_injection_and_restores_original_environment(guard):
    target, data, _ = guard
    _, first = takeover.prepare_launch(target, inherited={'TAKEOVER_TEST': 'OS value', 'PATH': 'keep'})
    assert first['TAKEOVER_TEST'] == 'app'
    data['env_vars'].clear()
    data['apps']['grok-bot']['env_vars'].clear()
    result, restarted = takeover.prepare_launch(target, inherited=first)
    assert result['ok']
    assert restarted['TAKEOVER_TEST'] == 'OS value'
    assert restarted['PATH'] == 'keep'


@pytest.mark.parametrize('name', ['Claude.exe', 'Codex.exe', 'Uninstall Grok Bot.exe'])
def test_takeover_refuses_every_other_application(tmp_path, name):
    target = tmp_path / name
    target.touch()
    with pytest.raises(ValueError, match='Grok Bot'):
        takeover.checked_target(target)


def test_takeover_does_not_stop_or_launch_an_existing_app_during_preflight(guard, monkeypatch):
    target, _, _ = guard
    stop = Mock(side_effect=AssertionError('Do not stop any app'))
    launch = Mock(side_effect=AssertionError('Do not launch during preflight'))
    monkeypatch.setattr(WindowsBackend, 'stop', stop)
    monkeypatch.setattr(WindowsBackend, 'launch', launch)
    assert takeover.prepare_launch(target)[0]['ok']
    stop.assert_not_called()
    launch.assert_not_called()


@pytest.mark.parametrize('app_id,name', [('claude', 'Claude.exe'), ('codex', 'Codex.exe'),
                                       ('grok-bot', 'Grok Bot.exe')])
def test_each_app_rechecks_and_uses_only_its_own_settings(guard, app_id, name):
    target, data, check = guard
    target = target.with_name(name)
    target.touch()
    data['apps'][app_id] = {'env_vars': {'ONLY_THIS_APP': app_id}}
    first, env = takeover.prepare_launch(target, inherited={}, app_id=app_id)
    assert first['ok'] and env['ONLY_THIS_APP'] == app_id
    assert check.call_args.args[0] == app_id
    data['apps'][app_id]['env_vars'] = {'NEW_SETTING': 'new'}
    second, env = takeover.prepare_launch(target, inherited=env, app_id=app_id)
    assert second['ok'] and env['NEW_SETTING'] == 'new'
    assert 'ONLY_THIS_APP' not in env
    check.return_value = {'status': 'unknown', 'reason': 'fixture'}
    blocked, env = takeover.prepare_launch(target, inherited=env, app_id=app_id)
    assert not blocked['ok'] and env is None
    assert check.call_count == 3


@pytest.mark.parametrize('platform', ['win32', 'darwin', 'linux'])
def test_preflight_delegates_proxy_to_selected_platform_without_launching(guard, monkeypatch, platform):
    from claude_china.desktop.platforms import get_backend
    monkeypatch.setattr(sys, 'platform', platform)
    backend = get_backend()
    monkeypatch.setattr(backend, 'system_http_proxy', Mock(return_value='http://127.0.0.1:1234'))
    monkeypatch.setattr(backend, 'proxy_enabled', Mock(return_value=True))
    monkeypatch.setattr(backend, 'stop', Mock(side_effect=AssertionError('must not stop')))
    monkeypatch.setattr(backend, 'launch', Mock(side_effect=AssertionError('must not launch')))
    target, data, _ = guard
    data.update(auto_proxy_env=True, check_system_proxy=True)
    result, env = takeover.prepare_launch(target, inherited={}, backend=backend)
    assert result['ok']
    assert env['HTTP_PROXY'] == env['HTTPS_PROXY'] == 'http://127.0.0.1:1234'
    backend.system_http_proxy.assert_called_once()
    backend.stop.assert_not_called()
    backend.launch.assert_not_called()


def test_proxy_parse_error_blocks_all_apps(guard, monkeypatch):
    from claude_china.desktop.proxy import SystemProxyError
    target, data, _ = guard
    data['auto_proxy_env'] = True
    backend = WindowsBackend()
    monkeypatch.setattr(backend, 'system_http_proxy', Mock(side_effect=SystemProxyError('invalid')))
    for app_id in ('claude', 'codex', 'grok-bot'):
        result, env = takeover.prepare_launch(target, app_id=app_id, backend=backend)
        assert not result['ok'] and env is None


@pytest.mark.parametrize('app_id,name', [('claude', 'Claude.exe'), ('codex', 'Codex.exe')])
def test_manifest_binds_each_application_to_its_executable(tmp_path, app_id, name):
    target = tmp_path / name
    target.touch()
    manifest = {'schema': 1, 'app_id': app_id, 'target': str(target), 'owner': 'a' * 32}
    assert takeover.validate_manifest(manifest, [str(target), '--deep-link']) == target.resolve()
    manifest['app_id'] = 'grok-bot'
    with pytest.raises(ValueError):
        takeover.validate_manifest(manifest, [str(target)])


def test_takeover_manifest_rejects_target_replacement_or_other_app(tmp_path):
    target = tmp_path / 'Grok Bot.exe'
    target.touch()
    manifest = {'schema': 1, 'app_id': 'grok-bot', 'target': str(target), 'owner': 'a' * 32}
    assert takeover.validate_manifest(manifest, [str(target), '--argument']) == target.resolve()
    with pytest.raises(ValueError):
        takeover.validate_manifest(manifest, [str(tmp_path / 'Claude.exe')])
    manifest['app_id'] = 'claude'
    with pytest.raises(ValueError):
        takeover.validate_manifest(manifest, [str(target)])


def test_takeover_accepts_replaced_executable_at_same_path(guard):
    target, _, check = guard
    assert takeover.prepare_launch(target)[0]['ok']
    replacement = target.with_suffix('.new')
    replacement.write_bytes(b'new release')
    replacement.replace(target)
    assert takeover.prepare_launch(target)[0]['ok']
    assert check.call_count == 2


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native child identity')
def test_native_hook_preserves_child_pid_environment_and_exit_status(tmp_path):
    from claude_china.desktop.takeover_native import hook_path, launch_with_hook
    import psutil
    if not hook_path().is_file():
        pytest.skip('Build tools/build_windows_hook.py first')
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    source = tmp_path / 'NativeGuard.cs'
    source.write_text('''using System; using System.IO; using System.Diagnostics;
class Probe { static int Main(string[] args) {
    if(args[0]=="--type=utility") {
        File.WriteAllLines(args[1], new[]{Process.GetCurrentProcess().Id.ToString(), Environment.GetEnvironmentVariable("GUARD_FIXTURE")});
        return 17;
    }
    var child = Process.Start(new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName,
        "--type=utility \\\""+args[0]+"\\\"") {UseShellExecute=false, CreateNoWindow=true});
    child.WaitForExit();
    var report=File.ReadAllLines(args[0]);
    return report[0]==child.Id.ToString() && report[1]=="injected" && child.ExitCode==17 ? 0 : 41;
} }''', encoding='utf-8')
    target = tmp_path / 'Grok Bot.exe'
    subprocess.run([str(compiler), '/nologo', '/platform:x64', '/out:' + str(target), str(source)],
                   check=True, capture_output=True, timeout=30)
    pid = launch_with_hook([str(target), str(tmp_path / 'child report.txt')],
                           dict(os.environ, GUARD_FIXTURE='injected'), str(tmp_path))
    assert psutil.Process(pid).wait(timeout=15) == 0


def test_broker_entry_dispatches_before_single_instance_gui(monkeypatch, tmp_path):
    from claude_china.desktop import entry
    call = Mock(return_value=17)
    monkeypatch.setattr(takeover, 'run_broker', call)
    path = tmp_path / 'manifest.json'
    assert entry.main(['--takeover-launch', str(path), '--', 'Grok Bot.exe', 'quoted argument']) == 17
    call.assert_called_once_with(path, ['Grok Bot.exe', 'quoted argument'])
