"""
Worker API client - helpers for workers to communicate with Flask app via API.

Workers use these functions instead of direct database access to maintain
the DMZ boundary. All functions require WORKER_API_KEY and FLASK_APP_URL
to be set in the environment.
"""

import os
from typing import Any

import requests


def _get_api_config() -> tuple[str, str]:
    """Get API configuration from environment.

    Returns:
        Tuple of (base_url, api_key)

    Raises:
        RuntimeError: If required config is missing
    """
    base_url = os.environ.get("FLASK_APP_URL", "").strip()
    api_key = os.environ.get("WORKER_API_KEY", "").strip()

    if not base_url:
        raise RuntimeError(
            "FLASK_APP_URL not configured - workers cannot communicate with Flask app"
        )

    if not api_key:
        raise RuntimeError(
            "WORKER_API_KEY not configured - workers cannot authenticate with Flask app"
        )

    return base_url, api_key


def _make_request(
    method: str, endpoint: str, json_data: dict | None = None
) -> dict[str, Any]:
    """Make authenticated API request.

    Args:
        method: HTTP method (GET, POST, PUT, etc.)
        endpoint: API endpoint path (e.g., "/worker/clips/123")
        json_data: Optional JSON request body

    Returns:
        JSON response as dict

    Raises:
        requests.HTTPError: If request fails
        RuntimeError: If configuration is missing
    """
    base_url, api_key = _get_api_config()

    url = f"{base_url}/api{endpoint}"
    headers = {"Authorization": f"Bearer {api_key}"}

    response = requests.request(
        method, url, headers=headers, json=json_data, timeout=30
    )
    response.raise_for_status()
    return response.json()


def get_clip_metadata(clip_id: int) -> dict[str, Any]:
    """Fetch clip metadata from Flask app.

    Args:
        clip_id: Clip ID

    Returns:
        {
            "id": int,
            "title": str,
            "source_url": str,
            "source_platform": str,
            "project_id": int,
            "user_id": int,
            "username": str,
            "project_name": str
        }
    """
    return _make_request("GET", f"/worker/clips/{clip_id}")


def update_clip_status(
    clip_id: int,
    is_downloaded: bool | None = None,
    media_file_id: int | None = None,
    duration: float | None = None,
) -> dict[str, Any]:
    """Update clip download status.

    Args:
        clip_id: Clip ID
        is_downloaded: Whether clip is downloaded
        media_file_id: Associated media file ID
        duration: Clip duration in seconds

    Returns:
        {"status": "updated", "clip_id": int}
    """
    data = {}
    if is_downloaded is not None:
        data["is_downloaded"] = is_downloaded
    if media_file_id is not None:
        data["media_file_id"] = media_file_id
    if duration is not None:
        data["duration"] = duration

    return _make_request("POST", f"/worker/clips/{clip_id}/status", data)


def get_media_metadata(media_id: int) -> dict[str, Any]:
    """Fetch media file metadata.

    Args:
        media_id: Media file ID

    Returns:
        {
            "id": int,
            "filename": str,
            "file_path": str,
            "media_type": str,
            "duration": float,
            "user_id": int,
            "username": str
        }
    """
    return _make_request("GET", f"/worker/media/{media_id}")


def create_processing_job(
    celery_task_id: str, job_type: str, project_id: int, user_id: int
) -> dict[str, Any]:
    """Create a processing job record.

    Args:
        celery_task_id: Celery task ID
        job_type: Job type (e.g., "download_clip", "compile_video")
        project_id: Project ID
        user_id: User ID

    Returns:
        {"status": "created", "job_id": int}
    """
    data = {
        "celery_task_id": celery_task_id,
        "job_type": job_type,
        "project_id": project_id,
        "user_id": user_id,
        "status": "started",
    }
    return _make_request("POST", "/worker/jobs", data)


def update_processing_job(
    job_id: int,
    status: str | None = None,
    progress: int | None = None,
    result_data: dict | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Update processing job status.

    Args:
        job_id: Job ID
        status: Job status
        progress: Progress percentage (0-100)
        result_data: Additional result data (will be merged with existing)
        error_message: Error message if failed

    Returns:
        {"status": "updated", "job_id": int}
    """
    data = {}
    if status is not None:
        data["status"] = status
    if progress is not None:
        data["progress"] = progress
    if result_data is not None:
        data["result_data"] = result_data
    if error_message is not None:
        data["error_message"] = error_message

    return _make_request("PUT", f"/worker/jobs/{job_id}", data)


def get_project_metadata(project_id: int) -> dict[str, Any]:
    """Fetch project metadata for compilation.

    Args:
        project_id: Project ID

    Returns:
        {
            "id": int,
            "name": str,
            "user_id": int,
            "username": str,
            "max_clip_duration": int,
            "output_resolution": str,
            "output_format": str,
            "audio_norm_db": float,
            "clips": [...]
        }
    """
    return _make_request("GET", f"/worker/projects/{project_id}")


def update_project_status(
    project_id: int,
    status: str | None = None,
    output_filename: str | None = None,
    output_file_size: int | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """Update project status and output information.

    Args:
        project_id: Project ID
        status: Project status
        output_filename: Output filename
        output_file_size: Output file size in bytes
        completed_at: Completion timestamp (ISO format)

    Returns:
        {"status": "updated", "project_id": int}
    """
    data = {}
    if status is not None:
        data["status"] = status
    if output_filename is not None:
        data["output_filename"] = output_filename
    if output_file_size is not None:
        data["output_file_size"] = output_file_size
    if completed_at is not None:
        data["completed_at"] = completed_at

    return _make_request("PUT", f"/worker/projects/{project_id}/status", data)


def create_media_file(
    filename: str,
    original_filename: str,
    file_path: str,
    file_size: int,
    mime_type: str,
    media_type: str,
    user_id: int,
    project_id: int | None = None,
    duration: float | None = None,
    width: int | None = None,
    height: int | None = None,
    framerate: float | None = None,
    thumbnail_path: str | None = None,
    is_processed: bool = True,
) -> dict[str, Any]:
    """Create a media file record.

    Args:
        filename: Filename
        original_filename: Original filename
        file_path: File path (relative to instance)
        file_size: File size in bytes
        mime_type: MIME type
        media_type: Media type (video, intro, outro, etc.)
        user_id: User ID
        project_id: Project ID (optional)
        duration: Duration in seconds
        width: Video width
        height: Video height
        framerate: Framerate
        thumbnail_path: Thumbnail path
        is_processed: Whether file is processed

    Returns:
        {"status": "created", "media_id": int}
    """
    data = {
        "filename": filename,
        "original_filename": original_filename,
        "file_path": file_path,
        "file_size": file_size,
        "mime_type": mime_type,
        "media_type": media_type,
        "user_id": user_id,
        "is_processed": is_processed,
    }

    if project_id is not None:
        data["project_id"] = project_id
    if duration is not None:
        data["duration"] = duration
    if width is not None:
        data["width"] = width
    if height is not None:
        data["height"] = height
    if framerate is not None:
        data["framerate"] = framerate
    if thumbnail_path is not None:
        data["thumbnail_path"] = thumbnail_path

    return _make_request("POST", "/worker/media", data)


def get_user_quota(user_id: int) -> dict[str, Any]:
    """Get user storage quota information.

    Args:
        user_id: User ID

    Returns:
        {
            "remaining_bytes": int,
            "total_bytes": int,
            "used_bytes": int
        }
    """
    return _make_request("GET", f"/worker/users/{user_id}/quota")


def get_user_tier_limits(user_id: int) -> dict[str, Any]:
    """Get user tier limits.

    Args:
        user_id: User ID

    Returns:
        {
            "max_clips": int,
            "max_resolution": str,
            "max_compilation_minutes": int,
            "watermark": bool
        }
    """
    return _make_request("GET", f"/worker/users/{user_id}/tier-limits")


def record_render_usage(
    user_id: int, project_id: int, seconds: float
) -> dict[str, Any]:
    """Record render usage for a user.

    Args:
        user_id: User ID
        project_id: Project ID
        seconds: Render duration in seconds

    Returns:
        {"status": "recorded"}
    """
    data = {"project_id": project_id, "seconds": seconds}
    return _make_request("POST", f"/worker/users/{user_id}/record-render", data)
