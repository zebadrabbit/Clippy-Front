"""
Simple API-based task for validating media file accessibility.

This task demonstrates the pattern for workers that communicate via API
instead of direct database access. It's used as a proof-of-concept for
Phase 2 of the worker API migration.

Usage:
    from app.tasks.validate_media_api import validate_media_file_task
    result = validate_media_file_task.delay(media_id=123)
"""

import os
from typing import Any

from app.tasks import worker_api
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, queue="celery")
def validate_media_file_task(self, media_id: int) -> dict[str, Any]:
    """
    Validate that a media file exists and is accessible (API-based, no DB access).

    This is a simple task that demonstrates the worker API pattern:
    1. Fetch metadata from API
    2. Perform work (file validation)
    3. Return results without touching the database

    Args:
        media_id: ID of the media file to validate

    Returns:
        Dict: {
            "media_id": int,
            "status": "valid" | "missing" | "error",
            "file_path": str,
            "exists": bool,
            "size": int (if exists),
            "error": str (if error)
        }
    """

    try:
        # Update task state
        self.update_state(
            state="PROGRESS", meta={"progress": 10, "status": "Fetching metadata"}
        )

        # Fetch media metadata from API (no DB access)
        media_meta = worker_api.get_media_metadata(media_id)

        self.update_state(
            state="PROGRESS", meta={"progress": 50, "status": "Validating file"}
        )

        # Resolve file path
        file_path = media_meta["file_path"]

        # Handle canonical /instance/... paths
        if file_path.startswith("/instance/"):
            instance_path = os.environ.get("CLIPPY_INSTANCE_PATH", "/app/instance")
            file_path = file_path.replace("/instance/", f"{instance_path}/", 1)

        # Check if file exists
        exists = os.path.exists(file_path)
        result = {
            "media_id": media_id,
            "status": "valid" if exists else "missing",
            "file_path": media_meta["file_path"],
            "resolved_path": file_path,
            "exists": exists,
        }

        if exists:
            result["size"] = os.path.getsize(file_path)
            result["readable"] = os.access(file_path, os.R_OK)
        else:
            result["error"] = f"File not found: {file_path}"

        self.update_state(
            state="PROGRESS", meta={"progress": 100, "status": "Complete"}
        )

        return result

    except Exception as e:
        return {
            "media_id": media_id,
            "status": "error",
            "error": str(e),
            "exists": False,
        }
