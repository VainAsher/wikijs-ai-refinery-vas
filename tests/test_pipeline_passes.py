from refinery.core import SourceDoc
from refinery.pipeline import PassConfig, PipelineState, PassDeps, run_pass


def _deps(taxonomy, content, source='employer_hosting'):
    doc = SourceDoc(title='Restart Guide', content=content, source=source, source_id='1')
    return PassDeps(taxonomy=taxonomy, model=None, source_content=content, source_doc=doc)


def test_clean_markdown_pass(taxonomy):
    raw = '# Title[edit]\n\n\n\n\nBody.\n<!-- comment -->\n##Section\n'
    st = PipelineState(); deps = _deps(taxonomy, raw)
    r = run_pass(PassConfig(id='clean_markdown'), st, deps)
    assert r.status == 'ok' and r.changed
    assert '[edit]' not in st.current_markdown and '<!--' not in st.current_markdown
    assert '## Section' in st.current_markdown          # heading spacing normalised
    assert st.pass_reports[-1]['pass_id'] == 'clean_markdown'


def test_classify_pass_populates_governance(taxonomy):
    st = PipelineState(); deps = _deps(taxonomy, '# Restart\nStop the spigot server, restore backup.')
    r = run_pass(PassConfig(id='classify'), st, deps)
    assert st.classification['source_org'] == 'employer_hosting'
    assert st.classification['source_role'] == 'employer_reference'   # governance reasserted
    assert r.metadata['service'] == st.service


def test_chunk_pass_counts_chunks(taxonomy):
    st = PipelineState(source_doc_ids=[5])
    st.current_markdown = '# A\nbody a\n\n## B\nbody b'
    r = run_pass(PassConfig(id='chunk'), st, _deps(taxonomy, ''))
    assert r.metadata['chunk_count'] >= 2 and len(r.metadata['chunk_hashes']) == r.metadata['chunk_count']


def test_fact_find_deterministic(taxonomy):
    content = ('# DNS\nConfigure SPF to authorise senders. DKIM signs outgoing mail. '
               'WARNING: deleting the zone is irreversible and causes data loss.')
    st = PipelineState(); r = run_pass(PassConfig(id='fact_find'), st, _deps(taxonomy, content))
    assert r.mode == 'deterministic' and st.approved_facts
    assert any('irreversible' in risk.lower() for risk in st.risks)   # risk extracted
    assert r.metadata['note'].startswith('facts are review candidates')


def test_final_gate_blocks_secret_leak(taxonomy):
    st = PipelineState(); st.current_markdown = '# Doc\nUse AKIAIOSFODNN7EXAMPLE to connect.'
    r = run_pass(PassConfig(id='final_gate'), st, _deps(taxonomy, ''))
    assert r.status == 'gate_failed'
    assert r.metadata['gates']['no_secret_leak'] is False
    assert r.metadata['gates']['human_review_required'] is True


def test_unimplemented_pass_is_skipped(taxonomy):
    # provenance_attach is a known pass id with no executor yet -> skipped (not errored).
    st = PipelineState(); r = run_pass(PassConfig(id='provenance_attach'), st, _deps(taxonomy, ''))
    assert r.status == 'skipped' and st.pass_reports[-1]['status'] == 'skipped'
