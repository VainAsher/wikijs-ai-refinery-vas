from pathlib import Path
from refinery.core import SourceDoc, DEFAULT_BRAND, build_wiki_path
from refinery.pipeline import PassDeps, run_pipeline, load_pipeline_templates, load_pipeline_dict

REPO = Path(__file__).resolve().parent.parent


def _deps(taxonomy, content, source='employer_hosting'):
    doc = SourceDoc(title='Email Setup', content=content, source=source, source_id='9')
    return PassDeps(taxonomy=taxonomy, brand=DEFAULT_BRAND, model=None,
                    source_content=content, source_doc=doc)


def test_pipeline_runs_in_order_and_creates_governed_draft(taxonomy):
    cfg = load_pipeline_templates(REPO / 'pipeline_templates')['customer_guide_pipeline']
    content = ('# Email\nConfigure SPF to authorise senders. DKIM signs outgoing mail. '
               'WARNING: deleting the DNS zone is irreversible.')
    res = run_pipeline(cfg, _deps(taxonomy, content), target_action='rewrite_into_customer_guide',
                       service='business_email', audience='customer', source_doc_ids=[9])
    assert res.status == 'completed'
    # passes executed in template order
    assert [r['pass_id'] for r in res.state.pass_reports] == [p.id for p in cfg.passes]
    # state accumulated between passes (fact_find -> draft used facts)
    assert res.state.approved_facts
    assert 'awaiting human review' in res.draft.content.lower()
    # governed VAS draft, never canonical/customer-safe/published
    c = res.classification
    assert res.draft.source == 'vainasherstudios_pipeline'
    assert c.source_org == 'vainasherstudios' and c.source_role == 'owned'
    assert c.authority == 'draft' and c.review_status == 'needs_review'
    assert c.customer_safe is False and c.canonical is False
    assert 'pipeline-generated' in c.tags and 'human-review-required' in c.tags
    assert not build_wiki_path(c).startswith('imports/')      # owned path, not quarantined
    assert res.draft.raw_metadata['source_doc_ids'] == [9]    # lineage recorded
    # every pass has gate results recorded
    assert all('gate_results' in r['metadata'] for r in res.state.pass_reports)


def test_critical_gate_failure_stops_pipeline(taxonomy):
    # clean -> final_gate over a doc with a live secret: clean keeps it (no draft pass),
    # so final_gate's no_secret_leak (critical) fails and the run stops as failed.
    cfg = load_pipeline_dict({'id': 'p', 'passes': [
        {'id': 'clean_markdown'},
        {'id': 'final_gate', 'gates': ['no_secret_leak']},
    ]})
    res = run_pipeline(cfg, _deps(taxonomy, '# Doc\nUse AKIAIOSFODNN7EXAMPLE to connect.'))
    assert res.status == 'failed'
    assert any(g['name'] == 'no_secret_leak' for g in res.gate_failures)
    assert [r['pass_id'] for r in res.state.pass_reports] == ['clean_markdown', 'final_gate']
