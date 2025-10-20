"""
Database models for Clippy application.

This module contains all SQLAlchemy models defining the database schema
for users, projects, media files, clips, and related entities.
"""
import secrets
from datetime import datetime
from enum import Enum

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

# Initialize SQLAlchemy instance
db = SQLAlchemy()


class UserRole(Enum):
    """
    Enumeration for user roles in the system.

    - USER: Regular user with basic permissions
    - ADMIN: Administrator with full system access
    """

    USER = "user"
    ADMIN = "admin"


class ProjectStatus(Enum):
    """
    Enumeration for project processing status.

    - DRAFT: Project being created/edited
    - PROCESSING: Video compilation in progress
    - COMPLETED: Video compilation finished
    - FAILED: Video compilation failed
    """

    DRAFT = "draft"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MediaType(Enum):
    """
    Enumeration for different types of media files.

    - INTRO: Introduction video
    - OUTRO: Ending video
    - TRANSITION: Transition between clips
    - CLIP: Main content clip
    - COMPILATION: Final compiled render output
    """

    INTRO = "intro"
    OUTRO = "outro"
    TRANSITION = "transition"
    CLIP = "clip"
    COMPILATION = "compilation"


class User(UserMixin, db.Model):
    """
    User model for authentication and user management.

    This model stores user account information, authentication data,
    and user preferences for the video compilation platform.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # User profile information
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    role = db.Column(db.Enum(UserRole), default=UserRole.USER, nullable=False)

    # Account status and timestamps
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime)
    # Optional path to user's profile image stored on disk
    profile_image_path = db.Column(db.String(500))

    # External service connections
    discord_user_id = db.Column(db.String(100), unique=True)
    twitch_username = db.Column(db.String(100))

    # Preferences
    date_format = db.Column(
        db.String(32),
        default="auto",
        nullable=False,
        doc="Preferred date format: auto|mdy|dmy|ymd|long",
    )

    # Relationships
    projects = db.relationship(
        "Project", backref="owner", lazy="dynamic", cascade="all, delete-orphan"
    )
    media_files = db.relationship(
        "MediaFile", backref="user", lazy="dynamic", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        """
        Hash and set the user's password.

        Args:
            password: Plain text password to hash
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """
        Check if the provided password matches the stored hash.

        Args:
            password: Plain text password to verify

        Returns:
            bool: True if password matches, False otherwise
        """
        return check_password_hash(self.password_hash, password)

    def is_admin(self) -> bool:
        """
        Check if user has admin privileges.

        Returns:
            bool: True if user is admin, False otherwise
        """
        return self.role == UserRole.ADMIN

    @property
    def full_name(self) -> str:
        """
        Get user's full name.

        Returns:
            str: Combined first and last name, or username if names not set
        """
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username

    def __repr__(self) -> str:
        return f"<User {self.username}>"

    # Convenience for templates expecting a method instead of property
    def get_display_name(self) -> str:
        """
        Return a human-friendly display name for the user.

        Falls back to username when first/last name are not set.
        """
        return self.full_name


class Project(db.Model):
    """
    Project model representing a video compilation project.

    Each project contains metadata about a video compilation including
    clips, processing status, and output settings.
    """

    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    # Short, opaque identifier for URL usage (non-sequential, URL-safe)
    public_id = db.Column(db.String(32), unique=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Project ownership and status
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(
        db.Enum(ProjectStatus), default=ProjectStatus.DRAFT, nullable=False
    )

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at = db.Column(db.DateTime)

    # Processing settings
    max_clip_duration = db.Column(db.Integer, default=30)  # seconds
    output_resolution = db.Column(db.String(20), default="1080p")
    output_format = db.Column(db.String(10), default="mp4")

    # Output file information
    output_filename = db.Column(db.String(255))
    output_file_size = db.Column(db.BigInteger)
    processing_log = db.Column(db.Text)

    # Relationships
    clips = db.relationship(
        "Clip", backref="project", lazy="dynamic", cascade="all, delete-orphan"
    )
    media_files = db.relationship("MediaFile", backref="project", lazy="dynamic")

    def get_total_duration(self) -> int:
        """
        Calculate total duration of all clips in the project.

        Returns:
            int: Total duration in seconds
        """
        return sum(clip.duration or 0 for clip in self.clips)

    def get_clip_count(self) -> int:
        """
        Get the number of clips in this project.

        Returns:
            int: Number of clips
        """
        return self.clips.count()

    def __repr__(self) -> str:
        return f"<Project {self.name}>"

    @staticmethod
    def generate_public_id() -> str:
        """Generate a short, URL-safe opaque identifier.

        12-16 chars from token_urlsafe provides ~72-96 bits of entropy.
        """
        return secrets.token_urlsafe(12)


class MediaFile(db.Model):
    """
    Media file model for storing uploaded videos and images.

    This model tracks all media files uploaded by users including
    intro videos, outro videos, transitions, and collected clips.
    """

    __tablename__ = "media_files"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    # Optional human description/title for library listing
    description = db.Column(db.Text)

    # File metadata
    file_path = db.Column(db.String(500), nullable=False)
    # Content checksum for dedupe/reuse (sha256 hex)
    checksum = db.Column(db.String(64), index=True)
    file_size = db.Column(db.BigInteger, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    media_type = db.Column(db.Enum(MediaType), nullable=False)

    # Video/Audio properties
    duration = db.Column(db.Float)  # Duration in seconds
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    framerate = db.Column(db.Float)

    # Ownership and project association
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))

    # Timestamps
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Processing status
    is_processed = db.Column(db.Boolean, default=False)
    thumbnail_path = db.Column(db.String(500))
    # Comma-separated tags (lightweight tagging)
    tags = db.Column(db.Text)

    @property
    def file_size_mb(self) -> float:
        """
        Get file size in megabytes.

        Returns:
            float: File size in MB
        """
        return self.file_size / (1024 * 1024)

    @property
    def duration_formatted(self) -> str:
        """
        Get formatted duration string.

        Returns:
            str: Duration in MM:SS format
        """
        if not self.duration:
            return "00:00"

        minutes = int(self.duration // 60)
        seconds = int(self.duration % 60)
        return f"{minutes:02d}:{seconds:02d}"

    def __repr__(self) -> str:
        return f"<MediaFile {self.filename}>"


class Clip(db.Model):
    """
    Clip model representing individual video clips in a project.

    Clips can be collected from external sources (Discord, Twitch)
    or uploaded directly by users.
    """

    __tablename__ = "clips"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Clip source information
    source_platform = db.Column(db.String(50))  # 'discord', 'twitch', 'upload'
    source_url = db.Column(db.String(500))
    source_id = db.Column(db.String(100))  # Platform-specific ID

    # Optional enriched metadata for UI and rendering
    creator_name = db.Column(db.String(120))  # who clipped it / creator
    creator_id = db.Column(db.String(64))  # platform user id (e.g., Twitch user id)
    creator_avatar_path = db.Column(
        db.String(500)
    )  # cached avatar file path if downloaded
    game_name = db.Column(db.String(120))  # game title if available
    clip_created_at = db.Column(db.DateTime)  # when clip was created on platform

    # Project association
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)

    # Media file reference
    media_file_id = db.Column(db.Integer, db.ForeignKey("media_files.id"))
    media_file = db.relationship("MediaFile", backref="clips")

    # Clip timing and order
    start_time = db.Column(db.Float, default=0.0)  # Start time in seconds
    end_time = db.Column(db.Float)  # End time in seconds
    duration = db.Column(db.Float)  # Duration in seconds
    order_index = db.Column(db.Integer, default=0)  # Order in compilation

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    collected_at = db.Column(
        db.DateTime
    )  # When clip was collected from external source

    # Processing flags
    is_downloaded = db.Column(db.Boolean, default=False)
    is_processed = db.Column(db.Boolean, default=False)

    @property
    def duration_formatted(self) -> str:
        """
        Get formatted duration string.

        Returns:
            str: Duration in MM:SS format
        """
        if not self.duration:
            return "00:00"

        minutes = int(self.duration // 60)
        seconds = int(self.duration % 60)
        return f"{minutes:02d}:{seconds:02d}"

    def __repr__(self) -> str:
        return f"<Clip {self.title}>"


class ProcessingJob(db.Model):
    """
    Processing job model for tracking video compilation jobs.

    This model tracks the status and progress of video processing
    tasks handled by Celery workers.
    """

    __tablename__ = "processing_jobs"

    id = db.Column(db.Integer, primary_key=True)
    celery_task_id = db.Column(db.String(100), unique=True, nullable=False)

    # Job information
    job_type = db.Column(
        db.String(50), nullable=False
    )  # 'compile_video', 'download_clip', etc.
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Status tracking
    status = db.Column(db.String(50), default="pending")
    progress = db.Column(db.Integer, default=0)  # 0-100

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    # Results and error handling
    result_data = db.Column(db.JSON)
    error_message = db.Column(db.Text)

    # Relationships
    project = db.relationship(
        "Project",
        backref=db.backref("processing_jobs", lazy="dynamic"),
    )
    user = db.relationship(
        "User",
        backref=db.backref("processing_jobs", lazy="dynamic"),
    )

    @property
    def is_completed(self) -> bool:
        """
        Check if job is completed (success or failure).

        Returns:
            bool: True if job is in terminal state
        """
        return self.status in ["success", "failure", "revoked"]

    @property
    def duration(self) -> float:
        """
        Get job duration in seconds.

        Returns:
            float: Duration in seconds, or None if not completed
        """
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def __repr__(self) -> str:
        return f"<ProcessingJob {self.job_type} - {self.status}>"


class SystemSetting(db.Model):
    """
    System-wide settings editable from the Admin UI.

    These override app.config at runtime for a curated allowlist. Secrets should
    remain in environment/.env and are not stored here.
    """

    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)
    value_type = db.Column(
        db.String(20),
        nullable=False,
        default="str",
        doc="str|int|float|bool|json",
    )
    group = db.Column(db.String(50), nullable=True, index=True)
    description = db.Column(db.Text)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_by_user = db.relationship(
        "User", backref=db.backref("settings_updates", lazy="dynamic")
    )

    def __repr__(self) -> str:
        return f"<SystemSetting {self.key}={self.value}>"


class Theme(db.Model):
    """UI theme with colors and branding assets.

    Allows admins to customize the look and feel: colors, logo, favicon,
    and optional watermark. One theme can be marked active.
    """

    __tablename__ = "themes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)

    # Activation flag (only one should be active; enforced at app level)
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    # Core palette (hex strings like #RRGGBB or CSS color names)
    color_primary = db.Column(db.String(20), default="#0d6efd")
    color_secondary = db.Column(db.String(20), default="#6c757d")
    color_accent = db.Column(db.String(20), default="#6610f2")
    color_background = db.Column(db.String(20), default="#121212")
    color_surface = db.Column(db.String(20), default="#1e1e1e")
    color_text = db.Column(db.String(20), default="#e9ecef")
    color_muted = db.Column(db.String(20), default="#adb5bd")
    navbar_bg = db.Column(db.String(20), default="#212529")
    navbar_text = db.Column(db.String(20), default="#ffffff")

    # Assets (stored under instance/uploads/system/themes/<id>/...)
    logo_path = db.Column(db.String(500))
    favicon_path = db.Column(db.String(500))
    watermark_path = db.Column(db.String(500))

    # Watermark options
    watermark_opacity = db.Column(db.Float, default=0.1)
    watermark_position = db.Column(
        db.String(32),
        default="bottom-right",
        doc="top-left|top-right|bottom-left|bottom-right|center",
    )

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_by_user = db.relationship(
        "User", backref=db.backref("theme_updates", lazy="dynamic")
    )
    # Explicit light/dark override. Values: 'auto'|'light'|'dark'
    mode = db.Column(db.String(10), default="auto")

    def as_css_vars(self) -> dict:
        """Return a dict of CSS variable names to values for templates."""
        return {
            "--color-primary": self.color_primary or "#0d6efd",
            "--color-secondary": self.color_secondary or "#6c757d",
            "--color-accent": self.color_accent or "#6610f2",
            "--color-background": self.color_background or "#121212",
            "--color-surface": self.color_surface or "#1e1e1e",
            "--color-text": self.color_text or "#e9ecef",
            "--color-muted": self.color_muted or "#adb5bd",
            "--navbar-bg": self.navbar_bg or "#212529",
            "--navbar-text": self.navbar_text or "#ffffff",
            # Focus ring and outline colors (defaults based on primary/accent)
            # These may be overridden further downstream if needed
            "--outline-color": self.color_accent or self.color_primary or "#6610f2",
        }

    def __repr__(self) -> str:
        return f"<Theme {self.name}{' *' if self.is_active else ''}>"
