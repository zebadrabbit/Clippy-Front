# Changelog

All notable changes to ClippyFront will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **BREAKING:** Workers no longer require `DATABASE_URL` environment variable
- Worker API Migration Phase 5 complete - all workers now 100% API-based
- Removed ~1,771 lines of deprecated database-based task code

### Removed
- Deprecated `compile_video_task` (replaced by `compile_video_task_v2`)
- Deprecated `download_clip_task` (replaced by `download_clip_task_v2`)
- `get_db_session()` function (workers no longer access database directly)
- Helper functions only used by old tasks: `process_clip`, `build_timeline_with_transitions`, `process_media_file`, `compile_final_video`, `save_final_video`

### Security
- Improved worker security: workers no longer have direct database credentials
- DMZ architecture compliance: workers communicate exclusively via REST API

---

## [0.12.1] - 2025-11-19

### Added
- Worker version checking system
- Documentation reorganization
- UI improvements

### Documentation
- Added `docs/WORKER_API_MIGRATION.md` - comprehensive migration guide
- Added `docs/REMOTE_WORKER_SETUP.md` - worker deployment guide
- Added `docs/WORKER_SETUP.md` - worker configuration guide

---

_For older changes, see git history._
