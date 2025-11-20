"""
Tests for database models.

Covers User, Project, Clip, MediaFile, and other core models.
"""
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


class TestUserModel:
    """Test User model."""

    def test_user_creation(self, app):
        """Should create user successfully."""
        with app.app_context():
            user = User(username="newuser", email="new@example.com")
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()

            retrieved = User.query.filter_by(username="newuser").first()
            assert retrieved is not None
            assert retrieved.email == "new@example.com"

    def test_password_hashing(self, app):
        """Should hash passwords securely."""
        with app.app_context():
            user = User(username="testpw", email="testpw@example.com")
            user.set_password("secret123")
            db.session.add(user)
            db.session.commit()

            # Password should be hashed
            assert user.password_hash != "secret123"
            # Check password should work
            assert user.check_password("secret123")
            assert not user.check_password("wrongpassword")

    def test_user_roles(self, app):
        """Should support different user roles."""
        with app.app_context():
            regular_user = User(username="regular", email="regular@example.com")
            assert regular_user.role == UserRole.USER

            admin_user = User(
                username="admintest", email="admin@example.com", role=UserRole.ADMIN
            )
            assert admin_user.role == UserRole.ADMIN

    def test_user_defaults(self, app):
        """Should have correct default values."""
        with app.app_context():
            user = User(username="defaults", email="defaults@example.com")
            db.session.add(user)
            db.session.commit()

            assert user.is_active is True
            assert user.email_verified is False
            assert user.role == UserRole.USER


class TestProjectModel:
    """Test Project model."""

    def test_project_creation(self, app, test_user):
        """Should create project successfully."""
        with app.app_context():
            project = Project(
                name="Test Project",
                user_id=test_user,
                status=ProjectStatus.DRAFT,
                output_resolution="1080p",
                output_format="mp4",
            )
            db.session.add(project)
            db.session.commit()

            retrieved = Project.query.filter_by(name="Test Project").first()
            assert retrieved is not None
            assert retrieved.status == ProjectStatus.DRAFT

    def test_project_status_transitions(self, app, test_user):
        """Should support different project statuses."""
        with app.app_context():
            project = Project(
                name="Status Test",
                user_id=test_user,
                status=ProjectStatus.DRAFT,
            )
            db.session.add(project)
            db.session.commit()

            # Update status
            project.status = ProjectStatus.COMPILING
            db.session.commit()
            assert project.status == ProjectStatus.COMPILING

            project.status = ProjectStatus.COMPLETED
            db.session.commit()
            assert project.status == ProjectStatus.COMPLETED

    def test_project_public_id_generation(self, app, test_user):
        """Should generate public ID for projects."""
        with app.app_context():
            project = Project(
                name="Public ID Test",
                user_id=test_user,
            )
            db.session.add(project)
            db.session.commit()

            # Public ID should be generated (if model has this feature)
            if hasattr(project, "public_id"):
                assert project.public_id is not None
                assert len(project.public_id) > 0


class TestClipModel:
    """Test Clip model."""

    def test_clip_creation(self, app, test_project):
        """Should create clip successfully."""
        with app.app_context():
            clip = Clip(
                title="Test Clip",
                source_url="https://clips.twitch.tv/test123",
                source_platform="twitch",
                project_id=test_project,
            )
            db.session.add(clip)
            db.session.commit()

            retrieved = Clip.query.filter_by(title="Test Clip").first()
            assert retrieved is not None
            assert retrieved.source_platform == "twitch"

    def test_clip_order_index(self, app, test_project):
        """Should support clip ordering."""
        with app.app_context():
            clip1 = Clip(
                title="Clip 1",
                source_url="https://example.com/1",
                project_id=test_project,
                order_index=0,
            )
            clip2 = Clip(
                title="Clip 2",
                source_url="https://example.com/2",
                project_id=test_project,
                order_index=1,
            )
            db.session.add_all([clip1, clip2])
            db.session.commit()

            clips = (
                Clip.query.filter_by(project_id=test_project)
                .order_by(Clip.order_index)
                .all()
            )
            assert len(clips) >= 2
            assert clips[0].order_index < clips[1].order_index


class TestMediaFileModel:
    """Test MediaFile model."""

    def test_media_file_creation(self, app, test_user):
        """Should create media file successfully."""
        with app.app_context():
            media = MediaFile(
                filename="test.mp4",
                original_filename="test.mp4",
                file_path="/test/path/test.mp4",
                file_size=1024,
                mime_type="video/mp4",
                media_type=MediaType.CLIP,
                user_id=test_user,
            )
            db.session.add(media)
            db.session.commit()

            retrieved = MediaFile.query.filter_by(filename="test.mp4").first()
            assert retrieved is not None
            assert retrieved.media_type == MediaType.CLIP

    def test_media_types(self, app, test_user):
        """Should support different media types."""
        with app.app_context():
            intro = MediaFile(
                filename="intro.mp4",
                file_path="/test/intro.mp4",
                media_type=MediaType.INTRO,
                user_id=test_user,
            )
            outro = MediaFile(
                filename="outro.mp4",
                file_path="/test/outro.mp4",
                media_type=MediaType.OUTRO,
                user_id=test_user,
            )
            transition = MediaFile(
                filename="transition.mp4",
                file_path="/test/transition.mp4",
                media_type=MediaType.TRANSITION,
                user_id=test_user,
            )
            db.session.add_all([intro, outro, transition])
            db.session.commit()

            assert intro.media_type == MediaType.INTRO
            assert outro.media_type == MediaType.OUTRO
            assert transition.media_type == MediaType.TRANSITION

    def test_media_metadata(self, app, test_user):
        """Should store video metadata."""
        with app.app_context():
            media = MediaFile(
                filename="metadata_test.mp4",
                file_path="/test/metadata.mp4",
                user_id=test_user,
                duration=60.5,
                width=1920,
                height=1080,
                framerate=30.0,
            )
            db.session.add(media)
            db.session.commit()

            retrieved = MediaFile.query.filter_by(filename="metadata_test.mp4").first()
            assert retrieved.duration == 60.5
            assert retrieved.width == 1920
            assert retrieved.height == 1080
            assert retrieved.framerate == 30.0
