#!/usr/bin/env python3
"""Deduplicate avatar files by keeping only the most recent one per creator.

This script identifies duplicate avatars (same creator name with different
random suffixes) and keeps only the most recent file, removing older duplicates.
"""

import argparse
import glob
import os
import re
import sys
from collections import defaultdict
from datetime import datetime


def parse_args():
    parser = argparse.ArgumentParser(
        description="Deduplicate creator avatars in instance/assets/avatars"
    )
    parser.add_argument(
        "--avatars-dir",
        default="instance/assets/avatars",
        help="Path to avatars directory (default: instance/assets/avatars)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed information about each file",
    )
    return parser.parse_args()


def group_avatar_files(avatars_dir):
    """Group avatar files by creator name.

    Returns:
        dict: {creator_name: [(filepath, mtime, has_suffix), ...]}
    """
    grouped = defaultdict(list)

    # Pattern: creator_name.ext or creator_name_HEXSUFFIX.ext
    pattern = re.compile(r"^([a-z0-9_-]+?)(?:_([0-9a-f]{8}))?(\.[a-z]+)$")

    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for filepath in glob.glob(os.path.join(avatars_dir, ext)):
            filename = os.path.basename(filepath)
            match = pattern.match(filename.lower())

            if match:
                creator_name = match.group(1)
                suffix = match.group(2)  # None if no suffix
                mtime = os.path.getmtime(filepath)

                grouped[creator_name].append(
                    (filepath, mtime, suffix is not None, filename)
                )

    return grouped


def deduplicate_avatars(avatars_dir, dry_run=False, verbose=False):
    """Remove duplicate avatar files, keeping the most recent one per creator."""

    if not os.path.isdir(avatars_dir):
        print(f"Error: Directory not found: {avatars_dir}", file=sys.stderr)
        return 1

    grouped = group_avatar_files(avatars_dir)

    total_duplicates = 0
    total_size_saved = 0

    for creator_name, files in sorted(grouped.items()):
        if len(files) <= 1:
            if verbose:
                print(f"✓ {creator_name}: single file, no duplicates")
            continue

        # Sort by modification time (most recent first)
        files.sort(key=lambda x: x[1], reverse=True)

        # Keep the first file (most recent)
        keep_file = files[0]
        duplicates = files[1:]

        print(f"\n{creator_name}: {len(files)} files found")
        if verbose:
            keep_time = datetime.fromtimestamp(keep_file[1]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            print(f"  ✓ Keeping: {keep_file[3]} (modified: {keep_time})")

        for filepath, mtime, _has_suffix, filename in duplicates:
            file_size = os.path.getsize(filepath)
            total_duplicates += 1
            total_size_saved += file_size

            action = "Would delete" if dry_run else "Deleting"
            size_kb = file_size / 1024
            dup_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

            print(f"  ✗ {action}: {filename} ({size_kb:.1f} KB, modified: {dup_time})")

            if not dry_run:
                try:
                    os.remove(filepath)
                except Exception as e:
                    print(f"    Error removing {filepath}: {e}", file=sys.stderr)

    print(f"\n{'=' * 60}")
    print(f"Total duplicate files: {total_duplicates}")
    print(
        f"Total space {'that would be' if dry_run else ''} saved: {total_size_saved / 1024:.1f} KB"
    )

    if dry_run and total_duplicates > 0:
        print("\nRun without --dry-run to actually delete the duplicate files.")

    return 0


def main():
    args = parse_args()
    return deduplicate_avatars(args.avatars_dir, args.dry_run, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
