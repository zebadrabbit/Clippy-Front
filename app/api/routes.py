"""
API routes and endpoints.
"""
from flask import Blueprint, jsonify, request

from app.tasks.background_tasks import example_long_task

api_bp = Blueprint("api", __name__)


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "message": "ClippyFront API is running"})


@api_bp.route("/tasks/start", methods=["POST"])
def start_task():
    """Start a background task."""
    data = request.get_json() or {}
    task_name = data.get("task_name", "default")

    # Start background task
    task = example_long_task.delay(task_name)

    return jsonify(
        {
            "task_id": task.id,
            "status": "started",
            "message": f"Task {task_name} started",
        }
    )


@api_bp.route("/tasks/<task_id>", methods=["GET"])
def get_task_status(task_id):
    """Get task status."""
    from app.tasks.celery_app import celery_app

    task = celery_app.AsyncResult(task_id)

    return jsonify(
        {
            "task_id": task_id,
            "status": task.status,
            "result": task.result if task.ready() else None,
        }
    )
