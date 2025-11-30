# Features

## Core Features

### Authentication & Users

- User registration and login
- **Two-Factor Authentication (2FA)** with TOTP (Google Authenticator/Authy)
  - Mandatory for all users
  - QR code setup with manual entry fallback
  - 10 single-use backup codes (hashed storage)
  - Rate limiting: 5 attempts per 15 minutes
  - Disable and regenerate backup codes with password confirmation
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

See [TIERS-AND-QUOTAS.md](TIERS-AND-QUOTAS.md) for details.

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
- **Metadata enrichment** for creator, game, timestamp
- **Creator avatars** auto-download and cache
- **URL normalization** for deduplication
- Connected account requirement (twitch_username in profile)

### Discord

- **Message fetching** with clip URL extraction (requires bot with Read Message History permission)
- **Reaction-based filtering** (min 0-100 reactions threshold)
- **Multi-source support** in single request
- **Twitch metadata enrichment** for Discord-sourced clips
- **Per-user channel configuration** (discord_channel_id in profile)
- **Bot setup**: Requires Message Content Intent and permission 65536
- See [Discord Integration Guide](DISCORD_INTEGRATION.md) for setup

### YouTube

- **OAuth 2.0 authentication** for login/signup and account linking
- **Google account integration** with email verification
- **YouTube channel detection** and storage
- **Access token management** with refresh token support
- **Multi-channel support** - multiple YouTube channels link to same account via email
- **YouTube Data API v3** integration for channel information
- **Login flow**: Sign in with YouTube button on login page
- **Account linking**: Connect YouTube account from integrations page
- **Auto-username generation** from YouTube channel custom URL (e.g., @zebadrabbit)
- **Requires configuration**: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`
- **OAuth scopes**: openid, email, profile, youtube.readonly, youtube.upload

## Help System

- **Discord-style help center** with category/section/article hierarchy
- **Featured articles** with visual badges
- **View count tracking** for popular articles
- **Breadcrumb navigation** for easy browsing
- **Article search** (search bar ready for future implementation)
- **Markdown/HTML content support** for rich formatting
- **Admin management** via database (future: admin UI planned)
- **Categories**: Getting Started, Features, Account & Billing (extensible)
- **Routes**:
  - `/help` - Main help center with all categories
  - `/help/<category>` - Category view with sections
  - `/help/<category>/<section>/<article>` - Full article view
- **Database models**: `HelpCategory`, `HelpSection`, `HelpArticle`
- **Seed script**: `scripts/seed_help_content.py` for initial content

## Analytics System

### Overview Dashboard

- **Total clips** collected from all sources
- **Total views** aggregated from Twitch
- **Unique creators** making clips
- **Unique games** being clipped
- **Date range** tracking for analytics period
- **Top performers** (game and creator highlights)

### Creator Leaderboards

- **Clip count** per creator
- **Total and average views** for engagement metrics
- **Discord activity** (shares and reactions)
- **Game diversity** showing content variety
- **Period filtering** (day/week/month/all-time)
- **Sortable columns** for custom analysis

### Game Performance Metrics

- **Clip volume** by game
- **View aggregation** with averages
- **Viral potential** indicators (high avg views)
- **Creator diversity** per game
- **Discord engagement** metrics
- **Trending detection** for content opportunities

### Engagement Analytics

- **Timeline view** showing daily/weekly clip activity
- **View trends** over time
- **Discord shares** correlation
- **Peak activity** period detection
- **Growth tracking** month-over-month

### Viral Clips Detection

- **High-view filtering** (configurable threshold)
- **Clip details** with creator and game
- **Direct links** to source clips
- **Engagement metrics** for each clip
- **Content repurposing** opportunities

### Background Processing

- **Automated aggregation** via Celery tasks
- **Period-based summaries** (daily/weekly/monthly/all-time)
- **Performance optimization** with indexed tables
- **Incremental updates** for real-time accuracy

### API Endpoints

- `GET /analytics/api/overview` - High-level summary stats
- `GET /analytics/api/top-creators` - Creator leaderboard
- `GET /analytics/api/top-games` - Game performance metrics
- `GET /analytics/api/viral-clips` - High-performing clips
- `GET /analytics/api/engagement-timeline` - Time-series data
- `GET /analytics/api/peak-times` - Activity distribution

### Data Capture

- **Twitch integration** for view counts and metadata
- **Discord integration** for shares and reactions
- **Automatic enrichment** on clip creation
- **Per-user isolation** for data security
- **Deduplication** on clip URLs

See [Analytics Documentation](ANALYTICS.md) for complete details.

## Notification System

### Real-time Notifications

- **Server-Sent Events (SSE)** for instant updates
- **Polling fallback** for environments without SSE support
- **Navbar dropdown** with unread badge
- **Auto-refresh** on new notifications
- **Mark as read** inline or bulk
- **Activity types**: compilation complete/failed, team member added, project shared, invitation received

### Email Notifications

- **SMTP integration** with TLS/SSL support (via `app/mailer.py`)
- **Per-event-type toggles**: compilation, team activity, project sharing
- **Daily digest** with configurable time (00:00-23:00)
- **User preferences UI** in account settings
- **Respects opt-out** settings for each notification type
- **Requires configuration**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`

### Browser Push Notifications

- **Web Push API** integration for offline/background alerts
- **Service worker** (`app/static/sw.js`) for handling push events
- **VAPID authentication** for secure delivery
- **Multi-device support** with automatic subscription management
- **Contextual actions**: click notification → navigate to project/team
- **Automatic cleanup** of expired/invalid subscriptions
- **Requires configuration**: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_EMAIL`
- **Requires library**: `pip install pywebpush py-vapid`

### Notification Management

- **Dedicated notifications page** (`/notifications`) with:
  - Pagination (20 per page)
  - Filter by type (all event types)
  - Filter by read/unread status
  - Filter by date range (today, week, month, 3 months, all time)
  - Bulk select with checkboxes
  - Bulk mark as read
  - Bulk delete
- **Actionable buttons**: "View Project", "Go to Team", "See Details", "View Invitation"
- **Retention policy**: Auto-delete read notifications after 30 days (configurable via `NOTIFICATION_RETENTION_DAYS`)
- **Scheduled cleanup** via Celery Beat (runs daily)
- **Real-time date formatting** with relative times ("2 hours ago")

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
