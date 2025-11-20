"""Tests for team collaboration features."""
from app.models import Project, Team, TeamMembership, TeamRole, User, db


class TestTeamModel:
    """Test Team model methods and relationships."""

    def test_create_team(self, app):
        """Should create team with owner."""
        with app.app_context():
            user = User(username="owner", email="owner@example.com")
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()

            team = Team(name="Test Team", owner_id=user.id)
            db.session.add(team)
            db.session.commit()

            assert team.id is not None
            assert team.name == "Test Team"
            assert team.owner_id == user.id
            assert team.owner.username == "owner"

    def test_get_member_role(self, app):
        """Should return member role or None."""
        with app.app_context():
            owner = User(username="owner", email="owner@example.com")
            owner.set_password("password123")
            member = User(username="member", email="member@example.com")
            member.set_password("password123")
            db.session.add_all([owner, member])
            db.session.commit()

            team = Team(name="Test Team", owner_id=owner.id)
            db.session.add(team)
            db.session.commit()

            # Add member
            membership = TeamMembership(
                team_id=team.id, user_id=member.id, role=TeamRole.EDITOR
            )
            db.session.add(membership)
            db.session.commit()

            # Check roles
            assert team.get_member_role(member.id) == TeamRole.EDITOR
            assert team.get_member_role(999) is None  # Non-member

    def test_has_permission_hierarchy(self, app):
        """Should enforce role hierarchy for permissions."""
        with app.app_context():
            owner = User(username="owner", email="owner@example.com")
            owner.set_password("password123")
            admin = User(username="admin", email="admin@example.com")
            admin.set_password("password123")
            editor = User(username="editor", email="editor@example.com")
            editor.set_password("password123")
            viewer = User(username="viewer", email="viewer@example.com")
            viewer.set_password("password123")
            db.session.add_all([owner, admin, editor, viewer])
            db.session.commit()

            team = Team(name="Test Team", owner_id=owner.id)
            db.session.add(team)
            db.session.commit()

            # Add members with different roles
            memberships = [
                TeamMembership(team_id=team.id, user_id=admin.id, role=TeamRole.ADMIN),
                TeamMembership(
                    team_id=team.id, user_id=editor.id, role=TeamRole.EDITOR
                ),
                TeamMembership(
                    team_id=team.id, user_id=viewer.id, role=TeamRole.VIEWER
                ),
            ]
            db.session.add_all(memberships)
            db.session.commit()

            # Test hierarchy
            assert team.has_permission(owner.id, TeamRole.OWNER)  # Owner has all
            assert team.has_permission(owner.id, TeamRole.ADMIN)
            assert team.has_permission(owner.id, TeamRole.EDITOR)
            assert team.has_permission(owner.id, TeamRole.VIEWER)

            assert not team.has_permission(admin.id, TeamRole.OWNER)  # Admin < Owner
            assert team.has_permission(admin.id, TeamRole.ADMIN)
            assert team.has_permission(admin.id, TeamRole.EDITOR)
            assert team.has_permission(admin.id, TeamRole.VIEWER)

            assert not team.has_permission(editor.id, TeamRole.ADMIN)  # Editor < Admin
            assert team.has_permission(editor.id, TeamRole.EDITOR)
            assert team.has_permission(editor.id, TeamRole.VIEWER)

            assert not team.has_permission(viewer.id, TeamRole.EDITOR)  # Viewer lowest
            assert team.has_permission(viewer.id, TeamRole.VIEWER)


class TestTeamAPI:
    """Test team management API endpoints."""

    def test_list_teams(self, client, auth):
        """Should list teams user owns or is member of."""
        auth.login()
        response = client.get("/api/teams")
        assert response.status_code == 200
        data = response.get_json()
        assert "teams" in data
        assert isinstance(data["teams"], list)

    def test_create_team(self, client, auth, app):
        """Should create new team with user as owner."""
        auth.login()
        response = client.post(
            "/api/teams",
            json={"name": "New Team", "description": "Test team description"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["name"] == "New Team"
        assert data["description"] == "Test team description"
        assert "id" in data

        # Verify in database
        with app.app_context():
            team = db.session.get(Team, data["id"])
            assert team is not None
            assert team.name == "New Team"

    def test_create_team_requires_name(self, client, auth):
        """Should require team name."""
        auth.login()
        response = client.post("/api/teams", json={})
        assert response.status_code == 400

    def test_get_team_details(self, client, auth, app, test_user):
        """Should return team details with members and projects."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Test Team Details"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        response = client.get(f"/api/teams/{team_id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "Test Team Details"
        assert "members" in data
        assert "projects" in data
        assert data["can_manage"] is True  # Owner can manage

    def test_update_team(self, client, auth, app, test_user):
        """Should update team details."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Original Name"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Update team
        response = client.put(
            f"/api/teams/{team_id}",
            json={"name": "Updated Team", "description": "New description"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "Updated Team"
        assert data["description"] == "New description"

    def test_delete_team(self, client, auth, app):
        """Should delete team."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Team To Delete"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Delete team
        response = client.delete(f"/api/teams/{team_id}")
        assert response.status_code == 204

        # Verify deleted
        with app.app_context():
            team = db.session.get(Team, team_id)
            assert team is None

    def test_add_member(self, client, auth, app, test_user):
        """Should add member to team."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Member Test Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Create another user
        with app.app_context():
            new_member = User(username="newmember_team", email="newteam@example.com")
            new_member.set_password("password123")
            db.session.add(new_member)
            db.session.commit()

        response = client.post(
            f"/api/teams/{team_id}/members",
            json={"username": "newmember_team", "role": "editor"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["username"] == "newmember_team"
        assert data["role"] == "editor"

    def test_update_member_role(self, client, auth, app, test_user):
        """Should update member role."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Role Update Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Create member and add via API
        with app.app_context():
            member = User(username="member_role", email="member_role@example.com")
            member.set_password("password123")
            db.session.add(member)
            db.session.commit()
            member_id = member.id

        # Add member first
        response = client.post(
            f"/api/teams/{team_id}/members",
            json={"user_id": member_id, "role": "viewer"},
        )
        assert response.status_code == 201

        # Update role
        response = client.put(
            f"/api/teams/{team_id}/members/{member_id}", json={"role": "admin"}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["role"] == "admin"

    def test_remove_member(self, client, auth, app, test_user):
        """Should remove member from team."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Remove Member Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        # Create member and add to team
        with app.app_context():
            member = User(username="member_remove", email="member_remove@example.com")
            member.set_password("password123")
            db.session.add(member)
            db.session.commit()
            member_id = member.id

        # Add member
        response = client.post(
            f"/api/teams/{team_id}/members",
            json={"user_id": member_id, "role": "viewer"},
        )
        assert response.status_code == 201

        # Remove member
        response = client.delete(f"/api/teams/{team_id}/members/{member_id}")
        assert response.status_code == 204

        # Verify removed
        with app.app_context():
            from sqlalchemy import select

            membership = db.session.execute(
                select(TeamMembership)
                .where(TeamMembership.team_id == team_id)
                .where(TeamMembership.user_id == member_id)
            ).scalar_one_or_none()

            assert membership is None

    def test_leave_team(self, client, app):
        """Should allow member to leave team."""
        # Create team and users
        with app.app_context():
            owner = User(username="owner_leave", email="owner_leave@example.com")
            owner.set_password("password123")
            member = User(username="member_leave", email="member_leave@example.com")
            member.set_password("password123")
            db.session.add_all([owner, member])
            db.session.commit()

            team = Team(name="Leave Team", owner_id=owner.id)
            db.session.add(team)
            db.session.commit()

            membership = TeamMembership(
                team_id=team.id, user_id=member.id, role=TeamRole.VIEWER
            )
            db.session.add(membership)
            db.session.commit()
            team_id = team.id
            member_id = member.id

        # Login as member
        client.post(
            "/auth/login",
            data={"username_or_email": "member_leave", "password": "password123"},
        )

        response = client.post(f"/api/teams/{team_id}/leave")
        assert response.status_code == 200

        # Verify left
        with app.app_context():
            from sqlalchemy import select

            membership = db.session.execute(
                select(TeamMembership)
                .where(TeamMembership.team_id == team_id)
                .where(TeamMembership.user_id == member_id)
            ).scalar_one_or_none()

            assert membership is None


class TestProjectSharing:
    """Test project sharing with teams."""

    def test_share_project(self, client, auth, app, test_user, test_project):
        """Should share project with team."""
        auth.login()

        # Create team via API
        response = client.post("/api/teams", json={"name": "Share Project Team"})
        assert response.status_code == 201
        team_data = response.get_json()
        team_id = team_data["id"]

        response = client.post(
            f"/api/projects/{test_project}/share", json={"team_id": team_id}
        )
        assert response.status_code == 200

        # Verify shared
        with app.app_context():
            project = db.session.get(Project, test_project)
            assert project.team_id == team_id

    def test_unshare_project(self, client, auth, app, test_user, test_project):
        """Should unshare project from team."""
        auth.login()

        # Create team and share project
        with app.app_context():
            user = db.session.get(User, test_user)
            team = Team(name="Test Team", owner_id=user.id)
            db.session.add(team)
            db.session.commit()

            project = db.session.get(Project, test_project)
            project.team_id = team.id
            db.session.commit()

        response = client.post(
            f"/api/projects/{test_project}/share", json={"team_id": None}
        )
        assert response.status_code == 200

        # Verify unshared
        with app.app_context():
            project = db.session.get(Project, test_project)
            assert project.team_id is None

    def test_share_project_requires_ownership(self, client, app):
        """Should only allow project owner to share."""
        # Create two users
        with app.app_context():
            owner = User(username="owner", email="owner@example.com")
            owner.set_password("password123")
            other = User(username="other", email="other@example.com")
            other.set_password("password123")
            db.session.add_all([owner, other])
            db.session.commit()

            project = Project(name="Test Project", user_id=owner.id)
            team = Team(name="Test Team", owner_id=other.id)
            db.session.add_all([project, team])
            db.session.commit()
            project_id = project.id
            team_id = team.id

        # Login as non-owner
        client.post(
            "/auth/login", data={"username": "other", "password": "password123"}
        )

        response = client.post(
            f"/api/projects/{project_id}/share", json={"team_id": team_id}
        )
        assert response.status_code in (403, 404)  # Forbidden or Not Found
