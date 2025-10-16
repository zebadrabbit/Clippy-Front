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
python init_db.py --all --password admin123
# Or incrementally:
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
- FFMPEG_BINARY, YT_DLP_BINARY (resolves local ./bin first if provided)
- FFMPEG_DISABLE_NVENC (set to 1/true to force CPU encoding)
- FFMPEG_NVENC_PRESET (override NVENC preset if supported by your ffmpeg)
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

### Media files exist on disk but don't show up

If you see files under `instance/uploads/<user_id>/...` but they aren't listed in the UI (Arrange, Media Library), the DB may be missing their rows. Reindex the media library:

Optional commands (run inside the venv):

```bash
python scripts/reindex_media.py            # backfill DB rows from disk
python scripts/reindex_media.py --regen-thumbnails  # also rebuild missing video thumbnails
```

The script infers media type from subfolders (intros/, outros/, transitions/, compilations/, images/, clips/).

### Static bumper

To customize the inter-segment “static” bumper, replace `instance/assets/static.mp4` with your own short clip. It will be inserted between every segment including transitions, intro, and outro.

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
