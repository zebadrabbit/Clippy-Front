# Worker Setup - Quick Start

## Current Architecture (v1 - Database Access Required)

Workers currently need **direct database access** to function. This is a temporary limitation while we migrate to API-based communication.

### Required Environment Variables

Create a `.env` file in your worker directory (see `.env.worker.example` for all options):

```bash
# Celery/Redis
CELERY_BROKER_URL=redis://your-redis:6379/0
CELERY_RESULT_BACKEND=redis://your-redis:6379/0

# Database (REQUIRED)
DATABASE_URL=postgresql://clippy_worker:password@db-host:5432/clippy_front

# Storage
HOST_INSTANCE_PATH=/mnt/clippyfront
CLIPPY_INSTANCE_PATH=/app/instance

# Worker settings
CELERY_CONCURRENCY=4
CELERY_QUEUES=gpu,celery
USE_GPU_QUEUE=true
```

### Deploy Worker

```bash
# Copy example env
cp .env.worker.example .env

# Edit .env with your values
nano .env

# Pull latest worker image from GHCR
docker pull ghcr.io/zebadrabbit/clippy-worker:latest

# Start worker with compose
docker compose -f compose.worker.yaml up -d worker artifact-sync
```

### Security Considerations

Since workers have database access:

1. **Use a dedicated DB user** with minimal privileges:
   ```sql
   CREATE USER clippy_worker WITH PASSWORD 'secure-password';
   GRANT CONNECT ON DATABASE clippy_front TO clippy_worker;
   GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO clippy_worker;
   ```

2. **Restrict network access** via VPN/firewall:
   - Only allow worker IPs to connect to database
   - Use SSL for database connections
   - Monitor worker DB queries

3. **Plan migration** to API-based workers (see `WORKER_API_MIGRATION.md`)

### Troubleshooting

**Error: "Could not parse SQLAlchemy URL from string ''"**
- Missing `DATABASE_URL` in worker `.env`
- Copy `.env.worker.example` to `.env` and fill in database connection details

**Error: "Downloads not permitted on queue 'celery'"**
- Worker is listening to wrong queue
- Set `CELERY_QUEUES=gpu,celery` (or `cpu,celery`)

**Worker sees tasks but doesn't process them**
- Check `CELERY_CONCURRENCY` - if set to 1, worker processes one task at a time
- For downloads, increase to 4-8
- For GPU compilation, keep at 1-2

**Files not found / permission errors**
- Ensure `HOST_INSTANCE_PATH` matches Flask app's instance storage
- Check volume mounts in `compose.worker.yaml`
- Verify file permissions (worker runs as root by default)

## Future: API-Based Workers (v2)

The long-term plan is to eliminate database dependencies. Workers will communicate via API endpoints:

- ✅ API endpoints created (`/api/worker/*`)
- ✅ Worker API client library created (`app/tasks/worker_api.py`)
- ⏳ Task refactoring in progress (large effort)

See `WORKER_API_MIGRATION.md` for details.

### Benefits of API-Based Approach

- Workers truly isolated from database (DMZ compliant)
- No database connection pooling issues
- Better security (workers can't directly modify sensitive data)
- Easier to scale workers
- Can run workers in completely untrusted environments

## Quick Reference

### Common Commands

```bash
# View worker logs
docker compose -f compose.worker.yaml logs -f worker

# Restart worker
docker compose -f compose.worker.yaml restart worker

# Check worker status
docker compose -f compose.worker.yaml ps

# Inspect Celery queues
docker compose -f compose.worker.yaml exec worker \
  celery -A app.tasks.celery_app inspect active_queues

# Test NVENC detection (GPU workers)
docker compose -f compose.worker.yaml exec worker \
  ffmpeg -hide_banner -encoders | grep nvenc
```

### Environment Variables Reference

See `.env.worker.example` for complete list with descriptions.

**Required:**
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `DATABASE_URL`
- `HOST_INSTANCE_PATH`

**Important:**
- `CELERY_CONCURRENCY` - Number of parallel tasks
- `CELERY_QUEUES` - Which queues to listen to
- `USE_GPU_QUEUE` - Use GPU for compilation

**Artifact Export:**
- `WORKER_ID` - Unique worker identifier
- `INGEST_HOST` - Rsync destination host
- `INGEST_USER` - Rsync destination user
- `INGEST_PATH` - Rsync destination path

See `docs/gpu-worker.md` for detailed GPU worker setup and WSL2 NVENC configuration.
