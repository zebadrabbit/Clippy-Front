# Contributing to ClippyFront

Thanks for your interest in improving ClippyFront! This guide explains how to set up your environment, code style, testing, and how to propose changes.

## Development Setup

1) Clone and create a virtual environment

```bash
git clone <your-repo-url>
cd ClippyFront
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

2) Optional tooling and assets

```bash
# Local vendor assets (Dropzone, Video.js)
bash scripts/fetch_vendor_assets.sh
# Local ffmpeg + yt-dlp
bash scripts/install_local_binaries.sh
```

3) Initialize the database

```bash
python init_db.py --all --password admin123
```

4) Run services

```bash
python main.py
# optional celery worker (in another terminal)
celery -A app.tasks.celery_app worker --loglevel=info
```

## Coding Standards

- Python: format with Black, lint with Ruff. Keep functions small and readable.
- Flask: prefer the app factory pattern and blueprints (auth, main, admin, api).
- Templates: keep JS/CSS self-hosted under `app/static/vendor`. Avoid inline script tags where possible.
- Security: maintain CSRF, CORS, Talisman CSP, and rate limiting.
- Database migrations: use Flask-Migrate for schema changes. For dev convenience, small additive checks may run at startup but proper migrations are preferred.

## Testing

- Add or update tests in `tests/` for new features and bug fixes.
- Run the test suite locally:

```bash
pytest
pytest --cov=app
```

- Include at least one happy path and one edge case where reasonable.

## Commit Messages

- Use concise, imperative style:
  - feat(media): add video mime probing and fallback
  - fix(auth): allow admin password reset via CLI
  - docs: update README with vendor asset script
- Reference issues when applicable: `Fixes #123` or `Refs #456`.

## Pull Requests

- Keep PRs focused and reasonably small.
- Update README/CONTRIBUTING/CHANGELOG when user-facing behavior changes.
- Ensure CI is green and tests pass.
- Be ready to iterate based on review feedback.

## Reporting Issues

- Include steps to reproduce, expected vs actual behavior, logs or screenshots if relevant, and environment details.

Thanks again for contributing!
