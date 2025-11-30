"""
Notification helper functions for creating and managing user notifications.

This module provides functions for creating notifications based on team/project
activities. Notifications are sent to relevant users when important events occur.
"""

from flask_login import current_user
from sqlalchemy import select

from app.models import (
    ActivityType,
    Notification,
    NotificationPreferences,
    Team,
    TeamMembership,
    User,
    db,
)


def send_email_notification(
    user: User,
    notification_type: ActivityType,
    subject: str,
    message: str,
    context: dict | None = None,
):
    """
    Send an email notification if user has enabled it for this event type.

    Args:
        user: User to notify
        notification_type: Type of notification
        subject: Email subject line
        message: Email body text
        context: Additional context (optional)
    """
    from app.mailer import send_email

    # Get user's notification preferences
    prefs = NotificationPreferences.get_or_create(user.id)

    # Check if email is enabled for this notification type
    should_send = False

    if notification_type == ActivityType.COMPILATION_COMPLETED:
        should_send = prefs.email_compilation_complete
    elif notification_type == ActivityType.COMPILATION_FAILED:
        should_send = prefs.email_compilation_failed
    elif notification_type == ActivityType.MEMBER_ADDED:
        should_send = prefs.email_team_member_added
    elif notification_type == ActivityType.PROJECT_SHARED:
        should_send = prefs.email_project_shared

    if not should_send:
        return

    # Send the email
    try:
        send_email(
            to_address=user.email,
            subject=subject,
            text=message,
        )
    except Exception as e:
        # Log but don't fail - email is non-critical
        try:
            from flask import current_app

            current_app.logger.warning(f"Failed to send email notification: {e}")
        except Exception:
            pass


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

    # Send push notification if configured
    try:
        from flask import current_app

        if hasattr(current_app.config, "VAPID_PRIVATE_KEY") and hasattr(
            current_app.config, "VAPID_CLAIMS"
        ):
            user = db.session.get(User, user_id)
            if user:
                from app.push import send_push_notification

                send_push_notification(
                    user=user,
                    title="ClippyFront Notification",
                    body=message,
                    notification_type=notification_type.value,
                    project_id=project_id,
                    team_id=team_id,
                    vapid_private_key=current_app.config.VAPID_PRIVATE_KEY,
                    vapid_claims=current_app.config.VAPID_CLAIMS,
                )
    except Exception as e:
        # Don't fail notification creation if push fails
        import logging

        logging.warning(f"Failed to send push notification: {e}")


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

        # Send email notification for project sharing
        if notification_type == ActivityType.PROJECT_SHARED:
            user = db.session.get(User, user_id)
            if user and context:
                project_name = context.get("project_name", "a project")
                team_name = context.get("team_name", team.name)
                send_email_notification(
                    user=user,
                    notification_type=ActivityType.PROJECT_SHARED,
                    subject=f"Project Shared: {project_name}",
                    message=f"A project '{project_name}' has been shared with your team '{team_name}'.\n\n"
                    f"You can now view and collaborate on this project.",
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

    # Send email to new member
    send_email_notification(
        user=new_user,
        notification_type=ActivityType.MEMBER_ADDED,
        subject=f"Added to Team: {team.name}",
        message=f"You have been added to the team '{team.name}' as a {role}.\n\n"
        f"You can now collaborate with other team members and share projects.",
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

        # Send email notification
        user = db.session.get(User, project.user_id)
        if user:
            send_email_notification(
                user=user,
                notification_type=ActivityType.COMPILATION_COMPLETED,
                subject=f"Compilation Complete: {project.name}",
                message=f"Your video compilation '{project.name}' has finished processing successfully.\n\n"
                f"You can now download your compiled video from the project page.",
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

        # Send email notification
        user = db.session.get(User, project.user_id)
        if user:
            send_email_notification(
                user=user,
                notification_type=ActivityType.COMPILATION_FAILED,
                subject=f"Compilation Failed: {project.name}",
                message=f"Your video compilation '{project.name}' failed to process.\n\n"
                f"Error: {error}\n\n"
                f"Please check your project settings and try again.",
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
    user_id: int,
    limit: int = 20,
    offset: int = 0,
    unread_only: bool = False,
    notification_type: str | None = None,
    date_range: str | None = None,
):
    """
    Get notifications for a user with pagination and filtering.

    Args:
        user_id: User ID
        limit: Maximum number of notifications to return
        offset: Offset for pagination
        unread_only: Only return unread notifications
        notification_type: Filter by notification type (optional)
        date_range: Filter by date range: today, week, month, 3months (optional)

    Returns:
        List of Notification objects
    """
    from datetime import datetime, timedelta

    query = select(Notification).where(Notification.user_id == user_id)

    if unread_only:
        query = query.where(Notification.is_read.is_(False))

    if notification_type:
        from app.models import ActivityType

        try:
            activity_type = ActivityType[notification_type]
            query = query.where(Notification.type == activity_type)
        except KeyError:
            pass  # Invalid type, ignore filter

    if date_range:
        now = datetime.utcnow()
        cutoff = None
        if date_range == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif date_range == "week":
            cutoff = now - timedelta(days=7)
        elif date_range == "month":
            cutoff = now - timedelta(days=30)
        elif date_range == "3months":
            cutoff = now - timedelta(days=90)

        if cutoff:
            query = query.where(Notification.created_at >= cutoff)

    query = query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)

    return list(db.session.execute(query).scalars())


def get_user_notifications_count(
    user_id: int,
    unread_only: bool = False,
    notification_type: str | None = None,
    date_range: str | None = None,
):
    """
    Get total count of notifications for a user with filtering.

    Args:
        user_id: User ID
        unread_only: Only count unread notifications
        notification_type: Filter by notification type (optional)
        date_range: Filter by date range (optional)

    Returns:
        Count of notifications matching filters
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func

    query = select(func.count(Notification.id)).where(Notification.user_id == user_id)

    if unread_only:
        query = query.where(Notification.is_read.is_(False))

    if notification_type:
        from app.models import ActivityType

        try:
            activity_type = ActivityType[notification_type]
            query = query.where(Notification.type == activity_type)
        except KeyError:
            pass

    if date_range:
        now = datetime.utcnow()
        cutoff = None
        if date_range == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif date_range == "week":
            cutoff = now - timedelta(days=7)
        elif date_range == "month":
            cutoff = now - timedelta(days=30)
        elif date_range == "3months":
            cutoff = now - timedelta(days=90)

        if cutoff:
            query = query.where(Notification.created_at >= cutoff)

    return db.session.execute(query).scalar() or 0


def mark_all_as_read(user_id: int):
    """Mark all notifications as read for a user."""
    from datetime import datetime

    db.session.execute(
        Notification.__table__.update()
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=datetime.utcnow())
    )
    db.session.commit()
