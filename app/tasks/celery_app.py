"""
Celery application configuration.
"""

import logging

from celery import Celery
from kombu import Queue

from config.settings import Config


def make_celery(app_name=__name__):
    """Create and configure Celery application."""
    config = Config()

    logger = logging.getLogger("celery.config")
    try:
        logger.info(
            "Initializing Celery with broker=%s backend=%s",
            config.CELERY_BROKER_URL,
            config.CELERY_RESULT_BACKEND,
        )
    except Exception:
        # Avoid hard failure if logging misconfigured; continue startup
        pass

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
        # Define queues: default 'celery' and a dedicated 'gpu' queue for heavy video tasks
        task_queues=(
            Queue("celery"),
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

    return celery_app


# Create Celery app
celery_app = make_celery()
