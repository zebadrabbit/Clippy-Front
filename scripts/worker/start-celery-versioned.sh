#!/usr/bin/env bash
# Start Celery worker with version-based naming
#
# Usage:
#   scripts/worker/start-celery-versioned.sh [worker-name] [queues] [concurrency]
#
# Examples:
#   # Default: main worker on celery queue with 2 workers
#   scripts/worker/start-celery-versioned.sh
#
#   # GPU worker on gpu,celery queues with 2 workers
#   scripts/worker/start-celery-versioned.sh gpu "gpu,celery" 2
#
#   # Main worker on celery queue with 4 workers
#   scripts/worker/start-celery-versioned.sh main "celery" 4

set -Eeuo pipefail

# Repo root is assumed to be the parent of scripts/worker/
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

# Arguments with defaults
WORKER_NAME="${1:-main}"
CELERY_QUEUES="${2:-celery,gpu,cpu}"
CELERY_CONCURRENCY="${3:-2}"

# Check for venv
if [[ ! -d "venv" ]]; then
  echo "Error: No venv found at ${REPO_ROOT}/venv" >&2
  echo "Create one with: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

# Activate venv
source venv/bin/activate

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
echo "Version:     ${VERSION}"
echo "Worker Name: ${WORKER_HOSTNAME}"
echo "Queues:      ${CELERY_QUEUES}"
echo "Concurrency: ${CELERY_CONCURRENCY}"
echo "========================================"

# Start the worker with version-based naming
exec celery -A app.tasks.celery_app worker \
  -n "${WORKER_HOSTNAME}" \
  -Q "${CELERY_QUEUES}" \
  -c "${CELERY_CONCURRENCY}" \
  --loglevel=info
