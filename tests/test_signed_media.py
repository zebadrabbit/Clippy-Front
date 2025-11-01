import os
import time

from app.models import MediaFile, MediaType, User, db
from app.security.signed_media import generate_signed_media_url


def _mkfile(dirpath: str, name: str, content: bytes = b"hello") -> str:
    p = os.path.join(dirpath, name)
    with open(p, "wb") as f:
        f.write(content)
    return p


def test_signed_media_happy_path(app, client):
    with app.app_context():
        # Create a media file for default user
        user: User = User.query.filter_by(username="tester").first()
        assert user is not None
        # Write a temp file under instance
        data_dir = os.path.join(app.instance_path, "data", user.username)
        os.makedirs(data_dir, exist_ok=True)
        fpath = _mkfile(data_dir, "clip1.mp4", b"data")
        mf = MediaFile(
            filename="clip1.mp4",
            original_filename="clip1.mp4",
            file_path=fpath,
            file_size=os.path.getsize(fpath),
            mime_type="video/mp4",
            media_type=MediaType.CLIP,
            user_id=user.id,
        )
        db.session.add(mf)
        db.session.commit()

        url = generate_signed_media_url(mf.id, user.id, ttl_seconds=120, external=False)
    # Fetch without auth
    rv = client.get(url)
    assert rv.status_code == 200
    assert rv.data == b"data"


def test_signed_media_expired_token(app, client):
    with app.app_context():
        user: User = User.query.filter_by(username="tester").first()
        data_dir = os.path.join(app.instance_path, "data", user.username)
        os.makedirs(data_dir, exist_ok=True)
        fpath = _mkfile(data_dir, "clip2.mp4", b"zzz")
        mf = MediaFile(
            filename="clip2.mp4",
            original_filename="clip2.mp4",
            file_path=fpath,
            file_size=os.path.getsize(fpath),
            mime_type="video/mp4",
            media_type=MediaType.CLIP,
            user_id=user.id,
        )
        db.session.add(mf)
        db.session.commit()

        # TTL 1 sec then sleep to expire
        url = generate_signed_media_url(mf.id, user.id, ttl_seconds=1, external=False)
        time.sleep(2)
    rv = client.get(url)
    assert rv.status_code in (400, 403)


def test_signed_media_wrong_owner_rejected(app, client):
    with app.app_context():
        user: User = User.query.filter_by(username="tester").first()
        admin: User = User.query.filter_by(username="admin").first()
        data_dir = os.path.join(app.instance_path, "data", user.username)
        os.makedirs(data_dir, exist_ok=True)
        fpath = _mkfile(data_dir, "clip3.mp4", b"abc")
        mf = MediaFile(
            filename="clip3.mp4",
            original_filename="clip3.mp4",
            file_path=fpath,
            file_size=os.path.getsize(fpath),
            mime_type="video/mp4",
            media_type=MediaType.CLIP,
            user_id=user.id,
        )
        db.session.add(mf)
        db.session.commit()

        # Generate token with wrong owner id
        url = generate_signed_media_url(mf.id, admin.id, ttl_seconds=60, external=False)
    rv = client.get(url)
    # Either signature fails or owner check fails
    assert rv.status_code in (403, 404)
