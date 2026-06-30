"""Deterministic gate validators.

Safety is decided by deterministic code, never by an LLM's self-assessment. Each gate
is a pure function (state, deps, params) -> (passed, message) and reuses the existing,
tested core primitives: the sensitive scanner, the brand scorer, the taxonomy, and the
source-governance rules. CRITICAL_GATES block a run on failure; the rest are warnings.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Tuple

from refinery.core import brand_compliance, reference_source_orgs, scrub_findings

Result = Tuple[bool, str]

# Gates that must pass — a failure stops/flags the pipeline as unsafe.
CRITICAL_GATES = {'non_empty_output', 'no_secret_leak', 'source_governance_reasserted', 'customer_safe'}

_INTERNAL_MARKERS = ('internal only', 'internal-only', 'admin only', 'admin-only',
                     'do not share', 'confidential', '[internal', 'staff only')


def _md(state) -> str:
    return state.current_markdown or ''


def gate_non_empty_output(state, deps, params) -> Result:
    return (bool(_md(state).strip()), 'output is empty' if not _md(state).strip() else 'ok')


def gate_no_secret_leak(state, deps, params) -> Result:
    bad = [f.kind for f in scrub_findings(_md(state)) if f.severity in ('critical', 'high')]
    return (not bad, f'secret/PII leak: {", ".join(sorted(set(bad)))}' if bad else 'ok')


def gate_taxonomy_valid(state, deps, params) -> Result:
    tax, c = deps.taxonomy or {}, state.classification or {}
    if not c:
        return (True, 'no classification to validate')
    checks = [('doc_type', 'doc_types'), ('service', 'services'), ('audience', 'audiences'),
              ('authority', 'authorities'), ('source_org', 'source_orgs'), ('source_role', 'source_roles'),
              ('reuse_policy', 'reuse_policies'), ('rewrite_status', 'rewrite_statuses')]
    bad = [f'{field}={c[field]}' for field, key in checks
           if c.get(field) and tax.get(key) and c[field] not in tax[key]]
    return (not bad, f'invalid taxonomy values: {", ".join(bad)}' if bad else 'ok')


def gate_source_governance_reasserted(state, deps, params) -> Result:
    c = state.classification or {}
    role = c.get('source_role', '')
    is_reference = (c.get('source_org') in reference_source_orgs()) or (role not in ('', 'owned'))
    if is_reference and (c.get('canonical') or c.get('customer_safe')):
        return (False, 'reference material marked canonical/customer_safe — governance not reasserted')
    return (True, 'ok')


def gate_customer_safe(state, deps, params) -> Result:
    ok_secret, msg = gate_no_secret_leak(state, deps, params)
    if not ok_secret:
        return (False, msg)
    low = _md(state).lower()
    hit = [m for m in _INTERNAL_MARKERS if m in low]
    return (not hit, f'internal-only content in customer output: {", ".join(hit)}' if hit else 'ok')


def gate_brand_score_min(state, deps, params) -> Result:
    threshold = int(params.get('value', 0) or 0)
    score = brand_compliance(_md(state), deps.brand or {}).get('overall_score', 0)
    return (score >= threshold, f'brand score {score} < {threshold}' if score < threshold else f'brand score {score}')


def gate_seo_metadata_present(state, deps, params) -> Result:
    ok = bool((state.seo_metadata or {}).get('meta_description'))
    return (ok, 'ok' if ok else 'missing SEO meta_description')


def gate_human_review_required(state, deps, params) -> Result:
    return (True, 'human review required before publish')      # always flagged, never auto-cleared


def gate_no_forbidden_change_marker(state, deps, params) -> Result:
    low = _md(state).lower()
    bad = [m for m in ('[removed warning]', '[forbidden]', 'todo:', 'fixme') if m in low]
    return (not bad, f'forbidden-change markers present: {", ".join(bad)}' if bad else 'ok')


def gate_facts_are_review_candidates(state, deps, params) -> Result:
    return (True, 'extracted facts are review candidates, not approved truth')


def gate_non_empty(state, deps, params) -> Result:
    return gate_non_empty_output(state, deps, params)


VALIDATORS: Dict[str, Callable] = {
    'non_empty_output': gate_non_empty_output,
    'non_empty': gate_non_empty,
    'no_secret_leak': gate_no_secret_leak,
    'taxonomy_valid': gate_taxonomy_valid,
    'source_governance_reasserted': gate_source_governance_reasserted,
    'customer_safe': gate_customer_safe,
    'brand_score_min': gate_brand_score_min,
    'seo_metadata_present': gate_seo_metadata_present,
    'human_review_required': gate_human_review_required,
    'no_forbidden_change_marker': gate_no_forbidden_change_marker,
    'facts_are_review_candidates': gate_facts_are_review_candidates,
}


def evaluate_gates(gates: List[Dict[str, Any]], state, deps) -> List[Dict[str, Any]]:
    """Run each gate; returns a list of {name, passed, critical, message}. Unknown gate
    names pass as informational (so a template can name a not-yet-coded gate)."""
    out = []
    for g in (gates or []):
        name = g.get('name', '')
        fn = VALIDATORS.get(name)
        if fn is None:
            out.append({'name': name, 'passed': True, 'critical': False, 'message': 'no validator (informational)'})
            continue
        passed, message = fn(state, deps, g)
        out.append({'name': name, 'passed': bool(passed),
                    'critical': name in CRITICAL_GATES, 'message': message})
    return out
