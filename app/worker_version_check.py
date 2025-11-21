"""
Worker version validation and compatibility checking.

Prevents stale/outdated workers from accepting tasks by inspecting
active workers and filtering based on version compatibility.
"""
import logging
import os

from app.tasks.celery_app import celery_app
from app.version import __version__

# Use standard logging to avoid kwargs issues
logger = logging.getLogger(__name__)

# Silence for CLI tools if needed
if os.environ.get("WORKER_CHECK_CLI"):
    logger.setLevel(logging.ERROR)


def parse_worker_version(worker_name):
    """
    Extract version from worker name if present.

    Expected format: celery@hostname or celery-v0.12.0@hostname

    Returns:
        tuple: (base_name, version or None)
    """
    if "@" in worker_name:
        name_part = worker_name.split("@")[0]
        if "-v" in name_part:
            # Format: celery-v0.12.0
            parts = name_part.split("-v")
            return parts[0], parts[1] if len(parts) > 1 else None
    return worker_name, None


def get_active_workers(timeout=2.0):
    """
    Get all active workers with their queues and versions.

    Returns:
        dict: {
            worker_name: {
                "queues": [queue_names],
                "version": version_string or None,
                "compatible": bool
            }
        }
    """
    inspector = celery_app.control.inspect(timeout=timeout)
    if not inspector:
        logger.warning("Worker inspection failed: inspector unavailable")
        return {}

    active_queues = inspector.active_queues() or {}
    workers = {}

    current_version = __version__

    for worker_name, queues in active_queues.items():
        base_name, version = parse_worker_version(worker_name)

        queue_names = []
        for q in queues or []:
            if isinstance(q, dict):
                queue_names.append(q.get("name"))
            else:
                queue_names.append(str(q))

        # Check version compatibility
        # IMPORTANT: Treat unknown/null versions as INCOMPATIBLE
        # This prevents hidden workers (e.g., Docker Desktop vs WSL2) from stealing tasks
        compatible = False
        reason = None

        if version is None:
            # No version tag - incompatible (could be old/hidden worker)
            reason = "no_version_tag"
            logger.warning(
                f"Worker without version: {worker_name} (queues: {queue_names}) - "
                f"Workers without version tags are incompatible with server v{current_version}"
            )
        elif version != current_version:
            # Explicit version mismatch
            reason = "version_mismatch"
            logger.warning(
                f"Version mismatch: {worker_name} has v{version}, "
                f"server is v{current_version} (queues: {queue_names})"
            )
        else:
            # Version matches - compatible
            compatible = True

        workers[worker_name] = {
            "queues": queue_names,
            "version": version,
            "compatible": compatible,
            "incompatible_reason": reason,
            "base_name": base_name,
        }

    return workers


def get_compatible_workers(queue_name, timeout=2.0):
    """
    Get workers compatible with current version for a specific queue.

    Args:
        queue_name: Queue to check (e.g., "gpu", "cpu", "celery")
        timeout: Inspection timeout in seconds

    Returns:
        list: Compatible worker names for the queue
    """
    all_workers = get_active_workers(timeout=timeout)
    compatible = []

    for worker_name, info in all_workers.items():
        # If version is embedded and doesn't match, skip
        if not info["compatible"]:
            continue

        # Check if worker handles this queue
        if queue_name in info["queues"]:
            compatible.append(worker_name)

    return compatible


def check_queue_health(queue_name, min_workers=1, timeout=2.0):
    """
    Check if a queue has sufficient compatible workers.

    Args:
        queue_name: Queue to check
        min_workers: Minimum required compatible workers
        timeout: Inspection timeout

    Returns:
        dict: {
            "healthy": bool,
            "compatible_workers": int,
            "incompatible_workers": int,
            "worker_names": [str]
        }
    """
    all_workers = get_active_workers(timeout=timeout)

    compatible = []
    incompatible = []

    for worker_name, info in all_workers.items():
        if queue_name not in info["queues"]:
            continue

        if info["compatible"]:
            compatible.append(worker_name)
        else:
            incompatible.append(worker_name)

    healthy = len(compatible) >= min_workers

    result = {
        "healthy": healthy,
        "compatible_workers": len(compatible),
        "incompatible_workers": len(incompatible),
        "worker_names": compatible,
    }

    if incompatible:
        logger.warning(
            f"Incompatible workers on queue '{queue_name}': {incompatible} "
            f"(compatible: {compatible})"
        )

    return result
