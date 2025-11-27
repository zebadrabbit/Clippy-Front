# Wizard Refactoring Plan

## Problem
- wizard.js: 2600+ lines of monolithic JavaScript
- HTML generation in JS instead of templates
- All steps loaded upfront, hidden/shown with CSS
- Hard to maintain, debug, and extend
- Preview feature blocked by architectural issues

## Goals
1. Move HTML back to templates where it belongs
2. Break wizard.js into focused, modular files
3. Lazy-load step content when needed
4. Clear separation of concerns
5. Make preview implementation straightforward
6. **Make wizard fully resumable at any step** - save progress to database
7. **Track project readiness state** - distinguish between drafts and ready-to-compile

## Architecture

### File Structure
```
app/static/js/wizard/
├── core.js           # Wizard state, navigation, API helpers (~200 lines)
├── step-setup.js     # Step 1: Project setup form (~150 lines)
├── step-clips.js     # Step 2: Fetch/download clips (~200 lines)
├── step-arrange.js   # Step 3: Timeline DnD, media selection (~400 lines)
├── step-compile.js   # Step 4: Compilation, preview, progress (~200 lines)
├── commands.js       # Undo/redo command pattern (~150 lines)
└── shortcuts.js      # Keyboard shortcuts (~100 lines)
```

### Template Structure
```
app/templates/main/wizard/
├── base.html              # Wizard chrome, chevrons, navigation
├── step_setup.html        # Step 1 form (included via {% include %})
├── step_clips.html        # Step 2 fetch UI
├── step_arrange.html      # Step 3 timeline + media library
└── step_compile.html      # Step 4 summary + compile controls
```

### Loading Strategy
- **Initial load**: base.html + core.js + current step
- **Navigation**: Lazy-load step HTML + JS module on demand
- **State**: Minimal wizard state object in localStorage
- **API**: RESTful endpoints, no more giant payload objects

## Phase 1: Extract Core & Setup Step
1. Create `app/static/js/wizard/core.js`
   - Wizard state object
   - Navigation (gotoStep)
   - API helper (fetch wrapper)
   - Chevron marking

2. Create `app/templates/main/wizard/step_setup.html`
   - Move Step 1 HTML from wizard.html
   - Platform preset form
   - Audio normalization controls
   - Vertical video settings

3. Create `app/static/js/wizard/step-setup.js`
   - Form submission
   - Preset selection logic
   - Audio slider interactions
   - Validation

## Phase 2: Clips Step
1. Create `app/templates/main/wizard/step_clips.html`
   - Fetch progress UI
   - Step indicators
   - Discord/Twitch forms

2. Create `app/static/js/wizard/step-clips.js`
   - Twitch/Discord fetchers
   - Download queue management
   - Progress polling

## Phase 3: Arrange Step
1. Create `app/templates/main/wizard/step_arrange.html`
   - Timeline container (server-rendered clip cards)
   - Media library tabs (intro/outro/transitions/music)
   - Downloaded clips grid

2. Create `app/static/js/wizard/step-arrange.js`
   - Drag & drop handlers
   - Media selection
   - Timeline order persistence

3. Create `app/static/js/wizard/commands.js`
   - Command pattern for undo/redo
   - MoveClipCommand
   - AddClipCommand
   - RemoveClipCommand

## Phase 4: Compile Step
1. Create `app/templates/main/wizard/step_compile.html`
   - Compilation summary (server-rendered from project data)
   - Preview container
   - Progress bar
   - Compile log

2. Create `app/static/js/wizard/step-compile.js`
   - Preview generation trigger
   - Task polling
   - Progress animation
   - Celebration effect

## Phase 5: Polish
1. Create `app/static/js/wizard/shortcuts.js`
   - Keyboard shortcuts
   - Isolated from step logic

2. Update `app/main/routes.py`
   - Add endpoints for lazy-loading step HTML fragments
   - `/wizard/step/<int:step>` returns partial HTML

3. Testing
   - Each module independently testable
   - Clear interfaces between components

## Phase 6: Database Persistence & Resumability
1. **Extend Project model** (`app/models.py`)
   - Add `wizard_step` field (INTEGER, default 1) - tracks which step user is on
   - Add `wizard_state` field (TEXT/JSON) - serialized wizard state (optional metadata)
   - Update `ProjectStatus` enum (currently has DRAFT, PROCESSING, COMPLETED, FAILED):
     - Keep `DRAFT` → User creating/editing, not ready to compile
     - Add `READY` → Timeline arranged, ready to compile (between DRAFT and PROCESSING)
     - Keep `PROCESSING` → Compilation in progress
     - Keep `COMPLETED` → Compilation finished
     - Keep `FAILED` → Compilation failed

2. **Auto-save at each step**
   - Step 1 (Setup): Save on project creation → `wizard_step=1`, `status=DRAFT`
   - Step 2 (Clips): Save after downloads complete → `wizard_step=2`, `status=DRAFT`
   - Step 3 (Arrange): Save timeline on every change → `wizard_step=3`, `status=DRAFT`
   - Step 3 (Arrange → Compile): Mark `status=READY` when user confirms timeline
   - Step 4 (Compile): Update to `status=PROCESSING` when compilation starts

3. **Update API endpoints**
   - `POST /api/projects` → Set `wizard_step=1`, `status=DRAFT`
   - `POST /api/projects/<id>/clips/order` → Set `wizard_step=3`, save timeline
   - `POST /api/projects/<id>/compile` → Require `status=READY`, set `status=PROCESSING`
   - `PATCH /api/projects/<id>/wizard` → Update wizard_step, wizard_state

4. **Update projects list view**
   - Show badge: "Draft: Step 2/4" or "Ready to Compile" or "Compiling..." or "Completed"
   - Add filter tabs: All / Drafts / Ready / Completed
   - Quick resume button: "Continue from Step 3" → `/wizard?project_id=<id>`

5. **Migration**
   - Create Alembic migration for new columns
   - Backfill existing projects:
     - `wizard_step=4` for completed projects
     - `wizard_step=3` for projects with clips
     - `wizard_step=1` otherwise
     - `status=COMPLETED` if output_filename exists
     - `status=DRAFT` otherwise

## Benefits
- **Maintainability**: Find code easily, ~200-400 lines per file
- **Performance**: Lazy-load only what's needed
- **Debuggability**: Isolated concerns, clear stack traces
- **Extensibility**: Add new steps without touching others
- **Template-first**: HTML where it belongs, JS for behavior
- **Preview**: Clean integration point in step-compile.js

## Migration Strategy
1. Keep old wizard.js working
2. Build new modules alongside
3. Feature-flag switch between old/new
4. Test thoroughly
5. Remove old wizard.js

## Timeline
- Phase 1: 2 hours
- Phase 2: 1 hour
- Phase 3: 3 hours
- Phase 4: 1 hour
- Phase 5: 1 hour
- Phase 6: 2 hours (database + UI updates)
- **Total: ~10 hours** for complete refactor with resumability

## Resumability Design Details

### Database Schema Changes
```sql
ALTER TABLE projects ADD COLUMN wizard_step INTEGER DEFAULT 1;
ALTER TABLE projects ADD COLUMN wizard_state TEXT;  -- JSON blob for step-specific metadata
```

### Project Status Flow
```
New Project → DRAFT (step 1)
  ↓ Setup complete
DRAFT (step 2) - Fetching clips
  ↓ Clips downloaded
DRAFT (step 3) - Arranging timeline
  ↓ User confirms "Timeline looks good"
READY (step 3) - Ready to compile
  ↓ Start compilation
PROCESSING (step 4)
  ↓ Compilation completes
COMPLETED (step 4)
```

### Projects List UI Enhancement
```html
<div class="project-card">
  <h5>Compilation of 2025-11-27</h5>

  <!-- Status badge with step indicator -->
  {% if project.status == 'DRAFT' %}
    <span class="badge bg-secondary">
      Draft: Step {{ project.wizard_step }}/4
      {% if project.wizard_step == 1 %}Setup{% endif %}
      {% if project.wizard_step == 2 %}Getting Clips{% endif %}
      {% if project.wizard_step == 3 %}Arranging{% endif %}
    </span>
    <a href="/wizard?project_id={{ project.id }}" class="btn btn-sm btn-primary">
      Resume from Step {{ project.wizard_step }}
    </a>

  {% elif project.status == 'READY' %}
    <span class="badge bg-success">Ready to Compile</span>
    <a href="/wizard?project_id={{ project.id }}&step=4" class="btn btn-sm btn-success">
      Compile Now
    </a>

  {% elif project.status == 'PROCESSING' %}
    <span class="badge bg-info">
      <span class="spinner-border spinner-border-sm"></span>
      Compiling...
    </span>

  {% elif project.status == 'COMPLETED' %}
    <span class="badge bg-dark">Completed</span>
    <a href="/projects/{{ project.public_id }}" class="btn btn-sm btn-outline-primary">
      View
    </a>
  {% endif %}
</div>
```

### Auto-save Strategy
Each step module saves its progress:

**step-setup.js**
```javascript
async onExit(wizard) {
  // Save setup complete
  await wizard.api(`/api/projects/${wizard.state.projectId}/wizard`, {
    method: 'PATCH',
    body: JSON.stringify({ wizard_step: 2, status: 'DRAFT' })
  });
}
```

**step-clips.js**
```javascript
async onDownloadsComplete(wizard) {
  await wizard.api(`/api/projects/${wizard.state.projectId}/wizard`, {
    method: 'PATCH',
    body: JSON.stringify({ wizard_step: 3, status: 'DRAFT' })
  });
}
```

**step-arrange.js**
```javascript
async onTimelineChange(wizard) {
  // Auto-save timeline order (already implemented)
  await wizard.api(`/api/projects/${wizard.state.projectId}/clips/order`, {
    method: 'POST',
    body: JSON.stringify({ clip_ids: [...] })
  });

  // Update wizard step
  await wizard.api(`/api/projects/${wizard.state.projectId}/wizard`, {
    method: 'PATCH',
    body: JSON.stringify({ wizard_step: 3 })
  });
}

async onConfirmTimeline(wizard) {
  // User clicked "Timeline looks good, ready to compile"
  await wizard.api(`/api/projects/${wizard.state.projectId}/wizard`, {
    method: 'PATCH',
    body: JSON.stringify({ wizard_step: 4, status: 'READY' })
  });
}
```

**step-compile.js**
```javascript
async onStartCompile(wizard) {
  await wizard.api(`/api/projects/${wizard.state.projectId}/wizard`, {
    method: 'PATCH',
    body: JSON.stringify({ status: 'PROCESSING' })
  });
}
```

### Resume Logic in core.js
```javascript
async loadProject(projectId) {
  const project = await this.api(`/api/projects/${projectId}`);

  this.state.projectId = projectId;
  this.state.currentStep = project.wizard_step || 1;

  // Navigate to saved step
  await this.gotoStep(this.state.currentStep);

  // Show restoration message
  this.showToast(`Resumed from ${this.getStepName(this.state.currentStep)}`, 'info');
}

getStepName(step) {
  const names = ['Setup', 'Get Clips', 'Arrange Timeline', 'Compile'];
  return names[step - 1] || 'Unknown';
}
```
