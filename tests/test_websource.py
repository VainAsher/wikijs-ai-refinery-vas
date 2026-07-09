"""FG-H5 Wave-2 CONTRACT TESTS - web sourcing as a user-exposed, opt-in config.

These tests are written FAILING-FIRST against docs/review/web-sourcing-spec.md and
are the executable spec for fix task FG-H5F. They encode:

- Settings schema: new web_sourcing_* keys in DEFAULTS/ENV_MAP, get_bool() semantics
  (spec section A, incl. both settings.py gotchas).
- Belt-and-braces domain rules: blacklist applied to query construction AND result
  filtering; allowlist-only mode; blacklist wins on conflict; subdomain matching
  (spec section B).
- Inert-when-disabled / offline-first: with web_sourcing_enabled off a full transform
  and a full pipeline make ZERO outbound HTTP attempts (spec section C).
- Per-run opt-in: fetch requires web_sourcing_enabled AND use_web_sources AND
  searxng_url (spec section A).
- Citations only ever minted from permitted domains - the terminal guard shared with
  FG-H3 (spec section B point 3).

Conventions: every Settings instance uses an isolated tmp_path store (never the real
data/settings.json); app-level tests monkeypatch refinery.app.SETTINGS onto an
isolated store too. The seam for HTTP assertions is refinery.websource._http_get
(the single place websource touches `requests`), plus an autouse fixture that makes
`requests` itself raise so the whole-app zero-outbound contract is directly observed.

refinery/websource.py does not exist yet: tests that need it fail via pytest.fail()
with a readable message (assertion-level failure, never a collection error).
"""
import json
import re
import time
from pathlib import Path

import pytest
import requests

from refinery.settings import Settings, DEFAULTS, ENV_MAP

REPO = Path(__file__).resolve().parent.parent

# Spec section A: key -> built-in default (all stored as strings).
WEB_SOURCING_DEFAULTS = {
    'web_sourcing_enabled': 'false',
    'searxng_url': '',
    'web_sourcing_max_sources': '6',
    'web_sourcing_results_per_keyword': '3',
    'web_sourcing_domain_blacklist': '',
    'web_sourcing_domain_allowlist': '',
    'web_sourcing_safe_search': 'true',
    'web_sourcing_probe_url': 'https://1.1.1.1',
    'web_sourcing_probe_timeout': '5.0',
}

# Spec section A: key -> env var.
WEB_SOURCING_ENV = {
    'web_sourcing_enabled': 'WEB_SOURCING_ENABLED',
    'searxng_url': 'SEARXNG_URL',
    'web_sourcing_max_sources': 'WEB_SOURCING_MAX_SOURCES',
    'web_sourcing_results_per_keyword': 'WEB_SOURCING_RESULTS_PER_KEYWORD',
    'web_sourcing_domain_blacklist': 'WEB_SOURCING_DOMAIN_BLACKLIST',
    'web_sourcing_domain_allowlist': 'WEB_SOURCING_DOMAIN_ALLOWLIST',
    'web_sourcing_safe_search': 'WEB_SOURCING_SAFE_SEARCH',
    'web_sourcing_probe_url': 'WEB_SOURCING_PROBE_URL',
    'web_sourcing_probe_timeout': 'WEB_SOURCING_PROBE_TIMEOUT',
}


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _websource():
    """Import refinery.websource, or fail (not error) with the contract it must meet."""
    try:
        import refinery.websource as ws
        return ws
    except ImportError:
        pytest.fail(
            'refinery/websource.py does not exist yet. FG-H5F must add it with: '
            'search(keywords, settings, *, use_web_sources) as the single entry point '
            '(guards first, no module-level HTTP client), _http_get(url, params, timeout) '
            'as the ONLY place requests.* is touched, and domain_allowed(url, blacklist, '
            'allowlist) as the shared rule function. See docs/review/web-sourcing-spec.md '
            'sections B and C.'
        )


def _isolated_settings(tmp_path, **saved):
    """Settings over an isolated tmp_path store - never the real data/settings.json."""
    s = Settings(tmp_path / 'settings.json')
    if saved:
        s.save(saved)
    return s


def _fact_url(fact):
    """RawFact may land as a dict or a small dataclass; accept either."""
    if isinstance(fact, dict):
        return fact.get('url', '')
    return getattr(fact, 'url', '')


class _FakeResponse:
    """Stand-in for the requests.Response returned through the _http_get seam."""

    def __init__(self, results):
        self._results = results
        self.status_code = 200
        self.ok = True

    def raise_for_status(self):
        return None

    def json(self):
        return {'results': self._results}


def _searxng_payload(*urls):
    return [{'title': f'result {i}', 'content': f'snippet {i}', 'url': u}
            for i, u in enumerate(urls)]


@pytest.fixture(autouse=True)
def outbound_attempts(monkeypatch):
    """Offline-first seam (spec C): any use of `requests` in this module's tests is an
    outbound attempt - recorded, and raised so unswallowed paths fail loudly."""
    attempts = []

    def _boom(kind):
        def _raise(*args, **kwargs):
            target = kwargs.get('url') or next((a for a in args if isinstance(a, str)), '?')
            attempts.append(f'requests.{kind} -> {target}')
            raise AssertionError(
                f'outbound HTTP attempted via requests.{kind} ({target}) during an '
                'offline-first contract test'
            )
        return _raise

    monkeypatch.setattr(requests, 'get', _boom('get'))
    monkeypatch.setattr(requests, 'post', _boom('post'))
    monkeypatch.setattr(requests.Session, 'request', _boom('Session.request'))
    return attempts


@pytest.fixture
def isolated_app_settings(tmp_path, monkeypatch):
    """Point the running app at an isolated tmp_path settings store so config-page
    round-trips never touch (or inherit state from) the shared session store."""
    import refinery.app as app_mod
    s = Settings(tmp_path / 'settings.json')
    monkeypatch.setattr(app_mod, 'SETTINGS', s)
    return s


def _wait_for_jobs(client, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = client.get('/jobs/active').json()['jobs']
        if not any(j['status'] == 'running' for j in jobs):
            return jobs
        time.sleep(0.05)
    raise AssertionError('background jobs did not finish within timeout')


# ---------------------------------------------------------------------------
# Settings parsing / defaults (spec A; E1, E2 + get_bool gotcha)
# ---------------------------------------------------------------------------

def test_web_sourcing_defaults(tmp_path):
    missing = [k for k in WEB_SOURCING_DEFAULTS if k not in DEFAULTS]
    assert not missing, (
        f'web sourcing keys missing from settings.DEFAULTS: {missing} '
        '(spec A: all nine keys are whitelisted, non-secret string defaults)'
    )
    for key, want in WEB_SOURCING_DEFAULTS.items():
        assert DEFAULTS[key] == want, (
            f'DEFAULTS[{key!r}] must be {want!r}, got {DEFAULTS[key]!r}'
        )
    s = _isolated_settings(tmp_path)
    assert hasattr(s, 'get_bool'), (
        'Settings.get_bool(key) is missing - spec A gotcha 1 requires a typed bool '
        "reader: str(value).strip().lower() in ('1','true','yes','on')"
    )
    assert s.get_bool('web_sourcing_enabled') is False, (
        'web_sourcing_enabled must default to False - OFF keeps Refinery offline-first'
    )
    assert s.get('searxng_url') == ''
    assert s.get('web_sourcing_max_sources') == '6'
    assert s.get('web_sourcing_results_per_keyword') == '3'
    assert s.get('web_sourcing_domain_blacklist') == ''
    assert s.get('web_sourcing_domain_allowlist') == ''


def test_web_sourcing_env_override(tmp_path, monkeypatch):
    missing = [k for k, v in WEB_SOURCING_ENV.items() if ENV_MAP.get(k) != v]
    assert not missing, (
        f'settings.ENV_MAP is missing/mismatched for web sourcing keys: {missing} '
        '(spec A maps each key to an env var)'
    )
    monkeypatch.setenv('WEB_SOURCING_ENABLED', 'true')
    s = _isolated_settings(tmp_path)
    assert hasattr(s, 'get_bool'), 'Settings.get_bool(key) is missing (spec A gotcha 1)'
    assert s.get_bool('web_sourcing_enabled') is True
    assert s.source_of('web_sourcing_enabled') == 'environment'


def test_settings_get_bool_semantics(tmp_path):
    s = _isolated_settings(tmp_path)
    if not hasattr(s, 'get_bool'):
        pytest.fail(
            'Settings.get_bool(key) is missing - spec A gotcha 1: needed because the '
            'store is string-only and checkboxes must round-trip as explicit '
            "'true'/'false' strings"
        )
    for truthy in ('1', 'true', 'yes', 'on', 'TRUE', ' On '):
        s.save({'web_sourcing_enabled': truthy})
        assert s.get_bool('web_sourcing_enabled') is True, (
            f'get_bool must treat {truthy!r} as True'
        )
    for falsy in ('0', 'false', 'no', 'off', 'anything-else'):
        s.save({'web_sourcing_enabled': falsy})
        assert s.get_bool('web_sourcing_enabled') is False, (
            f'get_bool must treat {falsy!r} as False'
        )


# ---------------------------------------------------------------------------
# Config-page round-trip (spec A UI + gotchas 1 & 2; E3)
# ---------------------------------------------------------------------------

def test_config_roundtrip(client, isolated_app_settings, tmp_path):
    # Checkbox ON + values: config_save must accept the new fields and persist them.
    r = client.post('/config/save', data={
        'web_sourcing_enabled': 'true',
        'searxng_url': 'http://searxng:8080',
        'web_sourcing_max_sources': '4',
        'web_sourcing_results_per_keyword': '2',
        'web_sourcing_domain_blacklist': 'blocked.example',
    }, follow_redirects=False)
    assert r.status_code == 303
    raw = json.loads((tmp_path / 'settings.json').read_text('utf-8'))
    assert raw.get('web_sourcing_enabled') == 'true', (
        'POST /config/save must persist web_sourcing_enabled to settings.json '
        '(config_save needs Form params + SETTINGS.save wiring for the new keys)'
    )
    assert raw.get('searxng_url') == 'http://searxng:8080'
    assert raw.get('web_sourcing_max_sources') == '4'

    # /config must render the new card with the saved values (via SETTINGS.view()).
    page = client.get('/config')
    assert 'web_sourcing_enabled' in page.text, (
        '/config page must render the "Web sourcing" card (spec A UI section)'
    )
    assert 'http://searxng:8080' in page.text

    # Checkbox OFF: an unchecked checkbox posts NOTHING, and save() skips empties, so
    # config_save must translate absence into an explicit persisted 'false'
    # (spec A gotcha 1 fix (a)).
    r = client.post('/config/save', data={
        'searxng_url': '',
        'web_sourcing_max_sources': '4',
    }, follow_redirects=False)
    assert r.status_code == 303
    raw = json.loads((tmp_path / 'settings.json').read_text('utf-8'))
    assert raw.get('web_sourcing_enabled') == 'false', (
        "unchecking the web_sourcing_enabled checkbox must persist an explicit 'false' "
        "string - it must never silently stay 'true' (spec A gotcha 1)"
    )
    # Blank NON-list text inputs keep the existing value (unchanged skip-empty rule).
    assert isolated_app_settings.get('searxng_url') == 'http://searxng:8080', (
        'blank searxng_url submission must keep the stored value (skip-empty semantics '
        'stay intact for non-checkbox, non-list keys)'
    )


def test_config_list_keys_always_overwrite(client, isolated_app_settings, tmp_path):
    # Seed both list keys through the UI path.
    r = client.post('/config/save', data={
        'web_sourcing_domain_blacklist': 'blocked.example\nworse.example',
        'web_sourcing_domain_allowlist': 'good.example',
    }, follow_redirects=False)
    assert r.status_code == 303
    assert isolated_app_settings.get('web_sourcing_domain_blacklist') == (
        'blocked.example\nworse.example'
    ), 'config_save must persist the multi-line blacklist textarea'
    assert isolated_app_settings.get('web_sourcing_domain_allowlist') == 'good.example'

    # Clearing from the UI must work: the two list keys are ALWAYS-OVERWRITE, so a
    # blank textarea empties the stored value (spec A gotcha 2, recommended tweak -
    # unlike token boxes, the UI is the source of truth for the domain rules).
    r = client.post('/config/save', data={
        'web_sourcing_domain_blacklist': '',
        'web_sourcing_domain_allowlist': '',
    }, follow_redirects=False)
    assert r.status_code == 303
    assert isolated_app_settings.get('web_sourcing_domain_allowlist') == '', (
        'clearing the allowlist textarea must persist empty - list keys are '
        'always-overwrite (spec A gotcha 2)'
    )
    assert isolated_app_settings.get('web_sourcing_domain_blacklist') == '', (
        'clearing the blacklist textarea must persist empty - list keys are '
        'always-overwrite (spec A gotcha 2)'
    )


# ---------------------------------------------------------------------------
# Blacklist / allowlist enforcement (spec B; E4-E7)
# ---------------------------------------------------------------------------

def test_blacklist_filters_results(tmp_path, monkeypatch):
    ws = _websource()
    s = _isolated_settings(
        tmp_path,
        web_sourcing_enabled='true',
        searxng_url='http://searxng.test:8080',
        web_sourcing_domain_blacklist='blocked.example',
    )
    monkeypatch.setattr(ws, '_http_get', lambda url, params, timeout: _FakeResponse(
        _searxng_payload(
            'https://ok.example/a',
            'https://blocked.example/b',
            'https://sub.blocked.example/c',
        )))
    out = ws.search(['spf'], s, use_web_sources=True)
    urls = [_fact_url(f) for f in out]
    assert any('ok.example' in u for u in urls), (
        f'permitted domain should survive result filtering, got {urls}'
    )
    assert not any('blocked.example' in u for u in urls), (
        f'blacklisted domain (incl. subdomains) leaked through result filtering: {urls} '
        '(spec B point 2 - the authoritative post-request gate)'
    )


def test_blacklist_filters_query(tmp_path, monkeypatch):
    ws = _websource()
    s = _isolated_settings(
        tmp_path,
        web_sourcing_enabled='true',
        searxng_url='http://searxng.test:8080',
        web_sourcing_domain_blacklist='blocked.example',
    )
    captured = []

    def _capture(url, params, timeout):
        captured.append((url, dict(params or {})))
        return _FakeResponse([])

    monkeypatch.setattr(ws, '_http_get', _capture)
    ws.search(['dns records'], s, use_web_sources=True)
    assert captured, 'search() must issue its queries through the _http_get seam'
    for url, params in captured:
        blob = (url + ' ' + ' '.join(str(v) for v in params.values())).lower()
        assert 'blocked.example' not in blob, (
            f'blacklisted domain appeared in an outgoing query ({url} {params}) - '
            'query construction must never include blacklisted terms (spec B point 1)'
        )


def test_allowlist_precedence(tmp_path, monkeypatch):
    ws = _websource()
    if not hasattr(ws, 'domain_allowed'):
        pytest.fail(
            'websource.domain_allowed(url, blacklist, allowlist) is missing - it is '
            'the single shared rule function (spec B)'
        )
    blacklist, allowlist = ['both.example'], ['allowed.example', 'both.example']
    assert ws.domain_allowed('https://allowed.example/x', blacklist, allowlist) is True
    assert ws.domain_allowed('https://other.example/x', blacklist, allowlist) is False, (
        'non-empty allowlist means allowlist-ONLY mode: unlisted domains are blocked'
    )
    assert ws.domain_allowed('https://both.example/x', blacklist, allowlist) is False, (
        'a domain in both lists must be BLOCKED - blacklist wins on conflict'
    )
    assert ws.domain_allowed('https://other.example/x', ['blocked.example'], []) is True, (
        'empty allowlist allows all non-blacklisted domains'
    )

    # And through search(): only allowlisted results survive.
    s = _isolated_settings(
        tmp_path,
        web_sourcing_enabled='true',
        searxng_url='http://searxng.test:8080',
        web_sourcing_domain_allowlist='allowed.example',
    )
    monkeypatch.setattr(ws, '_http_get', lambda url, params, timeout: _FakeResponse(
        _searxng_payload('https://allowed.example/a', 'https://other.example/b')))
    urls = [_fact_url(f) for f in ws.search(['x'], s, use_web_sources=True)]
    assert urls and all('allowed.example' in u for u in urls), (
        f'allowlist-only mode must drop non-allowlisted results, got {urls}'
    )


def test_subdomain_blocking(tmp_path):
    ws = _websource()
    if not hasattr(ws, 'domain_allowed'):
        pytest.fail('websource.domain_allowed(url, blacklist, allowlist) is missing (spec B)')
    assert ws.domain_allowed('https://example.com/p', ['example.com'], []) is False
    assert ws.domain_allowed('https://sub.example.com/p', ['example.com'], []) is False, (
        'blacklisting example.com must also block sub.example.com (endswith ".domain")'
    )
    assert ws.domain_allowed('https://sub.example.com:8443/p', ['example.com'], []) is False, (
        'port must be stripped before matching'
    )
    assert ws.domain_allowed('https://notexample.com/p', ['example.com'], []) is True, (
        'suffix match must respect the dot boundary - notexample.com is NOT a '
        'subdomain of example.com'
    )


# ---------------------------------------------------------------------------
# Inert-when-disabled / per-run opt-in (spec A + C; E8, E10-E12)
# ---------------------------------------------------------------------------

def _raising_http_get(*args, **kwargs):
    raise AssertionError(
        'websource._http_get was called even though the web-sourcing guards should '
        'have short-circuited (spec C: guards run before any HTTP object exists)'
    )


def test_inert_when_disabled_no_http(tmp_path, monkeypatch):
    ws = _websource()
    # Master flag left at its default (false); URL present; per-run opt-in true.
    s = _isolated_settings(tmp_path, searxng_url='http://searxng.test:8080')
    monkeypatch.setattr(ws, '_http_get', _raising_http_get)
    assert ws.search(['anything'], s, use_web_sources=True) == [], (
        'search() must return [] when web_sourcing_enabled is false'
    )


def test_per_transform_optin(tmp_path, monkeypatch):
    ws = _websource()
    # Master flag ON, but the per-run checkbox was not ticked -> no fetch.
    s = _isolated_settings(
        tmp_path,
        web_sourcing_enabled='true',
        searxng_url='http://searxng.test:8080',
    )
    monkeypatch.setattr(ws, '_http_get', _raising_http_get)
    assert ws.search(['anything'], s, use_web_sources=False) == [], (
        'the master flag only makes the capability AVAILABLE - each run must also '
        'opt in via use_web_sources (spec A per-run semantics)'
    )


def test_empty_searxng_url_is_inert(tmp_path, monkeypatch):
    ws = _websource()
    s = _isolated_settings(tmp_path, web_sourcing_enabled='true')  # no searxng_url
    monkeypatch.setattr(ws, '_http_get', _raising_http_get)
    assert ws.search(['anything'], s, use_web_sources=True) == [], (
        'enabled + opted-in but empty searxng_url must be inert (spec C guards: '
        'effective fetch requires enabled AND use_web_sources AND searxng_url)'
    )


def test_wan_probe_offline_degrades(tmp_path, monkeypatch):
    ws = _websource()
    s = _isolated_settings(
        tmp_path,
        web_sourcing_enabled='true',
        searxng_url='http://searxng.test:8080',
    )

    def _offline(url, params=None, timeout=None):
        raise requests.exceptions.ConnectionError(f'offline: {url}')

    monkeypatch.setattr(ws, '_http_get', _offline)
    out = ws.search(['anything'], s, use_web_sources=True)
    assert out == [], (
        'when the WAN probe/search cannot reach the network, search() must degrade to '
        '[] - no exception, and NO ChromaDB fallback (spec C: offline-first means '
        '"no sources", not "fetch from a vector container")'
    )


# ---------------------------------------------------------------------------
# Offline-first whole-app contract (spec C; E9)
# ---------------------------------------------------------------------------

def test_offline_first_pipeline_no_outbound(client, tmp_path, taxonomy,
                                            outbound_attempts, isolated_app_settings):
    # The contract is about the FEATURE being present but dark by default, so the
    # module must exist before this test means anything.
    _websource()

    # web_sourcing_enabled is false by default in the isolated store. The autouse
    # fixture makes every requests.* call raise AND records the attempt.
    src = tmp_path / 'offline-src'
    src.mkdir()
    (src / 'd.md').write_text(
        '# Restart Procedure\nStop the service, clear the cache, start it again.',
        encoding='utf-8')
    r = client.post('/bulk/import-source-dirs',
                    data={'source_dirs': f'employer_hosting|{src}', 'limit': '0'},
                    follow_redirects=False)
    assert r.status_code == 303
    _wait_for_jobs(client)
    m = re.search(r'/docs/(\d+)', client.get('/?q=Restart+Procedure&page_size=100').text)
    assert m, 'imported doc not found in queue'

    # Full transform with the flag off.
    r = client.post(f'/docs/{m.group(1)}/transform',
                    data={'target_action': 'rewrite_into_runbook'},
                    follow_redirects=False)
    assert r.status_code == 303, 'transform must still work fully offline'

    # Full pipeline with the flag off.
    from refinery.core import SourceDoc, DEFAULT_BRAND
    from refinery.pipeline import PassDeps, run_pipeline, load_pipeline_templates
    cfg = load_pipeline_templates(REPO / 'pipeline_templates')['customer_guide_pipeline']
    content = '# Email\nConfigure SPF to authorise senders. DKIM signs outgoing mail.'
    doc = SourceDoc(title='Email Setup', content=content, source='employer_hosting',
                    source_id='9')
    res = run_pipeline(cfg, PassDeps(taxonomy=taxonomy, brand=DEFAULT_BRAND, model=None,
                                     source_content=content, source_doc=doc),
                       target_action='rewrite_into_customer_guide')
    assert res.status == 'completed', 'pipeline must still complete fully offline'

    assert outbound_attempts == [], (
        'with web_sourcing_enabled=false, a full transform + full pipeline must make '
        f'ZERO outbound HTTP attempts, but saw: {outbound_attempts} (spec C '
        'offline-first contract)'
    )


# ---------------------------------------------------------------------------
# Terminal citation guard, shared with FG-H3 (spec B point 3; E13)
# ---------------------------------------------------------------------------

def test_citation_only_from_permitted_domains(tmp_path):
    ws = _websource()
    try:
        import refinery.citations as citations
    except ImportError:
        pytest.fail(
            'refinery/citations.py does not exist yet. FG-H3 owns CitationRecord / '
            'to_citation(); FG-H5 must ensure the citation-mint boundary re-applies '
            'domain_allowed as the TERMINAL guard so a blacklisted domain can never '
            'appear in verified_citations, even if an upstream filter is bypassed '
            '(spec B point 3).'
        )

    blacklist, allowlist = ['blocked.example'], []
    # Deliberately hand the mint boundary a fact that BYPASSED search()'s filter -
    # the terminal guard must still drop it.
    facts = _searxng_payload('https://ok.example/a', 'https://blocked.example/b')
    minter = (getattr(citations, 'mint_citations', None)
              or getattr(citations, 'filter_permitted', None))
    if minter is None:
        pytest.fail(
            'no citation-mint boundary found on refinery.citations (expected '
            'mint_citations(facts, blacklist, allowlist) or filter_permitted(...)) - '
            'the terminal domain guard must live at the point CitationRecords are '
            'minted (spec B point 3)'
        )
    minted = minter(facts, blacklist, allowlist)
    rendered = json.dumps([getattr(c, '__dict__', c) for c in minted], default=str)
    assert 'ok.example' in rendered, (
        'permitted-domain facts must still mint citations at the boundary'
    )
    assert 'blocked.example' not in rendered, (
        'a blacklisted domain reached a minted CitationRecord - the terminal guard at '
        'the citation boundary must re-apply domain_allowed (spec B point 3: the '
        '"can never appear" guarantee)'
    )
