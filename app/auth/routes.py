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
    session,
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

                # Security: Restrict admin account to local network (unless DEBUG mode)
                if (
                    user.username == "admin"
                    and current_app.config.get("RESTRICT_ADMIN_TO_LOCAL")
                    and not current_app.config.get("DEBUG")
                ):
                    client_ip = request.remote_addr
                    # Allow localhost and private network ranges
                    from ipaddress import ip_address, ip_network

                    try:
                        ip = ip_address(client_ip)
                        private_networks = [
                            ip_network("127.0.0.0/8"),  # localhost
                            ip_network("10.0.0.0/8"),  # private class A
                            ip_network("172.16.0.0/12"),  # private class B
                            ip_network("192.168.0.0/16"),  # private class C
                        ]
                        is_local = any(ip in network for network in private_networks)
                        if not is_local:
                            current_app.logger.warning(
                                f"Admin login attempt from non-local IP: {client_ip}"
                            )
                            flash(
                                "Admin account access is restricted to local network only.",
                                "danger",
                            )
                            return redirect(url_for("auth.login"))
                    except ValueError:
                        # Invalid IP format, deny access
                        current_app.logger.error(
                            f"Invalid IP format for admin login: {client_ip}"
                        )
                        flash("Unable to verify network access.", "danger")
                        return redirect(url_for("auth.login"))

                # Check if 2FA is enabled
                if user.totp_enabled:
                    # Store user ID and remember_me preference in session for 2FA verification
                    session["pending_2fa_user_id"] = user.id
                    session["remember_me"] = form.remember_me.data
                    return redirect(url_for("auth.verify_2fa"))

                # Log user in (no 2FA)
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
            # Get default tier for new users
            from app.quotas import get_default_tier

            default_tier = get_default_tier()

            # Create new user
            user = User(
                username=form.username.data,
                email=form.email.data,
                first_name=form.first_name.data or None,
                last_name=form.last_name.data or None,
                discord_user_id=form.discord_user_id.data or None,
                twitch_username=form.twitch_username.data or None,
                tier=default_tier,  # Assign default tier
            )
            user.set_password(form.password.data)

            # Save to database
            db.session.add(user)
            db.session.commit()

            current_app.logger.info(
                f"New user registered: {user.username} ({user.email}) with tier: {default_tier.name if default_tier else 'None'}"
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
    Verify email using token.

    Handles two cases:
    1. Email change verification (pending_email exists)
    2. Initial email verification (pending_email is None)

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

    try:
        # Case 1: Email change verification
        if user.pending_email:
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
                "Your email address has been successfully updated and verified!",
                "success",
            )

        # Case 2: Initial email verification
        else:
            user.email_verified = True
            user.email_verification_token = None
            user.email_verification_token_created_at = None
            db.session.commit()

            current_app.logger.info(f"Email verified for user {user.id}")
            flash("Your email address has been successfully verified!", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Email verification error for user {user.id}: {e}")
        flash("An error occurred. Please try again.", "danger")

    return redirect(
        url_for("main.account_settings")
        if current_user.is_authenticated
        else url_for("auth.login")
    )


@auth_bp.route("/resend-verification", methods=["POST"])
@login_required
def resend_verification():
    """Resend email verification for the current user.

    Generates a new verification token and sends it to the user's current email.
    Only works if the email is not already verified.

    Returns:
        JSON response with success or error message
    """
    if current_user.email_verified:
        return {"error": "Email is already verified"}, 400

    try:
        from app.mailer import send_verification_email

        # Generate new verification token
        token = current_user.generate_email_verification_token()
        current_user.email_verification_token = token
        current_user.email_verification_token_created_at = datetime.utcnow()
        db.session.commit()

        # Send verification email to current email address
        verify_url = url_for("auth.verify_email_change", token=token, _external=True)
        success = send_verification_email(
            to_address=current_user.email,
            username=current_user.username,
            verify_url=verify_url,
        )

        if success:
            current_app.logger.info(
                f"Verification email resent to user {current_user.id}"
            )
            return {"success": True, "message": "Verification email sent successfully"}
        else:
            current_app.logger.warning(
                f"Failed to send verification email to user {current_user.id}"
            )
            return {"error": "Failed to send email. Please try again later."}, 500

    except Exception as e:
        db.session.rollback()
        safe_log_error(
            current_app.logger,
            f"Resend verification error for user {current_user.id}",
            e,
        )
        return {"error": "An error occurred. Please try again."}, 500


@auth_bp.route("/login/discord")
def login_discord():
    """Initiate Discord OAuth2 flow for login/signup.

    Redirects user to Discord's authorization page. After authorization,
    Discord redirects back to /discord/callback where we handle login/signup.

    Uses a state parameter to distinguish between login and account linking flows.
    """
    client_id = current_app.config.get("DISCORD_CLIENT_ID")
    redirect_uri = current_app.config.get("DISCORD_REDIRECT_URI")

    if not client_id or not redirect_uri:
        flash("Discord OAuth is not configured.", "danger")
        return redirect(url_for("auth.login"))

    # Build Discord OAuth URL with email scope for account creation
    # Add state=login to distinguish from account linking
    discord_oauth_url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=identify+email"
        f"&state=login"
    )

    return redirect(discord_oauth_url)


@auth_bp.route("/login/twitch")
def login_twitch():
    """Initiate Twitch OAuth2 flow for login/signup.

    Redirects user to Twitch's authorization page. After authorization,
    Twitch redirects back to /twitch/callback where we handle login/signup.

    Uses a state parameter to distinguish between login and account linking flows.
    """
    client_id = current_app.config.get("TWITCH_CLIENT_ID")
    redirect_uri = current_app.config.get("TWITCH_REDIRECT_URI")

    if not client_id or not redirect_uri:
        flash("Twitch OAuth is not configured.", "danger")
        return redirect(url_for("auth.login"))

    # Build Twitch OAuth URL with user:read:email scope
    # Add state=login to distinguish from account linking
    twitch_oauth_url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=user:read:email"
        f"&state=login"
    )

    return redirect(twitch_oauth_url)


@auth_bp.route("/login/youtube")
def login_youtube():
    """Initiate YouTube/Google OAuth2 flow for login/signup.

    Redirects user to Google's authorization page. After authorization,
    Google redirects back to /youtube/login-callback where we handle login/signup.
    """
    from urllib.parse import urlencode

    client_id = current_app.config.get("YOUTUBE_CLIENT_ID")

    if not client_id:
        flash("YouTube OAuth is not configured.", "danger")
        return redirect(url_for("auth.login"))

    # Google OAuth requires exact redirect_uri match
    redirect_uri = "http://localhost:5000/auth/youtube/login-callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile https://www.googleapis.com/auth/youtube.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "state": "login",
    }

    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return redirect(auth_url)


@auth_bp.route("/discord/callback")
def discord_callback():
    """Handle Discord OAuth2 callback for login/signup.

    Exchanges authorization code for access token, fetches Discord user info,
    and either logs in existing user or creates new account.
    """
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        current_app.logger.warning(f"Discord OAuth error: {error}")
        flash("Discord authorization was denied or failed.", "warning")
        return redirect(url_for("auth.login"))

    if not code:
        flash("No authorization code received from Discord.", "warning")
        return redirect(url_for("auth.login"))

    client_id = current_app.config.get("DISCORD_CLIENT_ID")
    client_secret = current_app.config.get("DISCORD_CLIENT_SECRET")
    redirect_uri = current_app.config.get("DISCORD_REDIRECT_URI", "").replace(
        "/discord/callback", "/auth/discord/callback"
    )

    if not all([client_id, client_secret, redirect_uri]):
        flash("Discord OAuth is not properly configured.", "danger")
        return redirect(url_for("auth.login"))

    try:
        import requests

        # Exchange code for access token
        token_response = requests.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            current_app.logger.error(
                f"Discord token exchange failed: {token_response.status_code} - {token_response.text}"
            )
            flash("Failed to authenticate with Discord.", "danger")
            return redirect(url_for("auth.login"))

        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            flash("No access token received from Discord.", "danger")
            return redirect(url_for("auth.login"))

        # Fetch user info from Discord
        user_response = requests.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if user_response.status_code != 200:
            current_app.logger.error(
                f"Discord user fetch failed: {user_response.status_code} - {user_response.text}"
            )
            flash("Failed to fetch Discord user information.", "danger")
            return redirect(url_for("auth.login"))

        user_data = user_response.json()
        discord_user_id = user_data.get("id")
        discord_username = user_data.get("username")
        discord_email = user_data.get("email")

        if not discord_user_id:
            flash("Failed to get Discord User ID.", "danger")
            return redirect(url_for("auth.login"))

        # Check if user exists with this Discord ID
        user = User.query.filter_by(discord_user_id=discord_user_id).first()

        if user:
            # Existing user - log them in
            login_user(user, remember=True)
            user.last_login = datetime.utcnow()
            db.session.commit()

            flash(f"Welcome back, {user.username}!", "success")
            current_app.logger.info(f"User {user.username} logged in via Discord OAuth")

            # Redirect to requested page or dashboard
            next_page = request.args.get("next")
            if next_page and urlparse(next_page).netloc == "":
                return redirect(next_page)
            return redirect(url_for("main.dashboard"))

        else:
            # New user - create account
            # Generate username from Discord username (ensure uniqueness)
            base_username = discord_username.lower().replace(" ", "_")
            username = base_username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1

            # Get default tier
            from app.models import Tier

            default_tier = Tier.query.filter_by(name="Free").first()
            if not default_tier:
                flash("System error: Default tier not found.", "danger")
                return redirect(url_for("auth.login"))

            # Create new user
            new_user = User(
                username=username,
                email=discord_email
                or f"{discord_user_id}@discord.user",  # Fallback if no email
                discord_user_id=discord_user_id,
                tier_id=default_tier.id,
                email_verified=bool(discord_email),  # Verify if Discord provided email
            )
            # No password needed for OAuth-only accounts
            new_user.password_hash = None

            db.session.add(new_user)
            db.session.commit()

            # Log them in
            login_user(new_user, remember=True)

            flash(
                f"Welcome to ClippyFront, {username}! Your account has been created.",
                "success",
            )
            current_app.logger.info(
                f"New user registered via Discord OAuth: {username} (discord_id={discord_user_id})"
            )

            return redirect(url_for("main.dashboard"))

    except Exception as e:
        db.session.rollback()
        safe_log_error(
            current_app.logger,
            "Discord OAuth login/signup error",
            exc_info=e,
        )
        flash("An error occurred during Discord login.", "danger")
        return redirect(url_for("auth.login"))


@auth_bp.route("/youtube/login-callback")
def youtube_login_callback():
    """Handle YouTube OAuth callback for login/signup."""
    from datetime import datetime, timedelta

    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        current_app.logger.warning(f"YouTube OAuth login error: {error}")
        flash("YouTube authorization was denied or failed.", "warning")
        return redirect(url_for("auth.login"))

    if not code:
        flash("No authorization code received from YouTube.", "warning")
        return redirect(url_for("auth.login"))

    client_id = current_app.config.get("YOUTUBE_CLIENT_ID")
    client_secret = current_app.config.get("YOUTUBE_CLIENT_SECRET")

    if not all([client_id, client_secret]):
        flash("YouTube OAuth is not properly configured.", "danger")
        return redirect(url_for("auth.login"))

    # Must match the redirect_uri used in login_youtube()
    redirect_uri = "http://localhost:5000/auth/youtube/login-callback"

    try:
        import requests

        # Exchange code for access token
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            current_app.logger.error(
                f"YouTube token exchange failed: {token_response.text}"
            )
            flash("Failed to authenticate with YouTube.", "danger")
            return redirect(url_for("auth.login"))

        token_data = token_response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        # Get user info from Google
        userinfo_response = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if userinfo_response.status_code != 200:
            current_app.logger.error(
                f"YouTube userinfo fetch failed: {userinfo_response.text}"
            )
            flash("Failed to fetch user information from YouTube.", "danger")
            return redirect(url_for("auth.login"))

        user_data = userinfo_response.json()
        email = user_data.get("email")
        google_id = user_data.get("id")

        if not email or not google_id:
            flash("Could not retrieve email from YouTube account.", "warning")
            return redirect(url_for("auth.login"))

        # Get YouTube channel info
        channel_response = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )

        channel_id = None
        channel_custom_url = None
        if channel_response.status_code == 200:
            channel_data = channel_response.json()
            if channel_data.get("items"):
                channel_item = channel_data["items"][0]
                channel_id = channel_item["id"]
                snippet = channel_item.get("snippet", {})
                # Try to get custom URL (e.g., @zebadrabbit)
                channel_custom_url = snippet.get("customUrl", "")
                if channel_custom_url.startswith("@"):
                    channel_custom_url = channel_custom_url[1:]  # Remove @ prefix
            else:
                current_app.logger.warning(
                    f"No YouTube channel found for user. Response: {channel_data}"
                )
        else:
            current_app.logger.error(
                f"YouTube channel fetch failed: {channel_response.status_code} - {channel_response.text}"
            )

        # Check if user exists - prioritize email match over channel ID
        # This ensures multiple YouTube channels owned by same Google account
        # all link to the same user account
        user = User.query.filter_by(email=email).first()
        if not user and channel_id:
            user = User.query.filter_by(youtube_channel_id=channel_id).first()

        if user:
            # Login existing user
            user.youtube_channel_id = channel_id
            user.youtube_access_token = access_token
            user.youtube_refresh_token = refresh_token
            user.youtube_token_expires_at = datetime.utcnow() + timedelta(
                seconds=expires_in
            )
            db.session.commit()

            login_user(user, remember=True)
            current_app.logger.info(
                f"User logged in via YouTube: {user.username}, channel_id={channel_id}"
            )
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(url_for("main.dashboard"))
        else:
            # Create new user
            from app.models import Tier

            # Generate username from YouTube channel custom URL, or fall back to email
            if channel_custom_url:
                username = channel_custom_url
            else:
                username = email.split("@")[0]

            base_username = username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1

            # Get default tier
            default_tier = Tier.query.filter_by(is_default=True).first()

            new_user = User(
                username=username,
                email=email,
                email_verified=True,  # YouTube email is verified
                youtube_channel_id=channel_id,
                youtube_access_token=access_token,
                youtube_refresh_token=refresh_token,
                youtube_token_expires_at=datetime.utcnow()
                + timedelta(seconds=expires_in),
                tier_id=default_tier.id if default_tier else None,
            )

            # Set a random password (user can reset it later)
            import secrets

            new_user.set_password(secrets.token_urlsafe(32))

            db.session.add(new_user)
            db.session.commit()

            login_user(new_user, remember=True)
            flash(
                f"Welcome to Clippy, {username}! Your account has been created.",
                "success",
            )
            current_app.logger.info(
                f"New user registered via YouTube OAuth: {username} (channel_id={channel_id})"
            )

            return redirect(url_for("main.dashboard"))

    except Exception as e:
        db.session.rollback()
        safe_log_error(
            current_app.logger,
            "YouTube OAuth login/signup error",
            exc_info=e,
        )
        flash("An error occurred during YouTube login.", "danger")
        return redirect(url_for("auth.login"))


@auth_bp.route("/youtube/connect")
@login_required
def youtube_connect():
    """Initiate YouTube OAuth flow to connect account."""
    from urllib.parse import urlencode

    client_id = current_app.config.get("YOUTUBE_CLIENT_ID")
    if not client_id:
        flash("YouTube integration is not configured.", "danger")
        return redirect(url_for("main.account_integrations"))

    # Google OAuth requires exact redirect_uri match
    redirect_uri = "http://localhost:5000/auth/youtube/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload",
        "access_type": "offline",
        "prompt": "consent",
        "state": session.get("_id", ""),  # CSRF protection
    }

    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return redirect(auth_url)


@auth_bp.route("/youtube/callback")
@login_required
def youtube_callback():
    """Handle YouTube OAuth callback."""
    from datetime import datetime, timedelta

    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        current_app.logger.warning(f"YouTube OAuth error: {error}")
        flash("YouTube authorization was denied or failed.", "warning")
        return redirect(url_for("main.account_integrations"))

    if not code:
        flash("No authorization code received from YouTube.", "warning")
        return redirect(url_for("main.account_integrations"))

    client_id = current_app.config.get("YOUTUBE_CLIENT_ID")
    client_secret = current_app.config.get("YOUTUBE_CLIENT_SECRET")

    if not all([client_id, client_secret]):
        flash("YouTube OAuth is not properly configured.", "danger")
        return redirect(url_for("main.account_integrations"))

    # Must match the redirect_uri used in youtube_connect()
    redirect_uri = "http://localhost:5000/auth/youtube/callback"

    try:
        import requests

        # Exchange code for access token
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            current_app.logger.error(
                f"YouTube token exchange failed: {token_response.text}"
            )
            flash("Failed to connect YouTube account.", "danger")
            return redirect(url_for("main.account_integrations"))

        token_data = token_response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        # Get YouTube channel info
        channel_response = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if channel_response.status_code != 200:
            current_app.logger.error(
                f"YouTube channel fetch failed: {channel_response.text}"
            )
            flash("Failed to fetch YouTube channel information.", "danger")
            return redirect(url_for("main.account_integrations"))

        channel_data = channel_response.json()
        if not channel_data.get("items"):
            flash("No YouTube channel found for this account.", "warning")
            return redirect(url_for("main.account_integrations"))

        channel_id = channel_data["items"][0]["id"]

        # Save YouTube credentials to user
        current_user.youtube_channel_id = channel_id
        current_user.youtube_access_token = access_token
        current_user.youtube_refresh_token = refresh_token
        current_user.youtube_token_expires_at = datetime.utcnow() + timedelta(
            seconds=expires_in
        )

        db.session.commit()

        current_app.logger.info(
            f"User {current_user.username} connected YouTube channel: {channel_id}"
        )
        flash("YouTube account connected successfully!", "success")
        return redirect(url_for("main.account_integrations"))

    except Exception as e:
        db.session.rollback()
        safe_log_error(
            current_app.logger,
            "YouTube OAuth connection error",
            exc_info=e,
        )
        flash("An error occurred while connecting YouTube.", "danger")
        return redirect(url_for("main.account_integrations"))


@auth_bp.route("/youtube/disconnect", methods=["POST"])
@login_required
def youtube_disconnect():
    """Disconnect YouTube account."""
    current_user.youtube_channel_id = None
    current_user.youtube_access_token = None
    current_user.youtube_refresh_token = None
    current_user.youtube_token_expires_at = None

    db.session.commit()

    current_app.logger.info(f"User {current_user.username} disconnected YouTube")
    flash("YouTube account disconnected.", "success")
    return redirect(url_for("main.account_integrations"))


# ==============================================================================
# Two-Factor Authentication (2FA) Routes
# ==============================================================================


@auth_bp.route("/2fa/setup", methods=["GET", "POST"])
@login_required
def setup_2fa():
    """Setup two-factor authentication for the current user."""
    import base64
    import json
    import secrets
    from io import BytesIO

    import pyotp
    import qrcode
    from werkzeug.security import generate_password_hash

    if current_user.totp_enabled:
        flash("Two-factor authentication is already enabled.", "info")
        return redirect(url_for("main.account_security"))

    if request.method == "GET":
        # Check if we already have a pending secret in session
        totp_secret = session.get("pending_totp_secret")

        if not totp_secret:
            # Generate new TOTP secret only if we don't have one
            totp_secret = pyotp.random_base32()
            session["pending_totp_secret"] = totp_secret
            current_app.logger.info(
                f"Generated NEW TOTP secret for {current_user.username}: {totp_secret[:8]}... (length: {len(totp_secret)})"
            )
        else:
            current_app.logger.info(
                f"Reusing existing TOTP secret for {current_user.username}: {totp_secret[:8]}..."
            )

        # Create provisioning URI for QR code
        totp = pyotp.TOTP(totp_secret)
        provisioning_uri = totp.provisioning_uri(
            name=current_user.email, issuer_name="Clippy"
        )

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64 for embedding in HTML
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()

        current_app.logger.info(
            f"Rendering setup_2fa.html with totp_secret={totp_secret} (type: {type(totp_secret).__name__})"
        )

        return render_template(
            "auth/setup_2fa.html",
            totp_secret=totp_secret,
            qr_code_base64=qr_code_base64,
        )

    # POST: Verify code and enable 2FA
    totp_secret = session.get("pending_totp_secret")
    if not totp_secret:
        flash("2FA setup session expired. Please try again.", "danger")
        return redirect(url_for("auth.setup_2fa"))

    code = request.form.get("code", "").strip()
    if not code:
        flash("Please enter the 6-digit code from your authenticator app.", "danger")
        return redirect(url_for("auth.setup_2fa"))

    # Verify the code
    totp = pyotp.TOTP(totp_secret)
    current_app.logger.info(
        f"Verifying TOTP for {current_user.username}: code={code}, secret={totp_secret[:8]}..., current_valid_code={totp.now()}"
    )

    if not totp.verify(code, valid_window=1):
        flash("Invalid code. Please try again.", "danger")
        current_app.logger.warning(
            f"TOTP verification failed for {current_user.username}: entered={code}, expected={totp.now()}"
        )
        return redirect(url_for("auth.setup_2fa"))

    # Generate backup codes
    backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
    hashed_backup_codes = [generate_password_hash(code) for code in backup_codes]

    # Enable 2FA
    current_user.totp_secret = totp_secret
    current_user.totp_enabled = True
    current_user.totp_backup_codes = json.dumps(hashed_backup_codes)

    db.session.commit()
    session.pop("pending_totp_secret", None)

    current_app.logger.info(f"User {current_user.username} enabled 2FA")

    # Show backup codes
    return render_template("auth/2fa_backup_codes.html", backup_codes=backup_codes)


@auth_bp.route("/2fa/verify", methods=["GET", "POST"])
def verify_2fa():
    """Verify TOTP code during login."""
    import json
    from datetime import datetime, timedelta

    import pyotp
    from werkzeug.security import check_password_hash

    user_id = session.get("pending_2fa_user_id")
    if not user_id:
        flash("Session expired. Please log in again.", "danger")
        return redirect(url_for("auth.login"))

    user = User.query.get(user_id)
    if not user or not user.totp_enabled:
        session.pop("pending_2fa_user_id", None)
        flash("Invalid session. Please log in again.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        # Reset attempt counter on fresh page load
        session["2fa_attempts"] = 0
        session["2fa_lockout_until"] = None
        return render_template("auth/verify_2fa.html")

    # Rate limiting: max 5 attempts per 15 minutes
    attempts = session.get("2fa_attempts", 0)
    lockout_until = session.get("2fa_lockout_until")

    if lockout_until:
        lockout_time = datetime.fromisoformat(lockout_until)
        if datetime.utcnow() < lockout_time:
            remaining = (lockout_time - datetime.utcnow()).seconds // 60
            flash(
                f"Too many failed attempts. Please try again in {remaining} minutes.",
                "danger",
            )
            return redirect(url_for("auth.verify_2fa"))
        else:
            # Lockout expired, reset
            session["2fa_attempts"] = 0
            session["2fa_lockout_until"] = None
            attempts = 0

    if attempts >= 5:
        # Lock out for 15 minutes
        lockout_until = datetime.utcnow() + timedelta(minutes=15)
        session["2fa_lockout_until"] = lockout_until.isoformat()
        current_app.logger.warning(
            f"User {user.username} locked out from 2FA after 5 failed attempts"
        )
        flash("Too many failed attempts. Please try again in 15 minutes.", "danger")
        return redirect(url_for("auth.verify_2fa"))

    # POST: Verify code
    code = request.form.get("code", "").strip()
    use_backup = request.form.get("use_backup") == "1"

    if not code:
        flash("Please enter a code.", "danger")
        return redirect(url_for("auth.verify_2fa"))

    if use_backup:
        # Verify backup code
        backup_codes = json.loads(user.totp_backup_codes or "[]")
        code_valid = False

        for i, hashed_code in enumerate(backup_codes):
            if check_password_hash(hashed_code, code):
                # Remove used backup code
                backup_codes.pop(i)
                user.totp_backup_codes = json.dumps(backup_codes)
                db.session.commit()
                code_valid = True
                current_app.logger.info(
                    f"User {user.username} used backup code for 2FA"
                )

                # Warn if low on backup codes
                if len(backup_codes) <= 3:
                    flash(
                        f"Warning: You have {len(backup_codes)} backup codes remaining.",
                        "warning",
                    )
                break

        if not code_valid:
            session["2fa_attempts"] = attempts + 1
            flash("Invalid backup code.", "danger")
            return redirect(url_for("auth.verify_2fa"))
    else:
        # Verify TOTP code
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            session["2fa_attempts"] = attempts + 1
            flash("Invalid code. Please try again.", "danger")
            return redirect(url_for("auth.verify_2fa"))

    # Login successful - clear rate limiting
    session.pop("2fa_attempts", None)
    session.pop("2fa_lockout_until", None)
    session.pop("pending_2fa_user_id", None)
    login_user(user, remember=session.get("remember_me", False))
    session.pop("remember_me", None)

    current_app.logger.info(f"User {user.username} logged in with 2FA")
    flash(f"Welcome back, {user.username}!", "success")

    next_page = request.args.get("next")
    if not next_page or not next_page.startswith("/"):
        next_page = url_for("main.dashboard")

    return redirect(next_page)


@auth_bp.route("/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    """Disable two-factor authentication (requires password confirmation)."""
    if not current_user.totp_enabled:
        flash("Two-factor authentication is not enabled.", "info")
        return redirect(url_for("main.account_security"))

    password = request.form.get("password", "")
    if not password or not current_user.check_password(password):
        flash("Invalid password. Could not disable 2FA.", "danger")
        return redirect(url_for("main.account_security"))

    # Disable 2FA
    current_user.totp_secret = None
    current_user.totp_enabled = False
    current_user.totp_backup_codes = None

    db.session.commit()

    current_app.logger.info(f"User {current_user.username} disabled 2FA")
    flash("Two-factor authentication has been disabled.", "success")
    return redirect(url_for("main.account_security"))


@auth_bp.route("/2fa/regenerate-backup-codes", methods=["POST"])
@login_required
def regenerate_backup_codes():
    """Regenerate backup codes (requires password confirmation)."""
    import json
    import secrets

    from werkzeug.security import generate_password_hash

    if not current_user.totp_enabled:
        flash("Two-factor authentication is not enabled.", "danger")
        return redirect(url_for("main.account_security"))

    password = request.form.get("password", "")
    if not password or not current_user.check_password(password):
        flash("Invalid password.", "danger")
        return redirect(url_for("main.account_security"))

    # Generate new backup codes
    backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
    hashed_backup_codes = [generate_password_hash(code) for code in backup_codes]

    current_user.totp_backup_codes = json.dumps(hashed_backup_codes)
    db.session.commit()

    current_app.logger.info(
        f"User {current_user.username} regenerated 2FA backup codes"
    )

    return render_template(
        "auth/2fa_backup_codes.html", backup_codes=backup_codes, regenerated=True
    )
