"""FG-H3 CONTRACT TESTS - citation enrichment (the top-ranked ForgeOS harvest).

Written FAILING-FIRST against the Cartographer dossier (forgeos docs/review/
harvest-inventory.md section 3) as the executable spec for fix task FG-H3F.
They encode the donor lifecycle - mint -> bind claim->citation -> carry through
drafting -> embed verified_citations in output - re-expressed in Refinery's
sync/dataclass idiom on top of what FG-H5F already landed (refinery/citations.py
mint_citations + refinery/websource.py search(), currently present-but-dark):

- FactBlock (donor schemas.py L22-27) as a stdlib dataclass in refinery.citations.
- attribute_facts(doc, web_facts=, blacklist=, allowlist=, model=None) ->
  (fact_blocks, citation_records): the local source doc mints SRC-001 as a
  local-kind citation, permitted web facts mint sequential url-kind citations
  THROUGH the mint_citations terminal guard, and every FactBlock.citation_id
  refers to a minted citation (donor Auditor discipline, agents.py L128-192,
  deterministic when model is None - matching extract_facts' llm-optional idiom).
- validate_claims(fact_blocks, citations) -> (verified, rejected): a claim citing
  a nonexistent SRC-id is REJECTED, never silently kept.
- build_verified_citations(fact_blocks, citations) -> list of {id, source_name,
  url|local_path} dicts listing ONLY citations referenced by validated claims
  (donor exporter.py build_frontmatter used_ids; deliberately WITHOUT the donor's
  `or citations` fallback - unreferenced sources never masquerade as verified).
- Wiring: PipelineState carries fact_blocks + citations; PassDeps carries
  settings + use_web_sources; with the master flag AND the per-run opt-in AND a
  searxng_url the fact_find/enrichment path calls websource.search() (observed at
  the _http_get funnel) and web facts flow into verified_citations on the draft's
  raw_metadata; with the flag (or opt-in) OFF the SAME path completes local-only
  with ZERO outbound HTTP - extending, never violating, the inert-when-disabled
  seam from tests/test_websource.py.

Conventions: every Settings instance uses an isolated tmp_path store (never the
real data/settings.json). Missing modules/attributes fail via pytest.fail() with
the contract they must meet (assertion-level failure, never a collection error) -
the same guard pattern test_websource.py used for the then-missing websource.
"""
import dataclasses
import json
import re
from pathlib import Path

import pytest
import requests

import refinery.citations as citations
import refinery.websource as websource
from refinery.core import DEFAULT_BRAND, SourceDoc
from refinery.pipeline import PassDeps, load_pipeline_templates, run_pipeline
from refinery.pipeline.state import PipelineState
from refinery.settings import Settings

REPO = Path(__file__).resolve().parent.parent

SRC_ID = re.compile(r'^SRC-\d{3}$')

LOCAL_DOC = SourceDoc(
    title='Email Setup',
    content=('# SPF Records\n'
             'Configure SPF to authorise the sending servers for your domain. '
             'DKIM signs outgoing mail with a private key held by the server. '
             'DMARC tells receiving servers how to treat authentication failures.'),
    source='employer_hosting', source_id='42')

WEB_FACTS = [
    {'title': 'SPF syntax guide', 'kind': 'url',
     'content': 'An SPF record is a TXT record listing permitted senders.',
     'url': 'https://ok.example/spf'},
    {'title': 'Blocked SEO spam', 'kind': 'url',
     'content': 'Ten weird tricks for email deliverability.',
     'url': 'https://blocked.example/spam'},
]


# ---------------------------------------------------------------------------
# Guarded accessors - missing contract surface fails with the spec, not an error.
# ---------------------------------------------------------------------------

def _factblock_cls():
    cls = getattr(citations, 'FactBlock', None)
    if cls is None:
        pytest.fail(
            'refinery.citations.FactBlock is missing. FG-H3F must port the donor '
            'FactBlock (forgeos schemas.py L22-27: claim + citation_id) as a stdlib '
            'dataclass alongside CitationRecord - pydantic BaseModel -> dataclass is '
            'the established adaptation (see the CitationRecord docstring).'
        )
    return cls


def _factblock(claim, citation_id):
    return _factblock_cls()(claim=claim, citation_id=citation_id)


def _attribute_facts(**kwargs):
    fn = getattr(citations, 'attribute_facts', None)
    if fn is None:
        pytest.fail(
            'refinery.citations.attribute_facts(doc, web_facts=, blacklist=, '
            'allowlist=, model=None) is missing. FG-H3F must adapt the donor '
            'Auditor (agents.py L128-192) to the extract_facts idiom: extract '
            'claims from the local doc (SRC-001, local kind) and from permitted '
            'web facts (minted THROUGH mint_citations so the terminal domain '
            'guard applies), returning (fact_blocks, citation_records). '
            'Deterministic when model is None, like extract_facts.'
        )
    out = fn(**kwargs)
    assert isinstance(out, tuple) and len(out) == 2, (
        'attribute_facts must return the donor-shaped pair (fact_blocks, '
        f'citation_records), got {type(out).__name__}'
    )
    return out


def _validate_claims(fact_blocks, cites):
    fn = getattr(citations, 'validate_claims', None)
    if fn is None:
        pytest.fail(
            'refinery.citations.validate_claims(fact_blocks, citations) is missing. '
            'FG-H3F must port the Auditor claim->SRC-id validation loop: a claim is '
            'only VERIFIED if its citation_id exists in the minted citation set; '
            'everything else lands in the rejected list (flagged, never silently '
            'kept and never silently dropped). Return (verified, rejected).'
        )
    out = fn(fact_blocks, cites)
    assert isinstance(out, tuple) and len(out) == 2, (
        f'validate_claims must return (verified, rejected), got {type(out).__name__}'
    )
    return out


def _build_verified(fact_blocks, cites):
    fn = getattr(citations, 'build_verified_citations', None)
    if fn is None:
        pytest.fail(
            'refinery.citations.build_verified_citations(fact_blocks, citations) is '
            'missing. FG-H3F must port the donor frontmatter block (exporter.py '
            'build_frontmatter L36-58): emit only citations referenced by validated '
            'claims, each as {id, source_name, url|local_path} - WITHOUT the donor '
            '"or citations" fallback (an unreferenced source is not verified).'
        )
    return fn(fact_blocks, cites)


def _verified_block(result):
    meta = result.draft.raw_metadata or {}
    if 'verified_citations' not in meta:
        pytest.fail(
            "pipeline draft raw_metadata has no 'verified_citations' block. FG-H3F "
            'must embed the validated citation list on the enriched output (the '
            'refinery analogue of the donor frontmatter: runner._build_draft already '
            'carries seo_metadata this way), as JSON-serialisable dicts of '
            '{id, source_name, url|local_path}.'
        )
    return meta['verified_citations']


def _cid(c):
    return c.get('id') if isinstance(c, dict) else getattr(c, 'id', None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def outbound_attempts(monkeypatch):
    """Offline-first seam (same as test_websource.py): any requests.* call is an
    outbound attempt - recorded, and raised so unswallowed paths fail loudly."""
    attempts = []

    def _boom(kind):
        def _raise(*args, **kwargs):
            target = kwargs.get('url') or next((a for a in args if isinstance(a, str)), '?')
            attempts.append(f'requests.{kind} -> {target}')
            raise AssertionError(
                f'outbound HTTP attempted via requests.{kind} ({target}) during a '
                'local-only citation-enrichment test'
            )
        return _raise

    monkeypatch.setattr(requests, 'get', _boom('get'))
    monkeypatch.setattr(requests, 'post', _boom('post'))
    monkeypatch.setattr(requests.Session, 'request', _boom('Session.request'))
    return attempts


def _isolated_settings(tmp_path, **saved):
    """Settings over an isolated tmp_path store - never the real data/settings.json."""
    s = Settings(tmp_path / 'settings.json')
    if saved:
        s.save(saved)
    return s


class _FakeResponse:
    def __init__(self, results):
        self._results = results
        self.status_code = 200
        self.ok = True

    def raise_for_status(self):
        return None

    def json(self):
        return {'results': self._results}


def _enrichment_deps(settings, use_web, taxonomy, doc):
    """PassDeps for the enrichment path. The web-sourcing guards live on settings +
    the per-run opt-in, so the deps must carry both (deps already carry every other
    per-run input: source_content, source_doc, model...)."""
    names = {f.name for f in dataclasses.fields(PassDeps)}
    missing = sorted({'settings', 'use_web_sources'} - names)
    if missing:
        pytest.fail(
            f'PassDeps lacks {missing}. FG-H3F must thread the Settings store and '
            'the per-run use_web_sources opt-in into the pipeline so the '
            'fact_find/enrichment path can call websource.search(keywords, settings, '
            'use_web_sources=...) - the single web funnel; effective fetch still '
            'requires web_sourcing_enabled AND use_web_sources AND searxng_url.'
        )
    return PassDeps(taxonomy=taxonomy, brand=DEFAULT_BRAND, model=None,
                    source_content=doc.content, source_doc=doc,
                    settings=settings, use_web_sources=use_web)


def _run_enrichment(settings, use_web, taxonomy, doc=LOCAL_DOC):
    cfg = load_pipeline_templates(REPO / 'pipeline_templates')['customer_guide_pipeline']
    deps = _enrichment_deps(settings, use_web, taxonomy, doc)
    return run_pipeline(cfg, deps, target_action='rewrite_into_customer_guide')


# ---------------------------------------------------------------------------
# 1. FactBlock - donor schema in refinery dataclass style
# ---------------------------------------------------------------------------

def test_factblock_is_refinery_style_dataclass():
    cls = _factblock_cls()
    assert dataclasses.is_dataclass(cls), (
        'FactBlock must be a stdlib dataclass (Refinery house style - see '
        'CitationRecord), not a pydantic model like the donor'
    )
    names = [f.name for f in dataclasses.fields(cls)]
    assert 'claim' in names and 'citation_id' in names, (
        f'FactBlock must carry claim + citation_id (donor schemas.py L22-27), '
        f'got fields {names}'
    )
    fb = cls(claim='SPF is a TXT record.', citation_id='SRC-001')
    assert fb.claim and fb.citation_id == 'SRC-001'


# ---------------------------------------------------------------------------
# 2-3. Source attribution in fact extraction (local doc vs web kinds)
# ---------------------------------------------------------------------------

def test_attribute_facts_local_doc_mints_local_citation():
    fact_blocks, cites = _attribute_facts(doc=LOCAL_DOC, web_facts=[],
                                          blacklist=[], allowlist=[])
    assert cites, 'a local-only run must still mint the source doc as a citation'
    local = cites[0]
    assert local.id == 'SRC-001', (
        f'the local source doc must be SRC-001 (ids sequential per run), got {local.id!r}'
    )
    assert local.source_name == LOCAL_DOC.title, (
        'the local citation source_name must be the source doc title '
        f'(donor to_citation semantics), got {local.source_name!r}'
    )
    assert local.local_path and not local.url, (
        'a local doc is a local-kind citation: local_path set, url empty - kind is '
        f'expressed through which field is populated, got url={local.url!r} '
        f'local_path={local.local_path!r}'
    )
    assert fact_blocks, 'extract_facts finds claims in this doc, so attribution must too'
    valid_ids = {c.id for c in cites}
    for fb in fact_blocks:
        assert fb.citation_id in valid_ids, (
            f'every FactBlock must cite a minted citation, but {fb.claim!r} cites '
            f'{fb.citation_id!r} (valid: {sorted(valid_ids)}) - the Auditor discipline'
        )
    assert any(fb.citation_id == 'SRC-001' for fb in fact_blocks), (
        'claims extracted from the local doc must be attributed to its SRC-001 citation'
    )


def test_attribute_facts_web_kinds_and_terminal_domain_guard():
    fact_blocks, cites = _attribute_facts(doc=LOCAL_DOC, web_facts=WEB_FACTS,
                                          blacklist=['blocked.example'], allowlist=[])
    ids = [c.id for c in cites]
    assert ids == [f'SRC-{i:03d}' for i in range(1, len(cites) + 1)], (
        f'SRC ids must be stable and sequential across local+web in one run, got {ids}'
    )
    rendered = json.dumps([dataclasses.asdict(c) for c in cites])
    assert 'ok.example' in rendered, (
        'the permitted web fact must mint a url-kind citation carrying its url'
    )
    assert 'blocked.example' not in rendered, (
        'a blacklisted-domain web fact minted a citation - attribution must go '
        'THROUGH mint_citations so the terminal domain guard applies (spec B point 3)'
    )
    web = [c for c in cites if c.url]
    assert web and all(c.source_name for c in web), (
        'web citations must carry url AND title (source_name) for traceability'
    )
    valid_ids = {c.id for c in cites}
    assert all(fb.citation_id in valid_ids for fb in fact_blocks), (
        'no FactBlock may cite an unminted (e.g. domain-blocked) source'
    )
    assert any(fb.citation_id in {c.id for c in web} for fb in fact_blocks), (
        'each permitted web fact contributes claims attributed to ITS citation '
        '(deterministic mode: the fact content is the claim source)'
    )


# ---------------------------------------------------------------------------
# 4. Claim -> citation validation loop (donor Auditor discipline)
# ---------------------------------------------------------------------------

def test_validate_claims_rejects_nonexistent_src_id():
    cites = citations.mint_citations(WEB_FACTS[:1], [], [])
    good = _factblock('An SPF record is a TXT record.', cites[0].id)
    ghost = _factblock('Email was invented in 1965.', 'SRC-999')
    verified, rejected = _validate_claims([good, ghost], cites)
    assert good in verified, 'a claim citing an existing SRC-id must verify'
    assert ghost not in verified, (
        'a claim citing nonexistent SRC-999 leaked into the verified set - the '
        'Auditor loop must only accept citation_ids from the minted set'
    )
    assert ghost in rejected, (
        'the invalid claim must be FLAGGED in the rejected list, not silently dropped '
        '- reviewers need to see what failed validation'
    )


# ---------------------------------------------------------------------------
# 5. verified_citations block - only validated, donor dict shape, no fallback
# ---------------------------------------------------------------------------

def test_build_verified_citations_lists_only_validated():
    cites = [
        citations.CitationRecord(id='SRC-001', source_name='Email Setup', local_path='doc:42'),
        citations.CitationRecord(id='SRC-002', source_name='SPF guide', url='https://ok.example/spf'),
        citations.CitationRecord(id='SRC-003', source_name='DKIM guide', url='https://ok.example/dkim'),
    ]
    fact_blocks = [
        _factblock('Local claim.', 'SRC-001'),
        _factblock('DKIM signs mail.', 'SRC-003'),
        _factblock('Ghost claim.', 'SRC-999'),
    ]
    block = _build_verified(fact_blocks, cites)
    assert isinstance(block, list) and all(isinstance(e, dict) for e in block), (
        'verified_citations must be a JSON-serialisable list of dicts (it is embedded '
        'in persisted output metadata/frontmatter)'
    )
    got = sorted(e.get('id') for e in block)
    assert got == ['SRC-001', 'SRC-003'], (
        f'verified_citations must list EXACTLY the citations referenced by validated '
        f'claims - SRC-002 is unreferenced and SRC-999 does not exist - got {got}'
    )
    for e in block:
        assert e.get('source_name'), f'each entry needs source_name: {e}'
        assert bool(e.get('url')) != bool(e.get('local_path')), (
            f'each entry carries exactly one of url (web kind) or local_path '
            f'(local kind), per the CitationRecord dataclass: {e}'
        )
    assert _build_verified([_factblock('Ghost.', 'SRC-999')], cites) == [], (
        'when NO claim survives validation the block must be empty - the donor '
        '"or citations" fallback is deliberately NOT ported (an unreferenced source '
        'must never masquerade as verified)'
    )


# ---------------------------------------------------------------------------
# 6. Pipeline state carries the citation channel (persistable, like all state)
# ---------------------------------------------------------------------------

def test_pipeline_state_carries_fact_blocks_and_citations():
    names = {f.name for f in dataclasses.fields(PipelineState)}
    missing = sorted({'fact_blocks', 'citations'} - names)
    assert not missing, (
        f'PipelineState lacks {missing} - fact_find must land attributed facts and '
        'minted citations on the state (as JSON-round-trippable dicts, like every '
        'other PipelineState field) so later passes and persistence can see them'
    )
    payload = {'fact_blocks': [{'claim': 'x', 'citation_id': 'SRC-001'}],
               'citations': [{'id': 'SRC-001', 'source_name': 'Email Setup',
                              'local_path': 'doc:42', 'url': None}]}
    state = PipelineState.from_dict(payload)
    round_tripped = state.to_dict()
    assert round_tripped['fact_blocks'] == payload['fact_blocks'], (
        'fact_blocks must survive the to_dict/from_dict persistence round-trip'
    )
    assert round_tripped['citations'] == payload['citations'], (
        'citations must survive the to_dict/from_dict persistence round-trip'
    )


# ---------------------------------------------------------------------------
# 7-9. Wiring: websource.search() lights up the dark funnel; same path is
#      local-only + zero-HTTP when the flag or the per-run opt-in is off.
# ---------------------------------------------------------------------------

def test_pipeline_web_enrichment_calls_search_and_mints(tmp_path, taxonomy, monkeypatch):
    s = _isolated_settings(
        tmp_path,
        web_sourcing_enabled='true',
        searxng_url='http://searxng.test:8080',
        web_sourcing_domain_blacklist='blocked.example',
        web_sourcing_max_sources='2',
    )
    captured = []

    def _fake_http_get(url, params, timeout):
        captured.append((url, dict(params or {})))
        return _FakeResponse([
            {'title': 'SPF syntax guide', 'content': 'An SPF record is a TXT record.',
             'url': 'https://ok.example/spf'},
            {'title': 'Blocked spam', 'content': 'Ten weird tricks.',
             'url': 'https://blocked.example/spam'},
        ])

    monkeypatch.setattr(websource, '_http_get', _fake_http_get)
    res = _run_enrichment(s, use_web=True, taxonomy=taxonomy)
    assert res.status == 'completed'
    assert captured, (
        'with web_sourcing_enabled + per-run opt-in + searxng_url all set, the '
        'enrichment path must fetch through websource.search() (observed at the '
        '_http_get funnel) - FG-H3 is what wires the PRESENT-BUT-DARK websource '
        'module to a production call site'
    )
    block = _verified_block(res)
    rendered = json.dumps(block)
    assert 'ok.example' in rendered, (
        f'the permitted web source must flow through mint_citations into '
        f'verified_citations, got {block}'
    )
    assert 'blocked.example' not in rendered, (
        'a blacklisted domain reached verified_citations - web facts must be minted '
        'through the terminal guard in citations.py'
    )
    ids = [_cid(e) for e in block]
    assert all(i and SRC_ID.match(i) for i in ids) and len(ids) == len(set(ids)), (
        f'verified_citations ids must be unique SRC-### ids, got {ids}'
    )


def test_pipeline_disabled_same_path_is_local_only_zero_http(
        tmp_path, taxonomy, outbound_attempts):
    # Master flag at its default (false); per-run box ticked - still inert.
    s = _isolated_settings(tmp_path, searxng_url='http://searxng.test:8080')
    res = _run_enrichment(s, use_web=True, taxonomy=taxonomy)
    assert res.status == 'completed', (
        'the enrichment path must be ONE code path: with web sourcing dark it still '
        'completes local-only (extend, not duplicate, the offline-first seam)'
    )
    assert outbound_attempts == [], (
        'with web_sourcing_enabled=false the enrichment path must make ZERO outbound '
        f'HTTP attempts, but saw: {outbound_attempts}'
    )
    block = _verified_block(res)
    assert block, (
        'local-only enrichment must still attribute the source doc - '
        'verified_citations must carry the local-kind citation'
    )
    for e in block:
        assert e.get('local_path') and not e.get('url'), (
            f'with web sourcing dark every verified citation must be local-kind '
            f'(local_path, no url), got {e}'
        )


def test_pipeline_per_run_optout_no_http(tmp_path, taxonomy, monkeypatch,
                                         outbound_attempts):
    # Master flag ON and url set, but this run did NOT opt in.
    s = _isolated_settings(
        tmp_path,
        web_sourcing_enabled='true',
        searxng_url='http://searxng.test:8080',
    )

    def _raising_http_get(*args, **kwargs):
        raise AssertionError(
            'websource._http_get was reached although use_web_sources=False - the '
            'master flag only makes the capability AVAILABLE; each run must opt in'
        )

    monkeypatch.setattr(websource, '_http_get', _raising_http_get)
    res = _run_enrichment(s, use_web=False, taxonomy=taxonomy)
    assert res.status == 'completed'
    assert outbound_attempts == [], (
        f'per-run opt-out must mean zero outbound HTTP, saw: {outbound_attempts}'
    )
    for e in _verified_block(res):
        assert not e.get('url'), (
            f'an opted-out run must not carry web citations, got {e}'
        )
