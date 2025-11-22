"""
Tests for platform preset functionality.

This module tests:
- Preset enumeration and settings
- Preset API endpoints
- Preset application to projects
- Validation and error handling
"""
from app.models import PlatformPreset, Project, User, db


class TestPlatformPresetModel:
    """Tests for PlatformPreset enum and settings."""

    def test_all_presets_have_settings(self):
        """Test all presets return valid settings dictionaries."""
        for preset in PlatformPreset:
            settings = preset.get_settings()
            assert isinstance(settings, dict)
            assert "resolution" in settings
            assert "format" in settings
            assert "fps" in settings
            assert "orientation" in settings

    def test_youtube_preset_settings(self):
        """Test YouTube preset has correct settings."""
        settings = PlatformPreset.YOUTUBE.get_settings()
        assert settings["resolution"] == "1080p"
        assert settings["aspect_ratio"] == "16:9"
        assert settings["fps"] == 30
        assert settings["orientation"] == "landscape"
        assert settings["format"] == "mp4"

    def test_youtube_shorts_preset_settings(self):
        """Test YouTube Shorts preset has vertical format."""
        settings = PlatformPreset.YOUTUBE_SHORTS.get_settings()
        assert settings["resolution"] == "1080p"
        assert settings["aspect_ratio"] == "9:16"
        assert settings["orientation"] == "portrait"
        assert settings["max_duration"] == 60

    def test_tiktok_preset_settings(self):
        """Test TikTok preset has vertical format."""
        settings = PlatformPreset.TIKTOK.get_settings()
        assert settings["resolution"] == "1080p"
        assert settings["aspect_ratio"] == "9:16"
        assert settings["orientation"] == "portrait"
        assert settings["max_duration"] == 600  # 10 minutes

    def test_instagram_feed_preset_settings(self):
        """Test Instagram Feed preset has square format."""
        settings = PlatformPreset.INSTAGRAM_FEED.get_settings()
        assert settings["resolution"] == "1080p"
        assert settings["aspect_ratio"] == "1:1"
        assert settings["orientation"] == "square"
        assert settings["max_duration"] == 60

    def test_instagram_reel_preset_settings(self):
        """Test Instagram Reels preset has vertical format."""
        settings = PlatformPreset.INSTAGRAM_REEL.get_settings()
        assert settings["resolution"] == "1080p"
        assert settings["aspect_ratio"] == "9:16"
        assert settings["orientation"] == "portrait"
        assert settings["max_duration"] == 90

    def test_twitter_preset_settings(self):
        """Test Twitter preset has landscape format."""
        settings = PlatformPreset.TWITTER.get_settings()
        assert settings["resolution"] == "1080p"
        assert settings["aspect_ratio"] == "16:9"
        assert settings["orientation"] == "landscape"
        assert settings["fps"] == 30

    def test_twitch_preset_settings(self):
        """Test Twitch preset has high FPS."""
        settings = PlatformPreset.TWITCH.get_settings()
        assert settings["resolution"] == "1080p"
        assert settings["fps"] == 60  # Higher FPS for gaming
        assert settings["orientation"] == "landscape"
        assert settings["max_duration"] == 60

    def test_custom_preset_settings(self):
        """Test custom preset returns default settings."""
        settings = PlatformPreset.CUSTOM.get_settings()
        assert settings["resolution"] == "1080p"
        assert settings["format"] == "mp4"
        # Custom should not enforce max_duration
        assert settings["max_duration"] is None


class TestPresetsAPI:
    """Tests for presets API endpoints."""

    def test_list_presets_requires_auth(self, client):
        """Test listing presets requires authentication."""
        response = client.get("/api/presets")
        assert response.status_code == 302
        assert "/login" in response.location

    def test_list_presets_returns_all(self, client, auth):
        """Test listing presets returns all available presets."""
        auth.login()
        response = client.get("/api/presets")
        assert response.status_code == 200

        data = response.get_json()
        assert "presets" in data
        presets = data["presets"]
        assert isinstance(presets, list)
        assert len(presets) == len(PlatformPreset)

        # Check structure
        preset_values = {p["value"] for p in presets}
        assert "youtube" in preset_values
        assert "youtube_shorts" in preset_values
        assert "tiktok" in preset_values
        assert "instagram_feed" in preset_values
        assert "custom" in preset_values

    def test_preset_response_structure(self, client, auth):
        """Test preset response has correct structure."""
        auth.login()
        response = client.get("/api/presets")
        data = response.get_json()
        presets = data["presets"]

        youtube = next((p for p in presets if p["value"] == "youtube"), None)
        assert youtube is not None
        assert "value" in youtube
        assert "name" in youtube
        assert "settings" in youtube
        assert "description" in youtube

        # Check settings structure
        settings = youtube["settings"]
        assert "resolution" in settings
        assert "format" in settings
        assert "fps" in settings
        assert "orientation" in settings


class TestApplyPreset:
    """Tests for applying presets to projects."""

    def test_apply_preset_requires_auth(self, client, test_project):
        """Test applying preset requires authentication."""
        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "youtube"}
        )
        assert response.status_code == 302

    def test_apply_preset_to_project(self, client, auth, app, test_user, test_project):
        """Test applying a preset updates project settings."""
        auth.login()

        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "youtube"}
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "message" in data
        assert "preset" in data
        assert data["preset"] == "youtube"

        # Verify project was updated
        with app.app_context():
            project = db.session.get(Project, test_project)
            assert project.platform_preset == PlatformPreset.YOUTUBE
            assert project.output_resolution == "1080p"
            assert project.output_format == "mp4"
            assert project.fps == 30

    def test_apply_youtube_shorts_preset(self, client, auth, app, test_project):
        """Test applying YouTube Shorts preset (vertical)."""
        auth.login()

        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "youtube_shorts"}
        )
        assert response.status_code == 200

        with app.app_context():
            project = db.session.get(Project, test_project)
            assert project.platform_preset == PlatformPreset.YOUTUBE_SHORTS
            assert project.output_resolution == "1080p"
            assert project.fps == 30

    def test_apply_tiktok_preset(self, client, auth, app, test_project):
        """Test applying TikTok preset (vertical)."""
        auth.login()

        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "tiktok"}
        )
        assert response.status_code == 200

        with app.app_context():
            project = db.session.get(Project, test_project)
            assert project.platform_preset == PlatformPreset.TIKTOK

    def test_apply_instagram_feed_preset(self, client, auth, app, test_project):
        """Test applying Instagram Feed preset (square)."""
        auth.login()

        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "instagram_feed"}
        )
        assert response.status_code == 200

        with app.app_context():
            project = db.session.get(Project, test_project)
            assert project.platform_preset == PlatformPreset.INSTAGRAM_FEED

    def test_apply_preset_updates_quality_based_on_bitrate(
        self, client, auth, app, test_project
    ):
        """Test preset application sets quality based on bitrate."""
        auth.login()

        # Apply high-bitrate preset (8M)
        client.post(f"/api/projects/{test_project}/preset", json={"preset": "youtube"})

        with app.app_context():
            project = db.session.get(Project, test_project)
            assert project.quality == "high"  # 8M bitrate

    def test_apply_preset_invalid_preset(self, client, auth, test_project):
        """Test applying invalid preset returns error."""
        auth.login()

        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "invalid_preset"}
        )
        assert response.status_code == 400

        data = response.get_json()
        assert "error" in data
        assert "Invalid preset" in data["error"]

    def test_apply_preset_missing_preset_field(self, client, auth, test_project):
        """Test applying preset without preset field returns error."""
        auth.login()

        response = client.post(f"/api/projects/{test_project}/preset", json={})
        assert response.status_code == 400

        data = response.get_json()
        assert "error" in data
        assert "required" in data["error"].lower()

    def test_apply_preset_nonexistent_project(self, client, auth):
        """Test applying preset to non-existent project returns 404."""
        auth.login()

        response = client.post("/api/projects/99999/preset", json={"preset": "youtube"})
        assert response.status_code == 404

        data = response.get_json()
        assert "error" in data

    def test_apply_preset_unauthorized_project(self, client, auth, app):
        """Test applying preset to another user's project fails."""
        auth.login()

        # Create project for different user
        with app.app_context():
            other_user = User(username="other", email="other@example.com")
            other_user.set_password("password123")
            db.session.add(other_user)
            db.session.commit()

            other_project = Project(
                name="Other Project",
                user_id=other_user.id,
                output_resolution="1080p",
                output_format="mp4",
            )
            db.session.add(other_project)
            db.session.commit()
            other_project_id = other_project.id

        response = client.post(
            f"/api/projects/{other_project_id}/preset", json={"preset": "youtube"}
        )
        assert response.status_code == 404

    def test_apply_preset_returns_applied_settings(self, client, auth, test_project):
        """Test preset application returns updated settings."""
        auth.login()

        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "youtube"}
        )
        data = response.get_json()

        assert "settings" in data
        settings = data["settings"]
        assert settings["resolution"] == "1080p"
        assert settings["format"] == "mp4"
        assert settings["fps"] == 30
        assert "orientation" in settings

    def test_custom_preset_can_be_applied(self, client, auth, test_project):
        """Test custom preset is valid."""
        auth.login()

        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "custom"}
        )
        # Custom is a valid preset
        assert response.status_code == 200


class TestPresetIntegration:
    """Integration tests for preset workflows."""

    def test_wizard_flow_with_preset(self, client, auth, app, test_user):
        """Test creating project with preset in wizard."""
        auth.login()

        # Create project
        response = client.post(
            "/api/projects",
            json={
                "name": "Test Preset Project",
                "description": "Testing presets",
                "output_resolution": "1080p",
                "output_format": "mp4",
            },
        )
        assert response.status_code == 201
        project_id = response.get_json()["project_id"]

        # Apply preset immediately
        response = client.post(
            f"/api/projects/{project_id}/preset", json={"preset": "youtube_shorts"}
        )
        assert response.status_code == 200

        # Verify settings were applied
        with app.app_context():
            project = db.session.get(Project, project_id)
            assert project.platform_preset == PlatformPreset.YOUTUBE_SHORTS
            assert project.output_resolution == "1080p"
            assert project.fps == 30

    def test_changing_preset_updates_settings(self, client, auth, app, test_project):
        """Test changing from one preset to another."""
        auth.login()

        # Apply YouTube preset
        client.post(f"/api/projects/{test_project}/preset", json={"preset": "youtube"})

        # Change to TikTok preset
        response = client.post(
            f"/api/projects/{test_project}/preset", json={"preset": "tiktok"}
        )
        assert response.status_code == 200

        with app.app_context():
            project = db.session.get(Project, test_project)
            assert project.platform_preset == PlatformPreset.TIKTOK
            # Settings should match TikTok
            tiktok_settings = PlatformPreset.TIKTOK.get_settings()
            assert project.output_resolution == tiktok_settings["resolution"]
