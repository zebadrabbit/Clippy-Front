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

import mimetypes
import os
from datetime import datetime
from functools import wraps

from flask import current_app, jsonify, request, send_file

from app import storage as storage_lib
from app.api import api_bp
from app.models import Clip, MediaFile, MediaType, ProcessingJob, Project, db


def _download_creator_avatar(clip: Clip) -> bool:
    """Download and cache creator avatar for a clip.

    Args:
        clip: Clip object with creator_id and creator_name populated

    Returns:
        True if avatar was downloaded/found, False otherwise
    """
    if not clip.creator_id or not clip.creator_name:
        return False

    try:
        import glob
        import re

        import requests as _requests

        from app.integrations.twitch import get_user_profile_image_url

        current_app.logger.info(
            f"Processing avatar for {clip.creator_name} (ID: {clip.creator_id})"
        )

        # Sanitize creator name for filename
        safe_name = re.sub(r"[^a-z0-9_-]+", "_", clip.creator_name.strip().lower())

        # Prepare avatars directory
        avatars_dir = os.path.join(current_app.instance_path, "assets", "avatars")
        os.makedirs(avatars_dir, exist_ok=True)

        # Check if an avatar already exists for this creator
        existing_avatar = None
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            exact_match = os.path.join(avatars_dir, f"{safe_name}{ext}")
            if os.path.isfile(exact_match):
                existing_avatar = exact_match
                break
            matches = glob.glob(os.path.join(avatars_dir, f"{safe_name}_*{ext}"))
            if matches:
                matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                existing_avatar = matches[0]
                break

        if existing_avatar:
            clip.creator_avatar_path = existing_avatar
            current_app.logger.info(
                f"Reusing existing avatar for {clip.creator_name}: {existing_avatar}"
            )
            return True

        # Download new avatar
        avatar_url = get_user_profile_image_url(clip.creator_id)
        if not avatar_url:
            current_app.logger.warning(
                f"No avatar URL available for {clip.creator_name}"
            )
            return False

        current_app.logger.info(f"Downloading avatar from: {avatar_url}")
        ext = os.path.splitext(avatar_url.split("?")[0])[1] or ".jpg"
        avatar_filename = f"{safe_name}{ext}"
        avatar_path = os.path.join(avatars_dir, avatar_filename)

        resp = _requests.get(avatar_url, timeout=10)
        resp.raise_for_status()
        with open(avatar_path, "wb") as f:
            f.write(resp.content)

        clip.creator_avatar_path = avatar_path
        current_app.logger.info(f"Downloaded avatar to: {avatar_path}")
        return True

    except Exception as avatar_err:
        current_app.logger.warning(
            f"Failed to download avatar for {clip.creator_name}: {avatar_err}"
        )
        return False


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
        clip = db.session.get(Clip, clip_id)
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
        clip = db.session.get(Clip, clip_id)
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


@api_bp.route("/worker/clips/<int:clip_id>/enrich", methods=["POST"])
@require_worker_key
def worker_enrich_clip_metadata(clip_id: int):
    """Enrich clip with Twitch metadata (creator, game, date, avatar).

    Request body:
        {
            "source_url": str
        }

    Returns:
        {"status": "enriched", "clip_id": int} or {"status": "skipped"}
    """
    try:
        clip = db.session.get(Clip, clip_id)
        if not clip:
            return jsonify({"error": "Clip not found"}), 404

        data = request.get_json() or {}
        source_url = data.get("source_url", clip.source_url)

        if not source_url or "twitch" not in source_url.lower():
            return jsonify({"status": "skipped", "reason": "Not a Twitch URL"})

        # Extract clip slug and enrich metadata
        import re

        from app.integrations.twitch import get_clip_by_id

        match = re.search(
            r"(?:clips?\.twitch\.tv/|twitch\.tv/.+/clip/)([^/?&#]+)",
            source_url,
        )
        if not match:
            return jsonify({"status": "skipped", "reason": "Could not extract clip ID"})

        clip_slug = match.group(1)
        twitch_clip = get_clip_by_id(clip_slug)

        if not twitch_clip:
            return jsonify(
                {"status": "skipped", "reason": "No metadata from Twitch API"}
            )

        # Update clip metadata
        if twitch_clip.creator_name:
            clip.creator_name = twitch_clip.creator_name
        if twitch_clip.creator_id:
            clip.creator_id = twitch_clip.creator_id
        if twitch_clip.game_name:
            clip.game_name = twitch_clip.game_name
        if twitch_clip.created_at:
            try:
                clip.clip_created_at = datetime.fromisoformat(
                    twitch_clip.created_at.replace("Z", "+00:00")
                )
            except Exception:
                pass
        if twitch_clip.title and (not clip.title or clip.title.startswith("Clip ")):
            clip.title = twitch_clip.title

        db.session.commit()

        # Download avatar (always attempt, helper will reuse if exists)
        _download_creator_avatar(clip)
        db.session.commit()

        return jsonify({"status": "enriched", "clip_id": clip_id})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error enriching clip {clip_id}: {e}", exc_info=True)
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
        media = db.session.get(MediaFile, media_id)
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
        job = db.session.get(ProcessingJob, job_id)
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
        job = db.session.get(ProcessingJob, job_id)
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
        project = db.session.get(Project, project_id)
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
        project = db.session.get(Project, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        data = request.get_json() or {}

        if "status" in data:
            from app.models import ProjectStatus

            # Normalize status to uppercase to match enum values
            status_value = str(data["status"]).upper()
            project.status = ProjectStatus(status_value)

        if "output_filename" in data:
            project.output_filename = data["output_filename"]

        if "output_file_size" in data:
            project.output_file_size = int(data["output_file_size"])

        if "completed_at" in data:
            project.completed_at = datetime.fromisoformat(data["completed_at"])
        elif data.get("status", "").upper() == "COMPLETED":
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

        user = db.session.get(User, user_id)
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
            "is_unlimited": bool,
            "watermark_path": str | None,
            "watermark_opacity": float,
            "watermark_position": str
        }
    """
    try:
        from app.models import SystemSetting, User
        from app.quotas import get_effective_tier, should_apply_watermark

        user = db.session.get(User, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        tier = get_effective_tier(user)

        # Get watermark settings from system settings
        watermark_path = None
        watermark_opacity = 0.3
        watermark_position = "bottom-right"

        try:
            wm_path_setting = SystemSetting.query.filter_by(
                key="WATERMARK_PATH"
            ).first()
            if wm_path_setting and wm_path_setting.value:
                watermark_path = wm_path_setting.value

            wm_opacity_setting = SystemSetting.query.filter_by(
                key="WATERMARK_OPACITY"
            ).first()
            if wm_opacity_setting and wm_opacity_setting.value:
                watermark_opacity = float(wm_opacity_setting.value)

            wm_pos_setting = SystemSetting.query.filter_by(
                key="WATERMARK_POSITION"
            ).first()
            if wm_pos_setting and wm_pos_setting.value:
                watermark_position = wm_pos_setting.value
        except Exception as wm_err:
            current_app.logger.warning(f"Error loading watermark settings: {wm_err}")

        if not tier:
            # Return sensible defaults if no tier
            return jsonify(
                {
                    "storage_limit_bytes": 0,
                    "render_time_limit_seconds": 0,
                    "apply_watermark": True,
                    "is_unlimited": False,
                    "watermark_path": watermark_path,
                    "watermark_opacity": watermark_opacity,
                    "watermark_position": watermark_position,
                }
            )

        return jsonify(
            {
                "storage_limit_bytes": tier.storage_limit_bytes or 0,
                "render_time_limit_seconds": tier.render_time_limit_seconds or 0,
                "apply_watermark": should_apply_watermark(user),
                "is_unlimited": tier.is_unlimited,
                "watermark_path": watermark_path,
                "watermark_opacity": watermark_opacity,
                "watermark_position": watermark_position,
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

        user = db.session.get(User, user_id)
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


@api_bp.route(
    "/worker/projects/<int:project_id>/clips/<int:clip_id>/upload", methods=["POST"]
)
@require_worker_key
def worker_upload_clip(project_id: int, clip_id: int):
    """Upload clip video and thumbnail from worker after download.

    Multipart form data:
        - video: video file
        - thumbnail: thumbnail image (optional)
        - metadata: JSON string with {duration, width, height, framerate, file_size, source_id}

    Returns:
        {
            "status": "uploaded",
            "media_id": int,
            "clip_id": int,
            "file_path": str,
            "thumbnail_path": str
        }
    """
    try:
        # Verify project and clip exist
        project = db.session.get(Project, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        clip = db.session.get(Clip, clip_id)
        if not clip or clip.project_id != project_id:
            return jsonify({"error": "Clip not found or wrong project"}), 404

        # Get files from request
        if "video" not in request.files:
            return jsonify({"error": "No video file provided"}), 400

        video_file = request.files["video"]
        thumbnail_file = request.files.get("thumbnail")

        # Get metadata
        metadata_str = request.form.get("metadata", "{}")
        try:
            import json

            metadata = json.loads(metadata_str)
        except Exception:
            metadata = {}

        # Build storage path using storage.clips_dir()
        from app.storage import clips_dir as get_clips_dir

        clips_dir = get_clips_dir(project.owner, project.name)
        os.makedirs(clips_dir, exist_ok=True)

        # Use source_id for filename if available
        source_id = metadata.get("source_id") or clip.source_id or f"clip_{clip_id}"
        video_filename = f"{source_id}.mp4"
        thumbnail_filename = f"{source_id}.jpg"

        video_path = os.path.join(clips_dir, video_filename)
        thumbnail_path = (
            os.path.join(clips_dir, thumbnail_filename) if thumbnail_file else None
        )

        # Save video file
        video_file.save(video_path)
        current_app.logger.info(f"Saved clip video to {video_path}")

        # Save thumbnail if provided
        if thumbnail_file and thumbnail_path:
            thumbnail_file.save(thumbnail_path)
            current_app.logger.info(f"Saved thumbnail to {thumbnail_path}")

        # Create MediaFile record
        media = MediaFile(
            filename=video_filename,
            original_filename=video_file.filename,
            file_path=video_path,
            file_size=metadata.get("file_size", os.path.getsize(video_path)),
            mime_type="video/mp4",
            media_type=MediaType.CLIP,
            user_id=project.user_id,
            project_id=project_id,
            duration=metadata.get("duration"),
            width=metadata.get("width"),
            height=metadata.get("height"),
            framerate=metadata.get("framerate"),
            thumbnail_path=thumbnail_path,
            is_processed=True,
        )
        db.session.add(media)
        db.session.flush()

        # Link MediaFile to Clip
        clip.media_file_id = media.id
        clip.is_downloaded = True
        if metadata.get("duration"):
            clip.duration = metadata["duration"]

        db.session.commit()

        current_app.logger.info(
            f"Worker uploaded clip {clip_id} -> MediaFile {media.id} for project {project_id}"
        )

        # Enrich Twitch metadata synchronously (runs server-side with secrets)
        if clip.source_url and "twitch" in clip.source_url.lower():
            try:
                import re

                from app.integrations.twitch import get_clip_by_id

                current_app.logger.info(
                    f"Attempting to enrich Twitch metadata for clip {clip_id}, URL: {clip.source_url}"
                )

                # Extract clip slug from URL
                match = re.search(
                    r"(?:clips?\.twitch\.tv/|twitch\.tv/.+/clip/)([^/?&#]+)",
                    clip.source_url,
                )
                if match:
                    clip_slug = match.group(1)
                    current_app.logger.info(f"Extracted clip slug: {clip_slug}")

                    twitch_clip = get_clip_by_id(clip_slug)
                    if twitch_clip:
                        current_app.logger.info(
                            f"Got Twitch metadata: creator={twitch_clip.creator_name}, game={twitch_clip.game_name}"
                        )

                        # Update clip with metadata (always update, not just if empty)
                        if twitch_clip.creator_name:
                            clip.creator_name = twitch_clip.creator_name
                        if twitch_clip.creator_id:
                            clip.creator_id = twitch_clip.creator_id
                        if twitch_clip.game_name:
                            clip.game_name = twitch_clip.game_name
                        if twitch_clip.created_at:
                            try:
                                from datetime import datetime

                                clip.clip_created_at = datetime.fromisoformat(
                                    twitch_clip.created_at.replace("Z", "+00:00")
                                )
                            except Exception as dt_err:
                                current_app.logger.warning(
                                    f"Failed to parse created_at: {dt_err}"
                                )
                        if twitch_clip.title:
                            # Only override generic titles
                            if not clip.title or clip.title.startswith("Clip "):
                                clip.title = twitch_clip.title

                        db.session.commit()
                        current_app.logger.info(
                            f"Successfully enriched clip {clip_id} with Twitch metadata"
                        )
                    else:
                        current_app.logger.warning(
                            f"Twitch API returned no data for clip slug: {clip_slug}"
                        )
                else:
                    current_app.logger.warning(
                        f"Could not extract clip slug from URL: {clip.source_url}"
                    )
            except Exception as enrich_err:
                current_app.logger.error(
                    f"Failed to enrich clip {clip_id} metadata: {enrich_err}",
                    exc_info=True,
                )

        # Download creator avatar AFTER enrichment (so we have creator_id and creator_name)
        _download_creator_avatar(clip)
        db.session.commit()

        return jsonify(
            {
                "status": "uploaded",
                "media_id": media.id,
                "clip_id": clip_id,
                "file_path": video_path,
                "thumbnail_path": thumbnail_path,
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error uploading clip {clip_id}: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/worker/projects/<int:project_id>/preview/upload", methods=["POST"])
@require_worker_key
def worker_upload_preview(project_id: int):
    """Upload preview video from worker after rendering.

    Multipart form data:
        - preview: preview video file
        - metadata: JSON string with {file_size, clips_used}

    Returns:
        {
            "status": "uploaded",
            "project_id": int,
            "preview_filename": str,
            "preview_path": str
        }
    """
    try:
        # Verify project exists
        project = db.session.get(Project, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Get preview file from request
        if "preview" not in request.files:
            return jsonify({"error": "No preview file provided"}), 400

        preview_file = request.files["preview"]

        # Get metadata
        metadata_str = request.form.get("metadata", "{}")
        try:
            import json

            metadata = json.loads(metadata_str)
        except Exception:
            metadata = {}

        # Build storage path in instance/previews/<user_id>/
        preview_dir = os.path.join(
            current_app.instance_path, "previews", str(project.user_id)
        )
        os.makedirs(preview_dir, exist_ok=True)

        # Consistent naming
        preview_filename = f"preview_{project_id}.mp4"
        preview_path = os.path.join(preview_dir, preview_filename)

        # Save preview file
        preview_file.save(preview_path)
        current_app.logger.info(f"Saved preview video to {preview_path}")

        # Update project with preview info
        project.preview_filename = preview_filename
        project.preview_file_size = metadata.get(
            "file_size", os.path.getsize(preview_path)
        )

        db.session.commit()

        current_app.logger.info(
            f"Worker uploaded preview for project {project_id}: {preview_filename}"
        )

        return jsonify(
            {
                "status": "uploaded",
                "project_id": project_id,
                "preview_filename": preview_filename,
                "preview_path": preview_path,
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Preview upload failed for project {project_id}: {e}", exc_info=True
        )
        return jsonify({"error": str(e)}), 500


def _cleanup_old_compilations(
    output_dir: str, keep_count: int = 3, project_id: int | None = None
) -> None:
    """Remove old compilation files, keeping only the most recent ones.

    Args:
        output_dir: Directory containing compilation files
        keep_count: Number of most recent compilations to keep (default 3)
        project_id: Optional project ID to also clean up database records
    """
    try:
        # Get all video files in compilations directory
        video_files = []
        for filename in os.listdir(output_dir):
            file_path = os.path.join(output_dir, filename)
            if os.path.isfile(file_path) and filename.endswith(
                (".mp4", ".webm", ".mov")
            ):
                mtime = os.path.getmtime(file_path)
                video_files.append((mtime, file_path, filename))

        # Sort by modification time (newest first)
        video_files.sort(reverse=True, key=lambda x: x[0])

        # Collect stems of videos we're keeping
        kept_stems = set()
        for _, _, filename in video_files[:keep_count]:
            stem = os.path.splitext(filename)[0]
            kept_stems.add(stem)

        # Delete old compilations beyond keep_count
        for _, file_path, filename in video_files[keep_count:]:
            try:
                os.remove(file_path)
                current_app.logger.info(f"Deleted old compilation: {filename}")

                # Also delete associated thumbnail if it exists
                stem = os.path.splitext(filename)[0]
                thumb_path = os.path.join(output_dir, f"{stem}.jpg")
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
                    current_app.logger.info(f"Deleted old thumbnail: {stem}.jpg")
            except Exception as e:
                current_app.logger.warning(
                    f"Failed to delete old compilation {filename}: {e}"
                )

        # Clean up orphaned thumbnails (thumbnails without corresponding videos)
        for filename in os.listdir(output_dir):
            if filename.endswith(".jpg"):
                stem = os.path.splitext(filename)[0]
                if stem not in kept_stems:
                    orphan_path = os.path.join(output_dir, filename)
                    try:
                        os.remove(orphan_path)
                        current_app.logger.info(
                            f"Deleted orphaned thumbnail: {filename}"
                        )
                    except Exception as e:
                        current_app.logger.warning(
                            f"Failed to delete orphaned thumbnail {filename}: {e}"
                        )

    except Exception as e:
        # Don't fail compilation if cleanup fails
        current_app.logger.warning(f"Compilation cleanup failed: {e}")


@api_bp.route("/worker/projects/<int:project_id>/compilation/upload", methods=["POST"])
@require_worker_key
def worker_upload_compilation(project_id: int):
    """Upload compiled video and thumbnail from worker after rendering.

    Multipart form data:
        - video: compiled video file
        - thumbnail: thumbnail image (optional)
        - metadata: JSON string with {duration, width, height, framerate, file_size, filename}

    Returns:
        {
            "status": "uploaded",
            "media_id": int,
            "project_id": int,
            "file_path": str,
            "thumbnail_path": str
        }
    """
    try:
        # Verify project exists
        project = db.session.get(Project, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Get files from request
        if "video" not in request.files:
            return jsonify({"error": "No video file provided"}), 400

        video_file = request.files["video"]
        thumbnail_file = request.files.get("thumbnail")

        # Get metadata
        metadata_str = request.form.get("metadata", "{}")
        try:
            import json

            metadata = json.loads(metadata_str)
        except Exception:
            metadata = {}

        # Build storage path using storage.compilations_dir()
        from app.storage import compilations_dir as get_compilations_dir

        compilations_dir = get_compilations_dir(project.owner, project.name)
        os.makedirs(compilations_dir, exist_ok=True)

        # Clean up old compilations (keep most recent 3)
        _cleanup_old_compilations(compilations_dir, keep_count=3, project_id=project.id)

        # Use filename from metadata or generate one
        video_filename = metadata.get("filename") or f"compilation_{project_id}.mp4"
        # Strip path components if any
        video_filename = os.path.basename(video_filename)

        video_path = os.path.join(compilations_dir, video_filename)

        # Generate thumbnail filename
        stem = os.path.splitext(video_filename)[0]
        thumbnail_filename = f"{stem}.jpg"
        thumbnail_path = (
            os.path.join(compilations_dir, thumbnail_filename)
            if thumbnail_file
            else None
        )

        # Save video file
        video_file.save(video_path)
        current_app.logger.info(f"Saved compilation video to {video_path}")

        # Save thumbnail if provided
        if thumbnail_file and thumbnail_path:
            thumbnail_file.save(thumbnail_path)
            current_app.logger.info(f"Saved compilation thumbnail to {thumbnail_path}")

        # Create MediaFile record
        media = MediaFile(
            filename=video_filename,
            original_filename=video_file.filename,
            file_path=video_path,
            file_size=metadata.get("file_size", os.path.getsize(video_path)),
            mime_type="video/mp4",
            media_type=MediaType.COMPILATION,
            user_id=project.user_id,
            project_id=project_id,
            duration=metadata.get("duration"),
            width=metadata.get("width"),
            height=metadata.get("height"),
            framerate=metadata.get("framerate"),
            thumbnail_path=thumbnail_path,
            is_processed=True,
        )
        db.session.add(media)
        db.session.flush()

        # Update project with output file info
        project.output_filename = video_filename
        project.output_file_size = os.path.getsize(video_path)

        db.session.commit()

        current_app.logger.info(
            f"Worker uploaded compilation -> MediaFile {media.id} for project {project_id}"
        )

        return jsonify(
            {
                "status": "uploaded",
                "media_id": media.id,
                "project_id": project_id,
                "file_path": video_path,
                "thumbnail_path": thumbnail_path,
            }
        )

    except Exception as e:
        db.session.rollback()

        # Provide clearer error message for file size limit
        error_msg = str(e)
        if "413" in error_msg or "Request Entity Too Large" in error_msg:
            max_size_gb = current_app.config.get("MAX_CONTENT_LENGTH", 0) / (
                1024 * 1024 * 1024
            )
            error_msg = f"File size exceeds maximum allowed ({max_size_gb:.1f}GB). Consider increasing MAX_CONTENT_LENGTH."

        current_app.logger.error(
            f"Error uploading compilation for project {project_id}: {error_msg}"
        )
        import traceback

        traceback.print_exc()
        return jsonify({"error": error_msg}), 500


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
        project = db.session.get(Project, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Get ordered clips with eager-loaded media files
        from sqlalchemy.orm import joinedload

        clips = (
            Clip.query.filter_by(project_id=project_id)
            .options(joinedload(Clip.media_file))
            .order_by(Clip.order_index, Clip.id)
            .all()
        )

        # Get tier limits
        from app.models import SystemSetting, User

        user = db.session.get(User, project.user_id)
        tier_limits = {
            "max_res_label": None,
            "max_fps": None,
            "max_clips": None,
            "apply_watermark": False,
            "watermark_path": None,
            "watermark_opacity": 0.3,
            "watermark_position": "bottom-right",
            "watermark_size": 150,
        }
        username = None

        if user:
            username = user.username

            # Get watermark settings
            from app.quotas import should_apply_watermark

            apply_wm = should_apply_watermark(user)
            tier_limits["apply_watermark"] = apply_wm

            if apply_wm:
                # Get watermark configuration from SystemSettings
                try:
                    wm_path_setting = SystemSetting.query.filter_by(
                        key="WATERMARK_PATH"
                    ).first()
                    if wm_path_setting and wm_path_setting.value:
                        tier_limits["watermark_path"] = wm_path_setting.value

                    wm_opacity_setting = SystemSetting.query.filter_by(
                        key="WATERMARK_OPACITY"
                    ).first()
                    if wm_opacity_setting and wm_opacity_setting.value:
                        tier_limits["watermark_opacity"] = float(
                            wm_opacity_setting.value
                        )

                    wm_pos_setting = SystemSetting.query.filter_by(
                        key="WATERMARK_POSITION"
                    ).first()
                    if wm_pos_setting and wm_pos_setting.value:
                        tier_limits["watermark_position"] = wm_pos_setting.value

                    wm_size_setting = SystemSetting.query.filter_by(
                        key="WATERMARK_SIZE"
                    ).first()
                    if wm_size_setting and wm_size_setting.value:
                        tier_limits["watermark_size"] = int(wm_size_setting.value)
                except Exception as wm_err:
                    current_app.logger.warning(
                        f"Error loading watermark settings: {wm_err}"
                    )

            # Get tier-specific limits
            if hasattr(user, "tier") and user.tier and not user.tier.is_unlimited:
                tier_limits["max_res_label"] = user.tier.max_output_resolution
                tier_limits["max_fps"] = user.tier.max_fps
                tier_limits["max_clips"] = user.tier.max_clips_per_project

        # Serialize response
        return jsonify(
            {
                "project": {
                    "id": project.id,
                    "user_id": project.user_id,
                    "username": username,
                    "name": project.name or "",
                    "output_resolution": project.output_resolution or "1920x1080",
                    "output_format": project.output_format or "mp4",
                    "max_clip_duration": project.max_clip_duration,
                    "vertical_zoom": project.vertical_zoom or 100,
                    "vertical_align": project.vertical_align or "center",
                    "duck_threshold": project.duck_threshold or 0.02,
                    "duck_ratio": project.duck_ratio or 20.0,
                    "duck_attack": project.duck_attack or 1.0,
                    "duck_release": project.duck_release or 250.0,
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

        # Batch fetch with ownership validation (allow public or owned by user)
        from sqlalchemy import or_

        media_files = (
            MediaFile.query.filter(
                MediaFile.id.in_(media_ids),
                or_(MediaFile.user_id == user_id, MediaFile.is_public.is_(True)),
            ).all()
            if media_ids
            else []
        )

        # Verify all files exist on disk
        from app import storage as storage_lib

        existing_media = []
        for mf in media_files:
            # Expand canonical /instance/... paths to absolute paths
            abs_path = storage_lib.instance_expand(mf.file_path)
            if abs_path and os.path.exists(abs_path):
                existing_media.append(mf)
            else:
                current_app.logger.warning(
                    f"Media file {mf.id} not found on disk: {mf.file_path} (expanded: {abs_path})"
                )

        return jsonify(
            {
                "media_files": [
                    {
                        "id": mf.id,
                        "file_path": storage_lib.instance_expand(mf.file_path)
                        or mf.file_path
                        or "",
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


@api_bp.route("/worker/media/<int:media_id>/download", methods=["GET"])
@require_worker_key
def worker_download_media(media_id):
    """Download a media file by ID.

    Remote workers use this to download clips, intros, outros, and transitions
    needed for compilation when they don't have shared filesystem access.

    Query params:
        user_id: int - Required for ownership validation

    Response:
        - 200: File content with proper Content-Type and Content-Disposition headers
        - 404: File not found or doesn't exist on disk
        - 401: Unauthorized (wrong/missing user_id)
    """
    try:
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        # Fetch media file with ownership validation (allow public or owned by user)
        from sqlalchemy import or_

        media_file = MediaFile.query.filter(
            MediaFile.id == media_id,
            or_(MediaFile.user_id == user_id, MediaFile.is_public.is_(True)),
        ).first()
        if not media_file:
            current_app.logger.warning(
                f"Media file {media_id} not found or not accessible by user {user_id}"
            )
            return jsonify({"error": "Media file not found"}), 404

        # Check if file exists on disk (expand canonical path first)
        file_path = storage_lib.instance_expand(media_file.file_path)
        if not file_path or not os.path.exists(file_path):
            current_app.logger.error(
                f"Media file {media_id} path not found on disk: {media_file.file_path} (expanded: {file_path})"
            )
            return jsonify({"error": "File not found on disk"}), 404

        # Determine MIME type
        mimetype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        # Get filename from path
        filename = os.path.basename(file_path)

        current_app.logger.info(
            f"Worker downloading media {media_id} ({filename}) for user {user_id}"
        )

        # Send file with proper headers
        return send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        current_app.logger.error(f"Error downloading media {media_id}: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route("/worker/avatar/<creator_name>", methods=["GET"])
@require_worker_key
def worker_download_avatar(creator_name):
    """Download an avatar file by creator name.

    Remote workers use this to download creator avatars for video overlays
    when they don't have shared filesystem access.

    Response:
        - 200: Avatar file content with proper Content-Type and Content-Disposition headers
        - 404: Avatar not found
    """
    try:
        import glob
        import re

        # Sanitize creator name
        safe_name = re.sub(r"[^\w\-_]", "_", creator_name.lower())

        # Check AVATARS_PATH environment variable first
        avatars_path = os.environ.get("AVATARS_PATH", "")
        avatar_file = None

        if avatars_path:
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidate = os.path.join(avatars_path, f"{safe_name}{ext}")
                if os.path.isfile(candidate):
                    avatar_file = candidate
                    break

        # Check instance/assets/avatars (standard location)
        if not avatar_file:
            instance_path = (
                current_app.config.get("INSTANCE_PATH") or current_app.instance_path
            )
            default_avatars = os.path.join(instance_path, "assets", "avatars")
            if os.path.isdir(default_avatars):
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    # Try exact match first
                    exact_match = os.path.join(default_avatars, f"{safe_name}{ext}")
                    if os.path.isfile(exact_match):
                        avatar_file = exact_match
                        break
                    # Try wildcard pattern (handles old random suffix format)
                    matches = glob.glob(
                        os.path.join(default_avatars, f"{safe_name}_*{ext}")
                    )
                    if matches:
                        # Use most recent
                        matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                        avatar_file = matches[0]
                        break

        if not avatar_file:
            current_app.logger.warning(f"Avatar not found for creator '{creator_name}'")
            return jsonify({"error": "Avatar not found"}), 404

        # Determine MIME type
        mimetype = mimetypes.guess_type(avatar_file)[0] or "image/png"
        filename = os.path.basename(avatar_file)

        current_app.logger.info(
            f"Worker downloading avatar for '{creator_name}' ({filename})"
        )

        # Send file with proper headers
        return send_file(
            avatar_file,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        current_app.logger.error(f"Error downloading avatar for '{creator_name}': {e}")
        return jsonify({"error": "Internal error"}), 500
