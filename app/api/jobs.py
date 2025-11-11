"""Task/job endpoints for the API blueprint.

Mounts served by this module:

- GET /tasks/<task_id>
  - Purpose: fetch Celery task status and details for a given async task id.
  - Parameters:
    - task_id (path): Celery AsyncResult id to query.
  - Response: JSON payload with fields such as task_id, status, state, ready,
    optional info/result and serialized error information when available.

This module intentionally keeps serialization defensive so task info/results
that may contain exceptions or non-JSON types are converted into a safe
structure for the API consumer.
"""

from flask import jsonify, request, url_for

from app.api import api_bp
from app.tasks.celery_app import celery_app

# Compatibility endpoints expected by templates/js
# The templates reference `url_for('api.recent_jobs_api')` and
# `url_for('api.job_details_api', job_id=0)`. These lightweight wrappers
# expose those endpoint names and return JSON compatible enough for the
# client-side to render recent job lists and job detail links.


@api_bp.route("/tasks/<task_id>", methods=["GET"])
def get_task_status(task_id):
    """Get task status.

    Returns a JSON description of the Celery task identified by `task_id`.
    """

    task = celery_app.AsyncResult(task_id)

    def _safe_json(val):
        """Safely convert arbitrary objects (including Exceptions) into JSON-serializable structures.

        The function is defensive and will fall back to string representations
        when a value cannot be converted more precisely.
        """
        try:
            if val is None:
                return None
            t = type(val)
            if t in (bool, int, float, str):
                return val
            if isinstance(val, bytes):
                try:
                    return val.decode("utf-8", errors="replace")
                except Exception:
                    return str(val)
            if isinstance(val, dict):
                return {str(k): _safe_json(v) for k, v in val.items()}
            if isinstance(val, list):
                return [_safe_json(v) for v in val]
            if isinstance(val, tuple):
                return [_safe_json(v) for v in val]
            if isinstance(val, set):
                return [_safe_json(v) for v in val]
            if isinstance(val, BaseException):
                return {"type": type(val).__name__, "message": str(val)}
            return str(val)
        except Exception as e:  # Defensive: never raise from serializer
            return {"type": type(val).__name__, "message": f"<unserializable: {e}>"}

    payload = {
        "task_id": task_id,
        "status": task.status,
        "state": task.state,
        "ready": task.ready(),
    }
    try:
        info = task.info
        if info is not None:
            payload["info"] = _safe_json(info)
    except Exception:
        pass

    if task.ready():
        try:
            payload["result"] = _safe_json(task.result)
        except Exception as e:
            payload["result"] = None
            payload["error"] = str(e)

    if task.state == "FAILURE":
        try:
            payload.setdefault(
                "error", str(task.info) if task.info is not None else "Unknown error"
            )
        except Exception:
            payload.setdefault("error", "Unknown error")

    return jsonify(payload)


@api_bp.route("/jobs/recent", methods=["GET"], endpoint="recent_jobs_api")
def recent_jobs_api():
    """Return recent processing jobs for the current user.

    This is a compatibility wrapper used by the UI to display recent
    activity in the navbar. It accepts an optional `limit` query
    parameter.
    """
    try:
        # local imports to avoid import-time cycles
        from flask_login import current_user

        from app.models import ProcessingJob

        limit = request.args.get("limit", 10, type=int)
        q = (
            ProcessingJob.query.filter_by(user_id=current_user.id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(limit)
        )
        jobs = q.all()
        out = []
        for j in jobs:
            out.append(
                {
                    "id": j.id,
                    "celery_task_id": j.celery_task_id,
                    "job_type": j.job_type,
                    "status": j.status,
                    "progress": j.progress,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
            )
        return jsonify(out)
    except Exception:
        # Don't raise to the UI; return empty list on error
        return jsonify([])


@api_bp.route("/jobs/<int:job_id>", methods=["GET"], endpoint="job_details_api")
def job_details_api(job_id: int):
    """Return details for a single ProcessingJob (compat wrapper).

    The client expects a URL template to fetch job details; this
    endpoint returns a small JSON summary including a link to the
    underlying Celery task status endpoint.
    """
    try:
        from flask_login import current_user

        from app.models import ProcessingJob

        job = ProcessingJob.query.filter_by(id=job_id).first_or_404()
        # Ownership check
        if job.user_id != current_user.id and not current_user.is_admin():
            return jsonify({"error": "Not authorized"}), 403

        task_status_url = None
        if job.celery_task_id:
            task_status_url = url_for("api.get_task_status", task_id=job.celery_task_id)

        payload = {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "progress": job.progress,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "task_status_url": task_status_url,
        }
        return jsonify(payload)
    except Exception:
        return jsonify({"error": "Not found"}), 404
