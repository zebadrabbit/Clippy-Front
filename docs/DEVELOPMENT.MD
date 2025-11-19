# Development Guide

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL
- Redis
- Git

### Initial Setup

See [INSTALLATION.MD](INSTALLATION.MD) for complete setup instructions.

Quick start for development:

```bash
# Clone and setup
git clone <repo-url>
cd ClippyFront
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your settings

# Install assets and binaries
bash scripts/fetch_vendor_assets.sh
bash scripts/install_local_binaries.sh

# Initialize database
python init_db.py --all --password admin123

# Start services
python main.py                                           # Web app
celery -A app.tasks.celery_app worker -Q celery --loglevel=info  # Worker
```

## Project Structure

```
ClippyFront/
├── app/
│   ├── __init__.py              # Flask app factory
│   ├── admin/                   # Admin blueprint
│   ├── api/                     # API blueprint
│   ├── auth/                    # Auth blueprint
│   ├── main/                    # Main UI routes
│   ├── tasks/                   # Celery tasks
│   ├── templates/               # Jinja templates
│   ├── static/                  # Static assets
│   └── models.py                # Database models
├── config/
│   └── settings.py              # Configuration
├── scripts/                     # Utility scripts
├── tests/                       # Test suite
├── docs/                        # Documentation
├── main.py                      # Entry point
└── requirements.txt             # Dependencies
```

See [REPO-STRUCTURE.MD](REPO-STRUCTURE.MD) for detailed directory guide.

## Development Workflow

### Code Quality

**Linting** with Ruff:
```bash
ruff check .                     # Check for issues
ruff check --fix .               # Auto-fix issues
```

**Formatting** with Black:
```bash
black .                          # Format all files
black --check .                  # Check without modifying
```

**Pre-commit hooks**:
```bash
pre-commit install               # Set up hooks
pre-commit run --all-files       # Run manually
```

### Testing

**Run tests**:
```bash
pytest                           # All tests
pytest tests/test_api.py         # Specific file
pytest -k test_create_project    # Specific test
pytest -v                        # Verbose output
```

**With coverage**:
```bash
pytest --cov=app                 # Show coverage
pytest --cov=app --cov-report=html  # HTML report
```

**Test structure**:
- `tests/conftest.py` - Fixtures and test configuration
- `tests/test_*.py` - Test modules
- Fixtures: `client`, `app`, `admin_user`, `sample_project`, etc.

### Database Migrations

**Create migration**:
```bash
flask db migrate -m "Description of changes"
```

**Apply migrations**:
```bash
flask db upgrade
```

**Rollback**:
```bash
flask db downgrade
```

**Migration tips**:
- Migrations are idempotent on PostgreSQL
- Guard against duplicate columns/indexes
- Test migrations on clean database
- Review generated SQL before applying

### Running Services

**Web application**:
```bash
python main.py
# Visit http://localhost:5000
```

**Celery worker**:
```bash
# Server worker (maintenance tasks)
celery -A app.tasks.celery_app worker -Q celery --loglevel=info

# GPU worker (compilations)
celery -A app.tasks.celery_app worker -Q gpu,cpu --loglevel=info
```

**Celery beat** (for scheduled tasks):
```bash
celery -A app.tasks.celery_app beat --loglevel=info
```

**Redis**:
```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

## Debugging

### Flask Debug Mode

```bash
export FLASK_DEBUG=1
python main.py
```

Features:
- Auto-reload on code changes
- Detailed error pages
- Interactive debugger

### Logging

**Enable debug logging**:
```bash
export LOG_LEVEL=DEBUG
```

**Log locations**:
- `instance/logs/app.log` - Web application
- `instance/logs/worker.log` - Celery workers
- Console output when `FLASK_DEBUG=1`

**Overlay debugging**:
```bash
export OVERLAY_DEBUG=1  # Log avatar resolution
```

### Console TUI

Monitor workers and logs in real-time:
```bash
python scripts/console.py
```

See [TROUBLESHOOTING.MD](TROUBLESHOOTING.MD) for controls.

## Utility Scripts

### Health Checks

```bash
# Check database and Redis
python scripts/health_check.py --db "$DATABASE_URL" --redis "$REDIS_URL"
```

### Media Management

```bash
# Reindex media from filesystem
python scripts/reindex_media.py

# Regenerate thumbnails
python scripts/reindex_media.py --regen-thumbnails

# Clean up avatars
python scripts/cleanup_avatars.py --keep 5

# Check media paths
python scripts/check_media_path.py
```

### Worker Management

```bash
# Detect stale workers
./scripts/check_stale_workers.sh

# Stop stale workers interactively
./scripts/check_stale_workers.sh --stop

# Check NVENC support
python scripts/check_nvenc.py
```

### Database

```bash
# Create database
python scripts/create_database.py

# Initialize tables
python init_db.py --drop
python init_db.py --admin --password admin123

# Reset everything
python init_db.py --all --password admin123
```

## Architecture

### Flask App Factory

The app is created via factory pattern in `app/__init__.py`:

```python
from app import create_app

app = create_app()
```

### Blueprints

- `auth` - Login, logout, profile
- `main` - Projects, media library, wizard
- `admin` - User/theme/system management
- `api` - REST endpoints for AJAX/worker

### Models

Key models in `app/models.py`:
- `User` - Users and authentication
- `Project` - Video projects
- `Clip` - Individual clips in projects
- `MediaFile` - Uploaded/downloaded media
- `ProcessingJob` - Async job tracking
- `Theme` - UI theming

### Celery Tasks

Background tasks in `app/tasks/`:
- `download_clip_task_v2` - Download clips via yt-dlp
- `compile_video_v2` - Render compilations
- `ingest_import_task` - Import from ingest directory
- `scheduled_tasks_tick` - Automation scheduler

### Storage Layout

```
instance/
├── data/
│   └── <username>/
│       ├── _library/
│       │   ├── intros/
│       │   ├── outros/
│       │   └── transitions/
│       └── <project_slug>/
│           ├── clips/
│           └── compilations/
├── assets/
│   ├── avatars/
│   └── static.mp4
├── tmp/
└── logs/
```

See `app/storage.py` for path helpers.

## Contributing

See [CONTRIBUTING.MD](CONTRIBUTING.MD) for guidelines.

### Pull Request Process

1. Fork and create feature branch
2. Make changes with tests
3. Run linters and tests locally
4. Update documentation
5. Submit PR with clear description

### Code Style

- Follow PEP 8 (enforced by Ruff and Black)
- Type hints for public APIs
- Docstrings for modules and complex functions
- Keep functions focused and testable

### Commit Messages

Use Conventional Commits format:
- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation only
- `test:` - Test changes
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

### Testing Requirements

- Add tests for new features
- Maintain or improve coverage
- Test both happy path and edge cases
- Mock external services (Twitch, Discord)

## Deployment

See:
- [WORKER_SETUP.MD](WORKER_SETUP.MD) - Worker deployment
- [REMOTE_WORKER_SETUP.MD](REMOTE_WORKER_SETUP.MD) - Remote workers
- [WIREGUARD.MD](WIREGUARD.MD) - VPN setup

## AI Agent Guidelines

For AI coding assistants, see `.github/copilot-instructions.md` which covers:
- Architecture and data flow
- Wizard implementation patterns
- Media handling conventions
- Integration points
- Common gotchas

## Resources

- [FEATURES.MD](FEATURES.MD) - Feature overview
- [CONFIGURATION.MD](CONFIGURATION.MD) - Environment variables
- [TROUBLESHOOTING.MD](TROUBLESHOOTING.MD) - Common issues
- [ROUTES.MD](ROUTES.MD) - API endpoint reference
- [TIERS-AND-QUOTAS.MD](TIERS-AND-QUOTAS.MD) - Quota system
