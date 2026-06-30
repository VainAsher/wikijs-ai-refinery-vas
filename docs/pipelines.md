# Enrichment pipelines

A **pipeline** turns governed source evidence into a VainAsherStudios **draft** through
an ordered sequence of bounded **passes**. It is the v2 evolution of the single-shot
transform: instead of one prompt, a document flows through
`clean → classify → chunk → fact-find → draft → voice → brand → audience → SEO → final gate`,
accumulating structured context as it goes.

The core rule is unchanged: **imported third-party content is evidence, not truth.**
A pipeline never republishes source material and never auto-publishes. Its output is
always a draft with `review_status: needs_review`, `customer_safe: false`,
`canonical: false`, owned by `vainasherstudios` — ready for human review.

## Running a pipeline

**From the UI** — open a document, expand **Run enrichment pipeline**, pick a template,
target action, audience, and service (optionally an Ollama model), and run. You land on
the generated draft. The **Pipelines** tab lists templates and every run; each run page
shows per-pass status and gate results.

**From the CLI** (works without Ollama — deterministic fallbacks):

```bash
python refinery_cli.py pipeline list
python refinery_cli.py pipeline run --pipeline customer_guide_pipeline --doc-id 123 \
    --service business_email --audience customer --model mistral:latest
python refinery_cli.py chunk --doc-id 123     # store a doc's chunks
python refinery_cli.py index --doc-id 123     # same — index for retrieval
```

## What gets persisted

Each run records a `pipeline_runs` row (status, service/audience, final state JSON, the
new draft id), one `pass_runs` row per pass (status, mode, model, report, latency), a
`doc_lineage` row linking source → draft, and the draft's `doc_chunks`. The original
`runs` table (single transforms) is untouched.

## Templates

Pipelines are plain YAML in `pipeline_templates/`. The seed is
[`customer_guide.yml`](../pipeline_templates/customer_guide.yml). A template is:

```yaml
id: customer_guide_pipeline
name: Customer Guide Pipeline
description: Produce a customer-safe guide from governed source evidence.
passes:
  - id: clean_markdown        # must be a known pass id (see enrichment-passes.md)
    stage: preprocess
    mode: deterministic       # deterministic | llm_optional | llm_required
    allowed_changes: [normalise_headings, preserve_code_blocks]
    forbidden_changes: [remove_warnings, add_new_claims]
    progressive_context: {include: [source_content], exclude: []}
    retrieval: {collections: [], max_chunks: 0}
    gates: [non_empty_output]
  # ... more passes ...
```

Templates are validated on load: a missing id, empty `passes`, an unknown pass id, or an
invalid mode raises a clear `PipelineConfigError`. To add a template, drop a new `.yml`
in the folder — it appears in the UI and CLI immediately (no restart).

See **[enrichment-passes.md](enrichment-passes.md)** for the pass catalogue and how to add
one, and **[retrieval-context.md](retrieval-context.md)** for how each pass is fed context.
