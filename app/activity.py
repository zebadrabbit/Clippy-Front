"""
Activity logging utilities for team collaboration.

This module provides helper functions to log activities throughout
the application for audit trails and activity feeds.
"""

from typing import Optional

from flask_login import current_user

from app.models import ActivityLog, ActivityType, Project, Team, User, db


def log_activity(
    activity_type: ActivityType,
    user: Optional[User] = None,
    team: Optional[Team] = None,
    project: Optional[Project] = None,
    context: Optional[dict] = None,
) -> ActivityLog:
    """
    Log an activity to the activity log.

    Args:
        activity_type: Type of activity being logged
        user: User who performed the activity (defaults to current_user)
        team: Team associated with the activity (optional)
        project: Project associated with the activity (optional)
        context: Additional context data (optional)

    Returns:
        ActivityLog: The created activity log entry

    Example:
        log_activity(
            ActivityType.MEMBER_ADDED,
            team=team,
            context={"target_user_id": new_member.id, "role": "editor"}
        )
    """
    if user is None:
        if current_user.is_authenticated:
            user = current_user._get_current_object()
        else:
            raise ValueError(
                "User must be provided or current_user must be authenticated"
            )

    activity = ActivityLog(
        activity_type=activity_type,
        user_id=user.id,
        team_id=team.id if team else None,
        project_id=project.id if project else None,
        context=context,
    )

    db.session.add(activity)
    db.session.commit()

    return activity


def log_team_created(team: Team, user: Optional[User] = None) -> ActivityLog:
    """Log team creation activity."""
    return log_activity(
        ActivityType.TEAM_CREATED,
        user=user,
        team=team,
        context={"team_name": team.name},
    )


def log_team_updated(
    team: Team, changes: dict, user: Optional[User] = None
) -> ActivityLog:
    """
    Log team update activity.

    Args:
        team: Team that was updated
        changes: Dictionary of changed fields (e.g., {"name": "New Name"})
        user: User who made the update
    """
    return log_activity(
        ActivityType.TEAM_UPDATED, user=user, team=team, context={"changes": changes}
    )


def log_team_deleted(team: Team, user: Optional[User] = None) -> ActivityLog:
    """Log team deletion activity."""
    return log_activity(
        ActivityType.TEAM_DELETED,
        user=user,
        context={"team_id": team.id, "team_name": team.name},
    )


def log_member_added(
    team: Team, target_user: User, role: str, user: Optional[User] = None
) -> ActivityLog:
    """
    Log member addition to team.

    Args:
        team: Team the member was added to
        target_user: User who was added
        role: Role assigned to the new member
        user: User who added the member
    """
    return log_activity(
        ActivityType.MEMBER_ADDED,
        user=user,
        team=team,
        context={
            "target_user_id": target_user.id,
            "target_username": target_user.username,
            "role": role,
        },
    )


def log_member_removed(
    team: Team, target_user: User, user: Optional[User] = None
) -> ActivityLog:
    """
    Log member removal from team.

    Args:
        team: Team the member was removed from
        target_user: User who was removed
        user: User who removed the member
    """
    return log_activity(
        ActivityType.MEMBER_REMOVED,
        user=user,
        team=team,
        context={
            "target_user_id": target_user.id,
            "target_username": target_user.username,
        },
    )


def log_member_left(team: Team, user: Optional[User] = None) -> ActivityLog:
    """Log member leaving team voluntarily."""
    return log_activity(ActivityType.MEMBER_LEFT, user=user, team=team)


def log_member_role_changed(
    team: Team,
    target_user: User,
    old_role: str,
    new_role: str,
    user: Optional[User] = None,
) -> ActivityLog:
    """
    Log member role change.

    Args:
        team: Team where role was changed
        target_user: User whose role was changed
        old_role: Previous role
        new_role: New role
        user: User who changed the role
    """
    return log_activity(
        ActivityType.MEMBER_ROLE_CHANGED,
        user=user,
        team=team,
        context={
            "target_user_id": target_user.id,
            "target_username": target_user.username,
            "old_role": old_role,
            "new_role": new_role,
        },
    )


def log_project_created(project: Project, user: Optional[User] = None) -> ActivityLog:
    """Log project creation."""
    return log_activity(
        ActivityType.PROJECT_CREATED,
        user=user,
        project=project,
        team=project.team if project.team_id else None,
        context={"project_name": project.name},
    )


def log_project_shared(
    project: Project, team: Team, user: Optional[User] = None
) -> ActivityLog:
    """
    Log project being shared with a team.

    Args:
        project: Project that was shared
        team: Team the project was shared with
        user: User who shared the project
    """
    return log_activity(
        ActivityType.PROJECT_SHARED,
        user=user,
        project=project,
        team=team,
        context={"project_name": project.name, "team_name": team.name},
    )


def log_project_unshared(
    project: Project, team_name: str, user: Optional[User] = None
) -> ActivityLog:
    """
    Log project being unshared from a team.

    Args:
        project: Project that was unshared
        team_name: Name of the team it was unshared from
        user: User who unshared the project
    """
    return log_activity(
        ActivityType.PROJECT_UNSHARED,
        user=user,
        project=project,
        context={"project_name": project.name, "team_name": team_name},
    )


def log_project_updated(
    project: Project, changes: dict, user: Optional[User] = None
) -> ActivityLog:
    """
    Log project update.

    Args:
        project: Project that was updated
        changes: Dictionary of changed fields
        user: User who made the update
    """
    return log_activity(
        ActivityType.PROJECT_UPDATED,
        user=user,
        project=project,
        team=project.team if project.team_id else None,
        context={"changes": changes, "project_name": project.name},
    )


def log_project_deleted(project: Project, user: Optional[User] = None) -> ActivityLog:
    """Log project deletion."""
    return log_activity(
        ActivityType.PROJECT_DELETED,
        user=user,
        team=project.team if project.team_id else None,
        context={"project_id": project.id, "project_name": project.name},
    )


def log_preview_generated(project: Project, user: Optional[User] = None) -> ActivityLog:
    """Log preview video generation."""
    return log_activity(
        ActivityType.PREVIEW_GENERATED,
        user=user,
        project=project,
        team=project.team if project.team_id else None,
        context={"project_name": project.name},
    )


def log_compilation_started(
    project: Project, user: Optional[User] = None
) -> ActivityLog:
    """Log compilation start."""
    return log_activity(
        ActivityType.COMPILATION_STARTED,
        user=user,
        project=project,
        team=project.team if project.team_id else None,
        context={"project_name": project.name},
    )


def log_compilation_completed(
    project: Project, user: Optional[User] = None
) -> ActivityLog:
    """Log successful compilation completion."""
    return log_activity(
        ActivityType.COMPILATION_COMPLETED,
        user=user,
        project=project,
        team=project.team if project.team_id else None,
        context={"project_name": project.name},
    )


def log_compilation_failed(
    project: Project, error: str, user: Optional[User] = None
) -> ActivityLog:
    """
    Log compilation failure.

    Args:
        project: Project that failed to compile
        error: Error message or description
        user: User who attempted the compilation
    """
    return log_activity(
        ActivityType.COMPILATION_FAILED,
        user=user,
        project=project,
        team=project.team if project.team_id else None,
        context={"project_name": project.name, "error": error},
    )


def get_team_activities(
    team_id: int, limit: int = 50, offset: int = 0
) -> list[ActivityLog]:
    """
    Get recent activities for a team.

    Args:
        team_id: Team ID to fetch activities for
        limit: Maximum number of activities to return
        offset: Number of activities to skip (for pagination)

    Returns:
        List of ActivityLog entries
    """
    from sqlalchemy import select

    stmt = (
        select(ActivityLog)
        .where(ActivityLog.team_id == team_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return db.session.execute(stmt).scalars().all()


def get_project_activities(
    project_id: int, limit: int = 50, offset: int = 0
) -> list[ActivityLog]:
    """
    Get recent activities for a project.

    Args:
        project_id: Project ID to fetch activities for
        limit: Maximum number of activities to return
        offset: Number of activities to skip (for pagination)

    Returns:
        List of ActivityLog entries
    """
    from sqlalchemy import select

    stmt = (
        select(ActivityLog)
        .where(ActivityLog.project_id == project_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return db.session.execute(stmt).scalars().all()


def get_user_activities(
    user_id: int, limit: int = 50, offset: int = 0
) -> list[ActivityLog]:
    """
    Get recent activities by a user.

    Args:
        user_id: User ID to fetch activities for
        limit: Maximum number of activities to return
        offset: Number of activities to skip (for pagination)

    Returns:
        List of ActivityLog entries
    """
    from sqlalchemy import select

    stmt = (
        select(ActivityLog)
        .where(ActivityLog.user_id == user_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return db.session.execute(stmt).scalars().all()
