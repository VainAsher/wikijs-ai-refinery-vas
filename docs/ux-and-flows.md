# UX, story & flows

This document captures the *experience* the refinery is designed to deliver: who it's for, the story it tells, the personas, and the journeys they take. It complements the [user-guide.md](user-guide.md) (what each page does) with *why the experience is shaped this way*.

## The user

A **VainAsherStudios operator** — realistically the founder/operator wearing several hats: hosting, managed IT, AI workflows, and gaming-community operations. They are technical enough to run Ollama and a Wiki.js instance, but they are time-poor and doing knowledge work *alongside* delivery work, not as a full-time content team.

They have inherited a **mess of ~1,500 raw Markdown files** — exported from employers, scraped from competitor help centres, pulled from upstream tool docs (Authentik, Pterodactyl, Wiki.js itself). It's all *useful* as reference, but **none of it is VAS's to publish**. They want a clean, branded, trustworthy Wiki.js knowledge base — without legal/ethical exposure and without spending months copy-pasting.

## The core story

> *"I have a thousand-plus docs that aren't mine. I need to turn the useful ones into original VainAsherStudios documentation — in our voice, safely classified so I never accidentally republish a competitor's content — review them, and publish to our wiki. Locally. Without it taking forever."*

The product's entire shape follows from one promise: **you cannot leak or republish by accident.** Every interaction reinforces "imported = evidence, not truth." That promise is what lets an overwhelmed operator move *fast* through 1,500 docs without anxiety — the guardrails are deterministic, so speed is safe.

## The emotional arc

```
Overwhelmed ──► Reassured ──► In control ──► Confident
(1,500 docs)   (can't leak    (bulk triage   (review + brand
                by accident)   + filters)      scoring → publish)
```

1. **Overwhelmed** — a thousand files, none owned. The Bulk import + a single progress bar turns "a mountain" into "a running job."
2. **Reassured** — every imported doc is visibly stamped reference / rewrite-required, quarantined under `imports/`. The safety model is shown, not hidden.
3. **In control** — filters, stat-tile shortcuts, confidence sorting, and bulk batch-updates make 1,500 docs navigable in groups, not one-by-one.
4. **Confident** — the doc editor gives a brand score, a redaction gate, classifier reasoning, and an optional cloud reroll, so promoting a doc to canonical feels deliberate and earned.

## Personas (modes of the same operator)

| Persona | Goal | Primary surfaces |
|---------|------|------------------|
| **The Importer** | Get everything in, fast, safely labelled. | Bulk Workbench, Connectors, the progress tray. |
| **The Triager** | Make sense of the pile; group and prioritise. | Docs queue (filters, confidence pill), Bulk batch-update. |
| **The Author** | Turn a good reference doc into a great VAS draft. | Doc editor, transform + dials + fact gate, context packs, Claude reroll. |
| **The Reviewer** | Decide what becomes truth; keep secrets out. | Doc editor (redaction gate, brand score, approve/canonical). |
| **The Strategist** | Know what to build next and whether it's working. | Monitor, Gaps, History. |
| **The Publisher** | Ship approved docs to the wiki. | Publish button, Export, Config. |

## Key flows

### Flow A — The big first pass (the primary journey)

The reason the tool exists: 1,500 docs, from zero to a triaged, partly-rewritten knowledge base.

```
Bulk import (label|path, limit 0, no model)
  → background job + progress tray  →  "View results"
Docs queue: filter by source_org / service / doc_type; sort attention by low confidence
Bulk batch-update: set adaptation_action on a whole filtered slice
Transform the important docs (add a model; fact-gate the high-stakes ones)
  → brand score shown  → optional Claude reroll
Review: approve / mark canonical
Publish to Wiki.js  (or Export to Markdown)
Loop back via Gaps (what's still thin?) and History (what worked?)
```

What makes it feel good: nothing blocks. Imports and bulk updates are async with a tray that **follows across pages**, so the operator keeps working while a thousand files process.

### Flow B — Deep work on a single document

The craft loop, for a doc worth getting right.

```
Open /docs/{id}
  → read the "why it was classified this way" reasoning + confidence
  → (if flagged) open the Sensitive content gate → redact secrets/PII
  → Transform: pick target + dials + context packs
       ├─ Generate draft (direct), or
       └─ Prepare with fact gate → vet keywords/facts → commit
  → draft is created (new queue doc), auto brand-scored
  → optional: Refine with Claude (cost shown up front, actuals after)
  → edit in the Markdown editor (live preview)
  → Approve / Mark canonical
  → Publish
```

The fact gate and the brand score are the trust-builders here: the operator sees *exactly* which facts the rewrite is allowed to use, and a number for how on-brand the output is — turning "is this good enough?" from a gut call into a checkable one.

### Flow C — Strategy & monitoring

The "am I making progress, and on the right things?" loop.

```
Monitor → queue health, governance breakdowns, transform telemetry
Gaps    → which services have reference docs but no VAS draft (rewrite backlog),
           which have none (no coverage), which are shallow → click through to act
History → compare models/dials by brand score + latency before a bulk run
```

This closes the loop: Gaps tells the Strategist *what* to forge next; History tells them *which settings* produced the best drafts.

### Flow D — Configuration & onboarding

The quiet path that makes the rest work.

```
Config → Auto-detect Ollama (or paste URL) → pick a model from the live dropdown
       → Run test generation (words/sec on this machine)
       → add Wiki.js URL + token, and/or Anthropic key (both encrypted at rest)
Context → review/edit the brand voice, manifesto, visual identity, and rules packs
```

## Design principles the UX encodes

- **Safety is structural, not advisory.** The operator can't accidentally publish a competitor doc because governance is reapplied deterministically after every step — so the UI can afford to be fast and forgiving.
- **Never block the operator.** Heavy work runs in the background with a persistent progress tray; the app stays responsive at 1,500-doc scale.
- **Triage at group scale, craft at single-doc scale.** Filters + bulk actions for the pile; a rich editor for the few that matter.
- **Make judgement calls checkable.** Confidence (triage), brand score (quality), the fact gate (accuracy), and the redaction gate (safety) each replace a gut feeling with a visible signal.
- **AI is optional and never authoritative.** Everything works without a model; when a model is used, its output is validated and governance overrides it.
- **Progressive disclosure.** Essentials are always visible; advanced power (batch-update, dials, fact gate, classifier reasoning, governance fields) lives behind collapsible sections so the page isn't overwhelming.
- **Offline-first, local-first.** SQLite, local Ollama, optional cloud — the operator owns their data and can work without a network.

## Where the experience could go next

(Captured for the roadmap, not yet built.) Per-claim **source attribution** on drafts; a structured **brand profile editor** in the UI (today `brand.yaml` is edited as a file); inline **diff** between a reference doc and its generated draft; and a **bulk transform** that fans a filtered slice through the transform engine as one background job.
