#!/usr/bin/env python3
"""
Reset admin user password from command line.

This script allows resetting the password for admin users only.
For security, admin password resets should only be done via CLI, not web UI.

Usage:
    python scripts/reset_admin_password.py <username>
    python scripts/reset_admin_password.py --email <email>

The script will prompt for the new password securely.
"""
import getpass
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app
from app.models import User, UserRole, db


def reset_admin_password(identifier: str, by_email: bool = False):
    """
    Reset password for an admin user.

    Args:
        identifier: Username or email of the admin user
        by_email: If True, treat identifier as email; otherwise as username

    Returns:
        bool: True if successful, False otherwise
    """
    app = create_app()

    with app.app_context():
        # Find user
        if by_email:
            user = User.query.filter_by(email=identifier).first()
        else:
            user = User.query.filter_by(username=identifier).first()

        if not user:
            print(f"❌ User not found: {identifier}")
            return False

        # Verify user is admin
        if user.role != UserRole.ADMIN:
            print("❌ Security: Only admin users can have passwords reset via CLI")
            print(f"   User '{user.username}' has role: {user.role.value}")
            print("   Regular users should use the web-based password reset flow.")
            return False

        # Get new password
        print(f"✓ Found admin user: {user.username} ({user.email})")
        print()
        print("Enter new password (min 8 characters):")
        password = getpass.getpass("Password: ")

        if len(password) < 8:
            print("❌ Password must be at least 8 characters")
            return False

        confirm = getpass.getpass("Confirm password: ")

        if password != confirm:
            print("❌ Passwords do not match")
            return False

        # Update password
        try:
            user.set_password(password)
            # Clear any existing reset tokens
            user.reset_token = None
            user.reset_token_created_at = None
            # Update timestamp if column exists
            try:
                user.password_changed_at = db.func.now()
            except Exception:
                pass

            db.session.commit()
            print()
            print(f"✓ Password updated successfully for admin: {user.username}")
            print(f"  Last login: {user.last_login or 'Never'}")
            return True

        except Exception as e:
            db.session.rollback()
            print(f"❌ Error updating password: {e}")
            return False


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Reset admin user password (CLI only for security)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Reset by username:
    python scripts/reset_admin_password.py admin

  Reset by email:
    python scripts/reset_admin_password.py --email admin@example.com

Security Notice:
  This tool only works for users with admin role.
  Regular users should use the web-based password reset flow.
        """,
    )

    parser.add_argument(
        "identifier",
        nargs="?",
        help="Username or email of the admin user",
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="Treat identifier as email instead of username",
    )
    parser.add_argument(
        "--list-admins",
        action="store_true",
        help="List all admin users",
    )

    args = parser.parse_args()

    # List admins mode
    if args.list_admins:
        app = create_app()
        with app.app_context():
            admins = User.query.filter_by(role=UserRole.ADMIN).all()
            if not admins:
                print("No admin users found")
                return 0

            print("Admin users:")
            for admin in admins:
                status = "✓ active" if admin.is_active else "✗ inactive"
                print(f"  • {admin.username:20} {admin.email:30} {status}")
            return 0

    # Reset password mode
    if not args.identifier:
        parser.print_help()
        return 1

    success = reset_admin_password(args.identifier, by_email=args.email)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
