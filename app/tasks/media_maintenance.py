"""
Media maintenance tasks: reindex DB from filesystem and maintenance utilities.
"""
import fnmatch
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

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


def _list_worker_roots(ingest_root: Path, worker_ids_csv: str | None) -> list[Path]:
    if worker_ids_csv:
        ids = [w.strip() for w in worker_ids_csv.split(",") if w.strip()]
        return [ingest_root / wid for wid in ids if (ingest_root / wid).is_dir()]
    # Default: all first-level subdirs
    return [p for p in ingest_root.iterdir() if p.is_dir()]


def _artifact_ready(dir_path: Path, stable_seconds: int) -> bool:
    # Heuristic: consider ready if directory mtime is older than stable_seconds
    try:
        mtime = datetime.utcfromtimestamp(dir_path.stat().st_mtime)
        return (datetime.utcnow() - mtime) >= timedelta(seconds=max(stable_seconds, 0))
    except Exception:
        return False


def _iter_candidate_files(
    worker_root: Path, pattern: str, stable_seconds: int
) -> list[Path]:
    files: list[Path] = []
    for artifact_dir in sorted([d for d in worker_root.iterdir() if d.is_dir()]):
        if not _artifact_ready(artifact_dir, stable_seconds):
            continue
        for path in artifact_dir.rglob("*"):
            if path.is_file() and fnmatch.fnmatch(path.name, pattern):
                # Skip common sentinel filenames if they were transferred
                if path.name in {".READY", ".DONE", ".PUSHING", ".PUSHED"}:
                    continue
                files.append(path)
    return files


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


@celery_app.task(bind=True)
def ingest_import_task(self) -> dict:
    """Scan an ingest root for ready artifacts and import files into a project's
    compilations folder, then reindex so they appear in the UI.

    Controlled via Config/env:
      - INGEST_ROOT (default /srv/ingest)
      - INGEST_IMPORT_WORKER_IDS (CSV; empty => all)
      - INGEST_IMPORT_USERNAME (required)
      - INGEST_IMPORT_PROJECT (required)
      - INGEST_IMPORT_CREATE_PROJECT (default true)
      - INGEST_IMPORT_PATTERN (default *.mp4)
      - INGEST_IMPORT_ACTION (copy|move|link; default copy)
      - INGEST_IMPORT_STABLE_SECONDS (default 60)
    """
    # Late imports to avoid circulars and heavy initialization
    from app import create_app
    from app import storage as storage_lib
    from app.models import Project, User
    from config.settings import Config
    from scripts.reindex_media import reindex as run_reindex

    cfg = Config()
    ingest_root = Path(getattr(cfg, "INGEST_ROOT", "/srv/ingest") or "/srv/ingest")
    if not ingest_root.is_dir():
        return {"status": "skipped", "reason": f"No ingest root: {ingest_root}"}

    worker_ids_csv = getattr(cfg, "INGEST_IMPORT_WORKER_IDS", "") or ""
    pattern = getattr(cfg, "INGEST_IMPORT_PATTERN", "*.mp4") or "*.mp4"
    action = (getattr(cfg, "INGEST_IMPORT_ACTION", "copy") or "copy").lower()
    stable_seconds = int(getattr(cfg, "INGEST_IMPORT_STABLE_SECONDS", 60) or 60)

    username = getattr(cfg, "INGEST_IMPORT_USERNAME", None)
    project_name = getattr(cfg, "INGEST_IMPORT_PROJECT", None)
    allow_create = bool(getattr(cfg, "INGEST_IMPORT_CREATE_PROJECT", True))

    if not username or not project_name:
        return {
            "status": "skipped",
            "reason": "INGEST_IMPORT_USERNAME and INGEST_IMPORT_PROJECT must be set",
        }

    app = create_app()
    imported = 0
    examined = 0
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            return {"status": "skipped", "reason": f"User not found: {username}"}
        project = Project.query.filter_by(user_id=user.id, name=project_name).first()
        if not project:
            if not allow_create:
                return {
                    "status": "skipped",
                    "reason": f"Project not found: {project_name}",
                }
            project = Project(user_id=user.id, name=project_name)
            try:
                db.session.add(project)
                db.session.commit()
            except Exception:
                db.session.rollback()
                return {"status": "error", "reason": "Failed to create project"}

        dest_dir = Path(storage_lib.compilations_dir(user, project.name))
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Build candidate list from worker roots
        imported_paths: list[str] = []
        for wr in _list_worker_roots(ingest_root, worker_ids_csv):
            candidates = _iter_candidate_files(wr, pattern, stable_seconds)
            for src in candidates:
                examined += 1
                dst = dest_dir / src.name
                if dst.exists():
                    continue
                try:
                    if action == "move":
                        src.replace(dst)
                    elif action == "link":
                        os.symlink(src, dst)
                    else:
                        # copy
                        from shutil import copy2 as _copy2

                        _copy2(str(src), str(dst))
                    imported += 1
                    imported_paths.append(str(dst))
                except Exception:
                    continue

        # Reindex once after batch
        created = 0
        try:
            created = int(run_reindex(regen_thumbs=True, app=app) or 0)
        except Exception:
            created = 0

    return {
        "status": "completed",
        "imported": imported,
        "examined": examined,
        "reindexed": created,
        "dest": str(dest_dir),
        "ingest_root": str(ingest_root),
    }
