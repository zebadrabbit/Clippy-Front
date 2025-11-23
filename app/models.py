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


class TeamRole(Enum):
    """
    Enumeration for team member roles.

    - OWNER: Team owner with full permissions (cannot be removed)
    - ADMIN: Administrator with full team management permissions
    - EDITOR: Can edit shared projects but cannot manage team
    - VIEWER: Read-only access to shared projects
    """

    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class ActivityType(Enum):
    """
    Enumeration for activity log types.

    Team Activities:
    - TEAM_CREATED: Team was created
    - TEAM_UPDATED: Team name/description changed
    - TEAM_DELETED: Team was deleted
    - MEMBER_ADDED: User added to team
    - MEMBER_REMOVED: User removed from team
    - MEMBER_LEFT: User left team voluntarily
    - MEMBER_ROLE_CHANGED: User's role in team changed

    Project Activities:
    - PROJECT_CREATED: Project was created
    - PROJECT_SHARED: Project shared with team
    - PROJECT_UNSHARED: Project removed from team
    - PROJECT_UPDATED: Project settings changed
    - PROJECT_DELETED: Project was deleted

    Compilation Activities:
    - PREVIEW_GENERATED: Preview video created
    - COMPILATION_STARTED: Full compilation started
    - COMPILATION_COMPLETED: Compilation finished successfully
    - COMPILATION_FAILED: Compilation failed with error
    """

    # Team activities
    TEAM_CREATED = "team_created"
    TEAM_UPDATED = "team_updated"
    TEAM_DELETED = "team_deleted"
    MEMBER_ADDED = "member_added"
    MEMBER_REMOVED = "member_removed"
    MEMBER_LEFT = "member_left"
    MEMBER_ROLE_CHANGED = "member_role_changed"

    # Project activities
    PROJECT_CREATED = "project_created"
    PROJECT_SHARED = "project_shared"
    PROJECT_UNSHARED = "project_unshared"
    PROJECT_UPDATED = "project_updated"
    PROJECT_DELETED = "project_deleted"

    # Compilation activities
    PREVIEW_GENERATED = "preview_generated"
    COMPILATION_STARTED = "compilation_started"
    COMPILATION_COMPLETED = "compilation_completed"
    COMPILATION_FAILED = "compilation_failed"


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


class PlatformPreset(Enum):
    """
    Enumeration for social media platform export presets.

    Each preset defines optimal settings for specific platforms:
    - YOUTUBE: YouTube standard (1920x1080, 16:9, MP4)
    - YOUTUBE_SHORTS: YouTube Shorts (1080x1920, 9:16, ≤60s)
    - TIKTOK: TikTok (1080x1920, 9:16, ≤10min)
    - INSTAGRAM_FEED: Instagram Feed (1080x1080, 1:1)
    - INSTAGRAM_REEL: Instagram Reels (1080x1920, 9:16, ≤90s)
    - INSTAGRAM_STORY: Instagram Stories (1080x1920, 9:16, ≤60s)
    - TWITTER: Twitter/X (1920x1080, 16:9, ≤2:20)
    - FACEBOOK: Facebook (1920x1080, 16:9)
    - TWITCH: Twitch Clips (1920x1080, 16:9)
    - CUSTOM: User-defined settings
    """

    YOUTUBE = "youtube"
    YOUTUBE_SHORTS = "youtube_shorts"
    TIKTOK = "tiktok"
    INSTAGRAM_FEED = "instagram_feed"
    INSTAGRAM_REEL = "instagram_reel"
    INSTAGRAM_STORY = "instagram_story"
    TWITTER = "twitter"
    FACEBOOK = "facebook"
    TWITCH = "twitch"
    CUSTOM = "custom"

    @property
    def display_name(self) -> str:
        """Get human-readable platform name."""
        names = {
            "youtube": "YouTube",
            "youtube_shorts": "YouTube Shorts",
            "tiktok": "TikTok",
            "instagram_feed": "Instagram Feed",
            "instagram_reel": "Instagram Reels",
            "instagram_story": "Instagram Stories",
            "twitter": "Twitter/X",
            "facebook": "Facebook",
            "twitch": "Twitch Clips",
            "custom": "Custom",
        }
        return names.get(self.value, self.value.title())

    def get_settings(self) -> dict:
        """
        Get recommended export settings for this platform.

        Returns:
            dict: Export settings including resolution, aspect ratio, format, etc.
        """
        settings = {
            "youtube": {
                "width": 1920,
                "height": 1080,
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "8M",
                "max_duration": None,
                "orientation": "landscape",
            },
            "youtube_shorts": {
                "width": 1080,
                "height": 1920,
                "aspect_ratio": "9:16",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "5M",
                "max_duration": 60,
                "orientation": "portrait",
            },
            "tiktok": {
                "width": 1080,
                "height": 1920,
                "aspect_ratio": "9:16",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "5M",
                "max_duration": 600,
                "orientation": "portrait",
            },
            "instagram_feed": {
                "width": 1080,
                "height": 1080,
                "aspect_ratio": "1:1",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "5M",
                "max_duration": 60,
                "orientation": "square",
            },
            "instagram_reel": {
                "width": 1080,
                "height": 1920,
                "aspect_ratio": "9:16",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "5M",
                "max_duration": 90,
                "orientation": "portrait",
            },
            "instagram_story": {
                "width": 1080,
                "height": 1920,
                "aspect_ratio": "9:16",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "5M",
                "max_duration": 60,
                "orientation": "portrait",
            },
            "twitter": {
                "width": 1920,
                "height": 1080,
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "6M",
                "max_duration": 140,
                "orientation": "landscape",
            },
            "facebook": {
                "width": 1920,
                "height": 1080,
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "8M",
                "max_duration": None,
                "orientation": "landscape",
            },
            "twitch": {
                "width": 1920,
                "height": 1080,
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 60,
                "bitrate": "8M",
                "max_duration": 60,
                "orientation": "landscape",
            },
            "custom": {
                "width": 1920,
                "height": 1080,
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "format": "mp4",
                "codec": "h264",
                "fps": 30,
                "bitrate": "8M",
                "max_duration": None,
                "orientation": "landscape",
            },
        }
        return settings.get(self.value, settings["custom"])


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
    # Password reset token and expiration
    reset_token = db.Column(db.String(255))
    reset_token_created_at = db.Column(db.DateTime)
    # Email verification token and pending email
    email_verification_token = db.Column(db.String(255))
    email_verification_token_created_at = db.Column(db.DateTime)
    pending_email = db.Column(db.String(120))
    # Optional path to user's profile image stored on disk
    profile_image_path = db.Column(db.String(500))

    # Admin-only preference: disable global watermark overlay for this user
    watermark_disabled = db.Column(db.Boolean, default=False, nullable=False)

    # Tier/Plan assignment (quotas). Nullable for legacy rows; default applied in app logic.
    tier_id = db.Column(db.Integer, db.ForeignKey("tiers.id"))

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
    timezone = db.Column(
        db.String(64),
        nullable=True,
        doc="Preferred IANA timezone name for localizing schedules and times",
    )

    # Relationships
    projects = db.relationship(
        "Project", backref="owner", lazy="dynamic", cascade="all, delete-orphan"
    )
    media_files = db.relationship(
        "MediaFile", backref="user", lazy="dynamic", cascade="all, delete-orphan"
    )
    # Optional relationship to user's assigned tier
    tier = db.relationship("Tier", backref=db.backref("users", lazy="dynamic"))

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

    def generate_password_reset_token(self) -> str:
        """
        Generate a secure password reset token.

        Returns:
            str: URL-safe token (32 bytes hex = 64 chars)
        """
        return secrets.token_urlsafe(32)

    @staticmethod
    def verify_password_reset_token(token: str, max_age: int = 3600) -> "User | None":
        """
        Verify a password reset token and return the user.

        Args:
            token: The reset token to verify
            max_age: Token validity period in seconds (default 1 hour)

        Returns:
            User | None: User object if token is valid, None otherwise
        """
        # Simple implementation: find user with matching token that hasn't expired
        # For production, consider using itsdangerous.URLSafeTimedSerializer
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(seconds=max_age)
        user = User.query.filter(
            User.reset_token == token, User.reset_token_created_at > cutoff
        ).first()
        return user

    def generate_email_verification_token(self) -> str:
        """
        Generate a secure email verification token.

        Returns:
            str: URL-safe token (32 bytes hex = 64 chars)
        """
        return secrets.token_urlsafe(32)

    @staticmethod
    def verify_email_verification_token(
        token: str, max_age: int = 86400
    ) -> "User | None":
        """
        Verify an email verification token and return the user.

        Args:
            token: The verification token to verify
            max_age: Token validity period in seconds (default 24 hours)

        Returns:
            User | None: User object if token is valid, None otherwise
        """
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(seconds=max_age)
        user = User.query.filter(
            User.email_verification_token == token,
            User.email_verification_token_created_at > cutoff,
        ).first()
        return user

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

    # Team collaboration (optional)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)

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
    # Audio normalization (optional per-project)
    audio_norm_profile = db.Column(db.String(32))
    audio_norm_db = db.Column(db.Float)

    # Platform export preset
    platform_preset = db.Column(
        db.Enum(PlatformPreset, native_enum=False),
        default=PlatformPreset.CUSTOM,
        nullable=True,
    )
    # Additional video settings
    quality = db.Column(db.String(20), default="high")
    fps = db.Column(db.Integer, default=30)
    transitions_enabled = db.Column(db.Boolean, default=True)
    watermark_enabled = db.Column(db.Boolean, default=False)

    # Intro/Outro media references
    intro_media_id = db.Column(db.Integer, db.ForeignKey("media_files.id"))
    outro_media_id = db.Column(db.Integer, db.ForeignKey("media_files.id"))

    # Output file information
    output_filename = db.Column(db.String(255))
    output_file_size = db.Column(db.BigInteger)
    processing_log = db.Column(db.Text)

    # Preview file (low-res quick preview before full compile)
    preview_filename = db.Column(db.String(255))
    preview_file_size = db.Column(db.BigInteger)

    # Relationships
    clips = db.relationship(
        "Clip", backref="project", lazy="dynamic", cascade="all, delete-orphan"
    )
    media_files = db.relationship(
        "MediaFile",
        backref="project",
        lazy="dynamic",
        foreign_keys="MediaFile.project_id",
    )
    intro_media = db.relationship(
        "MediaFile", foreign_keys=[intro_media_id], uselist=False
    )
    outro_media = db.relationship(
        "MediaFile", foreign_keys=[outro_media_id], uselist=False
    )
    team = db.relationship(
        "Team",
        back_populates="projects",
        foreign_keys=[team_id],
    )

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
    view_count = db.Column(db.Integer)  # number of views on platform

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


# Association tables for many-to-many relationships
media_tags = db.Table(
    "media_tags",
    db.Column(
        "media_file_id", db.Integer, db.ForeignKey("media_files.id"), primary_key=True
    ),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), primary_key=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow, nullable=False),
)

clip_tags = db.Table(
    "clip_tags",
    db.Column("clip_id", db.Integer, db.ForeignKey("clips.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), primary_key=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow, nullable=False),
)


class Tag(db.Model):
    """
    Tag model for categorizing and filtering media files and clips.

    Tags provide a flexible way to organize content with support for
    hierarchical relationships (parent/child tags) and color coding.
    """

    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, index=True)
    slug = db.Column(db.String(50), nullable=False, index=True)
    description = db.Column(db.Text)

    # Visual customization
    color = db.Column(db.String(7), default="#6c757d")  # Hex color code

    # Ownership (user-specific tags or global)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_global = db.Column(db.Boolean, default=False)  # System-wide tags (admin only)

    # Hierarchical tags (optional parent-child relationship)
    parent_id = db.Column(db.Integer, db.ForeignKey("tags.id"))
    children = db.relationship(
        "Tag", backref=db.backref("parent", remote_side=[id]), lazy="dynamic"
    )

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships with media and clips
    media_files = db.relationship(
        "MediaFile",
        secondary=media_tags,
        backref=db.backref("tag_objects", lazy="dynamic"),
        lazy="dynamic",
    )

    clips = db.relationship(
        "Clip",
        secondary=clip_tags,
        backref=db.backref("tag_objects", lazy="dynamic"),
        lazy="dynamic",
    )

    # Usage statistics
    use_count = db.Column(db.Integer, default=0)  # Number of times tag is used

    __table_args__ = (
        db.UniqueConstraint("user_id", "slug", name="uix_user_tag_slug"),
        db.Index("ix_tags_user_name", "user_id", "name"),
    )

    @property
    def full_path(self) -> str:
        """
        Get the full hierarchical path of the tag.

        Returns:
            str: Full path like "Gaming/FPS/Valorant"
        """
        if self.parent:
            return f"{self.parent.full_path}/{self.name}"
        return self.name

    def increment_usage(self):
        """Increment the usage counter for this tag."""
        self.use_count = (self.use_count or 0) + 1
        self.updated_at = datetime.utcnow()

    def __repr__(self) -> str:
        return f"<Tag {self.name}>"


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


class Tier(db.Model):
    """Subscription tier/plan defining quotas and features.

    Limits are enforced as follows:
      - storage_limit_bytes: hard cap across all user's media (None => unlimited)
      - render_time_limit_seconds: monthly allowance based on output video durations (None => unlimited)
      - apply_watermark: when True, system watermark is applied on renders unless per-user override disables it
      - is_unlimited: shortcut to bypass all checks (admin/test tier)
    """

    __tablename__ = "tiers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)

    # Quotas
    storage_limit_bytes = db.Column(db.BigInteger, nullable=True)
    render_time_limit_seconds = db.Column(db.BigInteger, nullable=True)

    # Features
    apply_watermark = db.Column(db.Boolean, default=True, nullable=False)
    is_unlimited = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Output constraints (optional; None => unlimited)
    max_output_resolution = db.Column(
        db.String(10),
        nullable=True,
        doc="Maximum output resolution label allowed: 720p|1080p|1440p|2160p",
    )
    max_fps = db.Column(
        db.Integer, nullable=True, doc="Maximum frames per second for outputs"
    )
    max_clips_per_project = db.Column(
        db.Integer,
        nullable=True,
        doc="Maximum number of clips included in a single compilation",
    )
    # Automation/scheduling capability flags
    can_schedule_tasks = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        doc="Whether users on this tier can create scheduled automation tasks.",
    )
    max_schedules_per_user = db.Column(
        db.Integer,
        default=1,
        nullable=False,
        doc="Maximum number of active schedules per user for this tier.",
    )
    # Team collaboration limits
    max_teams_owned = db.Column(
        db.Integer,
        nullable=True,
        doc="Maximum number of teams a user can own (None => unlimited)",
    )
    max_team_members = db.Column(
        db.Integer,
        nullable=True,
        doc="Maximum number of members per team (None => unlimited)",
    )

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Tier {self.name}{' (unlimited)' if self.is_unlimited else ''}>"


class RenderUsage(db.Model):
    """Tracks render usage (based on compiled output duration) per user.

    Rows are appended after successful compilation with the final output duration
    to enable monthly aggregation and quota enforcement.
    """

    __tablename__ = "render_usage"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    seconds_used = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref=db.backref("render_usages", lazy="dynamic"))
    project = db.relationship(
        "Project", backref=db.backref("render_usages", lazy="dynamic")
    )


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

    # Optional explicit outline/focus ring color (falls back to accent)
    outline_color = db.Column(db.String(20))

    # Optional media/type-specific colors for UI accents
    media_color_intro = db.Column(db.String(20), default="#0ea5e9")
    media_color_clip = db.Column(
        db.String(20)
    )  # defaults to color_accent in CSS mapping
    media_color_outro = db.Column(db.String(20), default="#f59e0b")
    media_color_transition = db.Column(db.String(20), default="#22c55e")
    # Optional color for the final compiled output representation
    media_color_compilation = db.Column(db.String(20))

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
            "--outline-color": (
                self.outline_color
                or self.color_accent
                or self.color_primary
                or "#6610f2"
            ),
            # Media/type-specific accent colors
            "--media-color-intro": getattr(self, "media_color_intro", None)
            or "#0ea5e9",  # sky-500
            "--media-color-clip": getattr(self, "media_color_clip", None)
            or self.color_accent
            or "#6610f2",
            "--media-color-outro": getattr(self, "media_color_outro", None)
            or "#f59e0b",  # amber-500
            "--media-color-transition": getattr(self, "media_color_transition", None)
            or "#22c55e",  # green-500
            "--media-color-compilation": getattr(self, "media_color_compilation", None)
            or self.color_accent
            or "#6610f2",
        }

    def __repr__(self) -> str:
        return f"<Theme {self.name}{' *' if self.is_active else ''}>"


class CompilationTask(db.Model):
    """Reusable, parameterized compilation task definition.

    A task belongs to a single user and captures parameters for building a project
    and compiling it, such as clip source/limit, intro/outro IDs, transitions, and
    output settings overrides.
    """

    __tablename__ = "compilation_tasks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Template flag: if True, this is a saved template not meant for direct execution
    is_template = db.Column(db.Boolean, default=False, nullable=False)

    # Parameters blob; structure is validated in API layer
    params = db.Column(db.JSON, nullable=False, default={})

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    last_run_at = db.Column(db.DateTime)

    user = db.relationship(
        "User",
        backref=db.backref(
            "compilation_tasks", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    def __repr__(self) -> str:
        return f"<CompilationTask {self.id} {self.name}>"


class ScheduleType(Enum):
    """Supported schedule types for scheduled tasks."""

    DAILY = "daily"
    WEEKLY = "weekly"
    # Keep ONCE for backward-compat read of legacy rows, but don't expose in UI anymore
    ONCE = "once"
    MONTHLY = "monthly"


class ScheduledTask(db.Model):
    """A schedule attached to a CompilationTask.

    Minimal fields to avoid extra dependencies: supports daily at HH:MM, weekly on a given
    weekday at HH:MM (24h), or monthly on a given day at HH:MM. Time values are stored as
    strings and interpreted in UTC unless a timezone is provided (tz name). The scheduler
    tick will compute next_run_at.

    Note: legacy one-time ("once") schedules are still readable for backward compatibility
    but are treated as read-only via the API. They are not offered in the UI and should be
    migrated to a recurring type if further edits are needed.
    """

    __tablename__ = "scheduled_tasks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    task_id = db.Column(
        db.Integer, db.ForeignKey("compilation_tasks.id"), nullable=False
    )

    schedule_type = db.Column(
        db.Enum(
            ScheduleType,
            name="scheduletype",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=ScheduleType.DAILY,
    )
    # When schedule_type=ONCE: run_at is used (UTC)
    run_at = db.Column(db.DateTime)
    # When DAILY/WEEKLY: time of day "HH:MM" 24h
    daily_time = db.Column(db.String(5))
    # When WEEKLY: 0=Mon .. 6=Sun
    weekly_day = db.Column(db.Integer)
    # When MONTHLY: 1..31 (clamped to month's last day)
    monthly_day = db.Column(db.Integer)

    timezone = db.Column(db.String(64), default="UTC")
    enabled = db.Column(db.Boolean, default=True, nullable=False)

    next_run_at = db.Column(db.DateTime)
    last_run_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = db.relationship(
        "User",
        backref=db.backref(
            "scheduled_tasks", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )
    task = db.relationship(
        "CompilationTask",
        backref=db.backref("schedules", lazy="dynamic", cascade="all, delete-orphan"),
    )

    def __repr__(self) -> str:
        return f"<ScheduledTask {self.id} {self.schedule_type.value} enabled={self.enabled}>"


class Team(db.Model):
    """
    Team model for collaboration features.

    Teams allow multiple users to collaborate on projects.
    Each team has an owner and can have multiple members with different roles.
    """

    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)

    # Team ownership
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    owner = db.relationship(
        "User",
        foreign_keys=[owner_id],
        backref=db.backref("owned_teams", lazy="dynamic", cascade="all, delete-orphan"),
    )

    # Members relationship (through TeamMembership)
    memberships = db.relationship(
        "TeamMembership",
        back_populates="team",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # Projects shared with this team
    projects = db.relationship(
        "Project",
        back_populates="team",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Team {self.id} '{self.name}'>"

    def get_member_role(self, user_id: int):
        """
        Get the role of a user in this team.

        Args:
            user_id: ID of the user to check

        Returns:
            TeamRole if user is a member, None otherwise
        """
        if self.owner_id == user_id:
            return TeamRole.OWNER

        from sqlalchemy import select

        membership = db.session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == self.id, TeamMembership.user_id == user_id
            )
        ).scalar_one_or_none()

        return membership.role if membership else None

    def has_permission(self, user_id: int, required_role: TeamRole) -> bool:
        """
        Check if a user has at least the required permission level.

        Args:
            user_id: ID of the user to check
            required_role: Minimum required role

        Returns:
            True if user has sufficient permissions, False otherwise
        """
        role = self.get_member_role(user_id)
        if not role:
            return False

        # Role hierarchy: OWNER > ADMIN > EDITOR > VIEWER
        role_hierarchy = {
            TeamRole.OWNER: 4,
            TeamRole.ADMIN: 3,
            TeamRole.EDITOR: 2,
            TeamRole.VIEWER: 1,
        }

        return role_hierarchy.get(role, 0) >= role_hierarchy.get(required_role, 0)


class TeamMembership(db.Model):
    """
    Association model for team members.

    Tracks which users belong to which teams and their roles.
    """

    __tablename__ = "team_memberships"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    role = db.Column(
        db.Enum(
            TeamRole,
            name="teamrole",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=TeamRole.VIEWER,
    )

    # Timestamps
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    team = db.relationship("Team", back_populates="memberships")
    user = db.relationship(
        "User",
        backref=db.backref(
            "team_memberships", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    # Unique constraint: a user can only be in a team once
    __table_args__ = (
        db.UniqueConstraint("team_id", "user_id", name="unique_team_member"),
    )

    def __repr__(self) -> str:
        return f"<TeamMembership team={self.team_id} user={self.user_id} role={self.role.value}>"


class ActivityLog(db.Model):
    """
    Activity log for tracking team and project activities.

    Records important events like team member changes, project sharing,
    compilations, and other collaborative activities for audit trail
    and activity feeds.
    """

    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)

    # Activity metadata
    activity_type = db.Column(
        db.Enum(
            ActivityType,
            name="activitytype",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
    )

    # Relationships to entities
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)

    # Additional context (JSON for flexibility)
    # Examples:
    # - For MEMBER_ROLE_CHANGED: {"old_role": "viewer", "new_role": "editor", "target_user_id": 123}
    # - For COMPILATION_FAILED: {"error": "ffmpeg timeout"}
    # - For PROJECT_SHARED: {"team_name": "My Team"}
    context = db.Column(db.JSON, nullable=True)

    # Timestamp
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    # Relationships
    user = db.relationship("User", backref=db.backref("activities", lazy="dynamic"))
    team = db.relationship(
        "Team",
        backref=db.backref("activities", lazy="dynamic", cascade="all, delete-orphan"),
    )
    project = db.relationship(
        "Project",
        backref=db.backref("activities", lazy="dynamic", cascade="all, delete-orphan"),
    )

    # Indexes for efficient querying
    __table_args__ = (
        db.Index("idx_activity_team_created", "team_id", "created_at"),
        db.Index("idx_activity_project_created", "project_id", "created_at"),
        db.Index("idx_activity_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ActivityLog {self.activity_type.value} user={self.user_id} team={self.team_id} project={self.project_id}>"

    def to_dict(self) -> dict:
        """
        Convert activity log to dictionary for JSON serialization.

        Returns:
            dict: Activity log data including user info and context
        """
        return {
            "id": self.id,
            "activity_type": self.activity_type.value,
            "user_id": self.user_id,
            "user": {
                "id": self.user.id,
                "username": self.user.username,
            }
            if self.user
            else None,
            "team_id": self.team_id,
            "project_id": self.project_id,
            "context": self.context,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TeamInvitation(db.Model):
    """
    Team invitation model for inviting users to join teams.

    Allows team admins to send email invitations to users (existing or new).
    Invitations have unique tokens and can be accepted or declined.
    """

    __tablename__ = "team_invitations"

    id = db.Column(db.Integer, primary_key=True)

    # Invitation details
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)

    # Invited user (if they already have an account)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Role to assign when accepted
    role = db.Column(
        db.Enum(
            TeamRole,
            name="teamrole",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=TeamRole.VIEWER,
    )

    # Invitation token (unique)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Status
    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
    )  # pending, accepted, declined, expired

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)  # 7 days by default
    responded_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    team = db.relationship(
        "Team",
        backref=db.backref("invitations", lazy="dynamic", cascade="all, delete-orphan"),
    )
    invited_by = db.relationship("User", foreign_keys=[invited_by_id])
    user = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<TeamInvitation {self.email} → Team {self.team_id} ({self.status})>"

    def is_valid(self) -> bool:
        """Check if invitation is still valid (pending and not expired)."""
        return self.status == "pending" and self.expires_at > datetime.utcnow()

    def accept(self, user: "User") -> "TeamMembership":
        """
        Accept the invitation and create team membership.

        Args:
            user: User accepting the invitation

        Returns:
            TeamMembership: The created membership

        Raises:
            ValueError: If invitation is not valid
        """
        if not self.is_valid():
            raise ValueError("Invitation is not valid")

        # Create membership
        membership = TeamMembership(
            team_id=self.team_id, user_id=user.id, role=self.role
        )

        self.status = "accepted"
        self.responded_at = datetime.utcnow()
        self.user_id = user.id

        db.session.add(membership)
        db.session.commit()

        return membership

    def decline(self) -> None:
        """Decline the invitation."""
        if self.status != "pending":
            raise ValueError("Only pending invitations can be declined")

        self.status = "declined"
        self.responded_at = datetime.utcnow()
        db.session.commit()

    def to_dict(self) -> dict:
        """Convert invitation to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "team_id": self.team_id,
            "team": {
                "id": self.team.id,
                "name": self.team.name,
            }
            if self.team
            else None,
            "email": self.email,
            "role": self.role.value,
            "token": self.token,
            "status": self.status,
            "invited_by": {
                "id": self.invited_by.id,
                "username": self.invited_by.username,
            }
            if self.invited_by
            else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "responded_at": self.responded_at.isoformat()
            if self.responded_at
            else None,
        }


class Notification(db.Model):
    """
    Notification model for real-time user notifications.

    Notifications are triggered by team/project activities and
    allow users to stay informed about important events.
    """

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)

    # Recipient
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Notification type (reuses ActivityType enum)
    notification_type = db.Column(
        db.Enum(ActivityType, name="activitytype", create_type=False), nullable=False
    )

    # Context (what the notification is about)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)

    # Optional actor (who triggered the notification)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Message and metadata
    message = db.Column(db.Text, nullable=False)
    context = db.Column(
        db.JSON, nullable=True
    )  # Additional data (e.g., old_role, new_role)

    # Read status
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        backref=db.backref("notifications", lazy="dynamic"),
    )
    actor = db.relationship("User", foreign_keys=[actor_id])
    team = db.relationship("Team", backref=db.backref("notifications", lazy="dynamic"))
    project = db.relationship(
        "Project", backref=db.backref("notifications", lazy="dynamic")
    )

    # Indexes for efficient queries
    __table_args__ = (
        db.Index("ix_notifications_user_created", user_id, created_at.desc()),
        db.Index("ix_notifications_user_read", user_id, is_read),
    )

    def __repr__(self) -> str:
        return f"<Notification {self.id} {self.notification_type.value} for user {self.user_id}>"

    def mark_as_read(self):
        """Mark notification as read."""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()
            db.session.commit()

    def to_dict(self) -> dict:
        """Convert notification to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "type": self.notification_type.value,
            "message": self.message,
            "context": self.context,
            "is_read": self.is_read,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "actor": {
                "id": self.actor.id,
                "username": self.actor.username,
            }
            if self.actor
            else None,
            "team": {
                "id": self.team.id,
                "name": self.team.name,
            }
            if self.team
            else None,
            "project": {
                "id": self.project.id,
                "name": self.project.name,
            }
            if self.project
            else None,
        }


class NotificationPreferences(db.Model):
    """
    User preferences for notification delivery.

    Controls which events trigger in-app vs email notifications.
    """

    __tablename__ = "notification_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True
    )

    # Email notification preferences (per event type)
    email_compilation_complete = db.Column(db.Boolean, default=True, nullable=False)
    email_compilation_failed = db.Column(db.Boolean, default=True, nullable=False)
    email_team_invitation = db.Column(db.Boolean, default=True, nullable=False)
    email_team_member_added = db.Column(db.Boolean, default=True, nullable=False)
    email_project_shared = db.Column(db.Boolean, default=True, nullable=False)
    email_mention = db.Column(db.Boolean, default=True, nullable=False)

    # Email digest preferences
    email_digest_enabled = db.Column(db.Boolean, default=False, nullable=False)
    email_digest_frequency = db.Column(
        db.String(20), default="daily", nullable=False, doc="Frequency: daily|weekly"
    )
    email_digest_time = db.Column(
        db.String(5),
        default="09:00",
        nullable=False,
        doc="Time in HH:MM format (24-hour)",
    )

    # In-app notification preferences
    inapp_all_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationship
    user = db.relationship(
        "User", backref=db.backref("notification_preferences", uselist=False)
    )

    def __repr__(self) -> str:
        return f"<NotificationPreferences user_id={self.user_id}>"

    def to_dict(self) -> dict:
        """Convert preferences to dictionary."""
        return {
            "email_compilation_complete": self.email_compilation_complete,
            "email_compilation_failed": self.email_compilation_failed,
            "email_team_invitation": self.email_team_invitation,
            "email_team_member_added": self.email_team_member_added,
            "email_project_shared": self.email_project_shared,
            "email_mention": self.email_mention,
            "email_digest_enabled": self.email_digest_enabled,
            "email_digest_frequency": self.email_digest_frequency,
            "email_digest_time": self.email_digest_time,
            "inapp_all_enabled": self.inapp_all_enabled,
        }

    @staticmethod
    def get_or_create(user_id: int) -> "NotificationPreferences":
        """Get or create preferences for a user."""
        prefs = (
            db.session.query(NotificationPreferences).filter_by(user_id=user_id).first()
        )
        if not prefs:
            prefs = NotificationPreferences(user_id=user_id)
            db.session.add(prefs)
            db.session.commit()
        return prefs
