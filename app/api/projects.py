"""
Project-related API endpoints extracted from the legacy `app.api.routes` shim.

This module registers routes on the shared `api_bp` blueprint exported by
`app.api` and keeps heavy imports local inside handlers to avoid circular
import issues during app startup.
"""

from flask import current_app, jsonify, request, url_for
from flask_login import current_user, login_required

from app.api import api_bp


@api_bp.route("/projects", methods=["POST"])
@login_required
def create_project_api():
    """Create a new project via JSON API for the wizard flow."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        try:
            from datetime import date

            name = f"Compilation of {date.today().isoformat()}"
        except Exception:
            name = "Compilation of Today"

    description = (data.get("description") or "").strip() or None
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
        from app.models import Project, db

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
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error(f"API project creation failed: {e}")
        return jsonify({"error": "Failed to create project"}), 500


@api_bp.route("/projects/<int:project_id>/clips/download", methods=["POST"])
@login_required
def create_and_download_clips_api(project_id: int):
    """Create Clip rows from a list of URLs and dispatch download tasks."""
    from app.models import Clip, Project, db

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    urls = data.get("urls") or []
    provided_clips = data.get("clips") or []
    try:
        requested_limit = int(data.get("limit") or 0)
    except Exception:
        requested_limit = 0
    if not urls and not provided_clips:
        return jsonify({"error": "No URLs or clips provided"}), 400

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

    max_batch = 200
    if urls:
        urls = urls[:max_batch]
    if provided_clips:
        provided_clips = provided_clips[:max_batch]

    effective_limit = (
        requested_limit if requested_limit > 0 else (len(provided_clips) or len(urls))
    )
    effective_limit = max(1, min(effective_limit, max_batch))

    from app.tasks.download_clip_v2 import download_clip_task_v2 as download_clip_task

    download_queue: str | None = None
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
        if "gpu" in active_queues:
            download_queue = "gpu"
        elif "cpu" in active_queues:
            download_queue = "cpu"
    except Exception:
        download_queue = None
    if not download_queue:
        return (
            jsonify(
                {
                    "error": "No cpu/gpu workers available for downloads",
                    "hint": "Start a worker with -Q cpu or -Q gpu",
                }
            ),
            503,
        )

    items = []
    skipped_count = 0
    try:
        order_base = project.clips.count() or 0
        idx = 0

        def normalize_url(u: str) -> str:
            try:
                u = (u or "").strip()
                if not u:
                    return ""
                base = u.split("?")[0].split("#")[0]
                if base.endswith("/"):
                    base = base[:-1]
                return base
            except Exception:
                return (u or "").strip()

        def extract_key(u: str) -> str:
            try:
                s = normalize_url(u)
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
                        pass
                return s
            except Exception:
                return normalize_url(u)

        seen = set()

        def try_reuse(url_s: str):
            return False, None, None

        for obj in provided_clips[:effective_limit]:
            try:
                url_s = (obj.get("url") or "").strip()
                title = (obj.get("title") or "").strip()
                if not url_s:
                    current_app.logger.info(f"Skipping clip with empty URL: {title}")
                    skipped_count += 1
                    continue
                # Use clip slug for Twitch clips, normalized URL for others
                dedup_key = extract_key(url_s) or normalize_url(url_s)
                if not dedup_key or dedup_key in seen:
                    current_app.logger.warning(
                        f"Skipping duplicate clip '{title}': {url_s} (dedup key: {dedup_key}, already seen: {dedup_key in seen})"
                    )
                    skipped_count += 1
                    continue
                current_app.logger.info(
                    f"Processing clip '{title}': {url_s} (dedup key: {dedup_key})"
                )
                seen.add(dedup_key)
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

                clip = Clip(
                    title=title,
                    description=None,
                    source_platform=platform,
                    source_url=url_s,
                    source_id=(extract_key(url_s) if platform == "twitch" else None),
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

                try:
                    db.session.commit()
                except Exception as commit_err:
                    current_app.logger.error(
                        f"Failed to commit clip {clip.title} to database: {commit_err}"
                    )
                    db.session.rollback()
                    continue

                try:
                    task = download_clip_task.apply_async(
                        args=(clip.id, url_s), queue=download_queue
                    )
                    task_id = task.id
                    current_app.logger.info(
                        f"Queued download task {task_id} for clip {clip.id}: {url_s}"
                    )
                except Exception as task_err:
                    current_app.logger.error(
                        f"Failed to queue download task for clip {clip.id}: {task_err}"
                    )
                    task_id = None

                items.append({"clip_id": clip.id, "task_id": task_id, "url": url_s})
                idx += 1
            except Exception as outer_err:
                current_app.logger.error(
                    f"Unexpected error processing clip '{title}' ({url_s}): {outer_err}"
                )
                continue

        for url in urls[: max(0, effective_limit - len(items))]:
            url_s = (url or "").strip()
            if not url_s:
                skipped_count += 1
                continue
            # Use clip slug for Twitch clips, normalized URL for others
            dedup_key = extract_key(url_s) or normalize_url(url_s)
            if not dedup_key or dedup_key in seen:
                skipped_count += 1
                continue
            seen.add(dedup_key)
            platform = (
                "twitch"
                if "twitch" in url_s.lower()
                else ("discord" if "discord" in url_s.lower() else "external")
            )
            reused, media_file, src_platform = try_reuse(dedup_key)
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
                    is_downloaded=False,
                )
                db.session.add(clip)
                db.session.flush()
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    continue
                try:
                    task = download_clip_task.apply_async(
                        args=(clip.id, url_s), queue=download_queue
                    )
                    task_id = task.id
                except Exception:
                    task_id = None
                items.append(
                    {
                        "clip_id": clip.id,
                        "task_id": task_id,
                        "url": url_s,
                        "status": "queued",
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
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    continue
                task = download_clip_task.apply_async(
                    args=(clip.id, url_s), queue=download_queue
                )
                items.append({"clip_id": clip.id, "task_id": task.id, "url": url_s})
                idx += 1

        db.session.commit()
        return (
            jsonify(
                {
                    "items": items,
                    "count": len(items),
                    "skipped": skipped_count,
                    "requested": len(provided_clips) + len(urls),
                    "note": f"Created {len(items)} clips from {len(provided_clips) + len(urls)} provided URLs. Skipped {skipped_count} as duplicates or invalid.",
                }
            ),
            202,
        )
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error(f"API download dispatch failed: {e}")
        return jsonify({"error": "Failed to dispatch downloads"}), 500


@api_bp.route("/projects/<int:project_id>/compile", methods=["POST"])
@login_required
def compile_project_api(project_id: int):
    """Start compilation task for a project."""
    from app.models import Clip, Project, ProjectStatus, db

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if project.status == ProjectStatus.PROCESSING:
        return jsonify({"error": "Project is already being processed"}), 400

    data = request.get_json(silent=True) or {}

    # Optional subset timeline: clip_ids determines the exact
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
            rows = (
                db.session.query(Clip.id)
                .filter(Clip.project_id == project.id, Clip.id.in_(tmp))
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
        from sqlalchemy import func

        from app.quotas import check_render_quota
        from app.tasks.compile_video_v2 import (
            compile_video_task_v2 as compile_video_task,
        )

        intro_id = data.get("intro_id")
        outro_id = data.get("outro_id")
        transition_ids = data.get("transition_ids") or []
        randomize_transitions = bool(data.get("randomize_transitions") or False)

        valid_transition_ids: list[int] = []
        if isinstance(transition_ids, list) and transition_ids:
            try:
                from app.models import MediaFile, MediaType

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

        total_clip_seconds = 0.0
        try:
            if clip_ids is not None:
                rows = __import__("app")
                clips = []
            else:
                clips = project.clips.order_by(
                    Clip.order_index.asc(), Clip.created_at.asc()
                ).all()
            max_dur = float(project.max_clip_duration or 0)
            for c in clips:
                eff = 0.0
                try:
                    if c.start_time is not None and c.end_time is not None:
                        eff = max(0.0, float(c.end_time) - float(c.start_time))
                    elif c.duration is not None:
                        eff = float(c.duration)
                    elif getattr(c, "media_file", None) and c.media_file.duration:
                        eff = float(c.media_file.duration)
                    if max_dur > 0 and eff > 0:
                        eff = min(eff, max_dur)
                except Exception:
                    eff = max_dur if max_dur > 0 else 0.0
                total_clip_seconds += float(eff or 0.0)
        except Exception:
            total_clip_seconds = float(project.get_total_duration() or 0)

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
                from app.models import MediaFile, db

                rows = (
                    db.session.query(func.coalesce(func.avg(MediaFile.duration), 0.0))
                    .filter(MediaFile.id.in_(valid_transition_ids))
                    .scalar()
                    or 0.0
                )
                avg_trans = float(rows or 0.0)
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
            max(0.0, total_clip_seconds + intro_seconds + outro_seconds + trans_seconds)
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
        pass

    try:
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
            if "gpu" in active_queues:
                queue_name = "gpu"
            elif "cpu" in active_queues:
                queue_name = "cpu"
            else:
                if bool(current_app.config.get("USE_GPU_QUEUE")):
                    queue_name = "gpu"
        except Exception:
            if bool(current_app.config.get("USE_GPU_QUEUE")):
                queue_name = "gpu"

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
        project.status = getattr(project, "status", project.status)
        from app.models import db

        db.session.commit()
        return jsonify({"task_id": task.id, "status": "started"}), 202
    except Exception as e:
        try:
            from app.models import db

            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error(f"API compile start failed: {e}")
        return jsonify({"error": "Failed to start compilation"}), 500


@api_bp.route("/projects/<int:project_id>/clips", methods=["GET"])
@login_required
def list_project_clips_api(project_id: int):
    from app.models import Clip, Project

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
    from app.models import Clip, Project, db

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    ids = data.get("clip_ids") or []
    try:
        ids = [int(x) for x in ids]
    except Exception:
        return jsonify({"error": "clip_ids must be a list of integers"}), 400

    clips = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc()).all()
    if not clips:
        return jsonify({"error": "No clips to reorder"}), 400

    clip_map = {c.id: c for c in clips}
    desired = [cid for cid in ids if cid in clip_map]
    existing_set = set(desired)
    tail = [c.id for c in clips if c.id not in existing_set]
    new_order = desired + tail

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


@api_bp.route("/projects/<int:project_id>/ingest/raw", methods=["POST"])
@login_required
def ingest_raw_clips_api(project_id: int):
    from app.models import Project

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    worker_id = (data.get("worker_id") or "").strip() or None
    action = (data.get("action") or "copy").strip().lower()
    if action not in {"copy", "move", "link"}:
        action = "copy"
    regen_thumbnails = bool(data.get("regen_thumbnails") or False)

    try:
        from app.tasks.media_maintenance import (
            ingest_raw_clips_for_project as ingest_task,
        )

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
            if "celery" in active_queues:
                queue_name = "celery"
            elif "gpu" in active_queues:
                queue_name = "gpu"
            elif "cpu" in active_queues:
                queue_name = "cpu"
            else:
                if bool(current_app.config.get("USE_GPU_QUEUE")):
                    queue_name = "gpu"
        except Exception:
            if bool(current_app.config.get("USE_GPU_QUEUE")):
                queue_name = "gpu"

        task = ingest_task.apply_async(
            args=(project_id,),
            kwargs={
                "worker_id": worker_id,
                "action": action,
                "regen_thumbnails": regen_thumbnails,
            },
            queue=queue_name,
        )
        return jsonify({"task_id": task.id, "status": "started"}), 202
    except Exception as e:
        current_app.logger.error(f"API ingest raw clips failed: {e}")
        return jsonify({"error": "Failed to start ingest"}), 500


@api_bp.route("/projects/<int:project_id>/ingest/compiled", methods=["POST"])
@login_required
def ingest_compiled_api(project_id: int):
    from app.models import Project

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    worker_id = (data.get("worker_id") or "").strip() or None
    action = (data.get("action") or "copy").strip().lower()
    if action not in {"copy", "move", "link"}:
        action = "copy"
    try:
        from app.tasks.media_maintenance import ingest_compiled_for_project as task

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
            if "celery" in active_queues:
                queue_name = "celery"
            elif "gpu" in active_queues:
                queue_name = "gpu"
            elif "cpu" in active_queues:
                queue_name = "cpu"
        except Exception:
            pass

        t = task.apply_async(
            args=(project_id,),
            kwargs={"worker_id": worker_id, "action": action},
            queue=queue_name,
        )
        return jsonify({"task_id": t.id, "status": "started"}), 202
    except Exception as e:
        current_app.logger.error(f"API ingest compiled failed: {e}")
        return jsonify({"error": "Failed to start ingest"}), 500


@api_bp.route("/projects/<int:project_id>", methods=["GET"])
@login_required
def get_project_details_api(project_id: int):
    from app.models import Project

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    download_url = None
    preview_url = None
    compiled_duration = None

    if not project.output_filename:
        try:
            from app.models import MediaFile, MediaType

            mf = (
                MediaFile.query.filter_by(
                    project_id=project.id, media_type=MediaType.COMPILATION
                )
                .order_by(MediaFile.uploaded_at.desc())
                .first()
            )
            if mf and mf.filename:
                project.output_filename = mf.filename
                try:
                    project.output_file_size = mf.file_size
                except Exception:
                    pass
                try:
                    from app.models import db

                    db.session.add(project)
                    db.session.commit()
                except Exception:
                    try:
                        from app.models import db

                        db.session.rollback()
                    except Exception:
                        pass
        except Exception:
            pass

    if project.output_filename:
        try:
            if project.public_id:
                download_url = url_for(
                    "main.download_compiled_output_by_public",
                    public_id=project.public_id,
                )
                preview_url = url_for(
                    "main.preview_compiled_output_by_public",
                    public_id=project.public_id,
                )
            else:
                download_url = url_for(
                    "main.download_compiled_output", project_id=project.id
                )
                preview_url = url_for(
                    "main.preview_compiled_output", project_id=project.id
                )
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
                    if mf.filename == project.output_filename:
                        compiled_duration = mf.duration
                    else:
                        rows = (
                            MediaFile.query.filter_by(
                                project_id=project.id, media_type=MediaType.COMPILATION
                            )
                            .order_by(MediaFile.uploaded_at.desc())
                            .all()
                        )
                        for r in rows:
                            if r.filename == project.output_filename:
                                compiled_duration = r.duration
                                break
                        if compiled_duration is None and rows:
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
            "preview_url": preview_url,
            "compiled_duration": compiled_duration,
            "audio_norm_profile": getattr(project, "audio_norm_profile", None),
            "audio_norm_db": getattr(project, "audio_norm_db", None),
        }
    )
