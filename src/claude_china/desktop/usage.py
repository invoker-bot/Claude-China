"""Local usage index, incremental readers and a non-blocking desktop service."""

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

from .usage_records import ADAPTER_VERSION, COUNTERS, Parser, text


TOOLS = ('claude', 'codex', 'grok', 'grok-bot')
MAX_LINE = 4 * 1024 * 1024
MARKERS = {
    'claude': (b'"assistant"', b'"user"', b'relocated'),
    'codex': (b'token_usage_record', b'token_count', b'session_meta', b'turn_context', b'user_message'),
    'grok': (b'turn_completed', b'user_message_chunk', b'agent_message_chunk'),
}
WARNINGS = {
    'invalid_timestamp': '部分记录缺少有效时间，未计入统计。',
    'unsupported_usage': '部分用量格式无法识别，统计可能不完整。',
    'legacy_subagent': '旧格式子任务无法区分继承用量，已跳过这部分统计。',
    'counter_reset': '检测到累计计数重置，重置点的用量无法确认。',
    'overlapping_usage': '部分逐次记录与累计快照重叠，采用累计值，统计可能不完整。',
    'bad_record': '部分日志损坏或记录过大，已跳过。',
    'read_error': '部分日志无法读取，已保留上次统计。',
    'bot_activity_only': 'Grok Bot 仅统计本地缓存的会话活动，未提供 token 和项目明细。',
}


def discover_sources(home=None, profiles=None, environ=None, platform=None):
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    roots = {(tool, str((home / ('.' + tool)).resolve())) for tool in TOOLS[:3]}
    roots.add(('claude', str((Path(environ.get('XDG_CONFIG_HOME', home / '.config')) / 'claude').resolve())))
    for tool, variable in [('claude', 'CLAUDE_CONFIG_DIR'), ('codex', 'CODEX_HOME'), ('grok', 'GROK_HOME')]:
        if environ.get(variable):
            roots.add((tool, str(Path(environ[variable]).expanduser().resolve())))
    if profiles is None:
        from .. import config
        try:
            profiles = list(config.load_config().get('profiles', {}).values()) if Path(config.CONFIG_FILE).is_file() else []
        except (OSError, ValueError, TypeError):
            profiles = []
    for profile in profiles:
        if not isinstance(profile, dict) or profile.get('type') not in TOOLS[:3] or profile.get('mode') != 'login':
            continue
        location = profile.get('credentials_path')
        if isinstance(location, str) and Path(location).expanduser().is_absolute():
            roots.add((profile['type'], str(Path(location).expanduser().resolve())))
    if platform == 'win32':
        bot = Path(environ.get('APPDATA', home / 'AppData/Roaming')) / 'Grok Bot'
    elif platform == 'darwin':
        bot = home / 'Library/Application Support/Grok Bot'
    else:
        bot = Path(environ.get('XDG_CONFIG_HOME', home / '.config')) / 'Grok Bot'
    roots.add(('grok-bot', str(bot.resolve())))
    return [{'tool': kind, 'root': path} for kind, path in sorted(roots)]


def _bot_session(path):
    try:
        name = base64.b32decode(path.stem.upper() + '=' * (-len(path.stem) % 8)).decode('utf-8')
        marker = '.transcript.replicas.'
        return name.split(marker, 1)[1] if name.startswith('sand.client.') and marker in name else ''
    except (ValueError, UnicodeError):
        return ''


def _candidates(source):
    root = Path(source['root']).resolve()
    tool = source['tool']
    groups = {'claude': ('projects',), 'codex': ('sessions', 'archived_sessions'),
              'grok': ('sessions',), 'grok-bot': ('sand-client-persistence',)}

    def fail(error):
        raise error

    for name in groups[tool]:
        base = root / name
        try:
            base.stat()
        except FileNotFoundError:
            continue
        if root not in base.resolve().parents:
            continue
        # glob suppresses some filesystem errors. walk's onerror distinguishes
        # unreadable subdirectories from deletion so cached counts survive.
        for directory, children, names in os.walk(base, onerror=fail, followlinks=False):
            folder = Path(directory)
            children[:] = [child for child in children if root in (folder / child).resolve().parents]
            if tool == 'grok-bot' or (tool == 'grok' and len(folder.relative_to(base).parts) >= 2):
                children[:] = []
            for name in names:
                if tool == 'grok' and (name != 'updates.jsonl' or len(folder.relative_to(base).parts) != 2):
                    continue
                if tool in ('claude', 'codex') and not name.endswith('.jsonl'):
                    continue
                path = folder / name
                if tool == 'grok-bot' and (path.suffix != '.blob' or not _bot_session(path)):
                    continue
                if root in path.resolve().parents and path.is_file():
                    yield path.resolve()


def _fingerprint(stream, offset):
    stream.seek(0)
    head = stream.read(min(offset, 512))
    stream.seek(max(0, offset - 128))
    tail = stream.read(min(offset, 128))
    return hashlib.sha256(head + tail).hexdigest()


class UsageIndex:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, tool TEXT, size INTEGER, mtime INTEGER,
                    identity TEXT, offset INTEGER, fingerprint TEXT, state TEXT);
                CREATE TABLE IF NOT EXISTS records (
                    path TEXT, key TEXT, tool TEXT, session TEXT, project TEXT, model TEXT,
                    timestamp REAL, input_tokens INTEGER, output_tokens INTEGER,
                    cached_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER,
                    PRIMARY KEY(path, key));
                CREATE INDEX IF NOT EXISTS usage_time ON records(timestamp);
                CREATE INDEX IF NOT EXISTS usage_key ON records(tool, key);
                CREATE TABLE IF NOT EXISTS daily (
                    date TEXT, tool TEXT, session TEXT, project TEXT, model TEXT,
                    input_tokens INTEGER, output_tokens INTEGER, cached_tokens INTEGER,
                    cache_write_tokens INTEGER, reasoning_tokens INTEGER);
                CREATE INDEX IF NOT EXISTS daily_date ON daily(date, tool);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
            ''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def scan(self, sources, progress=None):
        candidates, warnings = {}, set()
        for source in sources:
            if source.get('tool') not in TOOLS:
                continue
            try:
                for path in _candidates(source):
                    candidates[str(path)] = source['tool']
            except OSError:
                warnings.add('read_error')
        result = {'files': len(candidates), 'scanned_files': 0, 'read_bytes': 0}
        with self.connect() as db:
            # Do not discard cached data when a directory cannot be enumerated.
            if 'read_error' not in warnings:
                for row in db.execute('SELECT path FROM files').fetchall():
                    if row['path'] not in candidates:
                        db.execute('DELETE FROM records WHERE path=?', (row['path'],))
                        db.execute('DELETE FROM files WHERE path=?', (row['path'],))
                db.commit()
            for filename, tool in candidates.items():
                try:
                    with db:
                        result['read_bytes'] += self._scan_file(db, Path(filename), tool)
                except (OSError, ValueError, TypeError, OverflowError):
                    warnings.add('read_error')
                result['scanned_files'] += 1
                if progress:
                    progress(dict(result))
            for row in db.execute('SELECT state FROM files'):
                warnings.update(json.loads(row['state']).get('warnings', []))
            # Build compact day/session/model groups once per scan, rather than
            # sorting hundreds of thousands of requests on every UI filter.
            if db.total_changes or not db.execute('SELECT 1 FROM metadata WHERE key=?', ('daily-v1',)).fetchone():
                db.execute('DELETE FROM daily')
                db.execute('''INSERT INTO daily
                    SELECT date(timestamp,'unixepoch','localtime'), tool, session, project, model,
                    SUM(input_tokens), SUM(output_tokens), SUM(cached_tokens),
                    SUM(cache_write_tokens), SUM(reasoning_tokens)
                    FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY tool,key ORDER BY
                        COALESCE(input_tokens,0)+COALESCE(output_tokens,0) DESC, timestamp DESC, path) AS rank
                        FROM records)
                    WHERE rank=1 GROUP BY date(timestamp,'unixepoch','localtime'), tool, session, project, model''')
                db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('daily-v1', '1'))
            result.update(updated_at=time.time(), warnings=sorted(warnings))
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', ('scan', json.dumps(result)))
        return result

    def _scan_file(self, db, path, tool):
        stat = path.stat()
        identity = '%s:%s' % (stat.st_dev, stat.st_ino)
        old = db.execute('SELECT * FROM files WHERE path=?', (str(path),)).fetchone()
        if old and json.loads(old['state']).get('adapter_version') != ADAPTER_VERSION:
            old = None
        if old and old['size'] == stat.st_size and old['mtime'] == stat.st_mtime_ns and old['identity'] == identity:
            return 0
        with path.open('rb') as stream:
            append = (tool != 'grok-bot' and old and old['identity'] == identity
                      and stat.st_size > old['size'] and old['offset'] <= stat.st_size
                      and _fingerprint(stream, old['offset']) == old['fingerprint'])
            offset = old['offset'] if append else 0
            state = json.loads(old['state']) if append else {}
            state['adapter_version'] = ADAPTER_VERSION
            if not append:
                db.execute('DELETE FROM records WHERE path=?', (str(path),))
            state.setdefault('session', path.parent.name if tool == 'grok' else _bot_session(path) if tool == 'grok-bot' else '')
            parser = Parser(tool, state)
            if tool == 'grok':
                try:
                    with (path.parent / 'summary.json').open('rb') as summary:
                        data = json.loads(summary.read(MAX_LINE))
                    info = data.get('info', {})
                    if isinstance(info, dict):
                        state['project'] = text(info.get('cwd'))
                    state['model'] = text(data.get('current_model_id'), 200)
                except (OSError, ValueError, TypeError, AttributeError):
                    parser.warnings.add('unsupported_usage')
            stream.seek(offset)
            read_bytes = 0
            if tool == 'grok-bot':
                raw = stream.read(MAX_LINE + 1)
                read_bytes += len(raw)
                if len(raw) > MAX_LINE:
                    parser.warnings.add('bad_record')
                else:
                    for event in parser.bot(json.loads(raw)):
                        self._store(db, path, event)
                offset = stream.tell()
            else:
                while stream.tell() < stat.st_size:
                    start = stream.tell()
                    raw = stream.readline(min(MAX_LINE + 1, stat.st_size - start))
                    read_bytes += len(raw)
                    if len(raw) > MAX_LINE:
                        while raw and not raw.endswith(b'\n') and stream.tell() < stat.st_size:
                            raw = stream.readline(min(MAX_LINE + 1, stat.st_size - stream.tell()))
                            read_bytes += len(raw)
                        parser.warnings.add('bad_record')
                        if not raw.endswith(b'\n'):
                            break
                        offset = stream.tell()
                        continue
                    if not raw.endswith(b'\n'):
                        break  # Retain cursor before an actively written record.
                    offset = stream.tell()
                    # Skip large conversation/tool bodies without JSON decoding.
                    if not any(marker in raw for marker in MARKERS[tool]):
                        continue
                    try:
                        row = json.loads(raw)
                    except (ValueError, UnicodeError):
                        parser.warnings.add('bad_record')
                        continue
                    for event in parser.feed(row, start):
                        self._store(db, path, event)
            db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?)',
                       (str(path), tool, stat.st_size, stat.st_mtime_ns, identity, offset,
                        _fingerprint(stream, offset), json.dumps(parser.saved_state())))
        return read_bytes

    @staticmethod
    def _store(db, path, event):
        values = [str(path)] + [event[k] for k in ('key', 'tool', 'session', 'project', 'model', 'timestamp') + COUNTERS]
        # Streaming fragments can update the same request. Preserve its largest
        # complete counters, never add fragments or copied requests together.
        updates = ','.join('%s=MAX(COALESCE(records.%s,0),excluded.%s)' % (k, k, k) for k in COUNTERS)
        db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path,key) DO UPDATE SET '
                   + updates + ',model=excluded.model,project=excluded.project', values)

    def report(self, days=30, tool='all', project='', now=None):
        if type(days) is not int or days not in (1, 7, 30, 90) or tool not in ('all',) + TOOLS or not isinstance(project, str):
            raise ValueError('无效的统计筛选条件。')
        now = datetime.now().astimezone() if now is None else now
        first = now.date() - timedelta(days=days - 1)
        daily = {str(first + timedelta(days=i)): _bucket() for i in range(days)}
        totals, models, projects, tools = _bucket(), {}, {}, {}
        project_options = set()
        with self.connect() as db:
            meta = db.execute('SELECT value FROM metadata WHERE key=?', ('scan',)).fetchone()
            scan = json.loads(meta['value']) if meta else {}
            rows = db.execute('SELECT * FROM daily WHERE date>=? AND date<=?', (str(first), str(now.date())))
            for row in rows:
                if tool != 'all' and row['tool'] != tool:
                    continue
                day = row['date']
                if day not in daily:
                    continue
                if row['project']:
                    project_options.add(row['project'])
                if project and row['project'] != project:
                    continue
                _add(totals, row, day)
                _add(daily[day], row, day)
                _add(tools.setdefault(row['tool'], _bucket()), row, day)
                if row['project']:
                    _add(projects.setdefault(row['project'], _bucket()), row, day)
                if row['input_tokens'] is not None:
                    _add(models.setdefault(row['model'], _bucket()), row, day)
            file_counts = {row['tool']: row['n'] for row in db.execute('SELECT tool,COUNT(*) AS n FROM files GROUP BY tool')}
        order = lambda item: item.get('tokens') or 0
        return {'totals': _finish(totals), 'daily': [dict(date=day, **_finish(value)) for day, value in daily.items()],
                'models': sorted([dict(model=key, **_finish(value)) for key, value in models.items()], key=order, reverse=True),
                'projects': sorted([dict(project=key, **_finish(value)) for key, value in projects.items()], key=lambda v: (v['tokens'] or 0, v['sessions']), reverse=True),
                'tools': [dict(tool=key, files=file_counts.get(key, 0), **_finish(tools.get(key, _bucket()))) for key in TOOLS],
                'project_options': sorted(project_options), 'updated_at': scan.get('updated_at'),
                'warnings': [WARNINGS[k] for k in scan.get('warnings', []) if k in WARNINGS]}


def _bucket():
    return dict.fromkeys(COUNTERS, 0) | {'has_usage': False, 'session_ids': set(), 'project_ids': set(), 'days': set()}


def _add(bucket, row, day):
    if row['session']:
        bucket['session_ids'].add((row['tool'], row['session']))
    if row['project']:
        bucket['project_ids'].add(row['project'])
    bucket['days'].add(day)
    if row['input_tokens'] is not None:
        bucket['has_usage'] = True
        for key in COUNTERS:
            bucket[key] += row[key] or 0


def _finish(bucket):
    return {**{k: bucket[k] if bucket['has_usage'] else None for k in COUNTERS},
            'tokens': bucket['input_tokens'] + bucket['output_tokens'] if bucket['has_usage'] else None,
            'sessions': len(bucket['session_ids']), 'projects': len(bucket['project_ids']), 'active_days': len(bucket['days'])}


class UsageService:
    def __init__(self, path=None, sources=None):
        from .config import DESKTOP_CONFIG_FILE
        self.index = UsageIndex(path or Path(DESKTOP_CONFIG_FILE).parent / 'usage-v1.sqlite')
        self.sources = sources or discover_sources
        self.lock = threading.Lock()
        self.status = {'phase': 'idle'}

    def start(self):
        with self.lock:
            if self.status['phase'] == 'scanning':
                return dict(self.status)
            self.status = {'phase': 'scanning', 'scanned_files': 0, 'files': 0}
            threading.Thread(target=self._scan, name='usage-index', daemon=True).start()
            return dict(self.status)

    def _scan(self):
        try:
            result = self.index.scan(self.sources(), self._progress)
            with self.lock:
                self.status = dict(result, phase='ready')
        except Exception:
            with self.lock:
                self.status = {'phase': 'error', 'error': '统计扫描失败，请重试。'}

    def _progress(self, progress):
        with self.lock:
            self.status = dict(progress, phase='scanning')

    def report(self, days=30, tool='all', project=''):
        data = self.index.report(days, tool, project)
        with self.lock:
            data['scan'] = dict(self.status)
        return data
