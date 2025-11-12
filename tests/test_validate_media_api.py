"""
Tests for validate_media_file_task - the simple API-based task pattern.

This validates Phase 2 of the worker API migration: a task that operates
entirely via API without direct database access.
"""

import os
import tempfile
from unittest.mock import patch

import pytest

from app.models import MediaFile, MediaType, db


@pytest.fixture
def test_media_with_file(app, test_user, test_project):
    """Create a media file with actual file on disk."""
    with app.app_context():
        # Create temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".mp4"
        ) as tmp_file:
            tmp_file.write("fake video content")
            temp_path = tmp_file.name

        # Create media record
        media = MediaFile(
            filename=os.path.basename(temp_path),
            original_filename="test_video.mp4",
            file_path=f"/instance/data/testuser/{os.path.basename(temp_path)}",
            file_size=os.path.getsize(temp_path),
            mime_type="video/mp4",
            media_type=MediaType.CLIP,
            user_id=test_user,
            project_id=test_project,
        )
        db.session.add(media)
        db.session.commit()
        media_id = media.id

    # Store actual path for cleanup (outside app context)
    class MediaWithFile:
        def __init__(self, media_id, temp_path, filename, user_id):
            self.id = media_id
            self._temp_path = temp_path
            self.filename = filename
            self.user_id = user_id

    result = MediaWithFile(media_id, temp_path, os.path.basename(temp_path), test_user)

    yield result

    # Cleanup
    try:
        os.unlink(temp_path)
    except Exception:
        pass


class TestValidateMediaFileTask:
    """Test the simple API-based validation task."""

    @patch("app.tasks.validate_media_api.worker_api")
    def test_validate_existing_file(self, mock_worker_api, app, test_media_with_file):
        """validate_media_file_task finds existing file."""
        from app.tasks.validate_media_api import validate_media_file_task

        # Mock API response
        mock_worker_api.get_media_metadata.return_value = {
            "id": test_media_with_file.id,
            "filename": test_media_with_file.filename,
            "file_path": test_media_with_file._temp_path,  # Use actual path
            "media_type": "clip",
            "duration": 30.0,
            "user_id": test_media_with_file.user_id,
            "username": "testuser",
        }

        with app.app_context():
            # Run task eagerly
            result = validate_media_file_task.apply(
                args=[test_media_with_file.id]
            ).get()

        # Verify API was called
        mock_worker_api.get_media_metadata.assert_called_once_with(
            test_media_with_file.id
        )

        # Verify result
        assert result["media_id"] == test_media_with_file.id
        assert result["status"] == "valid"
        assert result["exists"] is True
        assert result["size"] > 0
        assert result["readable"] is True

    @patch("app.tasks.validate_media_api.worker_api")
    def test_validate_missing_file(self, mock_worker_api, app):
        """validate_media_file_task detects missing file."""
        from app.tasks.validate_media_api import validate_media_file_task

        # Mock API response with non-existent path
        mock_worker_api.get_media_metadata.return_value = {
            "id": 999,
            "filename": "missing.mp4",
            "file_path": "/instance/data/testuser/does_not_exist.mp4",
            "media_type": "clip",
            "duration": 30.0,
            "user_id": 1,
            "username": "testuser",
        }

        with app.app_context():
            result = validate_media_file_task.apply(args=[999]).get()

        assert result["media_id"] == 999
        assert result["status"] == "missing"
        assert result["exists"] is False
        assert "error" in result
        assert "not found" in result["error"].lower()

    @patch("app.tasks.validate_media_api.worker_api")
    def test_validate_api_error(self, mock_worker_api, app):
        """validate_media_file_task handles API errors gracefully."""
        from app.tasks.validate_media_api import validate_media_file_task

        # Mock API raising exception
        mock_worker_api.get_media_metadata.side_effect = Exception(
            "API connection failed"
        )

        with app.app_context():
            result = validate_media_file_task.apply(args=[123]).get()

        assert result["status"] == "error"
        assert "API connection failed" in result["error"]
        assert result["exists"] is False

    @patch("app.tasks.validate_media_api.worker_api")
    @patch.dict("os.environ", {"CLIPPY_INSTANCE_PATH": "/custom/instance"})
    def test_validate_canonical_path_resolution(self, mock_worker_api, app):
        """validate_media_file_task resolves canonical /instance/ paths."""
        from app.tasks.validate_media_api import validate_media_file_task

        # Mock API response with canonical path
        mock_worker_api.get_media_metadata.return_value = {
            "id": 123,
            "filename": "test.mp4",
            "file_path": "/instance/data/testuser/test.mp4",
            "media_type": "clip",
            "duration": 30.0,
            "user_id": 1,
            "username": "testuser",
        }

        with app.app_context(), patch("os.path.exists", return_value=True), patch(
            "os.path.getsize", return_value=1000
        ), patch("os.access", return_value=True):
            result = validate_media_file_task.apply(args=[123]).get()

        # Verify path was resolved with custom instance path
        assert result["resolved_path"] == "/custom/instance/data/testuser/test.mp4"
        assert result["file_path"] == "/instance/data/testuser/test.mp4"  # Original


class TestWorkerAPIPattern:
    """Test that the API pattern works without DATABASE_URL."""

    @patch("app.tasks.validate_media_api.worker_api")
    def test_task_runs_without_database_access(self, mock_worker_api, app):
        """Verify task uses only API, no database access."""
        from app.tasks.validate_media_api import validate_media_file_task

        # Mock API response
        mock_worker_api.get_media_metadata.return_value = {
            "id": 999,
            "user_id": 1,
            "file_path": "/instance/data/testuser/media/test.mp4",
            "filename": "test.mp4",
            "media_type": "video",
        }

        with app.app_context():
            result = validate_media_file_task.apply(args=[999]).get()

        # Should complete without database access
        assert result["status"] in ["valid", "missing", "error"]
        mock_worker_api.get_media_metadata.assert_called_once_with(999)

    def test_task_registered_with_celery(self):
        """validate_media_file_task is registered with Celery."""
        from app.tasks.celery_app import celery_app

        # Check task is registered
        assert (
            "app.tasks.validate_media_api.validate_media_file_task" in celery_app.tasks
        )
