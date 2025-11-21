# Production Deployment Guide

This guide covers deploying ClippyFront to production using the automated deployment scripts.

## Overview

ClippyFront provides two automated deployment scripts for production infrastructure:

- **`scripts/setup_monitoring.sh`** - Prometheus + Grafana + Node Exporter monitoring stack
- **`scripts/setup_webserver.sh`** - Nginx + Gunicorn web server with SSL/TLS

Both scripts are:
- ✅ **Idempotent** - Safe to run multiple times for updates
- ✅ **Remote-capable** - Can deploy to remote hosts via SSH
- ✅ **OS-aware** - Auto-detects Ubuntu/Debian/CentOS/RHEL
- ✅ **Production-ready** - Security hardening, systemd services, logging

---

## Monitoring Stack Setup

The monitoring script installs and configures a complete observability stack.

### Components

- **Prometheus 2.48.0** - Metrics collection and alerting
- **Grafana 10.2.2** - Visualization and dashboards
- **Node Exporter 1.7.0** - System metrics (CPU, memory, disk)

### Quick Start

```bash
# Local installation
sudo scripts/setup_monitoring.sh

# Remote installation
scripts/setup_monitoring.sh --remote prod-server.example.com --user root
```

### Configuration Options

Environment variables for customization:

```bash
# Prometheus settings
export PROMETHEUS_VERSION="2.48.0"
export PROMETHEUS_PORT="9090"
export PROMETHEUS_RETENTION="30d"
export PROMETHEUS_SCRAPE_INTERVAL="15s"

# Grafana settings
export GRAFANA_VERSION="10.2.2"
export GRAFANA_PORT="3000"
export GRAFANA_ADMIN_USER="admin"
export GRAFANA_ADMIN_PASSWORD="your-secure-password"

# Node Exporter
export NODE_EXPORTER_VERSION="1.7.0"
export NODE_EXPORTER_PORT="9100"

# Application metrics
export APP_METRICS_PORT="5000"        # Flask app
export REDIS_METRICS_PORT="6379"      # Redis
export POSTGRES_EXPORTER_PORT="9187"  # PostgreSQL

# Installation paths
export INSTALL_DIR="/opt"
export DATA_DIR="/var/lib"
export CONFIG_DIR="/etc"

# Run installation
sudo -E scripts/setup_monitoring.sh
```

### What Gets Installed

**Prometheus** (`/opt/prometheus`):
- Scrapes metrics from:
  - Node Exporter (system metrics)
  - ClippyFront app (port 5000)
  - Redis (port 6379)
  - PostgreSQL (port 9187)
  - Celery workers
- 30-day data retention
- Alert rules for:
  - Instance down
  - High CPU usage (>80%)
  - High memory usage (>80%)
  - High disk usage (>85%)
- Accessible at: `http://localhost:9090`

**Grafana** (`/usr/share/grafana`):
- Auto-provisioned Prometheus datasource
- Pre-configured ClippyFront dashboard
- Accessible at: `http://localhost:3000`
- Default credentials: `admin` / (prompted during install)

**Node Exporter** (`/opt/node_exporter`):
- System metrics collection
- Accessible at: `http://localhost:9100/metrics`

**Systemd Services**:
- `prometheus.service` - Starts on boot, auto-restarts
- `grafana-server.service` - Starts on boot
- `node_exporter.service` - Starts on boot

### Firewall Configuration

The script automatically configures firewall rules:

**UFW** (Ubuntu/Debian):
```bash
# Ports opened
9090/tcp  # Prometheus
3000/tcp  # Grafana
9100/tcp  # Node Exporter
```

**firewalld** (CentOS/RHEL):
```bash
# Services added to default zone
prometheus (9090/tcp)
grafana (3000/tcp)
node-exporter (9100/tcp)
```

### Post-Installation

1. **Access Grafana**: Navigate to `http://your-server:3000`
   - Login with admin credentials
   - Default dashboard: "ClippyFront Monitoring"

2. **Access Prometheus**: Navigate to `http://your-server:9091`
   - Check targets: Status → Targets
   - View alerts: Alerts

3. **Verify Node Exporter**: `curl http://localhost:9100/metrics`

### Customization

**Add Custom Metrics** - Edit `/etc/prometheus/prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'my-service'
    static_configs:
      - targets: ['localhost:8080']
```

**Add Alerts** - Edit `/etc/prometheus/alert_rules.yml`:
```yaml
groups:
  - name: custom_alerts
    rules:
      - alert: CustomAlert
        expr: my_metric > 100
        for: 5m
```

**Reload Configuration**:
```bash
sudo systemctl reload prometheus
```

### Remote Installation

Deploy monitoring to a remote server:

```bash
# Via SSH
scripts/setup_monitoring.sh --remote prod-server --user root

# Via WireGuard VPN
scripts/setup_monitoring.sh --remote 10.0.0.2 --user root --wireguard
```

Requirements:
- SSH access to remote host
- Sudo privileges on remote host
- SSH key authentication (no password prompts)

---

## Web Server Setup

The web server script installs Nginx + Gunicorn with production hardening.

### Components

- **Nginx** - Reverse proxy, SSL/TLS termination, rate limiting
- **Gunicorn** - WSGI server with gevent workers
- **Systemd** - Service management and socket activation
- **Certbot** - SSL/TLS certificate management (optional)

### Quick Start

```bash
# Basic installation
sudo scripts/setup_webserver.sh

# With custom domain
sudo scripts/setup_webserver.sh --server-name clips.example.com

# With SSL/TLS
sudo scripts/setup_webserver.sh --server-name clips.example.com --enable-ssl

# Custom worker count
sudo scripts/setup_webserver.sh --workers 8

# Remote installation
scripts/setup_webserver.sh --remote web-server --user root --server-name clips.example.com
```

### Configuration Options

```bash
# Server configuration
--server-name DOMAIN       # Domain name (default: localhost)
--enable-ssl               # Enable SSL/TLS with self-signed cert
--workers N                # Gunicorn worker count (default: 4)
--worker-class CLASS       # Worker type (default: gevent)
--threads N                # Threads per worker (default: 2)
--timeout SECONDS          # Request timeout (default: 120)
--max-requests N           # Worker restart after N requests (default: 1000)

# Rate limiting
--rate-limit RATE          # Requests per second (default: 10)
--rate-burst N             # Burst allowance (default: 20)

# Upload limits
--max-upload-size SIZE     # Max upload size (default: 2048M)

# Paths
--app-path PATH            # Application directory (default: /var/www/clippyfront)
--venv-path PATH           # Virtual environment path (default: /var/www/clippyfront/venv)

# Remote execution
--remote HOST              # Remote hostname
--user USERNAME            # SSH user (default: root)
--wireguard                # Use WireGuard VPN
```

### What Gets Installed

**Application User** (`clippyfront:clippyfront`):
- Isolated user for running the application
- No shell access for security
- Owns application files

**Gunicorn Configuration** (`/etc/clippyfront/gunicorn.conf.py`):
- 4 gevent workers (async)
- 2 threads per worker
- 120-second timeout
- Worker restart after 1000 requests
- Binds to `127.0.0.1:8000`
- Logs to `instance/logs/gunicorn-*.log`

**Systemd Services**:
- `clippyfront-gunicorn.socket` - Socket activation
- `clippyfront-gunicorn.service` - Application service
  - Starts on boot
  - Auto-restart on failure
  - Security hardening: NoNewPrivileges, PrivateDevices, ProtectSystem

**Nginx Configuration** (`/etc/nginx/sites-available/clippyfront`):
- Reverse proxy to Gunicorn (127.0.0.1:8000)
- WebSocket/SSE support (for real-time notifications)
- Static file serving with caching (30 days)
- X-Accel-Redirect for internal media serving
- Rate limiting (10 req/s, burst 20)
- Large file uploads (2GB default)
- Security headers:
  - HSTS (max-age=31536000)
  - X-Frame-Options: DENY
  - X-Content-Type-Options: nosniff
  - X-XSS-Protection: 1; mode=block
  - Content-Security-Policy
- Health check endpoint: `/health`

**SSL/TLS** (when `--enable-ssl` used):
- Self-signed certificate for testing
- Ready for Let's Encrypt integration
- Automatic HTTP → HTTPS redirect
- Modern TLS configuration (TLSv1.2+)

**Log Rotation** (`/etc/logrotate.d/clippyfront`):
- Daily rotation
- 14-day retention
- Compression (gzip)
- Automatic reload

### Post-Installation

1. **Verify Services**:
```bash
# Check Gunicorn
sudo systemctl status clippyfront-gunicorn

# Check Nginx
sudo systemctl status nginx

# View logs
sudo journalctl -u clippyfront-gunicorn -f
sudo tail -f /var/log/nginx/clippyfront-access.log
```

2. **Test Application**:
```bash
# HTTP
curl http://localhost/

# HTTPS (if enabled)
curl https://clips.example.com/
```

3. **Configure DNS**:
   - Point your domain to server IP
   - Update `--server-name` if needed

4. **Install Let's Encrypt** (recommended for production):
```bash
# Install Certbot
sudo apt-get install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d clips.example.com

# Auto-renewal is configured by Certbot
```

### Security Hardening

**Firewall**:
```bash
# UFW
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# firewalld
sudo firewall-cmd --add-service=http --permanent
sudo firewall-cmd --add-service=https --permanent
sudo firewall-cmd --reload
```

**Systemd Security**:
- `NoNewPrivileges=true` - Prevents privilege escalation
- `PrivateDevices=true` - Restricts device access
- `ProtectSystem=strict` - Read-only system directories
- User/group isolation

**Nginx Security**:
- Rate limiting prevents abuse
- Security headers prevent XSS, clickjacking
- CSP restricts resource loading
- Server tokens hidden

### Performance Tuning

**Gunicorn Workers**:
```bash
# CPU-bound: workers = (CPU cores * 2) + 1
sudo scripts/setup_webserver.sh --workers 9  # For 4-core system

# Adjust in config
sudo nano /etc/clippyfront/gunicorn.conf.py
sudo systemctl restart clippyfront-gunicorn
```

**Nginx Caching**:
```nginx
# Add to /etc/nginx/sites-available/clippyfront
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=app_cache:10m max_size=1g;

location / {
    proxy_cache app_cache;
    proxy_cache_valid 200 5m;
}
```

**Rate Limiting**:
```bash
# Adjust limits
sudo scripts/setup_webserver.sh --rate-limit 20 --rate-burst 50
```

### Remote Installation

Deploy to remote server:

```bash
# Standard deployment
scripts/setup_webserver.sh \
  --remote prod-web.example.com \
  --user root \
  --server-name clips.example.com \
  --enable-ssl \
  --workers 8

# Via WireGuard VPN
scripts/setup_webserver.sh \
  --remote 10.0.0.2 \
  --user root \
  --wireguard \
  --server-name clips.internal.lan \
  --workers 4
```

Requirements:
- SSH access to remote host
- Sudo privileges
- SSH key authentication
- Application code deployed to `/var/www/clippyfront`

---

## Complete Production Setup

Deploy both monitoring and web server:

```bash
#!/bin/bash
set -e

SERVER="prod.example.com"
DOMAIN="clips.example.com"
USER="root"

# 1. Install monitoring stack
scripts/setup_monitoring.sh --remote "$SERVER" --user "$USER"

# 2. Install web server
scripts/setup_webserver.sh \
  --remote "$SERVER" \
  --user "$USER" \
  --server-name "$DOMAIN" \
  --enable-ssl \
  --workers 8 \
  --rate-limit 20

# 3. Verify services
ssh "$USER@$SERVER" "systemctl status prometheus grafana-server nginx clippyfront-gunicorn"

echo "✅ Production deployment complete!"
echo "📊 Grafana: http://$SERVER:3000"
echo "🌐 Application: https://$DOMAIN"
```

---

## Updating Configuration

Both scripts are idempotent - run them again to update configuration:

```bash
# Update monitoring retention
export PROMETHEUS_RETENTION="60d"
sudo scripts/setup_monitoring.sh

# Update web server workers
sudo scripts/setup_webserver.sh --workers 16

# Both scripts preserve data and restart services cleanly
```

---

## Troubleshooting

### Monitoring Stack

**Prometheus not collecting metrics**:
```bash
# Check Prometheus
sudo systemctl status prometheus
sudo journalctl -u prometheus -n 50

# Verify targets
curl http://localhost:9090/api/v1/targets

# Check firewall
sudo ufw status
```

**Grafana login issues**:
```bash
# Reset admin password
sudo grafana-cli admin reset-admin-password newpassword
sudo systemctl restart grafana-server
```

### Web Server

**502 Bad Gateway**:
```bash
# Check Gunicorn
sudo systemctl status clippyfront-gunicorn
sudo journalctl -u clippyfront-gunicorn -n 50

# Check socket
sudo systemctl status clippyfront-gunicorn.socket
ls -la /run/clippyfront/

# Restart services
sudo systemctl restart clippyfront-gunicorn nginx
```

**SSL certificate errors**:
```bash
# Verify certificate
sudo nginx -t

# Renew Let's Encrypt
sudo certbot renew --dry-run
sudo certbot renew

# Check auto-renewal
sudo systemctl status certbot.timer
```

**Rate limiting too aggressive**:
```bash
# Adjust limits in Nginx config
sudo nano /etc/nginx/sites-available/clippyfront

# Find:
limit_req_zone $binary_remote_addr zone=app_limit:10m rate=10r/s;
limit_req zone=app_limit burst=20 nodelay;

# Update and reload
sudo nginx -t
sudo systemctl reload nginx
```

---

## Uninstallation

### Remove Monitoring Stack

```bash
# Stop services
sudo systemctl stop prometheus grafana-server node_exporter
sudo systemctl disable prometheus grafana-server node_exporter

# Remove files
sudo rm -rf /opt/prometheus /opt/node_exporter
sudo rm -rf /var/lib/prometheus /var/lib/grafana
sudo rm -rf /etc/prometheus /etc/grafana
sudo rm /etc/systemd/system/prometheus.service
sudo rm /etc/systemd/system/node_exporter.service

# Reload systemd
sudo systemctl daemon-reload

# Remove firewall rules
sudo ufw delete allow 9090/tcp
sudo ufw delete allow 3000/tcp
sudo ufw delete allow 9100/tcp
```

### Remove Web Server

```bash
# Stop services
sudo systemctl stop clippyfront-gunicorn nginx
sudo systemctl disable clippyfront-gunicorn

# Remove configuration
sudo rm /etc/nginx/sites-enabled/clippyfront
sudo rm /etc/nginx/sites-available/clippyfront
sudo rm -rf /etc/clippyfront
sudo rm /etc/systemd/system/clippyfront-gunicorn.*

# Reload
sudo systemctl daemon-reload
sudo systemctl reload nginx

# Remove firewall rules
sudo ufw delete allow 80/tcp
sudo ufw delete allow 443/tcp
```

---

## See Also

- [Installation Guide](INSTALLATION.md) - Application setup
- [Worker Setup](WORKER_SETUP.md) - Background workers
- [Remote Worker Setup](REMOTE_WORKER_SETUP.md) - Distributed workers
- [Error Handling Audit](ERROR_HANDLING_AUDIT.md) - Observability details
- [Configuration](CONFIGURATION.md) - Environment variables
