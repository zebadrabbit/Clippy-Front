# Artifact-sync sidecar image for scanning and rsync-over-SSH pushes
FROM alpine:3.20

RUN apk add --no-cache \
    bash \
    curl \
    coreutils \
    rsync \
    openssh-client \
    inotify-tools \
    supervisor

WORKDIR /

# Copy worker scripts
COPY scripts/worker /scripts/worker
RUN chmod +x /scripts/worker/*.sh

# Default environment (override via compose/.env)
ENV PUSH_INTERVAL=60 \
    INGEST_PORT=22 \
    WORKER_ID=worker-01 \
    ARTIFACTS_DIR=/artifacts

VOLUME ["/artifacts"]

# Healthcheck: ensure scanner is running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD pgrep -f clippy-scan >/dev/null || exit 1

# Default entrypoint runs the scanner
ENTRYPOINT ["/scripts/worker/clippy-scan.sh"]
