"""
Team permission checking utilities.

This module provides decorators and helper functions for enforcing
team-based access control on projects and resources.
"""

from functools import wraps

from flask import abort
from flask_login import current_user
from sqlalchemy import select

from app.models import Project, TeamRole, db


def check_project_access(project, required_role=TeamRole.VIEWER):
    """
    Check if the current user has access to a project.

    Args:
        project: Project instance to check access for
        required_role: Minimum required team role (default: VIEWER)

    Returns:
        bool: True if user has access, False otherwise

    Raises:
        403: If user doesn't have sufficient permissions
        404: If project doesn't exist or user has no access
    """
    if not current_user.is_authenticated:
        abort(401)

    # Project owner always has full access
    if project.user_id == current_user.id:
        return True

    # Check team access if project is shared with a team
    if project.team_id:
        team = project.team
        if team and team.has_permission(current_user.id, required_role):
            return True

    # No access
    abort(404)  # Return 404 instead of 403 to not reveal existence


def require_project_access(required_role=TeamRole.VIEWER):
    """
    Decorator to enforce project access permissions.

    Usage:
        @require_project_access(TeamRole.EDITOR)
        def update_project(project_id):
            project = get_project_or_404(project_id)
            ...

    Args:
        required_role: Minimum required team role

    Returns:
        Decorated function that checks permissions
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # The decorated function should accept a project parameter
            # or fetch it using project_id from kwargs
            if "project" in kwargs:
                project = kwargs["project"]
            elif "project_id" in kwargs:
                project = db.session.execute(
                    select(Project).where(Project.id == kwargs["project_id"])
                ).scalar_one_or_none()
                if not project:
                    abort(404)
                kwargs["project"] = project
            else:
                raise ValueError(
                    "Decorated function must accept 'project' or 'project_id' parameter"
                )

            check_project_access(project, required_role)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def can_edit_project(project):
    """
    Check if current user can edit a project.

    Args:
        project: Project instance

    Returns:
        bool: True if user can edit, False otherwise
    """
    if not current_user.is_authenticated:
        return False

    # Owner can always edit
    if project.user_id == current_user.id:
        return True

    # Team admins and editors can edit
    if project.team_id:
        team = project.team
        if team:
            return team.has_permission(current_user.id, TeamRole.EDITOR)

    return False


def can_delete_project(project):
    """
    Check if current user can delete a project.

    Args:
        project: Project instance

    Returns:
        bool: True if user can delete, False otherwise
    """
    if not current_user.is_authenticated:
        return False

    # Only owner and team admins can delete
    if project.user_id == current_user.id:
        return True

    if project.team_id:
        team = project.team
        if team:
            return team.has_permission(current_user.id, TeamRole.ADMIN)

    return False


def can_share_project(project):
    """
    Check if current user can share a project with a team.

    Args:
        project: Project instance

    Returns:
        bool: True if user can share, False otherwise
    """
    if not current_user.is_authenticated:
        return False

    # Only the project owner can share/unshare
    return project.user_id == current_user.id


def get_user_team_role(team, user_id=None):
    """
    Get a user's role in a team.

    Args:
        team: Team instance
        user_id: User ID (defaults to current_user.id)

    Returns:
        TeamRole or None if user is not a member
    """
    if user_id is None:
        if not current_user.is_authenticated:
            return None
        user_id = current_user.id

    return team.get_member_role(user_id)


def can_manage_team(team, user_id=None):
    """
    Check if a user can manage team settings (name, description, members).

    Args:
        team: Team instance
        user_id: User ID (defaults to current_user.id)

    Returns:
        bool: True if user can manage team, False otherwise
    """
    if user_id is None:
        if not current_user.is_authenticated:
            return False
        user_id = current_user.id

    # Owner and admins can manage team
    return team.has_permission(user_id, TeamRole.ADMIN)


def can_delete_team(team, user_id=None):
    """
    Check if a user can delete a team.

    Args:
        team: Team instance
        user_id: User ID (defaults to current_user.id)

    Returns:
        bool: True if user can delete team, False otherwise
    """
    if user_id is None:
        if not current_user.is_authenticated:
            return False
        user_id = current_user.id

    # Only team owner can delete
    return team.owner_id == user_id
