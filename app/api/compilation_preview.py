"""
Compilation preview thumbnail generation.
"""

import os
import subprocess
import tempfile

import structlog
from flask import jsonify, send_file
from flask_login import current_user, login_required

from app.api import api_bp
from app.models import Clip, MediaFile, Project

logger = structlog.get_logger(__name__)


@api_bp.route("/projects/<int:project_id>/compilation-preview-thumb", methods=["GET"])
@login_required
def get_compilation_preview_thumb(project_id):
    """
    Generate a preview thumbnail from the compilation timeline at the 5-second mark.
    This extracts a frame from the first clip (or intro if present) at 5 seconds in.
    """
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Get timeline order: intro, clips, outro
    clips = (
        Clip.query.filter_by(project_id=project.id)
        .filter(Clip.is_downloaded == True)  # noqa: E712
        .order_by(Clip.order_index)
        .all()
    )

    # Determine which media file to extract frame from
    target_media = None
    seek_time = 5.0  # Default: seek 5 seconds from start

    # Check if there's an intro
    if project.intro_media_id:
        intro = MediaFile.query.get(project.intro_media_id)
        if intro and intro.duration:
            if intro.duration >= 5.0:
                # Intro is long enough, use it
                target_media = intro
                seek_time = 5.0
            else:
                # Intro is too short, skip to first clip
                if clips and clips[0].media_file:
                    target_media = clips[0].media_file
                    # Seek into the clip by (5 - intro_duration)
                    seek_time = 5.0 - intro.duration
        else:
            # No intro or no duration, use first clip
            if clips and clips[0].media_file:
                target_media = clips[0].media_file
                seek_time = 5.0
    else:
        # No intro, use first clip
        if clips and clips[0].media_file:
            target_media = clips[0].media_file
            seek_time = 5.0

    if not target_media:
        # No media available, return error
        return jsonify({"error": "No media available for preview"}), 404

    # Ensure seek time doesn't exceed media duration
    if target_media.duration and seek_time > target_media.duration:
        seek_time = max(0, target_media.duration - 1)

    # Generate thumbnail using ffmpeg
    try:
        # Get ffmpeg binary path
        from app.ffmpeg_config import _resolve_binary

        ffmpeg_bin = _resolve_binary("FFMPEG_BINARY", "ffmpeg")

        # Create temporary file for thumbnail
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_thumb:
            thumb_path = tmp_thumb.name

        # Extract frame at seek_time
        # Use -ss before -i for fast seeking
        cmd = [
            ffmpeg_bin,
            "-ss",
            str(seek_time),
            "-i",
            target_media.file_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",  # High quality JPEG
            "-y",
            thumb_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(
                "preview_thumb_failed",
                project_id=project_id,
                stderr=result.stderr,
            )
            # Clean up temp file
            try:
                os.unlink(thumb_path)
            except Exception:
                pass
            return jsonify({"error": "Failed to generate preview thumbnail"}), 500

        # Return the thumbnail file
        return send_file(
            thumb_path,
            mimetype="image/jpeg",
            as_attachment=False,
            download_name=f"preview_{project_id}.jpg",
        )

    except subprocess.TimeoutExpired:
        logger.error("preview_thumb_timeout", project_id=project_id)
        try:
            os.unlink(thumb_path)
        except Exception:
            pass
        return jsonify({"error": "Thumbnail generation timed out"}), 500
    except Exception as e:
        logger.error(
            "preview_thumb_exception",
            project_id=project_id,
            error=str(e),
        )
        return jsonify({"error": "Failed to generate preview thumbnail"}), 500
