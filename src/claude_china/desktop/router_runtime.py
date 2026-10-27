"""Shared runtime decisions for router-mode network monitoring."""

import json
import sys

from . import process, router

INTERVAL_SECONDS = 10.0
PROBE_TIMEOUT_SECONDS = 12.0
NETWORK_FAILED = "运行期间无法确认 Claude 网络安全。"
EXIT_CHANGED = "运行期间 Claude 网络出口发生变化。"


def sample(app_id, target):
    """Run the network probe in a time-limited child, including DNS resolution."""
    command = [sys.executable]
    if not getattr(sys, 'frozen', False):
        command += ['-m', 'claude_china.desktop.entry']
    command += ['--router-runtime-probe', app_id, '--router-runtime-target', target]
    try:
        result = process.run(command, capture_output=True, timeout=PROBE_TIMEOUT_SECONDS,
                             creationflags=process.CREATE_NO_WINDOW)
        if result.returncode or len(result.stdout) > 65536:
            raise ValueError('invalid probe output')
        report = json.loads(result.stdout.decode('utf-8'))
        if not isinstance(report, dict) or report.get('status') not in ('supported', 'unsupported', 'unknown'):
            raise ValueError('invalid probe report')
        return report
    except Exception:
        return {'status': 'unknown'}


def _addresses(report):
    measurements = report.get('router') if isinstance(report, dict) else None
    if not isinstance(measurements, dict):
        return {}
    result = {}
    for item in measurements.get('services', []):
        if isinstance(item, dict) and item.get('status') == 'ok' and item.get('ip'):
            result[('service', item.get('host'), item.get('family'))] = item['ip']
    for family in (4, 6):
        item = measurements.get('udp' + str(family))
        if isinstance(item, dict) and item.get('status') == 'match' and item.get('ip'):
            result[('udp', family)] = item['ip']
    return result


def failure(initial, current, settings):
    """Return a safe reason when the current measurement no longer qualifies."""
    if not isinstance(current, dict):
        current = {'status': 'unknown'}
    if not router.allowed(current, settings):
        return NETWORK_FAILED
    baseline = _addresses(initial)
    now = _addresses(current)
    if (any(value != now[key] for key, value in baseline.items() if key in now)
            or (initial.get('status') == current.get('status') == 'supported'
                and baseline and baseline.keys() != now.keys())):
        return EXIT_CHANGED
    return None


def watch(initial, settings, probe, disconnect, stop, interval=INTERVAL_SECONDS):
    """Monitor until stopped or a failed check invokes the caller's disconnect."""
    while not stop.wait(interval):
        try:
            current = probe()
        except Exception:
            current = {'status': 'unknown'}
        reason = failure(initial, current, settings)
        if reason and not stop.is_set():
            disconnect(reason)
            return reason
