(function(){
  // Encapsulate wizard logic; expects data attributes and endpoints present in the template
  const steps = Array.from(document.querySelectorAll('.wizard-step'));
  // Set dynamic placeholder for Project Name with today's date
  try {
    const nameInput = document.querySelector('#setup-form input[name="name"]');
    if (nameInput && (!nameInput.value || nameInput.value.trim() === '')) {
      const d = new Date();
      const pref = document.getElementById('wizard-data')?.dataset.dateFormat || 'auto';
      let dateStr = '';
      switch (pref) {
        case 'mdy':
          dateStr = `${(d.getMonth()+1).toString().padStart(2,'0')}/${d.getDate().toString().padStart(2,'0')}/${d.getFullYear()}`;
          break;
        case 'dmy':
          dateStr = `${d.getDate().toString().padStart(2,'0')}/${(d.getMonth()+1).toString().padStart(2,'0')}/${d.getFullYear()}`;
          break;
        case 'ymd':
          dateStr = `${d.getFullYear()}-${(d.getMonth()+1).toString().padStart(2,'0')}-${d.getDate().toString().padStart(2,'0')}`;
          break;
        case 'long':
          dateStr = d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
          break;
        case 'auto':
        default:
          dateStr = d.toLocaleDateString();
      }
      nameInput.placeholder = `Compilation of ${dateStr}`;
    }
  } catch (_) {}
  function markWizardChevron(stepStr){
    const nodes = document.querySelectorAll('#wizard-chevrons li');
    nodes.forEach(li => li.classList.toggle('active', li.dataset.step === stepStr));
    // Mark prior steps as done (checkmark visible on inactive items before the active one)
    let reached = false;
    nodes.forEach(li => {
      if (!reached && li.dataset.step !== stepStr) {
        li.classList.add('done');
      } else if (li.dataset.step === stepStr) {
        li.classList.remove('done');
        reached = true;
      } else {
        li.classList.remove('done');
      }
    });
  }
  function gotoStep(n){
    const stepStr = String(n);
    steps.forEach(s => s.classList.toggle('d-none', s.dataset.step !== stepStr));
    markWizardChevron(stepStr);
    if (stepStr === '3') {
      // Require explicit confirmation on Arrange each time user enters step 3
      const chk = document.getElementById('arranged-confirm');
      const nextBtn = document.getElementById('next-3');
      if (chk) chk.checked = false;
      if (nextBtn) nextBtn.disabled = true;
    }
    if (stepStr === '4') {
      try { renderCompileSummary(); } catch (_) {}
    }
    if (stepStr === '3' && wizard.projectId) {
      // Auto-refresh Arrange lists so user doesn't need to click refresh
      Promise.resolve().then(async () => {
        try { await refreshIntros(); } catch (_) {}
        try { await refreshOutros(); } catch (_) {}
        try { await refreshTransitions(); } catch (_) {}
        try { renderTransitionsBadge(); } catch (_) {}
      });
    }
    if (stepStr === '5' && wizard.projectId) { refreshExportInfo().catch(() => {}); }
  }
  document.querySelectorAll('#wizard-chevrons li').forEach(li => li.addEventListener('click', (e) => {
    e.preventDefault();
    const target = Number(li.dataset.step);
    if (target >= 4) {
      const arrangedConfirm = document.getElementById('arranged-confirm');
      if (arrangedConfirm && !arrangedConfirm.checked) {
        alert("Line up your timeline before we roll the render.");
        return;
      }
    }
    gotoStep(li.dataset.step);
  }));

  // Next/Back buttons and helpers
  let wizard = { projectId: null, downloadTasks: [], compileTaskId: null, selectedTransitionIds: [], settings: {} };
  const USER_HAS_TWITCH = (document.getElementById('wizard-data')?.dataset.userHasTwitch === '1');
  async function api(path, opts={}){
    const res = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  // Twitch warning toggle
  const routeSelect = document.getElementById('route-select');
  const twitchWarn = document.getElementById('twitch-warning');
  function updateTwitchWarning(){
    const val = routeSelect.value;
    const show = (val === 'twitch') && !USER_HAS_TWITCH;
    if (twitchWarn) twitchWarn.classList.toggle('d-none', !show);
  }
  routeSelect?.addEventListener('change', updateTwitchWarning);

  // Create project and go to Get Clips
  // Audio normalization slider wiring
  (function initAudioNormSlider(){
    const slider = document.getElementById('audio-norm-slider');
    if (!slider) return;
    const radios = Array.from(slider.querySelectorAll('input[type="radio"][name="audio_norm_profile"]'));
    const pos = slider.querySelector('.pos');
    const hiddenDb = document.getElementById('audio_norm_db');
    const enableCb = document.getElementById('audio-norm-enabled');
    const card = slider.closest('.audio-norm-card');
    function update(){
      const idx = radios.findIndex(r => r.checked);
      const count = Math.max(1, parseInt(slider.dataset.count || String(radios.length || 4), 10));
      const step = 100 / count;
      // center of each step: step*(idx+0.5)
      const left = (step * (idx + 0.5));
      if (pos) pos.style.left = left + '%';
      const db = (radios[idx]?.dataset.db || '-1');
      if (hiddenDb) hiddenDb.value = db;
    }
    function setEnabled(on){
      if (card) card.classList.toggle('off', !on);
      radios.forEach(r => { r.disabled = !on; });
      if (pos) pos.style.opacity = on ? '1' : '0.2';
      if (!on && hiddenDb) { hiddenDb.value = ''; }
      if (on) update();
    }
    radios.forEach(r => r.addEventListener('change', update));
    if (enableCb) {
      enableCb.addEventListener('change', () => setEnabled(!!enableCb.checked));
      setEnabled(!!enableCb.checked);
    } else {
      setEnabled(true);
    }
    update();
  })();

  document.getElementById('next-1')?.addEventListener('click', async () => {
    const route = routeSelect.value;
    const form = document.getElementById('setup-form');
    const fd = new FormData(form);
    const maxClips = parseInt(fd.get('max_clips') || '20', 10);
    const audioNormEnabled = !!document.getElementById('audio-norm-enabled')?.checked;
    const payload = {
      name: (fd.get('name') || '').toString(),
      description: (fd.get('description') || '').toString(),
      output_resolution: (fd.get('resolution') || '1080p').toString(),
      output_format: (fd.get('format') || 'mp4').toString(),
      max_clip_duration: parseInt(fd.get('max_len') || '300', 10),
      // audio normalization will be conditionally appended below
    };
    if (audioNormEnabled) {
      payload.audio_norm_profile = (fd.get('audio_norm_profile') || 'gaming').toString();
      const dbVal = (fd.get('audio_norm_db') || '').toString().trim();
      if (dbVal !== '') {
        payload.audio_norm_db = parseFloat(dbVal);
      }
    }
    // Persist settings for Compile summary
    wizard.settings = {
      route: route,
  name: payload.name || '',
      description: payload.description,
      resolution: payload.output_resolution,
      format: payload.output_format,
  fps: parseInt(fd.get('fps') || '60', 10),
      max_clips: Math.max(1, Math.min(500, parseInt(fd.get('max_clips') || '20', 10))),
      min_len: parseInt(fd.get('min_len') || '5', 10),
      max_len: payload.max_clip_duration,
      start_date: fd.get('start_date') || '',
      end_date: fd.get('end_date') || '',
      min_views: fd.get('min_views') || '',
      audio_norm_profile: audioNormEnabled ? payload.audio_norm_profile : undefined,
      audio_norm_db: audioNormEnabled ? payload.audio_norm_db : undefined
    };
    try {
      const r = await api('/api/projects', { method: 'POST', body: JSON.stringify(payload) });
      wizard.projectId = r.project_id;
      wizard.route = route;
      wizard.maxClips = Math.max(1, Math.min(100, isNaN(maxClips) ? 20 : maxClips));
      gotoStep(2);
      // Auto-run Get Clips behind the scenes
  setGcActive('fetch');
  setGcStatus('Casting a net for clips…');
      setGcFill(5);
      try {
        let urls = [];
        if ((wizard.route || routeSelect.value) === 'discord') {
          urls = await fetchDiscordClips();
        } else {
          urls = await fetchTwitchClips();
        }
        if (urls && urls.length) {
          setGcDone('fetch');
          setGcActive('extract');
          setGcStatus(`Detected ${urls.length} clip URL(s).`);
          setGcFill(20);
          await queueDownloads(urls);
          setGcDone('extract');
          setGcActive('queue');
          setGcStatus(`Stacking ${wizard.downloadTasks.length} download(s)…`);
          setGcFill(35);
          // Skip polling for reused items; only poll real tasks
          const hasRealTasks = (wizard.downloadTasks || []).some(t => t && t.task_id);
          setGcDone('queue');
          if (hasRealTasks) {
            setGcActive('download');
            setGcFill(40);
            await startDownloadPolling();
          } else {
            // All reused; mark progress, enable Next, and populate clips
            setGcDone('download');
            setGcDone('done');
            setGcActive('done');
            setGcStatus('All clips were already on deck. Reusing media.');
            setGcFill(100);
            document.getElementById('next-2').disabled = false;
            try { await populateClipsGrid(); } catch (_) {}
          }
        }
      } catch (_) {}
    } catch (e) {
      alert('Couldn’t create the project: ' + e.message);
    }
  });
  document.querySelector('[data-prev="1"]')?.addEventListener('click', () => gotoStep(1));
  document.querySelector('[data-prev="2"]')?.addEventListener('click', () => gotoStep(2));
  document.querySelector('[data-prev="3"]')?.addEventListener('click', () => gotoStep(3));
  document.querySelector('[data-prev="4"]')?.addEventListener('click', () => gotoStep(4));

  // Fetchers
  async function fetchTwitchClips() {
    try {
      const first = Math.max(1, Math.min(100, wizard.maxClips || 20));
      const res = await fetch(`/api/twitch/clips?first=${first}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const items = data.items || [];
      const urls = items.map(it => it.url).filter(Boolean);
      wizard.fetchedClips = items;
      setGcStatus(`Reeled in ${items.length} clips for @${data.username}.`);
      return urls;
    } catch (e) {
      setGcError('fetch');
      setGcStatus('Couldn’t fetch clips. Check your Twitch settings.');
      return [];
    }
  }
  async function fetchDiscordClips() {
    try {
      const res = await fetch('/api/discord/messages?limit=200');
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const items = data.items || [];
      const urls = (data.clip_urls || []).filter(Boolean);
      setGcStatus(`Sifted ${items.length} messages • found ${urls.length} clip link(s).`);
      return urls;
    } catch (e) {
      setGcError('fetch');
      setGcStatus('Couldn’t fetch Discord messages. Check DISCORD config.');
      return [];
    }
  }

  // Queue downloads
  async function queueDownloads(urls) {
    if (!wizard.projectId) { throw new Error('Project not created yet.'); }
    if (!urls || urls.length === 0) { throw new Error('No clip URLs to download.'); }
    const limit = Math.max(1, Math.min(100, wizard.maxClips || urls.length));
    let payload = { urls: urls.slice(0, limit), limit };
    if (Array.isArray(wizard.fetchedClips) && wizard.fetchedClips.length) {
      const source = wizard.fetchedClips.slice(0, limit);
      const clips = source.filter(c => c && c.url).map(c => ({
        url: c.url,
        title: c.title,
        creator_id: c.creator_id,
        creator_name: c.creator_name,
        game_name: c.game_name,
        created_at: c.created_at,
      }));
      if (clips.length) payload = { clips, limit };
    }
    const r = await api(`/api/projects/${wizard.projectId}/clips/download`, { method: 'POST', body: JSON.stringify(payload) });
    wizard.downloadTasks = r.items || [];
    setGcStatus(`Queued ${wizard.downloadTasks.length} downloads${wizard.maxClips ? ` (limit ${wizard.maxClips})` : ''}.`);
  }

  // Download progress/polling
  let dlTimer = null;
  async function startDownloadPolling() {
  setGcStatus('Pulling clips down…');
    // Only poll real tasks that have a valid task_id
    const realTasks = (wizard.downloadTasks || []).filter(t => t && t.task_id);
    const total = realTasks.length || 1;
    async function poll(){
      let done = 0, failed = 0;
      for (const t of realTasks) {
        if (!t || !t.task_id) { continue; }
        if (t.done) { done++; continue; }
        try {
          const s = await api(`/api/tasks/${t.task_id}`);
          const st = String((s && (s.state || s.status)) || '').toUpperCase();
          if (st) {
            t._lastState = st;
          }
          if (st === 'SUCCESS' || (s && s.ready && st !== 'FAILURE')) {
            t.done = true; done++;
          } else if (st === 'FAILURE') {
            t.done = true; t.failed = true; done++; failed++;
          }
        } catch (_) {}
      }
      const pct = Math.floor((done / total) * 100);
  setGcStatus(`Pulling clips down… ${pct}% (${done - failed}/${total} ok${failed?`, ${failed} hiccuped`:''})`);
      // Map download progress into the overall focal bar: 40% → 95%
      const overall = 40 + Math.round((pct / 100) * 55);
      setGcFill(overall);
      if (done >= total) {
        clearInterval(dlTimer);
        setGcDone('download');
        setGcDone('done');
        setGcActive('done');
        setGcStatus('Downloads wrapped.');
        setGcFill(100);
        document.getElementById('next-2').disabled = false;
        try { await populateClipsGrid(); } catch (_) {}
        return;
      }
    }
    dlTimer = setInterval(poll, 1000);
    await poll();
  }
  document.getElementById('next-2')?.addEventListener('click', () => gotoStep(3));

  // Step 2 helpers: compact progress UI
  function setGcStatus(text){ const el = document.getElementById('gc-status'); if (el) el.textContent = text || ''; }
  function setGcFill(pct){ const el = document.getElementById('gc-fill'); if (el){ const v = Math.max(0, Math.min(100, Math.floor(pct||0))); el.style.width = v + '%'; el.setAttribute('aria-valuenow', String(v)); } }
  function getGcStepEl(key){ return document.querySelector(`#gc-steps li[data-key="${key}"]`); }
  function clearGcStates(){ document.querySelectorAll('#gc-steps li').forEach(s => { s.classList.remove('active','error'); }); }
  function setGcActive(key){ clearGcStates(); const el = getGcStepEl(key); if (el) el.classList.add('active'); }
  function setGcDone(key){ const el = getGcStepEl(key); if (el){ el.classList.remove('active','error'); el.classList.add('done'); } }
  function setGcError(key){ const el = getGcStepEl(key); if (el){ el.classList.remove('active','done'); el.classList.add('error'); } }

  // Compile summary renderer
  function renderCompileSummary(){
    const details = document.getElementById('compile-details');
    if (!details) return;
    const s = wizard.settings || {};
    const list = document.getElementById('timeline-list');
    const intro = list.querySelector('.timeline-card.timeline-intro');
    const outro = list.querySelector('.timeline-card.timeline-outro');
    const clips = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
    const clipCount = clips.length;
    const clipTitles = clips.map(el => (el.querySelector('.title')?.textContent || el.querySelector('.fw-semibold')?.textContent || 'Clip'));
    const transCount = (wizard.selectedTransitionIds || []).length;
    const transMode = document.getElementById('transitions-randomize')?.checked ? 'Randomized' : 'Cycled';
    // Estimate total duration from timeline
    function num(val){ const n = Number(val); return isFinite(n) ? n : 0; }
    const introSec = intro ? num(intro.dataset.durationSec) : 0;
    const outroSec = outro ? num(outro.dataset.durationSec) : 0;
    const clipSecs = clips.reduce((acc, el) => acc + num(el.dataset.durationSec), 0);
    const segments = (intro ? 1 : 0) + clipCount + (outro ? 1 : 0);
    const gaps = Math.max(0, segments - 1);
    let avgTrans = 0;
    if (transCount) {
      const map = wizard.transitionDurationMap || {};
      const vals = (wizard.selectedTransitionIds || []).map(id => num(map[id])).filter(v => v > 0);
      avgTrans = vals.length ? (vals.reduce((a,b)=>a+b,0) / vals.length) : 3;
    }
    const estimatedSeconds = Math.floor(clipSecs + introSec + outroSec + (transCount ? gaps * avgTrans : 0));
    function fmtSec(sec){ const s = Math.max(0, Math.floor(sec)); const m = Math.floor(s/60); const r = (s%60).toString().padStart(2,'0'); return `${m}:${r}`; }
    // Build combined meta line: "1080p, 60fps, mp4, (-1db)"
    const norm = (typeof s.audio_norm_db === 'number' && !isNaN(s.audio_norm_db)) ? `, (${s.audio_norm_db.toString()}db)` : '';
    const combined = `${s.resolution || ''}, ${s.fps || 60}fps, ${s.format || 'mp4'}${norm}`;
    const yes = '<span class="text-success fw-semibold">Yes</span>';
    const no = '<span class="text-danger fw-semibold">No</span>';
    // Clip mini list (thumb, title, length)
    const itemsHtml = clips.map(el => {
      const title = (el.querySelector('.title')?.textContent || 'Clip');
      const dur = (el.querySelector('.badge-duration')?.textContent || '');
      const bg = el.querySelector('.thumb')?.style?.backgroundImage || '';
      const m = /url\(["']?([^"')]+)["']?\)/.exec(bg);
      const src = m ? m[1] : '';
      const prev = el.dataset.previewUrl || '';
      return `
        <div class="compile-clip-item" data-preview-url="${escapeHtml(prev)}">
          <div class="compile-clip-thumb-wrap">
            <img class="compile-clip-thumb" src="${escapeHtml(src)}" alt="">
          </div>
          <div class="compile-clip-meta">
            <div class="compile-clip-title">${escapeHtml(title)}</div>
            <div class="compile-clip-len text-muted">${escapeHtml(dur)}</div>
          </div>
        </div>`;
    }).join('');

    details.innerHTML = `
      <div class="compile-summary">
        <div class="compile-left small">
          <h6 class="mb-2">Render Summary</h6>
          <div class="mb-1"><strong>Project:</strong> ${escapeHtml(s.name || 'My Compilation')}</div>
          <div class="mb-1"><strong>Output:</strong> ${escapeHtml(combined)}</div>
          <div class="mb-1"><strong>Estimated length:</strong> ${fmtSec(estimatedSeconds)}</div>
          <div class="mb-1"><strong>Intro/Outro:</strong> ${intro ? yes : no}, ${outro ? yes : no}</div>
          <div class="mb-1"><strong>Transitions:</strong> ${transCount ? `${transCount} (${transMode})` : 'None'}</div>
          <div class="text-muted">Clip limits: min ${s.min_len || 0}s • max ${s.max_len || 0}s • max clips ${s.max_clips || 0}${s.start_date || s.end_date ? ` • Dates: ${escapeHtml(s.start_date || '—')} → ${escapeHtml(s.end_date || '—')}` : ''}${s.min_views ? ` • Min views: ${escapeHtml(String(s.min_views))}` : ''}</div>
        </div>
        <div class="compile-right">
          <div class="d-flex justify-content-between align-items-center">
            <h6 class="mb-0">Clips <span class="text-muted small">(${clipCount})</span></h6>
          </div>
          <div class="compile-clip-list">${itemsHtml || '<div class="text-muted small">No clips selected.</div>'}</div>
        </div>
      </div>`;
    try { attachHoverPreviews(details); } catch(_) {}
  }

  function attachHoverPreviews(root){
    const items = Array.from(root.querySelectorAll('.compile-clip-item'));
    items.forEach(it => {
      const wrap = it.querySelector('.compile-clip-thumb-wrap');
      if (!wrap) return;
      let vid = null;
      function show(){
        const url = it.getAttribute('data-preview-url');
        if (!url) return;
        if (vid && vid.isConnected) return;
        vid = document.createElement('video');
        vid.className = 'compile-clip-video';
        vid.src = url;
        vid.muted = true; vid.autoplay = true; vid.loop = true; vid.playsInline = true;
        wrap.appendChild(vid);
      }
      function hide(){ if (vid && vid.parentElement) { vid.pause(); vid.parentElement.removeChild(vid); } vid = null; }
      wrap.addEventListener('mouseenter', show);
      wrap.addEventListener('mouseleave', hide);
      wrap.addEventListener('focus', show, true);
      wrap.addEventListener('blur', hide, true);
    });
  }
  function escapeHtml(str){
    return String(str || '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[ch]));
  }

  async function populateClipsGrid(){
    const lst = await api(`/api/projects/${wizard.projectId}/clips`);
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
      const body = document.createElement('div'); body.className = 'card-body d-flex flex-column';
      const h5 = document.createElement('h5'); h5.className = 'card-title mb-2'; h5.textContent = item.title || 'Clip';
      const ul = document.createElement('ul'); ul.className = 'list-unstyled mb-3 small text-muted';
      const liWho = document.createElement('li'); liWho.textContent = item.creator_name ? `By ${item.creator_name}` : 'Unknown creator';
      const liGame = document.createElement('li'); liGame.textContent = item.game_name ? item.game_name : 'Unknown game';
      const liWhen = document.createElement('li'); liWhen.textContent = item.created_at ? new Date(item.created_at).toLocaleString() : 'Unknown date';
      ul.appendChild(liWho); ul.appendChild(liGame); ul.appendChild(liWhen);
      const btn = document.createElement('a'); btn.href = '#'; btn.className = 'btn btn-sm btn-primary mt-auto'; btn.textContent = 'Add to timeline';
      btn.addEventListener('click', (e) => { e.preventDefault();
        const list = document.getElementById('timeline-list');
        const cardEl = makeTimelineCard({
          title: item.title || 'Clip',
          subtitle: [item.creator_name ? `By ${item.creator_name}` : '', item.game_name ? `• ${item.game_name}` : ''].filter(Boolean).join(' '),
          thumbUrl: (item.media && item.media.thumbnail_url) || '',
          clipId: item.id,
          durationSec: (typeof item.duration === 'number' ? item.duration : (item.media && (typeof item.media.duration === 'number') ? item.media.duration : undefined)),
          kind: 'clip',
          previewUrl: (item.media && item.media.preview_url) || ''
        });
        // Insert new clips before Outro so Outro stays last
        const outro = list.querySelector('.timeline-card.timeline-outro');
        if (outro) {
          list.insertBefore(cardEl, outro);
        } else {
          list.appendChild(cardEl);
        }
        card.classList.add('d-none');
        updateClipsGridState();
        // Do not auto-check arrange confirmation; user must explicitly confirm
      });
      body.appendChild(h5); body.appendChild(ul); body.appendChild(btn); card.appendChild(body); grid.appendChild(card);
    });
    updateClipsGridState();
  }

  // Arrange gating
  const next3Btn = document.getElementById('next-3');
  const arrangedConfirm = document.getElementById('arranged-confirm');
  arrangedConfirm?.addEventListener('change', () => { if (next3Btn) next3Btn.disabled = !arrangedConfirm.checked; });
  document.getElementById('next-3')?.addEventListener('click', async () => {
    try { await saveTimelineOrder(); } catch (_) {}
    gotoStep(4);
  });

  // Timeline helpers
  function makeTimelineCard({title, subtitle, thumbUrl, clipId, kind, durationSec, previewUrl}){
    const card = document.createElement('div');
    card.className = 'timeline-card';
    // Lock intro/outro from dragging
    card.draggable = !(kind === 'intro' || kind === 'outro');
    if (clipId) card.dataset.clipId = String(clipId);
    if (kind) card.dataset.kind = kind;
    if (typeof durationSec === 'number' && !isNaN(durationSec)) card.dataset.durationSec = String(durationSec);
    if (previewUrl) card.dataset.previewUrl = String(previewUrl);
    // Add semantic class for styling by type
    if (kind) {
      card.classList.add(`timeline-${kind}`);
    }

    // Background thumbnail layer
    const thumb = document.createElement('div');
    thumb.className = 'thumb';
    if (thumbUrl) thumb.style.backgroundImage = `url(${thumbUrl})`;
    card.appendChild(thumb);

    // Duration badge
    if (typeof durationSec === 'number' && !isNaN(durationSec)){
      const badge = document.createElement('div');
      const mm = Math.floor(durationSec / 60);
      const ss = Math.round(durationSec % 60).toString().padStart(2,'0');
      badge.className = 'badge-duration';
      badge.textContent = `${mm}:${ss}`;
      card.appendChild(badge);
    }

    // Remove button
    const rm = document.createElement('button');
    rm.className = 'btn btn-sm btn-outline-danger btn-remove';
    rm.innerHTML = '×';
    rm.title = 'Remove';
    // Prevent drag interactions when clicking remove
    rm.addEventListener('dragstart', (e) => { e.stopPropagation(); e.preventDefault(); });
    rm.addEventListener('mousedown', (e) => { e.stopPropagation(); });
    rm.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      card.remove();
      rebuildSeparators();
      if (clipId){
        const src = document.querySelector(`.clip-card[data-clip-id="${clipId}"]`);
        if (src) src.classList.remove('d-none');
        updateClipsGridState();
      }
      const list = document.getElementById('timeline-list');
      if (list && list.querySelectorAll('.timeline-card[data-clip-id]').length === 0) {
        const chk = document.getElementById('arranged-confirm');
        if (chk) { chk.checked = false; chk.dispatchEvent(new Event('change')); }
      }
      saveTimelineOrder().catch(()=>{});
    });
    card.appendChild(rm);

    // Bottom overlay title/subtitle
    const ov = document.createElement('div');
    ov.className = 'overlay';
    const h6 = document.createElement('div'); h6.className = 'title text-truncate'; h6.textContent = title || 'Item';
    const small = document.createElement('div'); small.className = 'subtitle text-truncate'; small.textContent = subtitle || '';
    ov.appendChild(h6); ov.appendChild(small);
    card.appendChild(ov);

    // DnD handlers
    card.addEventListener('dragstart', (e) => {
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => { card.classList.remove('dragging'); rebuildSeparators(); saveTimelineOrder().catch(()=>{}); });
    return card;
  }

  function addIntroToTimeline(item){
    const list = document.getElementById('timeline-list');
    const existing = list.querySelector('.timeline-card.timeline-intro');
    if (existing) existing.remove();
  const card = makeTimelineCard({ title: `Intro`, subtitle: item.original_filename || item.filename, thumbUrl: item.thumbnail_url || '', kind: 'intro', durationSec: item.duration, previewUrl: item.preview_url || '' });
    card.classList.add('timeline-intro');
    list.prepend(card);
    rebuildSeparators();
  }
  function addOutroToTimeline(item){
    const list = document.getElementById('timeline-list');
    const existing = list.querySelector('.timeline-card.timeline-outro');
    if (existing) existing.remove();
  const card = makeTimelineCard({ title: `Outro`, subtitle: item.original_filename || item.filename, thumbUrl: item.thumbnail_url || '', kind: 'outro', durationSec: item.duration, previewUrl: item.preview_url || '' });
    card.classList.add('timeline-outro');
    list.appendChild(card);
    rebuildSeparators();
  }

  // Drag and drop container behavior
  (function initTimelineDnD(){
    const list = document.getElementById('timeline-list');
    // Single placeholder element indicating insertion point
    let insertPlaceholder = null;
    function getOrCreateInsertPlaceholder(){
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
    function getDragAfterElement(container, x){
      const els = [...container.querySelectorAll('.timeline-card:not(.dragging)')];
      return els.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = x - box.left - box.width / 2;
        if (offset < 0 && offset > closest.offset) return { offset, element: child };
        else return closest;
      }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
    }
    function placeInsertPlaceholder(x){
      const ph = getOrCreateInsertPlaceholder();
      const intro = list.querySelector('.timeline-card.timeline-intro');
      const outro = list.querySelector('.timeline-card.timeline-outro');
      let after = getDragAfterElement(list, x);
      // Prevent placing before intro
      if (intro && after === intro) after = intro.nextElementSibling;
      // Ensure placeholder exists in DOM for correct relative inserts
      if (!ph.isConnected) list.appendChild(ph);
      if (outro && (after == null || after === outro)) {
        list.insertBefore(ph, outro);
      } else if (after == null) {
        list.appendChild(ph);
      } else {
        list.insertBefore(ph, after);
      }
    }
    function removeInsertPlaceholder(){
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
      if (dragging && insertPlaceholder && insertPlaceholder.parentElement === list){
        list.insertBefore(dragging, insertPlaceholder);
      }
      removeInsertPlaceholder();
      rebuildSeparators();
      saveTimelineOrder().catch(()=>{});
    });
    list.addEventListener('dragleave', (e) => {
      // If leaving the list entirely, keep placeholder until drop or end to avoid flicker
      // No-op intentionally
    });
    document.addEventListener('dragend', () => {
      removeInsertPlaceholder();
    });
  })();

  function rebuildSeparators(){
    const list = document.getElementById('timeline-list');
    if (!list) return;
    // Remove existing separators
    Array.from(list.querySelectorAll('.timeline-sep')).forEach(el => el.remove());
    // Insert a narrow static separator between each timeline-card
    const cards = Array.from(list.querySelectorAll('.timeline-card'));
    for (let i = 0; i < cards.length - 1; i++){
      // Don't place separator after outro
      if (cards[i].classList.contains('timeline-outro')) continue;
      const sep = document.createElement('div');
      sep.className = 'timeline-sep';
      const lbl = document.createElement('div');
      lbl.className = 'timeline-sep-label';
      lbl.textContent = (wizard.selectedTransitionIds && wizard.selectedTransitionIds.length) ? 'transition' : 'static';
      sep.appendChild(lbl);
      list.insertBefore(sep, cards[i+1]);
    }
    // Apply transition visual if any transitions are selected
    updateSeparatorLabels();
  }

  function updateSeparatorLabels(){
    const list = document.getElementById('timeline-list');
    if (!list) return;
    const hasTransitions = !!(wizard.selectedTransitionIds && wizard.selectedTransitionIds.length);
    Array.from(list.querySelectorAll('.timeline-sep')).forEach(sep => {
      const lbl = sep.querySelector('.timeline-sep-label');
      if (lbl) lbl.textContent = hasTransitions ? 'transition' : 'static';
      sep.classList.toggle('has-transition', hasTransitions);
    });
  }

  async function saveTimelineOrder(){
    if (!wizard.projectId) return;
    const list = document.getElementById('timeline-list');
    const ids = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]')).map(el => parseInt(el.dataset.clipId, 10)).filter(Boolean);
    if (!ids.length) return;
    await api(`/api/projects/${wizard.projectId}/clips/order`, { method: 'POST', body: JSON.stringify({ clip_ids: ids }) });
  }

  // Compile and poll
  let compTimer = null;
  document.getElementById('start-compile')?.addEventListener('click', async () => {
  if (!wizard.projectId) { alert('No project loaded yet.'); return; }
    const bar = document.getElementById('compile-progress');
    const log = document.getElementById('compile-log');
    // Disable start during active compilation
    const startBtn = document.getElementById('start-compile');
    if (startBtn) startBtn.disabled = true;
    bar.style.width = '0%'; bar.textContent = '0%';
    document.getElementById('cancel-compile').disabled = false;
    renderCompileSummary();
  log.textContent = 'Splicing your highlights together…';
    try {
      const body = { };
      if (wizard.selectedIntroId) body.intro_id = wizard.selectedIntroId;
      if (wizard.selectedOutroId) body.outro_id = wizard.selectedOutroId;
      if (Array.isArray(wizard.selectedTransitionIds) && wizard.selectedTransitionIds.length) {
        body.transition_ids = wizard.selectedTransitionIds;
        body.randomize_transitions = !!document.getElementById('transitions-randomize')?.checked;
      }
      const r = await api(`/api/projects/${wizard.projectId}/compile`, { method: 'POST', body: JSON.stringify(body) });
      wizard.compileTaskId = r.task_id;
      if (!wizard.compileTaskId) {
        document.getElementById('cancel-compile').disabled = true;
        log.textContent = 'Failed to start compilation: missing task id.';
        return;
      }
      async function poll(){
        try {
          if (!wizard.compileTaskId) return;
          const s = await api(`/api/tasks/${wizard.compileTaskId}`);
          const st = s.state || s.status;
          const meta = s.info || {};
          const pct = Math.max(0, Math.min(100, Math.floor(meta.progress || 0)));
          bar.style.width = pct + '%'; bar.textContent = pct + '%';
          // Show current stage/step in log window if provided
          const stage = meta.stage || meta.step || meta.phase || meta.task || '';
          const msg = meta.message || meta.detail || meta.status || '';
          const parts = [];
          if (stage) parts.push(`[${stage}]`);
          if (msg) parts.push(msg);
          if (parts.length) log.textContent = parts.join(' ') + `\n${pct}%`;
          if (st === 'SUCCESS') {
            clearInterval(compTimer);
            document.getElementById('cancel-compile').disabled = true;
            if (startBtn) startBtn.disabled = true; // keep disabled after success
            log.textContent = "Show’s in the can!";
            document.getElementById('next-4').disabled = false;
            document.getElementById('export-ready').classList.remove('d-none');
            try { await refreshExportInfo(); } catch (e) {
              const dl = document.getElementById('download-output');
              dl.classList.remove('disabled');
              dl.href = `/projects/${wizard.projectId}/download-output`;
            }
            document.getElementById('upload-youtube').classList.remove('disabled');
            document.getElementById('upload-discord').classList.remove('disabled');
            return;
          }
          if (st === 'FAILURE') {
            clearInterval(compTimer);
            document.getElementById('cancel-compile').disabled = true;
            if (startBtn) startBtn.disabled = false; // allow retry on failure
            log.textContent = 'The cut failed. Let’s tweak and retry.';
            return;
          }
        } catch (_) {}
      }
      compTimer = setInterval(poll, 1200);
      poll();
    } catch (e) {
      alert('Couldn’t start the cut: ' + e.message);
    }
  });
  document.getElementById('cancel-compile')?.addEventListener('click', () => {
    if (compTimer) { clearInterval(compTimer); }
    document.getElementById('compile-log').textContent = 'Cut canceled.';
    const startBtn = document.getElementById('start-compile');
    if (startBtn) startBtn.disabled = false;
    document.getElementById('cancel-compile').disabled = true;
  });
  document.getElementById('next-4')?.addEventListener('click', () => gotoStep(5));

  // Default routing states on load
  gotoStep(1);
  updateTwitchWarning();
  // Render summary when entering Step 4
  document.querySelector('#wizard-chevrons li[data-step="4"]')?.addEventListener('click', () => {
    setTimeout(renderCompileSummary, 0);
  });

  async function refreshExportInfo(){
    if (!wizard.projectId) return;
    try {
      const details = await api(`/api/projects/${wizard.projectId}`);
      const dl = document.getElementById('download-output');
      const ready = document.getElementById('export-ready');
      if (details && details.download_url) {
        dl.classList.remove('disabled');
        dl.href = details.download_url;
        ready.classList.remove('d-none');
        dl.textContent = `Download Video${details.output_filename ? ` (${details.output_filename})` : ''}`;
      }
    } catch (_) {}
  }

  // Intro/Outro listing and selection
  async function loadMediaList(kind){
    if (!wizard.projectId) return [];
    try {
      const res = await fetch(`/api/projects/${wizard.projectId}/media?type=${encodeURIComponent(kind)}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      return data.items || [];
    } catch (_) { return []; }
  }
  function renderMediaList(containerId, items, selectHandler){
    const el = document.getElementById(containerId);
    el.innerHTML = '';
    if (!items.length){ el.innerHTML = '<div class="text-muted">No media found.</div>'; return; }
    items.forEach(it => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.width = '160px';
      card.style.cursor = 'pointer';
      const img = document.createElement('img');
      img.className = 'card-img-top';
      img.alt = it.original_filename || it.filename;
      img.src = it.thumbnail_url || '';
      img.onerror = () => { img.classList.add('d-none'); };
      const body = document.createElement('div');
      body.className = 'card-body p-2';
      const title = document.createElement('div');
      title.className = 'small text-truncate';
      title.textContent = it.original_filename || it.filename;
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm btn-primary w-100 mt-1';
      btn.textContent = 'Add to timeline';
      btn.addEventListener('click', (e) => { e.stopPropagation(); selectHandler(it); });
      card.addEventListener('click', () => {
        if (it.preview_url) window.open(it.preview_url, '_blank');
      });
      body.appendChild(title);
      body.appendChild(btn);
      card.appendChild(img);
      card.appendChild(body);
      el.appendChild(card);
    });
  }
  async function refreshIntros(){
    const items = await loadMediaList('intro');
    renderMediaList('intro-list', items, (it) => {
      wizard.selectedIntroId = it.id;
      addIntroToTimeline(it);
      document.querySelectorAll('#intro-list .card').forEach(c => c.classList.remove('border-primary'));
      const found = Array.from(document.querySelectorAll('#intro-list .card')).find(c => c.querySelector('.small')?.textContent === (it.original_filename || it.filename));
      if (found) found.classList.add('border', 'border-primary');
    });
  }
  async function refreshOutros(){
    const items = await loadMediaList('outro');
    renderMediaList('outro-list', items, (it) => {
      wizard.selectedOutroId = it.id;
      addOutroToTimeline(it);
      document.querySelectorAll('#outro-list .card').forEach(c => c.classList.remove('border-primary'));
      const found = Array.from(document.querySelectorAll('#outro-list .card')).find(c => c.querySelector('.small')?.textContent === (it.original_filename || it.filename));
      if (found) found.classList.add('border', 'border-primary');
    });
  }
  async function refreshTransitions(){
    const items = await loadMediaList('transition');
    const container = document.getElementById('transition-list');
    container.innerHTML = '';
    wizard.selectedTransitionIds = wizard.selectedTransitionIds || [];
    wizard.availableTransitionIds = (items || []).map(it => it.id);
    wizard.transitionDurationMap = Object.fromEntries((items || []).map(it => [it.id, it.duration || 0]));
    if (!items.length){ container.innerHTML = '<div class="text-muted">No transitions found.</div>'; return; }
    items.forEach(it => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.width = '160px';
      const img = document.createElement('img');
      img.className = 'card-img-top';
      img.alt = it.original_filename || it.filename;
      img.src = it.thumbnail_url || '';
      img.onerror = () => { img.classList.add('d-none'); };
      const body = document.createElement('div');
      body.className = 'card-body p-2';
      const row = document.createElement('div');
      row.className = 'd-flex align-items-center gap-2';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'form-check-input';
      cb.dataset.transitionId = String(it.id);
      cb.checked = wizard.selectedTransitionIds.includes(it.id);
      cb.addEventListener('change', () => {
        if (cb.checked) {
          if (!wizard.selectedTransitionIds.includes(it.id)) wizard.selectedTransitionIds.push(it.id);
        } else {
          wizard.selectedTransitionIds = wizard.selectedTransitionIds.filter(x => x !== it.id);
        }
        renderTransitionsBadge();
      });
      const title = document.createElement('div');
      title.className = 'small text-truncate';
      title.textContent = it.original_filename || it.filename;
      row.appendChild(cb);
      row.appendChild(title);
      body.appendChild(row);
      card.appendChild(img);
      card.appendChild(body);
      container.appendChild(card);
    });
  }
  function renderTransitionsBadge(){
    const tl = document.getElementById('timeline');
    const info = document.getElementById('timeline-info');
    const list = document.getElementById('timeline-list');
    if (!tl || !list) return;
    let badge = (info || tl).querySelector('.timeline-transitions');
    if (!badge) {
      badge = document.createElement('div');
      badge.className = 'timeline-item alert py-1 px-2 mb-2 timeline-transitions';
    }
    // Place badge in the dedicated info area if present
    if (info) {
      info.innerHTML = '';
      info.appendChild(badge);
    } else {
      tl.insertBefore(badge, list);
    }
    const count = (wizard.selectedTransitionIds || []).length;
    const rand = document.getElementById('transitions-randomize')?.checked;
    badge.textContent = count ? `Transitions selected: ${count}${count>1 ? (rand ? ' (randomized)' : ' (cycled)') : ''}` : 'No transitions selected';
    // Tint separators/labels accordingly
    try { updateSeparatorLabels(); } catch(_) {}
  }
  document.getElementById('transitions-randomize')?.addEventListener('change', renderTransitionsBadge);
  document.getElementById('select-all-transitions')?.addEventListener('click', (e) => {
    e.preventDefault();
    const list = document.getElementById('transition-list');
    const boxes = Array.from(list.querySelectorAll('input.form-check-input[type="checkbox"]'));
    const ids = new Set(wizard.availableTransitionIds || []);
    boxes.forEach(cb => { cb.checked = true; const id = parseInt(cb.dataset.transitionId || '0', 10); if (id) ids.add(id); });
    wizard.selectedTransitionIds = Array.from(ids);
    renderTransitionsBadge();
  });
  document.getElementById('clear-all-transitions')?.addEventListener('click', (e) => {
    e.preventDefault();
    const list = document.getElementById('transition-list');
    const boxes = Array.from(list.querySelectorAll('input.form-check-input[type="checkbox"]'));
    boxes.forEach(cb => { cb.checked = false; });
    wizard.selectedTransitionIds = [];
    renderTransitionsBadge();
  });
  // When clicking the Arrange chevron, auto-refresh lists too (in case user navigates directly)
  document.querySelector('#wizard-chevrons li[data-step="3"]')?.addEventListener('click', () => {
    Promise.resolve().then(async () => {
      try { await refreshIntros(); } catch (_) {}
      try { await refreshOutros(); } catch (_) {}
      try { await refreshTransitions(); } catch (_) {}
      try { renderTransitionsBadge(); } catch (_) {}
    });
  });

  // Ensure separators rebuild when adding clip from grid to timeline
  function attachAddToTimelineHandlers(){
    const grid = document.getElementById('clips-grid');
    if (!grid) return;
    grid.querySelectorAll('.clip-card a.btn').forEach(btn => {
      if (btn._timelineHandlerAttached) return;
      btn._timelineHandlerAttached = true;
      btn.addEventListener('click', () => {
        setTimeout(() => { try { rebuildSeparators(); } catch(_) {} }, 0);
      });
    });
  }
  // Run after clips grid gets populated
  const _populateClipsGrid = populateClipsGrid;
  populateClipsGrid = async function(){
    await _populateClipsGrid.apply(this, arguments);
    attachAddToTimelineHandlers();
  };

  // Collapsible Downloaded Clips logic
  function updateClipsGridState(){
    const grid = document.getElementById('clips-grid');
    const wrap = document.getElementById('clips-collapse');
    const badge = document.getElementById('clips-remaining');
    if (!grid || !wrap) return;
    const cards = Array.from(grid.querySelectorAll('.clip-card'));
    const visible = cards.filter(c => !c.classList.contains('d-none')).length;
    if (badge) {
      const total = cards.length;
      if (total > 0) {
        badge.textContent = `Available: ${visible}/${total}`;
      } else {
        badge.textContent = '';
      }
    }
    const wantCollapsed = (visible === 0 && cards.length > 0);
    // Bootstrap Collapse API if available
    try {
      const Coll = window.bootstrap?.Collapse;
      if (Coll) {
        let inst = Coll.getInstance(wrap);
        if (!inst) inst = new Coll(wrap, { toggle: false });
        if (wantCollapsed) inst.hide(); else inst.show();
      } else {
        // Fallback: toggle 'show' class
        wrap.classList.toggle('show', !wantCollapsed);
      }
    } catch (_) {
      wrap.classList.toggle('show', !wantCollapsed);
    }
  }
})();
