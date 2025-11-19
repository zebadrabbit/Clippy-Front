#!/usr/bin/env bash
# Quick setup script for running GPU worker on a remote machine.
#
# Usage:
#   scripts/worker/setup-tundra.sh [user@]host[:port] [remote_path]
#
# Examples:
#   scripts/worker/setup-tundra.sh winter@192.168.1.119:2222
#   scripts/worker/setup-tundra.sh tundra:2222 ~/ClippyFront
#
# This script guides you through the initial setup.

set -Eeuo pipefail

# Parse first argument if provided: [user@]host[:port]
if [[ -n "${1:-}" ]]; then
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
  echo "  $0 worker-gpu:2222 ~/ClippyFront" >&2
  exit 1
fi

echo "========================================"
echo "ClippyFront Remote GPU Worker Setup"
echo "========================================"
echo "Target: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
echo "Path:   ${REMOTE_PATH}"
echo "========================================"
echo

# Step 1: Check SSH connectivity
echo "Step 1: Checking SSH connectivity..."
if ! ssh -p "${REMOTE_PORT}" -o ConnectTimeout=5 "${REMOTE_USER}@${REMOTE_HOST}" "echo 'Connected'" >/dev/null 2>&1; then
  echo "❌ Cannot connect to ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
  echo "   Please ensure:"
  echo "   - Host is reachable"
  echo "   - SSH is configured (try: ssh -p ${REMOTE_PORT} ${REMOTE_USER}@${REMOTE_HOST})"
  exit 1
fi
echo "✓ SSH connection OK"
echo

# Step 2: Generate Worker API Key
echo "Step 2: Worker API Key"
echo "Generating a secure API key..."
API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "Generated API key: ${API_KEY}"
echo
echo "⚠️  IMPORTANT: Add this to your Flask app .env file:"
echo "   WORKER_API_KEY=${API_KEY}"
echo
read -p "Press Enter after you've added the key to Flask app .env and restarted..."
echo

# Step 3: Sync repo
echo "Step 3: Syncing repository to tundra..."
./scripts/worker/sync-to-tundra.sh
echo

# Step 4: Create .env.worker on remote
echo "Step 4: Creating worker configuration..."
echo "You'll need to provide:"
echo "  - Redis host (where your Flask app connects)"
echo "  - Flask app URL"
echo "  - Shared storage mount point"
echo

read -p "Redis host (e.g., 192.168.1.100): " REDIS_HOST
read -p "Redis port [6379]: " REDIS_PORT
REDIS_PORT=${REDIS_PORT:-6379}

read -p "Flask app URL (e.g., http://192.168.1.100:5000): " FLASK_URL

read -p "Shared storage mount point on tundra [/mnt/clippyfront]: " INSTANCE_PATH
INSTANCE_PATH=${INSTANCE_PATH:-/mnt/clippyfront}

# Create .env.worker on remote
ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" bash <<EOF
cd ${REMOTE_PATH}

cat > .env.worker <<'ENVEOF'
# Celery Broker & Backend
CELERY_BROKER_URL=redis://${REDIS_HOST}:${REDIS_PORT}/0
CELERY_RESULT_BACKEND=redis://${REDIS_HOST}:${REDIS_PORT}/0

# Worker API
FLASK_APP_URL=${FLASK_URL}
WORKER_API_KEY=${API_KEY}

# Shared Storage
CLIPPY_INSTANCE_PATH=${INSTANCE_PATH}
HOST_INSTANCE_PATH=${INSTANCE_PATH}
TMPDIR=${INSTANCE_PATH}/tmp

# Worker Configuration
CELERY_QUEUES=gpu,celery
CELERY_CONCURRENCY=2
USE_GPU_QUEUE=true

# GPU Settings
FFMPEG_DISABLE_NVENC=0

# Logging
LOG_LEVEL=INFO
ENVEOF

echo "✓ Created .env.worker"
EOF

echo "✓ Worker configuration created"
echo

# Step 5: Verify shared storage
echo "Step 5: Verifying shared storage..."
if ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" "test -d ${INSTANCE_PATH}/data"; then
  echo "✓ Shared storage found at ${INSTANCE_PATH}"
else
  echo "⚠️  Warning: ${INSTANCE_PATH}/data not found on tundra"
  echo "   Make sure shared storage is mounted before starting worker"
fi
echo

# Step 6: Test Redis connectivity
echo "Step 6: Testing Redis connectivity from tundra..."
if ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" "command -v redis-cli >/dev/null && redis-cli -h ${REDIS_HOST} -p ${REDIS_PORT} ping" 2>/dev/null | grep -q PONG; then
  echo "✓ Redis connection OK"
else
  echo "⚠️  Warning: Cannot reach Redis at ${REDIS_HOST}:${REDIS_PORT}"
  echo "   Install redis-tools on tundra: sudo apt install redis-tools"
  echo "   Ensure Redis is accessible from tundra"
fi
echo

# Step 7: Check GPU/NVENC
echo "Step 7: Checking GPU and NVENC support..."
if ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" "command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1"; then
  echo "✓ NVIDIA driver detected"
  if ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" "ffmpeg -hide_banner -encoders 2>/dev/null | grep -q nvenc"; then
    echo "✓ NVENC support detected in ffmpeg"
  else
    echo "⚠️  Warning: ffmpeg does not have NVENC support"
    echo "   Worker will fall back to CPU encoding"
  fi
else
  echo "⚠️  Warning: NVIDIA GPU not detected"
  echo "   Worker will use CPU encoding"
fi
echo

# Summary
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo
echo "To start the worker on tundra, run:"
echo "  ssh -p ${REMOTE_PORT} ${REMOTE_USER}@${REMOTE_HOST}"
echo "  cd ${REMOTE_PATH}"
echo "  ./scripts/worker/run-worker-remote.sh"
echo
echo "Or set up as a systemd service:"
echo "  See docs/REMOTE_WORKER_SETUP.md for instructions"
echo
echo "To sync code changes in the future:"
echo "  ./scripts/worker/sync-to-tundra.sh"
echo
