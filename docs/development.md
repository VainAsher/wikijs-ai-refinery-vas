# Development

## Running

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn refinery.app:app --host 127.0.0.1 --port 8000
```

`--reload` works but, on Windows, the file-watcher reloader has been observed leaving orphaned processes holding the port. If a fresh start "serves stale code", check for a leftover `uvicorn` process on port 8000 and kill it, or run without `--reload` and restart manually.

## Tests

```powershell
python -m pytest -q
```

`tests/conftest.py` points the app at an isolated `REFINERY_DATA`, so tests never touch a real store and need neither Ollama nor Wiki.js. Coverage:

| File | Covers |
|------|--------|
| `tests/test_core.py` | classification, governance re-assertion, confidence, the scrubber/redaction, dials, brand compliance, gap derivation, fact extraction, slugify, transforms. |
| `tests/test_db.py` | store CRUD, dedup, idempotent migration/backfill, indexed filters, counters/breakdowns, run history. |
| `tests/test_settings.py` | settings precedence, **secret encryption round-trip**, legacy-plaintext compatibility, masking. |
| `tests/test_app.py` | endpoint smoke tests, the background-job progress feed, the redaction-gate flow, the fact-gate flow. |
| `tests/test_refine.py` | Claude reroll defaults/pricing and graceful no-key failure (no live API call). |

Tests for the asynchronous import/bulk endpoints use a `_wait_for_jobs(client)` helper that polls `/jobs/active` until the background worker finishes.

## Project layout

```
refinery/
  app.py            FastAPI app + all routes
  core.py           domain logic (classification, governance, transforms, brand, gaps, …)
  db.py             SQLite Store (docs + runs)
  jobs.py           background-job registry (progress tray)
  settings.py       layered settings + secret encryption
  refine.py         optional Claude reroll
  connectors/       source connectors (local_markdown, zendesk, mediawiki, clickup, gdocs)
  templates/        Jinja UI (base.html + 11 pages)
refinery_cli.py     headless import/export/publish
taxonomy.yml        controlled vocabularies
tests/              pytest suite
docs/               this living documentation
```

Mutable state (`data/`) and secrets are git-ignored; the repo ships data-free and self-seeds.

## Headless CLI

`refinery_cli.py` mirrors the web import/export/publish for scripting/CI:

```powershell
# import
python refinery_cli.py import --connector local_markdown --local-path C:\docs\raw --source-label employer_hosting --limit 0
python refinery_cli.py import --connector zendesk --zendesk-url help.example.com --limit 50

# export reviewed docs to Markdown (with front-matter)
python refinery_cli.py export --status reviewed --output data\export

# publish reviewed docs to Wiki.js
python refinery_cli.py publish --status reviewed --wikijs-url $env:WIKIJS_URL --wikijs-token $env:WIKIJS_TOKEN
```

## Extending the system

### A new reference source / tool

- Reference org: add an entry to `SOURCE_REGISTRY` (`core.py`) + a line in `taxonomy.yml → source_orgs`.
- Managed tool docs: add a line to `MANAGED_SERVICE_DOC_ORGS` (`core.py`). The slug doubles as the `service`.

No conditional/`if-elif` changes are needed — the registry drives governance.

### A new connector

Subclass `Connector` (`refinery/connectors/base.py`), implement `fetch(limit) -> Iterable[SourceDoc]`, declare `name` and `required_config`, and register it in `connectors/__init__.py → CONNECTORS`. It then appears in the `/connectors` UI and the CLI automatically.

### A new service / doc type / transform target

Add the value to the relevant list in `taxonomy.yml` (and add keyword hints to the `services` dict in `deterministic_classify` if you want auto-detection). Transform targets are the `rewrite_into_*` entries in `adaptation_actions`.

### A new context pack

Drop a Markdown file into `data/vas_context/` (or add it to the `ensure_default_contexts()` defaults so fresh clones get it). It then appears as a selectable pack on the transform form.

### A new variation dial

Add it to `DIALS_DEFAULTS` / `DIAL_OPTIONS` (`core.py`), render it in the transform form, thread it through the `transform_doc` form params, and reference it in `dials_directives`.

### A new pipeline pass or template

- **Pass:** add the id to `KNOWN_PASS_IDS` (`pipeline/schema.py`), write `_my_pass(config, state, deps) -> PassReport` in `pipeline/passes.py` (deterministic, or LLM via `build_pass_prompt` with a deterministic fallback), register it in `EXECUTORS`, and add any new gate to `pipeline/validators.py` (and `CRITICAL_GATES` if blocking). Test with a mocked model — no live calls.
- **Template:** drop a `.yml` in `pipeline_templates/`; it's validated on load and appears in the UI and CLI immediately. See [pipelines.md](pipelines.md) and [enrichment-passes.md](enrichment-passes.md).

## Conventions

- Match the surrounding style: synchronous FastAPI handlers, raw `sqlite3` (no ORM), dense one-line route bodies in `app.py`, fuller documented functions in `core.py`.
- Long-running work goes through `JOBS.run(...)` so the request returns immediately and the progress tray tracks it.
- Anything that calls an AI model must keep governance deterministic: validate AI output against `taxonomy.yml` and let `source_governance()` have the final word.
- New behaviour gets a test; the suite is the contract.
