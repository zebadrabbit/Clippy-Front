"""
Celery application configuration.
"""

from celery import Celery
from celery.signals import task_postrun
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
