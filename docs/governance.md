# Governance & the safety model

Governance is the reason this tool exists. The refinery imports content VainAsherStudios does **not** own — documentation from employers, competitors, and upstream tools — and its core job is to make it **impossible to accidentally republish that content as VAS policy.**

## The one rule

> Imported third-party content is **evidence, not truth**.

Concretely:

- Reference docs are **never published verbatim**.
- Governance is **deterministic** and runs **after** any AI step. An LLM can suggest tags or a summary, but it can never flip a competitor's doc to "canonical".
- A document only becomes a VAS source of truth by being **transformed into an original draft, reviewed, and approved by a human.**

## The three document states

```
┌─ Reference / imported ─┐   ┌─ VAS transformed draft ─┐   ┌─ Reviewed canonical ─┐
│ source evidence only   │ ► │ original, editable,     │ ► │ approved VAS source   │
│ never canonical        │   │ VAS-owned working doc   │   │ of truth, ready for   │
│ never customer-safe    │   │ not auto-published      │   │ Wiki.js               │
│ rewrite_required       │   │ rewrite_status: draft   │   │ authority: canonical  │
└────────────────────────┘   └─────────────────────────┘   └───────────────────────┘
```

The middle state is the whole point: you extract the *useful operational patterns* from a reference doc into a brand-new VAS document, rather than copying its words.

## The source registry (`core.py → SOURCE_REGISTRY`)

Every document is attributed to a **`source_org`**, which determines its **governance defaults** in one lookup. The org is set from the **import label** (authoritative) or inferred from content.

| `source_org` (slug) | `source_role` | Posture |
|---------------------|---------------|---------|
| `vainasherstudios` | `owned` | The only org that can be canonical / customer-safe. |
| `employer_hosting` | `employer_reference` | A hosting employer's docs — reference only, rewrite required. |
| `competitor_hosting_1`, `competitor_hosting_2` | `competitor_reference` | Competing hosts — reference only, rewrite required. |
| `infrastructure_provider_1`, `infrastructure_provider_2` | `infrastructure_reference` | Cloud/infra suppliers VAS builds on — reference only. |
| `authentik`, `pterodactyl`, `wikijs`, `mailcow`, `nextcloud`, … | `vendor_documentation` | Upstream tools VAS operates — adapt into VAS runbooks, respect the licence, never republish. |

> **Anonymisation note.** The hosting/cloud slugs are intentionally **generic** — the codebase names no specific third-party company. Real brand names were replaced with category slugs (`employer_hosting`, `competitor_hosting_1`, …) so the repository is shareable. You assign the right slug at **import time** via the `label|path` field. The self-hosted **tool** names (Authentik, Pterodactyl, …) are kept because they double as functional service identifiers.

### What "reference" enforces

For any org flagged `reference: True`, `source_governance()` forces:

- `canonical = False`
- `authority = imported_unreviewed`
- `customer_safe = False`
- `reuse_policy = rewrite_required` (or `review_required` for an unknown org)

These are reapplied **every time** a doc is classified or re-classified, including after an AI merge — so they cannot drift.

## Why deterministic-after-AI matters

The transform and classification can call a local Ollama model (or, for re-rolls, Claude). Models are useful for *quality* but must not be trusted with *authority*. So the flow is always:

```
AI suggests fields ─► validate every value against taxonomy.yml ─► re-run source_governance() ─► store
                                                                    └─ reference orgs forced non-canonical here
```

`merge_ai_classification` drops any AI value that isn't in the controlled vocabulary, then calls `source_governance()` again. The test suite pins this behaviour (`test_merge_ai_validates_and_reasserts_governance`): an AI that tries to set `canonical: true` on a competitor doc is overruled.

## Governance vocabulary (glossary)

| Term | Meaning |
|------|---------|
| `source_org` | Who the doc came from. Drives the governance defaults. |
| `source_role` | Relationship to that source: `owned`, `competitor_reference`, `employer_reference`, `infrastructure_reference`, `vendor_documentation`. |
| `reuse_policy` | How you may use it: `owned_original`, `rewrite_required`, `reference_only`, `quote_prohibited`. |
| `adaptation_action` | The transform target, e.g. `rewrite_into_sop`, `rewrite_into_moderation_playbook`. |
| `rewrite_status` | Lifecycle of a reference doc: `needs_rewrite` → `draft_generated` → `in_review` → `approved`. |
| `authority` | Trust level: `imported_unreviewed`, `draft`, `approved`, `canonical`, `archived`. |
| `customer_safe` | Whether the content may face customers/community. Reference docs are forced `false`. |
| `confidence` | 0–1 score of how sure the **auto-classification** is (not a trust signal — a triage signal). |
| `brand_score` | 0–100 score of how well a draft matches the VAS brand profile (`data/brand.yaml`). |

## Where the wiki path comes from (`build_wiki_path`)

- A transformed draft (`source == vainasherstudios_transform`) → its `canonical_target` (e.g. `sops/minecraft/restart`).
- A VAS-owned canonical doc → its `canonical_target`.
- Anything else (reference docs) → `imports/{source_org}/{slug}` — quarantined under `imports/` so reference material is visibly separated from VAS-owned content.

## Sensitive content

`scan_sensitive` flags `contains_pii` / `contains_secrets` during classification. The **redaction gate** (`scrub_findings` / `apply_redactions`, surfaced on the doc editor) turns that passive detection into action: it lists detected secrets/PII (private keys, cloud tokens, JWTs, IPs, emails, …) and lets a reviewer replace them with `[REDACTED:kind]` placeholders before publishing. This pairs with the **privacy** context pack, which instructs AI rewrites never to surface secrets in customer-facing output.

## Adding a new source or tool

- A new **reference org**: add one entry to `SOURCE_REGISTRY` in `core.py` and one line to `source_orgs` in `taxonomy.yml`.
- A new **managed tool** whose docs you import: add one line to `MANAGED_SERVICE_DOC_ORGS` (the slug doubles as the `service`).

No `if/elif` edits are needed anywhere — the registry is the single source of truth.
