"""ContextBuilder — assembles bounded, safety-filtered context for each pass.

A pass declares what it wants via its config:
  progressive_context.include / .exclude   -> fields from the running PipelineState
  retrieval.collections / .max_chunks       -> retrieved chunks from named collections

The builder enforces two safety rules on top of the per-pass config:
  1. A hard deny floor (secrets are NEVER included, even if a pass asks).
  2. The pass's own exclude list (customer-facing passes exclude raw source, internal
     notes, etc.) — applied to both progressive fields and retrieval collections.

Retrieval here is deliberately simple/deterministic (a name -> [chunks] mapping the
caller supplies); the embedding/vector layer is a later, optional phase.
"""
from __future__ import annotations
import json
from typing import Callable, Dict, List, Optional

from refinery.pipeline.schema import PassConfig
from refinery.pipeline.state import PipelineState

# Never included in any pass context, regardless of what a template requests.
SAFETY_DENY = {'secrets', 'raw_secrets', 'client_data', 'credentials'}


def _bullets(items: List[str]) -> str:
    return '\n'.join(f'- {str(i).strip()}' for i in (items or []) if str(i).strip())


# Progressive-context key -> how to render it from the state (+ raw source).
def _progressive_value(key: str, state: PipelineState, source_content: str) -> str:
    if key in ('source_content', 'raw_source_content'):
        return source_content or ''
    if key == 'current_draft':
        return state.current_markdown or ''
    if key == 'classification':
        return json.dumps(state.classification, ensure_ascii=False) if state.classification else ''
    if key in ('approved_facts', 'facts'):
        return _bullets(state.approved_facts)
    if key == 'assumptions':
        return _bullets(state.assumptions)
    if key == 'risks':
        return _bullets(state.risks)
    if key == 'warnings':
        return _bullets(state.warnings)
    if key in ('target_audience', 'audience'):
        return state.audience or ''
    if key == 'service':
        return state.service or ''
    if key == 'canonical_target':
        return str(state.classification.get('canonical_target', '') if state.classification else '')
    if key in ('metadata', 'seo_metadata'):
        return json.dumps(state.seo_metadata, ensure_ascii=False) if state.seo_metadata else ''
    return ''   # unknown key -> nothing (never raw-dump the whole state)


class ContextBuilder:
    """Builds a labelled context string for a pass. `collections` maps a collection
    name to a list of chunk strings; `retriever`, if given, can rank chunks for a query
    (deterministic fallback is just first-N) — the embedding layer plugs in here later."""

    def __init__(self, collections: Optional[Dict[str, List[str]]] = None,
                 retriever: Optional[Callable[[str, List[str], int], List[str]]] = None):
        self.collections = collections or {}
        self.retriever = retriever

    def build_for_pass(self, config: PassConfig, state: PipelineState, source_content: str = '') -> str:
        exclude = set(config.progressive_context.get('exclude', []) or []) | SAFETY_DENY
        include = [k for k in (config.progressive_context.get('include', []) or []) if k not in exclude]

        parts: List[str] = []
        for key in include:
            val = _progressive_value(key, state, source_content).strip()
            if val:
                parts.append(f'[{key.upper()}]\n{val}')

        rconf = config.retrieval or {}
        max_chunks = int(rconf.get('max_chunks', 0) or 0)
        if max_chunks > 0:
            remaining = max_chunks
            query = (state.current_markdown or source_content or '')[:2000]
            for col in (rconf.get('collections', []) or []):
                if col in exclude or col in SAFETY_DENY or remaining <= 0:
                    continue
                chunks = self.collections.get(col, [])
                if not chunks:
                    continue
                ranked = self.retriever(query, chunks, remaining) if self.retriever else list(chunks)
                picked = [c for c in ranked[:remaining] if str(c).strip()]
                if picked:
                    parts.append(f'[RETRIEVED: {col}]\n' + '\n\n'.join(picked))
                    remaining -= len(picked)
        return '\n\n'.join(parts)
