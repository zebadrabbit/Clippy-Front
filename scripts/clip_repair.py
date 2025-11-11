#!/usr/bin/env python3
# ruff: noqa: E402,I001
"""
Diagnose and repair a Clip that references a missing MediaFile.

Usage:
  source venv/bin/activate
  python scripts/clip_repair.py diagnose <CLIP_ID>
  python scripts/clip_repair.py redownload <CLIP_ID>

Diagnose: prints JSON with clip, media linkage, resolved path and existence.
Redownload: clears media linkage and enqueues a new download task for the clip's source_url.
"""
import json
import os
import sys

from dotenv import load_dotenv

# Ensure repository root is on sys.path
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app import create_app
from app.main.routes import _rebase_instance_path
from app.models import Clip, MediaFile, Project, db


def _exists(path: str | None) -> bool:
    try:
        return (
            bool(path)
            and os.path.isabs(path)
            and os.path.exists(path)
            and os.path.isfile(path)
        )
    except Exception:
        return False


essential_fields = (
    "id",
    "project_id",
    "order_index",
    "source_platform",
    "source_url",
    "media_file_id",
    "is_downloaded",
    "duration",
)


def diagnose(app, clip_id: int):
    with app.app_context():
        clip = db.session.get(Clip, clip_id)
        if not clip:
            print(json.dumps({"clip_id": clip_id, "error": "clip not found"}))
            return 1
        proj = db.session.get(Project, clip.project_id) if clip.project_id else None
        media = (
            db.session.get(MediaFile, clip.media_file_id)
            if clip.media_file_id
            else None
        )
        db_path = media.file_path if media else None
        resolved = _rebase_instance_path(db_path) if db_path else None
        checked = (
            resolved if _exists(resolved) else (db_path if _exists(db_path) else None)
        )
        out = {
            "clip": {k: getattr(clip, k, None) for k in essential_fields},
            "project": {"id": proj.id, "name": proj.name} if proj else None,
            "media": (
                {
                    "id": media.id,
                    "filename": media.filename,
                    "original_filename": media.original_filename,
                    "mime": media.mime_type,
                    "db_path": db_path,
                    "resolved_path": resolved,
                    "exists": bool(checked),
                    "checked_path": checked,
                }
                if media
                else None
            ),
        }
        print(json.dumps(out, indent=2))
        return 0


def redownload(app, clip_id: int):
    with app.app_context():
        clip = db.session.get(Clip, clip_id)
        if not clip:
            print(json.dumps({"clip_id": clip_id, "error": "clip not found"}))
            return 1
        if not clip.source_url:
            print(json.dumps({"clip_id": clip_id, "error": "clip has no source_url"}))
            return 1
        # Detach any stale media link and mark as not downloaded
        clip.media_file_id = None
        try:
            clip.is_downloaded = False
        except Exception:
            pass
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        # Enqueue a fresh download
        try:
            from app.tasks.video_processing import download_clip_task

            # Choose a safe queue (gpu>cpu) to avoid local 'celery' workers performing downloads
            try:
                from app.tasks.celery_app import celery_app as _celery

                i = _celery.control.inspect(timeout=1.0)
                active_queues = set()
                if i:
                    aq = i.active_queues() or {}
                    for _worker, queues in aq.items():
                        for q in queues or []:
                            qname = q.get("name") if isinstance(q, dict) else None
                            if qname:
                                active_queues.add(qname)
                if "gpu" in active_queues:
                    qname = "gpu"
                elif "cpu" in active_queues:
                    qname = "cpu"
                else:
                    raise RuntimeError("no cpu/gpu workers available")
            except Exception as _qe:
                raise RuntimeError(f"queue selection failed: {_qe}") from _qe

            task = download_clip_task.apply_async(
                args=(clip.id, clip.source_url), queue=qname
            )
            print(
                json.dumps(
                    {"clip_id": clip.id, "status": "enqueued", "task_id": task.id}
                )
            )
            return 0
        except Exception as e:
            print(json.dumps({"clip_id": clip.id, "error": f"failed to enqueue: {e}"}))
            return 2


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"diagnose", "redownload"}:
        print(
            "Usage: python scripts/clip_repair.py [diagnose|redownload] <CLIP_ID>",
            file=sys.stderr,
        )
        sys.exit(2)
    action = sys.argv[1]
    try:
        clip_id = int(sys.argv[2])
    except Exception:
        print("CLIP_ID must be an integer", file=sys.stderr)
        sys.exit(2)

    try:
        load_dotenv()
    except Exception:
        pass
    app = create_app()
    if action == "diagnose":
        code = diagnose(app, clip_id)
        sys.exit(code)
    else:
        code = redownload(app, clip_id)
        sys.exit(code)


if __name__ == "__main__":
    main()
