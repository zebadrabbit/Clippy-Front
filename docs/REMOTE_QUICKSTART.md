# Running GPU Worker on Remote Machine (Quick Start)

Run the Celery GPU queue on a remote machine without Docker.

## Prerequisites

On your **remote worker machine**, ensure you have:
- Python 3.8+
- NVIDIA GPU with drivers installed
- ffmpeg with NVENC support
- Shared storage mounted at `/mnt/clippyfront` (same as Flask app)
- Network access to Redis and Flask app

## One-Time Setup

Run the interactive setup script from your dev machine:

```bash
# Example with specific host
scripts/worker/setup-remote.sh winter@192.168.1.119:2222

# Or with environment variables
export REMOTE_HOST=192.168.1.119
export REMOTE_USER=winter
export REMOTE_PORT=2222
scripts/worker/setup-remote.sh
```

This will:
1. ✓ Test SSH connectivity
2. ✓ Generate Worker API key
3. ✓ Sync repo to tundra
4. ✓ Create `.env.worker` configuration
5. ✓ Verify storage, Redis, and GPU

**Important:** Add the generated `WORKER_API_KEY` to your Flask app `.env` and restart the app.

## Start the Worker

SSH into the remote machine and start the worker:

```bash
ssh -p 2222 winter@192.168.1.119
cd ~/ClippyFront
./scripts/worker/run-worker-remote.sh
```

Or use the management script from your dev machine:

```bash
# Start worker remotely
scripts/worker/remote start winter@192.168.1.119:2222

# Check status
scripts/worker/remote status winter@192.168.1.119:2222

# View logs
scripts/worker/remote logs winter@192.168.1.119:2222
```

## Management Commands

The `scripts/worker/remote` script provides convenient shortcuts:

```bash
# Set connection info once
export REMOTE_HOST=192.168.1.119
export REMOTE_USER=winter
export REMOTE_PORT=2222

# Sync code changes to remote
scripts/worker/remote sync

# Start/stop/restart worker
scripts/worker/remote start
scripts/worker/remote stop
scripts/worker/remote restart

# Monitor
scripts/worker/remote logs      # Tail logs
scripts/worker/remote status    # Check if running
scripts/worker/remote inspect   # Show Celery queues
scripts/worker/remote gpu       # Check GPU status

# SSH into remote
scripts/worker/remote shell
```

## Run as a Service (Optional)

To keep the worker running persistently, set it up as a systemd service on the remote machine:

```bash
# On the remote machine
sudo nano /etc/systemd/system/clippy-worker.service
```

Paste this content:

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
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable clippy-worker
sudo systemctl start clippy-worker
sudo systemctl status clippy-worker
```

## Development Workflow

### Making Code Changes

1. Edit code on your dev machine
2. Sync to remote: `scripts/worker/remote sync`
3. Restart worker: `scripts/worker/remote restart`

### Continuous Sync (Optional)

For active development, run this on your dev machine to auto-sync every 60s:

```bash
# Set your remote info first
export REMOTE_HOST=192.168.1.119
export REMOTE_USER=winter
export REMOTE_PORT=2222

while true; do
  scripts/worker/remote sync
  sleep 60
done
```

## Troubleshooting

### Worker not picking up tasks

1. Check that Flask app has `USE_GPU_QUEUE=true` in `.env`
2. Verify worker is listening to correct queues:
   ```bash
   scripts/worker/remote inspect
   # Should show: gpu, celery
   ```
3. Check Redis connectivity from tundra:
   ```bash
   redis-cli -h <your-redis-host> ping
   ```

### API authentication errors (401)

- Ensure `WORKER_API_KEY` matches in both Flask app and worker `.env.worker`
- Check Flask app logs for auth errors

### Files not found

- Verify shared storage is mounted on remote:
  ```bash
  ssh -p 2222 winter@192.168.1.119 "ls -la /mnt/clippyfront/data/"
  ```
- Ensure mount point in `.env.worker` matches Flask app

### NVENC not working

- Check ffmpeg NVENC support:
  ```bash
  ssh -p 2222 winter@192.168.1.119 "ffmpeg -hide_banner -encoders | grep nvenc"
  ```
- If missing, install ffmpeg with NVENC or set `FFMPEG_DISABLE_NVENC=1`

## Configuration Files

- **On dev machine:**
  - `scripts/worker/sync-to-remote.sh` - Rsync script
  - `scripts/worker/remote` - Management commands
  - `scripts/worker/setup-remote.sh` - Interactive setup

- **On remote machine:**
  - `~/ClippyFront/.env.worker` - Worker configuration
  - `~/ClippyFront/scripts/worker/run-worker-remote.sh` - Start script

## Full Documentation

See `docs/REMOTE_WORKER_SETUP.md` for complete setup guide, systemd configuration, and advanced topics.

## Architecture

```
Dev Machine                     Remote Worker (e.g., 192.168.1.119:2222)
-----------                     -----------------------------------------
Flask App  ────Redis────────────> Celery Worker (GPU)
    │                                     │
    └──── Shared Storage (/mnt/clippyfront) ──┘
          (NFS/SMB/WireGuard)
```

Worker communicates via:
- **Redis** - Task queue (Celery broker/backend)
- **Worker API** - Flask REST endpoints (metadata, status updates)
- **Shared Storage** - Direct file access for media

No database credentials needed on worker! ✨
