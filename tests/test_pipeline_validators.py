from refinery.core import DEFAULT_BRAND
from refinery.pipeline import PipelineState, PassDeps, evaluate_gates


def _deps(taxonomy):
    return PassDeps(taxonomy=taxonomy, brand=DEFAULT_BRAND)


def test_no_secret_leak_gate_is_critical_and_blocks(taxonomy):
    st = PipelineState(); st.current_markdown = 'Use AKIAIOSFODNN7EXAMPLE to connect.'
    res = evaluate_gates([{'name': 'no_secret_leak'}], st, _deps(taxonomy))[0]
    assert res['passed'] is False and res['critical'] is True


def test_source_governance_gate_blocks_reference_marked_canonical(taxonomy):
    st = PipelineState()
    st.classification = {'source_org': 'employer_hosting', 'source_role': 'employer_reference',
                         'canonical': True, 'customer_safe': True}
    res = evaluate_gates([{'name': 'source_governance_reasserted'}], st, _deps(taxonomy))[0]
    assert res['passed'] is False and res['critical'] is True
    # owned VAS content marked canonical is fine
    st.classification = {'source_org': 'vainasherstudios', 'source_role': 'owned', 'canonical': True}
    assert evaluate_gates([{'name': 'source_governance_reasserted'}], st, _deps(taxonomy))[0]['passed']


def test_brand_score_min_gate(taxonomy):
    st = PipelineState(); st.current_markdown = 'A calm, practical guide.'
    assert evaluate_gates([{'name': 'brand_score_min', 'value': 80}], st, _deps(taxonomy))[0]['passed']
    st.current_markdown = 'This revolutionary game-changer is best-in-class and cutting-edge.'
    assert not evaluate_gates([{'name': 'brand_score_min', 'value': 80}], st, _deps(taxonomy))[0]['passed']


def test_customer_safe_gate_flags_internal_markers(taxonomy):
    st = PipelineState(); st.current_markdown = '# Guide\nINTERNAL ONLY: do not share with customers.'
    res = evaluate_gates([{'name': 'customer_safe'}], st, _deps(taxonomy))[0]
    assert res['passed'] is False and res['critical'] is True


def test_human_review_always_required_and_unknown_gate_informational(taxonomy):
    st = PipelineState(); st.current_markdown = '# Doc\nbody'
    results = evaluate_gates([{'name': 'human_review_required'}, {'name': 'some_future_gate'}], st, _deps(taxonomy))
    assert results[0]['passed'] is True
    assert results[1]['passed'] is True and 'informational' in results[1]['message']
