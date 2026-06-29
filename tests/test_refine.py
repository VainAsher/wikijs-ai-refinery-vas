from refinery.refine import (
    estimate_tokens, estimate_cost, refine_with_claude,
    CLAUDE_MODELS, DEFAULT_CLAUDE_MODEL,
)


def test_default_model_is_opus_4_8():
    # The cloud reroll must default to the most capable current model.
    assert DEFAULT_CLAUDE_MODEL == 'claude-opus-4-8'
    assert 'claude-opus-4-8' in CLAUDE_MODELS


def test_estimate_cost_uses_per_million_pricing():
    # Opus 4.8 is $5/$25 per million tokens.
    cost = estimate_cost('claude-opus-4-8', in_tokens=1_000_000, out_tokens=1_000_000)
    assert cost == 30.0
    assert estimate_tokens('x' * 400) == 100  # ~4 chars/token


def test_refine_without_api_key_returns_clean_error():
    # No key -> graceful failure, never raises (so the app stays usable).
    ok, msg, meta = refine_with_claude('# Doc\nbody', '', 'claude-opus-4-8', api_key='')
    assert ok is False and 'key' in msg.lower() and meta == {}
