"""
Media maintenance tasks: reindex DB from filesystem and maintenance utilities.
"""
import fnmatch
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import scoped_session, sessionmaker

from app.models import db
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
def reindex_media_task(self, regen_thumbnails: bool = True) -> dict:
    """Scan the per-user data root (instance/data) and backfill MediaFile rows (read-only).

    Note: Thumbnail regeneration is disabled by policy in this task to avoid modifying on-disk assets;
    the regen_thumbnails flag is ignored and retained only for backward compatibility. Use the script
    `python scripts/reindex_media.py --regen-thumbnails` if you need to restore missing thumbnails.
    """
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
            # Ensure project root is on sys.path so 'scripts' can be imported when worker is started via
            # 'celery -A app.tasks.celery_app worker' (which may not include CWD)
            _here = os.path.dirname(os.path.abspath(__file__))
            _repo_root = os.path.abspath(os.path.join(_here, "..", ".."))
            if _repo_root not in sys.path:
                sys.path.insert(0, _repo_root)
            from scripts.reindex_media import reindex as run_reindex

            # Skip pruning during import to avoid deleting clips being downloaded
            created = int(run_reindex(regen_thumbs=True, app=app, skip_prune=True) or 0)
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


@celery_app.task(bind=True)
def auto_ingest_compilations_scan(self) -> dict:
    """Scan ingest root for compilation artifacts with .READY sentinel and trigger ingest.

    This Beat task runs periodically to detect new compilations and queue
    ingest_compiled_for_project tasks for each one that hasn't been imported yet.
    Controlled via Config/env:
      - INGEST_ROOT (default /srv/ingest)
      - AUTO_INGEST_COMPILATIONS_ENABLED (default false)
      - AUTO_INGEST_WORKER_IDS (CSV; empty => all worker dirs)
    """
    import json as _json
    from pathlib import Path

    from config.settings import Config

    cfg = Config()
    if not getattr(cfg, "AUTO_INGEST_COMPILATIONS_ENABLED", False):
        return {"status": "disabled"}

    ingest_root = Path(getattr(cfg, "INGEST_ROOT", "/srv/ingest") or "/srv/ingest")
    if not ingest_root.is_dir():
        return {"status": "skipped", "reason": f"No ingest root: {ingest_root}"}

    worker_ids_csv = getattr(cfg, "AUTO_INGEST_WORKER_IDS", "") or ""
    worker_ids = (
        [w.strip() for w in worker_ids_csv.split(",") if w.strip()]
        if worker_ids_csv
        else []
    )

    # Determine worker dirs to scan
    roots = []
    if worker_ids:
        for wid in worker_ids:
            candidate = ingest_root / wid
            if candidate.is_dir():
                roots.append(candidate)
    else:
        try:
            roots = [p for p in ingest_root.iterdir() if p.is_dir()]
        except Exception:
            roots = []

    queued = 0
    examined = 0
    for wr in roots:
        try:
            artifact_dirs = [p for p in wr.iterdir() if p.is_dir()]
        except Exception:
            continue
        for d in artifact_dirs:
            examined += 1
            # Skip if already imported
            if (d / ".IMPORTED").is_file():
                continue
            # Check for .READY sentinel
            if not (d / ".READY").is_file():
                continue
            # Load manifest to get project_id
            manifest_file = d / "manifest.json"
            if not manifest_file.is_file():
                continue
            try:
                manifest = _json.loads(manifest_file.read_text())
            except Exception:
                continue
            # Must have project_id, filename, and no clip_id (compilation artifact)
            try:
                pid = int(manifest.get("project_id") or 0)
            except Exception:
                continue
            if not pid or not manifest.get("filename") or manifest.get("clip_id"):
                continue
            # Queue ingest task for this project
            try:
                worker_id = wr.name  # Use the worker directory name
                ingest_compiled_for_project.apply_async(
                    args=(pid,),
                    kwargs={"worker_id": worker_id, "action": "copy"},
                    queue="celery",
                )
                queued += 1
            except Exception:
                pass

    return {
        "status": "completed",
        "examined": examined,
        "queued": queued,
    }


@celery_app.task(bind=True)
def cleanup_imported_artifacts(self) -> dict:
    """Prune artifact directories that have been imported and are older than the configured age.

    Removes artifact directories from INGEST_ROOT/<worker_id>/ that have:
    - .IMPORTED sentinel file (successfully imported)
    - Last modified time older than CLEANUP_IMPORTED_AGE_HOURS (default 24h)

    Controlled via Config/env:
      - INGEST_ROOT (default /srv/ingest)
      - CLEANUP_IMPORTED_ENABLED (default false)
      - CLEANUP_IMPORTED_AGE_HOURS (default 24)
      - CLEANUP_IMPORTED_WORKER_IDS (CSV; empty => all worker dirs)
    """
    import shutil
    import time
    from pathlib import Path

    from config.settings import Config

    cfg = Config()
    if not getattr(cfg, "CLEANUP_IMPORTED_ENABLED", False):
        return {"status": "disabled"}

    ingest_root = Path(getattr(cfg, "INGEST_ROOT", "/srv/ingest") or "/srv/ingest")
    if not ingest_root.is_dir():
        return {"status": "skipped", "reason": f"No ingest root: {ingest_root}"}

    age_hours = int(getattr(cfg, "CLEANUP_IMPORTED_AGE_HOURS", 24) or 24)
    age_seconds = age_hours * 3600
    now = time.time()

    worker_ids_csv = getattr(cfg, "CLEANUP_IMPORTED_WORKER_IDS", "") or ""
    worker_ids = (
        [w.strip() for w in worker_ids_csv.split(",") if w.strip()]
        if worker_ids_csv
        else []
    )

    # Determine worker dirs to scan
    roots = []
    if worker_ids:
        for wid in worker_ids:
            candidate = ingest_root / wid
            if candidate.is_dir():
                roots.append(candidate)
    else:
        try:
            roots = [p for p in ingest_root.iterdir() if p.is_dir()]
        except Exception:
            roots = []

    removed = 0
    examined = 0
    for wr in roots:
        try:
            artifact_dirs = [p for p in wr.iterdir() if p.is_dir()]
        except Exception:
            continue
        for d in artifact_dirs:
            examined += 1
            # Only remove if .IMPORTED exists
            imported_marker = d / ".IMPORTED"
            if not imported_marker.is_file():
                continue
            # Check age
            try:
                mtime = imported_marker.stat().st_mtime
                age = now - mtime
                if age < age_seconds:
                    continue
            except Exception:
                continue
            # Remove the artifact directory
            try:
                shutil.rmtree(d)
                removed += 1
            except Exception as e:
                # Log but continue
                print(f"Failed to remove {d}: {e}")

    return {
        "status": "completed",
        "examined": examined,
        "removed": removed,
        "age_hours": age_hours,
    }


@celery_app.task(bind=True)
def ingest_compiled_for_project(
    self,
    project_id: int,
    worker_id: str | None = None,
    action: str = "copy",
) -> dict:
    """Import compiled artifacts (final renders) pushed via rsync into the project's compilations.

    - Scans Config.INGEST_ROOT[/<worker_id>] for artifact directories produced by workers
      (created via _export_artifact_if_configured)
    - Detects compilation artifacts by manifest.json containing project_id and filename and no clip_id
    - Copies/moves/links the compiled file into the project's compilations directory
    - Creates/updates a MediaFile row with media_type=COMPILATION
    - Updates Project.output_filename and output_file_size

    Returns summary counts and destination path.
    """
    import json as _json
    import mimetypes as _mimetypes
    import os
    from pathlib import Path

    # Local imports to avoid module import-time side effects
    from app import create_app
    from app import storage as storage_lib
    from app.models import MediaFile, MediaType, Project, User
    from config.settings import Config

    def _load_manifest(dir_path: Path) -> dict | None:
        mf = dir_path / "manifest.json"
        if not mf.is_file():
            return None
        try:
            return _json.loads(mf.read_text())
        except Exception:
            return None

    cfg = Config()
    ingest_root = Path(getattr(cfg, "INGEST_ROOT", "/srv/ingest") or "/srv/ingest")

    try:
        root_is_dir = ingest_root.is_dir()
    except PermissionError:
        return {
            "status": "skipped",
            "reason": f"Permission denied accessing ingest root: {ingest_root}",
            "ingest_root": str(ingest_root),
        }
    if not root_is_dir:
        return {"status": "skipped", "reason": f"No ingest root: {ingest_root}"}

    app = create_app()
    with app.app_context():
        project = Project.query.filter_by(id=project_id).first()
        if not project:
            return {"status": "skipped", "reason": f"Project not found: {project_id}"}
        owner = User.query.filter_by(id=project.user_id).first()
        if not owner:
            return {
                "status": "skipped",
                "reason": f"Owner not found: {project.user_id}",
            }

        # Determine roots to scan
        roots: list[Path] = []
        if worker_id:
            candidate = ingest_root / worker_id
            try:
                if candidate.is_dir():
                    roots = [candidate]
                else:
                    return {
                        "status": "skipped",
                        "reason": f"Worker directory not found or not a directory: {candidate}",
                        "ingest_root": str(ingest_root),
                        "worker_id": worker_id,
                    }
            except PermissionError:
                return {
                    "status": "skipped",
                    "reason": f"Permission denied accessing worker directory: {candidate}",
                    "ingest_root": str(ingest_root),
                    "worker_id": worker_id,
                }
        else:
            try:
                roots = [p for p in ingest_root.iterdir() if p.is_dir()]
            except PermissionError:
                return {
                    "status": "skipped",
                    "reason": f"Permission denied listing ingest root: {ingest_root}",
                    "ingest_root": str(ingest_root),
                }

        dest_dir = Path(storage_lib.compilations_dir(owner, project.name))
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        imported = 0
        examined = 0
        for wr in roots:
            if not wr.is_dir():
                continue
            try:
                artifact_dirs = [p for p in wr.iterdir() if p.is_dir()]
            except Exception:
                artifact_dirs = []
            for d in sorted(artifact_dirs):
                examined += 1
                # Skip if this artifact directory was already imported
                try:
                    if (d / ".IMPORTED").is_file():
                        continue
                except Exception:
                    pass
                # Skip if rsync transfer is still in progress (no .READY sentinel yet)
                # Also check for absence of .PUSHING and use stability heuristic as fallback
                transfer_complete = False
                try:
                    if (d / ".READY").is_file():
                        transfer_complete = True
                    elif not (d / ".PUSHING").is_file() and _artifact_ready(d, 30):
                        # Fallback: if no .PUSHING lock and directory hasn't been modified for 30s,
                        # assume transfer is complete (legacy behavior)
                        transfer_complete = True
                except Exception:
                    pass
                if not transfer_complete:
                    continue
                mani = _load_manifest(d) or {}
                # Identify compilation artifacts: must match project_id, have filename, and not specify a clip_id
                try:
                    pid = int(mani.get("project_id") or 0)
                except Exception:
                    pid = 0
                filename = (mani.get("filename") or "").strip() or None
                clip_id_present = "clip_id" in mani and mani.get("clip_id") is not None
                if pid != int(project.id) or not filename or clip_id_present:
                    continue
                src = d / filename
                if not src.is_file():
                    continue
                dst = dest_dir / filename
                if dst.exists():
                    # Already imported
                    continue
                try:
                    if action == "move":
                        src.replace(dst)
                    elif action == "link":
                        os.symlink(src, dst)
                    else:
                        from shutil import copy2 as _copy2

                        _copy2(str(src), str(dst))
                    imported += 1
                    # Mark artifact directory as imported to avoid duplicate imports later
                    try:
                        (d / ".IMPORTED").touch()
                        # Clean up .READY sentinel since we've successfully imported
                        try:
                            (d / ".READY").unlink(missing_ok=True)
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    continue

                # Create MediaFile record for the compilation
                try:
                    size = dst.stat().st_size if dst.exists() else 0
                except Exception:
                    size = 0
                mime = _mimetypes.guess_type(str(dst))[0] or "video/mp4"
                media = MediaFile(
                    filename=dst.name,
                    original_filename=dst.name,
                    file_path=str(dst),
                    file_size=size,
                    mime_type=mime,
                    media_type=MediaType.COMPILATION,
                    user_id=owner.id,
                    project_id=project.id,
                    is_processed=True,
                )
                # Best-effort: extract duration and dimensions using ffprobe
                try:
                    from app.tasks.video_processing import (
                        extract_video_metadata as _meta,
                    )

                    meta = _meta(str(dst)) or {}
                    media.duration = meta.get("duration")
                    media.width = meta.get("width")
                    media.height = meta.get("height")
                    media.framerate = meta.get("framerate")
                except Exception:
                    pass

                # Best-effort: copy thumbnail from artifact directory if present
                try:
                    thumb_src = d / "thumbnail.jpg"
                    if thumb_src.is_file():
                        thumb_dst = dst.parent / f"{dst.stem}_thumb.jpg"
                        if not thumb_dst.exists():
                            from shutil import copy2 as _copy2

                            _copy2(str(thumb_src), str(thumb_dst))
                            media.thumbnail_path = str(thumb_dst)
                except Exception:
                    pass

                db.session.add(media)
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                # Update project output fields if not already set or mismatch
                try:
                    project.output_filename = dst.name
                    project.output_file_size = size
                    # Do not force status; assume separate job updates it, but set to COMPLETED if unset
                    try:
                        from app.models import ProjectStatus as _PS

                        if (
                            not project.status
                            or str(project.status).lower() == "pending"
                        ):
                            project.status = _PS.COMPLETED
                    except Exception:
                        pass
                    db.session.add(project)
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        return {
            "status": "completed",
            "imported": imported,
            "examined": examined,
            "dest": str(dest_dir),
            "ingest_root": str(ingest_root),
        }


@celery_app.task(bind=True)
def ingest_raw_clips_for_project(
    self,
    project_id: int,
    worker_id: str | None = None,
    action: str = "copy",
    regen_thumbnails: bool = True,
) -> dict:
    """DEPRECATED: Legacy rsync-based importer for raw clips.

    This task is no longer used in the HTTP upload workflow.
    Clips are now uploaded directly via POST /api/worker/projects/<id>/clips/<id>/upload
    during the download task (see app/tasks/download_clip_v2.py and app/api/worker.py).

    Keeping this task for backwards compatibility with any existing queued jobs,
    but it will skip execution if no ingest directory exists.

    Historical behavior:
    - Scanned /srv/ingest[/<worker_id>] for artifact directories
    - Imported rsynced files into project's clips folder
    - Ran reindex to backfill DB rows

    Returns summary indicating skipped status.
    """
    # Check if ingest root exists (it won't in new HTTP-only deployments)
    import os

    from config.settings import Config

    ingest_root = getattr(Config, "INGEST_ROOT", "/srv/ingest")
    if not os.path.exists(ingest_root) or not os.path.isdir(ingest_root):
        return {
            "status": "skipped",
            "reason": f"No ingest root: {ingest_root} (exists={os.path.exists(ingest_root)}, is_dir={os.path.isdir(ingest_root) if os.path.exists(ingest_root) else False})",
        }

    # Legacy implementation below (kept for backwards compatibility)
    # Lazy imports to avoid app initialization in module import time
    import json as _json

    from app import create_app
    from app import storage as storage_lib
    from app.models import Project, User
    from config.settings import Config

    def _load_manifest(dir_path: Path) -> dict | None:
        mf = dir_path / "manifest.json"
        if not mf.is_file():
            return None
        try:
            return _json.loads(mf.read_text())
        except Exception:
            return None

    def _find_clip_file(dir_path: Path, filename_hint: str | None) -> Path | None:
        if filename_hint:
            p = dir_path / filename_hint
            if p.is_file():
                return p
        # fallback: largest non-json/non-sentinel file
        sentinels = {".READY", ".DONE", ".PUSHING", ".PUSHED", ".IMPORTED"}
        candidates: list[Path] = []
        try:
            for p in dir_path.iterdir():
                if (
                    p.is_file()
                    and p.name not in sentinels
                    and not p.name.endswith(".json")
                ):
                    candidates.append(p)
        except Exception:
            return None
        if not candidates:
            return None
        candidates.sort(
            key=lambda x: x.stat().st_size if x.exists() else 0, reverse=True
        )
        return candidates[0]

    cfg = Config()
    ingest_root = Path(getattr(cfg, "INGEST_ROOT", "/srv/ingest") or "/srv/ingest")
    # Validate ingest root exists and is accessible
    try:
        root_is_dir = ingest_root.is_dir()
    except PermissionError as e:
        return {
            "status": "skipped",
            "reason": f"Permission denied accessing ingest root: {ingest_root}: {e}",
            "ingest_root": str(ingest_root),
        }
    except Exception as e:
        return {
            "status": "skipped",
            "reason": f"Error checking ingest root: {ingest_root}: {e}",
            "ingest_root": str(ingest_root),
        }
    if not root_is_dir:
        return {
            "status": "skipped",
            "reason": f"No ingest root: {ingest_root} (exists={ingest_root.exists()}, is_dir={root_is_dir})",
        }

    app = create_app()
    with app.app_context():
        project = Project.query.filter_by(id=project_id).first()
        if not project:
            return {"status": "skipped", "reason": f"Project not found: {project_id}"}
        owner = User.query.filter_by(id=project.user_id).first()
        if not owner:
            return {
                "status": "skipped",
                "reason": f"Owner not found: {project.user_id}",
            }

        # Determine worker roots to scan with permission-aware handling
        roots: list[Path] = []
        if worker_id:
            candidate = ingest_root / worker_id
            try:
                if candidate.is_dir():
                    roots = [candidate]
                else:
                    return {
                        "status": "skipped",
                        "reason": f"Worker directory not found or not a directory: {candidate}",
                        "ingest_root": str(ingest_root),
                        "worker_id": worker_id,
                    }
            except PermissionError:
                return {
                    "status": "skipped",
                    "reason": f"Permission denied accessing worker directory: {candidate}",
                    "ingest_root": str(ingest_root),
                    "worker_id": worker_id,
                }
        else:
            try:
                roots = [p for p in ingest_root.iterdir() if p.is_dir()]
            except PermissionError:
                return {
                    "status": "skipped",
                    "reason": f"Permission denied listing ingest root: {ingest_root}. Ensure the Celery process has execute/read on this path (group/ACL).",
                    "ingest_root": str(ingest_root),
                }

        clips_dir = Path(storage_lib.clips_dir(owner, project.name))
        try:
            clips_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return {
                "status": "error",
                "reason": f"Failed to create clips directory {clips_dir}: {e}",
            }

        imported = 0
        examined = 0
        for wr in roots:
            if not wr.is_dir():
                continue
            # iterate artifact dirs
            try:
                artifact_dirs = [p for p in wr.iterdir() if p.is_dir()]
            except Exception:
                artifact_dirs = []
            for d in sorted(artifact_dirs):
                examined += 1
                # Skip if directory was already imported
                try:
                    if (d / ".IMPORTED").is_file():
                        continue
                except Exception:
                    pass
                # Skip if rsync transfer is still in progress (no .READY sentinel yet)
                # Also check for absence of .PUSHING and use stability heuristic as fallback
                transfer_complete = False
                try:
                    if (d / ".READY").is_file():
                        transfer_complete = True
                    elif not (d / ".PUSHING").is_file() and _artifact_ready(d, 30):
                        # Fallback: if no .PUSHING lock and directory hasn't been modified for 30s,
                        # assume transfer is complete (legacy behavior)
                        transfer_complete = True
                except Exception:
                    pass
                if not transfer_complete:
                    continue
                mf = _load_manifest(d) or {}
                # Only import raw clip artifacts for this project; skip compilations and unknowns
                try:
                    mtype = (mf.get("type") or "").strip().lower()
                except Exception:
                    mtype = ""
                clip_id = mf.get("clip_id")
                slug = mf.get("slug") or d.name  # Use directory name as fallback slug

                if mtype and mtype != "raw_clip":
                    self.app.log.get_default_logger().debug(
                        f"Skipping {d.name}: wrong type '{mtype}'"
                    )
                    continue

                # Match by source_id (slug) instead of clip_id to support clip reuse across projects
                from app.models import Clip as _ClipCheck

                matching_clip = _ClipCheck.query.filter_by(
                    project_id=project.id, source_id=slug
                ).first()

                if not matching_clip:
                    self.app.log.get_default_logger().debug(
                        f"Skipping {d.name}: no clip with source_id={slug} in project {project.id}"
                    )
                    continue

                # Use the matched clip's ID for linking
                clip_id = matching_clip.id
                filename = (mf.get("filename") or "").strip() or None
                src = _find_clip_file(d, filename)
                if not src:
                    self.app.log.get_default_logger().debug(
                        f"Skipping {d.name}: no source file found (hint={filename})"
                    )
                    continue
                self.app.log.get_default_logger().info(
                    f"Processing artifact {d.name}: clip_id={clip_id}, src={src.name}"
                )
                dst = clips_dir / src.name
                if dst.exists():
                    # Skip file copy but still mark as imported to allow cleanup
                    try:
                        (d / ".IMPORTED").touch()
                        try:
                            (d / ".READY").unlink(missing_ok=True)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    continue
                try:
                    self.update_state(
                        state="PROGRESS",
                        meta={"status": f"Importing {src.name}", "clip_id": clip_id},
                    )
                    if action == "move":
                        src.replace(dst)
                    elif action == "link":
                        os.symlink(src, dst)
                    else:
                        from shutil import copy2 as _copy2

                        _copy2(str(src), str(dst))
                    imported += 1
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "status": f"Imported {src.name}",
                            "clip_id": clip_id,
                            "imported": imported,
                        },
                    )

                    # Create or update MediaFile record immediately
                    try:
                        from app.models import Clip as _Clip
                        from app.models import MediaFile, MediaType

                        # Check if this clip already has a MediaFile (might be old worker-created one)
                        clip_record = None
                        old_media = None
                        if clip_id:
                            clip_record = _Clip.query.filter_by(
                                id=clip_id, project_id=project.id
                            ).first()
                            if clip_record and clip_record.media_file_id:
                                old_media = db.session.get(
                                    MediaFile, clip_record.media_file_id
                                )

                        # Check if MediaFile already exists for this file path
                        existing_media = MediaFile.query.filter_by(
                            file_path=str(dst)
                        ).first()

                        if existing_media:
                            # File already imported, just link to clip if needed
                            media = existing_media
                        elif old_media:
                            # Clip has old MediaFile - check if it points to a non-existent file
                            # (likely from worker temp download before artifact import)
                            old_path_exists = False
                            try:
                                import os as _os_check

                                old_file_path = old_media.file_path
                                # Try to resolve path if it looks like instance-relative
                                if old_file_path.startswith("/instance/"):
                                    from flask import current_app

                                    suffix = old_file_path[len("/instance/") :].lstrip(
                                        "/"
                                    )
                                    old_file_path = _os_check.path.join(
                                        current_app.instance_path, suffix
                                    )
                                old_path_exists = _os_check.path.exists(old_file_path)
                            except Exception:
                                pass

                            if not old_path_exists:
                                # Update old MediaFile to point to new imported file
                                import mimetypes

                                mime = mimetypes.guess_type(str(dst))[0] or "video/mp4"
                                size = dst.stat().st_size if dst.exists() else 0

                                old_media.filename = dst.name
                                old_media.original_filename = dst.name
                                old_media.file_path = str(dst)
                                old_media.file_size = size
                                old_media.mime_type = mime
                                old_media.is_processed = True

                                # Copy thumbnail if available
                                thumb_filename = mf.get("thumbnail", "thumbnail.jpg")
                                thumb_src = d / thumb_filename
                                if thumb_src.is_file():
                                    thumb_dst = dst.parent / f"{dst.stem}_thumb.jpg"
                                    if not thumb_dst.exists():
                                        from shutil import copy2 as _copy2_thumb

                                        _copy2_thumb(str(thumb_src), str(thumb_dst))
                                    old_media.thumbnail_path = str(thumb_dst)

                                media = old_media
                                db.session.commit()
                            else:
                                # Old media file still exists, create new one
                                media = old_media
                        else:
                            # Create new MediaFile
                            import mimetypes

                            mime = mimetypes.guess_type(str(dst))[0] or "video/mp4"
                            size = dst.stat().st_size if dst.exists() else 0

                            media = MediaFile(
                                filename=dst.name,
                                original_filename=dst.name,
                                file_path=str(dst),
                                file_size=size,
                                mime_type=mime,
                                media_type=MediaType.CLIP,
                                user_id=owner.id,
                                project_id=project.id,
                                is_processed=True,
                            )

                            # Copy thumbnail if available
                            thumb_filename = mf.get("thumbnail", "thumbnail.jpg")
                            thumb_src = d / thumb_filename
                            if thumb_src.is_file():
                                thumb_dst = dst.parent / f"{dst.stem}_thumb.jpg"
                                if not thumb_dst.exists():
                                    from shutil import copy2 as _copy2_thumb

                                    _copy2_thumb(str(thumb_src), str(thumb_dst))
                                media.thumbnail_path = str(thumb_dst)

                            db.session.add(media)
                            db.session.commit()

                        # Link MediaFile to Clip if clip_id is present
                        if clip_id and clip_record:
                            try:
                                if (
                                    not clip_record.media_file_id
                                    or clip_record.media_file_id != media.id
                                ):
                                    clip_record.media_file_id = media.id
                                    clip_record.is_downloaded = True
                                    if media.duration and not clip_record.duration:
                                        clip_record.duration = media.duration
                                    db.session.commit()
                            except Exception:
                                db.session.rollback()
                    except Exception:
                        db.session.rollback()

                    # Mark artifact directory as imported to avoid duplicates
                    try:
                        (d / ".IMPORTED").touch()
                        # Clean up .READY sentinel since we've successfully imported
                        try:
                            (d / ".READY").unlink(missing_ok=True)
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception as e:
                    # Log individual errors but continue processing other artifacts
                    import traceback

                    self.app.log.get_default_logger().error(
                        f"Failed to import {d.name}: {e}\n{traceback.format_exc()}"
                    )
                    continue

        # Reindex to backfill DB rows
        created = 0
        try:
            # Ensure project root is on sys.path so 'scripts' can be imported when worker is started via
            # 'celery -A app.tasks.celery_app worker' (which may not include CWD)
            _here = os.path.dirname(os.path.abspath(__file__))
            _repo_root = os.path.abspath(os.path.join(_here, "..", ".."))
            if _repo_root not in sys.path:
                sys.path.insert(0, _repo_root)
            from scripts.reindex_media import reindex as run_reindex

            created = int(
                run_reindex(regen_thumbs=bool(regen_thumbnails), app=app) or 0
            )
        except Exception:
            created = 0

        # Best-effort: attach newly imported media to clips by slug/filename
        try:
            import re as _re  # noqa: I001
            from sqlalchemy.orm import joinedload as _jl  # noqa: I001
            from app.models import MediaFile, MediaType, Clip as _Clip  # noqa: I001

            def _slugify(s: str) -> str:
                try:
                    safe = _re.sub(r"[^A-Za-z0-9._-]+", "_", s)
                    return _re.sub(r"_+", "_", safe).strip("._-")
                except Exception:
                    return s

            clips = (
                _Clip.query.options(_jl(_Clip.media_file))
                .filter_by(project_id=project.id)
                .all()
            )
            # Build lookup of project media by filename for quick match
            media_by_name = {
                m.filename: m
                for m in MediaFile.query.filter_by(
                    project_id=project.id, media_type=MediaType.CLIP
                ).all()
            }
            for c in clips:
                if getattr(c, "media_file_id", None):
                    continue
                slug = (getattr(c, "source_id", "") or "").strip()
                if not slug:
                    # Try extracting from URL path
                    try:
                        u = (c.source_url or "").strip()
                        if u:
                            # Strip query/fragment and pull last path segment
                            u0 = u.split("?", 1)[0].split("#", 1)[0]
                            parts = [p for p in u0.split("/") if p]
                            if parts:
                                slug = parts[-1]
                    except Exception:
                        slug = ""
                if not slug:
                    continue
                safe = _slugify(slug)
                candidates = [
                    f"{safe}{ext}" for ext in (".mp4", ".mkv", ".webm", ".mov")
                ]
                mf = None
                for nm in candidates:
                    mf = media_by_name.get(nm)
                    if mf:
                        break
                if mf:
                    try:
                        c.media_file_id = mf.id
                        c.is_downloaded = True
                        if mf.duration and not c.duration:
                            c.duration = mf.duration
                        db.session.add(c)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
        except Exception:
            pass

        return {
            "status": "completed",
            "imported": imported,
            "examined": examined,
            "reindexed": created,
            "dest": str(clips_dir),
            "ingest_root": str(ingest_root),
        }


@celery_app.task(bind=True)
def ingest_downloads_for_project(
    self,
    project_id: int,
    worker_id: str | None = None,
    action: str = "copy",
    pattern: str = "downloads_*/*.mp4",
) -> dict:
    """Import downloaded clips from artifact directories into the project's clips folder.

    Specifically designed for the downloads exported by download_clip_task_v2 which creates:
        /artifacts/downloads_<project_id>_<clip_id>_<timestamp>/
            clip_<clip_id>.mp4
            manifest.json
            .DONE

    - Scans Config.INGEST_ROOT[/<worker_id>]/downloads_* for artifacts
    - Filters by project_id in manifest.json
    - Imports clips into the project's clips directory
    - Updates Clip.is_downloaded and links to MediaFile

    Returns summary counts and destination path.
    """
    import json as _json
    import mimetypes as _mimetypes
    from pathlib import Path

    from app import create_app
    from app import storage as storage_lib
    from app.models import Clip, MediaFile, MediaType, Project, User
    from config.settings import Config

    def _load_manifest(dir_path: Path) -> dict | None:
        mf = dir_path / "manifest.json"
        if not mf.is_file():
            return None
        try:
            return _json.loads(mf.read_text())
        except Exception:
            return None

    cfg = Config()
    ingest_root = Path(getattr(cfg, "INGEST_ROOT", "/srv/ingest") or "/srv/ingest")

    try:
        root_is_dir = ingest_root.is_dir()
    except PermissionError:
        return {
            "status": "skipped",
            "reason": f"Permission denied accessing ingest root: {ingest_root}",
        }
    if not root_is_dir:
        return {"status": "skipped", "reason": f"No ingest root: {ingest_root}"}

    app = create_app()
    with app.app_context():
        project = Project.query.filter_by(id=project_id).first()
        if not project:
            return {"status": "skipped", "reason": f"Project not found: {project_id}"}
        owner = User.query.filter_by(id=project.user_id).first()
        if not owner:
            return {"status": "skipped", "reason": "Owner not found"}

        # Determine roots to scan
        roots: list[Path] = []
        if worker_id:
            candidate = ingest_root / worker_id
            try:
                if candidate.is_dir():
                    roots = [candidate]
                else:
                    return {
                        "status": "skipped",
                        "reason": f"Worker directory not found: {candidate}",
                    }
            except PermissionError:
                return {
                    "status": "skipped",
                    "reason": f"Permission denied: {candidate}",
                }
        else:
            try:
                roots = [p for p in ingest_root.iterdir() if p.is_dir()]
            except PermissionError:
                return {"status": "skipped", "reason": "Permission denied"}

        clips_dir = Path(storage_lib.clips_dir(owner, project.name))
        try:
            clips_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        imported = 0
        examined = 0

        for wr in roots:
            if not wr.is_dir():
                continue
            try:
                # Find all directories matching "downloads_*" pattern
                artifact_dirs = [
                    p
                    for p in wr.iterdir()
                    if p.is_dir() and p.name.startswith("downloads_")
                ]
            except Exception:
                artifact_dirs = []

            for d in sorted(artifact_dirs):
                examined += 1

                # Skip if already imported
                try:
                    if (d / ".IMPORTED").is_file():
                        continue
                except Exception:
                    pass

                # Check if transfer is complete
                transfer_complete = False
                try:
                    if (d / ".READY").is_file():
                        transfer_complete = True
                    elif not (d / ".PUSHING").is_file() and _artifact_ready(d, 30):
                        transfer_complete = True
                except Exception:
                    pass
                if not transfer_complete:
                    continue

                mani = _load_manifest(d) or {}

                # Verify this is a download artifact for our project
                try:
                    artifact_type = (mani.get("type") or "").strip().lower()
                except Exception:
                    artifact_type = ""
                if artifact_type != "download":
                    continue

                try:
                    pid = int(mani.get("project_id") or 0)
                except Exception:
                    pid = 0
                if pid != int(project.id):
                    continue

                try:
                    clip_id = int(mani.get("clip_id") or 0)
                except Exception:
                    clip_id = 0

                filename = (mani.get("filename") or "").strip()
                if not filename:
                    continue

                src = d / filename
                if not src.is_file():
                    continue

                dst = clips_dir / filename
                if dst.exists():
                    # File already exists, skip but mark as imported
                    try:
                        (d / ".IMPORTED").touch()
                        (d / ".READY").unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue

                # Import the file
                try:
                    if action == "move":
                        src.replace(dst)
                    elif action == "link":
                        import os

                        os.symlink(src, dst)
                    else:
                        from shutil import copy2 as _copy2

                        _copy2(str(src), str(dst))
                    imported += 1
                except Exception:
                    continue

                # Create MediaFile record
                try:
                    size = dst.stat().st_size if dst.exists() else 0
                except Exception:
                    size = 0

                mime = _mimetypes.guess_type(str(dst))[0] or "video/mp4"

                media = MediaFile(
                    filename=dst.name,
                    original_filename=dst.name,
                    file_path=str(dst),
                    file_size=size,
                    mime_type=mime,
                    media_type=MediaType.CLIP,
                    user_id=owner.id,
                    project_id=project.id,
                    is_processed=True,
                )

                # Extract metadata if available
                try:
                    from app.tasks.video_processing import (
                        extract_video_metadata as _meta,
                    )

                    meta = _meta(str(dst)) or {}
                    media.duration = meta.get("duration")
                    media.width = meta.get("width")
                    media.height = meta.get("height")
                    media.framerate = meta.get("framerate")
                except Exception:
                    pass

                # Copy thumbnail if available
                try:
                    thumb_src = d / f"{dst.stem}_thumb.jpg"
                    if thumb_src.is_file():
                        thumb_dst = dst.parent / f"{dst.stem}_thumb.jpg"
                        if not thumb_dst.exists():
                            from shutil import copy2 as _copy2

                            _copy2(str(thumb_src), str(thumb_dst))
                        media.thumbnail_path = str(thumb_dst)
                except Exception:
                    pass

                db.session.add(media)
                try:
                    db.session.commit()
                    media_id = media.id
                except Exception:
                    db.session.rollback()
                    media_id = None

                # Update the Clip record if clip_id was provided
                if clip_id and media_id:
                    try:
                        clip = Clip.query.filter_by(id=clip_id).first()
                        if clip:
                            clip.is_downloaded = True
                            clip.media_file_id = media_id
                            if media.duration and not clip.duration:
                                clip.duration = media.duration
                            db.session.add(clip)
                            db.session.commit()
                    except Exception:
                        db.session.rollback()

                # Mark as imported
                try:
                    (d / ".IMPORTED").touch()
                    (d / ".READY").unlink(missing_ok=True)
                except Exception:
                    pass

        return {
            "status": "completed",
            "imported": imported,
            "examined": examined,
            "dest": str(clips_dir),
            "ingest_root": str(ingest_root),
        }


@celery_app.task(bind=True)
def process_uploaded_media_task(
    self, media_id: int, generate_thumbnail: bool = True
) -> dict:
    """Process uploaded media file: generate thumbnail and extract metadata.

    This task should be called after a media file is uploaded to avoid
    blocking the web request with ffmpeg operations.

    Args:
        media_id: ID of the MediaFile to process
        generate_thumbnail: Whether to generate a thumbnail (default True)

    Returns:
        Dict with processing results
    """
    import subprocess
    from pathlib import Path

    from app import create_app
    from app.models import MediaFile, db

    app = create_app()
    with app.app_context():
        from sqlalchemy import select

        # Get media file
        media = db.session.execute(
            select(MediaFile).filter_by(id=media_id)
        ).scalar_one_or_none()

        if not media:
            return {"status": "error", "error": f"Media file {media_id} not found"}

        if not media.filepath or not Path(media.filepath).exists():
            return {
                "status": "error",
                "error": f"File not found: {media.filepath}",
            }

        file_path = Path(media.filepath)
        results = {"status": "success", "media_id": media_id}

        # Generate thumbnail for video files
        if (
            generate_thumbnail
            and media.mime_type
            and media.mime_type.startswith("video")
        ):
            try:
                from app.ffmpeg_config import config_args as _cfg_args
                from app.main.routes import _resolve_binary

                dest_dir = file_path.parent
                stem = file_path.stem
                thumb_path = dest_dir / f"{stem}_thumb.jpg"

                subprocess.run(
                    [
                        _resolve_binary(app, "ffmpeg"),
                        *_cfg_args(app, "ffmpeg", "thumbnail"),
                        "-y",
                        "-ss",
                        str(app.config.get("THUMBNAIL_TIMESTAMP_SECONDS", 1)),
                        "-i",
                        str(file_path),
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={int(app.config.get('THUMBNAIL_WIDTH', 480))}:-1",
                        str(thumb_path),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=30,
                )

                media.thumbnail_path = str(thumb_path)
                results["thumbnail"] = str(thumb_path)

            except Exception as e:
                app.logger.warning(f"Thumbnail generation failed for {media_id}: {e}")
                results["thumbnail_error"] = str(e)

        # Extract metadata with ffprobe
        if media.mime_type and media.mime_type.startswith("video"):
            try:
                from app.ffmpeg_config import config_args as _cfg_args
                from app.main.routes import _resolve_binary

                probe_cmd = [
                    _resolve_binary(app, "ffprobe"),
                    *_cfg_args(app, "ffprobe"),
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=width,height,r_frame_rate,codec_type",
                    "-of",
                    "json",
                    str(file_path),
                ]

                import json

                out = subprocess.check_output(
                    probe_cmd, text=True, encoding="utf-8", timeout=15
                )
                data = json.loads(out)

                # Extract duration from format
                duration = data.get("format", {}).get("duration")
                if duration:
                    media.duration = float(duration)
                    results["duration"] = float(duration)

                # Extract video stream metadata
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        if "width" in stream:
                            media.width = int(stream["width"])
                            results["width"] = int(stream["width"])
                        if "height" in stream:
                            media.height = int(stream["height"])
                            results["height"] = int(stream["height"])
                        if "r_frame_rate" in stream:
                            fps_str = stream["r_frame_rate"]
                            if "/" in fps_str:
                                num, den = fps_str.split("/")
                                media.fps = float(num) / float(den)
                                results["fps"] = float(num) / float(den)
                        break

            except Exception as e:
                app.logger.warning(f"Metadata extraction failed for {media_id}: {e}")
                results["metadata_error"] = str(e)

        # Save changes
        try:
            db.session.commit()
            results["saved"] = True
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to save media {media_id} metadata: {e}")
            results["save_error"] = str(e)

        return results
