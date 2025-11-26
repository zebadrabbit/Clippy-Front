#!/usr/bin/env bash
# Start Celery worker with version-based naming
#
# Usage:
#   scripts/worker/start-celery-versioned.sh [worker-name] [queues] [concurrency] [redis-db]
#
# Examples:
#   # Production GPU worker (Redis DB 1, opt_ tables)
#   scripts/worker/start-celery-versioned.sh tundra-gpu "gpu,celery" 2
#
#   # Development worker (Redis DB 0, dev_ tables)
#   scripts/worker/start-celery-versioned.sh dev-worker "celery" 2 0
#
#   # Main production worker on celery queue with 4 workers
#   scripts/worker/start-celery-versioned.sh main "celery" 4

set -Eeuo pipefail

# Repo root is assumed to be the parent of scripts/worker/
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

# Arguments with defaults
WORKER_NAME="${1:-main}"
CELERY_QUEUES="${2:-celery,gpu,cpu}"
CELERY_CONCURRENCY="${3:-2}"
REDIS_DB="${4:-1}"  # Default to production Redis DB 1

# Determine environment based on Redis DB
if [[ "$REDIS_DB" == "0" ]]; then
  ENVIRONMENT="dev"
  export TABLE_PREFIX="dev_"
else
  ENVIRONMENT="prod"
  export TABLE_PREFIX="opt_"
fi

# Check for venv
if [[ ! -d "venv" ]]; then
  echo "Error: No venv found at ${REPO_ROOT}/venv" >&2
  echo "Create one with: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

# Activate venv
source venv/bin/activate

# Override Redis configuration based on environment
REDIS_HOST="${REDIS_HOST:-10.8.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
export REDIS_URL="redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
export CELERY_BROKER_URL="redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
export CELERY_RESULT_BACKEND="redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"

# For production workers (remote or local), clear CLIPPY_INSTANCE_PATH
# Remote workers access files via MEDIA_BASE_URL API, not local filesystem
if [[ "$REDIS_DB" == "1" ]]; then
  unset CLIPPY_INSTANCE_PATH
fi

# Get version from app
VERSION=$(python -c "from app.version import __version__; print(__version__)")

if [[ -z "$VERSION" ]]; then
  echo "Error: Could not determine version from app.version" >&2
  exit 1
fi

# Build worker hostname with version
WORKER_HOSTNAME="${WORKER_NAME}-v${VERSION}@%h"

# Display config
echo "========================================"
echo "Starting Celery Worker (Versioned)"
echo "========================================"
echo "Environment:       ${ENVIRONMENT} (TABLE_PREFIX=${TABLE_PREFIX})"
echo "Version:           ${VERSION}"
echo "Worker Name:       ${WORKER_HOSTNAME}"
echo "Queues:            ${CELERY_QUEUES}"
echo "Concurrency:       ${CELERY_CONCURRENCY}"
echo "Redis DB:          ${REDIS_DB}"
echo "Broker URL:        ${CELERY_BROKER_URL}"
echo "========================================"

# Start the worker with version-based naming
exec celery -A app.tasks.celery_app worker \
  -n "${WORKER_HOSTNAME}" \
  -Q "${CELERY_QUEUES}" \
  -c "${CELERY_CONCURRENCY}" \
  --loglevel=info
