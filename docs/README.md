# Living documentation

Documentation for the **VainAsherStudios Wiki.js AI Refinery**. Start with the project [README](../README.md) for the overview and quick start; come here for depth.

| Doc | Read it when you want to… |
|-----|---------------------------|
| [architecture.md](architecture.md) | understand the modules, data model, request lifecycle, classification pipeline, and concurrency model. |
| [governance.md](governance.md) | understand the safety model — the source registry, document states, and why governance is deterministic. |
| [user-guide.md](user-guide.md) | learn every page and run the end-to-end workflows. |
| [configuration.md](configuration.md) | configure settings, Ollama, Wiki.js, Anthropic, and secret encryption. |
| [development.md](development.md) | run, test, use the CLI, and extend connectors/services/context/dials. |
| [ux-and-flows.md](ux-and-flows.md) | understand the user, the story, the personas, and the key journeys. |

## The 60-second model

- **Purpose:** turn ~1,500 raw imported Markdown docs into an original, governed, VAS-owned Wiki.js knowledge base.
- **The one rule:** imported content is *evidence, not truth* — import → classify → transform into an original draft → review → publish. Never republished verbatim.
- **Why it's safe:** governance is **deterministic** and reapplied after every AI step, so a reference doc can never become canonical by accident.
- **Stack:** FastAPI + server-rendered Jinja + SQLite, with optional local Ollama and optional Claude. Runs locally and offline.
- **Pipeline:** `Import → Classify → Triage → Transform → Review → Publish`, with background jobs, variation dials, a fact gate, brand scoring, a redaction gate, telemetry, and content-gap analysis layered on.

> These docs are **living** — when you change behaviour, update the matching doc (and its `requirements`/route/flow references) in the same commit.
