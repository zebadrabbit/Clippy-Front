# GPU Celery Worker in Docker

This image runs the ClippyFront Celery worker in a CUDA-enabled Linux container, suitable for GPU hosts (Windows via Docker Desktop + WSL2, or Linux).

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
# Map instance/ for downloads/outputs; pass GPU into container
docker run --rm \
  --gpus all \
  -e CELERY_BROKER_URL=redis://host.docker.internal:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/0 \
  -e DATABASE_URL=postgresql://<user>:<pass>@host.docker.internal/clippy_front \
  -e USE_GPU_QUEUE=true \
  -v $(pwd)/instance:/app/instance \
  --name clippy-gpu-worker \
  clippyfront-gpu-worker:latest
```

## Run with Compose
```
# Build and start with GPU passthrough via CLI flag
docker compose -f docker/docker-compose.gpu-worker.yml build
docker compose -f docker/docker-compose.gpu-worker.yml run --gpus all --name clippy-gpu-worker gpu-worker
```

## Notes
- FFmpeg is installed from Ubuntu packages; NVENC will be used automatically if available. The app will fall back to CPU encode if NVENC isn’t present.
- Override concurrency/queues via env: `CELERY_CONCURRENCY=2`, `CELERY_QUEUES=gpu,celery`.
- Ensure the web app and worker share the same database and broker.

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
  -v $(pwd)/instance:/app/instance \
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
```

Note: The worker image sets FLASK_ENV=production, so DEV_DATABASE_URL is ignored. Always set DATABASE_URL explicitly for the worker.
