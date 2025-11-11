"""
Worker API endpoints - for Celery workers to access metadata and update status.

These endpoints are designed for workers running outside the DMZ without direct
database access. Workers authenticate using a shared WORKER_API_KEY.

Endpoints:
- GET /worker/clips/<clip_id> - Get clip metadata for download
- POST /worker/clips/<clip_id>/status - Update clip download status
- GET /worker/media/<media_id> - Get media file metadata (for intro/outro/transitions)
- POST /worker/jobs - Create a processing job
- PUT /worker/jobs/<job_id> - Update processing job status/progress
"""

from datetime import datetime
from functools import wraps

from flask import current_app, jsonify, request

from app.api import api_bp
from app.models import Clip, MediaFile, ProcessingJob, Project, db


def require_worker_key(f):
    """Decorator to require WORKER_API_KEY for worker endpoints."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        expected_key = current_app.config.get("WORKER_API_KEY", "").strip()
        if not expected_key:
            current_app.logger.error(
                "WORKER_API_KEY not configured - worker endpoints disabled"
            )
            return jsonify({"error": "Worker API not configured"}), 500

        auth_header = request.headers.get("Authorization", "")
        provided_key = ""
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:].strip()

        if provided_key != expected_key:
            current_app.logger.warning(
                f"Worker API authentication failed from {request.remote_addr}"
            )
            return jsonify({"error": "Unauthorized"}), 401

        return f(*args, **kwargs)

    return decorated_function


@api_bp.route("/worker/clips/<int:clip_id>", methods=["GET"])
@require_worker_key
def worker_get_clip(clip_id: int):
    """Get clip metadata for download task.

    Returns:
        {
            "id": int,
            "title": str,
            "source_url": str,
            "source_platform": str,
            "project_id": int,
            "user_id": int,
            "username": str,
            "project_name": str
        }
    """
    try:
        clip = Clip.query.get(clip_id)
        if not clip:
            return jsonify({"error": "Clip not found"}), 404

        return jsonify(
            {
                "id": clip.id,
                "title": clip.title,
                "source_url": clip.source_url,
                "source_platform": clip.source_platform,
                "source_id": clip.source_id,
                "project_id": clip.project_id,
                "user_id": clip.project.user_id,
                "username": clip.project.user.username,
                "project_name": clip.project.name,
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching clip {clip_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/clips/<int:clip_id>/status", methods=["POST"])
@require_worker_key
def worker_update_clip_status(clip_id: int):
    """Update clip download status.

    Request body:
        {
            "is_downloaded": bool,
            "media_file_id": int (optional),
            "duration": float (optional),
            "error": str (optional)
        }
    """
    try:
        clip = Clip.query.get(clip_id)
        if not clip:
            return jsonify({"error": "Clip not found"}), 404

        data = request.get_json() or {}

        if "is_downloaded" in data:
            clip.is_downloaded = bool(data["is_downloaded"])

        if "media_file_id" in data:
            clip.media_file_id = int(data["media_file_id"])

        if "duration" in data:
            clip.duration = float(data["duration"])

        db.session.commit()

        return jsonify({"status": "updated", "clip_id": clip_id})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating clip {clip_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/media/<int:media_id>", methods=["GET"])
@require_worker_key
def worker_get_media(media_id: int):
    """Get media file metadata.

    Returns:
        {
            "id": int,
            "filename": str,
            "file_path": str,
            "media_type": str,
            "duration": float,
            "user_id": int,
            "username": str
        }
    """
    try:
        media = MediaFile.query.get(media_id)
        if not media:
            return jsonify({"error": "Media file not found"}), 404

        return jsonify(
            {
                "id": media.id,
                "filename": media.filename,
                "file_path": media.file_path,
                "media_type": media.media_type.value if media.media_type else None,
                "duration": media.duration,
                "user_id": media.user_id,
                "username": media.user.username,
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching media {media_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/jobs", methods=["POST"])
@require_worker_key
def worker_create_job():
    """Create a processing job.

    Request body:
        {
            "celery_task_id": str,
            "job_type": str,
            "project_id": int,
            "user_id": int,
            "status": str (default: "started")
        }
    """
    try:
        data = request.get_json() or {}

        job = ProcessingJob(
            celery_task_id=data.get("celery_task_id"),
            job_type=data.get("job_type", "unknown"),
            project_id=data.get("project_id"),
            user_id=data.get("user_id"),
            status=data.get("status", "started"),
            started_at=datetime.utcnow(),
        )
        db.session.add(job)
        db.session.commit()

        return jsonify({"status": "created", "job_id": job.id})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating job: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/jobs/<int:job_id>", methods=["PUT"])
@require_worker_key
def worker_update_job(job_id: int):
    """Update processing job status/progress.

    Request body:
        {
            "status": str (optional),
            "progress": int (optional),
            "result_data": dict (optional),
            "error_message": str (optional)
        }
    """
    try:
        job = ProcessingJob.query.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404

        data = request.get_json() or {}

        if "status" in data:
            job.status = data["status"]
            if data["status"] in ("completed", "failed"):
                job.completed_at = datetime.utcnow()

        if "progress" in data:
            job.progress = int(data["progress"])

        if "result_data" in data:
            # Merge with existing result_data
            existing = job.result_data or {}
            existing.update(data["result_data"])
            job.result_data = existing

        if "error_message" in data:
            job.error_message = data["error_message"]

        db.session.commit()

        return jsonify({"status": "updated", "job_id": job_id})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating job {job_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/projects/<int:project_id>", methods=["GET"])
@require_worker_key
def worker_get_project(project_id: int):
    """Get project metadata for compilation.

    Returns:
        {
            "id": int,
            "name": str,
            "user_id": int,
            "username": str,
            "max_clip_duration": int,
            "output_resolution": str,
            "output_format": str,
            "audio_norm_db": float,
            "clips": [...]
        }
    """
    try:
        project = Project.query.get(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        clips_data = []
        for clip in project.clips.order_by(Clip.order_index).all():
            clips_data.append(
                {
                    "id": clip.id,
                    "title": clip.title,
                    "order_index": clip.order_index,
                    "media_file_id": clip.media_file_id,
                    "duration": clip.duration,
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "is_downloaded": clip.is_downloaded,
                }
            )

        return jsonify(
            {
                "id": project.id,
                "name": project.name,
                "user_id": project.user_id,
                "username": project.user.username,
                "max_clip_duration": project.max_clip_duration,
                "output_resolution": project.output_resolution,
                "output_format": project.output_format,
                "audio_norm_db": project.audio_norm_db,
                "clips": clips_data,
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching project {project_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/projects/<int:project_id>/status", methods=["PUT"])
@require_worker_key
def worker_update_project_status(project_id: int):
    """Update project status and output information.

    Request body:
        {
            "status": str (optional),
            "output_filename": str (optional),
            "output_file_size": int (optional),
            "completed_at": str (optional, ISO format)
        }
    """
    try:
        project = Project.query.get(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        data = request.get_json() or {}

        if "status" in data:
            from app.models import ProjectStatus

            project.status = ProjectStatus(data["status"])

        if "output_filename" in data:
            project.output_filename = data["output_filename"]

        if "output_file_size" in data:
            project.output_file_size = int(data["output_file_size"])

        if "completed_at" in data:
            project.completed_at = datetime.fromisoformat(data["completed_at"])
        elif data.get("status") == "completed":
            project.completed_at = datetime.utcnow()

        db.session.commit()

        return jsonify({"status": "updated", "project_id": project_id})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating project {project_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/media", methods=["POST"])
@require_worker_key
def worker_create_media():
    """Create a media file record.

    Request body:
        {
            "filename": str,
            "original_filename": str,
            "file_path": str,
            "file_size": int,
            "mime_type": str,
            "media_type": str,
            "user_id": int,
            "project_id": int (optional),
            "duration": float (optional),
            "width": int (optional),
            "height": int (optional),
            "framerate": float (optional),
            "thumbnail_path": str (optional),
            "is_processed": bool (optional)
        }

    Returns:
        {"status": "created", "media_id": int}
    """
    try:
        data = request.get_json() or {}

        from app.models import MediaType

        media = MediaFile(
            filename=data.get("filename"),
            original_filename=data.get("original_filename"),
            file_path=data.get("file_path"),
            file_size=int(data.get("file_size", 0)),
            mime_type=data.get("mime_type"),
            media_type=MediaType(data.get("media_type", "video")),
            user_id=int(data.get("user_id")),
            project_id=data.get("project_id"),
            is_processed=data.get("is_processed", True),
        )

        if "duration" in data:
            media.duration = float(data["duration"])
        if "width" in data:
            media.width = int(data["width"])
        if "height" in data:
            media.height = int(data["height"])
        if "framerate" in data:
            media.framerate = float(data["framerate"])
        if "thumbnail_path" in data:
            media.thumbnail_path = data["thumbnail_path"]

        db.session.add(media)
        db.session.commit()

        return jsonify({"status": "created", "media_id": media.id})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating media file: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/worker/users/<int:user_id>/quota", methods=["GET"])
@require_worker_key
def worker_get_user_quota(user_id: int):
    """Get user storage quota information.

    Returns:
        {
            "remaining_bytes": int,
            "total_bytes": int,
            "used_bytes": int
        }
    """
    try:
        from app.models import User
        from app.quotas import storage_remaining_bytes

        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        remaining = storage_remaining_bytes(user)

        # Calculate total and used
        tier = user.tier or "free"
        from app.quotas import TIER_LIMITS

        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        total_bytes = limits.get("max_storage_bytes", 0)
        used_bytes = total_bytes - remaining if remaining and total_bytes else 0

        return jsonify(
            {
                "remaining_bytes": remaining,
                "total_bytes": total_bytes,
                "used_bytes": used_bytes,
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching quota for user {user_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/users/<int:user_id>/tier-limits", methods=["GET"])
@require_worker_key
def worker_get_tier_limits(user_id: int):
    """Get user tier limits.

    Returns:
        {
            "max_clips": int,
            "max_resolution": str,
            "max_compilation_minutes": int,
            "watermark": bool
        }
    """
    try:
        from app.models import User

        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        tier = user.tier or "free"
        from app.quotas import TIER_LIMITS

        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

        return jsonify(
            {
                "max_clips": limits.get("max_clips"),
                "max_resolution": limits.get("max_resolution"),
                "max_compilation_minutes": limits.get("max_compilation_minutes"),
                "watermark": limits.get("watermark", False),
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching tier limits for user {user_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/users/<int:user_id>/record-render", methods=["POST"])
@require_worker_key
def worker_record_render_usage(user_id: int):
    """Record render usage for a user.

    Request body:
        {
            "project_id": int,
            "seconds": float
        }
    """
    try:
        from app.models import User
        from app.quotas import record_render_usage

        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        data = request.get_json() or {}
        project_id = data.get("project_id")
        seconds = float(data.get("seconds", 0))

        record_render_usage(user, project_id, seconds)

        return jsonify({"status": "recorded"})
    except Exception as e:
        current_app.logger.error(
            f"Error recording render usage for user {user_id}: {e}"
        )
        return jsonify({"error": "Internal error"}), 500
