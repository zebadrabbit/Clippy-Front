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
    db,
)
from app.tasks.celery_app import celery_app


def get_db_session():
    """
    Get a new database session for use in Celery tasks.

    Returns:
        Session: Database session
    """
    from app import create_app

    app = create_app()

    with app.app_context():
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
        if orig_path and os.path.exists(orig_path):
            return orig_path
        ap = (orig_path or "").strip()
        if not ap:
            return orig_path
        # 1) Explicit alias
        alias_from = os.getenv("MEDIA_PATH_ALIAS_FROM")
        alias_to = os.getenv("MEDIA_PATH_ALIAS_TO")
        if alias_from and alias_to and ap.startswith(alias_from):
            cand = alias_to + ap[len(alias_from) :]
            if os.path.exists(cand):
                return cand
        # 2) Automatic '/instance/' remap
        marker = "/instance/"
        if marker in ap:
            try:
                from app import create_app

                app = create_app()
                suffix = ap.split(marker, 1)[1]
                cand = os.path.join(app.instance_path, suffix)
                if os.path.exists(cand):
                    return cand
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

        # Get clips in order
        clips = (
            session.query(Clip)
            .filter_by(project_id=project_id)
            .order_by(Clip.order_index.asc(), Clip.created_at.asc())
            .all()
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
                    file_path=final_output_path,
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
                    from app import create_app

                    app = create_app()
                    base_upload = os.path.join(
                        app.instance_path, app.config.get("UPLOAD_FOLDER", "uploads")
                    )
                    thumbs_dir = os.path.join(
                        base_upload, str(project.user_id), "thumbnails"
                    )
                    os.makedirs(thumbs_dir, exist_ok=True)
                    # Deterministic name based on final output filename
                    stem = os.path.splitext(os.path.basename(final_output_path))[0]
                    thumb_path = os.path.join(thumbs_dir, f"{stem}.jpg")
                    if not os.path.exists(thumb_path):
                        ffmpeg_bin = resolve_binary(app, "ffmpeg")
                        subprocess.run(
                            [
                                ffmpeg_bin,
                                "-y",
                                "-ss",
                                "1",
                                "-i",
                                final_output_path,
                                "-frames:v",
                                "1",
                                "-vf",
                                "scale=480:-1",
                                thumb_path,
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=True,
                        )
                    media.thumbnail_path = thumb_path
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

            # Update job status
            job.status = "success"
            job.completed_at = datetime.utcnow()
            job.progress = 100
            job.result_data = {
                "output_file": final_output_path,
                "clips_processed": len(processed_clips),
                "duration": (datetime.utcnow() - job.started_at).total_seconds(),
                **(job.result_data or {}),
            }
            log("success", "Compilation completed", status="completed")

            session.commit()

            return {
                "status": "completed",
                "output_file": final_output_path,
                "clips_processed": len(processed_clips),
                "project_id": project_id,
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

        # Download with yt-dlp
        output_path = download_with_yt_dlp(source_url, clip)

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
        media_file = MediaFile(
            filename=os.path.basename(output_path),
            original_filename=f"downloaded_{clip.title}",
            file_path=output_path,
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
            from app import create_app

            app = create_app()
            base_upload = os.path.join(
                app.instance_path, app.config.get("UPLOAD_FOLDER", "uploads")
            )
            thumbs_dir = os.path.join(
                base_upload, str(clip.project.user_id), "thumbnails"
            )
            os.makedirs(thumbs_dir, exist_ok=True)
            # Deterministic thumbnail name to avoid duplicates across restarts
            stem = os.path.splitext(os.path.basename(output_path))[0]
            thumb_path = os.path.join(thumbs_dir, f"{stem}.jpg")

            if not os.path.exists(thumb_path):
                ffmpeg_bin = resolve_binary(app, "ffmpeg")
                subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-ss",
                        "1",
                        "-i",
                        output_path,
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=480:-1",
                        thumb_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            media_file.thumbnail_path = thumb_path
        except Exception as thumb_err:
            # Do not fail the task if thumbnail creation fails
            print(f"Thumbnail generation failed for clip {clip.id}: {thumb_err}")

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
            "downloaded_file": output_path,
            "media_file_id": media_file.id,
            **(job.result_data or {}),
        }
        log("success", "Download completed", status="completed")

        session.commit()

        return {
            "status": "completed",
            "downloaded_file": output_path,
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

        session.close()
        raise


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

    input_path = _resolve_media_input_path(clip.media_file.file_path)
    output_path = os.path.join(temp_dir, f"clip_{clip.id}_processed.mp4")

    # Build ffmpeg command for clip processing with quality + overlay
    from app import create_app

    app = create_app()
    ffmpeg_bin = resolve_binary(app, "ffmpeg")
    cmd = [ffmpeg_bin]

    # Add clip trimming if specified
    if clip.start_time is not None and clip.end_time is not None:
        duration = clip.end_time - clip.start_time
        cmd.extend(["-ss", str(clip.start_time), "-t", str(duration)])
    elif project.max_clip_duration:
        cmd.extend(["-t", str(project.max_clip_duration)])

    # Scaling and overlay
    target_res = parse_resolution(None, project.output_resolution)
    scale_filter = (
        f"scale={target_res.split('x')[0]}:{target_res.split('x')[1]}:flags=lanczos"
    )
    # Compose overlay using creator_name and game_name if available
    font = resolve_fontfile()
    # Overlay chain handled via filter_complex above when available
    author = (clip.creator_name or "").strip() if clip.creator_name else ""
    game = (clip.game_name or "").strip() if clip.game_name else ""
    if font and (author or game) and overlay_enabled():
        # Build the overlay chain, with optional avatar as a second input.
        # Inputs must precede any filter definitions.
        cmd.extend(["-i", input_path])

        # Try to add an author avatar to the left area of the overlay
        def _resolve_avatar_path() -> str | None:
            try:
                from app import create_app  # local import to avoid top-level coupling

                app = create_app()
                # First preference: a cached path stored on the clip
                try:
                    if getattr(clip, "creator_avatar_path", None):
                        if os.path.exists(clip.creator_avatar_path):
                            return clip.creator_avatar_path
                except Exception:
                    pass
                # Allow env or app.config override for avatars base directory
                base_override = os.getenv("AVATARS_PATH") or app.config.get(
                    "AVATARS_PATH"
                )
                base = (
                    base_override
                    if base_override
                    else os.path.join(app.instance_path, "assets")
                )
                # Specific per-author avatar: <base>/avatars/<sanitized>.png|jpg|jpeg|webp
                if author:
                    import re as _re

                    safe = _re.sub(r"[^a-z0-9_-]+", "_", author.strip().lower())
                    for ext in (".png", ".jpg", ".jpeg", ".webp"):
                        cand = os.path.join(base, "avatars", safe + ext)
                        if os.path.exists(cand):
                            return cand
                # Default avatar placeholder in base directory
                for name in ("avatar.png", "avatar.jpg", "default_avatar.png"):
                    cand = os.path.join(base, name)
                    if os.path.exists(cand):
                        return cand
                # Fallback to app static folder if present: app/static/avatars/
                static_base = os.path.join(app.root_path, "static")
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    if author:
                        import re as _re

                        safe = _re.sub(r"[^a-z0-9_-]+", "_", author.strip().lower())
                        cand = os.path.join(static_base, "avatars", safe + ext)
                        if os.path.exists(cand):
                            return cand
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
            cmd.extend(["-i", avatar_path])
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
            cmd.extend(["-filter_complex", full_chain, "-map", "[v]", "-map", "0:a?"])
        else:
            # No avatar; use text-only overlay chain
            cmd.extend(["-filter_complex", ov, "-map", "[v]", "-map", "0:a?"])
    else:
        # No overlay; simple scale on video
        cmd.extend(["-i", input_path, "-vf", scale_filter])

    # Encoder args (NVENC preferred), audio args
    cmd.extend(encoder_args(ffmpeg_bin))
    cmd.extend(audio_args())
    # Faststart for mp4
    cmd.extend(["-movflags", "+faststart", "-y", output_path])  # Overwrite output

    # Execute ffmpeg command
    # Try processing; if NVENC path fails due to CUDA/driver issues, retry with CPU
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and "h264_nvenc" in " ".join(cmd):
        # Retry with CPU encoder
        try:
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
        except Exception:
            pass
    if result.returncode != 0:
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
        # Try to map processed clip paths to titles via id
        try:
            import re as _re

            m = _re.match(r"clip_(\\d+)_processed\\.mp4$", base)
            if m:
                cid = int(m.group(1))
                cobj = session.query(Clip).get(cid)
                if cobj and cobj.title:
                    label = cobj.title
        except Exception:
            pass
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
        from app import create_app

        app = create_app()
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
    from app import create_app

    app = create_app()
    # Normalize input path if coming from a different host
    input_path = _resolve_media_input_path(input_path)
    ffmpeg_bin = resolve_binary(app, "ffmpeg")
    cmd = [ffmpeg_bin, "-i", input_path]

    # Set output resolution to match project
    target_res = parse_resolution(None, project.output_resolution)
    scale_filter = (
        f"scale={target_res.split('x')[0]}:{target_res.split('x')[1]}:flags=lanczos"
    )
    cmd.extend(["-vf", scale_filter])

    cmd.extend(encoder_args(ffmpeg_bin))
    cmd.extend(audio_args())
    cmd.extend(["-movflags", "+faststart", "-y", output_path])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and "h264_nvenc" in " ".join(cmd):
        # Retry with CPU encoder if GPU path fails
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
    from app import create_app

    app = create_app()
    ffmpeg_bin = resolve_binary(app, "ffmpeg")
    cmd = [
        ffmpeg_bin,
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
    from app import create_app

    app = create_app()

    # Create output directory
    output_dir = os.path.join(app.instance_path, "compilations")
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

    return final_path


def download_with_yt_dlp(url: str, clip: Clip) -> str:
    """
    Download video using yt-dlp.

    Args:
        url: Video URL to download
        clip: Clip object

    Returns:
        str: Path to downloaded file
    """
    from app import create_app

    app = create_app()

    # Create download directory
    download_dir = os.path.join(app.instance_path, "downloads")
    os.makedirs(download_dir, exist_ok=True)

    # Generate output filename
    output_template = os.path.join(download_dir, f"clip_{clip.id}_%(title)s.%(ext)s")

    # yt-dlp command
    yt_bin = resolve_binary(app, "yt-dlp")
    cmd = [
        yt_bin,
        "--format",
        "best[ext=mp4]/best",
        "--output",
        output_template,
        "--no-playlist",
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp error downloading {url}: {result.stderr}")

    # Find the downloaded file
    for file in os.listdir(download_dir):
        if file.startswith(f"clip_{clip.id}_"):
            return os.path.join(download_dir, file)

    raise RuntimeError("Downloaded file not found")


def extract_video_metadata(file_path: str) -> dict[str, Any]:
    """
    Extract video metadata using ffprobe.

    Args:
        file_path: Path to video file

    Returns:
        Dict: Video metadata
    """
    from app import create_app

    app = create_app()
    ffprobe_bin = resolve_binary(app, "ffprobe")
    cmd = [
        ffprobe_bin,
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
    """Resolve a binary path using app config or local ./bin fallback.

    Looks for config keys FFMPEG_BINARY, YT_DLP_BINARY, FFPROBE_BINARY based on name.
    If not configured, prefers project-local bin/<name> if present, else returns name.
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
    candidate = os.path.join(proj_root, "bin", name)
    if os.path.exists(candidate):
        return candidate
    return name
