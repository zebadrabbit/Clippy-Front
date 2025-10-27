from app.models import Tier, User, db
from app.tasks.video_processing import (
    _cap_resolution_label,
    _get_user_tier_limits,
    _normalize_res_label,
)


def test_normalize_and_cap_resolution_labels():
    # Normalize various inputs
    assert _normalize_res_label("1080p") == "1080p"
    assert _normalize_res_label("2k") == "1440p"
    assert _normalize_res_label("4k") == "2160p"
    assert _normalize_res_label("1920x1080") == "1080p"
    assert _normalize_res_label("1280x720") == "720p"
    assert _normalize_res_label(None) is None

    # Cap to tier max
    assert _cap_resolution_label("2160p", "1080p") == "1080p"
    assert _cap_resolution_label("720p", "1080p") == "720p"
    assert _cap_resolution_label("1920x1080", "1440p") == "1080p"
    # When project is undefined, fallback to tier
    assert _cap_resolution_label(None, "720p") == "720p"


def test_get_user_tier_limits_reads_fields(app):
    with app.app_context():
        # Create a tier with limits
        t = Tier(
            name="TestTierCaps",
            max_output_resolution="1080p",
            max_fps=30,
            max_clips_per_project=5,
            is_unlimited=False,
            apply_watermark=True,
            is_active=True,
        )
        db.session.add(t)
        u = db.session.query(User).filter_by(username="tester").first()
        u.tier_id = None
        db.session.commit()
        u.tier_id = t.id
        db.session.commit()

        limits = _get_user_tier_limits(db.session, u.id)
        assert limits["max_res_label"] == "1080p"
        assert limits["max_fps"] == 30
        assert limits["max_clips"] == 5

        # Unlimited tier yields None caps
        t2 = Tier(
            name="UnlimitedCaps",
            is_unlimited=True,
            is_active=True,
        )
        db.session.add(t2)
        db.session.commit()
        u.tier_id = t2.id
        db.session.commit()

        limits2 = _get_user_tier_limits(db.session, u.id)
        assert limits2["max_res_label"] is None
        assert limits2["max_fps"] is None
        assert limits2["max_clips"] is None
