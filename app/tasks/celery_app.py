"""
Celery application configuration.
"""
# ruff: noqa: I001

import logging
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
        "app.tasks.video_processing",
        "app.tasks.media_maintenance",
        "app.tasks.automation",
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
                if name == "app.tasks.video_processing.compile_video_task"
                and config.USE_GPU_QUEUE
                else None
            )
        ),
    )

    # Optional beat schedule for the scheduler tick
    if getattr(config, "SCHEDULER_ENABLE_TICK", False):
        celery_app.conf.beat_schedule = {
            "automation-scheduler-tick": {
                "task": "app.tasks.automation.scheduled_tasks_tick",
                "schedule": int(getattr(config, "SCHEDULER_TICK_SECONDS", 60) or 60),
            }
        }

    return celery_app


# Create Celery app
celery_app = make_celery()


# Attach rotating file handlers for Celery loggers, using instance/logs/
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

        from app.logging_config import (
            attach_celery_file_logging as _attach,
            attach_named_file_logging as _attach_named,
        )

        _attach(logger, instance_path)
        # Also attach a dedicated beat.log for Celery Beat (if present)
        try:
            beat_logger = logging.getLogger("celery.beat")
            _attach_named(beat_logger, instance_path, "beat.log")
        except Exception:
            pass
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

        from app.logging_config import attach_celery_file_logging as _attach

        _attach(logger, instance_path)
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
