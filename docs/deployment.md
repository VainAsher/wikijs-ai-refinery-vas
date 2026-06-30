# Deployment (homelab + Docker Compose + Cloudflare tunnel)

This guide deploys the refinery on a homelab Docker host, talking to an **Ollama instance on your LAN**, and exposes it through a **Cloudflare tunnel** — gated, because the app has no built-in login.

## Architecture

```
                 Cloudflare Access (identity gate)
                          │
   Internet ──► Cloudflare edge ──► cloudflared (container) ──► refinery (container :8000)
                                                                     │
                                                          OLLAMA_URL  ▼
                                              Ollama on your LAN  (http://192.168.0.x:11434)
                                                                     │
                                                   persistent volume  ▼
                                                          refinery_data  (SQLite, settings, packs)
```

- The **app** runs in a container; **Ollama** runs elsewhere on the LAN/homelab (GPU box).
- **cloudflared** connects to the app over the internal Docker network (`http://refinery:8000`) — the app's host port is only for direct LAN access and isn't needed for the tunnel.
- All mutable state lives in the **`refinery_data`** named volume.

## ⚠️ Security: the app has no login

Anyone who can reach it can publish to Wiki.js, spend Anthropic credits, and read all imported content. Before exposing it via a public Cloudflare hostname, gate it with **both**:

1. **Cloudflare Access** (Zero Trust) — add an Access *application* over the tunnel hostname with an allow policy (your email / Google / GitHub identity). This is the primary gate and requires no app changes.
2. **App Basic Auth** (defense-in-depth) — set `REFINERY_BASIC_AUTH_USER` / `REFINERY_BASIC_AUTH_PASS`. The app then requires HTTP Basic on every route except `/healthz`.

Do not expose it publicly without at least Cloudflare Access.

## Quick start

```bash
git clone https://github.com/VainAsher/wikijs-ai-refinery-vas.git
cd wikijs-ai-refinery-vas
cp .env.docker.example .env        # then edit it (see below)
docker compose up -d --build       # app only
# add the tunnel once .env has a token:
docker compose --profile tunnel up -d
```

Open `http://<docker-host>:8000` on the LAN (or your Cloudflare hostname once the tunnel is up).

## Configuration (`.env`)

| Variable | Purpose | Example |
|----------|---------|---------|
| `REFINERY_PORT` | Host port for direct LAN access | `8000` |
| `OLLAMA_URL` | Your LAN Ollama `/api/generate` endpoint | `http://192.168.0.50:11434/api/generate` |
| `OLLAMA_MODEL` | Default model | `mistral:latest` |
| `OLLAMA_LAN_HOSTS` | Extra hosts the in-app **Auto-detect** probes (comma list) | `192.168.0.50:11434,ollama.lan` |
| `OLLAMA_NUM_CTX` / `OLLAMA_NUM_PREDICT` | Context/output token budgets (keep generous for detailed drafts) | `8192` / `4096` |
| `REFINERY_SECRET_KEY` | Stable Fernet key for encrypted settings | *(generate, see below)* |
| `REFINERY_BASIC_AUTH_USER` / `_PASS` | App Basic Auth | *(set when exposed)* |
| `CLOUDFLARE_TUNNEL_TOKEN` | Tunnel token (tunnel profile only) | *(from Cloudflare)* |

Generate a stable encryption key once:

```bash
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

Set it as `REFINERY_SECRET_KEY` so encrypted secrets (Wiki.js token, Anthropic key) survive a volume restore or a host move. If left blank, the app auto-generates one inside the volume (fine until you move the data elsewhere).

## Ollama on the LAN

The GPU/Ollama box is typically separate from the app container. Three ways to reach it:

1. **A fixed LAN host (recommended for a homelab):** `OLLAMA_URL=http://192.168.0.50:11434/api/generate`.
2. **Ollama on the Docker host itself:** the compose file maps `host.docker.internal:host-gateway`, so `OLLAMA_URL=http://host.docker.internal:11434/api/generate` works on Linux Docker.
3. **Auto-detect:** set `OLLAMA_LAN_HOSTS`, then click **Auto-detect Ollama** on the Config page; it probes those hosts plus the host gateway and localhost.

Ensure Ollama listens on the LAN (`OLLAMA_HOST=0.0.0.0` on that box) and that your firewall allows the app host to reach port 11434. Pull a capable model there: `ollama pull mistral` (per project guidance, `mistral:latest` gives the richest transforms).

## Importing source Markdown into the container

A container **cannot read host paths** (`C:\Users\...`, `/home/...`) unless they're mounted in — a Bulk/Connectors import of a host folder fails with *"Local Markdown path does not exist"*. Mount your corpus read-only:

1. Set `REFINERY_IMPORTS_DIR` in `.env` to the host folder that **contains** your Markdown (Windows/Docker Desktop: `C:\Users\you\OneDrive\Desktop\my_docs`; homelab: `/srv/refinery/imports`).
2. `docker compose up -d` to apply the mount (recreates the container).
3. In the **Bulk Workbench**, import using **container** paths under `/imports`, e.g.:

   ```
   squarespace|/imports/squarespace_kb_articles
   ```

The folder is mounted read-only, so imports never modify your source files. (Running the app directly on the host instead of in a container can read host paths natively — handy for one-off local imports.)

## Cloudflare tunnel

1. In **Cloudflare Zero Trust → Networks → Tunnels**, create a tunnel and copy its **token**.
2. Put it in `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
3. Add a **public hostname** to the tunnel pointing at the internal service **`http://refinery:8000`** (the container name on the compose network).
4. `docker compose --profile tunnel up -d`.
5. In **Zero Trust → Access → Applications**, add an application for that hostname with an allow policy (your identity). 

## Data, backups, updates

- **Backup:** snapshot the `refinery_data` volume (it holds the SQLite store, encrypted settings, context packs, and brand profile). Keep `REFINERY_SECRET_KEY` with the backup or encrypted secrets won't decrypt elsewhere.
- **Update:** `git pull && docker compose up -d --build` (or pull the published image — see CI/CD below).
- **Logs:** `docker compose logs -f refinery`.
- **Healthcheck:** the container reports health via `/healthz`; `docker ps` shows `healthy`.

## CI/CD

Two GitHub Actions workflows mirror the VAS wedding-portal model.

### `Tests` (`.github/workflows/test.yml`)
On every push/PR to `main` (and manual dispatch): runs the **pytest** suite with coverage, then **builds the Docker image and smoke-tests `/healthz`** in a throwaway container. This is the gate the deploy depends on.

### `Deploy` (`.github/workflows/deploy.yml`)
Runs **after `Tests` succeeds on `main`** (only if the `DEPLOY_ENABLED` variable is `true`), or via manual dispatch (deploy/rollback, choose environment). A runner SSHes into the homelab **through the Cloudflare tunnel** and runs **`scripts/deploy.sh`** there — the runner never touches Docker. `deploy.sh` checks out the revision, builds an **SHA-tagged image**, brings the stack up, polls `/healthz`, and **auto-rolls back** to the previous tag on failure. Secrets travel as a base64 blob over SSH stdin (never on the command line or disk).

`scripts/deploy.sh` is also usable by hand on the host: `deploy.sh deploy | rollback | status | logs`.

### Required configuration (repo or environment scope)

| Kind | Name | Purpose |
|------|------|---------|
| Variable | `DEPLOY_ENABLED` | Set to `true` to allow auto-deploys |
| Secret | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` | SSH into the homelab (via the tunnel) |
| Variable | `DEPLOY_PORT`, `DEPLOY_PATH` | SSH port (default 22) and the repo path on the host |
| Variable | `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_LAN_HOSTS`, `REFINERY_PORT`, `COMPOSE_PROFILES` | Non-secret runtime config passed into the deploy |
| Secret | `REFINERY_SECRET_KEY`, `CLOUDFLARE_TUNNEL_TOKEN`, `REFINERY_BASIC_AUTH_USER/PASS` | Optional secrets injected into the deploy env |

The homelab host needs Docker, this repo cloned at `DEPLOY_PATH`, and SSH reachable from the runner (e.g. a Cloudflare tunnel SSH route, or a self-hosted runner). Set `COMPOSE_PROFILES=tunnel` to have the deploy also run `cloudflared`.
