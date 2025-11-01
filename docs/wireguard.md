# Secure cross-host networking with WireGuard

> Note
> WireGuard remains the recommended way to connect your web server and workers privately. For artifact delivery from workers to the ingest host, pair WireGuard with the rsync-over-SSH sidecar from `compose.worker.yaml` (see README → Deployment → Worker Setup). This avoids needing SMB shares just to transfer final outputs.

This guide sets up a private VPN between your Linux host (server) and your Windows workstation (client), so Redis, Postgres, and the GPU worker communicate over an encrypted tunnel instead of exposing ports on your LAN.

## Topology
- Linux host: runs the Flask web app, Redis, and Postgres (or any subset). Acts as WireGuard server.
- Windows workstation: runs the GPU worker in Docker. Acts as WireGuard client.
- Private VPN subnet: 10.8.0.0/24 (adjust if needed). Linux server = 10.8.0.1, Windows client = 10.8.0.2.

## 1) Linux: install and configure WireGuard

```
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y wireguard qrencode

# Create keys
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey | tee /etc/wireguard/server_public.key
chmod 600 /etc/wireguard/server_private.key

# Create /etc/wireguard/wg0.conf (write template, then inject key)
sudo tee /etc/wireguard/wg0.conf > /dev/null <<'EOF'
[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = REPLACE_SERVER_PRIVATE_KEY
# Optional: limit to specific NIC for bind
# BindAddress = 0.0.0.0
# Basic firewalling is recommended (see below)

# Add peer after you create client keys on Windows and paste them here
# [Peer]
# PublicKey = <CLIENT_PUBLIC_KEY>
# AllowedIPs = 10.8.0.2/32
EOF

# Safely replace placeholder with actual private key (single-line)
sudo sed -i "s|REPLACE_SERVER_PRIVATE_KEY|$(sudo tr -d '\r' < /etc/wireguard/server_private.key)|" /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/wg0.conf
sudo chown root:root /etc/wireguard/wg0.conf

# Enable and start
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0

# Check status
sudo wg show

# If it fails to start, inspect logs:
#   journalctl -xeu wg-quick@wg0.service
# Common causes: malformed PrivateKey (extra quotes/newlines) or wrong permissions.
```

Firewall hardening (UFW example):
```
sudo ufw allow 51820/udp
# Restrict Redis and Postgres to VPN interface only (skip if using docker networks only)
sudo ufw deny in proto tcp to any port 6379
sudo ufw deny in proto tcp to any port 5432
# Optionally allow from VPN subnet explicitly
sudo ufw allow from 10.8.0.0/24 to any port 6379 proto tcp
sudo ufw allow from 10.8.0.0/24 to any port 5432 proto tcp
```

Redis bind:
- In /etc/redis/redis.conf, set `bind 127.0.0.1 10.8.0.1` and `protected-mode yes`. Restart Redis.

Postgres bind and auth:
- In postgresql.conf, set `listen_addresses = '10.8.0.1,localhost'`.
- In pg_hba.conf, add a line:
  - `host all all 10.8.0.0/24 md5`
- Reload Postgres.

## 2) Windows: install WireGuard and add a peer

- Install WireGuard for Windows: https://www.wireguard.com/install/
- Create a new tunnel and generate keys. Example client config:

```
[Interface]
PrivateKey = <CLIENT_PRIVATE_KEY>
Address = 10.8.0.2/24
DNS = 1.1.1.1

[Peer]
PublicKey = <SERVER_PUBLIC_KEY>
AllowedIPs = 10.8.0.0/24
Endpoint = <LINUX_PUBLIC_IP_OR_DDNS>:51820
PersistentKeepalive = 25
```

- On the Linux server, add the client as a peer:
```
sudo wg set wg0 peer <CLIENT_PUBLIC_KEY> allowed-ips 10.8.0.2/32
sudo wg show
```
- Activate the tunnel on Windows and ensure both sides show latest handshake.
- Test ping from Windows: `ping 10.8.0.1`; from Linux: `ping 10.8.0.2`.

## 3) Linux client alternative

On another Linux machine (e.g., a headless GPU host), install WireGuard:

```bash
sudo apt-get update && sudo apt-get install -y wireguard

sudo wg genkey | tee ~/client_private.key | wg pubkey | tee ~/client_public.key
CLIENT_PRIV=$(cat ~/client_private.key)
CLIENT_PUB=$(cat ~/client_public.key)

sudo tee /etc/wireguard/wg0.conf > /dev/null <<EOF
[Interface]
PrivateKey = $CLIENT_PRIV
Address = 10.8.0.3/24
DNS = 1.1.1.1

[Peer]
PublicKey = <SERVER_PUBLIC_KEY>
AllowedIPs = 10.8.0.0/24
Endpoint = <LINUX_PUBLIC_IP_OR_DDNS>:51820
PersistentKeepalive = 25
EOF

# Add client to server peer list
echo "Remember to add the client public key on the server:"
echo "sudo wg set wg0 peer $CLIENT_PUB allowed-ips 10.8.0.3/32"

sudo systemctl enable wg-quick@wg0 --now
sudo wg show
```

### Optional: IP forwarding / NAT
If you need the server to route traffic from the VPN to other networks (rare in this setup), enable IP forwarding and add NAT rules. For our use (service-to-service over VPN), it’s typically unnecessary.

## 4) Point ClippyFront services at the VPN IPs

Update environment variables so all components talk over the VPN subnet.

- On the Windows GPU worker (Docker run):
```
# Replace 10.8.0.1 with your Linux WireGuard server IP
-e CELERY_BROKER_URL=redis://10.8.0.1:6379/0 \
-e CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0 \
-e REDIS_URL=redis://10.8.0.1:6379/0 \
-e DATABASE_URL=postgresql://<user>:<pass>@10.8.0.1/clippy_front \
```

- On the Linux web app, set the same endpoints (or localhost if Redis/Postgres are on the same server but reachable via 10.8.0.1 for the worker):
```
CELERY_BROKER_URL=redis://10.8.0.1:6379/0
CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0
DATABASE_URL=postgresql://<user>:<pass>@10.8.0.1/clippy_front
```

Troubleshooting: worker still tries localhost for Postgres
- The worker image defaults to FLASK_ENV=production. In production, the config uses DATABASE_URL only; DEV_DATABASE_URL is ignored. If DATABASE_URL is unset or empty, it can fall back to postgresql://user:password@localhost/…
- Ensure you pass DATABASE_URL explicitly on docker run (or in compose env) pointing to 10.8.0.1.
- Validate inside the running container:
  - Print effective config via logs: the worker will log a line like: `Database: postgresql://10.8.0.1:5432/clippy_front (redacted user/pass)`
  - Manual probe (replace creds):
```
docker exec -it clippy-gpu-worker python - <<'PY'
import os, sys
import psycopg2
url = os.environ.get('DATABASE_URL')
print('Env DATABASE_URL =', url)
try:
    conn = psycopg2.connect(url)
    cur = conn.cursor(); cur.execute('SELECT 1'); print('psql ok:', cur.fetchone())
except Exception as e:
    print('psql failed:', e)
    sys.exit(1)
PY
```
If you still see localhost in errors, re-check your run command and .env precedence. Prefer passing DATABASE_URL directly on the docker run line.

## 5) Database choice

Use PostgreSQL for all environments (recommended/required outside unit tests). The previous SQLite-over-SMB option is discouraged and no longer supported in default configs.

## 6) Test end-to-end
- Ensure `wg show` reports handshakes on both ends.
- From the Windows container, verify Redis connectivity:
```
docker exec -it clippy-gpu-worker python -c "import redis; print(redis.Redis.from_url('redis://10.8.0.1:6379/0').ping())"
```
- Trigger a compile in the app; watch the worker logs. You should see tasks picked up from the `gpu` queue and the DB queries succeeding against 10.8.0.1.

## 7) Security notes
- Keep WireGuard keys secret. Restrict UDP 51820 on the Linux host to your client IPs if possible.
- Do not expose Redis/Postgres publicly; bind to localhost and the wg0 address only.
- Rotate credentials regularly; prefer strong Postgres passwords and disable unused accounts.
