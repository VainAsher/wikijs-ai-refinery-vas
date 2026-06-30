# Retrieval & progressive context

Each pass is fed a **bounded, safety-filtered** context built from two sources:

1. **Progressive context** — fields the pipeline has accumulated so far (the running
   `PipelineState`): `source_content`, `current_draft`, `classification`,
   `approved_facts`, `assumptions`, `risks`, `target_audience`, `service`,
   `seo_metadata`, …
2. **Retrieval context** — chunks pulled from named collections, ranked and capped.

## ContextBuilder

`refinery/pipeline/context.py` assembles the context string for a pass from its
`progressive_context.include` (minus `exclude`) and its `retrieval.collections`
(capped at `max_chunks`). Two safety rules sit **on top of** the template config:

- **Hard deny floor** — `secrets`, `raw_secrets`, `client_data`, `credentials` are
  **never** included, even if a template asks.
- **Per-pass excludes** — customer-facing passes exclude `raw_source_content`,
  `internal_notes`, etc., so internal material can't leak into customer output.

This is why customer pipelines stay safe: the draft pass sees approved *facts*, not the
raw competitor/employer source, and never the secrets.

## Chunking

`refinery/chunking.py` splits Markdown deterministically: at heading boundaries (tracking
the ancestor heading path), never inside a fenced code block (a `#` inside a fence is not
a heading) or a table, packing blocks up to `max_chars` with an oversized-block-kept-whole
fallback. Each chunk carries a stable `sha256` content hash for idempotent re-indexing.

## RetrievalIndex

`refinery/retrieval.py` indexes a doc (`index_doc` → chunk + store) and searches stored
chunks (`search` → ranked `DocChunk`s). Ranking is **deterministic keyword overlap** by
default, so retrieval works offline and tests never require a model. An optional
`embedder` hook is reserved for a future vector backend — **embeddings are never
required**. `keyword_rank` is also the ContextBuilder `retriever` hook, so when a pass
requests a collection the chunks are ranked against the current draft/source.

The `doc_chunks` table carries a nullable `embedding_json` column so vectors can be added
later without a migration. Until then, deterministic keyword search is the fallback —
exactly as the design requires.
