# Installation Guide

## Prerequisites

- Python 3.10+
- Redis server (for rate limiting and Celery)
- PostgreSQL database

## Setup Steps

### 1. Clone and Create Virtual Environment

```bash
git clone <your-repo-url>
cd ClippyFront
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` to set:
- `SECRET_KEY` - Generate a secure random key
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string

### 4. Fetch Frontend Vendor Assets

Fetch local frontend vendor assets (Dropzone + Video.js):

```bash
bash scripts/fetch_vendor_assets.sh
```

### 5. (Optional) Install Local Binaries

Install local ffmpeg and yt-dlp binaries to `./bin`:

```bash
bash scripts/install_local_binaries.sh
```

Then set environment variables to prefer local binaries:

```bash
export FFMPEG_BINARY="$(pwd)/bin/ffmpeg"
export YT_DLP_BINARY="$(pwd)/bin/yt-dlp"
```

### 6. Initialize Database

Create the database if it doesn't exist:

```bash
python scripts/create_database.py
```

Initialize tables and create admin user:

```bash
# Initialize tables and seed an admin + sample data (drops and recreates tables)
python init_db.py --all --password admin123

# Or incrementally:
python init_db.py --drop
python init_db.py --admin --password admin123
```

### 7. Apply Migrations

```bash
flask db upgrade
```

Notes:
- Migrations are idempotent on PostgreSQL; duplicate columns/indexes are guarded
- The app requires PostgreSQL; SQLite is only used in tests

### 8. Start Services

Start Redis:

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

Start the web application:

```bash
python main.py
```

In another terminal, start Celery worker (optional):

```bash
celery -A app.tasks.celery_app worker -Q celery --loglevel=info
```

Visit http://localhost:5000 and log in with the admin credentials.

## Configuration Reference

See [CONFIGURATION.MD](CONFIGURATION.MD) for detailed environment variable documentation.
