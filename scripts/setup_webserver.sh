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
GUNICORN_BIND="${GUNICORN_BIND:-127.0.0.1:8000}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"
GUNICORN_MAX_REQUESTS="${GUNICORN_MAX_REQUESTS:-1000}"
GUNICORN_MAX_REQUESTS_JITTER="${GUNICORN_MAX_REQUESTS_JITTER:-50}"

# Nginx settings
NGINX_PORT="${NGINX_PORT:-80}"
NGINX_SSL_PORT="${NGINX_SSL_PORT:-443}"
SERVER_NAME="${SERVER_NAME:-_}"  # Default to catch-all
ENABLE_SSL="${ENABLE_SSL:-false}"
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
Requires=gunicorn-${APP_NAME}.socket
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

    # Create socket file for systemd socket activation (optional but recommended)
    cat > /etc/systemd/system/gunicorn-${APP_NAME}.socket <<EOF
[Unit]
Description=Gunicorn socket for $APP_NAME

[Socket]
ListenStream=$GUNICORN_BIND

[Install]
WantedBy=sockets.target
EOF

    systemctl daemon-reload
    systemctl enable gunicorn-${APP_NAME}.service
    systemctl enable gunicorn-${APP_NAME}.socket

    log_info "Gunicorn systemd service created"
}

start_gunicorn() {
    log_info "Starting Gunicorn..."

    systemctl restart gunicorn-${APP_NAME}.service || {
        log_error "Failed to start Gunicorn. Check logs:"
        log_error "  journalctl -u gunicorn-${APP_NAME}.service -n 50"
        return 1
    }

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
    cat <<'SSL'
    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
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
SSL
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

# ==================== SSL Certificate ====================

setup_ssl_certificate() {
    if [[ "$ENABLE_SSL" == "true" ]]; then
        if [[ ! -f "$SSL_CERT_PATH" ]] || [[ ! -f "$SSL_KEY_PATH" ]]; then
            log_warn "SSL enabled but certificates not found"
            log_info "Generating self-signed certificate for testing..."

            mkdir -p "$(dirname "$SSL_CERT_PATH")"
            mkdir -p "$(dirname "$SSL_KEY_PATH")"

            openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
                -keyout "$SSL_KEY_PATH" \
                -out "$SSL_CERT_PATH" \
                -subj "/C=US/ST=State/L=City/O=Organization/CN=$SERVER_NAME"

            chmod 600 "$SSL_KEY_PATH"
            chmod 644 "$SSL_CERT_PATH"

            log_warn "Self-signed certificate created. For production, use Let's Encrypt:"
            log_warn "  sudo apt install certbot python3-certbot-nginx"
            log_warn "  sudo certbot --nginx -d $SERVER_NAME"
        else
            log_info "SSL certificates found"
        fi
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

    # Application setup
    create_app_user
    setup_app_directory
    setup_python_virtualenv
    install_app_dependencies

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
    echo
    if [[ "$ENABLE_SSL" == "true" ]] && [[ "$SSL_CERT_PATH" == *"self-signed"* ]]; then
        log_warn "Using self-signed SSL certificate. For production:"
        log_warn "  Install certbot and run: sudo certbot --nginx -d $SERVER_NAME"
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
        --enable-ssl)
            ENABLE_SSL=true
            shift
            ;;
        --workers)
            GUNICORN_WORKERS="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo
            echo "Options:"
            echo "  --remote <host>          Execute on remote host via SSH"
            echo "  --user <username>        Remote SSH user (default: root)"
            echo "  --app-dir <path>         Application directory (default: /opt/clippyfront)"
            echo "  --server-name <domain>   Server domain name (default: _)"
            echo "  --enable-ssl             Enable HTTPS with SSL"
            echo "  --workers <num>          Number of Gunicorn workers (default: 4)"
            echo
            echo "Environment variables:"
            echo "  APP_NAME                 Application name (default: clippyfront)"
            echo "  GUNICORN_WORKERS         Number of workers (default: 4)"
            echo "  CLIENT_MAX_BODY_SIZE     Max upload size (default: 2G)"
            echo "  ENABLE_RATE_LIMITING     Enable rate limiting (default: true)"
            echo
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
