"""
Main application routes for the Clippy platform.

This module handles the core user-facing routes including the landing page,
dashboard, project management, and media upload functionality.
"""
import hashlib
import mimetypes
import os
import subprocess
from uuid import uuid4

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import storage as storage_lib
from app.models import (
    Clip,
    MediaFile,
    MediaType,
    ProcessingJob,
    Project,
    ProjectStatus,
    db,
)
from app.version import get_version

# Create main blueprint
main_bp = Blueprint("main", __name__)


def _rebase_instance_path(path: str | None) -> str | None:
    """Map container/portable instance paths to this app's concrete instance_path.

    Supports the following patterns:
      - '/instance/…'  -> <app.instance_path>/…
      - '/app/instance/…' -> <app.instance_path>/… (common inside containers)
      - Explicit alias via env: MEDIA_PATH_ALIAS_FROM -> MEDIA_PATH_ALIAS_TO

    If no mapping applies, return the input unchanged.
    """
    if not path:
        return path
    try:
        p = str(path)
        # 1) Explicit alias mapping when configured
        alias_from = os.getenv("MEDIA_PATH_ALIAS_FROM")
        alias_to = os.getenv("MEDIA_PATH_ALIAS_TO")
        if alias_from and alias_to and p.startswith(alias_from):
            # Join safely to avoid missing path separators (e.g., 'instancedata')
            suffix = p[len(alias_from) :].lstrip(os.sep)
            base = alias_to.rstrip(os.sep)
            cand = os.path.join(base, suffix)
            return cand

        # 2) Canonical '/instance/' prefix
        if p.startswith("/instance/"):
            suffix = p[len("/instance/") :].lstrip("/")
            return os.path.join(current_app.instance_path, suffix)

        # 3) Container '/app/instance/' prefix
        prefix = "/app/instance/"
        if p.startswith(prefix):
            suffix = p[len(prefix) :].lstrip("/")
            return os.path.join(current_app.instance_path, suffix)
    except Exception:
        return path
    return path


@main_bp.route("/")
def index():
    """
    Landing page for the Clippy platform.

    Displays information about the platform and provides links to
    authentication for new and existing users.

    Returns:
        Response: Rendered landing page template
    """
    return render_template(
        "main/index.html",
        title="Clippy - Video Compilation Platform",
        version=get_version(),
    )


@main_bp.route("/dashboard")
@login_required
def dashboard():
    """
    User dashboard showing projects and recent activity.

    Displays user's projects, recent clips, processing status,
    and quick action buttons for creating new projects.

    Returns:
        Response: Rendered dashboard template
    """
    # Get user's recent projects (limit N)
    projects = current_user.projects.order_by(Project.updated_at.desc()).limit(10).all()

    # Ensure projects have a public_id for preview URLs and enrich with media info
    enriched_projects: list[dict] = []
    for p in projects:
        # Assign a public_id if missing (best-effort)
        if not getattr(p, "public_id", None):
            try:
                p.public_id = Project.generate_public_id()
                db.session.add(p)
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Newest compiled output for this project, if any
        compiled = (
            p.media_files.filter_by(media_type=MediaType.COMPILATION)
            .order_by(MediaFile.uploaded_at.desc())
            .first()
        )
        # URLs for thumbnail and hover preview
        thumb_url = (
            url_for("main.media_thumbnail", media_id=compiled.id) if compiled else None
        )
        preview_url = None
        try:
            if p.output_filename and p.public_id:
                preview_url = url_for(
                    "main.preview_compiled_output_by_public", public_id=p.public_id
                )
        except Exception:
            preview_url = None

        enriched_projects.append(
            {
                "project": p,
                "compiled": compiled,
                "thumb_url": thumb_url,
                "preview_url": preview_url,
                "duration_formatted": getattr(compiled, "duration_formatted", None),
                "tags": getattr(compiled, "tags", None) or "",
            }
        )

    # Get recent clips across all projects
    recent_clips = (
        db.session.query(Clip)
        .join(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Clip.created_at.desc())
        .limit(10)
        .all()
    )

    # Get statistics
    stats = {
        "total_projects": current_user.projects.count(),
        "completed_projects": current_user.projects.filter_by(
            status=ProjectStatus.COMPLETED
        ).count(),
        "processing_projects": current_user.projects.filter_by(
            status=ProjectStatus.PROCESSING
        ).count(),
        "total_clips": db.session.query(Clip)
        .join(Project)
        .filter(Project.user_id == current_user.id)
        .count(),
        "total_media_files": current_user.media_files.count(),
    }

    return render_template(
        "main/dashboard.html",
        title="Dashboard",
        projects=enriched_projects,
        recent_clips=recent_clips,
        stats=stats,
    )


@main_bp.route("/projects")
@login_required
def projects():
    """
    List all user projects with filtering and pagination.

    Returns:
        Response: Rendered projects list template
    """
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("PROJECTS_PER_PAGE", 20)

    # Filter by status if provided
    status_filter = request.args.get("status")
    query = current_user.projects

    if status_filter and status_filter in [s.value for s in ProjectStatus]:
        query = query.filter_by(status=ProjectStatus(status_filter))

    projects_pagination = query.order_by(Project.updated_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Import enums for template use
    from app.models import Clip, MediaType

    return render_template(
        "main/projects.html",
        title="My Projects",
        projects=projects_pagination.items,
        pagination=projects_pagination,
        status_filter=status_filter,
        MediaType=MediaType,
        Clip=Clip,
    )


## Legacy project creation route removed; use the wizard and API instead.


@main_bp.route("/p/<public_id>")
@login_required
def project_details_by_public(public_id):
    """
    Display detailed project information and management interface.

    Args:
        public_id: Opaque public id of the project to display

    Returns:
        Response: Rendered project details template or 404
    """
    # Owner-only view via opaque id
    project = Project.query.filter_by(
        public_id=public_id, user_id=current_user.id
    ).first_or_404()
    # Defense-in-depth: if project has no public_id (shouldn't happen here), assign one
    if not project.public_id:
        try:
            import secrets as _secrets

            project.public_id = _secrets.token_urlsafe(12)
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Get project clips with ordering (default)
    clips_query = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc())
    clips = clips_query.all()
    total_clip_count = clips_query.count()
    used_only = False

    # Get project media files and group by role
    media_files = project.media_files.order_by(MediaFile.uploaded_at.desc()).all()
    intros = (
        project.media_files.filter_by(media_type=MediaType.INTRO)
        .order_by(MediaFile.uploaded_at.desc())
        .all()
    )
    outros = (
        project.media_files.filter_by(media_type=MediaType.OUTRO)
        .order_by(MediaFile.uploaded_at.desc())
        .all()
    )
    transitions = (
        project.media_files.filter_by(media_type=MediaType.TRANSITION)
        .order_by(MediaFile.uploaded_at.desc())
        .all()
    )

    # Latest compiled media (for duration/thumbnail/title details)
    compiled_media = (
        project.media_files.filter_by(media_type=MediaType.COMPILATION)
        .order_by(MediaFile.uploaded_at.desc())
        .first()
    )

    # If we have a recent successful compile job with a used clip subset, prefer showing only those clips
    try:
        last_job = (
            ProcessingJob.query.filter_by(
                project_id=project.id, job_type="compile_video", status="success"
            )
            .order_by(ProcessingJob.completed_at.desc())
            .first()
        )
        used_ids = []
        if last_job and isinstance(last_job.result_data, dict):
            used_ids = last_job.result_data.get("used_clip_ids") or []
            if isinstance(used_ids, list) and used_ids:
                # Keep the same ordering as default query
                clips = [c for c in clips if c.id in set(used_ids)]
                used_only = True
    except Exception:
        # Fail quietly; show default all clips
        pass

    # Download URL for final compilation if present
    download_url = None
    if project.output_filename:
        try:
            if project.public_id:
                download_url = url_for(
                    "main.download_compiled_output_by_public",
                    public_id=project.public_id,
                )
            else:
                download_url = url_for(
                    "main.download_compiled_output", project_id=project.id
                )
        except Exception:
            download_url = None

    return render_template(
        "main/project_details.html",
        title=project.name,
        project=project,
        clips=clips,
        used_only=used_only,
        used_count=len(clips),
        total_clip_count=total_clip_count,
        media_files=media_files,
        intros=intros,
        outros=outros,
        transitions=transitions,
        download_url=download_url,
        compiled_media=compiled_media,
    )


@main_bp.route("/projects/<int:project_id>")
@login_required
def project_details(project_id):
    """Legacy numeric-id route retained for backwards compatibility.

    Redirects to the opaque-id route if available, while enforcing ownership.
    """
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()
    if not project.public_id:
        try:
            import secrets as _secrets

            project.public_id = _secrets.token_urlsafe(12)
            db.session.commit()
        except Exception:
            db.session.rollback()
    if project.public_id:
        return redirect(
            url_for("main.project_details_by_public", public_id=project.public_id)
        )
    # Fallback: render directly
    clips_query = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc())
    clips = clips_query.all()
    total_clip_count = clips_query.count()
    used_only = False
    media_files = project.media_files.order_by(MediaFile.uploaded_at.desc()).all()
    intros = (
        project.media_files.filter_by(media_type=MediaType.INTRO)
        .order_by(MediaFile.uploaded_at.desc())
        .all()
    )
    outros = (
        project.media_files.filter_by(media_type=MediaType.OUTRO)
        .order_by(MediaFile.uploaded_at.desc())
        .all()
    )
    transitions = (
        project.media_files.filter_by(media_type=MediaType.TRANSITION)
        .order_by(MediaFile.uploaded_at.desc())
        .all()
    )
    compiled_media = (
        project.media_files.filter_by(media_type=MediaType.COMPILATION)
        .order_by(MediaFile.uploaded_at.desc())
        .first()
    )
    # Prefer showing only the clips used in the latest successful compile, if available
    try:
        last_job = (
            ProcessingJob.query.filter_by(
                project_id=project.id, job_type="compile_video", status="success"
            )
            .order_by(ProcessingJob.completed_at.desc())
            .first()
        )
        used_ids = []
        if last_job and isinstance(last_job.result_data, dict):
            used_ids = last_job.result_data.get("used_clip_ids") or []
            if isinstance(used_ids, list) and used_ids:
                clips = [c for c in clips if c.id in set(used_ids)]
                used_only = True
    except Exception:
        pass
    download_url = None
    if project.output_filename:
        try:
            download_url = url_for(
                "main.download_compiled_output", project_id=project.id
            )
        except Exception:
            download_url = None
    return render_template(
        "main/project_details.html",
        title=project.name,
        project=project,
        clips=clips,
        used_only=used_only,
        used_count=len(clips),
        total_clip_count=total_clip_count,
        media_files=media_files,
        intros=intros,
        outros=outros,
        transitions=transitions,
        download_url=download_url,
        compiled_media=compiled_media,
    )


@main_bp.route("/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id: int):
    """Delete a project and its associated resources for the current user.

    - Removes compiled output file if present
    - Deletes media files on disk and thumbnails
    - Deletes DB rows for media files and clips
    - Deletes the project row
    """
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    # Capture project name and user before deletion for cleanup
    project_name = project.name
    project_user = current_user

    try:
        # Remove compiled output if present
        try:
            if project.output_filename:
                compiled_path = os.path.join(
                    current_app.instance_path, "compilations", project.output_filename
                )
                if os.path.exists(compiled_path):
                    os.remove(compiled_path)
        except Exception:
            pass

        # Handle media assets
        # - Reusable assets (intro/outro/transition) are DETACHED from the project to remain in the user's library
        # - Project-specific assets (clips, compilations, images tied to project) are DELETED from disk and DB
        preserved = 0
        removed = 0
        for m in list(project.media_files):
            try:
                if m.media_type in {
                    MediaType.INTRO,
                    MediaType.OUTRO,
                    MediaType.TRANSITION,
                }:
                    # Keep in library; just detach from this project
                    m.project_id = None
                    preserved += 1
                    continue
                # Delete project-scoped media and compiled outputs
                try:
                    if m.file_path and os.path.exists(m.file_path):
                        os.remove(m.file_path)
                except Exception:
                    pass
                try:
                    if m.thumbnail_path and os.path.exists(m.thumbnail_path):
                        os.remove(m.thumbnail_path)
                except Exception:
                    pass
                db.session.delete(m)
                removed += 1
            except Exception:
                # Best-effort cleanup; continue with others
                continue

        # Delete clips
        for c in list(project.clips):
            db.session.delete(c)

        # Finally, delete the project
        db.session.delete(project)
        db.session.commit()

        # Best-effort cleanup of empty project directory tree on disk
        try:
            storage_lib.cleanup_project_tree(project_user, project_name)
        except Exception:
            pass

        flash(
            f"Project deleted. Preserved {preserved} reusable media item(s) in your library.",
            "success",
        )
        return redirect(url_for("main.projects"))
    except Exception as e:
        current_app.logger.error(f"Project delete failed: {e}")
        db.session.rollback()
        flash("Failed to delete project. Please try again.", "danger")
        return redirect(url_for("main.projects"))


@main_bp.route("/projects/<int:project_id>/upload", methods=["GET", "POST"])
@login_required
def upload_media(project_id):
    """
    Handle media file uploads for a project.

    Args:
        project_id: ID of the project to upload media to

    Returns:
        Response: Rendered upload form or redirect to project
    """
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    if request.method == "POST":
        if "file" not in request.files:
            flash("No file selected.", "danger")
            return redirect(request.url)

        file = request.files["file"]
        media_type = request.form.get("media_type")

        if file.filename == "":
            flash("No file selected.", "danger")
            return redirect(request.url)

        if not media_type or media_type not in [t.value for t in MediaType]:
            flash("Invalid media type selected.", "danger")
            return redirect(request.url)

        if file and allowed_file(file.filename):
            try:
                # Preserve the user's original name for display (basename only)
                original_name = os.path.basename(file.filename or "")
                # Derive a safe extension for storage using a sanitized variant
                safe_name = secure_filename(original_name) or "uploaded_file"
                file_ext = os.path.splitext(safe_name)[1]
                # Determine media type and subfolder
                mtype = MediaType(media_type)
                mime_type = file.content_type or "application/octet-stream"
                subfolder = _media_type_folder(mtype, mime_type)

                # Resolve destination directory using project-based storage helpers
                if subfolder == "intros":
                    user_dir = storage_lib.intros_dir(
                        current_user, project.name, library=True
                    )
                elif subfolder == "outros":
                    user_dir = storage_lib.outros_dir(
                        current_user, project.name, library=True
                    )
                elif subfolder == "transitions":
                    user_dir = storage_lib.transitions_dir(
                        current_user, project.name, library=True
                    )
                elif subfolder == "compilations":
                    user_dir = storage_lib.compilations_dir(current_user, project.name)
                elif subfolder == "clips":
                    user_dir = storage_lib.clips_dir(current_user, project.name)
                else:
                    # Images and any other types: group under project root
                    user_dir = os.path.join(
                        storage_lib.project_root(current_user, project.name),
                        subfolder,
                    )
                storage_lib.ensure_dirs(user_dir)

                unique_name = f"{uuid4().hex}{file_ext}"
                dest_path = os.path.join(user_dir, unique_name)
                file.save(dest_path)

                # Improve MIME detection if browser provided a generic or missing type
                try:
                    if (
                        not mime_type
                        or (
                            mime_type
                            in ("application/octet-stream", "binary/octet-stream")
                        )
                        or not (
                            mime_type.startswith("image")
                            or mime_type.startswith("video")
                        )
                    ):
                        # Try python-magic first
                        try:
                            import magic  # type: ignore

                            ms = magic.Magic(mime=True)
                            detected = ms.from_file(dest_path)
                            if detected:
                                mime_type = detected
                        except Exception:
                            # Fallback: mimetypes by extension
                            guessed, _ = mimetypes.guess_type(dest_path)
                            if guessed:
                                mime_type = guessed
                except Exception:
                    pass

                # Enforce storage quota after saving but before DB insert
                try:
                    from app.quotas import check_storage_quota

                    new_size = os.path.getsize(dest_path)
                    qc = check_storage_quota(current_user, additional_bytes=new_size)
                    if not qc.ok:
                        # Clean up saved file and abort
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                        flash(
                            "Storage quota exceeded. Please remove some files or upgrade your tier.",
                            "danger",
                        )
                        return redirect(
                            url_for("main.project_details", project_id=project.id)
                        )
                except Exception:
                    # If quota check fails unexpectedly, continue; enforcement will happen on next operations
                    pass

                # Thumbnail generation and metadata extraction will be handled by background task
                # (no longer block web request with ffmpeg operations)

                checksum = None
                try:
                    import hashlib as _hashlib

                    h = _hashlib.sha256()
                    with open(dest_path, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            h.update(chunk)
                    checksum = h.hexdigest()
                except Exception:
                    checksum = None

                # Create media record (metadata will be filled in by background task)
                media_file = MediaFile(
                    filename=unique_name,
                    original_filename=original_name,
                    file_path=storage_lib.instance_canonicalize(dest_path) or dest_path,
                    file_size=os.path.getsize(dest_path),
                    mime_type=mime_type,
                    media_type=mtype,
                    user_id=current_user.id,
                    project_id=project.id,
                    checksum=checksum,
                )

                db.session.add(media_file)
                db.session.commit()

                # Queue background task to generate thumbnail and extract metadata
                # (offload ffmpeg work to worker instead of blocking web request)
                try:
                    from app.tasks.media_maintenance import process_uploaded_media_task

                    # Determine queue (prefer gpu/cpu workers, same as downloads)
                    queue_name = "cpu"  # Default to CPU for media processing
                    try:
                        from app.tasks.celery_app import celery_app as _celery

                        i = _celery.control.inspect(timeout=1.0)
                        active_queues = set()
                        if i:
                            aq = i.active_queues() or {}
                            for _worker, queues in aq.items():
                                for q in queues or []:
                                    qname = (
                                        q.get("name") if isinstance(q, dict) else None
                                    )
                                    if qname:
                                        active_queues.add(qname)

                        # Prefer cpu queue, fallback to gpu
                        if "cpu" in active_queues:
                            queue_name = "cpu"
                        elif "gpu" in active_queues:
                            queue_name = "gpu"
                    except Exception:
                        pass

                    process_uploaded_media_task.apply_async(
                        args=(media_file.id,),
                        kwargs={
                            "generate_thumbnail": bool(
                                mime_type and mime_type.startswith("video")
                            )
                        },
                        queue=queue_name,
                    )
                    current_app.logger.info(
                        f"Queued media processing task for {media_file.id} on {queue_name} queue"
                    )
                except Exception as e:
                    current_app.logger.warning(
                        f"Failed to queue media processing task for {media_file.id}: {e}"
                    )

                # Sidecar files are no longer used; all metadata is kept in DB

                flash(f"File '{original_name}' uploaded successfully!", "success")
                return redirect(url_for("main.project_details", project_id=project.id))

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"File upload error: {str(e)}")
                flash(
                    "An error occurred while uploading the file. Please try again.",
                    "danger",
                )
        else:
            flash(
                "Invalid file type. Please upload a supported video or image file.",
                "danger",
            )

    return render_template(
        "main/upload_media.html",
        title="Upload Media",
        project=project,
        media_types=MediaType,
    )


@main_bp.route("/projects/<int:project_id>/compile", methods=["POST"])
@login_required
def compile_project(project_id):
    """
    Start video compilation for a project.

    Args:
        project_id: ID of the project to compile

    Returns:
        Response: JSON response with task information
    """
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    if project.status == ProjectStatus.PROCESSING:
        return jsonify({"error": "Project is already being processed"}), 400

    if project.clips.count() == 0:
        return jsonify({"error": "Project has no clips to compile"}), 400

    try:
        # Import here to avoid circular import
        from app.tasks.compile_video_v2 import (
            compile_video_task_v2 as compile_video_task,
        )

        # Update project status
        project.status = ProjectStatus.PROCESSING
        db.session.commit()

        # Start compilation task
        task = compile_video_task.delay(project_id)

        flash(
            "Video compilation started! You'll be notified when it's complete.", "info"
        )
        return jsonify(
            {
                "task_id": task.id,
                "status": "started",
                "message": "Video compilation started",
            }
        )

    except Exception as e:
        project.status = ProjectStatus.DRAFT
        db.session.rollback()
        current_app.logger.error(f"Compilation start error: {str(e)}")
        return jsonify({"error": "Failed to start video compilation"}), 500


@main_bp.route("/media")
@login_required
def media_library():
    """
    Display user's media library with all uploaded files.

    Returns:
        Response: Rendered media library template
    """
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("MEDIA_PER_PAGE", 20)

    # Filter by media type if provided, but default listing excludes clips/compilations
    type_filter = request.args.get("type")
    query = current_user.media_files

    # Always exclude CLIP and COMPILATION from the default library view (user uploads only)
    allowed_types = {
        MediaType.INTRO,
        MediaType.OUTRO,
        MediaType.TRANSITION,
        MediaType.MUSIC,
    }
    if type_filter and type_filter in [t.value for t in allowed_types]:
        query = query.filter_by(media_type=MediaType(type_filter))
    else:
        query = query.filter(MediaFile.media_type.in_(list(allowed_types)))

    media_pagination = query.order_by(MediaFile.uploaded_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Opportunistically backfill missing video metadata (duration/size) for visible items
    try:
        dirty = False
        for m in media_pagination.items:
            try:
                if not m:
                    continue
                if not m.mime_type or not m.mime_type.startswith("video"):
                    continue
                if m.duration and m.duration > 0:
                    continue
                # Only probe if file exists
                if not m.file_path or not os.path.exists(m.file_path):
                    continue
                # Use ffprobe to extract duration and basic video props
                probe_cmd = [
                    _resolve_binary(current_app, "ffprobe"),
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,r_frame_rate",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    m.file_path,
                ]
                out = subprocess.check_output(probe_cmd, text=True, encoding="utf-8")
                import json as _json

                data = _json.loads(out)
                st = (data.get("streams") or [{}])[0]
                fr = st.get("r_frame_rate") or "0/1"
                try:
                    num, den = fr.split("/")
                    m.framerate = (float(num) / float(den)) if float(den) != 0 else None
                except Exception:
                    m.framerate = None
                try:
                    m.width = (
                        int(st.get("width")) if st.get("width") is not None else m.width
                    )
                    m.height = (
                        int(st.get("height"))
                        if st.get("height") is not None
                        else m.height
                    )
                except Exception:
                    pass
                try:
                    m.duration = float((data.get("format") or {}).get("duration") or 0)
                except Exception:
                    m.duration = None
                dirty = True
            except Exception:
                continue
        if dirty:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        # Non-fatal; continue rendering
        pass

    return render_template(
        "main/media_library.html",
        title="Media Library",
        media_files=media_pagination.items,
        pagination=media_pagination,
        type_filter=type_filter,
        media_types=MediaType,
    )


@main_bp.route("/automation")
@login_required
def automation():
    """Render the Automation page for creating and managing compilation tasks and schedules.

    The page consumes the Automation APIs to list tasks, run them, and (if allowed by tier)
    create schedules. Tier gating for scheduling is enforced server-side by the API and
    reflected in the UI.
    """
    # Determine tier gating flags for UI hints only
    can_schedule = False
    max_sched = 0
    try:
        t = getattr(current_user, "tier", None)
        if t is not None:
            can_schedule = bool(getattr(t, "can_schedule_tasks", False))
            try:
                max_sched = int(getattr(t, "max_schedules_per_user", 0) or 0)
            except Exception:
                max_sched = 0
    except Exception:
        can_schedule = False
        max_sched = 0
    return render_template(
        "main/automation.html",
        title="Automation",
        can_schedule=can_schedule,
        max_schedules=max_sched,
    )


@main_bp.route("/templates")
@login_required
def templates():
    """Render the Templates page for managing reusable project configurations."""
    return render_template("main/templates.html")


@main_bp.route("/automation/tasks/<int:task_id>")
@login_required
def automation_task_details(task_id: int):
    """Render a dedicated detail page for a single automation task.

    The page consumes the Automation APIs to fetch task details and manage schedules.
    """
    # We don't load the task server-side to keep the page simple and API-driven.
    # Ownership is enforced by the APIs.
    # Tier hints for UI gating
    can_schedule = False
    max_sched = 0
    try:
        t = getattr(current_user, "tier", None)
        if t is not None:
            can_schedule = bool(getattr(t, "can_schedule_tasks", False))
            try:
                max_sched = int(getattr(t, "max_schedules_per_user", 0) or 0)
            except Exception:
                max_sched = 0
    except Exception:
        can_schedule = False
        max_sched = 0
    return render_template(
        "main/automation_task.html",
        title="Task Details",
        task_id=task_id,
        can_schedule=can_schedule,
        max_schedules=max_sched,
    )


def _media_type_folder(media_type: MediaType, mime_type: str) -> str:
    """
    Map a MediaType/mime to a folder name.

    Returns:
        str: Subfolder under the user's media directory.
    """
    try:
        if media_type == MediaType.INTRO:
            return "intros"
        if media_type == MediaType.OUTRO:
            return "outros"
        if media_type == MediaType.TRANSITION:
            return "transitions"
        if media_type == MediaType.COMPILATION:
            return "compilations"
        if media_type == MediaType.MUSIC:
            return "music"
        # If it's an image, keep in images/
        if mime_type and mime_type.startswith("image"):
            return "images"
    except Exception:
        pass
    # Default bucket for general video clips
    return "clips"


def _resolve_binary(app, name: str) -> str:
    """Resolve a binary path, preferring app config and project-local bin/.

    Resolution order per name (case-insensitive):
      - ffmpeg  -> FFMPEG_BINARY   -> ./bin/ffmpeg -> "ffmpeg"
      - ffprobe -> FFPROBE_BINARY  -> ./bin/ffprobe -> "ffprobe"
      - yt-dlp  -> YT_DLP_BINARY   -> ./bin/yt-dlp -> "yt-dlp"
    """
    lname = (name or "").lower()
    if lname == "ffmpeg":
        cfg_key = "FFMPEG_BINARY"
    elif lname == "ffprobe":
        cfg_key = "FFPROBE_BINARY"
    elif lname in ("yt-dlp", "ytdlp"):
        cfg_key = "YT_DLP_BINARY"
    else:
        cfg_key = None

    # Config-specified first
    if cfg_key:
        cfg = app.config.get(cfg_key)
        if cfg:
            return cfg

    # Project-local bin fallback
    root = app.root_path  # app/ directory
    proj_root = os.path.dirname(root)
    candidate = os.path.join(proj_root, "bin", name)
    if os.path.exists(candidate):
        return candidate
    return name


@main_bp.route("/media/upload", methods=["POST"])
@login_required
def media_upload():
    """
    Upload a media file to the user's library (not tied to a specific project).

    Accepts multipart/form-data with fields:
      - file: the uploaded file
      - media_type: one of MediaType values (intro/outro/transition/clip)
    """
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    media_type_val = request.form.get("media_type")
    if not media_type_val or media_type_val not in [t.value for t in MediaType]:
        return jsonify({"error": "Invalid media type"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type"}), 400

    # Build per-user folder with media-type subfolder
    try:
        original_name = os.path.basename(file.filename or "")
        safe_name = secure_filename(original_name) or "uploaded_file"
        file_ext = os.path.splitext(safe_name)[1]
        unique_name = f"{uuid4().hex}{file_ext}"

        mtype = MediaType(media_type_val)
        mime_type = file.content_type or "application/octet-stream"
        subfolder = _media_type_folder(mtype, mime_type)

        # Choose library destination directory (intros/outros/transitions under library; others under library/<subfolder>)
        if subfolder == "intros":
            user_dir = storage_lib.intros_dir(current_user, None, library=True)
        elif subfolder == "outros":
            user_dir = storage_lib.outros_dir(current_user, None, library=True)
        elif subfolder == "transitions":
            user_dir = storage_lib.transitions_dir(current_user, None, library=True)
        elif subfolder == "music":
            base_lib = storage_lib.library_root(current_user)
            user_dir = os.path.join(base_lib, "music")
        else:
            # clips/images/other buckets inside library root
            base_lib = storage_lib.library_root(current_user)
            user_dir = os.path.join(base_lib, subfolder)
        storage_lib.ensure_dirs(user_dir)

        dest_path = os.path.join(user_dir, unique_name)
        file.save(dest_path)

        # Enforce storage quota right after save but before DB insert
        try:
            from app.quotas import check_storage_quota

            new_size = os.path.getsize(dest_path)
            qc = check_storage_quota(current_user, additional_bytes=new_size)
            if not qc.ok:
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
                return (
                    jsonify(
                        {
                            "error": "Storage quota exceeded",
                            "remaining_bytes": qc.remaining,
                            "limit_bytes": qc.limit,
                        }
                    ),
                    403,
                )
        except Exception:
            pass

        # Compute checksum for dedupe
        checksum = None
        try:
            h = hashlib.sha256()
            with open(dest_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            checksum = h.hexdigest()
        except Exception:
            checksum = None

        # Improve MIME detection if browser provided a generic or missing type
        try:
            if (
                not mime_type
                or (mime_type in ("application/octet-stream", "binary/octet-stream"))
                or not (mime_type.startswith("image") or mime_type.startswith("video"))
            ):
                # Try python-magic first
                try:
                    import magic  # type: ignore

                    ms = magic.Magic(mime=True)
                    detected = ms.from_file(dest_path)
                    if detected:
                        mime_type = detected
                except Exception:
                    # Fallback: mimetypes by extension
                    guessed, _ = mimetypes.guess_type(dest_path)
                    if guessed:
                        mime_type = guessed
        except Exception:
            pass

        # NOTE: deduplication by checksum has been disabled project-wide.
        # Historically we would detect identical uploads (same checksum) and
        # return an existing MediaFile row while deleting the newly uploaded
        # file. That behavior caused surprising cross-project reuse and races.
        # To keep uploads deterministic and ensure every upload generates a
        # MediaFile row, we now always continue and create a new DB record
        # below even when a checksum match exists.

        # Thumbnail generation will be handled by background task
        # (no longer block API request with ffmpeg operations)

        # Create media record (metadata will be filled in by background task)
        media_file = MediaFile(
            filename=unique_name,
            original_filename=original_name,
            file_path=storage_lib.instance_canonicalize(dest_path) or dest_path,
            file_size=os.path.getsize(dest_path),
            mime_type=mime_type,
            media_type=mtype,
            user_id=current_user.id,
            project_id=None,
            checksum=checksum,
        )
        db.session.add(media_file)
        db.session.commit()

        # Queue background task to generate thumbnail and extract metadata
        try:
            from app.tasks.media_maintenance import process_uploaded_media_task

            queue_name = "cpu"
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

                if "cpu" in active_queues:
                    queue_name = "cpu"
                elif "gpu" in active_queues:
                    queue_name = "gpu"
            except Exception:
                pass

            process_uploaded_media_task.apply_async(
                args=(media_file.id,),
                kwargs={
                    "generate_thumbnail": bool(
                        mime_type and mime_type.startswith("video")
                    )
                },
                queue=queue_name,
            )
            current_app.logger.info(
                f"Queued media processing for {media_file.id} on {queue_name}"
            )
        except Exception as e:
            current_app.logger.warning(
                f"Failed to queue media processing for {media_file.id}: {e}"
            )

        # Sidecar files are no longer used; all metadata is kept in DB

        return (
            jsonify(
                {
                    "success": True,
                    "id": media_file.id,
                    "filename": media_file.filename,
                    "type": media_file.media_type.value,
                    "preview_url": url_for(
                        "main.media_preview", media_id=media_file.id
                    ),
                    "thumbnail_url": url_for(
                        "main.media_thumbnail", media_id=media_file.id
                    ),
                    "mime": media_file.mime_type,
                    "original_filename": media_file.original_filename,
                    "tags": media_file.tags or "",
                    # Extras for client-rendered cards
                    "file_size_mb": round(
                        (media_file.file_size or 0) / (1024 * 1024), 1
                    ),
                    "duration": media_file.duration,
                    "duration_formatted": media_file.duration_formatted,
                }
            ),
            201,
        )
    except Exception as e:
        current_app.logger.error(f"Library upload failed: {e}")
        db.session.rollback()
        return jsonify({"error": "Upload failed"}), 500


@main_bp.route("/media/preview/<int:media_id>")
@login_required
def media_preview(media_id: int):
    """Serve a media file preview if the user has access."""
    media = db.session.get(MediaFile, media_id)
    if not media:
        return jsonify({"error": "Not found"}), 404
    if media.user_id != current_user.id and not current_user.is_admin():
        # Avoid leaking file paths
        return jsonify({"error": "Not authorized"}), 403

    # Resolve path that may have been created on a different host/container
    resolved_path = _rebase_instance_path(media.file_path) or media.file_path
    try:
        return send_file(resolved_path, mimetype=media.mime_type, conditional=True)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404


@main_bp.route("/media/thumbnail/<int:media_id>")
@login_required
def media_thumbnail(media_id: int):
    """Serve a thumbnail for a media file if available; fallback to preview for images."""
    media = db.session.get(MediaFile, media_id)
    if not media:
        current_app.logger.warning(
            f"Thumbnail request for non-existent media_id={media_id}"
        )
        return jsonify({"error": "Not found"}), 404
    if media.user_id != current_user.id and not current_user.is_admin():
        return jsonify({"error": "Not authorized"}), 403

    current_app.logger.info(
        f"Thumbnail request for media_id={media_id}, file_path={media.file_path}, thumbnail_path={media.thumbnail_path}"
    )

    # Local resolver for media paths
    # If we have a thumbnail, serve it
    thumb_path = _rebase_instance_path(media.thumbnail_path or "") or (
        media.thumbnail_path or ""
    )
    current_app.logger.info(
        f"Resolved thumbnail path: {thumb_path}, exists={os.path.exists(thumb_path) if thumb_path else False}"
    )

    if thumb_path and os.path.exists(thumb_path):
        try:
            current_app.logger.info(f"Serving thumbnail from: {thumb_path}")
            return send_file(thumb_path, mimetype="image/jpeg", conditional=True)
        except FileNotFoundError:
            current_app.logger.warning(
                f"Thumbnail file not found despite existence check: {thumb_path}"
            )
            pass
    # Lazy-generate a thumbnail for videos on-demand
    try:
        resolved_media_path = _rebase_instance_path(media.file_path) or media.file_path
        current_app.logger.info(
            f"Attempting lazy thumbnail generation. Resolved media path: {resolved_media_path}, exists={os.path.exists(resolved_media_path)}"
        )
        if (
            media.mime_type
            and media.mime_type.startswith("video")
            and os.path.exists(resolved_media_path)
        ):
            # Store thumbnail alongside the media file
            media_dir = os.path.dirname(resolved_media_path)
            stem = os.path.splitext(os.path.basename(media.file_path))[0]
            thumb_path = os.path.join(media_dir, f"{stem}_thumb.jpg")
            current_app.logger.info(
                f"Target thumbnail path: {thumb_path}, exists={os.path.exists(thumb_path)}"
            )
            if not os.path.exists(thumb_path):
                current_app.logger.info("Generating thumbnail with ffmpeg...")
                subprocess.run(
                    [
                        _resolve_binary(current_app, "ffmpeg"),
                        "-y",
                        "-ss",
                        str(current_app.config.get("THUMBNAIL_TIMESTAMP_SECONDS", 3)),
                        "-i",
                        resolved_media_path,
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={int(current_app.config.get('THUMBNAIL_WIDTH', 480))}:-1",
                        thumb_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
                current_app.logger.info("Thumbnail generated successfully")
            else:
                current_app.logger.info("Thumbnail already exists, using existing file")
            # Save path to DB if not already set
            if not media.thumbnail_path or media.thumbnail_path != thumb_path:
                # Store canonical '/instance/…' form for portability
                media.thumbnail_path = (
                    storage_lib.instance_canonicalize(thumb_path) or thumb_path
                )
                try:
                    db.session.commit()
                    current_app.logger.info(
                        f"Updated media.thumbnail_path to: {media.thumbnail_path}"
                    )
                except Exception:
                    db.session.rollback()
            current_app.logger.info(f"Serving generated thumbnail: {thumb_path}")
            return send_file(thumb_path, mimetype="image/jpeg", conditional=True)
        else:
            current_app.logger.warning(
                f"Cannot generate thumbnail: mime_type={media.mime_type}, resolved_path_exists={os.path.exists(resolved_media_path)}"
            )
    except Exception as e:
        # Non-fatal: fall through to placeholders
        current_app.logger.error(
            f"Error during thumbnail generation: {e}", exc_info=True
        )
        pass
    # Fallback: for images, serve image; for video with no thumbnail, placeholder if available
    if media.mime_type and media.mime_type.startswith("image"):
        img_path = _rebase_instance_path(media.file_path) or media.file_path
        return send_file(img_path, mimetype=media.mime_type, conditional=True)
    placeholder_svg = os.path.join(
        current_app.root_path, "static", "img", "video_placeholder.svg"
    )
    if os.path.exists(placeholder_svg):
        return send_file(placeholder_svg, mimetype="image/svg+xml", conditional=True)
    placeholder_jpg = os.path.join(
        current_app.root_path, "static", "img", "video_placeholder.jpg"
    )
    if os.path.exists(placeholder_jpg):
        return send_file(placeholder_jpg, mimetype="image/jpeg", conditional=True)
    return jsonify({"error": "Thumbnail not available"}), 404


@main_bp.route("/media/<int:media_id>/update", methods=["POST"])
@login_required
def media_update(media_id: int):
    """Rename or change type of a media file."""
    media = db.session.get(MediaFile, media_id)
    if not media:
        return jsonify({"error": "Not found"}), 404
    if media.user_id != current_user.id and not current_user.is_admin():
        return jsonify({"error": "Not authorized"}), 403
    new_name = request.form.get("original_filename", "").strip()
    new_type = request.form.get("media_type")
    new_tags = request.form.get("tags")
    changed = False
    if new_name and new_name != media.original_filename:
        media.original_filename = new_name
        changed = True
    if new_type and new_type in [t.value for t in MediaType]:
        media.media_type = MediaType(new_type)
        changed = True
    if new_tags is not None and new_tags != (media.tags or ""):
        media.tags = new_tags
        changed = True
    if changed:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Media update failed: {e}")
            return jsonify({"error": "Update failed"}), 500
    return jsonify({"success": True})


@main_bp.route("/media/<int:media_id>/delete", methods=["POST"])
@login_required
def media_delete(media_id: int):
    """Delete a media file and its thumbnail."""
    media = db.session.get(MediaFile, media_id)
    if not media:
        return jsonify({"error": "Not found"}), 404
    if media.user_id != current_user.id and not current_user.is_admin():
        return jsonify({"error": "Not authorized"}), 403
    try:
        # Remove files from disk
        try:
            if os.path.exists(media.file_path):
                os.remove(media.file_path)
        except Exception:
            pass
        try:
            if media.thumbnail_path and os.path.exists(media.thumbnail_path):
                os.remove(media.thumbnail_path)
        except Exception:
            pass
        db.session.delete(media)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        current_app.logger.error(f"Media delete failed: {e}")
        db.session.rollback()
        return jsonify({"error": "Delete failed"}), 500


@main_bp.route("/media/bulk", methods=["POST"])
@login_required
def media_bulk():
    """Bulk operations on media: delete or change type."""
    action = request.form.get("action")
    ids = request.form.getlist("ids[]") or request.form.getlist("ids")
    if not ids:
        return jsonify({"error": "No items selected"}), 400
    q = MediaFile.query.filter(
        MediaFile.id.in_(ids), MediaFile.user_id == current_user.id
    )
    items = q.all()
    if action == "delete":
        ok = 0
        for m in items:
            try:
                if os.path.exists(m.file_path):
                    os.remove(m.file_path)
            except Exception:
                pass
            try:
                if m.thumbnail_path and os.path.exists(m.thumbnail_path):
                    os.remove(m.thumbnail_path)
            except Exception:
                pass
            db.session.delete(m)
            ok += 1
        db.session.commit()
        return jsonify({"success": True, "deleted": ok})
    elif action == "change_type":
        new_type = request.form.get("media_type")
        if not new_type or new_type not in [t.value for t in MediaType]:
            return jsonify({"error": "Invalid media type"}), 400
        for m in items:
            m.media_type = MediaType(new_type)
        db.session.commit()
        return jsonify({"success": True, "updated": len(items)})
    elif action == "set_tags":
        tags_val = request.form.get("tags", "")
        for m in items:
            m.tags = tags_val
        db.session.commit()
        return jsonify({"success": True, "updated": len(items)})
    return jsonify({"error": "Unknown action"}), 400


def allowed_file(filename):
    """
    Check if uploaded file has allowed extension.

    Args:
        filename: Name of the uploaded file

    Returns:
        bool: True if file type is allowed
    """
    if not filename:
        return False

    file_ext = os.path.splitext(filename)[1].lower().lstrip(".")
    allowed_extensions = current_app.config.get(
        "ALLOWED_VIDEO_EXTENSIONS", set()
    ) | current_app.config.get("ALLOWED_IMAGE_EXTENSIONS", set())

    return file_ext in allowed_extensions


@main_bp.route("/projects/wizard", methods=["GET"])
@login_required
def project_wizard():
    """Render the multi-step project creation and compilation wizard.

    The wizard guides the user through:
        1) choosing the route (Twitch/Discord) and basic project setup
        2) connecting services (Discord/Twitch)
        3) fetching candidate clips/messages
        4) extracting/confirming clip URLs
        5) downloading clips with progress and cancellation
        6) previewing and arranging a timeline
        7) compiling clips into a single video
        8) exporting/sharing the result

    This endpoint currently serves the UI scaffolding. Back-end wiring for
    downloading and compilation can be integrated with Celery tasks.
    """
    return render_template(
        "main/project_wizard.html",
        title="Project Wizard",
        media_types=MediaType,
    )


# Informational and Legal pages


@main_bp.route("/docs")
def documentation():
    return render_template("main/docs.html", title="Documentation")


@main_bp.route("/api-reference")
def api_reference():
    return render_template("main/api_reference.html", title="API Reference")


@main_bp.route("/support")
def support():
    return render_template("main/support.html", title="Support")


@main_bp.route("/contact")
def contact():
    return render_template("main/contact.html", title="Contact Us")


@main_bp.route("/privacy")
def privacy_policy():
    return render_template("main/privacy.html", title="Privacy Policy")


@main_bp.route("/terms")
def terms_of_service():
    return render_template("main/terms.html", title="Terms of Service")


@main_bp.route("/license")
def license_page():
    return render_template("main/license.html", title="License")


@main_bp.route("/theme/logo")
def theme_logo():
    """Serve active theme logo (no auth to allow in navbar before auth)."""
    try:
        from app.models import Theme

        theme = Theme.query.filter_by(is_active=True).first()
        if theme and theme.logo_path and os.path.exists(theme.logo_path):
            guessed, _ = mimetypes.guess_type(theme.logo_path)
            return send_file(theme.logo_path, mimetype=guessed or "image/png")
    except Exception:
        pass
    return jsonify({"error": "No logo"}), 404


@main_bp.route("/theme/favicon")
def theme_favicon():
    """Serve active theme favicon."""
    try:
        from app.models import Theme

        theme = Theme.query.filter_by(is_active=True).first()
        if theme and theme.favicon_path and os.path.exists(theme.favicon_path):
            guessed, _ = mimetypes.guess_type(theme.favicon_path)
            return send_file(theme.favicon_path, mimetype=guessed or "image/x-icon")
    except Exception:
        pass
    return jsonify({"error": "No favicon"}), 404


@main_bp.route("/theme/watermark")
def theme_watermark():
    """Serve active theme watermark image."""
    try:
        from app.models import Theme

        theme = Theme.query.filter_by(is_active=True).first()
        if theme and theme.watermark_path and os.path.exists(theme.watermark_path):
            guessed, _ = mimetypes.guess_type(theme.watermark_path)
            return send_file(theme.watermark_path, mimetype=guessed or "image/png")
    except Exception:
        pass
    return jsonify({"error": "No watermark"}), 404


@main_bp.route("/theme.css")
def theme_css():
    """Serve CSS variables and a few overrides for the active theme.

    We keep this in a separate stylesheet to avoid inline <style> lint issues
    in templates. If no active theme exists, return a minimal empty sheet.
    """
    try:
        from app.models import Theme

        theme = Theme.query.filter_by(is_active=True).first()
        if not theme:
            return Response("/* no active theme */", mimetype="text/css")

        # Compose CSS with variables and a couple of Bootstrap overrides
        css_vars = theme.as_css_vars()

        # Safeguard lookups
        def v(key, default):
            return css_vars.get(key, default)

        css = [
            ":root{",
            f"--color-primary: {v('--color-primary', '#0d6efd')};",
            f"--color-secondary: {v('--color-secondary', '#6c757d')};",
            f"--color-accent: {v('--color-accent', '#6610f2')};",
            f"--color-background: {v('--color-background', '#121212')};",
            f"--color-surface: {v('--color-surface', '#1e1e1e')};",
            f"--color-text: {v('--color-text', '#e9ecef')};",
            f"--color-muted: {v('--color-muted', '#adb5bd')};",
            f"--navbar-bg: {v('--navbar-bg', '#212529')};",
            f"--navbar-text: {v('--navbar-text', '#ffffff')};",
            f"--outline-color: {v('--outline-color', v('--color-accent', '#6610f2'))};",
            # Media/type accents
            f"--media-color-intro: {v('--media-color-intro', '#0ea5e9')};",
            f"--media-color-clip: {v('--media-color-clip', v('--color-accent', '#6610f2'))};",
            f"--media-color-outro: {v('--media-color-outro', '#f59e0b')};",
            f"--media-color-transition: {v('--media-color-transition', '#22c55e')};",
            f"--media-color-compilation: {v('--media-color-compilation', v('--color-accent', '#6610f2'))};",
            "}",
            # Map theme vars to Bootstrap CSS variables for broad component support
            ":root{",
            "--bs-primary: var(--color-primary);",
            "--bs-secondary: var(--color-secondary);",
            "--bs-body-bg: var(--color-background);",
            "--bs-body-color: var(--color-text);",
            "--bs-card-bg: var(--color-surface);",
            "--bs-card-color: var(--color-text);",
            "--bs-border-color: #30363d;",
            "--bs-link-color: var(--color-accent);",
            "--bs-link-hover-color: var(--color-primary);",
            # Bootstrap focus ring variables
            "--bs-focus-ring-color: color-mix(in srgb, var(--outline-color), transparent 70%);",
            "--bs-focus-ring-opacity: 1;",
            "--bs-focus-ring-width: 0.25rem;",
            # Progress bar accent color
            "--bs-progress-bar-bg: var(--color-accent);",
            "}",
            # Base colors
            "body{background-color: var(--color-background); color: var(--color-text);}",
            ".card{background-color: var(--color-surface); color: var(--color-text);}",
            ".text-muted{color: var(--color-muted)!important;}",
            # Navbar tweaks overriding Bootstrap classes
            ".navbar.bg-dark{background-color: var(--navbar-bg)!important;}",
            ".navbar-dark .navbar-brand, .navbar-dark .navbar-nav .nav-link{color: var(--navbar-text)!important;}",
            # Sidebar and footer accents
            ".sidebar{background-color: var(--color-surface); border-right: 1px solid var(--bs-border-color);}",
            ".footer{background-color: var(--color-background); border-top: 1px solid var(--bs-border-color);}",
            # Buttons - override base.css hardcoded hover color
            ".btn-primary{background-color: var(--bs-primary); border-color: var(--bs-primary);}",
            ".btn-primary:hover{background-color: var(--bs-primary); border-color: var(--bs-primary); filter: brightness(0.9);}",
            # Tables - align Bootstrap table vars with theme colors
            ".table{",
            "--bs-table-color: var(--bs-body-color);",
            "--bs-table-bg: var(--bs-card-bg);",
            "--bs-table-border-color: var(--bs-border-color);",
            "--bs-table-striped-bg: color-mix(in srgb, var(--bs-table-bg), #ffffff 6%);",
            "--bs-table-striped-color: var(--bs-body-color);",
            "--bs-table-active-bg: color-mix(in srgb, var(--bs-table-bg), #ffffff 10%);",
            "--bs-table-active-color: var(--bs-body-color);",
            "--bs-table-hover-bg: color-mix(in srgb, var(--bs-table-bg), #ffffff 8%);",
            "--bs-table-hover-color: var(--bs-body-color);",
            "}",
            ".table-light{",
            "--bs-table-color: var(--bs-body-color);",
            "--bs-table-bg: color-mix(in srgb, var(--bs-card-bg), #ffffff 8%);",
            "--bs-table-border-color: var(--bs-border-color);",
            "--bs-table-striped-bg: color-mix(in srgb, var(--bs-table-bg), #ffffff 6%);",
            "--bs-table-striped-color: var(--bs-body-color);",
            "--bs-table-active-bg: color-mix(in srgb, var(--bs-table-bg), #ffffff 10%);",
            "--bs-table-active-color: var(--bs-body-color);",
            "--bs-table-hover-bg: color-mix(in srgb, var(--bs-table-bg), #ffffff 8%);",
            "--bs-table-hover-color: var(--bs-body-color);",
            "}",
            ".table thead th{border-bottom-color: var(--bs-border-color)!important;}",
            # Generic focus outline fallback
            ":focus{outline-color: var(--outline-color);}",
        ]
        return Response("\n".join(css), mimetype="text/css")
    except Exception:
        return Response("/* theme css error */", mimetype="text/css")


@main_bp.route("/p/<public_id>/download")
@login_required
def download_compiled_output_by_public(public_id: str):
    """Download the compiled output video for a project if available."""
    # Owner-only download via opaque id
    project = Project.query.filter_by(
        public_id=public_id, user_id=current_user.id
    ).first_or_404()

    # Resolve compiled file path with robust fallbacks, similar to owner route
    final_path = None
    # Prefer associated MediaFile entries
    try:
        compiled = (
            project.media_files.filter_by(media_type=MediaType.COMPILATION)
            .order_by(MediaFile.uploaded_at.desc())
            .all()
        )
        for mf in compiled:
            if (
                project.output_filename
                and mf.filename == project.output_filename
                and mf.file_path
            ):
                cand = _rebase_instance_path(mf.file_path) or mf.file_path
                if os.path.exists(cand):
                    final_path = cand
                    break
        if not final_path and compiled:
            mf = compiled[0]
            cand = _rebase_instance_path(mf.file_path) if mf.file_path else None
            if cand and os.path.exists(cand):
                final_path = cand
    except Exception:
        final_path = None

    # Fallbacks based on filename and storage layout
    try:
        from app.storage import clips_dir as _clips_dir
        from app.storage import compilations_dir as _comp_dir

        user = project.owner
        new_candidate = (
            os.path.join(_comp_dir(user, project.name), project.output_filename)
            if project.output_filename
            else None
        )
        clips_candidate = (
            os.path.join(_clips_dir(user, project.name), project.output_filename)
            if project.output_filename
            else None
        )
    except Exception:
        new_candidate = None
        clips_candidate = None
    legacy_candidate = (
        os.path.join(current_app.instance_path, "compilations", project.output_filename)
        if project.output_filename
        else None
    )
    if not final_path:
        for cand in (new_candidate, clips_candidate, legacy_candidate):
            if cand and os.path.exists(cand):
                final_path = cand
                break
    if not final_path or not os.path.exists(final_path):
        return jsonify({"error": "Compiled file not found"}), 404

    # Guess mime type based on extension
    guessed, _ = mimetypes.guess_type(final_path)
    mimetype = guessed or "application/octet-stream"
    return send_file(
        final_path,
        mimetype=mimetype,
        as_attachment=True,
        download_name=project.output_filename,
    )


@main_bp.route("/p/<public_id>/preview")
@login_required
def preview_compiled_output_by_public(public_id: str):
    """Stream the compiled output video inline for preview if available.

    Supports HTTP Range requests so the HTML5 <video> element can seek.
    """
    # Owner-only preview via opaque id
    project = Project.query.filter_by(
        public_id=public_id, user_id=current_user.id
    ).first_or_404()

    # Resolve compiled file path with robust fallbacks, similar to owner route
    final_path = None
    # Prefer associated MediaFile entries
    try:
        compiled = (
            project.media_files.filter_by(media_type=MediaType.COMPILATION)
            .order_by(MediaFile.uploaded_at.desc())
            .all()
        )
        for mf in compiled:
            if (
                project.output_filename
                and mf.filename == project.output_filename
                and mf.file_path
            ):
                cand = _rebase_instance_path(mf.file_path) or mf.file_path
                if os.path.exists(cand):
                    final_path = cand
                    break
        if not final_path and compiled:
            mf = compiled[0]
            cand = _rebase_instance_path(mf.file_path) if mf.file_path else None
            if cand and os.path.exists(cand):
                final_path = cand
    except Exception:
        final_path = None

    # Fallbacks based on filename and storage layout
    try:
        from app.storage import clips_dir as _clips_dir
        from app.storage import compilations_dir as _comp_dir

        user = project.owner
        new_candidate = (
            os.path.join(_comp_dir(user, project.name), project.output_filename)
            if project.output_filename
            else None
        )
        clips_candidate = (
            os.path.join(_clips_dir(user, project.name), project.output_filename)
            if project.output_filename
            else None
        )
    except Exception:
        new_candidate = None
        clips_candidate = None
    legacy_candidate = (
        os.path.join(current_app.instance_path, "compilations", project.output_filename)
        if project.output_filename
        else None
    )
    if not final_path:
        for cand in (new_candidate, clips_candidate, legacy_candidate):
            if cand and os.path.exists(cand):
                final_path = cand
                break
    if not final_path or not os.path.exists(final_path):
        return jsonify({"error": "Compiled file not found"}), 404

    guessed, _ = mimetypes.guess_type(final_path)
    mimetype = guessed or "video/mp4"

    # Range support
    range_header = request.headers.get("Range", None)
    if not range_header:
        return send_file(final_path, mimetype=mimetype, conditional=True)

    try:
        file_size = os.path.getsize(final_path)
        # Parse Range: bytes=start-end
        units, _, rng = range_header.partition("=")
        if units != "bytes":
            # Not supported; send whole file
            return send_file(final_path, mimetype=mimetype, conditional=True)
        start_str, _, end_str = rng.partition("-")
        start = int(start_str) if start_str.isdigit() else 0
        end = int(end_str) if end_str.isdigit() else file_size - 1
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))
        length = end - start + 1

        with open(final_path, "rb") as f:
            f.seek(start)
            data = f.read(length)

        rv = Response(data, 206, mimetype=mimetype, direct_passthrough=True)
        rv.headers.add("Content-Range", f"bytes {start}-{end}/{file_size}")
        rv.headers.add("Accept-Ranges", "bytes")
        rv.headers.add("Content-Length", str(length))
        return rv
    except Exception:
        # Fallback to full file
        return send_file(final_path, mimetype=mimetype, conditional=True)


@main_bp.route("/projects/<int:project_id>/download")
@login_required
def download_compiled_output(project_id: int):
    """Download the compiled output video (ownership enforced)."""
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    if not project.output_filename:
        return jsonify({"error": "No compiled output available"}), 404

    # Try to resolve via associated MediaFile first (most reliable)
    final_path = None
    try:
        compiled = (
            project.media_files.filter_by(media_type=MediaType.COMPILATION)
            .order_by(MediaFile.uploaded_at.desc())
            .all()
        )
        # Prefer exact filename match
        for mf in compiled:
            if mf.filename == project.output_filename and mf.file_path:
                cand = _rebase_instance_path(mf.file_path) or mf.file_path
                if os.path.exists(cand):
                    final_path = cand
                    break
        # Fallback to latest compilation's path
        if not final_path and compiled:
            mf = compiled[0]
            cand = _rebase_instance_path(mf.file_path) if mf.file_path else None
            if cand and os.path.exists(cand):
                final_path = cand
    except Exception:
        final_path = None

    # Fallbacks: new per-project layout, clips dir (historical), legacy global
    if not final_path:
        try:
            from app.storage import clips_dir as _clips_dir
            from app.storage import compilations_dir as _comp_dir

            user = project.owner
            new_candidate = os.path.join(
                _comp_dir(user, project.name), project.output_filename
            )
            clips_candidate = os.path.join(
                _clips_dir(user, project.name), project.output_filename
            )
        except Exception:
            new_candidate = None
            clips_candidate = None
        legacy_candidate = os.path.join(
            current_app.instance_path, "compilations", project.output_filename
        )
        for cand in (new_candidate, clips_candidate, legacy_candidate):
            if cand and os.path.exists(cand):
                final_path = cand
                break

    if not final_path or not os.path.exists(final_path):
        return jsonify({"error": "Compiled file not found"}), 404

    guessed, _ = mimetypes.guess_type(final_path)
    mimetype = guessed or "application/octet-stream"
    return send_file(
        final_path,
        mimetype=mimetype,
        as_attachment=True,
        download_name=project.output_filename,
    )


@main_bp.route("/projects/<int:project_id>/preview")
@login_required
def preview_compiled_output(project_id: int):
    """Stream the compiled output inline with Range support (ownership enforced)."""
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    if not project.output_filename:
        return jsonify({"error": "No compiled output available"}), 404

    # Try MediaFile first
    final_path = None
    try:
        compiled = (
            project.media_files.filter_by(media_type=MediaType.COMPILATION)
            .order_by(MediaFile.uploaded_at.desc())
            .all()
        )
        for mf in compiled:
            if mf.filename == project.output_filename and mf.file_path:
                cand = _rebase_instance_path(mf.file_path) or mf.file_path
                if os.path.exists(cand):
                    final_path = cand
                    break
        if not final_path and compiled:
            mf = compiled[0]
            cand = _rebase_instance_path(mf.file_path) if mf.file_path else None
            if cand and os.path.exists(cand):
                final_path = cand
    except Exception:
        final_path = None

    if not final_path:
        try:
            from app.storage import clips_dir as _clips_dir
            from app.storage import compilations_dir as _comp_dir

            user = project.owner
            new_candidate = os.path.join(
                _comp_dir(user, project.name), project.output_filename
            )
            clips_candidate = os.path.join(
                _clips_dir(user, project.name), project.output_filename
            )
        except Exception:
            new_candidate = None
            clips_candidate = None
        legacy_candidate = os.path.join(
            current_app.instance_path, "compilations", project.output_filename
        )
        for cand in (new_candidate, clips_candidate, legacy_candidate):
            if cand and os.path.exists(cand):
                final_path = cand
                break

    if not final_path or not os.path.exists(final_path):
        return jsonify({"error": "Compiled file not found"}), 404

    guessed, _ = mimetypes.guess_type(final_path)
    mimetype = guessed or "video/mp4"

    range_header = request.headers.get("Range", None)
    if not range_header:
        return send_file(final_path, mimetype=mimetype, conditional=True)

    try:
        file_size = os.path.getsize(final_path)
        units, _, rng = range_header.partition("=")
        if units != "bytes":
            return send_file(final_path, mimetype=mimetype, conditional=True)
        start_str, _, end_str = rng.partition("-")
        start = int(start_str) if start_str.isdigit() else 0
        end = int(end_str) if end_str.isdigit() else file_size - 1
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))
        length = end - start + 1

        with open(final_path, "rb") as f:
            f.seek(start)
            data = f.read(length)

        rv = Response(data, 206, mimetype=mimetype, direct_passthrough=True)
        rv.headers.add("Content-Range", f"bytes {start}-{end}/{file_size}")
        rv.headers.add("Accept-Ranges", "bytes")
        rv.headers.add("Content-Length", str(length))
        return rv
    except Exception:
        return send_file(final_path, mimetype=mimetype, conditional=True)


@main_bp.route("/projects/<int:project_id>/preview", methods=["GET"])
@login_required
def preview_preview_file(project_id: int):
    """Stream the preview file with Range support (ownership enforced)."""
    from sqlalchemy import select

    project = db.session.execute(
        select(Project).filter_by(id=project_id, user_id=current_user.id)
    ).scalar_one_or_none()

    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not project.preview_filename:
        return jsonify({"error": "No preview available"}), 404

    # Build path to preview file
    from app.storage import get_project_output_dir

    output_dir = get_project_output_dir(project.user_id, project.id)
    preview_path = os.path.join(output_dir, project.preview_filename)

    if not os.path.exists(preview_path):
        return jsonify({"error": "Preview file not found"}), 404

    guessed, _ = mimetypes.guess_type(preview_path)
    mimetype = guessed or "video/mp4"

    range_header = request.headers.get("Range", None)
    if not range_header:
        return send_file(preview_path, mimetype=mimetype, conditional=True)

    try:
        file_size = os.path.getsize(preview_path)
        units, _, rng = range_header.partition("=")
        if units != "bytes":
            return send_file(preview_path, mimetype=mimetype, conditional=True)
        start_str, _, end_str = rng.partition("-")
        start = int(start_str) if start_str.isdigit() else 0
        end = int(end_str) if end_str.isdigit() else file_size - 1
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))
        length = end - start + 1

        with open(preview_path, "rb") as f:
            f.seek(start)
            data = f.read(length)

        rv = Response(data, 206, mimetype=mimetype, direct_passthrough=True)
        rv.headers.add("Content-Range", f"bytes {start}-{end}/{file_size}")
        rv.headers.add("Accept-Ranges", "bytes")
        rv.headers.add("Content-Length", str(length))
        return rv
    except Exception:
        return send_file(preview_path, mimetype=mimetype, conditional=True)


@main_bp.route("/teams")
@login_required
def teams_list():
    """Display list of teams the user owns or belongs to."""
    return render_template("main/teams.html")


@main_bp.route("/teams/<int:team_id>")
@login_required
def team_details(team_id):
    """Display detailed view of a team."""
    from sqlalchemy import select

    from app.models import Team, TeamMembership, User
    from app.team_permissions import (
        can_delete_team,
        can_manage_team,
        get_user_team_role,
    )

    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        flash("Team not found", "error")
        return redirect(url_for("main.teams_list"))

    # Check access
    user_role = get_user_team_role(team)
    is_owner = team.owner_id == current_user.id

    if not is_owner and not user_role:
        flash("You don't have access to this team", "error")
        return redirect(url_for("main.teams_list"))

    # Get members
    members = []
    owner = db.session.execute(
        select(User).where(User.id == team.owner_id)
    ).scalar_one_or_none()
    if owner:
        members.append(
            {
                "user_id": owner.id,
                "username": owner.username,
                "email": owner.email,
                "role": "owner",
                "joined_at": team.created_at,
            }
        )

    memberships = db.session.execute(
        select(TeamMembership)
        .where(TeamMembership.team_id == team_id)
        .order_by(TeamMembership.joined_at)
    ).scalars()

    for membership in memberships:
        user = membership.user
        members.append(
            {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "role": membership.role.value,
                "joined_at": membership.joined_at,
            }
        )

    # Get shared projects
    projects = db.session.execute(
        select(Project)
        .where(Project.team_id == team_id)
        .order_by(Project.created_at.desc())
    ).scalars()

    return render_template(
        "main/team_details.html",
        team=team,
        members=members,
        projects=list(projects),
        is_owner=is_owner,
        user_role=user_role,
        can_manage=can_manage_team(team),
        can_delete=can_delete_team(team),
    )


@main_bp.route("/invitations/<token>")
def invitation(token):
    """Display team invitation acceptance page."""
    from sqlalchemy import select

    from app.models import TeamInvitation

    invitation = db.session.execute(
        select(TeamInvitation).where(TeamInvitation.token == token)
    ).scalar_one_or_none()

    if not invitation:
        flash("Invitation not found", "error")
        return redirect(url_for("main.index"))

    # Check if already responded
    if invitation.status != "pending":
        status_messages = {
            "accepted": "This invitation has already been accepted.",
            "declined": "This invitation has been declined.",
            "expired": "This invitation has expired.",
        }
        flash(
            status_messages.get(
                invitation.status, "This invitation is no longer valid"
            ),
            "warning",
        )
        return redirect(url_for("main.index"))

    # Check if expired
    if not invitation.is_valid():
        flash("This invitation has expired", "error")
        return redirect(url_for("main.index"))

    return render_template("main/invitation.html", invitation=invitation)
