# Remote GPU Worker Setup (No Docker)

This guide explains how to run a Celery GPU worker on a remote machine without Docker, using rsync to keep the code synchronized.

## Architecture Overview

```
[Your Dev Machine]  ──rsync──>  [Remote Worker: e.g., 192.168.1.119:2222]
     ↓                                ↓
   Flask App ←────── Redis ─────> Celery Worker
     ↓                                ↓
  PostgreSQL                    GPU (NVENC)
     ↓                                ↓
 Shared Storage <────────────────────┘
 (/mnt/clippyfront)
```

The worker needs:
1. **Redis connection** - Task queue (broker + backend)
2. **Flask API access** - Worker API endpoints (v0.12.0+)
3. **Shared storage** - Same mount point as Flask app for media files
4. **GPU access** - NVIDIA GPU with NVENC for hardware encoding

## Prerequisites on Remote Worker

### 1. System Dependencies

```bash
# On remote machine (Ubuntu/Debian)
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip \
  ffmpeg \
  curl \
  nvidia-driver-XXX  # If not already installed
```

### 2. Verify GPU/NVENC

```bash
# Check NVIDIA driver
nvidia-smi

# Check ffmpeg NVENC support
ffmpeg -hide_banner -encoders | grep nvenc
# Should show: h264_nvenc, hevc_nvenc, etc.
```

### 3. Mount Shared Storage

Ensure the same storage path used by the Flask app is mounted on the remote worker:

```bash
# Example: Mount via NFS
sudo mkdir -p /mnt/clippyfront
sudo mount -t nfs 192.168.1.100:/srv/clippyfront /mnt/clippyfront

# Or via SMB/CIFS
sudo mount -t cifs //192.168.1.100/clippyfront /mnt/clippyfront \
  -o username=winter,uid=$(id -u),gid=$(id -g)

# Make permanent by adding to /etc/fstab
```

Verify the mount contains the Flask app's instance data:

```bash
ls -la /mnt/clippyfront/
# Should show: data/ assets/ logs/ tmp/
```

## Setup Steps

### 1. Generate Worker API Key

On your dev machine (where Flask app runs):

```bash
# Generate a secure API key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Add this to your Flask app `.env`:

```bash
# In Flask app .env
WORKER_API_KEY=<generated-key>
```

Restart your Flask app to pick up the new key.

### 2. Initial Sync to Remote

On your dev machine:

```bash
# Sync the repo to remote worker
scripts/worker/sync-to-remote.sh winter@192.168.1.119:2222
```

This will sync the code to `winter@192.168.1.119:~/ClippyFront`, excluding:
- Virtual environments
- Cache directories
- Instance data (since it's on shared storage)
- Binary assets (ffmpeg, yt-dlp - install these on remote)

### 3. Configure Worker on Remote

SSH into the remote machine:

```bash
ssh -p 2222 winter@192.168.1.119
cd ~/ClippyFront
```

Create worker configuration:

```bash
# Copy the example config
cp .env.worker.example .env.worker

# Edit with your actual values
nano .env.worker
```

**Required edits in `.env.worker`:**

```bash
# Point to your Redis instance (Flask app host)
CELERY_BROKER_URL=redis://192.168.1.100:6379/0
CELERY_RESULT_BACKEND=redis://192.168.1.100:6379/0

# Point to your Flask app
FLASK_APP_URL=http://192.168.1.100:5000

# Use the SAME API key you set in Flask app .env
WORKER_API_KEY=<same-key-from-step-1>

# Shared storage mount point on remote worker
CLIPPY_INSTANCE_PATH=/mnt/clippyfront
HOST_INSTANCE_PATH=/mnt/clippyfront

# GPU worker configuration
CELERY_QUEUES=gpu,celery
CELERY_CONCURRENCY=2
USE_GPU_QUEUE=true
```

### 4. Start the Worker

On the remote machine:

```bash
cd ~/ClippyFront
./scripts/worker/run-worker-remote.sh
```

The script will:
1. Create/activate a Python venv
2. Install dependencies from `requirements.txt`
3. Load `.env.worker`
4. Start Celery worker listening to `gpu,celery` queues

You should see:

```
========================================
Starting Celery GPU Worker
========================================
Broker:    redis://192.168.1.100:6379/0
Backend:   redis://192.168.1.100:6379/0
Flask API: http://192.168.1.100:5000
Instance:  /mnt/clippyfront
Queues:    gpu,celery
Concurrency: 2
========================================

 -------------- celery@remote-gpu v5.x.x
...
[tasks]
  . app.tasks.compile_video_v2.compile_video_v2
  . app.tasks.download_clip_v2.download_clip_v2
  ...
```

## Running as a Service (systemd)

To keep the worker running persistently:

### 1. Create systemd service file

On the remote machine:

```bash
sudo nano /etc/systemd/system/clippy-worker.service
```

```ini
[Unit]
Description=ClippyFront GPU Celery Worker
After=network.target

[Service]
Type=simple
User=winter
Group=winter
WorkingDirectory=/home/winter/ClippyFront
Environment="PATH=/home/winter/ClippyFront/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/winter/ClippyFront/scripts/worker/run-worker-remote.sh
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 2. Enable and start service

```bash
sudo systemctl daemon-reload
sudo systemctl enable clippy-worker
sudo systemctl start clippy-worker

# Check status
sudo systemctl status clippy-worker

# View logs
sudo journalctl -u clippy-worker -f
```

## Maintenance & Updates

### Syncing Code Changes

When you make changes on your dev machine:

```bash
# On dev machine
scripts/worker/sync-to-remote.sh winter@192.168.1.119:2222

# Then on remote, restart the worker
sudo systemctl restart clippy-worker
# Or if running manually: Ctrl+C and re-run the script
```

### Watching for Changes (Development)

For active development, you can use `watch` or `fswatch` to auto-sync:

```bash
# On dev machine (simple polling)
export REMOTE_HOST=192.168.1.119
export REMOTE_USER=winter
export REMOTE_PORT=2222

while true; do
  scripts/worker/sync-to-remote.sh
  sleep 60
done
```

Or create a more sophisticated watcher with `inotifywait`:

```bash
#!/bin/bash
# scripts/worker/watch-and-sync.sh
inotifywait -m -r -e modify,create,delete \
  --exclude '(venv|__pycache__|\.git|instance/data)' \
  /home/winter/work/ClippyFront | \
while read; do
  scripts/worker/sync-to-remote.sh
done
```

## Troubleshooting

### Worker not picking up tasks

1. **Check queue configuration:**
   ```bash
   # On remote worker
   celery -A app.tasks.celery_app inspect active_queues
   ```
   Should show `gpu` and `celery` queues.

2. **Check Flask app routing:**
   In Flask app `.env`, ensure:
   ```bash
   USE_GPU_QUEUE=true
   ```

3. **Verify Redis connectivity:**
   ```bash
   redis-cli -h 192.168.1.100 ping
   # Should return: PONG
   ```

### API authentication errors (401)

- Verify `WORKER_API_KEY` matches between Flask app and worker `.env`
- Check Flask app logs for authentication errors
- Ensure Flask app is v0.12.0+ (has worker API endpoints)

### Shared storage issues

1. **Files not found:**
   ```bash
   # Verify mount on remote
   df -h /mnt/clippyfront
   ls -la /mnt/clippyfront/data/
   ```

2. **Permission errors:**
   ```bash
   # Ensure winter user can write
   touch /mnt/clippyfront/test.txt
   rm /mnt/clippyfront/test.txt
   ```

3. **EXDEV errors (cross-device link):**
   - Set `TMPDIR=/mnt/clippyfront/tmp` in `.env.worker`
   - This keeps temp files on the same filesystem

### NVENC not detected

```bash
# Check ffmpeg build
ffmpeg -hide_banner -encoders | grep nvenc

# If missing, rebuild ffmpeg with NVENC support or install from PPA:
sudo add-apt-repository ppa:graphics-drivers/ppa
sudo apt update
sudo apt install ffmpeg
```

### High memory usage

- Reduce `CELERY_CONCURRENCY` to 1 for compilation tasks
- GPU compilation tasks are memory-intensive

## Performance Tips

1. **Dedicated GPU worker:**
   - Set `CELERY_QUEUES=gpu` (only listen to GPU queue)
   - Run a separate CPU worker for downloads

2. **Concurrency tuning:**
   - Compilation: `CELERY_CONCURRENCY=1` or `2`
   - Downloads: `CELERY_CONCURRENCY=4` to `8`

3. **Network optimization:**
   - Use gigabit Ethernet between machines
   - Consider WireGuard VPN for secure remote workers (see `docs/WIREGUARD.MD`)

4. **Storage optimization:**
   - Use NFS for best performance
   - If using SMB/CIFS, mount with `cache=loose` for better performance
   - Ensure network storage can handle video bitrates (50+ MB/s)

## Alternative: Using Docker on Remote

If you prefer Docker on the remote machine:

```bash
# On remote
cd ~/ClippyFront
docker pull ghcr.io/zebadrabbit/clippy-worker:latest

# Use the Docker Compose workflow instead
cp .env.worker.example .env
docker compose -f docker/compose.worker.yaml up -d
```

See `docs/WORKER_SETUP.MD` for Docker-based worker setup.

## Security Considerations

1. **API Key Security:**
   - Keep `WORKER_API_KEY` secret
   - Rotate periodically
   - Never commit to git

2. **Network Security:**
   - Workers should only access Redis and Flask API
   - Use firewall rules to restrict access
   - Consider WireGuard for remote workers over untrusted networks

3. **Shared Storage:**
   - Use NFS with proper export restrictions
   - Or use authenticated SMB/CIFS mounts
   - Ensure worker user has minimal necessary permissions

## Related Documentation

- `docs/WORKER_SETUP.MD` - Docker-based worker setup
- `docs/WORKER_API_MIGRATION.MD` - Worker API architecture
- `docs/WIREGUARD.MD` - WireGuard VPN setup for remote workers
- `.env.example` - Full environment variable reference
