# Running workers (Linux and Windows/WSL2)

This guide consolidates how to run ClippyFront workers on Linux and Windows (via WSL2), with and without Docker, plus an audit of the flags/env vars you actually need.

Use cases
- GPU worker in Docker on Windows/WSL2 or Linux (NVENC-enabled ffmpeg preferred)
- Native Celery worker (no Docker) on Linux/WSL2 for CPU or GPU
- Shared storage and cross-host path handling

If you only need the GPU-in-Docker recipe, see also `docs/gpu-worker.md`. It now links back here for details and troubleshooting.

## Artifact sync via rsync-over-SSH

Workers can export final renders to a dedicated artifacts volume for transfer to a central ingest host over SSH.

How it works:

- The compile task saves the final render to the normal instance path and, when `ARTIFACTS_DIR` is set and exists, mirrors a copy into `${ARTIFACTS_DIR}/<projectId>_<slug>_<UTC>`.
- A `.DONE` sentinel is written into that directory. A sidecar scanner promotes `.DONE` → `.READY` once stable; a push sidecar rsyncs any `.READY` directory to `${INGEST_USER}@${INGEST_HOST}:${INGEST_PATH}/${WORKER_ID}/<dir>`.
- On success, the sync sidecar writes `.PUSHED` with a timestamp.

Quick start (compose stack included in repo): see `compose.worker.yaml` and the “Deployment → Worker Setup” section in `README.md`.

Artifacts path configuration (Compose)

- For the `compose.worker.yaml` stack in this repo, artifacts use a named Docker volume `artifacts` mounted at `/artifacts` in both worker and sync. No host path mounts are required.
- Inside the worker, ensure `ARTIFACTS_DIR=/artifacts` so the export step writes to that path.

Minimal variables for the sync sidecar:

- `WORKER_ID` — identifier for namespacing on the ingest host
- `INGEST_HOST`, `INGEST_USER`, `INGEST_PORT` (default 22), `INGEST_PATH`
- `PUSH_INTERVAL` (default 60s)
- SSH secrets mounted as Docker secrets: `rsync_key` and `known_hosts`

Tuning and retention:

- `RSYNC_BWLIMIT` (KB/s) to cap bandwidth, `RSYNC_EXTRA_FLAGS` for custom rsync flags
- `CLEANUP_MODE`: `none` (default), `delete`, or `archive` (moves to `/artifacts/_pushed/<dir>`)
 - Polling vs event-driven: The sync container includes `inotify-tools` and defaults to `WATCH_MODE=auto`, reacting immediately when `.DONE`/`.READY` files appear and also running periodic sweeps (`PUSH_INTERVAL`, default 60s). If no `.DONE` is present, the scanner can mark `.READY` after stability (`STABLE_MINUTES`, default 1 minute). Force behavior with `WATCH_MODE=inotify` or disable inotify with `WATCH_MODE=poll`.

Worker requirement:

- Set `ARTIFACTS_DIR=/artifacts` (or another path) in the worker environment, and ensure the path exists (e.g., via a Docker volume) so the export occurs.

Delivery notifications (optional): set `DELIVERY_WEBHOOK_URL` (and `DELIVERY_WEBHOOK_TOKEN`) to receive a POST per successful push. Payload includes `worker_id`, `artifact.name`, `artifact.remote_path`, `artifact.pushed_at`, and `artifact.files`.

Retention pruning:

- The sync image runs a pruning loop that deletes archived `_pushed` entries older than `RETENTION_DAYS` (default 30). Set `MIN_FREE_GB` to enforce a minimum free space threshold by removing oldest archives.

Smoke test

```
docker compose -f compose.worker.yaml run --rm artifact-sync /scripts/worker/smoke-artifact.sh
```

### Multiple workers topologies

- Separate stacks (per-worker namespace): run one `worker` + one `artifact-sync` per host/VM, each with a unique `WORKER_ID` and its own `/artifacts` volume. Remote uploads go to `${INGEST_PATH}/${WORKER_ID}/...` per worker.

- Scale workers with a shared sync: run multiple `worker` containers that write to the same `/artifacts` and a single `artifact-sync`. Set the sync’s `WORKER_ID` to a group label (e.g., the hostname). The manifest inside each artifact still records the originating worker’s id from its environment.

- Redundant sync watchers: you may run more than one `artifact-sync` pointed at the same `/artifacts`. The `.PUSHING` lock file in each artifact directory prevents duplicate uploads across watchers.

Collision considerations: artifact directory names are `<projectId>_<slug>_<UTC>`; duplicates are unlikely. If you anticipate extremely high concurrency across multiple workers, consider adding a short unique suffix to directory names—open to implement if needed.

## Prerequisites

- Redis and PostgreSQL reachable from the worker
  - Prefer private/VPN networking (see `docs/wireguard.md`). Avoid exposing 6379/5432 publicly.
- Shared storage for media (the app’s `instance/` directory).
  - REQUIRED: host mount at `/mnt/clippyfront` containing `uploads/`, `downloads/`, `compilations/`, `tmp/`, and `assets/`
  - Bind-mount `/mnt/clippyfront` into the container at `/app/instance`
  - The app prefers `/mnt/clippyfront` as its instance path and can enforce its presence with `REQUIRE_INSTANCE_MOUNT=1`
  - See `docs/samba-and-mounts.md` for Linux/Windows/WSL2 mounts
- Optional for artifact sync: a named Docker volume (e.g., `artifacts`) mounted at `/artifacts` in both the worker and the sync sidecar; set `ARTIFACTS_DIR=/artifacts` in the worker env. Alternatively, set `ARTIFACTS_HOST_PATH` in `.env` to bind-mount a specific host directory to `/artifacts` for easier inspection and backups.
- For GPU in Docker
  - Linux: NVIDIA drivers + nvidia-container-toolkit installed
  - Windows: Docker Desktop with WSL2 + NVIDIA GPU support enabled

## Quick starts

### A) GPU worker in Docker (Windows/WSL2 or Linux)

Minimal, required flags only. Replace credentials/hosts for your setup.

Windows/WSL2 (host.docker.internal works):

```bash
# From repo root (after docker build)
# docker build -f docker/celery-worker.Dockerfile -t clippyfront-gpu-worker:latest .

docker run --rm --gpus all \
  -e CELERY_BROKER_URL=redis://host.docker.internal:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/0 \
  -e DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal/clippy_front \
  -v "$(pwd)/instance:/app/instance" \
  clippyfront-gpu-worker:latest
```

Linux (add host-gateway for host.docker.internal):

```bash
docker run --rm --gpus all \
  --add-host=host.docker.internal:host-gateway \
  -e CELERY_BROKER_URL=redis://host.docker.internal:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/0 \
  -e DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal/clippy_front \
  -e REQUIRE_INSTANCE_MOUNT=1 \
  -e CLIPPY_INSTANCE_PATH=/app/instance \
  -e TMPDIR=/app/instance/tmp \
  -v "/mnt/clippyfront:/app/instance" \
  clippyfront-gpu-worker:latest
```

Recommended extras (especially on CIFS/WSL2 mounts):

- `-e TMPDIR=/app/instance/tmp` keeps temp + final outputs on the same filesystem to avoid EXDEV errors
- `-e CELERY_CONCURRENCY=1|2` for parallelism; default is 1 in the image
- `-e CELERY_QUEUES=gpu,celery` to consume both GPU and default queues; set to `gpu` only if you want a dedicated GPU worker

Compose caveat: docker-compose often ignores GPU reservations unless using Swarm. Prefer plain `docker run --gpus all` on single hosts. See `docker/docker-compose.gpu-worker.yml` for an example and adjust as needed.

### B) Native worker (no Docker) on Linux/WSL2

Inside your Python venv on the worker host:

```bash
# Ensure env points to the same Redis/Postgres as the web app
export CELERY_BROKER_URL=redis://10.8.0.1:6379/0
export CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0
export DATABASE_URL=postgresql://USER:PASSWORD@10.8.0.1/clippy_front
# For native (non-Docker) workers, the instance path is on the host
export CLIPPY_INSTANCE_PATH=/mnt/clippyfront
export REQUIRE_INSTANCE_MOUNT=1

# Optional: prefer local ffmpeg/yt-dlp
export FFMPEG_BINARY=ffmpeg
export YT_DLP_BINARY=yt-dlp

# Optional: avoid EXDEV on network/cifs storage
export TMPDIR=/app/instance/tmp

# Queue selection: run a GPU worker or a general-purpose worker
# GPU-only
celery -A app.tasks.celery_app worker -Q gpu --loglevel=info
# General (downloads + fallback compiles)
# celery -A app.tasks.celery_app worker -Q celery --loglevel=info
```

On Windows, run this inside WSL2 with the repo checked out into the Linux filesystem (not a Windows mount) for performance. If your media lives on a Windows share, mount it in WSL2 via CIFS to `/mnt/...` and point the app’s instance path there; see `docs/samba-and-mounts.md`.

## Storage and path mapping

Workers and the web app must “see” the same files at the same logical paths:

- REQUIRED mount: `/mnt/clippyfront` on the host; bind-mount to `/app/instance` for containers
- When sharing over CIFS/SMB, mount the remote path on the worker host (Linux or WSL2) at `/mnt/clippyfront`, then bind-mount that into the container

Cross-host path aliasing:

- If file paths in the database have a different root on your worker than on the web server, use alias envs to translate:
  - `MEDIA_PATH_ALIAS_FROM=/app/instance/`
  - `MEDIA_PATH_ALIAS_TO=/mnt/clippyfront/`
- The web app also auto-rebases any path containing `/instance/` under its own `instance_path` if it exists on disk
- Enable `MEDIA_PATH_DEBUG=1` temporarily to log how paths are resolved (both web server and worker)
 - Overlays: Avatar images are resolved under the shared assets. Set `AVATARS_PATH` to either the assets root (e.g., `/app/instance/assets`) or directly to the avatars directory (e.g., `/app/instance/assets/avatars`). Both forms are supported and normalized. Use `OVERLAY_DEBUG=1` for detailed resolution logs. On startup, if overlays are enabled but no avatars path/images are found, a warning is logged once.

### No shared storage? Use the raw media endpoint over HTTP

If your render worker cannot mount the same `instance/` storage as the web app, it can fetch media over HTTP from an internal‑only raw endpoint.

Pipeline behavior:

- Try local/remapped file paths first.
- When not found, download from `${MEDIA_BASE_URL}/api/media/raw/<media_id>` into the task’s temp directory before processing, with retry/backoff on transient errors.

Configure a base URL so workers can build absolute links outside a request context:

```
MEDIA_BASE_URL=https://your-clippyfront.example.com
```

Security: The raw endpoint doesn’t require login. Restrict access at the network layer (VPN, firewall, private ingress) and prefer HTTPS when traversing untrusted networks.

## Networking

- Windows/macOS: `host.docker.internal` resolves to the host; use it for Redis/Postgres when the host runs them
- Linux: add `--add-host=host.docker.internal:host-gateway` on `docker run`, or directly use the host IP/DNS
- VPN: For production-like setups, prefer WireGuard and use the VPN IPs (see `docs/wireguard.md`)

Connectivity checks from inside the container:

```bash
docker exec -it <container> python - <<'PY'
import redis, os
print('redis ping:', redis.Redis.from_url(os.environ['CELERY_BROKER_URL']).ping())
PY
```

## Queue model and routing

Queues defined: `celery` (default), `cpu`, `gpu`.

- The web app enqueues compile jobs to the best available queue in priority order: `gpu > cpu > celery`
- Start your worker with the queues it should consume, e.g. `-Q gpu` on GPU machines
- The environment flag `USE_GPU_QUEUE` influences how the SENDER routes tasks. That means it matters on the web app, not on the worker container. Setting `USE_GPU_QUEUE=true` inside the worker does not change which queue the worker consumes; that’s controlled by `-Q`/`CELERY_QUEUES`.

## CLI/env flags: what’s required vs optional

Required for workers that touch the DB and broker:
- CELERY_BROKER_URL: Redis broker URL (e.g., `redis://host:6379/0`)
- CELERY_RESULT_BACKEND: Redis backend URL (often same as broker)
- DATABASE_URL: Postgres URL (the worker reads/writes DB via tasks)

Recommended:
- TMPDIR: set to `/app/instance/tmp` on shared/network storage to avoid EXDEV issues
- CELERY_CONCURRENCY: number of worker processes; 1 by default in the image
- CELERY_QUEUES: comma-separated list of queues to consume; default `gpu,celery` in the image

Optional / context-dependent:
- FFMPEG_BINARY, YT_DLP_BINARY: override paths to local binaries
- REDIS_URL: used by the Flask app as a fallback; not needed if `CELERY_*` are set for the worker
- MEDIA_PATH_ALIAS_FROM, MEDIA_PATH_ALIAS_TO: only needed when the worker’s filesystem root differs from what’s stored in the DB
- MEDIA_PATH_DEBUG: temporary debugging of path resolution
- USE_GPU_QUEUE: only affects the sender’s routing (web app). Not needed in the worker container.

Redundancies to avoid:
- Passing both `REDIS_URL` and `CELERY_*` is redundant for the worker; prefer `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`
- Setting `USE_GPU_QUEUE` in the worker container has no effect on which queue the worker reads; use `-Q`/`CELERY_QUEUES`

## Troubleshooting tips

- “Connection refused” to Redis on localhost inside the container: use `host.docker.internal` (Windows/macOS), or add `--add-host=host.docker.internal:host-gateway` on Linux
- Cross-device link (EXDEV) when saving final outputs: set `TMPDIR=/app/instance/tmp`
- Media path not found: verify the file exists on the bind-mounted path and consider `MEDIA_PATH_ALIAS_*` with `MEDIA_PATH_DEBUG=1`
- NVENC not used: ensure the host GPU is available to Docker (`--gpus all`), and your ffmpeg supports NVENC. The app falls back to CPU (libx264) automatically.
  - On WSL2 host shells (native worker, not container), if you see `Cannot load libcuda.so.1`, export `LD_LIBRARY_PATH=/usr/lib/wsl/lib:${LD_LIBRARY_PATH}` before invoking ffmpeg or the checker.
  - If both a bundled `./bin/ffmpeg` and a system ffmpeg exist, set `PREFER_SYSTEM_FFMPEG=1` to prefer the system build (often NVENC-enabled).

### Upgrades and task signatures

If you update the repo and see Celery errors like `unexpected keyword argument 'clip_ids'`, your worker container/process is running an older version of the code than the web app. Rebuild and restart the worker(s) so they pick up the latest tasks, and restart the web app to keep both sides in sync. After any change that modifies a task signature, always restart both web and workers.

---

For end-to-end networking and storage patterns (WireGuard + Samba), see `docs/wireguard.md` and `docs/samba-and-mounts.md`.
