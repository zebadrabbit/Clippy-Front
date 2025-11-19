"""
API-based download_clip_task - replacement for the DB-dependent version.

This version uses worker API endpoints instead of direct database access,
allowing workers to run outside the DMZ.

USAGE: Replace the existing download_clip_task function in
app/tasks/video_processing.py (lines 866-1195) with this implementation.
"""

import os
from datetime import datetime
from typing import Any

from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, queue="celery")
def download_clip_task(self, clip_id: int, source_url: str) -> dict[str, Any]:
    """
    Download a clip from external source using yt-dlp (API-based, no DB access).

    This task is designed to run on workers outside the DMZ. It communicates
    with the Flask app via API endpoints instead of accessing the database directly.

    Args:
        clip_id: ID of the clip to download
        source_url: URL to download from

    Returns:
        Dict: Task result with downloaded file information
    """
    from app.tasks import worker_api
    from app.tasks.video_processing import (
        download_with_yt_dlp,
        extract_video_metadata,
    )

    # Safety: ensure downloads only run on GPU/CPU workers
    try:
        dinfo = getattr(self.request, "delivery_info", {}) or {}
        qname = (
            (dinfo.get("routing_key") or dinfo.get("exchange") or "")
            if isinstance(dinfo, dict)
            else ""
        ).strip()
        if qname and qname not in {"gpu", "cpu"}:
            raise RuntimeError(f"Downloads not permitted on queue '{qname}'")
    except Exception as _queue_guard_err:
        raise

    job_id = None

    try:
        # Fetch clip metadata from API
        self.update_state(
            state="PROGRESS", meta={"progress": 5, "status": "Fetching clip metadata"}
        )
        clip_meta = worker_api.get_clip_metadata(clip_id)

        # Create processing job via API
        self.update_state(
            state="PROGRESS", meta={"progress": 10, "status": "Creating processing job"}
        )
        job_response = worker_api.create_processing_job(
            celery_task_id=self.request.id,
            job_type="download_clip",
            project_id=clip_meta["project_id"],
            user_id=clip_meta["user_id"],
        )
        job_id = job_response["job_id"]

        # Update progress
        worker_api.update_processing_job(
            job_id,
            status="downloading",
            progress=20,
            result_data={
                "logs": [
                    {
                        "ts": datetime.utcnow().isoformat(),
                        "level": "info",
                        "message": f"Starting download: clip {clip_id}",
                        "status": "downloading",
                    }
                ]
            },
        )

        # Prepare download directory (use instance path from environment)
        instance_path = os.environ.get("CLIPPY_INSTANCE_PATH", "/app/instance")
        username = clip_meta["username"]
        project_name = clip_meta["project_name"]
        dl_dir = os.path.join(instance_path, "data", username, project_name, "clips")
        os.makedirs(dl_dir, exist_ok=True)

        # Download with yt-dlp
        self.update_state(
            state="PROGRESS", meta={"progress": 30, "status": "Downloading video"}
        )
        worker_api.update_processing_job(job_id, progress=30)

        # Create a minimal clip-like object for download_with_yt_dlp
        class ClipStub:
            def __init__(self, clip_id, title):
                self.id = clip_id
                self.title = title

        clip_stub = ClipStub(clip_id, clip_meta["title"])
        output_path = download_with_yt_dlp(
            source_url, clip_stub, max_bytes=None, download_dir=dl_dir
        )

        # Extract metadata
        self.update_state(
            state="PROGRESS", meta={"progress": 70, "status": "Extracting metadata"}
        )
        worker_api.update_processing_job(job_id, progress=70)

        metadata = extract_video_metadata(output_path)
        duration = metadata.get("duration") if metadata else None

        # Generate thumbnail
        self.update_state(
            state="PROGRESS", meta={"progress": 80, "status": "Generating thumbnail"}
        )
        worker_api.update_processing_job(job_id, progress=80)

        thumb_path = None
        try:
            output_dir = os.path.dirname(output_path)
            stem = os.path.splitext(os.path.basename(output_path))[0]
            thumb_path = os.path.join(output_dir, f"{stem}_thumb.jpg")

            if not os.path.exists(thumb_path):
                from app.ffmpeg_config import config_args as _cfg_args

                ffmpeg_bin = os.environ.get("FFMPEG_BINARY", "ffmpeg")
                ts = os.environ.get("THUMBNAIL_TIMESTAMP_SECONDS", "3")
                w = int(os.environ.get("THUMBNAIL_WIDTH", "480"))

                cmd = [
                    ffmpeg_bin,
                    *_cfg_args(ffmpeg_bin),
                    "-ss",
                    ts,
                    "-i",
                    output_path,
                    "-vf",
                    f"scale={w}:-1",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "5",
                    thumb_path,
                ]
                import subprocess

                subprocess.run(cmd, check=True, capture_output=True)
        except Exception:
            thumb_path = None

        # Create MediaFile record via API (need to add this endpoint)
        # For now, we'll return the file path and let the server create the record
        self.update_state(
            state="PROGRESS", meta={"progress": 90, "status": "Finalizing"}
        )

        # Normalize path for database storage (relative to instance)
        db_file_path = output_path.replace(f"{instance_path}/", "")

        result = {
            "status": "completed",
            "downloaded_file": db_file_path,
            "absolute_path": output_path,
            "clip_id": clip_id,
            "duration": duration,
            "thumbnail_path": thumb_path.replace(f"{instance_path}/", "")
            if thumb_path
            else None,
            "filesize": os.path.getsize(output_path),
        }

        # Update job as completed
        worker_api.update_processing_job(
            job_id,
            status="success",
            progress=100,
            result_data={"downloaded_file": db_file_path, **result},
        )

        # Update clip status (mark as downloaded)
        # Note: We can't set media_file_id yet since we don't have it
        # The server will need to create the MediaFile record and link it
        worker_api.update_clip_status(clip_id, is_downloaded=True, duration=duration)

        return result

    except Exception as e:
        # Update job as failed
        if job_id:
            try:
                worker_api.update_processing_job(
                    job_id,
                    status="failure",
                    result_data={
                        "logs": [
                            {
                                "ts": datetime.utcnow().isoformat(),
                                "level": "error",
                                "message": str(e),
                                "status": "failed",
                            }
                        ]
                    },
                    error_message=str(e),
                )
            except Exception:
                pass

        raise
