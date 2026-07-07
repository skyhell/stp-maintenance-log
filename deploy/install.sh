#!/usr/bin/env bash
# ============================================================
#  Installer for the Sewage Treatment Plant Maintenance Log
#  Target: Debian/Ubuntu (Proxmox LXC container or VM)
#  Run as root:  sudo bash deploy/install.sh
# ============================================================
set -euo pipefail

APP_NAME="stp-maintenance"
APP_USER="stp"
APP_DIR="/opt/${APP_NAME}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
PORT="${PORT:-8000}"

# Directory this script lives in (repo root is its parent).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { echo -e "\033[1;34m[install]\033[0m $*"; }
err() { echo -e "\033[1;31m[error]\033[0m $*" >&2; }

if [[ $EUID -ne 0 ]]; then
  err "Please run as root (sudo bash deploy/install.sh)."
  exit 1
fi

log "Installing system dependencies ..."
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates

log "Creating service user '${APP_USER}' ..."
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/${APP_USER}" \
    --shell /usr/sbin/nologin "${APP_USER}"
fi

log "Deploying application to ${APP_DIR} ..."
mkdir -p "${APP_DIR}"
# Copy repository contents (excluding venv / local data / git).
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'data' \
  --exclude '__pycache__' \
  "${REPO_DIR}/" "${APP_DIR}/"

log "Creating Python virtual environment ..."
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip -q
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -q

log "Preparing data directories ..."
mkdir -p "${APP_DIR}/data/uploads" "${APP_DIR}/data/backups"

if [[ ! -f "${APP_DIR}/.env" ]]; then
  log "Creating .env with a generated SECRET_KEY ..."
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  SECRET="$("${APP_DIR}/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" "${APP_DIR}/.env"
  sed -i "s|^PORT=.*|PORT=${PORT}|" "${APP_DIR}/.env"
else
  log ".env already exists — keeping it."
fi

log "Setting ownership ..."
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

log "Installing systemd service ..."
sed "s|--port 8000|--port ${PORT}|" \
  "${APP_DIR}/deploy/${APP_NAME}.service" > "${SERVICE_FILE}"
systemctl daemon-reload
systemctl enable "${APP_NAME}"
systemctl restart "${APP_NAME}"

sleep 2
if systemctl is-active --quiet "${APP_NAME}"; then
  IP="$(hostname -I | awk '{print $1}')"
  log "Done! Service is running."
  echo
  echo "  URL:      http://${IP}:${PORT}"
  echo "  Login:    admin / changeme   (CHANGE THIS IMMEDIATELY)"
  echo "  Logs:     journalctl -u ${APP_NAME} -f"
  echo "  Config:   ${APP_DIR}/.env"
  echo
  echo "  NOTE: Geolocation and voice input require HTTPS. Put this behind a"
  echo "        reverse proxy with TLS (see deploy/nginx.conf.example)."
else
  err "Service failed to start. Check: journalctl -u ${APP_NAME} -e"
  exit 1
fi
