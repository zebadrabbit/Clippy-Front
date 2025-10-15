# Copilot Instructions for ClippyFront

This repo is a Flask app with Celery workers for background processing and a media-focused UI. Use these guardrails to work productively and safely in this codebase.

## Architecture and key flows
- App factory + blueprints: `app/__init__.py` creates the Flask app; routes live under blueprints:
  - `app/main` (UI: projects, media library, project wizard)
  - `app/api` (JSON endpoints consumed by the wizard and pages)
  - `app/auth` (login/profile), `app/admin` (admin panel)
- Models in `app/models.py`: `User`, `Project`, `Clip`, `MediaFile`, `ProcessingJob` with enums `MediaType`, `ProjectStatus`.
- Background jobs in `app/tasks/`: Celery app and tasks for downloads/compilation.
- Templates in `app/templates/` with Bootstrap/JS; vendor assets (Dropzone, Video.js) are served locally from `app/static/vendor`.

High-level data flow for a compilation:
1) User creates a Project in the wizard (`main/project_wizard.html`) via `POST /api/projects`.
2) The wizard fetches clips (Twitch/Discord), then `POST /api/projects/<id>/clips/download` queues downloads. Dedup: existing media for the same URL is reused.
3) Downloads are polled via `GET /api/tasks/<task_id>`. After downloads, the wizard shows clips and allows arranging + intro/outro selection.
4) Compilation starts with `POST /api/projects/<id>/compile` (Celery), progress polled via tasks API, and final file served from `main.download_compiled_output`.

## Project-specific conventions
- Keep media reusable: intros/outros/transitions are stored in the user library (not bound to a single project). Deleting a project detaches these items instead of deleting files.
- Deduplicate downloads: `create_and_download_clips_api` normalizes URLs, skips batch dupes, and reuses existing `MediaFile` for the same URL owned by the user.
- Wizard UX: five-step flow (Setup → Get Clips → Arrange → Compile → Export). Get Clips should auto-run fetch/queue; Arrange lists intro/outro/clip rows as horizontally scrollable sections; Timeline uses card-style items and forces Intro first/Outro last.
- Vendor assets are local (CSP-friendly). If they’re missing, run `scripts/fetch_vendor_assets.sh`.
- Prefer per-user storage paths under `instance/` and use `FFMPEG_BINARY`/`YT_DLP_BINARY` (resolved with `_resolve_binary`).

## Development workflows
- Setup
  - `python3 -m venv venv && source venv/bin/activate`
  - `pip install -r requirements.txt`
  - `cp .env.example .env`; run `scripts/fetch_vendor_assets.sh` (and optionally `scripts/install_local_binaries.sh`).
  - `python init_db.py --all --password <pwd>` to seed an admin.
- Run
  - Web: `python main.py`
  - Worker (optional): `celery -A app.tasks.celery_app worker --loglevel=info`
- Tests/Lint
  - `pytest` (or `pytest --cov=app`)
  - `ruff check .` and `black .`
  - Pre-commit hooks run ruff/black/pytest on commit.

## Patterns to follow
- API endpoints
  - Always scope by `current_user` and validate project ownership.
  - For long-running work, kick off a Celery task and return `{ task_id }` to be polled via `/api/tasks/<id>`.
  - Return JSON with small, explicit payloads. Prefer URLs via `url_for` for media/thumbnail/preview.
- Media handling
  - On upload, detect MIME (python-magic fallback) and generate video thumbnails with ffmpeg.
  - Store thumbnails under the user’s area; serve previews via `main.media_preview` and thumbnails via `main.media_thumbnail` with auth checks.
- Wizard JS
  - Use the existing helpers in `project_wizard.html`: auto-run Get Clips, queue downloads, poll tasks; Arrange uses `addIntroToTimeline`, `addOutroToTimeline`, `addClipToTimeline` for correct placement and visuals.

## Integration points
- Twitch: `app/api/routes.py::twitch_clips_api` uses `app.integrations.twitch` for Helix calls (requires env credentials and a connected `twitch_username`).
- Discord: `app/api/routes.py::discord_messages_api` uses `app.integrations.discord` to fetch messages and extract clip URLs.
- Celery: `app/tasks/video_processing.py` provides `download_clip_task` and `compile_video_task`; task status comes from `GET /api/tasks/<id>`.

## Gotchas and tips
- If you change public behavior in API endpoints, update the wizard logic accordingly.
- For file paths and external executables, prefer `_resolve_binary` and `instance/` storage; don’t hardcode OS-specific paths.
- When deleting a project, keep intros/outros/transitions by detaching (already implemented in `main/routes.py`).
- To avoid duplicate storage, always go through the download API’s reuse logic rather than writing to `MediaFile` directly.

## Example references
- Deduped download flow: `app/api/routes.py::create_and_download_clips_api`
- Wizard behavior and UI: `app/templates/main/project_wizard.html`
- Media upload/preview: `app/main/routes.py::media_upload`, `media_preview`, `media_thumbnail`
- Models and enums: `app/models.py`

If anything here seems off or incomplete (e.g., different step flow, additional tasks, or new integrations), let me know and I’ll update these instructions accordingly.
