#!/usr/bin/env bash
set -euo pipefail

# WireGuard server setup helper (Ubuntu/Debian)
# Usage:
#   sudo bash scripts/wg_setup_server.sh [--interface wg0] [--subnet 10.8.0.0/24] [--server 10.8.0.1/24] [--port 51820] [--dns 1.1.1.1]
#
# This script installs WireGuard, generates server keys, writes /etc/wireguard/<iface>.conf,
# enables and starts the service, and prints status. It is idempotent for key generation.

IFACE="wg0"
SUBNET="10.8.0.0/24"
SERVER_ADDR="10.8.0.1/24"
PORT="51820"
DNS="1.1.1.1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interface) IFACE="$2"; shift 2;;
    --subnet) SUBNET="$2"; shift 2;;
    --server) SERVER_ADDR="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --dns) DNS="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)" >&2
  exit 1
fi

echo "Installing WireGuard..."
apt-get update -y
apt-get install -y wireguard qrencode

WG_DIR="/etc/wireguard"
mkdir -p "$WG_DIR"
chmod 700 "$WG_DIR"

PRIV_KEY="$WG_DIR/server_private.key"
PUB_KEY="$WG_DIR/server_public.key"

if [[ ! -f "$PRIV_KEY" ]]; then
  umask 077
  wg genkey | tee "$PRIV_KEY" | wg pubkey > "$PUB_KEY"
  chmod 600 "$PRIV_KEY"
  echo "Generated server keys: $PRIV_KEY, $PUB_KEY"
else
  echo "Server keys already exist: $PRIV_KEY"
fi

CONF="$WG_DIR/${IFACE}.conf"
if [[ -f "$CONF" ]]; then
  echo "Config exists: $CONF (will not overwrite)."
else
  echo "Writing $CONF"
  SERVER_PRIV=$(tr -d '\r' < "$PRIV_KEY")
  cat > "$CONF" <<EOF
[Interface]
Address = ${SERVER_ADDR}
ListenPort = ${PORT}
PrivateKey = ${SERVER_PRIV}

# Add client peers below using scripts/wg_add_client.sh
EOF
  chmod 600 "$CONF"
fi

echo "Enabling and starting wg-quick@${IFACE}"
systemctl enable wg-quick@"$IFACE"
systemctl restart wg-quick@"$IFACE" || systemctl start wg-quick@"$IFACE"

echo "WireGuard status:"
wg show || true

echo
echo "Recommended UFW rules (optional):"
echo "  ufw allow ${PORT}/udp"
echo "  ufw allow from ${SUBNET} to any port 5432 proto tcp   # Postgres over VPN"
echo "  ufw allow from ${SUBNET} to any port 6379 proto tcp   # Redis over VPN"
echo
echo "Done. Use scripts/wg_add_client.sh to add clients."
