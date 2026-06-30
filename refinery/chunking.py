"""Deterministic Markdown chunking (v2 enrichment-pipeline foundation).

Splits a Markdown document into ordered chunks for retrieval/indexing and per-pass
context. It is intentionally deterministic and offline — no model, no embeddings:

- chunks at heading boundaries, tracking the heading path (ancestor headings);
- never splits inside a fenced code block (and never treats ``# `` inside a fence as
  a heading) or inside a table;
- packs blocks up to ``max_chars`` and falls back to a sliding window for long
  sections (a single oversized block, e.g. a huge code block, is kept whole);
- emits a stable ``content_hash`` per chunk so re-indexing is idempotent.
"""
from __future__ import annotations
import dataclasses, hashlib, re
from typing import List

_HEADING = re.compile(r'^(#{1,6})\s+(.*\S)\s*$')


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token); good enough for budgeting context."""
    return max(0, len(text or '') // 4)


@dataclasses.dataclass
class DocChunk:
    doc_id: int
    chunk_index: int
    heading_path: List[str]            # ancestor headings, outermost first
    content: str
    content_hash: str
    token_estimate: int

    def to_dict(self) -> dict:
        return {'doc_id': self.doc_id, 'chunk_index': self.chunk_index,
                'heading_path': list(self.heading_path), 'content': self.content,
                'content_hash': self.content_hash, 'token_estimate': self.token_estimate}


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _split_sections(content: str):
    """Yield (heading_path, body_text) sections, splitting on real headings only
    (headings inside fenced code blocks are ignored). Preamble before the first
    heading is a section with an empty heading_path."""
    lines = content.splitlines()
    stack: List[tuple] = []          # (level, text)
    cur_path: List[str] = []
    buf: List[str] = []
    in_fence = False
    fence_tok = ''

    def flush(path):
        text = '\n'.join(buf).strip('\n')
        return (list(path), text)

    sections = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith('```') or stripped.startswith('~~~'):
            tok = stripped[:3]
            if not in_fence:
                in_fence, fence_tok = True, tok
            elif stripped.startswith(fence_tok):
                in_fence = False
            buf.append(line)
            continue
        m = None if in_fence else _HEADING.match(line)
        if m:
            # Close the current section before starting the new heading.
            if buf:
                sections.append(flush(cur_path))
                buf = []
            level, text = len(m.group(1)), m.group(0).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            cur_path = [t for _, t in stack]
            buf.append(line)
        else:
            buf.append(line)
    if buf:
        sections.append(flush(cur_path))
    return [s for s in sections if s[1].strip()]


def _blocks(text: str) -> List[str]:
    """Split a section body into atomic blocks that must never be split:
    fenced code blocks, contiguous table rows, and blank-line-separated paragraphs."""
    lines = text.splitlines()
    out: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.lstrip()
        if s.startswith('```') or s.startswith('~~~'):
            tok = s[:3]
            buf = [line]; i += 1
            while i < n:
                buf.append(lines[i])
                if lines[i].lstrip().startswith(tok):
                    i += 1; break
                i += 1
            out.append('\n'.join(buf)); continue
        if '|' in line and line.strip():                 # keep table rows together
            buf = [line]; i += 1
            while i < n and '|' in lines[i] and lines[i].strip():
                buf.append(lines[i]); i += 1
            out.append('\n'.join(buf)); continue
        if not line.strip():
            i += 1; continue                              # drop blank separators
        buf = [line]; i += 1                              # paragraph
        while i < n and lines[i].strip() and '|' not in lines[i] \
                and not lines[i].lstrip().startswith(('```', '~~~')):
            buf.append(lines[i]); i += 1
        out.append('\n'.join(buf))
    return out


def chunk_markdown(content: str, doc_id: int = 0, max_chars: int = 2000) -> List[DocChunk]:
    """Chunk Markdown into ordered DocChunks. Empty/whitespace input yields []."""
    if not content or not content.strip():
        return []
    chunks: List[DocChunk] = []
    idx = 0
    for heading_path, body in _split_sections(content):
        if len(body) <= max_chars:
            pieces = [body]
        else:
            # Pack atomic blocks up to max_chars; an oversized block stays whole.
            pieces, cur = [], ''
            for blk in _blocks(body):
                if cur and len(cur) + len(blk) + 2 > max_chars:
                    pieces.append(cur); cur = blk
                else:
                    cur = blk if not cur else cur + '\n\n' + blk
            if cur:
                pieces.append(cur)
        for piece in pieces:
            piece = piece.strip('\n')
            if not piece.strip():
                continue
            chunks.append(DocChunk(doc_id=doc_id, chunk_index=idx, heading_path=heading_path,
                                   content=piece, content_hash=_content_hash(piece),
                                   token_estimate=estimate_tokens(piece)))
            idx += 1
    return chunks
