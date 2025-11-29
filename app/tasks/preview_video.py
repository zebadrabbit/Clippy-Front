"""
Celery task for generating preview videos (low-res, 480p 10fps) for compilations.
Uses the actual compilation logic with preview-optimized settings to ensure accuracy.
"""
import os
import shutil
from datetime import datetime

import structlog
from celery import shared_task

from app import create_app
from app.models import Clip, Project

logger = structlog.get_logger(__name__)


@shared_task(bind=True)
def generate_preview_video_task(self, project_id, clip_ids=None):
    """Generate low-resolution preview by calling actual compilation with preview settings.

    Instead of reimplementing filter logic, this uses the real compilation pipeline
    with preview-optimized settings (480p, 10fps, limited clips).

    Args:
        project_id: ID of the project to generate preview for
        clip_ids: Optional list of clip IDs from timeline. If None, uses first 3 downloaded clips.

    Returns:
        dict: Preview result with path, file_size, cached status
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

            # Cache check: use existing preview if fresh
            if project.preview_filename:
                try:
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
                            return {
                                "preview": preview_path,
                                "cached": True,
                                "file_size": os.path.getsize(preview_path),
                            }
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

            # Get clips for preview (limit to 3 for speed)
            if clip_ids:
                clips = []
                for clip_id in clip_ids[:3]:
                    clip = (
                        Clip.query.filter_by(id=clip_id, project_id=project.id)
                        .filter(Clip.is_downloaded.is_(True))
                        .filter(Clip.media_file_id.isnot(None))
                        .first()
                    )
                    if clip:
                        clips.append(clip)
            else:
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
                return {"error": "No clips available for preview"}

            logger.info(
                "preview_clips_loaded",
                project_id=project_id,
                clip_count=len(clips),
                clip_ids=[c.id for c in clips],
            )

            self.update_state(
                state="PROGRESS",
                meta={
                    "progress": 20,
                    "status": f"Compiling preview with {len(clips)} clips",
                },
            )

            # Call the real compilation task with preview overrides
            # This ensures all filters/zoom/alignment work identically to final output
            from app.tasks.compile_video_v2 import compile_video_task_v2

            # We'll inject preview mode via a context variable that compile_video_v2 can check
            # For now, just call with limited clips and no intro/outro for speed
            result = compile_video_task_v2.apply(
                args=(project_id,),
                kwargs={
                    "intro_id": None,  # Skip intro/outro for preview speed
                    "outro_id": None,
                    "transition_ids": None,
                    "randomize_transitions": False,
                    "clip_ids": [c.id for c in clips],
                    "background_music_id": None,  # Skip music for preview
                    "music_volume": 0.2,
                    "music_start_mode": "fade_in",
                    "music_end_mode": "fade_out",
                    "preview_mode": True,  # Enable 480p 10fps preview rendering
                },
            )

            if result.failed():
                error = (
                    str(result.info)
                    if hasattr(result, "info")
                    else "Unknown compilation error"
                )
                logger.error(
                    "preview_compilation_failed", project_id=project_id, error=error
                )
                return {"error": f"Preview compilation failed: {error}"}

            compilation_result = result.result

            if "error" in compilation_result:
                logger.error(
                    "preview_compilation_error",
                    project_id=project_id,
                    error=compilation_result["error"],
                )
                return {"error": compilation_result["error"]}

            # The compilation created output_file - move it to preview directory
            output_file = compilation_result.get("output_file")

            logger.info(
                "preview_compilation_result",
                project_id=project_id,
                output_file=output_file,
                result_keys=list(compilation_result.keys()),
            )

            # Resolve the output file path (may be relative like /instance/...)
            if output_file and output_file.startswith("/instance/"):
                output_file = os.path.join(
                    app.instance_path, output_file[10:]
                )  # Strip "/instance/" prefix

            logger.info(
                "preview_resolved_path",
                project_id=project_id,
                output_file=output_file,
                exists=os.path.exists(output_file) if output_file else False,
            )

            if not output_file or not os.path.exists(output_file):
                logger.error(
                    "preview_output_missing",
                    project_id=project_id,
                    output_file=output_file,
                )
                return {"error": "Compilation output file not found"}

            preview_dir = os.path.join(
                app.instance_path, "previews", str(project.user_id)
            )
            os.makedirs(preview_dir, exist_ok=True)

            preview_filename = f"preview_{project_id}.mp4"
            preview_path = os.path.join(preview_dir, preview_filename)

            # Move compilation output to preview location
            shutil.move(output_file, preview_path)

            file_size = os.path.getsize(preview_path)

            self.update_state(
                state="PROGRESS", meta={"progress": 90, "status": "Uploading preview"}
            )

            # Upload to main server
            from app.tasks import worker_api

            upload_result = worker_api.upload_preview(
                project_id=project_id,
                video_path=preview_path,
                metadata={"file_size": file_size, "clips_used": len(clips)},
            )

            logger.info(
                "preview_uploaded",
                project_id=project_id,
                filename=upload_result.get("preview_filename"),
                size=file_size,
                clips=len(clips),
            )

            self.update_state(
                state="PROGRESS", meta={"progress": 100, "status": "Preview ready"}
            )

            return {
                "preview": upload_result.get("preview_path"),
                "cached": False,
                "file_size": file_size,
                "clips_used": len(clips),
            }

        except Exception as e:
            logger.error(
                "preview_generation_failed",
                project_id=project_id,
                error=str(e),
                exc_info=True,
            )
            return {"error": str(e)}
