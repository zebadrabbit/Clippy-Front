# Changelog

All notable changes to ClippyFront will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [0.14.0] - 2025-11-22

### Added
- **Project Wizard Enhancements**
  - Platform presets dropdown with 9 popular platforms:
    - YouTube (1080p 16:9 landscape)
    - YouTube Shorts (1080p 9:16 vertical)
    - TikTok (1080p 9:16 vertical)
    - Instagram Feed (1080p 1:1 square)
    - Instagram Reels (1080p 9:16 vertical)
    - Instagram Stories (1080p 9:16 vertical)
    - Twitter/X (1080p 16:9 landscape)
    - Facebook (1080p 16:9 landscape)
    - Twitch Clips (1080p 16:9 vertical)
  - Orientation selector for manual output settings (Landscape/Portrait/Square)
  - Automatic preset application - selecting a preset auto-fills orientation, resolution, format, and FPS
- **Compile Page Improvements**
  - Removed preview area for cleaner layout
  - Enhanced clip list with avatar thumbnails displayed for each creator
  - Added view count display in clip details
  - Added `view_count` column to Clip model with auto-migration

### Changed
- **Avatar Overlay Rendering** (Complete Overhaul)
  - Fixed avatar rendering in compiled videos using API-only worker workflow
  - Avatar properly scaled to 128x128 pixels before overlay
  - Positioned at x=50, y=H-223 (bottom-left corner with proper spacing)
  - Rendered AFTER drawbox and text overlays for correct visual layering
  - Matches original ffmpegApplyOverlay template design
- **Text Overlay Positioning**
  - "clip by" label: moved up 20px (y=-210)
  - Author name: moved up 20px (y=-180)
  - Game title: moved up 10px (y=-130)
  - Improved readability and visual balance with avatar
- **Project Wizard Workflow**
  - Removed Export step (Step 5) - now redirects directly to project details page after compilation
  - Updated wizard chevron progress: Setup → Get Clips → Arrange → Compile (4 steps)
  - Changed "Next: Export" button to "View Project" with success styling
  - localStorage now only restores projects from URL parameter, preventing old projects from blocking new ones
- **Render Summary Display**
  - Added platform preset information (e.g., "Preset: YouTube Shorts")
  - Updated output line to include orientation (e.g., "Output: 1080p, Portrait, 60fps, mp4")
  - Orientation displayed with proper capitalization (Landscape/Portrait/Square)
- **API Responses**
  - Added `public_id` field to `GET /api/projects/<id>` response for direct project page navigation
- **Worker Configuration**
  - Fixed Redis broker to use WireGuard address (10.8.0.1:6379) instead of LAN IP
  - Workers configured for 100% API-based operation (no shared filesystem)
  - NVENC GPU encoding enabled for 5-10x faster compilation

### Fixed
- **Avatar Overlay Issues**
  - Fixed movie filter hang by switching from `movie=` filter to `-loop 1 -i` input method
  - Fixed audio mapping to use correct input stream (0:a when video is first input)
  - Fixed filter chain syntax (proper semicolon/comma separation)
  - Fixed input ordering (video first, avatar second)
- **localStorage Project Restoration**
  - Fixed issue where old project IDs persisted across wizard sessions
  - New projects now properly start fresh instead of loading previous project state
  - Visiting `/projects/wizard` without URL params clears localStorage automatically
  - Projects only restore when explicitly passed via `?project_id=` parameter

---

## [0.13.0] - 2025-11-20

### Added
- **Error Handling Utilities** (`app/error_utils.py`)
  - `safe_log_error()`: Structured logging with exception info and context
  - `handle_api_exception()`: Standardized API error responses with logging
  - `safe_operation()`: Decorator for automatic error handling with fallbacks
  - `ErrorContext`: Context manager for clean error handling blocks
  - `get_error_details()`: Extract detailed exception information
  - `validate_and_handle()`: Input validation with automatic error responses
  - `chain_exceptions()`: Log chained exceptions during error handling
- **Error Recovery Tests** (`tests/test_error_recovery.py`)
  - 21 comprehensive tests (100% passing)
  - Error utility validation (safe_log_error, handle_api_exception, decorators)
  - Email sending failure scenarios
  - File upload errors (disk space, invalid types)
  - Video compilation errors (missing files, ffmpeg failures)
  - Database error recovery (login, profile updates)
- **Deployment Automation Scripts**
  - `scripts/setup_monitoring.sh`: Automated Prometheus + Grafana + Node Exporter installation
    - Version management (Prometheus 2.48.0, Grafana 10.2.2, Node Exporter 1.7.0)
    - Pre-configured dashboards and alert rules
    - ClippyFront-specific scrape configs
    - Remote execution support
    - Idempotent (safe to re-run)
  - `scripts/setup_webserver.sh`: Automated Nginx + Gunicorn deployment
    - SSL/TLS support with Let's Encrypt integration
    - Rate limiting and security headers
    - WebSocket/SSE support for real-time notifications
    - Systemd service management
    - Log rotation and firewall configuration
- **Error Handling Audit** (`docs/ERROR_HANDLING_AUDIT.md`)
  - Comprehensive analysis of 150+ exception handlers
  - Zero empty `except: pass` blocks found
  - 93% of handlers include logging
  - Recommendations and priority actions documented

### Changed
- **Structured Error Logging** (13 handlers improved)
  - `app/auth/routes.py`: 11 exception handlers with contextual logging
    - Login database errors (username, user_id context)
    - Profile updates (user_id, timezone, file paths)
    - Password changes (user context)
    - Profile image operations (file paths)
    - Defensive operations now log at DEBUG/WARNING level
  - `app/api/routes.py`: 2 exception handlers
    - Twitch API errors (username, user_id)
    - Discord API errors (channel_id, limit)
  - All handlers now use `exc_info=True` for full stack traces
  - Replaced f-string logging with structured context
- **API Documentation**
  - Added comprehensive Google-style docstrings to 4 key endpoints
  - `twitch_clips_api()`: Parameters, returns, exceptions, examples
  - `discord_messages_api()`: Complete error documentation
  - `login()`: Database errors, CSRF, security considerations
  - `profile()`: Timezone validation, update errors, examples
  - All docstrings include exception types and scenarios

### Improved
- **Error Visibility**: Zero silent failures - all errors logged with context
- **Debugging**: Structured logs ready for aggregation (Sentry, ELK, etc.)
- **Code Quality**: Reusable error handling patterns across codebase
- **Production Readiness**: Graceful degradation preserves user experience
- **Developer Experience**: Clear error contracts in API documentation
- **Observability**: Complete monitoring stack with one-command deployment

### Documentation
- Added comprehensive exception documentation to API endpoints
- Created error handling audit with findings and recommendations
- Updated deployment guides for monitoring and web server setup
- All error utilities documented with examples

---

## [0.12.1] - 2025-11-19

### Changed
- **Thumbnail Generation**: Default seek time increased from 1 to 3 seconds for better frame selection across all thumbnail generation (clips, compilations, uploads)
- **Projects Page UI**: Redesigned with card-based grid layout matching dashboard style
  - Compilation thumbnails now display correctly
  - Quick download buttons for completed projects
  - Delete button moved to project details danger zone for safer UX
  - Status badges with color-coding (draft, downloading, compiling, completed, failed)
  - Duration badges on thumbnails
  - Hover video previews for compilations
- **Logging**: Clarified that logs are stored in `instance/logs/` only
  - Old `logs/` directory marked as deprecated with README
  - Documentation updated across README, REPO-STRUCTURE
- **Cleanup**: Removed 3 orphaned supervisor config files (legacy Docker artifacts)

### Added
- Worker version checking system
- Documentation reorganization
- UI improvements

### Documentation
- Added `docs/WORKER_API_MIGRATION.md` - comprehensive migration guide
- Added `docs/REMOTE_WORKER_SETUP.md` - worker deployment guide
- Added `docs/WORKER_SETUP.md` - worker configuration guide

### Fixed
- Projects page now correctly queries compilation media files for thumbnails
- Download URLs properly generated for both public and private projects

## [0.12.0] - 2025-01-14

### Added
- **Phase 3: Download Task Migration** - Created `download_clip_v2.py` (303 lines)
  - 100% API-based clip download task with URL-based media reuse
  - New endpoint: `POST /api/worker/clips/download` - Batch download validation
  - New client function: `download_clip_batch()` in worker_api.py
  - Test coverage: `test_download_clip_v2.py` with 2 tests for batch endpoint
- **Phase 4: Compilation Task Migration** - Created `compile_video_v2.py` (685 lines)
  - 100% API-based video compilation task with batch operations
  - New endpoint: `GET /api/worker/projects/<id>/compilation-context` - Batch fetch project + clips + tier limits
  - New endpoint: `POST /api/worker/media/batch` - Batch fetch multiple MediaFile records
  - New endpoint: `GET /api/worker/jobs/<id>` - Get job metadata for logging
  - New client functions: `get_compilation_context()`, `get_media_batch()`, `get_processing_job()`
  - Test coverage: `test_compile_video_v2.py` with 5 tests for batch endpoints
- **Phase 5: Production Cutover** - Migrated all task invocations to v2
  - Updated `celery_app.py` to register v2 tasks
  - Updated 4 files to use v2 task imports (projects.py, routes.py, automation.py)
  - Import aliasing preserves compatibility at call sites
  - All 70 tests passing with zero regressions

### Changed
- **Worker Architecture: DMZ-Compliant** - Workers no longer require DATABASE_URL
  - Workers now communicate 100% via REST API using FLASK_APP_URL and WORKER_API_KEY
  - Total API coverage: 19 endpoints, 16 client functions
  - download_clip_task → download_clip_task_v2 (cutover complete)
  - compile_video_task → compile_video_task_v2 (cutover complete)
- Updated WORKER_API_MIGRATION.md with complete Phases 3-5 documentation
- Updated .env.worker.example to remove DATABASE_URL requirement
- Updated README.md with v0.12.0 migration notes and API-only worker configuration

### Fixed
- Model field mismatch in compilation context endpoint (Project.title → Project.name)
- Storage path consistency for thumbnails and compilations
- Duplicate function definition in worker_api.py

### Security
- Workers can now be deployed in untrusted DMZ environments without database credentials
- API key authentication enforces all worker-to-app communication
- Media file ownership validation in batch endpoints prevents unauthorized access

### Notes
- Migration journey: Phases 1-2 (infrastructure), Phase 3 (downloads), Phase 4 (compilation), Phase 5 (cutover)
- Original tasks in video_processing.py remain for reference but are no longer invoked
- All background processing now uses API-based v2 tasks exclusively
- Test coverage: 70/70 passing (65 original + 5 Phase 4)

## [0.11.1] - 2025-11-11

### Added
- Extended worker API with 5 new endpoints:
  - `POST /api/worker/media` - Create media file records from workers
  - `PUT /api/worker/projects/<id>/status` - Update project status and output info
  - `GET /api/worker/users/<id>/quota` - Fetch storage quota information
  - `GET /api/worker/users/<id>/tier-limits` - Fetch tier-based limits
  - `POST /api/worker/users/<id>/record-render` - Record render usage
- Worker API client library updated with 11 total helper functions covering all endpoints
- Phased migration plan in WORKER_API_MIGRATION.md with estimated timeline (2-3 weeks)

### Changed
- WORKER_API_MIGRATION.md now documents complete API coverage (13 endpoints total)
- Migration plan broken down into 5 phases with specific deliverables
- Updated documentation to clarify workers still require DATABASE_URL
- Improved complexity estimates for download_clip_task (416 lines, 50+ DB ops) and compile_video_task (800+ lines, 100+ DB ops)

### Notes
- All worker API infrastructure complete and production-ready
- Actual task refactoring to use APIs remains TODO (see WORKER_API_MIGRATION.md Phase 3-4)
- Workers must continue using DATABASE_URL until refactoring is complete

## [0.11.0] - 2025-11-11

### Added
- Worker API endpoints (`/api/worker/*`) for DMZ-isolated worker communication:
  - `GET /api/worker/clips/<id>` - Fetch clip metadata for download tasks
  - `POST /api/worker/clips/<id>/status` - Update clip download status
  - `GET /api/worker/media/<id>` - Fetch media file metadata (intro/outro/transitions)
  - `POST /api/worker/jobs` - Create processing job records
  - `PUT /api/worker/jobs/<id>` - Update job progress and status
  - `GET /api/worker/projects/<id>` - Fetch project compilation metadata
- Worker API client library (`app/tasks/worker_api.py`) with authentication helpers
- Comprehensive worker documentation:
  - `WORKER_SETUP.md` - Complete worker configuration guide with quick start
  - `WORKER_API_MIGRATION.md` - Long-term migration plan to eliminate DB dependencies
  - `.env.worker.example` - Detailed worker environment template with all options
- Configuration: `WORKER_API_KEY` and `FLASK_APP_URL` settings for API authentication
- Enhanced error messaging: `get_db_session()` now provides clear guidance when DATABASE_URL is missing
- Improved clip download API logging with better error tracking

### Changed
- README updated with worker setup quick start and references to new documentation
- Worker compose files consolidated: removed redundant examples, kept `compose.worker.yaml` as primary
- API routes now organized into focused modules: `health.py`, `jobs.py`, `media.py`, `projects.py`, `automation.py`, `worker.py`

### Deprecated
- Direct database access from workers (still required for v0.11.0, planned for removal in future releases)

### Security
- Worker API endpoints require bearer token authentication (`WORKER_API_KEY`)
- Workers documented to use dedicated DB user with minimal privileges
- Network isolation recommendations for worker database access

### Documentation
- Added WORKER_SETUP.md with troubleshooting guide and common commands
- Added WORKER_API_MIGRATION.md explaining pragmatic short-term vs long-term approach
- Updated docs/gpu-worker.md with WSL2 NVENC troubleshooting
- Cleaned up redundant compose files from docker/ directory

### Notes
- Workers currently require `DATABASE_URL` to function (416-line download task, 800+ line compile task)
- Full API migration estimated at 3-4 weeks; API infrastructure ready for gradual refactoring
- See WORKER_API_MIGRATION.md for migration strategy and timeline



## [0.10.0] - 2025-11-01

### Added
- Worker deployment improvements and documentation updates.

### Changed
- README "Deployment → Worker Setup" simplified; removed rsync-based artifact sync documentation.

### Deprecated
- Rsync-based artifact sync system removed; workers now upload files directly via HTTP API.

## [0.9.0] - 2025-10-27

### Added
- Timeline-aware compilation: the compile endpoint, worker, and wizard now honor only the clips placed on the Arrange timeline via `clip_ids`, preserving the exact order.
- Tests to validate selection behavior: rejects empty selections and accepts subsets in order.

### Changed
- Worker optimization: Celery worker now caches a single Flask app instance per process to reduce repeated DB/app initialization and lower database connection pressure.
- Documentation: README and workers guide updated with upgrade guidance for task signature changes, `STATIC_BUMPER_PATH` override for the static inter-segment clip, and path-alias tips (`MEDIA_PATH_ALIAS_FROM/TO`).

### Fixed
- Resolved a syntax error in `app/tasks/video_processing.py` introduced during worker refactor.


## [0.8.5] - 2025-10-27

### Changed
- Final documentation sweep to reflect canonical `/instance/...` paths and standardized host mount at `/mnt/clippyfront` across README and worker guides.
- Clarified GPU worker run script defaults; aliasing disabled by default and a mount sanity warning added when the path doesn't look like an instance root.
- Compose file notes GPU passthrough via `gpus: all` alongside device reservations (kept for Swarm).

### Fixed
- Ensured compile task stores canonicalized output and thumbnail paths consistently; verified end-to-end.
- Eliminated `set -u` unbound variable errors by defaulting optional `MEDIA_PATH_ALIAS_*` vars in the run script.

## [0.8.4] - 2025-10-27

### Changed
- Canonical path storage across the pipeline: media file paths are now stored as neutral `/instance/...` in the database and task results. At runtime, the app and workers transparently rebase these to the active instance directory, avoiding host path leaks in logs/DB.
- Docker/Compose alignment: standardized instance mount to `/mnt/clippyfront` on hosts; Compose binds `${HOST_INSTANCE_PATH:-/mnt/clippyfront}:/app/instance` and sets `CLIPPY_INSTANCE_PATH=/app/instance` inside the container. Added `gpus: all` and fixed volumes indentation.
- GPU worker launch script (`scripts/run_gpu_worker.sh`): safer defaults (no hard exports), aliasing disabled by default, optional flags documented, and a sanity warning when the mount doesn't look like an instance root.
- Documentation refresh (README, Samba/mounts): updated mount paths to `/mnt/clippyfront`, described canonical `/instance/...` storage and when aliasing is still useful for legacy migrations.

### Fixed
- Prevented `set -u` from erroring on unset `MEDIA_PATH_ALIAS_*` in the GPU worker script by providing empty-string defaults.
- Compilation task now stores canonicalized output and thumbnail paths to keep records consistent with download tasks.

## [0.8.3] - 2025-10-26

### Added
- Operational console (experimental): a two-pane Blessed TUI that tails rotating logs with runtime file toggles (app.log, worker.log, beat.log), quick search/filter box, verbosity presets, adjustable refresh rate, and persisted preferences (`instance/data/console_prefs.json`).

### Changed
- Centralized rotating logging under `instance/logs/` and attached dedicated handler for Celery Beat (`beat.log`).
- Reduced default startup noise: logging banners (DB target, destinations, ensure-create) demoted to DEBUG; schema updates summarized once per process; logs gated to the effective reloader child to avoid duplicates.
- [media-path] diagnostics are DEBUG-only and shown only when `MEDIA_PATH_DEBUG` is set.
- README updated with a "Console TUI (experimental)" section describing usage and controls.

## [0.8.2] - 2025-10-26

### Changed
- Reduced noisy startup logs: database target and runtime schema update messages now log once per process (web and workers).
- Scheduling UI/API: removed legacy one-time ("once") schedules from creation/update paths; monthly schedules are supported in UI. Legacy rows remain readable for backward compatibility.
- GPU/Workers docs: added guidance for avatar overlays (AVATARS_PATH can point to assets root or avatars/; OVERLAY_DEBUG for tracing) and noted the startup overlay sanity warning.

### Fixed
- Avatar overlays on GPU worker: robust path normalization for AVATARS_PATH and improved fallback logic ensure avatars resolve correctly when running in containers or across mounts.

## [0.8.1] - 2025-10-25

### Added
- NVENC diagnostic improvements: probe encodes now use a valid 320x180 yuv420p frame to avoid false negatives from minimum-dimension limits; standalone `scripts/check_nvenc.py` updated accordingly.
- Avatar cache maintenance script: `scripts/cleanup_avatars.py` to prune cached creator avatars (keep N, default 5).

### Changed
- Documentation overhauled across README and docs: clarified required instance mount (`/mnt/clippy` ↔ `/app/instance`), queue routing, NVENC troubleshooting (WSL2 `LD_LIBRARY_PATH`), and path alias examples.
- Prefer system ffmpeg when present: document `PREFER_SYSTEM_FFMPEG=1` for GPU workers if both bundled and system ffmpeg exist.

### Fixed
- Alembic migrations hardened to be idempotent on PostgreSQL: guard duplicate column/index creation to avoid aborted transactions during `flask db upgrade` on existing databases.
- yt-dlp download on workers: corrected `--max-filesize` formatting (plain bytes, no trailing `B`) and dropped conflicting `--limit-rate` flags from custom args to prevent "invalid rate limit" errors.

## [0.7.2] - 2025-10-21

### Added
- Theme/UI: added a dedicated color for the "Compilation" media type.
	- Admin → Themes now has a "Compilation Border" color input.
	- Dynamic `/theme.css` exposes `--media-color-compilation`.
	- Base CSS includes `.media-card[data-type="compilation"]` and `.badge.text-bg-compilation`.
	- Runtime schema updater and Alembic migration add `themes.media_color_compilation`.

## [0.7.1] - 2025-10-21

### Added
- docs/workers.md: consolidated guide for running workers on Linux and Windows/WSL2 (Docker and native), including networking/storage patterns and a required-vs-optional flag matrix.

### Changed
- docs/gpu-worker.md: links to the consolidated guide; simplified run command; clarified that USE_GPU_QUEUE affects sender routing only.
- README: replaced the GPU-only section with a concise Remote workers section referencing the new guide.

## [0.7.0] - 2025-10-21

### Added
- Arrange: dashed insert placeholder for drag-and-drop with intro/outro lock, thicker type-colored borders on timeline tiles, and a bold remove button.
- Theme: per-media-type colors (intro/clip/outro/transition) exposed via `/theme.css` and editable in Admin → Themes.
- Media Library: cards now show type-colored borders using theme variables.
- Scripts extracted: moved inline scripts from templates (toasts, admin theme form sync, error 429) into `app/static/js/`.

### Changed
- Defaults: 60fps set by default; project name defaults to "Compilation of <today>" when blank.
- Step 2 progress keeps "Done" active after reuse-only flows; transitions badge moved to timeline info area; separators tinted when transitions selected.

### Fixed
- Remove button on timeline now reliably clickable; overlay no longer intercepts clicks.

## [0.6.0] - 2025-10-20

### Added
- Theme system with DB model and admin CRUD; dynamic `/theme.css` that maps theme colors to Bootstrap CSS variables.
- Admin themes form supports native color inputs with live hex↔swatch synchronization (no external plugin).

### Changed
- Navbar updated to stacked icon+label style; centered layout with desktop search; aligned notifications and user menu to new style.
- Media Library upload section redesigned: two-column layout with a large dashed Dropzone and a simplified "Media Type" chooser; auto-clears previews after upload.
- Vendor colorpicker removed due to Bootstrap 5 compatibility issues; using native inputs for stability.
- Theme activation and deletion flows: normal HTML posts redirect back to the list with flash messages; JSON reserved for AJAX.

### Fixed
- Deleting a theme no longer shows a JSON response; the page redirects with a success message.
## [0.5.2] - 2025-10-19

### Added
- Helper scripts: `scripts/wg_setup_server.sh`, `scripts/wg_add_client.sh`, and `scripts/setup_samba_share.sh` for easy WireGuard and Samba setup.
- `scripts/bootstrap_infra.sh`: One-shot orchestration of WireGuard server + Samba + optional client creation, prints worker run examples.
- Docker example: `docker/docker-compose.gpu-worker.example.yml` for a VPN-backed GPU worker using a CIFS mount.

### Changed
- README updated with links to scripts and example compose; GPU worker docs cross-reference.


### Changed
- Removed dev-only demo Celery task and `/api/tasks/start` endpoint; task status API remains for real jobs.
- Added tests for opaque project URLs and compiled output preview/download with HTTP Range support.

## [0.5.1] - 2025-10-19

### Added
- Cross-host media path resolution for previews and thumbnails: server now remaps paths created on remote workers using `MEDIA_PATH_ALIAS_FROM`/`MEDIA_PATH_ALIAS_TO` and automatic `instance/` suffix rebasing.
- Docs: guidance for `TMPDIR=/app/instance/tmp` to keep temp files and final outputs on the same filesystem when using SMB/WSL2 shares (avoids EXDEV cross-device moves).

### Changed
- Celery queue docs clarified: three queues (`gpu`, `cpu`, `celery`) with enqueue priority `gpu > cpu > celery`.

### Fixed
- Media Library playback 404 for newly compiled output when the worker wrote a path not valid on the web server; preview and thumbnail routes now resolve correct local paths.

## [0.5.0] - 2025-10-19

### Added
- scripts/create_database.py: create the PostgreSQL database from DATABASE_URL if missing.
- scripts/health_check.py: quick connectivity probes for DATABASE_URL and REDIS_URL.

### Changed
- Default to PostgreSQL in all environments except tests; enforce Postgres-only at runtime outside TESTING.
- Improved database logging to show driver/host/port/db (secrets redacted) and warn on localhost in containers.
- TESTING stability: always initialize Flask-Login in tests; disable runtime schema ALTERs during tests.
- Docs: README, docs/gpu-worker.md, and docs/wireguard.md updated to reflect Postgres-only runtime and VPN guidance.

### Fixed
- Pytest failing due to Postgres auth when defaults switched: early pytest-aware overrides now force SQLite in-memory; schema updates are skipped in tests.

## [0.4.1] - 2025-10-19

### Added
- Wizard Step 2 now uses a chevron-style progress UI with a focal progress bar.
- Project details page redesigned: clip cards with metadata, featured compilation card with download link, and used intros/outros/transitions list.
- Admin maintenance flow for checksum-based media deduplication.

### Changed
- Externalized inline JS/CSS from templates into static files: base layout, wizard, media library, and auth pages (login/register/account settings).
- Safer compile API: enqueue task first, then set PROCESSING status; configurable Celery queue routing.
- Development: relax cryptography pin to ">=42,<43" for wider Python compatibility.
- Persistence: database is now the source of truth for uploads and project media. Removed sidecar `.meta.json` writes during uploads; metadata (checksum, duration, dimensions, framerate) is stored in DB.
- Startup behavior: automatic media reindex on startup is disabled by default to avoid masking DB state. You can opt-in via `AUTO_REINDEX_ON_STARTUP=true`.

### Fixed
- Compile button not proceeding due to Celery queue mismatch; added a queue routing toggle and corrected status handling.
- Avatar overlay now only shows during the intended time window and is positioned correctly (~30px upward).

## [0.4.0] - 2025-10-16

### Added
- Compile pipeline now supports interleaving user-selected transitions between every segment and inserts a static bumper (`instance/assets/static.mp4`) between all segments (intro↔clip↔outro and transitions).
- NVENC detection with automatic CPU fallback: attempts hardware encoding when available and falls back to libx264 if unavailable or failing; includes a `scripts/check_nvenc.py` diagnostic.
- Branded overlays on clips: drawbox + drawtext with "Clip by <author> • <game>" and optional author avatar overlay to the left when available under `instance/assets/avatars/`.
- Timeline UI upgraded to card-style items with thumbnails and native drag-and-drop reordering; backend endpoint persists `order_index`.
- Transitions panel includes multi-select with Randomize plus bulk actions: Select All and Clear All.

### Changed
- Compile step UI cleaned up: removed hint text and intro/outro checkboxes; progress log now shows "Concatenating: <name> (i of N)".
- Centralized FFmpeg configuration with quality presets, font resolution, and encoder selection; better logging and labels sidecar for concatenation.

### Fixed
- Improved Celery task polling reliability with richer status metadata and progress reporting.
- Addressed overlay text overlap by adjusting y-offsets and drawbox placement; fixed a thumbnail generation command in the compile flow.

## [0.3.1] - 2025-10-15

### Added
- Maintenance script `scripts/reindex_media.py` to scan `instance/uploads/` and backfill `MediaFile` rows for files that exist on disk but are missing in the database. Optional `--regen-thumbnails` flag can restore video thumbnails.

### Fixed
- Media persistence across restarts: if DB rows were lost or a project was deleted while keeping library files, you can now reindex to make uploads visible again in Arrange and the Media Library.

## [0.3.0] - 2025-10-14

### Added
- Project Wizard consolidation: merged Fetch, Parse, Download into a single "Get Clips" step and removed the separate Connect step
- Twitch connection warning on Setup with link to Profile

### Changed
- Simplified 5-step flow: Setup → Get Clips → Arrange → Compile → Export
- More robust client polling for download tasks; recognizes both `state` and `status` and uses `ready`

### Fixed
- Wizard template duplication and malformed script tags
- Progress bar stuck on "Polling download task progress..." due to strict status check

### Added
- Self-hosted Dropzone and Video.js vendor assets and fetch script
- Media Library page with uploads, thumbnails, tags, bulk actions
- Improved client video playback with MIME inference and fallbacks
- Server-side MIME detection (python-magic with mimetypes fallback)
- FFmpeg thumbnail generation on upload
- Admin password reset and DB bootstrap via `init_db.py`
- Local ffmpeg/yt-dlp installer script and config resolvers
- Tests for media endpoints and filters
- CONTRIBUTING guidelines

### Changed
- README overhauled with setup, vendor assets, troubleshooting
- CSP config aligned to local vendor assets
- Safer Jinja filter `safe_count` for SQLAlchemy queries and lists

### Fixed
- Video.js MEDIA_ERR_SRC_NOT_SUPPORTED by setting type and probing support
- Dropzone CDN nosniff by serving local assets
- Development CSRF relax for auth to avoid 400s during setup

## [0.2.0] - 2025-10-13

### Added
- User authentication system with Flask-Login
- Database models with SQLAlchemy
- Video processing capabilities with ffmpeg and yt-dlp
- External API integrations (Discord, Twitch)
- Security enhancements
- Version tracking system

### Changed
- Expanded requirements.txt with new dependencies
- Enhanced project structure for video compilation platform

## [0.1.0] - 2025-10-13

### Added
- Initial Flask application setup
- Celery integration for background tasks
- Redis configuration
- Basic API endpoints
- Testing framework with pytest
- Code formatting with Black and Ruff
- Pre-commit hooks
- GitHub Actions CI/CD pipeline
- Development scripts and documentation
