"""
Tests for project and automation task creation covering all user inputs
and defaulting/validation behaviors.
"""
from datetime import date

import pytest


def _get_project(app, pid):
    from app.models import Project, db

    with app.app_context():
        return db.session.get(Project, pid)


def _list_tasks_for_user(app, username="tester"):
    from app.models import CompilationTask, User, db

    with app.app_context():
        user = db.session.query(User).filter_by(username=username).first()
        return (
            db.session.query(CompilationTask)
            .filter_by(user_id=user.id)
            .order_by(CompilationTask.id.asc())
            .all()
        )


@pytest.mark.parametrize(
    "payload, expect",
    [
        # Minimal: blank -> defaults kick in (name becomes "Compilation of <today>")
        (
            {},
            {
                "name_prefix": f"Compilation of {date.today().isoformat()}",
                "desc": None,
                "res": "1080p",
                "fmt": "mp4",
                "maxd": 30,
                "ap": None,
                "adb": None,
            },
        ),
        # Explicit name/desc and overrides for output settings
        (
            {
                "name": "  My Project  ",
                "description": "  Cool clips ",
                "output_resolution": "720p",
                "output_format": "webm",
                "max_clip_duration": 15,
                "audio_norm_profile": "ebu_r128",
                "audio_norm_db": "-1.5",
            },
            {
                "name_exact": "My Project",
                "desc": "Cool clips",
                "res": "720p",
                "fmt": "webm",
                "maxd": 15,
                "ap": "ebu_r128",
                "adb": -1.5,
            },
        ),
        # Name whitespace-only -> default name; description whitespace -> None; string int for max; invalid audio db -> None
        (
            {
                "name": "   \t  ",
                "description": "   ",
                "max_clip_duration": "42",
                "audio_norm_profile": "",
                "audio_norm_db": "abc",
            },
            {
                "name_prefix": f"Compilation of {date.today().isoformat()}",
                "desc": None,
                "res": "1080p",
                "fmt": "mp4",
                "maxd": 42,
                "ap": None,
                "adb": None,
            },
        ),
        # Empty string for audio_norm_db should be treated as None
        (
            {
                "name": "Named",
                "audio_norm_db": "",
            },
            {
                "name_exact": "Named",
                "desc": None,
                "res": "1080p",
                "fmt": "mp4",
                "maxd": 30,
                "ap": None,
                "adb": None,
            },
        ),
    ],
)
def test_create_project_variations(client, app, auth, payload, expect):
    auth.login()
    r = client.post("/api/projects", json=payload)
    assert r.status_code == 201
    data = r.get_json()
    assert data and data.get("project_id")
    proj = _get_project(app, data["project_id"])
    assert proj is not None

    # Name expectations
    if "name_exact" in expect:
        assert proj.name == expect["name_exact"]
    else:
        # name_prefix
        assert proj.name.startswith(expect["name_prefix"])  # default name prefix

    # Description
    assert proj.description == expect["desc"]
    # Output settings and limits
    assert proj.output_resolution == expect["res"]
    assert proj.output_format == expect["fmt"]
    assert proj.max_clip_duration == expect["maxd"]
    # Audio normalization
    assert proj.audio_norm_profile == expect["ap"]
    assert (proj.audio_norm_db == expect["adb"]) or (
        proj.audio_norm_db is None and expect["adb"] is None
    )


def test_create_project_requires_auth(client):
    # Not logged in -> login_required should redirect
    r = client.post("/api/projects", json={"name": "X"}, follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/auth/login" in (r.headers.get("Location") or "")


def test_create_task_minimal_and_validation(client, app, auth):
    auth.login()
    # Missing name -> 400
    r_bad = client.post("/api/automation/tasks", json={"name": "  "})
    assert r_bad.status_code == 400
    assert "name is required" in r_bad.get_json().get("error", "")

    # Invalid source -> 400
    r_src = client.post(
        "/api/automation/tasks",
        json={
            "name": "Task 1",
            "params": {"source": "youtube", "clip_limit": 20},
        },
    )
    assert r_src.status_code == 400
    assert "source" in r_src.get_json().get("error", "")

    # Minimal valid (defaults to twitch source)
    r_ok = client.post(
        "/api/automation/tasks",
        json={
            "name": "  My Daily Clips  ",
            "description": "  grab 10  ",
            "params": {
                # source omitted -> twitch
                "clip_limit": 10,
                "output": {"output_resolution": "720p", "output_format": "mp4"},
            },
        },
    )
    assert r_ok.status_code == 201
    t_id = r_ok.get_json().get("id")
    assert t_id

    # Verify stored fields
    tasks = _list_tasks_for_user(app)
    found = [t for t in tasks if t.id == t_id]
    assert found, "Created task not found in DB"
    t = found[0]
    assert t.name == "My Daily Clips"
    assert t.description == "grab 10"
    assert isinstance(t.params, dict)
    assert t.params.get("clip_limit") == 10
    # Default source should be twitch
    assert (t.params.get("source") or "twitch") == "twitch"


def test_create_task_requires_auth(client):
    r = client.post(
        "/api/automation/tasks",
        json={"name": "X", "params": {"source": "twitch"}},
        follow_redirects=False,
    )
    assert r.status_code in (301, 302)
    assert "/auth/login" in (r.headers.get("Location") or "")
