# Features

## Core Features

### Authentication & Users

- User registration and login
- Profile management
- Admin user management
- Subscription tier system with quotas

### Media Library

- **Drag-and-drop uploads** with Dropzone
- **Server-side MIME detection** (python-magic with fallback)
- **Automatic video thumbnails** via ffmpeg
- **Video.js playback** with browser compatibility detection
- **Tag management** for organizing media
- **Bulk operations**: type change, delete, set tags
- **Multi-type support**: clips, intros, outros, transitions, images

### Project Management

- Create and organize projects
- Project wizard with 5-step workflow:
  1. Setup - Configure project details
  2. Get Clips - Fetch from Twitch/Discord
  3. Arrange - Build timeline with drag-and-drop
  4. Compile - Render final video
  5. Export - Download compiled output
- Timeline with visual reordering
- Per-project clip collections

### Video Compilation

- **Intro/Outro selection** from media library
- **Transition management** with multi-select and randomization
- **Drag-and-drop timeline** with visual feedback
- **Background rendering** via Celery
- **GPU acceleration** with NVENC (auto-fallback to CPU)
- **Branded overlays** with author/game text and avatars
- **Static bumper** between segments for channel-switching effect
- **Progress tracking** with detailed logs

### Theme System

- **Dynamic theming** via `/theme.css`
- **Admin theme CRUD**: create, edit, activate, delete
- **Per-media-type colors** for visual organization
- **Native color pickers** with hex field sync
- Bootstrap CSS variable mapping

## Subscription Tiers & Quotas

- **Monthly render-time quotas** per tier
- **Total storage quotas** per user
- **Tier-aware watermarks** (higher tiers can remove)
- **Unlimited tier** for admin/testing
- **Per-user override** for special cases
- **Automatic quota enforcement**:
  - Storage: pre-check on upload/download
  - Render-time: estimation before compile
  - Monthly reset: automatic calendar month rollover

See [TIERS-AND-QUOTAS.MD](TIERS-AND-QUOTAS.MD) for details.

## Automation & Scheduling

- **Parameterized compilation tasks**
- **Twitch clip auto-fetch** with deduplication
- **Scheduled runs**: daily/weekly/monthly
- **Tier-gated scheduling** limits
- **Celery Beat integration** for periodic execution
- **Manual trigger** via API

## Integrations

### Twitch

- **Clip fetching** via Helix API
- **Creator avatars** auto-download
- **URL normalization** for deduplication
- Connected account requirement

### Discord

- **Message fetching** with clip URL extraction
- **Multi-source support** in single request

### Content Policy

- **Allowlist mode**: Only Twitch/Discord by default
- **Configurable**: Enable external URLs via `ALLOW_EXTERNAL_URLS`
- **URL filtering**: Rejects disallowed sources with 400 error

## Performance & Optimization

### Download Deduplication

- **Normalized URL matching** across projects
- **Per-user reuse** of existing downloads
- **Batch deduplication** in wizard
- **Avatar caching** with automatic pruning

### NVENC Detection

- **Automatic capability test** on startup
- **Graceful CPU fallback** when unavailable
- **WSL2 support** with libcuda path hints
- **Manual override** via `FFMPEG_DISABLE_NVENC`

### Storage Optimization

- **Shared intro/outro/transition library** (not bound to projects)
- **Detach on delete** instead of removing files
- **Quota enforcement** with overflow cleanup
- **Path canonicalization** for cross-host compatibility

## Admin Panel

- **User management**: create, edit, delete, tier assignment
- **Theme management**: CRUD operations
- **Worker monitoring**: version compatibility, queue stats
- **System info**: versions, active workers, queues
- **Integration setup**: Twitch, Discord credentials

## Developer Experience

### Testing

- **pytest suite** with coverage
- **Fixtures** for users, projects, media
- **Mocked integrations** (Twitch, Discord)
- **SQLite in-memory** for fast tests

### Code Quality

- **Ruff linting** with auto-fix
- **Black formatting**
- **Pre-commit hooks** for automation
- **Type hints** in public APIs

### Monitoring

- **Structured logging** with JSON output
- **Worker version checking** with admin dashboard
- **Health check scripts** for DB/Redis connectivity
- **Console TUI** for live monitoring (experimental)

## Security

- **CSRF protection** on all forms
- **CORS configuration** with origin allowlist
- **Secure headers** via Talisman
- **Rate limiting** with Redis backend
- **Content Security Policy** (strict, local assets)
- **No database access** required for workers (v0.12.0+)

## Troubleshooting Tools

- **Reindex script**: Backfill DB from filesystem
- **Avatar cleanup**: Prune old cached avatars
- **NVENC check**: Diagnose GPU encoding
- **Stale worker detection**: Find duplicate/old workers
- **Health checks**: Validate DB/Redis connectivity
- **Media path checker**: Verify storage configuration
