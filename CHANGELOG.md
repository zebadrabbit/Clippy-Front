# Changelog

All notable changes to ClippyFront will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
