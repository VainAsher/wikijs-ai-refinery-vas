# VainAsherStudios Wiki.js AI Refinery

A local, offline-capable workbench for turning **raw imported Markdown into a VainAsherStudios-owned, governed Wiki.js knowledge base**.

It is built for one concrete situation: around **1,500 raw Markdown files** spread across multiple source directories — mostly hosting/reference material from employers, competitors, and upstream tools — that need to be safely re-authored into original VAS content for:

- website hosting · website development · managed IT · business email
- AI workflows · gaming community operations
- Minecraft / Project Zomboid / Rust community moderation · moderator & admin training
- YouTube, LinkedIn, Twitch, and Discord content

## The one rule

> **Imported third-party content is *evidence, not truth*.**
> You **import → classify → transform into an original VAS draft → review → publish.** Reference docs are never published verbatim, and governance is **deterministic** — it runs *after* any AI step, so a competitor/employer/vendor doc can never be marked canonical even if a model suggests it.

Everything in the app exists to protect that rule while making 1,500 documents tractable.

---

## Quick start (Windows PowerShell)

```powershell
git clone https://github.com/VainAsher/wikijs-ai-refinery-vas.git
cd wikijs-ai-refinery-vas
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn refinery.app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The app seeds its own `data/` directory (SQLite store, default context packs, brand profile) on first run — a fresh clone ships data-free and bootstraps itself.

No AI is required: the refinery classifies and produces safe fallback drafts deterministically. A local **Ollama** model (optional) improves rewrite quality; an **Anthropic API key** (optional) enables a higher-quality cloud "reroll".

### Homelab / Docker

For a homelab deployment (app in a container, Ollama on the LAN, exposed via a Cloudflare tunnel):

```bash
cp .env.docker.example .env   # set OLLAMA_URL to your LAN Ollama, etc.
docker compose up -d --build
docker compose --profile tunnel up -d   # optional: Cloudflare tunnel
```

The app has **no built-in login** — gate any public exposure with Cloudflare Access and/or app Basic Auth. Full guide: **[docs/deployment.md](docs/deployment.md)**.

---

## Pages at a glance

| Page | Route | Purpose |
|------|-------|---------|
| **Docs** | `/` | The in-flight review queue: filter, paginate, open, approve. Confidence pill per doc. |
| **Bulk** | `/bulk` | Import many local directories at once; batch-update a filtered slice. |
| **Connectors** | `/connectors` | One-off imports from Zendesk, MediaWiki, ClickUp, Google Docs, or local Markdown. |
| **Context** | `/context` | Edit the VAS context packs injected into AI rewrites (brand voice, manifesto, visual identity, services, rules). |
| **Monitor** | `/monitor` | Pipeline health: queue counts, governance breakdowns, Ollama/DB status, transform telemetry. |
| **Gaps** | `/gaps` | Content-gap analysis — which services need a rewrite, fresh coverage, or deepening. |
| **History** | `/history` | Every AI transform run: model, dials, brand score, latency. |
| **Config** | `/config` | Ollama URL/model (+ auto-detect), Wiki.js credentials, Anthropic key (encrypted at rest), live model speed test. |
| **Guide** | `/guide` | In-app workflow guide and glossary. |
| **Doc editor** | `/docs/{id}` | Per-document editor: metadata, Markdown editor + preview, transform, redaction gate, brand score, Claude reroll, publish. |

A live **progress tray** (bottom-right) tracks background imports/bulk-updates and follows you across pages.

---

## The pipeline

```
   Import ──► Classify ──► Triage ──► Transform ──► Review ──► Publish
 (bulk /     (deterministic  (filter +  (rewrite into   (edit,     (Wiki.js
  connectors) + optional AI,  bulk set)  an original     approve,    GraphQL or
              governed)                  VAS draft)      redact)     Markdown export)
```

- **Import** runs as a background job with a live progress bar; re-imports are de-duplicated, not duplicated.
- **Classify** assigns source governance, service, doc type, audience, risk, sensitivity, and a computed **confidence** score. AI output is validated against the taxonomy and governance is re-asserted afterwards.
- **Transform** turns a reference doc into a brand-new VAS draft, tunable with **variation dials** (tone, audience, length, citations, …) and optionally gated by a **fact-verification** step. Each draft is **brand-scored** against `data/brand.yaml`.
- **Review** is the per-document editor, with a **redaction gate** for detected secrets/PII and an optional **Claude cloud reroll**.
- **Publish** pushes approved docs to Wiki.js, or exports governed Markdown (with YAML front-matter) to disk.

See **[docs/](docs/)** for the full living documentation.

---

## Documentation

| Doc | What's in it |
|-----|--------------|
| [docs/architecture.md](docs/architecture.md) | Modules, data model, request lifecycle, the classification pipeline, concurrency model. |
| [docs/user-guide.md](docs/user-guide.md) | Page-by-page walkthrough and the end-to-end workflows. |
| [docs/governance.md](docs/governance.md) | The safety model, the source registry, document states, and *why* it's deterministic. |
| [docs/configuration.md](docs/configuration.md) | Settings precedence, environment variables, Ollama, Wiki.js, Anthropic, secret encryption. |
| [docs/deployment.md](docs/deployment.md) | Homelab Docker Compose deploy, LAN Ollama, Cloudflare tunnel, and the security model. |
| [docs/development.md](docs/development.md) | Running, testing, the headless CLI, and how to extend connectors/services/context. |
| [docs/pipelines.md](docs/pipelines.md) | **v2 multi-pass enrichment pipelines** — running them (UI/CLI), templates, persistence. |
| [docs/enrichment-passes.md](docs/enrichment-passes.md) | The pass catalogue, execution modes, deterministic gates, and how to add a pass. |
| [docs/retrieval-context.md](docs/retrieval-context.md) | ContextBuilder, progressive vs retrieval context, chunking, and the retrieval index. |
| [docs/ux-and-flows.md](docs/ux-and-flows.md) | The user, the story, the personas, and the key journeys. |

---

## Headless CLI

For scripting and CI, `refinery_cli.py` mirrors the web import/export/publish without the UI:

```powershell
python refinery_cli.py import  --connector local_markdown --local-path C:\docs\raw --source-label employer_hosting
python refinery_cli.py export  --status reviewed --output data\export
python refinery_cli.py publish --status reviewed --wikijs-url $env:WIKIJS_URL --wikijs-token $env:WIKIJS_TOKEN
```

## Tests

```powershell
python -m pytest -q
```

The suite covers classification, governance, the store/migrations, settings encryption, the redaction scrubber, dials, brand scoring, gap analysis, fact extraction, the background-job progress feed, and the endpoint flows.

---

## Safety model in one picture

```
Reference / imported docs  →  source evidence only      (never canonical, never customer-safe)
VAS transformed drafts     →  editable VAS-owned drafts  (not auto-published)
Reviewed canonical docs    →  Wiki.js source of truth    (approved, governed)
```

Do not publish imported third-party/employer/competitor docs directly as VAS policy. **Transform, edit, review, then promote.**
