# ClippyFront

ClippyFront is a Flask-based web application for organizing media and assembling clip compilations. It includes authentication, an admin panel, a media library with uploads and previews, and optional background processing via Celery.

## Highlights

- Flask app factory with blueprints: auth, main, admin, api
- Media Library: drag-and-drop uploads (Dropzone), per-user storage, thumbnails, tags, bulk actions
- Robust video preview using Video.js with MIME detection and graceful fallbacks
- Self-hosted frontend vendor assets (Dropzone, Video.js) for CSP/MIME safety
- Admin panel for users, projects, and system info
- Security: CSRF, CORS, secure headers (Talisman), rate limiting
- Optional async jobs via Celery + Redis
- Project Wizard: consolidated flow with robust task polling
- Arrange step: Intro/Outro selection, Transitions with multi-select, Randomize, Select All/Clear All
- Timeline: card-style items with thumbnails and native drag-and-drop reordering with persistence
- Compile pipeline: interleaves transitions and inserts a static bumper between all segments; clearer logs
- Branded overlays: author and game text with optional avatar; NVENC detection with CPU fallback
- Tests with pytest and coverage; linting (Ruff) and formatting (Black)

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
- TMPDIR (optional): set to `/app/instance/tmp` on workers bound to a network share to avoid EXDEV cross-device moves when saving final outputs.
- RATELIMIT_DEFAULT/RATELIMIT_STORAGE_URL
- UPLOAD_FOLDER, MAX_CONTENT_LENGTH
- FLASK_HOST, FLASK_PORT, FLASK_DEBUG

Notes:
- Vendor assets are served locally from `app/static/vendor`; re-run the fetch script if you clean the repo.
- Content Security Policy is strict by default; local assets avoid nosniff/MIME issues.

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
MEDIA_PATH_ALIAS_TO=/mnt/clippy/instance/
```

The server also auto-rebases any path containing `/instance/` under its own `instance_path` if that location exists on disk.

## Arrange and Compile

- Arrange: Pick an Intro and Outro from your Media Library; choose Transitions (multi-select) and optionally toggle Randomize. Use Select All or Clear All to quickly manage transitions.
- Timeline: Drag cards to reorder clips; the new order is saved to the server. Remove items with the X on each card.
- Compile: Starts a background job that builds the sequence, interleaves transitions, and inserts a short static bumper between segments for a channel-switching effect.
- Logs: The log window now shows which segment is processed next, e.g., “Concatenating: <name> (2 of 6)”.

Avatars: To show a creator avatar next to the overlay text, place a PNG/JPG under `instance/assets/avatars/` named after a sanitized creator name (e.g., `pokimane.png`). A fallback avatar is used if present (e.g., `avatar.png`).

NVENC: The app detects NVENC availability and performs a tiny test encode; if unavailable or failing (e.g., missing CUDA), it automatically falls back to CPU (libx264). You can force CPU via `FFMPEG_DISABLE_NVENC=1`. See `scripts/check_nvenc.py` to diagnose.

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

### Remote GPU workers (optional)

Offload compilation to remote machines with GPUs via Celery queues.

- This project defines a dedicated `gpu` queue for `compile_video_task`.
- Start your GPU worker on the powerful machine (with NVENC):

```bash
source venv/bin/activate
export FFMPEG_DISABLE_NVENC=
celery -A app.tasks.celery_app worker -Q gpu --loglevel=info
```

- Keep your default worker (downloads, light tasks) on the main server:

```bash
source venv/bin/activate
celery -A app.tasks.celery_app worker -Q celery --loglevel=info
```

Ensure both workers point to the same Redis broker/backends (CELERY_BROKER_URL, CELERY_RESULT_BACKEND) and can reach each other over the network.

Queue routing:

- The API enqueues compile jobs to the best available queue in priority order: `gpu > cpu > celery`.
- Start your workers with the queues they should consume (e.g., `-Q gpu` on GPU host, `-Q cpu` or `-Q celery` elsewhere).

Windows/WSL2 + network shares:

- Bind the app's `instance/` directory from the Linux server into WSL2 using CIFS, then mount that into the container (`-v /mnt/clippy:/app/instance`).
- Set `TMPDIR=/app/instance/tmp` on the worker to keep temp and final files on the same filesystem.

For full network and storage setup guides, see:

- docs/wireguard.md — Secure cross-host networking over WireGuard
- docs/samba-and-mounts.md — Sharing `instance/` via Samba; mounts for Windows/WSL2 and Linux

Helper scripts:

- scripts/wg_setup_server.sh — Initialize the WireGuard server (keys + service)
- scripts/wg_add_client.sh — Create a client peer and emit a config
- scripts/setup_samba_share.sh — Create a Samba share for `instance/`
- scripts/bootstrap_infra.sh — One-shot orchestration of the above and prints worker run examples

Compose example:

- docker/docker-compose.gpu-worker.example.yml — Fill in VPN_HOST_IP and user credentials; ensure `/mnt/clippy` is mounted on the host.

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
