# Configuration

All runtime configuration lives in `refinery/settings.py` and is layered so the UI, the environment, and code defaults cooperate.

## Precedence

On read, each setting resolves in this order:

```
saved value (data/settings.json)  ►  environment variable  ►  built-in default
```

This means the **Config page** can override an environment variable without a restart, while a fresh checkout still works purely from `.env` / shell environment. The Config page also shows the *source* of each effective value (`settings.json`, `environment`, or `default`).

## Settings

| Setting | Env var | Default | Notes |
|---------|---------|---------|-------|
| `ollama_url` | `OLLAMA_URL` | `http://localhost:11434/api/generate` | The `/api/generate` endpoint. Health/model lookups reuse its host. |
| `ollama_model` | `OLLAMA_MODEL` | *(empty)* | Default model for AI classification + transforms. Empty = deterministic only. |
| `wikijs_url` | `WIKIJS_URL` | *(empty)* | Wiki.js GraphQL endpoint, e.g. `http://localhost:3000/graphql`. |
| `wikijs_token` | `WIKIJS_TOKEN` | *(empty)* | **Secret** — encrypted at rest. |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | *(empty)* | **Secret** — encrypted at rest. Enables the Claude reroll. |

See `.env.example` for the full set, including connector credentials (`ZENDESK_URL`, `MEDIAWIKI_API_URL`, `CLICKUP_TOKEN`, `GOOGLE_DRIVE_FOLDER_ID`, …).

## Secret encryption at rest

Secret fields (`wikijs_token`, `anthropic_api_key`) are **Fernet-encrypted** before being written to `data/settings.json`, and decrypted transparently on read.

- The encryption key comes from `REFINERY_SECRET_KEY` (a valid Fernet key) if set, otherwise from an **auto-generated** `data/.secret_key` file (git-ignored). So encryption works out of the box with no manual key management.
- Stored values are prefixed `enc::`. Values written before encryption (plain, no prefix) keep working — the loader treats them as legacy plaintext.
- If the `cryptography` library is unavailable, the app **degrades to plaintext** storage rather than failing (the value is still masked in the UI).
- Encrypted values are never echoed back to the browser — the Config page shows only "currently set".

> To clear a stored secret, blank submission won't wipe it (by design); edit or delete `data/settings.json` directly. To rotate the encryption key, replace `data/.secret_key` (existing ciphertext becomes unreadable and the secret reads as unset).

## Ollama (local AI — optional)

The refinery is fully usable without Ollama. When present, a model improves the *quality* of AI classification and transforms — never the safety/governance rules.

- **Auto-detect** on the Config page probes, in order: `OLLAMA_URL` env, the configured value, the Docker service name (`http://ollama:11434`), `host.docker.internal`, and localhost. It fills in the first reachable `/api/generate` URL.
- When the server is reachable, the model fields become a **dropdown** populated from `/api/tags`.
- **Run test generation** does a tiny generation and reports latency + words/second, so you can compare models on your hardware before a bulk run.
- Larger instruct models (e.g. `mistral:latest`) produce fuller drafts; 3B-class models tend to under-generate.

```powershell
ollama serve
ollama pull mistral
```

## Wiki.js (publishing — optional)

Set the GraphQL URL and an API token (Config page or env). The **Publish** button on the doc editor calls the Wiki.js `pages.create` GraphQL mutation; reviewed/approved docs are published, rejected docs are created unpublished. Without Wiki.js configured, use **Export** to write governed Markdown to disk instead.

## Anthropic (cloud reroll — optional)

Install the SDK (`pip install anthropic`, already in `requirements.txt`) and set an API key. The "Refine with Claude" panel then becomes active on the doc editor. Default model is `claude-opus-4-8`; Sonnet 4.6 and Haiku 4.5 are selectable with their per-million-token pricing shown. Cost is estimated up front and reported exactly (from response usage) after each run.

## Data directory

Everything mutable lives under `data/` (git-ignored, seeded on first run):

```
data/
  refinery.sqlite3      the document + runs store
  settings.json         runtime settings (secrets encrypted)
  .secret_key           auto-generated Fernet key
  brand.yaml            the structured brand profile (compliance scoring)
  vas_context/*.md      the context packs
  export/               Markdown export output
```

Point the app at a different location with `REFINERY_DATA`.
