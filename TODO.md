# ClippyFront TODO List
*Last Updated: 2025-11-20*

## 🔴 CRITICAL - Fix Immediately

### 1. Type Annotation Linting Errors (5 minutes)
**Location:** `app/activity.py` (20 errors)
**Issue:** Using deprecated `Optional[Type]` instead of modern `Type | None` syntax
**Fix:**
```python
# Replace all instances of:
from typing import Optional
user: Optional[User] = None

# With:
user: User | None = None
```
**Impact:** Blocks clean linting, prevents pre-commit hooks from passing

---

## 🟡 HIGH PRIORITY - Missing Core Features

### 2. Email Invitation Sending (30 minutes)
**Location:** `app/api/teams.py` - `POST /api/teams/<id>/invitations`
**Issue:** Creates invitation tokens but doesn't send emails
**Current State:** Line 575 in IMPLEMENTATION_SUMMARY notes "TODO: Send invitation email"
**Fix Required:**
- Import `send_team_invitation_email` from `app.mailer`
- Call after creating invitation in database
- Handle email failures gracefully (log warning, don't block)
**Testing:**
- Create team invitation
- Check email received
- Verify link works

### 3. Email Verification for Email Changes (20 minutes)
**Location:** `app/auth/routes.py` line 803
**Issue:** Email change route exists but verification email not sent
**Current Code:**
```python
# TODO: Send verification email to new address
```
**Fix Required:**
- Implement `send_email_verification()` function
- Generate verification token
- Send email to new address
- Create verification route to confirm
**Testing:**
- Request email change
- Check verification email received
- Confirm new email via link

### 4. Verify Project Templates Implementation (10 minutes)
**Location:** Migrations and routes
**Issue:** Migration filename shown as placeholder `xxxx_add_project_templates.py`
**Tasks:**
- Search for actual migration file
- Verify `/api/templates` endpoints exist
- Check `/templates` UI route
- Test template creation/application flow
**If Missing:** File issue for templates feature completion

---

## 🟢 MEDIUM PRIORITY - Enhancements

### 5. Notification System SSE Upgrade (2 hours)
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

### 6. Test Coverage Completion (8-12 hours)
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

| Priority | Tasks | Estimated Time |
|----------|-------|----------------|
| 🔴 Critical | 1 | 5 minutes |
| 🟡 High | 3 | ~1 hour |
| 🟢 Medium | 3 | ~12 hours |
| 🔵 Low | 4 | ~30 hours |
| **TOTAL** | **11** | **~43 hours** |

---

## 🎯 Recommended Implementation Order

### Sprint 1: Critical Fixes (1 hour)
1. Type annotations (5 min)
2. Email invitation sending (30 min)
3. Email verification (20 min)
4. Verify templates (10 min)

### Sprint 2: Core Enhancements (6-8 hours)
5. SSE notification upgrade (2 hours)
6. Basic test coverage (4-6 hours)

### Sprint 3: Performance & Polish (8-12 hours)
7. Worker documentation (1-2 hours)
8. Caching implementation (3-4 hours)
9. Complete test suite (4-6 hours)

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
