from threading import Event
from unittest.mock import MagicMock, Mock
from pathlib import Path
import sys

import pytest

from claude_china.desktop import router_guardian


class Engine:
    def __init__(self, events, dynamic=False, fail_verify=False):
        self.events, self.dynamic, self.fail_verify = events, dynamic, fail_verify
        self.policy = {}

    def __enter__(self):
        self.events.append('dynamic-open' if self.dynamic else 'persistent-open')
        return self

    def __exit__(self, *args):
        self.events.append('dynamic-close' if self.dynamic else 'persistent-close')

    def read(self):
        return self.policy

    def replace(self, policy, expected=None):
        assert self.policy == expected
        self.policy = policy
        self.events.append('deny-install' if policy else 'deny-restore')

    def verify(self, policy):
        return self.policy == policy

    def add_router_permits(self, policy):
        self.events.append('permit-install')

    def verify_router_permits(self, policy):
        return not self.fail_verify


def test_guardian_leaves_persistent_deny_after_network_failure():
    events = []
    persistent, dynamic = Engine(events), Engine(events, dynamic=True)
    def factory(dynamic=False):
        return globals_dynamic if dynamic else persistent
    globals_dynamic = dynamic
    notices = []
    def watch(_persistent, _dynamic):
        events.append('watch')
        return 'network failed'
    result = router_guardian.guard_session({'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}},
                                           factory, watch, lambda: events.append('ready'), notices.append)
    assert result == 'blocked'
    assert events.index('deny-install') < events.index('permit-install') < events.index('ready')
    assert events.index('dynamic-close') < events.index('persistent-close')
    assert 'deny-restore' not in events
    assert notices == ['network failed']


def test_guardian_restores_rules_after_normal_session_exit():
    events = []
    persistent, dynamic = Engine(events), Engine(events, dynamic=True)
    result = router_guardian.guard_session({'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}},
                                           lambda active=False: dynamic if active else persistent,
                                           lambda *_: None, lambda: events.append('ready'), Mock())
    assert result == 'restored'
    assert events.index('dynamic-close') < events.index('deny-restore')


def test_guardian_rolls_back_if_it_cannot_verify_permission_before_launch():
    events = []
    persistent, dynamic = Engine(events), Engine(events, dynamic=True, fail_verify=True)
    try:
        router_guardian.guard_session({'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}},
                                      lambda active=False: dynamic if active else persistent,
                                      lambda *_: None, lambda: events.append('ready'), Mock())
    except ValueError:
        pass
    else:
        assert False, 'unverified guardian must not allow a launch'
    assert 'ready' not in events
    assert events.index('dynamic-close') < events.index('deny-restore')


def test_guardian_leaves_deny_if_monitor_itself_crashes():
    events = []
    persistent, dynamic = Engine(events), Engine(events, dynamic=True)
    notices = []
    def crash(_persistent, _dynamic):
        raise RuntimeError('private failure')
    result = router_guardian.guard_session({'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}},
                                           lambda active=False: dynamic if active else persistent,
                                           crash, lambda: events.append('ready'), notices.append)
    assert result == 'blocked'
    assert 'deny-restore' not in events
    assert 'private failure' not in notices[0]


def test_router_guard_status_distinguishes_healthy_from_blocked(monkeypatch):
    from claude_china.desktop.platforms import windows_wfp
    policy = {'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}}
    engine = MagicMock()
    engine.__enter__ = Mock(return_value=engine)
    engine.__exit__ = Mock(return_value=None)
    engine.read.return_value = policy
    engine.verify.return_value = True
    engine.verify_router_permits.return_value = True
    monkeypatch.setattr(windows_wfp, 'Engine', lambda **kwargs: engine)
    monkeypatch.setattr(router_guardian.sys, 'platform', 'win32')
    assert router_guardian.status('claude')['state'] == 'healthy'
    engine.router_permits_present.return_value = False
    engine.verify_router_permits.return_value = False
    assert router_guardian.status('claude')['state'] == 'blocked'


def test_router_guard_status_is_unknown_when_persistent_rules_cannot_be_verified(monkeypatch):
    from claude_china.desktop.platforms import windows_wfp
    engine = MagicMock()
    engine.__enter__ = Mock(return_value=engine)
    engine.__exit__ = Mock(return_value=None)
    engine.read.return_value = {'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}}
    engine.verify.return_value = False
    monkeypatch.setattr(windows_wfp, 'Engine', lambda **kwargs: engine)
    monkeypatch.setattr(router_guardian.sys, 'platform', 'win32')
    assert router_guardian.status('claude')['state'] == 'unknown'


def test_unverifiable_guard_reports_whether_temporary_permits_are_still_present(monkeypatch):
    from claude_china.desktop.platforms import windows_wfp
    engine = MagicMock()
    engine.__enter__ = Mock(return_value=engine)
    engine.__exit__ = Mock(return_value=None)
    engine.read.return_value = {'claude': {'mode': 'router', 'executables': ['C:/old/Claude.exe']}}
    engine.router_permits_present.return_value = False
    engine.verify.side_effect = OSError('file was removed')
    monkeypatch.setattr(windows_wfp, 'Engine', lambda **kwargs: engine)
    monkeypatch.setattr(router_guardian.sys, 'platform', 'win32')
    state = router_guardian.status('claude')
    assert state['state'] == 'unknown' and state['active'] is False


def test_partial_temporary_permits_are_not_reported_as_blocked(monkeypatch):
    from claude_china.desktop.platforms import windows_wfp
    engine = MagicMock()
    engine.__enter__ = Mock(return_value=engine)
    engine.__exit__ = Mock(return_value=None)
    engine.read.return_value = {'claude': {'mode': 'router', 'executables': ['C:/old/Claude.exe']}}
    engine.router_permits_present.return_value = True
    engine.verify.return_value = True
    engine.verify_router_permits.return_value = False
    monkeypatch.setattr(windows_wfp, 'Engine', lambda **kwargs: engine)
    monkeypatch.setattr(router_guardian.sys, 'platform', 'win32')
    state = router_guardian.status('claude')
    assert state['state'] == 'unknown' and state['active'] is True


def test_router_guard_rejects_unregistered_targets():
    import pytest
    with pytest.raises(ValueError):
        router_guardian.scope('anything-else')


def test_guardian_must_not_report_success_when_persistent_deny_is_unverified():
    events = []
    persistent, dynamic = Engine(events), Engine(events, dynamic=True)
    notices = []
    calls = iter([True, False])
    persistent.verify = lambda policy: next(calls)
    outcome = router_guardian.guard_session({'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}},
                                            lambda active=False: dynamic if active else persistent,
                                            lambda *_: 'network failed', lambda: None, notices.append)
    assert outcome == 'unverified'
    assert 'deny-restore' not in events
    assert notices != ['network failed']


def test_cli_targets_use_private_node_and_discovered_browsers(tmp_path, monkeypatch):
    from claude_china.desktop import cli_guard, playwright_guard
    node, browser = tmp_path / 'node.exe', tmp_path / 'chrome.exe'
    node.write_bytes(b'node-runtime')
    browser.write_bytes(b'browser')
    monkeypatch.setattr(cli_guard, 'runtime_dir', lambda: tmp_path / 'guarded')
    monkeypatch.setattr(playwright_guard, 'discover', lambda env, extra: [str(browser)])
    argv, targets = router_guardian.cli_targets([str(node), 'claude.js'], {}, {})
    assert argv[0] != str(node) and Path(argv[0]).read_bytes() == b'node-runtime'
    assert set(targets) == {argv[0], str(browser)}
    assert str(node) not in targets


def test_router_playwright_gate_rejects_unregistered_or_blocked_browser(tmp_path, monkeypatch):
    import pytest
    from claude_china.desktop import egress, playwright_guard
    browser = tmp_path / 'chrome.exe'
    browser.write_bytes(b'browser')
    policy = {'mode': 'router', 'executables': [str(browser)]}
    state = {'enabled': True, 'state': 'healthy', 'policy': policy}
    monkeypatch.setattr(router_guardian, 'status', lambda target: state)
    env = playwright_guard.prepare_router_environment({'HTTP_PROXY': 'fixture'})
    assert env[playwright_guard.HELPER]
    monkeypatch.setenv('CLAUDEC_ROUTER_GUARD', '1')
    assert playwright_guard.check_browser(str(browser))['mode'] == 'router'
    new_browser = tmp_path / 'new.exe'
    new_browser.write_bytes(b'new')
    with pytest.raises(egress.GuardError):
        playwright_guard.check_browser(str(new_browser))
    state['state'] = 'blocked'
    with pytest.raises(egress.GuardError):
        playwright_guard.check_browser(str(browser))


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows elevation protocol')
def test_guardian_start_waits_for_verified_ready_before_returning(tmp_path, monkeypatch):
    import json
    from claude_china.desktop.platforms import windows_wfp
    target = tmp_path / 'claude.exe'
    target.write_bytes(b'fixture')
    monkeypatch.setattr(router_guardian, '_control_file', lambda name: tmp_path / 'control.json')
    monkeypatch.setattr(router_guardian, 'status', Mock(side_effect=[
        {'enabled': False, 'state': 'none'}, {'enabled': True, 'state': 'healthy'}]))
    monkeypatch.setattr(windows_wfp, 'current_sid', lambda: 'S-1-5-21-123')
    kernel = Mock()
    monkeypatch.setattr(router_guardian, '_kernel', lambda: kernel)
    def open_helper(args):
        request = Path(args[1])
        (request.parent / 'ready.json').write_text('{"ok": true}', encoding='utf-8')
        return 123
    monkeypatch.setattr(windows_wfp, '_open_elevated', open_helper)
    session = router_guardian.start('claude', [str(target)], {'status': 'supported'}, {'block_unknown': True})
    assert json.loads((tmp_path / 'control.json').read_text())['target'] == 'claude'
    assert session['target'] == 'claude'
    kernel.CloseHandle.assert_called_once_with(123)
    router_guardian.stop_session(session)
    assert (Path(session['directory']) / 'stop').is_file()
    for name in ('request.json', 'ready.json', 'stop'):
        (Path(session['directory']) / name).unlink(missing_ok=True)
    Path(session['directory']).rmdir()


def test_missing_target_after_startup_grace_keeps_network_blocked(tmp_path, monkeypatch):
    import psutil
    ticks = iter([0, 46])
    monkeypatch.setattr(router_guardian.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(router_guardian, '_live_paths', lambda paths: False)
    parent = Mock(is_running=Mock(return_value=True), create_time=Mock(return_value=1))
    monkeypatch.setattr(psutil, 'Process', lambda pid: parent)
    stop, lost = Event(), Event()
    monkeypatch.setattr(stop, 'wait', lambda timeout: False)
    router_guardian._lifecycle(stop, lost, tmp_path, ['example.exe'], 123, 1)
    assert stop.is_set() and lost.is_set()


def test_process_restart_gap_does_not_end_monitoring(tmp_path, monkeypatch):
    import psutil
    times = iter([0, 1, 2, 3, 4, 10, 11, 16])
    monkeypatch.setattr(router_guardian.time, 'monotonic', lambda: next(times))
    alive = iter([True, False, True, False, False])
    monkeypatch.setattr(router_guardian, '_live_paths', lambda paths: next(alive))
    parent = Mock(is_running=Mock(return_value=True), create_time=Mock(return_value=1))
    monkeypatch.setattr(psutil, 'Process', lambda pid: parent)
    stop, lost = Event(), Event()
    monkeypatch.setattr(stop, 'wait', lambda timeout: False)
    router_guardian._lifecycle(stop, lost, tmp_path, ['example.exe'], 123, 1)
    assert stop.is_set() and not lost.is_set()
    assert next(alive, None) is None


def test_restore_finishes_if_guard_becomes_blocked_while_stopping(tmp_path, monkeypatch):
    from claude_china.desktop.platforms import windows_wfp
    import psutil
    states = iter([{'enabled': True, 'state': 'healthy'},
                   {'enabled': True, 'state': 'blocked'},
                   {'enabled': False, 'state': 'none'}])
    monkeypatch.setattr(router_guardian, 'status', lambda target: next(states))
    monkeypatch.setattr(router_guardian, '_read_control', lambda target: tmp_path)
    monkeypatch.setattr(router_guardian, '_control_file', lambda target: tmp_path / 'control.json')
    monkeypatch.setattr(windows_wfp, 'current_sid', lambda: 'S-1-5-21-123')
    elevate = Mock()
    monkeypatch.setattr(windows_wfp, '_elevate', elevate)
    monkeypatch.setattr(psutil, 'Process', lambda: Mock(create_time=lambda: 1))
    router_guardian.restore('claude')
    assert (tmp_path / 'stop').exists()
    elevate.assert_called_once()


def test_restore_can_remove_inactive_guard_even_if_executable_is_gone(tmp_path, monkeypatch):
    from claude_china.desktop.platforms import windows_wfp
    import psutil
    states = iter([{'enabled': True, 'state': 'unknown', 'active': False},
                   {'enabled': False, 'state': 'none'}])
    monkeypatch.setattr(router_guardian, 'status', lambda target: next(states))
    monkeypatch.setattr(router_guardian, '_control_file', lambda target: tmp_path / 'control.json')
    monkeypatch.setattr(windows_wfp, 'current_sid', lambda: 'S-1-5-21-123')
    elevate = Mock()
    monkeypatch.setattr(windows_wfp, '_elevate', elevate)
    monkeypatch.setattr(psutil, 'Process', lambda: Mock(create_time=lambda: 1))
    router_guardian.restore('claude')
    elevate.assert_called_once()


def test_default_cli_mode_cannot_bypass_existing_router_guard(monkeypatch):
    import pytest
    from claude_china.desktop import egress, playwright_guard
    monkeypatch.setattr(egress, 'supported', lambda: True)
    monkeypatch.setattr(router_guardian, 'status', lambda target: {'enabled': True, 'state': 'blocked'})
    with pytest.raises(egress.GuardError):
        playwright_guard.prepare_environment({}, data={}, ensure_router_clear=True)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows elevation protocol')
def test_guardian_rejects_elevation_into_another_windows_account(tmp_path, monkeypatch):
    import hashlib
    import json
    import psutil
    from claude_china.desktop.platforms import windows_wfp
    executable = tmp_path / 'Claude.exe'
    executable.write_bytes(b'fixture')
    data = {'schema': 1, 'owner': 'S-1-5-21-123', 'target': 'claude',
            'parent_pid': 123, 'parent_created': 1, 'paths': [str(executable)]}
    raw = json.dumps(data).encode()
    request = tmp_path / 'request.json'
    request.write_bytes(raw)
    monkeypatch.setattr(router_guardian, '_request_directory', lambda path: tmp_path)
    monkeypatch.setattr(router_guardian.ctypes.windll.shell32, 'IsUserAnAdmin', lambda: True)
    monkeypatch.setattr(windows_wfp, 'process_sid', lambda pid: data['owner'])
    monkeypatch.setattr(windows_wfp, 'current_sid', lambda: 'S-1-5-21-999')
    monkeypatch.setattr(psutil, 'Process', lambda pid: Mock(create_time=lambda: 1))
    sample = Mock()
    monkeypatch.setattr(router_guardian.router_runtime, 'sample', sample)
    assert router_guardian.run_request(request, hashlib.sha256(raw).hexdigest()) == 1
    sample.assert_not_called()
