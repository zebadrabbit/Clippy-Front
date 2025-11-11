#!/usr/bin/env python
# ruff: noqa: E402,I001
"""
Quick diagnostic script to resolve a MediaFile path as the web app would and report existence.

Usage:
  source venv/bin/activate
  python scripts/check_media_path.py <MEDIA_ID>

Respects environment variables such as:
  - CLIPPY_INSTANCE_PATH
  - MEDIA_PATH_ALIAS_FROM
  - MEDIA_PATH_ALIAS_TO

Outputs JSON with:
  - media_id
  - db_path: original path stored in the database
  - resolved_path: path after rebasing/aliasing
  - exists: whether the file exists on disk
  - instance_path: Flask instance path
"""
import json
import os
import sys

from dotenv import load_dotenv

# Ensure repository root is on sys.path so `import app` works when running directly
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app import create_app
from app.main.routes import _rebase_instance_path
from app.models import MediaFile, db


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_media_path.py <MEDIA_ID>", file=sys.stderr)
        sys.exit(2)

    media_id = int(sys.argv[1])
    # Load environment variables from .env if present
    try:
        load_dotenv()
    except Exception:
        pass
    app = create_app()

    with app.app_context():
        media = db.session.get(MediaFile, media_id)
        if not media:
            print(json.dumps({"media_id": media_id, "error": "not found in DB"}))
            return

        db_path = media.file_path
        resolved = _rebase_instance_path(db_path)
        path = None
        if resolved and os.path.isabs(resolved) and os.path.exists(resolved):
            path = resolved
        elif db_path and os.path.isabs(db_path) and os.path.exists(db_path):
            path = db_path

        out = {
            "media_id": media_id,
            "db_path": db_path,
            "resolved_path": resolved,
            "exists": bool(path),
            "checked_path": path,
            "instance_path": getattr(app, "instance_path", None),
            "env": {
                "CLIPPY_INSTANCE_PATH": os.getenv("CLIPPY_INSTANCE_PATH"),
                "MEDIA_PATH_ALIAS_FROM": os.getenv("MEDIA_PATH_ALIAS_FROM"),
                "MEDIA_PATH_ALIAS_TO": os.getenv("MEDIA_PATH_ALIAS_TO"),
            },
        }
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
