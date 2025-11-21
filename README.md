# ClippyFront

ClippyFront is a Flask-based web application for organizing media and assembling video compilations with professional overlays, transitions, and GPU-accelerated rendering.


## Quick Overview

- **Media Library**: Drag-and-drop uploads, video previews, tag management
- **Project Wizard**: Fetch clips from Twitch/Discord, arrange with drag-and-drop timeline, compile with GPU rendering
- **Theming**: Dynamic color system with per-media-type colors
- **Admin Panel**: User management, subscription tiers, worker monitoring
- **Background Processing**: Celery workers for downloads and compilations
- **Security**: CSRF protection, rate limiting, strict CSP
- **Subscription Tiers**: Quota-based rendering and storage limits

## Documentation

### Getting Started

- **[Installation Guide](docs/INSTALLATION.md)** - Complete setup instructions
- **[Configuration](docs/CONFIGURATION.md)** - Environment variables reference
- **[Features](docs/FEATURES.md)** - Detailed feature documentation

### Operations

- **[Deployment Guide](docs/DEPLOYMENT.md)** - Production deployment (monitoring + web server) (v0.13.0+)
- **[Worker Setup](docs/WORKER_SETUP.md)** - Deploy background workers (v0.12.0+)
- **[Remote Workers](docs/REMOTE_WORKER_SETUP.md)** - Multi-host deployment
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions

### Development

- **[Development Guide](docs/DEVELOPMENT.md)** - Developer workflow and architecture
- **[Contributing](docs/CONTRIBUTING.md)** - Contribution guidelines
- **[Repository Structure](docs/REPO-STRUCTURE.md)** - Directory layout

### Reference

- **[API Routes](docs/ROUTES.md)** - Endpoint documentation
- **[Tiers & Quotas](docs/TIERS-AND-QUOTAS.md)** - Subscription system
- **[Worker Versioning](docs/WORKER-VERSION-CHECKING.md)** - Version compatibility
- **[Error Handling Audit](docs/ERROR_HANDLING_AUDIT.md)** - Error handling analysis (v0.13.0+)
- **[Changelog](CHANGELOG.md)** - Release history

## Quick Start

```bash
# Clone and setup
git clone <your-repo-url>
cd ClippyFront
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
bash scripts/fetch_vendor_assets.sh

# Initialize
python init_db.py --all --password admin123
flask db upgrade

# Run
python main.py
```

Visit http://localhost:5000 and log in with `admin`/`admin123`.

See [Installation Guide](docs/INSTALLATION.md) for complete setup.

## Key Features

### Media Management

- Upload media with drag-and-drop (Dropzone)
- Automatic thumbnail generation
- Video.js player with format detection
- Tag-based organization
- Bulk operations

### Video Compilation

- **Fetch clips** from Twitch/Discord with deduplication
- **Drag-and-drop timeline** with visual reordering
- **Intro/outro/transitions** from media library
- **GPU rendering** with NVENC (auto-fallback to CPU)
- **Branded overlays** with author/game text and avatars
- **Progress tracking** with live logs

### Worker System (v0.12.0+)

Workers operate via HTTP API - **no database credentials needed**:

- Deploy in DMZ/untrusted environments
- Configure with `FLASK_APP_URL` and `WORKER_API_KEY`
- Version checking with admin dashboard
- Queue routing: `gpu`, `cpu`, `celery`

See [Worker Setup](docs/WORKER_SETUP.md) for details.

### Subscription Tiers

- Monthly render-time quotas
- Total storage quotas
- Tier-aware watermarks
- Admin management UI

See [Tiers & Quotas](docs/TIERS-AND-QUOTAS.md) for details.

### Error Handling & Observability (v0.13.0+)

- **Structured logging** with contextual data for all errors
- **Zero silent failures** - all errors logged and visible
- **Reusable error utilities** (`app/error_utils.py`)
- **Comprehensive test coverage** for error scenarios
- **Production monitoring** with one-command deployment
  - Prometheus + Grafana + Node Exporter
  - Pre-configured dashboards and alerts
  - ClippyFront-specific metrics
- **Automated web server setup** (Nginx + Gunicorn)
  - SSL/TLS with Let's Encrypt
  - Rate limiting and security headers
  - WebSocket/SSE support

Deploy monitoring stack:
```bash
# Install monitoring (Prometheus + Grafana)
sudo scripts/setup_monitoring.sh

# Install web server (Nginx + Gunicorn)
sudo scripts/setup_webserver.sh --server-name clips.example.com --enable-ssl
```

See [Deployment Guide](docs/DEPLOYMENT.md) for complete documentation including remote installation, configuration options, and troubleshooting.

## Architecture

- **Flask** app factory with blueprints
- **Celery** for background jobs
- **PostgreSQL** database (SQLite for tests only)
- **Redis** for caching and queues
- **FFmpeg** for video processing
- **yt-dlp** for clip downloads

## Testing

```bash
pytest                  # Run tests
pytest --cov=app        # With coverage
ruff check .            # Lint
black .                 # Format
```

## Project Structure

```
ClippyFront/
├── app/                # Application code
│   ├── admin/          # Admin panel
│   ├── api/            # REST API
│   ├── auth/           # Authentication
│   ├── main/           # Main UI
│   └── tasks/          # Celery tasks
├── docs/               # Documentation
├── scripts/            # Utility scripts
├── tests/              # Test suite
└── instance/           # Runtime data
    ├── data/           # Media storage
    ├── assets/         # Avatars, static bumper
    └── logs/           # Legacy location (deprecated, use instance/logs/)
```

See [Repository Structure](docs/REPO-STRUCTURE.md) for details.

## Common Tasks

### Initialize Database

```bash
python init_db.py --all --password admin123
```

### Run Services

```bash
# Web app
python main.py

# Server worker (maintenance tasks)
celery -A app.tasks.celery_app worker -Q celery --loglevel=info

# GPU/CPU worker (compilations)
celery -A app.tasks.celery_app worker -Q gpu,cpu --loglevel=info
```

### Troubleshooting

```bash
# Reindex media from disk
python scripts/reindex_media.py

# Reset admin password (CLI only for security)
python scripts/reset_admin_password.py admin
python scripts/reset_admin_password.py --email admin@example.com
python scripts/reset_admin_password.py --list-admins

# Check worker versions
# Visit /admin/workers

# Detect stale workers
./scripts/check_stale_workers.sh --stop

# Health check
python scripts/health_check.py --db "$DATABASE_URL" --redis "$REDIS_URL"
```

See [Troubleshooting Guide](docs/TROUBLESHOOTING.md) for more.

## Configuration

All configuration via environment variables in `.env`:

```bash
# Core
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://user:pass@localhost/clippy_front
REDIS_URL=redis://localhost:6379/0

# Media
FFMPEG_BINARY=/path/to/ffmpeg
ALLOW_EXTERNAL_URLS=false

# Workers (v0.12.0+)
FLASK_APP_URL=https://your-app.com
WORKER_API_KEY=your-secure-key
```

See [Configuration Guide](docs/CONFIGURATION.md) for all options.

## Contributing

Contributions welcome! See [Contributing Guide](docs/CONTRIBUTING.md).

## License

[Add your license here]

## Support

- **Documentation**: See `docs/` directory
- **Issues**: Check [Troubleshooting Guide](docs/TROUBLESHOOTING.md)
- **Development**: See [Development Guide](docs/DEVELOPMENT.md)


### Subscription tiers and quotas

- Per-user subscription tiers define monthly render-time and total storage quotas.
- Watermark policy is tier-aware: higher tiers can remove the watermark; admins/unlimited tier never apply it. A per-user override exists for special cases.
- An Unlimited tier is available for admin/testing with no limits and no watermark.
- Admin UI: manage tiers in Admin → Tiers (create/edit/delete) and assign a tier on the user edit page.
- Quotas are enforced consistently:
	- Storage: on uploads and clip downloads (pre-check, and cleanup on overflow)
	- Render-time: pre-compile estimation and enforcement; usage recorded after successful compilation
	- Monthly window: render usage resets each calendar month

See docs/tiers-and-quotas.md for details.

## Quickstart

### Prerequisites

- Python 3.10+
- Redis server (for rate limiting and Celery)

### Install

1) Clone and create a virtualenv

```bash
git clone <your-repo-url>
cd ClippyFront
python3 -m venv venv
source venv/bin/activate
```

2) Install dependencies

```bash
pip install -r requirements.txt
```

3) Configure environment

```bash
cp .env.example .env
```

4) Fetch local frontend vendor assets (Dropzone + Video.js)

```bash
bash scripts/fetch_vendor_assets.sh
```

5) (Optional) Install local ffmpeg and yt-dlp binaries to ./bin

```bash
bash scripts/install_local_binaries.sh
```

Then set environment variables to prefer local binaries (or prepend PATH):

```bash
export FFMPEG_BINARY="$(pwd)/bin/ffmpeg"
export YT_DLP_BINARY="$(pwd)/bin/yt-dlp"
```

6) Initialize the database and admin user

```bash
# Ensure your DATABASE_URL points to PostgreSQL (runtime uses Postgres; SQLite is test-only outside pytest)
# export DATABASE_URL=postgresql://postgres:postgres@localhost/clippy_front

# Optionally create the database if it doesn't exist
python scripts/create_database.py

# Initialize tables and seed an admin + sample data (drops and recreates tables)
python init_db.py --all --password admin123

# Or incrementally
python init_db.py --drop
python init_db.py --admin --password admin123
```

8) Apply migrations (upgrades)

```bash
# Use Flask-Migrate to apply Alembic migrations
flask db upgrade

# Notes
# - Migrations are idempotent on PostgreSQL; duplicate columns/indexes are guarded.
# - Outside of pytest, the app requires PostgreSQL; set DATABASE_URL accordingly.
```

7) Start services

```bash
# Start Redis (pick one approach)

# or
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Run the web app
python main.py

# In another terminal, run Celery (optional)
celery -A app.tasks.celery_app worker --loglevel=info
```

Visit http://localhost:5000 and log in with the admin user if created.

## Configuration

Adjust via environment variables (see `.env.example`):

- SECRET_KEY, DATABASE_URL, REDIS_URL
- Database env precedence in dev: `DATABASE_URL` (if set) > `DEV_DATABASE_URL` > default. Runtime enforces PostgreSQL outside tests; SQLite is reserved for pytest only. Set one stable Postgres URL and keep it consistent across runs.
- FFMPEG_BINARY, YT_DLP_BINARY (resolves local ./bin first if provided)
- FFMPEG_DISABLE_NVENC (set to 1/true to force CPU encoding)
- FFMPEG_NVENC_PRESET (override NVENC preset if supported by your ffmpeg)
- FFMPEG_GLOBAL_ARGS, FFMPEG_ENCODE_ARGS, FFMPEG_THUMBNAIL_ARGS, FFMPEG_CONCAT_ARGS, FFPROBE_ARGS, YT_DLP_ARGS (optional extra CLI flags injected at runtime)
- THUMBNAIL_TIMESTAMP_SECONDS (default: 3) - Seek time for thumbnail generation
- THUMBNAIL_WIDTH (default: 480) - Thumbnail width in pixels
- ALLOW_EXTERNAL_URLS (default: false): when false, only Twitch and Discord clip URLs are accepted by the download API and the wizard; non-supported URLs are filtered and if none remain the request returns 400. Set to true to allow other sources (e.g., YouTube).
- TMPDIR (optional): set to `/app/instance/tmp` on workers bound to a network share to avoid EXDEV cross-device moves when saving final outputs.
- Instance storage mount (required in multi-host setups):
	- Host path `/mnt/clippyfront` should contain `data/`, `tmp/`, and `assets/`
	- The app prefers `/mnt/clippyfront` automatically as its instance directory when present (outside tests)
	- Set `CLIPPY_INSTANCE_PATH=/mnt/clippyfront` on native hosts to force it explicitly; set `REQUIRE_INSTANCE_MOUNT=1` to fail fast if missing
	- In containers, bind-mount your instance dir to `/app/instance` and set `CLIPPY_INSTANCE_PATH=/app/instance` inside the container (e.g., `-v /mnt/clippyfront:/app/instance`)
- RATELIMIT_DEFAULT/RATELIMIT_STORAGE_URL
- UPLOAD_FOLDER, MAX_CONTENT_LENGTH
- FLASK_HOST, FLASK_PORT, FLASK_DEBUG

Notes:
- Vendor assets are served locally from `app/static/vendor`; re-run the fetch script if you clean the repo.
- Content Security Policy is strict by default; local assets avoid nosniff/MIME issues.

## Theming

- Create and manage themes in the Admin → Themes section.
- Activate a theme to apply it globally; the app serves `/theme.css` which maps your saved colors to Bootstrap CSS variables.
- Edit colors via native color inputs or hex fields; changes save on submit. Hex and swatch inputs stay in sync while editing.

## Media Library Capabilities

- Drag-and-drop uploads with Dropzone
- Server-side MIME detection (python-magic fallback to mimetypes)
- Video thumbnails via ffmpeg on upload
- Video.js playback with programmatic src/type and browser support probing
- Tag editing and bulk operations (type change, delete, set tags)

If a format isn't supported by the browser, the UI gracefully offers a direct file open. Consider transcoding inputs with ffmpeg for maximum compatibility.

Cross-host paths: Paths stored in the database are canonicalized to `/instance/<...>`. At runtime, the app transparently rebases `/instance/` to the active instance directory (native host or container). `MEDIA_PATH_ALIAS_FROM/TO` remains available as a fallback for translating legacy absolute paths during migrations.

## Arrange and Compile

- Arrange: Pick an Intro and Outro from your Media Library; choose Transitions (multi-select) and optionally toggle Randomize. Use Select All or Clear All to quickly manage transitions.
- Timeline: Drag cards to reorder clips; the new order is saved to the server. Remove items with the X on each card.
- Compile: Starts a background job that builds the sequence, interleaves transitions, and inserts a short static bumper between segments for a channel-switching effect. Only the clips you placed on the timeline are compiled, in that exact order. If nothing is placed on the timeline, the server rejects the request.
- Logs: The log window now shows which segment is processed next, e.g., “Concatenating: <name> (2 of 6)”.

- Clip sources policy: By default, only Twitch and Discord URLs are accepted for clip downloads. You can allow other sources by setting `ALLOW_EXTERNAL_URLS=true`. When disabled, the server filters out non-supported URLs and responds with HTTP 400 if a request contains only disallowed URLs.

Avatars: When downloading clips (e.g., from Twitch), the app auto-fetches creator avatars and caches them under `instance/assets/avatars/` (with reuse and pruning to avoid buildup). You can also place a PNG/JPG manually named after the sanitized creator (e.g., `pokimane.png`). A fallback avatar is used if present (e.g., `avatar.png`).

- AVATARS_PATH: You may point this to either the assets root (e.g., `/app/instance/assets`) or directly to the avatars folder (e.g., `/app/instance/assets/avatars`). The app normalizes both forms to find avatars reliably across hosts/containers.
- OVERLAY_DEBUG=1: Set to log how avatars are resolved (search roots, matches, fallbacks) during rendering.
- Startup sanity: When overlays are enabled but no avatars directory or images are found at the resolved path, a one-time startup warning is logged to help catch misconfigurations early.

NVENC: The app detects NVENC availability and performs a tiny test encode; if unavailable or failing (e.g., missing CUDA), it automatically falls back to CPU (libx264). You can force CPU via `FFMPEG_DISABLE_NVENC=1`. See `scripts/check_nvenc.py` to diagnose. On WSL2 host shells, if you see `Cannot load libcuda.so.1`, set `LD_LIBRARY_PATH=/usr/lib/wsl/lib:${LD_LIBRARY_PATH}` before running ffmpeg.

Avatar cache maintenance: The system prunes older cached avatars automatically, but you can also run the helper script:

```bash
python scripts/cleanup_avatars.py --keep 5   # dry-run add --dry-run
```

## Automation and scheduling

You can create reusable, parameterized compilation tasks and optionally schedule them (tier-gated).

- Define a task via API: POST /api/automation/tasks with a name and params describing clip source, limits, intro/outro, transitions, and output overrides.
- Run now: POST /api/automation/tasks/<id>/run enqueues downloads (with reuse) and then the compile job.
- Create schedules (if allowed by your tier): POST /api/automation/tasks/<id>/schedules with type=daily|weekly|monthly and time fields.
- A periodic scheduler tick task scans for due schedules and kicks runs. To enable it, run Celery Beat or trigger manually:
	- Celery Beat: configure a 1-minute periodic call of app.tasks.automation.scheduled_tasks_tick
	- Manual: as an admin, POST /api/automation/scheduler/tick

Notes:
- Twitch source requires a connected `twitch_username` (same integration used by the wizard). The task fetches the most recent N clip URLs and processes them.
- Scheduling availability and per-user limits are enforced by tier fields `can_schedule_tasks` and `max_schedules_per_user`.

Removed legacy: One-time ("once") schedules are no longer creatable via the API or UI. Existing legacy rows continue to be read to avoid breaking older data, but they won’t be offered in the interface.

## Testing and Quality

```bash
pytest               # run tests
pytest --cov=app     # with coverage
ruff check .         # lint
black .              # format
pre-commit install   # set up hooks

# Connectivity probes (optional)
python scripts/health_check.py --db "$DATABASE_URL" --redis "$REDIS_URL"
```

## Deployment → Worker Setup

**📖 See [WORKER_SETUP.md](WORKER_SETUP.md) for complete worker configuration guide**

### v0.12.0: DMZ-Compliant Workers

**Workers now operate 100% via API** - no database credentials required!

Workers communicate with the Flask app using only `FLASK_APP_URL` and `WORKER_API_KEY`, enabling deployment in untrusted DMZ environments without database access.

### Quick Start

1) Copy worker environment template

```bash
cp .env.worker.example .env
```

2) Configure required settings in `.env`:

```bash
# Celery/Redis
CELERY_BROKER_URL=redis://your-redis:6379/0
CELERY_RESULT_BACKEND=redis://your-redis:6379/0

# Worker API (NEW - required for v0.12.0+)
FLASK_APP_URL=https://your-flask-app.com
WORKER_API_KEY=your-secure-worker-api-key

# Storage
HOST_INSTANCE_PATH=/mnt/clippyfront
CELERY_CONCURRENCY=4
CELERY_QUEUES=gpu,celery
```

**Note**: `DATABASE_URL` is no longer required for workers. All data access is now via REST API.

3) Deploy worker

Workers are typically deployed using Docker or directly on GPU machines. See `docs/WORKER_SETUP.md` for complete deployment instructions.


If your render workers can’t mount the same instance storage, they can fetch source media over HTTP via an internal‑only raw endpoint.

How it works:

- The server exposes `GET /api/media/raw/<media_id>` which streams the file by id.
- This endpoint intentionally does not require login; restrict access at the network layer (e.g., VPN, firewall, private ingress).

Configuration (.env):

```
MEDIA_BASE_URL=https://your-clippyfront.example.com
```

The worker pipeline first tries to resolve a local/remapped filesystem path; if not found, it downloads from `${MEDIA_BASE_URL}/api/media/raw/<id>` with retry/backoff and timeouts. Keep the raw endpoint reachable only to trusted worker networks.

## Project Structure (abridged)

```
ClippyFront/
├── app/
│   ├── __init__.py              # Flask app factory, ext init, CSP, filters
│   ├── admin/                   # Admin blueprint
│   │   └── ... themes CRUD and routes
│   ├── api/                     # API blueprint
│   ├── auth/                    # Auth blueprint
│   ├── main/                    # Main UI routes (media library, projects)
│   ├── tasks/                   # Celery app and tasks
│   ├── templates/               # Jinja templates
│   └── static/vendor/           # Local Dropzone, Video.js assets
├── config/
│   └── settings.py              # Environment configs
├── scripts/
│   ├── install_local_binaries.sh
│   └── fetch_vendor_assets.sh
├── tests/                       # pytest suite
├── main.py                      # App entry point
├── celery_worker.py             # Celery startup
├── init_db.py                   # DB init, admin create/reset, sample data
├── requirements.txt             # Dependencies
├── pyproject.toml               # Tooling config (ruff, black, pytest)
└── .env.example                 # Env var template
```

For a detailed, per-directory guide (what each folder is for and what you can do there), see docs/repo-structure.md.

## Server-side ingest importer (optional)

If your GPU workers push compiled outputs to a central ingest path (e.g., `/srv/ingest/${WORKER_ID}/...`), you can enable a periodic importer in this server to copy/move/link those files into the app's project storage and record them in the database automatically.

Enable via environment (.env) and run Celery Beat alongside your worker:

- INGEST_IMPORT_ENABLED=true
- INGEST_ROOT=/srv/ingest
- INGEST_IMPORT_USERNAME=admin                 # target owner username
- INGEST_IMPORT_PROJECT="Highlights Oct-2025"  # target project name
- INGEST_IMPORT_CREATE_PROJECT=true            # create if missing
- INGEST_IMPORT_PATTERN=*.mp4                  # which files to import
- INGEST_IMPORT_ACTION=copy                    # copy|move|link
- INGEST_IMPORT_STABLE_SECONDS=60              # consider artifact dirs ready after N seconds unchanged
- INGEST_IMPORT_WORKER_IDS=                    # optional CSV of worker ids to limit scan; empty = all
- INGEST_IMPORT_INTERVAL_SECONDS=60            # periodic scan interval

Processes:

- Celery worker (already required):
	- `celery -A app.tasks.celery_app worker --loglevel=info`
- Celery beat (schedules the importer):
	- `celery -A app.tasks.celery_app beat --loglevel=info`

The task `app.tasks.media_maintenance.ingest_import_task` will:

- Scan `${INGEST_ROOT}/${WORKER_ID}/<artifact>/...` for files matching the pattern
- Heuristically consider an artifact directory “ready” when its mtime is older than `INGEST_IMPORT_STABLE_SECONDS`
- Import files into `instance/data/<username>/<project_slug>/compilations/` using the chosen action (copy/move/link)
- Run a reindex to add DB rows and generate thumbnails so the files appear in the UI

Alternative: one-off import helper

If you prefer a one-shot import, use:

`python scripts/import_from_ingest.py --username <user> --project <name> --ingest-root /srv/ingest --worker-id <id> --action copy --pattern "*.mp4" --regen-thumbnails`

## Troubleshooting

- Dropzone not defined or blocked by CSP: ensure you ran `scripts/fetch_vendor_assets.sh` and the CSS/JS are served from `app/static/vendor`.
- Video can't play (MEDIA_ERR_SRC_NOT_SUPPORTED): the browser may not support the codec/format. Try uploading MP4 (H.264/AAC) or transcode with ffmpeg. The UI will offer a direct open as fallback.
- Invalid login for admin/admin123: run `python init_db.py --reset-admin --password admin123`.
- Missing ffmpeg/yt-dlp: run `scripts/install_local_binaries.sh` and set `FFMPEG_BINARY`/`YT_DLP_BINARY` in your environment.

### Celery error: unexpected keyword argument 'clip_ids'

This means the web app and worker are running different code versions (the compile task signature changed). Rebuild/restart your worker(s) so they pick up the new code, and ensure the web app is also updated. After upgrades that change task signatures, restart both web and workers to keep them in sync.

**v0.12.0+: Worker Version Checking**

The admin dashboard (`/admin/workers`) now shows all connected workers with version compatibility. If you see:
- **Multiple workers on the same queue** (e.g., 2 GPU workers) → Stale container or duplicate deployment
- **Version mismatches** (yellow highlight) → Old code running on a worker

To find and stop stale workers:
```bash
./scripts/check_stale_workers.sh         # Detect stale workers
./scripts/check_stale_workers.sh --stop  # Stop them interactively
```

**Common issue**: Docker containers from previous deployments continue running and steal tasks. Use `docker ps | grep celery` to find them, then `docker stop <container_id>`.

See [docs/worker-version-checking.md](docs/worker-version-checking.md) for full details.

### Media files exist on disk but don't show up

If you see files under `instance/data/<username>/...` but they aren't listed in the UI (Arrange, Media Library), the DB may be missing their rows. Reindex the media library:

Optional command (run inside the venv):

```bash
python scripts/reindex_media.py            # backfill DB rows from disk (read-only by default)
```

The script infers media type from subfolders (intros/, outros/, transitions/, compilations/, images/, clips/).
It never modifies source media on disk. To restore video thumbnails for files missing thumbnails, pass `--regen-thumbnails`.

### Data persistence and sidecars

- The database is the single source of truth for media and projects. We no longer write or rely on per-file sidecar `.meta.json` metadata during uploads.
- If you previously had sidecars, the reindexer ignores them. It will still restore DB rows based on actual files on disk.
- In development, you can optionally enable an automatic reindex on startup if the DB is empty:
	- Set `AUTO_REINDEX_ON_STARTUP=true` in your environment (or `.env`).
	- By default this is disabled to avoid masking database issues.

We recommend PostgreSQL exclusively outside tests. At startup, the app logs the resolved database target safely (e.g., `postgresql://host:port/db (redacted)`), which helps diagnose accidental DB misconfiguration. Repetitive startup messages (database target and runtime schema updates) are logged once per process to keep worker logs clean.

### Static bumper

To customize the inter-segment “static” bumper, replace `instance/assets/static.mp4` with your own short clip, or set `STATIC_BUMPER_PATH=/path/to/your/static.mp4`. It will be inserted between every segment including transitions, intro, and outro.

### Remote workers (GPU/CPU)

Consolidated instructions live in `docs/workers.md` (Linux, Windows/WSL2, Docker and native). Quick examples:

- GPU worker in Docker (Windows/WSL2):

```bash
docker build -f docker/celery-worker.Dockerfile -t clippyfront-gpu-worker:latest .
docker run --rm --gpus all \
	-e CELERY_BROKER_URL=redis://host.docker.internal:6379/0 \
	-e CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/0 \
	-e DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal/clippy_front \
	-v "$(pwd)/instance:/app/instance" \
	clippyfront-gpu-worker:latest
```

- Native worker on Linux (CPU/general):

```bash
source venv/bin/activate
export CELERY_BROKER_URL=redis://localhost:6379/0
export CELERY_RESULT_BACKEND=redis://localhost:6379/0
export DATABASE_URL=postgresql://USER:PASSWORD@localhost/clippy_front
celery -A app.tasks.celery_app worker -Q celery --loglevel=info
```

Ensure workers point to the same Redis/Postgres as the web app. For VPN/storage patterns, see `docs/wireguard.md` and `docs/samba-and-mounts.md`.

## Console TUI (experimental)

A Blessed-based console is available to monitor workers, projects, and live logs in one screen.

- Top pane: workers online, active tasks, and project/job counts.
- Bottom pane: live log tail from `instance/logs/app.log` and `instance/logs/worker.log` with colorized levels.

Run inside the venv:

```bash
python scripts/console.py
```

Controls:
- q: quit
- f: cycle filter (INFO → WARNING → ERROR → DEBUG)
- d/i/w/e: toggle Debug/Info/Warning/Error
- c: clear log view
- PgUp/PgDn, Home/End: scroll logs

Notes:
- Logs are written to `instance/logs/` with size-based rotation (10MB x 5). Override with `LOG_DIR`.
- If Celery workers are remote or unreachable, the top pane will show limited details without failing the UI.

## Contributing

See CONTRIBUTING.md for guidelines.

## AI agents

Project-specific guidance for AI coding agents lives in `.github/copilot-instructions.md`. It covers:

- Architecture overview (Flask blueprints, Celery tasks, models)
- Wizard data flow (create → fetch/queue → dedup/reuse → compile → export)
- Media handling conventions (per-user storage, thumbnails, previews)
- Integration points (Twitch, Discord) and long-running task polling
- Dev workflows (setup, run, lint/test) and gotchas (CSP/vendor assets)

Agents should read that file first to follow established patterns and avoid duplicating downloads or breaking the wizard UI.

## License

[Add your license here]
