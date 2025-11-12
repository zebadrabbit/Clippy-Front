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

### ✅ Phase 1: Infrastructure (COMPLETE - v0.11.0)

1. **Created worker API endpoints** (`app/api/worker.py` - 13 endpoints):
   - `GET /api/worker/clips/<clip_id>` - Fetch clip metadata
   - `POST /api/worker/clips/<clip_id>/status` - Update clip status
   - `GET /api/worker/media/<media_id>` - Fetch media file metadata
   - `POST /api/worker/media` - Create media file record
   - `POST /api/worker/jobs` - Create processing job
   - `GET /api/worker/jobs/<job_id>` - Get job metadata
   - `PUT /api/worker/jobs/<job_id>` - Update job progress/status
   - `GET /api/worker/projects/<project_id>` - Fetch project metadata
   - `PUT /api/worker/projects/<project_id>/status` - Update project status
   - `GET /api/worker/users/<user_id>/quota` - Get storage quota
   - `GET /api/worker/users/<user_id>/tier-limits` - Get tier limits
   - `POST /api/worker/users/<user_id>/record-render` - Record render usage
   - `POST /api/worker/media/find-reusable` - Find reusable media by URL

2. **Created worker API client** (`app/tasks/worker_api.py` - 14 functions):
   - Helper functions for workers to call Flask APIs
   - Handles authentication with `WORKER_API_KEY`
   - Functions: `get_clip_metadata()`, `update_clip_status()`, `create_processing_job()`,
     `get_processing_job()`, `update_processing_job()`, `get_media_metadata()`,
     `create_media_file()`, `find_reusable_media()`, `get_project_metadata()`,
     `update_project_status()`, `get_user_quota()`, `get_user_tier_limits()`,
     `record_render_usage()`

3. **Added configuration**:
   - `WORKER_API_KEY` in `config/settings.py`
   - `FLASK_APP_URL` for workers to know where to connect

### ✅ Phase 2: Simple Tasks (COMPLETE - v0.11.0)

1. **Created reference implementation**:
   - `app/tasks/validate_media_api.py` - Simple API-based task
   - Proved workers can operate without DATABASE_URL
   - Pattern established for API-based tasks

### ✅ Phase 3: Download Task Migration (COMPLETE)

**Status**: Production-ready API-based download task implemented

**Created Files**:
- `app/tasks/download_clip_v2.py` (303 lines) - Full API-based download task
- `tests/test_download_clip_v2.py` - Unit tests for worker API endpoints

**New Endpoints** (added to `app/api/worker.py`):
- `POST /api/worker/media/find-reusable` - URL-based media reuse (replaces checksum dedup)
- Enhanced `POST /api/worker/media` - Simplified media creation (no checksum param)

**New Client Functions** (added to `app/tasks/worker_api.py`):
- `find_reusable_media(user_id, source_url, normalized_url, clip_key)` - Search for existing media
- `create_media_file(...)` - Create media record (simplified signature)

**Key Features**:
- ✅ No database access - 100% API-based
- ✅ URL-based media reuse (Twitch clip key matching)
- ✅ Quota enforcement via API
- ✅ yt-dlp download with filesize limits
- ✅ Thumbnail generation with ffmpeg
- ✅ ProcessingJob logging via API
- ✅ All tests passing (3 endpoint tests + 62 existing = 65 total)

**Deprecated**:
- ❌ Checksum-based deduplication removed (antiquated system)
- ❌ SHA256 computation removed
- ❌ Tempfile-based checksum verification removed

**Migration Path**:
Original `download_clip_task` remains for now. To switch to v2:
```python
# In celery_app.py or task registration
from app.tasks.download_clip_v2 import download_clip_task_v2
# Use download_clip_task_v2.delay() instead of download_clip_task.delay()
```

### ✅ Phase 4: Compile Task Migration (COMPLETE)

**Status**: Production-ready API-based compilation task implemented

**Created Files**:
- `app/tasks/compile_video_v2.py` (685 lines) - Full API-based compile task
- `tests/test_compile_video_v2.py` (5 endpoint tests)

**New Batch Endpoints** (added to `app/api/worker.py`):
- `GET /api/worker/projects/<id>/compilation-context` - Fetch project + clips + tier limits in one call
- `POST /api/worker/media/batch` - Fetch multiple media files by IDs (for intro/outro/transitions)

**New Client Functions** (added to `app/tasks/worker_api.py`):
- `get_compilation_context(project_id)` - Batch fetch all compilation data
- `get_media_batch(media_ids, user_id)` - Batch fetch media files

**Key Features**:
- ✅ No database access - 100% API-based
- ✅ Batch operations avoid N+1 queries (single API call for project+clips+limits)
- ✅ Timeline building with intro/outro/transitions
- ✅ Tier-based resolution/clip count enforcement
- ✅ Media reuse for intro/outro/transitions
- ✅ Thumbnail generation for final compilation
- ✅ Render usage recording via API
- ✅ All tests passing (5 endpoint tests + 65 existing = 70 total)

**Helper Functions (API-based)**:
- `_apply_tier_limits_to_clips()` - Apply max_clips tier limit
- `_process_clip_v2()` - Process individual clip (no session param)
- `_process_media_file_v2()` - Process intro/outro/transition (no session param)
- `_build_timeline_with_transitions_v2()` - Build full timeline (batch media fetch)
- `_compile_final_video_v2()` - Concatenate clips with ffmpeg
- `_save_final_video_v2()` - Save to persistent storage

**Migration Path**:
Original `compile_video_task` remains for now. To switch to v2:
```python
# In celery_app.py or task registration
from app.tasks.compile_video_v2 import compile_video_task_v2
# Use compile_video_task_v2.delay() instead of compile_video_task.delay()
```

### ⚠️ Phase 5: Cleanup and Cutover (TODO - Estimated: 1 week)

### ⚠️ Phase 5: Cleanup and Cutover (TODO - Estimated: 1 week)

**Remaining Tasks**:

1. **Switch default task implementations**:
   - Update `celery_app.py` to register `_v2` tasks as defaults
   - Update all `download_clip_task.delay()` calls to `download_clip_task_v2.delay()`
   - Update all `compile_video_task.delay()` calls to `compile_video_task_v2.delay()`
   - Search codebase for task invocations:
     ```bash
     grep -r "download_clip_task" app/
     grep -r "compile_video_task" app/
     ```

2. **Remove DATABASE_URL requirement from workers**:
   - Update worker Dockerfile to not require DATABASE_URL
   - Update `.env.worker.example` to remove DATABASE_URL
   - Update worker documentation
   - Test workers with only FLASK_APP_URL and WORKER_API_KEY

3. **Delete deprecated code**:
   - Remove original `download_clip_task` from `video_processing.py`
   - Remove original `compile_video_task` from `video_processing.py`
   - Remove `get_db_session()` function (no longer needed)
   - Remove old API-based reference implementations:
     - `download_clip_api_based.py`
     - `validate_media_api.py` (if not used elsewhere)

4. **Update automation tasks** (`app/tasks/automation.py`):
   - Update `run_compilation_task` to use `compile_video_task_v2`
   - Verify automation still works without worker DB access

5. **Documentation updates**:
   - Mark migration as ✅ COMPLETE in this document
   - Update main README.md
   - Update worker deployment docs
   - Add migration notes to CHANGELOG.md

6. **Production testing**:
   - Deploy to staging with DATABASE_URL removed from workers
   - Test full download → compilation workflow
   - Monitor API endpoint performance
   - Verify quota enforcement
   - Test error handling (network failures, API timeouts)

7. **Performance validation**:
   - Compare compilation times (DB vs API)
   - Monitor API endpoint latency
   - Check for N+1 query issues
   - Verify batch operations are efficient

### Migration Complete When:

- ✅ All worker tasks use API-only (no DB access)
- ✅ Workers run successfully without DATABASE_URL
- ✅ All tests passing (integration + unit)
- ✅ Production compilation workflows working
- ✅ Deprecated code removed
- ✅ Documentation updated

## Summary of Changes

### Worker API Endpoints (19 total)

**Phase 1** (Infrastructure - 12 endpoints):
- Clip metadata (GET/POST)
- Media files (GET/POST)
- Processing jobs (POST/GET/PUT)
- Projects (GET/PUT)
- User quota/tier-limits (GET)
- Render usage (POST)

**Phase 3** (Download task - 1 endpoint):
- Media reuse search (POST)

**Phase 4** (Compile task - 2 endpoints):
- Compilation context batch (GET)
- Media batch fetch (POST)

### Worker API Client (16 functions)

**Phase 1**: 11 core functions
**Phase 2**: 1 validation function
**Phase 3**: 2 download functions
**Phase 4**: 2 compilation batch functions

### Task Files

**Original** (deprecated):
- `app/tasks/video_processing.py` - Contains old DB-based tasks

**Phase 2**:
- `app/tasks/validate_media_api.py` - Simple proof of concept

**Phase 3**:
- `app/tasks/download_clip_v2.py` - Production download task (303 lines)

**Phase 4**:
- `app/tasks/compile_video_v2.py` - Production compilation task (685 lines)

### Test Coverage

**Phase 1**: Infrastructure tested via existing tests
**Phase 2**: 6 validation tests
**Phase 3**: 3 download endpoint tests
**Phase 4**: 5 compilation endpoint tests

**Total**: 70 tests passing (65 original + 5 Phase 4)

## Configuration Changes

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
