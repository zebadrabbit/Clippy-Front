import tempfile

import pytest

from app import create_app
from app.models import User, UserRole, db


@pytest.fixture()
def app():
    # Use a temp instance folder and sqlite DB for tests
    instance_path = tempfile.mkdtemp()
    cfg = {
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "UPLOAD_FOLDER": "uploads",
        "RATELIMIT_ENABLED": False,
        "FORCE_HTTPS": False,
    }
    flask_app = create_app()
    flask_app.config.update(cfg)
    # Override instance path
    flask_app.instance_path = instance_path
    with flask_app.app_context():
        # Ensure a clean schema per test run
        db.drop_all()
        db.create_all()
        # Create a default user
        user = User(username="tester", email="t@example.com")
        user.set_password("pass1234")
        db.session.add(user)
        admin = User(username="admin", email="a@example.com", role=UserRole.ADMIN)
        admin.set_password("admin1234")
        db.session.add(admin)
        db.session.commit()
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth(client):
    class AuthActions:
        def login(self, username="tester", password="pass1234"):
            return client.post(
                "/auth/login",
                data={
                    "username_or_email": username,
                    "password": password,
                },
                follow_redirects=True,
            )

        def logout(self):
            return client.get("/auth/logout", follow_redirects=True)

    return AuthActions()
