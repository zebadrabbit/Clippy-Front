"""
Tests for admin routes and functionality.

Covers admin dashboard, user management, and tier management.
"""

import pytest

from app.models import User


@pytest.fixture
def admin_auth(client, app):
    """Login as admin user."""

    class AdminAuth:
        def login(self):
            return client.post(
                "/auth/login",
                data={"username_or_email": "admin", "password": "admin1234"},
                follow_redirects=True,
            )

        def logout(self):
            return client.get("/auth/logout", follow_redirects=True)

    auth = AdminAuth()
    auth.login()
    return auth


class TestAdminAccess:
    """Test admin access control."""

    def test_admin_dashboard_requires_auth(self, client):
        """Admin dashboard should require authentication."""
        response = client.get("/admin/", follow_redirects=False)
        assert response.status_code in (301, 302, 401)

    def test_admin_dashboard_requires_admin_role(self, client, auth):
        """Regular user should not access admin dashboard."""
        auth.login()
        response = client.get("/admin/", follow_redirects=True)
        # Should get 403 Forbidden or redirect
        assert (
            response.status_code in (403, 302)
            or b"Forbidden" in response.data
            or b"unauthorized" in response.data.lower()
        )

    def test_admin_dashboard_accessible_by_admin(self, client, admin_auth):
        """Admin user should access admin dashboard."""
        response = client.get("/admin/")
        assert response.status_code == 200
        assert b"Admin" in response.data or b"Dashboard" in response.data


class TestUserManagement:
    """Test admin user management."""

    def test_admin_can_list_users(self, client, admin_auth):
        """Admin should see user list."""
        response = client.get("/admin/users")
        assert response.status_code == 200
        assert b"tester" in response.data or b"Users" in response.data

    def test_admin_can_view_user_details(self, client, admin_auth, app):
        """Admin should view individual user details."""
        with app.app_context():
            user = User.query.filter_by(username="tester").first()
            user_id = user.id

        response = client.get(f"/admin/users/{user_id}")
        assert response.status_code == 200
        assert b"tester" in response.data

    def test_regular_user_cannot_access_admin_users(self, client, auth):
        """Regular user should not access admin user management."""
        auth.login()
        response = client.get("/admin/users", follow_redirects=False)
        assert response.status_code in (403, 302)

    def test_admin_can_create_user(self, client, admin_auth, app):
        """Admin should be able to create new users."""
        response = client.post(
            "/admin/users/create",
            data={
                "username": "admincreatednewuser",
                "email": "admincreated@example.com",
                "password": "testpass123",
                "role": "USER",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        # Verify user was created
        with app.app_context():
            user = User.query.filter_by(username="admincreatednewuser").first()
            assert user is not None
            assert user.email == "admincreated@example.com"


class TestTierManagement:
    """Test admin tier management."""

    def test_admin_can_list_tiers(self, client, admin_auth):
        """Admin should see tier list."""
        response = client.get("/admin/tiers")
        assert response.status_code == 200
        assert b"Tier" in response.data or b"Subscription" in response.data

    def test_regular_user_cannot_access_tiers(self, client, auth):
        """Regular user should not access tier management."""
        auth.login()
        response = client.get("/admin/tiers", follow_redirects=False)
        assert response.status_code in (403, 302)
