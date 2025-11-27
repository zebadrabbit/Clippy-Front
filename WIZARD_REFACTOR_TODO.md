# Wizard Refactor TODO

## Phase 1: Core & Setup Step ✓
- [x] Create refactoring plan (REFACTOR_WIZARD.md)
- [x] Create directory structure (app/static/js/wizard/, app/templates/main/wizard/)
- [x] Create core.js (state management, navigation, API helpers)
- [x] Extract Step 1 HTML to step_setup.html
- [x] Create step-setup.js (form submission, validation)
- [x] Add USE_NEW_WIZARD feature flag
- [ ] Test Step 1 in isolation

## Phase 2: Clips Step ✓
- [x] Extract Step 2 HTML to step_clips.html
- [x] Create step-clips.js (fetch, download, polling)
- [x] Test Step 2 fetching and downloading
- [x] Test navigation between Step 1 ↔ Step 2

## Phase 3: Arrange Step ✓
- [x] Extract Step 3 HTML to step_arrange.html
- [x] Create step-arrange.js (DnD, media selection)
- [x] Create commands.js (undo/redo)
- [ ] Test timeline drag & drop
- [ ] Test intro/outro/transition selection
- [ ] Test navigation Step 2 ↔ Step 3

## Phase 4: Compile Step ✓
- [x] Extract Step 4 HTML to step_compile.html
- [x] Create step-compile.js (preview, compilation, progress)
- [ ] Test preview generation
- [ ] Test compilation flow
- [ ] Test celebration effect
- [ ] Test navigation Step 3 ↔ Step 4

## Phase 5: Polish ✓
- [x] Create shortcuts.js (keyboard shortcuts)
- [x] Integrate shortcuts into core.js
- [x] Add save-timeline event listener
- [ ] Add lazy-loading endpoints in routes.py (optional - already using dynamic imports)
- [ ] Integration testing across all steps
- [ ] Performance testing (lazy-load timing)

## Phase 6: Database Persistence & Resumability 🎯 ✓
### Database Changes
- [x] Add `wizard_step` column to projects table (INTEGER, default 1)
- [x] Add `wizard_state` column to projects table (TEXT/JSON, nullable)
- [x] Add `READY` status to ProjectStatus enum
- [x] Create Alembic migration
- [ ] Backfill existing projects with sensible defaults (run migration)

### API Updates
- [x] Add `PATCH /api/projects/<id>/wizard` endpoint
  - Update wizard_step
  - Update wizard_state
  - Update status (DRAFT → READY transition)
- [ ] Update `POST /api/projects` to set wizard_step=1, status=DRAFT (already defaults)
- [ ] Update `POST /api/projects/<id>/clips/order` to set wizard_step=3 (optional)
- [ ] Update `POST /api/projects/<id>/compile` to require status=READY (optional)
- [ ] Add validation: can't compile if status != READY (optional)

### Auto-save Integration
- [x] core.js: Save wizard_step on navigation (saveWizardStep method)
- [x] core.js: Add saveWizardState method for step state
- [x] core.js: Add markReady method (set status=READY, wizard_step=4)
- [x] core.js: Call onExit hook before navigation
- [ ] step-setup.js: Save wizard_step=2 on project creation (optional)
- [ ] step-clips.js: Save wizard_step=3 when downloads complete (optional)
- [ ] step-arrange.js: Save timeline on every change (already exists via saveTimelineOrder)
- [ ] step-arrange.js: Add "Ready to Compile" button → markReady (optional enhancement)
- [ ] step-compile.js: Set status=PROCESSING when compilation starts (optional)

### UI Updates
- [ ] Update projects list template
  - Show status badge: "Draft: Step X/4" | "Ready to Compile" | "Compiling..." | "Completed"
  - Add filter tabs: All / Drafts / Ready / Completed
  - Add "Resume" button for draft projects
  - Add "Compile Now" button for ready projects
- [ ] Update wizard template
  - Show "Resuming from Step X" message when loading existing project
  - Show autosave indicator
- [ ] Add confirmation dialog before navigating away from wizard with unsaved changes

### Testing
- [ ] Test: Create project → navigate away → resume from correct step
- [ ] Test: Step 1 → exit → resume → all form values restored
- [ ] Test: Step 3 → arrange timeline → exit → resume → timeline preserved
- [ ] Test: Mark project ready → navigate away → "Compile Now" button works
- [ ] Test: Start compilation → refresh page → still shows "Compiling..."
- [ ] Test: Projects list filters work (Drafts / Ready / Completed)
- [ ] Test: Old projects backfilled correctly

## Phase 7: Migration & Cleanup
- [ ] Add feature flag for old vs new wizard
- [ ] Run both systems in parallel (A/B test)
- [ ] Fix any bugs discovered in testing
- [ ] Remove old wizard.js (2600 lines → 0!)
- [ ] Remove unused templates
- [ ] Update documentation

## Success Criteria
- [x] Refactoring plan documented ✓
- [ ] wizard.js reduced from 2600 lines to ~100 lines (core only)
- [ ] Each step module < 400 lines
- [ ] HTML lives in templates, not JavaScript
- [ ] Preview feature works cleanly in step-compile.js
- [ ] Wizard is fully resumable - users can exit/resume at any step
- [ ] Project status clearly indicates wizard progress
- [ ] Projects list shows which step users are on
- [ ] Timeline auto-saves on every change
- [ ] No functionality lost from old wizard
- [ ] All tests passing

## Notes
- Keep old wizard.js working during migration
- Test each phase independently
- Focus on template-first approach
- Lazy-load for performance
- Clean separation of concerns
- Database persistence ensures users never lose work
