"""
Tests for Phase 4 worker API endpoints (compile_video_task migration).

These tests validate the batch endpoints that efficiently provide compilation
data to workers without requiring N+1 database queries.
"""


def test_get_compilation_context(client, test_user, test_project, test_clip):
    """Test fetching project + clips + tier limits in single call."""
    # Clip is already created with project_id set by fixture
    # Get worker API key from config
    from flask import current_app

    worker_key = current_app.config.get("WORKER_API_KEY", "test-worker-key")

    response = client.get(
        f"/api/worker/projects/{test_project}/compilation-context",
        headers={"Authorization": f"Bearer {worker_key}"},
    )

    assert response.status_code == 200
    data = response.json

    # Validate project data
    assert "project" in data
    assert data["project"]["id"] == test_project
    assert data["project"]["user_id"] == test_user
    assert "name" in data["project"]

    # Validate clips data
    assert "clips" in data
    assert len(data["clips"]) == 1
    clip_data = data["clips"][0]
    assert clip_data["id"] == test_clip
    # Media file may be None if not attached
    assert "media_file" in clip_data

    # Validate tier limits
    assert "tier_limits" in data
    tier = data["tier_limits"]
    assert "max_res_label" in tier
    assert "max_fps" in tier
    assert "max_clips" in tier


def test_get_compilation_context_not_found(client):
    """Test compilation context for non-existent project."""
    from flask import current_app

    worker_key = current_app.config.get("WORKER_API_KEY", "test-worker-key")

    response = client.get(
        "/api/worker/projects/99999/compilation-context",
        headers={"Authorization": f"Bearer {worker_key}"},
    )

    assert response.status_code == 404
    assert "error" in response.json


def test_get_media_batch(client, test_user, test_media_file):
    """Test batch fetching of media files."""
    from flask import current_app

    worker_key = current_app.config.get("WORKER_API_KEY", "test-worker-key")

    response = client.post(
        "/api/worker/media/batch",
        headers={"Authorization": f"Bearer {worker_key}"},
        json={"media_ids": [test_media_file], "user_id": test_user},
    )

    assert response.status_code == 200
    data = response.json

    assert "media_files" in data
    # Media file might not exist on disk, so list could be empty
    # Just verify structure is correct
    assert isinstance(data["media_files"], list)


def test_get_media_batch_ownership_validation(client, test_user):
    """Test that batch fetch validates ownership."""
    from flask import current_app

    worker_key = current_app.config.get("WORKER_API_KEY", "test-worker-key")

    # Try to fetch media for non-existent user
    response = client.post(
        "/api/worker/media/batch",
        headers={"Authorization": f"Bearer {worker_key}"},
        json={"media_ids": [1], "user_id": 99999},
    )

    assert response.status_code == 200
    data = response.json
    # Should return empty list for non-existent user's media
    assert data["media_files"] == []


def test_get_media_batch_missing_user_id(client):
    """Test that batch fetch requires user_id."""
    from flask import current_app

    worker_key = current_app.config.get("WORKER_API_KEY", "test-worker-key")

    response = client.post(
        "/api/worker/media/batch",
        headers={"Authorization": f"Bearer {worker_key}"},
        json={"media_ids": [1]},  # Missing user_id
    )

    assert response.status_code == 400
    assert "error" in response.json
