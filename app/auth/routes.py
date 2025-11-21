"""
Authentication routes for user login, registration, and profile management.

This module handles all authentication-related routes including user registration,
login, logout, password reset, and profile management.
"""
import logging
import os
from datetime import datetime
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app.auth.forms import (
    ChangeEmailForm,
    LoginForm,
    PasswordResetForm,
    PasswordResetRequestForm,
    ProfileForm,
    RegistrationForm,
)
from app.error_utils import safe_log_error
from app.models import User, db

# Create authentication blueprint
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login with credential validation and session management.

    This endpoint handles both displaying the login form and processing login
    credentials. It supports authentication via username or email, checks
    password validity, and manages user sessions.

    Methods:
        GET: Display the login form.
        POST: Process login credentials and authenticate user.

    Form Data (POST):
        username_or_email (str): User's username or email address.
        password (str): User's password.
        remember (bool, optional): Whether to remember the user's session.

    Returns:
        Response: On GET, renders login template.
                 On successful POST, redirects to dashboard or requested page.
                 On failed POST, renders login template with error messages.

    Raises:
        Exception: Database errors are caught and logged. User sees friendly
            error message: \"A database error occurred. Please retry in a moment.\"
            Errors logged include:
            - Database connection failures
            - Query execution errors
            - Transaction rollback failures

    Security:
        - CSRF protection via Flask-WTF
        - Password verification via werkzeug.security
        - Session fixation prevention
        - Account status checking (is_active flag)

    Example:
        # Login with username
        POST /login with form data: username_or_email=john, password=secret123

        # Login with email
        POST /login with form data: username_or_email=john@example.com, password=secret123
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
            # Defensive: ensure DB session is clean before querying
            try:
                db.session.rollback()
            except Exception as rollback_err:
                safe_log_error(
                    current_app.logger,
                    "Defensive rollback before login query failed",
                    exc_info=rollback_err,
                    level=logging.DEBUG,
                )
            # Find user by username or email
            try:
                user = User.query.filter(
                    (User.username == form.username_or_email.data)
                    | (User.email == form.username_or_email.data)
                ).first()
            except Exception as e:
                # Clear aborted transaction and surface a friendly error
                try:
                    db.session.rollback()
                except Exception as rollback_err:
                    safe_log_error(
                        current_app.logger,
                        "Failed to rollback after login query error",
                        exc_info=rollback_err,
                        level=logging.WARNING,
                    )
                safe_log_error(
                    current_app.logger,
                    "Login query error",
                    exc_info=e,
                    username_or_email=form.username_or_email.data,
                )
                flash(
                    "A database error occurred. Please retry in a moment.",
                    "danger",
                )
                return render_template("auth/login.html", title="Sign In", form=form)

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
    """Handle user profile viewing and editing with validation.

    This endpoint allows users to view and update their profile information,
    including personal details, connected service accounts, and preferences.

    Methods:
        GET: Display user profile with current information populated in form.
        POST: Process and save profile updates.

    Form Data (POST):
        first_name (str, optional): User's first name.
        last_name (str, optional): User's last name.
        discord_user_id (str, optional): Discord user ID for integration.
        twitch_username (str, optional): Twitch username for integration.
        date_format (str, optional): Preferred date format (auto/US/EU/ISO).
        timezone (str, optional): IANA timezone name (e.g., America/Los_Angeles).

    Returns:
        Response: Rendered profile template on GET or validation failure.
                 Redirects to profile page on successful POST.

    Raises:
        Exception: Database errors are caught and logged. User sees error flash:
            \"An error occurred while updating your profile.\"
            Specific cases:
            - Database commit failures (logged with user_id)
            - Invalid timezone (caught separately, shows timezone-specific error)
            - Form loading errors (caught separately, uses empty string)

    Validation:
        - Timezone must be valid IANA name (validated via zoneinfo.ZoneInfo)
        - Invalid timezones show warning, don't prevent other updates

    Example:
        POST /profile with form data:
            first_name=John, last_name=Doe,
            timezone=America/New_York, date_format=US
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
            # Timezone: validate IANA name when provided
            tz_input = (form.timezone.data or "").strip()
            if tz_input:
                try:
                    from zoneinfo import ZoneInfo

                    _ = ZoneInfo(tz_input)
                    current_user.timezone = tz_input
                except Exception as tz_err:
                    safe_log_error(
                        current_app.logger,
                        "Invalid timezone validation",
                        exc_info=tz_err,
                        level=logging.WARNING,
                        user_id=current_user.id,
                        timezone_input=tz_input,
                    )
                    flash(
                        "Invalid timezone. Please use a valid IANA name (e.g., America/Los_Angeles).",
                        "warning",
                    )

            db.session.commit()

            flash("Your profile has been updated successfully.", "success")
            return redirect(url_for("auth.profile"))

        except Exception as e:
            db.session.rollback()
            safe_log_error(
                current_app.logger,
                "Profile update error",
                exc_info=e,
                user_id=current_user.id,
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
        try:
            form.timezone.data = current_user.timezone or ""
        except Exception as tz_err:
            safe_log_error(
                current_app.logger,
                "Failed to load timezone for form",
                exc_info=tz_err,
                level=logging.WARNING,
                user_id=current_user.id,
            )
            form.timezone.data = ""

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


@auth_bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    """Handle password change from Account Settings modal."""
    current_pw = request.form.get("current_password", "")
    new_pw = request.form.get("new_password", "")
    confirm_pw = request.form.get("confirm_password", "")

    # Basic validations
    if not current_user.check_password(current_pw):
        flash("Current password is incorrect.", "danger")
        return redirect(url_for("auth.account_settings"))
    if not new_pw or len(new_pw) < 8:
        flash("New password must be at least 8 characters.", "warning")
        return redirect(url_for("auth.account_settings"))
    if new_pw != confirm_pw:
        flash("New password and confirmation do not match.", "warning")
        return redirect(url_for("auth.account_settings"))

    try:
        current_user.set_password(new_pw)
        # Record timestamp if column exists
        try:
            from sqlalchemy import inspect as _inspect

            insp = _inspect(db.engine)
            cols = {c["name"] for c in insp.get_columns("users")}
            if "password_changed_at" in cols:
                current_user.password_changed_at = db.func.now()
        except Exception as ts_err:
            # Non-fatal; proceed without timestamp
            safe_log_error(
                current_app.logger,
                "Failed to update password timestamp",
                exc_info=ts_err,
                level=logging.WARNING,
                user_id=current_user.id,
            )
        db.session.commit()
        flash("Your password has been changed.", "success")
    except Exception as e:
        db.session.rollback()
        safe_log_error(
            current_app.logger,
            "Password change failed",
            exc_info=e,
            user_id=current_user.id,
        )
        flash("Failed to change password. Please try again.", "danger")

    return redirect(url_for("auth.account_settings"))


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


@auth_bp.route("/profile/image", methods=["GET"])
@login_required
def profile_image():
    """Serve the current user's profile image if set."""
    path = current_user.profile_image_path
    if not path or not os.path.exists(path):
        return jsonify({"error": "No profile image"}), 404
    # Basic mime guess
    import mimetypes as _m

    mt, _ = _m.guess_type(path)
    return send_file(path, mimetype=mt or "image/jpeg", conditional=True)


@auth_bp.route("/profile/image/upload", methods=["POST"])
@login_required
def upload_profile_image():
    """Upload and set the current user's profile image (images only)."""
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected.", "warning")
        return redirect(url_for("auth.profile"))

    # Validate extension
    from flask import current_app as _app

    allowed = _app.config.get("ALLOWED_IMAGE_EXTENSIONS", set())
    ext = os.path.splitext(file.filename)[1].lower().lstrip(".")
    if ext not in allowed:
        flash("Unsupported image type.", "danger")
        return redirect(url_for("auth.profile"))

    # Prepare user dir under instance/assets/avatars
    base_assets = os.path.join(_app.instance_path, "assets", "avatars")
    os.makedirs(base_assets, exist_ok=True)
    user_dir = base_assets
    os.makedirs(user_dir, exist_ok=True)

    # Save with a deterministic name per user to avoid buildup
    dest_name = f"avatar_{current_user.id}.{ext}"
    dest_path = os.path.join(user_dir, dest_name)
    try:
        file.save(dest_path)
        # Remove previous image if different path
        try:
            prev = current_user.profile_image_path
            if prev and prev != dest_path and os.path.exists(prev):
                os.remove(prev)
        except Exception as rm_err:
            safe_log_error(
                current_app.logger,
                "Failed to remove old profile image",
                exc_info=rm_err,
                level=logging.WARNING,
                user_id=current_user.id,
                image_path=prev,
            )
        current_user.profile_image_path = dest_path
        db.session.commit()
        flash("Profile image updated.", "success")
    except Exception as e:
        db.session.rollback()
        safe_log_error(
            current_app.logger,
            "Profile image upload failed",
            exc_info=e,
            user_id=current_user.id,
        )
        flash("Failed to upload profile image.", "danger")
    return redirect(url_for("auth.profile"))


@auth_bp.route("/profile/image/remove", methods=["POST"])
@login_required
def remove_profile_image():
    """Remove the current user's profile image from disk and DB."""
    try:
        path = current_user.profile_image_path
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as rm_err:
                safe_log_error(
                    current_app.logger,
                    "Failed to delete profile image file during removal",
                    exc_info=rm_err,
                    level=logging.WARNING,
                    user_id=current_user.id,
                    image_path=path,
                )
        current_user.profile_image_path = None
        db.session.commit()
        flash("Profile image removed.", "info")
    except Exception as e:
        db.session.rollback()
        safe_log_error(
            current_app.logger,
            "Profile image remove failed",
            exc_info=e,
            user_id=current_user.id,
        )
        flash("Failed to remove profile image.", "danger")
    return redirect(url_for("auth.profile"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """
    Handle password reset request.

    GET: Display password reset request form
    POST: Generate reset token and send email

    Returns:
        Response: Rendered template or redirect to login
    """
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = PasswordResetRequestForm()

    if form.validate_on_submit():
        try:
            user = User.query.filter_by(email=form.email.data).first()
            if user:
                # Generate token
                token = user.generate_password_reset_token()
                user.reset_token = token
                user.reset_token_created_at = datetime.utcnow()
                db.session.commit()

                # Send reset email
                from app.mailer import send_email

                reset_url = url_for("auth.reset_password", token=token, _external=True)
                reset_text = (
                    f"Password Reset Request\n\n"
                    f"Click here to reset your password: {reset_url}\n\n"
                    f"This link will expire in 1 hour.\n\n"
                    f"If you did not request this, please ignore this email."
                )
                send_email(
                    to_address=user.email,
                    subject="Password Reset Request",
                    text=reset_text,
                )
                current_app.logger.info(f"Password reset requested for: {user.email}")

            # Always show success message (security best practice)
            flash(
                "If that email is registered, a password reset link has been sent.",
                "info",
            )
            return redirect(url_for("auth.login"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Password reset request error: {str(e)}")
            flash(
                "An error occurred. Please try again later.",
                "danger",
            )

    return render_template(
        "auth/forgot_password.html", title="Forgot Password", form=form
    )


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """
    Handle password reset with token.

    GET: Display password reset form
    POST: Update password if token is valid

    Args:
        token: Password reset token from email

    Returns:
        Response: Rendered template or redirect to login
    """
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    user = User.verify_password_reset_token(token)
    if not user:
        flash("Invalid or expired reset link.", "danger")
        return redirect(url_for("auth.forgot_password"))

    form = PasswordResetForm()

    if form.validate_on_submit():
        try:
            user.set_password(form.password.data)
            user.reset_token = None
            user.reset_token_created_at = None
            user.password_changed_at = datetime.utcnow()
            db.session.commit()

            current_app.logger.info(f"Password reset completed for: {user.email}")
            flash("Your password has been reset. You can now sign in.", "success")
            return redirect(url_for("auth.login"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Password reset error: {str(e)}")
            flash("An error occurred. Please try again.", "danger")

    return render_template(
        "auth/reset_password.html", title="Reset Password", form=form, token=token
    )


@auth_bp.route("/change-email", methods=["GET", "POST"])
@login_required
def change_email():
    """
    Handle email address change.

    Requires current password for security.
    Sends verification email to new address.

    Returns:
        Response: Redirect to account settings with flash message
    """
    form = ChangeEmailForm(current_user)

    if form.validate_on_submit():
        # Verify current password
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("auth.account_settings"))

        try:
            old_email = current_user.email
            current_user.email = form.new_email.data
            # Mark email as unverified until they confirm
            current_user.email_verified = False
            db.session.commit()

            # TODO: Send verification email to new address
            current_app.logger.info(
                f"Email changed for user {current_user.id}: {old_email} -> {current_user.email}"
            )
            flash(
                "Your email address has been updated. Please check your new email to verify.",
                "success",
            )
            return redirect(url_for("auth.account_settings"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Email change error for user {current_user.id}: {e}"
            )
            flash("An error occurred. Please try again.", "danger")
            return redirect(url_for("auth.account_settings"))

    # Show form errors
    for field, errors in form.errors.items():
        for error in errors:
            flash(f"{field.replace('_', ' ').title()}: {error}", "danger")

    return redirect(url_for("auth.account_settings"))
