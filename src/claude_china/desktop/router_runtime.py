"""Shared runtime decisions for router-mode network monitoring."""

import json
import sys

from . import process, router

INTERVAL_SECONDS = 10.0
PROBE_TIMEOUT_SECONDS = 12.0
NETWORK_FAILED = "运行期间出口地区检查未通过。"


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


def failure(initial, current, settings):
    """Return a safe reason when the current measurement no longer qualifies."""
    if not isinstance(current, dict):
        current = {'status': 'unknown'}
    if not router.allowed(current, settings):
        return NETWORK_FAILED
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
