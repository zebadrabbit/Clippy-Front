# Database Isolation: Development vs Production

## Overview

ClippyFront now uses table prefixes to isolate development and production databases. Both environments share the same PostgreSQL database (`clippy_front`) but use different table namespaces.

## Environment Configuration

### Production (/opt/clippyfront)
- **Table Prefix**: `opt_`
- **Redis Database**: 1 (`redis://10.8.0.1:6379/1`)
- **Configuration**: `/opt/clippyfront/.env`
  ```bash
  TABLE_PREFIX=opt_
  CLIPPY_INSTANCE_PATH=/opt/clippyfront/instance
  REDIS_URL=redis://10.8.0.1:6379/1
  CELERY_BROKER_URL=redis://10.8.0.1:6379/1
  CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/1
  ```
- **Admin Credentials**:
  - Username: `admin`
  - Password: `ClippyProd2025!`
  - Email: `admin@clippyfront.com`

### Development (/home/winter/work/ClippyFront)
- **Table Prefix**: `dev_`
- **Redis Database**: 0 (`redis://10.8.0.1:6379/0`)
- **Configuration**: `/home/winter/work/ClippyFront/.env`
  ```bash
  TABLE_PREFIX=dev_
  REDIS_URL=redis://10.8.0.1:6379/0
  CELERY_BROKER_URL=redis://10.8.0.1:6379/0
  CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/0
  ```
- **Admin Credentials**:
  - Username: `admin`
  - Password: `DevPass123!`
  - Email: `admin@clippyfront.com`

## Database Schema

Both environments have identical schema with 18 tables each:

| Development Tables (dev_*) | Production Tables (opt_*) |
|---------------------------|--------------------------|
| dev_users                 | opt_users                |
| dev_projects              | opt_projects             |
| dev_media_files           | opt_media_files          |
| dev_clips                 | opt_clips                |
| dev_tags                  | opt_tags                 |
| dev_processing_jobs       | opt_processing_jobs      |
| dev_tiers                 | opt_tiers                |
| dev_render_usage          | opt_render_usage         |
| dev_system_settings       | opt_system_settings      |
| dev_themes                | opt_themes               |
| dev_compilation_tasks     | opt_compilation_tasks    |
| dev_scheduled_tasks       | opt_scheduled_tasks      |
| dev_teams                 | opt_teams                |
| dev_team_memberships      | opt_team_memberships     |
| dev_activity_logs         | opt_activity_logs        |
| dev_team_invitations      | opt_team_invitations     |
| dev_notifications         | opt_notifications        |
| dev_notification_preferences | opt_notification_preferences |

## Shared Resources

### PostgreSQL Database
- **Database Name**: `clippy_front`
- **Host**: `10.8.0.1` (via WireGuard)
- Both environments share the same database server but use different table prefixes

### Redis Server
- **Host**: `10.8.0.1:6379` (via WireGuard)
- **Production**: Database 1 (`redis://10.8.0.1:6379/1`)
- **Development**: Database 0 (`redis://10.8.0.1:6379/0`)
- Complete isolation of task queues, results, cache, and rate limiting

### PostgreSQL ENUM Types
ENUM types are shared between environments:
- `userrole`
- `teamrole`
- `activitytype`
- `platformpreset`
- `jobstatus`
- `projectstatus`
- `mediatype`

## How It Works

### Code Implementation

The table prefix system uses a module-level variable in `app/models.py`:

```python
import os
_TABLE_PREFIX = os.environ.get('TABLE_PREFIX', '')

class User(UserMixin, db.Model):
    __tablename__ = f"{_TABLE_PREFIX}users"

    user_id = db.Column(db.Integer, db.ForeignKey(f"{_TABLE_PREFIX}users.id"))
```

All table names, foreign keys, constraints, and indexes use the prefix dynamically.

### Environment Loading

The `TABLE_PREFIX` environment variable must be set **before** importing the app:

```bash
# Development
export TABLE_PREFIX=dev_
python main.py

# Production (via systemd)
# Set in /opt/clippyfront/.env
# Loaded by systemd EnvironmentFile
```

## Database Operations

### Verify Table Isolation

```bash
sudo -u postgres psql clippy_front -c "\dt opt_*"   # Production tables
sudo -u postgres psql clippy_front -c "\dt dev_*"   # Development tables
```

### Check User Data

```sql
-- Production users
SELECT username FROM opt_users;

-- Development users
SELECT username FROM dev_users;
```

### Initialize Fresh Database

**Production:**
```bash
cd /opt/clippyfront
sudo -u clippyfront bash -c 'export TABLE_PREFIX=opt_ && source venv/bin/activate && python3 init_db.py --all --password "YourPassword"'
```

**Development:**
```bash
cd /home/winter/work/ClippyFront
source venv/bin/activate
export TABLE_PREFIX=dev_
python3 init_db.py --all --password "YourPassword"
```

## Migration Guide

### Updating Code

1. Edit models in `/home/winter/work/ClippyFront/app/models.py`
2. Test in development environment
3. Copy to production:
   ```bash
   sudo cp /home/winter/work/ClippyFront/app/models.py /opt/clippyfront/app/models.py
   sudo systemctl restart gunicorn-clippyfront
   ```

### Database Migrations

When using Flask-Migrate (Alembic):

**Development:**
```bash
cd /home/winter/work/ClippyFront
export TABLE_PREFIX=dev_
flask db migrate -m "Description"
flask db upgrade
```

**Production:**
```bash
cd /opt/clippyfront
sudo -u clippyfront bash -c 'export TABLE_PREFIX=opt_ && source venv/bin/activate && flask db upgrade'
```

## Troubleshooting

### Wrong Table Prefix

**Symptom:** App can't find tables (e.g., "relation 'users' does not exist")

**Solution:** Ensure TABLE_PREFIX is set before starting the app:
```bash
grep TABLE_PREFIX /opt/clippyfront/.env           # Production
grep TABLE_PREFIX /home/winter/work/ClippyFront/.env  # Development
```

### Constraint Conflicts

**Symptom:** "relation 'uix_user_tag_slug' already exists"

**Solution:** All constraint and index names include the prefix. If you encounter conflicts, the prefix is missing from a constraint definition in `app/models.py`.

### Mixed Data

**Symptom:** Development data appears in production or vice versa

**Solution:** Verify the correct TABLE_PREFIX is set in each environment's `.env` file and that systemd is loading it correctly:
```bash
sudo systemctl show gunicorn-clippyfront | grep EnvironmentFile
```

## Testing Isolation

Verify environments are completely isolated:

```python
# In development shell
export TABLE_PREFIX=dev_
python3 << 'PY'
from app import create_app
from app.models import User, db
app = create_app()
with app.app_context():
    dev_users = User.query.all()
    print(f"Dev users: {[u.username for u in dev_users]}")
PY
```

```python
# In production shell (as clippyfront user)
export TABLE_PREFIX=opt_
python3 << 'PY'
from app import create_app
from app.models import User, db
app = create_app()
with app.app_context():
    prod_users = User.query.all()
    print(f"Prod users: {[u.username for u in prod_users]}")
PY
```

Each should show their own isolated user list.

## Summary

- ✅ Development and production fully isolated
- ✅ No data cross-contamination
- ✅ Same PostgreSQL database, different table namespaces (dev_ vs opt_)
- ✅ Same Redis server, different databases (DB 0 vs DB 1)
- ✅ Independent Celery task queues and results
- ✅ Independent admin users and data
- ✅ Safe to work in dev without affecting production
- ✅ Production running on Gunicorn with opt_ tables
- ✅ Development ready with dev_ tables

## Celery Workers

### Running Two Workers (Recommended)

Since both environments run on the same server, you need **two separate Celery workers**:

**Development Worker:**
```bash
cd /home/winter/work/ClippyFront
source venv/bin/activate
export TABLE_PREFIX=dev_
celery -A app.tasks.celery_app worker --loglevel=info -Q celery,cpu,gpu
```
- Connects to Redis DB 0
- Uses `dev_*` database tables
- Processes development tasks only

**Production Worker:**
```bash
cd /opt/clippyfront
sudo -u clippyfront bash -c 'source venv/bin/activate && export TABLE_PREFIX=opt_ && celery -A app.tasks.celery_app worker --loglevel=info -Q celery,cpu,gpu'
```
- Connects to Redis DB 1
- Uses `opt_*` database tables
- Processes production tasks only

### Remote GPU/CPU Workers

Remote workers (via WireGuard) should connect to **production only**:

```yaml
# docker/compose.worker.yaml or similar
environment:
  - CELERY_BROKER_URL=redis://10.8.0.1:6379/1
  - CELERY_RESULT_BACKEND=redis://10.8.0.1:6379/1
  - TABLE_PREFIX=opt_  # Important: match production!
  - DATABASE_URL=postgresql://postgres:password@10.8.0.1/clippy_front
```

Remote workers:
- Process production compilation tasks on GPU queue
- Use `opt_*` tables when querying database
- Cannot access development environment (different Redis DB)

### Why Two Workers?

The `TABLE_PREFIX` is loaded at worker **startup time** and cannot change dynamically:
1. Worker imports task modules → `_TABLE_PREFIX` is set from environment
2. All SQLAlchemy queries use that prefix for the worker's lifetime
3. A single worker cannot switch between `dev_*` and `opt_*` tables

### Production Worker as Systemd Service

Create `/etc/systemd/system/celery-clippyfront.service`:

```ini
[Unit]
Description=Celery worker for ClippyFront (production)
After=network.target redis.service postgresql.service

[Service]
Type=forking
User=clippyfront
Group=clippyfront
WorkingDirectory=/opt/clippyfront
EnvironmentFile=/opt/clippyfront/.env
Environment="PATH=/opt/clippyfront/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/clippyfront/venv/bin/celery -A app.tasks.celery_app worker \
    --detach --loglevel=info -Q celery,cpu,gpu \
    --logfile=/opt/clippyfront/instance/logs/celery-worker.log \
    --pidfile=/opt/clippyfront/instance/celery-worker.pid
ExecStop=/opt/clippyfront/venv/bin/celery -A app.tasks.celery_app control shutdown
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable celery-clippyfront
sudo systemctl start celery-clippyfront
```

For deployment updates, see `docs/WORKER_SETUP.md` and `scripts/deploy_update.sh`.
