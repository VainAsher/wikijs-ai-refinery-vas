from refinery.core import DEFAULT_BRAND
from refinery.pipeline import PassConfig, PipelineState, PassDeps, run_pass
import refinery.pipeline.passes as passes


def test_draft_fallback_without_model():
    st = PipelineState(target_action='rewrite_into_customer_guide')
    st.approved_facts = ['SPF authorises senders.', 'DKIM signs outgoing mail.']
    st.risks = ['Deleting the DNS zone is irreversible.']
    r = run_pass(PassConfig(id='draft'), st, PassDeps(model=None))
    assert r.mode == 'fallback' and r.changed
    assert 'SPF authorises senders.' in st.current_markdown
    assert 'Assumptions for Review' in st.current_markdown
    assert 'irreversible' in st.current_markdown.lower()        # risk preserved


def test_draft_uses_model_when_available(monkeypatch):
    monkeypatch.setattr(passes, 'ollama_text', lambda *a, **k: '# VAS Email Guide\n\nDetailed model draft body.')
    st = PipelineState(target_action='rewrite_into_customer_guide')
    r = run_pass(PassConfig(id='draft'), st, PassDeps(model='mistral:latest'))
    assert r.mode == 'llm' and 'Detailed model draft body.' in st.current_markdown


def test_brand_pass_reports_score():
    st = PipelineState(); st.current_markdown = 'This revolutionary game-changer is best-in-class.'
    r = run_pass(PassConfig(id='brand_pass'), st, PassDeps(model=None, brand=DEFAULT_BRAND))
    assert 'brand_score' in r.metadata and r.metadata['brand_score'] < 100
    assert 'revolutionary' in r.metadata['brand_violations']


def test_seo_adds_metadata_without_altering_body():
    body = '# Restart\n\nStop the service. WARNING: this is irreversible.\n\n```\nrm cache\n```'
    st = PipelineState(); st.current_markdown = body
    r = run_pass(PassConfig(id='seo_enrichment'), st, PassDeps(model=None))
    assert st.seo_metadata.get('meta_description')              # metadata added
    assert st.current_markdown == body                          # body untouched -> technical steps/warnings safe
    assert r.changed is False


def test_voice_pass_is_noop_without_model():
    st = PipelineState(); st.current_markdown = '# Draft\nbody'
    r = run_pass(PassConfig(id='voice_pass'), st, PassDeps(model=None))
    assert r.mode == 'fallback' and r.changed is False and st.current_markdown == '# Draft\nbody'
