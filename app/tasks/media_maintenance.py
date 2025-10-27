"""
Media maintenance tasks: reindex DB from filesystem and maintenance utilities.
"""
import os
import sys
from collections import defaultdict

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
    """Scan the per-user data root (instance/data) and backfill MediaFile rows (read-only).

    Note: Thumbnail regeneration is disabled by policy in this task to avoid modifying on-disk assets;
    the regen_thumbnails flag is ignored and retained only for backward compatibility. Use the script
    `python scripts/reindex_media.py --regen-thumbnails` if you need to restore missing thumbnails.
    """
    # Run the existing reindex implementation from scripts
    try:
        # Warn if a caller tried to enable regeneration (no-op)
        if regen_thumbnails:
            try:
                import warnings as _warnings

                _warnings.warn(
                    "reindex_media_task: regen_thumbnails is ignored; reindex is read-only",
                    DeprecationWarning,
                    stacklevel=2,
                )
            except Exception:
                pass
        # Ensure project root is on sys.path so 'scripts' can be imported when worker is started via
        # 'celery -A app.tasks.celery_app worker' (which may not include CWD)
        _here = os.path.dirname(os.path.abspath(__file__))
        _repo_root = os.path.abspath(os.path.join(_here, "..", ".."))
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        from scripts.reindex_media import reindex as run_reindex

        # Always run in read-only mode (no thumbnail regeneration)
        created = int(run_reindex(regen_thumbs=False) or 0)
        return {
            "status": "completed",
            "created": created,
            "regen_thumbnails": False,
        }
    except Exception as e:
        raise RuntimeError(f"Reindex failed: {e}") from e


## Thumbnail regeneration has been removed by policy: filenames and on-disk media will not be modified.


@celery_app.task(bind=True)
def dedupe_media_task(self, dry_run: bool = False, user_id: int | None = None) -> dict:
    """Deduplicate MediaFile rows by per-user checksum and by duplicate file_path.

    Strategy:
      - For each user (or a specific user_id), group rows by (checksum) where checksum is not null.
      - Within each group, keep the most recent uploaded_at, delete others.
      - Also group by identical file_path per user and collapse duplicates.
    Returns a summary with counts of deleted rows.
    """
    session, _app = _get_db_session()
    deleted = 0
    examined = 0
    try:
        # Scope query
        q = session.query(MediaFile)
        if user_id:
            q = q.filter(MediaFile.user_id == user_id)
        items = q.order_by(MediaFile.user_id.asc(), MediaFile.uploaded_at.desc()).all()
        # Group by user -> checksum -> list
        by_user_checksum: dict[int, dict[str, list[MediaFile]]] = defaultdict(
            lambda: defaultdict(list)
        )
        by_user_path: dict[int, dict[str, list[MediaFile]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for m in items:
            examined += 1
            try:
                if m.checksum:
                    by_user_checksum[int(m.user_id)][m.checksum].append(m)
                if m.file_path:
                    by_user_path[int(m.user_id)][m.file_path].append(m)
            except Exception:
                continue

        def _delete_list(dups: list[MediaFile]):
            nonlocal deleted
            if not dups or len(dups) < 2:
                return
            # Keep the newest by uploaded_at, delete others
            dups_sorted = sorted(dups, key=lambda x: x.uploaded_at or 0, reverse=True)
            _keep = dups_sorted[0]
            for x in dups_sorted[1:]:
                try:
                    if not dry_run:
                        session.delete(x)
                    deleted += 1
                except Exception:
                    session.rollback()

        # Deduplicate by checksum
        for _uid, cmap in by_user_checksum.items():
            for _cs, rows in cmap.items():
                _delete_list(rows)

        # Deduplicate exact duplicate file_path entries too
        for _uid, pmap in by_user_path.items():
            for _fp, rows in pmap.items():
                _delete_list(rows)

        if not dry_run:
            session.commit()

        return {
            "status": "completed",
            "deleted": deleted,
            "examined": examined,
            "dry_run": bool(dry_run),
            "scoped_user": user_id,
        }
    except Exception as e:
        session.rollback()
        raise RuntimeError(f"Deduplication failed: {e}") from e
    finally:
        session.close()
