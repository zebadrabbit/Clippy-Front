"""
Version management for ClippyFront application.
"""

__version__ = "0.9.0"
__version_info__ = (0, 9, 0)

# Version history tracking
VERSION_HISTORY = {
    "0.1.0": "Initial Flask setup with Celery and basic API",
    "0.2.0": "Added user authentication, database models, and video processing pipeline",
    "0.3.0": "Project wizard overhaul (steps 3-5 consolidated), Twitch warning, and robust download polling",
    "0.3.1": "Maintenance: Add media reindex script to backfill DB from instance/uploads and regenerate thumbnails",
    "0.4.0": (
        "Compile pipeline upgrades: transitions interleaving + static bumper insertion, "
        "NVENC detection with CPU fallback, branded overlays incl. creator/game and optional avatar, "
        "timeline cards with drag-and-drop + order persistence, compile UI cleanup, and clearer concat logging."
    ),
    "0.4.1": (
        "Wizard Step 2 chevron progress UI; Celery compile routing fix with enqueue-first status; "
        "checksum-based media dedupe and admin UI; avatar overlay time-window + position fix; "
        "project details page redesign with download; externalized inline JS/CSS to static files."
    ),
    "0.5.0": (
        "Runtime now standardizes on PostgreSQL (SQLite reserved for tests); app enforces Postgres when not testing; "
        "improved DB logging; added scripts/create_database.py to provision DB and scripts/health_check.py to verify DB/Redis connectivity; "
        "test stability fixes (Flask-Login init in TESTING, runtime schema updates disabled in tests); docs updated (README, GPU worker, WireGuard)."
    ),
    "0.5.1": (
        "Media preview/thumbnail now resolve cross-host file paths (GPU worker → web server) via instance-path remap and MEDIA_PATH_ALIAS_FROM/TO; "
        "added docs for TMPDIR=/app/instance/tmp to avoid EXDEV on network shares; clarified Celery queues (gpu,cpu,celery) and routing (gpu>cpu>celery); "
        "minor docs refresh for WireGuard and GPU worker run examples."
    ),
    "0.5.2": (
        "Infra tooling and docs: added helper scripts for WireGuard server/client and Samba share setup; "
        "bootstrap script to orchestrate WG + Samba and emit worker run examples; docker compose example for GPU worker; "
        "README cross-links and guide enhancements."
    ),
    "0.6.0": (
        "Theme system and UI polish: added Theme model and admin CRUD, dynamic /theme.css mapping Bootstrap CSS variables, "
        "and live color editing (hex input sync). Navbar alignment and stacked icon+label style, centered layout with search; "
        "Media Library upload UX redesign with large dashed Dropzone and simplified type chooser; vendor plugin removed for stability. "
        "Admin delete flow now redirects instead of showing raw JSON; documentation refreshed."
    ),
    "0.7.0": (
        "Arrange timeline UX: horizontal tiles with type-colored borders, thicker outlines, clear remove button, and dashed insert marker; "
        "Transitions info badge placement and separator tinting; Step 2 progress keeps Done active on reuse; defaults to 60fps & auto project name. "
        "Theme extensions: per-media-type colors (intro/clip/outro/transition) exposed via /theme.css and editable in Admin → Themes; "
        "Media Library cards color-coded by type; inline scripts extracted to static files; docs updated."
    ),
    "0.7.1": (
        "Docs and DX: consolidated workers guide for Linux and Windows/WSL2 (Docker and native), clarified required vs optional flags, "
        "and removed redundant USE_GPU_QUEUE from worker run examples; README and GPU worker docs aligned."
    ),
    "0.7.2": (
        "Theme/UI: added 'Compilation' media type color across theme variables and UI. "
        "Admin → Themes now includes a Compilation color; /theme.css exposes --media-color-compilation; "
        "Media Library and badges style accordingly."
    ),
    "0.8.0": (
        "Quotas & Tiers: implemented subscription tiers with storage and monthly render-time limits, "
        "tier-based watermark policy (with per-user override), and an Unlimited tier. "
        "Added admin CRUD for tiers and user tier assignment. Enforced storage quotas on uploads & downloads, "
        "pre-compile render quota estimation (403 when exceeded), and post-compile usage accounting. "
        "Seed default tiers at startup and added tests for tier seeding, render quota enforcement, and storage quota on upload."
    ),
    "0.8.1": (
        "Video pipeline & docs polish: NVENC probe now uses a valid 320x180 yuv420p test to avoid false negatives; "
        "standalone NVENC checker updated; avatar cache maintenance script added; documentation overhauled (workers, GPU, Samba mounts, README) "
        "including WSL2 CUDA library tip and option to prefer system ffmpeg. Import sorting fixed to satisfy lint."
    ),
    "0.8.2": (
        "Overlays & scheduling cleanup: fixed avatar resolution on GPU workers with AVATARS_PATH normalization (accepts assets root or avatars dir), "
        "added OVERLAY_DEBUG trace logs and a startup sanity warning when overlays enabled but no avatars found; reduced noisy startup logs (DB URI, runtime schema) to once per process; "
        "removed legacy 'once' schedules from UI and API (kept read-only backward compatibility), added monthly scheduling in UI; docs updated (README, workers, GPU)."
    ),
    "0.8.3": (
        "Operational console & logging: introduced a two-pane Blessed TUI with runtime file toggles, quick search, verbosity presets, adjustable refresh, and persisted preferences; "
        "centralized rotating logs under instance/logs (app.log, worker.log, beat.log); greatly reduced default startup noise by demoting banners to DEBUG and gating duplicate reloader logs; "
        "[media-path] traces are now DEBUG-only behind MEDIA_PATH_DEBUG. README updated with TUI usage."
    ),
    "0.8.4": (
        "Canonical storage paths & Docker alignment: media paths stored as canonical '/instance/…' across downloads and compilations; "
        "runtime transparently rebases to the active instance dir. GPU worker Compose and run script standardized on /mnt/clippyfront with HOST_INSTANCE_PATH/INSTANCE_HOST_PATH; "
        "added 'gpus: all' to Compose, fixed volumes indentation, and hardened the run script (safe defaults, no unbound vars). Docs updated (README, Samba/mounts)."
    ),
    "0.8.5": (
        "Polish after canonicalization rollout: compile task path canonicalization verified end-to-end; final docs sweep (README, Samba/mounts, workers, GPU), "
        "GPU run script defaults clarified with mount sanity warning and aliasing off by default; Compose GPU flag noted alongside reservations. Tests and lint pass."
    ),
    "0.9.0": (
        "Timeline-aware compile and worker hardening: the compile API, worker, and wizard now honor only the clips placed on the timeline (clip_ids) in the exact order; "
        "added tests to enforce empty selection rejection and subset ordering. Celery worker reuses a single Flask app instance per process to reduce DB connection churn; "
        "resolved a syntax error introduced during refactor. Docs updated: README and workers guide cover task-signature upgrades, STATIC_BUMPER_PATH override, and path-alias tips."
    ),
}


def get_version():
    """Get the current version string."""
    return __version__


def get_version_info():
    """Get the current version as a tuple."""
    return __version_info__


def get_changelog():
    """Get the version history."""
    return VERSION_HISTORY
