# Running workers (Linux and Windows/WSL2)

This guide consolidates how to run ClippyFront workers on Linux and Windows (via WSL2), with and without Docker, plus an audit of the flags/env vars you actually need.

Use cases
- GPU worker in Docker on Windows/WSL2 or Linux (NVENC-enabled ffmpeg preferred)
- Native Celery worker (no Docker) on Linux/WSL2 for CPU or GPU
- Shared storage and cross-host path handling

If you only need the GPU-in-Docker recipe, see also `docs/gpu-worker.md`. It now links back here for details and troubleshooting.

## Prerequisites

- Redis and PostgreSQL reachable from the worker
  - Prefer private/VPN networking (see `docs/wireguard.md`). Avoid exposing 6379/5432 publicly.
- Shared storage for media (the app’s `instance/` directory).
  - REQUIRED: host mount at `/mnt/clippy` containing `uploads/`, `downloads/`, `compilations/`, `tmp/`, and `assets/`
  - Bind-mount `/mnt/clippy` into the container at `/app/instance`
  - The app prefers `/mnt/clippy` as its instance path and can enforce its presence with `REQUIRE_INSTANCE_MOUNT=1`
  - See `docs/samba-and-mounts.md` for Linux/Windows/WSL2 mounts
- For GPU in Docker
  - Linux: NVIDIA drivers + nvidia-container-toolkit installed
  - Windows: Docker Desktop with WSL2 + NVIDIA GPU support enabled

## Quick starts

### A) GPU worker in Docker (Windows/WSL2 or Linux)

Minimal, required flags only. Replace credentials/hosts for your setup.

Windows/WSL2 (host.docker.internal works):

```bash
# From repo root (after docker build)
# docker build -f docker/worker.Dockerfile -t clippyfront-gpu-worker:latest .

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
  -v "/mnt/clippy:/app/instance" \
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
export CLIPPY_INSTANCE_PATH=/mnt/clippy
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

- REQUIRED mount: `/mnt/clippy` on the host; bind-mount to `/app/instance` for containers
- When sharing over CIFS/SMB, mount the remote path on the worker host (Linux or WSL2) at `/mnt/clippy`, then bind-mount that into the container

Cross-host path aliasing:

- If file paths in the database have a different root on your worker than on the web server, use alias envs to translate:
  - `MEDIA_PATH_ALIAS_FROM=/app/instance/`
  - `MEDIA_PATH_ALIAS_TO=/mnt/clippy/`
- The web app also auto-rebases any path containing `/instance/` under its own `instance_path` if it exists on disk
- Enable `MEDIA_PATH_DEBUG=1` temporarily to log how paths are resolved (both web server and worker)

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

---

For end-to-end networking and storage patterns (WireGuard + Samba), see `docs/wireguard.md` and `docs/samba-and-mounts.md`.
