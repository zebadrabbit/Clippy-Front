"""
Version management for ClippyFront application.
"""

__version__ = "1.0.1"
__version_info__ = (1, 0, 1)

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
    "0.10.0": (
        "Worker deployment improvements: updated worker setup documentation; "
        "improved worker configuration management; "
        "enhanced worker deployment scripts and examples."
    ),
    "0.11.0": (
        "Worker API infrastructure and configuration overhaul: created worker API endpoints (/api/worker/*) for DMZ-isolated communication "
        "(clip metadata, status updates, processing jobs, media files, project data); added worker API client library with authentication; "
        "comprehensive worker setup documentation (WORKER_SETUP.md) and migration plan (WORKER_API_MIGRATION.md); .env.worker.example template; "
        "enhanced clip download API logging; improved error messages for missing DATABASE_URL. Workers currently require database access; "
        "API endpoints ready for gradual migration to eliminate DB dependency."
    ),
    "0.11.1": (
        "Extended worker API with complete endpoint coverage: added 5 new worker API endpoints "
        "(POST /worker/media for media file creation, PUT /worker/projects/{id}/status, GET /worker/users/{id}/quota, "
        "GET /worker/users/{id}/tier-limits, POST /worker/users/{id}/record-render); "
        "updated worker API client library with 11 total helper functions; "
        "documented phased migration approach in WORKER_API_MIGRATION.md (13 endpoints total, estimated 2-3 weeks for full refactoring). "
        "Workers still require DATABASE_URL; all API infrastructure complete and ready for gradual task refactoring."
    ),
    "0.12.0": (
        "Worker API migration complete - DMZ-compliant workers: completed Phases 3-5 of worker API migration, "
        "eliminating DATABASE_URL requirement for workers. Phase 3: created download_clip_v2 (303 lines) with URL-based media reuse, "
        "removed deprecated checksum deduplication. Phase 4: created compile_video_v2 (685 lines) with batch API endpoints "
        "(compilation-context, media-batch) to avoid N+1 queries; full feature parity (timeline, transitions, tier enforcement, thumbnails). "
        "Phase 5: switched all task invocations to v2, updated celery_app.py task routing, removed old imports. "
        "Workers now operate 100% via API with FLASK_APP_URL and WORKER_API_KEY. All 70 tests passing. "
        "19 total worker API endpoints, 16 client functions. Full migration documentation in WORKER_API_MIGRATION.md."
    ),
    "0.12.1": (
        "UI and configuration improvements: thumbnail generation now seeks to 3 seconds (from 1) for better frame selection; "
        "Projects page redesigned with card-based grid layout matching dashboard, compilation thumbnails, quick download buttons; "
        "delete moved to project details danger zone for safer UX. Logging clarified - all logs in instance/logs/ only. "
        "Removed orphaned supervisor configs (Docker artifacts). Updated documentation (.env.example, README, CHANGELOG, REPO-STRUCTURE)."
    ),
    "0.13.0": (
        "Error handling and observability infrastructure: created app/error_utils.py with reusable utilities (safe_log_error, handle_api_exception, "
        "safe_operation decorator, ErrorContext manager, validation helpers). Updated 13 exception handlers in auth and API routes with structured logging "
        "(exc_info=True, contextual data). Added 21 error recovery tests (100% passing) covering email failures, uploads, compilation, database errors. "
        "Comprehensive exception documentation in API docstrings (Google-style). Added deployment automation: scripts/setup_monitoring.sh (Prometheus + Grafana + Node Exporter) "
        "and scripts/setup_webserver.sh (Nginx + Gunicorn with SSL, security hardening). Error handling audit: 0 silent failures, 93% with logging. "
        "All errors now have structured context for log aggregation. Production-ready observability stack."
    ),
    "0.14.0": (
        "Avatar overlay rendering overhaul and compilation UI improvements: fixed avatar rendering in compiled videos using API-only workflow "
        "(no shared filesystem required). Avatar overlay now matches original design: proper scaling to 128x128px, positioned at x=50 y=H-223, "
        "rendered after drawbox/text overlays for correct layering. Text positioning refined: 'clip by' and author moved up 20px, game title up 10px. "
        "Compile wizard step cleaned up: removed preview area, enhanced clip list with avatar thumbnails and view counts. Added view_count column to Clip model. "
        "Fixed worker Redis broker to use WireGuard (10.8.0.1) instead of LAN IP. Resolved movie filter hang by switching to -loop input method. "
        "Workers run 100% API-based with NVENC GPU encoding enabled."
    ),
    "1.0.0": (
        "🎉 PRODUCTION READY - Major milestone release with 15 feature implementations and 75% TODO completion. "
        "Complete team collaboration system (4 permission levels, activity feeds, invitations, real-time SSE notifications). "
        "100% API-based worker architecture (DMZ-compliant, no DATABASE_URL required). "
        "Performance optimizations (Redis caching: 10-100ms savings, GPU encoding, async uploads: 30s→200ms). "
        "Social media presets (9 platforms), tag system with autocomplete, project templates. "
        "Enhanced workflows (preview-before-compile, keyboard shortcuts, undo/redo timeline editing). "
        "Self-service auth (password reset, email verification). SQLAlchemy 2.0 migration complete. "
        "Comprehensive error handling with structured logging. Production infrastructure (monitoring, deployment automation). "
        "70+ tests passing. ~7,400 lines added, ~1,771 deprecated lines removed. All critical/high/medium priority features complete."
    ),
    "1.0.1": (
        "Automation task system enhancements: fixed automation task execution with async download polling (2s intervals, 5min timeout), "
        "resolved Flask app context issue in _resolve_queue(), and added celery queue routing fix for automation tasks. "
        "Automation UI improvements: two-line task layout, activity history tracking with compilation status badges, "
        "last project links with status indicators, and real-time last_run_at updates. "
        "New API endpoint /api/automation/tasks/<id>/history for viewing past runs (50 most recent). "
        "Automation tasks now complete fully end-to-end: fetch clips → download → compile → update last_run timestamp."
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
