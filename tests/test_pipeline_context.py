from refinery.pipeline import ContextBuilder, PassConfig, PipelineState


def _state():
    s = PipelineState(service='minecraft', audience='customer')
    s.approved_facts = ['Restart clears the cache.']
    s.current_markdown = '# Draft body'
    return s


def test_pass_receives_progressive_context():
    cfg = PassConfig(id='voice_pass', progressive_context={'include': ['current_draft', 'approved_facts', 'target_audience']})
    out = ContextBuilder().build_for_pass(cfg, _state(), source_content='RAW SOURCE')
    assert 'Draft body' in out
    assert 'Restart clears the cache.' in out
    assert 'customer' in out
    assert 'RAW SOURCE' not in out          # not requested


def test_customer_pass_excludes_raw_and_internal_context():
    cfg = PassConfig(id='draft', progressive_context={
        'include': ['current_draft', 'source_content', 'approved_facts'],
        'exclude': ['source_content', 'raw_source_content', 'internal_notes'],
    })
    out = ContextBuilder().build_for_pass(cfg, _state(), source_content='SECRET RAW SOURCE TEXT')
    assert 'Draft body' in out
    assert 'SECRET RAW SOURCE TEXT' not in out   # excluded even though include-listed


def test_secrets_never_included_even_if_requested():
    cfg = PassConfig(id='draft',
                     progressive_context={'include': ['secrets', 'current_draft']},
                     retrieval={'collections': ['secrets', 'vas_context'], 'max_chunks': 5})
    cb = ContextBuilder(collections={'secrets': ['API_KEY=sk-leak'], 'vas_context': ['VAS brand note']})
    out = cb.build_for_pass(cfg, _state())
    assert 'sk-leak' not in out                  # hard safety deny floor
    assert 'VAS brand note' in out               # non-secret collection still retrieved


def test_retrieval_respects_max_chunks():
    cfg = PassConfig(id='fact_find', retrieval={'collections': ['docs'], 'max_chunks': 3})
    cb = ContextBuilder(collections={'docs': [f'chunk {i}' for i in range(10)]})
    out = cb.build_for_pass(cfg, _state(), source_content='q')
    assert out.count('chunk ') == 3              # capped at max_chunks
