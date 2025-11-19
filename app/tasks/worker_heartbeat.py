"""
Worker heartbeat and version reporting system.

This module ensures workers are running compatible code versions
and provides visibility into the worker fleet.
"""
import platform
import socket
from datetime import datetime, timezone

from celery import current_app as current_celery_app

from app.version import __version__


def get_worker_info():
    """Get worker environment information."""
    try:
        worker_name = current_celery_app.current_worker_task.request.hostname
    except Exception:
        worker_name = socket.gethostname()

    return {
        "worker_name": worker_name,
        "version": __version__,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "hostname": socket.gethostname(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@current_celery_app.task(name="app.tasks.worker_heartbeat.heartbeat_task")
def heartbeat_task():
    """Periodic heartbeat task that reports worker version and health."""
    info = get_worker_info()
    # Store in Redis with TTL for monitoring
    try:
        from app.tasks.celery_app import celery_app

        key = f"worker:heartbeat:{info['worker_name']}"
        celery_app.backend.set(key, info, ex=120)  # 2 minute TTL
    except Exception:
        pass

    return {"status": "alive", **info}


@current_celery_app.task(
    name="app.tasks.worker_heartbeat.worker_startup_task", bind=True
)
def worker_startup_task(self):
    """Task run on worker startup to register version."""
    info = get_worker_info()
    info["queues"] = self.request.delivery_info.get("routing_key", "unknown")

    # Log startup with version
    try:
        import structlog

        logger = structlog.get_logger(__name__)
        logger.info(
            "worker_started",
            version=info["version"],
            worker=info["worker_name"],
            hostname=info["hostname"],
            python_version=info["python_version"],
        )
    except Exception:
        # Fallback to basic logging
        import logging

        logging.info(
            f"Worker {info['worker_name']} started: "
            f"version={info['version']}, hostname={info['hostname']}"
        )

    return {"status": "started", **info}
