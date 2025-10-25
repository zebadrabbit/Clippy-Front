#!/usr/bin/env python
"""
Cleanup cached creator avatar images under instance/assets/avatars/.

Keeps the most recent N files per author (default: 5), deleting older ones.
Author key is inferred from filenames like '<safe>_<token>.ext' where token is
an 8-hex suffix (secrets.token_hex(4)). Files not matching this pattern are
kept unless --include-legacy is set, in which case they're grouped by stem.

Usage:
  python scripts/cleanup_avatars.py [--keep 5] [--dry-run] [--include-legacy]
  # Optionally target a specific directory
  python scripts/cleanup_avatars.py --path /mnt/clippy/assets/avatars --keep 5
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict


def _default_avatars_path() -> str:
    try:
        # Use app.instance_path if available to respect mount/alias policies
        from app import create_app

        app = create_app()
        return os.path.join(app.instance_path, "assets", "avatars")
    except Exception:
        # Fallback to repo-relative instance path
        here = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.abspath(os.path.join(here, os.pardir))
        return os.path.join(repo_root, "instance", "assets", "avatars")


def find_avatar_files(path: str) -> list[str]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    files: list[str] = []
    try:
        for entry in os.listdir(path):
            p = os.path.join(path, entry)
            if os.path.isfile(p) and os.path.splitext(entry)[1].lower() in exts:
                files.append(p)
    except FileNotFoundError:
        pass
    return files


def group_by_author(
    files: list[str], include_legacy: bool = False
) -> dict[str, list[tuple[str, float]]]:
    # Pattern for '<safe>_<8hex>' suffix
    pat = re.compile(r"^(?P<safe>.+)_(?P<tok>[0-9a-f]{8})$")
    groups: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for f in files:
        stem, _ext = os.path.splitext(os.path.basename(f))
        m = pat.match(stem)
        key = None
        if m:
            key = m.group("safe")
        elif include_legacy:
            # Group legacy by entire stem
            key = stem
        if key is None:
            continue
        try:
            mtime = os.path.getmtime(f)
        except Exception:
            mtime = 0.0
        groups[key].append((f, mtime))
    return groups


def prune(
    groups: dict[str, list[tuple[str, float]]], keep: int, dry_run: bool
) -> tuple[int, int]:
    deleted = 0
    kept = 0
    for _author, items in groups.items():
        items_sorted = sorted(items, key=lambda t: t[1], reverse=True)
        to_keep = items_sorted[:keep]
        to_delete = items_sorted[keep:]
        kept += len(to_keep)
        for f, _ in to_delete:
            if dry_run:
                print(f"[DRY] Would delete: {f}")
                continue
            try:
                os.remove(f)
                print(f"Deleted: {f}")
                deleted += 1
            except Exception as e:
                print(f"Failed to delete {f}: {e}")
    return kept, deleted


def main() -> int:
    ap = argparse.ArgumentParser(description="Prune cached creator avatars")
    ap.add_argument(
        "--path", help="Avatars directory (defaults to instance/assets/avatars)"
    )
    ap.add_argument(
        "--keep", type=int, default=5, help="Number of recent files to keep per author"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="List files without deleting"
    )
    ap.add_argument(
        "--include-legacy",
        action="store_true",
        help="Group unmatched filenames by stem and prune them too",
    )
    args = ap.parse_args()

    target = args.path or _default_avatars_path()
    print(f"Scanning: {target}")
    files = find_avatar_files(target)
    print(f"Found {len(files)} avatar file(s)")
    groups = group_by_author(files, include_legacy=args.include_legacy)
    total_groups = len(groups)
    total_items = sum(len(v) for v in groups.values())
    print(f"Grouped {total_items} files across {total_groups} author bucket(s)")
    kept, deleted = prune(
        groups, keep=max(0, int(args.keep)), dry_run=bool(args.dry_run)
    )
    print(f"Kept: {kept}  Deleted: {deleted}  Dry-run: {bool(args.dry_run)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
