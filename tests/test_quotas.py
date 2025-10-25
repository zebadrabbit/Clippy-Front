import io

import pytest

from app.models import MediaType, Tier, User, db


def test_ensure_default_tiers_seeds(app):
    from app.quotas import ensure_default_tiers

    with app.app_context():
        db.drop_all()
        db.create_all()
        # No tiers initially
        assert db.session.query(Tier).count() == 0
        ensure_default_tiers()
        # Defaults created
        names = {t.name for t in db.session.query(Tier).all()}
        assert {"Free", "Pro", "Unlimited"}.issubset(names)


def _login(client, username="tester", password="pass1234"):
    return client.post(
        "/auth/login",
        data={"username_or_email": username, "password": password},
        follow_redirects=True,
    )


def test_compile_blocks_when_over_render_quota(client, app):
    # Create a very small render quota tier and assign to tester
    with app.app_context():
        tiny = Tier(
            name="Tiny",
            description="Tiny monthly render cap",
            render_time_limit_seconds=5,  # 5 seconds/month
            storage_limit_bytes=1024 * 1024,  # 1MB (irrelevant here)
            apply_watermark=True,
            is_unlimited=False,
            is_active=True,
        )
        db.session.add(tiny)
        user = db.session.query(User).filter_by(username="tester").first()
        user.tier_id = None  # clear first
        db.session.commit()
        user.tier_id = tiny.id
        db.session.commit()

    _login(client)
    # Create a project via API
    r = client.post("/api/projects", json={"name": "Quota Test"})
    assert r.status_code == 201
    project_id = r.get_json()["project_id"]

    # Add one clip with duration exceeding the 5s limit
    with app.app_context():
        from app.models import Clip

        c = Clip(
            title="Long",
            project_id=project_id,
            duration=10.0,
            order_index=0,
        )
        db.session.add(c)
        db.session.commit()

    # Attempt to compile should 403 with quota info
    resp = client.post(f"/api/projects/{project_id}/compile", json={})
    assert resp.status_code == 403
    payload = resp.get_json()
    assert payload["error"]
    assert "remaining_seconds" in payload
    assert "limit_seconds" in payload
    assert payload.get("estimated_seconds") >= 10


@pytest.mark.parametrize(
    "limit_bytes,expect_statuses", [(1, (403,)), (10_000_000, (200, 201))]
)
def test_storage_quota_on_upload(client, app, limit_bytes, expect_statuses):
    # Create a custom tier with given storage limit and assign to tester
    with app.app_context():
        t = Tier(
            name=f"Storage-{limit_bytes}",
            storage_limit_bytes=limit_bytes,
            render_time_limit_seconds=60,
            apply_watermark=True,
            is_unlimited=False,
            is_active=True,
        )
        db.session.add(t)
        user = db.session.query(User).filter_by(username="tester").first()
        user.tier_id = None
        db.session.commit()
        user.tier_id = t.id
        db.session.commit()

    _login(client)

    # Prepare a tiny valid PNG file
    import base64

    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAuMBgKJY8tEAAAAASUVORK5CYII="
    )
    data = {
        "media_type": MediaType.CLIP.value,
        "file": (io.BytesIO(png_bytes), "tiny.png"),
    }
    resp = client.post(
        "/media/upload",
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code in expect_statuses
    if 403 in expect_statuses:
        p = resp.get_json()
        assert p.get("error")
