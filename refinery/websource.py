"""Web sourcing (FG-H5) — opt-in SearXNG search behind the offline-first contract.

Single funnel: ALL web acquisition goes through ``search(keywords, settings, *,
use_web_sources)``, whose first lines short-circuit to ``[]`` unless the master
flag (web_sourcing_enabled), the per-run opt-in (use_web_sources) AND a configured
searxng_url are all present — BEFORE any HTTP object is constructed. There is no
module-level HTTP client and no import-time network (deliberately unlike the donor
ForgeOS NetworkGuardian, whose eager module singleton owned an httpx.AsyncClient).

The only place this module touches ``requests`` is ``_http_get()`` — the seam the
offline-first tests monkeypatch to prove zero outbound attempts.

Domain rules (spec B): ``domain_allowed(url, blacklist, allowlist)`` is the shared
rule function — blacklist subtracts (subdomains included), a non-empty allowlist
means allowlist-ONLY mode, and blacklist wins on conflict. It is applied belt-and-
braces: to query construction (never emit blacklisted terms; bias with site:
filters when an allowlist is set) AND to result filtering before the max_sources
cap. The terminal guard at the citation-mint boundary lives in
refinery/citations.py (FG-H3's module) and re-applies the same function.

Adapted from ForgeOS services/backend/app/network.py (Scout/Miner SearXNG client):
async httpx + tenacity -> sync requests + inline retry; the ChromaDB offline
fallback is NOT ported — offline-first means "no sources", not "fetch from a
vector container".
"""
from __future__ import annotations

import time
from typing import List, Optional, Sequence
from urllib.parse import urlparse

import requests


class RawFact(dict):
    """Normalized fact: {title, content, url, kind}."""  # donor network.py L40-41


# ---------------------------------------------------------------------------
# The HTTP seam — the ONLY place requests.* is touched in this module.
# ---------------------------------------------------------------------------

def _http_get(url, params, timeout):
    """Single outbound funnel. Tests monkeypatch this to assert the inert-when-
    disabled contract; nothing else in websource may call requests directly."""
    return requests.get(url, params=params, timeout=timeout)


# ---------------------------------------------------------------------------
# Domain rules (spec B) — shared with the citation-mint boundary in citations.py
# ---------------------------------------------------------------------------

def _registrable_host(url: str) -> str:
    """Lowercased hostname with port (and userinfo) stripped."""
    try:
        return (urlparse(url).hostname or '').lower()
    except ValueError:
        return ''


def _clean_domains(domains: Sequence[str]) -> List[str]:
    return [d.strip().lower().lstrip('.') for d in domains if str(d).strip()]


def domain_allowed(url: str, blacklist: Sequence[str], allowlist: Sequence[str]) -> bool:
    """Blacklist always subtracts (subdomains too, on a dot boundary); a non-empty
    allowlist restricts to itself; a domain in both lists is BLOCKED."""
    host = _registrable_host(url)
    if not host:
        return False
    bl = _clean_domains(blacklist)
    al = _clean_domains(allowlist)
    if any(host == d or host.endswith('.' + d) for d in bl):
        return False
    if al:  # allowlist-only mode
        return any(host == d or host.endswith('.' + d) for d in al)
    return True


def parse_domain_list(raw: str) -> List[str]:
    """One domain per line, as stored by the config page's textareas."""
    return _clean_domains((raw or '').splitlines())


# ---------------------------------------------------------------------------
# Internals — only reachable once search()'s guards have passed.
# ---------------------------------------------------------------------------

def _int_setting(settings, key: str, fallback: int) -> int:
    try:
        return int(str(settings.get(key)).strip())
    except (ValueError, TypeError):
        return fallback


def _wan_viable(settings) -> bool:
    """WAN probe (donor check_viability, httpx->requests). Any failure degrades to
    offline — the caller returns [] rather than raising or falling back elsewhere."""
    probe_url = (settings.get('web_sourcing_probe_url') or '').strip()
    if not probe_url:
        return True  # probe disabled: let the search itself decide
    try:
        probe_timeout = float(str(settings.get('web_sourcing_probe_timeout')).strip())
    except (ValueError, TypeError):
        probe_timeout = 5.0
    try:
        resp = _http_get(probe_url, None, probe_timeout)
        return getattr(resp, 'status_code', 500) < 500
    except Exception:
        return False


def _scrape_keyword(base: str, keyword: str, allowlist: Sequence[str],
                    safesearch: str, per_keyword: int, attempts: int = 3) -> List[dict]:
    """One SearXNG query with a small inline retry (replaces donor tenacity).
    Query construction is the BELT: blacklisted terms are never emitted, and a
    non-empty allowlist biases/restricts via site: filters (best-effort — the
    post-request filter in search() remains the authoritative gate)."""
    query = keyword
    if allowlist:
        query = f"{keyword} {' OR '.join('site:' + d for d in _clean_domains(allowlist))}"
    params = {'format': 'json', 'safesearch': safesearch, 'q': query}
    for attempt in range(attempts):
        try:
            resp = _http_get(f'{base}/search', params, 15.0)
            resp.raise_for_status()
            return list(resp.json().get('results', []))[:per_keyword]
        except Exception:
            if attempt == attempts - 1:
                return []  # this keyword permanently failed; others may still work
            time.sleep(0.5 * (attempt + 1))
    return []


# ---------------------------------------------------------------------------
# The single entry point.
# ---------------------------------------------------------------------------

def search(keywords: Sequence[str], settings, *, use_web_sources: bool) -> List[RawFact]:
    """Fetch permitted web sources for the given keywords, or [] when the feature
    is dark. Guards run FIRST — before any HTTP object exists (spec C):
    effective fetch requires web_sourcing_enabled AND use_web_sources AND a
    configured searxng_url. Offline (probe or query failure) degrades to []."""
    if not (settings.get_bool('web_sourcing_enabled') and use_web_sources):
        return []
    base = (settings.get('searxng_url') or '').strip().rstrip('/')
    if not base:
        return []

    blacklist = parse_domain_list(settings.get('web_sourcing_domain_blacklist'))
    allowlist = parse_domain_list(settings.get('web_sourcing_domain_allowlist'))
    max_sources = _int_setting(settings, 'web_sourcing_max_sources', 6)
    per_keyword = _int_setting(settings, 'web_sourcing_results_per_keyword', 3)
    safesearch = '1' if settings.get_bool('web_sourcing_safe_search') else '0'

    if not _wan_viable(settings):
        return []  # offline-first: no sources, no error, no vector-store fallback

    facts: List[RawFact] = []
    for kw in keywords:
        if len(facts) >= max_sources:
            break
        for r in _scrape_keyword(base, kw, allowlist, safesearch, per_keyword):
            url = r.get('url', '')
            # BRACES: authoritative post-request gate, before the max_sources cap
            # and before any CitationRecord could be minted downstream (spec B.2).
            if not domain_allowed(url, blacklist, allowlist):
                continue
            facts.append(RawFact(
                title=r.get('title', ''),
                content=r.get('content', ''),
                url=url,
                kind='url',
            ))  # donor result->RawFact mapping, network.py L126-134
            if len(facts) >= max_sources:
                break
    return facts
