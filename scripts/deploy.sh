#!/usr/bin/env bash
# ===========================================================================
# Wiki.js AI Refinery — Docker-native deployment orchestrator (homelab).
#
# Mirrors the VAS wedding-portal deploy model, adapted to this app's single
# service + persistent data volume. It:
#   1. checks out the requested git revision,
#   2. builds an image tagged by git SHA (immutable, for rollback),
#   3. brings the stack up (KEEPING the refinery_data volume),
#   4. polls /healthz until healthy (or auto-rolls back to the previous tag),
#   5. records current/previous image tags for one-command rollback,
#   6. captures compose logs on any failure.
#
# Commands:
#   deploy.sh deploy     Build + roll out the requested revision (auto-rollback)
#   deploy.sh rollback   Re-up the previously-deployed image tag
#   deploy.sh status     Show recorded tags + live container/health state
#   deploy.sh logs       Tail compose logs for the current stack
#
# Environment (all optional unless noted):
#   DEPLOY_BRANCH        Git branch to fetch          (default: main)
#   DEPLOY_REVISION      Git revision to check out     (default: origin/$DEPLOY_BRANCH)
#   DEPLOY_SKIP_GIT      1 to skip git fetch/checkout  (CI already checked out)
#   DEPLOY_SKIP_BUILD    1 to skip the image build     (e.g. rollback)
#   IMAGE_TAG            Override the per-release tag   (default: git short SHA)
#   COMPOSE_PROFILES     e.g. "tunnel" to include cloudflared
#   HEALTH_TIMEOUT       Seconds to wait for health    (default: 120)
#   HEALTH_INTERVAL      Seconds between health polls   (default: 5)
#   REFINERY_PORT        Host port to health-check      (default: 8000)
#   DRY_RUN=1            Print commands instead of running them.
#
# Recommended secret (present in the homelab .env or the environment):
#   REFINERY_SECRET_KEY  Stable Fernet key so encrypted settings stay readable.
# ===========================================================================
set -Eeuo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${DEPLOY_STATE_DIR:-$APP_DIR/.deploy}"
LOG_DIR="${LOG_DIR:-$APP_DIR/logs}"
DEPLOY_LOG_FILE="${DEPLOY_LOG_FILE:-$LOG_DIR/deploy.log}"
FAILURE_LOG_FILE="${FAILURE_LOG_FILE:-/tmp/deploy-failure.log}"
CURRENT_TAG_FILE="$STATE_DIR/current_image_tag"
PREVIOUS_TAG_FILE="$STATE_DIR/previous_image_tag"

DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_REVISION="${DEPLOY_REVISION:-origin/$DEPLOY_BRANCH}"
DEPLOY_SKIP_GIT="${DEPLOY_SKIP_GIT:-0}"
DEPLOY_SKIP_BUILD="${DEPLOY_SKIP_BUILD:-0}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"
REFINERY_PORT="${REFINERY_PORT:-8000}"
DRY_RUN="${DRY_RUN:-0}"
IMAGE_REPO="${IMAGE_REPO:-ghcr.io/vainasher/wikijs-ai-refinery-vas}"

mkdir -p "$STATE_DIR" "$LOG_DIR"

log()  { printf '[deploy %s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" | tee -a "$DEPLOY_LOG_FILE" >&2; }
die()  { log "ERROR: $*"; exit 1; }
trap 'rc=$?; [ $rc -ne 0 ] && log "Unexpected failure (exit $rc) at line $LINENO"; exit $rc' ERR
run()  { if [ "$DRY_RUN" = "1" ]; then log "[dry-run] $*"; else "$@"; fi; }

# Resolve `docker compose` (v2 plugin) vs legacy `docker-compose`.
if docker compose version >/dev/null 2>&1; then DC=(docker compose); else DC=(docker-compose); fi
compose() { run "${DC[@]}" "$@"; }

short_sha() { git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown"; }

checkout_revision() {
  [ "$DEPLOY_SKIP_GIT" = "1" ] && { log "Skipping git checkout (DEPLOY_SKIP_GIT=1)."; return; }
  log "Fetching and checking out $DEPLOY_REVISION"
  run git -C "$APP_DIR" fetch --all --prune --tags
  run git -C "$APP_DIR" checkout --force "$DEPLOY_REVISION"
}

health_poll() {
  local url="http://127.0.0.1:${REFINERY_PORT}/healthz" waited=0
  log "Polling $url (timeout ${HEALTH_TIMEOUT}s)"
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then log "Healthy after ${waited}s."; return 0; fi
    sleep "$HEALTH_INTERVAL"; waited=$((waited + HEALTH_INTERVAL))
  done
  return 1
}

capture_failure() { { echo "== compose ps =="; "${DC[@]}" ps; echo; echo "== refinery logs =="; "${DC[@]}" logs --tail 200 refinery; } > "$FAILURE_LOG_FILE" 2>&1 || true; }

bring_up() {
  local tag="$1"
  export REFINERY_IMAGE="${IMAGE_REPO}:${tag}"
  log "Bringing up stack with image ${REFINERY_IMAGE}"
  if [ "$DEPLOY_SKIP_BUILD" = "1" ]; then compose up -d; else compose up -d --build; fi
}

cmd_deploy() {
  checkout_revision
  local tag; tag="${IMAGE_TAG:-$(short_sha)}"
  log "Deploying revision $(short_sha) as image tag '${tag}'"
  # Record rollback state: current -> previous, new -> current.
  if [ -f "$CURRENT_TAG_FILE" ]; then run cp "$CURRENT_TAG_FILE" "$PREVIOUS_TAG_FILE"; fi
  bring_up "$tag"
  if health_poll; then
    run bash -c "printf '%s' '$tag' > '$CURRENT_TAG_FILE'"
    log "Deploy OK. current=${tag} previous=$(cat "$PREVIOUS_TAG_FILE" 2>/dev/null || echo none)"
  else
    log "Health check FAILED — rolling back."
    capture_failure
    if [ -f "$PREVIOUS_TAG_FILE" ]; then
      DEPLOY_SKIP_BUILD=1 bring_up "$(cat "$PREVIOUS_TAG_FILE")"
      health_poll && log "Rolled back to $(cat "$PREVIOUS_TAG_FILE")." || log "Rollback also unhealthy — manual intervention needed."
    else
      log "No previous tag recorded; cannot auto-rollback."
    fi
    die "Deploy failed health check (rolled back). See $FAILURE_LOG_FILE."
  fi
}

cmd_rollback() {
  [ -f "$PREVIOUS_TAG_FILE" ] || die "No previous image tag recorded to roll back to."
  local prev; prev="$(cat "$PREVIOUS_TAG_FILE")"
  log "Rolling back to previous tag '${prev}'"
  DEPLOY_SKIP_BUILD=1 bring_up "$prev"
  health_poll || { capture_failure; die "Rollback target is unhealthy."; }
  run bash -c "printf '%s' '$prev' > '$CURRENT_TAG_FILE'"
  log "Rollback complete. current=${prev}"
}

cmd_status() {
  echo "current_image_tag:  $(cat "$CURRENT_TAG_FILE" 2>/dev/null || echo none)"
  echo "previous_image_tag: $(cat "$PREVIOUS_TAG_FILE" 2>/dev/null || echo none)"
  "${DC[@]}" ps
}

cmd_logs() { "${DC[@]}" logs --tail "${1:-100}" -f refinery; }

cd "$APP_DIR"
case "${1:-deploy}" in
  deploy)   cmd_deploy ;;
  rollback) cmd_rollback ;;
  status)   cmd_status ;;
  logs)     cmd_logs "${2:-100}" ;;
  *)        die "Unknown command '${1}'. Use: deploy | rollback | status | logs" ;;
esac
