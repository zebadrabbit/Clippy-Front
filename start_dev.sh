#!/bin/bash

# Start all services for ClippyFront development

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Starting ClippyFront development environment...${NC}"

# Check if virtual environment is activated
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source venv/bin/activate
fi

# Check if Redis is running
# Load .env so we can respect remote Redis if configured
set +a
if [[ -f .env ]]; then
    set -a && source .env && set +a
fi

# Start a local Redis only if REDIS_URL points to localhost
REDIS_HOST=$(echo "${REDIS_URL:-redis://localhost:6379/0}" | sed -E 's|^[a-z]+://([^:/]+).*|\1|')
if [[ "${REDIS_HOST}" == "localhost" || "${REDIS_HOST}" == "127.0.0.1" || -z "${REDIS_HOST}" ]]; then
    if ! redis-cli ping >/dev/null 2>&1; then
        echo -e "${YELLOW}Redis is not running locally. Starting Redis with Docker...${NC}"
        docker run -d --name clippyfront-redis -p 6379:6379 redis:7-alpine
        sleep 2
    fi
else
    echo -e "${GREEN}Using remote Redis at ${REDIS_HOST}; skipping local Redis startup.${NC}"
fi

echo -e "${GREEN}All services are ready!${NC}"
echo ""
echo -e "${BLUE}Starting services in tmux session...${NC}"

# Create tmux session with multiple panes
tmux new-session -d -s clippyfront

# Split window into panes
tmux split-window -h -t clippyfront
tmux split-window -v -t clippyfront:0.1

# Set up panes
tmux send-keys -t clippyfront:0.0 'source venv/bin/activate && set -a && source .env && set +a && python main.py' Enter
tmux send-keys -t clippyfront:0.1 'source venv/bin/activate && set -a && source .env && set +a && celery -A app.tasks.celery_app worker --loglevel=info -Q celery -c 2 -n main@%h' Enter
tmux send-keys -t clippyfront:0.2 'source venv/bin/activate && set -a && source .env && set +a' Enter

# Attach to tmux session
echo -e "${GREEN}Services started in tmux session 'clippyfront'${NC}"
echo -e "${BLUE}Attaching to session... (Use Ctrl+B then D to detach)${NC}"
tmux attach-session -t clippyfront
