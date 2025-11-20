"""Tests for activity logging and team invitations."""
from datetime import datetime, timedelta

from app.activity import (
    get_project_activities,
    get_team_activities,
    log_compilation_completed,
    log_member_added,
    log_project_shared,
    log_team_created,
)
from app.models import (
    ActivityLog,
    ActivityType,
    Project,
    Team,
    TeamInvitation,
    TeamMembership,
    TeamRole,
    User,
    db,
)


class TestActivityLogging:
    """Test activity logging functions."""

    def test_log_team_created(self, app, test_user):
        """Should log team creation activity."""
        with app.app_context():
            user = db.session.get(User, test_user)
            team = Team(name="New Team", owner_id=user.id)
            db.session.add(team)
            db.session.commit()

            # Log activity
            log_team_created(team, user)

            # Verify log created
            activity = (
                db.session.query(ActivityLog)
                .filter_by(team_id=team.id, activity_type=ActivityType.TEAM_CREATED)
                .first()
            )
            assert activity is not None
            assert activity.user_id == user.id
            assert activity.context["team_name"] == "New Team"

    def test_log_member_added(self, app):
        """Should log member addition activity."""
        with app.app_context():
            owner = User(username="owner_act", email="owner_act@example.com")
            owner.set_password("password123")
            member = User(username="member_act", email="member_act@example.com")
            member.set_password("password123")
            db.session.add_all([owner, member])
            db.session.commit()

            team = Team(name="Test Team", owner_id=owner.id)
            db.session.add(team)
            db.session.commit()

            # Log activity
            log_member_added(team, member, "editor", user=owner)

            # Verify log created
            from sqlalchemy import select

            activity = db.session.execute(
                select(ActivityLog)
                .where(ActivityLog.team_id == team.id)
                .where(ActivityLog.activity_type == ActivityType.MEMBER_ADDED)
            ).scalar_one_or_none()

            assert activity is not None
            assert activity.context["target_username"] == "member_act"
            assert activity.context["role"] == "editor"

    def test_log_project_shared(self, app, test_user, test_project):
        """Should log project sharing activity."""
        with app.app_context():
            user = db.session.get(User, test_user)
            team = Team(name="Test Team", owner_id=user.id)
            db.session.add(team)
            db.session.commit()

            project = db.session.get(Project, test_project)
            project.team_id = team.id
            db.session.commit()

            # Log activity
            log_project_shared(project, team, user)

            # Verify log created
            activity = (
                db.session.query(ActivityLog)
                .filter_by(
                    project_id=test_project, activity_type=ActivityType.PROJECT_SHARED
                )
                .first()
            )
            assert activity is not None
            assert activity.team_id == team.id

    def test_log_compilation_completed(self, app, test_user, test_project):
        """Should log compilation completion."""
        with app.app_context():
            user = db.session.get(User, test_user)
            project = db.session.get(Project, test_project)

            # Log activity
            log_compilation_completed(project, user)

            # Verify log created
            from sqlalchemy import select

            activity = db.session.execute(
                select(ActivityLog)
                .where(ActivityLog.project_id == test_project)
                .where(ActivityLog.activity_type == ActivityType.COMPILATION_COMPLETED)
            ).scalar_one_or_none()

            assert activity is not None
            assert activity.context["project_name"] == project.name

    def test_get_team_activities(self, app, test_user):
        """Should retrieve team activities with pagination."""
        with app.app_context():
            user = db.session.get(User, test_user)
            team = Team(name="Test Team Act", owner_id=user.id)
            db.session.add(team)
            db.session.commit()

            # Create multiple activities
            for i in range(15):
                activity = ActivityLog(
                    team_id=team.id,
                    user_id=user.id,
                    activity_type=ActivityType.TEAM_UPDATED,
                    context={"change": f"update {i}"},
                )
                db.session.add(activity)
            db.session.commit()

            # Get first page
            activities = get_team_activities(team.id, limit=10, offset=0)
            assert len(activities) == 10

            # Get second page
            activities = get_team_activities(team.id, limit=10, offset=10)
            assert len(activities) >= 5

    def test_get_project_activities(self, app, test_user, test_project):
        """Should retrieve project activities with pagination."""
        with app.app_context():
            user = db.session.get(User, test_user)

            # Create multiple activities
            for i in range(5):
                activity = ActivityLog(
                    project_id=test_project,
                    user_id=user.id,
                    activity_type=ActivityType.PROJECT_UPDATED,
                    context={"change": f"update {i}"},
                )
                db.session.add(activity)
            db.session.commit()

            # Get activities
            activities = get_project_activities(test_project, limit=10, offset=0)
            assert len(activities) == 5


class TestActivityAPI:
    """Test activity API endpoints."""

    def test_get_team_activity_feed(self, client, auth, app, test_user):
        """Should return team activity feed."""
        auth.login()

        # Create team via API to ensure proper ownership
        response = client.post("/api/teams", json={"name": "Activity Feed Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Get activity feed
        response = client.get(f"/api/teams/{team_id}/activity")
        assert response.status_code == 200
        data = response.get_json()
        assert "activities" in data
        assert len(data["activities"]) >= 1

    def test_get_project_activity_feed(self, client, auth, app, test_project):
        """Should return project activity feed."""
        auth.login()

        # Create activity
        with app.app_context():
            project = db.session.get(Project, test_project)
            log_compilation_completed(project, project.owner)

        response = client.get(f"/api/projects/{test_project}/activity")
        assert response.status_code == 200
        data = response.get_json()
        assert "activities" in data
        assert len(data["activities"]) >= 1

    def test_activity_pagination(self, client, auth, app, test_user):
        """Should paginate activity feed."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Pagination Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Create many activities
        with app.app_context():
            user = db.session.get(User, test_user)
            for i in range(25):
                activity = ActivityLog(
                    team_id=team_id,
                    user_id=user.id,
                    activity_type=ActivityType.TEAM_UPDATED,
                    context={"change": f"update {i}"},
                )
                db.session.add(activity)
            db.session.commit()

        # Request with limit
        response = client.get(f"/api/teams/{team_id}/activity?limit=10")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["activities"]) <= 10


class TestTeamInvitations:
    """Test team invitation system."""

    def test_create_invitation(self, client, auth, app, test_user):
        """Should create team invitation."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Invitation Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        response = client.post(
            f"/api/teams/{team_id}/invitations",
            json={"email": "invitee@example.com", "role": "editor"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["email"] == "invitee@example.com"
        assert data["role"] == "editor"
        assert "token" in data
        assert data["status"] == "pending"

    def test_list_invitations(self, client, auth, app, test_user):
        """Should list team invitations."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "List Invites Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Create invitation via API
        response = client.post(
            f"/api/teams/{team_id}/invitations",
            json={"email": "test@example.com", "role": "viewer"},
        )
        assert response.status_code == 201

        # List invitations
        response = client.get(f"/api/teams/{team_id}/invitations")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) >= 1
        assert data[0]["email"] == "test@example.com"

    def test_get_invitation_details(self, client, auth, app, test_user):
        """Should get invitation details (public endpoint)."""
        auth.login()

        # Create team and invitation via API
        response = client.post("/api/teams", json={"name": "Details Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        response = client.post(
            f"/api/teams/{team_id}/invitations",
            json={"email": "test@example.com", "role": "editor"},
        )
        assert response.status_code == 201
        invite_data = response.get_json()
        token = invite_data["token"]

        # Get invitation (no auth required)
        response = client.get(f"/api/invitations/{token}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["email"] == "test@example.com"
        assert data["role"] == "editor"
        assert "team" in data

    def test_accept_invitation(self, client, app):
        """Should accept invitation and create membership."""
        import secrets
        from datetime import timedelta

        # Create users and invitation
        with app.app_context():
            owner = User(username="owner_accept", email="owner_accept@example.com")
            owner.set_password("password123")
            invitee = User(
                username="invitee_accept", email="invitee_accept@example.com"
            )
            invitee.set_password("password123")
            db.session.add_all([owner, invitee])
            db.session.commit()

            team = Team(name="Accept Team", owner_id=owner.id)
            db.session.add(team)
            db.session.commit()

            token = secrets.token_urlsafe(32)
            invitation = TeamInvitation(
                team_id=team.id,
                invited_by_id=owner.id,
                email="invitee_accept@example.com",
                user_id=invitee.id,
                role=TeamRole.EDITOR,
                token=token,
                expires_at=datetime.utcnow() + timedelta(days=7),
            )
            db.session.add(invitation)
            db.session.commit()
            team_id = team.id
            invitee_id = invitee.id

        # Login as invitee and accept
        client.post(
            "/auth/login",
            data={"username_or_email": "invitee_accept", "password": "password123"},
        )
        response = client.post(f"/api/invitations/{token}/accept")
        assert response.status_code == 200
        data = response.get_json()
        assert "team_id" in data

        # Verify membership created
        with app.app_context():
            from sqlalchemy import select

            membership = db.session.execute(
                select(TeamMembership)
                .where(TeamMembership.team_id == team_id)
                .where(TeamMembership.user_id == invitee_id)
            ).scalar_one_or_none()

            assert membership is not None
            assert membership.role == TeamRole.EDITOR

    def test_decline_invitation(self, client, app):
        """Should decline invitation."""
        import secrets
        from datetime import timedelta

        # Create invitation
        with app.app_context():
            owner = User(username="owner_decline", email="owner_decline@example.com")
            owner.set_password("password123")
            invitee = User(
                username="invitee_decline", email="invitee_decline@example.com"
            )
            invitee.set_password("password123")
            db.session.add_all([owner, invitee])
            db.session.commit()

            team = Team(name="Decline Team", owner_id=owner.id)
            db.session.add(team)
            db.session.commit()

            token = secrets.token_urlsafe(32)
            invitation = TeamInvitation(
                team_id=team.id,
                invited_by_id=owner.id,
                email="invitee_decline@example.com",
                user_id=invitee.id,
                role=TeamRole.EDITOR,
                token=token,
                expires_at=datetime.utcnow() + timedelta(days=7),
            )
            db.session.add(invitation)
            db.session.commit()
            invitation_id = invitation.id

        # Login as invitee and decline
        client.post(
            "/auth/login",
            data={"username_or_email": "invitee_decline", "password": "password123"},
        )
        response = client.post(f"/api/invitations/{token}/decline")
        assert response.status_code == 204

        # Verify status updated
        with app.app_context():
            invitation = db.session.get(TeamInvitation, invitation_id)
            assert invitation.status == "declined"
            assert invitation.responded_at is not None

    def test_cancel_invitation(self, client, auth, app, test_user):
        """Should cancel pending invitation."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Cancel Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Create invitation via API
        response = client.post(
            f"/api/teams/{team_id}/invitations",
            json={"email": "test@example.com", "role": "viewer"},
        )
        assert response.status_code == 201
        invite_data = response.get_json()
        invitation_id = invite_data["id"]

        response = client.delete(f"/api/teams/{team_id}/invitations/{invitation_id}")
        assert response.status_code == 204

        # Verify deleted
        with app.app_context():
            invitation = db.session.get(TeamInvitation, invitation_id)
            assert invitation is None

    def test_invitation_expiration(self, app, test_user):
        """Should validate invitation expiration."""
        import secrets

        with app.app_context():
            user = db.session.get(User, test_user)
            team = Team(name="Expire Team", owner_id=user.id)
            db.session.add(team)
            db.session.commit()

            # Create expired invitation
            token = secrets.token_urlsafe(32)
            invitation = TeamInvitation(
                team_id=team.id,
                invited_by_id=user.id,
                email="test@example.com",
                role=TeamRole.VIEWER,
                token=token,
                expires_at=datetime.utcnow() - timedelta(days=1),
            )
            db.session.add(invitation)
            db.session.commit()

            assert invitation.is_valid() is False

    def test_invitation_prevents_duplicates(self, client, auth, app, test_user):
        """Should prevent duplicate invitations."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Duplicate Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Create first invitation
        response = client.post(
            f"/api/teams/{team_id}/invitations",
            json={"email": "test@example.com", "role": "viewer"},
        )
        assert response.status_code == 201

        # Try to create duplicate
        response = client.post(
            f"/api/teams/{team_id}/invitations",
            json={"email": "test@example.com", "role": "editor"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "already" in data["error"].lower()
