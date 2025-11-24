"""
Authentication routes for user login, registration, and profile management.

This module handles all authentication-related routes including user registration,
login, logout, password reset, and profile management.
"""
import logging
from datetime import datetime
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

from app.auth.forms import (
    ChangeEmailForm,
    LoginForm,
    PasswordResetForm,
    PasswordResetRequestForm,
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
            return redirect(url_for("main.account_settings"))

        try:
            from app.mailer import send_verification_email

            old_email = current_user.email
            new_email = form.new_email.data

            # Generate verification token
            token = current_user.generate_email_verification_token()
            current_user.email_verification_token = token
            current_user.email_verification_token_created_at = datetime.utcnow()
            current_user.pending_email = new_email
            db.session.commit()

            # Send verification email to new address
            verify_url = url_for(
                "auth.verify_email_change", token=token, _external=True
            )
            send_verification_email(
                to_address=new_email,
                username=current_user.username,
                verify_url=verify_url,
            )

            current_app.logger.info(
                f"Email change requested for user {current_user.id}: {old_email} -> {new_email}"
            )
            flash(
                "A verification email has been sent to your new email address. "
                "Please check your email and click the link to complete the change.",
                "success",
            )
            return redirect(url_for("main.account_settings"))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Email change error for user {current_user.id}: {e}"
            )
            flash("An error occurred. Please try again.", "danger")
            return redirect(url_for("main.account_settings"))

    # Show form errors
    for field, errors in form.errors.items():
        for error in errors:
            flash(f"{field.replace('_', ' ').title()}: {error}", "danger")

    return redirect(url_for("main.account_settings"))


@auth_bp.route("/verify-email/<token>")
def verify_email_change(token):
    """
    Verify email change using token sent to new address.

    Args:
        token: Email verification token

    Returns:
        Response: Redirect to login or account settings with flash message
    """
    from app.models import User

    # Verify the token (valid for 24 hours)
    user = User.verify_email_verification_token(token, max_age=86400)

    if not user:
        flash("Invalid or expired verification link.", "danger")
        return redirect(url_for("auth.login"))

    if not user.pending_email:
        flash("No pending email change found.", "danger")
        return redirect(url_for("main.account_settings"))

    try:
        old_email = user.email
        new_email = user.pending_email

        # Update email and mark as verified
        user.email = new_email
        user.email_verified = True
        user.pending_email = None
        user.email_verification_token = None
        user.email_verification_token_created_at = None
        db.session.commit()

        current_app.logger.info(
            f"Email verified and changed for user {user.id}: {old_email} -> {new_email}"
        )
        flash(
            "Your email address has been successfully updated and verified!", "success"
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Email verification error for user {user.id}: {e}")
        flash("An error occurred. Please try again.", "danger")

    return redirect(url_for("main.account_settings"))
