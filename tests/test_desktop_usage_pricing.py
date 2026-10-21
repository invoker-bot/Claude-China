"""API-equivalent estimates use public rates, never subscription charges."""
from datetime import datetime, timezone
import json

import pytest

from claude_china.desktop.usage import UsageIndex
from claude_china.desktop.usage_records import Parser
from claude_china.desktop.usage_pricing import estimate, lookup_price


def record(model='claude-opus-5-5', **changes):
    row = dict(model=model, key='request:one', tool='claude', input_tokens=1000,
               output_tokens=100, cached_tokens=700, cache_write_tokens=100,
               cache_write_long_tokens=20, reasoning_tokens=80, session_input_max=1000)
    row.update(changes)
    return row


def test_cache_reads_and_writes_are_subtracted_from_ordinary_input():
    result = estimate(record())
    # $4/MTok ordinary input, $.20 hits, $5 short writes, $8 long writes, $20 output.
    assert result['usd'] == pytest.approx((200*4 + 700*.2 + 80*5 + 20*8 + 100*20)/1e6)
    assert result['assumed'] is False


def test_missing_cache_ttl_is_an_explicit_short_ttl_assumption():
    result = estimate(record(cache_write_long_tokens=None))
    assert result['assumed'] is True
    assert result['usd'] == pytest.approx(.00344)


@pytest.mark.parametrize('name', ['gpt-6.1-sol-custom', 'grok-4.7-build', 'Atria-Dawn-Preview', '', '<synthetic>'])
def test_unknown_aliases_never_inherit_a_similarly_named_price(name):
    assert lookup_price(name) is None
    assert estimate(record(name))['usd'] is None


def test_dated_snapshot_matches_only_an_exact_known_model_base():
    assert lookup_price('claude-opus-5-5-20261001')['model'] == 'claude-opus-5-5'
    assert lookup_price('gpt-6.1-sol-2026-10-01')['model'] == 'gpt-6.1-sol'
    assert lookup_price('gpt-6.1-sol-fast') is None


@pytest.mark.parametrize('inputs,multiplier', [(272000, 1), (272001, 2)])
def test_openai_request_context_threshold_uses_request_input_including_cache(inputs, multiplier):
    result = estimate(record('gpt-6.1-sol', key='response:r', input_tokens=inputs,
                             cached_tokens=200000, cache_write_tokens=0, output_tokens=100))
    expected = ((inputs-200000)*2 + 200000*.1)*multiplier + 100*10*(1 if multiplier == 1 else 1.5)
    assert result['usd'] == pytest.approx(expected/1e6)


def test_gpt55_session_long_context_applies_to_earlier_short_requests():
    result = estimate(record('gpt-5.5', key='response:r', cache_write_tokens=0,
                             cached_tokens=0, session_input_max=300000))
    assert result['usd'] == pytest.approx((1000*10 + 100*45)/1e6)


def test_aggregate_usage_does_not_masquerade_as_one_long_request():
    result = estimate(record('grok-4.7', key='turn:session:prompt', input_tokens=400000,
                             cached_tokens=0, cache_write_tokens=0, output_tokens=100))
    assert result['assumed'] is True
    assert result['usd'] == pytest.approx((400000*2 + 100*6)/1e6)


def test_no_usage_is_unavailable_and_recorded_zero_cost_is_zero():
    assert estimate(record(input_tokens=None))['usd'] is None
    assert estimate(record(input_tokens=0, output_tokens=0, cached_tokens=0,
                           cache_write_tokens=0, cache_write_long_tokens=0))['usd'] == 0


def test_claude_adapter_preserves_cache_duration_without_retaining_body():
    row = {'type': 'assistant', 'timestamp': '2026-10-21T12:00:00Z', 'sessionId': 's',
           'message': {'id': 'm', 'model': 'claude-opus-5-5', 'content': 'PRIVATE', 'usage': {
               'input_tokens': 10, 'output_tokens': 2, 'cache_creation_input_tokens': 100,
               'cache_creation': {'ephemeral_5m_input_tokens': 80, 'ephemeral_1h_input_tokens': 20}}}}
    result = Parser('claude').feed(row, 0)[0]
    assert result['cache_write_long_tokens'] == 20
    assert 'PRIVATE' not in json.dumps(result)


def test_report_separates_tool_models_and_keeps_unpriced_usage_in_totals(tmp_path):
    root = tmp_path / 'logs'
    path = root / 'projects/p/log.jsonl'
    path.parent.mkdir(parents=True)
    rows = []
    for number, model in enumerate(['claude-opus-5-5', 'private-model']):
        rows.append({'type': 'assistant', 'timestamp': '2026-10-21T12:00:00Z', 'sessionId': 's', 'cwd': '/p',
                     'message': {'id': str(number), 'model': model, 'usage': {'input_tokens': 100, 'output_tokens': 10}}})
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    index = UsageIndex(tmp_path / 'index.sqlite')
    index.scan([{'tool': 'claude', 'root': str(root)}])
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    report = index.report(now=now)
    assert report['totals']['tokens'] == 220
    assert report['totals']['cost_usd'] == pytest.approx(.0006)
    assert report['totals']['priced_tokens'] == report['totals']['unpriced_tokens'] == 110
    assert report['totals']['cost_status'] == 'partial'
    assert {row['tool'] for row in report['models']} == {'claude'}
    selected = index.report(model='private-model', now=now)
    assert selected['totals']['cost_usd'] is None
    assert selected['totals']['tokens'] == 110
    assert selected['models'][0]['price'] is None
    assert index.report(model='claude-opus-5-5', now=now)['models'][0]['price']['input'] == 4
    assert sum(row['cost_usd'] or 0 for row in report['daily']) == pytest.approx(.0006)
    assert index.scan([{'tool': 'claude', 'root': str(root)}])['read_bytes'] == 0


def test_changed_prices_are_not_labelled_as_new_until_daily_cache_is_rebuilt(tmp_path, monkeypatch):
    from claude_china.desktop import usage_pricing
    root = tmp_path / 'logs'
    path = root / 'projects/p/log.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'type': 'assistant', 'timestamp': '2026-10-21T12:00:00Z', 'sessionId': 's',
                               'message': {'id': 'm', 'model': 'claude-opus-5-5', 'usage': {'input_tokens': 100, 'output_tokens': 10}}})+'\n')
    index = UsageIndex(tmp_path / 'index.sqlite')
    sources = [{'tool': 'claude', 'root': str(root)}]
    index.scan(sources)
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    monkeypatch.setattr(usage_pricing, 'PRICE_VERSION', 'new-catalog-fixture')
    pending = index.report(now=now)
    assert pending['pricing']['ready'] is False
    assert pending['totals']['cost_usd'] is None
    assert index.scan(sources)['read_bytes'] == 0
    assert index.report(now=now)['pricing']['ready'] is True
    assert index.report(now=now)['totals']['cost_usd'] == pytest.approx(.0006)


def test_price_source_opens_only_a_catalog_url(monkeypatch):
    from unittest.mock import Mock
    from claude_china.desktop.bridge import LauncherBridge
    import webbrowser
    opened = Mock(return_value=True)
    monkeypatch.setattr(webbrowser, 'open', opened)
    bridge = LauncherBridge(Mock(), apps=[])
    assert bridge.open_usage_price_source('https://untrusted.example')['ok'] is False
    assert bridge.open_usage_price_source([])['ok'] is False
    opened.assert_not_called()
    assert bridge.open_usage_price_source('claude-opus-5-5')['ok'] is True
    opened.assert_called_once_with(lookup_price('claude-opus-5-5')['source'])
