# Binary Update Checking

ClippyFront can automatically check for updates to critical binaries (ffmpeg, ffprobe, yt-dlp) and notify administrators when new versions are available.

## Features

- **Automated Checking**: Celery beat task runs weekly to check for binary updates
- **Admin Notifications**: Admins receive in-app notifications when updates are available
- **Manual Check**: Admins can trigger update checks manually from the maintenance page
- **One-Click Update**: Update binaries directly from the admin UI using the local installer script

## How It Works

### Automatic Checks (Weekly)

A Celery beat task runs every 7 days to check for updates:

```python
# Configured in app/tasks/celery_app.py
"check-binary-updates": {
    "task": "app.tasks.binary_updates.check_binary_updates_task",
    "schedule": 604800.0,  # 7 days in seconds
}
```

### Version Detection

The update checker compares currently installed versions against the latest available:

- **yt-dlp**: Queries GitHub API for latest release tag
- **ffmpeg/ffprobe**: Parses ffmpeg.org download page for latest version

### Update Storage

Update information is stored in the `SystemSetting` model:

- `BINARY_UPDATES_AVAILABLE`: Dictionary of available updates with current/latest versions
- `BINARY_UPDATES_CHECKED_AT`: ISO timestamp of last check

### Admin Notifications

When updates are found, all admin users receive a notification with:
- Summary of available updates (e.g., "yt-dlp (2024.10.22 → 2024.11.18)")
- Link to the maintenance page for review and installation

## Usage

### Manual Check

1. Navigate to `/admin/maintenance`
2. Click "Check for Updates" in the Binary Updates section
3. Task runs in background and updates page on next refresh
4. Admins receive notifications if updates are available

### Installing Updates

1. Navigate to `/admin/maintenance`
2. If updates are shown, click "Update Binaries"
3. System runs `scripts/install_local_binaries.sh` to download and install latest versions
4. Success/failure message displayed

### Viewing Update Status

The maintenance page shows:
- Current vs. latest version for each binary
- Resolved binary paths
- Last check timestamp
- Update/recheck buttons

## Configuration

No configuration needed - the feature works automatically once Celery beat is running.

To run Celery beat (required for automatic checks):

```bash
# In addition to your regular Celery worker
celery -A app.tasks.celery_app beat --loglevel=info
```

## Manual Task Trigger

You can also trigger the update check manually via Celery:

```python
from app.tasks.binary_updates import check_binary_updates_task

# Trigger check
task = check_binary_updates_task.delay()
print(f"Task ID: {task.id}")
```

## Implementation Details

### Task: `check_binary_updates_task`

Location: `app/tasks/binary_updates.py`

1. Resolves binary paths using `_resolve_binary()`
2. Gets current versions via `--version` or `-version` flags
3. Queries external sources for latest versions
4. Compares versions and stores results in `SystemSetting`
5. Creates notifications for all admin users if updates found

### Update Script

The "Update Binaries" button executes:

```bash
bash scripts/install_local_binaries.sh
```

This script:
- Downloads latest ffmpeg static build
- Downloads latest yt-dlp release
- Installs to `./bin/` directory
- Sets executable permissions

## Security Notes

- Update checks query public APIs (GitHub, ffmpeg.org) - no authentication required
- Update script downloads from official sources only
- Admin role required to view/trigger updates
- Update process has 5-minute timeout to prevent hangs

## Troubleshooting

### No Updates Showing

- Check Celery beat is running
- Manually trigger check from maintenance page
- Check logs for API errors (GitHub rate limiting, network issues)

### Update Failed

- Check `scripts/install_local_binaries.sh` exists and is executable
- Review error message in flash notification
- Check disk space and write permissions for `./bin/` directory
- Check network connectivity for downloads

### Version Detection Issues

- Ensure binaries are executable and in PATH or `./bin/`
- Check binary paths in `/admin/config?section=binaries`
- Review structlog output for detailed error messages

## Future Enhancements

Potential improvements:
- Changelog/release notes display
- Selective binary updates (choose which to update)
- Rollback to previous versions
- Update scheduling (choose when to auto-update)
- Email notifications in addition to in-app
