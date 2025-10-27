"""
Admin panel routes for Clippy platform management.

This module provides administrative functionality including user management,
system monitoring, and platform configuration for admin users only.
"""
import os
import secrets
import stat as _stat
from datetime import datetime
from functools import wraps
from urllib.parse import urlsplit, urlunsplit

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
from werkzeug.utils import secure_filename

from app.models import (
    Clip,
    MediaFile,
    MediaType,
    ProcessingJob,
    Project,
    ProjectStatus,
    SystemSetting,
    Theme,
    Tier,
    User,
    UserRole,
    db,
)
from app.tasks.celery_app import celery_app
from app.tasks.media_maintenance import dedupe_media_task, reindex_media_task
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

    # Keep the dashboard light: avoid expensive cross-service calls (Celery inspect)
    # and large aggregates here. Defer details to dedicated pages.

    return render_template(
        "admin/dashboard.html",
        title="Admin Dashboard",
        stats=stats,
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
            # Admin-only per-user watermark override
            wm_disabled_val = request.form.get("watermark_disabled")
            if wm_disabled_val is not None:
                user.watermark_disabled = wm_disabled_val in ("1", "true", "on")
            # Assign subscription tier
            tier_id_val = request.form.get("tier_id")
            if tier_id_val is not None:
                try:
                    t_id = int(tier_id_val) if tier_id_val else None
                except Exception:
                    t_id = None
                if t_id:
                    t = db.session.get(Tier, t_id)
                    if t:
                        user.tier_id = t.id
                else:
                    user.tier_id = None
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
        tiers=Tier.query.filter_by(is_active=True)
        .order_by(Tier.is_unlimited.desc(), Tier.name.asc())
        .all(),
    )


@admin_bp.route("/tiers")
@login_required
@admin_required
def tiers_list():
    """List and manage subscription tiers."""
    # Ensure defaults exist for convenience
    try:
        from app.quotas import ensure_default_tiers

        ensure_default_tiers()
    except Exception:
        pass
    tiers = Tier.query.order_by(
        Tier.is_unlimited.desc(), Tier.is_active.desc(), Tier.name.asc()
    ).all()
    return render_template("admin/tiers_list.html", title="Tiers", tiers=tiers)


@admin_bp.route("/tiers/create", methods=["GET", "POST"])
@login_required
@admin_required
def tier_create():
    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Name is required", "danger")
                return redirect(url_for("admin.tier_create"))
            desc = (request.form.get("description") or "").strip() or None
            # Output caps
            max_res_label = (
                request.form.get("max_output_resolution") or ""
            ).strip() or None
            # Normalize allowed labels
            if max_res_label:
                mr = max_res_label.lower()
                if mr in {"720p", "1080p", "1440p", "2160p", "2k", "4k"}:
                    if mr == "2k":
                        max_res_label = "1440p"
                    elif mr == "4k":
                        max_res_label = "2160p"
                    else:
                        max_res_label = mr
                else:
                    # Unknown label; clear to avoid invalid values
                    max_res_label = None
            max_fps = request.form.get("max_fps")
            max_clips = request.form.get("max_clips_per_project")
            # Accept MB input from the form, fallback to legacy bytes key if provided
            storage_mb = request.form.get("storage_limit_mb")
            storage_bytes_legacy = request.form.get("storage_limit_bytes")
            # Accept minutes for render time; fallback to legacy seconds field
            render_minutes = request.form.get("render_time_limit_minutes")
            render_seconds_legacy = request.form.get("render_time_limit_seconds")
            apply_wm = request.form.get("apply_watermark") in ("1", "true", "on")
            is_unlim = request.form.get("is_unlimited") in ("1", "true", "on")
            is_active = request.form.get("is_active") in ("1", "true", "on")
            sched_enabled = request.form.get("can_schedule_tasks") in (
                "1",
                "true",
                "on",
            )
            max_sched = request.form.get("max_schedules_per_user")

            def _to_int_or_none(v):
                try:
                    v2 = str(v or "").strip()
                    return int(v2) if v2 else None
                except Exception:
                    return None

            # Convert MB to bytes if provided
            def _mb_to_bytes(v):
                try:
                    s = str(v or "").strip()
                    if not s:
                        return None
                    return int(float(s) * 1024 * 1024)
                except Exception:
                    return None

            # Convert minutes to seconds if provided
            def _min_to_sec(v):
                try:
                    s = str(v or "").strip()
                    if not s:
                        return None
                    return int(float(s) * 60)
                except Exception:
                    return None

            tier = Tier(
                name=name,
                description=desc,
                max_output_resolution=max_res_label,
                max_fps=_to_int_or_none(max_fps),
                max_clips_per_project=_to_int_or_none(max_clips),
                storage_limit_bytes=(
                    _mb_to_bytes(storage_mb)
                    if (storage_mb is not None and str(storage_mb).strip() != "")
                    else _to_int_or_none(storage_bytes_legacy)
                ),
                render_time_limit_seconds=(
                    _min_to_sec(render_minutes)
                    if (
                        render_minutes is not None and str(render_minutes).strip() != ""
                    )
                    else _to_int_or_none(render_seconds_legacy)
                ),
                apply_watermark=apply_wm,
                is_unlimited=is_unlim,
                is_active=is_active,
                can_schedule_tasks=sched_enabled,
                max_schedules_per_user=_to_int_or_none(max_sched),
            )
            db.session.add(tier)
            db.session.commit()
            flash("Tier created", "success")
            return redirect(url_for("admin.tiers_list"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Tier create failed: {e}")
            flash("Failed to create tier", "danger")
    return render_template("admin/tiers_form.html", title="Create Tier", tier=None)


@admin_bp.route("/tiers/<int:tier_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def tier_edit(tier_id: int):
    tier = db.session.get(Tier, tier_id)
    if not tier:
        return abort(404)
    if request.method == "POST":
        try:
            tier.name = (request.form.get("name") or tier.name).strip()
            tier.description = (request.form.get("description") or "").strip() or None
            # Output caps
            max_res_label = (request.form.get("max_output_resolution") or "").strip()
            if max_res_label == "":
                tier.max_output_resolution = None
            else:
                mr = max_res_label.lower()
                if mr in {"720p", "1080p", "1440p", "2160p", "2k", "4k"}:
                    tier.max_output_resolution = (
                        "1440p" if mr == "2k" else ("2160p" if mr == "4k" else mr)
                    )
                else:
                    # Ignore invalid update and leave existing value
                    pass

            def _to_int_or_none(v):
                try:
                    v2 = str(v or "").strip()
                    return int(v2) if v2 else None
                except Exception:
                    return None

            # FPS / clips caps
            tier.max_fps = _to_int_or_none(request.form.get("max_fps"))
            tier.max_clips_per_project = _to_int_or_none(
                request.form.get("max_clips_per_project")
            )

            # Update storage from MB if present; fallback to legacy bytes field
            def _mb_to_bytes(v):
                try:
                    s = str(v or "").strip()
                    if not s:
                        return None
                    return int(float(s) * 1024 * 1024)
                except Exception:
                    return None

            if (
                request.form.get("storage_limit_mb") is not None
                and str(request.form.get("storage_limit_mb")).strip() != ""
            ):
                tier.storage_limit_bytes = _mb_to_bytes(
                    request.form.get("storage_limit_mb")
                )
            else:
                tier.storage_limit_bytes = _to_int_or_none(
                    request.form.get("storage_limit_bytes")
                )

            # Update render limit from minutes if present; fallback to legacy seconds
            def _min_to_sec(v):
                try:
                    s = str(v or "").strip()
                    if not s:
                        return None
                    return int(float(s) * 60)
                except Exception:
                    return None

            if (
                request.form.get("render_time_limit_minutes") is not None
                and str(request.form.get("render_time_limit_minutes")).strip() != ""
            ):
                tier.render_time_limit_seconds = _min_to_sec(
                    request.form.get("render_time_limit_minutes")
                )
            else:
                tier.render_time_limit_seconds = _to_int_or_none(
                    request.form.get("render_time_limit_seconds")
                )
            tier.apply_watermark = request.form.get("apply_watermark") in (
                "1",
                "true",
                "on",
            )
            tier.is_unlimited = request.form.get("is_unlimited") in ("1", "true", "on")
            tier.is_active = request.form.get("is_active") in ("1", "true", "on")
            # Scheduling policy
            tier.can_schedule_tasks = request.form.get("can_schedule_tasks") in (
                "1",
                "true",
                "on",
            )
            tier.max_schedules_per_user = _to_int_or_none(
                request.form.get("max_schedules_per_user")
            )
            db.session.commit()
            flash("Tier updated", "success")
            return redirect(url_for("admin.tiers_list"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Tier update failed: {e}")
            flash("Failed to update tier", "danger")
    return render_template(
        "admin/tiers_form.html", title=f"Edit Tier: {tier.name}", tier=tier
    )


@admin_bp.route("/tiers/<int:tier_id>/delete", methods=["POST"])
@login_required
@admin_required
def tier_delete(tier_id: int):
    tier = db.session.get(Tier, tier_id)
    if not tier:
        return jsonify({"error": "Tier not found"}), 404
    try:
        # Disallow deleting a tier that is assigned to users
        if tier.users and tier.users.count() > 0:
            return jsonify({"error": "Cannot delete a tier assigned to users"}), 400
        db.session.delete(tier)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Tier delete failed: {e}")
        return jsonify({"error": "Failed to delete tier"}), 500


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
    # Define editable settings groups and optional section filter
    section = (request.args.get("section") or "").strip().lower()
    base_groups = {
        "General": [
            {"key": "OUTPUT_VIDEO_QUALITY", "type": "str", "label": "Output Quality"},
            {"key": "USE_GPU_QUEUE", "type": "bool", "label": "Prefer GPU Queue"},
            {
                "key": "DEFAULT_OUTPUT_RESOLUTION",
                "type": "str",
                "label": "Default Output Resolution",
            },
            {
                "key": "DEFAULT_OUTPUT_FORMAT",
                "type": "str",
                "label": "Default Output Format",
            },
            {
                "key": "DEFAULT_MAX_CLIP_DURATION",
                "type": "int",
                "label": "Default Max Clip Duration (s)",
            },
            {
                "key": "DEFAULT_TRANSITION_DURATION_SECONDS",
                "type": "int",
                "label": "Default Transition Duration (s)",
            },
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
            {"key": "FFPROBE_BINARY", "type": "str", "label": "ffprobe Binary"},
            {"key": "YT_DLP_BINARY", "type": "str", "label": "yt-dlp Binary"},
        ],
        "Thumbnails": [
            {
                "key": "THUMBNAIL_TIMESTAMP_SECONDS",
                "type": "int",
                "label": "Thumbnail Timestamp (s)",
            },
            {"key": "THUMBNAIL_WIDTH", "type": "int", "label": "Thumbnail Width (px)"},
        ],
        "Pagination": [
            {
                "key": "PROJECTS_PER_PAGE",
                "type": "int",
                "label": "Projects per Page (UI)",
            },
            {
                "key": "MEDIA_PER_PAGE",
                "type": "int",
                "label": "Media per Page (Library)",
            },
            {
                "key": "ADMIN_USERS_PER_PAGE",
                "type": "int",
                "label": "Admin: Users per Page",
            },
            {
                "key": "ADMIN_PROJECTS_PER_PAGE",
                "type": "int",
                "label": "Admin: Projects per Page",
            },
        ],
        "CLI Arguments": [
            {"key": "FFMPEG_GLOBAL_ARGS", "type": "str", "label": "ffmpeg Global Args"},
            {"key": "FFMPEG_ENCODE_ARGS", "type": "str", "label": "ffmpeg Encode Args"},
            {
                "key": "FFMPEG_THUMBNAIL_ARGS",
                "type": "str",
                "label": "ffmpeg Thumbnail Args",
            },
            {"key": "FFMPEG_CONCAT_ARGS", "type": "str", "label": "ffmpeg Concat Args"},
            {"key": "FFPROBE_ARGS", "type": "str", "label": "ffprobe Args"},
            {"key": "YT_DLP_ARGS", "type": "str", "label": "yt-dlp Args"},
        ],
        "Watermark": [
            {
                "key": "WATERMARK_OPACITY",
                "type": "float",
                "label": "Watermark Opacity (0-1)",
            },
            {"key": "WATERMARK_POSITION", "type": "str", "label": "Watermark Position"},
        ],
        "Email": [
            {
                "key": "EMAIL_VERIFICATION_ENABLED",
                "type": "bool",
                "label": "Enable Email Verification",
            },
            {"key": "EMAIL_FROM_ADDRESS", "type": "str", "label": "From Address"},
            {"key": "SMTP_HOST", "type": "str", "label": "SMTP Host"},
            {"key": "SMTP_PORT", "type": "int", "label": "SMTP Port"},
            {"key": "SMTP_USE_TLS", "type": "bool", "label": "Use STARTTLS"},
            {"key": "SMTP_USE_SSL", "type": "bool", "label": "Use SSL (465)"},
            {"key": "SMTP_USERNAME", "type": "str", "label": "SMTP Username"},
            # NOTE: Password should be provided via environment (.env) as SMTP_PASSWORD
        ],
    }

    section_map = {
        "general": ["General"],
        "security": ["Security", "Rate Limiting"],
        "binaries": ["Binaries", "CLI Arguments"],
        # Display bucket includes pagination, thumbnails, and watermark
        "pagination": ["Watermark", "Pagination", "Thumbnails"],
        "email": ["Email"],
    }
    if section in section_map:
        keys = section_map[section]
        groups = {k: base_groups[k] for k in keys if k in base_groups}
    else:
        groups = base_groups

    # Build configuration overview & checks
    proj_root = os.path.dirname(current_app.root_path)
    env_path = os.path.join(proj_root, ".env")
    settings_path = os.path.join(proj_root, "config", "settings.py")
    from app import storage as storage_lib

    # Show the data root for project layout in the system config page
    uploads_dir = storage_lib.data_root()

    def _exists(p: str) -> bool:
        try:
            return os.path.exists(p)
        except Exception:
            return False

    def _rw(p: str) -> tuple[bool, bool]:
        try:
            return (os.access(p, os.R_OK), os.access(p, os.W_OK))
        except Exception:
            return (False, False)

    def _world_writable(p: str) -> bool:
        try:
            st = os.stat(p)
            return bool(st.st_mode & _stat.S_IWOTH)
        except Exception:
            return False

    def _redact(uri: str | None) -> str:
        if not uri:
            return ""
        try:
            sp = urlsplit(str(uri))
            netloc = sp.netloc
            if "@" in netloc:
                creds, host = netloc.split("@", 1)
                if ":" in creds:
                    user, _pwd = creds.split(":", 1)
                    netloc = f"{user}:***@{host}"
                else:
                    netloc = f"{creds}@{host}"
            return urlunsplit((sp.scheme, netloc, sp.path, sp.query, sp.fragment))
        except Exception:
            return str(uri)

    secret = str(current_app.config.get("SECRET_KEY") or "")
    weak_secret = (
        (len(secret) < 32)
        or ("secret" in secret.lower())
        or ("change" in secret.lower())
    )
    https_off_in_prod = (
        not current_app.config.get("DEBUG")
        and not current_app.config.get("TESTING")
        and not current_app.config.get("FORCE_HTTPS", False)
    )
    env_world_w = _world_writable(env_path) if _exists(env_path) else False
    settings_world_w = (
        _world_writable(settings_path) if _exists(settings_path) else False
    )

    security_warnings: list[str] = []
    if weak_secret:
        security_warnings.append(
            "SECRET_KEY looks weak or default; set a strong random value."
        )
    if https_off_in_prod:
        security_warnings.append(
            "HTTPS not enforced in production. Enable FORCE_HTTPS."
        )
    if env_world_w:
        security_warnings.append(".env is world-writable; tighten file permissions.")
    if settings_world_w:
        security_warnings.append(
            "config/settings.py is world-writable; tighten file permissions."
        )

    config_info = {
        "env": {
            "path": env_path,
            "exists": _exists(env_path),
            "read": _rw(env_path)[0],
            "write": _rw(env_path)[1],
        },
        "settings_py": {
            "path": settings_path,
            "exists": _exists(settings_path),
            "read": _rw(settings_path)[0],
            "write": _rw(settings_path)[1],
        },
        "instance_path": {
            "path": current_app.instance_path,
            "exists": _exists(current_app.instance_path),
            "read": _rw(current_app.instance_path)[0],
            "write": _rw(current_app.instance_path)[1],
        },
        "uploads_dir": {
            "path": uploads_dir,
            "exists": _exists(uploads_dir),
            "read": _rw(uploads_dir)[0],
            "write": _rw(uploads_dir)[1],
        },
        "database": _redact(current_app.config.get("SQLALCHEMY_DATABASE_URI")),
        "redis": _redact(current_app.config.get("REDIS_URL")),
        "environment": {
            "debug": bool(current_app.config.get("DEBUG")),
            "testing": bool(current_app.config.get("TESTING")),
        },
        "email": {
            "smtp_password_set": bool(os.environ.get("SMTP_PASSWORD")),
            "from": str(current_app.config.get("EMAIL_FROM_ADDRESS") or ""),
        },
    }

    # Persist updates
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save":
            try:
                changed = 0
                for section_name, items in groups.items():
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
                            row.group = section_name
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
        elif action == "upload_watermark":
            f = request.files.get("watermark")
            if not f or f.filename == "":
                flash("No watermark file selected", "warning")
                return redirect(url_for("admin.system_config", section="pagination"))
            try:
                base_upload = os.path.join(
                    current_app.instance_path, "assets", "system", "watermark"
                )
                os.makedirs(base_upload, exist_ok=True)
                ext = os.path.splitext(f.filename)[1].lower() or ""
                from werkzeug.utils import secure_filename as _sf

                filename = _sf(f"watermark{ext}")
                path = os.path.join(base_upload, filename)
                f.save(path)
                row = SystemSetting.query.filter_by(key="WATERMARK_PATH").first()
                if not row:
                    row = SystemSetting(
                        key="WATERMARK_PATH",
                        value=path,
                        value_type="str",
                        group="Watermark",
                        updated_by=current_user.id,
                    )
                    db.session.add(row)
                else:
                    row.value = path
                    row.group = "Watermark"
                    row.updated_by = current_user.id
                db.session.commit()
                flash("Watermark uploaded.", "success")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Watermark upload failed: {e}")
                flash("Failed to upload watermark", "danger")
            return redirect(url_for("admin.system_config", section="pagination"))
        elif action == "send_test_email":
            # Send a test email using configured SMTP settings
            to_addr = (request.form.get("test_to") or "").strip()
            if not to_addr:
                flash("Please provide a destination email address.", "warning")
                return redirect(url_for("admin.system_config", section="email"))
            try:
                from app import mailer as _mailer

                if not _mailer.is_configured():
                    flash(
                        "SMTP is not fully configured. Set host/port/username and SMTP_PASSWORD in .env.",
                        "warning",
                    )
                    return redirect(url_for("admin.system_config", section="email"))
                sent = _mailer.send_email(
                    to_addr,
                    subject="ClippyFront SMTP test",
                    html="<p>This is a <strong>test email</strong> from ClippyFront Admin.</p>",
                    text="This is a test email from ClippyFront Admin.",
                )
                if sent:
                    flash(f"Test email sent to {to_addr}.", "success")
                else:
                    flash(
                        "Failed to send test email. Check SMTP settings and logs.",
                        "danger",
                    )
            except Exception as e:
                current_app.logger.error(f"Test email send failed: {e}")
                flash("An error occurred while sending the test email.", "danger")
            return redirect(url_for("admin.system_config", section="email"))
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

    # Add WATERMARK_PATH to values for display convenience
    wm_path_row = SystemSetting.query.filter_by(key="WATERMARK_PATH").first()
    current_values["WATERMARK_PATH"] = wm_path_row.value if wm_path_row else ""

    return render_template(
        "admin/system_config.html",
        title="System Configuration",
        groups=groups,
        section=section,
        config_info=config_info,
        security_warnings=security_warnings,
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


# Theme Management


@admin_bp.route("/themes")
@login_required
@admin_required
def themes_list():
    themes = Theme.query.order_by(Theme.is_active.desc(), Theme.name.asc()).all()
    return render_template("admin/themes_list.html", title="Themes", themes=themes)


@admin_bp.route("/themes/create", methods=["GET", "POST"])
@login_required
@admin_required
def theme_create():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Theme name is required", "danger")
            return redirect(url_for("admin.theme_create"))
        # Collect colors
        colors = {
            "color_primary": request.form.get("color_primary") or "#0d6efd",
            "color_secondary": request.form.get("color_secondary") or "#6c757d",
            "color_accent": request.form.get("color_accent") or "#6610f2",
            "color_background": request.form.get("color_background") or "#121212",
            "color_surface": request.form.get("color_surface") or "#1e1e1e",
            "color_text": request.form.get("color_text") or "#e9ecef",
            "color_muted": request.form.get("color_muted") or "#adb5bd",
            "navbar_bg": request.form.get("navbar_bg") or "#212529",
            "navbar_text": request.form.get("navbar_text") or "#ffffff",
            # Media type colors
            "media_color_intro": request.form.get("media_color_intro") or "#0ea5e9",
            "media_color_clip": request.form.get("media_color_clip") or None,
            "media_color_outro": request.form.get("media_color_outro") or "#f59e0b",
            "media_color_transition": request.form.get("media_color_transition")
            or "#22c55e",
            "media_color_compilation": request.form.get("media_color_compilation")
            or None,
        }
        outline_color = (request.form.get("outline_color") or "").strip() or None
        desc = (request.form.get("description") or "").strip() or None
        wm_opacity = request.form.get("watermark_opacity", type=float) or 0.1
        wm_pos = (request.form.get("watermark_position") or "bottom-right").strip()
        mode = (request.form.get("mode") or "auto").strip().lower()
        if mode not in {"auto", "light", "dark"}:
            mode = "auto"
        try:
            theme = Theme(
                name=name,
                description=desc,
                updated_by=current_user.id,
                watermark_opacity=wm_opacity,
                watermark_position=wm_pos,
                mode=mode,
                **colors,
            )
            theme.outline_color = outline_color
            # outline_color is used for focus ring CSS only; do not override accent persistently
            db.session.add(theme)
            db.session.commit()
            # Handle uploads after we have an ID
            _handle_theme_uploads(theme)
            db.session.commit()
            flash("Theme created", "success")
            return redirect(url_for("admin.themes_list"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Theme create failed: {e}")
            flash("Failed to create theme", "danger")
    return render_template("admin/themes_form.html", title="Create Theme", theme=None)


@admin_bp.route("/themes/<int:theme_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def theme_edit(theme_id: int):
    theme = db.session.get(Theme, theme_id)
    if not theme:
        return abort(404)
    if request.method == "POST":
        try:
            theme.name = (request.form.get("name") or theme.name).strip()
            theme.description = (request.form.get("description") or "").strip() or None
            # Update colors
            for key in (
                "color_primary",
                "color_secondary",
                "color_accent",
                "color_background",
                "color_surface",
                "color_text",
                "color_muted",
                "navbar_bg",
                "navbar_text",
                "media_color_intro",
                "media_color_clip",
                "media_color_outro",
                "media_color_transition",
                "media_color_compilation",
            ):
                val = request.form.get(key)
                if val:
                    setattr(theme, key, val)
            # Outline/focus ring optional value
            ocol = request.form.get("outline_color")
            if ocol is not None:
                ocol = ocol.strip()
                theme.outline_color = ocol or None
            # Watermark settings
            wm_opacity = request.form.get("watermark_opacity", type=float)
            wm_pos = request.form.get("watermark_position")
            if wm_opacity is not None:
                theme.watermark_opacity = wm_opacity
            if wm_pos:
                theme.watermark_position = wm_pos
            # Mode override
            mode = (request.form.get("mode") or "").strip().lower()
            if mode in {"auto", "light", "dark"}:
                theme.mode = mode
            # Optional outline/focus override (maps to color_accent if provided)
            # outline_color may adjust focus ring in CSS dynamically; do not overwrite accent persistently
            # Touch updated_at to bust /theme.css cache param so changes apply immediately
            try:
                from datetime import datetime as _dt

                theme.updated_at = _dt.utcnow()
            except Exception:
                pass
            theme.updated_by = current_user.id
            _handle_theme_uploads(theme)
            db.session.commit()
            flash("Theme updated", "success")
            return redirect(url_for("admin.themes_list"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Theme update failed: {e}")
            flash("Failed to update theme", "danger")
    return render_template(
        "admin/themes_form.html", title=f"Edit Theme: {theme.name}", theme=theme
    )


@admin_bp.route("/themes/<int:theme_id>/delete", methods=["POST"])
@login_required
@admin_required
def theme_delete(theme_id: int):
    theme = db.session.get(Theme, theme_id)
    # Detect if the client explicitly wants JSON (AJAX/fetch) vs. standard HTML form navigation
    accept_hdr = (request.headers.get("Accept") or "").lower()
    is_ajax = (
        request.headers.get("X-Requested-With") or ""
    ).lower() == "xmlhttprequest"
    wants_json = is_ajax or (
        "application/json" in accept_hdr and "text/html" not in accept_hdr
    )
    if not theme:
        if not wants_json:
            flash("Theme not found", "danger")
            return redirect(url_for("admin.themes_list"))
        return jsonify({"error": "Theme not found"}), 404
    if theme.is_active:
        if not wants_json:
            flash("Cannot delete the active theme", "warning")
            return redirect(url_for("admin.themes_list"))
        return jsonify({"error": "Cannot delete the active theme"}), 400
    try:
        # Remove files on disk
        for path in (theme.logo_path, theme.favicon_path, theme.watermark_path):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        db.session.delete(theme)
        db.session.commit()
        if not wants_json:
            flash("Theme deleted", "success")
            return redirect(url_for("admin.themes_list"))
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Theme delete failed: {e}")
        if not wants_json:
            flash("Failed to delete theme", "danger")
            return redirect(url_for("admin.themes_list"))
        return jsonify({"error": "Failed to delete theme"}), 500


@admin_bp.route("/themes/<int:theme_id>/activate", methods=["POST"])
@login_required
@admin_required
def theme_activate(theme_id: int):
    theme = db.session.get(Theme, theme_id)
    # Detect if the client explicitly wants JSON (AJAX/fetch) vs. standard HTML form navigation
    accept_hdr = (request.headers.get("Accept") or "").lower()
    is_ajax = (
        request.headers.get("X-Requested-With") or ""
    ).lower() == "xmlhttprequest"
    wants_json = is_ajax or (
        "application/json" in accept_hdr and "text/html" not in accept_hdr
    )
    if not theme:
        # Prefer redirect for HTML requests
        if not wants_json:
            flash("Theme not found", "danger")
            return redirect(url_for("admin.themes_list"))
        return jsonify({"error": "Theme not found"}), 404
    try:
        # Deactivate others
        Theme.query.update({Theme.is_active: False})
        theme.is_active = True
        # Touch updated_at to ensure cache-busting param changes
        try:
            from datetime import datetime as _dt

            theme.updated_at = _dt.utcnow()
        except Exception:
            pass
        db.session.commit()
        flash(f"Activated theme '{theme.name}'", "success")
        # For normal form submissions (HTML), redirect back to list so the page refreshes
        if not wants_json:
            return redirect(url_for("admin.themes_list"))
        # Otherwise, return JSON for API/AJAX callers
        return jsonify({"success": True, "theme_id": theme.id, "name": theme.name})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Theme activation failed: {e}")
        if not wants_json:
            flash("Failed to activate theme", "danger")
            return redirect(url_for("admin.themes_list"))
        return jsonify({"error": "Failed to activate theme"}), 500


def _handle_theme_uploads(theme: Theme) -> None:
    """Handle logo, favicon, watermark file uploads for a theme."""
    base_upload = os.path.join(
        current_app.instance_path, "assets", "themes", str(theme.id)
    )
    os.makedirs(base_upload, exist_ok=True)
    files = {
        "logo": ("logo", ("logo.png", "logo.jpg", "logo.webp", "logo.svg")),
        "favicon": ("favicon", ("ico", "png")),
        "watermark": ("watermark", ("png", "webp", "svg")),
    }
    for key, (field, exts) in files.items():
        f = request.files.get(field)
        if not f or f.filename == "":
            continue
        ext = os.path.splitext(f.filename)[1].lower().lstrip(".")
        if exts and ext not in exts:
            # Allow anything image-ish for logo except enforce favicon typical exts
            if key != "favicon":
                pass
            else:
                flash(f"Unsupported {key} type", "warning")
                continue
        filename = secure_filename(f"{key}.{ext}") if ext else secure_filename(key)
        path = os.path.join(base_upload, filename)
        try:
            f.save(path)
            setattr(theme, f"{key}_path", path)
        except Exception as e:
            current_app.logger.error(f"Upload failed for {key}: {e}")
            flash(f"Failed to upload {key}", "danger")
