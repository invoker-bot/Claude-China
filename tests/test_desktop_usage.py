"""Synthetic usage logs: never read real conversations or start a provider."""
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import threading

import pytest

from claude_china.desktop.usage import UsageIndex, discover_sources
from claude_china.desktop.usage_records import Parser, counters, stamp


NOW = datetime(2026, 10, 21, 20, tzinfo=timezone.utc)
STAMP = '2026-10-21T12:00:00Z'


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    return path


def source(kind, root):
    return {'tool': kind, 'root': str(root)}


def claude_row(key='msg-1', output=10, stamp=STAMP):
    return {'type': 'assistant', 'timestamp': stamp, 'sessionId': 'session-1', 'cwd': '/projects/demo',
            'requestId': 'request-1', 'message': {'id': key, 'model': 'claude-fixture',
            'content': [{'type': 'text', 'text': 'PRIVATE TRANSCRIPT'}],
            'usage': {'input_tokens': 20, 'output_tokens': output, 'cache_read_input_tokens': 100,
                      'cache_creation_input_tokens': 30}}}


def test_claude_stream_updates_and_copied_logs_count_once_without_caching_content(tmp_path):
    root = tmp_path / 'claude'
    write(root / 'projects/a/session.jsonl', [claude_row(output=2), claude_row()])
    write(root / 'projects/copy/session.jsonl', [claude_row()])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('claude', root)])
    report = index.report(30, now=NOW)
    assert report['totals']['input_tokens'] == 150
    assert report['totals']['output_tokens'] == 10
    assert report['totals']['tokens'] == 160
    assert report['totals']['cached_tokens'] == 100
    assert report['totals']['sessions'] == report['totals']['projects'] == 1
    assert 'PRIVATE TRANSCRIPT' not in (tmp_path / 'stats.sqlite').read_bytes().decode('latin1')


def test_codex_direct_records_and_cumulative_snapshots_do_not_double_count(tmp_path):
    root = tmp_path / 'codex'
    usage = {'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 20,
             'reasoning_output_tokens': 12, 'total_tokens': 120}
    write(root / 'sessions/2026/10/21/rollout.jsonl', [
        {'type': 'session_meta', 'timestamp': STAMP, 'payload': {'id': 'codex-session', 'cwd': '/projects/demo'}},
        {'type': 'turn_context', 'payload': {'model': 'codex-fixture'}},
        {'type': 'token_usage_record', 'timestamp': STAMP, 'payload': {
            'thread_id': 'codex-session', 'response_id': 'response-1', 'usage': usage, 'thread_token_usage': usage}},
        {'type': 'event_msg', 'timestamp': STAMP, 'payload': {'type': 'token_count', 'info': {'total_token_usage': usage}}},
        {'type': 'event_msg', 'timestamp': STAMP, 'payload': {'type': 'token_count', 'info': {'total_token_usage': usage}}},
    ])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('codex', root)])
    total = index.report(30, now=NOW)['totals']
    assert (total['tokens'], total['cached_tokens'], total['reasoning_tokens']) == (120, 80, 12)


def test_legacy_codex_uses_advancing_totals_and_reports_counter_resets(tmp_path):
    root = tmp_path / 'codex'
    rows = [{'type': 'session_meta', 'timestamp': STAMP, 'payload': {'id': 'legacy', 'cwd': '/p'}}]
    for count in [100, 100, 180, 5]:
        rows.append({'type': 'event_msg', 'timestamp': STAMP, 'payload': {'type': 'token_count',
                     'info': {'total_token_usage': {'input_tokens': count, 'output_tokens': 0}}}})
    write(root / 'sessions/2026/10/21/log.jsonl', rows)
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('codex', root)])
    report = index.report(30, now=NOW)
    assert report['totals']['tokens'] == 180
    assert report['warnings']


def test_grok_completed_turn_includes_cache_but_not_reasoning_twice(tmp_path):
    root = tmp_path / 'grok'
    session = root / 'sessions/project/session-grok'
    session.mkdir(parents=True)
    (session / 'summary.json').write_text(json.dumps({'info': {'id': 'session-grok', 'cwd': '/grok'}}))
    row = {'timestamp': 1792584000000, 'params': {'sessionId': 'session-grok', 'update': {
        'sessionUpdate': 'turn_completed', 'prompt_id': 'prompt-1', 'usage': {
            'inputTokens': 100, 'outputTokens': 20, 'cachedReadTokens': 70, 'reasoningTokens': 10,
            'modelUsage': {'grok-fixture': {'inputTokens': 100, 'outputTokens': 20, 'cachedReadTokens': 70, 'reasoningTokens': 10}}}}}}
    write(session / 'updates.jsonl', [row, row])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('grok', root)])
    report = index.report(30, now=NOW)
    assert report['totals']['tokens'] == 120
    assert report['models'][0]['model'] == 'grok-fixture'


def test_incremental_scan_handles_partial_append_rewrite_and_delete(tmp_path):
    root = tmp_path / 'claude'
    path = write(root / 'projects/a/log.jsonl', [claude_row()])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    sources = [source('claude', root)]
    index.scan(sources)
    assert index.scan(sources)['read_bytes'] == 0
    partial = json.dumps(claude_row('msg-2')).encode()
    with path.open('ab') as stream:
        stream.write(partial[:20])
    index.scan(sources)
    assert index.report(30, now=NOW)['totals']['tokens'] == 160
    with path.open('ab') as stream:
        stream.write(partial[20:] + b'\n')
    index.scan(sources)
    assert index.report(30, now=NOW)['totals']['tokens'] == 320
    write(path, [claude_row('msg-3', output=3)])
    index.scan(sources)
    assert index.report(30, now=NOW)['totals']['tokens'] == 153
    path.unlink()
    index.scan(sources)
    assert index.report(30, now=NOW)['totals']['tokens'] is None


def test_grok_bot_activity_is_not_presented_as_zero_token_usage(tmp_path):
    root = tmp_path / 'bot'
    name = base64.b32encode(b'sand.client.slice.account.fixture.transcript.replicas.chat-1').decode().lower().rstrip('=')
    path = root / 'sand-client-persistence' / (name + '.blob')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'schemaVersion': 1, 'value': {'entries': [
        {'id': 'entry-1', 'kind': 'message', 'role': 'assistant', 'timestampMs': 1792584000000, 'content': 'PRIVATE'}]}}))
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('grok-bot', root)])
    report = index.report(30, tool='grok-bot', now=NOW)
    assert report['totals']['sessions'] == 1
    assert report['totals']['tokens'] is None
    assert report['totals']['projects'] == 0
    assert report['warnings']


def test_filters_and_missing_timestamp_do_not_invent_usage_dates(tmp_path):
    root = tmp_path / 'claude'
    write(root / 'projects/a/log.jsonl', [claude_row(), claude_row('old', stamp='2026-09-01T12:00:00Z'), claude_row('bad', stamp='invalid')])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('claude', root)])
    assert index.report(7, now=NOW)['totals']['tokens'] == 160
    assert index.report(7, tool='codex', now=NOW)['totals']['tokens'] is None
    assert index.report(7, project='/missing', now=NOW)['totals']['sessions'] == 0
    assert index.report(90, now=NOW)['totals']['tokens'] == 320


def test_discovery_includes_default_and_login_homes_but_deduplicates_profiles(tmp_path):
    profiles = [{'type': 'claude', 'mode': 'api'}, {'type': 'claude', 'mode': 'login', 'credentials_path': str(tmp_path / 'isolated')}] * 2
    roots = discover_sources(home=tmp_path, profiles=profiles, environ={}, platform='win32')
    assert len([s for s in roots if s['tool'] == 'claude']) == 3  # default, XDG fallback, isolated
    assert any(s['root'] == str(tmp_path / 'isolated') for s in roots)
    assert not (tmp_path / 'isolated').exists()


def test_codex_child_only_counts_responses_owned_by_the_child():
    parser = Parser('codex')
    parser.feed({'type': 'session_meta', 'payload': {'id': 'child', 'cwd': '/p', 'source': {'subagent': {}}}}, 0)
    inherited = {'type': 'token_usage_record', 'timestamp': STAMP, 'payload': {
        'thread_id': 'parent', 'response_id': 'parent-response', 'usage': {'input_tokens': 900, 'output_tokens': 20}}}
    assert parser.feed(inherited, 1) == []
    assert parser.feed({'type': 'event_msg', 'timestamp': STAMP, 'payload': {'type': 'token_count',
                       'info': {'total_token_usage': {'input_tokens': 900, 'output_tokens': 20}}}}, 2) == []
    owned = {'type': 'token_usage_record', 'timestamp': STAMP, 'payload': {
        'thread_id': 'child', 'response_id': 'child-response', 'usage': {'input_tokens': 100, 'output_tokens': 5}}}
    assert parser.feed(owned, 3)[0]['input_tokens'] == 100


def test_codex_snapshot_before_response_does_not_count_the_request_twice():
    parser = Parser('codex', {'session': 'session'})
    usage = {'input_tokens': 100, 'output_tokens': 20}
    events = parser.feed({'type': 'event_msg', 'timestamp': STAMP, 'payload': {'type': 'token_count', 'info': {'total_token_usage': usage}}}, 1)
    events += parser.feed({'type': 'token_usage_record', 'timestamp': STAMP, 'payload': {
        'thread_id': 'session', 'response_id': 'r', 'usage': usage, 'thread_token_usage': usage}}, 2)
    assert sum(event['input_tokens'] for event in events) == 100


def test_codex_response_without_thread_total_is_reconciled_with_next_snapshot():
    parser = Parser('codex', {'session': 'session'})
    usage = {'input_tokens': 100, 'output_tokens': 20}
    events = parser.feed({'type': 'token_usage_record', 'timestamp': STAMP, 'payload': {
        'thread_id': 'session', 'response_id': 'r', 'usage': usage}}, 1)
    events += parser.feed({'type': 'event_msg', 'timestamp': STAMP, 'payload': {'type': 'token_count', 'info': {'total_token_usage': usage}}}, 2)
    assert sum(event['input_tokens'] for event in events) == 100


@pytest.mark.parametrize('value', [-1, True, '10', 10**18])
def test_invalid_counters_are_unavailable_instead_of_fabricated_zeroes(value):
    assert counters({'input_tokens': value, 'output_tokens': 2}, 'claude') is None


@pytest.mark.parametrize('value', ['0001-01-01T00:00:00Z', '9999-01-01T00:00:00Z', 'not-a-date', float('nan')])
def test_invalid_dates_are_rejected(value):
    assert stamp(value) is None


def test_grok_in_progress_turn_has_activity_without_inventing_tokens():
    parser = Parser('grok', {'session': 'grok-session', 'project': '/project'})
    events = parser.feed({'timestamp': 1792584000000, 'params': {'sessionId': 'grok-session', 'update': {
        'sessionUpdate': 'user_message_chunk', 'content': {'type': 'text', 'text': 'PRIVATE'}}}}, 0)
    assert len(events) == 1 and events[0]['session'] == 'grok-session'
    assert events[0]['input_tokens'] is None
    assert 'PRIVATE' not in json.dumps(events)


def test_claude_assistant_without_usage_still_establishes_activity():
    row = claude_row()
    del row['message']['usage']
    events = Parser('claude').feed(row, 0)
    assert len(events) == 1 and events[0]['input_tokens'] is None


def test_copied_logs_remain_counted_after_one_copy_is_deleted(tmp_path):
    root = tmp_path / 'claude'
    first = write(root / 'projects/a/log.jsonl', [claude_row()])
    write(root / 'projects/b/log.jsonl', [claude_row()])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('claude', root)])
    first.unlink()
    index.scan([source('claude', root)])
    assert index.report(30, now=NOW)['totals']['tokens'] == 160


def test_unreadable_source_directory_preserves_previous_statistics(tmp_path, monkeypatch):
    root = tmp_path / 'claude'
    write(root / 'projects/a/log.jsonl', [claude_row()])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('claude', root)])
    original = os.scandir
    def unreadable(path):
        if Path(path) == root / 'projects/a':
            raise PermissionError('fixture access denied')
        return original(path)
    monkeypatch.setattr(os, 'scandir', unreadable)
    index.scan([source('claude', root)])
    report = index.report(30, now=NOW)
    assert report['totals']['tokens'] == 160
    assert report['warnings']


def test_usage_reader_keeps_grok_activity_before_a_completed_turn(tmp_path):
    root = tmp_path / 'grok'
    write(root / 'sessions/group/session/updates.jsonl', [{'timestamp': 1792584000000, 'params': {
        'sessionId': 'live-session', 'update': {'sessionUpdate': 'user_message_chunk', 'content': {'text':'PRIVATE'}}}}])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('grok', root)])
    report = index.report(30, now=NOW)
    assert report['totals']['tokens'] is None and report['totals']['sessions'] == 1


def test_trailing_partial_record_does_not_advance_cursor_or_lose_previous_counts(tmp_path):
    root = tmp_path / 'claude'
    path = write(root / 'projects/a/log.jsonl', [claude_row()])
    with path.open('ab') as stream:
        stream.write(b'{"type":"assistant","usage":')
    before = path.read_bytes()
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('claude', root)])
    index.scan([source('claude', root)])
    assert index.report(30, now=NOW)['totals']['tokens'] == 160
    assert path.read_bytes() == before


def test_background_scan_is_single_and_does_not_block_queries(tmp_path):
    from claude_china.desktop.usage import UsageService
    service = UsageService(tmp_path / 'stats.sqlite', sources=lambda: [])
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def scan(sources, progress):
        calls.append(1)
        entered.set()
        release.wait(3)
        finished.set()
        return {'files': 0, 'scanned_files': 0}
    service.index.scan = scan
    try:
        assert service.start()['phase'] == 'scanning'
        assert entered.wait(2)
        assert service.start()['phase'] == 'scanning'
        assert service.report()['scan']['phase'] == 'scanning'
        assert len(calls) == 1
    finally:
        release.set()
        assert finished.wait(2)


def test_bridge_usage_errors_do_not_expose_paths_or_credentials(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from claude_china.desktop.bridge import LauncherBridge
    from claude_china.desktop import config as cfg
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    bridge = LauncherBridge(Mock(), apps=[])
    bridge._usage_service = Mock()
    bridge._usage_service.report.side_effect = OSError('private token and path')
    result = bridge.get_usage_report()
    assert not result['ok'] and 'private' not in str(result)


def test_windows_project_spelling_is_deduplicated_without_touching_the_directory(tmp_path):
    root = tmp_path / 'claude'
    a, b = claude_row(), claude_row('second')
    a['cwd'] = 'D:/Projects/Demo/.'
    b['cwd'] = 'd:\\projects\\demo'
    write(root / 'projects/a/log.jsonl', [a,b])
    index = UsageIndex(tmp_path / 'stats.sqlite')
    index.scan([source('claude', root)])
    assert index.report(30, now=NOW)['totals']['projects'] == 1


@pytest.mark.parametrize('platform,suffix', [('darwin','Library/Application Support/Grok Bot'), ('linux','.config/Grok Bot'), ('win32','AppData/Roaming/Grok Bot')])
def test_platform_source_locations_do_not_create_provider_directories(tmp_path, platform, suffix):
    sources = discover_sources(home=tmp_path, profiles=[], environ={}, platform=platform)
    assert next(s['root'] for s in sources if s['tool']=='grok-bot') == str((tmp_path / suffix).resolve())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('days,tool,project', [(True,'all',''),(0,'all',''),(30,'invalid',''),(30,'all',[])])
def test_invalid_filters_are_rejected(tmp_path, days, tool, project):
    with pytest.raises(ValueError):
        UsageIndex(tmp_path / 'stats.sqlite').report(days,tool,project)
