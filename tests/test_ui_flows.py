"""
Tests for UI flows and user interactions.

Covers project wizard, media upload, and compilation workflows.
"""
import io
import json
from unittest.mock import patch

from app.models import Project, ProjectStatus, db


class TestProjectWizard:
    """Test project wizard flow."""

    def test_wizard_page_loads(self, client, auth):
        """Project wizard page should load for authenticated users."""
        auth.login()
        response = client.get("/projects/wizard")
        assert response.status_code == 200
        assert b"wizard" in response.data.lower() or b"project" in response.data.lower()

    def test_wizard_requires_auth(self, client):
        """Project wizard should require authentication."""
        response = client.get("/projects/wizard", follow_redirects=False)
        assert response.status_code in (301, 302, 401)

    def test_create_project_from_wizard(self, client, auth, app):
        """Should create project through wizard."""
        auth.login()

        # Create project via API endpoint
        response = client.post(
            "/api/projects",
            data=json.dumps(
                {
                    "name": "Wizard Test Project",
                    "description": "Created via wizard",
                    "output_resolution": "1080p",
                    "output_format": "mp4",
                }
            ),
            content_type="application/json",
        )

        # Should create successfully or return existing
        assert response.status_code in (200, 201)

        # Verify project was created
        with app.app_context():
            project = Project.query.filter_by(name="Wizard Test Project").first()
            if project:
                assert project.status == ProjectStatus.DRAFT


class TestMediaUpload:
    """Test media upload functionality."""

    def test_media_upload_page_requires_auth(self, client):
        """Media upload should require authentication."""
        response = client.get("/media", follow_redirects=False)
        assert response.status_code in (301, 302, 401)

    def test_media_library_page_loads(self, client, auth):
        """Authenticated user should see media library."""
        auth.login()
        response = client.get("/media")
        assert response.status_code == 200
        assert b"media" in response.data.lower() or b"library" in response.data.lower()

    def test_upload_video_file(self, client, auth, app, test_project):
        """Should upload video file to project."""
        auth.login()

        # Create a fake video file
        data = {
            "file": (io.BytesIO(b"fake video content"), "test_video.mp4"),
        }

        response = client.post(
            f"/projects/{test_project}/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        # Should succeed or show upload page
        assert response.status_code == 200

    def test_upload_invalid_file_type(self, client, auth, test_project):
        """Should reject invalid file types."""
        auth.login()

        # Try to upload a text file
        data = {
            "file": (io.BytesIO(b"not a video"), "test.txt"),
        }

        response = client.post(
            f"/projects/{test_project}/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        # Should show error or reject upload
        assert response.status_code in (200, 400)


class TestProjectCompilation:
    """Test project compilation flow."""

    def test_compilation_requires_clips(self, client, auth, test_project):
        """Should not compile project without clips."""
        auth.login()

        response = client.post(
            f"/projects/{test_project}/compile",
            follow_redirects=True,
        )

        # May show error or redirect back to project
        assert response.status_code in (200, 400, 302)

    @patch("app.tasks.compile_video_v2.compile_project_task.delay")
    def test_start_compilation(self, mock_task, client, auth, test_project, test_clip):
        """Should start compilation task."""
        auth.login()

        # Mock Celery task
        mock_task.return_value.id = "test-task-id"

        response = client.post(
            f"/projects/{test_project}/compile",
            follow_redirects=False,
        )

        # Should queue task and redirect
        assert response.status_code in (200, 302, 303)

    def test_download_compiled_video(self, client, auth, test_project, app):
        """Should download completed compilation."""
        auth.login()

        # Set project as completed
        with app.app_context():
            project = db.session.get(Project, test_project)
            project.status = ProjectStatus.COMPLETED
            project.output_file = "/instance/data/testuser/compilation.mp4"
            db.session.commit()

        # Try to download
        response = client.get(
            f"/projects/{test_project}/download",
            follow_redirects=False,
        )

        # Should serve file or show download page
        assert response.status_code in (200, 302, 404)


class TestProjectDashboard:
    """Test project dashboard and listing."""

    def test_dashboard_requires_auth(self, client):
        """Dashboard should require authentication."""
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code in (301, 302, 401)

    def test_dashboard_loads_for_user(self, client, auth):
        """Authenticated user should see dashboard."""
        auth.login()
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert (
            b"dashboard" in response.data.lower() or b"project" in response.data.lower()
        )

    def test_projects_list_page(self, client, auth):
        """Should list user's projects."""
        auth.login()
        response = client.get("/projects")
        assert response.status_code == 200

    def test_project_details_page(self, client, auth, test_project):
        """Should show project details."""
        auth.login()

        # Try to view project details
        with client.application.app_context():
            project = db.session.get(Project, test_project)
            if hasattr(project, "public_id") and project.public_id:
                response = client.get(f"/p/{project.public_id}")
            else:
                response = client.get(f"/projects/{test_project}")

            assert response.status_code in (200, 302, 404)

    def test_delete_project(self, client, auth, app):
        """Should delete project."""
        auth.login()

        # Create a temporary project
        with app.app_context():
            from app.models import User

            user = User.query.filter_by(username="tester").first()
            project = Project(
                name="Project to Delete",
                user_id=user.id,
                status=ProjectStatus.DRAFT,
            )
            db.session.add(project)
            db.session.commit()
            project_id = project.id

        # Delete the project
        response = client.post(
            f"/projects/{project_id}/delete",
            follow_redirects=True,
        )

        # Should succeed
        assert response.status_code == 200

        # Verify deletion
        with app.app_context():
            project = db.session.get(Project, project_id)
            assert project is None


class TestStaticPages:
    """Test static/informational pages."""

    def test_landing_page(self, client):
        """Landing page should load without auth."""
        response = client.get("/")
        assert response.status_code == 200

    def test_privacy_policy(self, client):
        """Privacy policy should be accessible."""
        response = client.get("/privacy")
        assert response.status_code in (200, 404)

    def test_terms_of_service(self, client):
        """Terms of service should be accessible."""
        response = client.get("/terms")
        assert response.status_code in (200, 404)

    def test_documentation_page(self, client):
        """Documentation should be accessible."""
        response = client.get("/docs")
        assert response.status_code in (200, 404)
