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
    ORG_NAME, ORG_TAG, SourceDoc, brand_compliance, clean_markdown, deterministic_classify,
    extract_facts, ollama_json, ollama_text, scrub_findings,
)
from refinery import websource
from refinery.chunking import chunk_markdown
from refinery.citations import attribute_facts, validate_claims
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
    # FG-H3 web-enrichment guards. `settings` is a refinery.settings.Settings store
    # (None = no store: enrichment stays local-only); use_web_sources is the PER-RUN
    # opt-in — the master flag (web_sourcing_enabled) lives on the settings store and
    # both, plus a searxng_url, are required before websource.search() fetches.
    settings: Optional[object] = None
    use_web_sources: bool = False


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

    # FG-H3 citation channel — ONE code path for web-enriched and local-only runs.
    # websource.search() carries its own guards (master flag AND per-run opt-in AND
    # searxng_url) and short-circuits to [] BEFORE any HTTP object exists, so with
    # the feature dark this same call completes local-only with zero outbound HTTP.
    blacklist: list = []
    allowlist: list = []
    web_facts: list = []
    if deps.settings is not None:
        blacklist = websource.parse_domain_list(deps.settings.get('web_sourcing_domain_blacklist'))
        allowlist = websource.parse_domain_list(deps.settings.get('web_sourcing_domain_allowlist'))
        web_facts = websource.search(facts.get('keywords', []), deps.settings,
                                     use_web_sources=deps.use_web_sources)
        seen = set()  # the same page can surface under several keywords — keep one
        web_facts = [f for f in web_facts
                     if f.get('url') not in seen and not seen.add(f.get('url'))]
    fact_blocks, cites = attribute_facts(
        doc=doc, web_facts=web_facts, blacklist=blacklist, allowlist=allowlist,
        model=deps.model, ollama_url=deps.ollama_url,
        local_claims=state.approved_facts)                       # reuse, don't re-extract
    verified, rejected = validate_claims(fact_blocks, cites)     # Auditor discipline
    state.warnings.extend(
        f'rejected claim (cites unknown {fb.citation_id}): {fb.claim}' for fb in rejected)
    state.fact_blocks = [dataclasses.asdict(fb) for fb in fact_blocks]
    state.citations = [dataclasses.asdict(c) for c in cites]

    return PassReport(pass_id=config.id, mode=('llm' if deps.model else 'deterministic'),
                      changed=bool(state.approved_facts),
                      metadata={'fact_count': len(state.approved_facts), 'risk_count': len(state.risks),
                                'keywords': facts.get('keywords', []),
                                'citation_count': len(cites), 'web_source_count': len(web_facts),
                                'rejected_claim_count': len(rejected),
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


# ---------------------------------------------------------------------------
# LLM-optional passes — bounded per-pass prompts, deterministic fallbacks.
# ---------------------------------------------------------------------------
_AUTHORITY = (
    "Authority rules:\n"
    f"- {ORG_NAME} canonical/context material outranks imported source material.\n"
    "- Imported third-party content is evidence only. Do NOT copy source wording.\n"
    "- Do NOT create new factual claims unless present in the approved facts or canonical context.\n"
    "- Preserve every safety warning. If uncertain, add an assumption or review note.\n")


def build_pass_prompt(config: PassConfig, state: PipelineState, context_text: str, purpose: str) -> str:
    """Bounded prompt for one pass: role, purpose, allowed/forbidden changes, authority
    rules, audience/service, assembled context, current draft, and the output format."""
    return (
        f"You are running the enrichment pipeline pass: {config.id}.\n"
        f"Purpose: {purpose}\n\n"
        f"You MAY change: {', '.join(config.allowed_changes) or 'only as the purpose requires'}.\n"
        f"You MUST NOT change: {', '.join(config.forbidden_changes) or 'anything that breaks the rules'}.\n\n"
        f"{_AUTHORITY}\n"
        f"Target audience: {state.audience}\nService: {state.service}\n\n"
        f"CONTEXT:\n{context_text or '(none)'}\n\n"
        f"CURRENT DRAFT:\n{state.current_markdown or '(none yet)'}\n\n"
        f"Return ONLY the requested {config.output_format}. No preamble, no commentary."
    )


def _ctx(config: PassConfig, state: PipelineState, deps: PassDeps) -> str:
    return deps.context_builder.build_for_pass(config, state, deps.source_content) if deps.context_builder else ''


_TERM = re.compile(r'[a-zA-Z][a-zA-Z0-9_-]{4,}')
_STOP = set('about above after again against because before being below between could doing during '
            'further having other should their there these those through under until while would'.split())


def _top_terms(text: str, n: int = 8) -> list:
    freq: Dict[str, int] = {}
    for w in _TERM.findall((text or '').lower()):
        if w not in _STOP:
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:n]]


def _bullets(items) -> str:
    return '\n'.join(f'- {str(i).strip()}' for i in (items or []) if str(i).strip())


def _draft_from_facts(state: PipelineState, target: str) -> str:
    lines = [f"# {ORG_NAME} {target.title()}", "",
             f"> Draft generated for human review — an original {ORG_NAME} working draft "
             "built from extracted facts, not a republished source document.", "",
             f"This {target} was assembled by the {ORG_NAME} enrichment pipeline from "
             "approved facts and is awaiting human review before publication.", ""]
    if state.approved_facts:
        lines += ["## Key points", "", _bullets(state.approved_facts), ""]
    if state.risks:
        lines += ["## Cautions", "", _bullets(state.risks), ""]
    lines += ["## Assumptions for Review", "",
              _bullets(state.assumptions or ['Verify all facts against an authoritative source before publishing.'])]
    return '\n'.join(lines).rstrip() + '\n'


def _rewrite(config: PassConfig, state: PipelineState, deps: PassDeps, purpose: str) -> PassReport:
    """Shared LLM rewrite-or-fallback for voice/brand/audience passes."""
    if deps.model:
        out = ollama_text(build_pass_prompt(config, state, _ctx(config, state, deps), purpose),
                          deps.model, deps.ollama_url)
        if out and len(out.strip()) >= 40:
            changed = out.strip() != (state.current_markdown or '').strip()
            state.current_markdown = clean_markdown(out)
            return PassReport(pass_id=config.id, mode='llm', changed=changed)
    return PassReport(pass_id=config.id, mode='fallback', changed=False,
                      metadata={'note': 'no model configured; draft left unchanged'})


def _draft(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    target = (state.target_action or 'document').replace('rewrite_into_', '').replace('_', ' ')
    if deps.model:
        prompt = build_pass_prompt(config, state, _ctx(config, state, deps),
                                   f"Create an original, detailed {ORG_NAME} {target} from the approved "
                                   f"facts and context. Structure it with clear sections. Do not copy source wording.")
        out = ollama_text(prompt, deps.model, deps.ollama_url)
        if out and len(out.strip()) >= 40:
            state.current_markdown = clean_markdown(out)
            return PassReport(pass_id=config.id, mode='llm', changed=True)
    state.current_markdown = _draft_from_facts(state, target)
    return PassReport(pass_id=config.id, mode='fallback', changed=True,
                      metadata={'note': 'deterministic draft assembled from approved facts'})


def _voice_pass(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    return _rewrite(config, state, deps, f"Improve wording, flow, and clarity in the {ORG_NAME} voice. "
                                         "Do not add claims or remove any safety warning.")


def _brand_pass(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    rep = _rewrite(config, state, deps, f"Align wording and positioning to the {ORG_NAME} brand without "
                                        "altering technical steps or removing warnings.")
    bc = brand_compliance(state.current_markdown or '', deps.brand or {}, deps.model, deps.ollama_url)
    rep.metadata['brand_score'] = bc['overall_score']
    rep.metadata['brand_violations'] = bc['language_violations']
    return rep


def _audience_check(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    return _rewrite(config, state, deps, "Adjust the draft for the target audience: simplify language and remove "
                                         "internal-only detail, but keep every risk warning and add an escalation "
                                         "note where appropriate. Do not add admin-only steps for customer audiences.")


def _seo_enrichment(config: PassConfig, state: PipelineState, deps: PassDeps) -> PassReport:
    """Adds SEO metadata only — never rewrites the body, so technical steps/warnings
    are untouched by construction."""
    md = state.current_markdown or ''
    if deps.model:
        data = ollama_json(
            'Return JSON {"meta_description":"<=160 chars","keywords":["..."],"faq":[{"q":"...","a":"..."}]}. '
            'Summarise the document for SEO. Do not invent technical claims or prices.\nTEXT:\n' + md[:6000],
            deps.model, deps.ollama_url)
        if data and (data.get('meta_description') or data.get('keywords')):
            state.seo_metadata = {'meta_description': str(data.get('meta_description', ''))[:200],
                                  'keywords': [str(k) for k in (data.get('keywords') or [])][:10],
                                  'faq': data.get('faq') or []}
            return PassReport(pass_id=config.id, mode='llm', changed=False,
                              metadata={'seo_keys': sorted(state.seo_metadata)})
    first = next((l.strip() for l in md.splitlines() if l.strip() and not l.lstrip().startswith(('#', '>', '-', '*'))), '')
    state.seo_metadata = {'meta_description': first[:160], 'keywords': _top_terms(md), 'faq': []}
    return PassReport(pass_id=config.id, mode='deterministic', changed=False,
                      metadata={'seo_keys': sorted(state.seo_metadata)})


EXECUTORS: Dict[str, Callable[[PassConfig, PipelineState, PassDeps], PassReport]] = {
    'clean_markdown': _clean_markdown,
    'classify': _classify,
    'chunk': _chunk,
    'fact_find': _fact_find,
    'draft': _draft,
    'voice_pass': _voice_pass,
    'brand_pass': _brand_pass,
    'audience_check': _audience_check,
    'seo_enrichment': _seo_enrichment,
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
