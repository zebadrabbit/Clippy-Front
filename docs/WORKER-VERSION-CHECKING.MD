# Worker Version Checking

## Overview

ClippyFront now includes **worker version validation** to prevent stale or outdated Celery workers from accepting tasks. This prevents issues where old Docker containers or legacy workers consume tasks with incompatible code.

## Problem This Solves

**Before:** If you had a stale Docker worker container still running from a previous deployment, it would:
- Connect to the same Redis broker
- Subscribe to the same queues (e.g., `gpu`, `celery`)
- Receive tasks round-robin with the current workers
- Process tasks with **old/incompatible code**
- Cause mysterious failures ("only 2 of 4 clips reached the worker")

**After:** The admin dashboard shows all connected workers with their versions, highlights incompatible workers, and allows you to identify and stop stale containers.

## How It Works

### 1. Version Embedding in Worker Names

Workers can optionally include their version in the worker name:

```bash
# Standard worker (no version)
celery -A app.tasks.celery_app worker -n celery@%h -Q gpu,celery

# Version-embedded worker (recommended)
celery -A app.tasks.celery_app worker -n celery-v0.12.0@%h -Q gpu,celery
```

The system parses worker names in the format: `basename-v<version>@hostname`

### 2. Admin Dashboard Detection

The admin dashboard at `/admin/workers` now shows:
- **Server version** (current Flask app version)
- **Worker version** (parsed from worker name, or "unknown" for legacy)
- **Compatibility status** (matches/doesn't match server version)
- **Queues** each worker is subscribed to
- **Warning badges** for version mismatches

### 3. Programmatic Checking

You can also check worker versions programmatically:

```python
from app.worker_version_check import get_active_workers, check_queue_health

# Get all workers with version info
workers = get_active_workers(timeout=2.0)
for name, info in workers.items():
    print(f"{name}: version={info['version']}, compatible={info['compatible']}")

# Check if a queue has sufficient compatible workers
health = check_queue_health("gpu", min_workers=1)
print(f"GPU queue healthy: {health['healthy']}")
print(f"Compatible workers: {health['compatible_workers']}")
print(f"Incompatible workers: {health['incompatible_workers']}")
```

## Deployment Workflow

### Finding Stale Workers

1. **Check the admin dashboard:**
   - Go to `/admin/workers`
   - Look for workers with version mismatches (highlighted in yellow)

2. **Use the terminal:**
   ```bash
   # List all Docker containers
   docker ps -a | grep celery

   # Or inspect from within the app
   python -c "from app.tasks.celery_app import celery_app; print(celery_app.control.inspect().active_queues())"
   ```

### Stopping Stale Workers

```bash
# Find the container
docker ps | grep celery

# Stop and remove it
docker stop <container_id>
docker rm <container_id>

# Or stop all celery containers
docker stop $(docker ps -q -f name=celery)
```

### Starting Version-Tagged Workers

Update your worker startup scripts/compose files to include the version:

**Docker Compose:**
```yaml
services:
  worker:
    image: ghcr.io/zebadrabbit/clippy-worker:latest
    command: celery -A app.tasks.celery_app worker -n celery-v0.12.0@%h -Q gpu,celery
```

**Systemd Service:**
```ini
[Service]
ExecStart=/path/to/venv/bin/celery -A app.tasks.celery_app worker \
    -n celery-v0.12.0@%h \
    -Q gpu,celery \
    --loglevel=info
```

**Shell Script:**
```bash
#!/bin/bash
VERSION=$(python -c "from app.version import __version__; print(__version__)")
celery -A app.tasks.celery_app worker -n "celery-v${VERSION}@$(hostname)" -Q gpu,celery
```

## API Endpoints

### GET /admin/workers
Web UI showing all workers with version compatibility.

### GET /admin/workers.json
JSON endpoint for raw worker inspection data.

### GET /admin/api/workers
JSON API with enhanced version checking:

```json
{
  "server_version": "0.12.0",
  "workers": {
    "celery-v0.12.0@remote-host": {
      "queues": ["gpu", "celery"],
      "version": "0.12.0",
      "compatible": true
    },
    "celery@old-host": {
      "queues": ["gpu"],
      "version": null,
      "compatible": true
    }
  },
  "queue_health": {
    "gpu": {
      "healthy": true,
      "compatible_workers": 1,
      "incompatible_workers": 0
    }
  }
}
```

## Version Detection Logic

1. **Worker name parsing:**
   - `celery-v0.12.0@hostname` → version = "0.12.0"
   - `celery@hostname` → version = null (NO VERSION TAG)
   - `main@hostname` → version = null (NO VERSION TAG)

2. **Compatibility check:**
   - If worker has NO version (null) → **INCOMPATIBLE** ⚠️
     - Reason: Could be stale worker, hidden Docker instance, or legacy deployment
     - Prevents issues like Docker Desktop vs WSL2 workers stealing tasks
   - If worker has a version AND it doesn't match server version → **INCOMPATIBLE** ⚠️
   - If worker version matches server version → **COMPATIBLE** ✅

3. **Why NO version = incompatible:**
   - **Real-world example**: Docker Desktop (Windows) and WSL2 Docker both running workers
   - Hidden workers can steal tasks without being visible in normal checks
   - Forces explicit version tagging for all production workers
   - Better safe than sorry - unknown workers are suspect by default

## Integration with Existing Code

The version checking is **passive** - it doesn't block tasks or reject workers automatically. It only provides **visibility** and **warnings** in the admin dashboard.

If you want to actively reject tasks from incompatible workers, you could:
1. Add a custom task router that checks worker versions
2. Modify task queuing to only send to compatible workers
3. Add a periodic task that shuts down incompatible workers

For now, the system focuses on **detection and visibility** to help operators identify and fix version mismatches manually.

## Troubleshooting

### "No workers shown in dashboard"
- Check if Redis is running: `redis-cli ping`
- Check if workers are connected: `celery -A app.tasks.celery_app inspect active_queues`
- Verify network connectivity between Flask and workers

### "Worker shows as unknown version"
- Worker was started without version tag in name
- This is normal for legacy workers
- Restart worker with `-n celery-v0.12.0@%h` to add version

### "Version mismatch detected"
- A worker is running different code than the server
- Find and stop the stale worker: `docker ps | grep celery`
- Verify all workers are updated to the same version

### "Round-robin task distribution"
- If you have 2 workers on the same queue, Celery distributes tasks evenly
- Use different queues for different worker capabilities (gpu vs cpu)
- Stop unwanted workers to ensure tasks go to the right place

## Example: Detecting the "2 of 4 clips" Issue

**Symptom:** Flask queues 4 download tasks to `gpu` queue, but only 2 appear on the remote worker.

**Diagnosis:**
1. Check `/admin/workers` → See 2 workers with `gpu` queue
2. One worker: `celery-v0.12.0@remote-host` (compatible)
3. Other worker: `celery@46b9a1cf718a` (no version, local Docker hash)
4. Realization: Stale local Docker container from previous deployment

**Fix:**
```bash
docker ps -a | grep celery
# Output: 46b9a1cf718a  clippy-worker...

docker stop 46b9a1cf718a
docker rm 46b9a1cf718a

# Verify
curl http://localhost:5000/admin/api/workers | jq '.workers'
# Now only shows celery-v0.12.0@remote-host
```

**Result:** All 4 tasks now go to the correct remote worker.

## Files

- `app/worker_version_check.py` - Version parsing and compatibility checking
- `app/tasks/worker_heartbeat.py` - Worker startup/heartbeat tasks (future)
- `app/admin/routes.py` - Admin dashboard endpoints (updated)
- `app/templates/admin/workers.html` - Worker dashboard UI (updated)
- `docs/WORKER-VERSION-CHECKING.MD` - This file

## Future Enhancements

- [ ] Automatic heartbeat tasks that report version to Redis
- [ ] Active rejection of tasks from incompatible workers
- [ ] Alerts/notifications when version mismatches detected
- [ ] Worker auto-update mechanism
- [ ] Version compatibility matrix (allow certain version ranges)
