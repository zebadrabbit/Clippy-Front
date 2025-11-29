# ClippyFront Roadmap
*Last Updated: 2025-11-22*

## 🎉 v1.0.0 Released!

**Production-ready milestone achieved** with 75% of original TODO completed (9/12 tasks). All critical, high, and medium priority features are complete. See `CHANGELOG.md` for full v1.0.0 release notes.

---

## 🚀 Post-1.0.0 Roadmap

All remaining tasks are **low priority** enhancements for future releases. Core functionality is complete and production-ready.

### Optional Enhancements (v1.1.0+)

#### 1. Preview Video Generation (4-6 hours) - v1.1.0 Candidate
**Description:** Generate low-resolution preview videos that reflect actual compilation output with transformations applied

**Features:**
1. **GPU/CPU Worker Preview Rendering** (3-4 hours)
   - Render 480p 10fps preview video on worker
   - Apply same filters/transformations as final compilation (portrait crop, zoom, etc.)
   - Cache previews for fast subsequent loads
   - Background task with progress indicator

2. **Preview Player Integration** (1-2 hours)
   - Replace static thumbnail with video player
   - Inline playback in compile step
   - Seek controls for quick scrubbing
   - Fallback to static thumbnail if preview fails

**Current State:** Static thumbnail preview showing random frame from random clip (original orientation, no transformations)

---

#### 2. Advanced Notification Features (6-10 hours) - v1.1.0 Candidate
**Description:** Enhance the existing SSE-based notification system with additional features

**Features:**
1. **Email Notifications** (3 hours) - ✅ **PARTIALLY COMPLETE**
   - ✅ Send emails for: compilation complete, team role changes, project shares
   - ✅ User preference toggles (per-event-type)
   - ✅ Daily digest option with time selection
   - ⚠️ Email sending implementation needs SMTP configuration

2. **Notification Preferences** (2 hours) - ✅ **COMPLETE**
   - ✅ Per-event-type enable/disable (6 event types)
   - ✅ Email vs. in-app settings
   - ✅ Frequency controls (daily/weekly digest)
   - ✅ Full UI in account settings with real-time save

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

**Current State:** Real-time SSE notifications working with navbar dropdown, polling fallback, and **full notification preferences UI complete** (email toggles, digest settings, in-app controls)

---

#### 2. Advanced Team Features (12-16 hours) - v1.2.0 Candidate
**Description:** Extend team collaboration with enterprise features

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

**Current State:** Full team collaboration with 4 permission levels, activity feeds, and token-based invitations

---

#### 3. Tag System Enhancements (6-8 hours) - v1.3.0 Candidate
**Description:** Advanced tag features for power users

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

**Current State:** Hierarchical tags with autocomplete, filtering, and color coding

---

## 📊 Effort Summary

| Enhancement | Estimated Time | Target Release |
|-------------|----------------|----------------|
| Preview Video Generation | 4-6 hours | v1.1.0 |
| Advanced Notifications | 8-12 hours | v1.1.0 |
| Advanced Team Features | 12-16 hours | v1.2.0 |
| Tag System Enhancements | 6-8 hours | v1.3.0 |
| **TOTAL** | **30-42 hours** | **Q1 2026** |

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
