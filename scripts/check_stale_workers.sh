#!/usr/bin/env bash
# Check for stale Celery workers and optionally stop them
# Usage: ./scripts/check_stale_workers.sh [--stop]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Activate venv if needed
if [ -d "venv" ] && [ -z "${VIRTUAL_ENV:-}" ]; then
    source venv/bin/activate
fi

STOP_WORKERS=false
if [ "${1:-}" = "--stop" ]; then
    STOP_WORKERS=true
fi

echo "=== Checking for stale Celery workers ==="
echo ""

# Get server version
SERVER_VERSION=$(python -c "from app.version import __version__; print(__version__)")
echo "Server version: $SERVER_VERSION"
echo ""

# Get active workers from Celery
echo "Querying Celery for active workers..."
WORKERS_JSON=$(WORKER_CHECK_CLI=1 python - <<'PYEOF'
import json
import sys
import os

# Signal to worker_version_check to be quiet
os.environ['WORKER_CHECK_CLI'] = '1'

from app.tasks.celery_app import celery_app
from app.worker_version_check import get_active_workers

try:
    workers = get_active_workers(timeout=3.0)
    print(json.dumps(workers, indent=2))
except Exception as e:
    sys.exit(1)
PYEOF
)

if [ $? -ne 0 ]; then
    echo "Error querying Celery workers"
    exit 1
fi

if [ "$WORKERS_JSON" = "{}" ] || [ -z "$WORKERS_JSON" ]; then
    echo "No workers connected to Celery."
    exit 0
fi

echo "$WORKERS_JSON"

echo "$WORKERS_JSON"

# Parse and display workers
python - <<PYEOF
import json

data = json.loads('''$WORKERS_JSON''')
server_version = "$SERVER_VERSION"

compatible = []
incompatible = []

for name, info in data.items():
    worker = {
        "name": name,
        "version": info.get("version"),
        "queues": info.get("queues", []),
        "compatible": info.get("compatible", True)
    }

    if worker["compatible"]:
        compatible.append(worker)
    else:
        incompatible.append(worker)

print(f"\n✅ Compatible workers ({len(compatible)}):")
if compatible:
    for w in compatible:
        version_str = w['version'] if w['version'] else "ERROR: No version tag!"
        queues_str = ", ".join(w['queues'])
        print(f"  - {w['name']}")
        print(f"    Version: {version_str}")
        print(f"    Queues: {queues_str}")
else:
    print("  (none)")

if incompatible:
    print(f"\n⚠️  Incompatible workers ({len(incompatible)}):")
    for w in incompatible:
        queues_str = ", ".join(w['queues'])
        print(f"  - {w['name']}")
        if w['version']:
            print(f"    Version: {w['version']} (expected: {server_version})")
        else:
            print(f"    Version: MISSING (no version tag)")
            print(f"    Reason: Workers without version tags are incompatible")
        print(f"    Queues: {queues_str}")

    # Check if any are Docker containers
    print("\n🔍 Checking for Docker containers...")
else:
    print("\n✨ All workers are properly versioned and compatible!")
PYEOF

WORKER_CHECK_STATUS=$?

# Check for multiple workers on same queue (potential issue)
GPU_WORKERS=$(echo "$WORKERS_JSON" | python -c "
import json, sys
data = json.load(sys.stdin)
gpu_workers = [name for name, info in data.items() if 'gpu' in info.get('queues', [])]
print(len(gpu_workers))
")

if [ "$GPU_WORKERS" -gt 1 ]; then
    echo ""
    echo "⚠️  WARNING: Multiple workers ($GPU_WORKERS) are listening to the 'gpu' queue!"
    echo "This causes round-robin task distribution. Only ONE should handle GPU tasks."
    echo ""
    echo "Workers on GPU queue:"
    echo "$WORKERS_JSON" | python -c "
import json, sys
data = json.load(sys.stdin)
for name, info in data.items():
    if 'gpu' in info.get('queues', []):
        print(f'  - {name}')
"
fi

if [ $WORKER_CHECK_STATUS -ne 0 ] || [ "$GPU_WORKERS" -gt 1 ]; then
    # Check for Docker containers
    echo ""
    if command -v docker &> /dev/null; then
        echo "Docker containers running celery:"
        docker ps --format "table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}" | grep -i celery || echo "  (none)"

        if $STOP_WORKERS; then
            echo ""
            read -p "Stop all celery containers? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                CELERY_CONTAINERS=$(docker ps -q -f name=celery 2>/dev/null)
                if [ -n "$CELERY_CONTAINERS" ]; then
                    echo "Stopping containers..."
                    docker stop $CELERY_CONTAINERS
                    echo "Removing containers..."
                    docker rm $CELERY_CONTAINERS
                    echo "✅ Stale containers removed"
                else
                    echo "No celery containers found"
                fi
            fi
        else
            echo ""
            echo "To stop stale workers, run:"
            echo "  $0 --stop"
            echo ""
            echo "Or manually:"
            echo "  docker stop \$(docker ps -q -f name=celery)"
            echo "  docker rm \$(docker ps -q -f name=celery)"
        fi
    else
        echo "Docker not available. Check workers manually."
    fi

    exit 1
fi

exit 0
