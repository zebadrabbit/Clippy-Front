"""
Authentication routes for user login, registration, and profile management.

This module handles all authentication-related routes including user registration,
login, logout, password reset, and profile management.
"""
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app.auth.forms import LoginForm, ProfileForm, RegistrationForm
from app.models import User, db

# Create authentication blueprint
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Handle user login.

    GET: Display login form
    POST: Process login credentials and authenticate user

    Returns:
        Response: Rendered login template or redirect to dashboard
    """
    # Redirect already authenticated users
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()

    # Single validation pass to avoid inconsistent outcomes on repeated calls
    is_post = request.method == "POST"
    is_valid = form.validate_on_submit() if is_post else False

    if is_post:
        current_app.logger.debug("POST request received for login")
        current_app.logger.debug(f"Raw form keys: {list(request.form.keys())}")
        current_app.logger.debug(f"CSRF token in form: {'csrf_token' in request.form}")
        if "csrf_token" in request.form:
            current_app.logger.debug(
                f"CSRF token value: {request.form['csrf_token'][:20]}..."
            )
        current_app.logger.debug(f"validate_on_submit (single-pass): {is_valid}")

        if is_valid:
            # Find user by username or email
            user = User.query.filter(
                (User.username == form.username_or_email.data)
                | (User.email == form.username_or_email.data)
            ).first()

            # Verify user exists and password is correct
            if user and user.check_password(form.password.data):
                if not user.is_active:
                    flash(
                        "Your account has been deactivated. Please contact support.",
                        "danger",
                    )
                    return redirect(url_for("auth.login"))

                # Log user in
                login_user(user, remember=form.remember_me.data)
                current_app.logger.info(f"User login successful: {user.username}")

                # Update last login timestamp
                user.last_login = db.func.now()
                db.session.commit()

                # Redirect to next page or dashboard
                next_page = request.args.get("next")
                if not next_page or urlparse(next_page).netloc != "":
                    next_page = url_for("main.dashboard")
                current_app.logger.debug(f"Redirecting to: {next_page}")

                flash(f"Welcome back, {user.username}!", "success")
                return redirect(next_page)
            else:
                flash("Invalid username/email or password.", "danger")
        else:
            # Surface specific CSRF or field validation issues to the user
            if "csrf_token" in form.errors:
                flash(
                    "Your session expired or the page was open too long. Please refresh and try again.",
                    "warning",
                )
            elif form.errors:
                # Generic validation error message
                flash("Please correct the highlighted errors and try again.", "warning")
            else:
                # No field errors but still invalid (edge cases)
                flash("Unable to submit the form. Please try again.", "warning")

    return render_template("auth/login.html", title="Sign In", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """
    Handle user registration.

    GET: Display registration form
    POST: Process registration data and create new user account

    Returns:
        Response: Rendered registration template or redirect to login
    """
    # Redirect already authenticated users
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegistrationForm()

    if form.validate_on_submit():
        try:
            # Create new user
            user = User(
                username=form.username.data,
                email=form.email.data,
                first_name=form.first_name.data or None,
                last_name=form.last_name.data or None,
                discord_user_id=form.discord_user_id.data or None,
                twitch_username=form.twitch_username.data or None,
            )
            user.set_password(form.password.data)

            # Save to database
            db.session.add(user)
            db.session.commit()

            current_app.logger.info(
                f"New user registered: {user.username} ({user.email})"
            )
            flash("Registration successful! You can now sign in.", "success")
            return redirect(url_for("auth.login"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Registration error: {str(e)}")
            flash("An error occurred during registration. Please try again.", "danger")

    return render_template("auth/register.html", title="Create Account", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    """
    Handle user logout.

    Logs out the current user and redirects to landing page.

    Returns:
        Response: Redirect to landing page
    """
    username = current_user.username
    logout_user()
    flash(f"You have been logged out, {username}.", "info")
    return redirect(url_for("main.index"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """
    Handle user profile viewing and editing.

    GET: Display user profile with current information
    POST: Process profile updates

    Returns:
        Response: Rendered profile template
    """
    form = ProfileForm(current_user)

    if form.validate_on_submit():
        try:
            # Update user profile
            current_user.first_name = form.first_name.data or None
            current_user.last_name = form.last_name.data or None
            current_user.discord_user_id = form.discord_user_id.data or None
            current_user.twitch_username = form.twitch_username.data or None
            if form.date_format.data:
                current_user.date_format = form.date_format.data

            db.session.commit()

            flash("Your profile has been updated successfully.", "success")
            return redirect(url_for("auth.profile"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Profile update error for user {current_user.id}: {str(e)}"
            )
            flash(
                "An error occurred while updating your profile. Please try again.",
                "danger",
            )

    # Pre-populate form with current user data
    elif request.method == "GET":
        form.first_name.data = current_user.first_name
        form.last_name.data = current_user.last_name
        form.discord_user_id.data = current_user.discord_user_id
        form.twitch_username.data = current_user.twitch_username
        form.date_format.data = current_user.date_format or "auto"

    return render_template("auth/profile.html", title="Profile", form=form)


@auth_bp.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    """
    Handle user account deletion.

    This is a destructive action that removes the user and all associated data.

    Returns:
        Response: Redirect to landing page
    """
    if not current_user.is_authenticated:
        flash("You must be logged in to delete your account.", "danger")
        return redirect(url_for("auth.login"))

    try:
        username = current_user.username
        user_id = current_user.id

        # Log the deletion
        current_app.logger.warning(
            f"User account deletion requested: {username} (ID: {user_id})"
        )

        # Delete user (cascading will handle related records)
        db.session.delete(current_user)
        db.session.commit()

        # Log out user
        logout_user()

        flash(f"Account '{username}' has been permanently deleted.", "warning")
        return redirect(url_for("main.index"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Account deletion error for user {current_user.id}: {str(e)}"
        )
        flash(
            "An error occurred while deleting your account. Please try again.", "danger"
        )
        return redirect(url_for("auth.profile"))


@auth_bp.route("/account-settings")
@login_required
def account_settings():
    """
    Display account settings page.

    Shows various account management options including password change,
    external service connections, and account deletion.

    Returns:
        Response: Rendered account settings template
    """
    return render_template("auth/account_settings.html", title="Account Settings")


@auth_bp.route("/connect/discord", methods=["POST"])
@login_required
def connect_discord():
    """Save Discord user identifier to the current user's account.

    This is a lightweight placeholder for a full OAuth flow. Accepts
    'discord_user_id' from a simple form submission and stores it.
    """
    discord_id = (request.form.get("discord_user_id") or "").strip()
    if not discord_id:
        flash("Please provide a Discord User ID.", "warning")
        return redirect(url_for("auth.account_settings"))
    try:
        current_user.discord_user_id = discord_id
        db.session.commit()
        flash("Discord connected successfully.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Discord connect failed for user {current_user.id}: {e}"
        )
        flash("Failed to connect Discord.", "danger")
    return redirect(url_for("auth.account_settings"))


@auth_bp.route("/disconnect/discord", methods=["POST"])
@login_required
def disconnect_discord():
    """Clear Discord connection from the current user's account."""
    try:
        current_user.discord_user_id = None
        db.session.commit()
        flash("Discord disconnected.", "info")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Discord disconnect failed for user {current_user.id}: {e}"
        )
        flash("Failed to disconnect Discord.", "danger")
    return redirect(url_for("auth.account_settings"))


@auth_bp.route("/connect/twitch", methods=["POST"])
@login_required
def connect_twitch():
    """Save Twitch username to the current user's account.

    Placeholder for OAuth: accepts 'twitch_username' from form.
    """
    twitch_name = (request.form.get("twitch_username") or "").strip()
    if not twitch_name:
        flash("Please provide a Twitch username.", "warning")
        return redirect(url_for("auth.account_settings"))
    try:
        current_user.twitch_username = twitch_name
        db.session.commit()
        flash("Twitch connected successfully.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Twitch connect failed for user {current_user.id}: {e}"
        )
        flash("Failed to connect Twitch.", "danger")
    return redirect(url_for("auth.account_settings"))


@auth_bp.route("/disconnect/twitch", methods=["POST"])
@login_required
def disconnect_twitch():
    """Clear Twitch connection from the current user's account."""
    try:
        current_user.twitch_username = None
        db.session.commit()
        flash("Twitch disconnected.", "info")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Twitch disconnect failed for user {current_user.id}: {e}"
        )
        flash("Failed to disconnect Twitch.", "danger")
    return redirect(url_for("auth.account_settings"))
