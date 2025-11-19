"""
Video processing tasks for Clippy platform.

This module contains Celery tasks for video compilation, clip downloading,
and media processing using ffmpeg and yt-dlp.
"""
import errno
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Any

from sqlalchemy.orm import scoped_session, sessionmaker

from app import storage as storage_lib
from app.ffmpeg_config import (
    audio_args,
    build_overlay_filter,
    cpu_encoder_args,
    encoder_args,
    overlay_enabled,
    parse_resolution,
    resolve_fontfile,
)
from app.models import (
    Clip,
    MediaFile,
    MediaType,
    ProcessingJob,
    Project,
    ProjectStatus,
    User,
    db,
)
from app.quotas import (
    check_storage_quota,
    record_render_usage,
    should_apply_watermark,
    storage_remaining_bytes,
)
from app.tasks.celery_app import celery_app

# Reuse a single Flask app per worker process to avoid repeatedly opening
# DB connections and re-applying runtime settings on every helper call.
_WORKER_APP = None


def _get_app():
    global _WORKER_APP
    if _WORKER_APP is None:
        from app import create_app as _create_app

        _WORKER_APP = _create_app()
    return _WORKER_APP


# ----- Tier limit helpers -----
def _normalize_res_label(val: str | None) -> str | None:
    """Normalize a resolution label from various inputs.

    Accepts labels like '720p', '1080p', '1440p' ('2k'), '2160p' ('4k'), or WxH strings.
    Returns one of: '720p' | '1080p' | '1440p' | '2160p' or None if unknown.
    """
    if not val:
        return None
    s = str(val).strip().lower()
    if s in {"720p", "1080p", "1440p", "2160p"}:
        return s
    if s in {"2k"}:
        return "1440p"
    if s in {"4k"}:
        return "2160p"
    if "x" in s:
        try:
            parts = s.split("x")
            h = int(parts[1]) if len(parts) > 1 else None
            if h:
                if h <= 720:
                    return "720p"
                if h <= 1080:
                    return "1080p"
                if h <= 1440:
                    return "1440p"
                return "2160p"
        except Exception:
            return None
    return None


def _res_rank(label: str | None) -> int:
    order = {None: -1, "720p": 0, "1080p": 1, "1440p": 2, "2160p": 3}
    return order.get(label, -1)


def _cap_resolution_label(
    project_val: str | None, tier_max_label: str | None
) -> str | None:
    p = _normalize_res_label(project_val)
    t = _normalize_res_label(tier_max_label)
    if not t:
        return p  # no cap
    if not p:
        return t  # default to tier when project undefined
    return p if _res_rank(p) <= _res_rank(t) else t


def _get_user_tier_limits(session, user_id: int) -> dict[str, Any]:
    """Fetch effective tier limits for the user.

    Returns dict with keys: max_res_label, max_fps, max_clips. None means unlimited.
    """
    try:
        u = session.get(User, user_id)
        if not u or not getattr(u, "tier", None) or u.tier.is_unlimited:
            return {"max_res_label": None, "max_fps": None, "max_clips": None}
        return {
            "max_res_label": _normalize_res_label(
                getattr(u.tier, "max_output_resolution", None)
            ),
            "max_fps": getattr(u.tier, "max_fps", None),
            "max_clips": getattr(u.tier, "max_clips_per_project", None),
        }
    except Exception:
        return {"max_res_label": None, "max_fps": None, "max_clips": None}


def get_db_session():
    """
    Get a new database session for use in Celery tasks.

    Returns:
        Session: Database session

    Raises:
        RuntimeError: If DATABASE_URL is not configured
    """
    app = _get_app()

    with app.app_context():
        # Verify database is configured
        db_url = app.config.get("SQLALCHEMY_DATABASE_URI", "").strip()
        if not db_url or db_url == "sqlite:///:memory:":
            raise RuntimeError(
                "DATABASE_URL not configured for worker. "
                "Workers currently require database access to function. "
                "See WORKER_API_MIGRATION.md and .env.worker.example for configuration details."
            )

        # Create a new session for this task
        Session = scoped_session(sessionmaker(bind=db.engine))
        return Session()


def _resolve_media_input_path(orig_path: str) -> str:
    """Resolve a media input path that may have been created on a different host.

    Handles two strategies:
      1) Explicit env alias: MEDIA_PATH_ALIAS_FROM + MEDIA_PATH_ALIAS_TO
         If orig_path startswith FROM, replace with TO and use if it exists.
      2) Automatic instance path remap: if the path contains '/instance/',
         rebuild path under this process's app.instance_path preserving the suffix.

    Returns the first existing candidate, else the original path.
    """
    try:
        debug = os.getenv("MEDIA_PATH_DEBUG", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if orig_path and os.path.exists(orig_path):
            if debug:
                print(f"[media-path] using original path (exists): {orig_path}")
            return orig_path
        ap = (orig_path or "").strip()
        if not ap:
            return orig_path
        # 1) Explicit alias
        alias_from = os.getenv("MEDIA_PATH_ALIAS_FROM")
        alias_to = os.getenv("MEDIA_PATH_ALIAS_TO")
        if alias_from and alias_to and ap.startswith(alias_from):
            cand = alias_to + ap[len(alias_from) :]
            if debug:
                print(
                    f"[media-path] alias candidate: FROM='{alias_from}' TO='{alias_to}' -> '{cand}' (exists={os.path.exists(cand)})"
                )
            if os.path.exists(cand):
                return cand
        # 2) Automatic '/instance/' remap
        marker = "/instance/"
        if marker in ap:
            try:
                app = _get_app()
                suffix = ap.split(marker, 1)[1]
                cand = os.path.join(app.instance_path, suffix)
                if debug:
                    print(
                        f"[media-path] instance remap candidate: base='{app.instance_path}' suffix='/{suffix}' -> '{cand}' (exists={os.path.exists(cand)})"
                    )
                if os.path.exists(cand):
                    return cand
                # Heuristic: if we're running in a different host (e.g., container), prefer
                # remapped app.instance_path even if the file existence check fails here.
                # This avoids trying to use the original host path inside the worker.
                try:
                    base_before_marker = ap.split(marker, 1)[0]
                except Exception:
                    base_before_marker = ""
                # If the base differs from our instance_path and our instance_path exists, we may be inside a container
                # where existence checks on host paths fail; in that case, the remap to app.instance_path is correct.
                # Only trust this path when running in a container; otherwise continue to alternate strategies.
                running_in_container = bool(
                    os.getenv("RUNNING_IN_CONTAINER")
                    or os.getenv("IN_CONTAINER")
                    or os.path.exists("/.dockerenv")
                )
                if (
                    base_before_marker.rstrip("/") != str(app.instance_path).rstrip("/")
                    and os.path.isdir(app.instance_path)
                    and running_in_container
                ):
                    if debug:
                        print(
                            f"[media-path] using remap path (container context) despite exists=False: '{cand}'"
                        )
                    return cand
            except Exception:
                pass
        # 2b) Automatic data-root remap: if path contains '/<DATA_FOLDER>/' under a different root,
        # rebuild under this process's app.instance_path/<DATA_FOLDER>/...
        try:
            app2 = _get_app()
            with app2.app_context():
                data_folder = (app2.config.get("DATA_FOLDER") or "data").strip("/")
                marker2 = f"/{data_folder}/"
                if marker2 in ap and not ap.startswith(str(app2.instance_path)):
                    suffix = ap.split(marker2, 1)[1]
                    cand2 = os.path.join(app2.instance_path, data_folder, suffix)
                    if debug:
                        try:
                            print(
                                f"[media-path] data-root remap candidate: base='{app2.instance_path}' folder='{data_folder}' suffix='/{suffix}' -> '{cand2}' (exists={os.path.exists(cand2)})"
                            )
                        except Exception:
                            pass
                    if os.path.exists(cand2):
                        return cand2
                    # Container heuristic as above: if roots differ, allow remap even if exists check fails
                    base_before_marker2 = ap.split(marker2, 1)[0]
                    running_in_container = bool(
                        os.getenv("RUNNING_IN_CONTAINER")
                        or os.getenv("IN_CONTAINER")
                        or os.path.exists("/.dockerenv")
                    )
                    if (
                        base_before_marker2.rstrip("/")
                        != str(app2.instance_path).rstrip("/")
                        and os.path.isdir(app2.instance_path)
                        and running_in_container
                    ):
                        if debug:
                            try:
                                print(
                                    f"[media-path] using data-root remap (container context) despite exists=False: '{cand2}'"
                                )
                            except Exception:
                                pass
                        return cand2
        except Exception:
            pass
    except Exception:
        pass
    return orig_path


@celery_app.task(bind=True)
def compile_video_task(
    self,
    project_id: int,
    intro_id: int | None = None,
    outro_id: int | None = None,
    transition_ids: list[int] | None = None,
    randomize_transitions: bool = False,
    clip_ids: list[int] | None = None,
) -> dict[str, Any]:
    """
    Compile video clips into a final compilation.

    Args:
        project_id: ID of the project to compile

    Returns:
        Dict: Task result with output file information
    """
    session = get_db_session()

    try:
        # Update task status
        self.update_state(
            state="PROGRESS", meta={"progress": 0, "status": "Starting compilation"}
        )

        # Get project and validate
        project = session.query(Project).get(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Create processing job record
        job = ProcessingJob(
            celery_task_id=self.request.id,
            job_type="compile_video",
            project_id=project_id,
            user_id=project.user_id,
            status="started",
            started_at=datetime.utcnow(),
        )
        session.add(job)
        session.commit()

        # Helper to append a log entry into result_data.logs
        def log(level: str, message: str, status: str | None = None):
            nonlocal job
            rd = job.result_data or {}
            logs = rd.get("logs") or []
            logs.append(
                {
                    "ts": datetime.utcnow().isoformat(),
                    "level": level,
                    "message": message,
                    "status": status,
                }
            )
            rd["logs"] = logs
            job.result_data = rd
            try:
                session.add(job)
                session.commit()
            except Exception:
                session.rollback()

        # Get clips in order (honor explicit timeline subset if provided)
        if clip_ids:
            # Fetch only the requested clips that belong to this project, then preserve requested order
            rows = (
                session.query(Clip)
                .filter(Clip.project_id == project_id, Clip.id.in_(clip_ids))
                .all()
            )
            by_id = {c.id: c for c in rows}
            clips = [by_id[cid] for cid in clip_ids if cid in by_id]
        else:
            clips = (
                session.query(Clip)
                .filter_by(project_id=project_id)
                .order_by(Clip.order_index.asc(), Clip.created_at.asc())
                .all()
            )

        # Apply tier-based limits (clip count)
        limits = _get_user_tier_limits(session, project.user_id)
        if limits.get("max_clips"):
            maxc = int(limits["max_clips"]) or 0
            if maxc > 0 and len(clips) > maxc:
                clips = clips[:maxc]
                log(
                    "info",
                    f"Tier limit: using first {maxc} clip(s) out of {len(rows) if clip_ids else session.query(Clip).filter_by(project_id=project_id).count()}",
                    status="limits",
                )

        if not clips:
            raise ValueError("No clips found for compilation")

        self.update_state(
            state="PROGRESS", meta={"progress": 10, "status": "Preparing clips"}
        )
        log("info", "Preparing clips", status="preparing")
        try:
            job.progress = 10
            session.add(job)
            session.commit()
        except Exception:
            session.rollback()

        # Create temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Process each clip
            processed_clips = []
            used_clip_ids: list[int] = []

            for i, clip in enumerate(clips):
                progress = 10 + (i / len(clips)) * 60  # 10-70% for clip processing
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "progress": progress,
                        "status": f"Processing clip {i+1}/{len(clips)}",
                    },
                )
                log("info", f"Processing clip {i+1}/{len(clips)}")
                try:
                    job.progress = int(progress)
                    session.add(job)
                    session.commit()
                except Exception:
                    session.rollback()

                clip_path = process_clip(session, clip, temp_dir, project)
                if clip_path:
                    processed_clips.append(clip_path)
                    try:
                        used_clip_ids.append(int(clip.id))
                    except Exception:
                        pass

            if not processed_clips:
                raise ValueError("No clips could be processed")

            self.update_state(
                state="PROGRESS", meta={"progress": 70, "status": "Adding intro/outro"}
            )
            log("info", "Adding intro/outro")
            try:
                job.progress = 70
                session.add(job)
                session.commit()
            except Exception:
                session.rollback()

            # Add intro/outro and interleave transitions if available
            final_clips = build_timeline_with_transitions(
                session=session,
                project=project,
                processed_clips=processed_clips,
                temp_dir=temp_dir,
                intro_id=intro_id,
                outro_id=outro_id,
                transition_ids=transition_ids or [],
                randomize=randomize_transitions,
            )

            self.update_state(
                state="PROGRESS",
                meta={"progress": 80, "status": "Compiling final video"},
            )
            log("info", "Compiling final video", status="compiling")
            try:
                job.progress = 80
                session.add(job)
                session.commit()
            except Exception:
                session.rollback()

            # Optional: read ordered labels for nicer logging during concat
            labels_path = os.path.join(temp_dir, "concat_labels.json")
            ordered_labels: list[str] = []
            try:
                if os.path.exists(labels_path):
                    with open(labels_path) as fp:
                        ordered_labels = json.load(fp) or []
            except Exception:
                ordered_labels = []

            # Emit pre-concat logs with names
            try:
                total_items = len(final_clips)
                for idx, label in enumerate(ordered_labels or []):
                    log(
                        "info",
                        f"Concatenating: {label} ({idx+1} of {total_items})",
                        status="concatenating",
                    )
            except Exception:
                pass

            # Compile final video
            output_path = compile_final_video(final_clips, temp_dir, project)

            self.update_state(
                state="PROGRESS", meta={"progress": 90, "status": "Saving output"}
            )
            log("info", "Saving output", status="saving")
            try:
                job.progress = 90
                session.add(job)
                session.commit()
            except Exception:
                session.rollback()

            # Move to final location and update project
            final_output_path = save_final_video(output_path, project)

            # Create a MediaFile record for the final compilation so it appears in the media library
            try:
                media = MediaFile(
                    filename=os.path.basename(final_output_path),
                    original_filename=os.path.basename(final_output_path),
                    file_path=storage_lib.instance_canonicalize(final_output_path)
                    or final_output_path,
                    file_size=os.path.getsize(final_output_path),
                    mime_type="video/mp4",
                    media_type=MediaType.COMPILATION,
                    user_id=project.user_id,
                    project_id=project.id,
                    is_processed=True,
                )
                # Extract metadata for final render
                meta = extract_video_metadata(final_output_path)
                if meta:
                    media.duration = meta.get("duration")
                    media.width = meta.get("width")
                    media.height = meta.get("height")
                    media.framerate = meta.get("framerate")
                # Generate thumbnail for final render
                try:
                    app = _get_app()
                    # Resolve thumbnails directory via project-based storage
                    with app.app_context():
                        try:
                            # Project.user relationship may not be loaded here; fetch if needed
                            user_obj = session.query(User).get(project.user_id)
                        except Exception:
                            user_obj = None
                        thumbs_dir = storage_lib.thumbnails_dir(
                            user_obj or project.owner
                        )
                        os.makedirs(thumbs_dir, exist_ok=True)
                    # Deterministic name based on final output filename
                    stem = os.path.splitext(os.path.basename(final_output_path))[0]
                    thumb_path = os.path.join(thumbs_dir, f"{stem}.jpg")
                    if not os.path.exists(thumb_path):
                        ffmpeg_bin = resolve_binary(app, "ffmpeg")
                        ts = str(app.config.get("THUMBNAIL_TIMESTAMP_SECONDS", 1))
                        w = int(app.config.get("THUMBNAIL_WIDTH", 480))
                        from app.ffmpeg_config import config_args as _cfg_args

                        subprocess.run(
                            [
                                ffmpeg_bin,
                                *_cfg_args(app, "ffmpeg", "thumbnail"),
                                "-y",
                                "-ss",
                                ts,
                                "-i",
                                final_output_path,
                                "-frames:v",
                                "1",
                                "-vf",
                                f"scale={w}:-1",
                                thumb_path,
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=True,
                        )
                    media.thumbnail_path = (
                        storage_lib.instance_canonicalize(thumb_path) or thumb_path
                    )
                except Exception:
                    pass

                session.add(media)
            except Exception:
                # Do not fail the compilation if media record creation fails
                pass

            # Update project status
            project.status = ProjectStatus.COMPLETED
            project.completed_at = datetime.utcnow()
            project.output_filename = os.path.basename(final_output_path)
            project.output_file_size = os.path.getsize(final_output_path)

            # Record render usage for this user/month based on final output duration
            try:
                seconds = None
                try:
                    # If we created a media record above, prefer its duration
                    if "media" in locals() and getattr(media, "duration", None):
                        seconds = int(float(media.duration))
                except Exception:
                    seconds = None
                if seconds is None:
                    meta2 = extract_video_metadata(final_output_path)
                    seconds = int(float(meta2.get("duration") or 0)) if meta2 else 0
                if seconds and seconds > 0:
                    record_render_usage(
                        project.user_id, project.id, int(seconds), session=session
                    )
            except Exception:
                pass

            # Update job status
            job.status = "success"
            job.completed_at = datetime.utcnow()
            job.progress = 100
            job.result_data = {
                "output_file": storage_lib.instance_canonicalize(final_output_path)
                or final_output_path,
                "clips_processed": len(processed_clips),
                "used_clip_ids": used_clip_ids,
                "duration": (datetime.utcnow() - job.started_at).total_seconds(),
                **(job.result_data or {}),
            }
            log("success", "Compilation completed", status="completed")

            session.commit()

            return {
                "status": "completed",
                "output_file": storage_lib.instance_canonicalize(final_output_path)
                or final_output_path,
                "clips_processed": len(processed_clips),
                "project_id": project_id,
                "used_clip_ids": used_clip_ids,
            }

    except Exception as e:
        # Update project and job status on error
        if "project" in locals() and project:
            project.status = ProjectStatus.FAILED
            project.processing_log = str(e)

        if "job" in locals() and job:
            job.status = "failure"
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            rd = job.result_data or {}
            logs = rd.get("logs") or []
            logs.append(
                {
                    "ts": datetime.utcnow().isoformat(),
                    "level": "error",
                    "message": str(e),
                    "status": "failed",
                }
            )
            rd["logs"] = logs
            job.result_data = rd

        session.commit()
        session.close()

        raise
    finally:
        # Always release DB connections on worker to avoid exhausting the pool
        try:
            session.close()
        except Exception:
            pass


@celery_app.task(bind=True, queue="celery")
def download_clip_task(self, clip_id: int, source_url: str) -> dict[str, Any]:
    """
    Download a clip from external source using yt-dlp.

    Args:
        clip_id: ID of the clip to download
        source_url: URL to download from

    Returns:
        Dict: Task result with downloaded file information
    """
    session = get_db_session()

    try:
        # Proactively clean any legacy leftovers for this clip under instance/downloads
        try:
            _app0 = _get_app()
            with _app0.app_context():
                _legacy_dir0 = os.path.join(_app0.instance_path, "downloads")
            if os.path.isdir(_legacy_dir0):
                prefix0 = f"clip_{clip_id}_"
                for _fname in list(os.listdir(_legacy_dir0)):
                    if _fname.startswith(prefix0):
                        try:
                            os.remove(os.path.join(_legacy_dir0, _fname))
                        except Exception:
                            pass
                # Remove dir if empty
                try:
                    if not os.listdir(_legacy_dir0):
                        os.rmdir(_legacy_dir0)
                except Exception:
                    pass
        except Exception:
            pass

        clip = session.query(Clip).get(clip_id)
        if not clip:
            raise ValueError(f"Clip {clip_id} not found")

        # Create processing job
        job = ProcessingJob(
            celery_task_id=self.request.id,
            job_type="download_clip",
            project_id=clip.project_id,
            user_id=clip.project.user_id,
            status="started",
            started_at=datetime.utcnow(),
        )
        session.add(job)
        session.commit()

        def log(level: str, message: str, status: str | None = None):
            nonlocal job
            rd = job.result_data or {}
            logs = rd.get("logs") or []
            logs.append(
                {
                    "ts": datetime.utcnow().isoformat(),
                    "level": level,
                    "message": message,
                    "status": status,
                }
            )
            rd["logs"] = logs
            job.result_data = rd
            try:
                session.add(job)
                session.commit()
            except Exception:
                session.rollback()

        self.update_state(
            state="PROGRESS", meta={"progress": 10, "status": "Starting download"}
        )
        log("info", f"Starting download: clip {clip_id}", status="downloading")
        try:
            job.progress = 10
            session.add(job)
            session.commit()
        except Exception:
            session.rollback()

        # Enforce storage quota before download using remaining as yt-dlp --max-filesize
        user_obj = session.get(User, clip.project.user_id)
        rem_bytes = None
        try:
            if user_obj:
                rem_bytes = storage_remaining_bytes(user_obj, session=session)
        except Exception:
            rem_bytes = None
        if rem_bytes is not None and int(rem_bytes) <= 0:
            raise RuntimeError(
                "Storage quota exceeded: no remaining bytes for download"
            )

        # Attempt reuse BEFORE downloading: find an existing media for this user with the same Twitch clip key or normalized URL
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

        try:
            key = _extract_clip_key(source_url)
            norm = _normalize_url(source_url)
            # Look for any previously downloaded clip by this user with a matching key or normalized URL
            candidates = (
                session.query(Clip)
                .join(Project, Project.id == Clip.project_id)
                .filter(
                    Project.user_id == clip.project.user_id,
                    Clip.media_file_id.isnot(None),
                )
                .order_by(Clip.created_at.desc())
                .limit(500)
                .all()
            )
            for prev in candidates:
                try:
                    pv_key = _extract_clip_key(prev.source_url or "")
                    pv_norm = _normalize_url(prev.source_url or "")
                except Exception:
                    pv_key = ""
                    pv_norm = ""
                if (pv_key and key and pv_key == key) or (pv_norm and pv_norm == norm):
                    if prev.media_file_id:
                        mf = session.get(MediaFile, prev.media_file_id)
                        # Resolve path for existence check (supports canonical '/instance/...')
                        cand_path = _resolve_media_input_path(
                            getattr(mf, "file_path", "") or ""
                        )
                        if mf and cand_path and os.path.exists(cand_path):
                            # Reuse: attach existing media to this clip and finish
                            clip.media_file = mf
                            clip.is_downloaded = True
                            clip.duration = mf.duration
                            clip.collected_at = datetime.utcnow()
                            job.status = "success"
                            job.completed_at = datetime.utcnow()
                            job.progress = 100
                            job.result_data = {
                                "reused_media_file_id": mf.id,
                                "reused_from_clip_id": prev.id,
                                **(job.result_data or {}),
                            }
                            session.commit()
                            log(
                                "success",
                                "Reused existing media (no download)",
                                status="reused",
                            )
                            return {
                                "status": "reused",
                                "media_file_id": mf.id,
                                "clip_id": clip_id,
                            }

        except Exception:
            # If reuse check fails, proceed to download
            pass

        # Download with yt-dlp (apply constraint when available)
        # Choose a project-aware download directory when using project layout
        dl_dir = None
        try:
            app = _get_app()
            with app.app_context():
                try:
                    dl_dir = storage_lib.clips_dir(
                        user_obj or clip.project.owner, clip.project.name
                    )
                except Exception:
                    dl_dir = None
        except Exception:
            dl_dir = None

        output_path = download_with_yt_dlp(
            source_url,
            clip,
            max_bytes=int(rem_bytes) if rem_bytes is not None else None,
            download_dir=dl_dir,
        )

        self.update_state(
            state="PROGRESS",
            meta={"progress": 80, "status": "Creating media file record"},
        )
        log("info", "Creating media file record")
        try:
            job.progress = 80
            session.add(job)
            session.commit()
        except Exception:
            session.rollback()

        # Create media file record
        db_file_path = storage_lib.instance_canonicalize(output_path) or output_path
        media_file = MediaFile(
            filename=os.path.basename(output_path),
            original_filename=f"downloaded_{clip.title}",
            file_path=db_file_path,
            file_size=os.path.getsize(output_path),
            mime_type="video/mp4",
            media_type=MediaType.CLIP,
            user_id=clip.project.user_id,
            project_id=clip.project_id,
        )

        # Extract video metadata
        metadata = extract_video_metadata(output_path)
        if metadata:
            media_file.duration = metadata.get("duration")
            media_file.width = metadata.get("width")
            media_file.height = metadata.get("height")
            media_file.framerate = metadata.get("framerate")

        # Generate thumbnail for the downloaded video
        try:
            app = _get_app()
            with app.app_context():
                owner = session.get(User, clip.project.user_id)
                thumbs_dir = storage_lib.thumbnails_dir(owner or clip.project.owner)
                os.makedirs(thumbs_dir, exist_ok=True)
            # Deterministic thumbnail name to avoid duplicates across restarts
            stem = os.path.splitext(os.path.basename(output_path))[0]
            thumb_path = os.path.join(thumbs_dir, f"{stem}.jpg")

            if not os.path.exists(thumb_path):
                ffmpeg_bin = resolve_binary(app, "ffmpeg")
                ts = str(app.config.get("THUMBNAIL_TIMESTAMP_SECONDS", 1))
                w = int(app.config.get("THUMBNAIL_WIDTH", 480))
                from app.ffmpeg_config import config_args as _cfg_args

                subprocess.run(
                    [
                        ffmpeg_bin,
                        *_cfg_args(app, "ffmpeg", "thumbnail"),
                        "-y",
                        "-ss",
                        ts,
                        "-i",
                        output_path,
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={w}:-1",
                        thumb_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            media_file.thumbnail_path = (
                storage_lib.instance_canonicalize(thumb_path) or thumb_path
            )
        except Exception as thumb_err:
            # Do not fail the task if thumbnail creation fails
            print(f"Thumbnail generation failed for clip {clip.id}: {thumb_err}")

        # Post-download storage enforcement: if we crossed the limit due to race, abort and clean up
        try:
            if user_obj:
                chk = check_storage_quota(user_obj, additional_bytes=0, session=session)
                if not chk.ok:
                    try:
                        if os.path.exists(output_path):
                            os.remove(output_path)
                    except Exception:
                        pass
                    raise RuntimeError("Storage quota exceeded after download")
        except Exception:
            pass

        # Compute checksum for dedupe-once-downloaded
        try:
            import hashlib as _hashlib

            h = _hashlib.sha256()
            with open(output_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            media_file.checksum = h.hexdigest()
        except Exception:
            media_file.checksum = None

        # If another identical file exists for this user, reuse it and delete the new file
        try:
            if media_file.checksum:
                dup = (
                    session.query(MediaFile)
                    .filter_by(
                        user_id=clip.project.user_id, checksum=media_file.checksum
                    )
                    .first()
                )
                dup_path = (
                    _resolve_media_input_path(getattr(dup, "file_path", "") or "")
                    if dup
                    else None
                )
                if dup_path and os.path.exists(dup_path):
                    # Remove freshly downloaded duplicate and reuse existing
                    try:
                        if os.path.exists(output_path):
                            os.remove(output_path)
                    except Exception:
                        pass
                    clip.media_file = dup
                    clip.is_downloaded = True
                    clip.duration = dup.duration
                    clip.collected_at = datetime.utcnow()
                    job.status = "success"
                    job.completed_at = datetime.utcnow()
                    job.progress = 100
                    job.result_data = {
                        "reused_media_file_id": dup.id,
                        "deduped_by_checksum": True,
                        **(job.result_data or {}),
                    }
                    session.commit()
                    log(
                        "success", "Reused identical media by checksum", status="reused"
                    )
                    return {
                        "status": "reused",
                        "media_file_id": dup.id,
                        "clip_id": clip_id,
                    }
        except Exception:
            pass

        session.add(media_file)
        session.flush()  # ensure media_file.id is available

        # Update clip
        clip.media_file = media_file
        clip.is_downloaded = True
        clip.duration = media_file.duration
        clip.collected_at = datetime.utcnow()

        # Update job
        job.status = "success"
        job.completed_at = datetime.utcnow()
        job.progress = 100
        job.result_data = {
            "downloaded_file": storage_lib.instance_canonicalize(output_path)
            or output_path,
            "media_file_id": media_file.id,
            **(job.result_data or {}),
        }
        log("success", "Download completed", status="completed")

        session.commit()

        return {
            "status": "completed",
            "downloaded_file": storage_lib.instance_canonicalize(output_path)
            or output_path,
            "media_file_id": media_file.id,
            "clip_id": clip_id,
        }

    except Exception as e:
        if "job" in locals() and job:
            job.status = "failure"
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            rd = job.result_data or {}
            logs = rd.get("logs") or []
            logs.append(
                {
                    "ts": datetime.utcnow().isoformat(),
                    "level": "error",
                    "message": str(e),
                    "status": "failed",
                }
            )
            rd["logs"] = logs
            job.result_data = rd
            session.commit()

        raise
    finally:
        # Ensure connections are not leaked on success or failure
        try:
            session.close()
        except Exception:
            pass


def process_clip(session, clip: Clip, temp_dir: str, project: Project) -> str:
    """
    Process a single clip for compilation.

    Args:
        session: Database session
        clip: Clip object to process
        temp_dir: Temporary directory for processing
        project: Parent project

    Returns:
        str: Path to processed clip file
    """
    if not clip.media_file:
        raise ValueError(f"Clip {clip.id} has no associated media file")

    # Resolve and repair input path if DB path is stale
    original_db_path = clip.media_file.file_path if clip.media_file else None
    input_path = _resolve_media_input_path(original_db_path or "")
    try:
        if (
            original_db_path
            and (not os.path.exists(original_db_path))
            and input_path
            and os.path.exists(input_path)
        ):
            # Persist the corrected path so future runs don't hit the fallback again
            clip.media_file.file_path = input_path
            try:
                session.add(clip.media_file)
                session.commit()
            except Exception:
                session.rollback()
    except Exception:
        pass
    output_path = os.path.join(temp_dir, f"clip_{clip.id}_processed.mp4")

    # Build ffmpeg command for clip processing with quality + overlay
    app = _get_app()
    ffmpeg_bin = resolve_binary(app, "ffmpeg")
    # Debug NVENC availability and chosen ffmpeg
    try:
        if os.getenv("FFMPEG_DEBUG"):
            from app.ffmpeg_config import detect_nvenc as _detect

            ok, reason = _detect(ffmpeg_bin)
            print(
                f"[ffmpeg] using='{ffmpeg_bin}' nvenc_available={ok} reason='{reason}'"
            )
    except Exception:
        pass
    # Include configurable global/encode args
    from app.ffmpeg_config import config_args as _cfg_args

    cmd = [ffmpeg_bin, *_cfg_args(app, "ffmpeg", "encode")]

    # Add clip trimming if specified
    if clip.start_time is not None and clip.end_time is not None:
        duration = clip.end_time - clip.start_time
        cmd.extend(["-ss", str(clip.start_time), "-t", str(duration)])
    elif project.max_clip_duration:
        cmd.extend(["-t", str(project.max_clip_duration)])

    # Scaling and overlay
    # Tier-based resolution cap
    limits = _get_user_tier_limits(session, project.user_id)
    eff_label = _cap_resolution_label(
        project.output_resolution, limits.get("max_res_label")
    )
    target_res = parse_resolution(None, eff_label or project.output_resolution)
    scale_filter = (
        f"scale={target_res.split('x')[0]}:{target_res.split('x')[1]}:flags=lanczos"
    )
    # Compose overlay using creator_name and game_name if available
    font = resolve_fontfile()
    # Overlay chain handled via filter_complex above when available
    author = (clip.creator_name or "").strip() if clip.creator_name else ""
    game = (clip.game_name or "").strip() if clip.game_name else ""

    # Resolve optional global watermark (system setting) considering user tier
    def _watermark_cfg():
        try:
            u = session.get(User, project.user_id)
            # If tier or per-user override disables watermark, skip applying it
            if u and not should_apply_watermark(u, session=session):
                return None
        except Exception:
            # Fall back to system setting when user lookup fails
            pass
        wm_path = app.config.get("WATERMARK_PATH")
        if not wm_path or not os.path.exists(str(wm_path)):
            return None
        try:
            op = float(app.config.get("WATERMARK_OPACITY", 0.3) or 0.3)
        except Exception:
            op = 0.3
        op = max(0.0, min(1.0, op))
        pos = (app.config.get("WATERMARK_POSITION") or "bottom-right").strip().lower()
        # normalize synonyms
        if pos == "lower-right":
            pos = "bottom-right"
        if pos == "lower-left":
            pos = "bottom-left"
        # 20px margin
        x = {
            "top-left": "20",
            "bottom-left": "20",
            "top-right": "main_w-overlay_w-20",
            "bottom-right": "main_w-overlay_w-20",
            "center": "(main_w-overlay_w)/2",
        }.get(pos, "main_w-overlay_w-20")
        y = {
            "top-left": "20",
            "top-right": "20",
            "bottom-left": "main_h-overlay_h-20",
            "bottom-right": "main_h-overlay_h-20",
            "center": "(main_h-overlay_h)/2",
        }.get(pos, "main_h-overlay_h-20")
        return {"path": wm_path, "opacity": op, "x": x, "y": y}

    wm = _watermark_cfg()

    looped_avatar = False  # whether we used -loop 1 for avatar image input
    if font and (author or game) and overlay_enabled():
        # Build the overlay chain, with optional avatar as a second input.
        # Inputs must precede any filter definitions.
        cmd.extend(["-i", input_path])

        # Try to add an author avatar to the left area of the overlay
        def _resolve_avatar_path() -> str | None:
            try:
                app = _get_app()
                # First preference: a cached path stored on the clip
                try:
                    if getattr(clip, "creator_avatar_path", None):
                        orig = clip.creator_avatar_path
                        # Remap path if it was created on a different host/container
                        remapped = _resolve_media_input_path(orig)
                        if os.getenv("OVERLAY_DEBUG"):
                            try:
                                print(
                                    f"[overlay] avatar orig='{orig}' remapped='{remapped}' exists_orig={os.path.exists(orig)} exists_remap={os.path.exists(remapped) if remapped else False}"
                                )
                            except Exception:
                                pass
                        # Prefer remapped if it exists; else fall back to original if it exists
                        if remapped and os.path.exists(remapped):
                            return remapped
                        if os.path.exists(orig):
                            return orig
                except Exception:
                    pass
                # Allow env or app.config override for avatars base directory
                base_override = os.getenv("AVATARS_PATH") or app.config.get(
                    "AVATARS_PATH"
                )
                # If override is set and points to a different host path, try remapping it too
                if base_override:
                    try:
                        remapped_base = _resolve_media_input_path(base_override)
                        if remapped_base and remapped_base != base_override:
                            if os.getenv("OVERLAY_DEBUG"):
                                try:
                                    print(
                                        f"[overlay] AVATARS_PATH remap: '{base_override}' -> '{remapped_base}'"
                                    )
                                except Exception:
                                    pass
                            base_override = remapped_base
                    except Exception:
                        pass
                # Determine base roots. Support AVATARS_PATH pointing either to:
                #  - the avatars directory itself (…/assets/avatars)
                #  - the assets base directory that contains an 'avatars' subdir (…/assets)
                base_root = (
                    base_override
                    if base_override
                    else os.path.join(app.instance_path, "assets")
                )
                avatars_dir = base_root
                try:
                    tail = os.path.basename(str(avatars_dir).rstrip("/"))
                    if tail.lower() != "avatars":
                        avatars_dir = os.path.join(avatars_dir, "avatars")
                except Exception:
                    avatars_dir = os.path.join(base_root, "avatars")
                if os.getenv("OVERLAY_DEBUG"):
                    try:
                        print(
                            f"[overlay] avatar search roots: base_root='{base_root}' avatars_dir='{avatars_dir}' exists_base={os.path.isdir(base_root)} exists_avatars={os.path.isdir(avatars_dir)}"
                        )
                    except Exception:
                        pass
                # Specific per-author avatar: <base>/avatars/<sanitized>.png|jpg|jpeg|webp
                if author:
                    import glob as _glob
                    import re as _re

                    safe = _re.sub(r"[^a-z0-9_-]+", "_", author.strip().lower())
                    for ext in (".png", ".jpg", ".jpeg", ".webp"):
                        cand = os.path.join(avatars_dir, safe + ext)
                        if os.path.exists(cand):
                            if os.getenv("OVERLAY_DEBUG"):
                                try:
                                    print(f"[overlay] matched specific avatar: {cand}")
                                except Exception:
                                    pass
                            return cand
                        # Also support cached Twitch avatar pattern: <safe>_<rand><ext>
                        try:
                            pattern = os.path.join(avatars_dir, f"{safe}_*{ext}")
                            matches = _glob.glob(pattern)
                            if matches:
                                # Prefer the most recently modified match
                                matches.sort(
                                    key=lambda p: os.path.getmtime(p), reverse=True
                                )
                                if os.getenv("OVERLAY_DEBUG"):
                                    try:
                                        print(
                                            f"[overlay] matched cached avatar pattern '{pattern}': using {matches[0]}"
                                        )
                                    except Exception:
                                        pass
                                return matches[0]
                        except Exception:
                            pass
                # Default avatar placeholder in base directories (root and avatars subdir)
                for name in ("avatar.png", "avatar.jpg", "default_avatar.png"):
                    cand = os.path.join(base_root, name)
                    if os.path.exists(cand):
                        if os.getenv("OVERLAY_DEBUG"):
                            try:
                                print(f"[overlay] using default avatar at base: {cand}")
                            except Exception:
                                pass
                        return cand
                    cand2 = os.path.join(avatars_dir, name)
                    if os.path.exists(cand2):
                        if os.getenv("OVERLAY_DEBUG"):
                            try:
                                print(
                                    f"[overlay] using default avatar in avatars_dir: {cand2}"
                                )
                            except Exception:
                                pass
                        return cand2
                # Fallback to app static folder if present: app/static/avatars/
                static_base = os.path.join(app.root_path, "static")
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    if author:
                        import glob as _glob
                        import re as _re

                        safe = _re.sub(r"[^a-z0-9_-]+", "_", author.strip().lower())
                        cand = os.path.join(static_base, "avatars", safe + ext)
                        if os.path.exists(cand):
                            return cand
                        try:
                            pattern = os.path.join(
                                static_base, "avatars", f"{safe}_*{ext}"
                            )
                            matches = _glob.glob(pattern)
                            if matches:
                                matches.sort(
                                    key=lambda p: os.path.getmtime(p), reverse=True
                                )
                                return matches[0]
                        except Exception:
                            pass
                for name in ("avatar.png", "avatar.jpg", "default_avatar.png"):
                    cand = os.path.join(static_base, "avatars", name)
                    if os.path.exists(cand):
                        return cand
            except Exception:
                pass
            return None

        avatar_path = _resolve_avatar_path()

        ov = build_overlay_filter(author=author, game=game, fontfile=font)
        # Inject scale in front of overlay chain to normalize dimensions
        if ov.startswith("[0:v]"):
            ov = ov.replace("[0:v]", f"[0:v]{scale_filter},", 1)

        if avatar_path:
            # Include avatar as a second input before filter_complex
            # Loop the static image so it persists for the whole clip duration
            cmd.extend(["-loop", "1", "-i", avatar_path])
            looped_avatar = True
            if os.getenv("OVERLAY_DEBUG"):
                try:
                    print(f"[overlay] using avatar: {avatar_path}")
                except Exception:
                    pass
            # Append watermark as third input if configured
            wm_index = None
            if wm:
                cmd.extend(["-i", wm["path"]])
                wm_index = 2
            # Replace final [v] with [bg], then overlay avatar onto background
            text_chain = ov
            if text_chain.endswith("[v]"):
                text_chain = text_chain[:-3] + "[bg]"
            # Scale avatar to 128x128 and overlay near the left side of the box
            # Show avatar only during the same window as the text/box (t=3..10) and raise ~30px
            full_chain = (
                f"{text_chain};"
                f"[1:v]scale=128:128[ava];"
                f"[bg][ava]overlay=x=40:y=main_h-254:enable='between(t,3,10)'[v]"
            )
            if wm and wm_index is not None:
                wm_chain = (
                    f"{full_chain};"
                    f"[{wm_index}:v]format=rgba,colorchannelmixer=aa={wm['opacity']}[wm];"
                    f"[v][wm]overlay=x={wm['x']}:y={wm['y']}:format=auto[vw]"
                )
                cmd.extend(
                    ["-filter_complex", wm_chain, "-map", "[vw]", "-map", "0:a?"]
                )
            else:
                cmd.extend(
                    ["-filter_complex", full_chain, "-map", "[v]", "-map", "0:a?"]
                )
        else:
            # No avatar; use text-only overlay chain
            if os.getenv("OVERLAY_DEBUG"):
                try:
                    print("[overlay] no avatar resolved for author='" + author + "'")
                except Exception:
                    pass
            # Append watermark as second input if configured
            wm_index = None
            if wm:
                cmd.extend(["-i", wm["path"]])
                wm_index = 1
                wm_chain = (
                    f"{ov};"
                    f"[{wm_index}:v]format=rgba,colorchannelmixer=aa={wm['opacity']}[wm];"
                    f"[v][wm]overlay=x={wm['x']}:y={wm['y']}:format=auto[vw]"
                )
                cmd.extend(
                    ["-filter_complex", wm_chain, "-map", "[vw]", "-map", "0:a?"]
                )
            else:
                cmd.extend(["-filter_complex", ov, "-map", "[v]", "-map", "0:a?"])
    else:
        # No overlay; simple scale on video
        if wm:
            cmd.extend(["-i", input_path, "-i", wm["path"]])
            chain = (
                f"[0:v]{scale_filter}[base];"
                f"[1:v]format=rgba,colorchannelmixer=aa={wm['opacity']}[wm];"
                f"[base][wm]overlay=x={wm['x']}:y={wm['y']}:format=auto[v]"
            )
            cmd.extend(["-filter_complex", chain, "-map", "[v]", "-map", "0:a?"])
        else:
            cmd.extend(["-i", input_path, "-vf", scale_filter])

    # Encoder args (NVENC preferred), audio args
    # Optional audio normalization (volume in dB) if set on project
    try:
        if getattr(project, "audio_norm_db", None) is not None:
            try:
                db_gain = float(project.audio_norm_db)
            except Exception:
                db_gain = None
            if db_gain is not None and abs(db_gain) > 1e-6:
                cmd.extend(["-filter:a", f"volume={db_gain}dB"])
    except Exception:
        pass
    # Enforce max FPS if tier requires
    try:
        max_fps = limits.get("max_fps") if isinstance(limits, dict) else None
        if max_fps and int(max_fps) > 0:
            cmd.extend(["-r", str(int(max_fps))])
    except Exception:
        pass
    cmd.extend(encoder_args(ffmpeg_bin))
    cmd.extend(audio_args())
    # Faststart for mp4; use -shortest when looping a static image
    tail_args = ["-movflags", "+faststart"]
    if looped_avatar:
        tail_args.append("-shortest")
    tail_args += ["-y", output_path]
    cmd.extend(tail_args)

    # Execute ffmpeg command
    # Try processing; if NVENC path fails due to CUDA/driver issues, retry with CPU
    result = subprocess.run(cmd, capture_output=True, text=True)
    # Retry without audio filter if failure indicates no audio stream
    if (
        result.returncode != 0
        and "-filter:a" in cmd
        and (
            "matches no streams" in (result.stderr or "")
            or "Stream specifier 'a'" in (result.stderr or "")
        )
    ):
        try:

            def _drop_audio_filter(args: list[str]) -> list[str]:
                a = []
                i = 0
                while i < len(args):
                    if args[i] == "-filter:a" and i + 1 < len(args):
                        i += 2
                        continue
                    a.append(args[i])
                    i += 1
                return a

            cmd_no_af = _drop_audio_filter(cmd)
            result = subprocess.run(cmd_no_af, capture_output=True, text=True)
        except Exception:
            pass
    if result.returncode != 0 and "h264_nvenc" in " ".join(cmd):
        # Retry with CPU encoder
        try:
            if os.getenv("FFMPEG_DEBUG"):
                try:
                    print("[ffmpeg] NVENC encode failed; retrying with CPU libx264")
                except Exception:
                    pass

            # Replace video encoder args: find index of -c:v and swap through next value
            def _replace_encoder(args: list[str]) -> list[str]:
                a = []
                i = 0
                while i < len(args):
                    if args[i] == "-c:v" and i + 1 < len(args):
                        # drop -c:v <enc> and any known nvenc-specific flags following
                        i += 2
                        # also drop until next -c:a or -movflags or output marker as a heuristic
                        while i < len(args) and args[i] not in {
                            "-c:a",
                            "-movflags",
                            "-map",
                            "-vf",
                            "-filter_complex",
                            "-y",
                        }:
                            i += 1
                        # inject CPU encoder args before continuing
                        a.extend(cpu_encoder_args())
                        continue
                    a.append(args[i])
                    i += 1
                return a

            cmd_cpu = _replace_encoder(cmd)
            result = subprocess.run(cmd_cpu, capture_output=True, text=True)
            if (
                result.returncode != 0
                and "-filter:a" in cmd_cpu
                and (
                    "matches no streams" in (result.stderr or "")
                    or "Stream specifier 'a'" in (result.stderr or "")
                )
            ):
                try:

                    def _drop_audio_filter(args: list[str]) -> list[str]:
                        a = []
                        i = 0
                        while i < len(args):
                            if args[i] == "-filter:a" and i + 1 < len(args):
                                i += 2
                                continue
                            a.append(args[i])
                            i += 1
                        return a

                    cmd_cpu2 = _drop_audio_filter(cmd_cpu)
                    result = subprocess.run(cmd_cpu2, capture_output=True, text=True)
                except Exception:
                    pass
        except Exception:
            pass
    if result.returncode != 0:
        if os.getenv("FFMPEG_DEBUG"):
            try:
                print(
                    f"[ffmpeg] final failure processing clip {clip.id}: {result.stderr}"
                )
            except Exception:
                pass
        raise RuntimeError(f"FFmpeg error processing clip {clip.id}: {result.stderr}")

    return output_path


def build_timeline_with_transitions(
    session,
    project: Project,
    processed_clips: list[str],
    temp_dir: str,
    intro_id: int | None = None,
    outro_id: int | None = None,
    transition_ids: list[int] | None = None,
    randomize: bool = False,
) -> list[str]:
    """Build the full timeline: [Intro] -> Clip1 -> T -> Clip2 -> T -> ... -> [Outro].

    - Accept intros/outros from user library via IDs (ownership already validated).
    - Support multiple transitions selected by the user.
      - If randomize=True, choose randomly per gap.
      - Else, cycle through selected transitions in order.
    - Ensure transitions are inserted between every adjacent pair, including between
      intro->first clip and last clip->outro when those segments exist.
    """

    # Resolve intro
    intro_path: str | None = None
    if intro_id is not None:
        intro = (
            session.query(MediaFile)
            .filter_by(id=intro_id, user_id=project.user_id)
            .first()
        )
    else:
        intro = (
            session.query(MediaFile)
            .filter_by(project_id=project.id, media_type=MediaType.INTRO)
            .first()
        )
    if intro:
        intro_processed = os.path.join(temp_dir, "intro_processed.mp4")
        process_media_file(intro.file_path, intro_processed, project)
        intro_path = intro_processed

    # Resolve outro
    outro_path: str | None = None
    if outro_id is not None:
        outro = (
            session.query(MediaFile)
            .filter_by(id=outro_id, user_id=project.user_id)
            .first()
        )
    else:
        outro = (
            session.query(MediaFile)
            .filter_by(project_id=project.id, media_type=MediaType.OUTRO)
            .first()
        )
    if outro:
        outro_processed = os.path.join(temp_dir, "outro_processed.mp4")
        process_media_file(outro.file_path, outro_processed, project)
        outro_path = outro_processed

    # Resolve transitions (one or many)
    transition_paths: list[str] = []
    ids = list(dict.fromkeys(transition_ids or []))  # dedupe, keep order
    if ids:
        for tid in ids:
            mf = (
                session.query(MediaFile)
                .filter_by(
                    id=tid, user_id=project.user_id, media_type=MediaType.TRANSITION
                )
                .first()
            )
            if mf:
                outp = os.path.join(temp_dir, f"transition_{tid}_processed.mp4")
                process_media_file(mf.file_path, outp, project)
                transition_paths.append(outp)
    else:
        # Backward compatibility: single project-bound transition
        mf = (
            session.query(MediaFile)
            .filter_by(project_id=project.id, media_type=MediaType.TRANSITION)
            .first()
        )
        if mf:
            outp = os.path.join(temp_dir, "transition_processed.mp4")
            process_media_file(mf.file_path, outp, project)
            transition_paths.append(outp)

    # Build sequence with transitions between every adjacent pair
    import random as _random

    def _next_transition(idx: int) -> str | None:
        if not transition_paths:
            return None
        if randomize:
            return _random.choice(transition_paths)
        return transition_paths[idx % len(transition_paths)]

    segments: list[str] = []
    # Add intro as first segment if present
    if intro_path:
        segments.append(intro_path)
    # Add all processed clips
    segments.extend(processed_clips)
    # Append outro as last segment if present
    if outro_path:
        segments.append(outro_path)

    if not segments:
        return []

    # Interleave transitions between every adjacent pair
    result: list[str] = []
    labels: list[str] = []
    for i, seg in enumerate(segments):
        result.append(seg)
        # Label this segment
        base = os.path.basename(seg)
        label = base
        labels.append(label)
        if i < len(segments) - 1:
            tpath = _next_transition(i)
            if tpath:
                result.append(tpath)
                # Label transition
                tlabel = f"Transition: {os.path.basename(tpath)}"
                labels.append(tlabel)

    # Insert a static bumper between every video, including transitions
    static_processed: str | None = None
    try:
        app = _get_app()
        # Allow override via env STATIC_BUMPER_PATH
        static_src = os.getenv(
            "STATIC_BUMPER_PATH",
            os.path.join(app.instance_path, "assets", "static.mp4"),
        )
        if os.path.exists(static_src):
            static_out = os.path.join(temp_dir, "static_processed.mp4")
            # Process once to match project settings and codecs
            process_media_file(static_src, static_out, project)
            static_processed = static_out
    except Exception:
        static_processed = None

    if static_processed:
        interleaved: list[str] = []
        interleaved_labels: list[str] = []
        for i, seg in enumerate(result):
            interleaved.append(seg)
            interleaved_labels.append(
                labels[i] if i < len(labels) else os.path.basename(seg)
            )
            if i < len(result) - 1:
                interleaved.append(static_processed)
                interleaved_labels.append("Static")
        try:
            with open(os.path.join(temp_dir, "concat_labels.json"), "w") as fp:
                json.dump(interleaved_labels, fp)
        except Exception:
            pass
        return interleaved

    # Write labels sidecar for logging
    try:
        with open(os.path.join(temp_dir, "concat_labels.json"), "w") as fp:
            json.dump(labels, fp)
    except Exception:
        pass

    return result


def process_media_file(input_path: str, output_path: str, project: Project) -> None:
    """
    Process a media file to match project settings.

    Args:
        input_path: Input file path
        output_path: Output file path
        project: Project with settings
    """
    app = _get_app()
    # Normalize input path if coming from a different host
    input_path = _resolve_media_input_path(input_path)
    ffmpeg_bin = resolve_binary(app, "ffmpeg")
    from app.ffmpeg_config import config_args as _cfg_args

    cmd = [ffmpeg_bin, *_cfg_args(app, "ffmpeg", "encode"), "-i", input_path]

    # Set output resolution to match project capped by tier limits
    try:
        limits = _get_user_tier_limits(db.session, project.user_id)
    except Exception:
        limits = {"max_res_label": None, "max_fps": None}
    eff_label = _cap_resolution_label(
        project.output_resolution, limits.get("max_res_label")
    )
    target_res = parse_resolution(None, eff_label or project.output_resolution)
    scale_filter = (
        f"scale={target_res.split('x')[0]}:{target_res.split('x')[1]}:flags=lanczos"
    )

    # Optional global watermark overlay (system setting) considering user tier
    def _wm_cfg():
        try:
            u = db.session.get(User, project.user_id)
            if u and not should_apply_watermark(u, session=db.session):
                return None
        except Exception:
            pass
        wm_path = app.config.get("WATERMARK_PATH")
        if not wm_path or not os.path.exists(str(wm_path)):
            return None
        try:
            op = float(app.config.get("WATERMARK_OPACITY", 0.3) or 0.3)
        except Exception:
            op = 0.3
        op = max(0.0, min(1.0, op))
        pos = (app.config.get("WATERMARK_POSITION") or "bottom-right").strip().lower()
        if pos == "lower-right":
            pos = "bottom-right"
        if pos == "lower-left":
            pos = "bottom-left"
        x = {
            "top-left": "20",
            "bottom-left": "20",
            "top-right": "main_w-overlay_w-20",
            "bottom-right": "main_w-overlay_w-20",
            "center": "(main_w-overlay_w)/2",
        }.get(pos, "main_w-overlay_w-20")
        y = {
            "top-left": "20",
            "top-right": "20",
            "bottom-left": "main_h-overlay_h-20",
            "bottom-right": "main_h-overlay_h-20",
            "center": "(main_h-overlay_h)/2",
        }.get(pos, "main_h-overlay_h-20")
        return {"path": wm_path, "opacity": op, "x": x, "y": y}

    wm = _wm_cfg()

    if wm:
        # Use filter_complex: scale then overlay watermark
        cmd.extend(
            [
                "-i",
                wm["path"],
                "-filter_complex",
                (
                    f"[0:v]{scale_filter}[base];"
                    f"[1:v]format=rgba,colorchannelmixer=aa={wm['opacity']}[wm];"
                    f"[base][wm]overlay=x={wm['x']}:y={wm['y']}:format=auto[v]"
                ),
                "-map",
                "[v]",
                "-map",
                "0:a?",
            ]
        )
    else:
        cmd.extend(["-vf", scale_filter])

    # Apply audio normalization if configured on the project
    try:
        if getattr(project, "audio_norm_db", None) is not None:
            try:
                db_gain = float(project.audio_norm_db)
            except Exception:
                db_gain = None
            if db_gain is not None and abs(db_gain) > 1e-6:
                cmd.extend(["-filter:a", f"volume={db_gain}dB"])
    except Exception:
        pass

    # Enforce max FPS if tier requires
    try:
        max_fps = limits.get("max_fps") if isinstance(limits, dict) else None
        if max_fps and int(max_fps) > 0:
            cmd.extend(["-r", str(int(max_fps))])
    except Exception:
        pass
    cmd.extend(encoder_args(ffmpeg_bin))
    cmd.extend(audio_args())
    cmd.extend(["-movflags", "+faststart", "-y", output_path])

    result = subprocess.run(cmd, capture_output=True, text=True)
    # Retry without audio filter if failure indicates no audio stream
    if (
        result.returncode != 0
        and "-filter:a" in cmd
        and (
            "matches no streams" in (result.stderr or "")
            or "Stream specifier 'a'" in (result.stderr or "")
        )
    ):
        try:

            def _drop_audio_filter(args: list[str]) -> list[str]:
                a = []
                i = 0
                while i < len(args):
                    if args[i] == "-filter:a" and i + 1 < len(args):
                        i += 2
                        continue
                    a.append(args[i])
                    i += 1
                return a

            cmd_no_af = _drop_audio_filter(cmd)
            result = subprocess.run(cmd_no_af, capture_output=True, text=True)
        except Exception:
            pass
    if result.returncode != 0 and "h264_nvenc" in " ".join(cmd):
        # Retry with CPU encoder if GPU path fails
        if os.getenv("FFMPEG_DEBUG"):
            try:
                print(
                    "[ffmpeg] NVENC encode failed in process_media_file; retrying with CPU libx264"
                )
            except Exception:
                pass

        def _replace_encoder(args: list[str]) -> list[str]:
            a = []
            i = 0
            while i < len(args):
                if args[i] == "-c:v" and i + 1 < len(args):
                    i += 2
                    while i < len(args) and args[i] not in {
                        "-c:a",
                        "-movflags",
                        "-map",
                        "-vf",
                        "-filter_complex",
                        "-y",
                    }:
                        i += 1
                    a.extend(cpu_encoder_args())
                    continue
                a.append(args[i])
                i += 1
            return a

        cmd_cpu = _replace_encoder(cmd)
        result = subprocess.run(cmd_cpu, capture_output=True, text=True)
        if (
            result.returncode != 0
            and "-filter:a" in cmd_cpu
            and (
                "matches no streams" in (result.stderr or "")
                or "Stream specifier 'a'" in (result.stderr or "")
            )
        ):
            try:

                def _drop_audio_filter(args: list[str]) -> list[str]:
                    a = []
                    i = 0
                    while i < len(args):
                        if args[i] == "-filter:a" and i + 1 < len(args):
                            i += 2
                            continue
                        a.append(args[i])
                        i += 1
                    return a

                cmd_cpu2 = _drop_audio_filter(cmd_cpu)
                result = subprocess.run(cmd_cpu2, capture_output=True, text=True)
            except Exception:
                pass
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error processing media file: {result.stderr}")


def compile_final_video(clips: list[str], temp_dir: str, project: Project) -> str:
    """
    Compile final video from processed clips.

    Args:
        clips: List of processed clip paths
        temp_dir: Temporary directory
        project: Project object

    Returns:
        str: Path to final compiled video
    """
    # Create file list for ffmpeg concat
    filelist_path = os.path.join(temp_dir, "filelist.txt")
    with open(filelist_path, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")

    output_path = os.path.join(
        temp_dir, f"compilation_{project.id}.{project.output_format}"
    )

    # Build ffmpeg concat command
    app = _get_app()
    ffmpeg_bin = resolve_binary(app, "ffmpeg")
    from app.ffmpeg_config import config_args as _cfg_args

    cmd = [
        ffmpeg_bin,
        *_cfg_args(app, "ffmpeg", "concat"),
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        filelist_path,
        "-c",
        "copy",
        "-y",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error compiling final video: {result.stderr}")

    return output_path


def save_final_video(temp_path: str, project: Project) -> str:
    """
    Move final video to permanent location.

    Args:
        temp_path: Temporary file path
        project: Project object

    Returns:
        str: Final file path
    """
    app = _get_app()

    # Create output directory (project-based)
    with app.app_context():
        # Ensure we have a user object for storage helpers
        try:
            user_obj = db.session.query(User).get(project.user_id)
        except Exception:
            user_obj = None
        output_dir = storage_lib.compilations_dir(
            user_obj or project.owner, project.name
        )
        os.makedirs(output_dir, exist_ok=True)

    # Generate final filename
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{project.name}_{timestamp}.{project.output_format}"
    filename = "".join(
        c for c in filename if c.isalnum() or c in "._-"
    )  # Sanitize filename

    final_path = os.path.join(output_dir, filename)

    # Move file: prefer atomic replace; if cross-device (EXDEV), fall back to copy/move
    try:
        # os.replace is atomic on same filesystem and overwrites if target exists
        os.replace(temp_path, final_path)
    except OSError as e:
        # 18 is EXDEV on Linux; fallback to shutil.move which copies across devices
        if getattr(e, "errno", None) in (errno.EXDEV, 18):
            shutil.move(temp_path, final_path)
        else:
            raise

    # Also export a copy to an artifacts directory for rsync-based transfer if configured
    try:
        _export_artifact_if_configured(final_path, project)
    except Exception:
        # Never fail the compilation due to artifact export issues
        pass

    return final_path


def _export_artifact_if_configured(
    final_output_path: str, project: Project
) -> str | None:
    """DEPRECATED: Artifact export is no longer used.

    Workers now upload files directly via HTTP during task execution.
    This function is kept for backwards compatibility but does nothing.

    Returns None always.
    """
    return None


def download_with_yt_dlp(
    url: str,
    clip: Clip,
    max_bytes: int | None = None,
    download_dir: str | None = None,
) -> str:
    """
    Download video using yt-dlp directly into the project clips directory
    using a slug-based filename '<slug>.<ext>'.

    Returns:
        str: Path to downloaded file
    """
    app = _get_app()

    # Resolve target download directory (project-aware)
    if not download_dir:
        with app.app_context():
            try:
                user = db.session.query(User).get(clip.project.user_id)
            except Exception:
                user = None
            download_dir = storage_lib.clips_dir(
                user or clip.project.owner, clip.project.name
            )
    os.makedirs(download_dir, exist_ok=True)

    # Compute sanitized slug for output filename
    slug = (getattr(clip, "source_id", None) or "").strip()
    if not slug:
        raise RuntimeError("Missing clip slug (clip.source_id) for output filename")
    import re as _re

    safe_slug = _re.sub(r"[^A-Za-z0-9._-]+", "_", slug)
    safe_slug = _re.sub(r"_+", "_", safe_slug).strip("._-") or "clip"

    # Build yt-dlp command (ignore path-affecting config/options)
    yt_bin = resolve_binary(app, "yt-dlp")
    from app.ffmpeg_config import config_args as _cfg_args

    def _sanitize_ytdlp_args(args: list[str]) -> list[str]:
        cleaned: list[str] = []
        skip_next = False
        for tok in args:
            if skip_next:
                skip_next = False
                continue
            if tok in {
                "-r",
                "--limit-rate",
                "-o",
                "--output",
                "-P",
                "--paths",
                "--paths-home",
                "--paths-temp",
                "--paths-subdirs",
            }:
                skip_next = True
                continue
            if (
                tok.startswith("--output=")
                or tok.startswith("-P=")
                or tok.startswith("--paths=")
            ):
                continue
            cleaned.append(tok)
        return cleaned

    base_args = _sanitize_ytdlp_args(_cfg_args(app, "yt-dlp"))
    output_template = os.path.join(download_dir, f"{safe_slug}.%(ext)s")
    cmd = [
        yt_bin,
        *base_args,
        "--no-config",
        "--format",
        "best[ext=mp4]/best",
        "--output",
        output_template,
        "--no-playlist",
        url,
    ]
    if max_bytes is not None and max_bytes > 0:
        cmd.extend(["--max-filesize", str(int(max_bytes))])
    if os.getenv("YT_DLP_DEBUG"):
        try:
            print("[yt-dlp] cmd:", " ".join(cmd[:-1]), "<URL>")
        except Exception:
            pass

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp error downloading {url}: {result.stderr}")

    # Determine path of downloaded file (prefer .mp4)
    downloaded_path: str | None = None
    try:
        mp4 = os.path.join(download_dir, f"{safe_slug}.mp4")
        if os.path.exists(mp4):
            downloaded_path = mp4
        else:
            for f in os.listdir(download_dir):
                if f.startswith(f"{safe_slug}."):
                    downloaded_path = os.path.join(download_dir, f)
                    break
    except Exception:
        downloaded_path = None

    if not downloaded_path:
        raise RuntimeError("Downloaded file not found")

    # Cleanup: remove any legacy clip_<id>_* files from instance/downloads to keep it empty
    try:
        _app3 = _get_app()
        with _app3.app_context():
            legacy_dir2 = os.path.join(_app3.instance_path, "downloads")
        if os.path.isdir(legacy_dir2):
            prefix = f"clip_{clip.id}_"
            for fname in list(os.listdir(legacy_dir2)):
                if fname.startswith(prefix):
                    try:
                        os.remove(os.path.join(legacy_dir2, fname))
                    except Exception:
                        pass
            # Remove the directory if now empty
            try:
                if not os.listdir(legacy_dir2):
                    os.rmdir(legacy_dir2)
            except Exception:
                pass
    except Exception:
        pass

    return downloaded_path


def extract_video_metadata(file_path: str) -> dict[str, Any]:
    """
    Extract video metadata using ffprobe.

    Args:
        file_path: Path to video file

    Returns:
        Dict: Video metadata
    """
    app = _get_app()
    ffprobe_bin = resolve_binary(app, "ffprobe")
    from app.ffmpeg_config import config_args as _cfg_args

    cmd = [
        ffprobe_bin,
        *_cfg_args(app, "ffprobe"),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)

            # Find video stream
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if video_stream:
                # Parse framerate safely (e.g., "30000/1001")
                fr_raw = video_stream.get("r_frame_rate", "0/1")
                try:
                    num, den = fr_raw.split("/")
                    fr_val = float(num) / float(den) if float(den or 0) else 0.0
                except Exception:
                    try:
                        fr_val = float(fr_raw)
                    except Exception:
                        fr_val = 0.0

                return {
                    "duration": float(data.get("format", {}).get("duration", 0)),
                    "width": int(video_stream.get("width", 0)),
                    "height": int(video_stream.get("height", 0)),
                    "framerate": fr_val,
                }

    except Exception:
        pass

    return {}


def resolve_binary(app, name: str) -> str:
    """Resolve a binary path using app config or local ./bin vs system smart fallback.

    Order of precedence:
      1) Explicit app.config override (FFMPEG_BINARY, YT_DLP_BINARY, FFPROBE_BINARY)
      2) For ffmpeg only: if PREFER_SYSTEM_FFMPEG=1, prefer system 'ffmpeg'
      3) Project-local ./bin/<name> if present
         - For ffmpeg: if local ffmpeg lacks NVENC but system ffmpeg has NVENC, prefer system
      4) Fallback to executable name (resolved via PATH)
    """
    cfg_key = None
    lname = name.lower()
    if lname == "ffmpeg":
        cfg_key = "FFMPEG_BINARY"
    elif lname in ("yt-dlp", "ytdlp"):
        cfg_key = "YT_DLP_BINARY"
    elif lname == "ffprobe":
        cfg_key = "FFPROBE_BINARY"

    if cfg_key:
        path = app.config.get(cfg_key)
        if path:
            return path

    proj_root = os.path.dirname(app.root_path)
    local_bin = os.path.join(proj_root, "bin", name)

    # For ffmpeg specifically, allow preferring system binary (useful in GPU containers)
    if lname == "ffmpeg":
        prefer_system = str(
            os.getenv(
                "PREFER_SYSTEM_FFMPEG", app.config.get("PREFER_SYSTEM_FFMPEG", "")
            )
        ).lower() in {"1", "true", "yes", "on"}
        if prefer_system:
            if os.getenv("FFMPEG_DEBUG"):
                try:
                    print("[ffmpeg] prefer system ffmpeg via PREFER_SYSTEM_FFMPEG=1")
                except Exception:
                    pass
            return "ffmpeg"

        # If local exists, but we're in a GPU context, pick the one that supports NVENC
        def _has_nvenc(bin_path: str) -> bool:
            try:
                import subprocess

                res = subprocess.run(
                    [bin_path, "-hide_banner", "-encoders"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=5,
                )
                return "h264_nvenc" in (res.stdout or "")
            except Exception:
                return False

        gpu_context = (
            str(os.getenv("USE_GPU_QUEUE", app.config.get("USE_GPU_QUEUE", ""))).lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
            or os.getenv("NVIDIA_VISIBLE_DEVICES")
            or os.getenv("CUDA_VISIBLE_DEVICES")
        )

        if os.path.exists(local_bin):
            if gpu_context:
                # Prefer the binary that actually has NVENC
                local_has = _has_nvenc(local_bin)
                sys_has = _has_nvenc("ffmpeg")
                if os.getenv("FFMPEG_DEBUG"):
                    try:
                        print(
                            f"[ffmpeg] gpu_context=1 local_bin='{local_bin}' local_nvenc={local_has} system_nvenc={sys_has}"
                        )
                    except Exception:
                        pass
                if sys_has and not local_has:
                    if os.getenv("FFMPEG_DEBUG"):
                        try:
                            print("[ffmpeg] selecting system ffmpeg (has NVENC)")
                        except Exception:
                            pass
                    return "ffmpeg"
            if os.getenv("FFMPEG_DEBUG"):
                try:
                    print(f"[ffmpeg] selecting local ffmpeg: {local_bin}")
                except Exception:
                    pass
            return local_bin
        # No local bin; system
        if os.getenv("FFMPEG_DEBUG"):
            try:
                print("[ffmpeg] no local ffmpeg; using system 'ffmpeg'")
            except Exception:
                pass
        return "ffmpeg"

    # Non-ffmpeg tools: prefer project-local if present, else PATH
    if os.path.exists(local_bin):
        return local_bin
    return name
