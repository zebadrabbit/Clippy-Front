/**
 * Step 4: Compile - Preview, compilation, and progress tracking
 * Handles compilation workflow, progress monitoring, and celebration
 */

let compileTimer = null;
let currentProgress = 0;
let targetProgress = 0;
let progressAnimationFrame = null;

export async function onEnter(wizard) {
  console.log('[step-compile] Entering compile step');

  // Setup navigation
  setupNavigation(wizard);

  // Setup compilation controls
  setupCompileControls(wizard);

  // Render compilation summary
  await renderCompileSummary(wizard);

  // Setup keyboard shortcuts
  setupKeyboardShortcuts(wizard);
}

export function onExit(wizard) {
  console.log('[step-compile] Exiting compile step');

  // Cleanup timers
  if (compileTimer) {
    clearInterval(compileTimer);
    compileTimer = null;
  }
  if (progressAnimationFrame) {
    clearTimeout(progressAnimationFrame);
    progressAnimationFrame = null;
  }
}

/**
 * Setup navigation handlers
 */
function setupNavigation(wizard) {
  const prevBtn = document.querySelector('[data-prev="3"]');
  const nextBtn = document.getElementById('next-4');

  prevBtn?.addEventListener('click', () => wizard.gotoStep(3));

  nextBtn?.addEventListener('click', async () => {
    if (!wizard.projectId) {
      alert('No project loaded.');
      return;
    }
    try {
      const res = await fetch(`/api/projects/${wizard.projectId}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const details = await res.json();

      // Navigate to public page if available, otherwise to project detail
      if (details.public_id) {
        window.location.href = `/p/${details.public_id}`;
      } else {
        // Fallback to project detail page
        window.location.href = `/projects/${wizard.projectId}`;
      }
    } catch (e) {
      console.error('Failed to get project details:', e);
      // Fallback to direct project navigation
      window.location.href = `/projects/${wizard.projectId}`;
    }
  });
}

/**
 * Setup keyboard shortcuts
 */
function setupKeyboardShortcuts(wizard) {
  const handler = (e) => {
    // Ctrl+Enter: Start compilation
    if (e.ctrlKey && e.key === 'Enter') {
      e.preventDefault();
      const startBtn = document.getElementById('start-compile');
      if (startBtn && !startBtn.disabled) {
        startBtn.click();
      }
    }
  };

  document.addEventListener('keydown', handler);

  // Store handler for cleanup if needed
  wizard._compileKeyHandler = handler;
}

/**
 * Setup compilation controls
 */
function setupCompileControls(wizard) {
  const startBtn = document.getElementById('start-compile');
  const cancelBtn = document.getElementById('cancel-compile');

  startBtn?.addEventListener('click', () => startCompilation(wizard));
  cancelBtn?.addEventListener('click', () => cancelCompilation(wizard));
}

/**
 * Render compilation summary
 */
async function renderCompileSummary(wizard) {
  const details = document.getElementById('compile-details');
  if (!details) return;

  // Fetch project data if we don't have settings cached
  let s = wizard.settings || {};
  if (wizard.projectId && (!s.output_resolution || !s.output_format)) {
    try {
      const project = await wizard.api(`/api/projects/${wizard.projectId}`);
      s = {
        ...s,
        output_resolution: project.output_resolution,
        output_format: project.output_format,
        fps: project.fps,
        platform_preset: project.platform_preset,
        audio_norm_profile: project.audio_norm_profile,
        audio_norm_db: project.audio_norm_db
      };
      wizard.settings = s;
    } catch (e) {
      console.warn('Failed to fetch project settings for summary:', e);
    }
  }

  const list = document.getElementById('timeline-list');
  const intro = list?.querySelector('.timeline-card.timeline-intro');
  const outro = list?.querySelector('.timeline-card.timeline-outro');
  const clips = Array.from(list?.querySelectorAll('.timeline-card[data-clip-id]') || []);
  const clipCount = clips.length;
  const transCount = (wizard.selectedTransitionIds || []).length;
  const transMode = document.getElementById('transitions-randomize')?.checked ? 'Randomized' : 'Cycled';

  // Estimate total duration
  const num = (val) => { const n = Number(val); return isFinite(n) ? n : 0; };
  const introSec = intro ? num(intro.dataset.durationSec) : 0;
  const outroSec = outro ? num(outro.dataset.durationSec) : 0;
  const clipSecs = clips.reduce((acc, el) => acc + num(el.dataset.durationSec), 0);
  const segments = (intro ? 1 : 0) + clipCount + (outro ? 1 : 0);
  const gaps = Math.max(0, segments - 1);

  let avgTrans = 0;
  if (transCount) {
    const map = wizard.transitionDurationMap || {};
    const vals = (wizard.selectedTransitionIds || []).map(id => num(map[id])).filter(v => v > 0);
    avgTrans = vals.length ? (vals.reduce((a, b) => a + b, 0) / vals.length) : 3;
  }

  const estimatedSeconds = Math.floor(clipSecs + introSec + outroSec + (transCount ? gaps * avgTrans : 0));
  const fmtSec = (sec) => {
    const s = Math.max(0, Math.floor(sec));
    const m = Math.floor(s / 60);
    const r = (s % 60).toString().padStart(2, '0');
    return `${m}:${r}`;
  };

  // Derive orientation from resolution
  let orientationLabel = 'Landscape';
  const res = s.output_resolution || s.resolution || '';
  if (res && res.includes('x')) {
    const [w, h] = res.split('x').map(Number);
    if (w && h) {
      if (w < h) orientationLabel = 'Portrait';
      else if (w === h) orientationLabel = 'Square';
      else orientationLabel = 'Landscape';
    }
  }

  // Build combined meta line
  const norm = (typeof s.audio_norm_db === 'number' && !isNaN(s.audio_norm_db)) ? `, (${s.audio_norm_db.toString()}db)` : '';
  const combined = `${orientationLabel}, ${s.fps || 60}fps, ${s.format || 'mp4'}${norm}`;

  // Platform preset label
  const presetLabels = {
    youtube: 'YouTube',
    youtube_shorts: 'YouTube Shorts',
    tiktok: 'TikTok',
    instagram_feed: 'Instagram Feed',
    instagram_reel: 'Instagram Reels',
    instagram_story: 'Instagram Stories',
    twitter: 'Twitter/X',
    facebook: 'Facebook',
    twitch: 'Twitch Clips',
    custom: 'Custom'
  };
  const presetName = presetLabels[s.platform_preset] || 'Custom';

  const yes = '<span class="text-success fw-semibold">Yes</span>';
  const no = '<span class="text-danger fw-semibold">No</span>';

  // Clip mini list
  const itemsHtml = clips.map((el, idx) => {
    const title = (el.querySelector('.title')?.textContent || 'Clip');
    const dur = (el.querySelector('.badge-duration')?.textContent || '');
    const creator = (el.querySelector('.subtitle')?.textContent || el.querySelector('.creator')?.textContent || '').trim();
    const views = el.dataset.viewCount || '';
    const avatarUrl = el.dataset.avatarUrl || '';
    const bg = el.querySelector('.thumb')?.style?.backgroundImage || '';
    const m = /url\(["']?([^"')]+)["']?\)/.exec(bg);
    const src = m ? m[1] : '';
    const prev = el.dataset.previewUrl || '';

    // Format view count
    let viewsLabel = '';
    if (views) {
      const v = parseInt(views, 10);
      if (!isNaN(v)) {
        viewsLabel = v >= 1000000 ? `${(v / 1000000).toFixed(1)}M views` :
                     v >= 1000 ? `${(v / 1000).toFixed(1)}K views` :
                     `${v} views`;
      }
    }

    return `
      <div class="compile-clip-item" data-preview-url="${escapeHtml(prev)}">
        <div class="compile-clip-index">${idx + 1}</div>
        ${avatarUrl ? `<img src="${escapeHtml(avatarUrl)}" alt="avatar" class="compile-clip-avatar">` : ''}
        <div class="compile-clip-thumb-wrap">
          <img class="compile-clip-thumb" src="${escapeHtml(src)}" alt="">
        </div>
        <div class="compile-clip-meta">
          <div class="compile-clip-title">${escapeHtml(title)}</div>
          <div class="compile-clip-info">
            <span class="compile-clip-duration">${escapeHtml(dur)}</span>
            ${creator ? `<span class="compile-clip-creator">${escapeHtml(creator)}</span>` : ''}
            ${viewsLabel ? `<span class="compile-clip-views">${escapeHtml(viewsLabel)}</span>` : ''}
          </div>
        </div>
      </div>`;
  }).join('');

  details.innerHTML = `
    <div class="compile-summary">
      <div class="compile-left small">
        <h6 class="mb-2">Render Summary</h6>
        <div class="mb-1"><strong>Project:</strong> ${escapeHtml(s.name || 'My Compilation')}</div>
        <div class="mb-1"><strong>Preset:</strong> ${escapeHtml(presetName)}</div>
        <div class="mb-1"><strong>Output:</strong> ${escapeHtml(combined)}</div>
        <div class="mb-1"><strong>Estimated length:</strong> ${fmtSec(estimatedSeconds)}</div>
        <div class="mb-1"><strong>Intro/Outro:</strong> ${intro ? yes : no}, ${outro ? yes : no}</div>
        <div class="mb-1"><strong>Transitions:</strong> ${transCount ? `${transCount} (${transMode})` : 'None'}</div>
        <div class="mb-1"><strong>Background Music:</strong> ${(Array.isArray(wizard.selectedMusicIds) && wizard.selectedMusicIds.length) ? `Yes (${document.getElementById('music-volume')?.value || 30}% volume)` : 'None'}</div>
        <div class="text-muted">Clip limits: max ${s.max_len || 0}s • max clips ${s.max_clips || 0}${s.compilation_length && s.compilation_length !== 'auto' ? ` • Target length: ${Math.floor(parseInt(s.compilation_length) / 60)}m` : ''}${s.start_date || s.end_date ? ` • Dates: ${escapeHtml(s.start_date || '—')} → ${escapeHtml(s.end_date || '—')}` : ''}</div>
      </div>
      <div class="compile-middle small">
        <h6 class="mb-2">Preview</h6>
        ${clipCount > 0 ? `
          <div class="preview-container" style="position: relative; min-height: 160px;">
            <img class="compilation-preview-img img-fluid rounded border"
                 alt="Compilation Preview"
                 style="max-width: 100%; max-height: 300px; display: none; width: 100%;">
            <video class="compilation-preview-video img-fluid rounded border"
                   alt="Compilation Preview"
                   style="max-width: 100%; max-height: 300px; display: none; width: 100%;"
                   muted playsinline>
              Your browser does not support the video tag.
            </video>
            <div class="preview-placeholder bg-dark border rounded d-flex align-items-center justify-content-center text-muted" style="position: absolute; top: 0; left: 0; right: 0; height: 160px; display: flex;">
              <div class="text-center">
                <div class="spinner-border spinner-border-sm mb-2" role="status">
                  <span class="visually-hidden">Loading...</span>
                </div>
                <div class="small">Loading preview...</div>
              </div>
            </div>
          </div>
        ` : '<div class="text-muted small">No clips to preview</div>'}
      </div>
      <div class="compile-right small">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <h6 class="mb-0">Clips <span class="text-muted small">(${clipCount})</span></h6>
        </div>
        <div class="compile-clip-list">${itemsHtml || '<div class="text-muted small">No clips selected.</div>'}</div>
      </div>
    </div>`;

  try {
    attachHoverPreviews(details);
  } catch (_) {}
}

/**
 * Attach hover preview functionality
 */
function attachHoverPreviews(root) {
  const items = Array.from(root.querySelectorAll('.compile-clip-item'));
  items.forEach(it => {
    const wrap = it.querySelector('.compile-clip-thumb-wrap');
    if (!wrap) return;

    let vid = null;

    function show() {
      const url = it.getAttribute('data-preview-url');
      if (!url) return;
      if (vid && vid.isConnected) return;

      vid = document.createElement('video');
      vid.className = 'compile-clip-video';
      vid.src = url;
      vid.muted = true;
      vid.autoplay = true;
      vid.loop = true;
      vid.playsInline = true;
      wrap.appendChild(vid);
    }

    function hide() {
      if (vid && vid.parentElement) {
        vid.pause();
        vid.parentElement.removeChild(vid);
      }
      vid = null;
    }

    wrap.addEventListener('mouseenter', show);
    wrap.addEventListener('mouseleave', hide);
    wrap.addEventListener('focus', show, true);
    wrap.addEventListener('blur', hide, true);
  });
}

/**
 * Animate progress bar
 */
function animateProgress() {
  if (currentProgress < targetProgress) {
    currentProgress = Math.min(currentProgress + 1, targetProgress);
    updateProgressUI();
    progressAnimationFrame = setTimeout(animateProgress, 20);
  } else if (currentProgress > targetProgress) {
    currentProgress = Math.max(currentProgress - 1, targetProgress);
    updateProgressUI();
    progressAnimationFrame = setTimeout(animateProgress, 20);
  }
}

/**
 * Update progress UI
 */
function updateProgressUI() {
  const barEl = document.getElementById('compile-progress-bar');
  if (barEl) barEl.value = currentProgress;

  const labelEl = document.getElementById('compile-progress-label');
  if (labelEl) {
    labelEl.setAttribute('data-value', currentProgress);
  }
}

/**
 * Start compilation
 */
async function startCompilation(wizard) {
  if (!wizard.projectId) {
    alert('No project loaded yet.');
    return;
  }

  const startBtn = document.getElementById('start-compile');
  const cancelBtn = document.getElementById('cancel-compile');
  const log = document.getElementById('compile-log');

  // Disable start button
  if (startBtn) startBtn.disabled = true;

  // Reset progress
  currentProgress = 0;
  targetProgress = 0;
  const barEl = document.getElementById('compile-progress-bar');
  if (barEl) barEl.value = 0;

  const labelEl = document.getElementById('compile-progress-label');
  if (labelEl) {
    labelEl.textContent = 'Compiling...';
    labelEl.setAttribute('data-value', '0');
  }

  if (cancelBtn) cancelBtn.disabled = false;
  log.textContent = 'Splicing your highlights together...';

  try {
    const body = {};

    // Add intro/outro (get first selected ID from arrays)
    if (Array.isArray(wizard.selectedIntroIds) && wizard.selectedIntroIds.length) {
      body.intro_id = wizard.selectedIntroIds[0];
    }
    if (Array.isArray(wizard.selectedOutroIds) && wizard.selectedOutroIds.length) {
      body.outro_id = wizard.selectedOutroIds[0];
    }

    // Add transitions (always send, even if empty array to indicate intent)
    body.transition_ids = Array.isArray(wizard.selectedTransitionIds) && wizard.selectedTransitionIds.length
      ? wizard.selectedTransitionIds
      : [];
    body.randomize_transitions = !!document.getElementById('transitions-randomize')?.checked;

    // Add music settings (get first selected ID from array)
    if (Array.isArray(wizard.selectedMusicIds) && wizard.selectedMusicIds.length) {
      body.background_music_id = wizard.selectedMusicIds[0];
      body.music_volume = parseFloat((parseInt(document.getElementById('music-volume')?.value || '30', 10) / 100).toFixed(2));
      body.music_start_mode = document.getElementById('music-start-mode')?.value || 'after_intro';
      body.music_end_mode = document.getElementById('music-end-mode')?.value || 'before_outro';

      // Include ducking parameters
      const thresholdSlider = parseInt(document.getElementById('duck-threshold')?.value || '2', 10);
      body.duck_threshold = parseFloat((thresholdSlider / 100).toFixed(2));
      body.duck_ratio = parseFloat(document.getElementById('duck-ratio')?.value || '20');
      const attackSlider = parseInt(document.getElementById('duck-attack')?.value || '10', 10);
      body.duck_attack = parseFloat((attackSlider / 10).toFixed(1));
      body.duck_release = parseFloat(document.getElementById('duck-release')?.value || '250');
    }

    console.log('[step-compile] Compilation body:', body);

    // Extract timeline clips
    const list = document.getElementById('timeline-list');
    const ids = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'))
      .map(el => parseInt(el.dataset.clipId, 10))
      .filter(v => Number.isFinite(v));

    if (!ids.length) {
      alert('Add at least one clip to the timeline.');
      if (cancelBtn) cancelBtn.disabled = true;
      if (startBtn) startBtn.disabled = false;
      return;
    }

    body.clip_ids = ids;

    // Start compilation
    const res = await fetch(`/api/projects/${wizard.projectId}/compile`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': wizard.getCsrfToken ? wizard.getCsrfToken() : ''
      },
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({ error: 'Unknown error' }));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }

    const r = await res.json();
    wizard.compileTaskId = r.task_id;

    if (!wizard.compileTaskId) {
      if (cancelBtn) cancelBtn.disabled = true;
      if (startBtn) startBtn.disabled = false;
      log.textContent = 'Failed to start compilation: missing task id.';
      console.error('[step-compile] API response missing task_id:', r);
      return;
    }

    // Poll for progress
    async function poll() {
      try {
        if (!wizard.compileTaskId) return;

        const taskRes = await fetch(`/api/tasks/${wizard.compileTaskId}`, {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json'
          }
        });

        if (!taskRes.ok) {
          console.error('[step-compile] Task status fetch failed:', taskRes.status);
          return;
        }

        const s = await taskRes.json();
        const st = s.state || s.status;
        const meta = s.info || {};
        const pct = Math.max(0, Math.min(100, Math.floor(meta.progress || 0)));

        console.log('[step-compile] Task status:', st, 'Progress:', pct, 'Meta:', meta);

        targetProgress = pct;
        if (progressAnimationFrame) clearTimeout(progressAnimationFrame);
        animateProgress();

        // Show current stage in log
        const stage = meta.stage || meta.step || meta.phase || meta.task || '';
        const msg = meta.message || meta.detail || meta.status || '';
        const parts = [];
        if (stage) parts.push(`[${stage}]`);
        if (msg) parts.push(msg);
        if (parts.length) log.textContent = parts.join(' ') + ` ${pct}%`;

        if (st === 'SUCCESS') {
          clearInterval(compileTimer);
          if (progressAnimationFrame) clearTimeout(progressAnimationFrame);
          if (cancelBtn) cancelBtn.disabled = true;
          if (startBtn) startBtn.disabled = true;

          // Ensure 100% progress
          targetProgress = 100;
          currentProgress = 100;
          updateProgressUI();

          log.textContent = "Show's in the can!";
          document.getElementById('next-4').disabled = false;

          // Trigger celebration
          setTimeout(() => {
            if (window.triggerCelebration) {
              window.triggerCelebration();
            }
          }, 300);

          return;
        }

        if (st === 'FAILURE') {
          clearInterval(compileTimer);
          if (cancelBtn) cancelBtn.disabled = true;
          if (startBtn) startBtn.disabled = false;
          const errorMsg = s.error || meta.error || 'Unknown error';
          log.textContent = `The cut failed: ${errorMsg}`;
          console.error('[step-compile] Task failed:', s);
          return;
        }
      } catch (err) {
        console.error('[step-compile] Poll error:', err);
      }
    }

    compileTimer = setInterval(poll, 1200);
    poll();
  } catch (e) {
    alert('Couldn\'t start the cut: ' + e.message);
  }
}

/**
 * Cancel compilation
 */
function cancelCompilation(wizard) {
  if (compileTimer) {
    clearInterval(compileTimer);
    compileTimer = null;
  }
  if (progressAnimationFrame) {
    clearTimeout(progressAnimationFrame);
    progressAnimationFrame = null;
  }

  document.getElementById('compile-log').textContent = 'Cut canceled.';

  const startBtn = document.getElementById('start-compile');
  if (startBtn) startBtn.disabled = false;

  const cancelBtn = document.getElementById('cancel-compile');
  if (cancelBtn) cancelBtn.disabled = true;
}

/**
 * Escape HTML
 */
function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]));
}
