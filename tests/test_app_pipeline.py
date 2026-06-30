"""UI smoke for the enrichment-pipeline pages (via the isolated TestClient)."""
import time
from refinery.core import SourceDoc, deterministic_classify, build_wiki_path


def _wait_for_jobs(client, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(j['status'] == 'running' for j in client.get('/jobs/active').json()['jobs']):
            return
        time.sleep(0.05)
    raise AssertionError('pipeline job did not finish in time')


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

    # Runs in the background now → redirects straight back to the source doc.
    r = client.post(f'/docs/{src_id}/run-pipeline',
                    data={'pipeline_id': 'customer_guide_pipeline', 'target_action': 'rewrite_into_customer_guide',
                          'service': 'business_email', 'audience': 'customer', 'deterministic': '1'},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers['location'] == f'/docs/{src_id}?notice=Pipeline+started+%E2%80%94+progress+in+the+tray'

    _wait_for_jobs(client)
    runs = app_mod.STORE.list_pipeline_runs(5)
    assert runs and runs[0]['status'] == 'completed'
    new_id = runs[0]['new_doc_id']
    assert new_id and new_id != src_id

    draft = app_mod.STORE.get_doc(new_id)
    assert draft['source'] == 'vainasherstudios_pipeline' and draft['review_status'] == 'needs_review'
    assert draft['published'] == 0
    assert client.get(f"/pipelines/{runs[0]['id']}").status_code == 200
    # the source doc's review page now offers the pipeline panel
    assert 'Run enrichment pipeline' in client.get(f'/docs/{src_id}').text
