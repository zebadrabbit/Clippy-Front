"""
Media maintenance tasks: reindex DB from filesystem and maintenance utilities.
"""
import os
import sys

from sqlalchemy.orm import scoped_session, sessionmaker

from app.models import db
from app.tasks.celery_app import celery_app


def _get_db_session():
    from app import create_app

    app = create_app()
    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))
        return Session(), app


def _resolve_binary(app, name: str) -> str:
    from app.tasks.video_processing import resolve_binary as _rb

    return _rb(app, name)


@celery_app.task(bind=True)
def reindex_media_task(self, regen_thumbnails: bool = True) -> dict:
    """Scan the per-user data root (instance/data) and backfill MediaFile rows (read-only).

    Note: Thumbnail regeneration is disabled by policy in this task to avoid modifying on-disk assets;
    the regen_thumbnails flag is ignored and retained only for backward compatibility. Use the script
    `python scripts/reindex_media.py --regen-thumbnails` if you need to restore missing thumbnails.
    """
    try:
        # Warn if a caller tried to enable regeneration (no-op)
        if regen_thumbnails:
            try:
                import warnings as _warnings

                _warnings.warn(
                    "reindex_media_task: regen_thumbnails is ignored; reindex is read-only",
                    DeprecationWarning,
                    stacklevel=2,
                )
            except Exception:
                pass
        # Ensure project root is on sys.path so 'scripts' can be imported when worker is started via
        # 'celery -A app.tasks.celery_app worker' (which may not include CWD)
        _here = os.path.dirname(os.path.abspath(__file__))
        _repo_root = os.path.abspath(os.path.join(_here, "..", ".."))
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        from scripts.reindex_media import reindex as run_reindex

        # Always run in read-only mode (no thumbnail regeneration)
        created = int(run_reindex(regen_thumbs=False) or 0)
        return {
            "status": "completed",
            "created": created,
            "regen_thumbnails": False,
        }
    except Exception as e:
        raise RuntimeError(f"Reindex failed: {e}") from e


@celery_app.task(bind=True)
def process_uploaded_media_task(
    self, media_id: int, generate_thumbnail: bool = True
) -> dict:
    """Process uploaded media file: generate thumbnail and extract metadata.

    This task should be called after a media file is uploaded to avoid
    blocking the web request with ffmpeg operations.

    Args:
        media_id: ID of the MediaFile to process
        generate_thumbnail: Whether to generate a thumbnail (default True)

    Returns:
        Dict with processing results
    """
    import subprocess
    from pathlib import Path

    from app import create_app
    from app.models import MediaFile, db

    app = create_app()
    with app.app_context():
        from sqlalchemy import select

        # Get media file
        media = db.session.execute(
            select(MediaFile).filter_by(id=media_id)
        ).scalar_one_or_none()

        if not media:
            return {"status": "error", "error": f"Media file {media_id} not found"}

        # Expand canonical /instance/... path to full absolute path
        from app.storage import instance_canonicalize, instance_expand

        expanded_path = instance_expand(media.file_path)
        if not expanded_path or not Path(expanded_path).exists():
            return {
                "status": "error",
                "error": f"File not found: {media.file_path} (expanded: {expanded_path})",
            }

        file_path = Path(expanded_path)
        results = {"status": "success", "media_id": media_id}

        # Generate thumbnail for video files
        if (
            generate_thumbnail
            and media.mime_type
            and media.mime_type.startswith("video")
        ):
            try:
                from app.ffmpeg_config import config_args as _cfg_args
                from app.main.routes import _resolve_binary

                dest_dir = file_path.parent
                stem = file_path.stem
                thumb_path = dest_dir / f"{stem}_thumb.jpg"

                app.logger.info(f"Generating thumbnail: {thumb_path} from {file_path}")
                subprocess.run(
                    [
                        _resolve_binary(app, "ffmpeg"),
                        *_cfg_args(app, "ffmpeg", "thumbnail"),
                        "-y",
                        "-i",
                        str(file_path),
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={int(app.config.get('THUMBNAIL_WIDTH', 480))}:-1",
                        str(thumb_path),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=30,
                )

                if not thumb_path.exists():
                    app.logger.error(
                        f"Thumbnail generation claimed success but file doesn't exist: {thumb_path}"
                    )
                    raise FileNotFoundError(f"Thumbnail not created: {thumb_path}")

                # Canonicalize the thumbnail path back to /instance/... format
                canonical_thumb = instance_canonicalize(str(thumb_path))
                app.logger.info(
                    f"Thumbnail created at {thumb_path}, canonical path: {canonical_thumb}"
                )
                media.thumbnail_path = canonical_thumb
                results["thumbnail"] = canonical_thumb

            except Exception as e:
                app.logger.warning(f"Thumbnail generation failed for {media_id}: {e}")
                results["thumbnail_error"] = str(e)

        # Extract metadata with ffprobe for video and audio files
        if media.mime_type and (
            media.mime_type.startswith("video") or media.mime_type.startswith("audio")
        ):
            try:
                from app.ffmpeg_config import config_args as _cfg_args
                from app.main.routes import _resolve_binary

                probe_cmd = [
                    _resolve_binary(app, "ffprobe"),
                    *_cfg_args(app, "ffprobe"),
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=width,height,r_frame_rate,codec_type",
                    "-of",
                    "json",
                    str(file_path),
                ]

                import json

                out = subprocess.check_output(
                    probe_cmd, text=True, encoding="utf-8", timeout=15
                )
                data = json.loads(out)

                # Extract duration from format
                duration = data.get("format", {}).get("duration")
                if duration:
                    media.duration = float(duration)
                    results["duration"] = float(duration)

                # Extract video stream metadata (only for video files)
                if media.mime_type.startswith("video"):
                    for stream in data.get("streams", []):
                        if stream.get("codec_type") == "video":
                            if "width" in stream:
                                media.width = int(stream["width"])
                                results["width"] = int(stream["width"])
                            if "height" in stream:
                                media.height = int(stream["height"])
                                results["height"] = int(stream["height"])
                            if "r_frame_rate" in stream:
                                fps_str = stream["r_frame_rate"]
                                if "/" in fps_str:
                                    num, den = fps_str.split("/")
                                    media.fps = float(num) / float(den)
                                    results["fps"] = float(num) / float(den)
                            break

            except Exception as e:
                app.logger.warning(f"Metadata extraction failed for {media_id}: {e}")
                results["metadata_error"] = str(e)

        # Extract ID3 tags and other audio metadata for music/audio files
        if media.mime_type and media.mime_type.startswith("audio"):
            try:
                from app.audio_metadata import extract_audio_metadata

                audio_meta = extract_audio_metadata(str(file_path))
                if audio_meta:
                    # Update media file with extracted metadata
                    if "artist" in audio_meta and audio_meta["artist"]:
                        media.artist = audio_meta["artist"]
                        results["artist"] = audio_meta["artist"]

                    if "album" in audio_meta and audio_meta["album"]:
                        media.album = audio_meta["album"]
                        results["album"] = audio_meta["album"]

                    if "title" in audio_meta and audio_meta["title"]:
                        media.title = audio_meta["title"]
                        results["title"] = audio_meta["title"]

                    if "license" in audio_meta and audio_meta["license"]:
                        media.license = audio_meta["license"]
                        results["license"] = audio_meta["license"]

                    if (
                        "attribution_url" in audio_meta
                        and audio_meta["attribution_url"]
                    ):
                        media.attribution_url = audio_meta["attribution_url"]
                        results["attribution_url"] = audio_meta["attribution_url"]

                    if (
                        "attribution_text" in audio_meta
                        and audio_meta["attribution_text"]
                    ):
                        media.attribution_text = audio_meta["attribution_text"]
                        results["attribution_text"] = audio_meta["attribution_text"]

                    # If duration wasn't extracted from ffprobe, use mutagen's value
                    if not media.duration and "duration" in audio_meta:
                        media.duration = audio_meta["duration"]
                        results["duration"] = audio_meta["duration"]

                    app.logger.info(
                        f"Extracted audio metadata for {media_id}: {audio_meta}"
                    )

            except Exception as e:
                app.logger.warning(
                    f"Audio metadata extraction failed for {media_id}: {e}"
                )
                results["audio_metadata_error"] = str(e)

        # Save changes
        try:
            db.session.commit()
            results["saved"] = True
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to save media {media_id} metadata: {e}")
            results["save_error"] = str(e)

        return results
