# Changelog

All notable changes to ClippyFront will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
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
- Branded overlays on clips: drawbox + drawtext with “Clip by <author> • <game>” and optional author avatar overlay to the left when available under `instance/assets/avatars/`.
- Timeline UI upgraded to card-style items with thumbnails and native drag-and-drop reordering; backend endpoint persists `order_index`.
- Transitions panel includes multi-select with Randomize plus bulk actions: Select All and Clear All.

### Changed
- Compile step UI cleaned up: removed hint text and intro/outro checkboxes; progress log now shows “Concatenating: <name> (i of N)”.
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
