"""
Tests for authentication routes and functionality.

Covers login, logout, registration, profile management, and account settings.
"""

from app.models import User, db


class TestLogin:
    """Test login functionality."""

    def test_login_page_loads(self, client):
        """GET /auth/login should load the login page."""
        response = client.get("/auth/login")
        assert response.status_code == 200
        assert b"Sign In" in response.data or b"Login" in response.data

    def test_successful_login(self, client):
        """Valid credentials should log user in and redirect to dashboard."""
        response = client.post(
            "/auth/login",
            data={"username_or_email": "tester", "password": "pass1234"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert (
            b"dashboard" in response.data.lower() or b"welcome" in response.data.lower()
        )

    def test_invalid_password(self, client):
        """Invalid password should fail with error message."""
        response = client.post(
            "/auth/login",
            data={"username_or_email": "tester", "password": "wrongpassword"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Invalid" in response.data or b"incorrect" in response.data.lower()

    def test_nonexistent_user(self, client):
        """Login with non-existent username should fail."""
        response = client.post(
            "/auth/login",
            data={"username_or_email": "nonexistent", "password": "pass1234"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Invalid" in response.data

    def test_login_with_email(self, client):
        """Should be able to login with email instead of username."""
        response = client.post(
            "/auth/login",
            data={"username_or_email": "t@example.com", "password": "pass1234"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        # Should redirect to dashboard
        assert (
            b"dashboard" in response.data.lower() or b"welcome" in response.data.lower()
        )

    def test_authenticated_user_redirected_from_login(self, client, auth):
        """Already authenticated user should be redirected from login page."""
        auth.login()
        response = client.get("/auth/login", follow_redirects=False)
        assert response.status_code in (301, 302)
        assert "/dashboard" in response.location


class TestRegistration:
    """Test user registration functionality."""

    def test_registration_page_loads(self, client):
        """GET /auth/register should load the registration page."""
        response = client.get("/auth/register")
        assert response.status_code == 200
        assert (
            b"Register" in response.data
            or b"Sign Up" in response.data
            or b"Create Account" in response.data
        )

    def test_successful_registration(self, client, app):
        """Valid registration should create user and redirect."""
        response = client.post(
            "/auth/register",
            data={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "newpass123",
                "password2": "newpass123",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        # Should show success message and redirect to login
        assert (
            b"success" in response.data.lower()
            or b"registered" in response.data.lower()
        )

        # Verify user was created
        with app.app_context():
            user = User.query.filter_by(username="newuser").first()
            assert user is not None
            assert user.email == "newuser@example.com"

    def test_duplicate_username(self, client):
        """Registration with existing username should fail."""
        response = client.post(
            "/auth/register",
            data={
                "username": "tester",  # Already exists from conftest
                "email": "different@example.com",
                "password": "newpass123",
                "password2": "newpass123",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert (
            b"username" in response.data.lower()
            or b"already exists" in response.data.lower()
        )

    def test_duplicate_email(self, client):
        """Registration with existing email should fail."""
        response = client.post(
            "/auth/register",
            data={
                "username": "differentuser",
                "email": "t@example.com",  # Already exists
                "password": "newpass123",
                "password2": "newpass123",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert (
            b"email" in response.data.lower()
            or b"already exists" in response.data.lower()
        )

    def test_password_mismatch(self, client):
        """Registration with mismatched passwords should fail."""
        response = client.post(
            "/auth/register",
            data={
                "username": "newuser2",
                "email": "newuser2@example.com",
                "password": "pass1",
                "password2": "pass2",  # Different
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"match" in response.data.lower() or b"password" in response.data.lower()

    def test_authenticated_user_redirected_from_register(self, client, auth):
        """Already authenticated user should be redirected from registration."""
        auth.login()
        response = client.get("/auth/register", follow_redirects=False)
        assert response.status_code in (301, 302)
        assert "/dashboard" in response.location


class TestLogout:
    """Test logout functionality."""

    def test_logout(self, client, auth):
        """Authenticated user should be able to logout."""
        auth.login()
        response = client.get("/auth/logout", follow_redirects=True)
        assert response.status_code == 200
        assert b"logged out" in response.data.lower()

    def test_logout_redirects_unauthenticated(self, client):
        """Unauthenticated user accessing logout should be redirected."""
        response = client.get("/auth/logout", follow_redirects=False)
        # Should redirect to login (401 handler)
        assert response.status_code in (301, 302, 401)


class TestProfile:
    """Test profile management."""

    def test_profile_page_requires_auth(self, client):
        """Profile page should require authentication."""
        response = client.get("/auth/profile", follow_redirects=False)
        assert response.status_code in (301, 302, 401)

    def test_profile_page_loads(self, client, auth):
        """Authenticated user should see profile page."""
        auth.login()
        response = client.get("/auth/profile")
        assert response.status_code == 200
        assert b"Profile" in response.data or b"tester" in response.data

    def test_update_profile(self, client, auth, app):
        """Should be able to update profile information."""
        auth.login()
        response = client.post(
            "/auth/profile",
            data={
                "first_name": "Test",
                "last_name": "User",
                "timezone": "America/New_York",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        # Verify update
        with app.app_context():
            user = User.query.filter_by(username="tester").first()
            assert user.first_name == "Test"
            assert user.last_name == "User"


class TestAccountSettings:
    """Test account settings functionality."""

    def test_account_settings_requires_auth(self, client):
        """Account settings should require authentication."""
        response = client.get("/auth/account-settings", follow_redirects=False)
        assert response.status_code in (301, 302, 401)

    def test_account_settings_page_loads(self, client, auth):
        """Authenticated user should see account settings."""
        auth.login()
        response = client.get("/auth/account-settings")
        assert response.status_code == 200
        assert b"Settings" in response.data or b"Account" in response.data

    def test_change_password(self, client, auth, app):
        """Should be able to change password."""
        auth.login()
        response = client.post(
            "/auth/change-password",
            data={
                "current_password": "pass1234",
                "new_password": "newpass456",
                "confirm_password": "newpass456",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        # Logout and try new password
        client.get("/auth/logout")
        login_response = client.post(
            "/auth/login",
            data={"username_or_email": "tester", "password": "newpass456"},
            follow_redirects=True,
        )
        assert login_response.status_code == 200
        assert (
            b"dashboard" in login_response.data.lower()
            or b"welcome" in login_response.data.lower()
        )

    def test_change_password_wrong_current(self, client, auth):
        """Should fail with wrong current password."""
        auth.login()
        response = client.post(
            "/auth/change-password",
            data={
                "current_password": "wrongpass",
                "new_password": "newpass456",
                "confirm_password": "newpass456",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert (
            b"incorrect" in response.data.lower()
            or b"current password" in response.data.lower()
        )


class TestAccountDeletion:
    """Test account deletion functionality."""

    def test_delete_account_requires_auth(self, client):
        """Account deletion should require authentication."""
        response = client.post("/auth/delete-account", follow_redirects=False)
        assert response.status_code in (301, 302, 401)

    def test_delete_account(self, client, app):
        """Should be able to delete own account."""
        # Create a temporary user
        with app.app_context():
            temp_user = User(username="tempuser", email="temp@example.com")
            temp_user.set_password("temppass123")
            db.session.add(temp_user)
            db.session.commit()

        # Login as temp user
        client.post(
            "/auth/login",
            data={"username_or_email": "tempuser", "password": "temppass123"},
            follow_redirects=True,
        )

        # Delete account
        response = client.post("/auth/delete-account", follow_redirects=True)
        assert response.status_code == 200
        assert b"deleted" in response.data.lower()

        # Verify user is gone
        with app.app_context():
            user = User.query.filter_by(username="tempuser").first()
            assert user is None
