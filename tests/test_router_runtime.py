from threading import Event
from subprocess import CompletedProcess, TimeoutExpired

import pytest

from claude_china.desktop import router_runtime


def report(status='supported', ip='8.8.8.8', reason='fixture'):
    return {'status': status, 'reason': reason, 'network': {'ip': ip, 'country_code': 'US'},
            'router': {'browser_webrtc': 'unknown'}}


def test_running_check_accepts_an_allowed_country():
    assert router_runtime.failure(report(), report(), {'block_unknown': True}) is None


def test_running_check_accepts_ip_changes_when_country_still_passes():
    assert router_runtime.failure(report(), report(ip='1.1.1.1'), {'block_unknown': True}) is None


@pytest.mark.parametrize('status', ['unknown', 'unsupported'])
def test_running_check_rejects_failed_network_or_unverified_status(status):
    assert router_runtime.failure(report(), report(status=status), {'block_unknown': True})


def test_running_check_respects_explicit_unknown_setting():
    assert router_runtime.failure(report(), report(status='unknown'), {'block_unknown': False}) is None


def test_watch_disconnects_once_on_failure_and_never_reports_network_details():
    samples = iter([report(), report(status='unsupported', reason='unsafe secret')])
    signals = []
    router_runtime.watch(report(), {'block_unknown': True}, lambda: next(samples),
                         signals.append, stop=Event(), interval=0)
    assert len(signals) == 1
    assert 'unsafe secret' not in signals[0]


def test_watch_stops_when_session_exits_without_disconnect():
    stop = Event()
    stop.set()
    signals = []
    router_runtime.watch(report(), {'block_unknown': True}, lambda: pytest.fail('unneeded'),
                         signals.append, stop=stop, interval=0)
    assert signals == []


def test_watch_treats_probe_exception_as_unknown():
    def broken():
        raise OSError('sensitive network detail')
    signals = []
    router_runtime.watch(report(), {'block_unknown': True}, broken,
                         signals.append, stop=Event(), interval=0)
    assert len(signals) == 1
    assert 'sensitive network detail' not in signals[0]


def test_runtime_probe_is_bounded_and_rejects_invalid_child_output(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, stdout=b'{"status":"supported"}')
    monkeypatch.setattr(router_runtime.process, 'run', run)
    assert router_runtime.sample('claude', 'playwright')['status'] == 'supported'
    assert calls[0][1]['timeout'] == router_runtime.PROBE_TIMEOUT_SECONDS
    assert '--router-runtime-probe' in calls[0][0]
    monkeypatch.setattr(router_runtime.process, 'run', lambda *a, **kw: CompletedProcess(a, 0, stdout=b'invalid'))
    assert router_runtime.sample('claude', 'playwright')['status'] == 'unknown'


def test_runtime_probe_times_out_to_unknown_without_exposing_errors(monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutExpired('private', 1)
    monkeypatch.setattr(router_runtime.process, 'run', timeout)
    result = router_runtime.sample('claude', 'claude')
    assert result['status'] == 'unknown'
    assert 'private' not in str(result)


def test_probe_entry_checks_existing_guard_before_and_after_network_probe(monkeypatch, capsys):
    import json
    from claude_china.desktop import config, entry, platforms, router
    monkeypatch.setattr(platforms, 'get_backend', lambda: object())
    monkeypatch.setattr(config, 'load_desktop_config', lambda: {})
    calls = []
    monkeypatch.setattr(router, 'check_ready', lambda target, data, backend, **kwargs: calls.append(target))
    monkeypatch.setattr(router, 'inspect', lambda app, backend: report())
    assert entry.main(['--router-runtime-probe', 'claude', '--router-runtime-target', 'playwright']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'supported'
    assert calls == ['playwright', 'playwright']


def test_probe_entry_safely_rejects_invalid_targets(capsys):
    import json
    from claude_china.desktop import entry
    assert entry.main(['--router-runtime-probe', 'not-an-app']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'unknown'


def test_watch_returns_reason_after_disconnect():
    signals = []
    reason = router_runtime.watch(report(), {'block_unknown': True}, lambda: report(status='unsupported'),
                                  signals.append, stop=Event(), interval=0)
    assert reason == signals[0]
