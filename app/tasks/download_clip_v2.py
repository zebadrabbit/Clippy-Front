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


def _extract_slug_from_url(url: str) -> str:
    """
    Extract Twitch clip slug from URL.

    Examples:
        https://www.twitch.tv/user/clip/FastInexpensiveCurry-5_abc → fastinexpensivecurry-5_abc
        https://clips.twitch.tv/FastInexpensiveCurry-5_abc → fastinexpensivecurry-5_abc
    """
    import re

    # Match Twitch clip URLs
    match = re.search(r"(?:clips?\.twitch\.tv/|twitch\.tv/.+/clip/)([^/?&#]+)", url)
    if match:
        return match.group(1).lower()

    # Fallback: extract last path segment
    parts = url.rstrip("/").split("/")
    return parts[-1].lower() if parts else "unknown"


def _upload_clip_to_server(
    output_path: str,
    thumb_path: str | None,
    clip_id: int,
    project_id: int,
    clip_meta: dict[str, Any],
) -> dict[str, Any]:
    """
    Upload downloaded clip to server via HTTP API.

    Returns API response with media_id and paths.
    """
    import requests

    api_url = os.environ.get("SERVER_API_URL", "http://10.8.0.1:5000")
    api_key = os.environ.get("WORKER_API_KEY")

    if not api_key:
        raise ValueError("WORKER_API_KEY not configured")

    # Extract metadata
    metadata = {
        "source_id": clip_meta.get("source_id")
        or clip_meta.get("slug")
        or clip_meta.get("id"),
        "duration": clip_meta.get("duration"),
        "file_size": os.path.getsize(output_path),
    }

    # Get video dimensions if available
    try:
        import json

        probe_cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            output_path,
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(result.stdout)
        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == "video":
                metadata["width"] = stream.get("width")
                metadata["height"] = stream.get("height")
                if "r_frame_rate" in stream:
                    num, den = stream["r_frame_rate"].split("/")
                    metadata["framerate"] = (
                        float(num) / float(den) if float(den) > 0 else None
                    )
                break
    except Exception as e:
        print(f"Could not probe video metadata: {e}")

    # Prepare multipart upload
    files = {
        "video": (os.path.basename(output_path), open(output_path, "rb"), "video/mp4")
    }

    if thumb_path and os.path.isfile(thumb_path):
        files["thumbnail"] = (
            os.path.basename(thumb_path),
            open(thumb_path, "rb"),
            "image/jpeg",
        )

    import json as json_module

    form_data = {"metadata": json_module.dumps(metadata)}

    headers = {"Authorization": f"Bearer {api_key}"}

    upload_url = f"{api_url}/api/worker/projects/{project_id}/clips/{clip_id}/upload"

    print(f"Uploading clip {clip_id} to {upload_url}")
    response = requests.post(
        upload_url, files=files, data=form_data, headers=headers, timeout=300
    )

    # Close file handles
    for f in files.values():
        if hasattr(f[1], "close"):
            f[1].close()

    if response.status_code != 200:
        raise Exception(f"Upload failed: {response.status_code} - {response.text}")

    return response.json()


def _download_with_ytdlp_standalone(
    url: str,
    source_id: str,
    clip_title: str,
    max_bytes: int | None = None,
    download_dir: str | None = None,
) -> str:
    """
    Standalone yt-dlp download without Flask app dependency.

    Args:
        url: Source URL to download
        source_id: Source identifier (Twitch slug) for filename
        clip_title: Clip title for fallback slug
        max_bytes: Maximum file size in bytes
        download_dir: Target directory

    Returns:
        Path to downloaded file
    """
    os.makedirs(download_dir, exist_ok=True)

    # Use source_id (Twitch slug) for filename
    safe_slug = source_id if source_id else clip_title.replace(" ", "_")[:50]

    # Get yt-dlp binary path
    yt_bin = os.environ.get("YT_DLP_BINARY", "yt-dlp")

    # Build output template
    output_template = os.path.join(download_dir, f"{safe_slug}.%(ext)s")

    # Build command
    cmd = [
        yt_bin,
        "--no-config",
        "--format",
        "best[ext=mp4]/best",
        "--output",
        output_template,
        "--no-playlist",
        url,
    ]

    # Add filesize limit if specified
    if max_bytes:
        cmd.extend(["--max-filesize", str(max_bytes)])

    # Add cookies if available
    cookies_path = os.environ.get("YT_DLP_COOKIES")
    if cookies_path and os.path.exists(cookies_path):
        cmd.extend(["--cookies", cookies_path])

    # Execute download
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    # Find downloaded file
    pattern = os.path.join(download_dir, f"{safe_slug}.*")
    import glob

    matches = glob.glob(pattern)

    if not matches:
        raise RuntimeError(f"Download succeeded but file not found: {pattern}")

    # Return the first match (should be only one)
    return matches[0]


def _extract_video_metadata_standalone(video_path: str) -> dict[str, Any]:
    """
    Extract video metadata using ffprobe without Flask app dependency.

    Returns:
        Dict with duration, width, height, framerate
    """
    ffprobe_bin = os.environ.get("FFPROBE_BINARY", "ffprobe")

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=width,height,r_frame_rate,codec_name",
        "-of",
        "json",
        video_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        return {}

    import json

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    # Extract metadata
    metadata = {}

    # Duration from format
    fmt = data.get("format", {})
    if "duration" in fmt:
        try:
            metadata["duration"] = float(fmt["duration"])
        except (ValueError, TypeError):
            pass

    # Video stream info
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)

    if video_stream:
        metadata["width"] = video_stream.get("width")
        metadata["height"] = video_stream.get("height")

        # Parse framerate (e.g., "30/1" -> 30.0)
        r_frame_rate = video_stream.get("r_frame_rate", "")
        if "/" in r_frame_rate:
            try:
                num, den = r_frame_rate.split("/")
                metadata["framerate"] = float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                pass

    return metadata


@celery_app.task(bind=True)
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

        # Check local cache before downloading
        import hashlib
        import time

        cache_dir = "/tmp/clippy-worker-cache"
        os.makedirs(cache_dir, exist_ok=True)

        # Clean up old cache files (>2 hours)
        try:
            max_age = 2 * 3600  # 2 hours in seconds
            now = time.time()
            for cached_file in os.listdir(cache_dir):
                cached_path = os.path.join(cache_dir, cached_file)
                if os.path.isfile(cached_path):
                    age = now - os.stat(cached_path).st_atime
                    if age > max_age:
                        try:
                            os.remove(cached_path)
                        except Exception:
                            pass
        except Exception:
            pass

        # Generate cache key from source URL
        url_hash = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        cache_pattern = os.path.join(cache_dir, f"clip_{url_hash}.*")

        # Check if cached file exists
        import glob

        cached_files = glob.glob(cache_pattern)
        output_path = None

        if cached_files:
            # Use cached file
            cached_path = cached_files[0]
            print(
                f"[CACHE HIT] Using cached clip for URL {source_url[:50]}... -> {cached_path}"
            )
            log("info", f"Using cached clip: {cached_path}", status="cache_hit")
            # Touch file to refresh TTL
            os.utime(cached_path, None)
            output_path = cached_path
        else:
            # Download to cache directory
            print(
                f"[CACHE MISS] Downloading from Twitch: {source_url[:50]}... to {cache_dir}"
            )
            self.update_state(
                state="PROGRESS", meta={"progress": 30, "status": "Downloading video"}
            )
            worker_api.update_processing_job(job_id, progress=30)
            log("info", "Downloading video from Twitch", status="downloading")

            # Download to cache
            output_path = _download_with_ytdlp_standalone(
                source_url,
                f"clip_{url_hash}",  # Use hash-based filename for cache
                clip_meta.get("title", f"clip_{clip_id}"),
                max_bytes=int(rem_bytes) if rem_bytes is not None else None,
                download_dir=cache_dir,
            )
            print(f"[CACHE SAVE] Downloaded to cache: {output_path}")
            log("info", f"Downloaded to cache: {output_path}", status="cached")

        # Extract metadata
        self.update_state(
            state="PROGRESS", meta={"progress": 70, "status": "Extracting metadata"}
        )
        worker_api.update_processing_job(job_id, progress=70)

        metadata = _extract_video_metadata_standalone(output_path)
        duration = metadata.get("duration") if metadata else None

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
                ts = os.environ.get("THUMBNAIL_TIMESTAMP_SECONDS", "3")
                w = int(os.environ.get("THUMBNAIL_WIDTH", "480"))

                subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-ss",
                        str(ts),
                        "-i",
                        output_path,
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={w}:-1",
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

        # Create MediaFile record and upload to server
        self.update_state(
            state="PROGRESS", meta={"progress": 90, "status": "Uploading to server"}
        )
        worker_api.update_processing_job(job_id, progress=90)
        log("info", "Uploading clip to server via HTTP")

        # Upload via HTTP API (replaces rsync workflow)
        upload_response = _upload_clip_to_server(
            output_path=output_path,
            thumb_path=thumb_path,
            clip_id=clip_id,
            project_id=project_id,
            clip_meta=clip_meta,
        )

        media_id = upload_response.get("media_id")
        log("success", f"Upload completed, MediaFile ID: {media_id}")

        # Complete job
        result_data = {
            "downloaded_file": upload_response.get("file_path"),
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
            "downloaded_file": upload_response.get("file_path"),
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
