import json
from refinery.pipeline import PipelineState, PassReport


def test_pass_report_roundtrip():
    r = PassReport(pass_id='draft', status='ok', mode='llm', model='mistral:latest',
                   changed=True, latency_ms=1200, warnings=['w'], metadata={'k': 'v'})
    d = r.to_dict()
    assert json.loads(json.dumps(d))            # JSON-serialisable
    r2 = PassReport.from_dict(d)
    assert r2 == r
    # unknown keys are ignored on load
    assert PassReport.from_dict({'pass_id': 'x', 'bogus': 1}).pass_id == 'x'


def test_pipeline_state_accumulates_and_roundtrips():
    s = PipelineState(source_doc_ids=[1, 2], service='minecraft', audience='customer')
    s.approved_facts.append('Restart clears the cache.')
    s.current_markdown = '# Draft'
    s.add_report(PassReport(pass_id='fact_find', changed=True))
    s.add_report(PassReport(pass_id='draft', mode='fallback'))
    d = s.to_dict()
    assert json.loads(json.dumps(d))            # whole state is JSON-serialisable
    assert len(d['pass_reports']) == 2 and d['pass_reports'][0]['pass_id'] == 'fact_find'
    s2 = PipelineState.from_dict(d)
    assert s2.source_doc_ids == [1, 2] and s2.approved_facts == ['Restart clears the cache.']
    assert s2.current_markdown == '# Draft'
