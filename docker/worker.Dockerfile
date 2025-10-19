# ClippyFront Celery GPU Worker
# Base: NVIDIA CUDA runtime for GPU passthrough on Windows/Linux hosts
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# OS deps: Python, pip, ffmpeg (NVENC will be used if available on host), ca-certs
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt ./
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt

# Copy application code
COPY . .

# Environment defaults (override via env / compose)
ENV FLASK_ENV=production \
    USE_GPU_QUEUE=true \
    FFMPEG_BINARY=ffmpeg \
    YT_DLP_BINARY=yt-dlp \
    CELERY_CONCURRENCY=1 \
    CELERY_QUEUES=gpu,celery

# Expose nothing by default (worker only)

# Entrypoint: Celery worker listening on gpu and default queues
CMD ["sh", "-lc", "celery --broker=${CELERY_BROKER_URL} --result-backend=${CELERY_RESULT_BACKEND} -A app.tasks.celery_app worker --loglevel=info -Q ${CELERY_QUEUES} -c ${CELERY_CONCURRENCY}"]
