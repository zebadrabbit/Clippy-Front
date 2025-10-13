"""
Authentication forms for user registration and login.

This module contains WTForms classes for handling user authentication
including registration, login, and password reset functionality.
"""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    ValidationError,
)

from app.models import User


class LoginForm(FlaskForm):
    """
    Form for user login.

    Allows users to authenticate using either username or email
    along with their password.
    """

    username_or_email = StringField(
        "Username or Email",
        validators=[DataRequired(), Length(min=3, max=120)],
        render_kw={"placeholder": "Enter your username or email"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired()],
        render_kw={"placeholder": "Enter your password"},
    )
    remember_me = BooleanField("Remember Me")
    submit = SubmitField("Sign In")


class RegistrationForm(FlaskForm):
    """
    Form for user registration.

    Collects user information for creating a new account including
    validation for unique usernames and emails.
    """

    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=3, max=80)],
        render_kw={"placeholder": "Choose a username"},
    )
    email = StringField(
        "Email",
        validators=[DataRequired(), Email()],
        render_kw={"placeholder": "Enter your email address"},
    )
    first_name = StringField(
        "First Name",
        validators=[Optional(), Length(max=100)],
        render_kw={"placeholder": "Your first name (optional)"},
    )
    last_name = StringField(
        "Last Name",
        validators=[Optional(), Length(max=100)],
        render_kw={"placeholder": "Your last name (optional)"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8)],
        render_kw={"placeholder": "Create a password (min 8 characters)"},
    )
    password_confirm = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(),
            EqualTo("password", message="Passwords must match"),
        ],
        render_kw={"placeholder": "Confirm your password"},
    )
    discord_user_id = StringField(
        "Discord User ID",
        validators=[Optional(), Length(max=100)],
        render_kw={"placeholder": "Your Discord User ID (optional)"},
    )
    twitch_username = StringField(
        "Twitch Username",
        validators=[Optional(), Length(max=100)],
        render_kw={"placeholder": "Your Twitch username (optional)"},
    )
    submit = SubmitField("Create Account")

    def validate_username(self, username):
        """
        Validate that username is unique.

        Args:
            username: Username field from form

        Raises:
            ValidationError: If username already exists
        """
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError(
                "Username already exists. Please choose a different one."
            )

    def validate_email(self, email):
        """
        Validate that email is unique.

        Args:
            email: Email field from form

        Raises:
            ValidationError: If email already exists
        """
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError(
                "Email already registered. Please use a different email."
            )

    def validate_discord_user_id(self, discord_user_id):
        """
        Validate that Discord User ID is unique if provided.

        Args:
            discord_user_id: Discord User ID field from form

        Raises:
            ValidationError: If Discord User ID already exists
        """
        if discord_user_id.data:
            user = User.query.filter_by(discord_user_id=discord_user_id.data).first()
            if user:
                raise ValidationError(
                    "Discord User ID already linked to another account."
                )


class PasswordResetRequestForm(FlaskForm):
    """
    Form for requesting password reset.

    Allows users to request a password reset by providing their email address.
    """

    email = StringField(
        "Email",
        validators=[DataRequired(), Email()],
        render_kw={"placeholder": "Enter your email address"},
    )
    submit = SubmitField("Send Reset Link")


class PasswordResetForm(FlaskForm):
    """
    Form for resetting password with token.

    Used when user clicks password reset link from email.
    """

    password = PasswordField(
        "New Password",
        validators=[DataRequired(), Length(min=8)],
        render_kw={"placeholder": "Enter new password (min 8 characters)"},
    )
    password_confirm = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired(),
            EqualTo("password", message="Passwords must match"),
        ],
        render_kw={"placeholder": "Confirm your new password"},
    )
    submit = SubmitField("Reset Password")


class ProfileForm(FlaskForm):
    """
    Form for updating user profile information.

    Allows users to update their profile details and external service connections.
    """

    first_name = StringField(
        "First Name",
        validators=[Optional(), Length(max=100)],
    )
    last_name = StringField(
        "Last Name",
        validators=[Optional(), Length(max=100)],
    )
    discord_user_id = StringField(
        "Discord User ID",
        validators=[Optional(), Length(max=100)],
    )
    twitch_username = StringField(
        "Twitch Username",
        validators=[Optional(), Length(max=100)],
    )
    submit = SubmitField("Update Profile")

    def __init__(self, current_user, *args, **kwargs):
        """
        Initialize form with current user data.

        Args:
            current_user: Current user object to exclude from validation
        """
        super().__init__(*args, **kwargs)
        self.current_user = current_user

    def validate_discord_user_id(self, discord_user_id):
        """
        Validate Discord User ID uniqueness excluding current user.

        Args:
            discord_user_id: Discord User ID field from form

        Raises:
            ValidationError: If Discord User ID already exists for another user
        """
        if (
            discord_user_id.data
            and discord_user_id.data != self.current_user.discord_user_id
        ):
            user = User.query.filter_by(discord_user_id=discord_user_id.data).first()
            if user:
                raise ValidationError(
                    "Discord User ID already linked to another account."
                )
