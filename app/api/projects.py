"""
Project-related API endpoints extracted from the legacy `app.api.routes` shim.

This module registers routes on the shared `api_bp` blueprint exported by
`app.api` and keeps heavy imports local inside handlers to avoid circular
import issues during app startup.
"""

import structlog
from flask import current_app, jsonify, request, url_for
from flask_login import current_user, login_required

from app.api import api_bp

logger = structlog.get_logger(__name__)


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

    # Tags (comma-separated string)
    tags = (data.get("tags") or "").strip() or None

    # Check if a platform preset was specified
    platform_preset_value = data.get("platform_preset")
    preset_settings = None

    if platform_preset_value and platform_preset_value != "custom":
        try:
            from app.models import PlatformPreset

            preset = PlatformPreset(platform_preset_value)
            preset_settings = preset.get_settings()
        except (ValueError, AttributeError):
            # Invalid preset, ignore and use defaults
            platform_preset_value = None

    # Use preset settings if available, otherwise use provided values or defaults
    if preset_settings:
        output_resolution = preset_settings["resolution"]
        output_format = preset_settings["format"]
        fps = preset_settings["fps"]
        # Set quality based on bitrate
        if preset_settings["bitrate"] and "M" in preset_settings["bitrate"]:
            bitrate_mb = int(preset_settings["bitrate"].replace("M", ""))
            if bitrate_mb >= 8:
                quality = "high"
            elif bitrate_mb >= 5:
                quality = "medium"
            else:
                quality = "low"
        else:
            quality = "high"
    else:
        output_resolution = data.get("output_resolution") or current_app.config.get(
            "DEFAULT_OUTPUT_RESOLUTION", "1080p"
        )
        output_format = data.get("output_format") or current_app.config.get(
            "DEFAULT_OUTPUT_FORMAT", "mp4"
        )
        fps = data.get("fps") or 30
        quality = data.get("quality") or "high"

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

    # Vertical video settings (for 9:16 conversions)
    vertical_zoom = int(data.get("vertical_zoom") or 100)
    vertical_zoom = max(100, min(120, vertical_zoom))  # Clamp to 100-120
    vertical_align = (data.get("vertical_align") or "center").strip()
    if vertical_align not in ["left", "center", "right"]:
        vertical_align = "center"

    # Music ducking parameters (for sidechaincompress)
    duck_threshold = float(data.get("duck_threshold") or 0.02)
    duck_threshold = max(0.0, min(1.0, duck_threshold))  # Clamp to 0.0-1.0
    duck_ratio = float(data.get("duck_ratio") or 20.0)
    duck_ratio = max(1.0, min(20.0, duck_ratio))  # Clamp to 1.0-20.0
    duck_attack = float(data.get("duck_attack") or 1.0)
    duck_attack = max(0.1, min(10.0, duck_attack))  # Clamp to 0.1-10.0
    duck_release = float(data.get("duck_release") or 250.0)
    duck_release = max(10.0, min(1000.0, duck_release))  # Clamp to 10.0-1000.0

    try:
        from app.models import PlatformPreset, Project, db

        # Ensure unique project name by appending (1), (2), etc. if needed
        # This prevents directory collisions when multiple projects share the same name
        unique_name = name
        counter = 1
        while Project.query.filter_by(
            user_id=current_user.id, name=unique_name
        ).first():
            unique_name = f"{name} ({counter})"
            counter += 1

        pid = None
        try:
            pid = Project.generate_public_id()
        except Exception:
            pid = None
        project = Project(
            name=unique_name,
            description=description,
            tags=tags,
            user_id=current_user.id,
            max_clip_duration=max_clip_duration,
            output_resolution=output_resolution,
            output_format=output_format,
            fps=fps,
            quality=quality,
            public_id=pid,
            audio_norm_profile=audio_norm_profile,
            audio_norm_db=audio_norm_db,
            vertical_zoom=vertical_zoom,
            vertical_align=vertical_align,
            duck_threshold=duck_threshold,
            duck_ratio=duck_ratio,
            duck_attack=duck_attack,
            duck_release=duck_release,
        )

        # Set platform preset if specified
        if platform_preset_value:
            try:
                project.platform_preset = PlatformPreset(platform_preset_value)
            except (ValueError, AttributeError):
                pass

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
                    "error": "No workers are currently available to download clips. Please try again in a moment or contact support if this persists.",
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

                # Enrich missing metadata for Twitch clips
                if platform == "twitch" and (
                    not creator_name or not game_name or not clip_created_at
                ):
                    try:
                        from app.integrations.twitch import get_clip_by_id

                        clip_id = extract_key(url_s)
                        if clip_id:
                            twitch_clip = get_clip_by_id(clip_id)
                            if twitch_clip:
                                current_app.logger.info(
                                    f"Enriched clip metadata from Twitch for: {clip_id}"
                                )
                                if not creator_name:
                                    creator_name = twitch_clip.creator_name
                                if not creator_id:
                                    creator_id = twitch_clip.creator_id
                                if not game_name:
                                    game_name = twitch_clip.game_name
                                if not clip_created_at:
                                    clip_created_at = twitch_clip.created_at
                                if not title or title.startswith("Clip "):
                                    title = twitch_clip.title
                    except Exception as enrich_err:
                        current_app.logger.warning(
                            f"Failed to enrich metadata for {url_s}: {enrich_err}"
                        )

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
                    try:
                        logger.info(
                            "download_queued",
                            task_id=task_id,
                            clip_id=clip.id,
                            url=url_s,
                            queue=download_queue,
                            project_id=project.id,
                        )
                    except Exception:
                        # Fallback if structlog not working
                        current_app.logger.info(
                            f"Queued download task {task_id} for clip {clip.id}: {url_s} [queue={download_queue}]"
                        )
                except Exception as task_err:
                    logger.error(
                        "download_queue_failed",
                        clip_id=clip.id,
                        error=str(task_err),
                        error_type=type(task_err).__name__,
                    )
                    # Fallback error logging
                    current_app.logger.error(
                        f"Failed to queue download for clip {clip.id}: {task_err}"
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

            # Enrich metadata for Twitch clips (URL-only path)
            title = f"Clip {order_base + idx + 1}"
            creator_name = None
            creator_id = None
            game_name = None
            clip_created_at = None

            if platform == "twitch":
                try:
                    from app.integrations.twitch import get_clip_by_id

                    clip_id = extract_key(url_s)
                    if clip_id:
                        twitch_clip = get_clip_by_id(clip_id)
                        if twitch_clip:
                            current_app.logger.info(
                                f"Enriched clip metadata from Twitch for: {clip_id}"
                            )
                            creator_name = twitch_clip.creator_name
                            creator_id = twitch_clip.creator_id
                            game_name = twitch_clip.game_name
                            clip_created_at = twitch_clip.created_at
                            title = twitch_clip.title
                except Exception as enrich_err:
                    current_app.logger.warning(
                        f"Failed to enrich metadata for {url_s}: {enrich_err}"
                    )

            reused, media_file, src_platform = try_reuse(dedup_key)
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
                    is_downloaded=False,
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
                except Exception:
                    db.session.rollback()
                    continue
                try:
                    task = download_clip_task.apply_async(
                        args=(clip.id, url_s), queue=download_queue
                    )
                    task_id = task.id
                    logger.info(
                        "download_queued",
                        task_id=task_id,
                        clip_id=clip.id,
                        url=url_s,
                        queue=download_queue,
                        project_id=project.id,
                    )
                except Exception as task_err:
                    task_id = None
                    logger.error(
                        "download_queue_failed",
                        clip_id=clip.id,
                        error=str(task_err),
                        error_type=type(task_err).__name__,
                    )
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
                except Exception:
                    db.session.rollback()
                    continue
                task = download_clip_task.apply_async(
                    args=(clip.id, url_s), queue=download_queue
                )
                logger.info(
                    "download_queued",
                    task_id=task.id,
                    clip_id=clip.id,
                    url=url_s,
                    queue=download_queue,
                    project_id=project.id,
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

    # Log what we received for music debugging
    current_app.logger.info(
        f"Compile request for project {project_id}: "
        f"background_music_id={data.get('background_music_id')}, "
        f"music_volume={data.get('music_volume')}"
    )

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
        # Add debug info to help diagnose
        debug_msg = "Project has no clips to compile. "
        if clip_ids is not None:
            debug_msg += f"Requested {len(raw_clip_ids)} clip IDs, {len(clip_ids)} valid after filtering. "
            if len(raw_clip_ids) > 0 and len(clip_ids) == 0:
                debug_msg += (
                    f"None of the requested clips belong to project {project_id}."
                )
        else:
            debug_msg += f"Project has {project.clips.count()} clips total."
        current_app.logger.warning(debug_msg)
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

        # Log what we received
        current_app.logger.info(
            f"[compile_project_api] Received request for project {project_id}: "
            f"intro_id={intro_id}, outro_id={outro_id}, "
            f"transition_ids={transition_ids}, randomize={randomize_transitions}"
        )

        # Background music settings
        background_music_id = data.get("background_music_id")
        music_volume = data.get("music_volume")
        music_start_mode = data.get("music_start_mode") or "after_intro"
        music_end_mode = data.get("music_end_mode") or "before_outro"

        # Music ducking parameters
        duck_threshold = data.get("duck_threshold")
        duck_ratio = data.get("duck_ratio")
        duck_attack = data.get("duck_attack")
        duck_release = data.get("duck_release")

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
        # Determine render queue - NEVER use 'celery' queue for rendering
        # Default to gpu, or cpu if USE_GPU_QUEUE is false
        queue_name = "gpu" if bool(current_app.config.get("USE_GPU_QUEUE")) else "cpu"

        try:
            from app.tasks.celery_app import celery_app as _celery

            # Check for active workers and prefer available queues
            i = _celery.control.inspect(timeout=1.0)
            active_queues = set()
            if i:
                aq = i.active_queues() or {}
                for _worker, queues in aq.items():
                    for q in queues or []:
                        qname = q.get("name") if isinstance(q, dict) else None
                        if qname:
                            active_queues.add(qname)

            # Prefer gpu if available and configured, otherwise cpu
            if bool(current_app.config.get("USE_GPU_QUEUE")):
                if "gpu" in active_queues:
                    queue_name = "gpu"
                elif "cpu" in active_queues:
                    queue_name = "cpu"  # Fallback to CPU if GPU not available
                # else keep default "gpu" - task will wait for worker
            else:
                # CPU mode - prefer cpu queue if available
                if "cpu" in active_queues:
                    queue_name = "cpu"
                elif "gpu" in active_queues:
                    queue_name = "gpu"  # GPU can do CPU work
                # else keep default "cpu" - task will wait for worker
        except Exception:
            # On error, use configured default (never 'celery')
            pass

        # Save intro/outro/music settings to project before compilation
        if intro_id is not None:
            project.intro_media_id = intro_id
        if outro_id is not None:
            project.outro_media_id = outro_id
        if background_music_id is not None:
            project.background_music_id = background_music_id
        if music_volume is not None:
            project.music_volume = music_volume
        if music_start_mode is not None:
            project.music_start_mode = music_start_mode
        if music_end_mode is not None:
            project.music_end_mode = music_end_mode

        # Save ducking parameters if provided
        duck_threshold = data.get("duck_threshold")
        duck_ratio = data.get("duck_ratio")
        duck_attack = data.get("duck_attack")
        duck_release = data.get("duck_release")
        if duck_threshold is not None:
            project.duck_threshold = duck_threshold
        if duck_ratio is not None:
            project.duck_ratio = duck_ratio
        if duck_attack is not None:
            project.duck_attack = duck_attack
        if duck_release is not None:
            project.duck_release = duck_release

        # Log what we're sending to the task
        current_app.logger.info(
            f"[compile_project_api] Starting task for project {project_id}: "
            f"intro_id={intro_id}, outro_id={outro_id}, "
            f"transition_ids={valid_transition_ids} (from {transition_ids}), "
            f"randomize={randomize_transitions}, clip_ids={clip_ids}"
        )

        task = compile_video_task.apply_async(
            args=(project_id,),
            kwargs={
                "intro_id": intro_id,
                "outro_id": outro_id,
                "transition_ids": valid_transition_ids,
                "randomize_transitions": randomize_transitions,
                "clip_ids": clip_ids,
                "background_music_id": background_music_id,
                "music_volume": music_volume,
                "music_start_mode": music_start_mode,
                "music_end_mode": music_end_mode,
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


@api_bp.route("/projects/<int:project_id>/preview", methods=["POST"])
@login_required
def generate_preview_api(project_id: int):
    """Generate low-resolution preview for quick validation before compilation."""
    from app.models import Project, ProjectStatus, db

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if project.status == ProjectStatus.PROCESSING:
        return jsonify({"error": "Project is currently being processed"}), 400

    data = request.get_json(silent=True) or {}

    # Use same clip_ids logic as compilation
    raw_clip_ids = data.get("clip_ids")
    clip_ids: list[int] | None = None
    if isinstance(raw_clip_ids, list):
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
            from app.models import Clip

            rows = (
                db.session.query(Clip.id)
                .filter(Clip.project_id == project.id, Clip.id.in_(tmp))
                .all()
            )
            valid = {rid for (rid,) in rows}
            clip_ids = [rid for rid in tmp if rid in valid]
        else:
            clip_ids = []

    # Check for clips
    if (clip_ids is not None and len(clip_ids) == 0) or (
        clip_ids is None and project.clips.count() == 0
    ):
        return jsonify({"error": "Project has no clips to preview"}), 400

    # Queue preview generation task
    from app.tasks.preview_video import generate_preview_video_task

    # Dynamically select queue similar to compilation logic; prefer gpu, else cpu
    queue_name = "cpu"  # safe default (never use 'celery' for render work)
    active_queues = set()
    try:
        from app.tasks.celery_app import celery_app as _celery

        i = _celery.control.inspect(timeout=1.0)
        if i:
            aq = i.active_queues() or {}
            for _worker, queues in aq.items():
                for q in queues or []:
                    qname = q.get("name") if isinstance(q, dict) else None
                    if qname:
                        active_queues.add(qname)
        # Prefer gpu if available
        if "gpu" in active_queues:
            queue_name = "gpu"
        elif "cpu" in active_queues:
            queue_name = "cpu"
    except Exception as e:
        current_app.logger.warning(f"Preview queue inspection failed: {e}")

    logger.info(
        "preview_queue_select",
        project_id=project.id,
        queue=queue_name,
        active=list(active_queues),
        clip_ids=clip_ids if clip_ids is not None else "ALL",
        has_preview=bool(project.preview_filename),
    )

    task = generate_preview_video_task.apply_async(
        args=(project.id, clip_ids), queue=queue_name
    )
    logger.info(
        "preview_task_queued", task_id=task.id, project_id=project.id, queue=queue_name
    )
    return jsonify({"task_id": task.id, "status": "queued", "queue": queue_name}), 202


@api_bp.route("/projects/<int:project_id>/preview/video", methods=["GET"])
@login_required
def serve_preview_video(project_id: int):
    """Serve the preview video file for a project."""
    import os

    from flask import send_file

    from app.models import Project

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not project.preview_filename:
        return jsonify({"error": "Preview not yet generated"}), 404

    preview_dir = os.path.join(
        current_app.instance_path, "previews", str(project.user_id)
    )
    preview_path = os.path.join(preview_dir, project.preview_filename)

    if not os.path.exists(preview_path):
        logger.warning(
            "preview_file_missing",
            project_id=project.id,
            expected_path=preview_path,
            preview_filename=project.preview_filename,
        )
        return jsonify({"error": "Preview file not found"}), 404

    logger.info("preview_video_served", project_id=project.id, path=preview_path)
    return send_file(preview_path, mimetype="video/mp4", as_attachment=False)

    # Original preview code commented out for reference - all code below is unreachable
    # intro_id = data.get("intro_id")
    # outro_id = data.get("outro_id")
    # transition_ids = data.get("transition_ids") or []
    # randomize_transitions = bool(data.get("randomize_transitions") or False)
    #
    # # Determine queue (same logic as compilation - use GPU/CPU workers, never 'celery')
    # # Default to gpu, or cpu if USE_GPU_QUEUE is false
    # queue_name = "gpu" if bool(current_app.config.get("USE_GPU_QUEUE")) else "cpu"
    #
    # try:
    #     from app.tasks.celery_app import celery_app as _celery
    #
    #     # Check for active workers and prefer available queues
    #     i = _celery.control.inspect(timeout=1.0)
    #     active_queues = set()
    #     if i:
    #         aq = i.active_queues() or {}
    #         for _worker, queues in aq.items():
    #             for q in queues or []:
    #                 qname = q.get("name") if isinstance(q, dict) else None
    #                 if qname:
    #                     active_queues.add(qname)
    #
    #     # Prefer gpu if available and configured, otherwise cpu
    #     if bool(current_app.config.get("USE_GPU_QUEUE")):
    #         if "gpu" in active_queues:
    #             queue_name = "gpu"
    #         elif "cpu" in active_queues:
    #             queue_name = "cpu"  # Fallback to CPU if GPU not available
    #         # else keep default "gpu" - task will wait for worker
    #     else:
    #         # CPU mode - prefer cpu queue if available
    #         if "cpu" in active_queues:
    #             queue_name = "cpu"
    #         elif "gpu" in active_queues:
    #             queue_name = "gpu"  # GPU can do CPU work
    #         # else keep default "cpu" - task will wait for worker
    # except Exception:
    #     # On error, use configured default (never 'celery')
    #     pass
    #
    # # Start preview generation task on worker queue
    # task = generate_preview_task.apply_async(
    #     args=(project_id,),
    #     kwargs={
    #         "intro_id": intro_id,
    #         "outro_id": outro_id,
    #         "transition_ids": transition_ids,
    #         "randomize_transitions": randomize_transitions,
    #         "clip_ids": clip_ids,
    #     },
    #     queue=queue_name,
    # )
    #
    # db.session.commit()
    # return jsonify({"task_id": task.id, "status": "started"}), 202
    #
    # except Exception as e:
    #     try:
    #         db.session.rollback()
    #     except Exception:
    #         pass
    #     current_app.logger.error(f"Preview generation failed: {e}")
    #     return jsonify({"error": "Failed to start preview generation"}), 500


@api_bp.route("/projects/<int:project_id>/clips", methods=["GET"])
@login_required
def list_project_clips_api(project_id: int):
    import json
    import os
    import subprocess

    from app.models import Clip, Project

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    clips = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc()).all()
    items = []
    for c in clips:
        media = c.media_file
        # Prefer clip.duration, then media.duration, then probe file with ffprobe
        duration = (
            c.duration
            if c.duration is not None
            else (media.duration if media else None)
        )

        # Final fallback: probe the file with ffprobe if we still don't have duration
        if duration is None and media and media.file_path:
            try:
                file_path = os.path.join(current_app.instance_path, media.file_path)
                if os.path.exists(file_path):
                    from app.ffmpeg_config import _resolve_binary

                    ffprobe_bin = _resolve_binary(current_app, "ffprobe")

                    result = subprocess.run(
                        [
                            ffprobe_bin,
                            "-v",
                            "quiet",
                            "-print_format",
                            "json",
                            "-show_format",
                            file_path,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    if result.returncode == 0:
                        probe_data = json.loads(result.stdout)
                        if (
                            "format" in probe_data
                            and "duration" in probe_data["format"]
                        ):
                            duration = float(probe_data["format"]["duration"])
                            # Update the media file duration for future use
                            media.duration = duration
                            from app.models import db

                            db.session.commit()
            except Exception as e:
                current_app.logger.warning(
                    f"Failed to probe duration for clip {c.id}: {e}"
                )

        items.append(
            {
                "id": c.id,
                "title": c.title,
                "source_url": c.source_url,
                "is_downloaded": c.is_downloaded,
                "duration": duration,
                "view_count": c.view_count,
                "creator_name": c.creator_name,
                "game_name": c.game_name,
                "created_at": c.clip_created_at.isoformat()
                if c.clip_created_at
                else None,
                "avatar_url": url_for(
                    "api.avatar_by_clip", clip_id=c.id, _external=True
                )
                if c.creator_name
                else None,
                "media": (
                    {
                        "id": media.id,
                        "mime": media.mime_type,
                        "filename": media.filename,
                        "duration": media.duration,
                        "thumbnail_url": url_for(
                            "main.media_thumbnail", media_id=media.id, _external=True
                        )
                        if media
                        else None,
                        "preview_url": url_for(
                            "main.media_preview", media_id=media.id, _external=True
                        )
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


@api_bp.route("/projects/<int:project_id>/preset", methods=["POST"])
@login_required
def apply_platform_preset_api(project_id: int):
    """Apply a platform preset to a project, updating all export settings."""
    from app.models import PlatformPreset, Project, db

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    preset_value = data.get("preset")

    if not preset_value:
        return jsonify({"error": "Preset is required"}), 400

    # Validate preset
    try:
        preset = PlatformPreset(preset_value)
    except ValueError:
        return (
            jsonify(
                {
                    "error": f"Invalid preset. Must be one of: {', '.join(p.value for p in PlatformPreset)}"
                }
            ),
            400,
        )

    # Get preset settings
    settings = preset.get_settings()

    # Apply settings to project
    project.platform_preset = preset
    project.output_resolution = settings["resolution"]
    project.output_format = settings["format"]
    project.fps = settings["fps"]

    # Update quality based on bitrate
    if settings["bitrate"] and "M" in settings["bitrate"]:
        bitrate_mb = int(settings["bitrate"].replace("M", ""))
        if bitrate_mb >= 8:
            project.quality = "high"
        elif bitrate_mb >= 5:
            project.quality = "medium"
        else:
            project.quality = "low"

    try:
        db.session.commit()
        logger.info(
            "platform_preset_applied",
            project_id=project.id,
            preset=preset.value,
            user_id=current_user.id,
        )

        return jsonify(
            {
                "message": f"Applied {preset.display_name} preset",
                "preset": preset.value,
                "settings": {
                    "resolution": project.output_resolution,
                    "format": project.output_format,
                    "fps": project.fps,
                    "quality": project.quality,
                    "aspect_ratio": settings["aspect_ratio"],
                    "max_duration": settings["max_duration"],
                    "orientation": settings["orientation"],
                },
            }
        )
    except Exception as e:
        db.session.rollback()
        logger.error("preset_apply_failed", project_id=project.id, error=str(e))
        return jsonify({"error": "Failed to apply preset"}), 500


@api_bp.route("/presets", methods=["GET"])
@login_required
def list_platform_presets_api():
    """List all available platform presets with their settings."""
    from app.models import PlatformPreset

    presets = []
    for preset in PlatformPreset:
        settings = preset.get_settings()
        presets.append(
            {
                "value": preset.value,
                "name": preset.display_name,
                "settings": settings,
                "description": f"{settings['width']}x{settings['height']} ({settings['aspect_ratio']})"
                + (
                    f" • Max {settings['max_duration']}s"
                    if settings["max_duration"]
                    else ""
                ),
            }
        )

    return jsonify({"presets": presets})


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
            "public_id": project.public_id,
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
            "platform_preset": project.platform_preset.value
            if hasattr(project.platform_preset, "value")
            else str(project.platform_preset),
            "output_resolution": project.output_resolution,
            "output_format": project.output_format,
            "fps": project.fps,
            "vertical_zoom": getattr(project, "vertical_zoom", 100),
            "vertical_align": getattr(project, "vertical_align", "center"),
            "tags": project.tags,
            "description": getattr(project, "description", None),
        }
    )


@api_bp.route("/projects/<int:project_id>", methods=["PATCH"])
@login_required
def update_project_details_api(project_id: int):
    """Update project details (platform preset, format, fps, audio normalization, tags, description)."""
    from app.models import PlatformPreset, Project, db

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}

    # Update platform preset if provided
    if "platform_preset" in data:
        try:
            preset = PlatformPreset(data["platform_preset"])
            project.platform_preset = preset
            # Also update resolution based on preset
            settings = preset.get_settings()
            project.output_resolution = settings["resolution"]
        except ValueError:
            return jsonify({"error": "Invalid platform preset"}), 400

    # Update output format if provided
    if "output_format" in data:
        project.output_format = data["output_format"]

    # Update FPS if provided
    if "fps" in data:
        try:
            project.fps = int(data["fps"])
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid FPS value"}), 400

    # Update vertical video settings if provided
    if "vertical_zoom" in data:
        try:
            project.vertical_zoom = int(data["vertical_zoom"])
        except (ValueError, TypeError):
            project.vertical_zoom = 100
    if "vertical_align" in data:
        project.vertical_align = data["vertical_align"]

    # Update audio normalization if provided
    if "audio_norm_profile" in data:
        project.audio_norm_profile = data["audio_norm_profile"]
    if "audio_norm_db" in data:
        try:
            project.audio_norm_db = (
                float(data["audio_norm_db"]) if data["audio_norm_db"] else None
            )
        except (ValueError, TypeError):
            project.audio_norm_db = None

    # Update tags if provided
    if "tags" in data:
        project.tags = data["tags"]

    # Update description if provided
    if "description" in data:
        project.description = data["description"]

    try:
        db.session.commit()
        logger.info(
            "project_details_updated",
            project_id=project.id,
            user_id=current_user.id,
            updated_fields=list(data.keys()),
        )

        return jsonify(
            {
                "message": "Project details updated successfully",
                "platform_preset": project.platform_preset.value
                if hasattr(project.platform_preset, "value")
                else str(project.platform_preset),
                "output_format": project.output_format,
                "fps": project.fps,
                "audio_norm_profile": project.audio_norm_profile,
                "audio_norm_db": project.audio_norm_db,
                "tags": project.tags,
                "description": getattr(project, "description", None),
            }
        )
    except Exception as e:
        db.session.rollback()
        logger.error("project_update_failed", project_id=project.id, error=str(e))
        return jsonify({"error": "Failed to update project details"}), 500


@api_bp.route("/projects/<int:project_id>/wizard", methods=["PATCH"])
@login_required
def update_wizard_state_api(project_id: int):
    """
    Update wizard state for a project (resumability).

    Request JSON:
    {
        "wizard_step": 1-4,  // Optional: current wizard step
        "wizard_state": {},  // Optional: step-specific state (JSON object)
        "status": "ready"    // Optional: update status (e.g., DRAFT -> READY)
    }

    Returns:
        JSON response with updated project info
    """
    from app.models import Project, ProjectStatus, db

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}

    # Update wizard_step (1-4)
    if "wizard_step" in data:
        step = int(data["wizard_step"])
        if 1 <= step <= 4:
            project.wizard_step = step
        else:
            return jsonify({"error": "wizard_step must be 1-4"}), 400

    # Update wizard_state (JSON blob)
    if "wizard_state" in data:
        import json

        try:
            # Validate it's valid JSON and serialize
            state_obj = data["wizard_state"]
            if state_obj is not None:
                project.wizard_state = json.dumps(state_obj)
            else:
                project.wizard_state = None
        except (TypeError, ValueError) as e:
            return jsonify({"error": f"Invalid wizard_state: {e}"}), 400

    # Update status (e.g., DRAFT -> READY)
    if "status" in data:
        status_value = data["status"].lower()
        try:
            new_status = ProjectStatus(status_value)
            # Only allow DRAFT -> READY or READY -> DRAFT transitions via this endpoint
            if new_status in (ProjectStatus.DRAFT, ProjectStatus.READY):
                project.status = new_status
            else:
                return (
                    jsonify(
                        {
                            "error": f"Cannot set status to {status_value} via wizard endpoint"
                        }
                    ),
                    400,
                )
        except ValueError:
            return jsonify({"error": f"Invalid status: {status_value}"}), 400

    try:
        db.session.commit()
        logger.info(
            "wizard_state_updated",
            project_id=project.id,
            wizard_step=project.wizard_step,
            status=project.status.value,
        )
    except Exception as e:
        db.session.rollback()
        logger.error("wizard_state_update_failed", project_id=project.id, error=str(e))
        return jsonify({"error": "Failed to update wizard state"}), 500

    return jsonify(
        {
            "id": project.id,
            "wizard_step": project.wizard_step,
            "wizard_state": project.wizard_state,
            "status": project.status.value,
        }
    )
