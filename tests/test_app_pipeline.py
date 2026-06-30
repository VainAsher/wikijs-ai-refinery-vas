"""UI smoke for the enrichment-pipeline pages (via the isolated TestClient)."""
from refinery.core import SourceDoc, deterministic_classify, build_wiki_path


def test_pipelines_page_loads(client):
    r = client.get('/pipelines')
    assert r.status_code == 200
    assert 'Customer Guide Pipeline' in r.text


def test_run_pipeline_from_doc_creates_draft_and_run_page(client):
    import refinery.app as app_mod
    doc = SourceDoc(title='Email Setup', source='employer_hosting', source_id='p1',
                    content='# Email\nConfigure SPF to authorise senders. WARNING: deleting the zone is irreversible.')
    c = deterministic_classify(doc, app_mod.TAXONOMY)
    src_id = app_mod.STORE.add_doc(doc, c, build_wiki_path(c))

    r = client.post(f'/docs/{src_id}/run-pipeline',
                    data={'pipeline_id': 'customer_guide_pipeline', 'target_action': 'rewrite_into_customer_guide',
                          'service': 'business_email', 'audience': 'customer', 'ollama_model': ''},
                    follow_redirects=False)
    assert r.status_code == 303
    new_id = int(r.headers['location'].split('/docs/')[1].split('?')[0])
    assert new_id != src_id

    draft = app_mod.STORE.get_doc(new_id)
    assert draft['source'] == 'vainasherstudios_pipeline' and draft['review_status'] == 'needs_review'
    assert draft['published'] == 0

    runs = app_mod.STORE.list_pipeline_runs(5)
    assert runs and runs[0]['new_doc_id'] == new_id
    assert client.get(f"/pipelines/{runs[0]['id']}").status_code == 200
    # the source doc's review page now offers the pipeline panel
    assert 'Run enrichment pipeline' in client.get(f'/docs/{src_id}').text
