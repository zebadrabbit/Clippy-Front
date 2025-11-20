"""
API endpoints for team management.

This module provides REST API endpoints for creating and managing teams,
team memberships, and team-based project sharing.
"""

from datetime import datetime, timedelta

from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_, select

from app.activity import (
    log_member_added,
    log_member_left,
    log_member_removed,
    log_member_role_changed,
    log_project_shared,
    log_project_unshared,
    log_team_created,
    log_team_deleted,
    log_team_updated,
)

# Import the shared blueprint instance
from app.api import api_bp
from app.models import Project, Team, TeamInvitation, TeamMembership, TeamRole, User, db
from app.notifications import (
    notify_member_added,
    notify_member_removed,
    notify_member_role_changed,
    notify_project_shared,
)
from app.team_permissions import (
    can_delete_team,
    can_manage_team,
    get_user_team_role,
)


@api_bp.route("/teams", methods=["GET"])
@login_required
def list_teams():
    """
    List all teams the current user owns or is a member of.

    Returns:
        JSON object with teams array
    """
    # Get teams where user is owner or member
    owned_teams = db.session.execute(
        select(Team).where(Team.owner_id == current_user.id).order_by(Team.name)
    ).scalars()

    member_teams = db.session.execute(
        select(Team)
        .join(TeamMembership)
        .where(TeamMembership.user_id == current_user.id)
        .order_by(Team.name)
    ).scalars()

    # Combine and deduplicate
    teams_dict = {}
    for team in owned_teams:
        teams_dict[team.id] = {
            "id": team.id,
            "name": team.name,
            "description": team.description,
            "owner_id": team.owner_id,
            "is_owner": True,
            "role": "owner",
            "member_count": team.memberships.count() + 1,  # +1 for owner
            "project_count": team.projects.count(),
            "created_at": team.created_at.isoformat(),
        }

    for team in member_teams:
        if team.id not in teams_dict:
            role = get_user_team_role(team)
            teams_dict[team.id] = {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "owner_id": team.owner_id,
                "is_owner": False,
                "role": role.value if role else "viewer",
                "member_count": team.memberships.count() + 1,
                "project_count": team.projects.count(),
                "created_at": team.created_at.isoformat(),
            }

    return jsonify({"teams": list(teams_dict.values())})


@api_bp.route("/teams", methods=["POST"])
@login_required
def create_team():
    """
    Create a new team.

    Request body:
        {
            "name": "Team Name",
            "description": "Optional description"
        }

    Returns:
        JSON object with created team details
    """
    from app.quotas import check_team_creation_quota

    # Check team creation quota
    quota_check = check_team_creation_quota(current_user)
    if not quota_check.ok:
        return (
            jsonify(
                {
                    "error": f"You have reached your team limit ({quota_check.limit} teams). Please upgrade your plan to create more teams."
                }
            ),
            403,
        )

    data = request.get_json()

    if not data or not data.get("name"):
        return jsonify({"error": "Team name is required"}), 400

    name = data["name"].strip()
    if not name:
        return jsonify({"error": "Team name cannot be empty"}), 400

    if len(name) > 128:
        return jsonify({"error": "Team name is too long (max 128 characters)"}), 400

    description = (
        data.get("description", "").strip() if data.get("description") else None
    )

    # Create team
    team = Team(
        name=name,
        description=description,
        owner_id=current_user.id,
    )

    db.session.add(team)
    db.session.commit()

    # Log activity
    log_team_created(team)

    return (
        jsonify(
            {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "owner_id": team.owner_id,
                "is_owner": True,
                "role": "owner",
                "member_count": 1,
                "project_count": 0,
                "created_at": team.created_at.isoformat(),
            }
        ),
        201,
    )


@api_bp.route("/teams/<int:team_id>", methods=["GET"])
@login_required
def get_team(team_id):
    """
    Get detailed information about a team.

    Args:
        team_id: Team ID

    Returns:
        JSON object with team details including members
    """
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    # Check if user has access (owner or member)
    user_role = get_user_team_role(team)
    is_owner = team.owner_id == current_user.id

    if not is_owner and not user_role:
        return jsonify({"error": "Team not found"}), 404

    # Get all members including owner
    members = []

    # Add owner
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
                "joined_at": team.created_at.isoformat(),
            }
        )

    # Add other members
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
                "joined_at": membership.joined_at.isoformat(),
            }
        )

    # Get shared projects
    projects = db.session.execute(
        select(Project)
        .where(Project.team_id == team_id)
        .order_by(Project.created_at.desc())
    ).scalars()

    project_list = [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status.value,
            "created_at": p.created_at.isoformat(),
        }
        for p in projects
    ]

    return jsonify(
        {
            "id": team.id,
            "name": team.name,
            "description": team.description,
            "owner_id": team.owner_id,
            "is_owner": is_owner,
            "user_role": "owner"
            if is_owner
            else (user_role.value if user_role else None),
            "can_manage": can_manage_team(team),
            "can_delete": can_delete_team(team),
            "members": members,
            "projects": project_list,
            "created_at": team.created_at.isoformat(),
            "updated_at": team.updated_at.isoformat() if team.updated_at else None,
        }
    )


@api_bp.route("/teams/<int:team_id>", methods=["PUT"])
@login_required
def update_team(team_id):
    """
    Update team details (name, description).

    Args:
        team_id: Team ID

    Request body:
        {
            "name": "New name",
            "description": "New description"
        }

    Returns:
        JSON object with updated team details
    """
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    if not can_manage_team(team):
        return jsonify({"error": "Permission denied"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    # Update name if provided
    changes = {}
    if "name" in data:
        name = data["name"].strip()
        if not name:
            return jsonify({"error": "Team name cannot be empty"}), 400
        if len(name) > 128:
            return jsonify({"error": "Team name is too long (max 128 characters)"}), 400
        if team.name != name:
            changes["name"] = {"old": team.name, "new": name}
            team.name = name

    # Update description if provided
    if "description" in data:
        new_desc = data["description"].strip() if data["description"] else None
        if team.description != new_desc:
            changes["description"] = {"old": team.description, "new": new_desc}
            team.description = new_desc

    db.session.commit()

    # Log activity if there were changes
    if changes:
        log_team_updated(team, changes)

    return jsonify(
        {
            "id": team.id,
            "name": team.name,
            "description": team.description,
            "updated_at": team.updated_at.isoformat() if team.updated_at else None,
        }
    )


@api_bp.route("/teams/<int:team_id>", methods=["DELETE"])
@login_required
def delete_team(team_id):
    """
    Delete a team. Only the owner can delete a team.

    Args:
        team_id: Team ID

    Returns:
        204 No Content on success
    """
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    if not can_delete_team(team):
        return jsonify({"error": "Permission denied"}), 403

    # Log activity before deletion
    log_team_deleted(team)

    # Unshare all projects (set team_id to NULL)
    db.session.execute(
        db.update(Project).where(Project.team_id == team_id).values(team_id=None)
    )

    # Delete team (cascade will delete memberships)
    db.session.delete(team)
    db.session.commit()

    return "", 204


@api_bp.route("/teams/<int:team_id>/members", methods=["POST"])
@login_required
def add_team_member(team_id):
    """
    Add a member to a team.

    Args:
        team_id: Team ID

    Request body:
        {
            "username": "username_or_email",
            "role": "viewer|editor|admin"
        }

    Returns:
        JSON object with new membership details
    """
    from app.quotas import check_team_member_quota

    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    if not can_manage_team(team):
        return jsonify({"error": "Permission denied"}), 403

    # Check team member quota
    quota_check = check_team_member_quota(team_id, team.owner)
    if not quota_check.ok:
        return (
            jsonify(
                {
                    "error": f"Team has reached its member limit ({quota_check.limit} members). Please upgrade the team owner's plan to add more members."
                }
            ),
            403,
        )

    data = request.get_json()

    # Support both username and user_id
    if data.get("user_id"):
        # Direct user_id provided
        user = db.session.get(User, data["user_id"])
    elif data.get("username"):
        # Find user by username or email
        username_or_email = data["username"].strip()
        user = db.session.execute(
            select(User).where(
                or_(User.username == username_or_email, User.email == username_or_email)
            )
        ).scalar_one_or_none()
    else:
        return jsonify({"error": "Username, email, or user_id is required"}), 400

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Check if user is already the owner
    if user.id == team.owner_id:
        return jsonify({"error": "User is already the team owner"}), 400

    # Check if user is already a member
    existing = db.session.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == team_id, TeamMembership.user_id == user.id
        )
    ).scalar_one_or_none()

    if existing:
        return jsonify({"error": "User is already a team member"}), 400

    # Parse role
    role_str = data.get("role", "viewer").lower()
    try:
        role = TeamRole(role_str)
    except ValueError:
        return jsonify({"error": "Invalid role. Must be viewer, editor, or admin"}), 400

    # Cannot add as owner
    if role == TeamRole.OWNER:
        return jsonify({"error": "Cannot add member with owner role"}), 400

    # Create membership
    membership = TeamMembership(team_id=team_id, user_id=user.id, role=role)

    db.session.add(membership)
    db.session.commit()

    # Log activity
    log_member_added(team, user, role.value)

    # Send notifications
    notify_member_added(team, user, role.value, actor_id=current_user.id)

    return (
        jsonify(
            {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "role": membership.role.value,
                "joined_at": membership.joined_at.isoformat(),
            }
        ),
        201,
    )


@api_bp.route("/teams/<int:team_id>/members/<int:user_id>", methods=["PUT"])
@login_required
def update_team_member_role(team_id, user_id):
    """
    Update a team member's role.

    Args:
        team_id: Team ID
        user_id: User ID

    Request body:
        {
            "role": "viewer|editor|admin"
        }

    Returns:
        JSON object with updated membership details
    """
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    if not can_manage_team(team):
        return jsonify({"error": "Permission denied"}), 403

    # Cannot change owner role
    if user_id == team.owner_id:
        return jsonify({"error": "Cannot change owner role"}), 400

    membership = db.session.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == team_id, TeamMembership.user_id == user_id
        )
    ).scalar_one_or_none()

    if not membership:
        return jsonify({"error": "User is not a team member"}), 404

    data = request.get_json()
    if not data or not data.get("role"):
        return jsonify({"error": "Role is required"}), 400

    # Parse new role
    role_str = data["role"].lower()
    try:
        new_role = TeamRole(role_str)
    except ValueError:
        return jsonify({"error": "Invalid role. Must be viewer, editor, or admin"}), 400

    # Cannot set as owner
    if new_role == TeamRole.OWNER:
        return jsonify({"error": "Cannot set member as owner"}), 400

    old_role = membership.role.value
    membership.role = new_role
    db.session.commit()

    # Log activity
    log_member_role_changed(team, membership.user, old_role, new_role.value)

    # Send notifications
    notify_member_role_changed(
        team, membership.user, old_role, new_role.value, actor_id=current_user.id
    )

    return jsonify(
        {
            "user_id": membership.user_id,
            "username": membership.user.username,
            "role": membership.role.value,
            "updated_at": membership.updated_at.isoformat()
            if membership.updated_at
            else None,
        }
    )


@api_bp.route("/teams/<int:team_id>/members/<int:user_id>", methods=["DELETE"])
@login_required
def remove_team_member(team_id, user_id):
    """
    Remove a member from a team.

    Args:
        team_id: Team ID
        user_id: User ID

    Returns:
        204 No Content on success
    """
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    if not can_manage_team(team):
        return jsonify({"error": "Permission denied"}), 403

    # Cannot remove owner
    if user_id == team.owner_id:
        return jsonify({"error": "Cannot remove team owner"}), 400

    membership = db.session.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == team_id, TeamMembership.user_id == user_id
        )
    ).scalar_one_or_none()

    if not membership:
        return jsonify({"error": "User is not a team member"}), 404

    # Get user object for logging
    target_user = membership.user

    db.session.delete(membership)
    db.session.commit()

    # Log activity
    log_member_removed(team, target_user)

    # Send notifications
    notify_member_removed(team, target_user, actor_id=current_user.id)

    return "", 204


@api_bp.route("/teams/<int:team_id>/leave", methods=["POST"])
@login_required
def leave_team(team_id):
    """
    Leave a team (remove self from team).

    Args:
        team_id: Team ID

    Returns:
        204 No Content on success
    """
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    # Owner cannot leave (must delete team instead)
    if team.owner_id == current_user.id:
        return (
            jsonify({"error": "Team owner cannot leave. Delete the team instead."}),
            400,
        )

    membership = db.session.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == team_id, TeamMembership.user_id == current_user.id
        )
    ).scalar_one_or_none()

    if not membership:
        return jsonify({"error": "You are not a member of this team"}), 404

    db.session.delete(membership)
    db.session.commit()

    # Log activity
    log_member_left(team)

    return jsonify({"message": "You have left the team"}), 200


@api_bp.route("/projects/<int:project_id>/share", methods=["POST"])
@login_required
def share_project_with_team(project_id):
    """
    Share a project with a team.

    Args:
        project_id: Project ID

    Request body:
        {
            "team_id": 123  # or null to unshare
        }

    Returns:
        JSON object with updated project details
    """
    project = db.session.execute(
        select(Project).where(Project.id == project_id)
    ).scalar_one_or_none()

    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Only project owner can share/unshare
    if project.user_id != current_user.id:
        return (
            jsonify({"error": "Permission denied. Only project owner can share."}),
            403,
        )

    data = request.get_json()
    if not data or "team_id" not in data:
        return jsonify({"error": "team_id is required"}), 400

    team_id = data["team_id"]

    if team_id is None:
        # Unshare project
        old_team_name = project.team.name if project.team else "Unknown"
        project.team_id = None
        db.session.commit()

        # Log activity
        log_project_unshared(project, old_team_name)

        return jsonify({"id": project.id, "team_id": None, "shared": False})

    # Share with team
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    # User must be owner or member of the team
    user_role = get_user_team_role(team)
    is_owner = team.owner_id == current_user.id

    if not is_owner and not user_role:
        return jsonify({"error": "You are not a member of this team"}), 403

    project.team_id = team_id
    db.session.commit()

    # Log activity
    log_project_shared(project, team)

    # Send notifications
    notify_project_shared(project, team, actor_id=current_user.id)

    return jsonify(
        {
            "id": project.id,
            "team_id": team_id,
            "team_name": team.name,
            "shared": True,
        }
    )


@api_bp.route("/teams/<int:team_id>/activity", methods=["GET"])
@login_required
def get_team_activity(team_id):
    """
    Get activity feed for a team.

    Args:
        team_id: Team ID

    Query params:
        limit: Max items to return (default 50, max 100)
        offset: Skip N items for pagination (default 0)

    Returns:
        JSON object with activities array and pagination info
    """
    from app.activity import get_team_activities
    from app.models import ActivityLog

    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    # Check user is a member
    user_role = get_user_team_role(team)
    is_owner = team.owner_id == current_user.id

    if not is_owner and not user_role:
        return jsonify({"error": "Permission denied"}), 403

    # Parse pagination params
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))

    # Get activities
    activities = get_team_activities(team_id, limit=limit, offset=offset)

    # Convert to dict
    activities_list = [activity.to_dict() for activity in activities]

    # Get total count for pagination
    total = db.session.execute(
        select(db.func.count(ActivityLog.id)).where(ActivityLog.team_id == team_id)
    ).scalar()

    return jsonify(
        {
            "activities": activities_list,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "has_more": (offset + limit) < total,
            },
        }
    )


@api_bp.route("/projects/<int:project_id>/activity", methods=["GET"])
@login_required
def get_project_activity(project_id):
    """
    Get activity feed for a project.

    Args:
        project_id: Project ID

    Query params:
        limit: Max items to return (default 50, max 100)
        offset: Skip N items for pagination (default 0)

    Returns:
        JSON object with activities array and pagination info
    """
    from app.activity import get_project_activities
    from app.models import ActivityLog
    from app.team_permissions import check_project_access

    project = db.session.execute(
        select(Project).where(Project.id == project_id)
    ).scalar_one_or_none()

    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Check user has access to project
    check_project_access(project, TeamRole.VIEWER)

    # Parse pagination params
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))

    # Get activities
    activities = get_project_activities(project_id, limit=limit, offset=offset)

    # Convert to dict
    activities_list = [activity.to_dict() for activity in activities]

    # Get total count for pagination
    total = db.session.execute(
        select(db.func.count(ActivityLog.id)).where(
            ActivityLog.project_id == project_id
        )
    ).scalar()

    return jsonify(
        {
            "activities": activities_list,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "has_more": (offset + limit) < total,
            },
        }
    )


@api_bp.route("/teams/<int:team_id>/invitations", methods=["POST"])
@login_required
def create_team_invitation(team_id):
    """
    Create and send a team invitation.

    Args:
        team_id: Team ID

    Request body:
        {
            "email": "user@example.com",
            "role": "viewer|editor|admin"
        }

    Returns:
        JSON object with invitation details
    """
    import secrets

    from app.quotas import check_team_member_quota

    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    if not can_manage_team(team):
        return jsonify({"error": "Permission denied"}), 403

    # Check team member quota (including pending invitations)
    quota_check = check_team_member_quota(team_id, team.owner)
    if not quota_check.ok:
        return (
            jsonify(
                {
                    "error": f"Team has reached its member limit ({quota_check.limit} members). Please upgrade the team owner's plan to invite more members."
                }
            ),
            403,
        )

    data = request.get_json()
    if not data or not data.get("email"):
        return jsonify({"error": "Email is required"}), 400

    email = data["email"].strip().lower()

    # Check if user is already a member or owner
    existing_user = db.session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()

    if existing_user:
        if existing_user.id == team.owner_id:
            return jsonify({"error": "User is already the team owner"}), 400

        existing_member = db.session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == existing_user.id,
            )
        ).scalar_one_or_none()

        if existing_member:
            return jsonify({"error": "User is already a team member"}), 400

    # Check for existing pending invitation
    existing_invitation = db.session.execute(
        select(TeamInvitation).where(
            TeamInvitation.team_id == team_id,
            TeamInvitation.email == email,
            TeamInvitation.status == "pending",
        )
    ).scalar_one_or_none()

    if existing_invitation:
        return jsonify({"error": "Invitation already sent to this email"}), 400

    # Parse role
    role_str = data.get("role", "viewer").lower()
    try:
        role = TeamRole(role_str)
    except ValueError:
        return jsonify({"error": "Invalid role"}), 400

    if role == TeamRole.OWNER:
        return jsonify({"error": "Cannot invite as owner"}), 400

    # Create invitation
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=7)

    invitation = TeamInvitation(
        team_id=team_id,
        invited_by_id=current_user.id,
        email=email,
        user_id=existing_user.id if existing_user else None,
        role=role,
        token=token,
        status="pending",
        expires_at=expires_at,
    )

    db.session.add(invitation)
    db.session.commit()

    # Send invitation email
    try:
        from flask import url_for

        from app.mailer import send_team_invitation_email

        invitation_url = url_for(
            "main.accept_team_invitation", token=token, _external=True
        )
        expires_formatted = expires_at.strftime("%B %d, %Y at %I:%M %p UTC")

        send_team_invitation_email(
            to_address=email,
            team_name=team.name,
            inviter_name=current_user.username,
            role=role.value,
            invitation_url=invitation_url,
            expires_at=expires_formatted,
        )
        current_app.logger.info(
            f"Team invitation email sent to {email} for team {team.name}"
        )
    except Exception as e:
        current_app.logger.warning(f"Failed to send invitation email: {e}")
        # Don't fail the request if email fails

    return jsonify(invitation.to_dict()), 201


@api_bp.route("/teams/<int:team_id>/invitations", methods=["GET"])
@login_required
def list_team_invitations(team_id):
    """
    List all invitations for a team.

    Args:
        team_id: Team ID

    Returns:
        JSON array of invitation objects
    """
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    if not can_manage_team(team):
        return jsonify({"error": "Permission denied"}), 403

    invitations = db.session.execute(
        select(TeamInvitation)
        .where(TeamInvitation.team_id == team_id)
        .order_by(TeamInvitation.created_at.desc())
    ).scalars()

    return jsonify([inv.to_dict() for inv in invitations])


@api_bp.route("/invitations/<token>", methods=["GET"])
def get_invitation(token):
    """
    Get invitation details by token (public endpoint).

    Args:
        token: Invitation token

    Returns:
        JSON object with invitation details
    """
    invitation = db.session.execute(
        select(TeamInvitation).where(TeamInvitation.token == token)
    ).scalar_one_or_none()

    if not invitation:
        return jsonify({"error": "Invitation not found"}), 404

    return jsonify(invitation.to_dict())


@api_bp.route("/invitations/<token>/accept", methods=["POST"])
@login_required
def accept_invitation(token):
    """
    Accept a team invitation.

    Args:
        token: Invitation token

    Returns:
        JSON object with membership details
    """
    from app.quotas import check_team_member_quota

    invitation = db.session.execute(
        select(TeamInvitation).where(TeamInvitation.token == token)
    ).scalar_one_or_none()

    if not invitation:
        return jsonify({"error": "Invitation not found"}), 404

    if not invitation.is_valid():
        return jsonify({"error": "Invitation is no longer valid"}), 400

    # Check if user email matches (if they have an account)
    if invitation.user_id and invitation.user_id != current_user.id:
        return (
            jsonify({"error": "This invitation is for a different user"}),
            403,
        )

    # Check if user is already a member
    existing_member = db.session.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == invitation.team_id,
            TeamMembership.user_id == current_user.id,
        )
    ).scalar_one_or_none()

    if existing_member:
        return jsonify({"error": "You are already a member of this team"}), 400

    # Check team member quota before accepting
    quota_check = check_team_member_quota(invitation.team_id, invitation.team.owner)
    if not quota_check.ok:
        return (
            jsonify(
                {
                    "error": f"This team has reached its member limit ({quota_check.limit} members). The team owner needs to upgrade their plan before you can join."
                }
            ),
            403,
        )

    try:
        membership = invitation.accept(current_user)

        # Log activity
        log_member_added(invitation.team, current_user, invitation.role.value)

        # Send notifications (inviter is the actor)
        notify_member_added(
            invitation.team,
            current_user,
            invitation.role.value,
            actor_id=invitation.invited_by_id,
        )

        return jsonify(
            {
                "message": "Invitation accepted",
                "team_id": invitation.team_id,
                "team_name": invitation.team.name,
                "role": membership.role.value,
            }
        )

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@api_bp.route("/invitations/<token>/decline", methods=["POST"])
@login_required
def decline_invitation(token):
    """
    Decline a team invitation.

    Args:
        token: Invitation token

    Returns:
        204 No Content on success
    """
    invitation = db.session.execute(
        select(TeamInvitation).where(TeamInvitation.token == token)
    ).scalar_one_or_none()

    if not invitation:
        return jsonify({"error": "Invitation not found"}), 404

    if invitation.status != "pending":
        return jsonify({"error": "Invitation is not pending"}), 400

    # Check if user email matches (if they have an account)
    if invitation.user_id and invitation.user_id != current_user.id:
        return (
            jsonify({"error": "This invitation is for a different user"}),
            403,
        )

    try:
        invitation.decline()
        return "", 204

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@api_bp.route(
    "/teams/<int:team_id>/invitations/<int:invitation_id>", methods=["DELETE"]
)
@login_required
def cancel_invitation(team_id, invitation_id):
    """
    Cancel a pending invitation.

    Args:
        team_id: Team ID
        invitation_id: Invitation ID

    Returns:
        204 No Content on success
    """
    team = db.session.execute(
        select(Team).where(Team.id == team_id)
    ).scalar_one_or_none()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    if not can_manage_team(team):
        return jsonify({"error": "Permission denied"}), 403

    invitation = db.session.execute(
        select(TeamInvitation).where(
            TeamInvitation.id == invitation_id,
            TeamInvitation.team_id == team_id,
        )
    ).scalar_one_or_none()

    if not invitation:
        return jsonify({"error": "Invitation not found"}), 404

    db.session.delete(invitation)
    db.session.commit()

    return "", 204
