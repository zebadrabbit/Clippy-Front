"""
Media maintenance tasks: reindex DB from filesystem and regenerate thumbnails.
"""
import os
import subprocess
from datetime import datetime

from sqlalchemy.orm import scoped_session, sessionmaker

from app.models import MediaFile, db
from app.tasks.celery_app import celery_app


def _get_db_session():
    from app import create_app

    app = create_app()
    with app.app_context():
        Session = scoped_session(sessionmaker(bind=db.engine))
        return Session(), app


def _resolve_binary(app, name: str) -> str:
    from app.tasks.video_processing import resolve_binary as _rb

    return _rb(app, name)


@celery_app.task(bind=True)
def reindex_media_task(self, regen_thumbnails: bool = False) -> dict:
    """Scan instance/uploads and backfill MediaFile rows. Optionally regenerate thumbnails."""
    # Run the existing reindex implementation from scripts
    try:
        from scripts.reindex_media import reindex as run_reindex

        created = int(run_reindex(regen_thumbs=regen_thumbnails) or 0)
        return {
            "status": "completed",
            "created": created,
            "regen_thumbnails": bool(regen_thumbnails),
        }
    except Exception as e:
        raise RuntimeError(f"Reindex failed: {e}") from e


@celery_app.task(bind=True)
def regenerate_thumbnails_task(
    self, user_id: int | None = None, limit: int | None = None
) -> dict:
    """Regenerate missing thumbnails for video media. Optionally scoped to a user."""
    session, app = _get_db_session()
    try:
        q = session.query(MediaFile).filter(MediaFile.mime_type.like("video%"))
        if user_id:
            q = q.filter(MediaFile.user_id == user_id)
        # Missing or non-existent thumbnails
        items = [
            m
            for m in q.order_by(MediaFile.uploaded_at.desc()).all()
            if not m.thumbnail_path or not os.path.exists(m.thumbnail_path)
        ]
        if limit is not None:
            items = items[: max(0, int(limit))]

        base_upload = os.path.join(
            app.instance_path, app.config.get("UPLOAD_FOLDER", "uploads")
        )
        updated = 0
        for m in items:
            try:
                thumbs_dir = os.path.join(base_upload, str(m.user_id), "thumbnails")
                os.makedirs(thumbs_dir, exist_ok=True)
                ts = int(datetime.utcnow().timestamp())
                thumb_path = os.path.join(thumbs_dir, f"regen_{m.id}_{ts}.jpg")
                subprocess.run(
                    [
                        _resolve_binary(app, "ffmpeg"),
                        "-y",
                        "-ss",
                        "1",
                        "-i",
                        m.file_path,
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
                m.thumbnail_path = thumb_path
                session.add(m)
                updated += 1
            except Exception:
                session.rollback()
                continue
        session.commit()
        return {"status": "completed", "updated": updated, "scoped_user": user_id}
    except Exception as e:
        session.rollback()
        raise RuntimeError(f"Thumbnail regeneration failed: {e}") from e
    finally:
        session.close()
