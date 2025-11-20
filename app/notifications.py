"""
Notification helper functions for creating and managing user notifications.

This module provides functions for creating notifications based on team/project
activities. Notifications are sent to relevant users when important events occur.
"""

from flask_login import current_user
from sqlalchemy import select

from app.models import ActivityType, Notification, Team, TeamMembership, User, db


def create_notification(
    user_id: int,
    notification_type: ActivityType,
    message: str,
    actor_id: int | None = None,
    team_id: int | None = None,
    project_id: int | None = None,
    context: dict | None = None,
):
    """
    Create a notification for a user.

    Args:
        user_id: ID of the user to notify
        notification_type: Type of notification (ActivityType enum)
        message: Human-readable message
        actor_id: ID of the user who triggered the action (optional)
        team_id: ID of the related team (optional)
        project_id: ID of the related project (optional)
        context: Additional metadata (optional)
    """
    # Don't notify the actor about their own actions
    if actor_id and user_id == actor_id:
        return

    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        message=message,
        actor_id=actor_id,
        team_id=team_id,
        project_id=project_id,
        context=context or {},
    )

    db.session.add(notification)
    db.session.commit()


def notify_team_members(
    team_id: int,
    notification_type: ActivityType,
    message: str,
    actor_id: int | None = None,
    project_id: int | None = None,
    context: dict | None = None,
    exclude_user_ids: list[int] | None = None,
):
    """
    Notify all members of a team about an event.

    Args:
        team_id: ID of the team
        notification_type: Type of notification
        message: Human-readable message
        actor_id: ID of the user who triggered the action
        project_id: ID of the related project (optional)
        context: Additional metadata (optional)
        exclude_user_ids: List of user IDs to exclude from notifications
    """
    exclude_ids = set(exclude_user_ids or [])
    if actor_id:
        exclude_ids.add(actor_id)

    # Get team owner and members
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()
    if not team:
        return

    user_ids = set()

    # Add owner
    if team.owner_id not in exclude_ids:
        user_ids.add(team.owner_id)

    # Add all members
    memberships = db.session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team_id)
    ).scalars()

    for membership in memberships:
        if membership.user_id not in exclude_ids:
            user_ids.add(membership.user_id)

    # Create notifications for all users
    for user_id in user_ids:
        create_notification(
            user_id=user_id,
            notification_type=notification_type,
            message=message,
            actor_id=actor_id,
            team_id=team_id,
            project_id=project_id,
            context=context,
        )


# Team-related notification helpers


def notify_team_created(team, actor_id: int | None = None):
    """Notify when a new team is created (currently no-op, owner already knows)."""
    pass


def notify_member_added(team, new_user: User, role: str, actor_id: int | None = None):
    """Notify team members when a new member joins."""
    actor_id = actor_id or current_user.id

    # Notify the new member
    create_notification(
        user_id=new_user.id,
        notification_type=ActivityType.MEMBER_ADDED,
        message=f"You were added to team '{team.name}' as {role}",
        actor_id=actor_id,
        team_id=team.id,
        context={"role": role},
    )

    # Notify existing team members
    notify_team_members(
        team_id=team.id,
        notification_type=ActivityType.MEMBER_ADDED,
        message=f"{new_user.username} joined the team as {role}",
        actor_id=actor_id,
        exclude_user_ids=[new_user.id],
        context={"username": new_user.username, "role": role},
    )


def notify_member_removed(team, removed_user: User, actor_id: int | None = None):
    """Notify when a member is removed from a team."""
    actor_id = actor_id or current_user.id

    # Notify the removed user
    create_notification(
        user_id=removed_user.id,
        notification_type=ActivityType.MEMBER_REMOVED,
        message=f"You were removed from team '{team.name}'",
        actor_id=actor_id,
        team_id=team.id,
    )

    # Notify remaining team members
    notify_team_members(
        team_id=team.id,
        notification_type=ActivityType.MEMBER_REMOVED,
        message=f"{removed_user.username} was removed from the team",
        actor_id=actor_id,
        exclude_user_ids=[removed_user.id],
        context={"username": removed_user.username},
    )


def notify_member_role_changed(
    team, target_user: User, old_role: str, new_role: str, actor_id: int | None = None
):
    """Notify when a member's role changes."""
    actor_id = actor_id or current_user.id

    # Notify the user whose role changed
    create_notification(
        user_id=target_user.id,
        notification_type=ActivityType.MEMBER_ROLE_CHANGED,
        message=f"Your role in team '{team.name}' changed from {old_role} to {new_role}",
        actor_id=actor_id,
        team_id=team.id,
        context={"old_role": old_role, "new_role": new_role},
    )

    # Notify other team members
    notify_team_members(
        team_id=team.id,
        notification_type=ActivityType.MEMBER_ROLE_CHANGED,
        message=f"{target_user.username}'s role changed from {old_role} to {new_role}",
        actor_id=actor_id,
        exclude_user_ids=[target_user.id],
        context={
            "username": target_user.username,
            "old_role": old_role,
            "new_role": new_role,
        },
    )


# Project-related notification helpers


def notify_project_shared(project, team, actor_id: int | None = None):
    """Notify team members when a project is shared with them."""
    actor_id = actor_id or current_user.id

    notify_team_members(
        team_id=team.id,
        notification_type=ActivityType.PROJECT_SHARED,
        message=f"Project '{project.name}' was shared with team '{team.name}'",
        actor_id=actor_id,
        project_id=project.id,
        context={"project_name": project.name, "team_name": team.name},
    )


def notify_project_unshared(project, team_name: str, actor_id: int | None = None):
    """Notify when a project is removed from a team (team members need to know)."""
    # Note: This is tricky since the project is already unshared
    # We would need to get the list before unsharing
    pass


def notify_compilation_completed(project, actor_id: int | None = None):
    """Notify project owner when compilation completes."""
    actor_id = actor_id or current_user.id

    # Notify project owner
    if project.user_id != actor_id:
        create_notification(
            user_id=project.user_id,
            notification_type=ActivityType.COMPILATION_COMPLETED,
            message=f"Compilation of '{project.name}' is complete",
            actor_id=actor_id,
            project_id=project.id,
        )

    # Notify team members if shared
    if project.team_id:
        notify_team_members(
            team_id=project.team_id,
            notification_type=ActivityType.COMPILATION_COMPLETED,
            message=f"Compilation of '{project.name}' is complete",
            actor_id=actor_id,
            project_id=project.id,
            exclude_user_ids=[project.user_id],  # Owner already notified
        )


def notify_compilation_failed(project, error: str, actor_id: int | None = None):
    """Notify project owner when compilation fails."""
    actor_id = actor_id or current_user.id

    # Notify project owner
    if project.user_id != actor_id:
        create_notification(
            user_id=project.user_id,
            notification_type=ActivityType.COMPILATION_FAILED,
            message=f"Compilation of '{project.name}' failed",
            actor_id=actor_id,
            project_id=project.id,
            context={"error": error},
        )


# Query helpers


def get_unread_count(user_id: int) -> int:
    """Get count of unread notifications for a user."""
    from sqlalchemy import func

    return (
        db.session.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)
            )
        ).scalar()
        or 0
    )


def get_user_notifications(
    user_id: int, limit: int = 20, offset: int = 0, unread_only: bool = False
):
    """
    Get notifications for a user with pagination.

    Args:
        user_id: User ID
        limit: Maximum number of notifications to return
        offset: Offset for pagination
        unread_only: Only return unread notifications

    Returns:
        List of Notification objects
    """
    query = select(Notification).where(Notification.user_id == user_id)

    if unread_only:
        query = query.where(Notification.is_read.is_(False))

    query = query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)

    return list(db.session.execute(query).scalars())


def mark_all_as_read(user_id: int):
    """Mark all notifications as read for a user."""
    from datetime import datetime

    db.session.execute(
        Notification.__table__.update()
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=datetime.utcnow())
    )
    db.session.commit()
