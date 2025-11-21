#!/usr/bin/env bash
# Start Celery GPU worker on a remote machine (tundra).
#
# Usage:
#   scripts/worker/run-worker-remote.sh
#
# This script is intended to be run ON the remote machine (tundra) after syncing.
# It activates the venv, sets up environment, and starts the Celery worker.

set -Eeuo pipefail

# Repo root is assumed to be the parent of scripts/worker/
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

# Check for venv
if [[ ! -d "venv" ]]; then
  echo "No venv found. Creating one..."
  python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install/upgrade dependencies
echo "Installing dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Load environment from .env.worker if it exists
if [[ -f .env.worker ]]; then
  echo "Loading .env.worker"
  set -a
  source .env.worker
  set +a
else
  echo "Warning: .env.worker not found. Using defaults/environment variables."
fi

# Set required environment variables (override with your actual values)
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://192.168.1.100:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://192.168.1.100:6379/0}"
export FLASK_APP_URL="${FLASK_APP_URL:-http://192.168.1.100:5000}"
export WORKER_API_KEY="${WORKER_API_KEY:-}"

# Instance path (shared storage mount point on tundra)
export CLIPPY_INSTANCE_PATH="${CLIPPY_INSTANCE_PATH:-/mnt/clippyfront}"
export HOST_INSTANCE_PATH="${HOST_INSTANCE_PATH:-/mnt/clippyfront}"

# Queue configuration for GPU worker
export CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-2}"
export USE_GPU_QUEUE="${USE_GPU_QUEUE:-true}"

# GPU worker listens to gpu,celery queues
CELERY_QUEUES="${CELERY_QUEUES:-gpu,celery}"

# Optional: disable NVENC if needed (leave unset to auto-detect)
# export FFMPEG_DISABLE_NVENC=0

# Temp dir (useful for CIFS/SMB mounts to avoid EXDEV errors)
export TMPDIR="${TMPDIR:-${CLIPPY_INSTANCE_PATH}/tmp}"
mkdir -p "${TMPDIR}" 2>/dev/null || true

# Ensure instance path exists
if [[ ! -d "${CLIPPY_INSTANCE_PATH}" ]]; then
  echo "Error: CLIPPY_INSTANCE_PATH not found: ${CLIPPY_INSTANCE_PATH}"
  echo "Ensure shared storage is mounted on tundra."
  exit 1
fi

# Get version from app
VERSION=$(python -c "from app.version import __version__; print(__version__)")

if [[ -z "$VERSION" ]]; then
  echo "Error: Could not determine version from app.version" >&2
  exit 1
fi

# Build worker hostname with version
WORKER_NAME="${WORKER_NAME:-tundra-gpu}"
WORKER_HOSTNAME="${WORKER_NAME}-v${VERSION}@%h"

# Display config
echo "========================================"
echo "Starting Celery GPU Worker (Versioned)"
echo "========================================"
echo "Version:   ${VERSION}"
echo "Broker:    ${CELERY_BROKER_URL}"
echo "Backend:   ${CELERY_RESULT_BACKEND}"
echo "Flask API: ${FLASK_APP_URL}"
echo "Instance:  ${CLIPPY_INSTANCE_PATH}"
echo "Queues:    ${CELERY_QUEUES}"
echo "Concurrency: ${CELERY_CONCURRENCY}"
echo "Hostname:  ${WORKER_HOSTNAME}"
echo "========================================"

# Start the worker
exec celery -A app.tasks.celery_app worker \
  --loglevel=info \
  --concurrency="${CELERY_CONCURRENCY}" \
  --queues="${CELERY_QUEUES}" \
  --hostname="${WORKER_HOSTNAME}"
