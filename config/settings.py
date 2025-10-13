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

    # Database Configuration
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL") or "sqlite:///clippy_front.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
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

    # External API Configuration
    DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
    TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID")
    TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET")

    # Rate Limiting Configuration
    RATELIMIT_STORAGE_URL = REDIS_URL
    RATELIMIT_DEFAULT = "100 per hour"

    # Video Processing Configuration
    FFMPEG_BINARY = os.environ.get("FFMPEG_BINARY") or "ffmpeg"
    OUTPUT_VIDEO_QUALITY = os.environ.get("OUTPUT_VIDEO_QUALITY") or "high"

    # Security Headers (Talisman)
    FORCE_HTTPS = False  # Set to True in production
    STRICT_TRANSPORT_SECURITY = True
    CONTENT_SECURITY_POLICY = {
        "default-src": "'self'",
        "script-src": "'self' 'unsafe-inline' cdn.jsdelivr.net",
        "style-src": "'self' 'unsafe-inline' cdn.jsdelivr.net",
        "img-src": "'self' data: https:",
        "font-src": "'self' cdn.jsdelivr.net",
    }


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

    # Development database (SQLite)
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DEV_DATABASE_URL") or "sqlite:///clippy_front_dev.db"
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

    # In-memory database for testing
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    # Disable rate limiting for tests
    RATELIMIT_ENABLED = False
