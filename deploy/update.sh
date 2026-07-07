#!/usr/bin/env bash
# ============================================================
#  Update an existing installation to the latest version.
#  Run as root INSIDE the container / on the host where the app
#  is installed:
#
#     sudo bash /opt/stp-maintenance/deploy/update.sh
#
#  It pulls the latest code, updates dependencies and restarts
#  the service. Your data (data/), config (.env) and the
#  virtualenv (.venv) are preserved. A snapshot of the SQLite
#  database is taken before restarting.
#
#  Private repo? Provide a token:
#     GITHUB_TOKEN=ghp_xxx sudo -E bash deploy/update.sh
# ============================================================
set -euo pipefail

APP_NAME="stp-maintenance"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
APP_USER="${APP_USER:-stp}"
SERVICE="${SERVICE:-${APP_NAME}}"
BRANCH="${BRANCH:-main}"
REPO_URL="${REPO_URL:-https://github.com/skyhell/stp-maintenance-log.git}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"

c_blue='\033[1;34m'; c_green='\033[1;32m'; c_red='\033[1;31m'; c_yellow='\033[1;33m'; c_reset='\033[0m'
log()  { echo -e "${c_blue}[update]${c_reset} $*"; }
ok()   { echo -e "${c_green}[ok]${c_reset} $*"; }
warn() { echo -e "${c_yellow}[warn]${c_reset} $*"; }
die()  { echo -e "${c_red}[error]${c_reset} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Please run as root (sudo bash deploy/update.sh)."
[[ -d "$APP_DIR" ]] || die "App directory ${APP_DIR} not found. Is the app installed?"
[[ -x "${APP_DIR}/.venv/bin/pip" ]] || die "Virtualenv not found at ${APP_DIR}/.venv."

log "Ensuring git and rsync are present ..."
apt-get update -qq
apt-get install -y --no-install-recommends git rsync ca-certificates >/dev/null

# Record the currently installed version for the summary.
OLD_VERSION="$("${APP_DIR}/.venv/bin/python" -c 'import app; print(app.__version__)' 2>/dev/null || echo '?')"

# ---------------- Fetch the latest code ----------------
CLONE_URL="$REPO_URL"
if [[ -n "$GITHUB_TOKEN" ]]; then
  CLONE_URL="$(echo "$REPO_URL" | sed -E "s#https://#https://${GITHUB_TOKEN}@#")"
fi

TMP_SRC="$(mktemp -d)"
cleanup() { rm -rf "$TMP_SRC"; }
trap cleanup EXIT

log "Cloning ${BRANCH} ..."
if ! git clone --depth 1 --branch "$BRANCH" "$CLONE_URL" "$TMP_SRC" >/dev/null 2>&1; then
  die "git clone failed. Private repo? Pass GITHUB_TOKEN=... (or make it public)."
fi
NEW_VERSION="$(grep -oE '__version__ = "[^"]+"' "$TMP_SRC/app/__init__.py" | head -1 | cut -d'"' -f2 || echo '?')"

# ---------------- Snapshot the database ----------------
DB_FILE="${APP_DIR}/data/app.db"
if [[ -f "$DB_FILE" ]]; then
  SNAP_DIR="${APP_DIR}/data/backups"
  mkdir -p "$SNAP_DIR"
  SNAP="${SNAP_DIR}/pre-update-$(date +%Y%m%d-%H%M%S).db"
  cp "$DB_FILE" "$SNAP"
  ok "Database snapshot: ${SNAP}"
fi

# ---------------- Sync code (preserve data/.env/.venv) ----------------
log "Syncing new code into ${APP_DIR} ..."
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'data' \
  --exclude '.env' \
  --exclude '__pycache__' \
  "${TMP_SRC}/" "${APP_DIR}/"

log "Updating Python dependencies ..."
"${APP_DIR}/.venv/bin/pip" install --upgrade pip -q
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -q

id -u "$APP_USER" >/dev/null 2>&1 && chown -R "${APP_USER}:${APP_USER}" "$APP_DIR"

# ---------------- Restart & health check ----------------
log "Restarting ${SERVICE} ..."
systemctl restart "$SERVICE"

PORT="$(grep -E '^PORT=' "${APP_DIR}/.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
PORT="${PORT:-8000}"

sleep 2
for i in $(seq 1 10); do
  if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    ok "Service healthy on port ${PORT}."
    echo
    ok "Updated ${OLD_VERSION} -> ${NEW_VERSION}."
    exit 0
  fi
  sleep 1
done

warn "Service did not report healthy within 12s. Check: journalctl -u ${SERVICE} -e"
exit 1
