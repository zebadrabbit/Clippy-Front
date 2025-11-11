# ClippyFront GPU Worker + Artifact Sync (single container)
# Runs Celery GPU worker and rsync-based artifact sync under Supervisor
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv ffmpeg ca-certificates \
      rsync openssh-client supervisor findutils coreutils curl inotify-tools \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app /app/instance /artifacts

WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt ./
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt

# Copy application code and worker scripts
COPY . .

# Copy supervisor config that launches Celery + sync sidecars
COPY scripts/worker/supervisord.combined.conf /etc/supervisor/conf.d/clippy-combined.conf
COPY scripts/worker/supervisord.main.conf /etc/supervisor/supervisord.conf

RUN chmod +x /usr/local/bin || true && \
    chmod +x /app/scripts/worker/*.sh || true

VOLUME ["/app/instance", "/artifacts"]

# Secrets are expected at /run/secrets/{rsync_key,known_hosts}

# Defaults (override via env / compose)
ENV FLASK_ENV=production \
    USE_GPU_QUEUE=true \
    FFMPEG_BINARY=ffmpeg \
    YT_DLP_BINARY=yt-dlp \
    CELERY_CONCURRENCY=1 \
    CELERY_QUEUES=gpu,celery \
    C_FORCE_ROOT=true \
    CLIPPY_INSTANCE_PATH=/app/instance \
    REQUIRE_INSTANCE_MOUNT=1 \
    TMPDIR=/app/instance/tmp \
    ARTIFACTS_DIR=/artifacts \
    PUSH_INTERVAL=60 \
    WATCH_MODE=auto \
    INGEST_PORT=22 \
    LD_LIBRARY_PATH=/usr/lib/wsl/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib64:${LD_LIBRARY_PATH}

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD bash -lc 'pgrep -f "celery .*worker" >/dev/null && pgrep -f clippy-push.sh >/dev/null && pgrep -f clippy-scan.sh >/dev/null'

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
