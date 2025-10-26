"""
Configuration settings for the Flask application.
This module contains all configuration classes for different environments.
"""
import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    """
    Base configuration class containing common settings.

    This class defines the default configuration that other
    environment-specific classes will inherit from.
    """

    # Security Configuration
    SECRET_KEY = (
        os.environ.get("SECRET_KEY") or "your-super-secret-key-change-in-production"
    )
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour
    WTF_CSRF_SSL_STRICT = False  # Allow CSRF tokens over HTTP in development

    # Database Configuration: default to PostgreSQL; SQLite is reserved for tests only
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or "postgresql://postgres:postgres@localhost/clippy_front"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SQLAlchemy engine pool settings (tunable via env for different processes)
    # Defaults are conservative to avoid exhausting Postgres connections when
    # multiple worker processes are running.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", 300)),
        "pool_size": int(os.environ.get("DB_POOL_SIZE", 5)),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", 10)),
        # Optional: how long to wait for a connection from the pool
        **(
            {"pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", 30))}
            if os.environ.get("DB_POOL_TIMEOUT")
            else {}
        ),
    }

    # Redis/Celery Configuration
    REDIS_URL = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or REDIS_URL
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL

    # Flask Configuration
    DEBUG = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
    PORT = int(os.environ.get("FLASK_PORT", 5000))

    # Session Configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # File Upload Configuration
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max file size
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or "uploads"
    ALLOWED_VIDEO_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm"}
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    # Thumbnails
    THUMBNAIL_TIMESTAMP_SECONDS = int(os.environ.get("THUMBNAIL_TIMESTAMP_SECONDS", 1))
    THUMBNAIL_WIDTH = int(os.environ.get("THUMBNAIL_WIDTH", 480))

    # External API Configuration
    DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
    DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID")
    TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID")
    TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET")
    # Optional avatars path for overlay feature (defaults resolved at runtime if not set)
    AVATARS_PATH = os.environ.get("AVATARS_PATH")

    # Rate Limiting Configuration
    RATELIMIT_STORAGE_URL = REDIS_URL
    RATELIMIT_DEFAULT = "100 per hour"

    # Video Processing Configuration
    FFMPEG_BINARY = os.environ.get("FFMPEG_BINARY") or "ffmpeg"
    FFPROBE_BINARY = os.environ.get("FFPROBE_BINARY") or "ffprobe"
    YT_DLP_BINARY = os.environ.get("YT_DLP_BINARY") or "yt-dlp"
    # Optional CLI args for fine-tuning tool behavior
    FFMPEG_GLOBAL_ARGS = os.environ.get("FFMPEG_GLOBAL_ARGS", "")
    FFMPEG_ENCODE_ARGS = os.environ.get("FFMPEG_ENCODE_ARGS", "")
    FFMPEG_THUMBNAIL_ARGS = os.environ.get("FFMPEG_THUMBNAIL_ARGS", "")
    FFMPEG_CONCAT_ARGS = os.environ.get("FFMPEG_CONCAT_ARGS", "")
    FFPROBE_ARGS = os.environ.get("FFPROBE_ARGS", "")
    YT_DLP_ARGS = os.environ.get("YT_DLP_ARGS", "")
    OUTPUT_VIDEO_QUALITY = os.environ.get("OUTPUT_VIDEO_QUALITY") or "high"
    # Queue selection: use a dedicated 'gpu' Celery queue for compile tasks when enabled
    USE_GPU_QUEUE = os.environ.get("USE_GPU_QUEUE", "false").lower() in {
        "1",
        "true",
        "yes",
    }

    # Automation scheduler (Celery Beat) optional enable
    SCHEDULER_ENABLE_TICK = os.environ.get(
        "SCHEDULER_ENABLE_TICK", "false"
    ).lower() in {
        "1",
        "true",
        "yes",
    }
    SCHEDULER_TICK_SECONDS = int(os.environ.get("SCHEDULER_TICK_SECONDS", 60))

    # Security Headers (Talisman)
    FORCE_HTTPS = False  # Set to True in production
    STRICT_TRANSPORT_SECURITY = True
    CONTENT_SECURITY_POLICY = {
        "default-src": "'self'",
        "script-src": "'self' 'unsafe-inline' cdn.jsdelivr.net vjs.zencdn.net",
        "style-src": "'self' 'unsafe-inline' cdn.jsdelivr.net vjs.zencdn.net",
        "img-src": "'self' data: https:",
        "font-src": "'self' cdn.jsdelivr.net vjs.zencdn.net",
        "media-src": "'self' https:",
    }

    # Pagination defaults
    PROJECTS_PER_PAGE = int(os.environ.get("PROJECTS_PER_PAGE", 20))
    MEDIA_PER_PAGE = int(os.environ.get("MEDIA_PER_PAGE", 20))
    ADMIN_USERS_PER_PAGE = int(os.environ.get("ADMIN_USERS_PER_PAGE", 25))
    ADMIN_PROJECTS_PER_PAGE = int(os.environ.get("ADMIN_PROJECTS_PER_PAGE", 25))

    # Defaults for new Projects
    DEFAULT_OUTPUT_RESOLUTION = os.environ.get("DEFAULT_OUTPUT_RESOLUTION", "1080p")
    DEFAULT_OUTPUT_FORMAT = os.environ.get("DEFAULT_OUTPUT_FORMAT", "mp4")
    DEFAULT_MAX_CLIP_DURATION = int(os.environ.get("DEFAULT_MAX_CLIP_DURATION", 30))

    # Global watermark defaults (can be overridden via System Settings)
    WATERMARK_PATH = os.environ.get("WATERMARK_PATH")  # path set via Admin UI upload
    WATERMARK_OPACITY = float(os.environ.get("WATERMARK_OPACITY", 0.3))
    WATERMARK_POSITION = os.environ.get("WATERMARK_POSITION", "bottom-right")


class DevelopmentConfig(Config):
    """
    Development environment configuration.

    This configuration is used during local development and testing.
    It includes debug mode and relaxed security settings.
    """

    DEBUG = True
    # Use form-level CSRF checks only in development to avoid global 400s
    WTF_CSRF_CHECK_DEFAULT = False
    SESSION_COOKIE_SECURE = False  # Allow HTTP in development
    FORCE_HTTPS = False
    # Disable rate limiting in development to avoid 429s during asset bursts
    RATELIMIT_ENABLED = False

    # Automatically reindex media on startup if the DB is empty (dev-only safety net)
    AUTO_REINDEX_ON_STARTUP = True

    # Development database precedence: DATABASE_URL (if set) > DEV_DATABASE_URL > default Postgres
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("DEV_DATABASE_URL")
        or "postgresql://postgres:postgres@localhost/clippy_front"
    )


class ProductionConfig(Config):
    """
    Production environment configuration.

    This configuration is used in production with enhanced security
    and performance optimizations.
    """

    DEBUG = False

    # Production database (PostgreSQL recommended)
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or "postgresql://user:password@localhost/clippy_front"
    )

    # Enhanced security for production
    FORCE_HTTPS = True
    SESSION_COOKIE_SECURE = True

    # Stricter rate limiting
    RATELIMIT_DEFAULT = "50 per hour"


class TestingConfig(Config):
    """
    Testing environment configuration.

    This configuration is used during automated testing.
    It uses in-memory databases and disabled security features.
    """

    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False  # Disable CSRF for testing

    # In-memory database for testing (only place SQLite is used)
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    # Override engine options for SQLite in-memory tests.
    # The default pool options (pool_size, max_overflow, etc.) are invalid with
    # SQLite's StaticPool used for in-memory DBs and cause create_engine errors.
    SQLALCHEMY_ENGINE_OPTIONS = {}

    # Disable rate limiting for tests
    RATELIMIT_ENABLED = False
