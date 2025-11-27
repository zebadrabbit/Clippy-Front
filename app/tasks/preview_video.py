"""
Celery task for generating preview videos (low-res, 480p 10fps) for compilations.
Applies same filters/transformations as final output.
Caches preview for fast subsequent loads.
"""
import os
import subprocess
import tempfile
from datetime import datetime

import structlog
from celery import shared_task

from app import create_app
from app.ffmpeg_config import parse_resolution
from app.models import Clip, Project

logger = structlog.get_logger(__name__)


def _build_preview_filter(project, target_width, target_height):
    """Build ffmpeg filter matching compilation output but optimized for preview.

    Applies same vertical zoom/align transformations as full compilation.
    """
    is_portrait_output = target_height > target_width
    vertical_zoom = getattr(project, "vertical_zoom", 100) or 100
    vertical_align = getattr(project, "vertical_align", "center") or "center"

    if is_portrait_output:
        # Portrait: apply zoom and crop
        zoom_factor = vertical_zoom / 100.0
        if vertical_align == "left":
            crop_x = "0"
        elif vertical_align == "right":
            crop_x = "iw-ow"
        else:  # center
            crop_x = "(iw-ow)/2"

        scale_filter = f"scale=iw*{zoom_factor}:ih*{zoom_factor},crop={target_width}:ih:{crop_x}:0,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black"
    else:
        # Landscape: simple scale
        scale_filter = f"scale={target_width}:{target_height}:flags=lanczos"

    # For preview, apply fps reduction and simplify quality
    return f"{scale_filter},fps=10"


@shared_task(bind=True)
def generate_preview_video_task(self, project_id, clip_ids=None):
    """Generate low-resolution preview for compilation.

    Renders first 3 clips (or all if fewer) with actual project transformations.
    Updates progress for UI feedback.

    Args:
        project_id: ID of the project to generate preview for
        clip_ids: Optional list of clip IDs to use (from timeline). If None, uses first 3 downloaded clips.
    """
    app = create_app()
    with app.app_context():
        try:
            self.update_state(
                state="PROGRESS", meta={"progress": 5, "status": "Initializing preview"}
            )

            project = Project.query.get(project_id)
            if not project:
                logger.error("preview_project_not_found", project_id=project_id)
                return {"error": "Project not found"}

            # Cache invalidation: check if preview already exists and is fresh
            if project.preview_filename:
                try:
                    # For local workers, check file mtime
                    preview_dir = os.path.join(
                        app.instance_path, "previews", str(project.user_id)
                    )
                    preview_path = os.path.join(preview_dir, project.preview_filename)
                    if os.path.exists(preview_path):
                        preview_mtime = datetime.fromtimestamp(
                            os.path.getmtime(preview_path)
                        )
                        project_mtime = project.updated_at or project.created_at
                        if preview_mtime > project_mtime:
                            logger.info(
                                "preview_cache_hit",
                                project_id=project_id,
                                preview_mtime=preview_mtime.isoformat(),
                                project_mtime=project_mtime.isoformat(),
                            )
                            return {"preview": preview_path, "cached": True}
                        logger.info(
                            "preview_cache_stale",
                            project_id=project_id,
                            preview_mtime=preview_mtime.isoformat(),
                            project_mtime=project_mtime.isoformat(),
                        )
                except Exception as cache_err:
                    logger.warning("preview_cache_check_failed", error=str(cache_err))

            self.update_state(
                state="PROGRESS", meta={"progress": 10, "status": "Loading clips"}
            )

            # Get clips for preview
            if clip_ids:
                # Use specified clip IDs from timeline (in order)
                clips = []
                for clip_id in clip_ids[:3]:  # Limit to first 3 for preview
                    clip = (
                        Clip.query.filter_by(id=clip_id, project_id=project.id)
                        .filter(Clip.is_downloaded.is_(True))
                        .filter(Clip.media_file_id.isnot(None))
                        .first()
                    )
                    if clip:
                        clips.append(clip)
            else:
                # Fallback to first 3 clips in order
                clips = (
                    Clip.query.filter_by(project_id=project.id)
                    .filter(Clip.is_downloaded.is_(True))
                    .filter(Clip.media_file_id.isnot(None))
                    .order_by(Clip.order_index.asc(), Clip.created_at.asc())
                    .limit(3)
                    .all()
                )

            if not clips:
                logger.error("preview_no_clips", project_id=project_id)
                return {"error": "No clips available"}

            logger.info(
                "preview_clips_loaded",
                project_id=project_id,
                clip_count=len(clips),
                clip_ids=[c.id for c in clips],
            )

            # Determine target resolution (use 480p for preview)
            output_res = getattr(project, "output_resolution", "1080p") or "1080p"
            target_res = parse_resolution(None, output_res)
            target_width, target_height = map(int, target_res.split("x"))

            # Scale down to 480p while maintaining aspect ratio
            if target_height > target_width:
                # Portrait
                preview_width = int(480 * target_width / target_height)
                preview_height = 480
            else:
                # Landscape
                preview_width = 480
                preview_height = int(480 * target_height / target_width)

            # Build filter with project transformations
            scale_filter = _build_preview_filter(project, preview_width, preview_height)

            self.update_state(
                state="PROGRESS",
                meta={"progress": 20, "status": f"Processing {len(clips)} clip(s)"},
            )

            # Get ffmpeg binary
            from app.tasks.compile_video_v2 import _download_media_file
            from app.tasks.video_processing import (
                _resolve_media_input_path,
                resolve_binary,
            )

            ffmpeg_bin = resolve_binary(app, "ffmpeg")

            # Process clips to temp files with transformations
            temp_files = []
            temp_dir = tempfile.mkdtemp(prefix="preview_")

            try:
                for i, clip in enumerate(clips):
                    if not clip.media_file or not clip.media_file.file_path:
                        logger.warning("preview_clip_no_media", clip_id=clip.id)
                        continue

                    # Resolve canonical path to actual filesystem path
                    input_path = _resolve_media_input_path(clip.media_file.file_path)

                    # If file doesn't exist locally, download it from main server
                    if not os.path.exists(input_path):
                        logger.warning(
                            "preview_clip_missing_downloading",
                            clip_id=clip.id,
                            canonical_path=clip.media_file.file_path,
                            resolved_path=input_path,
                        )
                        try:
                            # Create cache directory
                            cache_dir = os.path.join(
                                tempfile.gettempdir(), "clippy-worker-cache"
                            )
                            input_path = _download_media_file(
                                clip.media_file.id, project.user_id, cache_dir
                            )
                            logger.info(
                                "preview_clip_downloaded",
                                clip_id=clip.id,
                                media_id=clip.media_file.id,
                                path=input_path,
                            )
                        except Exception as e:
                            logger.error(
                                "preview_clip_download_failed",
                                clip_id=clip.id,
                                media_id=clip.media_file.id,
                                error=str(e),
                            )
                            continue

                    temp_output = os.path.join(temp_dir, f"clip_{i}.mp4")

                    # Limit each clip to 10 seconds for preview
                    max_duration = min(float(clip.media_file.duration or 10), 10.0)

                    cmd = [
                        ffmpeg_bin,
                        "-y",
                        "-i",
                        input_path,
                        "-t",
                        str(max_duration),
                        "-vf",
                        scale_filter,
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "28",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "96k",
                        "-ar",
                        "44100",
                        temp_output,
                    ]

                    logger.info("preview_processing_clip", clip_id=clip.id, index=i)
                    try:
                        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
                    except subprocess.CalledProcessError as e:
                        stderr = (
                            e.stderr.decode("utf-8", errors="replace")
                            if e.stderr
                            else ""
                        )
                        logger.error(
                            "preview_clip_ffmpeg_failed",
                            clip_id=clip.id,
                            index=i,
                            returncode=e.returncode,
                            command=" ".join(cmd),
                            stderr_full=stderr,
                        )
                        raise

                    if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
                        temp_files.append(temp_output)

                    progress = 20 + int((i + 1) / len(clips) * 50)
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "progress": progress,
                            "status": f"Processed clip {i+1}/{len(clips)}",
                        },
                    )

                if not temp_files:
                    logger.error("preview_no_valid_clips", project_id=project_id)
                    return {"error": "No valid clips could be processed"}

                self.update_state(
                    state="PROGRESS",
                    meta={"progress": 75, "status": "Concatenating clips"},
                )

                # Concatenate clips to temp output
                preview_output = os.path.join(temp_dir, "preview_final.mp4")

                if len(temp_files) == 1:
                    # Single clip, just copy
                    import shutil

                    shutil.move(temp_files[0], preview_output)
                else:
                    # Multiple clips, concat
                    concat_file = os.path.join(temp_dir, "concat.txt")
                    with open(concat_file, "w") as f:
                        for tf in temp_files:
                            f.write(f"file '{tf}'\\n")

                    concat_cmd = [
                        ffmpeg_bin,
                        "-y",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        concat_file,
                        "-c",
                        "copy",
                        preview_output,
                    ]

                    try:
                        subprocess.run(
                            concat_cmd, check=True, capture_output=True, timeout=60
                        )
                    except subprocess.CalledProcessError as e:
                        stderr = (
                            e.stderr.decode("utf-8", errors="replace")
                            if e.stderr
                            else ""
                        )
                        logger.error(
                            "preview_concat_ffmpeg_failed",
                            returncode=e.returncode,
                            command=" ".join(concat_cmd),
                            stderr_full=stderr,
                        )
                        raise

                self.update_state(
                    state="PROGRESS",
                    meta={"progress": 85, "status": "Uploading preview"},
                )

                # Validate output
                if not os.path.exists(preview_output):
                    raise RuntimeError("Preview file was not created")

                file_size = os.path.getsize(preview_output)
                if file_size < 1024:
                    raise RuntimeError(f"Preview file too small: {file_size} bytes")

                # Upload to main server (works for both local and remote workers)
                from app.tasks import worker_api

                upload_result = worker_api.upload_preview(
                    project_id=project_id,
                    video_path=preview_output,
                    metadata={"file_size": file_size, "clips_used": len(temp_files)},
                )

                logger.info(
                    "preview_uploaded",
                    project_id=project_id,
                    filename=upload_result.get("preview_filename"),
                    size=file_size,
                    clips=len(temp_files),
                )

                self.update_state(
                    state="PROGRESS", meta={"progress": 100, "status": "Preview ready"}
                )

                return {
                    "preview": upload_result.get("preview_path"),
                    "cached": False,
                    "file_size": file_size,
                    "clips_used": len(temp_files),
                }

            finally:
                # Cleanup temp files
                try:
                    import shutil

                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

        except subprocess.TimeoutExpired as e:
            logger.error("preview_timeout", project_id=project_id, error=str(e))
            return {"error": "Preview generation timed out"}
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            logger.error(
                "preview_ffmpeg_failed",
                project_id=project_id,
                returncode=e.returncode,
                stderr_full=stderr,
            )
            return {
                "error": f"Video processing failed: {stderr[-500:] if len(stderr) > 500 else stderr}"
            }
        except Exception as e:
            logger.error(
                "preview_failed",
                project_id=project_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return {"error": str(e)}
