"""
API routes and endpoints.
"""
# ruff: noqa: I001  # Suppress import-sorting cosmetic warning for this file
from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import current_user, login_required

from app.integrations.discord import extract_clip_urls, get_channel_messages
from app.integrations.twitch import (
    get_clips as twitch_get_clips,
    get_user_id as twitch_get_user_id,
)
from app.models import db, Clip, ProcessingJob, Project, ProjectStatus
from app.tasks.background_tasks import example_long_task

api_bp = Blueprint("api", __name__)


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "message": "Clippy API is running"})


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

    def _safe_json(val):
        """Safely convert arbitrary objects (including Exceptions) into JSON-serializable structures."""
        try:
            # Pass through simple JSON-native types quickly
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
            # Handle common non-serializable types like Exceptions
            if isinstance(val, BaseException):
                return {"type": type(val).__name__, "message": str(val)}
            # Fallback to string representation
            return str(val)
        except Exception as e:  # Defensive: never raise from serializer
            return {"type": type(val).__name__, "message": f"<unserializable: {e}>"}

    # Provide richer state info including progress metadata when available
    payload = {
        "task_id": task_id,
        "status": task.status,  # e.g., PENDING, STARTED, PROGRESS, SUCCESS, FAILURE
        "state": task.state,
        "ready": task.ready(),
    }
    try:
        info = task.info  # may contain {progress, status, ...} or an Exception
        if info is not None:
            payload["info"] = _safe_json(info)
    except Exception as e:
        current_app.logger.debug(f"Task info retrieval error: {e}")

    if task.ready():
        try:
            payload["result"] = _safe_json(task.result)
        except Exception as e:
            payload["result"] = None
            payload["error"] = str(e)

    # When FAILED, surface a simple error string for convenience
    if task.state == "FAILURE":
        try:
            payload.setdefault(
                "error", str(task.info) if task.info is not None else "Unknown error"
            )
        except Exception:
            payload.setdefault("error", "Unknown error")

    return jsonify(payload)


@api_bp.route("/jobs/recent", methods=["GET"])
@login_required
def recent_jobs_api():
    """Return recent processing jobs for the current user to power notifications.

    Query params:
      - limit: number of jobs to return (default 10, max 50)
    """
    limit = max(1, min(50, request.args.get("limit", default=10, type=int)))
    jobs = (
        ProcessingJob.query.filter_by(user_id=current_user.id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(limit)
        .all()
    )

    def serialize_job(job: ProcessingJob) -> dict:
        rd = job.result_data or {}
        logs = rd.get("logs") or []
        last_log = logs[-1] if logs else None
        return {
            "id": job.id,
            "celery_task_id": job.celery_task_id,
            "job_type": job.job_type,
            "project_id": job.project_id,
            "status": job.status,
            "progress": job.progress,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error_message": job.error_message,
            "result_data": {k: v for k, v in (rd.items()) if k != "logs"},
            "last_log": last_log,
        }

    return jsonify({"items": [serialize_job(j) for j in jobs], "count": len(jobs)})


@api_bp.route("/jobs/<int:job_id>", methods=["GET"])
@login_required
def job_details_api(job_id: int):
    """Return full job details including logs for a specific job."""
    job = ProcessingJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({"error": "Job not found"}), 404

    rd = job.result_data or {}
    project_name = None
    if job.project_id:
        proj = Project.query.get(job.project_id)
        project_name = proj.name if proj else None

    return jsonify(
        {
            "id": job.id,
            "celery_task_id": job.celery_task_id,
            "job_type": job.job_type,
            "project_id": job.project_id,
            "project_name": project_name,
            "status": job.status,
            "progress": job.progress,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "result_data": rd,
            "error_message": job.error_message,
        }
    )


# Wizard/Project API endpoints


@api_bp.route("/projects", methods=["POST"])
@login_required
def create_project_api():
    """Create a new project via JSON API for the wizard flow.

    Expected JSON body:
      - name (str, required)
      - description (str, optional)
      - output_resolution (str, optional)
      - output_format (str, optional)
      - max_clip_duration (int, optional)
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Project name is required"}), 400

    description = (data.get("description") or "").strip() or None
    output_resolution = data.get("output_resolution") or "1080p"
    output_format = data.get("output_format") or "mp4"
    max_clip_duration = int(data.get("max_clip_duration") or 30)

    try:
        project = Project(
            name=name,
            description=description,
            user_id=current_user.id,
            max_clip_duration=max_clip_duration,
            output_resolution=output_resolution,
            output_format=output_format,
        )
        db.session.add(project)
        db.session.commit()
        return jsonify({"project_id": project.id, "status": "created"}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API project creation failed: {e}")
        return jsonify({"error": "Failed to create project"}), 500


@api_bp.route("/projects/<int:project_id>/clips/download", methods=["POST"])
@login_required
def create_and_download_clips_api(project_id: int):
    """Create Clip rows from a list of URLs and dispatch download tasks.

    Expected JSON body:
      - urls: list[str] of Twitch/YouTube/etc clip URLs

    Returns: { items: [ {clip_id, task_id, url} ] }
    """
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    # Accept either plain URLs or structured clips
    urls = data.get("urls") or []
    provided_clips = data.get("clips") or []
    # Optional client-provided limit; also respect project-level constraints later
    try:
        requested_limit = int(data.get("limit") or 0)
    except Exception:
        requested_limit = 0
    if not urls and not provided_clips:
        return jsonify({"error": "No URLs or clips provided"}), 400

    # Limit to a reasonable batch size and requested limit
    max_batch = 200
    if urls:
        urls = urls[:max_batch]
    if provided_clips:
        provided_clips = provided_clips[:max_batch]

    # Determine effective limit: requested_limit if set, otherwise length of inputs
    effective_limit = (
        requested_limit if requested_limit > 0 else (len(provided_clips) or len(urls))
    )
    # Hard cap effective limit as well
    effective_limit = max(1, min(effective_limit, max_batch))

    from app.tasks.video_processing import download_clip_task

    items = []
    try:
        order_base = project.clips.count() or 0
        idx = 0

        # Build a normalized set of URLs to avoid duplicates within this batch
        def normalize_url(u: str) -> str:
            try:
                u = (u or "").strip()
                if not u:
                    return ""
                # Drop query/hash and trailing slash for basic normalization
                base = u.split("?")[0].split("#")[0]
                if base.endswith("/"):
                    base = base[:-1]
                return base
            except Exception:
                return (u or "").strip()

        seen = set()

        # Helper to try reuse: returns (reused: bool, media_file, source_platform)
        def try_reuse(url_s: str):
            # Check if clip already exists in this project
            # Check if clip already exists in this project
            existing_here = (
                Clip.query.filter_by(project_id=project.id, source_url=url_s)
                .order_by(Clip.created_at.desc())
                .first()
            )
            if existing_here and existing_here.media_file_id:
                return True, existing_here.media_file, existing_here.source_platform
            # Find any previously downloaded clip by this user with same URL
            prev = (
                db.session.query(Clip)
                .join(Project, Project.id == Clip.project_id)
                .filter(
                    Project.user_id == current_user.id,
                    Clip.source_url == url_s,
                    Clip.media_file_id.isnot(None),
                )
                .order_by(Clip.created_at.desc())
                .first()
            )
            if prev and prev.media_file_id:
                return True, prev.media_file, prev.source_platform
            return False, None, None

        # Structured clips if provided
        for obj in provided_clips[:effective_limit]:
            try:
                url_s = (obj.get("url") or "").strip()
                if not url_s:
                    continue
                norm = normalize_url(url_s)
                if not norm or norm in seen:
                    # Duplicate in this batch
                    continue
                seen.add(norm)
                platform = (
                    "twitch"
                    if "twitch" in url_s
                    else ("discord" if "discord" in url_s else "external")
                )
                title = (obj.get("title") or f"Clip {order_base + idx + 1}").strip()
                creator_name = obj.get("creator_name")
                game_name = obj.get("game_name")
                clip_created_at = obj.get("created_at")
                # Attempt reuse
                reused, media_file, src_platform = try_reuse(norm)
                if reused and media_file:
                    clip = Clip(
                        title=title,
                        description=None,
                        source_platform=src_platform or platform,
                        source_url=url_s,
                        project_id=project.id,
                        order_index=order_base + idx,
                        creator_name=creator_name,
                        game_name=game_name,
                        media_file_id=media_file.id,
                        is_downloaded=True,
                        duration=media_file.duration,
                    )
                    # Parse created_at if present
                    if clip_created_at:
                        try:
                            from datetime import datetime

                            clip.clip_created_at = datetime.fromisoformat(
                                clip_created_at.replace("Z", "+00:00")
                            )
                        except Exception:
                            pass
                    db.session.add(clip)
                    db.session.flush()
                    items.append(
                        {
                            "clip_id": clip.id,
                            "task_id": None,
                            "url": url_s,
                            "reused": True,
                        }
                    )
                    idx += 1
                else:
                    clip = Clip(
                        title=title,
                        description=None,
                        source_platform=platform,
                        source_url=url_s,
                        project_id=project.id,
                        order_index=order_base + idx,
                        creator_name=creator_name,
                        game_name=game_name,
                    )
                    if clip_created_at:
                        try:
                            from datetime import datetime

                            clip.clip_created_at = datetime.fromisoformat(
                                clip_created_at.replace("Z", "+00:00")
                            )
                        except Exception:
                            pass
                    db.session.add(clip)
                    db.session.flush()
                    task = download_clip_task.delay(clip.id, url_s)
                    items.append({"clip_id": clip.id, "task_id": task.id, "url": url_s})
                    idx += 1
            except Exception:
                continue

        # Plain URLs fallback
        for url in urls[: max(0, effective_limit - len(items))]:
            url_s = (url or "").strip()
            if not url_s:
                continue
            norm = normalize_url(url_s)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            platform = (
                "twitch"
                if "twitch" in url_s
                else ("discord" if "discord" in url_s else "external")
            )
            # Attempt reuse
            reused, media_file, src_platform = try_reuse(norm)
            if reused and media_file:
                clip = Clip(
                    title=f"Clip {order_base + idx + 1}",
                    description=None,
                    source_platform=src_platform or platform,
                    source_url=url_s,
                    project_id=project.id,
                    order_index=order_base + idx,
                    media_file_id=media_file.id,
                    is_downloaded=True,
                    duration=media_file.duration,
                )
                db.session.add(clip)
                db.session.flush()
                items.append(
                    {
                        "clip_id": clip.id,
                        "task_id": None,
                        "url": url_s,
                        "reused": True,
                    }
                )
                idx += 1
            else:
                clip = Clip(
                    title=f"Clip {order_base + idx + 1}",
                    description=None,
                    source_platform=platform,
                    source_url=url_s,
                    project_id=project.id,
                    order_index=order_base + idx,
                )
                db.session.add(clip)
                db.session.flush()
                task = download_clip_task.delay(clip.id, url_s)
                items.append({"clip_id": clip.id, "task_id": task.id, "url": url_s})
                idx += 1

        db.session.commit()
        return jsonify({"items": items, "count": len(items)}), 202
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API download dispatch failed: {e}")
        return jsonify({"error": "Failed to dispatch downloads"}), 500


@api_bp.route("/projects/<int:project_id>/compile", methods=["POST"])
@login_required
def compile_project_api(project_id: int):
    """Start compilation task for a project."""
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if project.status == ProjectStatus.PROCESSING:
        return jsonify({"error": "Project is already being processed"}), 400
    if project.clips.count() == 0:
        return jsonify({"error": "Project has no clips to compile"}), 400

    try:
        from app.tasks.video_processing import compile_video_task

        # Optional selections from client
        data = request.get_json(silent=True) or {}
        intro_id = data.get("intro_id")
        outro_id = data.get("outro_id")

        project.status = ProjectStatus.PROCESSING
        db.session.commit()

        task = compile_video_task.delay(
            project_id, intro_id=intro_id, outro_id=outro_id
        )
        return jsonify({"task_id": task.id, "status": "started"}), 202
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API compile start failed: {e}")
        return jsonify({"error": "Failed to start compilation"}), 500


@api_bp.route("/projects/<int:project_id>/clips", methods=["GET"])
@login_required
def list_project_clips_api(project_id: int):
    """List clips for a project with basic media info for UI rendering."""
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    clips = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc()).all()
    items = []
    for c in clips:
        media = c.media_file
        items.append(
            {
                "id": c.id,
                "title": c.title,
                "source_url": c.source_url,
                "is_downloaded": c.is_downloaded,
                "duration": c.duration,
                "creator_name": c.creator_name,
                "game_name": c.game_name,
                "created_at": c.clip_created_at.isoformat()
                if c.clip_created_at
                else None,
                "media": (
                    {
                        "id": media.id,
                        "mime": media.mime_type,
                        "filename": media.filename,
                        "thumbnail_url": url_for(
                            "main.media_thumbnail", media_id=media.id
                        )
                        if media
                        else None,
                        "preview_url": url_for("main.media_preview", media_id=media.id)
                        if media
                        else None,
                    }
                    if media
                    else None
                ),
            }
        )

    return jsonify({"items": items, "count": len(items)})


@api_bp.route("/twitch/clips", methods=["GET"])
@login_required
def twitch_clips_api():
    """Fetch Twitch clips for a given username or the current user's connected username.

    Query params:
      - username: optional; defaults to current_user.twitch_username
      - first: max 100
      - started_at, ended_at: RFC3339 timestamps (e.g., 2025-01-01T00:00:00Z)
      - after: pagination cursor
    """
    username = (
        request.args.get("username") or (current_user.twitch_username or "")
    ).strip()
    if not username:
        return jsonify({"error": "No Twitch username provided or connected."}), 400

    first = request.args.get("first", default=20, type=int)
    started_at = request.args.get("started_at")
    ended_at = request.args.get("ended_at")
    after = request.args.get("after")

    try:
        broadcaster_id = twitch_get_user_id(username)
        if not broadcaster_id:
            return jsonify({"error": "Twitch user not found"}), 404

        result = twitch_get_clips(
            broadcaster_id=broadcaster_id,
            started_at=started_at,
            ended_at=ended_at,
            first=first,
            after=after,
        )
        return jsonify(
            {
                "username": username,
                "broadcaster_id": broadcaster_id,
                **result,
            }
        )
    except Exception as e:
        current_app.logger.error(f"Twitch API error for user {username}: {e}")
        return jsonify({"error": "Failed to fetch Twitch clips"}), 502


@api_bp.route("/discord/messages", methods=["GET"])
@login_required
def discord_messages_api():
    """Fetch recent Discord messages and extract Twitch clip URLs.

    Query params:
      - channel_id: optional; defaults to Config.DISCORD_CHANNEL_ID
      - limit: 1-200, default 200
    Returns: { items: [...messages...], clip_urls: [...], channel_id }
    """
    limit = request.args.get("limit", default=200, type=int)
    channel_id = request.args.get("channel_id")
    try:
        messages = get_channel_messages(channel_id=channel_id, limit=limit)
        clip_urls = extract_clip_urls(messages)
        return jsonify(
            {
                "items": messages,
                "clip_urls": clip_urls,
                "channel_id": channel_id,
            }
        )
    except Exception as e:
        current_app.logger.error(f"Discord API error: {e}")
        return jsonify({"error": "Failed to fetch Discord messages"}), 502


@api_bp.route("/media/stats", methods=["GET"])
@login_required
def media_stats_api():
    """Return counts of media for the current user by type.

    Optional query param:
      - type: filter to a specific MediaType value
    """
    from app.models import MediaType  # local import to avoid cycles

    q = current_user.media_files
    type_filter = request.args.get("type")
    if type_filter and type_filter in [t.value for t in MediaType]:
        q = q.filter_by(media_type=MediaType(type_filter))

    items = q.all()
    total = len(items)
    by_type: dict[str, int] = {}
    for t in MediaType:
        by_type[t.value] = len([m for m in items if m.media_type == t])
    recent = [m.id for m in items[:5]]
    return jsonify({"total": total, "by_type": by_type, "recent_ids": recent})


@api_bp.route("/projects/<int:project_id>", methods=["GET"])
@login_required
def get_project_details_api(project_id: int):
    """Return basic project details including compilation output info.

    Response:
      - id, name, status, output_filename, output_file_size
      - download_url (if output available)
    """
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    download_url = None
    if project.output_filename:
        try:
            download_url = url_for(
                "main.download_compiled_output", project_id=project.id
            )
        except Exception:
            download_url = None

    return jsonify(
        {
            "id": project.id,
            "name": project.name,
            "status": project.status.value
            if hasattr(project.status, "value")
            else str(project.status),
            "output_filename": project.output_filename,
            "output_file_size": project.output_file_size,
            "download_url": download_url,
        }
    )


@api_bp.route("/projects/<int:project_id>/media", methods=["GET"])
@login_required
def list_project_media_api(project_id: int):
    """List media files for a project, optionally filtered by media type.

    Query params:
      - type: one of intro, outro, transition, clip (optional)
    """
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    from app.models import MediaType, MediaFile

    type_q = (request.args.get("type") or "").strip().lower()
    type_map = {
        "intro": MediaType.INTRO,
        "outro": MediaType.OUTRO,
        "transition": MediaType.TRANSITION,
        "clip": MediaType.CLIP,
    }

    # Show current user's media library (not limited to this project)
    q = MediaFile.query.filter_by(user_id=current_user.id)
    if type_q in type_map:
        q = q.filter_by(media_type=type_map[type_q])
    q = q.order_by(MediaFile.uploaded_at.desc())

    items = []
    for mf in q.all():
        items.append(
            {
                "id": mf.id,
                "filename": mf.filename,
                "original_filename": mf.original_filename,
                "duration": mf.duration,
                "width": mf.width,
                "height": mf.height,
                "framerate": mf.framerate,
                "media_type": mf.media_type.value
                if hasattr(mf.media_type, "value")
                else str(mf.media_type),
                "thumbnail_url": url_for("main.media_thumbnail", media_id=mf.id)
                if mf.thumbnail_path
                else None,
                "preview_url": url_for("main.media_preview", media_id=mf.id),
            }
        )

    return jsonify({"items": items, "count": len(items)})
