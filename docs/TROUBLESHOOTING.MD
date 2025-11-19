# Troubleshooting Guide

## Common Issues

### Frontend Assets

**Problem**: Dropzone not defined or blocked by CSP

**Solution**: Ensure vendor assets are installed locally
```bash
bash scripts/fetch_vendor_assets.sh
```

Verify files exist:
- `app/static/vendor/dropzone/`
- `app/static/vendor/videojs/`

### Video Playback

**Problem**: Video can't play (MEDIA_ERR_SRC_NOT_SUPPORTED)

**Cause**: Browser doesn't support codec/format

**Solutions**:
1. Upload MP4 with H.264/AAC codec
2. Transcode with ffmpeg:
   ```bash
   ffmpeg -i input.webm -c:v libx264 -c:a aac output.mp4
   ```
3. Use browser's direct file open fallback (UI offers this)

### Authentication

**Problem**: Invalid login for admin/admin123

**Solution**: Reset admin password
```bash
python init_db.py --reset-admin --password admin123
```

### Binary Dependencies

**Problem**: Missing ffmpeg or yt-dlp

**Solution**: Install local binaries
```bash
bash scripts/install_local_binaries.sh
```

Then configure environment:
```bash
export FFMPEG_BINARY="$(pwd)/bin/ffmpeg"
export YT_DLP_BINARY="$(pwd)/bin/yt-dlp"
```

## Worker Issues

### Celery Task Signature Errors

**Problem**: `unexpected keyword argument 'clip_ids'`

**Cause**: Web app and worker running different code versions

**Solution**: Rebuild and restart workers
```bash
# Stop all workers
pkill -f "celery.*worker"

# Rebuild containers (if using Docker)
docker build -f docker/celery-worker.Dockerfile -t worker:latest .

# Restart workers with same code version as web app
celery -A app.tasks.celery_app worker -Q gpu,cpu --loglevel=info
```

### Version Mismatches

**Problem**: Workers showing version mismatch in admin dashboard

**Check**: Visit `/admin/workers` to see version compatibility

**Solution**: Use stale worker detection
```bash
# Detect stale workers
./scripts/check_stale_workers.sh

# Stop them interactively
./scripts/check_stale_workers.sh --stop
```

**Common cause**: Old Docker containers still running
```bash
docker ps | grep celery
docker stop <container_id>
```

### Queue Routing

**Problem**: Compilations running on server instead of GPU/CPU workers

**Cause**: Server worker consuming from wrong queues

**Solution**: Restart server worker with correct queue
```bash
# Stop server worker
pkill -f "celery.*worker"

# Restart with celery queue only
celery -A app.tasks.celery_app worker -Q celery --loglevel=info
```

Verify queue configuration:
```bash
celery -A app.tasks.celery_app inspect active_queues
```

Should show:
- Server: `celery` queue only
- Workers: `gpu,cpu` queues only

## Database Issues

### Missing Media Files in UI

**Problem**: Files exist on disk but don't appear in Media Library

**Cause**: Database missing MediaFile records

**Solution**: Reindex media library
```bash
# Backfill DB rows from filesystem
python scripts/reindex_media.py

# Also regenerate missing thumbnails
python scripts/reindex_media.py --regen-thumbnails
```

The script:
- Scans `instance/data/<username>/...` directories
- Infers media type from subfolders
- Creates missing MediaFile records
- Optionally regenerates thumbnails

### Auto-Reindex on Startup

**Development only**: Enable automatic reindex when DB is empty
```bash
export AUTO_REINDEX_ON_STARTUP=true
```

Not recommended for production (may mask DB issues).

### Database Connection

**Problem**: Can't connect to database

**Check**: Verify DATABASE_URL is correct
```bash
python scripts/health_check.py --db "$DATABASE_URL"
```

**PostgreSQL requirement**: App requires PostgreSQL outside tests
- SQLite is only for pytest
- Set `DATABASE_URL=postgresql://...`

## NVENC / GPU Encoding

### NVENC Not Available

**Check**: Test NVENC support
```bash
python scripts/check_nvenc.py
```

**WSL2 specific**: Set library path
```bash
export LD_LIBRARY_PATH=/usr/lib/wsl/lib:${LD_LIBRARY_PATH}
```

**Force CPU encoding**:
```bash
export FFMPEG_DISABLE_NVENC=1
```

### CUDA Library Errors

**Problem**: `Cannot load libcuda.so.1`

**WSL2 Solution**:
```bash
export LD_LIBRARY_PATH=/usr/lib/wsl/lib:${LD_LIBRARY_PATH}
```

**Docker Solution**: Use `--gpus all` flag
```bash
docker run --gpus all ...
```

## Storage Issues

### Cross-Device Link Errors

**Problem**: `OSError: [Errno 18] Invalid cross-device link`

**Cause**: Worker temp directory on different filesystem

**Solution**: Set TMPDIR to instance mount
```bash
export TMPDIR=/app/instance/tmp
```

### Media Path Mismatches

**Problem**: Files stored with wrong paths

**Check**: Verify storage configuration
```bash
python scripts/check_media_path.py
```

**Migration**: Use path aliases for legacy paths
```bash
export MEDIA_PATH_ALIAS_FROM=/old/path
export MEDIA_PATH_ALIAS_TO=/new/path
```

### Avatar Resolution

**Problem**: Avatars not appearing in compilations

**Debug**: Enable overlay logging
```bash
export OVERLAY_DEBUG=1
```

Check logs for:
- Avatar search paths
- Match results
- Fallback usage

**Verify paths**:
- `AVATARS_PATH` points to `instance/assets/avatars` or `instance/assets`
- Files exist: `<creator_name>.png` or `<creator_name>.jpg`
- Fallback exists: `avatar.png`

### Avatar Cleanup

**Manage cache**: Prune old avatars
```bash
# Dry run (shows what would be deleted)
python scripts/cleanup_avatars.py --keep 5 --dry-run

# Actually delete
python scripts/cleanup_avatars.py --keep 5
```

## Static Bumper

**Customize**: Replace default static bumper
```bash
# Copy your custom bumper
cp /path/to/custom.mp4 instance/assets/static.mp4

# Or set custom path
export STATIC_BUMPER_PATH=/path/to/static.mp4
```

## Log Analysis

### Console TUI

**Monitor live**: Use experimental console
```bash
python scripts/console.py
```

Controls:
- `q` - quit
- `f` - cycle filter levels
- `d/i/w/e` - toggle Debug/Info/Warning/Error
- `c` - clear log view
- `PgUp/PgDn` - scroll logs

### Log Files

Default location: `instance/logs/`
- `app.log` - Web application logs
- `worker.log` - Celery worker logs
- Size-based rotation: 10MB × 5 files

**Override**: Set custom log directory
```bash
export LOG_DIR=/path/to/logs
```

## Network & Connectivity

### Redis Connection

**Test**: Verify Redis connectivity
```bash
python scripts/health_check.py --redis "$REDIS_URL"
```

**Docker**: Use host networking
```bash
docker run --network host ...
```

### Worker API (v0.12.0+)

**Problem**: Workers can't reach Flask app

**Check**: Verify environment
```bash
echo $FLASK_APP_URL
echo $WORKER_API_KEY
```

**Test**: Manual API call
```bash
curl -H "X-Worker-API-Key: $WORKER_API_KEY" \
     $FLASK_APP_URL/api/worker/health
```

### Remote Workers

**VPN setup**: See [WIREGUARD.MD](WIREGUARD.MD)

**Storage access**: See [WORKER_SETUP.MD](WORKER_SETUP.MD)

## Getting Help

1. Check logs in `instance/logs/`
2. Enable debug mode: `FLASK_DEBUG=1`
3. Run health checks: `scripts/health_check.py`
4. Check worker dashboard: `/admin/workers`
5. Review configuration: [CONFIGURATION.MD](CONFIGURATION.MD)

See also:
- [WORKER_SETUP.MD](WORKER_SETUP.MD) - Worker deployment
- [WORKER-VERSION-CHECKING.MD](WORKER-VERSION-CHECKING.MD) - Version compatibility
- [TIERS-AND-QUOTAS.MD](TIERS-AND-QUOTAS.MD) - Quota system
