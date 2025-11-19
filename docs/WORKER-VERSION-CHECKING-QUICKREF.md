# Worker Version Checking - Quick Reference

## Problem

**Stale workers steal tasks**: Old Docker containers or legacy workers can continue running after deployments, subscribing to the same queues and receiving tasks with incompatible code.

**Symptom**: Tasks mysteriously fail or only partial results appear (e.g., "4 clips queued, only 2 processed").

## Solution

1. **Check for stale workers**:
   ```bash
   ./scripts/check_stale_workers.sh
   ```

2. **Stop them**:
   ```bash
   ./scripts/check_stale_workers.sh --stop
   ```

3. **Or use the admin dashboard**:
   - Go to `/admin/workers`
   - Look for version mismatches or multiple workers on same queue
   - Use suggested `docker stop` commands

## Version Tagging (Recommended)

Start workers with version in the name:

```bash
# Get version
VERSION=$(python -c "from app.version import __version__; print(__version__)")

# Start worker with version tag
celery -A app.tasks.celery_app worker \
    -n celery-v${VERSION}@$(hostname) \
    -Q gpu,celery \
    --loglevel=info
```

**Benefits:**
- Admin dashboard shows version mismatches in yellow
- Easy to identify stale workers at a glance
- Prevents accidental version conflicts

## Quick Checks

**See all workers**:
```bash
python -c "from app.tasks.celery_app import celery_app; print(celery_app.control.inspect().active_queues())"
```

**Check admin API**:
```bash
curl -s http://localhost:5000/admin/api/workers | jq
```

**Find Docker workers**:
```bash
docker ps | grep celery
```

## Automatic Prevention

The Docker worker image (`docker/worker.Dockerfile`) now automatically embeds the version on startup. Just rebuild and redeploy:

```bash
docker build -f docker/worker.Dockerfile -t my-worker:latest .
docker-compose -f docker/compose.worker.yaml up -d
```

## See Also

- `/docs/WORKER-VERSION-CHECKING.md` - Full documentation
- `/admin/workers` - Web dashboard
- `/scripts/check_stale_workers.sh` - CLI checker
