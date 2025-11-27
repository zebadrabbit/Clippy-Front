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

  // Initialize wizard state
  if (!wizard.selectedTransitionIds) wizard.selectedTransitionIds = [];

  // Setup UI
  setupTabNavigation();
  setupNavigation(wizard);
  setupTimelineConfirmation(wizard);
  initTimelineDragDrop(wizard);

  // Load data
  await populateClipsGrid(wizard);
  await loadMediaLists(wizard);

  // Update UI state
  updateClipsGridState();
  updateArrangedConfirmState();
}

export function onExit(wizard) {
  console.log('[step-arrange] Exiting arrange step');
  // Cleanup if needed
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
  const nextBtn = document.getElementById('next-3');

  prevBtn?.addEventListener('click', () => wizard.gotoStep(2));
  nextBtn?.addEventListener('click', async () => {
    await saveTimelineOrder(wizard);
    wizard.gotoStep(4);
  });
}

/**
 * Setup timeline confirmation checkbox
 */
function setupTimelineConfirmation(wizard) {
  const arrangedConfirm = document.getElementById('arranged-confirm');
  const nextBtn = document.getElementById('next-3');

  arrangedConfirm?.addEventListener('change', () => {
    if (nextBtn) nextBtn.disabled = !arrangedConfirm.checked;
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
    const grid = document.getElementById('clips-grid');
    grid.innerHTML = '';

    (lst.items || []).forEach(item => {
      const card = document.createElement('div');
      card.className = 'card clip-card h-100 d-flex';
      card.dataset.clipId = String(item.id || '');

      const img = document.createElement('img');
      img.className = 'card-img-top';
      img.alt = item.title || 'clip thumbnail';
      img.src = (item.media && item.media.thumbnail_url) || '';
      card.appendChild(img);

      const body = document.createElement('div');
      body.className = 'card-body d-flex flex-column';

      const h5 = document.createElement('h5');
      h5.className = 'card-title mb-2';
      h5.textContent = item.title || 'Clip';

      const ul = document.createElement('ul');
      ul.className = 'list-unstyled mb-3 small text-muted';

      const liWho = document.createElement('li');
      liWho.textContent = item.creator_name ? `By ${item.creator_name}` : 'Unknown creator';

      const liGame = document.createElement('li');
      liGame.textContent = item.game_name ? item.game_name : 'Unknown game';

      const liWhen = document.createElement('li');
      liWhen.textContent = item.created_at ? new Date(item.created_at).toLocaleString() : 'Unknown date';

      ul.appendChild(liWho);
      ul.appendChild(liGame);
      ul.appendChild(liWhen);

      const btn = document.createElement('a');
      btn.href = '#';
      btn.className = 'btn btn-sm btn-primary mt-auto';
      btn.textContent = 'Add to timeline';
      btn.addEventListener('click', (e) => {
        e.preventDefault();

        const clipData = {
          title: item.title || 'Clip',
          subtitle: [item.creator_name ? `By ${item.creator_name}` : '', item.game_name ? `• ${item.game_name}` : ''].filter(Boolean).join(' '),
          thumbUrl: (item.media && item.media.thumbnail_url) || '',
          durationSec: (typeof item.duration === 'number' ? item.duration : (item.media && (typeof item.media.duration === 'number') ? item.media.duration : undefined)),
          previewUrl: (item.media && item.media.preview_url) || '',
          viewCount: item.view_count,
          avatarUrl: item.avatar_url
        };

        const addCmd = AddClipCommand(item.id, clipData, -1, {
          makeTimelineCard,
          rebuildSeparators: () => rebuildSeparators(wizard),
          saveTimelineOrder: () => saveTimelineOrder(wizard),
          updateArrangedConfirmState
        });
        commandHistory.execute(addCmd);

        card.classList.add('d-none');
        updateClipsGridState();
      });

      body.appendChild(h5);
      body.appendChild(ul);
      body.appendChild(btn);
      card.appendChild(body);
      grid.appendChild(card);
    });

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
  const nextBtn = document.getElementById('next-3');

  if (arrangedConfirm) {
    arrangedConfirm.disabled = !hasClips;
    if (!hasClips) {
      arrangedConfirm.checked = false;
      if (nextBtn) nextBtn.disabled = true;
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
 * Refresh intros list
 */
async function refreshIntros(wizard) {
  const items = await loadMediaList(wizard, 'intro');
  renderMediaList('intro-list', items, (it) => {
    addIntroToTimeline(wizard, it);
  });
}

/**
 * Refresh outros list
 */
async function refreshOutros(wizard) {
  const items = await loadMediaList(wizard, 'outro');
  renderMediaList('outro-list', items, (it) => {
    addOutroToTimeline(wizard, it);
  });
}

/**
 * Refresh transitions list
 */
async function refreshTransitions(wizard) {
  const items = await loadMediaList(wizard, 'transition');
  renderMediaList('transition-list', items, (it) => {
    // Transition selection logic here
  });
}

/**
 * Refresh music list
 */
async function refreshMusic(wizard) {
  const items = await loadMediaList(wizard, 'music');
  renderMediaList('music-list', items, (it) => {
    // Music selection logic here
  });
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
 * Render media list
 */
function renderMediaList(containerId, items, selectHandler) {
  const el = document.getElementById(containerId);
  el.innerHTML = '';

  if (!items.length) {
    el.innerHTML = '<div class="text-muted">No media found.</div>';
    return;
  }

  items.forEach(it => {
    const card = document.createElement('div');
    card.className = 'card';
    card.style.width = '160px';
    card.style.cursor = 'pointer';

    const imgWrapper = document.createElement('div');
    imgWrapper.style.position = 'relative';

    const img = document.createElement('img');
    img.className = 'card-img-top';
    img.alt = it.original_filename || it.filename;
    img.src = it.thumbnail_url || '';
    img.onerror = () => { img.classList.add('d-none'); };
    imgWrapper.appendChild(img);

    const body = document.createElement('div');
    body.className = 'card-body p-2';

    const title = document.createElement('div');
    title.className = 'small text-truncate';
    title.textContent = it.original_filename || it.filename;

    const btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-primary w-100 mt-1';
    btn.textContent = 'Add to timeline';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      selectHandler(it);
    });

    body.appendChild(title);
    body.appendChild(btn);
    card.appendChild(imgWrapper);
    card.appendChild(body);
    el.appendChild(card);
  });
}

/**
 * Add intro to timeline
 */
function addIntroToTimeline(wizard, item) {
  const list = document.getElementById('timeline-list');
  const existing = list.querySelector('.timeline-card.timeline-intro');
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
  rebuildSeparators(wizard);
}

/**
 * Add outro to timeline
 */
function addOutroToTimeline(wizard, item) {
  const list = document.getElementById('timeline-list');
  const existing = list.querySelector('.timeline-card.timeline-outro');
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
  updateArrangedConfirmState();
  rebuildSeparators(wizard);
}
