"""
API routes and endpoints.
"""
# ruff: noqa: I001  # Suppress import-sorting cosmetic warning for this file
from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import current_user, login_required

from app.integrations.discord import extract_clip_urls, get_channel_messages
import re
from app.integrations.twitch import (
    get_clips as twitch_get_clips,
    get_user_id as twitch_get_user_id,
    get_user_profile_image_url as twitch_get_user_profile_image_url,
)
from app.models import db, Clip, ProcessingJob, Project, ProjectStatus
import os

api_bp = Blueprint("api", __name__)


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "message": "Clippy API is running"})


## Demo background task endpoint removed; no longer supported.


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
        try:
            proj = db.session.get(Project, job.project_id)
            project_name = proj.name if proj else None
        except Exception:
            project_name = None

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
          - audio_norm_profile (str, optional)
          - audio_norm_db (float, optional; relative dB e.g., -1.0)
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        # Default to "Compilation of <YYYY-MM-DD>" when name is omitted/blank
        try:
            from datetime import date

            name = f"Compilation of {date.today().isoformat()}"
        except Exception:
            name = "Compilation of Today"

    description = (data.get("description") or "").strip() or None
    # Use centralized defaults when not provided by client
    output_resolution = data.get("output_resolution") or current_app.config.get(
        "DEFAULT_OUTPUT_RESOLUTION", "1080p"
    )
    output_format = data.get("output_format") or current_app.config.get(
        "DEFAULT_OUTPUT_FORMAT", "mp4"
    )
    max_clip_duration = int(
        data.get("max_clip_duration")
        or current_app.config.get("DEFAULT_MAX_CLIP_DURATION", 30)
    )

    # Optional audio normalization inputs
    audio_norm_profile = (data.get("audio_norm_profile") or "").strip() or None
    try:
        audio_norm_db = (
            float(data.get("audio_norm_db"))
            if data.get("audio_norm_db") is not None
            and str(data.get("audio_norm_db")).strip() != ""
            else None
        )
    except Exception:
        audio_norm_db = None

    try:
        # Ensure project has an opaque public_id
        pid = None
        try:
            pid = Project.generate_public_id()
        except Exception:
            pid = None
        project = Project(
            name=name,
            description=description,
            user_id=current_user.id,
            max_clip_duration=max_clip_duration,
            output_resolution=output_resolution,
            output_format=output_format,
            public_id=pid,
            audio_norm_profile=audio_norm_profile,
            audio_norm_db=audio_norm_db,
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

    # Optional policy: restrict to Twitch/Discord URLs when external URLs are disabled
    allow_external = bool(current_app.config.get("ALLOW_EXTERNAL_URLS", False))
    if not allow_external:

        def _is_supported(u: str) -> bool:
            try:
                s = (u or "").strip().lower()
                return (
                    ("twitch.tv" in s)
                    or ("discord.com" in s)
                    or ("discordapp.com" in s)
                )
            except Exception:
                return False

        # Filter plain URLs and structured clips by policy
        orig_urls_len = len(urls)
        orig_clips_len = len(provided_clips)
        urls = [u for u in urls if _is_supported(str(u))]
        provided_clips = [
            c for c in provided_clips if _is_supported(str(c.get("url", "")))
        ]
        if (orig_urls_len > 0 or orig_clips_len > 0) and (
            len(urls) == 0 and len(provided_clips) == 0
        ):
            return (
                jsonify(
                    {
                        "error": "External URLs are disabled by configuration. Only Twitch/Discord URLs are allowed.",
                    }
                ),
                400,
            )

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

        # Extract a stable clip key for reuse detection (e.g., Twitch slug after /clip/)
        def extract_key(u: str) -> str:
            try:
                s = normalize_url(u)
                if not s:
                    return ""
                low = s.lower()
                # Twitch clip URL patterns:
                #  - https://www.twitch.tv/<channel>/clip/<slug>
                #  - https://www.twitch.tv/clip/<slug>
                #  - https://clips.twitch.tv/<slug>
                if ("twitch.tv" in low and "/clip/" in low) or (
                    "clips.twitch.tv" in low
                ):
                    try:
                        if "clips.twitch.tv" in low:
                            # clips.twitch.tv/<slug>
                            slug = low.split("clips.twitch.tv", 1)[1].lstrip("/")
                        else:
                            slug = low.split("/clip/", 1)[1]
                        # strip anything after next '/'
                        slug = slug.split("/")[0]
                        return slug
                    except Exception:
                        pass
                # Fallback: return normalized base URL as key
                return s
            except Exception:
                return normalize_url(u)

        seen = set()

        # Helper to try reuse: returns (reused: bool, media_file, source_platform)
        def try_reuse(url_s: str):
            # Prefer matching by a stable key (e.g., Twitch slug) but also try normalized URL
            key = extract_key(url_s)
            norm = normalize_url(url_s)
            # In-project duplicate check (raw or normalized key match)
            existing_here = (
                Clip.query.filter(Clip.project_id == project.id)
                .order_by(Clip.created_at.desc())
                .all()
            )
            for ex in existing_here:
                try:
                    ex_key = extract_key(ex.source_url or "")
                    ex_norm = normalize_url(ex.source_url or "")
                except Exception:
                    ex_key = ""
                    ex_norm = ""
                if (ex_key and key and ex_key == key) or (ex_norm and ex_norm == norm):
                    if ex.media_file_id:
                        return True, ex.media_file, ex.source_platform
                    break
            # If nothing matched in-loop above, fall through to cross-project check
            # Find any previously downloaded clip by this user matching key or normalized URL
            candidates = (
                db.session.query(Clip)
                .join(Project, Project.id == Clip.project_id)
                .filter(
                    Project.user_id == current_user.id,
                    Clip.media_file_id.isnot(None),
                )
                .order_by(Clip.created_at.desc())
                .limit(500)
                .all()
            )
            for prev in candidates:
                try:
                    pv_key = extract_key(prev.source_url or "")
                    pv_norm = normalize_url(prev.source_url or "")
                except Exception:
                    pv_key = ""
                    pv_norm = ""
                if (pv_key and key and pv_key == key) or (pv_norm and pv_norm == norm):
                    if prev.media_file_id:
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
                    if "twitch" in url_s.lower()
                    else ("discord" if "discord" in url_s.lower() else "external")
                )
                title = (obj.get("title") or f"Clip {order_base + idx + 1}").strip()
                creator_name = obj.get("creator_name")
                creator_id = obj.get("creator_id")
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
                        source_id=(
                            extract_key(url_s)
                            if (src_platform or platform) == "twitch"
                            else None
                        ),
                        project_id=project.id,
                        order_index=order_base + idx,
                        creator_name=creator_name,
                        creator_id=creator_id,
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
                        source_id=(
                            extract_key(url_s) if platform == "twitch" else None
                        ),
                        project_id=project.id,
                        order_index=order_base + idx,
                        creator_name=creator_name,
                        creator_id=creator_id,
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
                    # Try to resolve and cache creator avatar if creator_id present
                    try:
                        if creator_id:
                            avatar_url = twitch_get_user_profile_image_url(creator_id)
                            if avatar_url:
                                # Cache under instance/assets/avatars/
                                base_avatars = os.path.join(
                                    current_app.instance_path, "assets", "avatars"
                                )
                                os.makedirs(base_avatars, exist_ok=True)
                                import re as _re
                                import glob as _glob
                                import secrets
                                import httpx as _httpx

                                safe = _re.sub(
                                    r"[^a-z0-9_-]+",
                                    "_",
                                    (creator_name or "").lower().strip(),
                                ) or str(creator_id)
                                # If we already have any cached avatar for this author, reuse latest
                                existing: list[str] = []
                                try:
                                    for extx in (".png", ".jpg", ".jpeg", ".webp"):
                                        existing.extend(
                                            _glob.glob(
                                                os.path.join(
                                                    base_avatars, f"{safe}_*{extx}"
                                                )
                                            )
                                        )
                                except Exception:
                                    existing = []
                                if existing:
                                    try:
                                        existing.sort(
                                            key=lambda p: os.path.getmtime(p),
                                            reverse=True,
                                        )
                                        clip.creator_avatar_path = existing[0]
                                    except Exception:
                                        pass
                                else:
                                    # Download a fresh copy once and store with a short random suffix
                                    try:
                                        ext = (
                                            os.path.splitext(avatar_url.split("?")[0])[
                                                1
                                            ]
                                            or ".png"
                                        )
                                        out_path = os.path.join(
                                            base_avatars,
                                            f"{safe}_{secrets.token_hex(4)}{ext}",
                                        )
                                        r = _httpx.get(avatar_url, timeout=10)
                                        if r.status_code == 200 and r.content:
                                            with open(out_path, "wb") as fp:
                                                fp.write(r.content)
                                            clip.creator_avatar_path = out_path
                                            # Prune older avatars for this author, keep most recent 5
                                            try:
                                                matches: list[str] = []
                                                for extx in (
                                                    ".png",
                                                    ".jpg",
                                                    ".jpeg",
                                                    ".webp",
                                                ):
                                                    matches.extend(
                                                        _glob.glob(
                                                            os.path.join(
                                                                base_avatars,
                                                                f"{safe}_*{extx}",
                                                            )
                                                        )
                                                    )
                                                if len(matches) > 5:
                                                    matches.sort(
                                                        key=lambda p: os.path.getmtime(
                                                            p
                                                        ),
                                                        reverse=True,
                                                    )
                                                    for stale in matches[5:]:
                                                        try:
                                                            os.remove(stale)
                                                        except Exception:
                                                            pass
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                    except Exception:
                        pass

                    # Ensure the Clip row is visible to the Celery worker
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                        # If commit fails, skip enqueue to avoid orphan task
                        continue
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
                if "twitch" in url_s.lower()
                else ("discord" if "discord" in url_s.lower() else "external")
            )
            # Attempt reuse
            reused, media_file, src_platform = try_reuse(norm)
            if reused and media_file:
                clip = Clip(
                    title=f"Clip {order_base + idx + 1}",
                    description=None,
                    source_platform=src_platform or platform,
                    source_url=url_s,
                    source_id=(
                        extract_key(url_s)
                        if (src_platform or platform) == "twitch"
                        else None
                    ),
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
                    source_id=(extract_key(url_s) if platform == "twitch" else None),
                    project_id=project.id,
                    order_index=order_base + idx,
                )
                db.session.add(clip)
                db.session.flush()
                # Commit before enqueuing so the worker can load the Clip row
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    continue
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
    # Load request body now to evaluate selected timeline subset
    data = request.get_json(silent=True) or {}

    # Optional subset selection from client timeline: clip_ids determines the exact
    # ordered list of clips to render. When omitted, all project clips will be used
    # (ordered by order_index then created_at).
    raw_clip_ids = data.get("clip_ids")
    clip_ids: list[int] | None = None
    if isinstance(raw_clip_ids, list):
        # Coerce to ints, drop invalid, and preserve order with de-dup
        tmp: list[int] = []
        seen: set[int] = set()
        for v in raw_clip_ids:
            try:
                iv = int(v)
            except Exception:
                continue
            if iv not in seen:
                tmp.append(iv)
                seen.add(iv)
        if tmp:
            # Filter to clips owned by this project/user
            from app.models import Clip as _Clip

            rows = (
                db.session.query(_Clip.id)
                .filter(_Clip.project_id == project.id, _Clip.id.in_(tmp))
                .all()
            )
            valid = {rid for (rid,) in rows}
            clip_ids = [rid for rid in tmp if rid in valid]
        else:
            clip_ids = []

    # Effective existence check: require some clips either in project or in selected subset
    if (clip_ids is not None and len(clip_ids) == 0) or (
        clip_ids is None and project.clips.count() == 0
    ):
        return jsonify({"error": "Project has no clips to compile"}), 400

    try:
        from app.tasks.video_processing import compile_video_task
        from app.quotas import check_render_quota
        from sqlalchemy import func

        # Optional selections from client (data parsed above)
        intro_id = data.get("intro_id")
        outro_id = data.get("outro_id")
        transition_ids = data.get("transition_ids") or []
        randomize_transitions = bool(data.get("randomize_transitions") or False)

        # Defense-in-depth: verify intro/outro ownership if provided
        if intro_id is not None:
            try:
                from app.models import MediaFile

                intro = MediaFile.query.filter_by(
                    id=intro_id, user_id=current_user.id
                ).first()
                if not intro:
                    return jsonify({"error": "Invalid intro selection"}), 400
            except Exception:
                return jsonify({"error": "Invalid intro selection"}), 400
        if outro_id is not None:
            try:
                from app.models import MediaFile

                outro = MediaFile.query.filter_by(
                    id=outro_id, user_id=current_user.id
                ).first()
                if not outro:
                    return jsonify({"error": "Invalid outro selection"}), 400
            except Exception:
                return jsonify({"error": "Invalid outro selection"}), 400

        # Verify transitions ownership if provided
        valid_transition_ids: list[int] = []
        if isinstance(transition_ids, list) and transition_ids:
            try:
                from app.models import MediaFile, MediaType

                # Coerce to ints and dedupe
                try:
                    tid_list = list({int(t) for t in transition_ids})
                except Exception:
                    tid_list = []
                if tid_list:
                    q = MediaFile.query.filter(
                        MediaFile.id.in_(tid_list),
                        MediaFile.user_id == current_user.id,
                        MediaFile.media_type == MediaType.TRANSITION,
                    )
                    valid_transition_ids = [m.id for m in q.all()]
            except Exception:
                valid_transition_ids = []

        # Estimate planned output duration (seconds) for quota enforcement
        try:
            # Compute effective durations per clip to account for trims and per-project caps
            total_clip_seconds = 0.0
            try:
                # Honor selected timeline subset if provided; else use all clips in project order
                if clip_ids is not None:
                    # Build map for quick lookup and then preserve requested order
                    rows = (
                        db.session.query(Clip)
                        .filter(Clip.project_id == project.id, Clip.id.in_(clip_ids))
                        .all()
                    )
                    by_id = {c.id: c for c in rows}
                    clips = [by_id[cid] for cid in clip_ids if cid in by_id]
                else:
                    clips = project.clips.order_by(
                        Clip.order_index.asc(), Clip.created_at.asc()
                    ).all()
                max_dur = float(project.max_clip_duration or 0)
                for c in clips:
                    eff = 0.0
                    try:
                        if c.start_time is not None and c.end_time is not None:
                            # Respect explicit trim window
                            eff = max(0.0, float(c.end_time) - float(c.start_time))
                        elif c.duration is not None:
                            eff = float(c.duration)
                        elif getattr(c, "media_file", None) and c.media_file.duration:
                            eff = float(c.media_file.duration)
                        # Apply per-clip cap when configured
                        if max_dur > 0 and eff > 0:
                            eff = min(eff, max_dur)
                    except Exception:
                        # If we can't determine this clip's duration, assume max if set
                        eff = max_dur if max_dur > 0 else 0.0
                    total_clip_seconds += float(eff or 0.0)
            except Exception:
                # Fallback to legacy aggregate when detailed calc fails
                total_clip_seconds = float(project.get_total_duration() or 0)

            # Add intro/outro durations if provided/available
            intro_seconds = 0.0
            if intro_id is not None:
                try:
                    from app.models import MediaFile

                    mf = MediaFile.query.filter_by(
                        id=intro_id, user_id=current_user.id
                    ).first()
                    if mf and mf.duration:
                        intro_seconds = float(mf.duration)
                except Exception:
                    intro_seconds = 0.0
            outro_seconds = 0.0
            if outro_id is not None:
                try:
                    from app.models import MediaFile

                    mf = MediaFile.query.filter_by(
                        id=outro_id, user_id=current_user.id
                    ).first()
                    if mf and mf.duration:
                        outro_seconds = float(mf.duration)
                except Exception:
                    outro_seconds = 0.0

            # Estimate transitions: average selected transition duration times number of gaps
            trans_seconds = 0.0
            try:
                segs = (
                    project.clips.count()
                    + (1 if intro_id is not None else 0)
                    + (1 if outro_id is not None else 0)
                )
                gaps = max(0, segs - 1)
                avg_trans = 0.0
                if valid_transition_ids:
                    from app.models import MediaFile

                    # Average known durations across selected transitions
                    rows = (
                        db.session.query(
                            func.coalesce(func.avg(MediaFile.duration), 0.0)
                        )
                        .filter(MediaFile.id.in_(valid_transition_ids))
                        .scalar()
                        or 0.0
                    )
                    avg_trans = float(rows or 0.0)
                    # Fallback to a conservative default when unknown
                    if avg_trans <= 0.0:
                        try:
                            avg_trans = float(
                                current_app.config.get(
                                    "DEFAULT_TRANSITION_DURATION_SECONDS", 3
                                )
                            )
                        except Exception:
                            avg_trans = 3.0
                trans_seconds = gaps * avg_trans
            except Exception:
                trans_seconds = 0.0

            estimated_seconds = int(
                max(
                    0.0,
                    total_clip_seconds + intro_seconds + outro_seconds + trans_seconds,
                )
            )
            qr = check_render_quota(current_user, planned_seconds=estimated_seconds)
            if not qr.ok:
                return (
                    jsonify(
                        {
                            "error": "Render time quota exceeded",
                            "remaining_seconds": qr.remaining,
                            "limit_seconds": qr.limit,
                            "estimated_seconds": estimated_seconds,
                        }
                    ),
                    403,
                )
        except Exception:
            # If any estimation/check fails, continue; enforcement will occur post-compile usage recording
            pass

        # Attempt to enqueue first; only mark PROCESSING if enqueue succeeds
        # Explicitly route to the GPU queue when enabled to avoid default-queue fallback
        # Queue selection priority: gpu > cpu > celery
        # We'll inspect known workers for declared queues via Celery's inspect API.
        # If inspect fails (e.g., permissions/network), fall back to USE_GPU_QUEUE flag.
        queue_name = "celery"
        try:
            from app.tasks.celery_app import celery_app as _celery

            i = _celery.control.inspect(timeout=1.0)
            active_queues = set()
            if i:
                aq = i.active_queues() or {}
                for _worker, queues in aq.items():
                    for q in queues or []:
                        qname = q.get("name") if isinstance(q, dict) else None
                        if qname:
                            active_queues.add(qname)
            # Choose by priority if present
            if "gpu" in active_queues:
                queue_name = "gpu"
            elif "cpu" in active_queues:
                queue_name = "cpu"
            else:
                # Final fallback: respect USE_GPU_QUEUE flag if set
                if bool(current_app.config.get("USE_GPU_QUEUE")):
                    queue_name = "gpu"
        except Exception:
            # On any error, keep default behavior
            if bool(current_app.config.get("USE_GPU_QUEUE")):
                queue_name = "gpu"
        # Optionally attach selected reusable media to this project for UI visibility
        try:
            from app.models import MediaFile, MediaType

            changed = 0
            if intro_id is not None:
                m = MediaFile.query.filter_by(
                    id=intro_id, user_id=current_user.id
                ).first()
                if m and m.media_type == MediaType.INTRO:
                    if m.project_id != project.id:
                        m.project_id = project.id
                        changed += 1
            if outro_id is not None:
                m = MediaFile.query.filter_by(
                    id=outro_id, user_id=current_user.id
                ).first()
                if m and m.media_type == MediaType.OUTRO:
                    if m.project_id != project.id:
                        m.project_id = project.id
                        changed += 1
            if valid_transition_ids:
                rows = MediaFile.query.filter(
                    MediaFile.id.in_(valid_transition_ids),
                    MediaFile.user_id == current_user.id,
                    MediaFile.media_type == MediaType.TRANSITION,
                ).all()
                for m in rows:
                    if m.project_id != project.id:
                        m.project_id = project.id
                        changed += 1
            if changed:
                db.session.commit()
        except Exception:
            # Non-fatal: attachment is purely for UI presentation
            try:
                db.session.rollback()
            except Exception:
                pass

        task = compile_video_task.apply_async(
            args=(project_id,),
            kwargs={
                "intro_id": intro_id,
                "outro_id": outro_id,
                "transition_ids": valid_transition_ids,
                "randomize_transitions": randomize_transitions,
                "clip_ids": clip_ids,
            },
            queue=queue_name,
        )
        # Enqueue succeeded; mark project as processing
        project.status = ProjectStatus.PROCESSING
        db.session.commit()
        return jsonify({"task_id": task.id, "status": "started"}), 202
    except Exception as e:
        # Ensure project remains not-processing on failure
        try:
            db.session.rollback()
        except Exception:
            pass
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
                        "duration": media.duration,
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


@api_bp.route("/projects/<int:project_id>/clips/order", methods=["POST"])
@login_required
def reorder_project_clips_api(project_id: int):
    """Reorder clips for a project.

    Expected JSON body: { clip_ids: [int, int, ...] } where clip_ids is the desired
    order for the clips. Any project clips not listed will be appended after in their
    existing relative order.
    """
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    ids = data.get("clip_ids") or []
    try:
        ids = [int(x) for x in ids]
    except Exception:
        return jsonify({"error": "clip_ids must be a list of integers"}), 400

    # Fetch current clips
    clips = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc()).all()
    if not clips:
        return jsonify({"error": "No clips to reorder"}), 400

    # Map id -> clip, filter ids to those belonging to this project
    clip_map = {c.id: c for c in clips}
    desired = [cid for cid in ids if cid in clip_map]

    # Append any missing clips in original order
    existing_set = set(desired)
    tail = [c.id for c in clips if c.id not in existing_set]
    new_order = desired + tail

    # Update order_index sequentially
    try:
        for idx, cid in enumerate(new_order):
            clip_map[cid].order_index = idx
        db.session.commit()
        return jsonify(
            {"status": "ok", "ordered_ids": new_order, "count": len(new_order)}
        )
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to update order"}), 500


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


@api_bp.route("/media", methods=["GET"])
@login_required
def list_user_media_api():
    """List current user's media library, optionally filtered by type.

    Query params:
      - type: one of intro,outro,transition,clip (optional)
    Returns an array of media with preview/thumbnail URLs for selection UIs.
    """
    from app.models import MediaType, MediaFile

    type_q = (request.args.get("type") or "").strip().lower()
    type_map = {
        "intro": MediaType.INTRO,
        "outro": MediaType.OUTRO,
        "transition": MediaType.TRANSITION,
        "clip": MediaType.CLIP,
    }

    q = MediaFile.query.filter_by(user_id=current_user.id)
    if type_q in type_map:
        q = q.filter_by(media_type=type_map[type_q])
    q = q.order_by(MediaFile.uploaded_at.desc())

    items = []
    for mf in q.all():
        items.append(
            {
                "id": mf.id,
                "filename": mf.original_filename or mf.filename,
                "duration": mf.duration,
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
    compiled_duration = None
    if project.output_filename:
        try:
            if project.public_id:
                download_url = url_for(
                    "main.download_compiled_output_by_public",
                    public_id=project.public_id,
                )
            # Try to resolve the duration from the associated compilation MediaFile
            try:
                from app.models import MediaFile, MediaType

                mf = (
                    MediaFile.query.filter_by(
                        project_id=project.id, media_type=MediaType.COMPILATION
                    )
                    .order_by(MediaFile.uploaded_at.desc())
                    .first()
                )
                if mf and mf.filename and project.output_filename:
                    # Prefer exact filename match when multiple exist
                    if mf.filename == project.output_filename:
                        compiled_duration = mf.duration
                    else:
                        # Try to find exact match among all compilations for this project
                        rows = (
                            MediaFile.query.filter_by(
                                project_id=project.id,
                                media_type=MediaType.COMPILATION,
                            )
                            .order_by(MediaFile.uploaded_at.desc())
                            .all()
                        )
                        for r in rows:
                            if r.filename == project.output_filename:
                                compiled_duration = r.duration
                                break
                        if compiled_duration is None and rows:
                            # Fallback: latest compilation's duration
                            compiled_duration = rows[0].duration
            except Exception:
                compiled_duration = None
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
            "compiled_duration": compiled_duration,
            "audio_norm_profile": getattr(project, "audio_norm_profile", None),
            "audio_norm_db": getattr(project, "audio_norm_db", None),
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


# Automation API: task definitions and schedules


@api_bp.route("/automation/tasks", methods=["POST"])
@login_required
def create_compilation_task_api():
    """Create a CompilationTask for the current user.

        Expected JSON body:
      - name (str, required)
      - description (str, optional)
      - params (object) with keys:
                    source: "twitch" (default twitch)
          clip_limit: int
          intro_id, outro_id: int (optional)
          transition_ids: [int]
          randomize_transitions: bool
          output: { output_resolution, output_format, max_clip_duration, audio_norm_db }
    Returns: { id }
    """
    from app.models import CompilationTask

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    description = (data.get("description") or "").strip() or None
    params = data.get("params") or {}

    # Light validation of params; deeper checks happen at run time
    source = (params.get("source") or "twitch").strip().lower()
    if source not in {"twitch"}:
        return jsonify({"error": "source must be 'twitch'"}), 400

    task = CompilationTask(
        user_id=current_user.id, name=name, description=description, params=params
    )
    try:
        db.session.add(task)
        db.session.commit()
        return jsonify({"id": task.id, "status": "created"}), 201
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to create task"}), 500


@api_bp.route("/automation/tasks", methods=["GET"])
@login_required
def list_compilation_tasks_api():
    from app.models import CompilationTask

    items = (
        CompilationTask.query.filter_by(user_id=current_user.id)
        .order_by(CompilationTask.updated_at.desc())
        .all()
    )
    return jsonify(
        {
            "items": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in items
            ],
            "count": len(items),
        }
    )


@api_bp.route("/automation/tasks/<int:task_id>/run", methods=["POST"])
@login_required
def run_compilation_task_api(task_id: int):
    from app.models import CompilationTask

    ctask = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not ctask:
        return jsonify({"error": "Task not found"}), 404
    try:
        from app.tasks.automation import run_compilation_task as _run

        res = _run.apply_async(args=(ctask.id,))
        return jsonify({"status": "started", "task_id": res.id}), 202
    except Exception:
        return jsonify({"error": "Failed to start run"}), 500


@api_bp.route("/automation/tasks/<int:task_id>", methods=["GET"])
@login_required
def get_compilation_task_api(task_id: int):
    """Fetch a single task with full params for editing/viewing."""
    from app.models import CompilationTask

    t = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not t:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "params": t.params or {},
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
    )


@api_bp.route("/automation/tasks/<int:task_id>", methods=["PATCH", "PUT"])
@login_required
def update_compilation_task_api(task_id: int):
    """Update name/description/params of a task owned by the current user."""
    from app.models import CompilationTask

    t = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not t:
        return jsonify({"error": "Task not found"}), 404
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if name is not None:
        name = (str(name) or "").strip()
        if not name:
            return jsonify({"error": "name cannot be blank"}), 400
        t.name = name
    if "description" in data:
        desc = data.get("description")
        t.description = (str(desc) or "").strip() or None
    if "params" in data:
        params = data.get("params") or {}
        # Light validation
        try:
            src = (params.get("source") or "twitch").strip().lower()
            if src not in {"twitch"}:
                return (
                    jsonify({"error": "params.source must be 'twitch'"}),
                    400,
                )
        except Exception:
            pass
        t.params = params
    try:
        db.session.commit()
        return jsonify({"success": True})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to update task"}), 500


@api_bp.route("/automation/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_compilation_task_api(task_id: int):
    """Delete a task and its schedules for the current user."""
    from app.models import CompilationTask, ScheduledTask

    t = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not t:
        return jsonify({"error": "Task not found"}), 404
    try:
        # Delete schedules owned by this user for the task first
        ScheduledTask.query.filter_by(user_id=current_user.id, task_id=t.id).delete()
        db.session.delete(t)
        db.session.commit()
        return jsonify({"success": True})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to delete task"}), 500


@api_bp.route("/automation/tasks/<int:task_id>/schedules", methods=["POST"])
@login_required
def create_schedule_api(task_id: int):
    """Create a schedule for a task, gated by the user's tier.

    Expected JSON body for schedule:
        - type: daily|weekly|monthly
        - time: HH:MM (24h) when daily/weekly/monthly
        - weekday: 0..6 (Mon..Sun) when weekly
        - month_day: 1..31 when monthly
    """
    from app.models import CompilationTask, ScheduledTask, ScheduleType

    ctask = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not ctask:
        return jsonify({"error": "Task not found"}), 404

    # Tier gating
    try:
        if not (
            current_user.tier
            and getattr(current_user.tier, "can_schedule_tasks", False)
        ):
            return jsonify({"error": "Scheduling not available for your tier"}), 403
        # Enforce per-tier max
        active_count = ScheduledTask.query.filter_by(
            user_id=current_user.id, enabled=True
        ).count()
        max_allowed = int(getattr(current_user.tier, "max_schedules_per_user", 1) or 1)
        if active_count >= max_allowed:
            return (
                jsonify({"error": "Schedule limit reached", "limit": max_allowed}),
                403,
            )
    except Exception:
        # If tier missing or error, deny by default
        return jsonify({"error": "Scheduling not available"}), 403

    data = request.get_json(silent=True) or {}
    stype = (data.get("type") or "").strip().lower()
    if stype not in {"daily", "weekly", "monthly"}:
        return jsonify({"error": "type must be one of: daily,weekly,monthly"}), 400

    run_at = None
    daily_time = None
    weekly_day = None
    month_day = None
    if stype == "daily":
        daily_time = (data.get("time") or "").strip()
        if not daily_time:
            return jsonify({"error": "time is required"}), 400
        if not re.match(r"^\d{2}:\d{2}$", daily_time):
            return jsonify({"error": "time must be HH:MM"}), 400
    elif stype == "weekly":
        daily_time = (data.get("time") or "").strip()
        if not daily_time:
            return jsonify({"error": "time is required"}), 400
        if not re.match(r"^\d{2}:\d{2}$", daily_time):
            return jsonify({"error": "time must be HH:MM"}), 400
        try:
            weekly_day = int(data.get("weekday"))
        except Exception:
            weekly_day = 0
        if weekly_day < 0 or weekly_day > 6:
            return jsonify({"error": "weekday must be 0..6 (Mon..Sun)"}), 400
    elif stype == "monthly":
        daily_time = (data.get("time") or "").strip()
        if not daily_time:
            return jsonify({"error": "time is required"}), 400
        if not re.match(r"^\d{2}:\d{2}$", daily_time):
            return jsonify({"error": "time must be HH:MM"}), 400
        try:
            month_day = int(data.get("month_day"))
        except Exception:
            month_day = 1
        if month_day < 1 or month_day > 31:
            return jsonify({"error": "month_day must be 1..31"}), 400

    # Optional timezone provided by client (IANA name); default to UTC
    # Prefer explicitly provided timezone; otherwise use user's saved preference; fallback to UTC
    tz_name = (data.get("timezone") or current_user.timezone or "UTC").strip() or "UTC"
    try:
        from zoneinfo import ZoneInfo  # validate timezone

        _ = ZoneInfo(tz_name)
    except Exception:
        tz_name = "UTC"

    sched = ScheduledTask(
        user_id=current_user.id,
        task_id=ctask.id,
        schedule_type=ScheduleType(stype),
        run_at=run_at,
        daily_time=daily_time,
        weekly_day=weekly_day,
        monthly_day=month_day,
        timezone=tz_name,
        enabled=True,
    )
    try:
        # Compute initial next_run_at so UI isn't blank and tick is ready
        try:
            from datetime import datetime as _dt
            from app.tasks.automation import _compute_next_run

            now_utc = _dt.utcnow().replace(tzinfo=None)
            sched.next_run_at = _compute_next_run(sched, now_utc)
        except Exception:
            sched.next_run_at = None

        db.session.add(sched)
        db.session.commit()
        # Populate next_run_at on first tick; returning basic info here
        return jsonify({"id": sched.id, "status": "created"}), 201
    except Exception as e:
        db.session.rollback()
        # Surface a more actionable error to the UI
        return (
            jsonify(
                {
                    "error": "Failed to create schedule",
                    "error_detail": str(e),
                }
            ),
            500,
        )


@api_bp.route("/automation/tasks/<int:task_id>/schedules", methods=["GET"])
@login_required
def list_schedules_api(task_id: int):
    from app.models import ScheduledTask

    rows = (
        ScheduledTask.query.filter_by(user_id=current_user.id, task_id=task_id)
        .order_by(ScheduledTask.created_at.desc())
        .all()
    )
    # Compute display next_run_at when missing (don't mutate DB in GET)
    try:
        from datetime import datetime as _dt
        from app.tasks.automation import _compute_next_run

        now_utc = _dt.utcnow().replace(tzinfo=None)
    except Exception:
        now_utc = None
    return jsonify(
        {
            "items": [
                {
                    "id": s.id,
                    "enabled": s.enabled,
                    "type": s.schedule_type.value
                    if hasattr(s.schedule_type, "value")
                    else str(s.schedule_type),
                    "run_at": s.run_at.isoformat() if s.run_at else None,
                    "time": s.daily_time,
                    "weekday": s.weekly_day,
                    "timezone": getattr(s, "timezone", None) or "UTC",
                    "month_day": s.monthly_day,
                    "next_run_at": (
                        s.next_run_at.isoformat()
                        if s.next_run_at
                        else (
                            _compute_next_run(s, now_utc).isoformat()
                            if (now_utc is not None and _compute_next_run(s, now_utc))
                            else None
                        )
                    ),
                    "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                }
                for s in rows
            ],
            "count": len(rows),
        }
    )


@api_bp.route("/automation/schedules/<int:schedule_id>", methods=["PATCH"])
@login_required
def update_schedule_api(schedule_id: int):
    """Update schedule fields: enabled, type, run_at/time/weekday, timezone.

    Body accepts any subset:
      - enabled: bool
    - type: daily|weekly|monthly
    - time: HH:MM when daily/weekly/monthly
    - weekday: 0..6 when weekly
    - month_day: 1..31 when monthly
      - timezone: Olson TZ name (stored only; tick uses UTC)
    """
    from app.models import ScheduledTask, ScheduleType
    from datetime import datetime as _dt
    from app.tasks.automation import _compute_next_run

    s = ScheduledTask.query.filter_by(id=schedule_id, user_id=current_user.id).first()
    if not s:
        return jsonify({"error": "Schedule not found"}), 404
    data = request.get_json(silent=True) or {}
    # Enabled toggle
    if "enabled" in data:
        s.enabled = bool(data.get("enabled"))
    # Type change
    if "type" in data:
        stype = (str(data.get("type")) or "").strip().lower()
        if stype not in {"daily", "weekly", "monthly"}:
            return jsonify({"error": "type must be daily|weekly|monthly"}), 400
        s.schedule_type = ScheduleType(stype)
        # Reset type-specific fields when switching types
        s.run_at = None
        s.daily_time = None
        s.weekly_day = None
        s.monthly_day = None
    # Legacy 'once' schedules are read-only except for changing type away from 'once'
    if s.schedule_type == ScheduleType.ONCE:
        # If client attempts to modify fields other than 'enabled' or 'type', reject
        forbidden_keys = {k for k in data.keys() if k not in {"enabled", "type"}}
        if forbidden_keys:
            return (
                jsonify(
                    {
                        "error": "Legacy one-time schedules are read-only. Change type to daily/weekly/monthly to edit.",
                        "forbidden": sorted(forbidden_keys),
                    }
                ),
                400,
            )
    # Time fields for recurring schedules
    if s.schedule_type in (
        ScheduleType.DAILY,
        ScheduleType.WEEKLY,
        ScheduleType.MONTHLY,
    ):
        if "time" in data:
            s.daily_time = (str(data.get("time")) or "00:00").strip()
        if s.schedule_type == ScheduleType.WEEKLY and "weekday" in data:
            try:
                s.weekly_day = int(data.get("weekday"))
            except Exception:
                s.weekly_day = 0
        if s.schedule_type == ScheduleType.MONTHLY and "month_day" in data:
            try:
                s.monthly_day = int(data.get("month_day"))
            except Exception:
                s.monthly_day = 1
    # Timezone stored verbatim for future enhancements
    if "timezone" in data:
        tz = (str(data.get("timezone")) or "UTC").strip() or "UTC"
        s.timezone = tz

    # Recompute next_run_at based on new settings
    try:
        now_utc = _dt.utcnow().replace(tzinfo=None)
        s.next_run_at = _compute_next_run(s, now_utc)
    except Exception:
        # If computation fails, leave next_run_at as-is or None
        pass
    try:
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "enabled": s.enabled,
                "type": s.schedule_type.value,
                "run_at": s.run_at.isoformat() if s.run_at else None,
                "time": s.daily_time,
                "weekday": s.weekly_day,
                "timezone": s.timezone,
                "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
            }
        )
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to update schedule"}), 500


@api_bp.route("/automation/schedules/<int:schedule_id>", methods=["DELETE"])
@login_required
def delete_schedule_api(schedule_id: int):
    from app.models import ScheduledTask

    s = ScheduledTask.query.filter_by(id=schedule_id, user_id=current_user.id).first()
    if not s:
        return jsonify({"error": "Schedule not found"}), 404
    try:
        db.session.delete(s)
        db.session.commit()
        return jsonify({"success": True})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to delete schedule"}), 500


@api_bp.route("/automation/tasks/<int:task_id>/clone", methods=["POST"])
@login_required
def clone_compilation_task_api(task_id: int):
    """Clone a CompilationTask for the current user.

    Optional JSON: { copy_schedules: bool } — when true, duplicates schedules as disabled.
    """
    from app.models import CompilationTask, ScheduledTask

    src = CompilationTask.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not src:
        return jsonify({"error": "Task not found"}), 404
    data = request.get_json(silent=True) or {}
    copy_schedules = bool(data.get("copy_schedules") or False)

    # Derive a copy name
    base = src.name or "Task"
    new_name = f"Copy of {base}"
    # Avoid collision by appending a counter if necessary
    try:
        existing_names = {
            t.name
            for t in CompilationTask.query.filter_by(user_id=current_user.id).all()
        }
        if new_name in existing_names:
            idx = 2
            while f"{new_name} ({idx})" in existing_names and idx < 1000:
                idx += 1
            new_name = f"{new_name} ({idx})"
    except Exception:
        pass

    try:
        clone = CompilationTask(
            user_id=current_user.id,
            name=new_name,
            description=src.description,
            params=dict(src.params or {}),
        )
        db.session.add(clone)
        db.session.flush()

        if copy_schedules:
            # Copy schedules as disabled to avoid accidental runs
            rows = (
                ScheduledTask.query.filter_by(user_id=current_user.id, task_id=src.id)
                .order_by(ScheduledTask.created_at.asc())
                .all()
            )
            for s in rows:
                dup = ScheduledTask(
                    user_id=current_user.id,
                    task_id=clone.id,
                    schedule_type=s.schedule_type,
                    run_at=s.run_at,
                    daily_time=s.daily_time,
                    weekly_day=s.weekly_day,
                    timezone=s.timezone,
                    enabled=False,
                )
                db.session.add(dup)

        db.session.commit()
        return jsonify({"id": clone.id, "status": "cloned"}), 201
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to clone task"}), 500


@api_bp.route("/automation/scheduler/tick", methods=["POST"])
@login_required
def trigger_scheduler_tick_api():
    """Trigger the scheduler tick. Restricted to admins to avoid abuse."""
    if not current_user.is_admin():
        return jsonify({"error": "Forbidden"}), 403
    try:
        from app.tasks.automation import scheduled_tasks_tick as _tick

        res = _tick.apply_async()
        return jsonify({"status": "started", "task_id": res.id}), 202
    except Exception:
        return jsonify({"error": "Failed to trigger tick"}), 500
