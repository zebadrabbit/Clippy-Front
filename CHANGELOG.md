# Changelog

All notable changes to ClippyFront will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
