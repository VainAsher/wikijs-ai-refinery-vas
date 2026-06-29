"""Optional cloud refinement via the Claude API (ForgeOS's "cloud reroll" idea).

Lets an operator polish a draft with a more capable model than local Ollama. Opt-in
and degrades gracefully: needs the `anthropic` SDK plus an API key (ANTHROPIC_API_KEY
env or the encrypted anthropic_api_key setting). Without either, it returns a clean
error instead of raising, so the rest of the app is unaffected.
"""
from __future__ import annotations
from typing import Dict, Tuple

try:
    import anthropic
    _HAVE_ANTHROPIC = True
except Exception:  # pragma: no cover - SDK not installed
    anthropic = None
    _HAVE_ANTHROPIC = False

# Current Claude models + per-million-token pricing (USD), from the claude-api
# reference. Default to the most capable model unless the operator picks another.
CLAUDE_MODELS: Dict[str, Dict] = {
    'claude-opus-4-8':   {'label': 'Opus 4.8 — most capable', 'in': 5.0, 'out': 25.0},
    'claude-sonnet-4-6': {'label': 'Sonnet 4.6 — balanced',   'in': 3.0, 'out': 15.0},
    'claude-haiku-4-5':  {'label': 'Haiku 4.5 — fast & cheap', 'in': 1.0, 'out': 5.0},
}
DEFAULT_CLAUDE_MODEL = 'claude-opus-4-8'

REFINE_SYSTEM = (
    "You are an expert content editor for VainAsherStudios. Improve the document's clarity, "
    "structure, and flow while preserving its meaning, facts, and Markdown structure, and "
    "keeping the VainAsherStudios voice. Respond directly with only the improved Markdown — "
    "no preamble, no commentary, no code fences around the whole document."
)


def claude_available() -> bool:
    return _HAVE_ANTHROPIC


def estimate_tokens(text: str) -> int:
    """Rough local token estimate (~4 chars/token) for a pre-flight cost preview.
    Actual usage is read from the response and is authoritative."""
    return max(1, len(text or '') // 4)


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    p = CLAUDE_MODELS.get(model, CLAUDE_MODELS[DEFAULT_CLAUDE_MODEL])
    return round(in_tokens / 1_000_000 * p['in'] + out_tokens / 1_000_000 * p['out'], 4)


def refine_with_claude(text: str, instructions: str, model: str, api_key: str,
                       max_tokens: int = 8000) -> Tuple[bool, str, Dict]:
    """Refine `text` with Claude. Returns (ok, result_or_error, meta). On success the
    meta carries actual token usage and cost computed from the response."""
    if not _HAVE_ANTHROPIC:
        return False, 'The anthropic SDK is not installed (pip install anthropic).', {}
    if not api_key:
        return False, 'No Anthropic API key configured (set it on the Config page or ANTHROPIC_API_KEY).', {}
    model = model if model in CLAUDE_MODELS else DEFAULT_CLAUDE_MODEL
    user = (instructions.strip() + '\n\n' if instructions.strip() else '') + 'DOCUMENT TO IMPROVE:\n\n' + (text or '')
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=REFINE_SYSTEM,
            messages=[{'role': 'user', 'content': user}],
        )
        meta = {'model': model, 'input_tokens': resp.usage.input_tokens,
                'output_tokens': resp.usage.output_tokens,
                'cost': estimate_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)}
        if resp.stop_reason == 'refusal':
            return False, 'Claude declined to refine this content for safety reasons.', meta
        out = ''.join(b.text for b in resp.content if getattr(b, 'type', '') == 'text').strip()
        if not out:
            return False, 'Claude returned no text.', meta
        return True, out, meta
    except Exception as e:  # network/auth/SDK errors all surface as a clean message
        return False, f'Claude refinement failed: {e}', {}
