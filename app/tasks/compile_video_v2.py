"""
Video compilation task (v2) - Worker API based implementation.

This is the Phase 4 migration of compile_video_task to use worker API instead
of direct database access. Workers can run without DATABASE_URL configured.

Key differences from original:
- Uses worker_api.get_compilation_context() instead of session queries
- Uses worker_api.get_media_batch() for intro/outro/transitions
- Uses worker_api for all job/project updates
- Helper functions no longer take session parameter
- All tier limits come from API response
"""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Any

import structlog

from app import storage as storage_lib
from app.ffmpeg_config import (
    audio_args,
    build_overlay_filter,
    encoder_args,
    overlay_enabled,
    parse_resolution,
    resolve_fontfile,
)
from app.tasks import worker_api
from app.tasks.celery_app import celery_app
from app.tasks.video_processing import (
    _cap_resolution_label,
    _get_app,
    _resolve_media_input_path,
    extract_video_metadata,
    resolve_binary,
)

logger = structlog.get_logger(__name__)


def _resolve_avatar_path(
    app, clip_id: int | None, creator_name: str | None
) -> str | None:
    """Resolve the avatar file path for a clip's creator.

    Checks multiple locations in this order:
    1. AVATARS_PATH directory for <sanitized_creator_name>.*
    2. instance/assets/avatars directory for <sanitized_creator_name>.*
    3. Download from main server via worker API (if configured)

    Args:
        app: Flask app instance
        clip_id: Optional clip ID to lookup in database
        creator_name: Creator name to search for avatar files

    Returns:
        str: Path to avatar file, or None if not found
    """
    if not creator_name:
        return None

    # Sanitize creator name for filesystem
    import re

    safe_name = re.sub(r"[^\w\-_]", "_", creator_name.lower())

    # Check environment variable location first
    avatars_path = os.environ.get("AVATARS_PATH", "")
    if avatars_path:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            avatar_file = os.path.join(avatars_path, f"{safe_name}{ext}")
            if os.path.isfile(avatar_file):
                app.logger.info(f"Found avatar in AVATARS_PATH: {avatar_file}")
                return avatar_file

    # Check instance/assets/avatars (standard location)
    instance_path = app.config.get("INSTANCE_PATH") or app.instance_path
    default_avatars = os.path.join(instance_path, "assets", "avatars")
    if os.path.isdir(default_avatars):
        import glob

        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            # Try exact match first
            exact_match = os.path.join(default_avatars, f"{safe_name}{ext}")
            if os.path.isfile(exact_match):
                app.logger.info(f"Found avatar (exact): {exact_match}")
                return exact_match
            # Try wildcard pattern (handles old random suffix format)
            matches = glob.glob(os.path.join(default_avatars, f"{safe_name}_*{ext}"))
            if matches:
                app.logger.info(f"Found avatar (pattern): {matches[0]}")
                return matches[0]

    # Try downloading from main server if API is configured
    api_base = app.config.get("MEDIA_BASE_URL", "").rstrip("/")
    api_key = app.config.get("WORKER_API_KEY", "")

    if api_base and api_key:
        try:
            import requests

            # Ensure avatars directory exists
            os.makedirs(default_avatars, exist_ok=True)

            url = f"{api_base}/api/worker/avatar/{creator_name}"
            headers = {"Authorization": f"Bearer {api_key}"}

            app.logger.info(f"Downloading avatar for '{creator_name}' from {url}")
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                # Determine file extension from Content-Type or filename
                content_type = response.headers.get("Content-Type", "")
                ext = ".png"  # default
                if "jpeg" in content_type or "jpg" in content_type:
                    ext = ".jpg"
                elif "webp" in content_type:
                    ext = ".webp"

                # Save to local cache
                avatar_file = os.path.join(default_avatars, f"{safe_name}{ext}")
                with open(avatar_file, "wb") as f:
                    f.write(response.content)

                app.logger.info(
                    f"Downloaded avatar for '{creator_name}' to {avatar_file}"
                )
                return avatar_file
            else:
                app.logger.warning(
                    f"Avatar download failed for '{creator_name}': HTTP {response.status_code}"
                )
        except Exception as e:
            app.logger.error(f"Failed to download avatar for '{creator_name}': {e}")

    app.logger.warning(f"Avatar not found for creator '{creator_name}'")
    return None


def _download_media_file(media_id: int, user_id: int, cache_dir: str) -> str:
    """Download a media file from the main server via worker API.

    Remote workers use this to fetch clips, intros, outros, and transitions
    when they don't have shared filesystem access.

    Args:
        media_id: MediaFile ID to download
        user_id: User ID for ownership validation
        cache_dir: Directory to save downloaded file

    Returns:
        str: Path to downloaded file

    Raises:
        RuntimeError: If download fails
    """
    import requests

    app = _get_app()
    api_base = app.config.get("MEDIA_BASE_URL", "").rstrip("/")
    api_key = app.config.get("WORKER_API_KEY", "")

    if not api_base or not api_key:
        raise RuntimeError("MEDIA_BASE_URL or WORKER_API_KEY not configured")

    # Check if already cached
    cached_path = os.path.join(cache_dir, f"media_{media_id}.mp4")
    if os.path.exists(cached_path):
        app.logger.info(f"Using cached media file {media_id}: {cached_path}")
        return cached_path

    # Download from API
    url = f"{api_base}/api/worker/media/{media_id}/download?user_id={user_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        app.logger.info(f"Downloading media {media_id} from {url}")
        response = requests.get(url, headers=headers, stream=True, timeout=300)
        response.raise_for_status()

        # Save to cache
        os.makedirs(cache_dir, exist_ok=True)
        with open(cached_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        app.logger.info(f"Downloaded media {media_id} to {cached_path}")
        return cached_path

    except Exception as e:
        raise RuntimeError(f"Failed to download media {media_id}: {e}") from e


def _apply_tier_limits_to_clips(
    clips: list[dict], tier_limits: dict[str, Any]
) -> list[dict]:
    """Apply tier-based clip count limits.

    Args:
        clips: List of clip dicts from API
        tier_limits: Tier limits dict with max_clips

    Returns:
        Clipped list if tier enforces max_clips
    """
    max_clips = tier_limits.get("max_clips")
    if max_clips and isinstance(max_clips, int) and max_clips > 0:
        if len(clips) > max_clips:
            return clips[:max_clips]
    return clips


def _process_clip_v2(
    clip_data: dict, temp_dir: str, project_data: dict, tier_limits: dict
) -> str:
    """Process a single clip for compilation (API-based).

    Args:
        clip_data: Clip dict from API (includes media_file nested dict)
        temp_dir: Temporary directory for processing
        project_data: Project dict from API
        tier_limits: Tier limits dict

    Returns:
        str: Path to processed clip file

    Raises:
        ValueError: If clip has no media file or file doesn't exist
    """
    media_file = clip_data.get("media_file")
    if not media_file:
        raise ValueError(f"Clip {clip_data['id']} has no associated media file")

    # Resolve and repair input path if needed
    original_path = media_file.get("file_path", "")
    input_path = _resolve_media_input_path(original_path)

    # If file doesn't exist locally, download it from main server
    if not os.path.exists(input_path):
        app = _get_app()
        app.logger.warning(
            f"Media file not found locally: {input_path}. Attempting download..."
        )

        # Create cache directory
        cache_dir = os.path.join(tempfile.gettempdir(), "clippy-worker-cache")

        try:
            # Download the file
            media_id = media_file.get("id")
            user_id = project_data.get("user_id")

            if not media_id or not user_id:
                raise ValueError(
                    f"Missing media_id or user_id for clip {clip_data['id']}"
                )

            app.logger.info(
                f"Attempting to download media_id={media_id}, user_id={user_id}"
            )
            input_path = _download_media_file(media_id, user_id, cache_dir)
            app.logger.info(f"Successfully downloaded media {media_id} to {input_path}")

        except Exception as e:
            app.logger.error(
                f"Download failed for clip {clip_data['id']}: {e}", exc_info=True
            )
            raise ValueError(
                f"Media file not found for clip {clip_data['id']} "
                f"and download failed: {e}"
            ) from e

    output_path = os.path.join(temp_dir, f"clip_{clip_data['id']}_processed.mp4")

    # Build ffmpeg command
    app = _get_app()
    ffmpeg_bin = resolve_binary(app, "ffmpeg")

    from app.ffmpeg_config import config_args as _cfg_args

    cmd = [ffmpeg_bin, *_cfg_args(app, "ffmpeg", "encode")]

    # Add clip trimming if specified
    start_time = clip_data.get("start_time")
    end_time = clip_data.get("end_time")
    max_clip_duration = project_data.get("max_clip_duration")

    if start_time is not None and end_time is not None:
        duration = end_time - start_time
        cmd.extend(["-ss", str(start_time), "-t", str(duration)])
    elif max_clip_duration:
        cmd.extend(["-t", str(max_clip_duration)])

    # Apply tier-based resolution cap
    project_output_res = project_data.get("output_resolution", "1080p")
    tier_max_res = tier_limits.get("max_res_label")
    logger.info(
        "resolution_pipeline",
        project_output_res=project_output_res,
        tier_max_res=tier_max_res,
        clip_id=clip_data.get("id"),
    )
    print(
        f"[CLIP] Resolution debug - Project: {project_output_res}, Tier max: {tier_max_res}"
    )

    eff_label = _cap_resolution_label(project_output_res, tier_max_res)
    logger.info(
        "resolution_after_cap", effective_label=eff_label, clip_id=clip_data.get("id")
    )
    print(f"[CLIP] Resolution debug - After cap: {eff_label}")

    target_res = parse_resolution(None, eff_label or project_output_res)
    logger.info("resolution_final", target_res=target_res, clip_id=clip_data.get("id"))
    print(f"[CLIP] Resolution debug - Final target_res: {target_res}")

    # Determine if we need letterboxing (portrait output with landscape input)
    target_width, target_height = map(int, target_res.split("x"))
    is_portrait_output = target_height > target_width

    # Build scale filter with letterboxing for portrait outputs
    if is_portrait_output:
        # For portrait: scale up by 20%, crop to fit, then pad to canvas size
        # This zooms in slightly to reduce black bars while maintaining 16:9 content
        scale_filter = f"scale=iw*1.2:ih*1.2,crop={target_width}:ih,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black"
    else:
        # For landscape/square: scale normally
        scale_filter = f"scale={target_width}:{target_height}:flags=lanczos"

    # Overlay text (creator + game name)
    font = resolve_fontfile()
    creator_name = (clip_data.get("creator_name") or "").strip()
    game_name = (clip_data.get("game_name") or "").strip()

    # Resolve avatar path for overlay
    avatar_path = None
    if creator_name:
        avatar_path = _resolve_avatar_path(app, clip_data.get("id"), creator_name)

    # Build filter complex with overlay if enabled
    # Add main video input first
    cmd.extend(["-i", input_path])

    # Then add avatar as second input if present
    has_avatar = False
    if (
        overlay_enabled()
        and creator_name
        and avatar_path
        and os.path.isfile(avatar_path)
    ):
        has_avatar = True
        cmd.extend(["-i", avatar_path])

    # Build filter complex
    if overlay_enabled() and (creator_name or game_name):
        if has_avatar:
            # Build filter matching original ffmpegApplyOverlay template
            # [0:v] is main video, [1:v] is avatar (if present)
            author_text = (creator_name or "").replace("'", "'")
            game_text = (game_name or "").replace("'", "'") if game_name else ""

            # Scale video first (with letterboxing if portrait), then apply overlays
            filter_chain = (
                f"[0:v]{scale_filter},"
                f"drawbox=enable='between(t,3,10)':x=0:y=(ih)-238:h=157:w=1000:color=black@0.7:t=fill,"
                f"drawtext=enable='between(t,3,10)':x=198:y=(h)-210:fontfile='{font}':fontsize=28:fontcolor=white@0.4:text='clip by',"
                f"drawtext=enable='between(t,3,10)':x=198:y=(h)-180:fontfile='{font}':fontsize=48:fontcolor=white@0.9:text='{author_text}'"
            )

            if game_text:
                filter_chain += f",drawtext=enable='between(t,3,10)':x=198:y=(h)-130:fontfile='{font}':fontsize=26:fontcolor=white@0.5:text='{game_text}'"

            # Scale avatar to 128x128 and overlay on top
            filter_chain += "[overlay];[1:v]scale=128:128[avatar];[overlay][avatar]overlay=enable='between(t,3,10)':x=50:y=H-223[v]"

            filter_complex = filter_chain
        else:
            # No avatar - use build_overlay_filter for text only
            has_avatar_flag, overlay_chain = build_overlay_filter(
                author=creator_name, game=game_name, fontfile=font, avatar_path=None
            )
            filter_complex = f"[0:v]{scale_filter}," + overlay_chain + "[v]"
    else:
        filter_complex = f"[0:v]{scale_filter}[v]"

    print(f"[CLIP] Built filter_complex: {filter_complex[:200]}...")
    cmd.extend(["-filter_complex", filter_complex])

    # Map the filtered video output
    cmd.extend(["-map", "[v]"])

    # Add encoder args
    cmd.extend(encoder_args(ffmpeg_bin))

    # Add audio normalization if configured
    audio_profile = project_data.get("audio_norm_profile")
    audio_db = project_data.get("audio_norm_db")
    if audio_profile or audio_db:
        cmd.extend(audio_args(app, audio_profile, audio_db))
    else:
        # Map audio stream from the main video input
        # When avatar is present: input 0=video (with audio), input 1=avatar.png (no audio)
        # When no avatar: input 0=video (with audio)
        cmd.extend(["-map", "0:a"])

    # Output
    cmd.extend(["-y", output_path])

    # Execute
    app.logger.info(
        f"Running ffmpeg for clip {clip_data['id']}: {' '.join(cmd[:10])}..."
    )
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # Log stderr to see what ffmpeg is complaining about
        stderr_output = (
            e.stderr.decode("utf-8", errors="replace") if e.stderr else "No stderr"
        )
        app.logger.error(
            f"ffmpeg failed for clip {clip_data['id']} with exit code {e.returncode}"
        )
        app.logger.error(f"ffmpeg stderr: {stderr_output}")
        raise

    return output_path


def _process_media_file_v2(
    media_data: dict, output_path: str, project_data: dict, tier_limits: dict
) -> None:
    """Process intro/outro/transition media file (API-based).

    Args:
        media_data: Media file dict with id, file_path, etc.
        output_path: Output processed file path
        project_data: Project dict from API
        tier_limits: Tier limits dict
    """
    app = _get_app()
    ffmpeg_bin = resolve_binary(app, "ffmpeg")

    # Resolve and repair input path if needed
    original_path = media_data.get("file_path", "")
    media_path = _resolve_media_input_path(original_path)

    # If file doesn't exist locally, download it from main server
    if not os.path.exists(media_path):
        app.logger.warning(
            f"Media file not found locally: {media_path}. Attempting download..."
        )

        # Create cache directory
        cache_dir = os.path.join(tempfile.gettempdir(), "clippy-worker-cache")

        try:
            # Download the file
            media_id = media_data.get("id")
            user_id = project_data.get("user_id")

            if not media_id or not user_id:
                raise ValueError(
                    f"Missing media_id or user_id for media file {media_data}"
                )

            media_path = _download_media_file(media_id, user_id, cache_dir)
            app.logger.info(f"Successfully downloaded media {media_id} to {media_path}")

        except Exception as e:
            raise ValueError(f"Media file not found and download failed: {e}") from e

    from app.ffmpeg_config import config_args as _cfg_args

    # Apply tier-based resolution cap
    eff_label = _cap_resolution_label(
        project_data.get("output_resolution", "1080p"),
        tier_limits.get("max_res_label"),
    )
    target_res = parse_resolution(
        None, eff_label or project_data.get("output_resolution", "1080p")
    )

    target_width, target_height = map(int, target_res.split("x"))
    is_portrait_output = target_height > target_width

    # For intro/outro/transitions/static: scale and crop to fit portrait canvas
    if is_portrait_output:
        # Scale to ensure we have enough height, then crop to exact dimensions
        # For 1920x1080 -> 1080x1920: scale to -1:1920 (auto width), then crop to 1080:1920
        scale_filter = f"scale=-1:{target_height},crop={target_width}:{target_height}"
    else:
        # For landscape/square: scale normally
        scale_filter = f"scale={target_width}:{target_height}:flags=lanczos"

    cmd = [
        ffmpeg_bin,
        *_cfg_args(app, "ffmpeg", "encode"),
        "-i",
        media_path,
        "-vf",
        scale_filter,
        *encoder_args(ffmpeg_bin),
        "-y",
        output_path,
    ]

    subprocess.run(cmd, check=True, capture_output=True)


def _build_timeline_with_transitions_v2(
    project_data: dict,
    processed_clips: list[str],
    temp_dir: str,
    intro_id: int | None,
    outro_id: int | None,
    transition_ids: list[int],
    randomize: bool,
    tier_limits: dict,
) -> list[str]:
    """Build timeline with intro/outro/transitions (API-based).

    Args:
        project_data: Project dict from API
        processed_clips: List of processed clip file paths
        temp_dir: Temporary directory
        intro_id: Optional intro media file ID
        outro_id: Optional outro media file ID
        transition_ids: List of transition media file IDs
        randomize: Whether to randomize transition selection
        tier_limits: Tier limits dict

    Returns:
        List of file paths in final timeline order
    """
    user_id = project_data["user_id"]

    # Collect all media IDs to fetch
    media_ids = []
    if intro_id:
        media_ids.append(intro_id)
    if outro_id:
        media_ids.append(outro_id)
    if transition_ids:
        media_ids.extend(transition_ids)

    # Batch fetch intro/outro/transitions
    media_files = {}
    if media_ids:
        response = worker_api.get_media_batch(media_ids, user_id)
        for mf in response.get("media_files", []):
            media_files[mf["id"]] = mf

    # Process intro
    intro_path = None
    if intro_id and intro_id in media_files:
        intro = media_files[intro_id]
        intro_processed = os.path.join(temp_dir, "intro_processed.mp4")
        _process_media_file_v2(intro, intro_processed, project_data, tier_limits)
        intro_path = intro_processed

    # Process outro
    outro_path = None
    if outro_id and outro_id in media_files:
        outro = media_files[outro_id]
        outro_processed = os.path.join(temp_dir, "outro_processed.mp4")
        _process_media_file_v2(outro, outro_processed, project_data, tier_limits)
        outro_path = outro_processed

    # Process transitions
    transition_paths = []
    for tid in transition_ids:
        if tid in media_files:
            trans = media_files[tid]
            trans_processed = os.path.join(temp_dir, f"transition_{tid}_processed.mp4")
            _process_media_file_v2(trans, trans_processed, project_data, tier_limits)
            transition_paths.append(trans_processed)

    # Get static bumper path
    app = _get_app()
    static_bumper_path = None

    # Check configured path first
    configured_static = app.config.get("STATIC_BUMPER_PATH")
    if configured_static and os.path.exists(configured_static):
        static_bumper_path = configured_static
    else:
        # Try instance/assets/static.mp4
        with app.app_context():
            from app.storage import data_root

            instance_static = os.path.join(data_root(), "..", "assets", "static.mp4")
            instance_static = os.path.normpath(instance_static)
            if os.path.exists(instance_static):
                static_bumper_path = instance_static

    # Process static bumper if present
    processed_static_path = None
    if static_bumper_path and os.path.exists(static_bumper_path):
        processed_static_path = os.path.join(temp_dir, "static_processed.mp4")
        # Create a minimal media_data dict for static.mp4
        static_media_data = {"file_path": static_bumper_path}
        _process_media_file_v2(
            static_media_data, processed_static_path, project_data, tier_limits
        )

    # Build timeline with transitions between segments
    import random as _random

    def _next_transition(idx: int) -> str | None:
        if not transition_paths:
            return None
        if randomize:
            return _random.choice(transition_paths)
        return transition_paths[idx % len(transition_paths)]

    segments = []

    # Intro
    if intro_path:
        segments.append(intro_path)

    # Static after intro
    if intro_path and processed_static_path:
        segments.append(processed_static_path)

    # Add clips with transitions and static bumpers
    transition_idx = 0
    for i, clip_path in enumerate(processed_clips):
        # Add transition before this clip (not before first clip)
        if i > 0 and transition_paths:
            trans = _next_transition(transition_idx)
            if trans:
                segments.append(trans)
                transition_idx += 1

        # Static before clip (after transition, or at start if no intro)
        if processed_static_path:
            segments.append(processed_static_path)

        # The clip itself
        segments.append(clip_path)

        # Static after clip
        if processed_static_path:
            segments.append(processed_static_path)

    # Outro
    if outro_path:
        segments.append(outro_path)

    # Save segment labels for logging
    labels = []
    for seg in segments:
        basename = os.path.basename(seg)
        if "intro" in basename:
            labels.append("Intro")
        elif "outro" in basename:
            labels.append("Outro")
        elif "transition" in basename:
            labels.append("Transition")
        elif "clip" in basename:
            labels.append(basename.replace("_processed.mp4", ""))
        else:
            labels.append(basename)

    labels_path = os.path.join(temp_dir, "concat_labels.json")
    with open(labels_path, "w") as f:
        json.dump(labels, f)

    return segments


def _compile_final_video_v2(
    clips: list[str],
    temp_dir: str,
    project_data: dict,
    background_music_id: int | None = None,
    music_volume: float | None = None,
    music_start_mode: str | None = None,
    music_end_mode: str | None = None,
    intro_id: int | None = None,
    outro_id: int | None = None,
    user_id: int | None = None,
) -> str:
    """Compile final video from clips with optional background music (API-based).

    Args:
        clips: List of processed clip file paths
        temp_dir: Temporary directory
        project_data: Project dict from API
        background_music_id: Optional background music file ID
        music_volume: Music volume (0.0-1.0), defaults to 0.3
        music_start_mode: When to start music ('start' or 'after_intro')
        music_end_mode: When to end music ('end' or 'before_outro')
        intro_id: Intro media file ID (used to detect timing)
        outro_id: Outro media file ID (used to detect timing)
        user_id: User ID for fetching music file

    Returns:
        Path to compiled output file
    """
    app = _get_app()
    ffmpeg_bin = resolve_binary(app, "ffmpeg")

    output_format = project_data.get("output_format", "mp4")
    output_path = os.path.join(
        temp_dir, f"compilation_{project_data['id']}.{output_format}"
    )

    # Create concat file
    concat_file = os.path.join(temp_dir, "concat.txt")
    with open(concat_file, "w") as f:
        for clip_path in clips:
            # Escape single quotes in path
            escaped = clip_path.replace("'", r"'\''")
            f.write(f"file '{escaped}'\n")

    from app.ffmpeg_config import config_args as _cfg_args

    # First, concat all video segments
    concat_output = os.path.join(temp_dir, "concat_no_music.mp4")
    cmd = [
        ffmpeg_bin,
        *_cfg_args(app, "ffmpeg", "concat"),
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_file,
        "-c",
        "copy",
        "-y",
        concat_output,
    ]

    subprocess.run(cmd, check=True, capture_output=True)

    # If no background music, return the concat output
    if not background_music_id:
        shutil.move(concat_output, output_path)
        return output_path

    # Fetch music file
    music_path = None
    try:
        if user_id:
            response = worker_api.get_media_batch([background_music_id], user_id)
            media_files = response.get("media_files", [])
            if media_files:
                music_data = media_files[0]
                music_path = music_data.get("file_path")
    except Exception:
        pass

    # If music file not found, return without music
    if not music_path or not os.path.exists(music_path):
        shutil.move(concat_output, output_path)
        return output_path

    # Calculate music start/end times based on intro/outro
    # First, get total video duration
    video_meta = extract_video_metadata(concat_output)
    total_duration = video_meta.get("duration", 0)

    music_start_time = 0.0
    music_end_time = total_duration

    # Calculate start time
    if music_start_mode == "after_intro" and intro_id:
        try:
            if user_id:
                response = worker_api.get_media_batch([intro_id], user_id)
                media_files = response.get("media_files", [])
                if media_files:
                    intro_data = media_files[0]
                    intro_duration = intro_data.get("duration", 0)
                    if intro_duration:
                        music_start_time = float(intro_duration)
        except Exception:
            pass

    # Calculate end time
    if music_end_mode == "before_outro" and outro_id:
        try:
            if user_id:
                response = worker_api.get_media_batch([outro_id], user_id)
                media_files = response.get("media_files", [])
                if media_files:
                    outro_data = media_files[0]
                    outro_duration = outro_data.get("duration", 0)
                    if outro_duration:
                        music_end_time = total_duration - float(outro_duration)
        except Exception:
            pass

    # Mix background music with audio ducking for clips that have audio
    volume = music_volume if music_volume is not None else 0.3
    volume = max(0.0, min(1.0, float(volume)))  # Clamp to 0-1

    # Detect if video has audible content using silencedetect
    # This helps us duck the music when the video has actual audio
    try:
        probe_cmd = [
            resolve_binary(app, "ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            concat_output,
        ]
        import json

        probe_output = subprocess.check_output(probe_cmd, text=True)
        probe_data = json.loads(probe_output)
        has_audio_stream = any(
            s.get("codec_type") == "audio" for s in probe_data.get("streams", [])
        )
    except Exception:
        has_audio_stream = True  # Assume audio exists if detection fails

    # Get music file duration to determine if we need to loop it
    music_meta = extract_video_metadata(music_path)
    music_file_duration = music_meta.get("duration", 0)

    # Build ffmpeg command to mix audio
    # If video has audio streams, use sidechaincompress to duck music when video audio is present
    # Otherwise, just mix normally
    music_duration = music_end_time - music_start_time

    # Determine if we need to loop the music to cover the video duration
    # We need music to last from start_time to end_time
    needed_music_duration = music_duration + music_start_time
    needs_loop = music_file_duration > 0 and music_file_duration < needed_music_duration

    if has_audio_stream:
        # Use sidechaincompress for automatic ducking when video audio is present
        # This reduces music volume by ~20dB when video audio is detected above -40dB threshold
        if needs_loop:
            # Loop music to ensure it covers the full video duration
            loop_count = int(needed_music_duration / music_file_duration) + 1
            filter_complex = (
                f"[1:a]aloop=loop={loop_count}:size={int(music_file_duration * 48000)},"
                f"adelay={int(music_start_time * 1000)}|{int(music_start_time * 1000)},"
                f"volume={volume},afade=t=out:st={music_duration - 2}:d=2[music];"
                f"[0:a]asplit=2[va1][va2];"
                f"[music][va2]sidechaincompress=threshold=0.02:ratio=20:attack=1:release=250[compressed];"
                f"[va1][compressed]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
        else:
            filter_complex = (
                f"[1:a]adelay={int(music_start_time * 1000)}|{int(music_start_time * 1000)},"
                f"volume={volume},afade=t=out:st={music_duration - 2}:d=2[music];"
                f"[0:a]asplit=2[va1][va2];"
                f"[music][va2]sidechaincompress=threshold=0.02:ratio=20:attack=1:release=250[compressed];"
                f"[va1][compressed]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
        audio_map = "[aout]"
    else:
        # No audio in video, use music as the only audio source
        # Loop music if needed to cover the video duration
        if needs_loop:
            loop_count = int(needed_music_duration / music_file_duration) + 1
            filter_complex = (
                f"[1:a]aloop=loop={loop_count}:size={int(music_file_duration * 48000)},"
                f"adelay={int(music_start_time * 1000)}|{int(music_start_time * 1000)},"
                f"volume={volume},afade=t=out:st={music_duration - 2}:d=2[music]"
            )
        else:
            filter_complex = (
                f"[1:a]adelay={int(music_start_time * 1000)}|{int(music_start_time * 1000)},"
                f"volume={volume},afade=t=out:st={music_duration - 2}:d=2[music]"
            )
        audio_map = "[music]"

    cmd = [
        ffmpeg_bin,
        *_cfg_args(app, "ffmpeg", "encode"),
        "-i",
        concat_output,  # Video input
        "-stream_loop",
        "-1",  # Loop music input indefinitely
        "-i",
        music_path,  # Music input
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",  # Use video from first input
        "-map",
        audio_map,  # Use mixed/ducked audio or just music
        "-c:v",
        "copy",  # Copy video (already processed)
        "-c:a",
        "aac",  # Encode audio
        "-b:a",
        "192k",
        "-shortest",  # End when video ends
        "-y",
        output_path,
    ]

    subprocess.run(cmd, check=True, capture_output=True)

    return output_path


def _save_final_video_v2(temp_path: str, project_data: dict, user_id: int) -> str:
    """Save final video to persistent storage (API-based).

    Args:
        temp_path: Temporary output file path
        project_data: Project dict from API
        user_id: User ID (passed separately since we don't have user object)

    Returns:
        Final persistent file path
    """
    app = _get_app()

    with app.app_context():
        # Build output directory using storage helper for project-based layout
        from app.models import User, db

        user = db.session.get(User, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        project_name = project_data.get("name", f"project_{project_data['id']}")
        output_dir = storage_lib.compilations_dir(user, project_name)
        os.makedirs(output_dir, exist_ok=True)

        # Generate filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_format = project_data.get("output_format", "mp4")
        project_name = project_data.get("name", f"project_{project_data['id']}")
        # Sanitize project name for filename
        safe_name = "".join(
            c for c in project_name if c.isalnum() or c in (" ", "_", "-")
        )
        safe_name = safe_name.replace(" ", "_")
        filename = f"{safe_name}_{timestamp}.{output_format}"

        final_path = os.path.join(output_dir, filename)
        shutil.move(temp_path, final_path)

        return final_path


@celery_app.task(bind=True, name="tasks.compile_video_v2")
def compile_video_task_v2(
    self,
    project_id: int,
    intro_id: int | None = None,
    outro_id: int | None = None,
    transition_ids: list[int] | None = None,
    randomize_transitions: bool = False,
    clip_ids: list[int] | None = None,
    background_music_id: int | None = None,
    music_volume: float | None = None,
    music_start_mode: str | None = None,
    music_end_mode: str | None = None,
) -> dict[str, Any]:
    """Compile video clips into final compilation (Worker API version).

    This version uses worker API instead of direct database access,
    allowing workers to run in DMZ without DATABASE_URL.

    Args:
        project_id: ID of the project to compile
        intro_id: Optional intro media file ID
        outro_id: Optional outro media file ID
        transition_ids: Optional list of transition media file IDs
        randomize_transitions: Whether to randomize transition selection
        clip_ids: Optional explicit timeline subset
        background_music_id: Optional background music file ID
        music_volume: Music volume (0.0-1.0), defaults to 0.3
        music_start_mode: When to start music ('start' or 'after_intro')
        music_end_mode: When to end music ('end' or 'before_outro')

    Returns:
        Dict with compilation results
    """
    try:
        # Update task status
        self.update_state(
            state="PROGRESS", meta={"progress": 0, "status": "Starting compilation"}
        )

        # Fetch all compilation context in one API call
        context = worker_api.get_compilation_context(project_id)
        project_data = context["project"]
        all_clips = context["clips"]
        tier_limits = context["tier_limits"]

        # Create processing job
        job_response = worker_api.create_processing_job(
            celery_task_id=self.request.id,
            job_type="compile_video",
            project_id=project_id,
            user_id=project_data["user_id"],
        )
        job_id = job_response["job_id"]

        # Helper to log to job result_data
        def log(level: str, message: str, status: str | None = None):
            try:
                # Fetch current job to get existing logs
                job_data = worker_api.get_processing_job(job_id)
                result_data = job_data.get("result_data") or {}
                logs = result_data.get("logs") or []
                logs.append(
                    {
                        "ts": datetime.utcnow().isoformat(),
                        "level": level,
                        "message": message,
                        "status": status,
                    }
                )
                result_data["logs"] = logs
                worker_api.update_processing_job(job_id, result_data=result_data)
            except Exception:
                pass  # Don't fail compilation if logging fails

        # Filter clips if explicit timeline provided
        if clip_ids:
            clip_map = {c["id"]: c for c in all_clips}
            clips = [clip_map[cid] for cid in clip_ids if cid in clip_map]
        else:
            clips = all_clips

        # Apply tier limits
        original_count = len(clips)
        clips = _apply_tier_limits_to_clips(clips, tier_limits)
        if len(clips) < original_count:
            max_clips = tier_limits.get("max_clips", 0)
            log(
                "info",
                f"Tier limit: using first {max_clips} clip(s) out of {original_count}",
                status="limits",
            )

        if not clips:
            raise ValueError("No clips found for compilation")

        self.update_state(
            state="PROGRESS", meta={"progress": 10, "status": "Preparing clips"}
        )
        log("info", "Preparing clips", status="preparing")
        worker_api.update_processing_job(job_id, progress=10)

        # Process clips in temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            processed_clips = []
            used_clip_ids = []

            for i, clip in enumerate(clips):
                progress = 10 + (i / len(clips)) * 60  # 10-70%
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "progress": progress,
                        "status": f"Processing clip {i+1}/{len(clips)}",
                    },
                )
                log("info", f"Processing clip {i+1}/{len(clips)}")
                worker_api.update_processing_job(job_id, progress=int(progress))

                try:
                    clip_path = _process_clip_v2(
                        clip, temp_dir, project_data, tier_limits
                    )
                    if clip_path:
                        processed_clips.append(clip_path)
                        used_clip_ids.append(clip["id"])
                except Exception as e:
                    _get_app().logger.error(
                        f"Failed to process clip {clip['id']}: {str(e)}", exc_info=True
                    )
                    log("error", f"Failed to process clip {clip['id']}: {str(e)}")
                    continue

            if not processed_clips:
                raise ValueError("No clips could be processed")

            self.update_state(
                state="PROGRESS", meta={"progress": 70, "status": "Adding intro/outro"}
            )
            log("info", "Adding intro/outro")
            worker_api.update_processing_job(job_id, progress=70)

            # Build timeline with transitions
            final_clips = _build_timeline_with_transitions_v2(
                project_data=project_data,
                processed_clips=processed_clips,
                temp_dir=temp_dir,
                intro_id=intro_id,
                outro_id=outro_id,
                transition_ids=transition_ids or [],
                randomize=randomize_transitions,
                tier_limits=tier_limits,
            )

            self.update_state(
                state="PROGRESS",
                meta={"progress": 80, "status": "Compiling final video"},
            )
            log("info", "Compiling final video", status="compiling")
            worker_api.update_processing_job(job_id, progress=80)

            # Log concat items
            labels_path = os.path.join(temp_dir, "concat_labels.json")
            try:
                if os.path.exists(labels_path):
                    with open(labels_path) as f:
                        labels = json.load(f) or []
                        for idx, label in enumerate(labels):
                            log(
                                "info",
                                f"Concatenating: {label} ({idx+1} of {len(labels)})",
                                status="concatenating",
                            )
            except Exception:
                pass

            # Compile final video
            output_path = _compile_final_video_v2(
                final_clips,
                temp_dir,
                project_data,
                background_music_id=background_music_id,
                music_volume=music_volume,
                music_start_mode=music_start_mode,
                music_end_mode=music_end_mode,
                intro_id=intro_id,
                outro_id=outro_id,
                user_id=project_data["user_id"],
            )

            self.update_state(
                state="PROGRESS",
                meta={"progress": 90, "status": "Uploading compilation"},
            )
            log("info", "Uploading compilation", status="uploading")
            worker_api.update_processing_job(job_id, progress=90)

            # Extract metadata before upload
            meta = extract_video_metadata(output_path)
            file_size = os.path.getsize(output_path)

            # Generate thumbnail
            thumb_path = None
            try:
                app = _get_app()
                thumb_dir = tempfile.mkdtemp(prefix="thumb_")
                stem = os.path.splitext(os.path.basename(output_path))[0]
                thumb_path = os.path.join(thumb_dir, f"{stem}.jpg")

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
            except Exception as e:
                log("warning", f"Failed to generate thumbnail: {e}")
                thumb_path = None

            # Upload compilation to server
            try:
                # Generate filename with timestamp
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                output_format = project_data.get("output_format", "mp4")
                project_name = project_data.get("name", f"project_{project_data['id']}")
                safe_name = "".join(
                    c for c in project_name if c.isalnum() or c in (" ", "_", "-")
                )
                safe_name = safe_name.replace(" ", "_")
                filename = f"{safe_name}_{timestamp}.{output_format}"

                upload_metadata = {
                    "filename": filename,
                    "file_size": file_size,
                }
                if meta:
                    upload_metadata.update(
                        {
                            "duration": meta.get("duration"),
                            "width": meta.get("width"),
                            "height": meta.get("height"),
                            "framerate": meta.get("framerate"),
                        }
                    )

                upload_result = worker_api.upload_compilation(
                    project_id=project_id,
                    video_path=output_path,
                    thumbnail_path=thumb_path,
                    metadata=upload_metadata,
                )

                log(
                    "success",
                    f"Uploaded compilation: {upload_result.get('media_id')}",
                    status="uploaded",
                )
                final_output_path = upload_result.get("file_path", output_path)

            except Exception as e:
                log("error", f"Failed to upload compilation: {e}")
                # Fall back to local path if upload fails
                final_output_path = output_path
                # Still try to save locally
                final_output_path = _save_final_video_v2(
                    output_path, project_data, project_data["user_id"]
                )

            # Update project status
            worker_api.update_project_status(
                project_id=project_id,
                status="completed",
                output_filename=os.path.basename(final_output_path),
                output_file_size=file_size,
            )

            # Record render usage
            try:
                if meta and meta.get("duration"):
                    seconds = int(float(meta["duration"]))
                    if seconds > 0:
                        worker_api.record_render_usage(
                            user_id=project_data["user_id"],
                            project_id=project_id,
                            seconds=seconds,
                        )
            except Exception:
                pass

            # Update job status
            result_data = {
                "output_file": storage_lib.instance_canonicalize(final_output_path)
                or final_output_path,
                "clips_processed": len(processed_clips),
                "used_clip_ids": used_clip_ids,
            }

            worker_api.update_processing_job(
                job_id,
                status="success",
                progress=100,
                result_data=result_data,
            )

            log("success", "Compilation completed", status="completed")

            return {
                "status": "completed",
                "output_file": storage_lib.instance_canonicalize(final_output_path)
                or final_output_path,
                "clips_processed": len(processed_clips),
                "project_id": project_id,
                "used_clip_ids": used_clip_ids,
            }

    except Exception as e:
        # Update project and job on error
        try:
            worker_api.update_project_status(
                project_id=project_id, status="failed", processing_log=str(e)
            )
        except Exception:
            pass

        if "job_id" in locals():
            try:
                worker_api.update_processing_job(
                    job_id, status="failure", error_message=str(e)
                )
            except Exception:
                pass

        raise
