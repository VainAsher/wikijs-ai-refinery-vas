from pathlib import Path
from refinery.core import SourceDoc, DEFAULT_BRAND, deterministic_classify, build_wiki_path
from refinery.pipeline import load_pipeline_templates, run_and_persist

REPO = Path(__file__).resolve().parent.parent


def _seed_source(store, taxonomy):
    doc = SourceDoc(title='Email Setup', source='employer_hosting', source_id='1',
                    content='# Email\nConfigure SPF to authorise senders. WARNING: deleting the zone is irreversible.')
    c = deterministic_classify(doc, taxonomy)
    return store.add_doc(doc, c, build_wiki_path(c))


def test_run_and_persist_creates_draft_and_records_everything(store, taxonomy):
    src_id = _seed_source(store, taxonomy)
    cfg = load_pipeline_templates(REPO / 'pipeline_templates')['customer_guide_pipeline']
    out = run_and_persist(store, cfg, source_doc_id=src_id, taxonomy=taxonomy, brand=DEFAULT_BRAND,
                          model=None, service='business_email', audience='customer')
    assert out['status'] == 'completed' and out['new_doc_id'] != src_id

    # the generated draft is a governed, unpublished VAS doc
    draft = store.get_doc(out['new_doc_id'])
    assert draft['source'] == 'vainasherstudios_pipeline' and draft['review_status'] == 'needs_review'
    assert draft['published'] == 0

    # run + passes + lineage + chunks all persisted
    run = store.get_pipeline_run(out['run_id'])
    assert run['status'] == 'completed' and run['new_doc_id'] == out['new_doc_id']
    assert len(store.list_pass_runs(out['run_id'])) == len(cfg.passes)
    assert store.get_doc_chunks(out['new_doc_id'])           # draft was chunked/indexed
    lineage = store.conn.execute('SELECT * FROM doc_lineage WHERE child_doc_id=?', (out['new_doc_id'],)).fetchone()
    assert lineage['parent_doc_id'] == src_id and lineage['relationship'] == 'pipeline_draft'
