"""Pass executors.

Each executor takes (PassConfig, PipelineState, PassDeps), does deterministic or
LLM-optional work, mutates the state, and returns a PassReport. Deterministic passes
reuse the existing, already-tested core functions (clean_markdown, deterministic
classification, the sensitive scanner, fact extraction) so governance behaviour is
shared, not re-implemented. LLM passes land in the next phase; unknown pass ids are
skipped (status='skipped') so a pipeline runs end-to-end as executors are added.
"""
from __future__ import annotations
import dataclasses, re, time
from typing import Callable, Dict, Optional

from refinery.core import (
    SourceDoc, clean_markdown, deterministic_classify, extract_facts,
    scrub_findings,
)
from refinery.chunking import chunk_markdown
from refinery.pipeline.context import ContextBuilder
from refinery.pipeline.schema import PassConfig
from refinery.pipeline.state import PipelineState, PassReport


@dataclasses.dataclass
class PassDeps:
    taxonomy: Dict = dataclasses.field(default_factory=dict)
    brand: Dict = dataclasses.field(default_factory=dict)
    model: Optional[str] = None
    ollama_url: str = 'http://localhost:11434/api/generate'
    context_builder: Optional[ContextBuilder] = None
    source_content: str = ''
    source_doc: Optional[SourceDoc] = None


_RISK_WORDS = ('warning', 'caution', 'danger', 'irreversible', 'destructive', 'data loss',
               'delete', 'wipe', 'rm -rf', 'drop database', 'cannot be undone', 'permanent')


def _extract_risks(content: str) -> list:
    out = []
    for raw in re.split(r'(?<=[.!?])\s+|\n', content or ''):
        s = raw.strip()
        if 20 <= len(s) <= 200 and any(w in s.lower() for w in _RISK_WORDS):
            if s not in out:
                out.append(s)
    return out[:8]


def _clean_markdown(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    before = state.current_markdown or deps.source_content or ''
    cleaned = clean_markdown(before)
    cleaned = re.sub(r'(?m)^(#{1,6})([^#\s])', r'\1 \2', cleaned)   # normalise heading spacing
    state.current_markdown = cleaned
    return PassReport(pass_id=config.id, mode='deterministic',
                      changed=(cleaned.strip() != before.strip()), metadata={'chars': len(cleaned)})


def _classify(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    doc = deps.source_doc or SourceDoc(title='', content=state.current_markdown or deps.source_content, source='')
    c = deterministic_classify(doc, deps.taxonomy)               # governance applied inside
    state.classification = dataclasses.asdict(c)
    if state.service in ('', 'unknown'):
        state.service = c.service
    return PassReport(pass_id=config.id, mode='deterministic', changed=True,
                      metadata={'source_org': c.source_org, 'source_role': c.source_role,
                                'service': c.service, 'reuse_policy': c.reuse_policy})


def _chunk(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    text = state.current_markdown or deps.source_content or ''
    doc_id = state.source_doc_ids[0] if state.source_doc_ids else 0
    chunks = chunk_markdown(text, doc_id=doc_id)
    return PassReport(pass_id=config.id, mode='deterministic', changed=False,
                      metadata={'chunk_count': len(chunks),
                                'chunk_hashes': [c.content_hash for c in chunks]})


def _fact_find(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    doc = deps.source_doc or SourceDoc(title='', content=deps.source_content or state.current_markdown, source='')
    facts = extract_facts(doc, deps.model, deps.ollama_url)      # llm_optional; deterministic fallback inside
    state.approved_facts = facts.get('facts', [])
    state.risks = _extract_risks(doc.content)
    return PassReport(pass_id=config.id, mode=('llm' if deps.model else 'deterministic'),
                      changed=bool(state.approved_facts),
                      metadata={'fact_count': len(state.approved_facts), 'risk_count': len(state.risks),
                                'keywords': facts.get('keywords', []),
                                'note': 'facts are review candidates, not approved truth'})


def _final_gate(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    md = state.current_markdown or ''
    findings = scrub_findings(md)
    secret_leak = any(f.severity in ('critical', 'high') for f in findings)
    gates = {
        'non_empty_output': bool(md.strip()),
        'no_secret_leak': not secret_leak,
        'human_review_required': True,           # pipeline output ALWAYS needs review
    }
    failed = [g for g, ok in gates.items() if not ok]
    status = 'gate_failed' if any(g in failed for g in ('non_empty_output', 'no_secret_leak')) else 'ok'
    return PassReport(pass_id=config.id, mode='deterministic', status=status,
                      errors=[f'gate failed: {g}' for g in failed],
                      metadata={'gates': gates, 'finding_kinds': sorted({f.kind for f in findings})})


# Registry. LLM-optional passes (draft/voice/brand/audience/seo) are added next phase.
EXECUTORS: Dict[str, Callable[[PassConfig, PipelineState, PassDeps], PassReport]] = {
    'clean_markdown': _clean_markdown,
    'classify': _classify,
    'chunk': _chunk,
    'fact_find': _fact_find,
    'final_gate': _final_gate,
}


def run_pass(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    """Dispatch to the pass executor, time it, and append the report to the state.
    Passes without an executor yet are recorded as skipped (so a pipeline still runs)."""
    fn = EXECUTORS.get(config.id)
    t0 = time.time()
    if fn is None:
        report = PassReport(pass_id=config.id, status='skipped',
                            metadata={'reason': 'no executor implemented yet'})
    else:
        report = fn(config, state, deps)
    report.latency_ms = int((time.time() - t0) * 1000)
    state.add_report(report)
    return report
