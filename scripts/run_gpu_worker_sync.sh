#!/usr/bin/env bash
# Launch the combined GPU Celery worker + artifact sync in a single container.
# This runs Celery, clippy-scan, clippy-push, and clippy-retain under Supervisor.
#
# Usage:
#   scripts/run_gpu_worker_sync.sh            # uses defaults and named volume for /artifacts
#   ARTIFACTS_HOST_PATH=/srv/clippy/artifacts \
#     scripts/run_gpu_worker_sync.sh          # bind-mount /artifacts from host
#
# Optional: set BUILD=1 to build the image from docker/worker-combined.Dockerfile first.
#   BUILD=1 scripts/run_gpu_worker_sync.sh

set -Eeuo pipefail

require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 127; }; }
require_cmd docker

# --- Image + runtime defaults ---
IMAGE="${IMAGE:-clippyfront-gpu-worker-sync:latest}"
DOCKERFILE="${DOCKERFILE:-docker/worker-combined.Dockerfile}"
NAME="${NAME:-clippy-gpu-worker-sync}"

# Core connectivity (override in environment or .env)
BROKER_URL="${CELERY_BROKER_URL:-redis://host.docker.internal:6379/0}"
RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$BROKER_URL}"
DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@host.docker.internal/clippy_front}"

# Instance storage
INSTANCE_HOST_PATH="${HOST_INSTANCE_PATH:-/mnt/clippyfront}"
CLIPPY_INSTANCE_PATH="${CLIPPY_INSTANCE_PATH:-/app/instance}"
REQUIRE_INSTANCE_MOUNT="${REQUIRE_INSTANCE_MOUNT:-1}"
TMPDIR_IN_CONTAINER="${TMPDIR:-/app/instance/tmp}"

# Artifacts storage: bind-mount if ARTIFACTS_HOST_PATH is set; else use a named volume
ARTIFACTS_HOST_PATH="${ARTIFACTS_HOST_PATH:-}"
ARTIFACTS_VOLUME="${ARTIFACTS_VOLUME:-clippy_artifacts}"

# Artifact export + sync
ARTIFACTS_DIR_IN_CONTAINER="${ARTIFACTS_DIR:-/artifacts}"
WORKER_ID="${WORKER_ID:-gpu-worker-01}"
INGEST_HOST="${INGEST_HOST:-localhost}"
INGEST_USER="${INGEST_USER:-ingest}"
INGEST_PORT="${INGEST_PORT:-22}"
INGEST_PATH="${INGEST_PATH:-/srv/ingest}"
PUSH_INTERVAL="${PUSH_INTERVAL:-60}"
WATCH_MODE="${WATCH_MODE:-auto}"
STABLE_MINUTES="${STABLE_MINUTES:-1}"
CLEANUP_MODE="${CLEANUP_MODE:-none}"
RSYNC_BWLIMIT="${RSYNC_BWLIMIT:-}"
RSYNC_EXTRA_FLAGS="${RSYNC_EXTRA_FLAGS:-}"
DELIVERY_WEBHOOK_URL="${DELIVERY_WEBHOOK_URL:-}"
DELIVERY_WEBHOOK_TOKEN="${DELIVERY_WEBHOOK_TOKEN:-}"
DELIVERY_WEBHOOK_TIMEOUT="${DELIVERY_WEBHOOK_TIMEOUT:-5}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
MIN_FREE_GB="${MIN_FREE_GB:-}"

# Secrets
SECRETS_DIR="${SECRETS_DIR:-$(pwd)/secrets}"
RSYNC_KEY_PATH="${RSYNC_KEY_PATH:-${SECRETS_DIR}/rsync_key}"
KNOWN_HOSTS_PATH="${KNOWN_HOSTS_PATH:-${SECRETS_DIR}/known_hosts}"

# Optional path aliasing (usually not needed)
MEDIA_PATH_ALIAS_FROM="${MEDIA_PATH_ALIAS_FROM:-}"
MEDIA_PATH_ALIAS_TO="${MEDIA_PATH_ALIAS_TO:-}"

# Build image if requested
if [[ "${BUILD:-0}" != 0 ]]; then
  docker build -f "$DOCKERFILE" -t "$IMAGE" .
fi

# Validate instance mount
if [[ "$REQUIRE_INSTANCE_MOUNT" =~ ^(?i:1|true|yes|on)$ ]]; then
  if [[ ! -d "$INSTANCE_HOST_PATH" ]]; then
    echo "Required instance mount not found: $INSTANCE_HOST_PATH" >&2
    echo "Create/mount it on the host, then re-run." >&2
    exit 1
  fi
  mkdir -p "$INSTANCE_HOST_PATH/tmp" || true
fi

# Prepare artifact bind mount arg
ARTIFACTS_MOUNT_ARG=( -v "${ARTIFACTS_VOLUME}:${ARTIFACTS_DIR_IN_CONTAINER}" )
if [[ -n "$ARTIFACTS_HOST_PATH" ]]; then
  mkdir -p "$ARTIFACTS_HOST_PATH" || true
  ARTIFACTS_MOUNT_ARG=( -v "${ARTIFACTS_HOST_PATH}:${ARTIFACTS_DIR_IN_CONTAINER}" )
fi

# Secrets mount args (best-effort)
SECRET_ARGS=()
if [[ -f "$RSYNC_KEY_PATH" ]]; then
  SECRET_ARGS+=( -v "${RSYNC_KEY_PATH}:/run/secrets/rsync_key:ro" )
else
  echo "Warning: SSH key not found at $RSYNC_KEY_PATH — rsync pushes will fail." >&2
fi
if [[ -f "$KNOWN_HOSTS_PATH" ]]; then
  SECRET_ARGS+=( -v "${KNOWN_HOSTS_PATH}:/run/secrets/known_hosts:ro" )
else
  echo "Warning: known_hosts not found at $KNOWN_HOSTS_PATH — host key verification will fail." >&2
fi

# Add host-gateway mapping on Linux if using host.docker.internal
ADD_HOST_ARG=""
if [[ "$(uname -s)" == "Linux" ]]; then
  case "${BROKER_URL}${RESULT_BACKEND}${DATABASE_URL}" in
    *host.docker.internal*) ADD_HOST_ARG="--add-host=host.docker.internal:host-gateway" ;;
  esac
fi

set -x
exec docker run --rm \
  --gpus all \
  ${ADD_HOST_ARG} \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
  # Core app/worker env
  -e CELERY_BROKER_URL="${BROKER_URL}" \
  -e CELERY_RESULT_BACKEND="${RESULT_BACKEND}" \
  -e DATABASE_URL="${DATABASE_URL}" \
  -e REQUIRE_INSTANCE_MOUNT="${REQUIRE_INSTANCE_MOUNT}" \
  -e CLIPPY_INSTANCE_PATH="${CLIPPY_INSTANCE_PATH}" \
  -e TMPDIR="${TMPDIR_IN_CONTAINER}" \
  -e MEDIA_PATH_ALIAS_FROM="${MEDIA_PATH_ALIAS_FROM}" \
  -e MEDIA_PATH_ALIAS_TO="${MEDIA_PATH_ALIAS_TO}" \
  # Artifact export + sync env
  -e ARTIFACTS_DIR="${ARTIFACTS_DIR_IN_CONTAINER}" \
  -e WORKER_ID="${WORKER_ID}" \
  -e INGEST_HOST="${INGEST_HOST}" \
  -e INGEST_USER="${INGEST_USER}" \
  -e INGEST_PORT="${INGEST_PORT}" \
  -e INGEST_PATH="${INGEST_PATH}" \
  -e PUSH_INTERVAL="${PUSH_INTERVAL}" \
  -e WATCH_MODE="${WATCH_MODE}" \
  -e STABLE_MINUTES="${STABLE_MINUTES}" \
  -e CLEANUP_MODE="${CLEANUP_MODE}" \
  -e RSYNC_BWLIMIT="${RSYNC_BWLIMIT}" \
  -e RSYNC_EXTRA_FLAGS="${RSYNC_EXTRA_FLAGS}" \
  -e DELIVERY_WEBHOOK_URL="${DELIVERY_WEBHOOK_URL}" \
  -e DELIVERY_WEBHOOK_TOKEN="${DELIVERY_WEBHOOK_TOKEN}" \
  -e DELIVERY_WEBHOOK_TIMEOUT="${DELIVERY_WEBHOOK_TIMEOUT}" \
  -e RETENTION_DAYS="${RETENTION_DAYS}" \
  -e MIN_FREE_GB="${MIN_FREE_GB}" \
  -v "${INSTANCE_HOST_PATH}:/app/instance" \
  "${ARTIFACTS_MOUNT_ARG[@]}" \
  "${SECRET_ARGS[@]}" \
  --name "${NAME}" \
  "${IMAGE}"
