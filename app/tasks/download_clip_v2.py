"""
Phase 3: API-based download_clip_task implementation.

This is a complete rewrite of download_clip_task that operates entirely via
the worker API, with no direct database access. Demonstrates that workers can
run outside the DMZ without DATABASE_URL.

Features:
- Pre-download media reuse check (URL/Twitch key matching)
- Quota enforcement via API
- yt-dlp download with filesize limits
- Video metadata extraction
- Thumbnail generation
- ProcessingJob logging
"""

import os
import subprocess
from datetime import datetime
from typing import Any

from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, queue="celery")
def download_clip_task_v2(self, clip_id: int, source_url: str) -> dict[str, Any]:
    """
    Download a clip from external source using yt-dlp (API-based, no DB access).

    This is the Phase 3 implementation that demonstrates full worker API usage
    without any direct database dependencies.

    Args:
        clip_id: ID of the clip to download
        source_url: URL to download from

    Returns:
        Dict: Task result with downloaded file information
    """
    from app.tasks import worker_api
    from app.tasks.video_processing import download_with_yt_dlp, extract_video_metadata

    job_id = None

    def log(level: str, message: str, status: str | None = None):
        """Helper to add log entries to job result_data."""
        if not job_id:
            return
        try:
            worker_api.update_processing_job(
                job_id,
                result_data={
                    "logs": [
                        {
                            "ts": datetime.utcnow().isoformat(),
                            "level": level,
                            "message": message,
                            "status": status,
                        }
                    ]
                },
            )
        except Exception:
            pass

    try:
        # Fetch clip metadata
        self.update_state(
            state="PROGRESS", meta={"progress": 5, "status": "Fetching metadata"}
        )
        clip_meta = worker_api.get_clip_metadata(clip_id)
        user_id = clip_meta["user_id"]
        project_id = clip_meta["project_id"]
        username = clip_meta["username"]
        project_name = clip_meta["project_name"]

        # Create processing job
        self.update_state(
            state="PROGRESS", meta={"progress": 10, "status": "Creating job"}
        )
        job_response = worker_api.create_processing_job(
            celery_task_id=self.request.id,
            job_type="download_clip",
            project_id=project_id,
            user_id=user_id,
        )
        job_id = job_response["job_id"]
        log("info", f"Starting download: clip {clip_id}", status="downloading")

        # Check for reusable media BEFORE downloading
        self.update_state(
            state="PROGRESS", meta={"progress": 15, "status": "Checking for reuse"}
        )
        worker_api.update_processing_job(job_id, progress=15)

        reuse_check = worker_api.find_reusable_media(
            user_id=user_id,
            source_url=source_url,
        )

        if reuse_check.get("found"):
            # Reuse existing media
            media_id = reuse_check["media_file_id"]
            duration = reuse_check.get("duration")

            # Update clip status
            worker_api.update_clip_status(
                clip_id,
                is_downloaded=True,
                media_file_id=media_id,
                duration=duration,
            )

            # Complete job
            worker_api.update_processing_job(
                job_id,
                status="success",
                progress=100,
                result_data={
                    "reused_media_file_id": media_id,
                    "reused_from_clip_id": reuse_check.get("reused_from_clip_id"),
                },
            )
            log("success", "Reused existing media (no download)", status="reused")

            return {
                "status": "reused",
                "media_file_id": media_id,
                "clip_id": clip_id,
            }

        # No reusable media found - proceed with download

        # Get quota for max filesize
        self.update_state(
            state="PROGRESS", meta={"progress": 20, "status": "Checking quota"}
        )
        worker_api.update_processing_job(job_id, progress=20)

        quota = worker_api.get_user_quota(user_id)
        rem_bytes = quota.get("remaining_bytes")

        if rem_bytes is not None and int(rem_bytes) <= 0:
            raise RuntimeError(
                "Storage quota exceeded: no remaining bytes for download"
            )

        # Prepare download directory
        instance_path = os.environ.get("CLIPPY_INSTANCE_PATH", "/app/instance")
        dl_dir = os.path.join(instance_path, "data", username, project_name, "clips")
        os.makedirs(dl_dir, exist_ok=True)

        # Download with yt-dlp
        self.update_state(
            state="PROGRESS", meta={"progress": 30, "status": "Downloading video"}
        )
        worker_api.update_processing_job(job_id, progress=30)
        log("info", "Downloading video", status="downloading")

        # Create minimal clip stub for download_with_yt_dlp
        class ClipStub:
            def __init__(self, clip_id, title):
                self.id = clip_id
                self.title = title

        clip_stub = ClipStub(clip_id, clip_meta.get("title", f"clip_{clip_id}"))

        output_path = download_with_yt_dlp(
            source_url,
            clip_stub,
            max_bytes=int(rem_bytes) if rem_bytes is not None else None,
            download_dir=dl_dir,
        )

        # Extract metadata
        self.update_state(
            state="PROGRESS", meta={"progress": 70, "status": "Extracting metadata"}
        )
        worker_api.update_processing_job(job_id, progress=70)

        metadata = extract_video_metadata(output_path)
        duration = metadata.get("duration") if metadata else None
        width = metadata.get("width") if metadata else None
        height = metadata.get("height") if metadata else None
        framerate = metadata.get("framerate") if metadata else None

        # Generate thumbnail
        self.update_state(
            state="PROGRESS", meta={"progress": 80, "status": "Generating thumbnail"}
        )
        worker_api.update_processing_job(job_id, progress=80)
        log("info", "Generating thumbnail")

        thumb_path = None
        try:
            output_dir = os.path.dirname(output_path)
            stem = os.path.splitext(os.path.basename(output_path))[0]
            thumb_path = os.path.join(output_dir, f"{stem}_thumb.jpg")

            if not os.path.exists(thumb_path):
                ffmpeg_bin = os.environ.get("FFMPEG_BINARY", "ffmpeg")

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
                        "-q:v",
                        "5",
                        thumb_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
        except Exception as thumb_err:
            print(f"Thumbnail generation failed: {thumb_err}")
            thumb_path = None

        # Create MediaFile record
        self.update_state(
            state="PROGRESS", meta={"progress": 90, "status": "Creating media record"}
        )
        worker_api.update_processing_job(job_id, progress=90)
        log("info", "Creating media file record")

        # Normalize path for database (relative to instance)
        db_file_path = output_path.replace(f"{instance_path}/", "")
        db_thumb_path = (
            thumb_path.replace(f"{instance_path}/", "") if thumb_path else None
        )

        media_response = worker_api.create_media_file(
            filename=os.path.basename(output_path),
            original_filename=f"downloaded_{clip_meta.get('title', 'clip')}",
            file_path=db_file_path,
            file_size=os.path.getsize(output_path),
            mime_type="video/mp4",
            media_type="CLIP",
            user_id=user_id,
            project_id=project_id,
            duration=duration,
            width=width,
            height=height,
            framerate=framerate,
            thumbnail_path=db_thumb_path,
        )

        media_id = media_response["media_id"]

        # Update clip status
        worker_api.update_clip_status(
            clip_id,
            is_downloaded=True,
            media_file_id=media_id,
            duration=duration,
        )

        # Complete job
        result_data = {
            "downloaded_file": db_file_path,
            "media_file_id": media_id,
        }

        worker_api.update_processing_job(
            job_id,
            status="success",
            progress=100,
            result_data=result_data,
        )

        log("success", "Download completed", status="completed")

        return {
            "status": "completed",
            "downloaded_file": db_file_path,
            "media_file_id": media_id,
            "clip_id": clip_id,
        }

    except Exception as e:
        # Update job as failed
        if job_id:
            try:
                worker_api.update_processing_job(
                    job_id,
                    status="failure",
                    error_message=str(e),
                )
                log("error", str(e), status="failed")
            except Exception:
                pass

        raise
