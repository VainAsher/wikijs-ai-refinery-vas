"""Retrieval / indexing layer (deterministic-first, embeddings optional).

Indexing chunks a doc (via refinery.chunking) and stores the chunks. Search ranks
stored chunks against a query. The default ranking is deterministic keyword overlap so
everything works offline and in tests; an embedding function can be supplied later
without changing callers. ``keyword_rank`` is also the drop-in ``retriever`` hook for
ContextBuilder (ranks an in-memory list of chunk strings).
"""
from __future__ import annotations
import json, re
from typing import Any, Callable, Dict, List, Optional

from refinery.chunking import DocChunk, chunk_markdown

_TERM = re.compile(r'[a-z0-9]{3,}')
_STOP = set('the and for with that this from your you are not was has have will into over under '
            'how what when where which who why can use using used an of to in on at by or'.split())


def _terms(text: str) -> set:
    return {w for w in _TERM.findall((text or '').lower()) if w not in _STOP}


def _overlap(query_terms: set, text: str) -> int:
    if not query_terms:
        return 0
    text_terms = _terms(text)
    return sum(1 for t in query_terms if t in text_terms)


def keyword_rank(query: str, chunks: List[str], limit: int = 8) -> List[str]:
    """Rank in-memory chunk strings by keyword overlap (deterministic). Ties keep input
    order (stable sort). Used as the ContextBuilder retriever hook."""
    qt = _terms(query)
    ranked = sorted(chunks, key=lambda c: -_overlap(qt, c))
    return ranked[:limit] if limit else ranked


class RetrievalIndex:
    """Store-backed chunk index. ``embedder`` is an optional callable reserved for a
    future vector backend; when None (the default) search uses deterministic keyword
    ranking — never required for tests, always available offline."""

    def __init__(self, store, embedder: Optional[Callable[[str], Any]] = None):
        self.store = store
        self.embedder = embedder

    def index_doc(self, doc_id: int, content: str) -> List[DocChunk]:
        chunks = chunk_markdown(content, doc_id=doc_id)
        self.store.replace_doc_chunks(doc_id, chunks)
        return chunks

    def _candidate_rows(self, filters: Optional[Dict[str, Any]]) -> List[Any]:
        filters = filters or {}
        if filters.get('doc_id'):
            return list(self.store.conn.execute(
                'SELECT * FROM doc_chunks WHERE doc_id=? ORDER BY chunk_index', (int(filters['doc_id']),)))
        if filters.get('doc_ids'):
            ids = list(filters['doc_ids'])
            ph = ','.join('?' * len(ids))
            return list(self.store.conn.execute(
                f'SELECT * FROM doc_chunks WHERE doc_id IN ({ph}) ORDER BY doc_id, chunk_index', ids))
        if filters.get('source_org'):
            return list(self.store.conn.execute(
                'SELECT dc.* FROM doc_chunks dc JOIN docs d ON d.id=dc.doc_id WHERE d.source_org=?',
                (filters['source_org'],)))
        return list(self.store.conn.execute('SELECT * FROM doc_chunks ORDER BY doc_id, chunk_index LIMIT 5000'))

    def search(self, query: str, filters: Optional[Dict[str, Any]] = None, limit: int = 8) -> List[DocChunk]:
        qt = _terms(query)
        scored = []
        for r in self._candidate_rows(filters):
            score = _overlap(qt, r['content'])
            if score > 0:
                scored.append((score, DocChunk(doc_id=r['doc_id'], chunk_index=r['chunk_index'],
                                                heading_path=json.loads(r['heading_path_json'] or '[]'),
                                                content=r['content'], content_hash=r['content_hash'],
                                                token_estimate=r['token_estimate'])))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:limit]]
