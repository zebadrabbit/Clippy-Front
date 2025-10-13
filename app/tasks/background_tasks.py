"""
Background tasks using Celery.
"""
import time

from app.tasks.celery_app import celery_app


@celery_app.task
def example_long_task(task_name: str = "default"):
    """
    Example long-running task.

    Args:
        task_name: Name of the task to execute

    Returns:
        dict: Task result
    """
    # Simulate long-running work
    time.sleep(10)

    return {
        "task_name": task_name,
        "status": "completed",
        "message": f"Task {task_name} completed successfully",
    }


@celery_app.task
def process_data(data: dict):
    """
    Process data in background.

    Args:
        data: Data to process

    Returns:
        dict: Processed result
    """
    # Simulate data processing
    time.sleep(5)

    return {"original_data": data, "processed": True, "timestamp": time.time()}
