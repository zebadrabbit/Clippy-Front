#!/usr/bin/env python3
# ruff: noqa: E402,I001
"""
Reindex media library from the filesystem into the database.

This script scans the new project-based data layout under DATA_FOLDER and creates
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
from app.models import MediaFile, MediaType, Project, User, db
from app import storage as storage_lib
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
        # Use project-based thumbnails directory
        try:
            owner = db.session.get(User, media.user_id)
        except Exception:
            owner = None
        thumbs_dir = storage_lib.thumbnails_dir(owner)
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
        data_root = storage_lib.data_root()
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

        # Optionally regenerate thumbnails for existing media missing them
        if regen_thumbs:
            for m in mf_all:
                _ensure_thumbnail(app, m)

        # Reindex user library and projects under data_root
        if not os.path.isdir(data_root):
            print(f"No data directory: {data_root}")
        else:
            # Build user lookup (username -> User)
            users = {str(u.id): u for u in User.query.all()}
            # Layout: <data_root>/<username>/...
            for uname in os.listdir(data_root):
                user_path = os.path.join(data_root, uname)
                if not os.path.isdir(user_path):
                    continue
                # Find matching user by username (fallback to any user if mismatch)
                user_obj = None
                for u in users.values():
                    if storage_lib.username_of(u) == uname:
                        user_obj = u
                        break
                if not user_obj:
                    continue
                uid = int(user_obj.id)
                # 1) Library
                lib_root = storage_lib.library_root(user_obj)
                for sub in ("intros", "outros", "transitions", "images", "clips"):
                    sub_dir = os.path.join(lib_root, sub)
                    if not os.path.isdir(sub_dir):
                        continue
                    mtype = _infer_type_from_subfolder(sub)
                    for fname in os.listdir(sub_dir):
                        if fname.startswith(".") or fname.endswith(".meta.json"):
                            continue
                        fpath = os.path.join(sub_dir, fname)
                        if not os.path.isfile(fpath) or fpath in known_paths:
                            continue
                        mime = _detect_mime(fpath)
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
                        try:
                            if (
                                checksum
                                and uid in user_checksums
                                and checksum in user_checksums[uid]
                            ):
                                continue
                        except Exception:
                            pass
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
                            user_id=uid,
                            project_id=None,
                            checksum=checksum,
                        )
                        db.session.add(media)
                        # Ensure thumbnail for newly indexed media (no-op for non-video)
                        _ensure_thumbnail(app, media)
                        if checksum:
                            user_checksums.setdefault(uid, set()).add(checksum)
                        created += 1
                # 2) Projects: scan per-project clips and compilations
                # Map of user projects by slug for quick path lookup
                projects = Project.query.filter_by(user_id=uid).all()
                for proj in projects:
                    root = storage_lib.project_root(user_obj, proj.name)
                    for sub, mtype in (
                        ("clips", MediaType.CLIP),
                        ("compilations", MediaType.COMPILATION),
                    ):
                        sub_dir = os.path.join(root, sub)
                        if not os.path.isdir(sub_dir):
                            continue
                        for fname in os.listdir(sub_dir):
                            if fname.startswith(".") or fname.endswith(".meta.json"):
                                continue
                            fpath = os.path.join(sub_dir, fname)
                            if not os.path.isfile(fpath) or fpath in known_paths:
                                continue
                            mime = _detect_mime(fpath)
                            checksum = None
                            try:
                                h = hashlib.sha256()
                                with open(fpath, "rb") as fh:
                                    for chunk in iter(
                                        lambda: fh.read(1024 * 1024), b""
                                    ):
                                        h.update(chunk)
                                checksum = h.hexdigest()
                            except Exception:
                                checksum = None
                            if not checksum:
                                continue
                            try:
                                if (
                                    checksum
                                    and uid in user_checksums
                                    and checksum in user_checksums[uid]
                                ):
                                    continue
                            except Exception:
                                pass
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
                                user_id=uid,
                                project_id=proj.id,
                                checksum=checksum,
                            )
                            db.session.add(media)
                            # Ensure thumbnail for newly indexed media (no-op for non-video)
                            _ensure_thumbnail(app, media)
                            if checksum:
                                user_checksums.setdefault(uid, set()).add(checksum)
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
