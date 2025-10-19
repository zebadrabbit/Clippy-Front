"""
Flask application factory and configuration.

This module contains the Flask application factory that initializes
and configures all extensions, blueprints, and application settings.
"""
import os
import shutil

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

    # If running under pytest, force test-friendly overrides BEFORE initializing extensions
    try:
        import os as _os

        if _os.environ.get("PYTEST_CURRENT_TEST"):
            app.config.update(
                {
                    "TESTING": True,
                    "WTF_CSRF_ENABLED": False,
                    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                    "SQLALCHEMY_TRACK_MODIFICATIONS": False,
                    "RATELIMIT_ENABLED": False,
                    "FORCE_HTTPS": False,
                }
            )
    except Exception:
        pass

    # Database engine enforcement and optional SQLite path normalization for tests only
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    # Enforce PostgreSQL outside tests: SQLite is reserved for tests only
    if (
        isinstance(db_uri, str)
        and not app.config.get("TESTING")
        and db_uri.startswith("sqlite:")
    ):
        raise RuntimeError(
            "SQLite is only supported in TESTING. Set DATABASE_URL/DEV_DATABASE_URL to PostgreSQL."
        )
    # In tests, normalize relative sqlite paths to absolute under instance/ to avoid stray files
    if app.config.get("TESTING"):
        try:
            if (
                isinstance(db_uri, str)
                and db_uri.startswith("sqlite:///")
                and not db_uri.startswith("sqlite:////")
            ):
                # Extract the relative path after the scheme (three slashes)
                rel_path = db_uri[len("sqlite:///") :]
                # Skip special in-memory DB
                if rel_path.strip() == ":memory:":
                    raise RuntimeError("skip-normalize")
                # Guard: ensure we're dealing with a relative filesystem path
                if rel_path and not rel_path.startswith("/"):
                    abs_path = os.path.join(app.instance_path, rel_path)
                    abs_dir = os.path.dirname(abs_path)
                    os.makedirs(abs_dir, exist_ok=True)

                    # If the new absolute path doesn't exist yet, attempt to migrate
                    # an existing DB from common legacy locations to avoid data loss.
                    if not os.path.exists(abs_path):
                        legacy_candidates = []
                        # 1) Working directory
                        legacy_candidates.append(os.path.join(os.getcwd(), rel_path))
                        # 2) Repository root (parent of app.root_path)
                        repo_root = os.path.abspath(
                            os.path.join(app.root_path, os.pardir)
                        )
                        legacy_candidates.append(os.path.join(repo_root, rel_path))
                        # 3) Application root (app.root_path)
                        legacy_candidates.append(os.path.join(app.root_path, rel_path))
                        for legacy in legacy_candidates:
                            try:
                                if os.path.exists(legacy) and os.path.isfile(legacy):
                                    shutil.copy2(legacy, abs_path)
                                    app.logger.info(
                                        "Migrated existing SQLite DB from '%s' to '%s'",
                                        legacy,
                                        abs_path,
                                    )
                                    break
                            except Exception as e:
                                app.logger.warning(
                                    "Failed to migrate legacy DB from '%s': %s",
                                    legacy,
                                    e,
                                )

                    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{abs_path}"
        except Exception:
            # If any issue occurs, keep the original URI; better to proceed than fail startup
            pass

    # Log the resolved DB target in a safe way (avoid leaking credentials)
    try:
        ruri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if isinstance(ruri, str):
            if ruri.startswith("sqlite///"):
                app.logger.info("Database: %s", ruri)
            else:
                # Try to extract host/port/db without secrets for better diagnostics
                try:
                    from sqlalchemy.engine.url import make_url as _make_url

                    u = _make_url(ruri)
                    host = u.host or ""
                    port = f":{u.port}" if u.port else ""
                    dbn = u.database or ""
                    app.logger.info(
                        "Database: %s://%s%s/%s (redacted user/pass)",
                        u.drivername,
                        host or "<no-host>",
                        port,
                        dbn,
                    )
                    if host in {"localhost", "127.0.0.1", "::1", ""}:
                        app.logger.warning(
                            "Database host looks like localhost. If this process runs in Docker, set DATABASE_URL to a reachable host/IP."
                        )
                except Exception:
                    # Fallback: redact to scheme only
                    scheme = ruri.split(":", 1)[0] if ":" in ruri else "db"
                    app.logger.info("Database: %s://… (redacted)", scheme)
    except Exception:
        pass

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

    # Optionally auto-reindex media from disk when DB is empty (dev-friendly)
    try:
        # Default: do NOT auto-reindex on startup. Can be enabled via AUTO_REINDEX_ON_STARTUP=1.
        auto_reindex = app.config.get("AUTO_REINDEX_ON_STARTUP", False)
        if auto_reindex and not app.config.get("TESTING"):
            from app.models import MediaFile

            with app.app_context():
                # Only if MediaFile table is empty
                empty = MediaFile.query.limit(1).count() == 0
                if empty:
                    base_upload = os.path.join(
                        app.instance_path, app.config["UPLOAD_FOLDER"]
                    )
                    downloads_dir = os.path.join(app.instance_path, "downloads")
                    compilations_dir = os.path.join(app.instance_path, "compilations")

                    def _has_files(path: str) -> bool:
                        try:
                            if not os.path.isdir(path):
                                return False
                            for root, _dirs, files in os.walk(path):
                                # Skip thumbnails directory
                                if os.path.basename(root).lower() == "thumbnails":
                                    continue
                                if files:
                                    return True
                            return False
                        except Exception:
                            return False

                    if any(
                        _has_files(p)
                        for p in (base_upload, downloads_dir, compilations_dir)
                    ):
                        try:
                            # Ensure repo root on sys.path to import scripts module
                            import sys as _sys

                            repo_root = os.path.abspath(
                                os.path.join(app.root_path, os.pardir)
                            )
                            if repo_root not in _sys.path:
                                _sys.path.insert(0, repo_root)
                            from scripts.reindex_media import reindex as _reindex

                            created = int(_reindex(regen_thumbs=False, app=app) or 0)
                            app.logger.info(
                                "Auto-reindex completed: %d file(s) added", created
                            )
                        except Exception as e:
                            app.logger.warning(f"Auto-reindex skipped/failed: {e}")
    except Exception:
        # Non-fatal
        pass

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

    # Database migrations available in all environments
    Migrate(app, db)

    # Ensure minimal runtime schema updates (safe additive changes)
    # Only run these in non-testing environments to avoid touching the engine during pytest.
    if not app.config.get("TESTING"):
        try:
            with app.app_context():
                # Flask-SQLAlchemy 3.x: use db.engine instead of deprecated get_engine()
                engine = db.engine
                insp = sa_inspect(engine)
                # Collect existing columns once
                mf_cols = {c["name"] for c in insp.get_columns("media_files")}
                clip_cols = {c["name"] for c in insp.get_columns("clips")}
                proj_cols = {c["name"] for c in insp.get_columns("projects")}
                try:
                    user_cols = {c["name"] for c in insp.get_columns("users")}
                except Exception:
                    user_cols = set()

                statements = []
                # media_files: add tags if missing
                if "tags" not in mf_cols:
                    statements.append(
                        text("ALTER TABLE media_files ADD COLUMN tags TEXT")
                    )
                # media_files: add checksum and description if missing
                if "checksum" not in mf_cols:
                    statements.append(
                        text("ALTER TABLE media_files ADD COLUMN checksum VARCHAR(64)")
                    )
                if "description" not in mf_cols:
                    statements.append(
                        text("ALTER TABLE media_files ADD COLUMN description TEXT")
                    )
                # clips: add metadata columns if missing
                if "creator_name" not in clip_cols:
                    statements.append(
                        text("ALTER TABLE clips ADD COLUMN creator_name VARCHAR(120)")
                    )
                if "creator_id" not in clip_cols:
                    statements.append(
                        text("ALTER TABLE clips ADD COLUMN creator_id VARCHAR(64)")
                    )
                if "creator_avatar_path" not in clip_cols:
                    statements.append(
                        text(
                            "ALTER TABLE clips ADD COLUMN creator_avatar_path VARCHAR(500)"
                        )
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
                # Backfill public_id for projects: add column if missing, then populate empties
                proj_statements = []
                if "public_id" not in proj_cols:
                    proj_statements.append(
                        text("ALTER TABLE projects ADD COLUMN public_id VARCHAR(32)")
                    )
                    proj_statements.append(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_public_id ON projects(public_id)"
                        )
                    )
                if proj_statements:
                    with engine.begin() as conn:
                        for stmt in proj_statements:
                            conn.execute(stmt)
                    app.logger.info(
                        "Applied projects table runtime updates: %s",
                        ", ".join(s.text for s in proj_statements),
                    )

                # Populate any missing/empty public_id values
                try:
                    from app.models import Project  # local import

                    with app.app_context():
                        rows = (
                            db.session.query(Project)
                            .filter(
                                (Project.public_id.is_(None))
                                | (Project.public_id == "")
                            )
                            .all()
                        )
                        if rows:
                            import secrets as _secrets

                            for p in rows:
                                p.public_id = _secrets.token_urlsafe(12)
                            db.session.commit()
                except Exception as _e:
                    app.logger.warning(
                        f"Project public_id backfill skipped/failed: {_e}"
                    )
                # Separate transaction to add user external-connection columns if missing
                user_statements = []
                if "twitch_username" not in user_cols:
                    user_statements.append(
                        text(
                            "ALTER TABLE users ADD COLUMN twitch_username VARCHAR(100)"
                        )
                    )
                if "discord_user_id" not in user_cols:
                    user_statements.append(
                        text(
                            "ALTER TABLE users ADD COLUMN discord_user_id VARCHAR(100)"
                        )
                    )
                if "date_format" not in user_cols:
                    # Add user preference for date formatting with default 'auto'
                    user_statements.append(
                        text(
                            "ALTER TABLE users ADD COLUMN date_format VARCHAR(32) DEFAULT 'auto'"
                        )
                    )
                if user_statements:
                    with engine.begin() as conn:
                        for stmt in user_statements:
                            conn.execute(stmt)
                    app.logger.info(
                        "Applied users table runtime updates: %s",
                        ", ".join(s.text for s in user_statements),
                    )
        except Exception as e:
            # Log and proceed; migrations should handle in production
            app.logger.warning(f"Schema check/upgrade skipped or failed: {e}")

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

        # Avoid deprecated Query.get; use Session.get
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None


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
