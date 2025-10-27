#!/usr/bin/env bash
# Launch the ClippyFront GPU Celery worker in Docker with sane defaults.
#
# Usage:
#   scripts/run_gpu_worker.sh
#
# You can override defaults via environment variables in your shell before invoking this script.
# Below are the defaults applied if not provided.
#   IMAGE=clippyfront-gpu-worker:latest
#   NAME=clippy-gpu-worker
#   CELERY_BROKER_URL=redis://host.docker.internal:6379/0
#   CELERY_RESULT_BACKEND=$CELERY_BROKER_URL
#   DATABASE_URL=postgresql://postgres:postgres@host.docker.internal/clippy_front
#   INSTANCE_HOST_PATH=/mnt/clippyfront            # host path that contains data/, tmp/, assets/
#   CLIPPY_INSTANCE_PATH=/app/instance             # instance dir inside the container
#   REQUIRE_INSTANCE_MOUNT=1                       # fail fast if missing
#   TMPDIR=/app/instance/tmp                       # temp inside container (good for CIFS)
#   EXTRA_DOCKER_ARGS="--detach"                  # any extra flags for docker run
#
# Path aliasing is disabled by default. Only set BOTH if you are migrating legacy
# absolute paths and need the worker to translate them at runtime.
#   MEDIA_PATH_ALIAS_FROM=/app/instance/
#   MEDIA_PATH_ALIAS_TO=/mnt/clippyfront/
#
# On Linux, if you use host.docker.internal in URLs, we'll add the host-gateway mapping.

set -Eeuo pipefail

require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 127; }; }
require_cmd docker

IMAGE="${IMAGE:-clippyfront-gpu-worker:latest}"
NAME="${NAME:-clippy-gpu-worker}"
BROKER_URL="${CELERY_BROKER_URL:-redis://host.docker.internal:6379/0}"
RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$BROKER_URL}"
DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@host.docker.internal/clippy_front}"
# Host path that corresponds to the instance root (should contain data/, tmp/, assets/)
INSTANCE_HOST_PATH="${INSTANCE_HOST_PATH:-/mnt/clippyfront}"
# Inside the container, the app should use /app/instance as its instance path
CLIPPY_INSTANCE_PATH="${CLIPPY_INSTANCE_PATH:-/app/instance}"
REQUIRE_INSTANCE_MOUNT="${REQUIRE_INSTANCE_MOUNT:-1}"
TMPDIR_IN_CONTAINER="${TMPDIR:-/app/instance/tmp}"
EXTRA_DOCKER_ARGS="${EXTRA_DOCKER_ARGS:-}"

# Optional path aliasing: default to empty strings so set -u doesn't fail
MEDIA_PATH_ALIAS_FROM="${MEDIA_PATH_ALIAS_FROM:-}"
MEDIA_PATH_ALIAS_TO="${MEDIA_PATH_ALIAS_TO:-}"

if [[ "${REQUIRE_INSTANCE_MOUNT}" =~ ^(?i:1|true|yes|on)$ ]]; then
  if [[ ! -d "${INSTANCE_HOST_PATH}" ]]; then
    echo "Required instance mount not found: ${INSTANCE_HOST_PATH}" >&2
    echo "Create/mount it on the host, then re-run." >&2
    exit 1
  fi
  # Sanity: warn if this doesn't look like an instance root
  if [[ ! -d "${INSTANCE_HOST_PATH}/data" ]]; then
    echo "Warning: ${INSTANCE_HOST_PATH} does not contain a data/ directory. If your instance lives at <repo>/instance, set INSTANCE_HOST_PATH=\"$(pwd)/instance\"." >&2
  fi
fi

# Create tmp dir on host to avoid container failing on first write
mkdir -p "${INSTANCE_HOST_PATH}/tmp" || true

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
  -e CELERY_BROKER_URL="${BROKER_URL}" \
  -e CELERY_RESULT_BACKEND="${RESULT_BACKEND}" \
  -e DATABASE_URL="${DATABASE_URL}" \
  -e REQUIRE_INSTANCE_MOUNT="${REQUIRE_INSTANCE_MOUNT}" \
  -e CLIPPY_INSTANCE_PATH="${CLIPPY_INSTANCE_PATH}" \
  -e MEDIA_PATH_ALIAS_FROM="${MEDIA_PATH_ALIAS_FROM}" \
  -e MEDIA_PATH_ALIAS_TO="${MEDIA_PATH_ALIAS_TO}" \
  -e PREFER_SYSTEM_FFMPEG=1 \
  -e TMPDIR="${TMPDIR_IN_CONTAINER}" \
  -v "${INSTANCE_HOST_PATH}:/app/instance" \
  --name "${NAME}" \
  ${EXTRA_DOCKER_ARGS} \
  "${IMAGE}"
