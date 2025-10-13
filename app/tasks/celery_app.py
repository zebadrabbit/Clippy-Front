"""
Celery application configuration.
"""
from celery import Celery

from config.settings import Config


def make_celery(app_name=__name__):
    """Create and configure Celery application."""
    config = Config()

    celery_app = Celery(
        app_name,
        broker=config.CELERY_BROKER_URL,
        backend=config.CELERY_RESULT_BACKEND,
        include=["app.tasks.background_tasks"],
    )

    # Update configuration
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )

    return celery_app


# Create Celery app
celery_app = make_celery()
