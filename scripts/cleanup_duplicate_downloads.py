#!/usr/bin/env python3
# ruff: noqa: E402,I001
"""
Clean up duplicate downloaded media files by checksum (per user).

This script scans MediaFile rows grouped by checksum within each user and:
  - Reports duplicates and potential space savings (default dry-run)
  - With --apply: rewrites Clip.media_file_id to the canonical MediaFile,
    removes duplicate MediaFile rows, and deletes duplicate files from disk.

It also optionally scans instance/downloads/ for orphaned files (not referenced by
any MediaFile) and reports or deletes them when --include-orphans is provided.

Usage:
    source venv/bin/activate
    python scripts/cleanup_duplicate_downloads.py [--user <id>] [--apply] [--include-orphans]

Notes:
  - Canonical pick strategy: keep the oldest uploaded MediaFile that still exists on disk;
    fall back to the first in the group if timestamps are equal/missing.
  - Scope: dedupe is performed per-user. Content shared across different users is not merged.
  - Safety: default is dry-run/report; no DB/file mutations unless --apply is passed.
"""
import argparse
import os
import sys
import hashlib

# Ensure repository root is on sys.path so `import app` works when running directly
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from dotenv import load_dotenv  # type: ignore
from app.models import db, MediaFile, Clip


def _compute_checksum(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _pick_canonical(group: list[MediaFile]) -> MediaFile:
    # Prefer existing-on-disk; among those, the oldest uploaded_at (or smallest id)
    existing = [m for m in group if m.file_path and os.path.exists(m.file_path)]
    if not existing:
        existing = group[:]
    existing.sort(key=lambda m: (m.uploaded_at or 0, m.id or 0))
    return existing[0]


def _bytes_fmt(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def cleanup(
    user_id: int | None, apply: bool, include_orphans: bool, app=None
) -> tuple[int, int]:
    """
    Perform duplicate cleanup.

    Returns:
        (duplicates_removed, bytes_reclaimed)
    """
    try:
        load_dotenv()
    except Exception:
        pass

    if app is None:
        from app import create_app  # type: ignore

        app = create_app()

    removed = 0
    reclaimed = 0

    with app.app_context():
        # 1) Ensure checksums are populated where possible
        q = MediaFile.query
        if user_id is not None:
            q = q.filter(MediaFile.user_id == user_id)
        media_rows: list[MediaFile] = q.all()

        # Compute missing checksums for files that exist
        for m in media_rows:
            if not m.checksum and m.file_path and os.path.exists(m.file_path):
                cs = _compute_checksum(m.file_path)
                if cs:
                    m.checksum = cs
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        # 2) Group by (user_id, checksum)
        groups: dict[tuple[int, str], list[MediaFile]] = {}
        for m in media_rows:
            if not m.user_id or not m.checksum:
                continue
            key = (int(m.user_id), m.checksum)
            groups.setdefault(key, []).append(m)

        # 3) Handle duplicate groups
        for (uid, csum), group in groups.items():
            if len(group) <= 1:
                continue
            canonical = _pick_canonical(group)
            dups = [m for m in group if m.id != canonical.id]

            # Compute reclaimable bytes from files that exist on disk
            group_bytes = 0
            for d in dups:
                try:
                    if d.file_path and os.path.exists(d.file_path):
                        group_bytes += os.path.getsize(d.file_path)
                except Exception:
                    pass

            print(
                f"User {uid}: checksum {csum[:12]}... has {len(group)} entries -> keep #{canonical.id}, remove {len(dups)} (reclaim ~{_bytes_fmt(group_bytes)})"
            )

            if not apply:
                continue

            # Repoint Clip references to canonical
            try:
                for d in dups:
                    # Update any Clip rows referencing the duplicate media_file_id
                    clips = Clip.query.filter(Clip.media_file_id == d.id).all()
                    for c in clips:
                        c.media_file_id = canonical.id
                db.session.commit()
            except Exception as e:
                print(f"  ! Failed updating clips for checksum {csum[:12]}...: {e}")
                db.session.rollback()
                continue

            # Delete duplicate files and DB rows
            for d in dups:
                try:
                    # Delete file from disk if exists and not same as canonical
                    if d.file_path and os.path.exists(d.file_path):
                        # Extra safety: don't delete the canonical path
                        if d.file_path != canonical.file_path:
                            try:
                                os.remove(d.file_path)
                                reclaimed += d.file_size or 0
                            except Exception as fe:
                                print(f"  ! Failed to delete file {d.file_path}: {fe}")
                    # Remove DB row
                    db.session.delete(d)
                    removed += 1
                except Exception as de:
                    print(f"  ! Failed while deleting duplicate id={d.id}: {de}")
            try:
                db.session.commit()
            except Exception as e:
                print(f"  ! Commit failed while finalizing group {csum[:12]}...: {e}")
                db.session.rollback()

        # 4) Optionally handle orphan files in instance/downloads
        if include_orphans:
            downloads_dir = os.path.join(app.instance_path, "downloads")
            if os.path.isdir(downloads_dir):
                # Build a set of known file paths from DB
                known_paths = {
                    m.file_path for m in MediaFile.query.all() if m.file_path
                }
                for fname in os.listdir(downloads_dir):
                    if fname.startswith(".") or fname.endswith(".meta.json"):
                        continue
                    fpath = os.path.join(downloads_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    if fpath in known_paths:
                        continue
                    try:
                        size = os.path.getsize(fpath)
                    except Exception:
                        size = 0
                    print(f"Orphan file: {fpath} ({_bytes_fmt(size)})")
                    if apply:
                        try:
                            os.remove(fpath)
                            reclaimed += size
                        except Exception as e:
                            print(f"  ! Failed to delete orphan {fpath}: {e}")

    return removed, reclaimed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cleanup duplicate downloaded media by checksum (per user)"
    )
    parser.add_argument(
        "--user", type=int, help="Only process this user id", default=None
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply changes (otherwise dry-run/report)"
    )
    parser.add_argument(
        "--include-orphans",
        action="store_true",
        help="Also scan instance/downloads for orphaned files and remove them (with --apply)",
    )
    args = parser.parse_args()

    removed, reclaimed = cleanup(
        user_id=args.user, apply=args.apply, include_orphans=args.include_orphans
    )
    if args.apply:
        print(f"Removed {removed} duplicate rows; reclaimed ~{_bytes_fmt(reclaimed)}")
    else:
        print("Dry run complete. Use --apply to perform cleanup.")
