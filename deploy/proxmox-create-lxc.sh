#!/usr/bin/env bash
# ============================================================
#  Run this ON THE PROXMOX HOST. It creates a Debian 12 LXC
#  container named "stp-maintenance-log" and installs the Sewage
#  Treatment Plant Maintenance Log as a systemd service.
#
#  Usage (as root on the Proxmox node):
#     bash proxmox-create-lxc.sh
#
#  Everything is configurable via environment variables, e.g.:
#     CTID=150 CT_HOSTNAME=stp-maintenance-log CORES=2 RAM=1024 DISK=6 \
#     BRIDGE=vmbr0 STORAGE=local-lvm bash proxmox-create-lxc.sh
#
#  Private GitHub repo? Provide a token so the container can clone it:
#     GITHUB_TOKEN=ghp_xxx bash proxmox-create-lxc.sh
# ============================================================
set -euo pipefail

# ---------------- Configuration (override via env) ----------------
CTID="${CTID:-}"                       # empty -> auto-pick next free VMID
# NOTE: do NOT name this HOSTNAME — that is a reserved shell variable already
# set to the Proxmox node's name (usually "pve"), which would override the default.
CT_HOSTNAME="${CT_HOSTNAME:-stp-maintenance-log}"
CORES="${CORES:-1}"
RAM="${RAM:-512}"                      # MB
DISK="${DISK:-6}"                      # GB
BRIDGE="${BRIDGE:-vmbr0}"
STORAGE="${STORAGE:-local-lvm}"        # rootfs storage (pvesm status)
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
IPCONFIG="${IPCONFIG:-dhcp}"           # "dhcp" or e.g. "192.168.1.50/24,gw=192.168.1.1"
UNPRIVILEGED="${UNPRIVILEGED:-1}"
ONBOOT="${ONBOOT:-1}"
START_PORT="${PORT:-8000}"

REPO_URL="${REPO_URL:-https://github.com/skyhell/stp-maintenance-log.git}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"       # required only for a private repo
CT_PASSWORD="${CT_PASSWORD:-}"         # empty -> a random root password is generated

# ---------------- Helpers ----------------
c_blue='\033[1;34m'; c_green='\033[1;32m'; c_red='\033[1;31m'; c_yellow='\033[1;33m'; c_reset='\033[0m'
log()  { echo -e "${c_blue}[proxmox]${c_reset} $*"; }
ok()   { echo -e "${c_green}[ok]${c_reset} $*"; }
warn() { echo -e "${c_yellow}[warn]${c_reset} $*"; }
die()  { echo -e "${c_red}[error]${c_reset} $*" >&2; exit 1; }

# ---------------- Pre-flight checks ----------------
[[ $EUID -eq 0 ]] || die "Run this as root on the Proxmox host."
command -v pct   >/dev/null 2>&1 || die "'pct' not found — this must run on a Proxmox VE node."
command -v pveam >/dev/null 2>&1 || die "'pveam' not found — this must run on a Proxmox VE node."

if [[ -z "$CTID" ]]; then
  CTID="$(pvesh get /cluster/nextid)"
  log "Auto-selected next free VMID: ${CTID}"
fi
if pct status "$CTID" >/dev/null 2>&1; then
  die "Container ${CTID} already exists. Pass a different CTID."
fi

if [[ -z "$CT_PASSWORD" ]]; then
  CT_PASSWORD="$(openssl rand -base64 18 2>/dev/null || head -c 18 /dev/urandom | base64)"
  GENERATED_PW=1
fi

# ---------------- Ensure the Debian 12 template ----------------
log "Refreshing template catalog ..."
pveam update >/dev/null 2>&1 || warn "pveam update failed (continuing)."

TEMPLATE_NAME="$(pveam available --section system \
  | awk '/debian-12-standard/ {print $2}' | sort -V | tail -1)"
[[ -n "$TEMPLATE_NAME" ]] || die "No debian-12-standard template found in the catalog."

if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE_NAME"; then
  log "Downloading template ${TEMPLATE_NAME} to ${TEMPLATE_STORAGE} ..."
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE_NAME"
else
  ok "Template already present: ${TEMPLATE_NAME}"
fi
TEMPLATE_REF="${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE_NAME}"

# ---------------- Create the container ----------------
log "Creating LXC ${CTID} (${CT_HOSTNAME}: ${CORES} vCPU, ${RAM}MB RAM, ${DISK}GB disk) ..."
pct create "$CTID" "$TEMPLATE_REF" \
  --hostname "$CT_HOSTNAME" \
  --cores "$CORES" \
  --memory "$RAM" \
  --swap "$RAM" \
  --rootfs "${STORAGE}:${DISK}" \
  --net0 "name=eth0,bridge=${BRIDGE},ip=${IPCONFIG}" \
  --unprivileged "$UNPRIVILEGED" \
  --features nesting=1 \
  --onboot "$ONBOOT" \
  --password "$CT_PASSWORD" \
  --description "Sewage Treatment Plant Maintenance Log (stp-maintenance-log)"

ok "Container created."

log "Starting container ${CTID} ..."
pct start "$CTID"

# ---------------- Wait for network ----------------
log "Waiting for network inside the container ..."
for i in $(seq 1 30); do
  if pct exec "$CTID" -- getent hosts github.com >/dev/null 2>&1; then
    ok "Network is up."
    break
  fi
  sleep 2
  [[ $i -eq 30 ]] && die "Container did not get network/DNS within 60s."
done

# ---------------- Install the application inside the container ----------------
CLONE_URL="$REPO_URL"
if [[ -n "$GITHUB_TOKEN" ]]; then
  # Inject the token for a private clone (not persisted in the container).
  CLONE_URL="$(echo "$REPO_URL" | sed -E "s#https://#https://${GITHUB_TOKEN}@#")"
fi

log "Installing dependencies and cloning the application ..."
pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y --no-install-recommends git ca-certificates >/dev/null"

if ! pct exec "$CTID" -- bash -c "rm -rf /root/app-src && git clone --depth 1 '${CLONE_URL}' /root/app-src >/dev/null 2>&1"; then
  die "git clone failed. If the repo is private, pass GITHUB_TOKEN=... (or make the repo public)."
fi

log "Running the in-container installer (deploy/install.sh) ..."
pct exec "$CTID" -- bash -c "PORT=${START_PORT} bash /root/app-src/deploy/install.sh"

# Remove the token-bearing clone remote just in case, keep code.
pct exec "$CTID" -- bash -c "cd /root/app-src && git remote set-url origin '${REPO_URL}' 2>/dev/null || true"

# ---------------- Summary ----------------
IP="$(pct exec "$CTID" -- bash -c "hostname -I | awk '{print \$1}'" 2>/dev/null || echo '')"
echo
ok "Done! stp-maintenance-log is installed in LXC ${CTID} (${CT_HOSTNAME})."
echo "  ----------------------------------------------------------------"
echo "  Web UI:        http://${IP:-<container-ip>}:${START_PORT}"
echo "  App login:     admin / changeme    (CHANGE THIS IMMEDIATELY)"
if [[ "${GENERATED_PW:-0}" == "1" ]]; then
  echo "  CT root pw:    ${CT_PASSWORD}"
fi
echo "  Enter shell:   pct enter ${CTID}"
echo "  Service:       systemctl status stp-maintenance"
echo "  Logs:          pct exec ${CTID} -- journalctl -u stp-maintenance -f"
echo "  ----------------------------------------------------------------"
warn "Geolocation & voice input require HTTPS. Put a TLS reverse proxy in front"
warn "(see deploy/nginx.conf.example) and set SECURE_COOKIES=true in the .env."
