#!/usr/bin/env bash
set -euo pipefail

# Samba share setup helper (Ubuntu/Debian)
# Usage:
#   sudo bash scripts/setup_samba_share.sh [--path /srv/clippy/instance] [--share clippy-instance] [--wg-subnet 10.8.0.0/24] [--user clippy]

SHARE_PATH="/srv/clippy/instance"
SHARE_NAME="clippy-instance"
WG_SUBNET="10.8.0.0/24"
SMB_USER="clippy"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path) SHARE_PATH="$2"; shift 2;;
    --share) SHARE_NAME="$2"; shift 2;;
    --wg-subnet) WG_SUBNET="$2"; shift 2;;
    --user) SMB_USER="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)" >&2
  exit 1
fi

echo "Installing Samba..."
apt-get update -y
apt-get install -y samba

mkdir -p "$SHARE_PATH"

echo "Creating user/group if missing"
getent group clippyusers >/dev/null || groupadd clippyusers
id -u "$SMB_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$SMB_USER"
usermod -aG clippyusers "$SMB_USER" || true
chown -R "$SMB_USER":"$SMB_USER" "$SHARE_PATH"

SMB_CONF="/etc/samba/smb.conf"
BACKUP="/etc/samba/smb.conf.bak.$(date +%s)"
cp "$SMB_CONF" "$BACKUP"
echo "Backed up $SMB_CONF to $BACKUP"

echo "Updating $SMB_CONF"
if ! grep -q "^\s*interfaces\s*=.*$" "$SMB_CONF"; then
  sed -i '/^\[global\]/a interfaces = 127.0.0.1/8 10.8.0.1/24\nbind interfaces only = yes\nserver min protocol = SMB2\nclient min protocol = SMB2' "$SMB_CONF"
fi

cat >> "$SMB_CONF" <<EOF

[$SHARE_NAME]
   comment = ClippyFront Instance
   path = $SHARE_PATH
   browsable = yes
   read only = no
   create mask = 0644
   directory mask = 0755
   force user = $SMB_USER
   force group = $SMB_USER
   valid users = @$SMB_USER $SMB_USER
EOF

echo "Reloading Samba"
systemctl enable smbd --now
systemctl restart smbd

echo
echo "Set a Samba password for user $SMB_USER (if not already):"
echo "  smbpasswd -a $SMB_USER"
echo
echo "UFW example (restrict to WireGuard subnet):"
echo "  ufw allow from $WG_SUBNET to any app Samba"
echo "  ufw deny proto tcp to any port 445"
echo "  ufw deny proto udp to any port 137:138"
echo
echo "Share available as: \\10.8.0.1\\$SHARE_NAME (adjust to your server's WG IP)"
echo "Done."
