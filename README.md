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

This repository includes an rsync-over-SSH artifact sync system for distributed workers. The pattern is:

- A Celery worker container produces compiled outputs into a shared named volume `artifacts` at `/artifacts`.
- A lightweight sidecar (`artifact-sync`) scans `/artifacts` every 60s and pushes any directory containing a `.READY` sentinel to an ingest host via SSH/rsync.
- An optional `tunnel` sidecar can maintain a reverse SSH tunnel if outbound connectivity is restricted.

Artifacts mount location:

- By default, `compose.worker.yaml` uses a named Docker volume called `artifacts` and mounts it at `/artifacts` in both the worker and sync containers.
- Inside the worker, set `ARTIFACTS_DIR=/artifacts` so the compile pipeline knows where to export the final outputs and write the `.DONE` sentinel.

### 1) Generate SSH keypair for the worker

```bash
mkdir -p secrets
ssh-keygen -t ed25519 -N "" -f secrets/rsync_key
```

### 2) Trust the ingest host and install the worker public key there

On your control machine:

```bash
# Replace with your ingest host and port
export INGEST_HOST=ingest.example.com
export INGEST_PORT=22

# Capture the host key for StrictHostKeyChecking
ssh-keyscan -p "$INGEST_PORT" "$INGEST_HOST" > secrets/known_hosts

# Show the worker public key to add to the ingest host's authorized_keys
cat secrets/rsync_key.pub
```

On the ingest host, append the above public key to the target user’s `~/.ssh/authorized_keys` (the user should own the destination path below).

#### Ingest host account (INGEST_USER)

`INGEST_USER` is the SSH username on your ingest host. It must be a real Unix user on that machine with write access to `INGEST_PATH` (e.g., `/srv/ingest`). A simple, secure baseline is to create a dedicated unprivileged account and directory owned by that user:

```bash
# On the ingest host (run as root or via sudo)
adduser --disabled-password --gecos "" ingest    # or: useradd -m ingest
mkdir -p /srv/ingest
chown ingest:ingest /srv/ingest
chmod 750 /srv/ingest

# Install the worker public key for key-only SSH
sudo -u ingest mkdir -p ~ingest/.ssh
sudo -u ingest bash -c 'cat >> ~ingest/.ssh/authorized_keys' < /path/to/rsync_key.pub
chmod 700 ~ingest/.ssh
chmod 600 ~ingest/.ssh/authorized_keys
```

Hardening tips (optional): in `authorized_keys`, you can prepend restrictions like `no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty`, and/or a `from="<worker-ip>"` source filter if you have a static source IP.

### 3) Create a minimal .env for the artifact sync

```bash
cat > .env << 'EOF'
# Identify this worker in the destination path
WORKER_ID=worker-01

# Ingest SSH target and destination path for artifacts
INGEST_HOST=ingest.example.com
INGEST_USER=ingest   # Unix user on the ingest host with write access to INGEST_PATH
INGEST_PORT=22
INGEST_PATH=/srv/ingest

# Scan/push interval in seconds
PUSH_INTERVAL=60

# Optional: reverse-tunnel mapping when enabling the tunnel profile
# TUNNEL_REVERSE=2222:localhost:22
EOF
```

### 4) Start the stack (local-first)

```bash
docker compose -f compose.worker.yaml --profile local up -d --build worker-local artifact-sync
```

This brings up:

- `worker-local`: the Celery worker built locally from `docker/worker.Dockerfile` (tag `clippyfront-worker:local`) that writes outputs into `/artifacts`.
- `artifact-sync`: a tiny container that runs `scripts/worker/clippy-scan.sh` and `clippy-push.sh` to detect `.READY` directories and push them via rsync/SSH.

The named volume `artifacts` is shared between both containers. SSH credentials are mounted as Docker secrets: `rsync_key` and `known_hosts`.

Optional: enable the reverse tunnel sidecar with a profile if your network requires inbound connectivity on the ingest host:

```bash
docker compose -f compose.worker.yaml --profile tunnel up -d
```

Alternative: use the published worker image from GHCR

If you see an error like:

```
error from registry: denied
```

1) Authenticate to GHCR to pull the worker image

```bash
# Create a GitHub Personal Access Token (classic) with read:packages
# Then login to GHCR (will prompt or read from stdin)
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin

docker compose -f compose.worker.yaml up -d --build worker artifact-sync
```

2) Alternatively, override the image to a locally-built tag without profiles:

```bash
WORKER_IMAGE=clippyfront-worker:local docker compose -f compose.worker.yaml up -d --build worker artifact-sync
```

The local worker build uses `docker/worker.Dockerfile` in this repo and writes artifacts to the shared named volume at `/artifacts` the same way.

For a full GPU worker deployment guide with recommended environment variables, examples, and troubleshooting, see `docs/gpu-worker.md`. For broader worker patterns (native, Docker, storage, networking), see `docs/workers.md`.

Notes:

- The sync sidecar respects env vars: `WORKER_ID`, `INGEST_HOST`, `INGEST_USER`, `INGEST_PATH`, `INGEST_PORT`, `PUSH_INTERVAL`. It scans `/artifacts` and pushes any directory containing a `.READY` sentinel; on success, it writes `.PUSHED` with a timestamp.
- If you already produce a `.DONE` sentinel, the scanner will promote it to `.READY`. Otherwise, it heuristically marks directories `.READY` once they appear stable (no file changes for ~1 minute) and non-empty.
- No host directory mounts are required—only the named volume `artifacts` and Docker secrets.

Secrets troubleshooting (secrets mounted as directories on some platforms)

- On some platforms (WSL/Docker Desktop), Compose may present secrets under `/run/secrets/<name>` as directories instead of files. The sidecar handles both, but manual SSH probes can fail unless you target an actual file.
- Easiest, cross-platform approach: bind your local `./secrets` directory into the container and point the sidecar at those paths via env.

```bash
# Use a robust override that mounts the whole ./secrets dir at /secrets
cp compose.worker.override.yaml.example compose.worker.override.yaml
docker compose -f compose.worker.yaml -f compose.worker.override.yaml up -d --build artifact-sync

# Optional: strict host key check probe inside the container
docker compose -f compose.worker.yaml -f compose.worker.override.yaml exec artifact-sync sh -lc '\
  ssh -o StrictHostKeyChecking=yes \
     -o UserKnownHostsFile=${KNOWN_HOSTS_FILE:-/run/secrets/known_hosts} \
     -i ${RSYNC_KEY_FILE:-/run/secrets/rsync_key} \
     -p ${INGEST_PORT:-22} \
     ${INGEST_USER}@${INGEST_HOST} true'
```

If you prefer to stick with Docker secrets, ensure `secrets/known_hosts` and `secrets/rsync_key` are real files on the host (not directories) before you (re)create `artifact-sync`.

Quick examples:

```
# Example: ingest behind WireGuard at 10.8.0.1:22
ssh-keyscan -p 22 -t ed25519 -H 10.8.0.1 > secrets/known_hosts

# Bring up just the sync sidecar for a smoke test
docker compose -f compose.worker.yaml up -d --build artifact-sync

# Create a dummy artifact in the shared volume
docker compose -f compose.worker.yaml run --rm artifact-sync /scripts/worker/smoke-artifact.sh

# Tail logs
docker compose -f compose.worker.yaml logs --tail=200 artifact-sync
```

Polling vs event-driven latency:

- By default the image now includes inotify and runs in `WATCH_MODE=auto`, so it reacts immediately when a `.DONE` or `.READY` file is created (event-driven) and still performs periodic safety sweeps.
- Without `.DONE`, readiness can still rely on stability: no file modifications for `STABLE_MINUTES` (default 1 minute). You can set `STABLE_MINUTES=0` if you always write `.DONE`.
- To force modes: set `WATCH_MODE=inotify` (event-driven only + sweeps) or `WATCH_MODE=poll` to disable inotify and rely only on `PUSH_INTERVAL`.

Advanced options:

- Limit egress with `RSYNC_BWLIMIT` (KB/s) and pass `RSYNC_EXTRA_FLAGS` (e.g., `--chmod=F644,D755`).
- Control local retention after successful push with `CLEANUP_MODE`:
	- `none` (default): keep the directory with `.PUSHED` marker
	- `delete`: remove the directory entirely after a successful push
	- `archive`: move to `/artifacts/_pushed/<dir>` for local retention

Optional delivery webhook:

- Set `DELIVERY_WEBHOOK_URL=https://...` (and optionally `DELIVERY_WEBHOOK_TOKEN`) to receive a POST after each successful push with JSON:
	`{ "worker_id": "...", "artifact": { "name": "...", "remote_path": "...", "pushed_at": "ISO8601", "files": N } }`

Retention pruning:

- A background job removes archived artifacts older than `RETENTION_DAYS` (default 30). You can also enforce a minimum free space with `MIN_FREE_GB`.

Smoke test:

- Validate the scan/push flow by creating a dummy artifact locally:

```bash
# Rebuild the artifact-sync image to ensure scripts are included
docker compose -f compose.worker.yaml build --no-cache artifact-sync

# Start the scanner only (no worker dependency required)
docker compose -f compose.worker.yaml up -d artifact-sync

# Create a dummy artifact in the shared volume without starting dependencies
# Use --entrypoint to run via bash regardless of image entrypoint settings
docker compose -f compose.worker.yaml run --no-deps --rm \
	--entrypoint /bin/bash artifact-sync -lc '/scripts/worker/smoke-artifact.sh'

Troubleshooting: Host key verification failed

If pushes fail with `Host key verification failed.`, refresh the host key for your target and recreate the sidecar:

```
ssh-keyscan -p 22 -H 10.8.0.1 > secrets/known_hosts
docker compose -f compose.worker.yaml up -d --force-recreate artifact-sync
```
```

### Multiple workers

There are a few safe ways to run more than one worker:

- One worker per sync (recommended for per-worker segregation)
	- Run a separate compose stack (or service pair) for each worker host.
	- Give each its own `/artifacts` volume and a unique `WORKER_ID`.
	- Remote paths become `${INGEST_PATH}/${WORKER_ID}/...`, cleanly namespaced.

- Many workers, one sync (shared namespace)
	- You can scale the `worker` service and keep a single `artifact-sync` that watches a shared `/artifacts` volume.
	- Set `WORKER_ID` on the sync to a group label (e.g., the host name). All artifacts upload under that prefix.
	- The artifact manifest still records the originating worker’s `worker_id` (from the worker container env) even if the sync uses a group `WORKER_ID`.

- HA sync watchers (optional)
	- You may run multiple `artifact-sync` watchers against the same `/artifacts`. A `.PUSHING` lock file prevents duplicate uploads; whichever sync grabs it first pushes, others skip.

Notes:
- Ensure every worker uses a distinct `WORKER_ID` if you want remote-level segregation. If you deliberately share a `WORKER_ID`, artifacts from those workers land under the same remote prefix.
- Artifact directory names include project id, slug, and UTC timestamp to seconds. Collisions are rare; if you expect extremely high concurrency, we can add a short unique suffix for extra safety.

### Secure HTTP media for workers (signed URLs)

If your render workers can’t mount the same instance storage, they can fetch source media over HTTP using short‑lived, signed URLs that are resistant to URL snooping.

How it works:

- The server exposes `GET /api/media/signed/<media_id>?u=<owner_id>&e=<epoch>&sig=<hmac>`.
- The signature is HMAC‑SHA256 over `(media_id, owner_id, expiry, optional_ip)` using `MEDIA_SIGNING_KEY` (falls back to `SECRET_KEY`).
- Tokens expire after `MEDIA_URL_TTL` seconds (default 300). Optionally bind to the requester IP with `MEDIA_URL_BIND_IP=true`.

Configuration (.env):

```
MEDIA_SIGNING_KEY= # optional; defaults to SECRET_KEY
MEDIA_URL_TTL=300
MEDIA_URL_BIND_IP=false
```

Generating URLs (server‑side helpers):

- In app code, import `generate_signed_media_url(media_id, owner_user_id, ttl_seconds=None, client_ip=None)` from `app.security.signed_media`.
- Example:

```python
from app.security.signed_media import generate_signed_media_url

url = generate_signed_media_url(media.id, media.user_id, ttl_seconds=300)
```

Workers can then `GET` the URL and stream the file without a user session. If you enable IP binding, generate tokens with the known worker IP (e.g., your WireGuard address) or keep the default and enforce TLS + short TTLs.

Notes:

- This route is authorization‑by‑signature and does not require login. It only serves files when the HMAC, owner id, and expiry validate, and the media exists for that owner.
- For large jobs, consider batching signed URL generation and passing them to the worker with the task payload.
- Always run behind HTTPS in production.

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
