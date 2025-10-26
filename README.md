# ClippyFront

ClippyFront is a Flask-based web application for organizing media and assembling clip compilations. It includes authentication, an admin panel, a media library with uploads and previews, and optional background processing via Celery.

## Highlights

- Flask app factory with blueprints: auth, main, admin, api
- Theme system: dynamic `/theme.css` that maps theme colors to Bootstrap variables; admin CRUD to create, edit, activate, and delete themes
	- Per-media-type colors (intro/clip/outro/transition) are themeable and applied to Media Library cards and the Arrange timeline.
- Media Library: drag-and-drop uploads (Dropzone), per-user storage, thumbnails, tags, bulk actions
- Robust video preview using Video.js with MIME detection and graceful fallbacks
- Self-hosted frontend vendor assets (Dropzone, Video.js) for CSP/MIME safety
- Admin panel for users, projects, themes, and system info
- Security: CSRF, CORS, secure headers (Talisman), rate limiting
- Optional async jobs via Celery + Redis
- Project Wizard: consolidated flow with robust task polling
- Arrange step: Intro/Outro selection, Transitions with multi-select, Randomize, Select All/Clear All
- Timeline: card-style items with thumbnails and native drag-and-drop reordering with persistence
	- Type-colored borders and a dashed insert marker for clear placement during drag.
- Compile pipeline: interleaves transitions and inserts a static bumper between all segments; clearer logs
- Branded overlays: author and game text with optional avatar; NVENC detection with CPU fallback
- Download deduplication across projects: normalized-URL reuse avoids re-downloading the same clip for the same user
	- Creator avatars are auto-fetched (when available) during clip downloads, cached under `instance/assets/avatars/`, and pruned to keep only recent files per author
- Tests with pytest and coverage; linting (Ruff) and formatting (Black)

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
- TMPDIR (optional): set to `/app/instance/tmp` on workers bound to a network share to avoid EXDEV cross-device moves when saving final outputs.
- Instance storage mount (required in multi-host setups):
	- Host path `/mnt/clippy` must exist and contain `uploads/`, `downloads/`, `compilations/`, `tmp/`, and `assets/`
	- The app prefers `/mnt/clippy` automatically as its instance directory when present (outside tests)
	- Set `CLIPPY_INSTANCE_PATH=/mnt/clippy` on native hosts to force it explicitly; set `REQUIRE_INSTANCE_MOUNT=1` to fail fast if missing
	- In containers, bind-mount `/mnt/clippy` to `/app/instance` and set `CLIPPY_INSTANCE_PATH=/app/instance` inside the container
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

Cross-host paths: If a remote worker writes media paths that differ from the web server, set:

```
MEDIA_PATH_ALIAS_FROM=/app/instance/
MEDIA_PATH_ALIAS_TO=/mnt/clippy/
```

The server also auto-rebases any path containing `/instance/` under its own `instance_path` if that location exists on disk.

## Arrange and Compile

- Arrange: Pick an Intro and Outro from your Media Library; choose Transitions (multi-select) and optionally toggle Randomize. Use Select All or Clear All to quickly manage transitions.
- Timeline: Drag cards to reorder clips; the new order is saved to the server. Remove items with the X on each card.
- Compile: Starts a background job that builds the sequence, interleaves transitions, and inserts a short static bumper between segments for a channel-switching effect.
- Logs: The log window now shows which segment is processed next, e.g., “Concatenating: <name> (2 of 6)”.

Avatars: When downloading clips (e.g., from Twitch), the app auto-fetches creator avatars and caches them under `instance/assets/avatars/` (with reuse and pruning to avoid buildup). You can also place a PNG/JPG manually named after the sanitized creator (e.g., `pokimane.png`). A fallback avatar is used if present (e.g., `avatar.png`).

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

## Troubleshooting

- Dropzone not defined or blocked by CSP: ensure you ran `scripts/fetch_vendor_assets.sh` and the CSS/JS are served from `app/static/vendor`.
- Video can't play (MEDIA_ERR_SRC_NOT_SUPPORTED): the browser may not support the codec/format. Try uploading MP4 (H.264/AAC) or transcode with ffmpeg. The UI will offer a direct open as fallback.
- Invalid login for admin/admin123: run `python init_db.py --reset-admin --password admin123`.
- Missing ffmpeg/yt-dlp: run `scripts/install_local_binaries.sh` and set `FFMPEG_BINARY`/`YT_DLP_BINARY` in your environment.

### Admin password seems to change daily

If your admin password appears to “change,” it was typically due to multiple SQLite files being created with relative paths. We now standardize on PostgreSQL to avoid this class of issue. If you still hit issues:

- Ensure you’re using the same environment variables (`FLASK_ENV`, `DATABASE_URL`) for each run.
- Avoid re-running `init_db.py --all` unless you intend to drop/recreate tables.
- Reset the admin password explicitly when needed:
	- `python init_db.py --reset-admin --password <newpassword>`

### Media files exist on disk but don't show up

If you see files under `instance/uploads/<user_id>/...` but they aren't listed in the UI (Arrange, Media Library), the DB may be missing their rows. Reindex the media library:

Optional command (run inside the venv):

```bash
python scripts/reindex_media.py            # backfill DB rows from disk (read-only)
```

The script infers media type from subfolders (intros/, outros/, transitions/, compilations/, images/, clips/).
It never modifies files on disk and does not regenerate thumbnails.

### Data persistence and sidecars

- The database is the single source of truth for media and projects. We no longer write or rely on per-file sidecar `.meta.json` metadata during uploads.
- If you previously had sidecars, the reindexer ignores them. It will still restore DB rows based on actual files on disk.
- In development, you can optionally enable an automatic reindex on startup if the DB is empty:
	- Set `AUTO_REINDEX_ON_STARTUP=true` in your environment (or `.env`).
	- By default this is disabled to avoid masking database issues.

We recommend PostgreSQL exclusively outside tests. At startup, the app logs the resolved database target safely (e.g., `postgresql://host:port/db (redacted)`), which helps diagnose accidental DB misconfiguration.

### Static bumper

To customize the inter-segment “static” bumper, replace `instance/assets/static.mp4` with your own short clip. It will be inserted between every segment including transitions, intro, and outro.

### Remote workers (GPU/CPU)

Consolidated instructions live in `docs/workers.md` (Linux, Windows/WSL2, Docker and native). Quick examples:

- GPU worker in Docker (Windows/WSL2):

```bash
docker build -f docker/worker.Dockerfile -t clippyfront-gpu-worker:latest .
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
