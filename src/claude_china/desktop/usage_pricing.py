"""Offline, versioned USD token-price snapshot. These are not account charges."""
from functools import lru_cache
import re


CHECKED_ON = '2026-10-22'
PRICE_VERSION = CHECKED_ON + '-1'
OPENAI = 'https://developers.openai.com/api/docs/pricing'
CLAUDE = 'https://platform.claude.com/docs/en/about-claude/pricing'
GROK = 'https://docs.x.ai/developers/pricing'


def _price(input_rate, output, cached, write=None, long_write=None, source=CLAUDE,
           long_from=None, input_multiplier=2, output_multiplier=1.5, session_tier=False):
    return dict(input=input_rate, output=output, cached=cached, write=write, long_write=long_write,
                source=source, checked_on=CHECKED_ON, long_from=long_from,
                input_multiplier=input_multiplier, output_multiplier=output_multiplier,
                session_tier=session_tier)


# USD per million tokens, Standard/global tier. Each model is an explicit entry;
# internal build names and arbitrary provider aliases never match by prefix.
PRICES = {
    'claude-fable-5-1': _price(10, 50, .25, 12.5, 20),
    'claude-fable-5': _price(10, 50, 1, 12.5, 20),
    'claude-opus-5-5': _price(4, 20, .2, 5, 8),
    'claude-opus-5': _price(5, 25, .5, 6.25, 10),
    'claude-opus-4-8': _price(5, 25, .5, 6.25, 10),
    'claude-opus-4-7': _price(5, 25, .5, 6.25, 10),
    'claude-opus-4-6': _price(5, 25, .5, 6.25, 10),
    'claude-opus-4-5': _price(5, 25, .5, 6.25, 10),
    'claude-sonnet-5-5': _price(2, 10, .1, 2.5, 4),
    'claude-sonnet-5': _price(2, 10, .2, 2.5, 4),
    'claude-sonnet-4-6': _price(3, 15, .3, 3.75, 6),
    'claude-haiku-5-5': _price(.1, .5, .01, .125, .2, long_from=100001, input_multiplier=5, output_multiplier=5),
    'claude-haiku-4-5': _price(1, 5, .1, 1.25, 2),
    'gpt-6.1-sol': _price(2, 10, .1, 2.5, 5, source=OPENAI, long_from=272001),
    'gpt-6-sol': _price(2, 10, .2, 2.5, 5, source='https://developers.openai.com/api/docs/models/gpt-6-sol', long_from=272001),
    'gpt-6-astra': _price(10, 50, 1, 12.5, 25, source=OPENAI, long_from=272001),
    'gpt-5.5': _price(5, 30, .5, source='https://developers.openai.com/api/docs/models/gpt-5.5', long_from=272001, session_tier=True),
    'gpt-5.3-codex': _price(1.75, 14, .175, source=OPENAI),
    'grok-4.7': _price(2, 6, .5, source=GROK, long_from=200000, output_multiplier=2),
    'grok-4.6': _price(2, 6, .5, source=GROK, long_from=200000, output_multiplier=2),
    'grok-4.5': _price(2, 6, .3, source=GROK, long_from=200000, output_multiplier=2),
    'grok-4.3': _price(1.25, 2.5, .2, source=GROK, long_from=200000, output_multiplier=2),
    'grok-build-0.1': _price(1, 2, .2, source=GROK, long_from=200000, output_multiplier=2),
}


@lru_cache(maxsize=512)
def lookup_price(model):
    canonical = model
    if canonical not in PRICES:
        canonical = re.sub(r'-(?:\d{8}|\d{4}-\d{2}-\d{2})$', '', model)
    return dict(PRICES[canonical], model=canonical) if canonical in PRICES else None


def estimate(row):
    price = lookup_price(row['model'])
    inputs, outputs = row['input_tokens'], row['output_tokens']
    result = {'usd': None, 'assumed': False}
    if price is None or inputs is None or outputs is None:
        return result
    cached, writes = row['cached_tokens'] or 0, row['cache_write_tokens'] or 0
    if writes and price['write'] is None:
        return result
    long_writes = row.get('cache_write_long_tokens')
    assumed = bool(writes and long_writes is None)
    long_writes = min(writes, max(0, long_writes or 0))
    # Cumulative deltas / Grok turn totals can span several requests. Applying a
    # long-context tier to their sum would inflate costs; disclose a short-tier
    # assumption instead. The UI calls every amount an API-equivalent estimate.
    request_level = row['key'].startswith(('request:', 'response:'))
    context = row.get('session_input_max', inputs) if price['session_tier'] else inputs
    long_context = bool(price['long_from'] and request_level and context >= price['long_from'])
    assumed |= bool(price['long_from'] and not request_level)
    input_multiplier = price['input_multiplier'] if long_context else 1
    output_multiplier = price['output_multiplier'] if long_context else 1
    prompt_cost = (max(0, inputs-cached-writes)*price['input'] + cached*price['cached']
                   + (writes-long_writes)*(price['write'] or 0) + long_writes*(price['long_write'] or price['write'] or 0))
    result.update(usd=(prompt_cost*input_multiplier + outputs*price['output']*output_multiplier)/1e6,
                  assumed=assumed)
    return result
