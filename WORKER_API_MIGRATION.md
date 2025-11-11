# Worker API Migration Guide

## Problem

Workers currently require direct database access, violating the DMZ security model where workers should be "outside the DMZ" and only communicate with the Flask app via API.

Current issues:
- `download_clip_task` (416 lines) uses `get_db_session()` extensively
- `compile_video_task` queries database for clips, media files, project settings
- ProcessingJob records created/updated directly in worker code
- Quota checks require database access

## Pragmatic Short-term Solution ⚡

**STATUS: Workers need DATABASE_URL for now**

The full refactoring is a **multi-week effort** (416-line download function, 800+ line compile function). For immediate functionality:

### Current Setup (Works, but violates DMZ):

**Worker `.env`:**
```bash
DATABASE_URL=postgresql://user:pass@db-host:5432/clippy_front  # Required for now
CELERY_BROKER_URL=redis://redis-host:6379/0
CELERY_RESULT_BACKEND=redis://redis-host:6379/0
FLASK_APP_URL=http://flask-server:5000  # For future API calls
WORKER_API_KEY=<secure-key>  # For future API calls
```

**Security mitigation:**
- Use read-only DB user for workers if possible
- Restrict worker DB access via firewall/VPN
- Monitor worker DB queries
- Plan migration to API-based (see Long-term Solution below)

### Why This Is Necessary:

1. `download_clip_task`: 416 lines, 50+ DB operations
2. `compile_video_task`: 800+ lines, 100+ DB operations
3. Heavy integration with SQLAlchemy ORM throughout
4. Quota checks, media file lookups, project metadata all DB-dependent

Refactoring estimate: **3-4 weeks of focused development + testing**

## Long-term Solution (API-based) 🎯

## Implementation Status

### ✅ Completed

1. **Created worker API endpoints** (`app/api/worker.py`):
   - `GET /api/worker/clips/<clip_id>` - Fetch clip metadata
   - `POST /api/worker/clips/<clip_id>/status` - Update clip status
   - `GET /api/worker/media/<media_id>` - Fetch media file metadata
   - `POST /api/worker/jobs` - Create processing job
   - `PUT /api/worker/jobs/<job_id>` - Update job progress/status
   - `GET /api/worker/projects/<project_id>` - Fetch project metadata

2. **Created worker API client** (`app/tasks/worker_api.py`):
   - Helper functions for workers to call Flask APIs
   - Handles authentication with `WORKER_API_KEY`
   - Functions: `get_clip_metadata()`, `update_clip_status()`, `create_processing_job()`, etc.

3. **Added configuration**:
   - `WORKER_API_KEY` in `config/settings.py`
   - `FLASK_APP_URL` for workers to know where to connect

4. **Registered routes**:
   - Worker endpoints auto-loaded in `app/api/routes.py`

### ⚠️ TODO

1. **Refactor `download_clip_task`** (328 lines, complex):
   - Remove `session = get_db_session()`
   - Replace all `session.query()` calls with `worker_api` calls
   - Remove ProcessingJob DB manipulation, use API instead
   - See `app/tasks/download_clip_api_based.py` for reference implementation

2. **Refactor `compile_video_task`**:
   - Replace project/clip queries with `worker_api.get_project_metadata()`
   - Replace intro/outro media queries with `worker_api.get_media_metadata()`
   - Remove ProcessingJob DB manipulation

3. **Handle MediaFile creation**:
   - Workers currently create MediaFile records directly
   - Need API endpoint: `POST /api/worker/media` to create MediaFile
   - Workers return file paths, server creates DB records

4. **Quota checks**:
   - Move quota validation to server-side API
   - Workers get quota info via API before starting work
   - Or: API rejects work assignment if quota exceeded

5. **Update automation tasks** (`app/tasks/automation.py`):
   - `run_compilation_task` uses `download_clip_task.apply()` inline
   - This runs in same worker process, still needs DB access
   - Consider moving automation to server-side or using API

## Configuration Required

### Server `.env`:
```bash
WORKER_API_KEY=your-secure-random-key-here
```

### Worker `.env`:
```bash
FLASK_APP_URL=http://your-flask-server:5000
WORKER_API_KEY=your-secure-random-key-here
# Remove DATABASE_URL - workers should NOT have DB access
```

## Security Notes

- Worker API endpoints require `Authorization: Bearer <WORKER_API_KEY>`
- Key should be long, random, and kept secret
- Consider IP whitelisting for worker endpoints
- Workers run outside DMZ, communicate only via HTTPS API calls
- No direct database credentials on worker machines

## Migration Steps

1. Generate secure `WORKER_API_KEY`:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Add to server `.env`:
   ```bash
   WORKER_API_KEY=<generated-key>
   ```

3. Update worker `.env`:
   ```bash
   FLASK_APP_URL=https://your-server.com
   WORKER_API_KEY=<same-key>
   # REMOVE: DATABASE_URL
   ```

4. Deploy API changes to server:
   ```bash
   docker compose restart web
   ```

5. Test worker API access:
   ```bash
   curl -H "Authorization: Bearer <key>" \
     https://your-server.com/api/worker/clips/1
   ```

6. Refactor tasks (large effort - see TODO above)

7. Deploy new worker image

8. Verify workers no longer attempt DB connections

## Testing

```bash
# Test worker API endpoints
curl -H "Authorization: Bearer $WORKER_API_KEY" \
  http://localhost:5000/api/worker/clips/123

# Verify worker can fetch metadata
python -c "
from app.tasks.worker_api import get_clip_metadata
print(get_clip_metadata(123))
"
```

## Rollback Plan

If issues arise:
1. Re-add `DATABASE_URL` to worker `.env`
2. Workers fall back to direct DB access
3. Worker API endpoints remain available but unused

## Benefits

- ✅ Workers isolated from database (DMZ compliant)
- ✅ Easier to scale workers (no DB connection pooling issues)
- ✅ Better security (workers can't directly modify sensitive data)
- ✅ Clearer separation of concerns
- ✅ Easier to monitor worker→server communication
- ✅ Can run workers in untrusted environments

## Current Blockers

The main blocker is the size/complexity of refactoring `download_clip_task` and `compile_video_task`. These are 300+ line functions with extensive DB operations.

**Recommendation**: Tackle in phases:
1. Phase 1: Get worker API working with simple test task ✅ DONE
2. Phase 2: Refactor `download_clip_task` (this document)
3. Phase 3: Refactor `compile_video_task`
4. Phase 4: Remove `get_db_session()` from worker code entirely
