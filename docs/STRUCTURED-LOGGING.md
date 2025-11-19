# Structured Logging with Structlog

ClippyFront uses [structlog](https://www.structlog.org/) for robust, production-ready structured logging.

## Features

✅ **Structured JSON output** - Easy parsing and analysis with log aggregation tools
✅ **Context-aware logging** - Automatic request IDs, user IDs, task IDs
✅ **Smart filtering** - Noisy endpoints filtered at INFO, visible at DEBUG
✅ **Security** - Automatic redaction of passwords, tokens, API keys
✅ **Component control** - Fine-grained log levels per library
✅ **Multiple outputs** - JSON files + human-readable console
✅ **Log rotation** - 50 MB per file, 10 backups (500 MB total)

## Log Files

All logs are written to `instance/logs/`:

- **app.json** - All application logs (structured JSON)
- **worker.json** - Celery worker logs (structured JSON)
- **error.json** - Errors and warnings only (structured JSON)

## Basic Usage

### In Flask routes

```python
import structlog

logger = structlog.get_logger(__name__)

@api_bp.route("/projects/<int:project_id>/compile", methods=["POST"])
def compile_project(project_id):
    logger.info(
        "compile_requested",
        project_id=project_id,
        user_id=current_user.id,
        resolution=request.json.get("resolution"),
    )

    try:
        result = start_compilation(project_id)
        logger.info("compile_queued", project_id=project_id, task_id=result.id)
        return jsonify({"task_id": result.id})
    except Exception as e:
        logger.error("compile_failed", project_id=project_id, error=str(e))
        raise
```

### In Celery tasks

```python
import structlog

logger = structlog.get_logger(__name__)

@celery_app.task(bind=True)
def download_clip_task(self, clip_id, url):
    logger.info("download_started", clip_id=clip_id, url=url)

    try:
        result = download_file(url)
        logger.info(
            "download_completed",
            clip_id=clip_id,
            duration=result.duration,
            size_mb=result.size / 1024 / 1024,
        )
        return result
    except Exception as e:
        logger.error("download_failed", clip_id=clip_id, url=url, error=str(e))
        raise
```

### In utility functions

```python
import structlog

logger = structlog.get_logger(__name__)

def process_video(input_path, output_path):
    logger.debug("video_processing_started", input=input_path, output=output_path)

    # Processing logic

    logger.info(
        "video_processed",
        input=input_path,
        output=output_path,
        processing_time_seconds=elapsed,
    )
```

## Automatic Context

Structlog automatically adds context to your logs:

### Flask requests
```json
{
  "event": "download_requested",
  "clip_id": 123,
  "endpoint": "api.download_clip",
  "method": "POST",
  "path": "/api/clips/123/download",
  "remote_addr": "10.8.0.2",
  "user_id": 5,
  "username": "alice",
  "request_id": "abc-123",
  "timestamp": "2025-11-12T03:45:12.123456Z",
  "level": "info"
}
```

### Celery tasks
```json
{
  "event": "compilation_started",
  "project_id": 42,
  "task_id": "5937adce-7cb8-4a31-98c1-6a3b903b3acd",
  "task_name": "app.tasks.compile_video_v2.compile_video_task_v2",
  "timestamp": "2025-11-12T03:45:12.123456Z",
  "level": "info"
}
```

## Log Levels

Configure via environment variable:

```bash
export LOG_LEVEL=DEBUG    # Verbose (shows everything including health checks)
export LOG_LEVEL=INFO     # Default (hides polling, shows important events)
export LOG_LEVEL=WARNING  # Errors and warnings only
```

### Component-specific levels

Structlog automatically configures sensible defaults:

| Component | Default Level | Debug Mode |
|-----------|---------------|------------|
| ClippyFront app | INFO | DEBUG |
| Werkzeug (Flask) | WARNING | DEBUG |
| SQLAlchemy | WARNING | INFO |
| Celery | INFO | INFO |
| yt-dlp | WARNING | WARNING |
| Discord.py | WARNING | WARNING |
| urllib3/requests | WARNING | WARNING |

## Filtering Noisy Endpoints

At INFO level, these endpoints are automatically filtered:

- `/api/health`
- `/api/tasks/<id>` (polling)
- `/api/jobs/recent` (polling)
- `/api/projects/<id>/clips` (frequent updates)

To see these, set `LOG_LEVEL=DEBUG`.

## Security

Structlog automatically redacts sensitive fields:

```python
logger.info("user_login", username="alice", password="secret123")
```

Output:
```json
{
  "event": "user_login",
  "username": "alice",
  "password": "***REDACTED***"
}
```

Redacted patterns:
- `password`
- `api_key`
- `secret`
- `token`
- `authorization`
- `cookie`
- `csrf_token`

## Best Practices

### ✅ DO

**Use structured fields instead of string formatting:**

```python
# Good
logger.info("download_completed", clip_id=123, size_mb=45.2, duration_seconds=120)

# Bad
logger.info(f"Downloaded clip {123}, size: {45.2} MB, duration: {120}s")
```

**Use descriptive event names:**

```python
logger.info("compilation_started", project_id=42)
logger.info("compilation_progress", project_id=42, percent=50)
logger.info("compilation_completed", project_id=42, output_path="/path/to/video.mp4")
```

**Add context to errors:**

```python
try:
    result = compile_video(project_id)
except Exception as e:
    logger.error(
        "compilation_failed",
        project_id=project_id,
        error=str(e),
        error_type=type(e).__name__,
        traceback=traceback.format_exc(),
    )
    raise
```

### ❌ DON'T

**Don't log sensitive data explicitly:**

```python
# Bad - exposes secrets
logger.info("api_call", api_key=config.API_KEY)
```

**Don't use string interpolation:**

```python
# Bad - loses structure
logger.info(f"User {user_id} downloaded {clip_id}")

# Good - structured
logger.info("download", user_id=user_id, clip_id=clip_id)
```

**Don't log inside tight loops:**

```python
# Bad - creates huge logs
for frame in video_frames:
    logger.debug("processing_frame", frame_num=frame.num)

# Good - log progress periodically
for i, frame in enumerate(video_frames):
    if i % 100 == 0:
        logger.debug("processing_progress", frames_processed=i, total=len(video_frames))
```

## Querying JSON Logs

### Using jq

```bash
# Show all compilation events
cat instance/logs/app.json | jq 'select(.event | startswith("compilation"))'

# Find errors for a specific user
cat instance/logs/error.json | jq 'select(.user_id == 5)'

# Show download task durations
cat instance/logs/worker.json | jq 'select(.event == "download_completed") | {clip_id, duration_seconds, size_mb}'

# Count events by type
cat instance/logs/app.json | jq -r '.event' | sort | uniq -c | sort -rn
```

### Using grep

```bash
# Find all logs for a specific task
grep "5937adce-7cb8-4a31-98c1-6a3b903b3acd" instance/logs/worker.json

# Find all compilation failures
grep '"level":"error"' instance/logs/error.json | grep compilation

# Show recent API errors
tail -100 instance/logs/error.json | jq 'select(.endpoint)'
```

## Migration from Old Logging

Old style:
```python
from flask import current_app

current_app.logger.info(f"Queued download task {task_id} for clip {clip_id}")
```

New style:
```python
import structlog

logger = structlog.get_logger(__name__)
logger.info("download_queued", task_id=task_id, clip_id=clip_id, url=url, queue=download_queue)
```

Benefits:
- Queryable fields (find all downloads for clip 123)
- Automatic context (user, endpoint, request ID)
- No string formatting overhead
- Type-safe field names

## Troubleshooting

### Logs not appearing

Check log level:
```bash
export LOG_LEVEL=DEBUG
sudo systemctl restart clippy-front
```

### Too many logs

Increase filtering:
```bash
export LOG_LEVEL=WARNING
```

Or customize component levels in `app/structured_logging.py`:
```python
def configure_component_loggers(base_level: int) -> None:
    # Make yt-dlp completely silent
    logging.getLogger("yt_dlp").setLevel(logging.CRITICAL)
```

### JSON parsing errors

Logs are written with one JSON object per line (newline-delimited JSON):
```bash
# This works
cat app.json | jq .

# This doesn't (not a JSON array)
jq . app.json
```

Use `jq -R 'fromjson?'` or process line-by-line.

## Performance

Structlog is designed for production:

- **Lazy evaluation** - Fields only computed if logged
- **Caching** - Logger instances cached on first use
- **Filtering** - Events dropped before formatting
- **Batching** - Handlers buffer writes

Overhead: ~5-10 μs per log call (negligible).
