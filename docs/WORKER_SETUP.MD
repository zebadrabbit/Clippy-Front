# Worker Setup - Quick Start

## Current Architecture (v0.12.0+ - API-Based, DMZ Compliant)

Workers now communicate **100% via REST API** - no database credentials required! This enables deployment in untrusted DMZ environments.

### Required Environment Variables

Create a `.env` file in your worker directory (see `.env.worker.example` for all options):

```bash
# Celery/Redis
CELERY_BROKER_URL=redis://your-redis:6379/0
CELERY_RESULT_BACKEND=redis://your-redis:6379/0

# Worker API (v0.12.0+)
FLASK_APP_URL=https://your-flask-server.com
WORKER_API_KEY=your-secure-worker-api-key

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

# Generate a secure worker API key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Pull latest worker image from GHCR
docker pull ghcr.io/zebadrabbit/clippy-worker:latest

# Start worker with compose
docker compose -f compose.worker.yaml up -d worker artifact-sync
```

### Security Considerations

API-based workers are **DMZ compliant**:

1. **No database credentials** - Workers never touch the database
2. **API key authentication** - All communication secured via `WORKER_API_KEY`
3. **Isolated deployment** - Can run in completely untrusted environments
4. **Minimal attack surface** - Workers only have access to:
   - Redis (for task queue)
   - Flask app API endpoints (authenticated)
   - Shared storage volume (read/write for media files)

### API Endpoints Used by Workers

Workers communicate via these authenticated endpoints (see `docs/WORKER_API_MIGRATION.MD` for details):

- `GET /api/worker/clips/<id>` - Fetch clip metadata for downloads
- `POST /api/worker/clips/<id>/status` - Update download status
- `POST /api/worker/clips/download` - Batch download validation
- `GET /api/worker/media/<id>` - Fetch media file metadata
- `POST /api/worker/media` - Create media file records
- `POST /api/worker/media/batch` - Batch fetch media files
- `GET /api/worker/projects/<id>` - Fetch project metadata
- `GET /api/worker/projects/<id>/compilation-context` - Batch fetch compilation data
- `PUT /api/worker/projects/<id>/status` - Update project status
- `POST /api/worker/jobs` - Create processing job
- `PUT /api/worker/jobs/<id>` - Update job progress
- `GET /api/worker/jobs/<id>` - Get job metadata
- `GET /api/worker/users/<id>/quota` - Get user storage quota
- `GET /api/worker/users/<id>/tier-limits` - Get tier limits
- `POST /api/worker/users/<id>/record-render` - Record render usage

### Troubleshooting

**Error: "Missing WORKER_API_KEY or FLASK_APP_URL"**
- Missing required API configuration in worker `.env`
- Copy `.env.worker.example` to `.env` and fill in `FLASK_APP_URL` and `WORKER_API_KEY`
- Generate API key with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

**Error: "Worker API authentication failed (401)"**
- `WORKER_API_KEY` in worker `.env` doesn't match Flask app configuration
- Verify the same key is set in both Flask app and worker environments
- Check Flask app logs for authentication errors

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

**API endpoint errors (404, 500)**
- Verify `FLASK_APP_URL` is correct and accessible from worker
- Check Flask app is running and healthy
- Review Flask app logs for endpoint errors
- Ensure Flask app is v0.12.0+ (older versions don't have all worker API endpoints)

## Migration from v0.11.x (Database-Based Workers)

If upgrading from workers that used `DATABASE_URL`:

1. **Update worker image** to v0.12.0+:
   ```bash
   docker pull ghcr.io/zebadrabbit/clippy-worker:latest
   ```

2. **Update `.env`** file:
   - Remove: `DATABASE_URL`
   - Add: `FLASK_APP_URL=https://your-flask-server.com`
   - Add: `WORKER_API_KEY=your-secure-key`

3. **Set Flask app environment**:
   ```bash
   # In Flask app .env
   WORKER_API_KEY=same-secure-key-as-workers
   ```

4. **Restart workers**:
   ```bash
   docker compose -f compose.worker.yaml down
   docker compose -f compose.worker.yaml up -d
   ```

All tasks now use API-based communication automatically (download_clip_v2, compile_video_v2).

## Architecture Details

## Architecture Details

### Worker API Migration (Completed v0.12.0)

- ✅ Phase 1-2: API infrastructure (19 endpoints, 16 client functions)
- ✅ Phase 3: Download task migration (download_clip_v2)
- ✅ Phase 4: Compilation task migration (compile_video_v2)
- ✅ Phase 5: Production cutover (all tasks use v2)

See `docs/WORKER_API_MIGRATION.MD` for complete migration details.

### Benefits of API-Based Architecture

- ✅ Workers truly isolated from database (DMZ compliant)
- ✅ No database connection pooling issues
- ✅ Better security (workers can't directly modify sensitive data)
- ✅ Easier to scale workers horizontally
- ✅ Can run workers in completely untrusted environments
- ✅ Simplified worker deployment (fewer credentials to manage)

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
- `FLASK_APP_URL` (v0.12.0+)
- `WORKER_API_KEY` (v0.12.0+)
- `HOST_INSTANCE_PATH`

**Important:**
- `CELERY_CONCURRENCY` - Number of parallel tasks
- `CELERY_QUEUES` - Which queues to listen to
- `USE_GPU_QUEUE` - Use GPU for compilation

See `docs/gpu-worker.md` for detailed GPU worker setup and WSL2 NVENC configuration.
