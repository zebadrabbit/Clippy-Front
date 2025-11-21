"""
Tests for password reset functionality.

This module tests the password reset flow including:
- Password reset request form and email sending
- Token generation and validation
- Password reset with valid/invalid tokens
- Token expiration handling
"""
from datetime import datetime, timedelta

from app.models import User, db


class TestPasswordResetRequest:
    """Tests for password reset request functionality."""

    def test_forgot_password_page_renders(self, client):
        """Test forgot password page loads correctly."""
        response = client.get("/auth/forgot-password")
        assert response.status_code == 200
        assert b"Reset Password" in response.data
        assert b"email" in response.data.lower()

    def test_forgot_password_sends_email_for_valid_user(self, client, test_user_obj):
        """Test password reset email is sent for valid user."""
        user = test_user_obj
        response = client.post(
            "/auth/forgot-password",
            data={"email": user.email},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"reset link has been sent" in response.data.lower()

        # Verify token was generated
        user = test_user_obj
        assert user.reset_token is not None
        assert user.reset_token_created_at is not None

    def test_forgot_password_shows_success_for_unknown_email(self, client):
        """Test forgot password doesn't reveal if email exists (security)."""
        response = client.post(
            "/auth/forgot-password",
            data={"email": "nonexistent@example.com"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        # Should show same message (don't reveal if email exists)
        assert b"reset link has been sent" in response.data.lower()

    def test_forgot_password_requires_valid_email(self, client):
        """Test forgot password validates email format."""
        response = client.post(
            "/auth/forgot-password",
            data={"email": "not-an-email"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert b"Invalid email address" in response.data


class TestPasswordReset:
    """Tests for password reset with token functionality."""

    def test_reset_password_page_renders_with_valid_token(self, client, test_user_obj):
        """Test reset password page loads with valid token."""
        # Generate token
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow()
        db.session.commit()

        response = client.get(f"/auth/reset-password/{token}")
        assert response.status_code == 200
        assert b"Create New Password" in response.data
        assert b"password" in response.data.lower()

    def test_reset_password_rejects_invalid_token(self, client):
        """Test reset password rejects invalid token."""
        response = client.get("/auth/reset-password/invalid-token-xyz")
        assert response.status_code == 302
        # Follow redirect to see error message
        response = client.get(
            "/auth/reset-password/invalid-token-xyz", follow_redirects=True
        )
        assert b"Invalid or expired" in response.data

    def test_reset_password_rejects_expired_token(self, client, test_user_obj):
        """Test reset password rejects expired token."""
        # Generate token but set creation time to 2 hours ago
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow() - timedelta(hours=2)
        db.session.commit()

        response = client.get(f"/auth/reset-password/{token}", follow_redirects=True)
        assert b"Invalid or expired" in response.data

    def test_reset_password_updates_password(self, client, test_user_obj):
        """Test password reset successfully updates password."""
        # Generate token
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow()
        db.session.commit()

        # Reset password
        new_password = "NewSecurePassword123!"
        response = client.post(
            f"/auth/reset-password/{token}",
            data={"password": new_password, "password_confirm": new_password},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"password has been reset" in response.data.lower()

        # Verify password was changed
        user = db.session.get(User, test_user_obj.id)
        assert user.check_password(new_password)
        assert not user.check_password("old_password")

        # Verify token was cleared
        assert user.reset_token is None
        assert user.reset_token_created_at is None

    def test_reset_password_requires_matching_passwords(self, client, test_user_obj):
        """Test password reset validates password confirmation."""
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow()
        db.session.commit()

        response = client.post(
            f"/auth/reset-password/{token}",
            data={
                "password": "Password123!",
                "password_confirm": "DifferentPassword123!",
            },
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert b"Passwords must match" in response.data

    def test_reset_password_requires_minimum_length(self, client, test_user_obj):
        """Test password reset enforces minimum password length."""
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow()
        db.session.commit()

        short_password = "Short1!"
        response = client.post(
            f"/auth/reset-password/{token}",
            data={"password": short_password, "password_confirm": short_password},
            follow_redirects=False,
        )
        assert response.status_code == 200
        # Check for minimum length validation
        assert b"at least 8 characters" in response.data.lower()

    def test_reset_password_updates_timestamp(self, client, test_user_obj):
        """Test password reset updates password_changed_at timestamp."""
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow()
        db.session.commit()

        new_password = "NewSecurePassword123!"
        client.post(
            f"/auth/reset-password/{token}",
            data={"password": new_password, "password_confirm": new_password},
            follow_redirects=True,
        )

        # Verify timestamp was updated
        user = db.session.get(User, test_user_obj.id)
        assert user.password_changed_at is not None
        # Should be recent (within last minute)
        assert (datetime.utcnow() - user.password_changed_at).total_seconds() < 60


class TestUserTokenMethods:
    """Tests for User model token generation/verification methods."""

    def test_generate_password_reset_token_creates_unique_token(self, test_user_obj):
        """Test token generation creates unique tokens."""
        token1 = test_user_obj.generate_password_reset_token()
        token2 = test_user_obj.generate_password_reset_token()
        assert token1 != token2
        assert len(token1) > 20  # Should be substantial length

    def test_verify_password_reset_token_finds_user(self, test_user_obj):
        """Test token verification finds correct user."""
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow()
        db.session.commit()

        verified_user = User.verify_password_reset_token(token)
        assert verified_user is not None
        assert verified_user.id == test_user_obj.id

    def test_verify_password_reset_token_returns_none_for_invalid(self):
        """Test token verification returns None for invalid token."""
        verified_user = User.verify_password_reset_token("invalid-token-xyz")
        assert verified_user is None

    def test_verify_password_reset_token_respects_max_age(self, test_user_obj):
        """Test token verification respects max_age parameter."""
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        # Set token creation to 10 seconds ago
        test_user_obj.reset_token_created_at = datetime.utcnow() - timedelta(seconds=10)
        db.session.commit()

        # Should be valid with max_age=3600 (1 hour)
        verified_user = User.verify_password_reset_token(token, max_age=3600)
        assert verified_user is not None

        # Should be invalid with max_age=5 (5 seconds)
        verified_user = User.verify_password_reset_token(token, max_age=5)
        assert verified_user is None


class TestPasswordResetSecurity:
    """Tests for password reset security considerations."""

    def test_forgot_password_redirects_authenticated_users(self, client, test_user_obj):
        """Test authenticated users are redirected from forgot password page."""
        # Log in
        client.post(
            "/login",
            data={
                "username_or_email": test_user_obj.username,
                "password": "test_password",
            },
        )

        response = client.get("/auth/forgot-password")
        assert response.status_code == 302
        assert "/dashboard" in response.location

    def test_reset_password_redirects_authenticated_users(self, client, test_user_obj):
        """Test authenticated users are redirected from reset password page."""
        # Log in
        client.post(
            "/login",
            data={
                "username_or_email": test_user_obj.username,
                "password": "test_password",
            },
        )

        token = "some-token"
        response = client.get(f"/auth/reset-password/{token}")
        assert response.status_code == 302
        assert "/dashboard" in response.location

    def test_token_can_only_be_used_once(self, client, test_user_obj):
        """Test reset token is invalidated after use."""
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow()
        db.session.commit()

        # Use token once
        new_password = "NewPassword123!"
        client.post(
            f"/auth/reset-password/{token}",
            data={"password": new_password, "password_confirm": new_password},
            follow_redirects=True,
        )

        # Try to use token again
        response = client.get(f"/auth/reset-password/{token}", follow_redirects=True)
        assert b"Invalid or expired" in response.data

    def test_old_password_invalid_after_reset(self, client, test_user_obj):
        """Test old password doesn't work after reset."""
        old_password = "test_password"
        assert test_user_obj.check_password(old_password)

        # Reset password
        token = test_user_obj.generate_password_reset_token()
        test_user_obj.reset_token = token
        test_user_obj.reset_token_created_at = datetime.utcnow()
        db.session.commit()

        new_password = "NewSecurePassword123!"
        client.post(
            f"/auth/reset-password/{token}",
            data={"password": new_password, "password_confirm": new_password},
            follow_redirects=True,
        )

        # Try to login with old password
        response = client.post(
            "/login",
            data={
                "username_or_email": test_user_obj.username,
                "password": old_password,
            },
            follow_redirects=True,
        )
        assert b"Invalid username/email or password" in response.data

        # Verify new password works
        response = client.post(
            "/login",
            data={
                "username_or_email": test_user_obj.username,
                "password": new_password,
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Welcome back" in response.data or b"Dashboard" in response.data
