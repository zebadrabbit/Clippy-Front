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

import os
from datetime import datetime
from functools import wraps

from flask import current_app, jsonify, request

from app.api import api_bp
from app.models import Clip, MediaFile, MediaType, ProcessingJob, Project, db


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
                "username": clip.project.owner.username,
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


@api_bp.route("/worker/media/find-reusable", methods=["POST"])
@require_worker_key
def worker_find_reusable_media():
    """Find reusable media for a user by URL/key matching.

    Searches for existing media files owned by the user that match
    the provided source URL (normalized or Twitch clip key).

    Request body:
        {
            "user_id": int,
            "source_url": str,
            "normalized_url": str (optional),
            "clip_key": str (optional - for Twitch clips)
        }

    Returns:
        {
            "found": bool,
            "media_file_id": int (if found),
            "file_path": str (if found),
            "duration": float (if found)
        }
    """
    try:
        data = request.get_json() or {}
        user_id = data.get("user_id")
        source_url = (data.get("source_url") or "").strip()
        normalized_url = (data.get("normalized_url") or "").strip()
        clip_key = (data.get("clip_key") or "").strip()

        if not user_id or not source_url:
            return jsonify({"error": "user_id and source_url required"}), 400

        # Helper functions (same as in download_clip_task)
        def _normalize_url(u: str) -> str:
            try:
                s = (u or "").strip()
                if not s:
                    return ""
                base = s.split("?")[0].split("#")[0]
                return base[:-1] if base.endswith("/") else base
            except Exception:
                return (u or "").strip()

        def _extract_clip_key(u: str) -> str:
            try:
                s = _normalize_url(u)
                if not s:
                    return ""
                low = s.lower()
                if ("twitch.tv" in low and "/clip/" in low) or (
                    "clips.twitch.tv" in low
                ):
                    try:
                        if "clips.twitch.tv" in low:
                            slug = low.split("clips.twitch.tv", 1)[1].lstrip("/")
                        else:
                            slug = low.split("/clip/", 1)[1]
                        slug = slug.split("/")[0]
                        return slug
                    except Exception:
                        return s
                return s
            except Exception:
                return _normalize_url(u)

        # Use provided values or compute them
        key = clip_key or _extract_clip_key(source_url)
        norm = normalized_url or _normalize_url(source_url)

        # Look for matching clips with media files
        from app.models import Clip, Project

        candidates = (
            db.session.query(Clip)
            .join(Project, Project.id == Clip.project_id)
            .filter(
                Project.user_id == user_id,
                Clip.media_file_id.isnot(None),
            )
            .order_by(Clip.created_at.desc())
            .limit(500)
            .all()
        )

        for prev in candidates:
            try:
                # Skip if clip has no source_url
                if not prev.source_url:
                    continue

                pv_key = _extract_clip_key(prev.source_url)
                pv_norm = _normalize_url(prev.source_url)
            except Exception:
                continue

            if (pv_key and key and pv_key == key) or (pv_norm and pv_norm == norm):
                if prev.media_file_id:
                    mf = db.session.get(MediaFile, prev.media_file_id)
                    if not mf or not mf.file_path:
                        continue

                    # Check if file exists (using canonical path resolution)
                    from app.tasks.video_processing import _resolve_media_input_path

                    try:
                        file_path = _resolve_media_input_path(mf.file_path)
                        if file_path and os.path.exists(file_path):
                            return jsonify(
                                {
                                    "found": True,
                                    "media_file_id": mf.id,
                                    "file_path": mf.file_path,
                                    "duration": mf.duration,
                                    "reused_from_clip_id": prev.id,
                                }
                            )
                    except Exception:
                        # File path couldn't be resolved, continue searching
                        continue

        return jsonify({"found": False})

    except Exception as e:
        current_app.logger.error(f"Error finding reusable media: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/media", methods=["POST"])
@require_worker_key
def worker_create_media_file():
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
            "thumbnail_path": str (optional)
        }

    Returns:
        {
            "status": "created",
            "media_id": int
        }
    """
    try:
        data = request.get_json() or {}
        user_id = data.get("user_id")

        # Create new media file
        media = MediaFile(
            filename=data.get("filename"),
            original_filename=data.get("original_filename"),
            file_path=data.get("file_path"),
            file_size=data.get("file_size"),
            mime_type=data.get("mime_type"),
            media_type=MediaType[data.get("media_type").upper()]
            if data.get("media_type")
            else MediaType.CLIP,
            user_id=user_id,
            project_id=data.get("project_id"),
            duration=data.get("duration"),
            width=data.get("width"),
            height=data.get("height"),
            framerate=data.get("framerate"),
            thumbnail_path=data.get("thumbnail_path"),
        )

        db.session.add(media)
        db.session.commit()

        return jsonify(
            {
                "status": "created",
                "media_id": media.id,
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating media file: {e}")
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


@api_bp.route("/worker/jobs/<int:job_id>", methods=["GET"])
@require_worker_key
def worker_get_job(job_id: int):
    """Get processing job metadata.

    Returns:
        {
            "id": int,
            "celery_task_id": str,
            "job_type": str,
            "status": str,
            "progress": int,
            "result_data": dict,
            "error_message": str | None
        }
    """
    try:
        job = ProcessingJob.query.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404

        return jsonify(
            {
                "id": job.id,
                "celery_task_id": job.celery_task_id,
                "job_type": job.job_type,
                "status": job.status,
                "progress": job.progress or 0,
                "result_data": job.result_data or {},
                "error_message": job.error_message,
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching job {job_id}: {e}")
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
            if data["status"] in ("completed", "success", "failed", "failure"):
                job.completed_at = datetime.utcnow()

        if "progress" in data:
            job.progress = int(data["progress"])

        if "result_data" in data:
            # Merge with existing result_data
            # SQLAlchemy JSON columns need explicit flagging for mutations
            existing = job.result_data or {}
            existing.update(data["result_data"])
            job.result_data = existing
            # Force SQLAlchemy to detect the change
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(job, "result_data")

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
                "username": project.owner.username,
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
        from app.quotas import get_effective_tier, storage_used_bytes

        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        tier = get_effective_tier(user)
        if not tier:
            # No tier assigned, return defaults
            return jsonify(
                {
                    "remaining_bytes": 0,
                    "total_bytes": 0,
                    "used_bytes": 0,
                }
            )

        used_bytes = storage_used_bytes(user.id)
        total_bytes = tier.storage_limit_bytes if tier else 0
        remaining_bytes = max(0, total_bytes - used_bytes) if total_bytes else None

        return jsonify(
            {
                "remaining_bytes": remaining_bytes,
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
            "storage_limit_bytes": int,
            "render_time_limit_seconds": int,
            "apply_watermark": bool,
            "is_unlimited": bool
        }
    """
    try:
        from app.models import User
        from app.quotas import get_effective_tier, should_apply_watermark

        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        tier = get_effective_tier(user)
        if not tier:
            # Return sensible defaults if no tier
            return jsonify(
                {
                    "storage_limit_bytes": 0,
                    "render_time_limit_seconds": 0,
                    "apply_watermark": True,
                    "is_unlimited": False,
                }
            )

        return jsonify(
            {
                "storage_limit_bytes": tier.storage_limit_bytes or 0,
                "render_time_limit_seconds": tier.render_time_limit_seconds or 0,
                "apply_watermark": should_apply_watermark(user),
                "is_unlimited": tier.is_unlimited,
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


# ============================================================================
# Phase 4: Batch endpoints for compile_video_task migration
# ============================================================================


@api_bp.route("/worker/projects/<int:project_id>/compilation-context", methods=["GET"])
@require_worker_key
def worker_get_compilation_context(project_id: int):
    """Get all data needed for video compilation in a single call.

    Returns project metadata, ordered clips with media files, and tier limits.
    Avoids N+1 queries by fetching everything in one batch.

    Response:
        {
            "project": {
                "id": int,
                "user_id": int,
                "name": str,
                "output_resolution": str,
                "output_format": str,
                "max_clip_duration": float | None,
                ...
            },
            "clips": [
                {
                    "id": int,
                    "order_index": int,
                    "start_time": float | None,
                    "end_time": float | None,
                    "creator_name": str | None,
                    "game_name": str | None,
                    "media_file": {
                        "id": int,
                        "file_path": str,
                        "duration": float,
                        ...
                    }
                }
            ],
            "tier_limits": {
                "max_res_label": str | None,
                "max_fps": int | None,
                "max_clips": int | None
            }
        }
    """
    try:
        project = Project.query.get(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Get ordered clips with eager-loaded media files
        clips = (
            Clip.query.filter_by(project_id=project_id)
            .order_by(Clip.order_index, Clip.id)
            .all()
        )

        # Get tier limits
        from app.models import User

        user = User.query.get(project.user_id)
        tier_limits = {"max_res_label": None, "max_fps": None, "max_clips": None}

        if user and hasattr(user, "tier") and user.tier:
            if not user.tier.is_unlimited:
                tier_limits = {
                    "max_res_label": user.tier.max_output_resolution,
                    "max_fps": user.tier.max_fps,
                    "max_clips": user.tier.max_clips_per_project,
                }

        # Serialize response
        return jsonify(
            {
                "project": {
                    "id": project.id,
                    "user_id": project.user_id,
                    "name": project.name or "",
                    "output_resolution": project.output_resolution or "1920x1080",
                    "output_format": project.output_format or "mp4",
                    "max_clip_duration": project.max_clip_duration,
                },
                "clips": [
                    {
                        "id": clip.id,
                        "order_index": clip.order_index or 0,
                        "start_time": clip.start_time,
                        "end_time": clip.end_time,
                        "creator_name": clip.creator_name,
                        "game_name": clip.game_name,
                        "media_file": (
                            {
                                "id": clip.media_file.id,
                                "file_path": clip.media_file.file_path or "",
                                "duration": clip.media_file.duration,
                                "width": clip.media_file.width,
                                "height": clip.media_file.height,
                                "framerate": clip.media_file.framerate,
                            }
                            if clip.media_file
                            else None
                        ),
                    }
                    for clip in clips
                ],
                "tier_limits": tier_limits,
            }
        )
    except Exception as e:
        current_app.logger.error(
            f"Error fetching compilation context for project {project_id}: {e}"
        )
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/media/batch", methods=["POST"])
@require_worker_key
def worker_get_media_batch():
    """Get multiple MediaFile records by IDs in a single query.

    Used for fetching intro/outro/transitions efficiently.

    Request body:
        {
            "media_ids": [int, ...],
            "user_id": int  # For ownership validation
        }

    Response:
        {
            "media_files": [
                {
                    "id": int,
                    "file_path": str,
                    "media_type": str,
                    "duration": float,
                    ...
                }
            ]
        }
    """
    try:
        data = request.get_json() or {}
        media_ids = data.get("media_ids", [])
        user_id = data.get("user_id")

        if not isinstance(media_ids, list):
            return jsonify({"error": "media_ids must be a list"}), 400

        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        # Batch fetch with ownership validation
        media_files = (
            MediaFile.query.filter(
                MediaFile.id.in_(media_ids), MediaFile.user_id == user_id
            ).all()
            if media_ids
            else []
        )

        # Verify all files exist on disk
        existing_media = []
        for mf in media_files:
            if mf.file_path and os.path.exists(mf.file_path):
                existing_media.append(mf)
            else:
                current_app.logger.warning(
                    f"Media file {mf.id} not found on disk: {mf.file_path}"
                )

        return jsonify(
            {
                "media_files": [
                    {
                        "id": mf.id,
                        "file_path": mf.file_path or "",
                        "media_type": mf.media_type.value if mf.media_type else None,
                        "duration": mf.duration,
                        "width": mf.width,
                        "height": mf.height,
                        "framerate": mf.framerate,
                    }
                    for mf in existing_media
                ]
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error fetching media batch: {e}")
        return jsonify({"error": "Internal error"}), 500
