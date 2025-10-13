#!/bin/bash

# Watch for file changes and auto-commit
# Usage: ./watch_and_commit.sh

echo "Starting file watcher for auto-commits..."
echo "Press Ctrl+C to stop"

# Function to handle cleanup
cleanup() {
    echo ""
    echo "Stopping file watcher..."
    exit 0
}

# Set up signal handler
trap cleanup SIGINT SIGTERM

# Watch for changes in the current directory (excluding .git and venv)
inotifywait -m -r -e modify,create,delete,move \
    --exclude '(\.git|venv|__pycache__|\.pyc$|\.log$)' \
    . 2>/dev/null | while read path action file; do

    echo "Change detected: $action $path$file"

    # Small delay to allow multiple rapid changes to settle
    sleep 2

    # Run the auto-commit script
    ./.git/hooks/auto-commit.sh
done
