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

### 2. Discord Route Enhancement (4-6 hours) - NEXT UP
**Location:** Project Wizard, `app/api/routes.py`, `app/integrations/discord.py`
**Current State:** Discord route exists but lacks community curation workflow
**Issue:** Need to leverage Discord as a curation layer for Twitch clips
**Workflow:**
1. Community posts Twitch clip URLs in specified Discord channel
2. Users react with emojis to curate best clips
3. ClippyFront reads channel messages, filters by reaction count
4. Downloads clips from Twitch using extracted URLs

**Implementation Tasks:**
- [ ] **Wizard UI Updates** (1 hour)
  - Show Discord-specific parameters when Discord route selected
  - Add "Minimum Reactions" number input (default: 1)
  - Add "Reaction Emoji" filter (optional, e.g., 👍, ⭐, 🔥)
  - Show/hide parameters based on route selection
- [ ] **Discord Integration Enhancement** (2-3 hours)
  - Extend `app/integrations/discord.py` to fetch message reactions
  - Filter messages by reaction count threshold
  - Extract Twitch clip URLs from message content
  - Handle various URL formats (clips.twitch.tv, twitch.tv/*/clip/*)
- [ ] **API Endpoint Updates** (1 hour)
  - Update `POST /api/discord/messages` to accept reaction filters
  - Add validation for min_reactions parameter
  - Return reaction counts with clip data
- [ ] **URL Extraction Logic** (30 minutes)
  - Regex patterns for Twitch clip URLs in Discord messages
  - Handle multiple URLs per message
  - Validate extracted URLs before queuing downloads

**Testing:**
- Create Discord channel with test messages
- Add reactions to messages
- Test wizard with various min_reactions thresholds
- Verify only clips meeting reaction threshold are downloaded
- Test with different emoji types

**Benefits:**
- Community-curated content (higher quality)
- Reduced manual clip selection time
- Leverages existing Discord community engagement
- Natural spam/low-quality clip filtering

### 3. Email Invitation Sending (30 minutes) - ✅ ALREADY DONE
**Location:** `app/api/teams.py` - `POST /api/teams/<id>/invitations`
**Status:** ✅ Feature already implemented and working correctly
**Verification:** Email sending occurs at line 987, error handling at line 993

### 4. Email Verification for Email Changes (20 minutes) - ✅ COMPLETED
**Location:** `app/auth/routes.py` line 803
**Status:** ✅ Fully implemented with migration and verification route
**Implementation:**
- Migration `c9e5d7f8a1b2` adds `email_verification_token`, `pending_email` columns
- `generate_email_verification_token()` creates secure token
- `verify_email_verification_token()` validates token (24 hour expiry)
- `/verify-email/<token>` route completes email change
- Email sent to new address before change applied

### 5. Verify Project Templates Implementation (10 minutes) - ✅ VERIFIED
**Status:** ✅ Templates feature fully implemented and working
**Verification Results:**
- Migration `9d86f89dd601_add_is_template_to_compilationtask.py` exists
- All 7 `/api/templates` endpoints functional (GET, POST, PUT, DELETE, apply)
- UI route `/templates` exists and loads without errors
- Module imports successfully, no linting errors

---

## 🟢 MEDIUM PRIORITY - Enhancements

### 6. Notification System SSE Upgrade (2 hours)
**Current:** 30-second polling in navbar bell icon
**Available:** SSE endpoint at `/api/notifications/stream` (just fixed!)
**Upgrade Path:**
1. Replace polling with `EventSource` in `base.html`
2. Listen for SSE events
3. Update badge count in real-time
4. Update dropdown list on new notifications
5. Fallback to polling if SSE connection fails
**Benefits:**
- Instant notification delivery (no 30s delay)
- Reduced server load (no constant polling)
- Better UX (immediate feedback)

### 7. Test Coverage Completion (8-12 hours)
**Missing Unit Tests:**
- [ ] Preset application logic (`test_presets.py`)
- [ ] Template creation/application (`test_templates.py`)
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

### 7. Worker Documentation Updates (1-2 hours)
**Location:** `docs/WORKER_API_MIGRATION.md`
**Remaining TODOs (line 244):**
- Document Phase 5 cleanup process
- Update `.env.worker.example` to remove DATABASE_URL
- Add troubleshooting section for API-only workers
- Document rollback procedure if needed
- Add performance comparison (before/after metrics)

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
| 🟡 High | 1 | 0 | 1 | 4-6 hours |
| 🟢 Medium | 3 | 0 | 3 | ~12 hours |
| 🔵 Low | 4 | 0 | 4 | ~30 hours |
| **TOTAL** | **12** | **4** | **8** | **~42 hours remaining** |

---

## 🎯 Recommended Implementation Order

### ✅ Sprint 1: Critical Fixes (1 hour) - COMPLETED 2025-11-21
1. ✅ Type annotations (5 min) - Fixed all 20 errors in app/activity.py
2. ✅ Email invitation sending (0 min) - Already implemented
3. ✅ Email verification (35 min) - Migration + route + methods added
4. ✅ Verify templates (10 min) - Confirmed working

### Sprint 2: Discord Enhancement (4-6 hours)
5. Discord route with reaction-based curation (4-6 hours)

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
