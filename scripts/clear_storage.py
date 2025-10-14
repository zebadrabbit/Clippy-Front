#!/usr/bin/env python3
"""
Safely clear downloaded and uploaded media data for ClippyFront.

This script removes the contents of the following directories (if present):
- <instance>/<UPLOAD_FOLDER> (uploads root; contains per-user folders)
- <instance>/downloads (downloaded clips)
- <instance>/compilations (final renders)

Granular options for uploads (per-user subfolders):
- intros, outros, transitions, thumbnails

By default, the script only runs when --confirm is provided.
Use --dry-run to see what would be deleted without changing anything.
Target subsets with flags like --uploads/--downloads/--compilations and/or
granular upload flags like --intros/--outros/--transitions/--thumbnails.

Examples:
    Dry-run everything:
        python scripts/clear_storage.py --dry-run

    Actually delete all:
        python scripts/clear_storage.py --confirm

    Only clear downloads and compilations:
        python scripts/clear_storage.py --confirm --downloads --compilations

    Only clear upload thumbnails across all users:
        python scripts/clear_storage.py --confirm --thumbnails

    Clear intros and transitions, but keep others:
        python scripts/clear_storage.py --confirm --intros --transitions
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Iterable

from dotenv import load_dotenv

# Ensure repository root is on sys.path so `import app` works when running directly
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _purge_dir(path: str, dry_run: bool = False) -> tuple[int, int]:
    """Remove all files and subdirectories inside a directory, not the directory itself.

    Returns (files_deleted, dirs_deleted). If dry_run is True, nothing is removed.
    """
    files_deleted = 0
    dirs_deleted = 0

    if not os.path.exists(path):
        print(f"[skip] {path} does not exist")
        return (0, 0)

    if not os.path.isdir(path):
        print(f"[warn] {path} exists but is not a directory; skipping")
        return (0, 0)

    try:
        entries = list(os.scandir(path))
    except PermissionError:
        print(f"[error] Permission denied reading {path}")
        return (0, 0)

    if not entries:
        print(f"[ok] {path} is already empty")
        return (0, 0)

    print(f"[info] Purging contents of {path} ({len(entries)} top-level entries)")

    for entry in entries:
        p = entry.path
        try:
            if entry.is_dir(follow_symlinks=False):
                if dry_run:
                    print(f"  [dir]  would remove {p}")
                else:
                    shutil.rmtree(p, ignore_errors=False)
                    print(f"  [dir]  removed {p}")
                dirs_deleted += 1
            else:
                if dry_run:
                    print(f"  [file] would remove {p}")
                else:
                    os.remove(p)
                    print(f"  [file] removed {p}")
                files_deleted += 1
        except Exception as e:
            print(f"  [error] Failed to remove {p}: {e}")

    return (files_deleted, dirs_deleted)


def _resolve_targets(app) -> Iterable[tuple[str, str]]:
    """Yield (label, absolute_path) tuples for directories we can purge."""
    instance_path = app.instance_path
    upload_folder = app.config.get("UPLOAD_FOLDER", "uploads")

    upload_dir = os.path.join(instance_path, upload_folder)
    downloads_dir = os.path.join(instance_path, "downloads")
    compilations_dir = os.path.join(instance_path, "compilations")

    return (
        ("uploads", os.path.abspath(upload_dir)),
        ("downloads", os.path.abspath(downloads_dir)),
        ("compilations", os.path.abspath(compilations_dir)),
    )


def _load_app():
    # Load environment variables from .env, if present
    load_dotenv()
    # Import and create the Flask app to access instance_path and config
    try:
        from app import create_app
    except Exception as e:
        print(f"[error] Failed to import app factory: {e}")
        sys.exit(2)

    try:
        app = create_app()
    except Exception as e:
        print(f"[error] Failed to create app: {e}")
        sys.exit(2)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clear uploaded and downloaded data")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually perform deletion. Without this, the script exits unless --dry-run is specified.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without changing anything.",
    )
    parser.add_argument(
        "--uploads",
        action="store_true",
        help="Only clear uploads (including thumbnails).",
    )
    parser.add_argument(
        "--downloads",
        action="store_true",
        help="Only clear downloads.",
    )
    parser.add_argument(
        "--compilations",
        action="store_true",
        help="Only clear compilations (final renders).",
    )
    # Granular upload subfolders
    parser.add_argument(
        "--intros",
        action="store_true",
        help="Clear only upload 'intros' subfolders (per-user).",
    )
    parser.add_argument(
        "--outros",
        action="store_true",
        help="Clear only upload 'outros' subfolders (per-user).",
    )
    parser.add_argument(
        "--transitions",
        action="store_true",
        help="Clear only upload 'transitions' subfolders (per-user).",
    )
    parser.add_argument(
        "--thumbnails",
        action="store_true",
        help="Clear only upload 'thumbnails' subfolders (per-user).",
    )

    args = parser.parse_args(argv)

    # Allow dry-run without confirm; require confirm for actual deletion
    if not args.dry_run and not args.confirm:
        print("[safe] Refusing to delete without --confirm. Use --dry-run to preview.")
        return 1

    app = _load_app()

    selected = {
        "uploads": args.uploads,
        "downloads": args.downloads,
        "compilations": args.compilations,
        # granular
        "intros": args.intros,
        "outros": args.outros,
        "transitions": args.transitions,
        "thumbnails": args.thumbnails,
    }
    limit_to_subset = any(selected.values())

    targets: list[tuple[str, str]] = []
    # Top-level targets
    base_targets = list(_resolve_targets(app))
    # If no subset flags, include all three top-level dirs
    if not limit_to_subset:
        targets.extend(base_targets)
    else:
        # Add chosen top-levels
        for label, path in base_targets:
            if selected.get(label, False):
                targets.append((label, path))

    # Add granular upload subfolders if requested
    granular_keys = [
        k
        for k in ("intros", "outros", "transitions", "thumbnails")
        if selected.get(k, False)
    ]
    if granular_keys:
        # Resolve upload base dir
        upload_dir = None
        try:
            upload_dir = os.path.join(
                app.instance_path, app.config.get("UPLOAD_FOLDER", "uploads")
            )
        except Exception:
            upload_dir = None

        if upload_dir and os.path.isdir(upload_dir):
            try:
                # Per-user dirs under uploads
                for entry in os.scandir(upload_dir):
                    if not entry.is_dir():
                        continue
                    user_dir = entry.path
                    for sub in granular_keys:
                        p = os.path.join(user_dir, sub)
                        if os.path.isdir(p):
                            targets.append((f"{sub} ({os.path.basename(user_dir)})", p))
            except Exception as e:
                print(f"[warn] Failed to enumerate upload subfolders: {e}")
        else:
            print(
                "[warn] Uploads directory not found; skipping granular upload targets"
            )

    # Safety: warn if any target resolves outside the instance directory
    inst_abs = os.path.abspath(app.instance_path)
    for label, path in targets:
        # Normalize to avoid false negatives on symlinks
        try:
            real_inst = os.path.realpath(inst_abs)
            real_target = os.path.realpath(path)
        except Exception:
            real_inst = inst_abs
            real_target = path
        if not real_target.startswith(real_inst):
            print(f"[warn] {label} directory is outside instance path: {real_target}")
            print("       Proceed only if you are sure this is intentional.")

    total_files = 0
    total_dirs = 0

    for label, path in targets:
        if limit_to_subset:
            # Only filter by selection for top-level labels; granular targets were
            # added explicitly based on their own flags and should not be skipped.
            if label in ("uploads", "downloads", "compilations") and not selected.get(
                label, False
            ):
                continue
        print(f"\n=== {label.upper()} ===")
        f, d = _purge_dir(path, dry_run=args.dry_run)
        total_files += f
        total_dirs += d

    action = "would be deleted" if args.dry_run else "deleted"
    print(f"\nSummary: {total_files} files and {total_dirs} directories {action}.")

    if args.dry_run and not args.confirm:
        print("[note] This was a dry run. Re-run with --confirm to actually delete.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
