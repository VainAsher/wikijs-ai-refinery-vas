# Architecture

The refinery is a single-process **FastAPI** application with a **server-rendered** Jinja UI, a **SQLite** store, and an optional dependency on a local **Ollama** server and the **Anthropic** API. It is deliberately small, synchronous, and dependency-light so it can run on a laptop, offline, against ~1,500 documents.

## Module map

| Module | Lines | Responsibility |
|--------|------:|----------------|
| `refinery/app.py` | ~600 | FastAPI app and **all** HTTP routes. Orchestrates imports, transforms, review, publish, and the monitoring pages. Owns `STORE`, `SETTINGS`, `TAXONOMY`, and the data paths. |
| `refinery/core.py` | ~790 | The domain brain — pure-ish logic with no web framework. Taxonomy, the source-governance registry, deterministic + AI-merged classification, confidence, the secret/PII scrubber, variation dials, the brand profile + compliance scorer, content-gap derivation, fact extraction, the Ollama transform, Wiki.js publishing, and Markdown enrichment. |
| `refinery/db.py` | ~190 | `Store`: a thin wrapper over one shared `sqlite3` connection. The `docs` and `runs` tables, idempotent additive migrations, denormalised indexed filter columns, import-key de-duplication, counters/breakdowns, and service coverage. |
| `refinery/jobs.py` | ~110 | In-memory background-job registry powering the live progress tray. Thread-safe; ephemeral by design. |
| `refinery/settings.py` | ~130 | Layered runtime settings (saved → env → default) with **Fernet encryption** of secret fields at rest. |
| `refinery/refine.py` | ~80 | Optional Claude cloud "reroll" via the official `anthropic` SDK, with model pricing and a token/cost estimate. |
| `refinery/connectors/` | — | Pluggable source connectors (`local_markdown`, `zendesk`, `mediawiki`, `clickup`, `gdocs`), each yielding `SourceDoc`s. |
| `refinery/pipeline/` | — | **v2 multi-pass enrichment pipeline**: `schema` (PassConfig/PipelineConfig + YAML loader), `state` (PipelineState/PassReport), `context` (ContextBuilder + safety filtering), `passes` (executors + run_pass), `validators` (deterministic gates), `runner` (run_pipeline → governed draft), `service` (run_and_persist). |
| `refinery/chunking.py` · `refinery/retrieval.py` | — | Deterministic Markdown chunking and the keyword/optional-embedding retrieval index that feed pipeline context. |
| `refinery/templates/` | — | Jinja templates extending `base.html` (theme tokens, light/dark, the progress-tray poller), incl. the pipeline pages. |
| `refinery_cli.py` | — | Headless `import` / `export` / `publish` plus `pipeline` / `chunk` / `index` for scripting and CI. |
| `taxonomy.yml` | — | The controlled vocabularies the classifier and UI dropdowns validate against. |

## Data model

Two dataclasses in `core.py` carry everything:

- **`SourceDoc`** — a raw imported document: `title`, `content`, `source` (the import label), `source_id`, `source_url`, `original_updated_at`, `raw_metadata`. Connectors yield these; nothing about governance is decided yet.
- **`Classification`** — the rich governance + metadata record attached to every stored doc. Key fields:
  - **Governance**: `source_org`, `source_role`, `reuse_policy`, `adaptation_action`, `rewrite_status`, `authority`, `canonical`, `customer_safe`.
  - **Classification**: `service`, `doc_type`, `domain`, `audience`, `risk_level`, `contains_pii`, `contains_secrets`, `tags`.
  - **Signals**: `confidence` (0–1, computed), `brand_score` (0–100, −1 = unscored), `reasons` (human-readable trace).
  - **Lineage**: `transform_source_doc_id`, `transform_notes`, `canonical_target`.

### How a document is stored

A `docs` row = the `SourceDoc` fields **+** the full `Classification` serialised to `classification_json` **+** five **denormalised, indexed columns** (`source_org`, `service`, `doc_type`, `rewrite_status`, `authority`) so the queue filters hit an index instead of scanning JSON **+** an `import_key` (SHA-1 of `source::source_id`, used for idempotent re-import) **+** `wiki_path`, `published`, `publish_message`, and timestamps.

A second table, **`runs`**, records each AI transform (model, dials JSON, brand score, latency) for the History and Monitor telemetry.

## Request lifecycle (a transform, end to end)

```
POST /docs/{id}/transform
  └─ load doc + Classification from Store
  └─ read_context_packs(selected) ──────────────► VAS context text (higher authority than source)
  └─ normalise_dials(form) ─────────────────────► tone/length/citation directives
  └─ transform_to_vas(source, c, target, model, url, context, dials)
        ├─ if Ollama model set → ollama_json(prompt) → draft JSON
        └─ else → deterministic safe-fallback draft template
  └─ deterministic_classify(draft) ─────────────► new Classification for the draft
        └─ source_governance() forces source_org=vainasherstudios / owned
  └─ brand_compliance(draft, brand.yaml, model) ► brand_score + violations
  └─ Store.add_doc(draft) ──────────────────────► new queue row
  └─ Store.add_run(...) ────────────────────────► telemetry row
  └─ 303 redirect → /docs/{new_id}
```

The fact-gated variant (`/transform/prepare` → gate → `/transform/commit`) inserts a human checkpoint: `extract_facts` proposes keywords + claims, the operator edits them, and the approved set is injected as **authoritative** context before drafting.

## The classification pipeline (`deterministic_classify`)

Deterministic first; AI only refines, and governance always wins.

1. **`infer_source_org`** — the import label is authoritative (`label in SOURCE_REGISTRY` → that org); otherwise fall back to content sniffing. (Brand aliases were deliberately anonymised to generic slugs, so detection is now label-driven.)
2. **`source_governance`** — looks the org up in `SOURCE_REGISTRY` and stamps `source_role` / `reuse_policy` / `adaptation_action` / `rewrite_status`. Reference orgs are forced **non-canonical, `imported_unreviewed`, not customer-safe**.
3. **Service scoring** — brand tokens are stripped from the text, then each service is scored by keyword hits and the strongest wins (a vendor tool's own docs use the source label as the service).
4. **Doc type / audience / risk** — keyword heuristics.
5. **`scan_sensitive`** — sets `contains_pii` / `contains_secrets`.
6. **`compute_confidence`** — a 0–1 score from real signal (authoritative label, keyword-hit strength, resolved doc type, content length), surfaced as a pill in the queue and as a `reason`.
7. **`suggest_canonical_target`** — proposes the Wiki.js path the rewrite should live at.

When an Ollama model is supplied, **`merge_ai_classification`** validates each AI-suggested field against `taxonomy.yml`, keeps only valid values, then **re-runs `source_governance`** — so the AI can enrich tags/summaries but can never escalate a reference doc to canonical.

## Concurrency model

- FastAPI runs sync endpoints on a threadpool. Long-running work (bulk import, connector pulls, bulk metadata updates) is dispatched to a **daemon thread** via `JOBS.run(...)`, so the POST returns immediately (303) and the browser never blocks.
- `Store` opens its SQLite connection with `check_same_thread=False` and serialises **writes** behind a `threading.Lock`, so a background import and a foreground click can't corrupt each other.
- The progress tray polls `GET /jobs/active` (~1.2 s while a job runs, ~5 s idle). Job state is process-local and intentionally ephemeral — a restart clears it (the worker thread is gone too).

## External dependencies (all optional)

| Dependency | Used for | Absent behaviour |
|------------|----------|------------------|
| **Ollama** (local) | AI classification + richer transforms | Deterministic classification + safe fallback draft template. |
| **Anthropic API** | "Refine with Claude" cloud reroll | Panel shows a friendly "not configured" note; everything else works. |
| **Wiki.js** | Publishing approved docs | Use `/export` to write governed Markdown to disk instead. |
| `cryptography` | Encrypting secrets at rest | Falls back to plaintext storage (with the secret still masked in the UI). |

See [governance.md](governance.md) for the source registry and document-state machine; the data model and store schema are documented above.
