import io
import json

from app.models import MediaType


def login(client, username="tester", password="pass1234"):
    return client.post(
        "/auth/login",
        data={
            "username_or_email": username,
            "password": password,
        },
        follow_redirects=True,
    )


def test_media_library_requires_login(client):
    resp = client.get("/media")
    # Should redirect to login
    assert resp.status_code in (301, 302)


def test_media_library_list_after_login(client, auth):
    auth.login()
    resp = client.get("/media")
    assert resp.status_code == 200
    assert b"Media Library" in resp.data


def test_media_upload_image_and_thumbnail_fallback(client, app, auth, tmp_path):
    auth.login()
    # Create a small PNG in memory
    import base64

    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAuMBgKJY8tEAAAAASUVORK5CYII="
    )
    data = {
        "media_type": MediaType.CLIP.value,
    }
    data_file = {
        "file": (io.BytesIO(png_bytes), "tiny.png"),
    }
    resp = client.post(
        "/media/upload", data={**data, **data_file}, content_type="multipart/form-data"
    )
    assert resp.status_code in (200, 201)
    payload = json.loads(resp.data)
    assert payload["success"] is True
    media_id = payload["id"]

    # Preview should work
    prev = client.get(f"/media/preview/{media_id}")
    assert prev.status_code == 200

    # Thumbnail route should fall back to image itself for images
    thumb = client.get(f"/media/thumbnail/{media_id}")
    assert thumb.status_code == 200


def test_media_update_and_delete(client, auth):
    auth.login()
    # Upload a tiny file first
    import base64

    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAuMBgKJY8tEAAAAASUVORK5CYII="
    )
    resp = client.post(
        "/media/upload",
        data={
            "media_type": MediaType.CLIP.value,
            "file": (io.BytesIO(png_bytes), "a.png"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code in (200, 201)
    media_id = json.loads(resp.data)["id"]

    # Update name and tags
    resp2 = client.post(
        f"/media/{media_id}/update",
        data={
            "original_filename": "renamed.png",
            "media_type": MediaType.INTRO.value,
            "tags": "Tag1, tag1,  Tag2 ",
        },
    )
    assert resp2.status_code == 200
    assert json.loads(resp2.data)["success"] is True

    # Delete
    resp3 = client.post(f"/media/{media_id}/delete")
    assert resp3.status_code == 200
    assert json.loads(resp3.data)["success"] is True


def test_media_bulk_actions(client, auth):
    auth.login()
    import base64

    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAuMBgKJY8tEAAAAASUVORK5CYII="
    )
    ids = []
    for name in ("b.png", "c.png"):
        r = client.post(
            "/media/upload",
            data={
                "media_type": MediaType.CLIP.value,
                "file": (io.BytesIO(png_bytes), name),
            },
            content_type="multipart/form-data",
        )
        ids.append(json.loads(r.data)["id"])

    # Change type
    r2 = client.post(
        "/media/bulk",
        data={
            "action": "change_type",
            "media_type": MediaType.TRANSITION.value,
            "ids[]": ids,
        },
    )
    assert r2.status_code == 200
    assert json.loads(r2.data)["success"] is True

    # Set tags
    r3 = client.post(
        "/media/bulk",
        data={
            "action": "set_tags",
            "tags": "x, y , x",
            "ids[]": ids,
        },
    )
    assert r3.status_code == 200
    assert json.loads(r3.data)["success"] is True

    # Delete both
    r4 = client.post(
        "/media/bulk",
        data={
            "action": "delete",
            "ids[]": ids,
        },
    )
    assert r4.status_code == 200
    assert json.loads(r4.data)["success"] is True
