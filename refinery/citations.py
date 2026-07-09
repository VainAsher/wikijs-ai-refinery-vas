"""Citation records + the terminal domain guard (FG-H5 / FG-H3 shared boundary).

FG-H5 hands FG-H3 only already-permitted RawFacts (websource.search() filters
post-request), but the "a blacklisted domain can NEVER appear in
verified_citations" guarantee is enforced HERE, at the point CitationRecords are
minted — so even a fact that bypassed the upstream filter cannot mint a citation
(spec B point 3, defense in depth).

Chosen boundary API (note for FG-H3): ``mint_citations(facts, blacklist,
allowlist)`` — filter + mint in one call, sequential SRC-### ids over the
permitted facts only. FG-H3's claim-id validation / verified_citations
frontmatter builder should thread citations through this function (or at minimum
re-use ``domain_allowed`` from refinery.websource) rather than minting records
directly from raw facts.

CitationRecord and to_citation() are ported from ForgeOS (schemas.py L15-19,
network.py L242-249); pydantic BaseModel -> stdlib dataclass to match Refinery's
house style (SourceDoc etc.), and the fact's URL may live under 'url' (Refinery
RawFact) or 'source' (donor shape) — both accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from refinery.websource import domain_allowed


@dataclass
class CitationRecord:
    id: str
    source_name: str
    local_path: Optional[str] = None
    url: Optional[str] = None


def _get(fact, key: str, default=''):
    """Facts may arrive as dicts (RawFact) or small objects; accept either."""
    if isinstance(fact, dict):
        return fact.get(key, default)
    return getattr(fact, key, default)


def _fact_location(fact) -> str:
    """URL (or local path) of a fact: Refinery RawFacts use 'url', the donor
    shape used 'source'."""
    return _get(fact, 'url') or _get(fact, 'source') or ''


def to_citation(idx: int, fact) -> CitationRecord:
    """Donor NetworkGuardian.to_citation (network.py L242-249)."""
    kind = _get(fact, 'kind', 'url') or 'url'
    location = _fact_location(fact)
    return CitationRecord(
        id=f'SRC-{idx:03d}',
        source_name=_get(fact, 'title') or 'Unknown source',
        local_path=location if kind == 'local' else None,
        url=location if kind == 'url' else None,
    )


def mint_citations(facts: Sequence, blacklist: Sequence[str],
                   allowlist: Sequence[str]) -> List[CitationRecord]:
    """The TERMINAL guard: only facts from permitted domains mint citations.
    Re-applies domain_allowed even though websource.search() already filtered,
    so an upstream bypass can never place a blocked domain in
    verified_citations. Local-kind facts (no domain) pass through untouched —
    the domain rules govern web sources only."""
    minted: List[CitationRecord] = []
    for fact in facts:
        kind = _get(fact, 'kind', 'url') or 'url'
        if kind != 'local' and not domain_allowed(
                _fact_location(fact), blacklist, allowlist):
            continue
        minted.append(to_citation(len(minted) + 1, fact))
    return minted
