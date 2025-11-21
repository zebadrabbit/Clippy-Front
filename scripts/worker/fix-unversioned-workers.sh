#!/usr/bin/env bash
# Quick script to kill unversioned workers and show instructions
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "========================================"
echo "Stopping Unversioned Workers"
echo "========================================"

# Find celery worker processes without version tags
UNVERSIONED=$(ps aux | grep -E 'celery.*worker' | grep -v grep | grep -v 'v[0-9]\+\.[0-9]\+\.[0-9]\+' || true)

if [[ -z "$UNVERSIONED" ]]; then
  echo "✓ No unversioned workers found"
else
  echo "Found unversioned workers:"
  echo "$UNVERSIONED"
  echo ""
  read -p "Kill these workers? [y/N] " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    pkill -f 'celery -A app.tasks.celery_app worker -Q celery' || true
    pkill -f 'celery.*worker.*main@' || true
    sleep 2
    echo "✓ Workers stopped"
  fi
fi

echo ""
echo "========================================"
echo "Start Versioned Worker"
echo "========================================"
echo "Run one of these commands:"
echo ""
echo "# Start main worker on celery queue:"
echo "./scripts/worker/start-celery-versioned.sh main \"celery\" 2"
echo ""
echo "# Or as background process:"
echo "nohup ./scripts/worker/start-celery-versioned.sh main \"celery\" 2 > logs/worker.log 2>&1 &"
echo ""
echo "# Or install systemd service (requires sudo):"
echo "sudo cp scripts/clippyfront-worker.service /etc/systemd/system/"
echo "sudo systemctl daemon-reload"
echo "sudo systemctl enable clippyfront-worker"
echo "sudo systemctl start clippyfront-worker"
