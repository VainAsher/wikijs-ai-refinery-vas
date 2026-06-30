import json
from refinery.chunking import chunk_markdown
from refinery.pipeline import PipelineState, PassReport


def test_pipeline_and_pass_run_persistence(store):
    rid = store.add_pipeline_run(pipeline_id='customer_guide_pipeline', source_doc_ids=[1, 2],
                                 target_action='rewrite_into_customer_guide', service='email', audience='customer')
    assert isinstance(rid, int)
    store.add_pass_run(rid, PassReport(pass_id='clean_markdown', status='ok', latency_ms=5).to_dict())
    store.add_pass_run(rid, PassReport(pass_id='draft', status='ok', mode='fallback', latency_ms=12).to_dict())

    state = PipelineState(source_doc_ids=[1, 2], service='email')
    store.finish_pipeline_run(rid, status='completed', state=state.to_dict(), new_doc_id=99)

    run = store.get_pipeline_run(rid)
    assert run['status'] == 'completed' and run['new_doc_id'] == 99 and run['completed_at']
    assert json.loads(run['source_doc_ids_json']) == [1, 2]
    assert json.loads(run['state_json'])['service'] == 'email'

    passes = store.list_pass_runs(rid)
    assert [p['pass_id'] for p in passes] == ['clean_markdown', 'draft']
    assert store.list_pipeline_runs()[0]['id'] == rid


def test_doc_chunks_roundtrip_is_idempotent(store):
    chunks = chunk_markdown('# A\nbody a\n\n## B\nbody b', doc_id=42)
    n = store.replace_doc_chunks(42, chunks)
    assert n == len(chunks)
    got = store.get_doc_chunks(42)
    assert len(got) == len(chunks)
    assert json.loads(got[0]['heading_path_json']) == chunks[0].heading_path
    assert got[0]['content_hash'] == chunks[0].content_hash
    # re-storing replaces, never duplicates
    store.replace_doc_chunks(42, chunks)
    assert len(store.get_doc_chunks(42)) == len(chunks)


def test_doc_lineage_recorded(store):
    lid = store.add_doc_lineage(parent_doc_id=1, child_doc_id=2, relationship='pipeline_draft',
                                pipeline_run_id=7, pass_id='draft')
    row = store.conn.execute('SELECT * FROM doc_lineage WHERE id=?', (lid,)).fetchone()
    assert row['parent_doc_id'] == 1 and row['child_doc_id'] == 2
    assert row['relationship'] == 'pipeline_draft' and row['pipeline_run_id'] == 7
