"""
Flask application factory and configuration.

This module contains the Flask application factory that initializes
and configures all extensions, blueprints, and application settings.
"""
import os
import shutil
import time

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

# Module-level guards to avoid repeated noisy logs and schema checks per process
_DB_URI_LOGGED = False
_RUNTIME_SCHEMA_CHECKED = False

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
    # Prefer a shared, host-mounted instance directory when configured
    # or when a well-known mount exists (e.g., /mnt/clippyfront). Avoid this
    # auto-detection during pytest to keep tests hermetic.
    _is_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    preferred_instance = os.environ.get("CLIPPY_INSTANCE_PATH")

    if preferred_instance:
        # Ensure the directory exists before constructing the app
        try:
            os.makedirs(preferred_instance, exist_ok=True)
        except Exception:
            pass
        app = Flask(__name__, instance_path=preferred_instance)
    else:
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

    # Configure structured logging early (no-op during tests)
    try:
        from app.structured_logging import configure_structlog

        configure_structlog(app, role="web")
    except Exception:
        # Never fail startup due to logging setup
        pass

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
                    # Critical for SQLite in-memory: strip pool options that are invalid
                    # with SQLite's StaticPool to avoid create_engine TypeErrors.
                    "SQLALCHEMY_ENGINE_OPTIONS": {},
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

    # Determine whether we're in the effective reloader child (to avoid duplicate parent logs)
    _is_main_reloader = (not app.debug) or os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    # Log the resolved DB target in a safe way (avoid leaking credentials)
    try:
        global _DB_URI_LOGGED
        if not _DB_URI_LOGGED and _is_main_reloader:
            ruri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
            if isinstance(ruri, str):
                if ruri.startswith("sqlite///"):
                    app.logger.debug("Database: %s", ruri)
                else:
                    # Try to extract host/port/db without secrets for better diagnostics
                    try:
                        from sqlalchemy.engine.url import make_url as _make_url

                        u = _make_url(ruri)
                        host = u.host or ""
                        port = f":{u.port}" if u.port else ""
                        dbn = u.database or ""
                        app.logger.debug(
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
                        app.logger.debug("Database: %s://… (redacted)", scheme)
            _DB_URI_LOGGED = True
    except Exception:
        pass

    # Optionally require that the instance mount exists and is writable.
    # Set REQUIRE_INSTANCE_MOUNT=1 to turn this on (recommended for workers).
    try:
        if str(os.environ.get("REQUIRE_INSTANCE_MOUNT", "")).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            # Ensure instance directory exists
            if not os.path.isdir(app.instance_path):
                try:
                    os.makedirs(app.instance_path, exist_ok=True)
                    app.logger.info(f"Created instance directory: {app.instance_path}")
                except Exception as e:
                    raise RuntimeError(
                        f"Cannot create instance directory {app.instance_path}: {e}"
                    ) from e
            # Basic writability check: create instance/tmp if needed
            probe_dir = os.path.join(app.instance_path, "tmp")
            os.makedirs(probe_dir, exist_ok=True)
    except Exception:
        raise

    # Ensure project-based data root exists
    try:
        from app import storage as storage_lib

        os.makedirs(storage_lib.data_root(), exist_ok=True)
    except Exception:
        pass

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

    # Optional startup sanity check: avatar directory presence when overlays are enabled
    try:
        from app.ffmpeg_config import overlay_enabled as _overlay_enabled

        if not app.config.get("TESTING") and _overlay_enabled():
            # Determine base and avatars dir similar to runtime resolution in tasks
            base_root = os.environ.get("AVATARS_PATH") or os.path.join(
                app.instance_path, "assets"
            )
            avatars_dir = base_root
            try:
                tail = os.path.basename(str(avatars_dir).rstrip("/"))
                if tail.lower() != "avatars":
                    avatars_dir = os.path.join(avatars_dir, "avatars")
            except Exception:
                avatars_dir = os.path.join(base_root, "avatars")

            # Check existence and at least one image file
            exists = os.path.isdir(avatars_dir)
            has_images = False
            try:
                if exists:
                    import glob as _glob

                    matches = []
                    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                        matches.extend(_glob.glob(os.path.join(avatars_dir, ext)))
                    has_images = len(matches) > 0
            except Exception:
                has_images = False

            if not exists or not has_images:
                app.logger.warning(
                    "Overlay is enabled but no avatars directory or images were found."
                    " Checked base_root='%s' avatars_dir='%s' exists=%s images=%s."
                    " If you expect author avatars in overlays, mount your instance path and/or set AVATARS_PATH.",
                    base_root,
                    avatars_dir,
                    exists,
                    has_images,
                )
    except Exception:
        # Never fail startup due to sanity checks
        pass

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
                    from app import storage as storage_lib

                    base_upload = storage_lib.data_root()

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

                    if _has_files(base_upload):
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
    from app.models import SystemSetting, db

    db.init_app(app)

    # Cache initialization
    from app.cache import init_cache

    init_cache(app)

    # Database migrations available in all environments
    Migrate(app, db)

    # Ensure minimal runtime schema updates (safe additive changes)
    # Only run these in non-testing environments to avoid touching the engine during pytest.
    global _RUNTIME_SCHEMA_CHECKED
    _is_main_reloader = (not app.debug) or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if (
        not app.config.get("TESTING")
        and not _RUNTIME_SCHEMA_CHECKED
        and _is_main_reloader
    ):
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
                    sched_cols = {
                        c["name"] for c in insp.get_columns("scheduled_tasks")
                    }
                except Exception:
                    sched_cols = set()
                try:
                    user_cols = {c["name"] for c in insp.get_columns("users")}
                except Exception:
                    user_cols = set()
                try:
                    tier_cols = {c["name"] for c in insp.get_columns("tiers")}
                except Exception:
                    tier_cols = set()

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
                    # Use TIMESTAMP for broad backend compatibility (SQLite stores as TEXT)
                    statements.append(
                        text("ALTER TABLE clips ADD COLUMN clip_created_at TIMESTAMP")
                    )
                if "view_count" not in clip_cols:
                    statements.append(
                        text("ALTER TABLE clips ADD COLUMN view_count INTEGER")
                    )

                # Schedules table: add monthly_day if missing, and ensure enum has 'monthly'
                sched_statements = []
                if "monthly_day" not in sched_cols:
                    sched_statements.append(
                        text(
                            "ALTER TABLE scheduled_tasks ADD COLUMN monthly_day INTEGER"
                        )
                    )
                # Add new enum value 'monthly' for PostgreSQL if missing
                try:
                    if engine.dialect.name == "postgresql":
                        sched_statements.append(
                            text(
                                """
                                DO $$
                                BEGIN
                                    IF NOT EXISTS (
                                        SELECT 1 FROM pg_enum e
                                        JOIN pg_type t ON e.enumtypid = t.oid
                                        WHERE t.typname = 'scheduletype' AND e.enumlabel = 'monthly'
                                    ) THEN
                                        ALTER TYPE scheduletype ADD VALUE 'monthly';
                                    END IF;
                                END$$;
                                """
                            )
                        )
                except Exception:
                    pass

                if statements or sched_statements:
                    # Execute in a single transaction; SQLAlchemy 2.x style
                    with engine.begin() as conn:
                        for stmt in statements + sched_statements:
                            conn.execute(stmt)
                    # Optionally re-inspect or log success
                    app.logger.info(
                        "Applied runtime schema updates (%d change%s)",
                        len(statements + sched_statements),
                        "s" if len(statements + sched_statements) != 1 else "",
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
                # Audio normalization settings (optional)
                if "audio_norm_profile" not in proj_cols:
                    proj_statements.append(
                        text(
                            "ALTER TABLE projects ADD COLUMN audio_norm_profile VARCHAR(32)"
                        )
                    )
                if "audio_norm_db" not in proj_cols:
                    proj_statements.append(
                        text("ALTER TABLE projects ADD COLUMN audio_norm_db FLOAT")
                    )
                if proj_statements:
                    with engine.begin() as conn:
                        for stmt in proj_statements:
                            conn.execute(stmt)
                    app.logger.info(
                        "Applied projects table runtime updates (%d change%s)",
                        len(proj_statements),
                        "s" if len(proj_statements) != 1 else "",
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
                    # Ensure DB session is usable for subsequent queries
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
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
                # Add user timezone preference if missing (IANA name string)
                if "timezone" not in user_cols:
                    user_statements.append(
                        text("ALTER TABLE users ADD COLUMN timezone VARCHAR(64)")
                    )
                if "password_changed_at" not in user_cols:
                    # Track when user last changed password
                    user_statements.append(
                        text(
                            "ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP"
                        )
                    )
                if "profile_image_path" not in user_cols:
                    user_statements.append(
                        text(
                            "ALTER TABLE users ADD COLUMN profile_image_path VARCHAR(500)"
                        )
                    )
                if user_statements:
                    with engine.begin() as conn:
                        for stmt in user_statements:
                            conn.execute(stmt)
                    app.logger.info(
                        "Applied users table runtime updates (%d change%s)",
                        len(user_statements),
                        "s" if len(user_statements) != 1 else "",
                    )
                # Additive columns for tiers: output constraints
                tier_statements = []
                if "max_output_resolution" not in tier_cols:
                    tier_statements.append(
                        text(
                            "ALTER TABLE tiers ADD COLUMN max_output_resolution VARCHAR(10)"
                        )
                    )
                if "max_fps" not in tier_cols:
                    tier_statements.append(
                        text("ALTER TABLE tiers ADD COLUMN max_fps INTEGER")
                    )
                if "max_clips_per_project" not in tier_cols:
                    tier_statements.append(
                        text(
                            "ALTER TABLE tiers ADD COLUMN max_clips_per_project INTEGER"
                        )
                    )
                if tier_statements:
                    with engine.begin() as conn:
                        for stmt in tier_statements:
                            conn.execute(stmt)
                    app.logger.info(
                        "Applied tiers table runtime updates (%d change%s)",
                        len(tier_statements),
                        "s" if len(tier_statements) != 1 else "",
                    )
                # Ensure system_settings table exists using ORM to avoid backend-specific DDL
                try:
                    existing_tables = set(insp.get_table_names())
                    if "system_settings" not in existing_tables:
                        with app.app_context():
                            db.create_all()
                        app.logger.debug("Ensured system_settings via ORM create_all")
                except Exception as e2:
                    app.logger.warning(
                        f"system_settings table ensure failed/skipped: {e2}"
                    )

                # Ensure themes table exists (safe creation via ORM if needed)
                try:
                    existing_tables = set(insp.get_table_names())
                    if "themes" not in existing_tables:
                        with app.app_context():
                            db.create_all()
                        app.logger.debug("Ensured themes table via ORM create_all")
                    else:
                        # Additive columns for themes if missing (works for SQLite/Postgres)
                        theme_cols = {c["name"] for c in insp.get_columns("themes")}
                        add_theme_stmts = []

                        def _add(colspec: str):
                            add_theme_stmts.append(
                                text(f"ALTER TABLE themes ADD COLUMN {colspec}")
                            )

                        if "description" not in theme_cols:
                            _add("description TEXT")
                        if "is_active" not in theme_cols:
                            _add("is_active BOOLEAN DEFAULT 0 NOT NULL")
                        for col in (
                            "color_primary VARCHAR(20)",
                            "color_secondary VARCHAR(20)",
                            "color_accent VARCHAR(20)",
                            "color_background VARCHAR(20)",
                            "color_surface VARCHAR(20)",
                            "color_text VARCHAR(20)",
                            "color_muted VARCHAR(20)",
                            "navbar_bg VARCHAR(20)",
                            "navbar_text VARCHAR(20)",
                            "outline_color VARCHAR(20)",
                            "media_color_intro VARCHAR(20)",
                            "media_color_clip VARCHAR(20)",
                            "media_color_outro VARCHAR(20)",
                            "media_color_transition VARCHAR(20)",
                            "media_color_compilation VARCHAR(20)",
                            "logo_path VARCHAR(500)",
                            "favicon_path VARCHAR(500)",
                            "watermark_path VARCHAR(500)",
                            "watermark_opacity FLOAT",
                            "watermark_position VARCHAR(32)",
                            "updated_at TIMESTAMP",
                            "updated_by INTEGER",
                            "mode VARCHAR(10)",
                        ):
                            # extract name before first space
                            cname = col.split(" ", 1)[0]
                            if cname not in theme_cols:
                                _add(col)
                        if add_theme_stmts:
                            with engine.begin() as conn:
                                for stmt in add_theme_stmts:
                                    conn.execute(stmt)
                            app.logger.info(
                                "Applied runtime theme schema updates (%d change%s)",
                                len(add_theme_stmts),
                                "s" if len(add_theme_stmts) != 1 else "",
                            )
                except Exception as e:
                    app.logger.warning(f"Themes table ensure failed/skipped: {e}")

                # Ensure users table has watermark_disabled column for per-user override
                try:
                    existing_tables = set(insp.get_table_names())
                    if "users" in existing_tables:
                        user_cols = {c["name"] for c in insp.get_columns("users")}
                        if "watermark_disabled" not in user_cols:
                            with engine.begin() as conn:
                                conn.execute(
                                    text(
                                        "ALTER TABLE users ADD COLUMN watermark_disabled BOOLEAN DEFAULT FALSE NOT NULL"
                                    )
                                )
                            app.logger.info(
                                "Applied runtime users schema update: watermark_disabled"
                            )
                except Exception as e:
                    app.logger.warning(
                        f"Users table watermark_disabled ensure failed/skipped: {e}"
                    )
        except Exception as e:
            # Log and proceed; migrations should handle in production
            app.logger.warning(f"Schema check/upgrade skipped or failed: {e}")
        finally:
            # Avoid re-running (and re-logging) this block on subsequent app creations in this process
            _RUNTIME_SCHEMA_CHECKED = True

    # CORS for API access
    CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000"])

    # CSRF Protection
    csrf.init_app(app)

    # Ensure default subscription tiers exist (idempotent)
    try:
        if not app.config.get("TESTING"):
            from app.quotas import ensure_default_tiers  # local import to avoid cycles

            with app.app_context():
                ensure_default_tiers()
    except Exception:
        # Non-fatal if quotas module unavailable or DB not ready yet
        pass

    # Defensive: ensure any aborted transactions are cleared at the start of a request
    # This prevents 'InFailedSqlTransaction' errors from a previous failed statement
    @app.before_request
    def _ensure_clean_db_session():  # pragma: no cover - simple guard
        try:
            from app.models import db as _db

            # Rollback clears any pending/aborted transaction state on the connection
            _db.session.rollback()
        except Exception:
            # If DB isn't ready or rollback isn't needed, ignore
            pass

    # Extra safety: always clean up the session at the end of each request.
    # This prevents 'InFailedSqlTransaction' from leaking across requests if any view errored.
    @app.teardown_request
    def _teardown_request(exc):  # pragma: no cover - simple guard
        # On request errors, ensure the transaction is rolled back.
        # Avoid forcibly removing the session here to keep Flask-SQLAlchemy's
        # own appcontext-scoped cleanup behavior and prevent detaching models
        # mid-request/redirect chains in tests.
        try:
            from app.models import db as _db

            if exc is not None:
                try:
                    _db.session.rollback()
                except Exception:
                    pass
        except Exception:
            pass

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

    # Apply settings overrides (allowlist only)
    try:
        if not app.config.get("TESTING"):
            # Retry a few times if DB is transiently overloaded
            for _attempt in range(3):
                try:
                    with app.app_context():
                        allowed = {
                            "RATELIMIT_ENABLED": "bool",
                            "RATELIMIT_DEFAULT": "str",
                            "FORCE_HTTPS": "bool",
                            "AUTO_REINDEX_ON_STARTUP": "bool",
                            "USE_GPU_QUEUE": "bool",
                            "ALLOW_EXTERNAL_URLS": "bool",
                            "OUTPUT_VIDEO_QUALITY": "str",
                            "FFMPEG_BINARY": "str",
                            "YT_DLP_BINARY": "str",
                            "FFPROBE_BINARY": "str",
                            # CLI args for multimedia tools
                            "FFMPEG_GLOBAL_ARGS": "str",
                            "FFMPEG_ENCODE_ARGS": "str",
                            "FFMPEG_THUMBNAIL_ARGS": "str",
                            "FFMPEG_CONCAT_ARGS": "str",
                            "FFPROBE_ARGS": "str",
                            "YT_DLP_ARGS": "str",
                            "THUMBNAIL_TIMESTAMP_SECONDS": "int",
                            "THUMBNAIL_WIDTH": "int",
                            "PROJECTS_PER_PAGE": "int",
                            "MEDIA_PER_PAGE": "int",
                            "ADMIN_USERS_PER_PAGE": "int",
                            "ADMIN_PROJECTS_PER_PAGE": "int",
                            "AVATARS_PATH": "str",
                            "DEFAULT_OUTPUT_RESOLUTION": "str",
                            "DEFAULT_OUTPUT_FORMAT": "str",
                            "DEFAULT_MAX_CLIP_DURATION": "int",
                            "DEFAULT_TRANSITION_DURATION_SECONDS": "int",
                            "AVERAGE_CLIP_DURATION_SECONDS": "int",
                        }
                        # Allowlist of System Settings that can override app.config at runtime
                        allowed.update(
                            {
                                "WATERMARK_PATH": "str",
                                "WATERMARK_OPACITY": "float",
                                "WATERMARK_POSITION": "str",
                            }
                        )
                        # Extend allowlist with Email/SMTP settings (no secrets)
                        allowed.update(
                            {
                                "EMAIL_VERIFICATION_ENABLED": "bool",
                                "EMAIL_FROM_ADDRESS": "str",
                                "SMTP_HOST": "str",
                                "SMTP_PORT": "int",
                                "SMTP_USE_TLS": "bool",
                                "SMTP_USE_SSL": "bool",
                                "SMTP_USERNAME": "str",
                            }
                        )
                        rows = SystemSetting.query.filter(
                            SystemSetting.key.in_(allowed.keys())
                        ).all()
                        for row in rows:
                            vtype = (
                                row.value_type or allowed.get(row.key) or "str"
                            ).lower()
                            raw = row.value
                            val = raw
                            if vtype == "bool":
                                val = raw.strip().lower() in {"1", "true", "yes", "on"}
                            elif vtype == "int":
                                try:
                                    val = int(raw)
                                except Exception:
                                    continue
                            elif vtype == "float":
                                try:
                                    val = float(raw)
                                except Exception:
                                    continue
                            elif vtype == "json":
                                import json as _json

                                try:
                                    val = _json.loads(raw)
                                except Exception:
                                    continue
                            app.config[row.key] = val
                        if rows:
                            app.logger.debug(
                                "Applied %d system setting override(s): %s",
                                len(rows),
                                ", ".join(r.key for r in rows),
                            )
                    break
                except Exception as e:
                    # Retry on transient connection exhaustion
                    if "too many clients" in str(e).lower() and _attempt < 2:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        time.sleep(1 + _attempt)
                        continue
                    # Otherwise, bubble to outer handler
                    raise
    except Exception as e:
        # Rollback session to clear any aborted transaction state
        try:
            db.session.rollback()
        except Exception:
            pass
        app.logger.warning(f"Failed applying system settings: {e}")


def register_blueprints(flask_app):
    """
    Register Flask blueprints.

    Args:
        flask_app: Flask application instance
    """
    # API routes - All API endpoints are registered on the shared api_bp blueprint
    # Import modules to register their routes, then register the blueprint once
    from app.api.routes import api_bp

    # Import API modules to register their routes on api_bp
    try:
        import app.api.notifications  # noqa: F401 - registers routes on api_bp
        import app.api.tags  # noqa: F401 - registers routes on api_bp (optional)
        import app.api.teams  # noqa: F401 - registers routes on api_bp
        import app.api.templates  # noqa: F401 - registers routes on api_bp (optional)
    except ImportError as e:
        flask_app.logger.warning(f"Some API modules not available: {e}")

    flask_app.register_blueprint(api_bp, url_prefix="/api")

    # Authentication routes
    from app.auth.routes import auth_bp

    flask_app.register_blueprint(auth_bp, url_prefix="/auth")

    # Main web interface routes
    from app.main.routes import main_bp

    flask_app.register_blueprint(main_bp)

    # Admin interface routes
    from app.admin.routes import admin_bp

    flask_app.register_blueprint(admin_bp, url_prefix="/admin")


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

    @app.context_processor
    def inject_active_theme():
        """Provide active theme and CSS variables to all templates."""
        try:
            from app.models import Theme

            theme = Theme.query.filter_by(is_active=True).first()
        except Exception:
            theme = None
        css_vars = theme.as_css_vars() if theme else {}

        # Heuristic to choose Bootstrap theme mode (light/dark) based on background color
        def _hex_to_rgb(hex_color: str):
            h = (hex_color or "").lstrip("#")
            if len(h) in (3, 4):
                h = "".join([c * 2 for c in h[:3]])
            if len(h) >= 6:
                try:
                    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
                except Exception:
                    return (18, 18, 18)
            return (18, 18, 18)

        def _luminance(rgb):
            r, g, b = (x / 255.0 for x in rgb)
            # relative luminance approximation
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        bg_hex = None
        if theme and getattr(theme, "color_background", None):
            bg_hex = theme.color_background
        else:
            bg_hex = "#121212"
        lum = _luminance(_hex_to_rgb(bg_hex))
        # Start with heuristic, then override with explicit theme.mode if provided
        bs_theme_mode = "light" if lum >= 0.5 else "dark"
        try:
            if (
                theme
                and getattr(theme, "mode", None)
                and theme.mode in {"light", "dark"}
            ):
                bs_theme_mode = theme.mode
        except Exception:
            pass
        return {
            "active_theme": theme,
            "theme_css_vars": css_vars,
            "bs_theme_mode": bs_theme_mode,
        }


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
