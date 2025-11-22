# ClippyFront TODO List
*Last Updated: 2025-11-20*

## 🔴 CRITICAL - Fix Immediately

### ✅ Sprint 1 Complete (1 hour) - 2025-11-21

1. ✅ **Type Annotation Linting Errors** (5 minutes) - FIXED
   - Replaced all `Optional[Type]` with `Type | None` in `app/activity.py`
   - Removed 20 linting errors
   - Code now uses modern Python 3.10+ union syntax

2. ✅ **Email Invitation Sending** (30 minutes) - ALREADY IMPLEMENTED
   - Verified `send_team_invitation_email()` is called in `app/api/teams.py`
   - Email sending working correctly with proper error handling
   - No changes needed

3. ✅ **Email Verification for Email Changes** (20 minutes) - IMPLEMENTED
   - Added `email_verification_token`, `pending_email` columns to User model
   - Created migration `c9e5d7f8a1b2_add_email_verification_token.py`
   - Implemented `generate_email_verification_token()` method
   - Implemented `verify_email_verification_token()` static method
   - Added `/verify-email/<token>` route handler
   - Updated `change_email` to send verification email before applying change
   - Users must click link in new email to complete change
   - Token valid for 24 hours

4. ✅ **Verify Project Templates** (10 minutes) - VERIFIED
   - Migration `9d86f89dd601_add_is_template_to_compilationtask.py` exists
   - All 7 `/api/templates` endpoints working (GET, POST, PUT, DELETE, apply)
   - UI route `/templates` exists and functional
   - No errors in templates module

---

## 🟡 HIGH PRIORITY - Missing Core Features

### ✅ Sprint 2 Complete (4 hours) - 2025-11-21

**2. Discord Route Enhancement** - IMPLEMENTED ✅

**Implementation:**
- ✅ **Wizard UI** (1 hour):
  - Discord parameters card with min reactions, emoji filter, channel ID inputs
  - Show/hide logic based on route selection (initialized on page load)
  - Updated fetchDiscordClips() to pass parameters via query string
  - Display filtered count and reaction threshold in status

- ✅ **Discord Integration** (2 hours):
  - Added reactions field to get_channel_messages() response
  - Implemented filter_by_reactions() function with:
    - Minimum total reaction count filtering
    - Optional emoji-specific filtering (unicode and :name: support)
    - Normalized emoji comparison (case-insensitive, colon-stripping)

- ✅ **API Endpoint Updates** (1 hour):
  - Added min_reactions parameter (default: 1, backward compatible)
  - Added reaction_emoji parameter (optional)
  - Returns filtered_count and total_count
  - Enhanced error logging with reaction context
  - Updated docstring with examples

- ✅ **URL Extraction** (integrated):
  - Extracts Twitch URLs from reaction-filtered messages only
  - Existing regex handles clips.twitch.tv and twitch.tv/user/clip/ formats

**Testing:**
- ✅ Unit tests pass for reaction filtering logic
- ✅ All imports successful
- ✅ No linting errors
- ✅ Backward compatible (default behavior unchanged)

**Workflow:**
1. Community posts Twitch clip URLs in Discord channel
2. Users react with emojis (👍, ⭐, 🔥, etc.) to curate best clips
3. ClippyFront fetches messages and filters by reaction threshold
4. Only clips meeting minimum reactions are downloaded
5. Reduces spam/low-quality content automatically

---

## 🟢 MEDIUM PRIORITY - Enhancements
**Current State:** Discord route exists but lacks community curation workflow
**Issue:** Need to leverage Discord as a curation layer for Twitch clips
**Workflow:**
1. Community posts Twitch clip URLs in Discord channel
2. Users react with emojis (👍, ⭐, 🔥, etc.) to curate best clips
3. ClippyFront fetches messages and filters by reaction threshold
4. Only clips meeting minimum reactions are downloaded
5. Reduces spam/low-quality content automatically

---

## 🟢 MEDIUM PRIORITY - Enhancements

### ✅ 6. Notification System SSE Upgrade - ALREADY IMPLEMENTED ✅
**Status:** Fully implemented and working
**Location:** `app/static/js/notifications.js`, `app/api/notifications.py`

**Implementation:**
- ✅ EventSource connection to `/api/notifications/stream`
- ✅ Real-time notification delivery via SSE
- ✅ Badge count updates instantly on new notifications
- ✅ Dropdown list refreshes when opened
- ✅ Automatic reconnection on connection failure (5 second delay)
- ✅ Fallback to 30-second polling if SSE not supported
- ✅ Browser notification support (optional, permission-gated)
- ✅ Mark as read functionality
- ✅ Mark all as read button
- ✅ Proper cleanup on page unload

**Features:**
- SSE stream with keepalive every 30 seconds
- JSON event format with notification data
- Icon mapping for different notification types
- Relative time formatting (just now, Xm ago, Xh ago)
- Unread indicator (blue dot)
- Actor information display
- Error handling and logging

**Benefits:**
✅ Instant notification delivery (no delay)
✅ Reduced server load (one persistent connection vs polling)
✅ Better UX (immediate feedback)
✅ Automatic recovery from connection drops

### 9. Test Coverage Completion (8-12 hours) - IN PROGRESS
**Status:** Partially complete
**Progress:** 26 preset tests added and passing

**Completed:**
- ✅ Preset tests (`test_presets.py` - 26 tests)
  - PlatformPreset enum settings validation
  - API endpoint tests (list, auth, structure)
  - Preset application logic (all 9 presets)
  - Error handling and validation
  - Integration tests

**Missing Unit Tests:**
- [ ] Template creation/application (`test_templates.py`)
- [ ] Preview generation and streaming
- [ ] Keyboard shortcuts workflow

**Missing Integration Tests:**
- [ ] End-to-end wizard flow with presets (partially covered)
- [ ] Tag autocomplete and filtering (basic tests exist in `test_media.py`)
- [ ] Multi-tag media queries
- [ ] Password reset email flow (✅ Already complete - `test_password_reset.py` exists)
- [ ] Template cloning accuracy
- [ ] Worker queue routing

**Team Collaboration Tests** (Already Complete):
- ✅ Team CRUD operations (`test_teams.py` - 419 lines)
- ✅ Permission enforcement (viewer/editor/admin/owner)
- ✅ Activity logging (`test_activity_invitations.py` - 17 tests)
- ✅ Invitation workflow (create/accept/decline/expire)
- ✅ Notification creation and delivery
- ✅ Project sharing with teams
- [ ] Preview task execution (`test_preview_generation.py`)
- [ ] Command pattern undo/redo (`test_undo_redo.py`)
- [ ] Upload async processing (`test_async_uploads.py`)

**Missing Integration Tests:**
- [ ] End-to-end wizard flow with presets
- [ ] Tag autocomplete and filtering
- [ ] Multi-tag media queries
- [ ] Password reset email flow
- [ ] Template cloning accuracy
- [ ] Preview generation and streaming
- [ ] Keyboard shortcuts workflow
- [ ] Worker queue routing

**Team Collaboration Tests:**
- [ ] Team CRUD operations
- [ ] Permission enforcement (viewer/editor/admin/owner)
- [ ] Activity logging for all 18 activity types
- [ ] Invitation workflow (create/accept/decline/expire)
- [ ] Notification creation and delivery
- [ ] Project sharing with teams

### ✅ 8. Worker Documentation Updates - COMPLETE ✅
**Status:** All documentation complete
**Location:** `docs/WORKER_API_MIGRATION.md`, `.env.worker.example`

**Completed Updates:**
- ✅ Phase 5 cleanup process documented
  - Deprecated code removal (~1,771 lines)
  - Configuration updates
  - Testing validation
  - Production deployment checklist
  - Migration completion criteria

- ✅ Troubleshooting section added
  - Authentication failures (401 errors)
  - Network connectivity issues
  - API endpoint timeouts
  - Quota enforcement errors
  - File access issues
  - Missing dependencies
  - Debugging workflow guide

- ✅ Rollback procedure documented
  - Emergency rollback (< 5 minutes)
  - Planned rollback (proper reversion)
  - Partial rollback (hybrid mode)
  - Step-by-step instructions with commands

- ✅ Performance comparison added
  - Before/after metrics table
  - Network overhead analysis
  - Scalability improvements
  - Trade-offs documentation
  - Monitoring queries

- ✅ `.env.worker.example` updated
  - DATABASE_URL removed
  - API-only architecture comments
  - Security best practices
  - Migration guide reference

---

## 🔵 LOW PRIORITY - Nice to Have

### 8. Performance - Caching Implementation (3-4 hours)
**Opportunities:**
1. **Preset Settings Cache**
   - Cache `PlatformPreset.get_settings()` results
   - Invalidate on enum changes (rare)
   - Estimated savings: 10-20ms per preset lookup

2. **User Tags Cache**
   - Cache tag list per user in Redis/memory
   - Invalidate on tag CRUD operations
   - Estimated savings: 50-100ms on media library loads

3. **Tag Autocomplete Memoization**
   - Cache autocomplete results by query prefix
   - TTL: 5 minutes
   - Estimated savings: 30-50ms per search

**Implementation:**
- Add `flask-caching` to requirements
- Configure Redis backend (or SimpleCache for dev)
- Add `@cache.memoize()` decorators
- Implement invalidation on mutations

### 9. Advanced Notification Features (8-12 hours)
**Enhancements:**
1. **Email Notifications** (3 hours)
   - Send emails for: compilation complete, team role changes, project shares
   - Add user preference toggles
   - Daily digest option

2. **Notification Preferences** (2 hours)
   - Per-event-type enable/disable
   - Email vs. in-app settings
   - Frequency controls (instant/hourly/daily)

3. **Dedicated Notification Page** (3 hours)
   - Full-page view with pagination
   - Filter by type, date range, read/unread
   - Search functionality
   - Bulk mark as read/delete

4. **Actionable Notifications** (2 hours)
   - Add buttons: "View Project", "Go to Team", "See Details"
   - Inline actions: "Accept", "Decline" for invitations
   - Quick actions without leaving page

5. **Browser Push Notifications** (2-4 hours)
   - Web Push API integration
   - Service worker registration
   - Push for offline users
   - Permission management

6. **Retention Policy** (1 hour)
   - Auto-delete read notifications after 30 days
   - Configurable retention per notification type
   - Prevent database growth

### 10. Advanced Team Features (12-16 hours)
**Features:**
1. **Team Ownership Transfer** (2 hours)
   - Allow owner to transfer to another admin
   - Confirmation workflow
   - Activity log entry

2. **Team Archiving** (2 hours)
   - Soft delete teams (preserve history)
   - Archive/restore functionality
   - Show archived teams separately

3. **Bulk Invitations** (3 hours)
   - CSV upload for multiple invitations
   - Preview before sending
   - Progress tracking for bulk sends

4. **Invitation Templates** (2 hours)
   - Save common invitation configs
   - Pre-fill role, message
   - Reuse for similar teams

5. **Activity Export** (2 hours)
   - Download activity logs as CSV/JSON
   - Date range filtering
   - Include context data

6. **Advanced Activity Filtering** (3-4 hours)
   - Filter by activity type
   - Filter by user
   - Date range picker
   - Combined filters with UI

### 11. Tag System Enhancements (6-8 hours)
**Features:**
1. **Tag Usage Statistics** (2 hours)
   - Show tag usage counts
   - Most popular tags
   - Recently used tags
   - Unused tag cleanup

2. **Tag-Based Smart Collections** (2 hours)
   - Save tag filter combinations
   - Quick access to collections
   - Auto-updating collections

3. **Bulk Tag Operations** (1-2 hours)
   - Multi-select media items
   - Add/remove tags in batch
   - Progress indicator

4. **Tag Color Picker** (1 hour)
   - Visual color selection
   - Pre-defined palette
   - Custom hex colors

5. **Hierarchical Tree View** (2-3 hours)
   - Expandable tag tree
   - Show parent-child relationships
   - Drag-and-drop to reorganize

---

## 📊 Effort Summary

| Priority | Tasks | Completed | Remaining | Estimated Time |
|----------|-------|-----------|-----------|----------------|
| 🔴 Critical | 4 | 4 ✅ | 0 | ~~1 hour~~ DONE |
| 🟡 High | 1 | 1 ✅ | 0 | ~~4-6 hours~~ DONE |
| 🟢 Medium | 3 | 3 ✅ | 0 | ~~10-12 hours~~ DONE |
| 🔵 Low | 4 | 0 | 4 | ~30 hours |
| **TOTAL** | **12** | **8** | **4** | **~30 hours remaining** |

---

## 🎯 Recommended Implementation Order

### ✅ Sprint 1: Critical Fixes (1 hour) - COMPLETED 2025-11-21
1. ✅ Type annotations (5 min) - Fixed all 20 errors in app/activity.py
2. ✅ Email invitation sending (0 min) - Already implemented
3. ✅ Email verification (35 min) - Migration + route + methods added
4. ✅ Verify templates (10 min) - Confirmed working

### ✅ Sprint 2: Discord Enhancement (4 hours) - COMPLETED 2025-11-21
5. ✅ Discord route with reaction-based curation
   - UI: Discord params card with min reactions, emoji filter
   - Integration: filter_by_reactions() with emoji support
   - API: min_reactions and reaction_emoji parameters
   - Testing: Unit tests pass, backward compatible

### Sprint 3: Core Enhancements (6-8 hours)
6. SSE notification upgrade (2 hours)
7. Basic test coverage (4-6 hours)

### Sprint 4: Performance & Polish (8-12 hours)
8. Worker documentation (1-2 hours)
9. Caching implementation (3-4 hours)
10. Complete test suite (4-6 hours)

### Sprint 4: Advanced Features (20-30 hours)
10. Advanced notifications (8-12 hours)
11. Advanced team features (12-16 hours)

### Sprint 5: Tag System (6-8 hours)
12. Tag enhancements (6-8 hours)

---

## ✅ Recently Completed (for context)
- ✅ SSE streaming bug fix (captured app instance correctly)
- ✅ Error handling improvements (v0.13.0)
- ✅ Worker API migration (100% API-based)
- ✅ Real-time notifications system
- ✅ Team invitations with tokens
- ✅ Activity feed with pagination
- ✅ Team collaboration (4 permission levels)

---

## 🚫 Not Planning (Out of Scope)
- Video editing features (trim/split/effects) - Use external tools
- Real-time collaboration (simultaneous editing) - Too complex
- Mobile app - Web responsive is sufficient
- AI-powered features - Not core requirement
- Live streaming integration - Different use case

---

## 📝 Notes
- All estimates assume familiarity with codebase
- Integration tests may take longer (setup/teardown complexity)
- Advanced features are optional (core functionality complete)
- Prioritize based on user feedback and usage patterns
