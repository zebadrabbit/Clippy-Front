#!/usr/bin/env python3
"""
Database initialization script for ClippyFront.

This script creates the database tables and optionally adds sample data
for development and testing purposes.
"""
from app import create_app
from app.models import Project, ProjectStatus, User, UserRole, db
from config.settings import DevelopmentConfig


def init_db(drop_existing=False):
    """
    Initialize the database with tables.

    Args:
        drop_existing: Whether to drop existing tables first
    """
    app = create_app(DevelopmentConfig)

    with app.app_context():
        if drop_existing:
            print("Dropping existing tables...")
            db.drop_all()

        print("Creating database tables...")
        db.create_all()

        print("Database initialized successfully!")


def create_admin_user(password: str = "admin123"):
    """Create an admin user for development.

    Args:
        password: Password to set for the admin user.
    """
    app = create_app(DevelopmentConfig)

    with app.app_context():
        # Check if admin already exists
        admin = User.query.filter_by(username="admin").first()
        if admin:
            print("Admin user already exists!")
            return

        # Create admin user
        admin = User(
            username="admin",
            email="admin@clippyfront.com",
            first_name="Admin",
            last_name="User",
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
        )
        admin.set_password(password)  # Change this in production!

        db.session.add(admin)
        db.session.commit()

        print("Admin user created:")
        print("  Username: admin")
        print(f"  Password: {password}")
        print("  Email: admin@clippyfront.com")


def reset_admin_password(password: str = "admin123"):
    """Reset the admin user's password.

    Args:
        password: New password to set.
    """
    app = create_app(DevelopmentConfig)

    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            print("Admin user not found. Creating a new admin user.")
            create_admin_user(password=password)
            return
        admin.set_password(password)
        db.session.commit()
        print("Admin password has been reset.")
        print("  Username: admin")
        print(f"  New Password: {password}")


def create_sample_data():
    """Create sample data for development."""
    app = create_app(DevelopmentConfig)

    with app.app_context():
        # Create a test user
        test_user = User.query.filter_by(username="testuser").first()
        if not test_user:
            test_user = User(
                username="testuser",
                email="test@clippyfront.com",
                first_name="Test",
                last_name="User",
                role=UserRole.USER,
                is_active=True,
                email_verified=True,
            )
            test_user.set_password("test123")
            db.session.add(test_user)
            db.session.commit()
            print("Test user created: testuser / test123")

        # Create a sample project
        sample_project = Project.query.filter_by(name="Sample Project").first()
        if not sample_project:
            sample_project = Project(
                name="Sample Project",
                description="A sample video compilation project for testing",
                user_id=test_user.id,
                status=ProjectStatus.DRAFT,
                max_clip_duration=30,
                output_resolution="1080p",
                output_format="mp4",
            )
            db.session.add(sample_project)
            db.session.commit()
            print("Sample project created!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Initialize ClippyFront database")
    parser.add_argument(
        "--drop", action="store_true", help="Drop existing tables first"
    )
    parser.add_argument("--admin", action="store_true", help="Create admin user")
    parser.add_argument(
        "--reset-admin",
        action="store_true",
        help="Reset password for admin user (creates if missing)",
    )
    parser.add_argument(
        "--password",
        type=str,
        help="Password to use with --admin or --reset-admin (default: admin123)",
    )
    parser.add_argument("--sample", action="store_true", help="Create sample data")
    parser.add_argument("--all", action="store_true", help="Initialize everything")

    args = parser.parse_args()

    if args.all:
        init_db(drop_existing=True)
        create_admin_user(password=args.password or "admin123")
        create_sample_data()
    else:
        if args.drop or not any(vars(args).values()):
            init_db(drop_existing=args.drop)

        if args.admin:
            create_admin_user(password=args.password or "admin123")

        if args.reset_admin:
            reset_admin_password(password=args.password or "admin123")

        if args.sample:
            create_sample_data()

    print("\nDatabase setup complete!")
    print("\nTo start the application:")
    print("  python main.py")
    print("\nTo start Celery worker:")
    print("  celery -A app.tasks.celery_app worker --loglevel=info")
