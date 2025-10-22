import os


def test_numeric_route_redirects_to_public(client, app, auth):
    auth.login()
    # Create a project directly without public_id to exercise backfill/redirect
    from app.models import Project, User, db

    with app.app_context():
        user = db.session.query(User).filter_by(username="tester").first()
        p = Project(name="Proj A", user_id=user.id)
        db.session.add(p)
        db.session.commit()
        pid = p.id

    # Hit legacy numeric route; should 302 to /p/<public_id> and backfill id
    resp = client.get(f"/projects/{pid}", follow_redirects=False)
    assert resp.status_code in (301, 302)

    # Fetch updated public_id
    with app.app_context():
        p2 = db.session.get(Project, pid)
        assert p2.public_id
        assert f"/p/{p2.public_id}" in resp.headers.get("Location", "")


def _create_compilation_file(
    app, filename: str, content: bytes = b"hello world"
) -> str:
    out_dir = os.path.join(app.instance_path, "compilations")
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, filename)
    with open(fp, "wb") as f:
        f.write(content)
    return fp


def test_preview_and_download_by_public_owner_and_nonowner(client, app, auth):
    auth.login()
    # Create project via API to ensure it has a public_id
    r = client.post("/api/projects", json={"name": "With Output"})
    assert r.status_code == 201
    project_id = r.get_json()["project_id"]

    # Assign a fake compiled output file
    from app.models import Project, db

    with app.app_context():
        proj = db.session.get(Project, project_id)
        assert proj.public_id
        filename = "test_compiled.mp4"
        _create_compilation_file(app, filename, b"0123456789ABCDEF")
        proj.output_filename = filename
        db.session.commit()
        public_id = proj.public_id

    # Owner: preview without range
    pv = client.get(f"/p/{public_id}/preview")
    assert pv.status_code == 200
    assert pv.headers.get("Content-Type", "").startswith("video/") or pv.data

    # Owner: preview with range header
    pv2 = client.get(f"/p/{public_id}/preview", headers={"Range": "bytes=2-5"})
    assert pv2.status_code == 206
    assert pv2.headers.get("Content-Range") is not None
    assert pv2.data == b"2345"

    # Owner: download
    dl = client.get(f"/p/{public_id}/download")
    assert dl.status_code == 200
    cd = dl.headers.get("Content-Disposition", "")
    assert "attachment" in cd and "test_compiled.mp4" in cd

    # Non-owner should not be able to access
    auth.logout()
    auth.login(username="admin", password="admin1234")
    pv_other = client.get(f"/p/{public_id}/preview")
    assert pv_other.status_code == 404
    dl_other = client.get(f"/p/{public_id}/download")
    assert dl_other.status_code == 404
