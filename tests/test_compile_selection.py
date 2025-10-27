import json


def _create_project_with_clips(app, user_id: int, n: int = 5):
    from app.models import Clip, Project, db

    with app.app_context():
        p = Project(name="SelTest", user_id=user_id)
        db.session.add(p)
        db.session.flush()
        clip_ids = []
        for i in range(n):
            c = Clip(
                title=f"Clip {i+1}",
                project_id=p.id,
                order_index=i,
            )
            db.session.add(c)
            db.session.flush()
            clip_ids.append(c.id)
        db.session.commit()
        return p.id, clip_ids


def test_compile_requires_selected_or_existing_clips(client, app, auth):
    auth.login()
    # Create empty project -> compile with empty clip_ids should 400
    r = client.post("/api/projects", json={"name": "Empty"})
    assert r.status_code == 201
    project_id = r.get_json()["project_id"]
    r2 = client.post(f"/api/projects/{project_id}/compile", json={"clip_ids": []})
    assert r2.status_code == 400
    assert "no clips" in r2.get_json().get("error", "").lower()


def test_compile_uses_selected_subset_ids(client, app, auth):
    auth.login()
    # Create a project with 5 clips
    from app.models import User, db

    with app.app_context():
        user = db.session.query(User).filter_by(username="tester").first()
        pid, clip_ids = _create_project_with_clips(app, user.id, n=5)

    # Select only 3 clips in a custom order (e.g., [4, 2, 5])
    subset = [clip_ids[3], clip_ids[1], clip_ids[4]]
    payload = {"clip_ids": subset}
    resp = client.post(f"/api/projects/{pid}/compile", json=payload)
    # We can't execute Celery here, but the API should accept and enqueue with 202
    assert resp.status_code == 202
    data = json.loads(resp.data)
    assert "task_id" in data and data["status"] == "started"
