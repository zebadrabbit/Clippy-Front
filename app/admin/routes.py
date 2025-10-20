"""
Admin panel routes for Clippy platform management.

This module provides administrative functionality including user management,
system monitoring, and platform configuration for admin users only.
"""
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from app.models import (
    Clip,
    MediaFile,
    MediaType,
    ProcessingJob,
    Project,
    ProjectStatus,
    SystemSetting,
    User,
    UserRole,
    db,
)
from app.tasks.celery_app import celery_app
from app.tasks.media_maintenance import (
    dedupe_media_task,
    reindex_media_task,
)
from app.version import get_changelog, get_version

# Create admin blueprint
admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    """
    Decorator to ensure only admin users can access admin routes.

    Args:
        f: Function to wrap

    Returns:
        Function: Wrapped function with admin check
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash("Access denied. Admin privileges required.", "danger")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)

    return decorated_function


@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    """
    Admin dashboard with system overview and statistics.

    Displays key metrics, recent activity, and system status
    for platform administrators.

    Returns:
        Response: Rendered admin dashboard template
    """
    # Get system statistics
    stats = {
        "total_users": User.query.count(),
        "active_users": User.query.filter_by(is_active=True).count(),
        "admin_users": User.query.filter_by(role=UserRole.ADMIN).count(),
        "total_projects": Project.query.count(),
        "active_projects": Project.query.filter_by(
            status=ProjectStatus.PROCESSING
        ).count(),
        "completed_projects": Project.query.filter_by(
            status=ProjectStatus.COMPLETED
        ).count(),
        "total_media_files": MediaFile.query.count(),
        "total_clips": Clip.query.count(),
        "pending_jobs": ProcessingJob.query.filter_by(status="pending").count(),
    }

    # Get recent activity (last 24 hours)
    yesterday = datetime.utcnow() - timedelta(days=1)
    recent_stats = {
        "new_users": User.query.filter(User.created_at >= yesterday).count(),
        "new_projects": Project.query.filter(Project.created_at >= yesterday).count(),
        "new_media_files": MediaFile.query.filter(
            MediaFile.uploaded_at >= yesterday
        ).count(),
        "completed_jobs": ProcessingJob.query.filter(
            ProcessingJob.completed_at >= yesterday, ProcessingJob.status == "success"
        ).count(),
    }

    # Get recent users and projects
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_projects = Project.query.order_by(Project.created_at.desc()).limit(5).all()

    # Calculate storage usage
    total_storage = db.session.query(func.sum(MediaFile.file_size)).scalar() or 0
    total_storage_mb = total_storage / (1024 * 1024)

    # Celery workers snapshot (compact)
    workers_info = []
    try:
        insp = celery_app.control.inspect(timeout=2)
        aq = insp.active_queues() or {}
        st = insp.stats() or {}
        for name in sorted(set(list(aq.keys()) + list(st.keys()))):
            queues = [q.get("name") for q in (aq.get(name) or [])]
            workers_info.append(
                {
                    "name": name,
                    "queues": queues,
                    "pid": (st.get(name) or {}).get("pid"),
                    "pool": (st.get(name) or {}).get("pool"),
                }
            )
    except Exception:
        workers_info = []

    # DB quick stats for dashboard
    db_stats = {
        "users": stats["total_users"],
        "projects": stats["total_projects"],
        "media_files": MediaFile.query.count(),
        "clips": Clip.query.count(),
    }

    return render_template(
        "admin/dashboard.html",
        title="Admin Dashboard",
        stats=stats,
        recent_stats=recent_stats,
        recent_users=recent_users,
        recent_projects=recent_projects,
        total_storage_mb=total_storage_mb,
        db_stats=db_stats,
        workers=workers_info,
        version=get_version(),
    )


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    """
    User management interface with listing and filtering.

    Returns:
        Response: Rendered users management template
    """
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("ADMIN_USERS_PER_PAGE", 25)

    # Filter options
    role_filter = request.args.get("role")
    status_filter = request.args.get("status")
    search_query = request.args.get("search", "").strip()

    # Build query
    query = User.query

    if role_filter and role_filter in [r.value for r in UserRole]:
        query = query.filter_by(role=UserRole(role_filter))

    if status_filter == "active":
        query = query.filter_by(is_active=True)
    elif status_filter == "inactive":
        query = query.filter_by(is_active=False)

    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(
            (User.username.ilike(search_term))
            | (User.email.ilike(search_term))
            | (User.first_name.ilike(search_term))
            | (User.last_name.ilike(search_term))
        )

    users_pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template(
        "admin/users.html",
        title="User Management",
        users=users_pagination.items,
        pagination=users_pagination,
        role_filter=role_filter,
        status_filter=status_filter,
        search_query=search_query,
        user_roles=UserRole,
    )


@admin_bp.route("/users/create", methods=["GET", "POST"])
@login_required
@admin_required
def user_create():
    """Create a new user (admin-only)."""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or secrets.token_urlsafe(9)
        role_val = request.form.get("role") or UserRole.USER.value
        first_name = (request.form.get("first_name") or "").strip()
        last_name = (request.form.get("last_name") or "").strip()
        if not username or not email:
            flash("Username and email are required", "danger")
            return redirect(url_for("admin.user_create"))
        if User.query.filter(
            (User.username == username) | (User.email == email)
        ).first():
            flash("Username or email already exists", "danger")
            return redirect(url_for("admin.user_create"))
        try:
            user = User(
                username=username,
                email=email,
                role=UserRole(role_val)
                if role_val in [r.value for r in UserRole]
                else UserRole.USER,
                first_name=first_name or None,
                last_name=last_name or None,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("User created successfully", "success")
            # Show generated password one-time if admin didn't provide one
            if not request.form.get("password"):
                flash(f"Temporary password for {username}: {password}", "warning")
            return redirect(url_for("admin.users"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"User create failed: {e}")
            flash("Failed to create user", "danger")
            return redirect(url_for("admin.user_create"))
    # GET
    return render_template(
        "admin/user_create.html", title="Create User", user_roles=UserRole
    )


@admin_bp.route("/users/<int:user_id>")
@login_required
@admin_required
def user_details(user_id):
    """
    Detailed view of a specific user account.

    Args:
        user_id: ID of the user to display

    Returns:
        Response: Rendered user details template
    """
    user = db.session.get(User, user_id)
    if not user:
        return abort(404)

    # Get user statistics
    user_stats = {
        "total_projects": user.projects.count(),
        "completed_projects": user.projects.filter_by(
            status=ProjectStatus.COMPLETED
        ).count(),
        "total_media_files": user.media_files.count(),
        "total_storage": db.session.query(func.sum(MediaFile.file_size))
        .filter_by(user_id=user_id)
        .scalar()
        or 0,
        # processing_jobs relationship backref may be a list; count explicitly via query
        "processing_jobs": ProcessingJob.query.filter_by(user_id=user_id).count(),
    }

    # Convert storage to MB
    user_stats["total_storage_mb"] = user_stats["total_storage"] / (1024 * 1024)

    # Get recent activity
    recent_projects = user.projects.order_by(Project.created_at.desc()).limit(5).all()
    recent_media = (
        user.media_files.order_by(MediaFile.uploaded_at.desc()).limit(5).all()
    )

    return render_template(
        "admin/user_details.html",
        title=f"User: {user.username}",
        user=user,
        user_stats=user_stats,
        recent_projects=recent_projects,
        recent_media=recent_media,
    )


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def user_edit(user_id):
    """Edit user profile fields (admin-only)."""
    user = db.session.get(User, user_id)
    if not user:
        return abort(404)
    if request.method == "POST":
        try:
            user.email = (request.form.get("email") or user.email).strip()
            user.first_name = (request.form.get("first_name") or "").strip() or None
            user.last_name = (request.form.get("last_name") or "").strip() or None
            role_val = request.form.get("role")
            if role_val and role_val in [r.value for r in UserRole]:
                user.role = UserRole(role_val)
            is_active_val = request.form.get("is_active")
            if is_active_val is not None:
                user.is_active = is_active_val in ("1", "true", "on")
            db.session.commit()
            flash("User updated", "success")
            return redirect(url_for("admin.user_details", user_id=user.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"User update failed: {e}")
            flash("Failed to update user", "danger")
    return render_template(
        "admin/user_edit.html",
        title=f"Edit User: {user.username}",
        user=user,
        user_roles=UserRole,
    )


@admin_bp.route("/users/<int:user_id>/toggle-status", methods=["POST"])
@login_required
@admin_required
def toggle_user_status(user_id):
    """
    Toggle user active/inactive status.

    Args:
        user_id: ID of the user to toggle

    Returns:
        Response: JSON response with new status
    """
    if user_id == current_user.id:
        return jsonify({"error": "Cannot deactivate your own account"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        user.is_active = not user.is_active
        db.session.commit()

        status = "activated" if user.is_active else "deactivated"
        current_app.logger.info(
            f"User {user.username} (ID: {user_id}) {status} by admin {current_user.username}"
        )

        return jsonify(
            {
                "success": True,
                "is_active": user.is_active,
                "message": f"User {user.username} has been {status}",
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling user status: {str(e)}")
        return jsonify({"error": "Failed to update user status"}), 500


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@admin_required
def admin_reset_password(user_id):
    """Reset a user's password; if not provided, generate a temp password and show it once."""
    if user_id == current_user.id:
        return jsonify({"error": "Cannot reset your own password here"}), 400
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    new_pw = request.form.get("new_password") or secrets.token_urlsafe(9)
    try:
        user.set_password(new_pw)
        db.session.commit()
        # Do not log passwords
        return jsonify(
            {
                "success": True,
                "generated": not bool(request.form.get("new_password")),
                "temp_password": new_pw
                if not request.form.get("new_password")
                else None,
            }
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Password reset failed: {e}")
        return jsonify({"error": "Failed to reset password"}), 500


@admin_bp.route("/users/<int:user_id>/resend-verification", methods=["POST"])
@login_required
@admin_required
def resend_verification(user_id):
    """Mark user as unverified and simulate a verification email being resent.

    This endpoint does not send email by itself; integrate your mailer here.
    """
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    try:
        user.email_verified = False  # Mark as needing verification
        db.session.commit()
        current_app.logger.info(f"Verification email requested for user {user.id}")
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Resend verification failed: {e}")
        return jsonify({"error": "Failed to mark verification"}), 500


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def user_delete(user_id):
    """Delete a user and cascade related data; cannot delete self."""
    if user_id == current_user.id:
        return jsonify({"error": "Cannot delete your own account"}), 400
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User delete failed: {e}")
        return jsonify({"error": "Failed to delete user"}), 500


@admin_bp.route("/users/<int:user_id>/promote", methods=["POST"])
@login_required
@admin_required
def promote_user(user_id):
    """
    Promote user to admin or demote admin to user.

    Args:
        user_id: ID of the user to promote/demote

    Returns:
        Response: JSON response with new role
    """
    if user_id == current_user.id:
        return jsonify({"error": "Cannot modify your own admin status"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        if user.role == UserRole.ADMIN:
            user.role = UserRole.USER
            action = "demoted from admin"
        else:
            user.role = UserRole.ADMIN
            action = "promoted to admin"

        db.session.commit()

        current_app.logger.warning(
            f"User {user.username} (ID: {user_id}) {action} by admin {current_user.username}"
        )

        return jsonify(
            {
                "success": True,
                "role": user.role.value,
                "message": f"User {user.username} has been {action}",
            }
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating user role: {str(e)}")
        return jsonify({"error": "Failed to update user role"}), 500


@admin_bp.route("/projects")
@login_required
@admin_required
def projects():
    """
    Project management interface for admins.

    Returns:
        Response: Rendered projects management template
    """
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("ADMIN_PROJECTS_PER_PAGE", 25)

    # Filter options
    status_filter = request.args.get("status")
    user_filter = request.args.get("user_id", type=int)

    # Build query
    query = Project.query

    if status_filter and status_filter in [s.value for s in ProjectStatus]:
        query = query.filter_by(status=ProjectStatus(status_filter))

    if user_filter:
        query = query.filter_by(user_id=user_filter)

    projects_pagination = query.order_by(Project.updated_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Get users for filter dropdown
    users_with_projects = db.session.query(User).join(Project).distinct().all()

    return render_template(
        "admin/projects.html",
        title="Project Management",
        projects=projects_pagination.items,
        pagination=projects_pagination,
        status_filter=status_filter,
        user_filter=user_filter,
        users_with_projects=users_with_projects,
        project_statuses=ProjectStatus,
    )


@admin_bp.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def project_edit(project_id: int):
    """Edit a project's metadata and status; optionally reassign owner."""
    project = db.session.get(Project, project_id)
    if not project:
        return abort(404)
    if request.method == "POST":
        try:
            name = (request.form.get("name") or project.name).strip()
            desc = (request.form.get("description") or "").strip()
            status_val = request.form.get("status")
            new_user_id = request.form.get("user_id", type=int)
            project.name = name or project.name
            project.description = desc or None
            if status_val and status_val in [s.value for s in ProjectStatus]:
                project.status = ProjectStatus(status_val)
            if new_user_id and new_user_id != project.user_id:
                # Reassign project owner
                if db.session.get(User, new_user_id):
                    project.user_id = new_user_id
            db.session.commit()
            flash("Project updated", "success")
            return redirect(url_for("admin.projects"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Project update failed: {e}")
            flash("Failed to update project", "danger")
    # GET
    users_all = User.query.order_by(User.username.asc()).all()
    return render_template(
        "admin/project_edit.html",
        title=f"Edit Project: {project.name}",
        project=project,
        project_statuses=ProjectStatus,
        users=users_all,
    )


@admin_bp.route("/projects/<int:project_id>/delete", methods=["POST"])
@login_required
@admin_required
def project_delete(project_id: int):
    """Delete a project and its associated resources (admin override)."""
    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    try:
        # Remove compiled output if present
        try:
            if project.output_filename:
                import os

                compiled_path = os.path.join(
                    current_app.instance_path, "compilations", project.output_filename
                )
                if os.path.exists(compiled_path):
                    os.remove(compiled_path)
        except Exception:
            pass
        # Detach reusable media and delete project-scoped media
        removed = 0
        preserved = 0
        for m in list(project.media_files):
            try:
                if m.media_type in {
                    MediaType.INTRO,
                    MediaType.OUTRO,
                    MediaType.TRANSITION,
                }:
                    m.project_id = None
                    preserved += 1
                    continue
                import os

                if m.file_path and os.path.exists(m.file_path):
                    os.remove(m.file_path)
                if m.thumbnail_path and os.path.exists(m.thumbnail_path):
                    os.remove(m.thumbnail_path)
                db.session.delete(m)
                removed += 1
            except Exception:
                continue
        # Delete clips
        for c in list(project.clips):
            db.session.delete(c)
        db.session.delete(project)
        db.session.commit()
        return jsonify({"success": True, "removed": removed, "preserved": preserved})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Project delete failed: {e}")
        return jsonify({"error": "Failed to delete project"}), 500


@admin_bp.route("/system")
@login_required
@admin_required
def system_info():
    """
    System information and configuration panel.

    Returns:
        Response: Rendered system info template
    """
    # Get database statistics
    db_stats = {
        "users": User.query.count(),
        "projects": Project.query.count(),
        "media_files": MediaFile.query.count(),
        "clips": Clip.query.count(),
        "processing_jobs": ProcessingJob.query.count(),
    }

    # Get storage statistics
    storage_stats = {
        "total_size": db.session.query(func.sum(MediaFile.file_size)).scalar() or 0,
        "by_type": {},
    }

    # Storage by media type (use Enum members so PG enum comparison works)
    media_types = [
        MediaType.INTRO,
        MediaType.OUTRO,
        MediaType.TRANSITION,
        MediaType.CLIP,
    ]
    for mt in media_types:
        size = (
            db.session.query(func.sum(MediaFile.file_size))
            .filter(MediaFile.media_type == mt)
            .scalar()
            or 0
        )
        storage_stats["by_type"][mt.value] = size / (1024 * 1024)  # Convert to MB

    storage_stats["total_size_mb"] = storage_stats["total_size"] / (1024 * 1024)

    # Get processing job statistics
    job_stats = {}
    for status in ["pending", "started", "success", "failure", "retry", "revoked"]:
        job_stats[status] = ProcessingJob.query.filter_by(status=status).count()

    return render_template(
        "admin/system_info.html",
        title="System Information",
        db_stats=db_stats,
        storage_stats=storage_stats,
        job_stats=job_stats,
        version=get_version(),
        changelog=get_changelog(),
    )


@admin_bp.route("/logs")
@login_required
@admin_required
def logs():
    """
    System logs viewer for debugging and monitoring.

    Returns:
        Response: Rendered logs template
    """
    # This would typically read from log files
    # For now, return a placeholder
    return render_template(
        "admin/logs.html",
        title="System Logs",
        logs=[
            {
                "timestamp": datetime.utcnow(),
                "level": "INFO",
                "message": "System started",
            },
            {
                "timestamp": datetime.utcnow(),
                "level": "INFO",
                "message": "Database connected",
            },
        ],
    )


@admin_bp.route("/config", methods=["GET", "POST"])  # System configuration UI
@login_required
@admin_required
def system_config():
    """View and update system settings from the UI.

    Only a curated allowlist of settings is exposed. Secrets (tokens/passwords)
    must remain in environment variables or the .env file.
    """
    # Define editable settings groups
    groups = {
        "General": [
            {"key": "OUTPUT_VIDEO_QUALITY", "type": "str", "label": "Output Quality"},
            {"key": "USE_GPU_QUEUE", "type": "bool", "label": "Prefer GPU Queue"},
        ],
        "Security": [
            {"key": "FORCE_HTTPS", "type": "bool", "label": "Force HTTPS"},
        ],
        "Rate Limiting": [
            {
                "key": "RATELIMIT_ENABLED",
                "type": "bool",
                "label": "Enable Rate Limiting",
            },
            {"key": "RATELIMIT_DEFAULT", "type": "str", "label": "Default Rate Limit"},
        ],
        "Binaries": [
            {"key": "FFMPEG_BINARY", "type": "str", "label": "ffmpeg Binary"},
            {"key": "YT_DLP_BINARY", "type": "str", "label": "yt-dlp Binary"},
        ],
        "Maintenance": [
            {
                "key": "AUTO_REINDEX_ON_STARTUP",
                "type": "bool",
                "label": "Auto Reindex on Startup",
            },
        ],
    }

    # Persist updates
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save":
            try:
                changed = 0
                for section, items in groups.items():
                    for item in items:
                        key = item["key"]
                        typ = item["type"]
                        form_key = f"setting_{key}"
                        if typ == "bool":
                            val = (
                                "true"
                                if request.form.get(form_key) in ("1", "on", "true")
                                else "false"
                            )
                        else:
                            val = (request.form.get(form_key) or "").strip()
                        if val == "" and typ != "bool":
                            # Skip empty clears to avoid nuking config by mistake
                            continue
                        row = SystemSetting.query.filter_by(key=key).first()
                        if not row:
                            row = SystemSetting(
                                key=key,
                                value=val,
                                value_type=typ,
                                group=section,
                                updated_by=current_user.id,
                            )
                            db.session.add(row)
                        else:
                            row.value = val
                            row.value_type = typ
                            row.group = section
                            row.updated_by = current_user.id
                        changed += 1
                db.session.commit()
                flash("Settings saved.", "success")
                # Inform admin a restart may be needed
                flash(
                    "Some changes require a server restart to take effect.", "warning"
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Saving settings failed: {e}")
                flash("Failed to save settings", "danger")
            return redirect(url_for("admin.system_config"))
        elif action in {"restart_web", "restart_workers"}:
            # Trigger restart endpoints
            return redirect(url_for("admin.restart", target=action.split("_")[1]))

    # Load current values (prefer overrides, fallback to app.config)
    current_values = {}
    for _section, items in groups.items():
        for item in items:
            key = item["key"]
            row = SystemSetting.query.filter_by(key=key).first()
            if row:
                current_values[key] = row.value
            else:
                current_values[key] = str(current_app.config.get(key, ""))

    return render_template(
        "admin/system_config.html",
        title="System Configuration",
        groups=groups,
        values=current_values,
    )


@admin_bp.route("/restart/<target>", methods=["POST", "GET"])  # restart controls
@login_required
@admin_required
def restart(target: str):
    """Restart application or workers.

    Implementation notes:
    - Web restart: touch a known file to trigger process manager reload (e.g., systemd, gunicorn --reload)
    - Workers: enqueue a shutdown broadcast via Celery control then rely on process manager to restart
    """
    target = target.lower()
    msg = None
    try:
        if target in {"web", "app"}:
            # Touch a file under instance dir as a simple trigger for reload setups
            import os
            import time

            marker = os.path.join(current_app.instance_path, ".restart-web")
            with open(marker, "a") as f:
                f.write(str(time.time()))
            msg = "Web restart marker created. If supervised (systemd/docker), it should restart or reload."
        elif target in {"workers", "worker"}:
            # Ask Celery workers to shutdown gracefully
            try:
                celery_app.control.broadcast("shutdown")
                msg = "Sent shutdown broadcast to Celery workers. Ensure your process manager restarts them."
            except Exception as e:
                current_app.logger.warning(f"Worker restart broadcast failed: {e}")
                msg = "Attempted to restart workers, but broadcast failed. Check logs."
        else:
            flash("Unknown restart target", "danger")
            return redirect(url_for("admin.system_config"))
        flash(msg or "Restart action invoked", "info")
    except Exception as e:
        current_app.logger.error(f"Restart action failed: {e}")
        flash("Restart failed. Check server logs.", "danger")
    return redirect(url_for("admin.system_config"))


@admin_bp.route("/maintenance", methods=["GET", "POST"])
@login_required
@admin_required
def maintenance():
    """Admin-only maintenance actions: reindex media and deduplicate entries."""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "reindex":
            task = reindex_media_task.delay(False)
            flash(
                f"Started reindex task ({task.id}). Check Jobs in the UI to monitor.",
                "info",
            )
        elif action == "dedupe_media":
            user_id = request.form.get("user_id", type=int)
            dry_run = request.form.get("dry_run") == "1"
            task = dedupe_media_task.delay(dry_run=dry_run, user_id=user_id)
            flash(
                f"Started media deduplication task ({task.id}). This keeps newest entries and removes duplicates.",
                "warning",
            )
        return redirect(url_for("admin.maintenance"))

    # GET: show simple form
    return render_template("admin/maintenance.html", title="Maintenance")


@admin_bp.route("/workers")
@login_required
@admin_required
def workers():
    """Show Celery worker nodes and queues.

    Uses Celery's inspect API to display connected workers, their active queues,
    and basic runtime statistics. Useful when running remote GPU workers.
    """
    info = {
        "stats": {},
        "active": {},
        "registered": {},
        "scheduled": {},
        "active_queues": {},
        "errors": [],
    }
    try:
        insp = celery_app.control.inspect(timeout=2)
        info["stats"] = insp.stats() or {}
        info["active"] = insp.active() or {}
        info["registered"] = insp.registered() or {}
        info["scheduled"] = insp.scheduled() or {}
        info["active_queues"] = insp.active_queues() or {}
    except Exception as e:
        info["errors"].append(str(e))

    # Normalize into a list of workers for easier rendering
    workers_list = []
    keys = set()
    for d in (
        info["stats"],
        info["active"],
        info["registered"],
        info["scheduled"],
        info["active_queues"],
    ):
        if isinstance(d, dict):
            keys.update(d.keys())
    for name in sorted(keys):
        workers_list.append(
            {
                "name": name,
                "stats": (info["stats"] or {}).get(name) or {},
                "active": (info["active"] or {}).get(name) or [],
                "registered": (info["registered"] or {}).get(name) or [],
                "scheduled": (info["scheduled"] or {}).get(name) or [],
                "queues": (info["active_queues"] or {}).get(name) or [],
            }
        )

    return render_template(
        "admin/workers.html",
        title="Workers",
        workers=workers_list,
        raw=info,
    )


@admin_bp.route("/workers.json")
@login_required
@admin_required
def workers_json():
    """JSON view of Celery workers and queues."""
    try:
        insp = celery_app.control.inspect(timeout=2)
        payload = {
            "stats": insp.stats() or {},
            "active": insp.active() or {},
            "registered": insp.registered() or {},
            "scheduled": insp.scheduled() or {},
            "active_queues": insp.active_queues() or {},
        }
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
