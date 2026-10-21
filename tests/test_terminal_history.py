import json
import os
from pathlib import Path
from urllib.parse import quote

import pytest

from claude_china.desktop import terminal_history as history


SESSION = '019a1111-2222-7333-8444-555555555555'
OTHER = '019a1111-2222-7333-8444-666666666666'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def write_lines(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(v) + '\n' for v in values), encoding='utf-8')


def test_claude_reads_native_history_and_title_without_returning_transcripts(tmp_path):
    project = tmp_path / 'project with spaces'
    project.mkdir()
    transcript = tmp_path / 'home/projects/encoded' / (SESSION + '.jsonl')
    write_lines(transcript, [
        {'type': 'user', 'sessionId': SESSION, 'cwd': str(project), 'message': {'content': 'first task'}},
        {'type': 'assistant', 'message': {'content': 'PRIVATE response and credentials'}},
        {'type': 'custom-title', 'sessionId': SESSION, 'customTitle': 'Renamed project task'},
    ])
    write_json(transcript.parent / 'sessions-index.json', {'entries': [
        {'sessionId': SESSION, 'projectPath': str(project), 'summary': 'Older title'},
        {'sessionId': OTHER, 'projectPath': str(project), 'summary': 'Deleted session'},
    ]})
    write_lines(transcript.parent / ('agent-' + OTHER + '.jsonl'), [
        {'type': 'user', 'sessionId': OTHER, 'cwd': str(project), 'isSidechain': True}])
    result = history.list_sessions('claude', tmp_path / 'home')
    assert len(result['sessions']) == 1
    session = result['sessions'][0]
    assert session['id'] == SESSION and session['title'] == 'Renamed project task'
    assert session['directory'] == str(project) and session['available']
    assert 'PRIVATE' not in json.dumps(result)
    assert 'message' not in session and 'fullPath' not in session


def test_codex_uses_index_titles_excludes_subagents_and_tolerates_incomplete_tail(tmp_path):
    home = tmp_path / 'home'
    path = home / 'sessions/2026/10/21' / ('rollout-time-' + SESSION + '.jsonl')
    write_lines(path, [{'type': 'session_meta', 'payload': {'id': SESSION, 'cwd': str(tmp_path), 'source': 'cli'}}])
    with path.open('a') as stream:
        stream.write('{"type":')
    write_lines(path.with_name('rollout-child-' + OTHER + '.jsonl'), [
        {'type': 'session_meta', 'payload': {'id': OTHER, 'cwd': str(tmp_path), 'source': {'subagent': {'other': 'worker'}}}}])
    write_lines(home / 'session_index.jsonl', [
        {'id': SESSION, 'thread_name': 'Old title'}, {'id': SESSION, 'thread_name': 'Current title'}])
    result = history.list_sessions('codex', home)
    assert [(s['id'], s['title']) for s in result['sessions']] == [(SESSION, 'Current title')]


def test_codex_reads_the_first_and_only_title_index_record(tmp_path):
    write_lines(tmp_path / 'sessions/2026/10/21/rollout.jsonl', [
        {'type': 'session_meta', 'payload': {'id': SESSION, 'cwd': str(tmp_path), 'source': 'cli'}}])
    write_lines(tmp_path / 'session_index.jsonl', [{'id': SESSION, 'thread_name': 'Only saved title'}])
    assert history.list_sessions('codex', tmp_path)['sessions'][0]['title'] == 'Only saved title'


@pytest.mark.parametrize('hashed', [False, True])
def test_grok_reads_local_summary_and_requires_resumable_update_log(tmp_path, hashed):
    home = tmp_path / 'home'
    group = home / 'sessions' / ('project-hash' if hashed else quote(str(tmp_path), safe=''))
    path = group / SESSION / 'summary.json'
    write_json(path, {'title': 'Grok task', 'summary': 'PRIVATE full summary'})
    (path.parent / 'updates.jsonl').write_text('{}\n')
    if hashed:
        (group / '.cwd').write_text(str(tmp_path), encoding='utf-8')
    write_json(group / OTHER / 'summary.json', {'title': 'Incomplete session'})
    result = history.list_sessions('grok', home)
    assert len(result['sessions']) == 1
    assert result['sessions'][0]['directory'] == str(tmp_path)
    assert result['sessions'][0]['title'] == 'Grok task'
    assert 'PRIVATE' not in json.dumps(result)


def test_grok_reads_current_native_generated_title_and_info(tmp_path):
    path = tmp_path / 'sessions' / quote(str(tmp_path), safe='') / SESSION / 'summary.json'
    write_json(path, {'info': {'id': SESSION, 'cwd': str(tmp_path)},
                     'generated_title': 'Native Grok title', 'session_summary': 'Long conversation summary',
                     'updated_at': '2026-10-21T08:00:00Z'})
    (path.parent / 'updates.jsonl').write_text('{}\n')
    session = history.list_sessions('grok', tmp_path)['sessions'][0]
    assert session['title'] == 'Native Grok title'
    assert session['updated_at'].startswith('2026-10-21T08:00:00')


def test_missing_directory_is_visible_and_invalid_or_missing_records_do_not_crash(tmp_path):
    home = tmp_path / 'home'
    path = home / 'projects/test' / (SESSION + '.jsonl')
    write_lines(path, [{'type': 'user', 'cwd': str(tmp_path / 'gone'), 'sessionId': SESSION}])
    (path.parent / 'broken.jsonl').write_text('{broken')
    result = history.list_sessions('claude', home)
    assert len(result['sessions']) == 1 and not result['sessions'][0]['available']
    assert history.list_sessions('claude', tmp_path / 'not-installed')['sessions'] == []


def test_history_normalizes_directory_spelling_to_match_project_favorites(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (tmp_path / 'other').mkdir()
    alias = str(tmp_path / 'other' / '..' / 'project')
    write_lines(tmp_path / 'projects/test' / (SESSION + '.jsonl'), [
        {'type': 'user', 'cwd': alias, 'sessionId': SESSION}])
    assert history.list_sessions('claude', tmp_path)['sessions'][0]['directory'] == str(project.resolve())


def test_history_sorts_by_activity_and_bounds_results(tmp_path, monkeypatch):
    for i, session_id in enumerate((SESSION, OTHER)):
        path = tmp_path / 'projects/test' / (session_id + '.jsonl')
        write_lines(path, [{'type': 'user', 'cwd': str(tmp_path), 'sessionId': session_id}])
        os.utime(path, (100 + i, 100 + i))
    monkeypatch.setattr(history, 'MAX_SESSIONS', 1)
    result = history.list_sessions('claude', tmp_path)
    assert [s['id'] for s in result['sessions']] == [OTHER]
    assert result['truncated']


def test_scan_budget_keeps_newest_files_instead_of_directory_enumeration_order(tmp_path, monkeypatch):
    for i, session_id in enumerate((SESSION, OTHER)):
        path = tmp_path / 'projects/test' / (session_id + '.jsonl')
        write_lines(path, [{'type': 'user', 'cwd': str(tmp_path), 'sessionId': session_id}])
        os.utime(path, (100 + i, 100 + i))
    monkeypatch.setattr(history, 'MAX_FILES', 1)
    result = history.list_sessions('claude', tmp_path)
    assert [s['id'] for s in result['sessions']] == [OTHER]
    assert result['truncated']


def test_profile_history_home_matches_launch_environment_and_does_not_create_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'inherited-other-account'))
    assert history.profile_home({'type': 'codex', 'mode': 'api'}) == tmp_path / '.codex'
    account = tmp_path / 'isolated-account'
    assert history.profile_home({'type': 'codex', 'mode': 'login', 'credentials_path': str(account)}) == account
    assert not account.exists()


@pytest.mark.parametrize('session_id', ['--help', '../other', 'bad; command', '', None])
def test_resume_identifiers_are_validated(session_id):
    with pytest.raises(ValueError):
        history.resume_args('claude', session_id, [])


@pytest.mark.parametrize('kind,prefix', [('claude', ['--resume']), ('codex', ['resume']), ('grok', ['--resume'])])
def test_resume_uses_exact_id_and_preserves_model_arguments(kind, prefix):
    assert history.resume_args(kind, SESSION, ['--model', 'a model']) == prefix + [SESSION, '--model', 'a model']


@pytest.mark.parametrize('kind,args', [
    ('claude', ['--continue']), ('claude', ['--resume=other']), ('grok', ['--fork-session']),
    ('grok', ['--restore-code']), ('codex', ['--cd', '/another']), ('codex', ['resume', '--last']),
    ('codex', ['-C/another']), ('claude', ['-r' + OTHER]), ('grok', ['-wnew-branch']),
])
def test_resume_rejects_profile_arguments_that_override_selected_session_or_directory(kind, args):
    with pytest.raises(ValueError, match='默认参数'):
        history.resume_args(kind, SESSION, args)
