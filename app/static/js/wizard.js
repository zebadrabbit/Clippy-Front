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
        alert('Please arrange your timeline before proceeding to compile.');
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
  document.getElementById('next-1')?.addEventListener('click', async () => {
    const route = routeSelect.value;
    const form = document.getElementById('setup-form');
    const fd = new FormData(form);
    const maxClips = parseInt(fd.get('max_clips') || '20', 10);
    const payload = {
      name: (fd.get('name') || 'My Compilation').toString(),
      description: (fd.get('description') || '').toString(),
      output_resolution: (fd.get('resolution') || '1080p').toString(),
      output_format: (fd.get('format') || 'mp4').toString(),
      max_clip_duration: parseInt(fd.get('max_len') || '300', 10)
    };
    // Persist settings for Compile summary
    wizard.settings = {
      route: route,
      name: payload.name,
      description: payload.description,
      resolution: payload.output_resolution,
      format: payload.output_format,
  fps: parseInt(fd.get('fps') || '30', 10),
      max_clips: Math.max(1, Math.min(500, parseInt(fd.get('max_clips') || '20', 10))),
      min_len: parseInt(fd.get('min_len') || '5', 10),
      max_len: payload.max_clip_duration,
      start_date: fd.get('start_date') || '',
      end_date: fd.get('end_date') || '',
      min_views: fd.get('min_views') || ''
    };
    try {
      const r = await api('/api/projects', { method: 'POST', body: JSON.stringify(payload) });
      wizard.projectId = r.project_id;
      wizard.route = route;
      wizard.maxClips = Math.max(1, Math.min(100, isNaN(maxClips) ? 20 : maxClips));
      gotoStep(2);
      // Auto-run Get Clips behind the scenes
      setGcActive('fetch');
      setGcStatus('Fetching clips…');
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
          setGcStatus(`Queued ${wizard.downloadTasks.length} download(s).`);
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
            setGcStatus('All clips already downloaded. Reused existing media.');
            setGcFill(100);
            document.getElementById('next-2').disabled = false;
            try { await populateClipsGrid(); } catch (_) {}
          }
        }
      } catch (_) {}
    } catch (e) {
      alert('Failed to create project: ' + e.message);
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
      setGcStatus(`Fetched ${items.length} clips for @${data.username}.`);
      return urls;
    } catch (e) {
      setGcError('fetch');
      setGcStatus('Failed to fetch clips. Check your Twitch settings.');
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
      setGcStatus(`Fetched ${items.length} messages • detected ${urls.length} clip URL(s).`);
      return urls;
    } catch (e) {
      setGcError('fetch');
      setGcStatus('Failed to fetch Discord messages. Check DISCORD config.');
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
    setGcStatus('Downloading…');
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
      setGcStatus(`Downloading… ${pct}% (${done - failed}/${total} ok${failed?`, ${failed} failed`:''})`);
      // Map download progress into the overall focal bar: 40% → 95%
      const overall = 40 + Math.round((pct / 100) * 55);
      setGcFill(overall);
      if (done >= total) {
        clearInterval(dlTimer);
        setGcDone('download');
        setGcDone('done');
        setGcStatus('Downloads complete.');
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
  function clearGcStates(){ document.querySelectorAll('#gc-steps li').forEach(s => { s.classList.remove('active','done','error'); }); }
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
    const clipTitles = clips.map(el => el.querySelector('.fw-semibold')?.textContent || 'Clip');
    const transCount = (wizard.selectedTransitionIds || []).length;
    const transMode = document.getElementById('transitions-randomize')?.checked ? 'Randomized' : 'Cycled';
    const parts = [];
    parts.push(`<h6 class="mb-2">Render Summary</h6>`);
    parts.push('<div class="row small g-2">');
    parts.push(`<div class="col-md-6"><strong>Project:</strong> ${escapeHtml(s.name || 'My Compilation')}</div>`);
    parts.push(`<div class="col-md-6"><strong>Route:</strong> ${escapeHtml(s.route || '')}</div>`);
    parts.push(`<div class="col-md-6"><strong>Resolution:</strong> ${escapeHtml(s.resolution || '')}</div>`);
    parts.push(`<div class="col-md-6"><strong>Format/FPS:</strong> ${escapeHtml((s.format || '') + (s.fps?` @ ${s.fps}fps`:''))}</div>`);
    parts.push(`<div class="col-md-6"><strong>Clip Limits:</strong> min ${s.min_len || 0}s • max ${s.max_len || 0}s • max clips ${s.max_clips || 0}</div>`);
    if (s.start_date || s.end_date) parts.push(`<div class="col-md-6"><strong>Date Range:</strong> ${escapeHtml(s.start_date || '—')} to ${escapeHtml(s.end_date || '—')}</div>`);
    if (s.min_views) parts.push(`<div class="col-md-6"><strong>Min Views:</strong> ${escapeHtml(String(s.min_views))}</div>`);
    parts.push(`<div class="col-md-6"><strong>Intro:</strong> ${intro ? 'Yes' : 'No'}</div>`);
    parts.push(`<div class="col-md-6"><strong>Outro:</strong> ${outro ? 'Yes' : 'No'}</div>`);
    parts.push(`<div class="col-12"><strong>Clips (${clipCount}):</strong> ${clipTitles.map(escapeHtml).join(', ') || '—'}</div>`);
    parts.push(`<div class="col-12"><strong>Transitions:</strong> ${transCount ? `${transCount} (${transMode})` : 'None'}</div>`);
    parts.push('</div>');
    details.innerHTML = parts.join('\n');
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
          kind: 'clip'
        });
        // Insert new clips before Outro so Outro stays last
        const outro = list.querySelector('.timeline-card.timeline-outro');
        if (outro) {
          list.insertBefore(cardEl, outro);
        } else {
          list.appendChild(cardEl);
        }
        card.classList.add('d-none');
        // Do not auto-check arrange confirmation; user must explicitly confirm
      });
      body.appendChild(h5); body.appendChild(ul); body.appendChild(btn); card.appendChild(body); grid.appendChild(card);
    });
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
  function makeTimelineCard({title, subtitle, thumbUrl, clipId, kind}){
    const card = document.createElement('div');
    card.className = 'card timeline-card';
    // Keep intro at first and outro at last by preventing their drag
    card.draggable = !(kind === 'intro' || kind === 'outro');
    if (clipId) card.dataset.clipId = String(clipId);
    if (kind) card.dataset.kind = kind;
    const row = document.createElement('div');
    row.className = 'row g-0 align-items-center';
    if (thumbUrl){
      const colImg = document.createElement('div');
      colImg.className = 'col-auto';
      const img = document.createElement('img');
      img.src = thumbUrl; img.alt = title || 'thumb';
      img.style.width = '64px'; img.style.height = '48px'; img.style.objectFit = 'cover';
      img.className = 'rounded-start';
      colImg.appendChild(img); row.appendChild(colImg);
    }
    const colBody = document.createElement('div'); colBody.className = 'col';
    const body = document.createElement('div'); body.className = 'card-body py-2 px-3';
    const h6 = document.createElement('div'); h6.className = 'fw-semibold text-truncate'; h6.textContent = title || 'Item';
    const small = document.createElement('div'); small.className = 'small text-muted text-truncate'; small.textContent = subtitle || '';
    body.appendChild(h6); body.appendChild(small); colBody.appendChild(body); row.appendChild(colBody);
    const colBtn = document.createElement('div'); colBtn.className = 'col-auto pe-2';
    const rm = document.createElement('button'); rm.className = 'btn btn-sm btn-outline-danger'; rm.textContent = 'Remove';
    rm.addEventListener('click', () => {
      card.remove();
      if (clipId){
        const src = document.querySelector(`.clip-card[data-clip-id="${clipId}"]`);
        if (src) src.classList.remove('d-none');
      }
      const list = document.getElementById('timeline-list');
      if (list && list.querySelectorAll('.timeline-card[data-clip-id]').length === 0) {
        const chk = document.getElementById('arranged-confirm');
        if (chk) { chk.checked = false; chk.dispatchEvent(new Event('change')); }
      }
    });
    colBtn.appendChild(rm); row.appendChild(colBtn);
    card.appendChild(row);

    // DnD handlers
    card.addEventListener('dragstart', (e) => {
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => { card.classList.remove('dragging'); saveTimelineOrder().catch(()=>{}); });
    return card;
  }

  function addIntroToTimeline(item){
    const list = document.getElementById('timeline-list');
    const existing = list.querySelector('.timeline-card.timeline-intro');
    if (existing) existing.remove();
    const card = makeTimelineCard({ title: `Intro`, subtitle: item.original_filename || item.filename, thumbUrl: item.thumbnail_url || '', kind: 'intro' });
    card.classList.add('timeline-intro');
    list.prepend(card);
  }
  function addOutroToTimeline(item){
    const list = document.getElementById('timeline-list');
    const existing = list.querySelector('.timeline-card.timeline-outro');
    if (existing) existing.remove();
    const card = makeTimelineCard({ title: `Outro`, subtitle: item.original_filename || item.filename, thumbUrl: item.thumbnail_url || '', kind: 'outro' });
    card.classList.add('timeline-outro');
    list.appendChild(card);
  }

  // Drag and drop container behavior
  (function initTimelineDnD(){
    const list = document.getElementById('timeline-list');
    const topInd = document.getElementById('timeline-drop-top');
    const botInd = document.getElementById('timeline-drop-bottom');
    function getDragAfterElement(container, y){
      const els = [...container.querySelectorAll('.timeline-card:not(.dragging)')];
      return els.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) return { offset, element: child };
        else return closest;
      }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
    }
    list.addEventListener('dragover', (e) => {
      e.preventDefault();
      const after = getDragAfterElement(list, e.clientY);
      const dragging = document.querySelector('.timeline-card.dragging');
      if (!dragging) return;
      // Enforce that intro stays first and outro stays last
      const intro = list.querySelector('.timeline-card.timeline-intro');
      const outro = list.querySelector('.timeline-card.timeline-outro');
      let target = after;
      if (intro && target === intro) {
        target = intro.nextElementSibling; // never insert before intro
      }
      if (outro && (target == null)) {
        // appending: ensure it's placed before outro
        list.insertBefore(dragging, outro);
      } else if (outro && target === outro) {
        // don't insert after outro; insert before it
        list.insertBefore(dragging, outro);
      } else if (target == null) {
        list.appendChild(dragging);
      } else {
        list.insertBefore(dragging, target);
      }
      topInd.classList.toggle('active', list.firstChild === dragging);
      botInd.classList.toggle('active', list.lastChild === dragging);
    });
    list.addEventListener('drop', () => { topInd.classList.remove('active'); botInd.classList.remove('active'); });
  })();

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
    if (!wizard.projectId) { alert('Project not set.'); return; }
    const bar = document.getElementById('compile-progress');
    const log = document.getElementById('compile-log');
    // Disable start during active compilation
    const startBtn = document.getElementById('start-compile');
    if (startBtn) startBtn.disabled = true;
    bar.style.width = '0%'; bar.textContent = '0%';
    document.getElementById('cancel-compile').disabled = false;
    renderCompileSummary();
    log.textContent = 'Starting compilation...';
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
            log.textContent = 'Compilation complete.';
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
            log.textContent = 'Compilation failed.';
            return;
          }
        } catch (_) {}
      }
      compTimer = setInterval(poll, 1200);
      poll();
    } catch (e) {
      alert('Failed to start compilation: ' + e.message);
    }
  });
  document.getElementById('cancel-compile')?.addEventListener('click', () => {
    if (compTimer) { clearInterval(compTimer); }
    document.getElementById('compile-log').textContent = 'Cancelled.';
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
    const list = document.getElementById('timeline-list');
    if (!tl || !list) return;
    let badge = tl.querySelector('.timeline-transitions');
    if (!badge) {
      badge = document.createElement('div');
      badge.className = 'timeline-item alert alert-info py-1 px-2 mt-2 mb-2 timeline-transitions';
    }
    // Ensure badge is placed at the top of the timeline, just before the list
    tl.insertBefore(badge, list);
    const count = (wizard.selectedTransitionIds || []).length;
    const rand = document.getElementById('transitions-randomize')?.checked;
    badge.textContent = count ? `Transitions selected: ${count}${count>1 ? (rand ? ' (randomized)' : ' (cycled)') : ''}` : 'No transitions selected';
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
})();
