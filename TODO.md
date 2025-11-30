# ClippyFront Roadmap
*Last Updated: 2025-11-29*

## 🎉 v1.0.0 Released!

**Production-ready milestone achieved** with 75% of original TODO completed (9/12 tasks). All critical, high, and medium priority features are complete. See `CHANGELOG.md` for full v1.0.0 release notes.

---

## 🚀 Post-1.0.0 Roadmap

All remaining tasks are **low priority** enhancements for future releases. Core functionality is complete and production-ready.

### Optional Enhancements (v1.1.0+)

#### 1. Preview Video Generation - ✅ **COMPLETE**
**Description:** Generate low-resolution preview videos that reflect actual compilation output with transformations applied

**Implementation:**
- ✅ **GPU/CPU Worker Preview Rendering** - Full backend in `app/tasks/preview_video.py`
  - Renders 480p 10fps preview video using `compile_video_v2` with `preview_mode=True`
  - Applies same filters/transformations as final compilation (portrait crop, zoom, alignment)
  - Smart caching with staleness check (project.updated_at vs preview mtime)
  - Background task with progress updates and queue selection (gpu/cpu)
  - API endpoints: `POST /api/projects/<id>/preview` and `GET /api/projects/<id>/preview/video`
  - Worker upload support via `upload_preview()` in worker API

- ✅ **Preview Player Integration** - Fully integrated in wizard compile step
  - Automatically triggered on compile step navigation (`app/static/js/wizard/step-compile.js`)
  - Video player with inline playback (`<video>` element with controls)
  - Graceful fallback to placeholder if preview fails
  - Task polling with progress updates during generation

**Status:** Fully implemented and deployed in production. Preview auto-generates and displays in wizard step 4 (Compile).

---

#### 2. Advanced Notification Features (6-10 hours) - v1.1.0 Candidate
**Description:** Enhance the existing SSE-based notification system with additional features

**Features:**
1. **Email Notifications** - ✅ **COMPLETE**
   - ✅ Full SMTP implementation in `app/mailer.py` with TLS/SSL support
   - ✅ Send emails for: compilation complete/failed, team member added, project shared
   - ✅ User preference toggles (per-event-type) with UI in account settings
   - ✅ Daily digest option with time selection (00:00-23:00)
   - ✅ Fully integrated with notification system via `send_email_notification()`
   - ℹ️ Requires SMTP configuration in .env (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD)

2. **Notification Preferences** (2 hours) - ✅ **COMPLETE**
   - ✅ Per-event-type enable/disable (6 event types)
   - ✅ Email vs. in-app settings
   - ✅ Frequency controls (daily/weekly digest)
   - ✅ Full UI in account settings with real-time save

3. **Dedicated Notification Page** - ✅ **COMPLETE**
   - ✅ Full-page view at `/notifications` with clean UI
   - ✅ Pagination (20 per page) with page navigation
   - ✅ Filter by type (all event types) with badge chips
   - ✅ Filter by read/unread status
   - ✅ Filter by date range (today, week, month, 3 months, all time)
   - ✅ Search functionality via type/status filters
   - ✅ Bulk select with checkboxes
   - ✅ Bulk mark as read action (`/api/notifications/bulk-mark-read`)
   - ✅ Bulk delete action (`/api/notifications/bulk-delete`)
   - ✅ Individual notification actions (mark read, delete)
   - ✅ "View All" link in navbar dropdown
   - ✅ Real-time date formatting (relative times)
   - ✅ Empty states and loading indicators

4. **Actionable Notifications** - ✅ **COMPLETE**
   - ✅ Contextual action buttons based on notification type
   - ✅ "View Project" button for compilation completed/failed notifications
   - ✅ "Go to Team" button for member added notifications
   - ✅ "See Details" button for project shared notifications
   - ✅ "View Invitation" button for invitation received notifications
   - ✅ Buttons integrated in both dropdown and full page views
   - ✅ Inline actions without leaving current page
   - ✅ Automatic redirect to relevant context pages

5. **Browser Push Notifications** - ✅ **COMPLETE**
   - ✅ Service worker (`app/static/sw.js`) for handling push events
   - ✅ Push notification JavaScript module (`app/static/js/push-notifications.js`)
   - ✅ `PushSubscription` model for storing user device subscriptions
   - ✅ API endpoints: `/api/push/subscribe`, `/api/push/unsubscribe`, `/api/push/subscriptions`
   - ✅ Push sending utility (`app/push.py`) using pywebpush library
   - ✅ Integrated with notification system - auto-sends push on all notification types
   - ✅ VAPID key configuration (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_EMAIL`)
   - ✅ UI in account settings for enabling/disabling push notifications
   - ✅ Automatic cleanup of expired/invalid subscriptions
   - ✅ Support for contextual actions (click notification → navigate to project/team)
   - ✅ User agent tracking for managing multiple devices
   - ⚠️ Requires: `pip install pywebpush py-vapid` and VAPID key generation

6. **Retention Policy** - ✅ **COMPLETE**
   - ✅ Scheduled Celery Beat task (`cleanup_old_notifications_task`)
   - ✅ Auto-delete read notifications older than retention period
   - ✅ Configurable retention period via `NOTIFICATION_RETENTION_DAYS` (default: 30 days)
   - ✅ Unread notifications never deleted (preserves important information)
   - ✅ Runs daily at midnight to prevent database growth
   - ✅ Structured logging with cleanup statistics
   - ✅ Task registered in Celery beat schedule

**Current State:** All Advanced Notification features **complete**! Real-time SSE notifications with navbar dropdown, polling fallback, full notification preferences UI, complete email notification system (SMTP integration, per-event toggles, digest support), dedicated notification page with filtering/pagination/bulk actions, actionable notification buttons, automatic cleanup of old notifications, and **browser push notifications** for offline/background alerts.

---

## 📊 Effort Summary

| Enhancement | Estimated Time | Target Release |
|-------------|----------------|----------------|
| Preview Video Generation | ✅ Complete | v1.0.0 |
| Advanced Notifications | ✅ Complete | v1.0.0 |
| Advanced Team Features | 12-16 hours | v1.2.0 |
| Tag System Enhancements | 6-8 hours | v1.3.0 |
| **TOTAL REMAINING** | **18-24 hours** | **Q1 2026** |

---

## ✅ Completed in v1.0.0

### Critical Priority (4/4) ✅
1. ✅ Type annotations (SQLAlchemy 2.0 migration)
2. ✅ Email invitation sending
3. ✅ Email verification for email changes
4. ✅ Project templates verification

### High Priority (1/1) ✅
1. ✅ Discord route enhancement with reaction-based curation

### Medium Priority (3/3) ✅
1. ✅ SSE notification system
2. ✅ Worker documentation updates
3. ✅ Test coverage completion

### Low Priority (1/4) ✅
1. ✅ Performance - Redis caching implementation

**Total Completed:** 9/12 tasks (75%)

---

## 🎯 Implementation Priority

### Recommended Order
1. **v1.1.0** - Preview Video Generation + Advanced Notifications (highest user impact)
2. **v1.2.0** - Advanced Team Features (enterprise adoption)
3. **v1.3.0** - Tag System Enhancements (power user workflows)

### Release Cadence
- Minor releases (v1.x.0) every 4-6 weeks
- Patch releases (v1.x.y) as needed for bug fixes
- Feature freeze 1 week before each minor release

---

## 🚫 Out of Scope

The following features are **not planned** for ClippyFront:

- ❌ Video editing features (trim/split/effects) - Use external tools
- ❌ Real-time collaboration (simultaneous editing) - Too complex for current scope
- ❌ Mobile native app - Web responsive design is sufficient
- ❌ AI-powered features - Not core requirement
- ❌ Live streaming integration - Different use case

---

## 📝 Notes

- All estimates assume familiarity with codebase
- Prioritize based on user feedback and usage patterns
- Each enhancement is independent and can be implemented separately
- Core functionality is complete - these are optional improvements
- See `CHANGELOG.md` for complete v1.0.0 implementation details

---

## 🔗 Related Documentation

- **CHANGELOG.md** - Full release history and v1.0.0 details
- **IMPLEMENTATION_SUMMARY.md** - Technical implementation overview (to be archived)
- **CONTRIBUTING.md** - Development guidelines
- **docs/** - Comprehensive documentation for all features
