"""
Celery application configuration.
"""
# ruff: noqa: I001

from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger, task_postrun
from kombu import Queue

from config.settings import Config


def make_celery(app_name=__name__):
    """Create and configure Celery application."""
    config = Config()

    celery_app = Celery(
        app_name,
        broker=config.CELERY_BROKER_URL,
        backend=config.CELERY_RESULT_BACKEND,
        include=[],
    )
    # Conditionally register task modules
    celery_includes = [
        "app.tasks.download_clip_v2",  # Phase 3: API-based download
        "app.tasks.compile_video_v2",  # Phase 4: API-based compilation
        "app.tasks.preview_video",  # Preview video generation
        "app.tasks.enrich_clip_metadata",  # Server-side Twitch metadata enrichment
        "app.tasks.media_maintenance",
        "app.tasks.notification_cleanup",  # Notification retention cleanup
        "app.tasks.video_processing",  # Utility functions only (no DB-based tasks)
    ]

    celery_app.conf.update(include=celery_includes)

    # Update configuration
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        # Celery 6+ change: explicitly retry broker connections on startup
        broker_connection_retry_on_startup=True,
        # Define queues: default 'celery', a dedicated 'cpu' queue for CPU renders,
        # and a 'gpu' queue for NVENC-capable workers
        task_queues=(
            Queue("celery"),
            Queue("cpu"),
            Queue("gpu"),
        ),
        # Route compile tasks to the GPU queue by default
        task_routes=(
            lambda name, args, kwargs, options, task=None: (
                {"queue": "gpu"}
                if name == "tasks.compile_video_v2"  # Updated to v2 task
                and config.USE_GPU_QUEUE
                else None
            )
        ),
    )

    # Beat schedule for periodic tasks
    beat_schedule = {
        "cleanup-old-notifications": {
            "task": "app.tasks.notification_cleanup.cleanup_old_notifications_task",
            "schedule": 86400.0,  # Run daily (24 hours in seconds)
            "args": (config.NOTIFICATION_RETENTION_DAYS,),
        },
        "check-binary-updates": {
            "task": "app.tasks.binary_updates.check_binary_updates_task",
            "schedule": 604800.0,  # Run weekly (7 days in seconds)
        },
    }
    celery_app.conf.beat_schedule = beat_schedule

    return celery_app


# Create Celery app
celery_app = make_celery()


# Attach structlog for Celery loggers
@after_setup_logger.connect
def _setup_celery_logger(logger, *args, **kwargs):  # pragma: no cover - logging init
    try:
        # Detect instance path similarly to Flask's default for this project root
        import os as _os

        repo_root = _os.path.abspath(
            _os.path.join(_os.path.dirname(__file__), "..", "..")
        )
        # Prefer CLIPPY_INSTANCE_PATH if set, else app default instance under repo
        instance_path = _os.environ.get("CLIPPY_INSTANCE_PATH") or _os.path.join(
            repo_root, "instance"
        )

        from app.structured_logging import configure_structlog_celery

        configure_structlog_celery(instance_path)
    except Exception:
        # Non-fatal; fallback to stderr
        pass


@after_setup_task_logger.connect
def _setup_celery_task_logger(
    logger, *args, **kwargs
):  # pragma: no cover - logging init
    try:
        import os as _os

        repo_root = _os.path.abspath(
            _os.path.join(_os.path.dirname(__file__), "..", "..")
        )
        instance_path = _os.environ.get("CLIPPY_INSTANCE_PATH") or _os.path.join(
            repo_root, "instance"
        )

        from app.structured_logging import configure_structlog_celery

        configure_structlog_celery(instance_path)
    except Exception:
        pass


# Ensure SQLAlchemy sessions are cleaned up after each task to avoid leaking
# connections across Celery worker processes.
@task_postrun.connect
def _cleanup_db_session(*args, **kwargs):  # pragma: no cover - simple guard
    try:
        from app.models import db

        db.session.remove()
    except Exception:
        # If DB isn't initialized yet or session not used, ignore
        pass
