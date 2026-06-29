# User guide

This is the page-by-page reference and the end-to-end workflows. For the *why* behind the rules, read [governance.md](governance.md).

## The workflow in six steps

```
1 Import   2 Classify   3 Triage   4 Transform   5 Review   6 Publish
```

1. **Import** — Bulk Workbench (many local dirs) or Connectors (one-off) pull raw docs into the queue. Runs as a background job with a live progress bar.
2. **Classify** — each doc is auto-tagged with source governance, service, doc type, audience, risk, sensitivity, and a confidence score.
3. **Triage** — filter the queue; use Bulk to set actions on whole groups.
4. **Transform** — rewrite a reference doc into an original VAS draft (AI optional; dials + optional fact gate).
5. **Review** — edit, redact, brand-score, optionally Claude-refine, then approve or mark canonical.
6. **Publish** — push approved docs to Wiki.js, or export governed Markdown to disk.

---

## Docs queue (`/`)

The in-flight review queue and home page.

- **Stat tiles** double as one-click filters (Total, Needs review, Reviewed, VAS drafts, Needs rewrite, Published).
- **Filters**: free-text search (title + body), status, and an advanced row for source org, service, doc type, rewrite status, authority, and page size. Active advanced filters expand automatically.
- **Each row** shows the title, source governance pills (org · role · reuse policy), classification pills (doc type · service · audience · risk · **confidence %**), status, the target Wiki path, and quick **Open / Approve** actions.
- The **confidence pill** is colour-coded (green ≥ 75%, plain ≥ 50%, amber below). Sort your attention to the low-confidence docs first — they're the ones the classifier was unsure about.

## Bulk Workbench (`/bulk`)

The fastest way to handle a large import.

**Step 1 — Import source directories.** One directory per line as `source_label|path`:

```
employer_hosting|C:\docs\raw\employer
competitor_hosting_1|C:\docs\raw\competitor_a
authentik|C:\docs\raw\authentik
```

The label becomes the `source_org` and drives governance (see [governance.md](governance.md)). Use limit `0` to import every `.md` file (recursively). Leave the Ollama box empty for a fast deterministic first pass. Re-importing is safe — existing docs are refreshed, not duplicated.

**Step 2 — Batch-update a filtered slice (collapsed/advanced).** Pick a slice with the filters, then set an adaptation action / rewrite status / review status / tag on the whole slice in one go — ideal for tagging obvious groups across hundreds of docs.

Both actions run in the background; watch the **progress tray** (bottom-right) and click **View results** when done.

## Connectors (`/connectors`)

One-off imports from a single source. Available connectors:

| Connector | Pulls from | Key config |
|-----------|-----------|------------|
| `local_markdown` | Local `.md` files | folder path(s), or `label|path` mappings |
| `zendesk` | A Zendesk Help Center | Help-Center URL (public articles API) |
| `mediawiki` | A MediaWiki site | API URL, optional session cookie, namespace |
| `clickup` | ClickUp Docs | API token, workspace id |
| `gdocs` | Google Drive folder | folder id + service-account `credentials.json` |

All connectors convert source HTML to Markdown and yield the same `SourceDoc` shape, so everything downstream treats them identically.

## Context library (`/context`)

The **context packs** are Markdown documents injected into AI rewrites as **higher authority than the source**, so transformed drafts follow VAS voice, services, and rules. The defaults (seeded on first run, derived from the VainOS BrandOS):

`brand_manifesto` · `brand_voice` (layered: clarity for SOPs, full noir voice for content) · `visual_identity` · `service_catalogue` · `privacy_and_data_rules` · `technical_stack_iac` · `gaming_community_ops` · `moderator_training_standards` · `content_channels_strategy` · `platform_minecraft_project_zomboid_rust`.

Click a pack to load it into the editor; create new packs with the form. You pick which packs to inject per transform on the doc editor.

## Document editor (`/docs/{id}`)

Where a single document is reviewed and re-authored. Sections:

- **Essentials / Classification / Source rights** — edit any metadata; changing `source_org` re-applies governance on save.
- **Markdown editor** — edit tab + live preview tab.
- **Actions** — **Approve** (reviewed → approved), **Mark canonical** (the VAS source of truth), **Reject/archive**, **Publish to Wiki.js**, **Check brand voice** (re-score on demand; shows a `brand N/100` pill).
- **Sensitive content gate** (appears when secrets/PII are detected) — a table of findings with critical/high pre-selected; **Redact selected** replaces the matches with `[REDACTED:kind]` and refreshes the flags.
- **Transform into a VAS-owned draft** — the rewrite engine (see below).
- **Refine with Claude** — optional cloud reroll (see below).
- **Why it was classified this way** — the classifier's reasoning trace.

### Transforming a reference doc

In the Transform section:

1. Pick a **Target** (`rewrite_into_sop`, `rewrite_into_moderation_playbook`, `rewrite_into_youtube_script`, …).
2. Optionally set an **Ollama model** (blank = a safe template draft).
3. Open **Variation dials** to tune tone, audience, length, citation strictness, emoji policy, reading grade, and call-to-action.
4. Tick the **context packs** to inject.
5. Add **extra one-off context** if needed.
6. Either **Generate draft** (direct) or **Prepare with fact gate**.

The draft is created as a **new** queue document (it never marks the source canonical), brand-scored automatically, and logged to History.

### The fact gate (`Prepare with fact gate`)

A staged transform with a human checkpoint:

1. The refinery extracts candidate **keywords** and **facts** from the source.
2. You review and **edit** them — delete anything you can't confirm.
3. **Accept facts & generate draft** drafts using *only* the facts you approved (injected as authoritative). The draft is tagged `fact-gated`.

### Refine with Claude (optional cloud reroll)

If the `anthropic` SDK is installed and an Anthropic key is configured (Config page), this panel polishes the current content with a Claude model:

- Pick a model (`claude-opus-4-8` default, or Sonnet 4.6 / Haiku 4.5) — pricing per million tokens is shown.
- Add optional instructions.
- The document's input-token estimate is shown up front; **actual** tokens + cost are reported after the run. On success the content is replaced, re-brand-scored, and tagged `claude-refined`.

## Monitor (`/monitor`)

Pipeline health at a glance: queue counts, the rewrite-pipeline funnel, VAS-owned count, Ollama/Wiki.js/DB status, governance **breakdowns** by field, and the **transform telemetry** panel (count, avg latency, avg brand score, model usage). Links to Transform history.

## Gaps (`/gaps`)

Content-gap analysis so you know **what to forge next**. For each service it derives:

- **rewrite_backlog** — reference docs exist but no VAS-owned draft (highest value).
- **no_coverage** — zero docs for the service.
- **shallow** — only 1–2 docs.

Each gap links straight to the filtered queue; a full owned-vs-reference coverage table sits below.

## History (`/history`)

Every AI transform run, newest first: source → draft, target, model (or "template"), the dials used, the brand score, and latency. Use it to compare models and settings before committing to a bulk run.

## Config (`/config`)

- **Ollama URL** with an **Auto-detect** button (probes Docker + localhost) and a **model dropdown** populated from the live server.
- **Wiki.js GraphQL URL** + token.
- **Anthropic API key** — enables the Claude reroll.
- Tokens are **encrypted at rest** and never echoed back.
- **Run test generation** measures real words/second for a chosen model on this machine.

## Export (`/export`)

Writes every doc of a chosen status (default `reviewed`) to `data/export/` as Markdown with full YAML front-matter (governance metadata + path), using `enriched_markdown`. The CLI mirrors this.

---

## Recommended first pass for ~1,500 files

1. **Bulk** → paste one `label|path` per source directory, limit `0`, no model → fast deterministic import.
2. **Docs** → filter by `source_org` / `service` / `doc_type` to find natural groups; sort attention by low **confidence**.
3. **Bulk** → set an `adaptation_action` (e.g. `rewrite_into_sop`) on a whole filtered slice.
4. **Transform** the important docs (add `mistral:latest` for quality; use the fact gate for high-stakes runs), check the **brand score**, optionally **Refine with Claude**.
5. **Review** → approve / mark canonical.
6. **Config** Wiki.js → **Publish**, or **Export** to Markdown.
7. Revisit **Gaps** to see what's still thin, and **History** to compare what worked.
