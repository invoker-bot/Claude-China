from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from claude_china.desktop import notifications, router_guardian, router_runtime


def notification_fixture():
    item = notifications.WindowsNotification.__new__(notifications.WindowsNotification)
    item.title = 'Claude China · 网络防护'
    item.message = '网络异常'
    item.window = None
    item.icon = None
    item.owns_icon = False
    item.added = False
    actions = []
    item.shell32 = SimpleNamespace(Shell_NotifyIconW=lambda action, data: actions.append((action, data._obj)) or True)
    item.user32 = SimpleNamespace(
        CreateWindowExW=lambda *args: 123,
        LoadImageW=lambda *args: 456,
        LoadIconW=lambda *args: 789,
        DestroyWindow=lambda window: actions.append(('destroy-window', window)),
        DestroyIcon=lambda icon: actions.append(('destroy-icon', icon)),
    )
    return item, actions


def test_shell_notification_is_non_modal_and_cleans_up_its_icon():
    item, actions = notification_fixture()
    item.show()
    assert [action for action, _ in actions[:2]] == [0, 1]
    assert actions[1][1].info == '网络异常'
    assert actions[1][1].info_flags == 0x02
    item.close()
    assert [action for action, _ in actions[2:4]] == [1, 2]
    assert ('destroy-window', 123) in actions and ('destroy-icon', 456) in actions
    assert not item.added and item.window is None


def test_show_failure_never_falls_back_to_a_modal_dialog(monkeypatch):
    monkeypatch.setattr(notifications.sys, 'platform', 'win32')
    broken = Mock()
    broken.show.side_effect = OSError('private failure')
    broken.close = Mock()
    monkeypatch.setattr(notifications, 'WindowsNotification', lambda *args: broken)
    notifications.show_network_warning('network failed')
    broken.close.assert_called_once()
    assert notifications._active is None


def test_non_windows_platform_does_not_create_a_notification(monkeypatch):
    monkeypatch.setattr(notifications.sys, 'platform', 'linux')
    factory = Mock(side_effect=AssertionError('Windows API used'))
    monkeypatch.setattr(notifications, 'WindowsNotification', factory)
    notifications.show_network_warning('network failed')
    factory.assert_not_called()


def test_blocked_monitor_dismisses_on_recovery_and_can_alert_again(monkeypatch):
    stop = Event()
    waits = iter([False, False, True])
    monkeypatch.setattr(stop, 'wait', lambda timeout: next(waits))
    samples = iter([{'status': 'supported'}, {'status': 'unsupported'}])
    monkeypatch.setattr(router_runtime, 'sample', lambda *args: next(samples))
    dismiss = Mock()
    monkeypatch.setattr(notifications, 'dismiss_network_warning', dismiss)
    alert = Mock()
    monkeypatch.setattr(router_guardian, '_alert', alert)
    router_guardian._monitor_blocked(stop, {'block_unknown': True}, 'claude')
    assert dismiss.call_count == 2
    alert.assert_called_once_with(router_runtime.NETWORK_FAILED)


def test_stopping_a_blocked_session_dismisses_without_recovery_probe(monkeypatch):
    stop = Event()
    stop.set()
    sample = Mock(side_effect=AssertionError('unexpected probe'))
    monkeypatch.setattr(router_runtime, 'sample', sample)
    dismiss = Mock()
    monkeypatch.setattr(notifications, 'dismiss_network_warning', dismiss)
    router_guardian._monitor_blocked(stop, {'block_unknown': True}, 'claude')
    dismiss.assert_called_once()
    sample.assert_not_called()


def test_blocked_restore_signals_recovery_monitor_to_stop(tmp_path, monkeypatch):
    states = iter([{'enabled': True, 'state': 'blocked'}, {'enabled': False, 'state': 'none'}])
    monkeypatch.setattr(router_guardian, 'status', lambda target: next(states))
    monkeypatch.setattr(router_guardian, '_read_control', lambda target: tmp_path)
    monkeypatch.setattr(router_guardian, '_control_file', lambda target: tmp_path / 'control.json')
    from claude_china.desktop.platforms import windows_wfp
    import psutil
    monkeypatch.setattr(windows_wfp, 'current_sid', lambda: 'S-1-5-21-123')
    elevate = Mock()
    monkeypatch.setattr(windows_wfp, '_elevate', elevate)
    monkeypatch.setattr(psutil, 'Process', lambda: Mock(create_time=lambda: 1))
    router_guardian.restore('claude')
    assert (tmp_path / 'stop').is_file()
    elevate.assert_called_once()


def test_unverified_rules_and_network_must_both_recover_before_dismissal(monkeypatch):
    stop = Event()
    waits = iter([False, False, True])
    monkeypatch.setattr(stop, 'wait', lambda timeout: next(waits))
    monkeypatch.setattr(router_runtime, 'sample', lambda *args: {'status': 'supported'})
    verified = iter([False, True])
    dismiss = Mock()
    monkeypatch.setattr(notifications, 'dismiss_network_warning', dismiss)
    alert = Mock()
    monkeypatch.setattr(router_guardian, '_alert', alert)
    router_guardian._monitor_blocked(stop, {'block_unknown': True}, 'claude', lambda: next(verified))
    assert dismiss.call_count == 2
    alert.assert_not_called()


def test_rule_verification_failure_dismisses_only_when_session_stops(monkeypatch):
    stop = Event()
    waits = iter([False, True])
    monkeypatch.setattr(stop, 'wait', lambda timeout: next(waits))
    monkeypatch.setattr(router_runtime, 'sample', lambda *args: {'status': 'supported'})
    dismiss = Mock()
    monkeypatch.setattr(notifications, 'dismiss_network_warning', dismiss)
    verify = Mock(side_effect=OSError('private WFP failure'))
    router_guardian._monitor_blocked(stop, {'block_unknown': True}, 'claude', verify)
    verify.assert_called_once()
    dismiss.assert_called_once()


def test_recovery_restores_rules_dismisses_notice_and_stops_monitor(monkeypatch):
    stop = Event()
    monkeypatch.setattr(stop, 'wait', lambda timeout: False)
    monkeypatch.setattr(router_runtime, 'sample', lambda *args: {'status': 'supported'})
    restore = Mock()
    dismiss = Mock()
    monkeypatch.setattr(notifications, 'dismiss_network_warning', dismiss)
    router_guardian._monitor_blocked(stop, {'block_unknown': True}, 'claude', lambda: True, restore)
    restore.assert_called_once_with()
    assert stop.is_set()
    dismiss.assert_called()


def test_failed_automatic_restore_keeps_blocking_and_retries(monkeypatch):
    stop = Event()
    waits = iter([False, True])
    monkeypatch.setattr(stop, 'wait', lambda timeout: next(waits))
    monkeypatch.setattr(router_runtime, 'sample', lambda *args: {'status': 'supported'})
    restore = Mock(side_effect=OSError('private WFP failure'))
    dismiss = Mock()
    monkeypatch.setattr(notifications, 'dismiss_network_warning', dismiss)
    router_guardian._monitor_blocked(stop, {'block_unknown': True}, 'claude', lambda: True, restore)
    restore.assert_called_once_with()
    assert not stop.is_set()
    dismiss.assert_called_once_with()


def test_restore_verified_removes_only_the_unchanged_owned_policy(tmp_path, monkeypatch):
    policies = {'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}}
    calls = []

    class Engine:
        def __init__(self, owner, scope):
            calls.append(('open', owner, scope))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def verify(self, value):
            return value == policies
        def replace(self, value, expected):
            calls.append(('replace', value, expected))
        def read(self):
            return {}

    from claude_china.desktop.platforms import windows_wfp
    monkeypatch.setattr(windows_wfp, 'Engine', Engine)
    monkeypatch.setattr(router_guardian, '_control_file', lambda target: tmp_path / 'control.json')
    router_guardian._control_file('claude').write_text('{}', encoding='utf-8')
    router_guardian._restore_verified('S-1-5-21-123', 'claude', policies)
    assert ('replace', {}, policies) in calls
    assert not router_guardian._control_file('claude').exists()


def test_restore_verified_rejects_changed_rules(tmp_path, monkeypatch):
    policies = {'claude': {'mode': 'router', 'executables': ['C:/fixture/Claude.exe']}}
    replace = Mock()
    engine = Mock()
    engine.__enter__ = Mock(return_value=engine)
    engine.__exit__ = Mock(return_value=None)
    engine.verify.return_value = False
    engine.replace = replace
    from claude_china.desktop.platforms import windows_wfp
    monkeypatch.setattr(windows_wfp, 'Engine', lambda owner, scope: engine)
    monkeypatch.setattr(router_guardian, '_control_file', lambda target: tmp_path / 'control.json')
    with pytest.raises(router_guardian.GuardError, match='变化'):
        router_guardian._restore_verified('S-1-5-21-123', 'claude', policies)
    replace.assert_not_called()


def test_restored_router_session_no_longer_blocks_playwright(monkeypatch):
    from claude_china.desktop import playwright_guard
    monkeypatch.setenv('CLAUDEC_ROUTER_GUARD', '1')
    monkeypatch.setattr(router_guardian, 'status', lambda target: {'enabled': False, 'state': 'none'})
    assert playwright_guard.check_browser('not-installed-after-restore.exe') is None
