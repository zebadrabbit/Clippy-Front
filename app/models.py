"""
Database models for ClippyFront application.

This module contains all SQLAlchemy models defining the database schema
for users, projects, media files, clips, and related entities.
"""
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
    """

    INTRO = "intro"
    OUTRO = "outro"
    TRANSITION = "transition"
    CLIP = "clip"


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

    # External service connections
    discord_user_id = db.Column(db.String(100), unique=True)
    twitch_username = db.Column(db.String(100))

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

    # File metadata
    file_path = db.Column(db.String(500), nullable=False)
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
