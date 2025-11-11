# GPU Celery Worker in Docker (with artifact sync)

This image runs the ClippyFront Celery worker in a CUDA-enabled Linux container, suitable for GPU hosts (Windows via Docker Desktop + WSL2, or Linux).

For native workers, storage/path mapping, and a full flag matrix, see `docs/workers.md`.

## Artifact export and rsync sync

If you want workers to push final renders to a central ingest host, enable artifact export and run the provided artifact‑sync sidecar. The flow is:

- Worker writes final outputs to a shared volume at `/artifacts` and drops a `.DONE` sentinel (the scanner can also detect readiness by stability if `.DONE` is missing).
- Scanner promotes `.DONE` → `.READY` and triggers an immediate push (inotify), with periodic sweeps as a safety net.
- Pusher rsyncs any `.READY` directory to `${INGEST_USER}@${INGEST_HOST}:${INGEST_PATH}/${WORKER_ID}/<dir>` with StrictHostKeyChecking.

Quickstart (sidecar + worker via Compose — local-first)

```
# 1) Generate SSH keypair and known_hosts
mkdir -p secrets
ssh-keygen -t ed25519 -N "" -f secrets/rsync_key
# Example: ingest behind WireGuard at 10.8.0.1:22
# Prefer the ED25519 host key type for StrictHostKeyChecking
ssh-keyscan -p 22 -t ed25519 -H 10.8.0.1 > secrets/known_hosts

# 2) Add public key to ingest host (as the target user)
cat secrets/rsync_key.pub   # append to ~ingest/.ssh/authorized_keys on the ingest box

# 3) Minimal .env for the sync sidecar
cat > .env <<'EOF'
WORKER_ID=gpu-worker-01
INGEST_HOST=10.8.0.1
INGEST_USER=ingest
INGEST_PORT=22
INGEST_PATH=/srv/ingest
PUSH_INTERVAL=60
# Default watch mode is auto (inotify + periodic sweeps)
WATCH_MODE=auto
EOF

# 4) Bring up the stack (local-first; builds worker locally, no GHCR needed)
docker compose -f compose.worker.yaml --profile local up -d --build worker-local artifact-sync

# Optional: create a dummy artifact to test end-to-end
docker compose -f compose.worker.yaml run --rm artifact-sync /scripts/worker/smoke-artifact.sh

# Inspect logs
docker compose -f compose.worker.yaml logs --tail=200 artifact-sync
```

Alternative: pull the published worker image from GHCR (optional)

```
# Authenticate (requires a GitHub token with read:packages)
# echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin

# Bring up the worker + artifact-sync using the published image
docker compose -f compose.worker.yaml up -d --build worker artifact-sync
```

Prepare SSH materials beforehand (as Docker secrets):

- `secrets/rsync_key` (private key) and `secrets/known_hosts` (from `ssh-keyscan`) — see README “Deployment → Worker Setup”.

Environment (artifact‑sync sidecar)

- Required: `WORKER_ID`, `INGEST_HOST`, `INGEST_USER`, `INGEST_PATH`
- Optional: `INGEST_PORT` (22), `PUSH_INTERVAL` (60), `WATCH_MODE` (`auto`|`inotify`|`poll`)
  - Tuning: `RSYNC_BWLIMIT` (KB/s), `RSYNC_EXTRA_FLAGS` (e.g., `--chmod=F644,D755`)
  - Retention: `CLEANUP_MODE=none|delete|archive` (archive moves to `/artifacts/_pushed/<dir>`)

Delivery webhook (optional): set `DELIVERY_WEBHOOK_URL` and optionally `DELIVERY_WEBHOOK_TOKEN` for a POST per push.

Readiness and latency:

- Default `WATCH_MODE=auto` uses inotify for instant reactions when `.DONE`/`.READY` appears and still sweeps every `PUSH_INTERVAL` seconds.
- If your worker never creates `.DONE`, the scanner uses stability detection (no writes for ~1 minute) before promoting `.READY`. Set `STABLE_MINUTES=0` if you always write `.DONE`.

Troubleshooting host key verification

- If you see `Host key verification failed.`, refresh `secrets/known_hosts` for the exact host and port you target, then recreate the container:

```
ssh-keyscan -p 22 -t ed25519 -H 10.8.0.1 > secrets/known_hosts
docker compose -f compose.worker.yaml up -d --force-recreate artifact-sync
```

### Single-container: GPU worker + artifact sync (optional)

Prefer the sidecar model for clarity and isolation. If you still want a single container on the worker host, use the combined image that launches Celery and the sync sidecars under Supervisor:

Build and run with Compose:

```
# Set these in your .env first: CELERY_BROKER_URL, CELERY_RESULT_BACKEND, DATABASE_URL,
# HOST_INSTANCE_PATH, WORKER_ID, INGEST_HOST, INGEST_USER, INGEST_PATH

docker compose -f docker/docker-compose.gpu-worker-sync.yml up -d --build
```

Notes:

- The combined image is defined in `docker/worker-combined.Dockerfile` and includes `rsync`, `openssh-client`, `inotify-tools`, and Supervisor.
- It runs four programs: Celery worker, clippy-scan, clippy-push, and clippy-retain.
- Secrets `rsync_key` and `known_hosts` are mounted at `/run/secrets/...` just like the two-container stack.
- Artifacts mount is configurable via `ARTIFACTS_HOST_PATH` in `.env` (or defaults to the named volume `artifacts`).

Artifacts mount location (Compose)

- For the `compose.worker.yaml` stack in this repo, artifacts are stored in a named Docker volume `artifacts` mounted at `/artifacts` in both worker and sync. No host directory mounts are required.
- Inside the worker container, set `ARTIFACTS_DIR=/artifacts` so the compile step exports to that path.

## Prereqs
- Docker Desktop with WSL2 (Windows) and NVIDIA GPU support enabled
- Latest NVIDIA drivers on the host
- Redis broker reachable from container (default: `redis://host.docker.internal:6379/0`)

## Build
```
# From repo root
docker build -f docker/worker.Dockerfile -t clippyfront-gpu-worker:latest .
```

## Run (simple)
```
# REQUIREMENT: mount your shared storage at /mnt/clippyfront on the host and bind it
# into the container at /app/instance. Inside the container, set
# CLIPPY_INSTANCE_PATH=/app/instance so the app resolves paths correctly.
# You can enforce the mount with REQUIRE_INSTANCE_MOUNT=1.
docker run --rm \
  --gpus all \
  -e CELERY_BROKER_URL=redis://host.docker.internal:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/0 \
  -e DATABASE_URL=postgresql://<user>:<pass>@host.docker.internal/clippy_front \
  -e TMPDIR=/app/instance/tmp \
  -e REQUIRE_INSTANCE_MOUNT=1 \
  -e CLIPPY_INSTANCE_PATH=/app/instance \
  -v /mnt/clippyfront:/app/instance \
  -e ARTIFACTS_DIR=/artifacts \
  -v clippy_artifacts:/artifacts \
  --name clippy-gpu-worker \
  clippyfront-gpu-worker:latest
```

## Run with Compose
```
# Point HOST_INSTANCE_PATH to the same storage used by the web app
# (for example, if your web writes to /mnt/clippyfront on the host)
export HOST_INSTANCE_PATH=/mnt/clippyfront

# Build the image
docker compose -f docker/docker-compose.gpu-worker.yml build

# Run with GPU passthrough via CLI flag (Compose may ignore device reservations)
docker compose -f docker/docker-compose.gpu-worker.yml run --gpus all --name clippy-gpu-worker gpu-worker
```

Notes
- The compose file now mounts ${HOST_INSTANCE_PATH:-/mnt/clippyfront} to /app/instance and sets CLIPPY_INSTANCE_PATH=/app/instance inside the container.
- For the artifact sync stack, use `compose.worker.yaml` at the repo root; it defines a `worker` service (published image), an `artifact-sync` service (rsync/scanner), a named volume `artifacts`, and SSH secrets.
- Ensure the path you set in HOST_INSTANCE_PATH contains the data your web app writes (e.g., /mnt/clippyfront/data/.../clips/... files). If your web app writes to a different host path, update HOST_INSTANCE_PATH accordingly.
- If running on Linux and using host.docker.internal in env URLs, you may need to add a host gateway mapping: --add-host=host.docker.internal:host-gateway.

## Notes
- FFmpeg is installed from Ubuntu packages; NVENC will be used automatically if available. The app will fall back to CPU encode if NVENC isn’t present.
- If your image also includes a bundled `./bin/ffmpeg`, set `PREFER_SYSTEM_FFMPEG=1` so the worker prefers the system ffmpeg (typically the NVENC-enabled one).
- Override concurrency/queues via env: `CELERY_CONCURRENCY=2`, `CELERY_QUEUES=gpu,celery`.
- Ensure the web app and worker share the same database and broker.
 - Queue priority at enqueue is `gpu > cpu > celery`; start your worker with the appropriate `-Q` list.
 - `USE_GPU_QUEUE` affects how the web app routes compile tasks. Setting it inside this worker container does not change which queues the worker consumes; use `-Q`/`CELERY_QUEUES` instead.
 - Avatars/overlays: Set `AVATARS_PATH` to the shared assets root (e.g., `/app/instance/assets`) or directly to `/app/instance/assets/avatars`. The app normalizes both. Enable `OVERLAY_DEBUG=1` to trace avatar resolution. On startup, if overlays are enabled but no avatars are found at the resolved path, a warning is logged once.

### WSL2 NVENC Support

When running on Windows with WSL2 and an NVIDIA GPU, ffmpeg needs access to CUDA libraries. The worker Docker images automatically set `LD_LIBRARY_PATH` to include WSL2 CUDA paths:

```bash
LD_LIBRARY_PATH=/usr/lib/wsl/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib64
```

**Troubleshooting NVENC detection:**

1. Verify NVIDIA drivers are installed on Windows host
2. Check Docker Desktop has "Use WSL 2 based engine" enabled
3. Verify GPU passthrough works:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi
   ```
4. Test NVENC availability in worker container:
   ```bash
   docker exec <worker-container> ffmpeg -hide_banner -encoders | grep nvenc
   ```
5. Check for CUDA library errors in worker logs:
   ```bash
   docker logs <worker-container> 2>&1 | grep -i "cuda\|nvenc"
   ```

If ffmpeg shows "Cannot load libcuda.so.1" or similar errors, verify:
- Windows NVIDIA drivers are up to date (536.67+)
- WSL2 kernel is updated: `wsl --update`
- The `/usr/lib/wsl/lib` directory exists in the container and contains `libcuda.so.1`

To disable NVENC and force CPU encoding (for debugging):
```bash
export FFMPEG_DISABLE_NVENC=1
```

### Optional: standalone artifact sync container

If you only want the sync sidecars (without running the Celery worker in the same compose project), you can run just the `artifact-sync` service from `compose.worker.yaml` and point it at a local `/artifacts` volume where your workflow drops `.DONE`/`.READY` directories.

```
docker compose -f compose.worker.yaml up -d --build artifact-sync
```

Set env via `.env` for the sync destination. The compose file auto-creates a named volume `artifacts`; no host bind is required.

## Deployment guide (GPU worker + sync)

This section consolidates recommended environment variables and example commands for a VPN-backed setup (e.g., 10.8.0.1 via WireGuard):

Example environment (.env)

```
# Core connectivity (points to your VPN server 10.8.0.1)
CELERY_BROKER_URL=redis://10.8.0.1:6379/0
CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0
DATABASE_URL=postgresql://postgres:CHANGEME@10.8.0.1/clippy_front

# Artifact sync destination (SSH target on 10.8.0.1)
WORKER_ID=gpu-worker-01
INGEST_HOST=10.8.0.1
INGEST_USER=ingest
INGEST_PORT=22
INGEST_PATH=/srv/ingest

# Sync behavior
WATCH_MODE=auto          # inotify + periodic sweeps
PUSH_INTERVAL=60         # seconds
STABLE_MINUTES=1         # only used if you don’t write .DONE
CLEANUP_MODE=none        # none | delete | archive
RSYNC_BWLIMIT=           # e.g., 50000 (KB/s) or leave empty
RSYNC_EXTRA_FLAGS=--chmod=F644,D755
```

Secrets setup (host):

```
mkdir -p secrets
ssh-keygen -t ed25519 -N "" -f secrets/rsync_key
ssh-keyscan -p 22 -t ed25519 -H 10.8.0.1 > secrets/known_hosts
# Append secrets/rsync_key.pub to ~ingest/.ssh/authorized_keys on 10.8.0.1
```

Bring up the stack (local-first):

```
docker compose -f compose.worker.yaml --profile local up -d --build worker-local artifact-sync
```

Alternatively, if you prefer to use the published worker image, login to GHCR and run the non-local service:

```
# Authenticate (requires a GitHub token with read:packages)
# echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin

# Or override the image
# WORKER_IMAGE=clippyfront-worker:local docker compose -f compose.worker.yaml up -d --build worker artifact-sync
```

Smoke test and logs:

```
docker compose -f compose.worker.yaml run --rm artifact-sync /scripts/worker/smoke-artifact.sh
docker compose -f compose.worker.yaml logs --tail=200 -f artifact-sync
```

Expected: `.DONE` is promoted to `.READY`, rsync pushes to
`/srv/ingest/${WORKER_ID}/<artifact>`, and a `.PUSHED` file appears locally.

Troubleshooting

- Host key verification failed: regenerate ED25519 known_hosts for the exact host:port and recreate the sync container.
  - `ssh-keyscan -p 22 -t ed25519 -H 10.8.0.1 > secrets/known_hosts`
- Permission denied (publickey): ensure `secrets/rsync_key.pub` is in `~ingest/.ssh/authorized_keys` on the ingest host and perms are strict (700 `~/.ssh`, 600 `authorized_keys`).
- No such file or directory (receiver mkdir): the pusher now creates the full remote path; if this persists, verify `INGEST_PATH` exists and `INGEST_USER` owns it.
- Secrets look like directories in the container: ensure you created files at `secrets/rsync_key` and `secrets/known_hosts` next to `compose.worker.yaml`. Recreate the container after fixing.
- Build warnings (buildx/bake) or TMPDIR errors: set `TMPDIR=/tmp` for compose builds/runs from your host shell.

## Troubleshooting: Redis connection refused inside container

Symptom:

```
[ERROR/MainProcess] consumer: Cannot connect to redis://localhost:6379/0: Error 111 connecting to localhost:6379. Connection refused..
```

Cause: inside the container, `localhost` refers to the container itself. If your `.env` sets `REDIS_URL`, `CELERY_BROKER_URL`, or `CELERY_RESULT_BACKEND` to `redis://localhost:6379/0`, the worker will try to connect to itself and fail. `docker-compose.gpu-worker.yml` includes `env_file: ../.env`, so those values may be inherited unless you override them.

Fix (Windows/macOS with Docker Desktop): override the env vars to use the host gateway name `host.docker.internal`.

Optional command (compose):

```
docker compose -f docker/docker-compose.gpu-worker.yml run --gpus all \
  -e CELERY_BROKER_URL=redis://host.docker.internal:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/0 \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  --name clippy-gpu-worker gpu-worker
```

Optional command (plain docker):

```
docker run --rm --gpus all \
  -e CELERY_BROKER_URL=redis://host.docker.internal:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/0 \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  -e TMPDIR=/app/instance/tmp \
  -e REQUIRE_INSTANCE_MOUNT=1 \
  -e CLIPPY_INSTANCE_PATH=/app/instance \
  -v /mnt/clippyfront:/app/instance \
  --name clippy-gpu-worker clippyfront-gpu-worker:latest
```

If Redis is on another machine, replace `host.docker.internal` with that machine’s IP/DNS (and ensure its firewall allows inbound TCP 6379, and Redis is bound to a reachable interface).

If `host.docker.internal` doesn’t resolve, try adding a host mapping (more common on Linux):

```
--add-host=host.docker.internal:host-gateway
```

Quick connectivity check from inside the container:

```
docker exec -it clippy-gpu-worker python -c "import redis; print(redis.Redis.from_url('redis://host.docker.internal:6379/0').ping())"
```

Security note: opening Redis to the network is unsafe in production. For local dev, limit exposure to your LAN, use firewall rules, and prefer Docker networks over broad binds.

## Secure cross-host networking (WireGuard)
For production-like environments or when crossing untrusted networks, run Redis/Postgres behind a WireGuard VPN and point both the web app and worker to the VPN address instead of host.docker.internal. See `docs/wireguard.md`.

Example worker env with VPN server on 10.8.0.1:

```
CELERY_BROKER_URL=redis://10.8.0.1:6379/0
CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0
REDIS_URL=redis://10.8.0.1:6379/0
DATABASE_URL=postgresql://<user>:<pass>@10.8.0.1/clippy_front
TMPDIR=/app/instance/tmp
```

Note: The worker image sets FLASK_ENV=production, so DEV_DATABASE_URL is ignored. Always set DATABASE_URL explicitly for the worker.

Path aliasing for previews (optional): if the worker writes file paths with a different root than the web server, set these on the web app to translate paths when serving previews/thumbnails:

```
MEDIA_PATH_ALIAS_FROM=/app/instance/
MEDIA_PATH_ALIAS_TO=/mnt/clippyfront/
```

Rebuild tip: if you recently changed code and still hit EXDEV or missing path resolutions, rebuild the worker image without cache:

```
docker build --no-cache -f docker/worker.Dockerfile -t clippyfront-gpu-worker:latest .
```
