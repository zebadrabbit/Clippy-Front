/**
 * Step 3: Arrange - Timeline management and media selection
 * Handles drag & drop, media library, undo/redo, and timeline confirmation
 */

import { CommandHistory, AddClipCommand, RemoveClipCommand } from './commands.js';

let commandHistory = null;

export async function onEnter(wizard) {
  console.log('[step-arrange] Entering arrange step');

  // Initialize command history
  commandHistory = new CommandHistory();
  wizard.commandHistory = commandHistory;

  // Load saved wizard state from database
  const savedState = wizard.wizardState || {};
  console.log('[step-arrange] Loading saved state:', savedState);

  // Initialize wizard state with saved values or defaults
  wizard.selectedTransitionIds = savedState.selectedTransitionIds || wizard.selectedTransitionIds || [];
  wizard.transitionsRandomize = savedState.transitionsRandomize !== undefined
    ? savedState.transitionsRandomize
    : (wizard.transitionsRandomize !== undefined ? wizard.transitionsRandomize : false);
  wizard.selectedMusicIds = savedState.selectedMusicIds || wizard.selectedMusicIds || [];
  wizard.musicVolume = savedState.musicVolume !== undefined
    ? savedState.musicVolume
    : (wizard.musicVolume !== undefined ? wizard.musicVolume : 0.3);
  wizard.selectedIntroIds = savedState.selectedIntroIds || wizard.selectedIntroIds || [];
  wizard.selectedOutroIds = savedState.selectedOutroIds || wizard.selectedOutroIds || [];
  wizard.selectedClipIds = savedState.selectedClipIds || wizard.selectedClipIds || [];

  console.log('[step-arrange] Restored state:', {
    transitions: wizard.selectedTransitionIds,
    music: wizard.selectedMusicIds,
    intros: wizard.selectedIntroIds,
    outros: wizard.selectedOutroIds,
    clips: wizard.selectedClipIds
  });

  // Wire up transition controls
  setupTransitionControls(wizard);

  // Wire up music controls
  setupMusicControls(wizard);

  // Setup UI
  setupTabNavigation();
  setupNavigation(wizard);
  setupTimelineConfirmation(wizard);
  setupProjectDetailsForm(wizard);
  initDetailsAudioNormSlider();
  initTimelineDragDrop(wizard);

  // Load data
  await populateClipsGrid(wizard);
  await loadMediaLists(wizard);
  await loadProjectDetails(wizard);

  // Restore timeline from saved state
  await restoreTimelineFromState(wizard);

  // Update UI state
  updateClipsGridState();
  updateArrangedConfirmState();
  updateTimelineInfo(wizard);
}

export function onExit(wizard) {
  console.log('[step-arrange] Exiting arrange step');
}

/**
 * Setup tab navigation
 */
function setupTabNavigation() {
  document.querySelectorAll('[data-arrange-tab]').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const targetTab = link.dataset.arrangeTab;

      document.querySelectorAll('[data-arrange-tab]').forEach(l => l.classList.remove('active'));
      link.classList.add('active');

      document.querySelectorAll('.arrange-tab-content').forEach(content => {
        content.classList.toggle('active', content.dataset.tab === targetTab);
      });
    });
  });
}

/**
 * Setup navigation handlers
 */
function setupNavigation(wizard) {
  const prevBtn = document.querySelector('[data-prev="2"]');
  const markReadyBtn = document.getElementById('mark-ready-btn');

  prevBtn?.addEventListener('click', () => wizard.gotoStep(2));
  markReadyBtn?.addEventListener('click', async () => {
    await saveTimelineOrder(wizard);

    // Mark project as READY
    try {
      await wizard.api(`/api/projects/${wizard.projectId}/wizard`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'ready' })
      });
      wizard.showToast('Project marked as ready for compilation!', 'success');

      // Navigate to compile step after short delay
      setTimeout(() => {
        wizard.gotoStep(4);
      }, 1000);
    } catch (err) {
      console.error('[step-arrange] Failed to mark project as ready:', err);
      wizard.showToast('Failed to mark project as ready', 'danger');
    }
  });

  // Add All Clips to Timeline button
  const addAllBtn = document.getElementById('add-all-clips');
  addAllBtn?.addEventListener('click', async () => {
    if (!wizard.projectId) return;

    try {
      const res = await wizard.api(`/api/projects/${wizard.projectId}/clips`);
      const data = await res.json();
      const items = data.items || [];

      // Add all clips that aren't already in the timeline
      for (const item of items) {
        if (!wizard.selectedClipIds.includes(item.id)) {
          wizard.selectedClipIds.push(item.id);

          // Transform to match media item format and add to timeline
          const clipItem = {
            id: item.id,
            original_filename: item.title || 'Clip',
            filename: item.title || 'Clip',
            thumbnail_url: (item.media && item.media.thumbnail_url) || '',
            duration: (typeof item.duration === 'number' ? item.duration : (item.media && typeof item.media.duration === 'number' ? item.media.duration : undefined)),
            preview_url: (item.media && item.media.preview_url) || '',
            creator_name: item.creator_name,
            game_name: item.game_name,
            view_count: item.view_count,
            avatar_url: item.avatar_url
          };

          addClipToTimeline(wizard, clipItem);
        }
      }

      wizard.showToast?.(`Added ${items.length} clips to timeline`, 'success');
    } catch (err) {
      console.error('[step-arrange] Failed to add all clips:', err);
      wizard.showToast?.('Failed to add clips', 'error');
    }
  });
}

/**
 * Setup timeline confirmation checkbox
 */
function setupTimelineConfirmation(wizard) {
  const arrangedConfirm = document.getElementById('arranged-confirm');
  const markReadyBtn = document.getElementById('mark-ready-btn');

  arrangedConfirm?.addEventListener('change', () => {
    if (markReadyBtn) markReadyBtn.disabled = !arrangedConfirm.checked;
  });
}

/**
 * Populate clips grid
 */
async function populateClipsGrid(wizard) {
  if (!wizard.projectId) return;

  try {
    const res = await wizard.api(`/api/projects/${wizard.projectId}/clips`);
    const data = await res.json();
    const lst = data || {};
    const items = lst.items || [];

    // Render clips using the standard renderMediaList with selection
    const grid = document.getElementById('clips-grid');
    if (!items.length) {
      grid.innerHTML = '<div class="text-muted">No clips yet. Download first.</div>';
      return;
    }

    // Transform clips to match media item format
    const clipItems = items.map(item => ({
      id: item.id,
      original_filename: item.title || 'Clip',
      filename: item.title || 'Clip',
      thumbnail_url: (item.media && item.media.thumbnail_url) || '',
      duration: (typeof item.duration === 'number' ? item.duration : (item.media && (typeof item.media.duration === 'number') ? item.media.duration : undefined)),
      duration_formatted: item.duration_formatted,
      preview_url: (item.media && item.media.preview_url) || '',
      is_public: false,
      // Store clip-specific data
      creator_name: item.creator_name,
      game_name: item.game_name,
      view_count: item.view_count,
      avatar_url: item.avatar_url,
      created_at: item.created_at
    }));

    renderMediaList('clips-grid', clipItems, 'clip', (it) => {
      addClipToTimeline(wizard, it);
    }, wizard);

    updateClipsGridState();
  } catch (err) {
    console.error('[step-arrange] Failed to populate clips grid:', err);
  }
}

/**
 * Update clips grid state (remaining count)
 */
function updateClipsGridState() {
  const grid = document.getElementById('clips-grid');
  const visible = grid?.querySelectorAll('.clip-card:not(.d-none)').length || 0;
  const remaining = document.getElementById('clips-remaining');
  const badge = document.getElementById('clips-count-badge');

  if (remaining) {
    remaining.textContent = visible > 0 ? `${visible} available` : 'All added';
  }
  if (badge) {
    badge.textContent = String(visible);
  }
}

/**
 * Update arranged confirmation state
 */
function updateArrangedConfirmState() {
  const timelineList = document.getElementById('timeline-list');
  const hasClips = timelineList && timelineList.querySelectorAll('.timeline-card[data-clip-id]').length > 0;
  const arrangedConfirm = document.getElementById('arranged-confirm');
  const markReadyBtn = document.getElementById('mark-ready-btn');

  if (arrangedConfirm) {
    arrangedConfirm.disabled = !hasClips;
    if (!hasClips) {
      arrangedConfirm.checked = false;
      if (markReadyBtn) markReadyBtn.disabled = true;
    }
  }
}

/**
 * Make a timeline card element
 */
function makeTimelineCard({ title, subtitle, thumbUrl, clipId, kind, durationSec, previewUrl, viewCount, avatarUrl }) {
  const card = document.createElement('div');
  card.className = 'timeline-card';
  card.draggable = !(kind === 'intro' || kind === 'outro');

  if (clipId) card.dataset.clipId = String(clipId);
  if (kind) card.dataset.kind = kind;
  if (typeof durationSec === 'number' && !isNaN(durationSec)) card.dataset.durationSec = String(durationSec);
  if (previewUrl) card.dataset.previewUrl = String(previewUrl);
  if (typeof viewCount === 'number') card.dataset.viewCount = String(viewCount);
  if (avatarUrl) card.dataset.avatarUrl = String(avatarUrl);

  if (kind) card.classList.add(`timeline-${kind}`);

  // Thumbnail
  const thumb = document.createElement('div');
  thumb.className = 'thumb';
  if (thumbUrl) thumb.style.backgroundImage = `url(${thumbUrl})`;
  card.appendChild(thumb);

  // Duration badge
  if (typeof durationSec === 'number' && !isNaN(durationSec)) {
    const badge = document.createElement('div');
    const mm = Math.floor(durationSec / 60);
    const ss = Math.round(durationSec % 60).toString().padStart(2, '0');
    badge.className = 'badge-duration';
    badge.textContent = `${mm}:${ss}`;
    card.appendChild(badge);
  }

  // Content
  const content = document.createElement('div');
  content.className = 'content';

  const titleEl = document.createElement('div');
  titleEl.className = 'title';
  titleEl.textContent = title || 'Untitled';
  content.appendChild(titleEl);

  if (subtitle) {
    const subtitleEl = document.createElement('div');
    subtitleEl.className = 'subtitle';
    subtitleEl.textContent = subtitle;
    content.appendChild(subtitleEl);
  }

  card.appendChild(content);

  // Remove button (not for intro/outro)
  if (kind !== 'intro' && kind !== 'outro') {
    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-clip';
    removeBtn.innerHTML = '&times;';
    removeBtn.title = 'Remove from timeline';
    removeBtn.addEventListener('click', () => handleRemoveClick(card));
    card.appendChild(removeBtn);
  }

  // Drag event listeners
  if (card.draggable) {
    card.addEventListener('dragstart', () => card.classList.add('dragging'));
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
  }

  return card;
}

/**
 * Handle remove clip click
 */
function handleRemoveClick(card) {
  const clipId = parseInt(card.dataset.clipId);
  const list = document.getElementById('timeline-list');
  const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
  const position = cards.indexOf(card);

  const clipData = {
    title: card.querySelector('.title')?.textContent || 'Clip',
    subtitle: card.querySelector('.subtitle')?.textContent || '',
    thumbUrl: card.querySelector('.thumb')?.style.backgroundImage?.slice(5, -2) || '',
    durationSec: card.dataset.durationSec ? parseFloat(card.dataset.durationSec) : undefined,
    previewUrl: card.dataset.previewUrl || '',
    viewCount: card.dataset.viewCount ? parseInt(card.dataset.viewCount) : undefined,
    avatarUrl: card.dataset.avatarUrl || ''
  };

  const removeCmd = RemoveClipCommand(clipId, clipData, position, {
    rebuildSeparators: () => rebuildSeparators(wizard),
    saveTimelineOrder: () => saveTimelineOrder(wizard),
    updateArrangedConfirmState
  });
  commandHistory.execute(removeCmd);
}

/**
 * Initialize timeline drag and drop
 */
function initTimelineDragDrop(wizard) {
  const list = document.getElementById('timeline-list');
  let insertPlaceholder = null;

  function getOrCreateInsertPlaceholder() {
    if (insertPlaceholder && insertPlaceholder.isConnected) return insertPlaceholder;
    const ph = document.createElement('div');
    ph.className = 'timeline-insert';
    const plus = document.createElement('div');
    plus.className = 'timeline-insert-plus';
    plus.textContent = '+';
    ph.appendChild(plus);
    insertPlaceholder = ph;
    return ph;
  }

  function getDragAfterElement(container, x) {
    const els = [...container.querySelectorAll('.timeline-card:not(.dragging)')];
    return els.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = x - box.left - box.width / 2;
      if (offset < 0 && offset > closest.offset) return { offset, element: child };
      else return closest;
    }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
  }

  function placeInsertPlaceholder(x) {
    const ph = getOrCreateInsertPlaceholder();
    const intro = list.querySelector('.timeline-card.timeline-intro');
    const outro = list.querySelector('.timeline-card.timeline-outro');
    let after = getDragAfterElement(list, x);

    if (intro && after === intro) after = intro.nextElementSibling;
    if (!ph.isConnected) list.appendChild(ph);

    if (outro && (after == null || after === outro)) {
      list.insertBefore(ph, outro);
    } else if (after == null) {
      list.appendChild(ph);
    } else {
      list.insertBefore(ph, after);
    }
  }

  function removeInsertPlaceholder() {
    if (insertPlaceholder && insertPlaceholder.parentElement) {
      insertPlaceholder.parentElement.removeChild(insertPlaceholder);
    }
  }

  list.addEventListener('dragover', (e) => {
    e.preventDefault();
    const dragging = document.querySelector('.timeline-card.dragging');
    if (!dragging) return;
    placeInsertPlaceholder(e.clientX);
  });

  list.addEventListener('drop', () => {
    const dragging = document.querySelector('.timeline-card.dragging');
    if (dragging && insertPlaceholder && insertPlaceholder.parentElement === list) {
      list.insertBefore(dragging, insertPlaceholder);
    }
    removeInsertPlaceholder();
    rebuildSeparators(wizard);
    saveTimelineOrder(wizard);
  });

  document.addEventListener('dragend', () => {
    removeInsertPlaceholder();
  });
}

/**
 * Rebuild timeline separators
 */
function rebuildSeparators(wizard) {
  const list = document.getElementById('timeline-list');
  if (!list) return;

  Array.from(list.querySelectorAll('.timeline-sep')).forEach(el => el.remove());

  const cards = Array.from(list.querySelectorAll('.timeline-card'));
  for (let i = 0; i < cards.length - 1; i++) {
    if (cards[i].classList.contains('timeline-outro')) continue;

    const sep = document.createElement('div');
    sep.className = 'timeline-sep';
    const lbl = document.createElement('div');
    lbl.className = 'timeline-sep-label';
    lbl.textContent = (wizard.selectedTransitionIds && wizard.selectedTransitionIds.length) ? 'transition' : 'static';
    sep.appendChild(lbl);
    list.insertBefore(sep, cards[i + 1]);
  }

  updateSeparatorLabels(wizard);
  updateArrangedConfirmState();
}

/**
 * Update separator labels
 */
function updateSeparatorLabels(wizard) {
  const list = document.getElementById('timeline-list');
  if (!list) return;

  const hasTransitions = !!(wizard.selectedTransitionIds && wizard.selectedTransitionIds.length);
  Array.from(list.querySelectorAll('.timeline-sep')).forEach(sep => {
    const lbl = sep.querySelector('.timeline-sep-label');
    if (lbl) lbl.textContent = hasTransitions ? 'transition' : 'static';
    sep.classList.toggle('has-transition', hasTransitions);
  });

  updateTimelineInfo(wizard);
}

/**
 * Update timeline info status bar
 */
function updateTimelineInfo(wizard) {
  const info = document.getElementById('timeline-info');
  if (!info) return;

  const transitionCount = wizard.selectedTransitionIds ? wizard.selectedTransitionIds.length : 0;
  const randomize = wizard.transitionsRandomize || false;
  const musicCount = wizard.selectedMusicIds ? wizard.selectedMusicIds.length : 0;
  const musicVolume = wizard.musicVolume !== undefined ? wizard.musicVolume : 30;

  // Calculate total duration
  const timeline = document.getElementById('timeline-list');
  let totalDuration = 0;
  if (timeline) {
    const cards = timeline.querySelectorAll('.timeline-card[data-duration-sec]');
    cards.forEach(card => {
      const dur = parseFloat(card.dataset.durationSec);
      if (!isNaN(dur)) totalDuration += dur;
    });
  }

  let parts = [];

  // Duration status
  if (totalDuration > 0) {
    const mins = Math.floor(totalDuration / 60);
    const secs = Math.round(totalDuration % 60);
    parts.push(`<span class="text-primary"><i class="bi bi-clock"></i> ${mins}:${secs.toString().padStart(2, '0')}</span>`);
  }

  // Transition status
  if (transitionCount === 0) {
    parts.push('<span class="text-muted"><i class="bi bi-info-circle"></i> No transitions</span>');
  } else if (transitionCount === 1) {
    parts.push(`<span class="text-success"><i class="bi bi-check-circle"></i> 1 transition ${randomize ? '(randomized)' : ''}</span>`);
  } else {
    parts.push(`<span class="text-success"><i class="bi bi-check-circle"></i> ${transitionCount} transitions ${randomize ? '(randomized)' : ''}</span>`);
  }

  // Music status
  if (musicCount === 0) {
    parts.push('<span class="text-muted">No music</span>');
  } else {
    // Get music names if available
    const musicNames = wizard.selectedMusicNames || [];
    if (musicNames.length > 0) {
      const nameList = musicNames.join(', ');
      parts.push(`<span class="text-info"><i class="bi bi-music-note-beamed"></i> Music: ${nameList} • Volume: ${musicVolume}%</span>`);
    } else {
      parts.push(`<span class="text-info"><i class="bi bi-music-note-beamed"></i> ${musicCount} track${musicCount > 1 ? 's' : ''} • Volume: ${musicVolume}%</span>`);
    }
  }

  info.innerHTML = parts.join(' <span class="text-muted mx-2">|</span> ');
}

/**
 * Save timeline order to server
 */
async function saveTimelineOrder(wizard) {
  if (!wizard.projectId) return;

  const list = document.getElementById('timeline-list');
  const ids = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'))
    .map(el => parseInt(el.dataset.clipId, 10))
    .filter(Boolean);

  if (!ids.length) return;

  try {
    const res = await wizard.api(`/api/projects/${wizard.projectId}/clips/order`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clip_ids: ids })
    });

    if (!res.ok) {
      console.error('[step-arrange] Failed to save timeline order');
    } else {
      wizard.showSaveIndicator();
    }
  } catch (err) {
    console.error('[step-arrange] Error saving timeline order:', err);
  }
}

/**
 * Load media lists (intros, outros, transitions, music)
 */
async function loadMediaLists(wizard) {
  await Promise.all([
    refreshIntros(wizard),
    refreshOutros(wizard),
    refreshTransitions(wizard),
    refreshMusic(wizard)
  ]);
}

/**
 * Restore timeline from saved wizard state
 */
async function restoreTimelineFromState(wizard) {
  console.log('[step-arrange] Restoring timeline from saved state');

  // Clear timeline first
  const timeline = document.getElementById('timeline-list');
  if (!timeline) {
    console.warn('[step-arrange] Timeline container not found');
    return;
  }

  timeline.innerHTML = '';

  try {
    // Restore intro
    if (wizard.selectedIntroIds && wizard.selectedIntroIds.length > 0) {
      const introId = wizard.selectedIntroIds[0];
      const intros = await loadMediaList(wizard, 'intro');
      const intro = intros.find(it => it.id === introId);
      if (intro) {
        console.log('[step-arrange] Restoring intro:', intro);

        const card = makeTimelineCard({
          title: 'Intro',
          subtitle: intro.original_filename || intro.filename,
          thumbUrl: intro.thumbnail_url || '',
          kind: 'intro',
          durationSec: intro.duration,
          previewUrl: intro.preview_url || ''
        });
        card.classList.add('timeline-intro');
        timeline.prepend(card);
      }
    }

    // Restore clips
    if (wizard.selectedClipIds && wizard.selectedClipIds.length > 0) {
      const clipRes = await wizard.api(`/api/projects/${wizard.projectId}/clips`);
      const clipData = await clipRes.json();
      const allClips = clipData.items || [];

      for (const clipId of wizard.selectedClipIds) {
        const clip = allClips.find(c => c.id === clipId);
        if (clip) {
          console.log('[step-arrange] Restoring clip:', clip);

          const card = makeTimelineCard({
            title: clip.title || clip.original_filename || clip.filename || 'Clip',
            subtitle: [
              clip.creator_name ? `By ${clip.creator_name}` : '',
              clip.game_name ? `• ${clip.game_name}` : ''
            ].filter(Boolean).join(' '),
            thumbUrl: (clip.media && clip.media.thumbnail_url) || clip.thumbnail_url || '',
            clipId: clip.id,
            durationSec: (typeof clip.duration === 'number' ? clip.duration : (clip.media && typeof clip.media.duration === 'number' ? clip.media.duration : undefined)),
            previewUrl: (clip.media && clip.media.preview_url) || clip.preview_url || '',
            viewCount: clip.view_count,
            avatarUrl: clip.avatar_url,
            kind: 'clip'
          });

          timeline.appendChild(card);
        }
      }
    }

    // Restore outro
    if (wizard.selectedOutroIds && wizard.selectedOutroIds.length > 0) {
      const outroId = wizard.selectedOutroIds[0];
      const outros = await loadMediaList(wizard, 'outro');
      const outro = outros.find(it => it.id === outroId);
      if (outro) {
        console.log('[step-arrange] Restoring outro:', outro);

        const card = makeTimelineCard({
          title: 'Outro',
          subtitle: outro.original_filename || outro.filename,
          thumbUrl: outro.thumbnail_url || '',
          kind: 'outro',
          durationSec: outro.duration,
          previewUrl: outro.preview_url || ''
        });
        card.classList.add('timeline-outro');
        timeline.appendChild(card);
      }
    }

    // Restore music names for status display
    if (wizard.selectedMusicIds && wizard.selectedMusicIds.length > 0) {
      const musicItems = await loadMediaList(wizard, 'music');
      wizard.selectedMusicNames = wizard.selectedMusicIds
        .map(musicId => {
          const music = musicItems.find(m => m.id === musicId);
          return music ? (music.original_filename || music.filename) : null;
        })
        .filter(Boolean);
      console.log('[step-arrange] Restored music names:', wizard.selectedMusicNames);
    }

    // Rebuild separators and update state
    rebuildSeparators(wizard);
    updateArrangedConfirmState();

    console.log('[step-arrange] Timeline restored successfully');
  } catch (e) {
    console.error('[step-arrange] Error restoring timeline:', e);
  }
}

/**
 * Escape HTML to prevent XSS
 */
/**
 * Setup transition controls (randomize, select all, clear all)
 */
function setupTransitionControls(wizard) {
  // Randomize toggle
  const randomizeToggle = document.getElementById('transitions-randomize');
  if (randomizeToggle) {
    randomizeToggle.checked = wizard.transitionsRandomize || false;
    randomizeToggle.addEventListener('change', (e) => {
      wizard.transitionsRandomize = e.target.checked;
      updateTimelineInfo(wizard);
      wizard.saveWizardState({ transitionsRandomize: wizard.transitionsRandomize });
    });
  }

  // Select all button
  const selectAllBtn = document.getElementById('select-all-transitions');
  if (selectAllBtn) {
    selectAllBtn.addEventListener('click', async () => {
      const items = await loadMediaList(wizard, 'transition');
      wizard.selectedTransitionIds = items.map(it => it.id);
      updateSeparatorLabels(wizard);
      refreshTransitions(wizard);
      wizard.saveWizardState({ selectedTransitionIds: wizard.selectedTransitionIds });
    });
  }

  // Clear all button
  const clearAllBtn = document.getElementById('clear-all-transitions');
  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', () => {
      wizard.selectedTransitionIds = [];
      updateSeparatorLabels(wizard);
      refreshTransitions(wizard);
      wizard.saveWizardState({ selectedTransitionIds: [] });
    });
  }
}

/**
 * Setup music controls (select all, clear all)
 */
function setupMusicControls(wizard) {
  // Music volume
  const volumeSlider = document.getElementById('music-volume');
  const volumeDisplay = document.getElementById('music-volume-display');
  if (volumeSlider && volumeDisplay) {
    // Initialize from wizard state
    if (wizard.musicVolume !== undefined) {
      volumeSlider.value = wizard.musicVolume;
      volumeDisplay.textContent = wizard.musicVolume + '%';
    }

    volumeSlider.addEventListener('input', (e) => {
      volumeDisplay.textContent = e.target.value + '%';
      wizard.musicVolume = parseInt(e.target.value);
      updateTimelineInfo(wizard);
      wizard.saveWizardState({ musicVolume: wizard.musicVolume });
    });
  }
}

/**
 * Refresh intros list
 */
async function refreshIntros(wizard) {
  const items = await loadMediaList(wizard, 'intro');
  renderMediaList('intro-list', items, 'intro', (it) => {
    addIntroToTimeline(wizard, it);
  }, wizard);
}

/**
 * Refresh outros list
 */
async function refreshOutros(wizard) {
  const items = await loadMediaList(wizard, 'outro');
  renderMediaList('outro-list', items, 'outro', (it) => {
    addOutroToTimeline(wizard, it);
  }, wizard);
}

/**
 * Refresh transitions list
 */
async function refreshTransitions(wizard) {
  const items = await loadMediaList(wizard, 'transition');
  renderMediaList('transition-list', items, 'transition', (it) => {
    addTransitionToTimeline(wizard, it);
  }, wizard);
}

/**
 * Add transition to timeline (updates global transition selection)
 */
function addTransitionToTimeline(wizard, transition) {
  if (!wizard.selectedTransitionIds) wizard.selectedTransitionIds = [];

  // Toggle transition selection
  const idx = wizard.selectedTransitionIds.indexOf(transition.id);
  if (idx >= 0) {
    wizard.selectedTransitionIds.splice(idx, 1);
  } else {
    wizard.selectedTransitionIds.push(transition.id);
  }

  // Update separator labels to show "transition" or "static"
  updateSeparatorLabels(wizard);

  // Refresh transitions list to update UI
  refreshTransitions(wizard);

  // Save to wizard state
  wizard.saveWizardState({
    selectedTransitionIds: wizard.selectedTransitionIds,
    transitionsRandomize: wizard.transitionsRandomize
  });
}

/**
 * Add music to timeline (updates global music selection)
 */
function addMusicToTimeline(wizard, music) {
  if (!wizard.selectedMusicIds) wizard.selectedMusicIds = [];
  if (!wizard.selectedMusicNames) wizard.selectedMusicNames = [];

  // Toggle music selection
  const idx = wizard.selectedMusicIds.indexOf(music.id);
  if (idx >= 0) {
    wizard.selectedMusicIds.splice(idx, 1);
    wizard.selectedMusicNames.splice(idx, 1);
  } else {
    wizard.selectedMusicIds.push(music.id);
    wizard.selectedMusicNames.push(music.original_filename || music.filename);
  }

  // Update timeline info
  updateTimelineInfo(wizard);

  // Refresh music list to update UI
  refreshMusic(wizard);

  // Save to wizard state
  wizard.saveWizardState({
    selectedMusicIds: wizard.selectedMusicIds,
    selectedMusicNames: wizard.selectedMusicNames
  });
}

/**
 * Refresh music list
 */
async function refreshMusic(wizard) {
  const items = await loadMediaList(wizard, 'music');
  renderMediaList('music-list', items, 'music', (it) => {
    addMusicToTimeline(wizard, it);
  }, wizard);
}

/**
 * Load media list by type
 */
async function loadMediaList(wizard, kind) {
  if (!wizard.projectId) return [];

  try {
    const res = await wizard.api(`/api/projects/${wizard.projectId}/media?type=${encodeURIComponent(kind)}`);
    const data = await res.json();
    return data.items || [];
  } catch (e) {
    console.error(`[step-arrange] Error loading ${kind}:`, e);
    return [];
  }
}

/**
 * Render media list in a container (matches media library format)
 */
function renderMediaList(containerId, items, type, selectHandler, wizard = null) {
  const el = document.getElementById(containerId);
  el.innerHTML = '';

  if (!items.length) {
    el.innerHTML = '<div class="text-muted">No media found.</div>';
    return;
  }

  // Check if this is a transition list with selected items
  const isTransitionList = type === 'transition' && wizard && wizard.selectedTransitionIds;
  const selectedIds = isTransitionList ? wizard.selectedTransitionIds : [];

  // Check if this is a music list with selected items
  const isMusicList = type === 'music' && wizard && wizard.selectedMusicIds;
  const selectedMusicIds = isMusicList ? wizard.selectedMusicIds : [];

  // Check if this is an intro/outro list with selected items
  const isIntroList = type === 'intro' && wizard && wizard.selectedIntroIds;
  const selectedIntroIds = isIntroList ? wizard.selectedIntroIds : [];
  const isOutroList = type === 'outro' && wizard && wizard.selectedOutroIds;
  const selectedOutroIds = isOutroList ? wizard.selectedOutroIds : [];

  // Check if this is a clip list with selected items
  const isClipList = type === 'clip' && wizard && wizard.selectedClipIds;
  const selectedClipIds = isClipList ? wizard.selectedClipIds : [];

  items.forEach(it => {
    const isSelected = (isTransitionList && selectedIds.includes(it.id)) ||
                      (isMusicList && selectedMusicIds.includes(it.id)) ||
                      (isIntroList && selectedIntroIds.includes(it.id)) ||
                      (isOutroList && selectedOutroIds.includes(it.id)) ||
                      (isClipList && selectedClipIds.includes(it.id));

    const card = document.createElement('div');
    card.className = 'card h-100 position-relative media-card';
    if (isSelected) card.classList.add('border-success');
    card.style.width = '160px';
    card.style.cursor = 'pointer';
    card.setAttribute('data-type', type);
    card.setAttribute('data-media-id', it.id);

    // Selected checkmark (top-left for transitions)
    if (isSelected) {
      const checkmark = document.createElement('div');
      checkmark.className = 'position-absolute top-0 start-0 p-1';
      checkmark.style.zIndex = '10';
      const icon = document.createElement('i');
      icon.className = 'bi bi-check-circle-fill text-success';
      icon.style.fontSize = '1.5rem';
      checkmark.appendChild(icon);
      card.appendChild(checkmark);
    }

    // Public badge (top-right)
    if (it.is_public) {
      const publicBadge = document.createElement('div');
      publicBadge.className = 'position-absolute top-0 end-0 p-1';
      publicBadge.style.zIndex = '10';
      const badge = document.createElement('span');
      badge.className = 'badge bg-info';
      badge.style.fontSize = '0.65rem';
      badge.textContent = 'Public';
      publicBadge.appendChild(badge);
      card.appendChild(publicBadge);
    }

    // Image or placeholder for audio
    if (type === 'music') {
      // Audio placeholder
      const placeholder = document.createElement('div');
      placeholder.className = 'card-img-top d-flex align-items-center justify-content-center media-thumb';
      placeholder.style.height = '140px';
      placeholder.style.background = 'var(--bs-card-bg)';
      const icon = document.createElement('i');
      icon.className = 'bi bi-music-note-beamed';
      icon.style.fontSize = '3rem';
      placeholder.appendChild(icon);
      card.appendChild(placeholder);
    } else {
      // Video thumbnail
      const img = document.createElement('img');
      img.className = 'card-img-top media-thumb';
      img.alt = it.original_filename || it.filename;
      img.src = it.thumbnail_url || '';
      img.style.maxHeight = '140px';
      img.style.objectFit = 'cover';
      img.onerror = () => {
        // Fallback to placeholder
        const placeholder = document.createElement('div');
        placeholder.className = 'card-img-top d-flex align-items-center justify-content-center';
        placeholder.style.height = '140px';
        placeholder.style.background = 'var(--bs-card-bg)';
        const icon = document.createElement('i');
        icon.className = 'bi bi-file-earmark-play';
        icon.style.fontSize = '2rem';
        placeholder.appendChild(icon);
        img.replaceWith(placeholder);
      };
      card.appendChild(img);
    }

    // Card body
    const body = document.createElement('div');
    body.className = 'card-body p-2';

    // Title
    const title = document.createElement('div');
    title.className = 'fw-semibold text-truncate small';
    title.title = it.original_filename || it.filename;
    title.textContent = it.original_filename || it.filename;
    body.appendChild(title);

    // Details list
    const ul = document.createElement('ul');
    ul.className = 'list-unstyled small mb-0 mt-2';

    // Type badge
    const typeLi = document.createElement('li');
    const typeBadge = document.createElement('span');
    typeBadge.className = `badge text-bg-${type}`;
    typeBadge.textContent = type.charAt(0).toUpperCase() + type.slice(1);
    typeLi.appendChild(typeBadge);
    ul.appendChild(typeLi);

    // Duration (for video/audio)
    if (it.duration || it.duration_formatted) {
      const durationLi = document.createElement('li');
      const durationSpan = document.createElement('span');
      durationSpan.className = 'text-muted';
      const clockIcon = document.createElement('i');
      clockIcon.className = 'bi bi-clock';
      durationSpan.appendChild(clockIcon);
      durationSpan.appendChild(document.createTextNode(' ' + (it.duration_formatted || formatDuration(it.duration))));
      durationLi.appendChild(durationSpan);
      ul.appendChild(durationLi);
    }

    body.appendChild(ul);

    // Button(s)
    if (isTransitionList || isMusicList || isIntroList || isOutroList || isClipList) {
      if (isSelected) {
        // Remove button for selected items
        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-sm btn-outline-danger w-100 mt-2';
        removeBtn.innerHTML = '<i class="bi bi-x-circle"></i> Remove';
        removeBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          selectHandler(it);
        });
        body.appendChild(removeBtn);
      } else {
        // Add button for unselected items
        const addBtn = document.createElement('button');
        addBtn.className = 'btn btn-sm btn-primary w-100 mt-2';
        addBtn.innerHTML = '<i class="bi bi-plus-circle"></i> Add';
        addBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          selectHandler(it);
        });
        body.appendChild(addBtn);
      }
    } else {
      // Standard add button for other media types
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm btn-primary w-100 mt-2';
      btn.textContent = 'Add to timeline';
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        selectHandler(it);
      });
      body.appendChild(btn);
    }

    card.appendChild(body);
    el.appendChild(card);
  });
}

/**
 * Format duration in seconds to MM:SS or HH:MM:SS
 */
function formatDuration(seconds) {
  if (!seconds) return '0:00';
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hrs > 0) {
    return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * Add intro to timeline (toggle selection)
 */
function addIntroToTimeline(wizard, item) {
  if (!wizard.selectedIntroIds) wizard.selectedIntroIds = [];

  const list = document.getElementById('timeline-list');
  const existing = list.querySelector('.timeline-card.timeline-intro');

  // Toggle intro selection
  const idx = wizard.selectedIntroIds.indexOf(item.id);
  if (idx >= 0) {
    // Remove from selection and timeline
    wizard.selectedIntroIds.splice(idx, 1);
    if (existing) existing.remove();
  } else {
    // Add to selection (replace any existing intro)
    wizard.selectedIntroIds = [item.id];

    if (existing) existing.remove();

    const card = makeTimelineCard({
      title: 'Intro',
      subtitle: item.original_filename || item.filename,
      thumbUrl: item.thumbnail_url || '',
      kind: 'intro',
      durationSec: item.duration,
      previewUrl: item.preview_url || ''
    });

    card.classList.add('timeline-intro');
    list.prepend(card);
  }

  rebuildSeparators(wizard);
  refreshIntros(wizard);
  wizard.saveWizardState({ selectedIntroIds: wizard.selectedIntroIds });
}

/**
 * Add outro to timeline (toggle selection)
 */
function addOutroToTimeline(wizard, item) {
  if (!wizard.selectedOutroIds) wizard.selectedOutroIds = [];

  const list = document.getElementById('timeline-list');
  const existing = list.querySelector('.timeline-card.timeline-outro');

  // Toggle outro selection
  const idx = wizard.selectedOutroIds.indexOf(item.id);
  if (idx >= 0) {
    // Remove from selection and timeline
    wizard.selectedOutroIds.splice(idx, 1);
    if (existing) existing.remove();
  } else {
    // Add to selection (replace any existing outro)
    wizard.selectedOutroIds = [item.id];

    if (existing) existing.remove();

    const card = makeTimelineCard({
      title: 'Outro',
      subtitle: item.original_filename || item.filename,
      thumbUrl: item.thumbnail_url || '',
      kind: 'outro',
      durationSec: item.duration,
      previewUrl: item.preview_url || ''
    });

    card.classList.add('timeline-outro');
    list.appendChild(card);
  }

  updateArrangedConfirmState();
  rebuildSeparators(wizard);
  refreshOutros(wizard);
  wizard.saveWizardState({ selectedOutroIds: wizard.selectedOutroIds });
}

/**
 * Add clip to timeline (toggle selection)
 */
function addClipToTimeline(wizard, item) {
  if (!wizard.selectedClipIds) wizard.selectedClipIds = [];

  const list = document.getElementById('timeline-list');

  // Toggle clip selection
  const idx = wizard.selectedClipIds.indexOf(item.id);
  if (idx >= 0) {
    // Remove from selection and timeline
    wizard.selectedClipIds.splice(idx, 1);
    const existing = list.querySelector(`.timeline-card[data-clip-id="${item.id}"]`);
    if (existing) existing.remove();
  } else {
    // Add to selection and timeline
    wizard.selectedClipIds.push(item.id);

    const clipData = {
      title: item.original_filename || item.filename,
      subtitle: [item.creator_name ? `By ${item.creator_name}` : '', item.game_name ? `• ${item.game_name}` : ''].filter(Boolean).join(' '),
      thumbUrl: item.thumbnail_url || '',
      clipId: item.id,
      durationSec: item.duration,
      previewUrl: item.preview_url || '',
      viewCount: item.view_count,
      avatarUrl: item.avatar_url,
      kind: 'clip'
    };

    const card = makeTimelineCard(clipData);

    // Insert before outro or at end
    const outro = list.querySelector('.timeline-card.timeline-outro');
    if (outro) {
      list.insertBefore(card, outro);
    } else {
      list.appendChild(card);
    }
  }

  rebuildSeparators(wizard);
  updateArrangedConfirmState();
  populateClipsGrid(wizard);
  wizard.saveWizardState({ selectedClipIds: wizard.selectedClipIds });
}

/**
 * Initialize audio normalization slider in Details tab
 */
function initDetailsAudioNormSlider() {
  const slider = document.getElementById('details-audio-norm-slider');
  if (!slider) return;

  const radios = Array.from(slider.querySelectorAll('input[type="radio"][name="audio_norm_profile"]'));
  const pos = slider.querySelector('.pos');
  const hiddenDb = document.getElementById('details-audio-norm-db');
  const enableCb = document.getElementById('details-audio-norm-enabled');
  const card = slider.closest('.audio-norm-card');

  function update() {
    const idx = radios.findIndex(r => r.checked);
    const count = Math.max(1, parseInt(slider.dataset.count || String(radios.length || 4), 10));
    const step = 100 / count;
    const left = step * (idx + 0.5);

    if (pos) pos.style.left = left + '%';

    const db = radios[idx]?.dataset.db || '-1';
    if (hiddenDb) hiddenDb.value = db;
  }

  function setEnabled(on) {
    if (card) card.classList.toggle('off', !on);
    radios.forEach(r => { r.disabled = !on; });
    if (pos) pos.style.opacity = on ? '1' : '0.2';
    if (!on && hiddenDb) hiddenDb.value = '';
    if (on) update();
  }

  radios.forEach(r => r.addEventListener('change', update));
  if (enableCb) enableCb.addEventListener('change', () => setEnabled(enableCb.checked));

  update();
  if (enableCb) setEnabled(enableCb.checked);
}

/**
 * Load project details into the form
 */
async function loadProjectDetails(wizard) {
  if (!wizard.projectId) return;

  try {
    const res = await wizard.api(`/api/projects/${wizard.projectId}`);
    if (!res.ok) {
      console.error('[step-arrange] Failed to load project details');
      return;
    }

    const project = await res.json();

    // Populate form fields
    const form = document.getElementById('project-details-form');
    if (!form) return;

    // Platform preset
    const presetSelect = document.getElementById('details-platform-preset');
    if (presetSelect && project.platform_preset) {
      presetSelect.value = project.platform_preset;
    }

    // Output format
    const formatSelect = document.getElementById('details-output-format');
    if (formatSelect && project.output_format) {
      formatSelect.value = project.output_format;
    }

    // FPS
    const fpsSelect = document.getElementById('details-fps');
    if (fpsSelect && project.fps) {
      fpsSelect.value = String(project.fps);
    }

    // Audio normalization
    const audioNormEnabled = document.getElementById('details-audio-norm-enabled');
    if (project.audio_norm_profile && project.audio_norm_profile !== 'off') {
      if (audioNormEnabled) audioNormEnabled.checked = true;
      const radio = document.getElementById(`details-an-${project.audio_norm_profile}`);
      if (radio) {
        radio.checked = true;
        // Trigger the slider update
        radio.dispatchEvent(new Event('change'));
      }
      // Trigger enable/disable handler
      if (audioNormEnabled) audioNormEnabled.dispatchEvent(new Event('change'));
    } else {
      if (audioNormEnabled) {
        audioNormEnabled.checked = false;
        audioNormEnabled.dispatchEvent(new Event('change'));
      }
    }

    // Tags
    const tagsInput = document.getElementById('details-tags');
    if (tagsInput && project.tags) {
      tagsInput.value = project.tags;
    }

    // Description
    const descInput = document.getElementById('details-description');
    if (descInput && project.description) {
      descInput.value = project.description;
    }
  } catch (err) {
    console.error('[step-arrange] Error loading project details:', err);
  }
}

/**
 * Setup project details form submission
 */
function setupProjectDetailsForm(wizard) {
  const form = document.getElementById('project-details-form');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!wizard.projectId) {
      wizard.showToast('No project loaded', 'danger');
      return;
    }

    const formData = new FormData(form);
    const audioNormEnabled = document.getElementById('details-audio-norm-enabled');
    const payload = {
      platform_preset: formData.get('platform_preset'),
      output_format: formData.get('output_format'),
      fps: parseInt(formData.get('fps'), 10),
      audio_norm_profile: audioNormEnabled?.checked ? formData.get('audio_norm_profile') : 'off',
      audio_norm_db: audioNormEnabled?.checked ? parseFloat(formData.get('audio_norm_db')) : 0,
      tags: formData.get('tags'),
      description: formData.get('description')
    };

    try {
      const res = await wizard.api(`/api/projects/${wizard.projectId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        throw new Error('Failed to update project details');
      }

      wizard.showToast('Project details updated successfully!', 'success');
      wizard.showSaveIndicator();
    } catch (err) {
      console.error('[step-arrange] Error saving project details:', err);
      wizard.showToast('Failed to save project details', 'danger');
    }
  });
}
