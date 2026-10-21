import json
from datetime import datetime, timezone

from claude_china.desktop.usage import UsageIndex
from claude_china.desktop.usage_records import Parser


STAMP = '2026-10-21T12:00:00Z'
NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def test_claude_tool_calls_deduplicate_stream_fragments_and_exclude_arguments(tmp_path):
    root = tmp_path / 'claude'
    path = root / 'projects/p/log.jsonl'
    path.parent.mkdir(parents=True)
    row = {'type': 'assistant', 'timestamp': STAMP, 'sessionId': 's', 'cwd': '/p', 'message': {
        'id': 'm', 'model': 'claude-opus-5-5', 'usage': {'input_tokens': 100, 'output_tokens': 10},
        'content': [{'type': 'tool_use', 'id': 'c1', 'name': 'Bash', 'input': {'command': 'PRIVATE'}},
                    {'type': 'tool_use', 'id': 'c2', 'name': 'mcp__server__read', 'input': 'SECRET'}]}}
    path.write_text((json.dumps(row)+'\n')*2)
    copy = path.with_name('copy.jsonl')
    copy.write_bytes(path.read_bytes())
    index = UsageIndex(tmp_path / 'index.sqlite')
    sources = [{'tool': 'claude', 'root': str(root)}]
    index.scan(sources)
    report = index.report(now=NOW)
    assert report['totals']['tool_calls'] == 2
    assert report['totals']['tokens'] == 110
    assert {v['name']: v['calls'] for v in report['tool_calls']} == {'Bash': 1, 'mcp__server__read': 1}
    assert sum(v['calls'] for v in report['tool_calls'] if v['is_mcp']) == 1
    assert index.report(model='different', now=NOW)['totals']['tool_calls'] == 0
    assert index.report(model='claude-opus-5-5', now=NOW)['totals']['tool_calls'] == 2
    with index.connect() as db:
        saved = repr([tuple(r) for r in db.execute('SELECT * FROM records')])
    assert 'PRIVATE' not in saved and 'SECRET' not in saved
    assert index.scan(sources)['read_bytes'] == 0
    path.unlink()
    copy.unlink()
    index.scan(sources)
    assert index.report(now=NOW)['totals']['tool_calls'] == 0


def test_codex_calls_keep_namespaces_and_do_not_count_outputs():
    parser = Parser('codex', {'session': 's', 'model': 'gpt-6.1-sol'})
    row = {'type': 'response_item', 'timestamp': STAMP, 'payload': {
        'type': 'function_call', 'call_id': 'call1', 'name': 'js', 'namespace': 'mcp__cua_repl', 'arguments': 'PRIVATE'}}
    event = parser.feed(row, 0)[0]
    assert event['call_name'] == 'mcp__cua_repl.js'
    assert event['model'] == 'gpt-6.1-sol'
    row['payload']['type'] = 'function_call_output'
    assert parser.feed(row, 1) == []
    assert 'PRIVATE' not in json.dumps(event)


def test_codex_child_does_not_attribute_inherited_calls_to_new_session():
    parser = Parser('codex')
    parser.feed({'type': 'session_meta', 'timestamp': STAMP, 'payload': {'id': 'child', 'source': {'subagent': {}}}}, 0)
    row = {'type': 'response_item', 'timestamp': '2026-10-20T12:00:00Z', 'payload': {
        'type': 'custom_tool_call', 'call_id': 'parent-call', 'name': 'apply_patch', 'input': 'PRIVATE'}}
    assert parser.feed(row, 1) == []
    row['timestamp'] = '2026-10-21T12:01:00Z'
    row['payload']['call_id'] = 'child-call'
    assert parser.feed(row, 2)[0]['call_name'] == 'apply_patch'


def test_grok_call_updates_use_metadata_not_titles_and_deduplicate(tmp_path):
    root = tmp_path / 'grok'
    path = root / 'sessions/project/session/updates.jsonl'
    path.parent.mkdir(parents=True)
    (path.parent / 'summary.json').write_text(json.dumps({'info': {'cwd': '/p'}, 'current_model_id': 'grok-4.7-build'}))
    rows = []
    for kind in ['tool_call', 'tool_call_update']:
        rows.append({'timestamp': 1792584000000, 'params': {'sessionId': 's', 'update': {
            'sessionUpdate': kind, 'toolCallId': 'c1', 'title': 'PRIVATE command', 'rawInput': 'SECRET',
            '_meta': {'x.ai/tool': {'name': 'read_file', 'namespace': 'fs'}}}}})
    rows.append({'timestamp': 1792584001000, 'params': {'sessionId': 's', 'update': {
        'sessionUpdate': 'tool_call_update', 'toolCallId': 'c1', 'status': 'completed', 'rawOutput': 'PRIVATE'}}})
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    index = UsageIndex(tmp_path / 'index.sqlite')
    index.scan([{'tool': 'grok', 'root': str(root)}])
    report = index.report(now=NOW)
    assert report['totals']['tool_calls'] == 1
    assert report['tool_calls'][0]['name'] == 'fs.read_file'
    # A mutable session summary cannot establish the model of an older call.
    assert report['models'][0]['model'] == ''
    assert index.report(model='grok-4.7-build', now=NOW)['totals']['tool_calls'] == 0
