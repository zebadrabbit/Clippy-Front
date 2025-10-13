#!/usr/bin/env python3
"""
Celery worker startup script.
"""
import os
import sys

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import after path modification
from app.tasks.celery_app import celery_app  # noqa: E402

if __name__ == "__main__":
    celery_app.start()
