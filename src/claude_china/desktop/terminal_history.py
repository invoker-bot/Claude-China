"""Read local CLI session metadata without executing a CLI or loading credentials."""

from datetime import datetime, timezone
from heapq import nlargest
import json
from pathlib import Path
import re
from urllib.parse import unquote

MAX_SESSIONS = 200
MAX_FILES = 5000
HEADER_BYTES = 512 * 1024
TAIL_BYTES = 64 * 1024
_UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
_HOMES = {'claude': '.claude', 'codex': '.codex', 'grok': '.grok'}


def profile_home(record):
    if record.get('mode', 'api') == 'login':
        value = record.get('credentials_path')
        if not isinstance(value, str) or not value.strip():
            raise ValueError('登录配置缺少历史记录目录，请先编辑配置。')
        root = Path(value).expanduser()
        if not root.is_absolute():
            raise ValueError('登录配置目录必须使用绝对路径。')
        return root.resolve()
    return Path.home() / _HOMES[record['type']]


def _title(value):
    return ' '.join(value.split())[:160] if isinstance(value, str) else ''


def _json(path):
    with path.open('rb') as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError('Metadata too large')
    return json.loads(data)


def _modified(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return -1


def _lines(path, head=HEADER_BYTES, tail=TAIL_BYTES):
    # Logs can be hundreds of MB and can still be written by an active CLI.
    # Read bounded windows; an incomplete or oversized JSON line is ignored.
    with path.open('rb') as stream:
        prefix = stream.read(head)
        stream.seek(0, 2)
        size = stream.tell()
        chunks = [prefix]
        if size > head and tail:
            offset = max(head, size - tail)
            stream.seek(max(0, offset - 1))
            boundary = stream.read(1) if offset else b'\n'
            suffix = stream.read(tail)
            chunks.append(suffix if boundary == b'\n' else suffix.partition(b'\n')[2])
    for chunk in chunks:
        for line in chunk.splitlines():
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(row, dict):
                yield row


def _entry(session_id, directory, title, modified):
    if not isinstance(session_id, str) or not _UUID.fullmatch(session_id):
        return None
    if (not isinstance(directory, str) or not directory
            or any(ord(c) < 32 for c in directory) or not Path(directory).is_absolute()):
        return None
    path = Path(directory).resolve()
    return {'id': session_id, 'directory': str(path),
            'title': _title(title) or path.name or str(path),
            'updated_at': datetime.fromtimestamp(modified, timezone.utc).isoformat(),
            'available': path.is_dir()}


def _claude(path, modified, indexes):
    session_id = path.stem
    if not _UUID.fullmatch(session_id):
        return None
    if path.parent not in indexes:
        try:
            data = _json(path.parent / 'sessions-index.json')
            entries = data.get('entries', []) if isinstance(data, dict) else []
            indexes[path.parent] = {e.get('sessionId'): e for e in entries if isinstance(e, dict)}
        except (OSError, ValueError, TypeError):
            indexes[path.parent] = {}
    index = indexes[path.parent].get(session_id, {})
    if index.get('isSidechain'):
        return None
    directory = index.get('projectPath')
    title = index.get('customTitle') or index.get('summary') or index.get('firstPrompt')
    renamed, first_prompt = '', ''
    for row in _lines(path):
        if row.get('isSidechain'):
            return None
        if row.get('sessionId') not in (None, session_id):
            continue
        if row.get('cwd'):
            directory = row['cwd']
        if row.get('type') == 'relocated' and row.get('relocatedCwd'):
            directory = row['relocatedCwd']
        if row.get('type') == 'custom-title':
            renamed = _title(row.get('customTitle')) or renamed
        if row.get('type') == 'user' and not first_prompt:
            message = row.get('message')
            content = message.get('content') if isinstance(message, dict) else None
            if isinstance(content, str):
                first_prompt = _title(content)
    return _entry(session_id, directory, renamed or title or first_prompt, modified)


def _codex(path, modified, titles):
    # The first record is the CLI's session_meta; never read conversation bodies.
    with path.open('rb') as stream:
        row = json.loads(stream.readline(HEADER_BYTES))
    if not isinstance(row, dict) or row.get('type') != 'session_meta':
        return None
    meta = row.get('payload')
    if not isinstance(meta, dict) or isinstance(meta.get('source'), dict):
        return None  # Structured sources are background/subagent tasks.
    session_id = meta.get('id') or meta.get('session_id')
    return _entry(session_id, meta.get('cwd'), titles.get(session_id), modified)


def _grok(path, modified):
    data = _json(path)
    if not isinstance(data, dict) or data.get('is_subagent') or not (path.parent / 'updates.jsonl').is_file():
        return None
    group = path.parent.parent
    marker = group / '.cwd'
    if marker.is_file():
        with marker.open(encoding='utf-8') as stream:
            directory = stream.read(32768).strip()
    else:
        directory = unquote(group.name)
    info = data.get('info')
    if isinstance(info, dict):
        if info.get('id') not in (None, path.parent.name):
            return None
        directory = info.get('cwd') or directory
    title = data.get('title') or data.get('generated_title') or data.get('session_summary') or data.get('summary')
    timestamp = data.get('last_active_at') or data.get('updated_at')
    if isinstance(timestamp, str):
        try:
            date = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            modified = (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
        except (ValueError, OverflowError):
            pass
    return _entry(path.parent.name, directory, title, modified)


def list_sessions(kind, root):
    root = Path(root).resolve()
    patterns = {'claude': 'projects/*/*.jsonl', 'codex': 'sessions/*/*/*/*.jsonl',
                'grok': 'sessions/*/*/summary.json'}
    if kind not in patterns:
        raise ValueError('此 CLI 暂不支持历史会话。')
    entries, warnings, indexes, titles = [], [], {}, {}
    if kind == 'codex':
        try:
            for row in _lines(root / 'session_index.jsonl', head=0, tail=4 * 1024 * 1024):
                if isinstance(row.get('id'), str) and _title(row.get('thread_name')):
                    titles[row['id']] = _title(row['thread_name'])
        except OSError:
            pass
    try:
        files = nlargest(MAX_FILES + 1, root.glob(patterns[kind]), key=_modified)
    except OSError:
        files = []
        warnings.append('无法读取历史目录，请检查文件访问权限。')
    for path in files[:MAX_FILES]:
        try:
            if root not in path.resolve().parents or not path.is_file():
                continue
            modified = path.stat().st_mtime
            if kind == 'claude':
                entry = _claude(path, modified, indexes)
            elif kind == 'codex':
                entry = _codex(path, modified, titles)
            else:
                entry = _grok(path, modified)
            if entry:
                entries.append(entry)
                if kind != 'grok' and len({item['id'] for item in entries}) > MAX_SESSIONS:
                    break
        except (OSError, ValueError, TypeError, OverflowError):
            if not warnings:
                warnings.append('部分历史记录无法读取，已跳过；其余会话仍可使用。')
    entries.sort(key=lambda item: item['updated_at'], reverse=True)
    # Copied/migrated logs can contain the same session twice.
    unique = {entry['id']: entry for entry in reversed(entries)}
    entries = sorted(unique.values(), key=lambda item: item['updated_at'], reverse=True)
    return {'sessions': entries[:MAX_SESSIONS], 'warnings': warnings,
            'truncated': len(entries) > MAX_SESSIONS or len(files) > MAX_FILES}


def _check_defaults(kind, defaults, resuming):
    # A saved default must not silently switch the selected session or project,
    # fork it, restore files, or connect to a remote server instead.
    blocked = {'--resume', '-r', '--continue', '--cwd', '--cd', '-C', '--last', '--remote', '--'}
    blocked.add('-c' if kind != 'codex' else '--include-non-interactive')
    if resuming:
        blocked.update({'--fork-session', '--session-id', '--restore-code', '--worktree', '-w'})
        if kind == 'grok':
            blocked.add('-s')
    short = tuple(flag for flag in blocked if len(flag) == 2 and flag != '--')
    if (any(arg.split('=', 1)[0] in blocked for arg in defaults)
            or any(arg.startswith(short) for arg in defaults)
            or (kind == 'codex' and defaults and defaults[0] in ('resume', 'fork', 'exec', 'app'))):
        raise ValueError('默认参数中含有会话或目录切换选项，请先编辑配置再启动。')


def new_session_args(kind, defaults):
    _check_defaults(kind, defaults, resuming=False)
    return defaults


def resume_args(kind, session_id, defaults):
    if not isinstance(session_id, str) or not _UUID.fullmatch(session_id):
        raise ValueError('会话 ID 无效，请刷新历史记录。')
    _check_defaults(kind, defaults, resuming=True)
    prefix = ['resume'] if kind == 'codex' else ['--resume']
    return prefix + [session_id] + defaults
