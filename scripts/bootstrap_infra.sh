#!/usr/bin/env bash
set -euo pipefail

# Bootstrap ClippyFront infra on a Linux host:
# - Sets up WireGuard server (keys + wg0.conf + service)
# - Sets up Samba share for the instance directory
# - Optionally creates a WireGuard client peer (e.g., gpu-worker)
# - Prints example docker run and compose snippets for the GPU worker
#
# Usage (run as root):
#   sudo bash scripts/bootstrap_infra.sh \
#     --wg-interface wg0 \
#     --wg-server 10.8.0.1/24 \
#     --wg-subnet 10.8.0.0/24 \
#     --wg-port 51820 \
#     --endpoint your.public.ip.or.ddns:51820 \
#     --dns 1.1.1.1 \
#     --samba-path /srv/clippy/instance \
#     --samba-user clippy \
#     --samba-share clippy-instance \
#     --client-name gpu-worker \
#     --client-ip 10.8.0.2/32

IFACE="wg0"
WG_SERVER_ADDR="10.8.0.1/24"
WG_SUBNET="10.8.0.0/24"
WG_PORT="51820"
WG_DNS="1.1.1.1"
ENDPOINT=""  # host:port

SAMBA_PATH="/srv/clippy/instance"
SAMBA_USER="clippy"
SAMBA_SHARE="clippy-instance"

CLIENT_NAME="gpu-worker"
CLIENT_IP="10.8.0.2/32"
CREATE_CLIENT=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wg-interface) IFACE="$2"; shift 2;;
    --wg-server) WG_SERVER_ADDR="$2"; shift 2;;
    --wg-subnet) WG_SUBNET="$2"; shift 2;;
    --wg-port) WG_PORT="$2"; shift 2;;
    --endpoint) ENDPOINT="$2"; shift 2;;
    --dns) WG_DNS="$2"; shift 2;;
    --samba-path) SAMBA_PATH="$2"; shift 2;;
    --samba-user) SAMBA_USER="$2"; shift 2;;
    --samba-share) SAMBA_SHARE="$2"; shift 2;;
    --client-name) CLIENT_NAME="$2"; shift 2;;
    --client-ip) CLIENT_IP="$2"; shift 2;;
    --no-client) CREATE_CLIENT=false; shift;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)" >&2
  exit 1
fi

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)

echo "[1/4] Setting up WireGuard server ($IFACE, $WG_SERVER_ADDR, port $WG_PORT)"
bash "$REPO_DIR/scripts/wg_setup_server.sh" \
  --interface "$IFACE" \
  --server "$WG_SERVER_ADDR" \
  --subnet "$WG_SUBNET" \
  --port "$WG_PORT" \
  --dns "$WG_DNS"

echo "[2/4] Setting up Samba share ($SAMBA_SHARE at $SAMBA_PATH)"
bash "$REPO_DIR/scripts/setup_samba_share.sh" \
  --path "$SAMBA_PATH" \
  --share "$SAMBA_SHARE" \
  --wg-subnet "$WG_SUBNET" \
  --user "$SAMBA_USER"

if $CREATE_CLIENT; then
  if [[ -z "$ENDPOINT" ]]; then
    echo "[3/4] Skipping client creation: --endpoint not provided."
  else
    echo "[3/4] Creating WireGuard client peer: $CLIENT_NAME ($CLIENT_IP)"
    bash "$REPO_DIR/scripts/wg_add_client.sh" "$CLIENT_NAME" \
      --interface "$IFACE" \
      --ip "$CLIENT_IP" \
      --server-endpoint "$ENDPOINT" \
      --dns "$WG_DNS"
  fi
else
  echo "[3/4] Skipping client creation (--no-client)"
fi

WG_HOST_IP=${WG_SERVER_ADDR%/*}

echo "[4/4] Example commands for the GPU worker (Windows/WSL2/Linux)"
cat <<EOC

# WSL2/Linux CIFS mount example (after Samba and WireGuard are up)
sudo mkdir -p /mnt/clippyfront
sudo mount -t cifs //${WG_HOST_IP}/${SAMBA_SHARE} /mnt/clippyfront \
  -o vers=3.0,username=${SAMBA_USER},password='<YOUR_SAMBA_PASSWORD>',file_mode=0644,dir_mode=0755

# Docker run example (GPU worker)
docker run --rm --gpus all \\
  -e CELERY_BROKER_URL=redis://${WG_HOST_IP}:6379/0 \\
  -e CELERY_RESULT_BACKEND=redis://${WG_HOST_IP}:6379/0 \\
  -e REDIS_URL=redis://${WG_HOST_IP}:6379/0 \\
  -e DATABASE_URL=postgresql://<user>:<pass>@${WG_HOST_IP}/clippy_front \\
  -e TMPDIR=/app/instance/tmp \\
  -v /mnt/clippyfront:/app/instance \\
  --name clippy-gpu-worker clippyfront-gpu-worker:latest

# Compose example file exists in docker/docker-compose.gpu-worker.example.yml
# Replace VPN_HOST_IP with ${WG_HOST_IP} and bind your CIFS mount to /app/instance.
EOC

echo "\nBootstrap complete. See docs/wireguard.md and docs/samba-and-mounts.md for details."
