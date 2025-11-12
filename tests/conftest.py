import tempfile

import pytest

from app import create_app
from app.models import (
    Clip,
    MediaFile,
    MediaType,
    Project,
    ProjectStatus,
    User,
    UserRole,
    db,
)


@pytest.fixture()
def app():
    # Use a temp instance folder and sqlite DB for tests
    instance_path = tempfile.mkdtemp()
    cfg = {
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "UPLOAD_FOLDER": "uploads",
        "RATELIMIT_ENABLED": False,
        "FORCE_HTTPS": False,
        "WORKER_API_KEY": "test-worker-key-12345",  # For worker API tests
    }
    flask_app = create_app()
    flask_app.config.update(cfg)
    # Override instance path
    flask_app.instance_path = instance_path
    with flask_app.app_context():
        # Ensure a clean schema per test run
        db.drop_all()
        db.create_all()
        # Create a default user
        user = User(username="tester", email="t@example.com")
        user.set_password("pass1234")
        db.session.add(user)
        admin = User(username="admin", email="a@example.com", role=UserRole.ADMIN)
        admin.set_password("admin1234")
        db.session.add(admin)
        db.session.commit()
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth(client):
    class AuthActions:
        def login(self, username="tester", password="pass1234"):
            return client.post(
                "/auth/login",
                data={
                    "username_or_email": username,
                    "password": password,
                },
                follow_redirects=True,
            )

        def logout(self):
            return client.get("/auth/logout", follow_redirects=True)

    return AuthActions()


@pytest.fixture()
def test_user(app):
    """Create a test user for worker API tests."""
    with app.app_context():
        user = User.query.filter_by(username="testuser").first()
        if not user:
            user = User(username="testuser", email="testuser@example.com")
            user.set_password("testpass123")
            db.session.add(user)
            db.session.commit()
        # Capture and return the ID while inside the app context to avoid detached instances
        user_id = int(user.id)
        return user_id


@pytest.fixture()
def test_project(app, test_user):
    """Create a test project for worker API tests."""
    with app.app_context():
        project = Project(
            name="Test Project",
            user_id=test_user,  # test_user is an ID
            status=ProjectStatus.DRAFT,
            output_resolution="1080p",
            output_format="mp4",
        )
        db.session.add(project)
        db.session.commit()
        project_id = int(project.id)
        return project_id


@pytest.fixture()
def test_clip(app, test_project):
    """Create a test clip for worker API tests."""
    with app.app_context():
        clip = Clip(
            title="Test Clip",
            source_url="https://youtube.com/watch?v=test-clip-url",
            source_platform="YouTube",
            project_id=test_project,
            is_downloaded=False,
        )
        db.session.add(clip)
        db.session.commit()
        clip_id = int(clip.id)
        return clip_id


@pytest.fixture()
def test_media_file(app, test_user, test_project):
    """Create a test media file for worker API tests."""
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
        )
        db.session.add(media)
        db.session.commit()
        media_id = int(media.id)
        return media_id
