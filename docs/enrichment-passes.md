# Enrichment passes

A **pass** is one bounded unit of work. It receives the running `PipelineState` and its
`PassConfig`, does deterministic or LLM-optional work, validates, updates the state, and
returns a `PassReport` (status, mode, model, changed, latency, metadata incl. gate
results). Passes live in `refinery/pipeline/passes.py`; the runner calls them in order.

## Execution modes

| Mode | Behaviour |
|---|---|
| `deterministic` | Never calls a model. Pure, repeatable. |
| `llm_optional` | Uses the model if one is configured; otherwise a deterministic fallback. |
| `llm_required` | Needs a model (reserved; current passes are deterministic or optional). |

Every LLM pass is built from a **bounded prompt** (`build_pass_prompt`): the pass id and
purpose, its `allowed_changes` / `forbidden_changes`, the authority rules (VAS canonical
outranks imported evidence; don't copy source wording; don't invent claims; preserve
warnings), the audience/service, the assembled context, the current draft, and the
required output format.

## The pass catalogue

| Pass | Mode | Does |
|---|---|---|
| `clean_markdown` | deterministic | Strip scrape artifacts, normalise headings; preserve code/warnings. |
| `classify` | deterministic | Deterministic classification → governance reasserted into state. |
| `chunk` | deterministic | Heading-aware chunking; records chunk count/hashes. |
| `fact_find` | llm_optional | Extract facts (review candidates) + risks. |
| `draft` | llm_optional | Original VAS draft from approved facts (never copies source). |
| `voice_pass` | llm_optional | Wording/flow/clarity in VAS voice; no new claims, keep warnings. |
| `brand_pass` | llm_optional | Brand alignment; records brand score + violations. |
| `audience_check` | llm_optional | Tune for audience; keep risk warnings, no admin-only steps. |
| `seo_enrichment` | llm_optional | Adds SEO metadata **only** — never rewrites the body. |
| `final_gate` | deterministic | Deterministic gate report; blocks secret leaks. |

Reserved ids (no executor yet, skipped gracefully): `technical_accuracy_check`,
`technical_repair`, `embed_suggestions`, `provenance_attach`, `final_polish`,
`service_registry_extract`, `iac_reference_extract`, `support_macro_generation`.

## Gates (deterministic validators)

Safety is decided by **deterministic code, not the LLM**
(`refinery/pipeline/validators.py`). `evaluate_gates` runs a pass's gates and marks the
**critical** ones — `non_empty_output`, `no_secret_leak`, `source_governance_reasserted`,
`customer_safe` — as blocking; a critical failure stops the run. Others
(`brand_score_min`, `seo_metadata_present`, `human_review_required`, …) are warnings.
Validators reuse the existing scanners/scorers: `scrub_findings`, `brand_compliance`,
the taxonomy, and `reference_source_orgs`.

## Adding a new pass

1. Add the id to `KNOWN_PASS_IDS` in `refinery/pipeline/schema.py` (so templates may use it).
2. Write `def _my_pass(config, state, deps) -> PassReport` in `passes.py` (mutate
   `state`, return a report). For LLM work, build the prompt with `build_pass_prompt`
   and provide a deterministic fallback.
3. Register it in `EXECUTORS`.
4. If it needs a new gate, add a validator to `validators.py` and (if blocking)
   `CRITICAL_GATES`.
5. Add it to a pipeline template and write a test (mock the model — no live calls).
