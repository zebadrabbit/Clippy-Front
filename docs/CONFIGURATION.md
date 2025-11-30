# Configuration Guide

All configuration is managed via environment variables. Copy `.env.example` to `.env` and adjust as needed.

## Core Settings

### Application

- `SECRET_KEY` - Flask secret key for sessions (required)
- `FLASK_HOST` - Host to bind (default: 0.0.0.0)
- `FLASK_PORT` - Port to bind (default: 5000)
- `FLASK_DEBUG` - Enable debug mode (default: false)

### Database

- `DATABASE_URL` - PostgreSQL connection string (required)
  - Format: `postgresql://user:password@host:port/database`
  - In dev: Falls back to `DEV_DATABASE_URL` if set
  - PostgreSQL is required outside tests; SQLite is reserved for pytest only

### Redis

- `REDIS_URL` - Redis connection string (default: redis://localhost:6379/0)
- `RATELIMIT_STORAGE_URL` - Redis URL for rate limiting (defaults to REDIS_URL)
- `RATELIMIT_DEFAULT` - Default rate limit (e.g., "200 per day")

## Media Processing

### FFmpeg

- `FFMPEG_BINARY` - Path to ffmpeg binary (resolves local ./bin first)
- `FFMPEG_DISABLE_NVENC` - Set to 1/true to force CPU encoding
- `FFMPEG_NVENC_PRESET` - NVENC preset (e.g., p1-p7, slow, medium, fast)
- `FFMPEG_GLOBAL_ARGS` - Extra global ffmpeg arguments
- `FFMPEG_ENCODE_ARGS` - Extra encoding arguments
- `FFMPEG_THUMBNAIL_ARGS` - Extra thumbnail generation arguments
- `FFMPEG_CONCAT_ARGS` - Extra concatenation arguments
- `FFPROBE_ARGS` - Extra ffprobe arguments

### yt-dlp

- `YT_DLP_BINARY` - Path to yt-dlp binary (resolves local ./bin first)
- `YT_DLP_ARGS` - Extra yt-dlp arguments

### Content Policy

- `ALLOW_EXTERNAL_URLS` - Allow non-Twitch/Discord URLs (default: false)
  - When false, only Twitch and Discord clip URLs are accepted
  - Set to true to allow YouTube and other sources

## Storage

### Instance Directory

The instance directory contains data, logs, and assets.

- `CLIPPY_INSTANCE_PATH` - Force specific instance path (optional)
- `REQUIRE_INSTANCE_MOUNT` - Fail fast if instance mount missing (default: false)
- `HOST_INSTANCE_PATH` - Host path for instance storage (e.g., /mnt/clippyfront)

**Multi-host setups:**
- Host path `/mnt/clippyfront` should contain `data/`, `tmp/`, and `assets/`
- The app prefers `/mnt/clippyfront` automatically when present (outside tests)
- In containers, bind-mount to `/app/instance` and set `CLIPPY_INSTANCE_PATH=/app/instance`

### Media Storage

- `UPLOAD_FOLDER` - Upload directory (default: instance/data)
- `MAX_CONTENT_LENGTH` - Max upload size in bytes (default: 500MB)
- `DATA_FOLDER` - Base data folder (default: data)
- `TMPDIR` - Temporary directory for processing (optional)
  - Set to `/app/instance/tmp` on workers to avoid cross-device moves

## Worker Configuration

### API Mode (v0.12.0+)

Workers no longer need database access:

- `FLASK_APP_URL` - Flask app URL for worker API calls (required)
- `WORKER_API_KEY` - Authentication key for worker endpoints (required)

### Celery

- `CELERY_BROKER_URL` - Celery broker URL (default: REDIS_URL)
- `CELERY_RESULT_BACKEND` - Celery result backend URL (default: REDIS_URL)
- `CELERY_CONCURRENCY` - Worker concurrency (default: 4)
- `CELERY_QUEUES` - Comma-separated queue list (e.g., "gpu,cpu")

### Queue Routing

- `USE_GPU_QUEUE` - Route compilations to gpu queue (default: false)
  - When false, routes to cpu queue
  - Server worker should only consume from "celery" queue

## Features

### Notifications

- `NOTIFICATION_RETENTION_DAYS` - Auto-delete read notifications after N days (default: 30)
- `VAPID_PUBLIC_KEY` - VAPID public key for Web Push API (required for browser push)
- `VAPID_PRIVATE_KEY` - VAPID private key for Web Push API (required for browser push)
- `VAPID_EMAIL` - Contact email for push notifications (e.g., mailto:admin@example.com)

Generate VAPID keys with:
```bash
python -c "from py_vapid import Vapid; vapid = Vapid(); vapid.generate_keys(); print('Public:', vapid.public_key.decode()); print('Private:', vapid.private_key.decode())"
```

### Email

- `SMTP_HOST` - SMTP server hostname (required for email notifications)
- `SMTP_PORT` - SMTP server port (default: 587)
- `SMTP_USERNAME` - SMTP authentication username
- `SMTP_PASSWORD` - SMTP authentication password
- `SMTP_FROM_EMAIL` - From address for notification emails
- `MAIL_SERVER` - Fallback to SMTP_HOST for Flask-Mail
- `MAIL_PORT` - Fallback to SMTP_PORT
- `MAIL_USERNAME` - Fallback to SMTP_USERNAME
- `MAIL_PASSWORD` - Fallback to SMTP_PASSWORD
- `MAIL_DEFAULT_SENDER` - Fallback to SMTP_FROM_EMAIL

### Overlays

- `OVERLAY_DEBUG` - Enable avatar resolution logging (default: false)
- `AVATARS_PATH` - Avatar storage path (default: instance/assets/avatars)
- `STATIC_BUMPER_PATH` - Path to static bumper video (default: instance/assets/static.mp4)

### Automation

- `AUTO_REINDEX_ON_STARTUP` - Reindex media on startup if DB empty (default: false)

### Logging

- `LOG_DIR` - Log directory (default: instance/logs)
- `LOG_LEVEL` - Logging level (default: INFO)

## Integrations

### Twitch

Configure via admin UI (Admin → Integrations)

### Discord

Configure via admin UI (Admin → Integrations)

### YouTube OAuth

- `YOUTUBE_CLIENT_ID` - Google OAuth 2.0 Client ID (required for YouTube integration)
- `YOUTUBE_CLIENT_SECRET` - Google OAuth 2.0 Client Secret (required for YouTube integration)

**Setup Steps:**
1. Create OAuth 2.0 credentials at https://console.cloud.google.com/apis/credentials
2. Add authorized redirect URIs:
   - `http://localhost:5000/auth/youtube/callback` (for account linking)
   - `http://localhost:5000/auth/youtube/login-callback` (for login/signup)
3. Enable YouTube Data API v3 at https://console.cloud.google.com/apis/library/youtube.googleapis.com
4. Add test users at https://console.cloud.google.com/apis/credentials/consent (required during testing phase)
5. Set scopes: openid, email, profile, youtube.readonly, youtube.upload

## Security

### Admin Account Protection

- `RESTRICT_ADMIN_TO_LOCAL` - Restrict admin account login to local network only (default: true)
  - Automatically disabled when `FLASK_DEBUG=true`
  - Allowed IP ranges: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
  - Set to `false` to allow admin login from any IP

### CORS

- `CORS_ORIGINS` - Allowed CORS origins (comma-separated)

### Rate Limiting

Configured via `RATELIMIT_DEFAULT` and `RATELIMIT_STORAGE_URL`

### Content Security Policy

Strict CSP enabled by default via Talisman. Local vendor assets avoid CSP issues.

## Development

### Testing

- `PYTEST_CURRENT_TEST` - Automatically set during pytest runs
- Tests always use SQLite in-memory database

### Debug Tools

- `FLASK_DEBUG=1` - Enable Flask debug mode
- `OVERLAY_DEBUG=1` - Log avatar resolution details
