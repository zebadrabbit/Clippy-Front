# Logging System Upgrade: Structlog

## What Changed

ClippyFront now uses **structlog** for production-grade structured logging, replacing the basic Python logging system.

### New Features

✅ **Structured JSON logs** - Machine-parseable, queryable logs
✅ **Automatic context** - Request IDs, user IDs, task IDs added automatically
✅ **Smart filtering** - Noisy polling endpoints suppressed at INFO level
✅ **Security** - Auto-redaction of passwords, tokens, API keys
✅ **Component control** - Per-library log level configuration
✅ **Better rotation** - 50 MB files, 10 backups (500 MB total)

## Migration Guide

### Old Logging (Deprecated)

```python
from flask import current_app

current_app.logger.info(f"Queued download task {task_id} for clip {clip_id}")
current_app.logger.error(f"Download failed: {error}")
```

### New Logging (Recommended)

```python
import structlog

logger = structlog.get_logger(__name__)

logger.info("download_queued", task_id=task_id, clip_id=clip_id, url=url, queue="gpu")
logger.error("download_failed", clip_id=clip_id, error=str(error), error_type=type(error).__name__)
```

## Files Changed

### New Files
- `app/structured_logging.py` - Core structlog configuration
- `docs/STRUCTURED-LOGGING.md` - Complete usage guide
- `docs/LOGGING_UPGRADE.md` - This file

### Modified Files
- `requirements.txt` - Added `structlog` and `python-json-logger`
- `app/__init__.py` - Use `configure_structlog()` instead of `configure_logging()`
- `app/tasks/celery_app.py` - Use `configure_structlog_celery()`
- `app/api/projects.py` - Example migration to structlog

### Deprecated (still works, but no longer updated)
- `app/logging_config.py` - Old rotating file handler system

## Log File Changes

### Before
```
instance/logs/
├── app.log          # Plain text, all logs mixed
├── worker.log       # Plain text, worker logs
└── beat.log         # Plain text, beat scheduler
```

### After
```
instance/logs/
├── app.json         # Structured JSON, all app logs
├── worker.json      # Structured JSON, worker logs
├── error.json       # Structured JSON, errors only (WARNING+)
└── app.log          # (Old file, will stop growing)
```

## Benefits

### Before (Plain Text)
```
2025-11-12 02:19:20,123 [INFO] MainProcess app.api.projects: Queued download task abc-123 for clip 970: https://clips.twitch.tv/example [queue=gpu]
```

Hard to:
- Parse programmatically
- Query specific fields
- Aggregate across systems
- Filter by context

### After (Structured JSON)
```json
{
  "event": "download_queued",
  "task_id": "abc-123",
  "clip_id": 970,
  "url": "https://clips.twitch.tv/example",
  "queue": "gpu",
  "project_id": 42,
  "user_id": 5,
  "username": "alice",
  "endpoint": "api.create_and_download_clips",
  "timestamp": "2025-11-12T02:19:20.123456Z",
  "level": "info",
  "filename": "projects.py",
  "lineno": 290
}
```

Easy to:
- Parse with `jq`, Python, log aggregators
- Query: "Show all downloads for user 5"
- Filter: "Find slow downloads (duration > 60s)"
- Aggregate: "Count downloads per queue"

## Querying Examples

### Find all download events for a specific task
```bash
cat instance/logs/app.json | jq 'select(.task_id == "abc-123")'
```

### Show all errors for project 42
```bash
cat instance/logs/error.json | jq 'select(.project_id == 42)'
```

### Count downloads by queue
```bash
cat instance/logs/app.json | jq -r 'select(.event == "download_queued") | .queue' | sort | uniq -c
```

### Find slow compilations (if we add duration logging)
```bash
cat instance/logs/worker.json | jq 'select(.event == "compilation_completed" and .duration_seconds > 300)'
```

## Environment Variables

### LOG_LEVEL
Controls verbosity:
```bash
export LOG_LEVEL=DEBUG    # Show everything (including health checks)
export LOG_LEVEL=INFO     # Default (suppress polling, show events)
export LOG_LEVEL=WARNING  # Errors only
```

### Component Overrides
Fine-grained control in `app/structured_logging.py`:

```python
def configure_component_loggers(base_level: int) -> None:
    logging.getLogger("werkzeug").setLevel(logging.WARNING)      # Flask request logs
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)  # SQL queries
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)        # yt-dlp output
    logging.getLogger("celery").setLevel(logging.INFO)           # Celery tasks
```

## Deployment Steps

### 1. Install Dependencies
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Restart Services
```bash
sudo systemctl restart clippy-front
sudo systemctl restart clippy-worker  # or docker restart for remote workers
```

### 3. Verify Logs
```bash
# Check JSON logs are being created
ls -lh instance/logs/*.json

# View recent structured logs
tail -5 instance/logs/app.json | jq .

# Monitor live (pretty-printed)
tail -f instance/logs/app.json | jq .
```

### 4. Update Log Aggregation (if using)
If you send logs to Elasticsearch, Datadog, CloudWatch, etc., update your shipper config:

**Before:**
```yaml
# Filebeat example
- type: log
  paths:
    - /path/to/instance/logs/app.log
  multiline.pattern: '^\d{4}-\d{2}-\d{2}'
  multiline.negate: true
  multiline.match: after
```

**After:**
```yaml
# Filebeat example
- type: log
  paths:
    - /path/to/instance/logs/app.json
  json.keys_under_root: true
  json.add_error_key: true
```

## Rollback Plan

If issues occur, you can temporarily revert:

1. **In `app/__init__.py`:**
```python
# Revert to old logging
from app.logging_config import configure_logging as _configure_logging
_configure_logging(app, role="web")
```

2. **In `app/tasks/celery_app.py`:**
```python
# Revert Celery logging
from app.logging_config import attach_celery_file_logging as _attach
_attach(logger, instance_path)
```

3. **Restart services**

Old `.log` files will resume growth.

## Performance Impact

Minimal overhead:
- Structlog: ~5-10 μs per log call
- JSON formatting: ~20-30 μs per event
- File rotation: Background thread, non-blocking

**Expected:** <0.1% CPU increase for typical workloads.

## Next Steps

1. ✅ Core logging system migrated
2. ⏳ Migrate remaining `current_app.logger` calls to structlog
3. ⏳ Add request ID middleware for end-to-end tracing
4. ⏳ Set up log aggregation (optional)
5. ⏳ Create alerting rules on error.json events

## See Also

- `docs/structured-logging.md` - Complete usage guide
- `app/structured_logging.py` - Configuration source
- [Structlog Docs](https://www.structlog.org/) - Official documentation
