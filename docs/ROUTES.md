# Routes catalog for ClippyFront

This document is a developer-facing index of the main HTTP routes found in the
repository. It is intended as a quick reference for contributors and was
generated from the current codebase (first-pass). If you want a full
exhaustive machine-generated list, I can extend this file to include every
decorator match and example payload.

Notes:
- File: the Python module where the route is defined (blueprint may be returned by `url_for`).
- Path: the URL path pattern.
- Methods: allowed HTTP methods.
- Brief: one-line description.
- Parameters: path/query/body fields that matter.
- Example: a small example JSON response (when the handler returns JSON).

---

## API blueprint (app/api/*)

### app/api/health.py
- Path: GET /api/health
- Methods: GET
- Brief: Liveness/health check for load-balancers and orchestration.
- Parameters: none
- Example response:
  {
    "status": "healthy",
    "message": "Clippy API is running"
  }

### app/api/jobs.py
- Path: GET /api/tasks/<task_id>
- Methods: GET
- Brief: Query a Celery AsyncResult and return a defensive JSON summary.
- Parameters: task_id (path)
- Example response:
  {
    "task_id": "<id>",
    "status": "PENDING|STARTED|SUCCESS|FAILURE",
    "ready": true|false,
    "info": {...},
    "result": {...}
  }

### app/api/media.py
- Path: GET /api/media/raw/<media_id>
- Methods: GET
- Brief: Internal raw media file access (no signatures).
- Parameters: media_id (path)
- Example response: Streams file or JSON {"error":"Not found"}

- Path: GET /api/avatars/by-clip/<clip_id>
- Methods: GET
- Brief: Serve a cached avatar image for a clip's creator.
- Parameters: clip_id (path)

- Path: GET /api/media/stats
- Methods: GET
- Brief: Counts of the current user's media by type.
- Parameters: ?type=<intro|outro|transition|clip> (optional)
- Example response:
  {
    "total": 12,
    "by_type": {"intro": 1, "clip": 8, "outro": 1, "transition": 2},
    "recent_ids": [12,11,10,9,8]
  }

- Path: GET /api/media
- Methods: GET
- Brief: List user's media library with preview/thumbnail URLs.
- Parameters: ?type=

- Path: GET /api/projects/<project_id>/media
- Methods: GET
- Brief: List media visible/attached to a project (or user's library filtered by project).

### app/api/routes.py (selected endpoints)
- Path: POST /api/projects
- Methods: POST
- Brief: Create a new Project for current_user (wizard flow).
- Parameters (JSON body): name (required or defaulted), description, output_resolution, output_format, max_clip_duration, audio_norm_profile, audio_norm_db
- Example response:
  {"project_id": 42, "status": "created"}

- Path: POST /api/projects/<project_id>/clips/download
- Methods: POST
- Brief: Create Clip rows from URLs/structured clips and enqueue download tasks (queues to cpu/gpu).
- Parameters (JSON): {"urls": [...], "clips": [...], "limit": n}
- Example response (202):
  {"items": [{"clip_id": 123, "task_id": "<celery_id>", "url": "..."}], "count": 1, "skipped": 0}

- Path: POST /api/projects/<project_id>/compile
- Methods: POST
- Brief: Start compilation task for a project (performs quota checks and queues a Celery job).
- Parameters (JSON): intro_id, outro_id, transition_ids, randomize_transitions, clip_ids
- Example response (202): {"task_id": "<celery_id>", "status": "started"}

- Path: GET /api/projects/<project_id>/clips
- Methods: GET
- Brief: List clips for a project with basic media info.

- Path: POST /api/projects/<project_id>/clips/order
- Methods: POST
- Brief: Reorder clips. Body: {"clip_ids": [int,...]}

- Path: POST /api/worker/projects/<project_id>/clips/<clip_id>/upload
- Methods: POST
- Brief: Worker endpoint to upload downloaded clip and thumbnail directly.
- Parameters: multipart/form-data with video file, thumbnail file, and JSON metadata.
- Auth: Requires WORKER_API_KEY bearer token.

- Path: GET /api/twitch/clips
- Methods: GET
- Brief: Fetch Twitch clips for a username (Helix integration).
- Query params: username, first, started_at, ended_at, after

- Path: GET /api/discord/messages
- Methods: GET
- Brief: Fetch Discord channel messages and extract clip URLs.
- Query params: channel_id, limit

- Automation endpoints (selected):
  - POST /api/automation/tasks — create compilation task
  - GET /api/automation/tasks — list tasks
  - POST /api/automation/tasks/<id>/run — run a task
  - GET/PATCH/PUT/DELETE /api/automation/tasks/<id> — task CRUD
  - POST/GET /api/automation/tasks/<id>/schedules — schedule CRUD
  - PATCH/DELETE /api/automation/schedules/<id>

---

## Main blueprint (app/main/routes.py)

The main blueprint serves user-facing pages and many JSON endpoints used by the UI.

- Path: GET /
  - Methods: GET
  - Brief: Landing page

- Path: GET /dashboard
  - Methods: GET
  - Brief: User dashboard (requires auth)

- Path: GET /projects
  - Methods: GET
  - Brief: List user's projects (pagination/query filters)

- Path: GET /p/<public_id>
  - Methods: GET
  - Brief: Project detail (opaque public id)

- Path: GET /projects/<project_id>
  - Methods: GET
  - Brief: Legacy numeric project detail (redirects to opaque route)

- Path: POST /projects/<project_id>/upload
  - Methods: GET, POST
  - Brief: Upload media file for a project (multipart/form-data)

- Path: POST /projects/<project_id>/compile
  - Methods: POST
  - Brief: Start compilation (UI route that queues a Celery task)
  - Example response: {"task_id":"<id>", "status":"started"}

- Path: GET /media
  - Methods: GET
  - Brief: Render media library page (HTML)

- Path: POST /media/upload
  - Methods: POST
  - Brief: API to upload media into user's library; returns JSON with created media id and preview/thumbnail URLs.

- Path: GET /media/preview/<media_id>
  - Methods: GET
  - Brief: Stream media preview (auth enforced)

- Path: GET /media/thumbnail/<media_id>
  - Methods: GET
  - Brief: Serve thumbnail; will generate on-demand for videos and store path in DB if created.

- Path: POST /media/<media_id>/update
  - Methods: POST
  - Brief: Rename or change type/tags of a media file (AJAX)

- Path: POST /media/<media_id>/delete
  - Methods: POST
  - Brief: Delete a media file and its thumbnail

- Path: POST /media/bulk
  - Methods: POST
  - Brief: Bulk operations on selected media (delete, change_type, set_tags)

- Path: GET /projects/wizard
  - Methods: GET
  - Brief: Project creation wizard UI (multi-step)

- Several theme assets and preview/download routes:
  - /theme/logo, /theme/favicon, /theme/watermark, /theme.css
  - /p/<public_id>/download and /p/<public_id>/preview (compiled output download/stream)

- Help system routes (v1.5.1+):
  - GET /help - Main help center with all categories
  - GET /help/<category_slug> - Category view with sections
  - GET /help/<category_slug>/<section_slug>/<article_slug> - Full article view with view tracking

---

## Analytics blueprint (app/analytics/routes.py) - v1.4.0+

- Path: GET /analytics
  - Methods: GET
  - Brief: Analytics dashboard showing clip engagement metrics
  - Parameters: none
  - Returns: HTML page with period selectors and data tables

- Path: GET /analytics/api/overview
  - Methods: GET
  - Brief: High-level analytics summary
  - Parameters: ?period=day|week|month|all_time (default: all_time)
  - Example response:
    {
      "total_clips": 1234,
      "total_views": 456789,
      "unique_creators": 89,
      "unique_games": 23,
      "date_range": {"start": "2025-01-01", "end": "2025-11-30"},
      "top_game": {"name": "Elden Ring", "clip_count": 145},
      "top_creator": {"name": "xXClipperXx", "clip_count": 67}
    }

- Path: GET /analytics/api/top-creators
  - Methods: GET
  - Brief: Creator leaderboard with engagement metrics
  - Parameters: ?period=day|week|month|all_time, ?limit=10 (default)
  - Example response:
    {
      "period": "all_time",
      "creators": [
        {
          "creator_name": "xXClipperXx",
          "creator_id": "12345",
          "clip_count": 67,
          "total_views": 123456,
          "avg_views": 1841.7,
          "discord_shares": 12,
          "discord_reactions": 89,
          "unique_games": 8
        }
      ]
    }

- Path: GET /analytics/api/top-games
  - Methods: GET
  - Brief: Game performance metrics and viral potential
  - Parameters: ?period=day|week|month|all_time, ?limit=10
  - Example response:
    {
      "period": "week",
      "games": [
        {
          "game_name": "Elden Ring",
          "game_id": "512953",
          "clip_count": 145,
          "total_views": 234567,
          "avg_views": 1617.7,
          "unique_creators": 23,
          "discord_shares": 34,
          "discord_reactions": 156
        }
      ]
    }

- Path: GET /analytics/api/viral-clips
  - Methods: GET
  - Brief: High-performing clips for content repurposing
  - Parameters: ?period=day|week|month|all_time, ?limit=20, ?min_views=1000
  - Example response:
    {
      "period": "month",
      "min_views": 1000,
      "clips": [
        {
          "clip_id": 456,
          "title": "Epic Moment",
          "creator_name": "ProGamer",
          "game_name": "Elden Ring",
          "view_count": 15234,
          "discord_shares": 8,
          "discord_reactions": 45,
          "created_at": "2025-11-15T14:23:00Z",
          "url": "https://clips.twitch.tv/..."
        }
      ]
    }

- Path: GET /analytics/api/engagement-timeline
  - Methods: GET
  - Brief: Time-series data for trend analysis
  - Parameters: ?period=day|week|month (default: week), ?days=30 (lookback)
  - Example response:
    {
      "period": "day",
      "timeline": [
        {
          "date": "2025-11-30",
          "clip_count": 12,
          "total_views": 5678,
          "discord_shares": 4,
          "discord_reactions": 23
        }
      ]
    }

- Path: GET /analytics/api/peak-times
  - Methods: GET
  - Brief: Hourly and daily distribution of clip creation
  - Parameters: ?period=day|week|month|all_time
  - Example response:
    {
      "hourly": [
        {"hour": 0, "clip_count": 12},
        {"hour": 1, "clip_count": 8},
        ...
      ],
      "daily": [
        {"day_of_week": 0, "day_name": "Monday", "clip_count": 145},
        ...
      ]
    }

---

## Auth blueprint (app/auth/routes.py)

- Path: GET,POST /auth/login
  - Methods: GET, POST
  - Brief: Login form and submission

- Path: GET,POST /auth/register
  - Methods: GET, POST
  - Brief: User registration

- Path: GET /auth/logout
  - Methods: GET
  - Brief: Logout

- Path: GET,POST /auth/profile
  - Methods: GET, POST
  - Brief: View and edit profile

- Path: POST /auth/delete-account
  - Methods: POST
  - Brief: Delete the user and cascade deletion

- OAuth & external connections:
  - GET /auth/login/discord - Initiate Discord OAuth for login/signup
  - GET /auth/discord/callback - Handle Discord OAuth callback
  - GET /auth/login/twitch - Initiate Twitch OAuth for login/signup
  - GET /auth/twitch/callback - Handle Twitch OAuth callback
  - GET /auth/login/youtube - Initiate YouTube/Google OAuth for login/signup
  - GET /auth/youtube/login-callback - Handle YouTube OAuth callback for login
  - GET /auth/youtube/connect - Connect YouTube account (requires login)
  - GET /auth/youtube/callback - Handle YouTube OAuth callback for account linking
  - POST /auth/youtube/disconnect - Disconnect YouTube account
  - POST /auth/change-password - Change user password
  - POST /auth/connect/discord, /auth/connect/twitch - Legacy connect endpoints
  - POST /auth/disconnect/... - Disconnect various integrations

---

## Admin blueprint (app/admin/routes.py)

This module exposes many admin-only HTML and JSON endpoints. Only a handful are
listed here; see the file for the full set.

- Path: GET /admin/
  - Methods: GET
  - Brief: Admin dashboard (system stats)

- Path: GET /admin/users
  - Methods: GET
  - Brief: User management list

- Path: GET,POST /admin/users/create
  - Methods: GET, POST
  - Brief: Create a new user (admin)

- Path: GET /admin/users/<user_id>
  - Methods: GET
  - Brief: User details

- Path: POST /admin/users/<user_id>/toggle-status
  - Methods: POST
  - Brief: Activate/deactivate user (JSON)

- Path: POST /admin/users/<user_id>/reset-password
  - Methods: POST
  - Brief: Reset a user's password and optionally return a generated temporary password

- Path: GET /admin/projects
  - Methods: GET
  - Brief: Admin project management list

- Path: POST /admin/projects/<project_id>/delete
  - Methods: POST
  - Brief: Admin delete project (removes compiled outputs and optionally media rows)

- Maintenance & workers:
  - GET/POST /admin/maintenance, /admin/workers, /admin/workers.json

---

## How to extend

This is a first-pass index focusing on the most important, frequently used
routes. If you'd like, I can:

- (A) Expand this file to include every decorator found across the repo (all
  ~140 matches discovered), with extracted docstring summaries and example
  responses where available.
- (B) Produce a machine-readable JSON/YAML manifest of routes for tooling.
- (C) Continue the incremental refactor and move more API endpoints into
  dedicated modules with header docs (projects, automation, etc.).

Tell me which option you prefer and I'll continue.

---

Generated by an automated scan and manual summarization — consider this a
developer convenience sheet, and update as routes evolve.

---

## Expanded route catalog (detailed)

This section expands the earlier summary into a more exhaustive list of the
primary routes discovered in the codebase. It includes the file/module, the
URL path, HTTP methods, a short description, parameters (path/query/body) and
an example or notes where appropriate. This is a first-pass; some handlers
render HTML (templates) while others return JSON or stream files.

Notes about prefixes:
- `api` endpoints are registered on the `api_bp` blueprint and typically mounted
  under `/api` in the app factory (see `app/__init__.py` for the actual mount).
- `main`, `auth`, and `admin` blueprints are usually mounted at root paths
  (no `/api` prefix) and serve HTML pages in addition to JSON endpoints.

### app/api/health.py
- GET /api/health
  - Methods: GET
  - Purpose: Liveness probe / health check for infra.
  - Returns: JSON with status/message.

### app/api/jobs.py
- GET /api/tasks/<task_id>
  - Methods: GET
  - Purpose: Returns Celery AsyncResult summary (defensive JSON serialization).
  - Params: task_id (path)
  - Example: {"task_id":"...","status":"PENDING","ready":false}

### app/api/media.py (detailed)
- GET /api/media/raw/<media_id>
  - Methods: GET
  - Purpose: Serve raw media by id for internal/worker use (no signed URLs).
  - Returns: file stream or JSON error.

- GET /api/avatars/by-clip/<clip_id>
  - Methods: GET
  - Purpose: Return a cached avatar image for a clip's creator.

- GET /api/media/stats
  - Methods: GET
  - Purpose: Per-user media counts by type. Optional ?type= filter.

- GET /api/media
  - Methods: GET
  - Purpose: List media in user's library. Optional ?type= filter.

- GET /api/projects/<project_id>/media
  - Methods: GET
  - Purpose: List media relevant to a project or the user's library filtered
    by media type.

### app/api/routes.py — project & wizard APIs (selected)
Note: This file acts as a compatibility shim; many endpoints are implemented
here and in the submodules imported by it.

- POST /api/projects
  - Methods: POST
  - Purpose: Create a new Project (wizard API)
  - Body (JSON): name (optional), description, output_resolution, output_format, max_clip_duration, audio_norm_profile, audio_norm_db
  - Example: {"project_id":42,"status":"created"}

- POST /api/projects/<project_id>/clips/download
  - Methods: POST
  - Purpose: Accepts URLs or structured clips and creates Clip rows and
    enqueues download tasks (to 'gpu' or 'cpu' queue).
  - Body (JSON): {"urls": [...], "clips": [...], "limit": n}
  - Notes: Dedup/reuse logic intentionally disabled; every request creates
    fresh Clip rows and queues downloads to avoid cross-project races.

- POST /api/projects/<project_id>/compile
  - Methods: POST
  - Purpose: Start compilation; validates selected intro/outro/transitions,
    checks render quota, enqueues a Celery `compile_video_task`.
  - Body (JSON): {"intro_id":int,"outro_id":int,"transition_ids":[...],"randomize_transitions":bool,"clip_ids":[...]}
  - Example success: {"task_id":"<celery_id>","status":"started"}

- GET /api/projects/<project_id>/clips
  - Methods: GET
  - Purpose: Return project clip metadata (duration, creator, media preview
    URLs). Used by the UI's Arrange step.

- POST /api/projects/<project_id>/clips/order
  - Methods: POST
  - Purpose: Reorder clips. Body: {"clip_ids":[int,...]}

- POST /api/projects/<project_id>/ingest/raw
  - Methods: POST
  - Purpose: Trigger ingestion of raw files from worker ingest roots into a
    project. Enqueues `ingest_raw_clips_for_project` Celery task.
  - Body: {"worker_id":"...","action":"copy|move|link","regen_thumbnails":bool}

- POST /api/projects/<project_id>/ingest/compiled
  - Methods: POST
  - Purpose: Trigger ingestion of compiled artifacts for a project.

- GET /api/twitch/clips
  - Methods: GET
  - Purpose: Query Twitch Helix for clips by username.
  - Query: username, first, started_at, ended_at, after

- GET /api/discord/messages
  - Methods: GET
  - Purpose: Retrieve recent messages from a Discord channel and extract
    clip URLs.
  - Query: channel_id, limit

### app/api/automation (selected endpoints from routes in api)
- POST /api/automation/tasks
  - Methods: POST
  - Purpose: Create an automation/compilation task (user-specific).
  - Body: {"name":...,"description":...,"params":{...}}

- GET /api/automation/tasks
  - Methods: GET
  - Purpose: List user's automation tasks.

- POST /api/automation/tasks/<id>/run
  - Methods: POST
  - Purpose: Trigger a run of a CompilationTask; enqueues automation job.

- GET/PATCH/PUT/DELETE /api/automation/tasks/<id>
  - Methods: GET,PATCH,PUT,DELETE
  - Purpose: Full CRUD for automation tasks (ownership enforced).

- POST/GET /api/automation/tasks/<id>/schedules
  - Methods: POST, GET
  - Purpose: Create/list schedules for a task (tier-gated).

- PATCH/DELETE /api/automation/schedules/<id>
  - Methods: PATCH, DELETE
  - Purpose: Update or delete a scheduled run.

---

### app/main/routes.py (user-facing HTML + JSON endpoints)

- GET /
  - Methods: GET
  - Purpose: Landing page (HTML)

- GET /dashboard
  - Methods: GET
  - Purpose: User dashboard; shows recent projects and stats.

- GET /projects
  - Methods: GET
  - Purpose: Projects listing (UI) with pagination and optional status filter.
  - Query: page, status

- GET /p/<public_id>
  - Methods: GET
  - Purpose: Project detail by opaque public id (UI). Ownership enforced.

- GET /projects/<project_id>
  - Methods: GET
  - Purpose: Legacy numeric-id view; redirects to opaque-id view when
    available.

- GET,POST /projects/<project_id>/upload
  - Methods: GET, POST
  - Purpose: Upload files tied to a project (multipart form). Handles
    thumbnails, metadata probe, quota enforcement.

- POST /projects/<project_id>/compile
  - Methods: POST
  - Purpose: UI-triggered compile that enqueues a Celery task (compile_video_task).

- GET /media
  - Methods: GET
  - Purpose: Render the media library page (HTML) with optional type filter.

- POST /media/upload
  - Methods: POST
  - Purpose: API endpoint to upload media into the user's library. Returns
    JSON including media id, preview and thumbnail URLs.

- GET /media/preview/<media_id>
  - Methods: GET
  - Purpose: Stream a media file (auth & ownership checks applied).

- GET /media/thumbnail/<media_id>
  - Methods: GET
  - Purpose: Serve or lazily generate a thumbnail for a media file.

- POST /media/<media_id>/update
  - Methods: POST
  - Purpose: Rename media or change its type/tags.

- POST /media/<media_id>/delete
  - Methods: POST
  - Purpose: Delete a media file and its thumbnail (auth enforced).

- POST /media/bulk
  - Methods: POST
  - Purpose: Bulk operations: delete, change_type, set_tags. Form-encoded.

- GET /projects/wizard
  - Methods: GET
  - Purpose: The multi-step wizard UI for project creation and compilation.

- Theme & compiled output routes:
  - GET /theme/logo, /theme/favicon, /theme/watermark — binaries for active theme
  - GET /theme.css — CSS based on active theme
  - GET /p/<public_id>/download — download compiled output (attachment)
  - GET /p/<public_id>/preview — stream compiled output (range support)
  - GET /projects/<project_id>/download — owner-only compiled download
  - GET /projects/<project_id>/preview — owner-only compiled preview

### Authentication (app/auth/routes.py)

- GET,POST /login
  - Methods: GET, POST
  - Purpose: Sign-in form; validates via `LoginForm` and logs user in.

- GET,POST /register
  - Methods: GET, POST
  - Purpose: User registration page and processing.

- GET /logout
  - Methods: GET
  - Purpose: Logout current user.

- GET,POST /profile
  - Methods: GET, POST
  - Purpose: View and edit user profile; timezone validation.

- POST /delete-account
  - Methods: POST
  - Purpose: Delete current user's account (destructive)

- POST /change-password
  - Methods: POST
  - Purpose: Change password (requires current password and confirmation).

- POST /connect/discord, /disconnect/discord, /connect/twitch, /disconnect/twitch
  - Methods: POST
  - Purpose: Lightweight endpoints to save/clear external service identifiers.

### Admin (app/admin/routes.py) — selected endpoints

- GET /admin/
  - Methods: GET
  - Purpose: Admin dashboard showing system statistics.

- GET /admin/users
  - Methods: GET
  - Purpose: Admin user management listing with filters.

- GET,POST /admin/users/create
  - Methods: GET, POST
  - Purpose: Create new users (admin-only).

- GET /admin/users/<user_id>
  - Methods: GET
  - Purpose: Detailed user view + stats.

- POST /admin/users/<user_id>/toggle-status
  - Methods: POST
  - Purpose: Activate/deactivate a user; returns JSON with new status.

- POST /admin/users/<user_id>/reset-password
  - Methods: POST
  - Purpose: Admin password reset for a user; may return a temp password.

- GET /admin/projects, /admin/projects/<id>/edit, POST /admin/projects/<id>/delete
  - Methods: GET, POST
  - Purpose: Project administration and deletion with preservation/detachment
    behavior for reusable media.

- GET/POST /admin/maintenance
  - Methods: GET, POST
  - Purpose: Trigger reindex/reindex+prune via Celery tasks.

- GET /admin/workers and /admin/workers.json
  - Methods: GET
  - Purpose: Inspect Celery workers and return JSON summaries.

---

## Gaps & next improvements

- This expanded catalog covers the most important routes inspected in the
  repository and expands the initial one-page summary. There are additional
  endpoints and route decorators across the codebase (including many smaller
  AJAX endpoints and admin utilities). If you'd like, I can:

  1) Produce a full machine-extracted list of every `@*_bp.route` decorator
     with the exact file/line, method list, and function docstring summary.
  2) Output the entire manifest as JSON/YAML for use in tooling or a small
     web-based index page.
  3) Run the linter (ruff) and formatter (black) inside the virtualenv and
     iterate on any lint errors.

Pick one of the above and I'll continue. If you'd like me to run ruff/black
now, confirm that I should activate the project's `venv/` and run the tools
there — I can then present the results and fix trivial issues where safe.
