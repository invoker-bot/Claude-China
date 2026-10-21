"""Allowlisted usage metadata adapters. Conversation content is never retained."""

from datetime import datetime, timezone
import math
import ntpath
import posixpath


COUNTERS = ('input_tokens', 'output_tokens', 'cached_tokens', 'cache_write_tokens', 'reasoning_tokens')
ADAPTER_VERSION = 4


def number(value):
    return value if type(value) is int and 0 <= value < 10**15 else 0


def stamp(value):
    try:
        if isinstance(value, str):
            date = datetime.fromisoformat(value.replace('Z', '+00:00'))
            value = (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
            return value if 0 < value < 4102444800 else None
        if type(value) in (float, int) and math.isfinite(value):
            value = value / 10**6 if value > 10**14 else value / 1000 if value > 10**11 else value
            if 0 < value < 4102444800:
                return value
    except (ValueError, OverflowError, OSError):
        pass
    return None


def text(value, limit=4096):
    return value[:limit] if isinstance(value, str) else ''


def counters(data, kind):
    if not isinstance(data, dict):
        return None
    names = {
        'claude': ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'reasoning_output_tokens'),
        'codex': ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'reasoning_output_tokens'),
        'grok': ('inputTokens', 'outputTokens', 'cachedReadTokens', 'cacheCreationTokens', 'reasoningTokens'),
    }[kind]
    if not any(type(data.get(name)) is int for name in names[:2]):
        return None
    if any(data.get(name) is not None and (type(data[name]) is not int or not 0 <= data[name] < 10**15) for name in names):
        return None
    result = {key: number(data.get(name)) for key, name in zip(COUNTERS, names)}
    if kind == 'claude':
        result['input_tokens'] += result['cached_tokens'] + result['cache_write_tokens']
        details = data.get('output_tokens_details')
        if isinstance(details, dict):
            result['reasoning_tokens'] = number(details.get('thinking_tokens'))
    # Cache is a subset of input; reasoning is a subset of output.
    result['cached_tokens'] = min(result['cached_tokens'], result['input_tokens'])
    result['cache_write_tokens'] = min(result['cache_write_tokens'], result['input_tokens'] - result['cached_tokens'])
    result['reasoning_tokens'] = min(result['reasoning_tokens'], result['output_tokens'])
    return result


class Parser:
    def __init__(self, tool, state=None):
        self.tool = tool
        self.state = state or {}
        self.warnings = set(self.state.pop('warnings', []))

    def saved_state(self):
        return dict(self.state, warnings=sorted(self.warnings))

    def event(self, key, timestamp, usage=None, model=None, cache_write_long_tokens=None):
        when = stamp(timestamp)
        if when is None:
            self.warnings.add('invalid_timestamp')
            return []
        project = text(self.state.get('project'))
        if ntpath.splitdrive(project)[0] and ntpath.isabs(project):
            project = ntpath.normcase(ntpath.normpath(project))
        elif project.startswith('/'):
            project = posixpath.normpath(project)
        else:
            project = ''
        return [{'key': text(key), 'tool': self.tool, 'session': text(self.state.get('session')),
                 'project': project, 'model': text(model or self.state.get('model'), 200),
                 'timestamp': when, 'cache_write_long_tokens': cache_write_long_tokens, 'call_name': '',
                 **({k: None for k in COUNTERS} if usage is None else usage)}]

    def feed(self, row, offset):
        if not isinstance(row, dict):
            return []
        return getattr(self, '_' + self.tool)(row, offset)

    def call(self, identifier, name, timestamp, namespace='', model=None):
        identifier, name, namespace = text(identifier, 200), text(name, 200), text(namespace, 200)
        if not identifier or not name:
            self.warnings.add('unsupported_calls')
            return []
        if namespace and not name.startswith(namespace + '.'):
            name = namespace + '.' + name
        events = self.event('call:%s:%s' % (self.state.get('session', ''), identifier), timestamp, model=model)
        for event in events:
            event['call_name'] = name
            if model == '':
                event['model'] = ''
        return events

    def _claude(self, row, offset):
        s = self.state
        s['session'] = text(row.get('sessionId')) or s.get('session', '')
        s['project'] = text(row.get('relocatedCwd') or row.get('cwd')) or s.get('project', '')
        message = row.get('message')
        if row.get('type') == 'assistant' and isinstance(message, dict):
            calls = []
            content = message.get('content')
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get('type') in ('tool_use', 'server_tool_use'):
                        calls.extend(self.call(item.get('id'), item.get('name'), row.get('timestamp'), model=text(message.get('model'))))
            usage = counters(message.get('usage'), 'claude')
            key = text(message.get('id')) or text(row.get('uuid')) or '%s:%s' % (s.get('session'), offset)
            if usage is not None:
                creation = message['usage'].get('cache_creation')
                long_writes = None
                if isinstance(creation, dict):
                    short, long = creation.get('ephemeral_5m_input_tokens'), creation.get('ephemeral_1h_input_tokens')
                    if (type(short) is int and type(long) is int and short >= 0 and long >= 0
                            and short + long == usage['cache_write_tokens']):
                        long_writes = long
                return calls + self.event('request:' + key + ':' + text(row.get('requestId')), row.get('timestamp'),
                                  usage, message.get('model'), long_writes)
            if 'usage' in message:
                self.warnings.add('unsupported_usage')
            return calls + self.event('activity:' + key, row.get('timestamp'))
        if row.get('type') == 'user':
            # Tool-result messages are not human prompts, but still establish activity.
            key = text(row.get('uuid')) or '%s:%s' % (s.get('session'), offset)
            return self.event('activity:' + key, row.get('timestamp'))
        return []

    def _codex(self, row, offset):
        s = self.state
        kind, payload = row.get('type'), row.get('payload')
        if not isinstance(payload, dict):
            return []
        if kind == 'session_meta':
            if s.get('session'):
                return []
            s['session'] = text(payload.get('id') or payload.get('session_id'))
            s['project'] = text(payload.get('cwd'))
            s['child'] = isinstance(payload.get('source'), dict)
            s['started_at'] = stamp(row.get('timestamp'))
            return []
        if kind == 'turn_context':
            s['model'] = text(payload.get('model'), 200)
            return []
        if kind == 'response_item' and payload.get('type') in ('function_call', 'custom_tool_call', 'web_search_call', 'local_shell_call'):
            when = stamp(row.get('timestamp'))
            if s.get('child') and (not s.get('started_at') or when is None or when < s['started_at']):
                self.warnings.add('inherited_calls')
                return []
            name = payload.get('name') or {'web_search_call': 'web_search', 'local_shell_call': 'local_shell'}.get(payload['type'])
            return self.call(payload.get('call_id') or payload.get('id'), name, row.get('timestamp'), payload.get('namespace'))
        if kind == 'token_usage_record':
            owner = payload.get('thread_id') or payload.get('session_id')
            if owner and owner != s.get('session'):
                return []  # Replayed parent history in a subagent/fork.
            usage = counters(payload.get('usage'), 'codex')
            response = text(payload.get('response_id'))
            if usage is None or not response:
                self.warnings.add('unsupported_usage')
                return []
            total = counters(payload.get('thread_token_usage'), 'codex')
            if total is not None:
                if s.get('snapshot') == total and not s.get('child'):
                    # Older writers can emit the snapshot before the response.
                    # Its tokens are already present; do not add them again.
                    self.warnings.add('overlapping_usage')
                    return []
                previous = s.get('baseline', {})
                s['baseline'] = {k: max(previous.get(k, 0), total[k]) for k in COUNTERS}
            else:
                pending = s.setdefault('pending', dict.fromkeys(COUNTERS, 0))
                for k in COUNTERS:
                    pending[k] += usage[k]
            return self.event('response:' + response, row.get('timestamp'), usage)
        if kind != 'event_msg':
            return []
        if payload.get('type') == 'user_message' and not s.get('child'):
            return self.event('activity:%s:%s' % (s.get('session'), row.get('timestamp')), row.get('timestamp'))
        if payload.get('type') != 'token_count':
            return []
        if s.get('child'):
            # Old child snapshots can replay inherited totals. Only explicit,
            # owned response records above can be attributed without guessing.
            if 'baseline' not in s:
                self.warnings.add('legacy_subagent')
            return []
        info = payload.get('info')
        if not isinstance(info, dict):
            return []
        total = counters(info.get('total_token_usage'), 'codex')
        if total is None:
            self.warnings.add('unsupported_usage')
            return []
        s['snapshot'] = total
        previous = s.get('baseline', dict.fromkeys(COUNTERS, 0))
        if total['input_tokens'] + total['output_tokens'] < previous['input_tokens'] + previous['output_tokens']:
            self.warnings.add('counter_reset')
            # Set a new baseline; the reset snapshot itself is ambiguous.
            s['baseline'] = total
            s.pop('pending', None)
            return []
        pending = s.pop('pending', {})
        delta = {k: max(0, total[k] - previous.get(k, 0) - pending.get(k, 0)) for k in COUNTERS}
        delta['cached_tokens'] = min(delta['cached_tokens'], delta['input_tokens'])
        delta['cache_write_tokens'] = min(delta['cache_write_tokens'], delta['input_tokens'] - delta['cached_tokens'])
        delta['reasoning_tokens'] = min(delta['reasoning_tokens'], delta['output_tokens'])
        s['baseline'] = total
        if not delta['input_tokens'] and not delta['output_tokens']:
            return []
        key = 'counter:%s:%s:%s:%s' % (s.get('session'), row.get('timestamp'), total['input_tokens'], total['output_tokens'])
        return self.event(key, row.get('timestamp'), delta)

    def _grok(self, row, offset):
        params = row.get('params')
        update = params.get('update') if isinstance(params, dict) else None
        if not isinstance(update, dict):
            return []
        self.state['session'] = text(params.get('sessionId')) or self.state.get('session', '')
        if update.get('sessionUpdate') in ('tool_call', 'tool_call_update'):
            meta = update.get('_meta')
            tool = meta.get('x.ai/tool') if isinstance(meta, dict) else None
            if isinstance(tool, dict):
                return self.call(update.get('toolCallId'), tool.get('name'), row.get('timestamp'), tool.get('namespace'), model='')
            if update.get('sessionUpdate') == 'tool_call':
                self.warnings.add('unsupported_calls')
            return []  # Status/title updates are not additional invocations.
        if update.get('sessionUpdate') in ('user_message_chunk', 'agent_message_chunk'):
            return self.event('activity:%s:%s' % (self.state.get('session'), row.get('timestamp')), row.get('timestamp'))
        if update.get('sessionUpdate') != 'turn_completed':
            return []
        data = update.get('usage')
        if not isinstance(data, dict):
            self.warnings.add('unsupported_usage')
            return self.event('activity:%s:%s' % (self.state.get('session'), row.get('timestamp')), row.get('timestamp'))
        key = 'turn:%s:%s' % (self.state.get('session'), text(update.get('prompt_id')) or row.get('timestamp'))
        models = data.get('modelUsage')
        if isinstance(models, dict) and models:
            events = []
            for model, values in models.items():
                usage = counters(values, 'grok')
                if usage is not None:
                    events.extend(self.event(key + ':' + text(model), row.get('timestamp'), usage, model))
                else:
                    self.warnings.add('unsupported_usage')
            return events
        usage = counters(data, 'grok')
        if usage is None:
            self.warnings.add('unsupported_usage')
        return self.event(key, row.get('timestamp'), usage)

    def bot(self, data):
        self.warnings.add('bot_activity_only')
        if not isinstance(data, dict) or data.get('schemaVersion') != 1 or not isinstance(data.get('value'), dict):
            self.warnings.add('unsupported_usage')
            return []
        entries = data['value'].get('entries')
        if not isinstance(entries, list):
            self.warnings.add('unsupported_usage')
            return []
        events = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get('kind') not in ('send-message', 'message'):
                continue
            key = text(entry.get('id'))
            if key:
                events.extend(self.event('activity:' + self.state['session'] + ':' + key, entry.get('timestampMs')))
        return events
