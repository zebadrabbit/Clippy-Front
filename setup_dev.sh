#!/usr/bin/env bash

# Development setup script for ClippyFront

set -euo pipefail

echo "Setting up ClippyFront development environment..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Copy .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
fi

# Install pre-commit hooks
echo "Installing pre-commit hooks..."
pre-commit install

# Run initial code formatting
echo "Running initial code formatting..."
black .
ruff check . --fix

echo "Development environment setup complete!"
echo ""
echo "To start the application:"
echo "  1. Start Redis server: redis-server"
echo "  2. Start Flask app: python main.py"
echo "  3. Start Celery worker: celery -A app.tasks.celery_app worker --loglevel=info"
echo ""
echo "To run tests: pytest"
