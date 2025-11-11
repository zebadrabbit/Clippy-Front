#!/usr/bin/env python3
"""
Import raw clip artifacts from an ingest directory into the appropriate
project clips folder, then reindex so they appear in the UI.

Raw clip artifacts are directories created by workers containing:
  - the original clip file
  - optional thumbnail.jpg
  - manifest.json with metadata { type: "raw_clip", clip_id, project_id, user_id, filename, ... }

Typical use:
    source venv/bin/activate
    python scripts/ingest_raw_clips.py \
        --ingest-root /srv/ingest \
        --worker-id gpu-worker-01 \
        --action move --regen-thumbnails

Actions:
  - copy (default): copy matched files
  - move: move matched files (removes originals from ingest)
  - link: create symlinks in the destination pointing to the ingest files

Notes:
  - Sentinel files (.READY, .DONE, .PUSHING, .PUSHED) are ignored; they may not be present remotely.
  - Destination is the project's clips dir resolved via app.storage for the owner/project.
  - Reindex is performed at the end to add DB rows and generate thumbnails if requested.
  - After successful import of a directory, a marker file `.IMPORTED` is written to that directory to avoid reprocessing.
"""
from __future__ import annotations

import argparse
import json
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

SENTINELS = {".READY", ".DONE", ".PUSHING", ".PUSHED", ".IMPORTED"}


def _load_manifest(dir_path: Path) -> dict | None:
    mf = dir_path / "manifest.json"
    if not mf.is_file():
        return None
    try:
        return json.loads(mf.read_text())
    except Exception:
        return None


def _find_clip_file(dir_path: Path, filename_hint: str | None) -> Path | None:
    # Prefer the hinted filename from manifest
    if filename_hint:
        p = dir_path / filename_hint
        if p.is_file():
            return p
    # Fallback: pick the largest non-sentinel file that looks like video
    candidates: list[Path] = []
    for p in dir_path.iterdir():
        if p.is_file() and p.name not in SENTINELS and not p.name.endswith(".json"):
            candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.stat().st_size if x.exists() else 0, reverse=True)
    return candidates[0]


def _parse_clip_id_from_dirname(dir_name: str) -> int | None:
    # Expect names like: clip_<id>_<slug>_<UTC>
    try:
        if not dir_name.startswith("clip_"):
            return None
        parts = dir_name.split("_", 2)
        # parts[0] = 'clip', parts[1] = '<id>'
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    except Exception:
        return None
    return None


def main() -> int:
    load_dotenv()

    ap = argparse.ArgumentParser(
        description="Import raw clip artifacts into project clips"
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
        "--username",
        default=None,
        help="Force destination owner username; overrides manifest/lookup when provided",
    )
    ap.add_argument(
        "--project",
        default=None,
        help="Force destination project name; overrides manifest/lookup when provided",
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

    from app import create_app
    from app import storage as storage_lib
    from app.models import Project, User, db
    from scripts.reindex_media import reindex as reindex_media

    app = create_app()

    ingest_root = Path(args.ingest_root).resolve()
    if not ingest_root.is_dir():
        print(f"Ingest root not found: {ingest_root}")
        return 1

    # Build source roots
    worker_roots: list[Path]
    if args.worker_id:
        worker_roots = [ingest_root / args.worker_id]
    else:
        worker_roots = [p for p in ingest_root.iterdir() if p.is_dir()]

    # Collect candidate artifact dirs (prefer those with valid manifest; fallback to id parsing)
    artifact_dirs: list[Path] = []
    for wr in worker_roots:
        for d in sorted([p for p in wr.iterdir() if p.is_dir()]):
            if (d / ".IMPORTED").exists():
                continue
            mf = _load_manifest(d)
            if mf and (mf.get("type") or "").lower() == "raw_clip":
                artifact_dirs.append(d)
                continue
            # If manifest missing/invalid, still add as candidate; we'll try to parse clip id
            artifact_dirs.append(d)

    if not artifact_dirs:
        print("No raw clip artifacts found to import.")
        return 0

    print(f"Found {len(artifact_dirs)} raw clip artifact(s) to process")

    with app.app_context():
        # If a destination override is provided, resolve it once
        forced_owner = None
        forced_proj = None
        if args.username and args.project:
            forced_owner = User.query.filter_by(username=args.username).first()
            if not forced_owner:
                print(f"Destination user not found: {args.username}")
                return 2
            forced_proj = Project.query.filter_by(
                user_id=forced_owner.id, name=args.project
            ).first()
            if not forced_proj:
                # auto-create for convenience
                forced_proj = Project(user_id=forced_owner.id, name=args.project)
                try:
                    db.session.add(forced_proj)
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"Failed to create destination project '{args.project}': {e}")
                    return 3
        imported = 0
        for d in artifact_dirs:
            mf = _load_manifest(d) or {}
            uid = int(mf.get("user_id") or 0)
            pid = int(mf.get("project_id") or 0)
            filename = (mf.get("filename") or "").strip() or None

            owner = forced_owner
            proj = forced_proj
            # Try manifest mapping first
            if not (owner and proj) and uid and pid:
                owner = db.session.get(User, uid)
                proj = db.session.get(Project, pid)
                if not owner or not proj or int(getattr(proj, "user_id", 0)) != uid:
                    owner, proj = None, None
            # Fallback: parse clip id from directory name and resolve project via Clip
            if not (owner and proj):
                try:
                    from app.models import Clip

                    cid = _parse_clip_id_from_dirname(d.name)
                    if cid:
                        clip = db.session.get(Clip, int(cid))
                        if clip:
                            proj = (
                                db.session.get(Project, int(clip.project_id))
                                if clip.project_id
                                else None
                            )
                            owner = (
                                db.session.get(User, int(proj.user_id))
                                if proj
                                else None
                            )
                except Exception:
                    owner, proj = None, None

            if not (owner and proj):
                print(
                    f"Skipping {d.name}: could not resolve owner/project (no manifest or lookup failed)"
                )
                continue

            src = _find_clip_file(d, filename)
            if not src:
                print(f"Skipping {d.name}: clip file not found")
                continue

            clips_dir = Path(storage_lib.clips_dir(owner, proj.name))
            try:
                clips_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            dst = clips_dir / src.name
            if dst.exists():
                # Avoid duplicate import by name
                print(f"Already exists, skipping: {dst}")
                try:
                    (d / ".IMPORTED").write_text("exists\n")
                except PermissionError:
                    print(
                        f"Note: could not write .IMPORTED in {d} (permission denied); continuing"
                    )
                except Exception as e:
                    print(f"Note: could not write .IMPORTED in {d}: {e}")
                continue

            if args.dry_run:
                print(f"DRY-RUN: {args.action} {src} -> {dst}")
                imported += 1
            else:
                try:
                    if args.action == "copy":
                        shutil.copy2(str(src), str(dst))
                    elif args.action == "move":
                        shutil.move(str(src), str(dst))
                    elif args.action == "link":
                        os.symlink(src, dst)
                    # Mark directory as imported (best-effort)
                    try:
                        (d / ".IMPORTED").write_text("ok\n")
                    except PermissionError:
                        # Read-only ingest root (e.g., owned by different user); skip marker
                        print(
                            f"Note: could not write .IMPORTED in {d} (permission denied); continuing"
                        )
                    except Exception as e:
                        print(f"Note: could not write .IMPORTED in {d}: {e}")
                    imported += 1
                except Exception as e:
                    print(f"Failed to {args.action} {src} -> {dst}: {e}")

        # Reindex to add DB rows and thumbnails (if requested)
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
