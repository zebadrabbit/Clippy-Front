#!/usr/bin/env bash
#
# deploy_update.sh - Deploy code updates to ClippyFront production server
#
# Usage:
#   Local:  ./deploy_update.sh [--restart-workers]
#   Remote: ./deploy_update.sh --remote <host> [--user <user>] [--restart-workers]
#
# This script:
#   1. Syncs code from source to production directory
#   2. Installs/updates Python dependencies
#   3. Runs database migrations
#   4. Restarts Gunicorn (and optionally Celery workers)
#

set -euo pipefail

# ==================== Configuration ====================

APP_NAME="${APP_NAME:-clippyfront}"
APP_DIR="${APP_DIR:-/opt/clippyfront}"
SOURCE_DIR="${SOURCE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/venv}"

RESTART_WORKERS="${RESTART_WORKERS:-false}"
REMOTE_HOST=""
REMOTE_USER="root"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"
SKIP_DEPS="${SKIP_DEPS:-false}"

# ==================== Helper Functions ====================

log_info() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $*"
}

log_error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

log_warn() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [WARN] $*"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# ==================== Deployment Functions ====================

sync_code() {
    log_info "Syncing code from $SOURCE_DIR to $APP_DIR..."

    # Ensure source directory exists
    if [[ ! -d "$SOURCE_DIR" ]]; then
        log_error "Source directory not found: $SOURCE_DIR"
        exit 1
    fi

    # Sync application code (exclude instance data, venv, cache)
    rsync -av --delete \
        --exclude '.git/' \
        --exclude 'venv/' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude '.pytest_cache/' \
        --exclude 'instance/' \
        --exclude '.env' \
        --exclude 'tmp/' \
        --exclude 'logs/' \
        --exclude 'data/' \
        "$SOURCE_DIR/" "$APP_DIR/"

    log_info "Code sync complete"
}

update_dependencies() {
    if [[ "$SKIP_DEPS" == "true" ]]; then
        log_info "Skipping dependency updates (--skip-deps)"
        return 0
    fi

    log_info "Updating Python dependencies..."

    cd "$APP_DIR"

    # Activate virtual environment
    source "$VENV_DIR/bin/activate"

    # Upgrade pip
    python -m pip install --upgrade pip -q

    # Install/update dependencies
    pip install -r requirements.txt -q

    log_info "Dependencies updated"
}

run_migrations() {
    if [[ "$RUN_MIGRATIONS" != "true" ]]; then
        log_info "Skipping database migrations (--skip-migrations)"
        return 0
    fi

    log_info "Running database migrations..."

    cd "$APP_DIR"
    source "$VENV_DIR/bin/activate"

    # Check if Flask-Migrate is configured
    if [[ -d "migrations" ]]; then
        flask db upgrade || {
            log_warn "Migration failed or no migrations to run"
        }
    else
        log_warn "No migrations directory found, skipping"
    fi

    log_info "Database migrations complete"
}

restart_services() {
    log_info "Restarting application services..."

    # Restart Gunicorn
    if systemctl is-active --quiet "gunicorn-${APP_NAME}.service"; then
        systemctl restart "gunicorn-${APP_NAME}.service"
        log_info "Gunicorn restarted"
    else
        log_warn "Gunicorn service not running, starting..."
        systemctl start "gunicorn-${APP_NAME}.service"
    fi

    # Restart Celery workers if requested
    if [[ "$RESTART_WORKERS" == "true" ]]; then
        if systemctl is-active --quiet "celery-worker@${APP_NAME}.service" 2>/dev/null; then
            systemctl restart "celery-worker@${APP_NAME}.service"
            log_info "Celery workers restarted"
        elif pgrep -f "celery.*worker" >/dev/null; then
            log_warn "Celery workers running but not managed by systemd"
            log_warn "Please restart manually: sudo systemctl restart celery-worker"
        else
            log_info "No Celery workers to restart"
        fi
    fi

    # Reload Nginx (no restart needed, just reload config)
    if systemctl is-active --quiet nginx; then
        systemctl reload nginx
        log_info "Nginx configuration reloaded"
    fi
}

verify_deployment() {
    log_info "Verifying deployment..."

    # Check Gunicorn is running
    if ! systemctl is-active --quiet "gunicorn-${APP_NAME}.service"; then
        log_error "Gunicorn failed to start!"
        systemctl status "gunicorn-${APP_NAME}.service" --no-pager
        return 1
    fi

    # Check application responds
    sleep 2
    if curl -sf http://localhost:8000/health >/dev/null 2>&1 || \
       curl -sf http://localhost:8001/health >/dev/null 2>&1; then
        log_info "Application health check: OK"
    else
        log_warn "Health check endpoint not responding (this may be expected)"
    fi

    log_info "Deployment verification complete"
}

# ==================== Remote Execution ====================

execute_remotely() {
    log_info "Deploying to remote host: $REMOTE_HOST"

    # Copy this script to remote
    scp "$0" "${REMOTE_USER}@${REMOTE_HOST}:/tmp/deploy_update.sh"

    # Copy source code to remote
    log_info "Syncing code to remote host..."
    rsync -avz --delete \
        --exclude '.git/' \
        --exclude 'venv/' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude 'instance/' \
        "${REMOTE_USER}@${REMOTE_HOST}:${SOURCE_DIR}/" "${SOURCE_DIR}/"

    # Execute deployment on remote
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "bash /tmp/deploy_update.sh \
        --source-dir '$SOURCE_DIR' \
        --app-dir '$APP_DIR' \
        $([ "$RESTART_WORKERS" == "true" ] && echo "--restart-workers") \
        $([ "$SKIP_DEPS" == "true" ] && echo "--skip-deps") \
        $([ "$RUN_MIGRATIONS" != "true" ] && echo "--skip-migrations")"

    log_info "Remote deployment complete"
}

# ==================== Main Execution ====================

main() {
    log_info "Starting deployment update..."
    log_info "Source: $SOURCE_DIR"
    log_info "Target: $APP_DIR"

    check_root

    # Create backup of current code
    if [[ -d "$APP_DIR" ]]; then
        backup_dir="${APP_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
        log_info "Creating backup: $backup_dir"
        cp -r "$APP_DIR" "$backup_dir"
    fi

    sync_code
    update_dependencies
    run_migrations
    restart_services
    verify_deployment

    log_info "======================================"
    log_info "Deployment update complete!"
    log_info "======================================"
    echo
    log_info "Application: $APP_NAME"
    log_info "Directory: $APP_DIR"
    echo
    log_info "Service status:"
    systemctl status "gunicorn-${APP_NAME}.service" --no-pager | head -5
    echo
    log_info "View logs:"
    log_info "  sudo journalctl -u gunicorn-${APP_NAME} -f"
    if [[ "$RESTART_WORKERS" == "true" ]]; then
        log_info "  sudo journalctl -u celery-worker -f"
    fi
}

# ==================== CLI Argument Parsing ====================

while [[ $# -gt 0 ]]; do
    case $1 in
        --remote)
            REMOTE_HOST="$2"
            shift 2
            ;;
        --user)
            REMOTE_USER="$2"
            shift 2
            ;;
        --source-dir)
            SOURCE_DIR="$2"
            shift 2
            ;;
        --app-dir)
            APP_DIR="$2"
            shift 2
            ;;
        --restart-workers)
            RESTART_WORKERS=true
            shift
            ;;
        --skip-deps)
            SKIP_DEPS=true
            shift
            ;;
        --skip-migrations)
            RUN_MIGRATIONS=false
            shift
            ;;
        --help)
            cat <<'HELP'
Usage: deploy_update.sh [OPTIONS]

Deploy code updates to ClippyFront production server.

OPTIONS:
  --remote <host>          Deploy to remote host via SSH
  --user <username>        Remote SSH user (default: root)
  --source-dir <path>      Source code directory (default: script parent dir)
  --app-dir <path>         Application directory (default: /opt/clippyfront)
  --restart-workers        Also restart Celery workers
  --skip-deps              Skip Python dependency updates
  --skip-migrations        Skip database migrations
  --help                   Show this help message

EXAMPLES:

  # Local deployment
  sudo ./deploy_update.sh

  # Local with worker restart
  sudo ./deploy_update.sh --restart-workers

  # Remote deployment
  ./deploy_update.sh --remote server.example.com --user deploy

  # Quick code-only update (no deps or migrations)
  sudo ./deploy_update.sh --skip-deps --skip-migrations

  # Deploy from specific source
  sudo ./deploy_update.sh --source-dir /home/winter/work/ClippyFront

NOTES:
  • This script is idempotent - safe to run multiple times
  • Creates automatic backup before deployment
  • Backs up to: /opt/clippyfront_backup_YYYYMMDD_HHMMSS
  • Uses rsync to efficiently sync only changed files
  • Preserves instance/ directory (database, uploads, logs)

HELP
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Execute main or remotely
if [[ -n "$REMOTE_HOST" ]]; then
    execute_remotely
else
    main
fi
