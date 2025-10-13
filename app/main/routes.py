"""
Main application routes for the ClippyFront platform.

This module handles the core user-facing routes including the landing page,
dashboard, project management, and media upload functionality.
"""
import os
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
    Landing page for the ClippyFront platform.

    Displays information about the platform and provides links to
    authentication for new and existing users.

    Returns:
        Response: Rendered landing page template
    """
    return render_template(
        "main/index.html",
        title="ClippyFront - Video Compilation Platform",
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


@main_bp.route("/projects/new", methods=["GET", "POST"])
@login_required
def create_project():
    """
    Create a new video compilation project.

    GET: Display project creation form
    POST: Process form and create new project

    Returns:
        Response: Rendered form or redirect to project details
    """
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        max_clip_duration = request.form.get("max_clip_duration", 30, type=int)
        output_resolution = request.form.get("output_resolution", "1080p")

        if not name:
            flash("Project name is required.", "danger")
            return redirect(url_for("main.create_project"))

        try:
            project = Project(
                name=name,
                description=description or None,
                user_id=current_user.id,
                max_clip_duration=max_clip_duration,
                output_resolution=output_resolution,
            )

            db.session.add(project)
            db.session.commit()

            flash(f"Project '{name}' created successfully!", "success")
            return redirect(url_for("main.project_details", project_id=project.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Project creation error for user {current_user.id}: {str(e)}"
            )
            flash(
                "An error occurred while creating the project. Please try again.",
                "danger",
            )

    return render_template("main/create_project.html", title="New Project")


@main_bp.route("/projects/<int:project_id>")
@login_required
def project_details(project_id):
    """
    Display detailed project information and management interface.

    Args:
        project_id: ID of the project to display

    Returns:
        Response: Rendered project details template or 404
    """
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first_or_404()

    # Get project clips with ordering
    clips = project.clips.order_by(Clip.order_index.asc(), Clip.created_at.asc()).all()

    # Get project media files
    media_files = project.media_files.order_by(MediaFile.uploaded_at.desc()).all()

    return render_template(
        "main/project_details.html",
        title=project.name,
        project=project,
        clips=clips,
        media_files=media_files,
    )


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
                # Generate secure filename
                filename = secure_filename(file.filename)
                if not filename:
                    filename = "uploaded_file"

                # Create unique filename
                file_ext = os.path.splitext(filename)[1]
                unique_filename = f"{current_user.id}_{project_id}_{MediaFile.query.count() + 1}{file_ext}"

                # Save file
                upload_path = os.path.join(
                    current_app.instance_path, current_app.config["UPLOAD_FOLDER"]
                )
                file_path = os.path.join(upload_path, unique_filename)
                file.save(file_path)

                # Create media file record
                media_file = MediaFile(
                    filename=unique_filename,
                    original_filename=filename,
                    file_path=file_path,
                    file_size=os.path.getsize(file_path),
                    mime_type=file.content_type or "application/octet-stream",
                    media_type=MediaType(media_type),
                    user_id=current_user.id,
                    project_id=project.id,
                )

                db.session.add(media_file)
                db.session.commit()

                flash(f"File '{filename}' uploaded successfully!", "success")
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
        # If it's an image, keep in images/
        if mime_type and mime_type.startswith("image"):
            return "images"
    except Exception:
        pass
    # Default bucket for general video clips
    return "clips"


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

        media_file = MediaFile(
            filename=unique_name,
            original_filename=safe_name,
            file_path=dest_path,
            file_size=os.path.getsize(dest_path),
            mime_type=mime_type,
            media_type=mtype,
            user_id=current_user.id,
            project_id=None,
        )
        db.session.add(media_file)
        db.session.commit()

        return (
            jsonify(
                {
                    "success": True,
                    "id": media_file.id,
                    "filename": media_file.filename,
                    "type": media_file.media_type.value,
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
    media = MediaFile.query.get_or_404(media_id)
    if media.user_id != current_user.id and not current_user.is_admin():
        # Avoid leaking file paths
        return jsonify({"error": "Not authorized"}), 403
    try:
        return send_file(media.file_path, mimetype=media.mime_type, conditional=True)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404


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
