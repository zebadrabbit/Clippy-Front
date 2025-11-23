"""
Tests for caching functionality.

Verifies that Flask-Caching is properly configured and that cache
invalidation works correctly for tags and presets.
"""

from app.models import PlatformPreset, Tag


def test_preset_settings_caching(app):
    """Test that platform preset settings are cached."""
    with app.app_context():
        # First call - should hit DB/enum
        settings1 = PlatformPreset.YOUTUBE.get_settings()

        # Second call - should hit cache
        settings2 = PlatformPreset.YOUTUBE.get_settings()

        assert settings1 == settings2
        assert settings1["width"] == 1920
        assert settings1["height"] == 1080
        assert settings1["orientation"] == "landscape"


def test_preset_settings_different_platforms(app):
    """Test that different platforms return different cached settings."""
    with app.app_context():
        youtube_settings = PlatformPreset.YOUTUBE.get_settings()
        shorts_settings = PlatformPreset.YOUTUBE_SHORTS.get_settings()

        assert youtube_settings["orientation"] == "landscape"
        assert shorts_settings["orientation"] == "portrait"
        assert youtube_settings["height"] == 1080
        assert shorts_settings["height"] == 1920


def test_tag_list_caching(client, auth, test_user_obj):
    """Test that tag listings are cached per user."""
    # Login first
    auth.login()

    # Create some tags
    from app.api.tags import slugify
    from app.models import db

    with client.application.app_context():
        tag1 = Tag(
            name="Test Tag 1",
            slug=slugify("Test Tag 1"),
            user_id=test_user_obj.id,
            color="#FF0000",
        )
        tag2 = Tag(
            name="Test Tag 2",
            slug=slugify("Test Tag 2"),
            user_id=test_user_obj.id,
            color="#00FF00",
        )
        db.session.add_all([tag1, tag2])
        db.session.commit()

    # First request - should populate cache
    response1 = client.get("/api/tags")
    assert response1.status_code == 200
    data1 = response1.get_json()

    # Second request - should hit cache
    response2 = client.get("/api/tags")
    assert response2.status_code == 200
    data2 = response2.get_json()

    assert data1 == data2
    assert len(data1["tags"]) >= 2


def test_tag_cache_invalidation_on_create(client, auth, test_user_obj):
    """Test that cache is invalidated when a new tag is created."""
    auth.login()

    # Get initial tags
    response1 = client.get("/api/tags")
    data1 = response1.get_json()
    initial_count = len(data1["tags"])

    # Create a new tag
    create_response = client.post(
        "/api/tags", json={"name": "New Cached Tag", "color": "#0000FF"}
    )
    assert create_response.status_code == 201

    # Get tags again - should reflect the new tag
    response2 = client.get("/api/tags")
    data2 = response2.get_json()

    assert len(data2["tags"]) == initial_count + 1
    tag_names = [t["name"] for t in data2["tags"]]
    assert "New Cached Tag" in tag_names


def test_tag_cache_invalidation_on_update(client, auth, test_user_obj):
    """Test that cache is invalidated when a tag is updated."""
    from app.api.tags import slugify
    from app.models import Tag, db

    auth.login()

    # Create a tag
    with client.application.app_context():
        tag = Tag(
            name="Original Name",
            slug=slugify("Original Name"),
            user_id=test_user_obj.id,
            color="#FF00FF",
        )
        db.session.add(tag)
        db.session.commit()
        tag_id = tag.id

    # Get initial tags (populate cache)
    response1 = client.get("/api/tags")
    data1 = response1.get_json()
    original_tag = next((t for t in data1["tags"] if t["id"] == tag_id), None)
    assert original_tag["name"] == "Original Name"

    # Update the tag
    update_response = client.put(f"/api/tags/{tag_id}", json={"name": "Updated Name"})
    assert update_response.status_code == 200

    # Get tags again - should reflect the update
    response2 = client.get("/api/tags")
    data2 = response2.get_json()
    updated_tag = next((t for t in data2["tags"] if t["id"] == tag_id), None)
    assert updated_tag["name"] == "Updated Name"


def test_tag_cache_invalidation_on_delete(client, auth, test_user_obj):
    """Test that cache is invalidated when a tag is deleted."""
    from app.api.tags import slugify
    from app.models import Tag, db

    auth.login()

    # Create a tag
    with client.application.app_context():
        tag = Tag(
            name="To Be Deleted",
            slug=slugify("To Be Deleted"),
            user_id=test_user_obj.id,
            color="#FFFF00",
        )
        db.session.add(tag)
        db.session.commit()
        tag_id = tag.id

    # Get initial tags (populate cache)
    response1 = client.get("/api/tags")
    data1 = response1.get_json()
    initial_count = len(data1["tags"])
    assert any(t["id"] == tag_id for t in data1["tags"])

    # Delete the tag
    delete_response = client.delete(f"/api/tags/{tag_id}")
    assert delete_response.status_code == 200

    # Get tags again - should not include deleted tag
    response2 = client.get("/api/tags")
    data2 = response2.get_json()
    assert len(data2["tags"]) == initial_count - 1
    assert not any(t["id"] == tag_id for t in data2["tags"])


def test_tag_search_caching(client, auth, test_user_obj):
    """Test that tag search results are cached separately from full list."""
    from app.api.tags import slugify
    from app.models import Tag, db

    auth.login()

    # Create tags with different names
    with client.application.app_context():
        tag1 = Tag(
            name="Python Programming",
            slug=slugify("Python Programming"),
            user_id=test_user_obj.id,
            color="#306998",
        )
        tag2 = Tag(
            name="JavaScript Coding",
            slug=slugify("JavaScript Coding"),
            user_id=test_user_obj.id,
            color="#F7DF1E",
        )
        tag3 = Tag(
            name="Rust Development",
            slug=slugify("Rust Development"),
            user_id=test_user_obj.id,
            color="#CE422B",
        )
        db.session.add_all([tag1, tag2, tag3])
        db.session.commit()

    # Search for "Python" - should cache this specific query
    response1 = client.get("/api/tags?q=Python")
    data1 = response1.get_json()
    assert len(data1["tags"]) >= 1
    assert all("python" in t["name"].lower() for t in data1["tags"])

    # Same search again - should hit cache
    response2 = client.get("/api/tags?q=Python")
    data2 = response2.get_json()
    assert data1 == data2

    # Different search - different cache key
    response3 = client.get("/api/tags?q=Rust")
    data3 = response3.get_json()
    assert len(data3["tags"]) >= 1
    assert all("rust" in t["name"].lower() for t in data3["tags"])
