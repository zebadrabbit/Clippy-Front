#!/usr/bin/env python3
# ruff: noqa: E402,I001
"""
Reindex media library from the filesystem into the database.

This script scans instance/uploads/<user_id>/** (excluding thumbnails) and creates
MediaFile rows for files that exist on disk but are missing in the DB.

It detects MIME (python-magic fallback to mimetypes) and generates thumbnails for
video files if missing. It infers media_type from the folder:
    intros/ → intro, outros/ → outro, transitions/ → transition,
    compilations/ → compilation, images/ → clip (image), clips/ → clip (video)

Usage:
    source venv/bin/activate
    python scripts/reindex_media.py [--regen-thumbnails]
"""
import argparse
import mimetypes
import os
import sys
from uuid import uuid4

# Ensure repository root is on sys.path so `import app` works when running directly
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from dotenv import load_dotenv
from app import create_app
from app.models import MediaFile, MediaType, db


def _infer_type_from_subfolder(sub: str) -> MediaType:
    s = (sub or "").lower()
    if s == "intros":
        return MediaType.INTRO
    if s == "outros":
        return MediaType.OUTRO
    if s == "transitions":
        return MediaType.TRANSITION
    if s == "compilations":
        return MediaType.COMPILATION
    # default bucket
    return MediaType.CLIP


def _detect_mime(path: str, fallback: str = "application/octet-stream") -> str:
    mime = None
    # Try python-magic first
    try:
        import magic  # type: ignore

        ms = magic.Magic(mime=True)
        detected = ms.from_file(path)
        if detected:
            mime = detected
    except Exception:
        pass
    if not mime:
        guessed, _ = mimetypes.guess_type(path)
        mime = guessed or fallback
    return mime


def _resolve_binary(app, name: str) -> str:
    # Adapted from app.main.routes._resolve_binary to avoid import cycles
    cfg = app.config.get("FFMPEG_BINARY" if name == "ffmpeg" else "YT_DLP_BINARY")
    if cfg:
        return cfg
    root = app.root_path
    proj_root = os.path.dirname(root)
    candidate = os.path.join(proj_root, "bin", name)
    if os.path.exists(candidate):
        return candidate
    return name


def _ensure_thumbnail(app, media: MediaFile):
    try:
        if not (media.mime_type or "").startswith("video"):
            return
        if media.thumbnail_path and os.path.exists(media.thumbnail_path):
            return
        base_upload = os.path.join(app.instance_path, app.config["UPLOAD_FOLDER"])
        thumbs_dir = os.path.join(base_upload, str(media.user_id), "thumbnails")
        os.makedirs(thumbs_dir, exist_ok=True)
        thumb_name = f"{uuid4().hex}.jpg"
        thumb_path = os.path.join(thumbs_dir, thumb_name)
        # Extract a frame at 1s; scale width to 480 keeping aspect ratio
        import subprocess

        subprocess.run(
            [
                _resolve_binary(app, "ffmpeg"),
                "-y",
                "-ss",
                "1",
                "-i",
                media.file_path,
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
        # Non-fatal
        pass


def reindex(regen_thumbs: bool = False) -> int:
    # Load environment variables from .env if present
    try:
        load_dotenv()
    except Exception:
        pass

    app = create_app()
    with app.app_context():
        base_upload = os.path.join(app.instance_path, app.config["UPLOAD_FOLDER"])
        if not os.path.isdir(base_upload):
            print(f"No upload directory: {base_upload}")
            return 0

        # Build set of known files in DB for quick skip
        known_paths = {m.file_path for m in MediaFile.query.all()}
        created = 0

        for uid in os.listdir(base_upload):
            user_dir = os.path.join(base_upload, uid)
            if not os.path.isdir(user_dir) or not uid.isdigit():
                continue
            for sub in os.listdir(user_dir):
                if sub.lower() == "thumbnails":
                    continue
                sub_dir = os.path.join(user_dir, sub)
                if not os.path.isdir(sub_dir):
                    continue
                mtype = _infer_type_from_subfolder(sub)
                for fname in os.listdir(sub_dir):
                    fpath = os.path.join(sub_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    if fpath in known_paths:
                        continue  # Already indexed
                    mime = _detect_mime(fpath)
                    try:
                        size = os.path.getsize(fpath)
                    except Exception:
                        size = 0
                    media = MediaFile(
                        filename=fname,
                        original_filename=fname,
                        file_path=fpath,
                        file_size=size,
                        mime_type=mime,
                        media_type=mtype,
                        user_id=int(uid),
                        project_id=None,
                    )
                    db.session.add(media)
                    if regen_thumbs:
                        _ensure_thumbnail(app, media)
                    created += 1
        if created:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Commit failed: {e}")
                return 0
        print(f"Reindexed {created} file(s).")
        return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reindex media library from disk")
    parser.add_argument(
        "--regen-thumbnails",
        action="store_true",
        help="Regenerate thumbnails for video files missing thumbnails",
    )
    args = parser.parse_args()
    reindex(regen_thumbs=args.regen_thumbnails)
