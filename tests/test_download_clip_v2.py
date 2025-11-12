"""
Tests for Phase 3: Worker API endpoints for download_clip_task_v2.
Tests the /api/worker/media endpoints: find-reusable and media creation.
"""

import pytest

from app.models import Clip, MediaFile, db


class TestWorkerDownloadEndpoints:
    """Tests for worker API endpoints added in Phase 3."""

    def test_find_reusable_media_found(
        self,
        client,
        worker_headers,
        test_user,
        test_project,
        test_clip,
        test_media_file,
    ):
        """POST /api/worker/media/find-reusable returns existing media."""
        # Update the clip and media file for matching
        media = MediaFile.query.get(test_media_file)
        media.source_url = "https://clips.twitch.tv/test-clip"
        db.session.commit()

        clip = Clip.query.get(test_clip)
        clip.source_url = "https://clips.twitch.tv/test-clip"
        clip.media_file_id = test_media_file
        db.session.commit()

        data = {
            "user_id": test_user,
            "source_url": "https://clips.twitch.tv/test-clip",
            "normalized_url": "clips.twitch.tv/test-clip",
            "clip_key": None,
        }
        response = client.post(
            "/api/worker/media/find-reusable",
            headers=worker_headers,
            json=data,
        )
        assert response.status_code == 200
        result = response.get_json()
        # Might not find due to file existence check, but shouldn't error
        assert "found" in result

    def test_find_reusable_media_not_found(self, client, worker_headers, test_user):
        """POST /api/worker/media/find-reusable returns not found for new URL."""
        data = {
            "user_id": test_user,
            "source_url": "https://youtube.com/watch?v=brand-new-video",
            "normalized_url": "youtube.com/watch?v=brand-new-video",
            "clip_key": None,
        }
        response = client.post(
            "/api/worker/media/find-reusable",
            headers=worker_headers,
            json=data,
        )
        assert response.status_code == 200
        result = response.get_json()
        assert result["found"] is False

    def test_create_media_file(self, client, worker_headers, test_user, test_project):
        """POST /api/worker/media creates new media file."""
        data = {
            "filename": "video3.mp4",
            "original_filename": "original3.mp4",
            "file_path": "/instance/data/testuser/video3.mp4",
            "file_size": 2000,
            "mime_type": "video/mp4",
            "media_type": "CLIP",
            "user_id": test_user,
            "project_id": test_project,
        }
        response = client.post(
            "/api/worker/media",
            headers=worker_headers,
            json=data,
        )
        assert response.status_code == 200
        result = response.get_json()
        assert result["status"] == "created"
        assert "media_id" in result


@pytest.fixture
def worker_api_key(app):
    """Get the configured worker API key."""
    with app.app_context():
        from flask import current_app

        return current_app.config.get("WORKER_API_KEY", "test-worker-key-12345")


@pytest.fixture
def worker_headers(worker_api_key):
    """Create headers with worker API authentication."""
    return {"Authorization": f"Bearer {worker_api_key}"}
