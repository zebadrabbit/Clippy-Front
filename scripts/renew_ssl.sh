#!/usr/bin/env bash
#
# renew_ssl.sh - Attempt to renew Let's Encrypt certificate
#
# This script checks if the certificate needs renewal and attempts it.
# For manual DNS challenge, it will fail but log the required TXT record.
#

set -euo pipefail

DOMAIN="${1:-dev.clipshow.io}"
CERT_PATH="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
LOG_FILE="/var/log/letsencrypt/renewal-check.log"
DAYS_BEFORE_EXPIRY=30

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

# For manual DNS challenge, we can't automate fully, so send notification
log_warn "Manual DNS challenge renewal required:"
log_warn "  1. Run: sudo certbot certonly --manual --preferred-challenges dns -d $DOMAIN"
log_warn "  2. Add the TXT record to DNS"
log_warn "  3. Complete the challenge"
log_warn "  4. Nginx will automatically use the new certificate (no reload needed)"

# Send email notification if mail is configured
if command -v mail &>/dev/null; then
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
        echo "Certificate details:"
        echo "  Domain: $DOMAIN"
        echo "  Expires: $expiry_date"
        echo "  Days remaining: $days_until_expiry"
    } | mail -s "SSL Certificate Renewal Required: $DOMAIN" root
    log_info "Notification email sent to root"
fi

exit 0
