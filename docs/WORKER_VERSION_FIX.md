# Worker Version Issues - Fix Guide

## Problem Summary

**Date:** 2025-11-20
**Server Version:** v0.13.0

### Issues Found

1. **Two pandalab workers without versions:**
   - `celery@pandalab-01` (PID 2465874) - No version tag
   - `main@pandalab-01` (PID 2666496) - No version tag

2. **Tundra worker has old version:**
   - `tundra-worker-01-v0.12.0@tundra` - Should be v0.13.0

### Root Causes

#### Pandalab Issue
Workers started without using `start-celery-versioned.sh`:
```bash
# Wrong (no version):
celery -A app.tasks.celery_app worker -Q celery --loglevel=info

# Wrong (no version):
celery -A app.tasks.celery_app worker -n main@%h -Q celery -c 2

# Correct (with version):
celery -A app.tasks.celery_app worker -n main-v0.13.0@%h -Q celery -c 2
```

#### Tundra Issue
The `run-worker-remote.sh` script uses **hardcoded hostname** instead of version-based naming:
```bash
# Current (WRONG):
exec celery -A app.tasks.celery_app worker \
  --hostname="tundra-gpu@%h"

# Should be (CORRECT):
VERSION=$(python -c "from app.version import __version__; print(__version__)")
exec celery -A app.tasks.celery_app worker \
  --hostname="tundra-gpu-v${VERSION}@%h"
```

## Immediate Fix Steps

### 1. Stop Unversioned Workers on Pandalab

```bash
# Kill old celery worker (PID 2465874)
kill 2465874

# Kill main worker without version (PID 2666496)
kill 2666496

# Wait for graceful shutdown
sleep 5

# Force kill if still running
pkill -f 'celery.*worker.*main@'
pkill -f 'celery -A app.tasks.celery_app worker -Q celery'
```

### 2. Start Versioned Worker on Pandalab

```bash
cd /home/winter/work/ClippyFront

# Option A: Using the versioned script (recommended)
./scripts/worker/start-celery-versioned.sh main "celery" 2

# Option B: Direct command with version
source venv/bin/activate
VERSION=$(python -c "from app.version import __version__; print(__version__)")
celery -A app.tasks.celery_app worker \
  -n "main-v${VERSION}@%h" \
  -Q celery \
  -c 2 \
  --loglevel=info
```

### 3. Fix and Restart Tundra Worker

**On pandalab (sync updated code):**
```bash
cd /home/winter/work/ClippyFront

# Sync to tundra (after fixing the script below)
./scripts/worker/sync-to-remote.sh winter@192.168.1.119:2222 ~/ClippyFront
```

**On tundra:**
```bash
# Stop old worker
pkill -f 'celery.*tundra-worker'

# Start new versioned worker
cd ~/ClippyFront
./scripts/worker/run-worker-remote.sh
```

## Permanent Fix - Update Scripts

### Fix 1: Update `run-worker-remote.sh`

**File:** `scripts/worker/run-worker-remote.sh`

**Change:**
```bash
# Before (line ~80):
exec celery -A app.tasks.celery_app worker \
  --loglevel=info \
  --concurrency="${CELERY_CONCURRENCY}" \
  --queues="${CELERY_QUEUES}" \
  --hostname="tundra-gpu@%h"

# After:
# Get version from app
VERSION=$(python -c "from app.version import __version__; print(__version__)")

if [[ -z "$VERSION" ]]; then
  echo "Error: Could not determine version from app.version" >&2
  exit 1
fi

# Build worker hostname with version
WORKER_NAME="${WORKER_NAME:-tundra-gpu}"
WORKER_HOSTNAME="${WORKER_NAME}-v${VERSION}@%h"

echo "Worker Version: ${VERSION}"
echo "Worker Hostname: ${WORKER_HOSTNAME}"

exec celery -A app.tasks.celery_app worker \
  --loglevel=info \
  --concurrency="${CELERY_CONCURRENCY}" \
  --queues="${CELERY_QUEUES}" \
  --hostname="${WORKER_HOSTNAME}"
```

### Fix 2: Create Systemd Service (Optional)

For automatic startup on pandalab:

**File:** `/etc/systemd/system/clippyfront-worker.service`
```ini
[Unit]
Description=ClippyFront Celery Worker (Versioned)
After=network.target redis.target

[Service]
Type=simple
User=winter
WorkingDirectory=/home/winter/work/ClippyFront
Environment="PATH=/home/winter/work/ClippyFront/venv/bin"
ExecStart=/home/winter/work/ClippyFront/scripts/worker/start-celery-versioned.sh main "celery" 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable clippyfront-worker
sudo systemctl start clippyfront-worker
```

## Verification

After fixes, verify all workers have versions:

```bash
cd /home/winter/work/ClippyFront
source venv/bin/activate

celery -A app.tasks.celery_app inspect active_queues
```

**Expected Output:**
```
-> main-v0.13.0@pandalab-01: OK
   * celery queue

-> tundra-gpu-v0.13.0@tundra: OK
   * gpu queue
   * celery queue
```

**Check via Python:**
```python
from app.worker_version_check import get_active_workers

workers = get_active_workers()
for name, info in workers.items():
    print(f"{name}: version={info['version']}, compatible={info['compatible']}")
```

**Expected:**
```
main-v0.13.0@pandalab-01: version=0.13.0, compatible=True
tundra-gpu-v0.13.0@tundra: version=0.13.0, compatible=True
```

## Additional Issue: Network Configuration

### Problem
Tundra worker was using `192.168.1.100` for Redis/Flask API, which is not routable from remote workers.

### Solution
Use WireGuard VPN network (`10.8.0.0/24`):
- Pandalab server: `10.8.0.1`
- Tundra worker: `10.8.0.2`

**Create `.env.worker` on tundra:**
```bash
# Copy template to tundra
scp -P 2222 /tmp/tundra.env.worker winter@192.168.1.119:~/ClippyFront/.env.worker

# Or create directly on tundra with correct WireGuard IPs:
# CELERY_BROKER_URL=redis://10.8.0.1:6379/0
# CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0
# FLASK_APP_URL=http://10.8.0.1:5000
```

**Test connectivity:**
```bash
# From tundra, test Redis via WireGuard
ssh -p 2222 winter@192.168.1.119 "cd ~/ClippyFront && source venv/bin/activate && python -c 'import redis; print(redis.Redis(host=\"10.8.0.1\").ping())'"
# Should print: True
```

See `docs/WIREGUARD.md` for complete VPN setup instructions.

## Why This Matters

Workers without version tags are marked **incompatible** by design:
- Prevents hidden workers from stealing tasks
- Ensures version consistency across distributed workers
- Allows safe parallel deployment (old + new workers during rollout)

From `app/worker_version_check.py`:
```python
# IMPORTANT: Treat unknown/null versions as INCOMPATIBLE
# This prevents hidden workers (e.g., Docker Desktop vs WSL2) from stealing tasks
compatible = False
reason = None

if version is None:
    # No version tag - incompatible (could be old/hidden worker)
    reason = "no_version_tag"
```

Unversioned workers **will not receive tasks** from the server, leading to:
- Stale compilations (tasks stuck in queue)
- Failed background processing
- User-facing errors

## Related Documentation

- `docs/worker-version-checking.md` - Full version checking system
- `docs/WORKER_SETUP.md` - Worker setup guide
- `scripts/worker/start-celery-versioned.sh` - Versioned worker starter
