#!/usr/bin/env bash
#
# setup_webserver.sh - Install and configure Nginx + Gunicorn for ClippyFront
#
# Usage:
#   Local:  ./setup_webserver.sh
#   Remote: ./setup_webserver.sh --remote <host> [--user <username>]
#
# This script is idempotent - safe to run multiple times to update configuration.
#

set -euo pipefail

# ==================== Configuration ====================

# Application settings
APP_NAME="${APP_NAME:-clippyfront}"
APP_USER="${APP_USER:-clippyfront}"
APP_GROUP="${APP_GROUP:-clippyfront}"
APP_DIR="${APP_DIR:-/opt/clippyfront}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/venv}"
INSTANCE_DIR="${INSTANCE_DIR:-${APP_DIR}/instance}"

# Gunicorn settings
GUNICORN_WORKERS="${GUNICORN_WORKERS:-4}"
GUNICORN_THREADS="${GUNICORN_THREADS:-2}"
GUNICORN_BIND="${GUNICORN_BIND:-127.0.0.1:8000}"  # Default production port
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"
GUNICORN_MAX_REQUESTS="${GUNICORN_MAX_REQUESTS:-1000}"
GUNICORN_MAX_REQUESTS_JITTER="${GUNICORN_MAX_REQUESTS_JITTER:-50}"

# Nginx settings
NGINX_PORT="${NGINX_PORT:-80}"
NGINX_SSL_PORT="${NGINX_SSL_PORT:-443}"
SERVER_NAME="${SERVER_NAME:-_}"  # Default to catch-all
ENABLE_SSL="${ENABLE_SSL:-false}"
USE_LETSENCRYPT="${USE_LETSENCRYPT:-false}"
SSL_EMAIL="${SSL_EMAIL:-}"
SSL_CONFIGURED_VIA_FLAGS="${SSL_CONFIGURED_VIA_FLAGS:-false}"
SSL_CERT_PATH="${SSL_CERT_PATH:-/etc/ssl/certs/clippyfront.crt}"
SSL_KEY_PATH="${SSL_KEY_PATH:-/etc/ssl/private/clippyfront.key}"
CLIENT_MAX_BODY_SIZE="${CLIENT_MAX_BODY_SIZE:-2G}"  # For large video uploads

# Security settings
ENABLE_RATE_LIMITING="${ENABLE_RATE_LIMITING:-true}"
RATE_LIMIT="${RATE_LIMIT:-10r/s}"  # Requests per second
RATE_LIMIT_BURST="${RATE_LIMIT_BURST:-20}"

# Remote execution
REMOTE_HOST=""
REMOTE_USER="root"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ==================== Helper Functions ====================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

check_root() {
    if [[ $EUID -ne 0 && -z "$REMOTE_HOST" ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

check_port_available() {
    local bind_addr="$1"
    local port="${bind_addr##*:}"

    if lsof -i ":$port" -P -n >/dev/null 2>&1; then
        log_error "Port $port is already in use:"
        lsof -i ":$port" -P -n | head -5
        log_error "Please stop the service using this port or change GUNICORN_BIND"
        log_error "Current processes using port $port:"
        lsof -i ":$port" -P -n | tail -n +2 | awk '{print "  " $1 " (PID: " $2 ", User: " $3 ")"}'
        return 1
    fi
    log_info "Port $port is available"
    return 0
}

detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$ID
        OS_VERSION=$VERSION_ID
        log_info "Detected OS: $OS $OS_VERSION"
    else
        log_error "Cannot detect OS"
        exit 1
    fi
}

# ==================== System Dependencies ====================

install_system_packages() {
    log_info "Installing system packages..."

    case "$OS" in
        ubuntu|debian)
            apt-get update -qq
            apt-get install -y -qq \
                nginx \
                python3 \
                python3-pip \
                python3-venv \
                python3-dev \
                build-essential \
                libpq-dev \
                redis-server \
                postgresql-client \
                supervisor \
                curl \
                wget \
                git
            ;;
        centos|rhel|rocky|almalinux)
            yum install -y -q \
                nginx \
                python3 \
                python3-pip \
                python3-devel \
                gcc \
                gcc-c++ \
                make \
                postgresql-devel \
                redis \
                supervisor \
                curl \
                wget \
                git
            ;;
        *)
            log_error "Unsupported OS: $OS"
            exit 1
            ;;
    esac

    log_info "System packages installed"
}

# ==================== Application Setup ====================

create_app_user() {
    if ! id "$APP_USER" &>/dev/null; then
        log_info "Creating application user: $APP_USER"
        useradd --system --create-home --shell /bin/bash "$APP_USER"
    else
        log_info "User $APP_USER already exists"
    fi
}

setup_app_directory() {
    log_info "Setting up application directory: $APP_DIR"

    # Create directories
    mkdir -p "$APP_DIR"
    mkdir -p "$INSTANCE_DIR"/{data,logs,uploads,tmp}

    # Set ownership
    chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
    chmod 755 "$APP_DIR"

    # Secure instance directory
    chmod 750 "$INSTANCE_DIR"
    chmod 770 "$INSTANCE_DIR"/{data,logs,uploads,tmp}

    log_info "Application directories created"
}

setup_python_virtualenv() {
    log_info "Setting up Python virtual environment..."

    if [[ ! -d "$VENV_DIR" ]]; then
        sudo -u "$APP_USER" python3 -m venv "$VENV_DIR"
        log_info "Virtual environment created"
    else
        log_info "Virtual environment already exists"
    fi

    # Upgrade pip
    sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip setuptools wheel

    # Install gunicorn
    sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet gunicorn gevent

    log_info "Python virtual environment ready"
}

install_app_dependencies() {
    if [[ -f "$APP_DIR/requirements.txt" ]]; then
        log_info "Installing application dependencies..."
        sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
        log_info "Application dependencies installed"
    else
        log_warn "No requirements.txt found at $APP_DIR/requirements.txt"
        log_warn "Please copy your application code and run this script again"
    fi
}

setup_production_env() {
    log_info "Setting up production .env file..."

    local env_file="$APP_DIR/.env"

    if [[ -f "$env_file" ]]; then
        log_warn "Existing .env file found at $env_file"
        log_warn "Updating critical production settings..."

        # Update instance path to production directory
        if grep -q '^CLIPPY_INSTANCE_PATH=' "$env_file"; then
            sudo sed -i "s|^CLIPPY_INSTANCE_PATH=.*|CLIPPY_INSTANCE_PATH=$INSTANCE_DIR|" "$env_file"
            log_info "Updated CLIPPY_INSTANCE_PATH to $INSTANCE_DIR"
        else
            echo "CLIPPY_INSTANCE_PATH=$INSTANCE_DIR" | sudo tee -a "$env_file" >/dev/null
            log_info "Added CLIPPY_INSTANCE_PATH=$INSTANCE_DIR"
        fi

        # Set table prefix for production (opt_ by default)
        local table_prefix="${TABLE_PREFIX:-opt_}"
        if grep -q '^TABLE_PREFIX=' "$env_file"; then
            sudo sed -i "s|^TABLE_PREFIX=.*|TABLE_PREFIX=$table_prefix|" "$env_file"
            log_info "Updated TABLE_PREFIX to $table_prefix"
        else
            echo "TABLE_PREFIX=$table_prefix" | sudo tee -a "$env_file" >/dev/null
            log_info "Added TABLE_PREFIX=$table_prefix"
        fi

        # Ensure FLASK_APP_URL is set (required for worker communication)
        if ! grep -q '^FLASK_APP_URL=' "$env_file"; then
            local flask_url="http://127.0.0.1:${GUNICORN_BIND##*:}"
            echo "FLASK_APP_URL=$flask_url" | sudo tee -a "$env_file" >/dev/null
            log_info "Added FLASK_APP_URL=$flask_url"
        fi

        # Ensure MEDIA_BASE_URL is set
        if ! grep -q '^MEDIA_BASE_URL=' "$env_file"; then
            local media_url="http://127.0.0.1:${GUNICORN_BIND##*:}"
            echo "MEDIA_BASE_URL=$media_url" | sudo tee -a "$env_file" >/dev/null
            log_info "Added MEDIA_BASE_URL=$media_url"
        fi

    else
        log_info "Creating new production .env file..."
        log_warn "This is a minimal configuration - review and update as needed"

        cat | sudo tee "$env_file" >/dev/null <<ENV_TEMPLATE
# ClippyFront Production Configuration
# Auto-generated by setup_webserver.sh
# Review and update as needed

# Application
FLASK_ENV=production
FLASK_DEBUG=False
SECRET_KEY=$(openssl rand -hex 32)

# Instance paths
CLIPPY_INSTANCE_PATH=$INSTANCE_DIR

# Database
TABLE_PREFIX=${TABLE_PREFIX:-opt_}
DATABASE_URL=postgresql://clippyfront:CHANGEME@localhost/clippyfront

# Redis
REDIS_URL=redis://localhost:6379/1
REDIS_DB=1

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Server URLs (update after nginx is configured)
FLASK_APP_URL=http://127.0.0.1:${GUNICORN_BIND##*:}
MEDIA_BASE_URL=http://127.0.0.1:${GUNICORN_BIND##*:}

# Worker API
WORKER_API_KEY=$(openssl rand -base64 32)

# File paths
UPLOAD_FOLDER=$INSTANCE_DIR/uploads
DATA_FOLDER=$INSTANCE_DIR/data

ENV_TEMPLATE

        log_info "Created .env file at $env_file"
    fi

    # Set ownership and permissions
    sudo chown "$APP_USER:$APP_GROUP" "$env_file"
    sudo chmod 640 "$env_file"

    log_info "Production environment file configured"
    log_warn "IMPORTANT: Review $env_file and update:"
    log_warn "  - DATABASE_URL with actual credentials"
    log_warn "  - SECRET_KEY if not auto-generated"
    log_warn "  - FLASK_APP_URL and MEDIA_BASE_URL after SSL/domain setup"
    log_warn "  - WORKER_API_KEY must match remote worker configuration"
}

# ==================== Gunicorn Configuration ====================

create_gunicorn_config() {
    log_info "Creating Gunicorn configuration..."

    local config_file="$APP_DIR/gunicorn.conf.py"

    cat > "$config_file" <<EOF
# Gunicorn configuration file
# Generated by setup_webserver.sh

import multiprocessing
import os

# Server socket
bind = "$GUNICORN_BIND"
backlog = 2048

# Worker processes
workers = $GUNICORN_WORKERS
worker_class = "gevent"  # Async workers for better concurrency
worker_connections = 1000
threads = $GUNICORN_THREADS
timeout = $GUNICORN_TIMEOUT
keepalive = 5

# Worker restart
max_requests = $GUNICORN_MAX_REQUESTS
max_requests_jitter = $GUNICORN_MAX_REQUESTS_JITTER

# Logging
accesslog = "$INSTANCE_DIR/logs/gunicorn-access.log"
errorlog = "$INSTANCE_DIR/logs/gunicorn-error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "$APP_NAME"

# Server mechanics
daemon = False
pidfile = "$INSTANCE_DIR/gunicorn.pid"
umask = 0o007
user = "$APP_USER"
group = "$APP_GROUP"
tmp_upload_dir = "$INSTANCE_DIR/tmp"

# SSL (if needed behind nginx, usually not required)
# keyfile = None
# certfile = None

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# Server hooks
def on_starting(server):
    """Called just before the master process is initialized."""
    pass

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    pass

def when_ready(server):
    """Called just after the server is started."""
    pass

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    pass

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    pass

def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    pass
EOF

    chown "$APP_USER:$APP_GROUP" "$config_file"
    log_info "Gunicorn configuration written to $config_file"
}

create_gunicorn_systemd() {
    log_info "Creating Gunicorn systemd service..."

    cat > /etc/systemd/system/gunicorn-${APP_NAME}.service <<EOF
[Unit]
Description=Gunicorn daemon for $APP_NAME
After=network.target

[Service]
Type=notify
User=$APP_USER
Group=$APP_GROUP
RuntimeDirectory=gunicorn
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin"
ExecStart=$VENV_DIR/bin/gunicorn \\
    --config $APP_DIR/gunicorn.conf.py \\
    main:app
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=30
PrivateTmp=true
Restart=always
RestartSec=5

# Security hardening
NoNewPrivileges=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTANCE_DIR

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable gunicorn-${APP_NAME}.service

    log_info "Gunicorn systemd service created"
}

start_gunicorn() {
    log_info "Starting Gunicorn..."

    # Extract port from GUNICORN_BIND (format: host:port or port)
    local bind_port
    if [[ "$GUNICORN_BIND" =~ :([0-9]+)$ ]]; then
        bind_port="${BASH_REMATCH[1]}"
    else
        bind_port="$GUNICORN_BIND"
    fi

    # Check if Gunicorn service is already running
    if systemctl is-active --quiet gunicorn-${APP_NAME}.service; then
        log_info "Gunicorn service already running, restarting..."
        systemctl restart gunicorn-${APP_NAME}.service || {
            log_error "Failed to restart Gunicorn. Check logs:"
            log_error "  journalctl -u gunicorn-${APP_NAME}.service -n 50"
            log_error "  cat $INSTANCE_DIR/logs/gunicorn-error.log"
            return 1
        }
    else
        # Service not running, check if port is in use by something else
        if ! check_port_available "$GUNICORN_BIND"; then
            log_error "Cannot start Gunicorn - port $bind_port is in use by another process"
            log_error "Please stop the service using this port or change GUNICORN_BIND"
            return 1
        fi

        systemctl enable gunicorn-${APP_NAME}.service
        systemctl start gunicorn-${APP_NAME}.service || {
            log_error "Failed to start Gunicorn. Check logs:"
            log_error "  journalctl -u gunicorn-${APP_NAME}.service -n 50"
            log_error "  cat $INSTANCE_DIR/logs/gunicorn-error.log"
            return 1
        }
    fi

    sleep 2

    if systemctl is-active --quiet gunicorn-${APP_NAME}.service; then
        log_info "Gunicorn service started successfully"
    else
        log_error "Gunicorn service failed to start"
        journalctl -u gunicorn-${APP_NAME}.service -n 20 --no-pager
        return 1
    fi
}

# ==================== Nginx Configuration ====================

configure_nginx() {
    log_info "Configuring Nginx..."

    local nginx_config="/etc/nginx/sites-available/${APP_NAME}"
    local nginx_enabled="/etc/nginx/sites-enabled/${APP_NAME}"

    # Create sites-available directory if it doesn't exist (CentOS/RHEL)
    mkdir -p /etc/nginx/sites-available
    mkdir -p /etc/nginx/sites-enabled

    # Ensure nginx.conf includes sites-enabled
    if ! grep -q "sites-enabled" /etc/nginx/nginx.conf; then
        sed -i '/http {/a \    include /etc/nginx/sites-enabled/*;' /etc/nginx/nginx.conf
    fi

    # Create Nginx configuration
    cat > "$nginx_config" <<EOF
# Nginx configuration for $APP_NAME
# Generated by setup_webserver.sh

# Rate limiting zones
$(if [[ "$ENABLE_RATE_LIMITING" == "true" ]]; then
    echo "limit_req_zone \$binary_remote_addr zone=${APP_NAME}_limit:10m rate=${RATE_LIMIT};"
    echo "limit_req_status 429;"
fi)

# Upstream Gunicorn
upstream ${APP_NAME}_app {
    server $GUNICORN_BIND fail_timeout=0;
}

# HTTP Server
server {
    listen $NGINX_PORT;
    listen [::]:$NGINX_PORT;
    server_name $SERVER_NAME;

$(if [[ "$ENABLE_SSL" == "true" ]]; then
    cat <<SSL_BLOCK
    # Redirect to HTTPS
    return 301 https://\$server_name\$request_uri;
}

# HTTPS Server
server {
    listen $NGINX_SSL_PORT ssl http2;
    listen [::]:$NGINX_SSL_PORT ssl http2;
    server_name $SERVER_NAME;

    # SSL certificates
    ssl_certificate $SSL_CERT_PATH;
    ssl_certificate_key $SSL_KEY_PATH;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
SSL_BLOCK
fi)

    # Client settings
    client_max_body_size $CLIENT_MAX_BODY_SIZE;
    client_body_buffer_size 128k;
    client_body_timeout 120s;

    # Timeouts
    proxy_connect_timeout 120s;
    proxy_send_timeout 120s;
    proxy_read_timeout 120s;
    send_timeout 120s;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Logging
    access_log $INSTANCE_DIR/logs/nginx-access.log combined;
    error_log $INSTANCE_DIR/logs/nginx-error.log warn;

    # Root location
    location / {
$(if [[ "$ENABLE_RATE_LIMITING" == "true" ]]; then
    echo "        limit_req zone=${APP_NAME}_limit burst=$RATE_LIMIT_BURST nodelay;"
fi)
        proxy_pass http://${APP_NAME}_app;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;

        # WebSocket support (for SSE/notifications)
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Buffering
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # Static files (if served separately)
    location /static {
        alias $APP_DIR/app/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Media files (uploads, videos)
    location /instance/data {
        internal;  # Only accessible via X-Accel-Redirect
        alias $INSTANCE_DIR/data;
    }

    # Health check endpoint
    location /health {
        access_log off;
        proxy_pass http://${APP_NAME}_app/health;
    }

    # Deny access to sensitive files
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    location ~ ~\$ {
        deny all;
        access_log off;
        log_not_found off;
    }
}
EOF

    # Enable site
    ln -sf "$nginx_config" "$nginx_enabled"

    # Remove default site if it exists
    if [[ -f /etc/nginx/sites-enabled/default ]]; then
        rm -f /etc/nginx/sites-enabled/default
        log_info "Removed default Nginx site"
    fi

    log_info "Nginx configuration written to $nginx_config"
}

test_nginx_config() {
    log_info "Testing Nginx configuration..."

    if nginx -t; then
        log_info "Nginx configuration is valid"
        return 0
    else
        log_error "Nginx configuration test failed"
        return 1
    fi
}

start_nginx() {
    log_info "Starting Nginx..."

    systemctl enable nginx
    systemctl restart nginx || {
        log_error "Failed to start Nginx. Check configuration:"
        log_error "  nginx -t"
        return 1
    }

    if systemctl is-active --quiet nginx; then
        log_info "Nginx service started successfully"
    else
        log_error "Nginx service failed to start"
        journalctl -u nginx -n 20 --no-pager
        return 1
    fi
}

# ==================== Firewall Configuration ====================

configure_firewall() {
    log_info "Configuring firewall rules..."

    if command -v ufw &>/dev/null; then
        # UFW (Ubuntu/Debian)
        ufw allow "$NGINX_PORT/tcp" comment "Nginx HTTP"
        if [[ "$ENABLE_SSL" == "true" ]]; then
            ufw allow "$NGINX_SSL_PORT/tcp" comment "Nginx HTTPS"
        fi
        log_info "UFW rules added"
    elif command -v firewall-cmd &>/dev/null; then
        # firewalld (RHEL/CentOS)
        firewall-cmd --permanent --add-service=http
        if [[ "$ENABLE_SSL" == "true" ]]; then
            firewall-cmd --permanent --add-service=https
        fi
        firewall-cmd --reload
        log_info "firewalld rules added"
    else
        log_warn "No supported firewall found. Please configure manually."
    fi
}

# ==================== SSL Certificate Renewal ====================

setup_ssl_renewal_script() {
    log_info "Setting up SSL certificate renewal monitoring..."

    local renewal_script="/usr/local/bin/renew_${APP_NAME}_ssl.sh"

    cat > "$renewal_script" <<'RENEWAL_SCRIPT'
#!/usr/bin/env bash
#
# SSL Certificate Renewal Check Script
# Auto-generated by setup_webserver.sh
#

set -euo pipefail

DOMAIN="${1:-__DOMAIN__}"
CERT_PATH="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
LOG_FILE="/var/log/letsencrypt/renewal-check.log"
DAYS_BEFORE_EXPIRY=__RENEWAL_DAYS__
NOTIFY_EMAIL="__NOTIFY_EMAIL__"

# Logging functions
log_info() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE"
}

log_warn() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [WARN] $*" | tee -a "$LOG_FILE"
}

# Check if certificate exists
if [[ ! -f "$CERT_PATH" ]]; then
    log_error "Certificate not found at $CERT_PATH"
    exit 1
fi

# Check certificate expiration
expiry_date=$(openssl x509 -enddate -noout -in "$CERT_PATH" | cut -d= -f2)
expiry_epoch=$(date -d "$expiry_date" +%s)
current_epoch=$(date +%s)
days_until_expiry=$(( ($expiry_epoch - $current_epoch) / 86400 ))

log_info "Certificate for $DOMAIN expires in $days_until_expiry days"

# Check if renewal is needed
if [[ $days_until_expiry -gt $DAYS_BEFORE_EXPIRY ]]; then
    log_info "Certificate is still valid for $days_until_expiry days. No renewal needed."
    exit 0
fi

log_warn "Certificate expires in $days_until_expiry days. Renewal recommended!"
log_warn "Manual DNS challenge renewal required:"
log_warn "  1. Run: sudo certbot certonly --manual --preferred-challenges dns -d $DOMAIN"
log_warn "  2. Add the TXT record to DNS as shown by certbot"
log_warn "  3. Complete the challenge"
log_warn "  4. Nginx will automatically use the new certificate"

# Send email notification if mail is configured
if command -v mail &>/dev/null && [[ -n "$NOTIFY_EMAIL" ]]; then
    {
        echo "Subject: SSL Certificate Renewal Required for $DOMAIN"
        echo
        echo "The SSL certificate for $DOMAIN will expire in $days_until_expiry days."
        echo
        echo "To renew:"
        echo "  1. SSH to the server"
        echo "  2. Run: sudo certbot certonly --manual --preferred-challenges dns -d $DOMAIN"
        echo "  3. Add the DNS TXT record shown by certbot"
        echo "  4. Complete the challenge"
        echo
        echo "After renewal, update Nginx configuration if needed:"
        echo "  sudo sed -i 's|ssl_certificate .*;|ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;|' /etc/nginx/sites-available/__APP_NAME__"
        echo "  sudo sed -i 's|ssl_certificate_key .*;|ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;|' /etc/nginx/sites-available/__APP_NAME__"
        echo "  sudo nginx -t && sudo systemctl reload nginx"
        echo
        echo "Certificate details:"
        echo "  Domain: $DOMAIN"
        echo "  Expires: $expiry_date"
        echo "  Days remaining: $days_until_expiry"
    } | mail -s "SSL Certificate Renewal Required: $DOMAIN" "$NOTIFY_EMAIL"
    log_info "Notification email sent to $NOTIFY_EMAIL"
fi

exit 0
RENEWAL_SCRIPT

    # Substitute placeholders
    sed -i "s|__DOMAIN__|$SERVER_NAME|g" "$renewal_script"
    sed -i "s|__RENEWAL_DAYS__|$SSL_RENEWAL_DAYS|g" "$renewal_script"
    sed -i "s|__NOTIFY_EMAIL__|$SSL_RENEWAL_EMAIL|g" "$renewal_script"
    sed -i "s|__APP_NAME__|$APP_NAME|g" "$renewal_script"

    chmod +x "$renewal_script"

    log_info "SSL renewal script installed at $renewal_script"
}

setup_ssl_renewal_cron() {
    if [[ "$SSL_RENEWAL_CRON" != "true" ]]; then
        log_info "SSL renewal cron disabled, skipping"
        return 0
    fi

    log_info "Setting up SSL certificate renewal cron job..."

    local cron_file="/etc/cron.d/renew-${APP_NAME}-ssl"

    cat > "$cron_file" <<EOF
# SSL Certificate Renewal Check for ${APP_NAME}
# Auto-generated by setup_webserver.sh
# Runs every Monday at 3 AM
0 3 * * 1 root /usr/local/bin/renew_${APP_NAME}_ssl.sh $SERVER_NAME
EOF

    chmod 644 "$cron_file"

    log_info "SSL renewal cron job installed at $cron_file"
    log_info "Certificate expiry will be checked weekly (Mondays at 3 AM)"
    log_info "Notifications will be sent to: $SSL_RENEWAL_EMAIL"
}

# ==================== SSL Certificate ====================

# ==================== SSL Certificate ====================

install_certbot() {
    log_info "Installing Certbot..."

    case "$OS" in
        ubuntu|debian)
            apt-get install -y -qq certbot python3-certbot-nginx
            ;;
        centos|rhel|rocky|almalinux)
            yum install -y -q certbot python3-certbot-nginx
            ;;
        *)
            log_error "Unsupported OS for Certbot installation: $OS"
            return 1
            ;;
    esac

    log_info "Certbot installed successfully"
}

setup_letsencrypt_ssl() {
    local domain="$1"
    local email="$2"

    log_info "Setting up Let's Encrypt SSL for $domain..."

    # Validate inputs
    if [[ -z "$domain" ]] || [[ "$domain" == "_" ]]; then
        log_error "A valid domain name is required for Let's Encrypt"
        log_error "Cannot use '_' or empty domain for SSL certificates"
        return 1
    fi

    if [[ -z "$email" ]]; then
        log_error "An email address is required for Let's Encrypt"
        return 1
    fi

    # Make sure Nginx is running
    if ! systemctl is-active --quiet nginx; then
        log_info "Starting Nginx for certificate verification..."
        systemctl start nginx || {
            log_error "Failed to start Nginx"
            return 1
        }
    fi

    # Run certbot
    log_info "Running Certbot to obtain SSL certificate..."
    certbot --nginx \
        -d "$domain" \
        --non-interactive \
        --agree-tos \
        --email "$email" \
        --redirect || {
        log_error "Certbot failed to obtain certificate"
        log_error "Please check:"
        log_error "  1. Domain $domain points to this server's IP"
        log_error "  2. Port 80 is accessible from the internet"
        log_error "  3. No firewall is blocking HTTP/HTTPS traffic"
        return 1
    }

    # Setup auto-renewal
    log_info "Setting up automatic certificate renewal..."

    # Test renewal process
    certbot renew --dry-run || {
        log_warn "Dry-run renewal test failed, but certificate was issued"
    }

    # Ensure certbot timer is enabled
    systemctl enable certbot.timer 2>/dev/null || true
    systemctl start certbot.timer 2>/dev/null || true

    log_info "SSL certificate installed successfully!"
    log_info "Certificate auto-renewal is configured"

    return 0
}

setup_ssl_certificate() {
    if [[ "$ENABLE_SSL" == "true" ]]; then
        if [[ "$USE_LETSENCRYPT" == "true" ]]; then
            # Let's Encrypt setup
            if [[ -z "$SSL_EMAIL" ]]; then
                log_error "SSL_EMAIL is required for Let's Encrypt"
                return 1
            fi

            if [[ "$SERVER_NAME" == "_" ]]; then
                log_error "A valid domain name (SERVER_NAME) is required for Let's Encrypt"
                log_error "Cannot use catch-all '_' with Let's Encrypt"
                return 1
            fi

            install_certbot
            setup_letsencrypt_ssl "$SERVER_NAME" "$SSL_EMAIL"

        else
            # Self-signed certificate setup
            if [[ ! -f "$SSL_CERT_PATH" ]] || [[ ! -f "$SSL_KEY_PATH" ]]; then
                log_warn "SSL enabled but certificates not found"
                log_info "Generating self-signed certificate for testing..."

                mkdir -p "$(dirname "$SSL_CERT_PATH")"
                mkdir -p "$(dirname "$SSL_KEY_PATH")"

                openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
                    -keyout "$SSL_KEY_PATH" \
                    -out "$SSL_CERT_PATH" \
                    -subj "/C=US/ST=State/L=City/O=Organization/CN=$SERVER_NAME"

                # Set proper permissions for Nginx to read the key
                chmod 640 "$SSL_KEY_PATH"
                chmod 644 "$SSL_CERT_PATH"
                chgrp ssl-cert "$SSL_KEY_PATH" 2>/dev/null || true

                # Ensure www-data user can read SSL certificates
                usermod -aG ssl-cert www-data 2>/dev/null || true

                log_warn "Self-signed certificate created at $SSL_CERT_PATH"
                log_warn "For production, use Let's Encrypt:"
                log_warn "  Run this script with --enable-ssl --use-letsencrypt"
                log_warn "  Or manually: sudo certbot --nginx -d $SERVER_NAME"
            else
                log_info "SSL certificates found at $SSL_CERT_PATH"

                # Ensure permissions are correct even for existing certs
                chmod 640 "$SSL_KEY_PATH" 2>/dev/null || true
                chmod 644 "$SSL_CERT_PATH" 2>/dev/null || true
                chgrp ssl-cert "$SSL_KEY_PATH" 2>/dev/null || true
                usermod -aG ssl-cert www-data 2>/dev/null || true
            fi
        fi
    fi
}

prompt_ssl_setup() {
    # Skip prompts if running remotely or non-interactively
    if [[ -n "$REMOTE_HOST" ]] || [[ ! -t 0 ]]; then
        return 0
    fi

    # Skip if SSL settings already provided via flags
    if [[ "$SSL_CONFIGURED_VIA_FLAGS" == "true" ]]; then
        return 0
    fi

    echo
    read -p "Do you want to set up HTTPS/SSL? (y/n): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ENABLE_SSL=true

        echo
        read -p "Enter your domain name (e.g., example.com): " domain_input

        if [[ -n "$domain_input" ]] && [[ "$domain_input" != "_" ]]; then
            SERVER_NAME="$domain_input"

            echo
            read -p "Use Let's Encrypt for free SSL certificate? (y/n): " -n 1 -r
            echo

            if [[ $REPLY =~ ^[Yy]$ ]]; then
                USE_LETSENCRYPT=true

                echo
                read -p "Enter your email address for Let's Encrypt: " email_input
                SSL_EMAIL="$email_input"

                log_info "Will set up Let's Encrypt SSL for $SERVER_NAME"
                log_warn "Make sure:"
                log_warn "  1. Domain $SERVER_NAME points to this server's IP"
                log_warn "  2. Port 80 is accessible from the internet"
                log_warn "  3. No firewall is blocking traffic"
                echo
                read -p "Press Enter to continue or Ctrl+C to cancel..."
            else
                log_info "Will generate self-signed certificate for testing"
            fi

            # Ask about automatic renewal monitoring
            echo
            read -p "Set up automatic SSL renewal monitoring? (y/n): " -n 1 -r
            echo

            if [[ $REPLY =~ ^[Yy]$ ]]; then
                SSL_RENEWAL_CRON=true

                echo
                read -p "Email for renewal notifications (default: root): " notify_email_input
                SSL_RENEWAL_EMAIL="${notify_email_input:-root}"

                echo
                read -p "Days before expiry to send warning (default: 30): " renewal_days_input
                SSL_RENEWAL_DAYS="${renewal_days_input:-30}"

                log_info "Renewal monitoring enabled:"
                log_info "  - Weekly checks every Monday at 3 AM"
                log_info "  - Notifications sent to: $SSL_RENEWAL_EMAIL"
                log_info "  - Warning threshold: $SSL_RENEWAL_DAYS days before expiry"
            else
                SSL_RENEWAL_CRON=false
                log_info "SSL renewal monitoring disabled"
            fi
        else
            log_warn "No valid domain provided, SSL will be disabled"
            ENABLE_SSL=false
        fi
    else
        ENABLE_SSL=false
        log_info "Skipping SSL setup (HTTP only)"
    fi
}

# ==================== Monitoring & Logging ====================

setup_log_rotation() {
    log_info "Setting up log rotation..."

    cat > /etc/logrotate.d/${APP_NAME} <<EOF
$INSTANCE_DIR/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 $APP_USER $APP_GROUP
    sharedscripts
    postrotate
        systemctl reload nginx > /dev/null 2>&1 || true
        systemctl reload gunicorn-${APP_NAME}.service > /dev/null 2>&1 || true
    endscript
}
EOF

    log_info "Log rotation configured"
}

# ==================== Remote Execution ====================

execute_remotely() {
    local script_path="$0"
    local remote_args=""

    # Build arguments without --remote flags
    for arg in "$@"; do
        if [[ "$arg" != "--remote" && "$arg" != "$REMOTE_HOST" && "$arg" != "--user" && "$arg" != "$REMOTE_USER" ]]; then
            remote_args="$remote_args $arg"
        fi
    done

    log_info "Executing on remote host: $REMOTE_USER@$REMOTE_HOST"

    # Copy script to remote
    scp "$script_path" "$REMOTE_USER@$REMOTE_HOST:/tmp/setup_webserver.sh"

    # Execute remotely
    ssh "$REMOTE_USER@$REMOTE_HOST" "bash /tmp/setup_webserver.sh $remote_args"

    # Cleanup
    ssh "$REMOTE_USER@$REMOTE_HOST" "rm /tmp/setup_webserver.sh"

    log_info "Remote execution complete"
}

# ==================== Main Installation ====================

main() {
    log_info "Starting web server installation..."
    log_info "Application: $APP_NAME"
    log_info "Install directory: $APP_DIR"

    check_root
    detect_os
    install_system_packages

    # Prompt for SSL setup (interactive)
    prompt_ssl_setup

    # Application setup
    create_app_user
    setup_app_directory
    setup_python_virtualenv
    install_app_dependencies
    setup_production_env

    # Gunicorn setup
    create_gunicorn_config
    create_gunicorn_systemd
    start_gunicorn

    # Nginx setup
    setup_ssl_certificate
    configure_nginx
    test_nginx_config && start_nginx

    # Additional configuration
    configure_firewall
    setup_log_rotation

    # SSL renewal monitoring setup
    if [[ "$ENABLE_SSL" == "true" ]] && [[ "$SSL_RENEWAL_CRON" == "true" ]]; then
        setup_ssl_renewal_script
        setup_ssl_renewal_cron
    fi

    # Summary
    log_info "======================================"
    log_info "Web server installation complete!"
    log_info "======================================"
    echo
    log_info "Application:"
    log_info "  Directory: $APP_DIR"
    log_info "  User: $APP_USER"
    log_info "  Virtual env: $VENV_DIR"
    echo
    log_info "Access URL:"
    if [[ "$ENABLE_SSL" == "true" ]]; then
        log_info "  https://$SERVER_NAME"
    else
        log_info "  http://$SERVER_NAME"
    fi
    echo
    log_info "Service commands:"
    log_info "  sudo systemctl status gunicorn-${APP_NAME}"
    log_info "  sudo systemctl status nginx"
    log_info "  sudo systemctl restart gunicorn-${APP_NAME}"
    log_info "  sudo systemctl restart nginx"
    echo
    log_info "Logs:"
    log_info "  Application: $INSTANCE_DIR/logs/"
    log_info "  Gunicorn: journalctl -u gunicorn-${APP_NAME} -f"
    log_info "  Nginx: journalctl -u nginx -f"
    echo
    log_info "Configuration files:"
    log_info "  Gunicorn: $APP_DIR/gunicorn.conf.py"
    log_info "  Nginx: /etc/nginx/sites-available/${APP_NAME}"
    log_info "  Environment: $APP_DIR/.env"
    if [[ "$ENABLE_SSL" == "true" ]] && [[ "$SSL_RENEWAL_CRON" == "true" ]]; then
        log_info "  SSL Renewal: /usr/local/bin/renew_${APP_NAME}_ssl.sh"
        log_info "  Renewal Cron: /etc/cron.d/renew-${APP_NAME}-ssl"
        log_info "  Renewal Log: /var/log/letsencrypt/renewal-check.log"
    fi
    echo
    log_warn "NEXT STEPS:"
    log_warn "  1. Review and update $APP_DIR/.env with correct values"
    log_warn "  2. Update FLASK_APP_URL and MEDIA_BASE_URL if using domain/SSL"
    log_warn "  3. Ensure DATABASE_URL has correct credentials"
    log_warn "  4. Copy WORKER_API_KEY to remote worker .env file"
    log_warn "  5. Restart services after updating .env:"
    log_warn "     sudo systemctl restart gunicorn-${APP_NAME}"
    echo
    if [[ "$ENABLE_SSL" == "true" ]] && [[ "$SSL_CERT_PATH" == *"self-signed"* ]]; then
        log_warn "Using self-signed SSL certificate. For production:"
        log_warn "  Install certbot and run: sudo certbot --nginx -d $SERVER_NAME"
    fi
    if [[ "$ENABLE_SSL" == "true" ]] && [[ "$SSL_RENEWAL_CRON" == "true" ]]; then
        log_info "SSL renewal monitoring is active:"
        log_info "  - Checks run weekly (Mondays at 3 AM)"
        log_info "  - Notifications sent to: $SSL_RENEWAL_EMAIL when cert expires in ≤$SSL_RENEWAL_DAYS days"
        log_info "  - Manual check: sudo /usr/local/bin/renew_${APP_NAME}_ssl.sh $SERVER_NAME"
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
        --app-dir)
            APP_DIR="$2"
            shift 2
            ;;
        --server-name)
            SERVER_NAME="$2"
            shift 2
            ;;
        --table-prefix)
            TABLE_PREFIX="$2"
            shift 2
            ;;
        --enable-ssl)
            ENABLE_SSL=true
            SSL_CONFIGURED_VIA_FLAGS=true
            shift
            ;;
        --use-letsencrypt)
            USE_LETSENCRYPT=true
            SSL_CONFIGURED_VIA_FLAGS=true
            shift
            ;;
        --ssl-email)
            SSL_EMAIL="$2"
            SSL_CONFIGURED_VIA_FLAGS=true
            shift 2
            ;;
        --ssl-renewal-cron)
            SSL_RENEWAL_CRON="$2"
            shift 2
            ;;
        --ssl-renewal-days)
            SSL_RENEWAL_DAYS="$2"
            shift 2
            ;;
        --ssl-renewal-email)
            SSL_RENEWAL_EMAIL="$2"
            shift 2
            ;;
        --workers)
            GUNICORN_WORKERS="$2"
            shift 2
            ;;
        --bind)
            GUNICORN_BIND="$2"
            shift 2
            ;;
        --help)
            cat <<'HELP'
Usage: setup_webserver.sh [OPTIONS]

Deploy ClippyFront web application with Nginx reverse proxy and Gunicorn WSGI server.
Supports both local and remote installation with comprehensive SSL/TLS configuration.

=== BASIC OPTIONS ===
  --remote <host>              Execute installation on remote host via SSH
  --user <username>            Remote SSH user (default: root)
  --app-dir <path>             Application directory (default: /opt/clippyfront)
  --server-name <domain>       Server domain name (default: _)
                               Use '_' for catch-all or specify domain (e.g., example.com)
  --table-prefix <prefix>      Database table prefix (default: opt_ for production)
                               Set to match your deployment (dev_, opt_, etc.)

=== GUNICORN OPTIONS ===
  --workers <num>              Number of Gunicorn worker processes (default: 4)
                               Recommended: (2 x CPU cores) + 1
  --bind <addr:port>           Gunicorn bind address (default: 127.0.0.1:8001)
                               Format: IP:PORT or unix:/path/to/socket

=== SSL/TLS OPTIONS ===
  --enable-ssl                 Enable HTTPS with SSL/TLS certificates
  --use-letsencrypt            Use Let's Encrypt for free trusted certificates
                               Requires valid domain and port 80 access
  --ssl-email <email>          Email for Let's Encrypt notifications
                               Required when using --use-letsencrypt

  --ssl-renewal-cron <bool>    Enable automatic renewal monitoring (default: true)
                               Values: true, false
  --ssl-renewal-days <num>     Days before expiry to send warnings (default: 30)
                               Notifications sent when cert expires in N days
  --ssl-renewal-email <email>  Email for renewal notifications (default: root)
                               Requires 'mail' command to be configured

=== EXAMPLES ===

  # Basic HTTP-only installation
  sudo ./setup_webserver.sh

  # HTTPS with self-signed certificate (testing)
  sudo ./setup_webserver.sh --enable-ssl --server-name dev.example.com

  # HTTPS with Let's Encrypt (production)
  sudo ./setup_webserver.sh \
    --enable-ssl \
    --use-letsencrypt \
    --server-name example.com \
    --ssl-email admin@example.com \
    --ssl-renewal-email admin@example.com

  # Custom ports with SSL renewal monitoring
  sudo NGINX_PORT=8080 NGINX_SSL_PORT=8443 ./setup_webserver.sh \
    --enable-ssl \
    --server-name dev.example.com \
    --ssl-renewal-days 45 \
    --ssl-renewal-email devops@example.com

  # Remote installation
  sudo ./setup_webserver.sh \
    --remote server.example.com \
    --user deploy \
    --enable-ssl \
    --server-name app.example.com

  # High-performance configuration
  sudo ./setup_webserver.sh \
    --workers 8 \
    --bind 127.0.0.1:8000 \
    --enable-ssl

=== ENVIRONMENT VARIABLES ===

  APP_NAME                     Application name (default: clippyfront)
  APP_USER                     System user for application (default: clippyfront)
  APP_GROUP                    System group for application (default: clippyfront)
  TABLE_PREFIX                 Database table prefix (default: opt_ for production)

  NGINX_PORT                   HTTP port (default: 80)
  NGINX_SSL_PORT               HTTPS port (default: 443)
  CLIENT_MAX_BODY_SIZE         Max upload size (default: 2G)

  GUNICORN_WORKERS             Number of workers (default: 4)
  GUNICORN_THREADS             Threads per worker (default: 2)
  GUNICORN_BIND                Bind address (default: 127.0.0.1:8001)
  GUNICORN_TIMEOUT             Request timeout in seconds (default: 120)

  ENABLE_RATE_LIMITING         Enable rate limiting (default: true)
  RATE_LIMIT                   Requests per second (default: 10r/s)
  RATE_LIMIT_BURST             Burst size (default: 20)

  SSL_RENEWAL_CRON             Auto-check cert expiry (default: true)
  SSL_RENEWAL_DAYS             Warning threshold days (default: 30)
  SSL_RENEWAL_EMAIL            Notification email (default: root)

=== SSL RENEWAL MONITORING ===

When enabled, the script installs:
  - Renewal check script: /usr/local/bin/renew_<appname>_ssl.sh
  - Cron job: /etc/cron.d/renew-<appname>-ssl
  - Log file: /var/log/letsencrypt/renewal-check.log

The cron job runs weekly (Mondays at 3 AM) and:
  1. Checks certificate expiration date
  2. Sends email if expiring within threshold days
  3. Logs all checks for audit trail

Manual check:
  sudo /usr/local/bin/renew_<appname>_ssl.sh <domain>

=== LOGS AND DEBUGGING ===

  Application logs:     /opt/clippyfront/instance/logs/
  Gunicorn service:     journalctl -u gunicorn-clippyfront -f
  Nginx service:        journalctl -u nginx -f
  SSL renewal:          tail -f /var/log/letsencrypt/renewal-check.log

=== SYSTEMD SERVICES ===

  Check status:         sudo systemctl status gunicorn-clippyfront
                        sudo systemctl status nginx

  Restart services:     sudo systemctl restart gunicorn-clippyfront
                        sudo systemctl restart nginx

  View logs:            sudo journalctl -u gunicorn-clippyfront -n 50
                        sudo journalctl -u nginx -n 50

=== CONFIGURATION FILES ===

  Gunicorn config:      /opt/clippyfront/gunicorn.conf.py
  Systemd service:      /etc/systemd/system/gunicorn-clippyfront.service
  Nginx config:         /etc/nginx/sites-available/clippyfront
  SSL certificates:     /etc/letsencrypt/live/<domain>/
  Renewal script:       /usr/local/bin/renew_clippyfront_ssl.sh
  Renewal cron:         /etc/cron.d/renew-clippyfront-ssl

=== NOTES ===

  • This script is idempotent - safe to run multiple times
  • For Let's Encrypt: domain must point to server and port 80 accessible
  • For non-standard ports: configure router port forwarding accordingly
  • Email notifications require 'mail' command (postfix/sendmail)
  • Self-signed certificates will show browser warnings
  • Production deployments should use Let's Encrypt or commercial certs

For more information, see: https://github.com/zebadrabbit/ClippyFront
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
    execute_remotely "$@"
else
    main
fi
