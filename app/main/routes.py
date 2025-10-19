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

from app.models import Clip, MediaFile, MediaType, Project, ProjectStatus, db
from app.version import get_version

# Create main blueprint
main_bp = Blueprint("main", __name__)


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
    # Get user's projects with counts
    projects = current_user.projects.order_by(Project.updated_at.desc()).limit(10).all()

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
        projects=projects,
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

    return render_template(
        "main/projects.html",
        title="My Projects",
        projects=projects_pagination.items,
        pagination=projects_pagination,
        status_filter=status_filter,
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

    # Get project clips with ordering
    clips = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc()).all()

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
        media_files=media_files,
        intros=intros,
        outros=outros,
        transitions=transitions,
        download_url=download_url,
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
    clips = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc()).all()
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
        media_files=media_files,
        intros=intros,
        outros=outros,
        transitions=transitions,
        download_url=download_url,
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
                # Secure source name
                safe_name = secure_filename(file.filename) or "uploaded_file"
                file_ext = os.path.splitext(safe_name)[1]
                # Determine media type and subfolder
                mtype = MediaType(media_type)
                mime_type = file.content_type or "application/octet-stream"
                subfolder = _media_type_folder(mtype, mime_type)

                # Build per-user destination path
                base_upload = os.path.join(
                    current_app.instance_path, current_app.config["UPLOAD_FOLDER"]
                )
                user_dir = os.path.join(base_upload, str(current_user.id), subfolder)
                os.makedirs(user_dir, exist_ok=True)

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

                # Generate thumbnail for videos
                thumb_path = None
                if mime_type and mime_type.startswith("video"):
                    try:
                        thumbs_dir = os.path.join(
                            base_upload, str(current_user.id), "thumbnails"
                        )
                        os.makedirs(thumbs_dir, exist_ok=True)
                        thumb_name = f"{uuid4().hex}.jpg"
                        thumb_path = os.path.join(thumbs_dir, thumb_name)
                        # Extract a frame at 1s; scale width to 480 keeping aspect ratio
                        subprocess.run(
                            [
                                _resolve_binary(current_app, "ffmpeg"),
                                "-y",
                                "-ss",
                                "1",
                                "-i",
                                dest_path,
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
                    except Exception as e:
                        current_app.logger.warning(
                            f"Thumbnail generation failed (project upload): {e}"
                        )
                        thumb_path = None

                # Optionally probe basic video metadata and checksum
                v_duration = None
                v_width = None
                v_height = None
                v_fps = None
                try:
                    if mime_type and mime_type.startswith("video"):
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
                            dest_path,
                        ]
                        out = subprocess.check_output(
                            probe_cmd, text=True, encoding="utf-8"
                        )
                        import json as _json

                        data = _json.loads(out)
                        st = (data.get("streams") or [{}])[0]
                        fr = st.get("r_frame_rate") or "0/1"
                        try:
                            num, den = fr.split("/")
                            v_fps = (
                                (float(num) / float(den)) if float(den) != 0 else None
                            )
                        except Exception:
                            v_fps = None
                        v_width = st.get("width")
                        v_height = st.get("height")
                        try:
                            v_duration = float(
                                (data.get("format") or {}).get("duration")
                            )
                        except Exception:
                            v_duration = None
                except Exception:
                    pass

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

                # Create media record
                media_file = MediaFile(
                    filename=unique_name,
                    original_filename=safe_name,
                    file_path=dest_path,
                    file_size=os.path.getsize(dest_path),
                    mime_type=mime_type,
                    media_type=mtype,
                    user_id=current_user.id,
                    project_id=project.id,
                    thumbnail_path=thumb_path,
                    checksum=checksum,
                    duration=v_duration,
                    width=v_width,
                    height=v_height,
                    framerate=v_fps,
                )

                db.session.add(media_file)
                db.session.commit()

                # Sidecar files are no longer used; all metadata is kept in DB

                flash(f"File '{safe_name}' uploaded successfully!", "success")
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
        from app.tasks.video_processing import compile_video_task

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

    # Filter by media type if provided
    type_filter = request.args.get("type")
    query = current_user.media_files

    if type_filter and type_filter in [t.value for t in MediaType]:
        query = query.filter_by(media_type=MediaType(type_filter))

    media_pagination = query.order_by(MediaFile.uploaded_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template(
        "main/media_library.html",
        title="Media Library",
        media_files=media_pagination.items,
        pagination=media_pagination,
        type_filter=type_filter,
        media_types=MediaType,
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
        safe_name = secure_filename(file.filename) or "uploaded_file"
        file_ext = os.path.splitext(safe_name)[1]
        unique_name = f"{uuid4().hex}{file_ext}"

        mtype = MediaType(media_type_val)
        mime_type = file.content_type or "application/octet-stream"
        subfolder = _media_type_folder(mtype, mime_type)

        base_upload = os.path.join(
            current_app.instance_path, current_app.config["UPLOAD_FOLDER"]
        )
        user_dir = os.path.join(base_upload, str(current_user.id), subfolder)
        os.makedirs(user_dir, exist_ok=True)

        dest_path = os.path.join(user_dir, unique_name)
        file.save(dest_path)

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

        # If same content already exists for this user, reuse existing DB row and remove duplicate file
        try:
            if checksum:
                existing = (
                    db.session.query(MediaFile)
                    .filter_by(user_id=current_user.id, checksum=checksum)
                    .first()
                )
                if existing and os.path.exists(existing.file_path):
                    # Remove the new file; return existing record
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                    return (
                        jsonify(
                            {
                                "success": True,
                                "id": existing.id,
                                "filename": existing.filename,
                                "type": existing.media_type.value,
                                "preview_url": url_for(
                                    "main.media_preview", media_id=existing.id
                                ),
                                "thumbnail_url": url_for(
                                    "main.media_thumbnail", media_id=existing.id
                                ),
                                "mime": existing.mime_type,
                                "original_filename": existing.original_filename,
                                "tags": existing.tags or "",
                            }
                        ),
                        200,
                    )
        except Exception:
            pass

        # Generate thumbnail for videos (deterministic name; reuse if exists)
        thumb_path = None
        if mime_type and mime_type.startswith("video"):
            try:
                thumbs_dir = os.path.join(
                    base_upload, str(current_user.id), "thumbnails"
                )
                os.makedirs(thumbs_dir, exist_ok=True)
                stem = os.path.splitext(unique_name)[0]
                thumb_path = os.path.join(thumbs_dir, f"{stem}.jpg")
                if not os.path.exists(thumb_path):
                    # Extract a frame at 1s; scale width to 480 keeping aspect ratio
                    subprocess.run(
                        [
                            _resolve_binary(current_app, "ffmpeg"),
                            "-y",
                            "-ss",
                            "1",
                            "-i",
                            dest_path,
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
            except Exception as e:
                current_app.logger.warning(f"Thumbnail generation failed: {e}")
                thumb_path = None

        # Optionally probe basic video metadata
        v_duration = None
        v_width = None
        v_height = None
        v_fps = None
        try:
            if mime_type and mime_type.startswith("video"):
                # Use ffprobe via subprocess for portability
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
                    dest_path,
                ]
                out = subprocess.check_output(probe_cmd, text=True, encoding="utf-8")
                import json as _json

                data = _json.loads(out)
                st = (data.get("streams") or [{}])[0]
                fr = st.get("r_frame_rate") or "0/1"
                try:
                    num, den = fr.split("/")
                    v_fps = (float(num) / float(den)) if float(den) != 0 else None
                except Exception:
                    v_fps = None
                v_width = st.get("width")
                v_height = st.get("height")
                try:
                    v_duration = float((data.get("format") or {}).get("duration"))
                except Exception:
                    v_duration = None
        except Exception:
            pass

        media_file = MediaFile(
            filename=unique_name,
            original_filename=safe_name,
            file_path=dest_path,
            file_size=os.path.getsize(dest_path),
            mime_type=mime_type,
            media_type=mtype,
            user_id=current_user.id,
            project_id=None,
            thumbnail_path=thumb_path,
            checksum=checksum,
            duration=v_duration,
            width=v_width,
            height=v_height,
            framerate=v_fps,
        )
        db.session.add(media_file)
        db.session.commit()

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
    def _resolve_media_server_path(orig_path: str) -> str:
        try:
            if orig_path and os.path.exists(orig_path):
                return orig_path
            ap = (orig_path or "").strip()
            if not ap:
                return orig_path
            alias_from = os.getenv("MEDIA_PATH_ALIAS_FROM")
            alias_to = os.getenv("MEDIA_PATH_ALIAS_TO")
            if alias_from and alias_to and ap.startswith(alias_from):
                cand = alias_to + ap[len(alias_from) :]
                if os.path.exists(cand):
                    return cand
            marker = "/instance/"
            if marker in ap:
                try:
                    suffix = ap.split(marker, 1)[1]
                    cand = os.path.join(current_app.instance_path, suffix)
                    if os.path.exists(cand):
                        return cand
                except Exception:
                    pass
        except Exception:
            pass
        return orig_path

    resolved_path = _resolve_media_server_path(media.file_path)
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
        return jsonify({"error": "Not found"}), 404
    if media.user_id != current_user.id and not current_user.is_admin():
        return jsonify({"error": "Not authorized"}), 403

    # Local resolver for media paths
    def _resolve_media_server_path(orig_path: str) -> str:
        try:
            if orig_path and os.path.exists(orig_path):
                return orig_path
            ap = (orig_path or "").strip()
            if not ap:
                return orig_path
            alias_from = os.getenv("MEDIA_PATH_ALIAS_FROM")
            alias_to = os.getenv("MEDIA_PATH_ALIAS_TO")
            if alias_from and alias_to and ap.startswith(alias_from):
                cand = alias_to + ap[len(alias_from) :]
                if os.path.exists(cand):
                    return cand
            marker = "/instance/"
            if marker in ap:
                try:
                    suffix = ap.split(marker, 1)[1]
                    cand = os.path.join(current_app.instance_path, suffix)
                    if os.path.exists(cand):
                        return cand
                except Exception:
                    pass
        except Exception:
            pass
        return orig_path

    # If we have a thumbnail, serve it
    thumb_path = _resolve_media_server_path(media.thumbnail_path or "")
    if thumb_path and os.path.exists(thumb_path):
        try:
            return send_file(thumb_path, mimetype="image/jpeg", conditional=True)
        except FileNotFoundError:
            pass
    # Lazy-generate a thumbnail for videos on-demand
    try:
        if (
            media.mime_type
            and media.mime_type.startswith("video")
            and os.path.exists(_resolve_media_server_path(media.file_path))
        ):
            base_upload = os.path.join(
                current_app.instance_path, current_app.config["UPLOAD_FOLDER"]
            )
            thumbs_dir = os.path.join(base_upload, str(media.user_id), "thumbnails")
            os.makedirs(thumbs_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(media.file_path))[0]
            thumb_path = os.path.join(thumbs_dir, f"{stem}.jpg")
            if not os.path.exists(thumb_path):
                subprocess.run(
                    [
                        _resolve_binary(current_app, "ffmpeg"),
                        "-y",
                        "-ss",
                        "1",
                        "-i",
                        _resolve_media_server_path(media.file_path),
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
            # Save path to DB if not already set
            if not media.thumbnail_path or media.thumbnail_path != thumb_path:
                media.thumbnail_path = thumb_path
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
            return send_file(thumb_path, mimetype="image/jpeg", conditional=True)
    except Exception:
        # Non-fatal: fall through to placeholders
        pass
    # Fallback: for images, serve image; for video with no thumbnail, placeholder if available
    if media.mime_type and media.mime_type.startswith("image"):
        return send_file(media.file_path, mimetype=media.mime_type, conditional=True)
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


@main_bp.route("/p/<public_id>/download")
@login_required
def download_compiled_output_by_public(public_id: str):
    """Download the compiled output video for a project if available."""
    project = Project.query.filter_by(
        public_id=public_id, user_id=current_user.id
    ).first_or_404()

    if not project.output_filename:
        return jsonify({"error": "No compiled output available"}), 404

    # The compiled file is stored under instance/compilations/<filename>
    final_path = os.path.join(
        current_app.instance_path, "compilations", project.output_filename
    )
    if not os.path.exists(final_path):
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
    project = Project.query.filter_by(
        public_id=public_id, user_id=current_user.id
    ).first_or_404()

    if not project.output_filename:
        return jsonify({"error": "No compiled output available"}), 404

    final_path = os.path.join(
        current_app.instance_path, "compilations", project.output_filename
    )
    if not os.path.exists(final_path):
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

        from flask import Response

        rv = Response(data, 206, mimetype=mimetype, direct_passthrough=True)
        rv.headers.add("Content-Range", f"bytes {start}-{end}/{file_size}")
        rv.headers.add("Accept-Ranges", "bytes")
        rv.headers.add("Content-Length", str(length))
        return rv
    except Exception:
        # Fallback to full file
        return send_file(final_path, mimetype=mimetype, conditional=True)
