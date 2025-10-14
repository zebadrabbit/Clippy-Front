"""
Flask application factory and configuration.

This module contains the Flask application factory that initializes
and configures all extensions, blueprints, and application settings.
"""
import os

from flask import Flask, render_template
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from config.settings import Config, DevelopmentConfig, ProductionConfig, TestingConfig

# Optional typing-friendly import for SQLAlchemy Query detection in filters
try:
    from sqlalchemy.orm import Query as SAQuery  # type: ignore
except Exception:  # pragma: no cover - fallback if SQLAlchemy import shape differs
    SAQuery = None  # type: ignore


# Make CSRFProtect available app-wide so routes can optionally exempt endpoints
csrf = CSRFProtect()


def create_app(config_class=None):
    """
    Create and configure Flask application.

    This factory function creates a Flask application instance and configures
    all necessary extensions, blueprints, and security measures.

    Args:
        config_class: Configuration class to use. If None, will be determined
                     from FLASK_ENV environment variable.

    Returns:
        Flask: Configured Flask application instance
    """
    app = Flask(__name__)

    # Determine configuration class if not provided
    if config_class is None:
        env = os.environ.get("FLASK_ENV", "development")
        if env == "production":
            config_class = ProductionConfig
        elif env == "testing":
            config_class = TestingConfig
        else:
            config_class = DevelopmentConfig

    app.config.from_object(config_class)

    # Create upload directory if it doesn't exist
    upload_dir = os.path.join(app.instance_path, app.config["UPLOAD_FOLDER"])
    os.makedirs(upload_dir, exist_ok=True)

    # Initialize extensions
    init_extensions(app)

    # Register blueprints
    register_blueprints(app)

    # In development, relax CSRF on auth endpoints to avoid 400s during setup
    if app.debug:
        # Exempt the entire auth blueprint from CSRF checks in development only
        auth_blueprint = app.blueprints.get("auth")
        if auth_blueprint is not None:
            csrf.exempt(auth_blueprint)

    # Register error handlers
    register_error_handlers(app)

    # Register Jinja filters
    register_template_filters(app)

    # Setup security headers (only in production or if explicitly enabled)
    if app.config.get("FORCE_HTTPS") or not app.debug:
        Talisman(
            app,
            force_https=app.config.get("FORCE_HTTPS", False),
            strict_transport_security=app.config.get("STRICT_TRANSPORT_SECURITY", True),
            content_security_policy=app.config.get("CONTENT_SECURITY_POLICY"),
        )

    return app


def init_extensions(app):
    """
    Initialize Flask extensions.

    Args:
        app: Flask application instance
    """
    # Database
    from app.models import db

    db.init_app(app)

    # Ensure minimal runtime schema updates (safe additive changes)
    try:
        with app.app_context():
            engine = db.get_engine()
            insp = sa_inspect(engine)
            # Collect existing columns once
            mf_cols = {c["name"] for c in insp.get_columns("media_files")}
            clip_cols = {c["name"] for c in insp.get_columns("clips")}

            statements = []
            # media_files: add tags if missing
            if "tags" not in mf_cols:
                statements.append(text("ALTER TABLE media_files ADD COLUMN tags TEXT"))
            # clips: add metadata columns if missing
            if "creator_name" not in clip_cols:
                statements.append(
                    text("ALTER TABLE clips ADD COLUMN creator_name VARCHAR(120)")
                )
            if "game_name" not in clip_cols:
                statements.append(
                    text("ALTER TABLE clips ADD COLUMN game_name VARCHAR(120)")
                )
            if "clip_created_at" not in clip_cols:
                # Use DATETIME which is friendlier across backends (SQLite stores as TEXT)
                statements.append(
                    text("ALTER TABLE clips ADD COLUMN clip_created_at DATETIME")
                )

            if statements:
                # Execute in a single transaction; SQLAlchemy 2.x style
                with engine.begin() as conn:
                    for stmt in statements:
                        conn.execute(stmt)
                # Optionally re-inspect or log success
                app.logger.info(
                    "Applied runtime schema updates: %s",
                    ", ".join(s.text for s in statements),
                )
    except Exception as e:
        # Log and proceed; migrations should handle in production
        app.logger.warning(f"Schema check/upgrade skipped or failed: {e}")

    # Database migrations
    Migrate(app, db)

    # CORS for API access
    CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000"])

    # CSRF Protection
    csrf.init_app(app)

    # Rate limiting (can be disabled via RATELIMIT_ENABLED=False)
    if app.config.get("RATELIMIT_ENABLED", True):
        limiter = Limiter(
            key_func=get_remote_address,
            default_limits=[app.config.get("RATELIMIT_DEFAULT", "100 per hour")],
            storage_uri=app.config.get("RATELIMIT_STORAGE_URL"),
        )
        limiter.init_app(app)

    # User session management
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        """Load user by ID for Flask-Login."""
        from app.models import User

        return User.query.get(int(user_id))


def register_blueprints(app):
    """
    Register Flask blueprints.

    Args:
        app: Flask application instance
    """
    # API routes
    from app.api.routes import api_bp

    app.register_blueprint(api_bp, url_prefix="/api")

    # Authentication routes
    from app.auth.routes import auth_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")

    # Main web interface routes
    from app.main.routes import main_bp

    app.register_blueprint(main_bp)

    # Admin interface routes
    from app.admin.routes import admin_bp

    app.register_blueprint(admin_bp, url_prefix="/admin")


def register_template_filters(app: Flask) -> None:
    """
    Register custom Jinja template filters.

    Args:
        app: Flask application instance
    """

    def safe_count(value) -> int:
        """Safely count SQLAlchemy queries or Python collections.

        - If value is an SQLAlchemy Query (including dynamic relationship queries),
          call Query.count() to perform a DB-side count.
        - Otherwise, fall back to len(value) for normal Python collections.

        Returns 0 if the value cannot be counted.
        """
        # SQLAlchemy Query detection first to avoid list.count(arg) confusion
        try:
            if SAQuery is not None and isinstance(value, SAQuery):
                return int(value.count())
        except Exception:
            # If detection fails, fall through to safer attempts
            pass

        # Attempt to call .count() (may raise TypeError on lists)
        try:
            result = value.count()  # type: ignore[attr-defined]
            # Guard against list.count(arg) signature misuse by ensuring int-like return
            return int(result)
        except TypeError:
            # Likely a Python list/collection where .count requires an argument
            try:
                return len(value)  # type: ignore[arg-type]
            except Exception:
                return 0
        except Exception:
            # Fallback to len
            try:
                return len(value)  # type: ignore[arg-type]
            except Exception:
                return 0

    app.jinja_env.filters["safe_count"] = safe_count


def register_error_handlers(app):
    """
    Register error handlers for common HTTP errors.

    Args:
        app: Flask application instance
    """

    @app.errorhandler(400)
    def bad_request(error):
        """Handle 400 Bad Request errors."""
        return render_template("errors/400.html"), 400

    @app.errorhandler(401)
    def unauthorized(error):
        """Handle 401 Unauthorized errors."""
        return render_template("errors/401.html"), 401

    @app.errorhandler(403)
    def forbidden(error):
        """Handle 403 Forbidden errors."""
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 Not Found errors."""
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle 413 Request Entity Too Large errors."""
        return render_template("errors/413.html"), 413

    @app.errorhandler(429)
    def ratelimit_handler(error):
        """Handle 429 Too Many Requests errors."""
        return render_template("errors/429.html"), 429

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 Internal Server Error."""
        return render_template("errors/500.html"), 500
