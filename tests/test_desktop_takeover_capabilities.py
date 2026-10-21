"""Unsupported launch routes must never be reported as globally protected."""

from copy import deepcopy
import json
import sys
from unittest.mock import Mock

import pytest

from claude_china.desktop import config, takeover, takeover_windows
from claude_china.desktop.apps import get_app
from claude_china.desktop.bridge import LauncherBridge
from claude_china.desktop.platforms.base import AppStatus
from claude_china.desktop.platforms.windows import WindowsBackend


@pytest.fixture
def windows_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    hook = tmp_path / 'hook.dll'
    hook.touch()
    monkeypatch.setattr(takeover_windows, 'hook_path', lambda: hook)
    monkeypatch.setattr(takeover_windows, 'manifest_path', lambda app_id='grok-bot': tmp_path / (app_id + '.json'))
    monkeypatch.setattr(takeover_windows, 'read_registration', Mock(return_value=None))
    return tmp_path


@pytest.mark.parametrize('app_id', ['claude', 'codex', 'grok-bot'])
def test_stable_executable_can_be_selected_independently(windows_runtime, app_id):
    target = windows_runtime / takeover.WINDOWS_EXECUTABLES[app_id]
    target.touch()
    status = AppStatus(app_id, True, True, str(target), str(target))
    result = takeover.get_status(app_id, status)
    assert result['supported'] and not result['enabled']
    assert result['app_id'] == app_id


@pytest.mark.parametrize('app_id', ['claude', 'codex'])
def test_msix_never_exposes_enable_or_writes_registration(windows_runtime, monkeypatch, app_id):
    status = AppStatus(app_id, True, False, get_app(app_id).win_aumid, str(windows_runtime))
    write = Mock(side_effect=AssertionError('must not register MSIX'))
    monkeypatch.setattr(takeover_windows, 'set_enabled', write)
    result = takeover.get_status(app_id, status)
    assert not result['supported'] and not result['enabled']
    assert result['mode'] == 'msix-unavailable'
    with pytest.raises(ValueError, match='MSIX'):
        takeover.set_enabled(app_id, True, status)
    write.assert_not_called()


@pytest.mark.parametrize('platform,description', [('darwin', 'macOS'), ('linux', 'Linux')])
def test_other_platforms_do_not_claim_global_support_or_use_windows_registration(monkeypatch, platform, description):
    monkeypatch.setattr(sys, 'platform', platform)
    read = Mock(side_effect=AssertionError('no Windows registry on this platform'))
    write = Mock(side_effect=AssertionError('no Windows registry on this platform'))
    monkeypatch.setattr(takeover_windows, 'get_status', read)
    monkeypatch.setattr(takeover_windows, 'set_enabled', write)
    for app_id in ('claude', 'codex', 'grok-bot'):
        status = AppStatus(app_id, True, True, '/Applications/vendor')
        result = takeover.get_status(app_id, status)
        assert not result['supported'] and not result['enabled']
        assert description in result['message']
        with pytest.raises(ValueError, match=description):
            takeover.set_enabled(app_id, True, status)
    read.assert_not_called()
    write.assert_not_called()


def test_changed_path_reports_unprotected_but_allows_removal(windows_runtime, monkeypatch):
    target = windows_runtime / 'Claude.exe'
    target.touch()
    manifest = {'schema': 1, 'app_id': 'claude', 'owner': 'a' * 32,
                'target': str(target), 'broker': sys.executable}
    path = takeover_windows.manifest_path('claude')
    path.write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(takeover_windows, 'read_registration', lambda app_id: {
        'owner': manifest['owner'], 'enabled': 1, 'target': str(target),
        'debugger': takeover_windows.debugger_command(manifest, path)})
    status = AppStatus('claude', True, True, str(windows_runtime / 'new' / 'Claude.exe'))
    result = takeover.get_status('claude', status)
    assert not result['enabled'] and not result['supported']
    assert result['can_disable']
    assert '旧路径' in result['message']


@pytest.mark.parametrize('broken', ['missing_manifest', 'msix_conversion'])
def test_stale_registration_never_reports_a_working_protected_entry(windows_runtime, monkeypatch, broken):
    target = windows_runtime / 'Claude.exe'
    target.touch()
    manifest = {'schema': 1, 'app_id': 'claude', 'owner': 'a' * 32,
                'target': str(target), 'broker': sys.executable}
    path = takeover_windows.manifest_path('claude')
    if broken != 'missing_manifest':
        path.write_text(json.dumps(manifest), encoding='utf-8')
        (windows_runtime / 'AppxManifest.xml').write_text('<Package/>', encoding='utf-8')
    monkeypatch.setattr(takeover_windows, 'read_registration', lambda app_id: {
        'owner': manifest['owner'], 'enabled': 1, 'target': str(target),
        'debugger': takeover_windows.debugger_command(manifest, path)})
    status = AppStatus('claude', True, True, str(target))
    result = takeover.get_status('claude', status)
    assert not result['enabled'] and not result['supported']
    assert result['can_disable'] == (broken != 'missing_manifest')


def test_bridge_refreshes_only_requested_app_and_never_changes_running_processes(monkeypatch, tmp_path):
    data = deepcopy(config.DEFAULTS)
    monkeypatch.setattr(config, 'load_desktop_config', lambda: deepcopy(data))
    backend = Mock(spec=WindowsBackend)
    backend.detect.side_effect = lambda app, path=None: AppStatus(app.id, True, True, path or str(tmp_path / (app.display + '.exe')))
    backend.stop.side_effect = AssertionError('do not stop any app')
    backend.launch.side_effect = AssertionError('do not launch any app')
    bridge = LauncherBridge(backend)
    backend.reset_mock()
    read = Mock(return_value={'supported': True, 'enabled': False})
    write = Mock(return_value={'supported': True, 'enabled': True})
    monkeypatch.setattr(takeover, 'get_status', read)
    monkeypatch.setattr(takeover, 'set_enabled', write)
    data['apps'] = {'codex': {'path': str(tmp_path / 'new' / 'Codex.exe')}}
    assert not bridge.get_takeover_status('codex')['enabled']
    assert bridge.set_takeover('codex', True)['ok']
    assert all(call.args[0].id == 'codex' for call in backend.detect.call_args_list)
    assert write.call_args.args[0:2] == ('codex', True)
    assert write.call_args.args[2].launch_target == data['apps']['codex']['path']
    backend.stop.assert_not_called()
    backend.launch.assert_not_called()


def test_bridge_rejects_unknown_application_or_non_boolean_without_side_effects(monkeypatch):
    monkeypatch.setattr(config, 'load_desktop_config', lambda: deepcopy(config.DEFAULTS))
    backend = Mock(spec=WindowsBackend)
    bridge = LauncherBridge(backend)
    backend.reset_mock()
    assert not bridge.set_takeover('other', True)['ok']
    assert not bridge.set_takeover('claude', 'false')['ok']
    backend.detect.assert_not_called()


def test_disable_does_not_depend_on_detection_of_removed_vendor_app(monkeypatch):
    monkeypatch.setattr(config, 'load_desktop_config', lambda: deepcopy(config.DEFAULTS))
    backend = Mock(spec=WindowsBackend)
    bridge = LauncherBridge(backend)
    backend.detect.side_effect = OSError('Application removed')
    write = Mock(return_value={'enabled': False})
    monkeypatch.setattr(takeover, 'set_enabled', write)
    assert bridge.set_takeover('codex', False)['ok']
    assert write.call_args.args[0:2] == ('codex', False)
