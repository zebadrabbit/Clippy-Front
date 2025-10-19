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

# Ensure repository root is on sys.path so `import app` works when running directly
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from dotenv import load_dotenv
from app.models import Clip, MediaFile, MediaType, Project, db
import hashlib


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
        # Deterministic thumbnail name based on media filename stem
        stem = os.path.splitext(os.path.basename(media.file_path))[0]
        thumb_path = os.path.join(thumbs_dir, f"{stem}.jpg")
        if os.path.exists(thumb_path):
            media.thumbnail_path = thumb_path
            return
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


def reindex(regen_thumbs: bool = False, app=None) -> int:
    # Load environment variables from .env if present
    try:
        load_dotenv()
    except Exception:
        pass

    # Use provided app if given (avoids recursion when called during create_app())
    if app is None:
        # Lazy import to avoid import cycle on module import
        from app import create_app  # type: ignore

        app = create_app()
    with app.app_context():
        base_upload = os.path.join(app.instance_path, app.config["UPLOAD_FOLDER"])
        downloads_dir = os.path.join(app.instance_path, "downloads")
        compilations_dir = os.path.join(app.instance_path, "compilations")
        created = 0

        # Cleanup: remove any previously indexed sidecar .meta.json entries (DB rows only)
        try:
            sidecars = (
                db.session.query(MediaFile)
                .filter(MediaFile.file_path.like("%.meta.json"))
                .all()
            )
            if sidecars:
                for sc in sidecars:
                    db.session.delete(sc)
                db.session.commit()
        except Exception:
            db.session.rollback()

        # Build sets for quick skip
        mf_all = MediaFile.query.all()
        known_paths = {m.file_path for m in mf_all}
        # Map user_id -> set of checksums to avoid reindexing dup content
        user_checksums: dict[int, set[str]] = {}
        for m in mf_all:
            if m.user_id is None:
                continue
            if m.checksum:
                user_checksums.setdefault(int(m.user_id), set()).add(m.checksum)

        # 1) Reindex per-user uploads library
        if not os.path.isdir(base_upload):
            print(f"No upload directory: {base_upload}")
        else:
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
                        # Skip hidden files and sidecar metadata
                        if fname.startswith(".") or fname.endswith(".meta.json"):
                            continue
                        fpath = os.path.join(sub_dir, fname)
                        if not os.path.isfile(fpath):
                            continue
                        if fpath in known_paths:
                            continue  # Already indexed
                        mime = _detect_mime(fpath)
                        # Compute checksum to prevent duplicate content rows
                        checksum = None
                        try:
                            h = hashlib.sha256()
                            with open(fpath, "rb") as fh:
                                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                                    h.update(chunk)
                            checksum = h.hexdigest()
                        except Exception:
                            checksum = None
                        # If we cannot obtain a checksum, skip indexing to avoid accumulating unknown files
                        if not checksum:
                            continue
                        # Skip if same content already indexed for this user
                        try:
                            if (
                                checksum
                                and int(uid) in user_checksums
                                and checksum in user_checksums[int(uid)]
                            ):
                                continue
                        except Exception:
                            pass
                        try:
                            size = os.path.getsize(fpath)
                        except Exception:
                            size = 0
                        # Do not read or create any sidecar metadata; database is the source of truth
                        original_name = fname

                        media = MediaFile(
                            filename=fname,
                            original_filename=original_name,
                            file_path=fpath,
                            file_size=size,
                            mime_type=mime,
                            media_type=mtype,
                            user_id=int(uid),
                            project_id=None,
                            checksum=checksum,
                        )
                        db.session.add(media)
                        if checksum:
                            user_checksums.setdefault(int(uid), set()).add(checksum)
                        # Never regenerate or modify files on disk during reindex
                        created += 1

        # 2) Reindex global downloads directory (assign to user 0 if unknown)
        if os.path.isdir(downloads_dir):
            # Build a map from clip id -> (user_id, project_id)
            clip_map = {
                c.id: (
                    c.project.owner.id if c.project and c.project.owner else None,
                    c.project_id,
                )
                for c in Clip.query.all()
            }
            import re as _re

            for fname in os.listdir(downloads_dir):
                if fname.startswith(".") or fname.endswith(".meta.json"):
                    continue
                fpath = os.path.join(downloads_dir, fname)
                if not os.path.isfile(fpath) or fpath in known_paths:
                    continue
                m = _re.match(r"clip_(\d+)_", fname)
                if not m:
                    continue  # can't infer owner; skip
                cid = int(m.group(1))
                owner_proj = clip_map.get(cid)
                if not owner_proj or not owner_proj[0]:
                    continue
                user_id, project_id = owner_proj
                mime = _detect_mime(fpath)
                # Compute checksum to prevent duplicate content rows
                checksum = None
                try:
                    h = hashlib.sha256()
                    with open(fpath, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            h.update(chunk)
                    checksum = h.hexdigest()
                except Exception:
                    checksum = None
                if not checksum:
                    continue
                # Skip if same content already indexed for this user
                try:
                    if (
                        checksum
                        and user_id in user_checksums
                        and checksum in user_checksums[user_id]
                    ):
                        continue
                except Exception:
                    pass
                try:
                    size = os.path.getsize(fpath)
                except Exception:
                    size = 0
                original_name = fname

                media = MediaFile(
                    filename=fname,
                    original_filename=original_name,
                    file_path=fpath,
                    file_size=size,
                    mime_type=mime,
                    media_type=MediaType.CLIP,
                    user_id=user_id,
                    project_id=project_id,
                    checksum=checksum,
                )
                db.session.add(media)
                if checksum:
                    user_checksums.setdefault(int(user_id), set()).add(checksum)
                # Never regenerate or modify files on disk during reindex
                created += 1

        # 3) Reindex compiled outputs
        if os.path.isdir(compilations_dir):
            # Map output_filename -> (user_id, project_id)
            proj_map = {
                (p.output_filename or ""): (p.user_id, p.id)
                for p in Project.query.all()
                if p.output_filename
            }
            for fname in os.listdir(compilations_dir):
                if fname.startswith(".") or fname.endswith(".meta.json"):
                    continue
                fpath = os.path.join(compilations_dir, fname)
                if not os.path.isfile(fpath) or fpath in known_paths:
                    continue
                owner = proj_map.get(fname)
                if not owner:
                    continue  # unknown compilation; skip to avoid FK issues
                user_id, project_id = owner
                mime = _detect_mime(fpath)
                # Compute checksum to prevent duplicate content rows
                checksum = None
                try:
                    h = hashlib.sha256()
                    with open(fpath, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            h.update(chunk)
                    checksum = h.hexdigest()
                except Exception:
                    checksum = None
                if not checksum:
                    continue
                # Skip if same content already indexed for this user
                try:
                    if (
                        checksum
                        and user_id in user_checksums
                        and checksum in user_checksums[user_id]
                    ):
                        continue
                except Exception:
                    pass
                try:
                    size = os.path.getsize(fpath)
                except Exception:
                    size = 0
                original_name = fname

                media = MediaFile(
                    filename=fname,
                    original_filename=original_name,
                    file_path=fpath,
                    file_size=size,
                    mime_type=mime,
                    media_type=MediaType.COMPILATION,
                    user_id=user_id,
                    project_id=project_id,
                    checksum=checksum,
                )
                db.session.add(media)
                if checksum:
                    user_checksums.setdefault(int(user_id), set()).add(checksum)
                # Never regenerate or modify files on disk during reindex
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
