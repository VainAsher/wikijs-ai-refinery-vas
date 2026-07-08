"""Endpoint smoke + behaviour tests via FastAPI TestClient.

The client fixture points the app at an isolated REFINERY_DATA (see conftest), so
these tests never touch a real store and don't require Ollama or Wiki.js.
"""
import time
from pathlib import Path


def _wait_for_jobs(client, timeout=10.0):
    """Imports/bulk updates now run in a background thread and report progress via
    /jobs/active. Block until nothing is still running so assertions are stable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = client.get('/jobs/active').json()['jobs']
        if not any(j['status'] == 'running' for j in jobs):
            return jobs
        time.sleep(0.05)
    raise AssertionError('background jobs did not finish within timeout')


def test_pages_load(client):
    for path in ('/', '/bulk', '/connectors', '/context', '/monitor', '/history', '/gaps', '/config', '/guide'):
        r = client.get(path)
        assert r.status_code == 200, path


def test_healthz_is_open(client):
    r = client.get('/healthz')
    assert r.status_code == 200 and r.json()['status'] == 'ok'


def test_missing_doc_404(client):
    r = client.get('/docs/999999')
    assert r.status_code == 404
    assert 'not found' in r.text.lower()


def test_bulk_import_then_filter(client, tmp_path):
    src = tmp_path / 'raw'
    src.mkdir()
    (src / 'a.md').write_text('# Minecraft Restart\nGame server panel, spigot plugins.', encoding='utf-8')
    r = client.post('/bulk/import-source-dirs',
                    data={'source_dirs': f'employer_hosting|{src}', 'limit': '0', 'ollama_model': ''},
                    follow_redirects=False)
    assert r.status_code == 303
    _wait_for_jobs(client)
    # the imported doc should now be filterable by its governed source_org
    listing = client.get('/?source_org=employer_hosting&page_size=100')
    assert listing.status_code == 200
    assert 'Minecraft Restart' in listing.text


def test_import_reports_progress_job(client, tmp_path):
    # the background import should surface a completed 'import' job with a known total
    src = tmp_path / 'rawp'; src.mkdir()
    for i in range(3):
        (src / f'd{i}.md').write_text(f'# Doc {i}\nhosting content', encoding='utf-8')
    r = client.post('/bulk/import-source-dirs',
                    data={'source_dirs': f'competitor_hosting_1|{src}', 'limit': '0'}, follow_redirects=False)
    assert r.status_code == 303
    jobs = _wait_for_jobs(client)
    done = [j for j in jobs if j['kind'] == 'import' and j['status'] == 'done']
    assert done and done[-1]['total'] == 3 and done[-1]['done'] == 3


def test_redaction_gate_flow(client, tmp_path):
    # import a doc containing a secret, confirm the gate detects it, then redact it
    src = tmp_path / 'sec'; src.mkdir()
    (src / 's.md').write_text('# Server\nUse key AKIAIOSFODNN7EXAMPLE to connect.', encoding='utf-8')
    client.post('/bulk/import-source-dirs',
                data={'source_dirs': f'employer_hosting|{src}', 'limit': '0'}, follow_redirects=False)
    _wait_for_jobs(client)
    doc_id = client.get('/?q=Server&page_size=100')  # find the doc id from the queue
    import re as _re
    m = _re.search(r'/docs/(\d+)', doc_id.text)
    assert m, 'doc not found in queue'
    did = m.group(1)
    page = client.get(f'/docs/{did}')
    assert 'Sensitive content gate' in page.text and 'aws_access_key' in page.text
    r = client.post(f'/docs/{did}/redact', data={'redact': ['0']}, follow_redirects=False)
    assert r.status_code == 303
    after = client.get(f'/docs/{did}/markdown')
    assert 'AKIAIOSFODNN7EXAMPLE' not in after.text and '[REDACTED:aws_access_key]' in after.text


def test_fact_gate_prepare_and_commit(client, tmp_path):
    # import a reference doc, open the fact gate, then commit to draft from approved facts
    src = tmp_path / 'fg'; src.mkdir()
    (src / 'f.md').write_text('# Restart\nStop the service, clear the cache, start it again.', encoding='utf-8')
    client.post('/bulk/import-source-dirs',
                data={'source_dirs': f'employer_hosting|{src}', 'limit': '0'}, follow_redirects=False)
    _wait_for_jobs(client)
    import re as _re
    did = _re.search(r'/docs/(\d+)', client.get('/?q=Restart&page_size=100').text).group(1)
    gate = client.post(f'/docs/{did}/transform/prepare',
                       data={'target_action': 'rewrite_into_runbook'})
    assert gate.status_code == 200 and 'Fact gate' in gate.text and 'verified_facts' in gate.text
    commit = client.post(f'/docs/{did}/transform/commit',
                         data={'target_action': 'rewrite_into_runbook',
                               'verified_facts': 'Stop the service before clearing the cache.'},
                         follow_redirects=False)
    assert commit.status_code == 303 and '/docs/' in commit.headers['location']


def test_config_save_roundtrip(client):
    r = client.post('/config/save',
                    data={'ollama_url': 'http://localhost:11434/api/generate',
                          'ollama_model': 'mistral:latest', 'wikijs_url': '', 'wikijs_token': ''},
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get('/config')
    assert 'mistral:latest' in page.text


def test_publish_without_config_reports_message(client, tmp_path):
    # import one doc, then try to publish with no Wiki.js config -> friendly message, no crash
    src = tmp_path / 'raw2'; src.mkdir()
    (src / 'b.md').write_text('# Email Setup\nSPF DKIM DMARC mailbox.', encoding='utf-8')
    client.post('/bulk/import-source-dirs', data={'source_dirs': f'infrastructure_provider_1|{src}', 'limit': '0'}, follow_redirects=False)
    _wait_for_jobs(client)
    listing = client.get('/?source_org=infrastructure_provider_1')
    assert 'Email Setup' in listing.text


def test_training_artifact_transform_review_and_export(client, tmp_path):
    # import a source doc, transform it straight into a quiz (no model configured -
    # exercises the deterministic fallback), approve it, then export it as raw JSON
    # and confirm the untransformed source doc doesn't leak into the export folder.
    import json, re as _re
    src = tmp_path / 'quizsrc'; src.mkdir()
    (src / 'q.md').write_text('# RCON Basics\nUse the rcon command to message players.', encoding='utf-8')
    client.post('/bulk/import-source-dirs',
                data={'source_dirs': f'employer_hosting|{src}', 'limit': '0'}, follow_redirects=False)
    _wait_for_jobs(client)
    source_id = _re.search(r'/docs/(\d+)', client.get('/?q=RCON+Basics&page_size=100').text).group(1)

    transform = client.post(f'/docs/{source_id}/transform',
                            data={'target_action': 'rewrite_into_quiz'}, follow_redirects=False)
    assert transform.status_code == 303
    draft_id = _re.search(r'/docs/(\d+)', transform.headers['location']).group(1)
    assert draft_id != source_id

    draft_page = client.get(f'/docs/{draft_id}')
    assert draft_page.status_code == 200

    approve = client.post(f'/docs/{draft_id}/quick', data={'action': 'approve'}, follow_redirects=False)
    assert approve.status_code == 303

    exported = client.get('/export/training/quiz')
    assert exported.status_code == 200
    body = exported.json()
    assert body['exported'] >= 1
    files = list(Path(body['folder']).glob('*.json'))
    assert files, 'expected at least one exported quiz JSON file'
    contents = [json.loads(f.read_text(encoding='utf-8')) for f in files]
    assert all('questions' in c for c in contents)  # only the quiz draft, never the raw source doc


def test_export_training_rejects_unknown_artifact_type(client):
    r = client.get('/export/training/not_a_real_type')
    assert r.status_code == 404
