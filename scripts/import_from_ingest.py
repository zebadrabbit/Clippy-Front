#!/usr/bin/env python3
"""
Import compiled artifacts from an ingest directory into a project's compilations
folder, then reindex so they appear in the UI.

Typical use:
    source venv/bin/activate
    python scripts/import_from_ingest.py \
        --username admin \
        --project "Highlights Oct-2025" \
        --ingest-root /srv/ingest \
        --worker-id gpu-worker-01 \
        --action copy --pattern "*.mp4" --regen-thumbnails

Actions:
  - copy (default): copy matched files
  - move: move matched files (removes originals from ingest)
  - link: create symlinks in the destination pointing to the ingest files

Notes:
  - Sentinel files (., .READY, .DONE, .PUSHING, .PUSHED) are always ignored.
  - Destination is resolved via app.storage.compilations_dir(user, project_name).
  - Reindex is performed at the end to add DB rows and generate thumbnails.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure repo root on sys.path so `import app` works when run directly
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SENTINELS = {".READY", ".DONE", ".PUSHING", ".PUSHED"}


def _is_sentinel(p: Path) -> bool:
    name = p.name
    if name in SENTINELS:
        return True
    # ignore hidden top-level sentinels too
    if name.startswith(".") and name.upper().strip() in SENTINELS:
        return True
    return False


def _iter_artifact_files(root: Path, pattern: str) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for artifact_dir in sorted([d for d in root.iterdir() if d.is_dir()]):
        for path in artifact_dir.rglob("*"):
            if (
                path.is_file()
                and fnmatch.fnmatch(path.name, pattern)
                and not _is_sentinel(path)
            ):
                files.append(path)
    return files


def main() -> int:
    load_dotenv()

    ap = argparse.ArgumentParser(description="Import compiled artifacts into a project")
    ap.add_argument("--username", required=True, help="Owner username")
    ap.add_argument(
        "--project",
        required=True,
        help="Target project name (will be created with this name if --create-project)",
    )
    ap.add_argument(
        "--ingest-root",
        default="/srv/ingest",
        help="Ingest root path (default: /srv/ingest)",
    )
    ap.add_argument(
        "--worker-id",
        default=None,
        help="Specific worker subdir under ingest-root to import from (default: all subdirs)",
    )
    ap.add_argument(
        "--action",
        choices=["copy", "move", "link"],
        default="copy",
        help="How to import files (default: copy)",
    )
    ap.add_argument(
        "--pattern",
        default="*.mp4",
        help="Glob pattern for files to import (default: *.mp4)",
    )
    ap.add_argument(
        "--create-project",
        action="store_true",
        help="Create the project if it doesn't exist",
    )
    ap.add_argument(
        "--regen-thumbnails",
        action="store_true",
        help="Regenerate thumbnails during reindex",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without making changes",
    )
    args = ap.parse_args()

    # Defer heavy imports until we have args and env loaded
    from app import create_app
    from app import storage as storage_lib
    from app.models import Project, User, db
    from scripts.reindex_media import reindex as reindex_media

    app = create_app()

    ingest_root = Path(args.ingest_root).resolve()
    if not ingest_root.is_dir():
        print(f"Ingest root not found: {ingest_root}")
        return 1

    with app.app_context():
        # Resolve user
        user = User.query.filter_by(username=args.username).first()
        if not user:
            print(f"User not found: {args.username}")
            return 2

        # Resolve or create project
        project = Project.query.filter_by(user_id=user.id, name=args.project).first()
        if not project:
            if not args.create_project:
                print(
                    f"Project not found for user '{args.username}': '{args.project}'. Use --create-project to create it."
                )
                return 3
            project = Project(user_id=user.id, name=args.project)
            db.session.add(project)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Failed to create project: {e}")
                return 4

        # Destination compilations directory
        dest_dir = Path(storage_lib.compilations_dir(user, project.name))
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Build source root(s)
        worker_roots: list[Path] = []
        if args.worker_id:
            worker_roots = [ingest_root / args.worker_id]
        else:
            # all immediate subdirs under ingest_root
            worker_roots = [p for p in ingest_root.iterdir() if p.is_dir()]

        # Collect files to import
        candidates: list[Path] = []
        for wr in worker_roots:
            candidates.extend(_iter_artifact_files(wr, args.pattern))
        if not candidates:
            print("No matching files found to import.")
            return 0

        print(f"Found {len(candidates)} file(s) to {args.action} into {dest_dir}")
        # Import files
        imported = 0
        for src in candidates:
            dst = dest_dir / src.name
            if dst.exists():
                # Skip duplicates by name; a smarter variant could add a suffix
                continue
            if args.dry_run:
                print(f"DRY-RUN: {args.action} {src} -> {dst}")
                imported += 1
                continue
            try:
                if args.action == "copy":
                    shutil.copy2(str(src), str(dst))
                elif args.action == "move":
                    shutil.move(str(src), str(dst))
                elif args.action == "link":
                    os.symlink(src, dst)
                imported += 1
            except Exception as e:
                print(f"Failed to {args.action} {src} -> {dst}: {e}")

        # Reindex
        if args.dry_run:
            print(
                f"DRY-RUN: would reindex media (regen_thumbnails={args.regen_thumbnails})"
            )
            return 0
        created = int(reindex_media(regen_thumbs=args.regen_thumbnails, app=app) or 0)
        print(f"Imported {imported} file(s); reindexed {created} new file(s).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
