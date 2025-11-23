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
    MAX_CONTENT_LENGTH = int(
        os.environ.get("MAX_CONTENT_LENGTH", 500 * 1024 * 1024)
    )  # Default 500MB
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or "uploads"
    ALLOWED_VIDEO_EXTENSIONS = {
        "mp4",
        "avi",
        "mov",
        "mkv",
        "webm",
        "flv",
        "wmv",
        "mpg",
        "mpeg",
        "m4v",
        "3gp",
        "3g2",
        "f4v",
        "ts",
        "mts",
        "m2ts",
        "vob",
        "ogv",
        "divx",
        "xvid",
    }
    ALLOWED_IMAGE_EXTENSIONS = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "bmp",
        "tiff",
        "tif",
        "svg",
    }
    ALLOWED_AUDIO_EXTENSIONS = {
        "mp3",
        "wav",
        "ogg",
        "m4a",
        "flac",
        "aac",
        "wma",
        "opus",
        "oga",
        "webm",
        "ac3",
        "dts",
        "ape",
        "alac",
        "amr",
        "aiff",
        "au",
        "mp2",
        "mka",
    }
    # Thumbnails
    THUMBNAIL_TIMESTAMP_SECONDS = int(os.environ.get("THUMBNAIL_TIMESTAMP_SECONDS", 3))
    THUMBNAIL_WIDTH = int(os.environ.get("THUMBNAIL_WIDTH", 480))

    # External API Configuration
    DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
    DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID")
    TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID")
    TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET")

    # Worker API Configuration
    # Shared secret for workers to authenticate with the Flask app
    WORKER_API_KEY = os.environ.get("WORKER_API_KEY", "")
    FLASK_APP_URL = os.environ.get("FLASK_APP_URL", "http://localhost:5000")

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
    # Restrict external clip sources to Twitch/Discord URLs only when disabled
    ALLOW_EXTERNAL_URLS = os.environ.get("ALLOW_EXTERNAL_URLS", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # Queue selection: use a dedicated 'gpu' Celery queue for compile tasks when enabled
    USE_GPU_QUEUE = os.environ.get("USE_GPU_QUEUE", "false").lower() in {
        "1",
        "true",
        "yes",
    }

    # Worker media over HTTP
    # Base URL used by workers (or any process without a request context) to build
    # absolute raw media URLs. Example: https://clippy.example.com
    MEDIA_BASE_URL = os.environ.get("MEDIA_BASE_URL")

    # Ingest importer (server-side) configuration
    INGEST_IMPORT_ENABLED = os.environ.get(
        "INGEST_IMPORT_ENABLED", "false"
    ).lower() in {"1", "true", "yes", "on"}
    INGEST_ROOT = os.environ.get("INGEST_ROOT", "/srv/ingest")
    # Comma-separated list of worker IDs to scan (empty => all subdirs under INGEST_ROOT)
    INGEST_IMPORT_WORKER_IDS = os.environ.get("INGEST_IMPORT_WORKER_IDS", "")
    # Default owner/project for imported files if no smarter mapping is provided
    INGEST_IMPORT_USERNAME = os.environ.get("INGEST_IMPORT_USERNAME")
    INGEST_IMPORT_PROJECT = os.environ.get("INGEST_IMPORT_PROJECT")
    INGEST_IMPORT_CREATE_PROJECT = os.environ.get(
        "INGEST_IMPORT_CREATE_PROJECT", "true"
    ).lower() in {"1", "true", "yes", "on"}
    INGEST_IMPORT_PATTERN = os.environ.get("INGEST_IMPORT_PATTERN", "*.mp4")
    INGEST_IMPORT_ACTION = os.environ.get("INGEST_IMPORT_ACTION", "copy")
    INGEST_IMPORT_STABLE_SECONDS = int(
        os.environ.get("INGEST_IMPORT_STABLE_SECONDS", 60)
    )
    # Celery Beat schedule (seconds) for periodic scans
    INGEST_IMPORT_INTERVAL_SECONDS = int(
        os.environ.get("INGEST_IMPORT_INTERVAL_SECONDS", 60)
    )

    # Auto-ingest compilations scanner (server-side Beat task)
    AUTO_INGEST_COMPILATIONS_ENABLED = os.environ.get(
        "AUTO_INGEST_COMPILATIONS_ENABLED", "false"
    ).lower() in {"1", "true", "yes", "on"}
    AUTO_INGEST_WORKER_IDS = os.environ.get("AUTO_INGEST_WORKER_IDS", "")
    AUTO_INGEST_COMPILATIONS_INTERVAL_SECONDS = int(
        os.environ.get("AUTO_INGEST_COMPILATIONS_INTERVAL_SECONDS", 60)
    )

    # Cleanup imported artifacts (server-side Beat task)
    CLEANUP_IMPORTED_ENABLED = os.environ.get(
        "CLEANUP_IMPORTED_ENABLED", "false"
    ).lower() in {"1", "true", "yes", "on"}
    CLEANUP_IMPORTED_AGE_HOURS = int(os.environ.get("CLEANUP_IMPORTED_AGE_HOURS", 24))
    CLEANUP_IMPORTED_WORKER_IDS = os.environ.get("CLEANUP_IMPORTED_WORKER_IDS", "")
    CLEANUP_IMPORTED_INTERVAL_SECONDS = int(
        os.environ.get("CLEANUP_IMPORTED_INTERVAL_SECONDS", 3600)
    )

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

    # Email / SMTP configuration (verification emails, notifications)
    EMAIL_VERIFICATION_ENABLED = os.environ.get(
        "EMAIL_VERIFICATION_ENABLED", "false"
    ).lower() in {"1", "true", "yes", "on"}
    EMAIL_FROM_ADDRESS = os.environ.get("EMAIL_FROM_ADDRESS", "no-reply@example.com")
    SMTP_HOST = os.environ.get("SMTP_HOST")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")  # Only from environment/.env


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
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")

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
