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
from typing import List, Optional, Sequence, Tuple

from refinery.websource import domain_allowed


@dataclass
class CitationRecord:
    id: str
    source_name: str
    local_path: Optional[str] = None
    url: Optional[str] = None


@dataclass
class FactBlock:
    """A single attributed claim (donor: forgeos schemas.py L22-27, pydantic ->
    stdlib dataclass per the CitationRecord precedent). citation_id refers to a
    minted CitationRecord.id (SRC-###)."""
    claim: str
    citation_id: str


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


# ---------------------------------------------------------------------------
# FG-H3: source attribution + the Auditor validation discipline.
# ---------------------------------------------------------------------------

def _local_source_fact(doc) -> dict:
    """Render the local source doc as a local-kind fact so it mints a citation
    through the same mint_citations boundary as web facts. The location lands
    under 'source' (donor RawFact shape) -> CitationRecord.local_path."""
    source_id = getattr(doc, 'source_id', '') or ''
    location = f'doc:{source_id}' if source_id else (getattr(doc, 'source', '') or 'local')
    return {'title': getattr(doc, 'title', '') or 'Local source',
            'content': getattr(doc, 'content', '') or '',
            'kind': 'local', 'source': location}


def attribute_facts(doc, web_facts: Sequence = (), blacklist: Sequence[str] = (),
                    allowlist: Sequence[str] = (), model: Optional[str] = None,
                    ollama_url: str = 'http://localhost:11434/api/generate',
                    local_claims: Optional[Sequence[str]] = None,
                    ) -> Tuple[List[FactBlock], List[CitationRecord]]:
    """Extract claims WITH source attribution (donor Auditor, agents.py L128-192,
    adapted to the sync llm-optional extract_facts idiom: deterministic when
    model is None).

    The local source doc mints SRC-001 (local kind); permitted web facts mint
    sequential url-kind citations. ALL records come from mint_citations, so the
    terminal domain guard applies — a blocked-domain fact never mints and never
    receives claims. Every returned FactBlock cites a minted citation.

    ``local_claims`` lets a caller that already ran extract_facts reuse those
    claims instead of extracting twice.
    """
    from refinery.core import extract_facts  # deferred: keep module deps one-way

    facts = [_local_source_fact(doc)] + list(web_facts or [])
    minted = mint_citations(facts, blacklist, allowlist)

    fact_blocks: List[FactBlock] = []
    k = 0  # cursor into minted (mint_citations preserves fact order)
    for fact in facts:
        kind = _get(fact, 'kind', 'url') or 'url'
        if kind != 'local' and not domain_allowed(
                _fact_location(fact), blacklist, allowlist):
            continue  # not minted by the terminal guard -> may not be cited
        cit = minted[k]
        k += 1
        if kind == 'local':
            claims = list(local_claims) if local_claims is not None else \
                extract_facts(doc, model, ollama_url).get('facts', [])
        else:
            # Deterministic attribution: the fact's own content is the claim
            # source, bound to ITS citation (donor Auditor digest semantics).
            content = str(_get(fact, 'content') or '').strip()
            claims = [content] if content else []
        fact_blocks.extend(FactBlock(claim=str(c).strip(), citation_id=cit.id)
                           for c in claims if str(c).strip())
    return fact_blocks, minted


def _block_id(fb) -> str:
    return _get(fb, 'citation_id', '') or ''


def _record_id(c) -> str:
    return _get(c, 'id', '') or ''


def validate_claims(fact_blocks: Sequence, citations: Sequence) -> Tuple[list, list]:
    """Auditor discipline (donor agents.py L165-181): a claim is VERIFIED only if
    its citation_id exists in the minted set; everything else is returned in the
    rejected list — flagged for reviewers, never silently kept or dropped.
    Accepts FactBlock/CitationRecord objects or their asdict() dicts."""
    valid_ids = {_record_id(c) for c in citations}
    verified = [fb for fb in fact_blocks if _block_id(fb) in valid_ids]
    rejected = [fb for fb in fact_blocks if _block_id(fb) not in valid_ids]
    return verified, rejected


def build_verified_citations(fact_blocks: Sequence, citations: Sequence) -> List[dict]:
    """verified_citations block (donor exporter.py build_frontmatter L36-58):
    only citations referenced by VALIDATED claims, as JSON-serialisable dicts of
    {id, source_name, url|local_path}. The donor's ``or citations`` fallback is
    deliberately NOT ported — an unreferenced source is not verified."""
    verified, _ = validate_claims(fact_blocks, citations)
    used_ids = {_block_id(fb) for fb in verified}
    block: List[dict] = []
    for c in citations:
        if _record_id(c) not in used_ids:
            continue
        entry = {'id': _record_id(c), 'source_name': _get(c, 'source_name', '')}
        local_path = _get(c, 'local_path', None)
        url = _get(c, 'url', None)
        if local_path:
            entry['local_path'] = local_path
        if url:
            entry['url'] = url
        block.append(entry)
    return block
