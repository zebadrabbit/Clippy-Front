# Sharing and mounting the instance directory (Samba, Linux, Windows/WSL2)

This guide shows how to share ClippyFront's `instance/` directory from a Linux server and mount it on Windows/WSL2 or another Linux machine. This is useful when a remote GPU worker needs to read/write media on the main server.

Goals
- Share the Linux server path (e.g., `/srv/clippy/instance`) over SMB (Samba)
- Restrict access to your WireGuard VPN subnet
- Mount the share from Windows (Explorer), Windows/WSL2 (CIFS), and Linux
- Bind the mounted path into Docker containers for Celery workers

Security note: avoid exposing SMB to the public internet. Restrict to your VPN subnet and trusted LANs.

## 1) Linux server: install and configure Samba

Install packages (Ubuntu/Debian):

```bash
sudo apt-get update && sudo apt-get install -y samba
```

Choose a canonical path for ClippyFront instance data (example):

```bash
sudo mkdir -p /srv/clippy/instance
sudo chown -R $USER:$USER /srv/clippy
```

Update ClippyFront to use this path (optional): run the app from the repo pointing `instance_path` to `/srv/clippy/instance` or move the repo's `instance/` contents there.

Samba configuration `/etc/samba/smb.conf` (append at end):

```ini
[global]
   workgroup = WORKGROUP
   server string = Clippy Samba Server
   map to guest = Bad User
   log file = /var/log/samba/log.%m
   max log size = 1000
   dns proxy = no
   unix extensions = no
   # Harden: only listen on WireGuard and loopback
   interfaces = 127.0.0.1/8 10.8.0.1/24
   bind interfaces only = yes
   # SMB protocol settings (modern clients)
   server min protocol = SMB2
   client min protocol = SMB2

[clippy-instance]
   comment = ClippyFront Instance
   path = /srv/clippy/instance
   browsable = yes
   read only = no
   create mask = 0644
   directory mask = 0755
   force user = clippy
   force group = clippy
   valid users = @clippyusers clippy
```

Create a dedicated user/group to own the share:

```bash
sudo groupadd -f clippyusers
sudo useradd -m -s /bin/bash clippy || true
sudo usermod -aG clippyusers clippy
sudo chown -R clippy:clippy /srv/clippy/instance

# Set a Samba password for the 'clippy' account
echo "Set a Samba password for user 'clippy'"
sudo smbpasswd -a clippy

# Test config and restart
sudo testparm
sudo systemctl enable smbd --now
```

Firewall restrictions (UFW):

```bash
sudo ufw allow from 10.8.0.0/24 to any app Samba
sudo ufw deny proto tcp to any port 445
sudo ufw deny proto udp to any port 137:138
```

Notes:
- `interfaces=10.8.0.1/24` makes Samba bind to your WireGuard interface only. Adjust to your WG server IP.
- `force user` ensures consistent ownership on files created via SMB.

## 2) Windows: map the share in Explorer

Assuming your WireGuard client is connected and the server is 10.8.0.1:

1. Open Explorer → This PC → Map network drive.
2. Folder: `\\10.8.0.1\clippy-instance`
3. Check "Connect using different credentials".
4. Enter username `clippy` and the Samba password you set.
5. Finish. A new drive letter maps to your instance path.

Troubleshooting:
- Ensure the Windows WireGuard tunnel is active and can ping 10.8.0.1.
- If mapping fails, try `net use * \\10.8.0.1\clippy-instance /user:clippy` in an elevated PowerShell.

## 3) Windows Subsystem for Linux (WSL2): CIFS mount

WSL2 can mount SMB shares directly so Linux paths are available to Docker on WSL2.

Create a credentials file (inside WSL2):

```bash
mkdir -p ~/.smb && chmod 700 ~/.smb
cat > ~/.smb/clippy.creds <<'EOF'
username=clippy
password=YOUR_SAMBA_PASSWORD
domain=WORKGROUP
EOF
chmod 600 ~/.smb/clippy.creds
```

Mount the share to `/mnt/clippy`:

```bash
sudo mkdir -p /mnt/clippy
sudo mount -t cifs //10.8.0.1/clippy-instance /mnt/clippy \
  -o vers=3.0,credentials=/home/$USER/.smb/clippy.creds,uid=$(id -u),gid=$(id -g),file_mode=0644,dir_mode=0755
```

Persist the mount in `/etc/fstab` (inside WSL2):

```fstab
//10.8.0.1/clippy-instance  /mnt/clippy  cifs  vers=3.0,credentials=/home/%U/.smb/clippy.creds,uid=%U,gid=%U,file_mode=0644,dir_mode=0755  0  0
```

Using the mount in Docker (WSL2):

```bash
docker run --rm --gpus all \
  -e CELERY_BROKER_URL=redis://10.8.0.1:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0 \
  -e DATABASE_URL=postgresql://<user>:<pass>@10.8.0.1/clippy_front \
  -e TMPDIR=/app/instance/tmp \
  -v /mnt/clippy:/app/instance \
  --name clippy-gpu-worker clippyfront-gpu-worker:latest
```

Tip: set `TMPDIR=/app/instance/tmp` to keep temp files and outputs on the same filesystem and avoid EXDEV on CIFS.

## 4) Linux client: CIFS mount

Install CIFS utilities and mount:

```bash
sudo apt-get install -y cifs-utils
sudo mkdir -p /mnt/clippy
sudo mount -t cifs //10.8.0.1/clippy-instance /mnt/clippy \
  -o vers=3.0,username=clippy,password='YOUR_SAMBA_PASSWORD',file_mode=0644,dir_mode=0755
```

Recommended: use a credentials file and specify `uid`, `gid` for correct ownership mapping.

Persist with `/etc/fstab`:

```fstab
//10.8.0.1/clippy-instance  /mnt/clippy  cifs  vers=3.0,credentials=/root/.smb/clippy.creds,uid=1000,gid=1000,file_mode=0644,dir_mode=0755  0  0
```

## 5) Docker bind mounts: patterns

Bind-mount the CIFS path into containers that need access:

```bash
docker run --rm \
  -v /mnt/clippy:/app/instance \
  your-image:tag
```

Compose example:

```yaml
services:
  gpu-worker:
    image: clippyfront-gpu-worker:latest
    deploy: {}
    environment:
      - CELERY_BROKER_URL=redis://10.8.0.1:6379/0
      - CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0
      - DATABASE_URL=postgresql://<user>:<pass>@10.8.0.1/clippy_front
      - TMPDIR=/app/instance/tmp
    volumes:
      - /mnt/clippy:/app/instance
    command: ["celery", "-A", "app.tasks.celery_app", "worker", "-Q", "gpu", "--loglevel=info"]
```

## 6) Troubleshooting

- Cannot write to share: check permissions on `/srv/clippy/instance` and `force user` in `smb.conf`. Ensure the Samba user matches ownership or use `uid`/`gid` mount options.
- Windows cannot map drive: verify WireGuard is connected; try `\\10.8.0.1\clippy-instance` and correct credentials.
- Docker container sees empty dir on Windows: use the WSL2 CIFS mount path (`/mnt/clippy`) not a Windows UNC path.
- Cross-device link (EXDEV) errors: set `TMPDIR=/app/instance/tmp` in the worker so temp and final paths are on the same filesystem.
- Thumbnails/preview 404s after remote compiles: configure path aliasing on the web app:

```bash
export MEDIA_PATH_ALIAS_FROM=/app/instance/
export MEDIA_PATH_ALIAS_TO=/mnt/clippy/instance/
```

These allow the server to translate worker-produced paths when serving previews.
