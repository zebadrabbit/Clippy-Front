"""
Simple SMTP mailer utility.

Reads configuration from Flask app config (overridable via System Settings).
Password is sourced only from environment (.env) via SMTP_PASSWORD for security.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from flask import current_app


def _get(key: str, default=None):
    try:
        return current_app.config.get(key, default)
    except Exception:
        return default


def is_configured() -> bool:
    host = _get("SMTP_HOST")
    port = int(_get("SMTP_PORT", 0) or 0)
    user = _get("SMTP_USERNAME")
    pw = _get("SMTP_PASSWORD")
    return bool(host and port and user and pw)


def send_email(
    to_address: str,
    subject: str,
    html: str | None = None,
    text: str | None = None,
    from_address: str | None = None,
) -> bool:
    """Send an email using configured SMTP settings.

    Returns True on success, False on failure. Never raises in production; logs errors.
    """
    host = _get("SMTP_HOST")
    port = int(_get("SMTP_PORT", 0) or 0)
    use_tls = bool(_get("SMTP_USE_TLS", True))
    use_ssl = bool(_get("SMTP_USE_SSL", False))
    user = _get("SMTP_USERNAME")
    pw = _get("SMTP_PASSWORD")  # Only via environment/.env
    from_addr = from_address or _get("EMAIL_FROM_ADDRESS") or "no-reply@example.com"

    if not (host and port and user and pw):
        try:
            current_app.logger.warning("SMTP not fully configured; email skipped.")
        except Exception:
            pass
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    body_text = (
        text
        or (html and "This email contains HTML content; please view in an HTML client.")
        or ""
    )
    if html:
        msg.set_content(body_text)
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(body_text)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port) as smtp:
                smtp.login(user, pw)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as smtp:
                if use_tls:
                    smtp.starttls()
                smtp.login(user, pw)
                smtp.send_message(msg)
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Email send failed: {e}")
        except Exception:
            pass
        return False


def send_verification_email(to_address: str, username: str, verify_url: str) -> bool:
    subject = "Verify your email address"
    html = f"""
    <p>Hi {username},</p>
    <p>Please verify your email address by clicking the link below:</p>
    <p><a href=\"{verify_url}\">Verify Email</a></p>
    <p>If you did not sign up, you can ignore this email.</p>
    """
    text = f"Hi {username},\n\nPlease verify your email address by opening this link: {verify_url}\n\n"
    return send_email(to_address, subject, html=html, text=text)


def send_team_invitation_email(
    to_address: str,
    team_name: str,
    inviter_name: str,
    role: str,
    invitation_url: str,
    expires_at: str,
) -> bool:
    """Send a team invitation email.

    Args:
        to_address: Recipient email
        team_name: Name of the team
        inviter_name: Username of person sending invitation
        role: Role being offered (viewer, editor, admin)
        invitation_url: Full URL to accept invitation
        expires_at: Expiration date/time string

    Returns:
        True on success, False on failure
    """
    subject = f"You've been invited to join {team_name}"

    role_description = {
        "viewer": "view projects and media",
        "editor": "view and edit projects",
        "admin": "manage team members and projects",
    }.get(role.lower(), "collaborate")

    html = f"""
    <h2>Team Invitation</h2>
    <p>Hi there!</p>
    <p><strong>{inviter_name}</strong> has invited you to join the team <strong>{team_name}</strong> as a <strong>{role}</strong>.</p>
    <p>As a {role}, you'll be able to {role_description}.</p>
    <p style="margin: 20px 0;">
        <a href="{invitation_url}" style="background-color: #0d6efd; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">
            Accept Invitation
        </a>
    </p>
    <p style="color: #666; font-size: 0.9em;">
        This invitation expires on {expires_at}.<br>
        If you don't want to join this team, you can safely ignore this email.
    </p>
    <p style="color: #999; font-size: 0.8em; margin-top: 30px;">
        If the button doesn't work, copy and paste this link:<br>
        {invitation_url}
    </p>
    """

    text = f"""
You've been invited to join {team_name}

{inviter_name} has invited you to join the team "{team_name}" as a {role}.

As a {role}, you'll be able to {role_description}.

To accept this invitation, open this link:
{invitation_url}

This invitation expires on {expires_at}.

If you don't want to join this team, you can safely ignore this email.
    """

    return send_email(to_address, subject, html=html, text=text)
