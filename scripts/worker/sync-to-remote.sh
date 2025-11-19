#!/usr/bin/env bash
# Sync ClippyFront repo to a remote machine for running a GPU worker.
#
# Usage:
#   scripts/worker/sync-to-tundra.sh [user@]host[:port] [remote_path]
#
# Examples:
#   scripts/worker/sync-to-tundra.sh winter@192.168.1.119
#   scripts/worker/sync-to-tundra.sh winter@192.168.1.119:2222 ~/ClippyFront
#   REMOTE_USER=winter REMOTE_HOST=tundra scripts/worker/sync-to-tundra.sh

set -Eeuo pipefail

# Parse first argument if provided: [user@]host[:port]
if [[ -n "${1:-}" ]]; then
  # Extract user, host, port from user@host:port format
  ARG="$1"
  if [[ "$ARG" =~ ^([^@]+)@([^:]+):([0-9]+)$ ]]; then
    REMOTE_USER="${BASH_REMATCH[1]}"
    REMOTE_HOST="${BASH_REMATCH[2]}"
    REMOTE_PORT="${BASH_REMATCH[3]}"
  elif [[ "$ARG" =~ ^([^@]+)@([^:]+)$ ]]; then
    REMOTE_USER="${BASH_REMATCH[1]}"
    REMOTE_HOST="${BASH_REMATCH[2]}"
    REMOTE_PORT="${REMOTE_PORT:-22}"
  elif [[ "$ARG" =~ ^([^:]+):([0-9]+)$ ]]; then
    REMOTE_HOST="${BASH_REMATCH[1]}"
    REMOTE_PORT="${BASH_REMATCH[2]}"
    REMOTE_USER="${REMOTE_USER:-${USER}}"
  else
    REMOTE_HOST="$ARG"
    REMOTE_USER="${REMOTE_USER:-${USER}}"
    REMOTE_PORT="${REMOTE_PORT:-22}"
  fi
else
  REMOTE_USER="${REMOTE_USER:-${USER}}"
  REMOTE_HOST="${REMOTE_HOST:-}"
  REMOTE_PORT="${REMOTE_PORT:-22}"
fi

# Second argument is remote path
REMOTE_PATH="${2:-${REMOTE_PATH:-~/ClippyFront}}"

# Validate required values
if [[ -z "$REMOTE_HOST" ]]; then
  echo "Usage: $0 [user@]host[:port] [remote_path]" >&2
  echo "" >&2
  echo "Examples:" >&2
  echo "  $0 winter@192.168.1.119:2222" >&2
  echo "  $0 tundra:2222 ~/ClippyFront" >&2
  echo "  REMOTE_HOST=tundra REMOTE_PORT=2222 $0" >&2
  exit 1
fi
LOCAL_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "Syncing repository to remote worker..."
echo "  Local:  ${LOCAL_REPO}"
echo "  Remote: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}:${REMOTE_PATH}"
echo ""

rsync -avz --delete \
  -e "ssh -p ${REMOTE_PORT}" \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.git/' \
  --exclude 'instance/data/' \
  --exclude 'instance/logs/' \
  --exclude 'artifacts/' \
  --exclude 'tmp/' \
  --exclude 'logs/' \
  --exclude 'data/' \
  --exclude 'uploads/' \
  --exclude 'node_modules/' \
  --exclude '.pytest_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' \
  --exclude 'bin/ffmpeg' \
  --exclude 'bin/ffprobe' \
  --exclude 'bin/yt-dlp' \
  "${LOCAL_REPO}/" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"

echo "✓ Sync complete. Now run: ssh -p ${REMOTE_PORT} ${REMOTE_USER}@${REMOTE_HOST}"
