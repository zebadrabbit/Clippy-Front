#!/usr/bin/env bash
set -euo pipefail

# Add a WireGuard client peer and emit a ready-to-use client config.
# Usage:
#   sudo bash scripts/wg_add_client.sh <client-name> [--interface wg0] [--ip 10.8.0.2/32] [--server-endpoint host:51820] [--dns 1.1.1.1]

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <client-name> [--interface wg0] [--ip 10.8.0.2/32] [--server-endpoint host:51820] [--dns 1.1.1.1]" >&2
  exit 1
fi

CLIENT_NAME="$1"; shift || true
IFACE="wg0"
CLIENT_IP="10.8.0.2/32"
SERVER_ENDPOINT=""
DNS="1.1.1.1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interface) IFACE="$2"; shift 2;;
    --ip) CLIENT_IP="$2"; shift 2;;
    --server-endpoint) SERVER_ENDPOINT="$2"; shift 2;;
    --dns) DNS="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)" >&2
  exit 1
fi

WG_DIR="/etc/wireguard"
CONF="$WG_DIR/${IFACE}.conf"
if [[ ! -f "$CONF" ]]; then
  echo "Server config not found: $CONF. Run scripts/wg_setup_server.sh first." >&2
  exit 1
fi

SERVER_PUB_KEY=$(wg show "$IFACE" public-key)
if [[ -z "$SERVER_ENDPOINT" ]]; then
  echo "--server-endpoint not provided. Example: your.public.ip:51820" >&2
  exit 1
fi

CLIENT_DIR="$WG_DIR/clients/${CLIENT_NAME}"
mkdir -p "$CLIENT_DIR"
chmod 700 "$CLIENT_DIR"

CLIENT_PRIV="$CLIENT_DIR/private.key"
CLIENT_PUB="$CLIENT_DIR/public.key"
if [[ -f "$CLIENT_PRIV" ]]; then
  echo "Client keys already exist for $CLIENT_NAME in $CLIENT_DIR" >&2
else
  umask 077
  wg genkey | tee "$CLIENT_PRIV" | wg pubkey > "$CLIENT_PUB"
  chmod 600 "$CLIENT_PRIV"
fi

PUB=$(cat "$CLIENT_PUB")

echo "Adding peer to $CONF"
wg set "$IFACE" peer "$PUB" allowed-ips "$CLIENT_IP"

echo "Saving config to $CONF (persistent)"
cat >> "$CONF" <<EOF

[Peer]
PublicKey = $PUB
AllowedIPs = $CLIENT_IP
EOF

systemctl restart wg-quick@"$IFACE"

CLIENT_ADDR_NO_MASK=${CLIENT_IP%/*}

echo "Emitting client config: $CLIENT_DIR/${CLIENT_NAME}.conf"
cat > "$CLIENT_DIR/${CLIENT_NAME}.conf" <<EOF
[Interface]
PrivateKey = $(cat "$CLIENT_PRIV")
Address = ${CLIENT_IP}
DNS = ${DNS}

[Peer]
PublicKey = ${SERVER_PUB_KEY}
AllowedIPs = 10.8.0.0/24
Endpoint = ${SERVER_ENDPOINT}
PersistentKeepalive = 25
EOF

if command -v qrencode >/dev/null 2>&1; then
  echo "Client config QR (for mobile):"
  qrencode -t ansiutf8 < "$CLIENT_DIR/${CLIENT_NAME}.conf" || true
fi

echo "Client files:"
ls -l "$CLIENT_DIR"
echo "Done. Distribute ${CLIENT_DIR}/${CLIENT_NAME}.conf to the client."
