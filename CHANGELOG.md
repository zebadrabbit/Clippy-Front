# Changelog

All notable changes to ClippyFront will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- User authentication system with registration and login
- Database models for users, projects, media uploads, and clips
- Bootstrap frontend with dark theme
- Media upload functionality for intro/outro videos and transitions
- Discord bot integration for clip collection
- Twitch API integration for clip downloading
- Video processing pipeline with ffmpeg and yt-dlp
- Admin panel for user and system management
- Security measures including CSRF protection, rate limiting, and secure headers
- Comprehensive documentation and comments

### Changed
- Enhanced project structure for multi-user environment
- Updated dependencies for video processing and authentication

### Security
- Added password hashing with bcrypt
- Implemented CSRF protection
- Added rate limiting for API endpoints
- Secure session management
- Input validation and sanitization

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
