"""
Tests for worker API endpoints and client library.

These tests validate that workers can operate without direct database access
by using the /api/worker/* endpoints with bearer token authentication.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.models import Clip, MediaFile, MediaType, ProcessingJob, Project, db


@pytest.fixture
def worker_api_key(app):
    """Get the configured worker API key."""
    with app.app_context():
        from flask import current_app

        return current_app.config.get("WORKER_API_KEY", "test-worker-key-12345")


@pytest.fixture
def worker_headers(worker_api_key):
    """Create headers with worker authentication."""
    return {"Authorization": f"Bearer {worker_api_key}"}


@pytest.fixture
def test_media_file(app, test_user, test_project):
    """Create a test media file."""
    with app.app_context():
        media = MediaFile(
            filename="test_video.mp4",
            original_filename="test_video.mp4",
            file_path="/instance/data/testuser/test_project/test_video.mp4",
            file_size=1024000,
            mime_type="video/mp4",
            media_type=MediaType.CLIP,
            user_id=test_user,
            project_id=test_project,
            duration=30.5,
            width=1920,
            height=1080,
            framerate=30.0,
        )
        db.session.add(media)
        db.session.commit()
        return media.id


@pytest.fixture
def test_clip(app, test_project, test_media_file):
    """Create a test clip."""
    with app.app_context():
        clip = Clip(
            title="Test Clip",
            source_url="https://clips.twitch.tv/test123",
            source_platform="twitch",
            source_id="test123",
            project_id=test_project,
            media_file_id=test_media_file,
            duration=30.5,
            is_downloaded=True,
            order_index=0,
        )
        db.session.add(clip)
        db.session.commit()
        return clip.id


class TestWorkerAPIAuthentication:
    """Test authentication for worker API endpoints."""

    def test_missing_auth_header(self, client):
        """Request without Authorization header should fail."""
        response = client.get("/api/worker/clips/1")
        assert response.status_code == 401
        assert b"Unauthorized" in response.data

    def test_invalid_bearer_token(self, client):
        """Request with wrong token should fail."""
        headers = {"Authorization": "Bearer wrong-token"}
        response = client.get("/api/worker/clips/1", headers=headers)
        assert response.status_code == 401
        assert b"Unauthorized" in response.data

    def test_malformed_auth_header(self, client, worker_api_key):
        """Request with malformed header should fail."""
        headers = {"Authorization": f"Basic {worker_api_key}"}
        response = client.get("/api/worker/clips/1", headers=headers)
        assert response.status_code == 401

    def test_valid_auth(self, client, worker_headers, app, test_clip):
        """Request with valid token should succeed."""
        response = client.get(f"/api/worker/clips/{test_clip}", headers=worker_headers)
        assert response.status_code == 200


class TestWorkerClipEndpoints:
    """Test /api/worker/clips/* endpoints."""

    def test_get_clip_metadata(self, client, worker_headers, app, test_clip):
        """GET /api/worker/clips/<id> returns clip metadata."""
        response = client.get(f"/api/worker/clips/{test_clip}", headers=worker_headers)
        assert response.status_code == 200

        data = response.get_json()
        assert data["id"] == test_clip
        assert data["title"] == "Test Clip"
        assert data["source_url"] == "https://clips.twitch.tv/test123"
        assert data["source_platform"] == "twitch"
        assert data["username"] == "testuser"
        assert data["project_name"] == "Test Project"

    def test_get_clip_not_found(self, client, worker_headers):
        """GET /api/worker/clips/<id> with invalid ID returns 404."""
        response = client.get("/api/worker/clips/99999", headers=worker_headers)
        assert response.status_code == 404
        assert b"not found" in response.data

    def test_update_clip_status(self, client, worker_headers, app, test_clip):
        """POST /api/worker/clips/<id>/status updates clip."""
        data = {
            "is_downloaded": True,
            "duration": 45.2,
        }
        response = client.post(
            f"/api/worker/clips/{test_clip}/status",
            headers=worker_headers,
            json=data,
        )
        assert response.status_code == 200

        result = response.get_json()
        assert result["status"] == "updated"
        assert result["clip_id"] == test_clip

        # Verify database was updated
        with app.app_context():
            clip_obj = Clip.query.get(test_clip)
            assert clip_obj.is_downloaded is True
            assert clip_obj.duration == 45.2

    def test_update_clip_with_media_file_id(
        self, client, worker_headers, app, test_clip, test_media_file
    ):
        """POST /api/worker/clips/<id>/status can set media_file_id."""
        data = {"media_file_id": test_media_file}
        response = client.post(
            f"/api/worker/clips/{test_clip}/status",
            headers=worker_headers,
            json=data,
        )
        assert response.status_code == 200

        with app.app_context():
            clip_obj = Clip.query.get(test_clip)
            assert clip_obj.media_file_id == test_media_file


class TestWorkerMediaEndpoints:
    """Test /api/worker/media/* endpoints."""

    def test_get_media_metadata(self, client, worker_headers, test_media_file):
        """GET /api/worker/media/<id> returns metadata."""
        response = client.get(
            f"/api/worker/media/{test_media_file}", headers=worker_headers
        )
        assert response.status_code == 200

        data = response.get_json()
        assert data["id"] == test_media_file
        assert data["filename"] == "test_video.mp4"
        assert (
            data["file_path"] == "/instance/data/testuser/test_project/test_video.mp4"
        )
        assert data["media_type"] == "clip"
        assert data["duration"] == 30.5
        # Fetch the actual object to check user_id
        media = MediaFile.query.get(test_media_file)
        assert data["user_id"] == media.user_id
        assert data["username"] == "testuser"

    def test_get_media_not_found(self, client, worker_headers):
        """GET /api/worker/media/<id> with invalid ID returns 404."""
        response = client.get("/api/worker/media/99999", headers=worker_headers)
        assert response.status_code == 404

    def test_create_media_file(self, client, worker_headers, test_user, test_project):
        """POST /api/worker/media creates new media file."""
        data = {
            "filename": "new_video.mp4",
            "original_filename": "original.mp4",
            "file_path": "/instance/data/testuser/new_video.mp4",
            "file_size": 2048000,
            "mime_type": "video/mp4",
            "media_type": "clip",
            "user_id": test_user,
            "project_id": test_project,
            "duration": 60.0,
            "width": 1920,
            "height": 1080,
            "framerate": 30.0,
            "thumbnail_path": "/instance/data/testuser/new_video_thumb.jpg",
        }
        response = client.post("/api/worker/media", headers=worker_headers, json=data)
        assert response.status_code == 200

        result = response.get_json()
        assert result["status"] == "created"
        assert "media_id" in result

        # Verify database record
        media = MediaFile.query.get(result["media_id"])
        assert media is not None
        assert media.filename == "new_video.mp4"
        assert media.file_size == 2048000
        assert media.duration == 60.0
        assert media.width == 1920
        assert media.height == 1080

    def test_create_media_file_minimal(self, client, worker_headers, test_user):
        """POST /api/worker/media works with minimal required fields."""
        data = {
            "filename": "minimal.mp4",
            "original_filename": "minimal.mp4",
            "file_path": "/instance/data/testuser/minimal.mp4",
            "file_size": 1000,
            "mime_type": "video/mp4",
            "media_type": "clip",
            "user_id": test_user,
        }
        response = client.post("/api/worker/media", headers=worker_headers, json=data)
        assert response.status_code == 200

        result = response.get_json()
        media = MediaFile.query.get(result["media_id"])
        assert media.filename == "minimal.mp4"
        assert media.project_id is None
        assert media.duration is None


class TestWorkerJobEndpoints:
    """Test /api/worker/jobs/* endpoints."""

    def test_create_processing_job(
        self, client, worker_headers, test_user, test_project
    ):
        """POST /api/worker/jobs creates new job."""
        data = {
            "celery_task_id": "test-task-123",
            "job_type": "download_clip",
            "project_id": test_project,
            "user_id": test_user,
            "status": "started",
        }
        response = client.post("/api/worker/jobs", headers=worker_headers, json=data)
        assert response.status_code == 200

        result = response.get_json()
        assert result["status"] == "created"
        assert "job_id" in result

        # Verify database record
        job = ProcessingJob.query.get(result["job_id"])
        assert job is not None
        assert job.celery_task_id == "test-task-123"
        assert job.job_type == "download_clip"
        assert job.status == "started"
        assert job.started_at is not None

    def test_update_processing_job(
        self, client, worker_headers, test_user, test_project
    ):
        """PUT /api/worker/jobs/<id> updates job status."""
        # Create a job first
        job = ProcessingJob(
            celery_task_id="test-task-456",
            job_type="compile_video",
            project_id=test_project,
            user_id=test_user,
            status="started",
            started_at=datetime.utcnow(),
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

        # Update it
        update_data = {
            "status": "success",
            "progress": 100,
            "result_data": {"output_file": "/path/to/output.mp4"},
        }
        response = client.put(
            f"/api/worker/jobs/{job_id}", headers=worker_headers, json=update_data
        )
        assert response.status_code == 200

        result = response.get_json()
        assert result["status"] == "updated"

        # Verify database
        db.session.refresh(job)
        assert job.status == "success"
        assert job.progress == 100
        assert job.completed_at is not None
        assert job.result_data["output_file"] == "/path/to/output.mp4"

    def test_update_job_merges_result_data(
        self, client, worker_headers, test_user, test_project
    ):
        """PUT /api/worker/jobs/<id> merges result_data instead of replacing."""
        job = ProcessingJob(
            celery_task_id="test-task-789",
            job_type="test",
            project_id=test_project,
            user_id=test_user,
            status="started",
            started_at=datetime.utcnow(),
            result_data={"existing_key": "existing_value"},
        )
        db.session.add(job)
        db.session.commit()

        update_data = {"result_data": {"new_key": "new_value"}}
        client.put(
            f"/api/worker/jobs/{job.id}", headers=worker_headers, json=update_data
        )

        db.session.refresh(job)
        assert job.result_data["existing_key"] == "existing_value"
        assert job.result_data["new_key"] == "new_value"

    def test_update_job_not_found(self, client, worker_headers):
        """PUT /api/worker/jobs/<id> with invalid ID returns 404."""
        response = client.put(
            "/api/worker/jobs/99999",
            headers=worker_headers,
            json={"status": "success"},
        )
        assert response.status_code == 404


class TestWorkerProjectEndpoints:
    """Test /api/worker/projects/* endpoints."""

    def test_get_project_metadata(
        self, client, worker_headers, test_project, test_clip
    ):
        """GET /api/worker/projects/<id> returns project with clips."""
        response = client.get(
            f"/api/worker/projects/{test_project}", headers=worker_headers
        )
        assert response.status_code == 200

        data = response.get_json()
        assert data["id"] == test_project
        assert data["name"] == "Test Project"
        # Fetch the actual object to check user_id
        project = Project.query.get(test_project)
        assert data["user_id"] == project.user_id
        assert data["username"] == "testuser"
        assert data["output_resolution"] == "1080p"

        # Check clips array
        assert len(data["clips"]) > 0
        clip_data = data["clips"][0]
        assert clip_data["id"] == test_clip
        assert clip_data["title"] == "Test Clip"
        assert clip_data["is_downloaded"] is True

    def test_get_project_not_found(self, client, worker_headers):
        """GET /api/worker/projects/<id> with invalid ID returns 404."""
        response = client.get("/api/worker/projects/99999", headers=worker_headers)
        assert response.status_code == 404

    def test_update_project_status(self, client, worker_headers, test_project):
        """PUT /api/worker/projects/<id>/status updates project."""
        update_data = {
            "status": "completed",
            "output_filename": "final_output.mp4",
            "output_file_size": 50000000,
        }
        response = client.put(
            f"/api/worker/projects/{test_project}/status",
            headers=worker_headers,
            json=update_data,
        )
        assert response.status_code == 200

        result = response.get_json()
        assert result["status"] == "updated"

        # Verify database - fetch the object
        project = Project.query.get(test_project)
        assert str(project.status.value) == "completed"
        assert project.output_filename == "final_output.mp4"
        assert project.output_file_size == 50000000
        assert project.completed_at is not None

    def test_update_project_explicit_completed_at(
        self, client, worker_headers, test_project
    ):
        """PUT /api/worker/projects/<id>/status can set explicit completed_at."""
        completed_time = "2025-11-11T12:00:00"
        update_data = {"status": "completed", "completed_at": completed_time}
        response = client.put(
            f"/api/worker/projects/{test_project}/status",
            headers=worker_headers,
            json=update_data,
        )
        assert response.status_code == 200

        # Fetch the object to check
        project = Project.query.get(test_project)
        assert project.completed_at.isoformat().startswith("2025-11-11T12:00")


class TestWorkerUserEndpoints:
    """Test /api/worker/users/* endpoints."""

    def test_get_user_quota(self, client, worker_headers, test_user):
        """GET /api/worker/users/<id>/quota returns quota info."""
        response = client.get(
            f"/api/worker/users/{test_user}/quota", headers=worker_headers
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "remaining_bytes" in data
        assert "total_bytes" in data
        assert "used_bytes" in data
        assert isinstance(data["remaining_bytes"], int)

    def test_get_user_quota_not_found(self, client, worker_headers):
        """GET /api/worker/users/<id>/quota with invalid ID returns 404."""
        response = client.get("/api/worker/users/99999/quota", headers=worker_headers)
        assert response.status_code == 404

    def test_get_user_tier_limits(self, client, worker_headers, test_user):
        """GET /api/worker/users/<id>/tier-limits returns limits."""
        response = client.get(
            f"/api/worker/users/{test_user}/tier-limits", headers=worker_headers
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "storage_limit_bytes" in data
        assert "render_time_limit_seconds" in data
        assert "apply_watermark" in data
        assert "is_unlimited" in data

    def test_record_render_usage(self, client, worker_headers, test_user, test_project):
        """POST /api/worker/users/<id>/record-render records usage."""
        data = {"project_id": test_project, "seconds": 120.5}
        response = client.post(
            f"/api/worker/users/{test_user}/record-render",
            headers=worker_headers,
            json=data,
        )
        assert response.status_code == 200

        result = response.get_json()
        assert result["status"] == "recorded"


class TestWorkerAPIClient:
    """Test worker_api.py client library."""

    @patch("app.tasks.worker_api.requests.request")
    def test_get_clip_metadata(self, mock_request):
        """worker_api.get_clip_metadata() makes correct API call."""
        from app.tasks import worker_api

        # Mock environment
        with patch.dict(
            "os.environ",
            {"FLASK_APP_URL": "http://test:5000", "WORKER_API_KEY": "test-key"},
        ):
            # Mock response
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": 123,
                "title": "Test Clip",
                "source_url": "https://test.url",
            }
            mock_request.return_value = mock_response

            # Call function
            result = worker_api.get_clip_metadata(123)

            # Verify request
            mock_request.assert_called_once()
            args, kwargs = mock_request.call_args
            assert args[0] == "GET"
            assert args[1] == "http://test:5000/api/worker/clips/123"
            assert kwargs["headers"]["Authorization"] == "Bearer test-key"

            # Verify result
            assert result["id"] == 123
            assert result["title"] == "Test Clip"

    @patch("app.tasks.worker_api.requests.request")
    def test_create_media_file(self, mock_request):
        """worker_api.create_media_file() sends correct data."""
        from app.tasks import worker_api

        with patch.dict(
            "os.environ",
            {"FLASK_APP_URL": "http://test:5000", "WORKER_API_KEY": "test-key"},
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = {"status": "created", "media_id": 456}
            mock_request.return_value = mock_response

            result = worker_api.create_media_file(
                filename="test.mp4",
                original_filename="test.mp4",
                file_path="/instance/test.mp4",
                file_size=1000,
                mime_type="video/mp4",
                media_type="clip",
                user_id=1,
                duration=30.0,
            )

            # Verify request
            args, kwargs = mock_request.call_args
            assert args[0] == "POST"
            assert args[1] == "http://test:5000/api/worker/media"
            assert kwargs["json"]["filename"] == "test.mp4"
            assert kwargs["json"]["duration"] == 30.0

            assert result["media_id"] == 456

    def test_missing_api_url_raises_error(self):
        """worker_api functions raise error when FLASK_APP_URL not set."""
        from app.tasks import worker_api

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="FLASK_APP_URL not configured"):
                worker_api.get_clip_metadata(123)

    def test_missing_api_key_raises_error(self):
        """worker_api functions raise error when WORKER_API_KEY not set."""
        from app.tasks import worker_api

        # Clear WORKER_API_KEY but keep FLASK_APP_URL
        with patch.dict(
            "os.environ", {"FLASK_APP_URL": "http://test:5000", "WORKER_API_KEY": ""}
        ):
            with pytest.raises(RuntimeError, match="WORKER_API_KEY not configured"):
                worker_api.get_clip_metadata(123)
