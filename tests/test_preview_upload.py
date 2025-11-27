"""Test preview video upload from workers."""

import io
import json
import os

from app.models import Project, ProjectStatus, db


def test_worker_preview_upload(client, app, test_user):
    """Test worker uploading a preview video."""
    with app.app_context():
        # Create a test project
        project = Project(
            name="Test Preview Project",
            user_id=test_user,
            status=ProjectStatus.PROCESSING,
            output_resolution="1080p",
        )
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    # Mock preview video file
    preview_data = b"fake preview video data for testing"
    preview_file = (io.BytesIO(preview_data), "preview.mp4")

    # Metadata
    metadata = {"file_size": len(preview_data), "clips_used": 3}

    # Upload preview as worker
    worker_key = app.config["WORKER_API_KEY"]
    response = client.post(
        f"/api/worker/projects/{project_id}/preview/upload",
        data={
            "preview": preview_file,
            "metadata": json.dumps(metadata),
        },
        headers={"Authorization": f"Bearer {worker_key}"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "uploaded"
    assert data["project_id"] == project_id
    assert data["preview_filename"] == f"preview_{project_id}.mp4"

    # Verify project updated
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert project.preview_filename == f"preview_{project_id}.mp4"
        assert project.preview_file_size == len(preview_data)

        # Verify file saved
        preview_dir = os.path.join(app.instance_path, "previews", str(test_user))
        preview_path = os.path.join(preview_dir, data["preview_filename"])
        assert os.path.exists(preview_path)

        # Cleanup
        if os.path.exists(preview_path):
            os.remove(preview_path)


def test_worker_preview_upload_missing_file(client, app, test_user):
    """Test upload fails without preview file."""
    with app.app_context():
        project = Project(
            name="Test Project",
            user_id=test_user,
            status=ProjectStatus.PROCESSING,
        )
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    worker_key = app.config["WORKER_API_KEY"]
    response = client.post(
        f"/api/worker/projects/{project_id}/preview/upload",
        data={"metadata": json.dumps({})},
        headers={"Authorization": f"Bearer {worker_key}"},
    )

    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data
    assert "No preview file" in data["error"]


def test_worker_preview_upload_project_not_found(client, app):
    """Test upload fails for nonexistent project."""
    worker_key = app.config["WORKER_API_KEY"]
    preview_data = b"fake data"
    preview_file = (io.BytesIO(preview_data), "preview.mp4")

    response = client.post(
        "/api/worker/projects/99999/preview/upload",
        data={
            "preview": preview_file,
            "metadata": json.dumps({}),
        },
        headers={"Authorization": f"Bearer {worker_key}"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 404
    data = response.get_json()
    assert "error" in data
    assert "not found" in data["error"].lower()


def test_worker_preview_upload_requires_auth(client, app, test_user):
    """Test upload requires worker API key."""
    with app.app_context():
        project = Project(
            name="Test Project",
            user_id=test_user,
            status=ProjectStatus.PROCESSING,
        )
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    preview_data = b"fake data"
    preview_file = (io.BytesIO(preview_data), "preview.mp4")

    # No auth header
    response = client.post(
        f"/api/worker/projects/{project_id}/preview/upload",
        data={
            "preview": preview_file,
            "metadata": json.dumps({}),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 401
    data = response.get_json()
    assert "error" in data
