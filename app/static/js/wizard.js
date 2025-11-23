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
        // Proactively import rsynced raw clips when entering Arrange if none are present yet
        try {
          const lst = await api(`/api/projects/${wizard.projectId}/clips`);
          const hasAny = Array.isArray(lst?.items) && lst.items.length > 0;
          if (!hasAny) {
            // Run a shallow ingest so we don't block the UI for long
            try {
              showArrangeIngestBanner('Importing rsynced raw clips…');
              await runRawIngest({ shallow: true });
            } catch (_) { /* non-fatal */ }
          }
        } catch (_) {}
        try { await populateClipsGrid(); } catch (_) {}
        hideArrangeIngestBanner();
        try { await refreshIntros(); } catch (_) {}
        try { await refreshOutros(); } catch (_) {}
        try { await refreshTransitions(); } catch (_) {}
        try { renderTransitionsBadge(); } catch (_) {}
      });
    }
  }

  // Arrange ingest banner helpers
  function showArrangeIngestBanner(text){
    try {
      const el = document.getElementById('arrange-ingest-banner');
      const label = document.getElementById('arrange-ingest-text');
      if (!el) return;
      if (label && typeof text === 'string' && text.trim() !== '') label.textContent = text;
      el.classList.remove('d-none');
    } catch (_) {}
  }
  function hideArrangeIngestBanner(){
    try {
      const el = document.getElementById('arrange-ingest-banner');
      if (!el) return;
      el.classList.add('d-none');
    } catch (_) {}
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

  // Undo/Redo Command History Manager
  const commandHistory = {
    undoStack: [],
    redoStack: [],
    maxHistory: 50, // Limit history to prevent memory issues

    // Execute and record a command
    execute(command) {
      command.execute();
      this.undoStack.push(command);
      // Clear redo stack when new action is performed
      this.redoStack = [];
      // Limit history size
      if (this.undoStack.length > this.maxHistory) {
        this.undoStack.shift();
      }
    },

    // Undo last action
    undo() {
      if (this.undoStack.length === 0) {
        console.log('Nothing to undo');
        return false;
      }
      const command = this.undoStack.pop();
      command.undo();
      this.redoStack.push(command);
      return true;
    },

    // Redo last undone action
    redo() {
      if (this.redoStack.length === 0) {
        console.log('Nothing to redo');
        return false;
      }
      const command = this.redoStack.pop();
      command.execute();
      this.undoStack.push(command);
      return true;
    },

    // Clear all history
    clear() {
      this.undoStack = [];
      this.redoStack = [];
    },

    // Check if undo/redo available
    canUndo() {
      return this.undoStack.length > 0;
    },

    canRedo() {
      return this.redoStack.length > 0;
    }
  };

  // Command: Move clip in timeline
  function MoveClipCommand(clipId, oldIndex, newIndex) {
    return {
      type: 'move',
      clipId: clipId,
      oldIndex: oldIndex,
      newIndex: newIndex,
      execute() {
        const list = document.getElementById('timeline-list');
        const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
        const card = cards.find(c => parseInt(c.dataset.clipId) === this.clipId);
        if (!card) return;

        // Move card to new position
        const targetCard = cards[this.newIndex];
        if (targetCard && targetCard !== card) {
          if (this.newIndex > this.oldIndex) {
            targetCard.after(card);
          } else {
            targetCard.before(card);
          }
        }
        saveTimelineOrder().catch(() => {});
      },
      undo() {
        const list = document.getElementById('timeline-list');
        const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
        const card = cards.find(c => parseInt(c.dataset.clipId) === this.clipId);
        if (!card) return;

        // Move card back to old position
        const targetCard = cards[this.oldIndex];
        if (targetCard && targetCard !== card) {
          if (this.oldIndex > this.newIndex) {
            targetCard.after(card);
          } else {
            targetCard.before(card);
          }
        }
        saveTimelineOrder().catch(() => {});
      }
    };
  }

  // Command: Remove clip from timeline
  function RemoveClipCommand(clipId, clipData, position) {
    return {
      type: 'remove',
      clipId: clipId,
      clipData: clipData,
      position: position,
      execute() {
        const list = document.getElementById('timeline-list');
        const card = list.querySelector(`.timeline-card[data-clip-id="${this.clipId}"]`);
        if (card) {
          // Store HTML for undo
          this.cardHTML = card.outerHTML;
          card.remove();
        }
        saveTimelineOrder().catch(() => {});
      },
      undo() {
        const list = document.getElementById('timeline-list');
        const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));

        // Re-create the card
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = this.cardHTML;
        const card = tempDiv.firstChild;

        // Insert at original position
        if (this.position >= cards.length) {
          list.appendChild(card);
        } else if (this.position === 0) {
          list.insertBefore(card, cards[0]);
        } else {
          cards[this.position - 1].after(card);
        }

        // Re-attach event listeners
        const removeBtn = card.querySelector('.remove-clip');
        if (removeBtn) {
          removeBtn.addEventListener('click', handleRemoveClip);
        }

        saveTimelineOrder().catch(() => {});
      }
    };
  }

  // Command: Add clip to timeline
  function AddClipCommand(clipId, clipData, position) {
    return {
      type: 'add',
      clipId: clipId,
      clipData: clipData,
      position: position,
      execute() {
        // Add clip to timeline at specified position
        const list = document.getElementById('timeline-list');
        const cardEl = makeTimelineCard({
          title: this.clipData.title,
          subtitle: this.clipData.subtitle,
          thumbUrl: this.clipData.thumbUrl,
          clipId: this.clipId,
          durationSec: this.clipData.durationSec,
          kind: 'clip',
          previewUrl: this.clipData.previewUrl,
          viewCount: this.clipData.viewCount,
          avatarUrl: this.clipData.avatarUrl
        });

        // Insert before outro if exists, otherwise append
        const outro = list.querySelector('.timeline-card.timeline-outro');
        if (outro) {
          list.insertBefore(cardEl, outro);
        } else {
          list.appendChild(cardEl);
        }

        rebuildSeparators();
        saveTimelineOrder().catch(() => {});
      },
      undo() {
        const list = document.getElementById('timeline-list');
        const card = list.querySelector(`.timeline-card[data-clip-id="${this.clipId}"]`);
        if (card) {
          card.remove();
          rebuildSeparators();
        }
        saveTimelineOrder().catch(() => {});
      }
    };
  }

  // Try to restore project ID ONLY from URL params, clear localStorage otherwise
  // This prevents old projects from blocking new project creation
  try {
    const params = new URLSearchParams(window.location.search);
    const urlProjectId = params.get('project_id') || params.get('projectId');
    if (urlProjectId) {
      wizard.projectId = parseInt(urlProjectId, 10);
      console.log('Restored project ID from URL:', wizard.projectId);
      // Save to localStorage for persistence
      localStorage.setItem('wizard_project_id', wizard.projectId);
    } else {
      // No URL param = user wants to create a new project, clear old state
      localStorage.removeItem('wizard_project_id');
      console.log('Cleared localStorage, starting fresh project');
    }
  } catch (e) {
    console.warn('Failed to restore project ID:', e);
  }

  const USER_HAS_TWITCH = (document.getElementById('wizard-data')?.dataset.userHasTwitch === '1');
  async function api(path, opts={}){
    const res = await fetch(path, Object.assign({
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include'
    }, opts));
    if (!res.ok) {
      let errorMessage = 'An error occurred';
      try {
        const text = await res.text();
        // Try to parse as JSON
        const errData = JSON.parse(text);
        // Extract error message from JSON response
        errorMessage = errData.error || errData.message || text;
      } catch (parseErr) {
        // If parsing fails, use response text directly
        try {
          const text = await res.text();
          errorMessage = text;
        } catch (textErr) {
          errorMessage = 'Unknown error occurred';
        }
      }
      throw new Error(errorMessage);
    }
    return res.json();
  }
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

  // Twitch warning toggle
  const routeSelect = document.getElementById('route-select');
  const twitchWarn = document.getElementById('twitch-warning');
  const discordParams = document.getElementById('discord-params');

  function updateTwitchWarning(){
    const val = routeSelect.value;
    const show = (val === 'twitch') && !USER_HAS_TWITCH;
    if (twitchWarn) twitchWarn.classList.toggle('d-none', !show);
  }

  function updateDiscordParams(){
    const val = routeSelect.value;
    if (discordParams) discordParams.classList.toggle('d-none', val !== 'discord');
  }

  routeSelect?.addEventListener('change', () => {
    updateTwitchWarning();
    updateDiscordParams();
  });

  // Initialize on page load
  updateTwitchWarning();
  updateDiscordParams();

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

    // If project already exists (loaded from URL), verify it exists before skipping
    if (wizard.projectId) {
      console.log('Project already loaded, verifying:', wizard.projectId);
      try {
        // Check if project still exists
        const checkResponse = await fetch(`/api/projects/${wizard.projectId}/clips`, {
          credentials: 'include'
        });
        console.log('Verification response status:', checkResponse.status);
        if (checkResponse.ok) {
          // Project exists, check if it has clips
          console.log('Project verified, checking clip count');
          const clipsData = await checkResponse.json();
          const clipCount = (clipsData.items || []).length;

          wizard.route = route;
          wizard.maxClips = Math.max(1, Math.min(100, isNaN(maxClips) ? 20 : maxClips));
          gotoStep(2);

          if (clipCount === 0) {
            // Empty project - run auto-fetch as if it's new
            console.log('Project has no clips, running auto-fetch');
            // Fall through to auto-run code below (don't return)
          } else {
            // Project has clips, check if they're downloaded
            console.log('Project has', clipCount, 'clips, checking download status');
            const downloadedCount = (clipsData.items || []).filter(c => c.is_downloaded).length;

            if (downloadedCount === 0 && clipCount > 0) {
              // Clips exist but none downloaded - this is a broken project
              console.warn('Project has clips but none downloaded, clearing and starting fresh');
              wizard.projectId = null;
              localStorage.removeItem('wizard_project_id');
              // Fall through to create new project
            } else {
              // Normal case: project has downloaded clips
              await populateClipsGrid();
              setGcStatus(`Loaded ${clipCount} clip${clipCount !== 1 ? 's' : ''}.`);
              setGcFill(100);
              setGcActive('done');
              setGcDone('done');
              document.getElementById('next-2').disabled = false;
              return;
            }
          }
        } else {
          // Project doesn't exist, clear the ID and create new one
          console.warn('Project', wizard.projectId, 'not found, creating new project');
          wizard.projectId = null;
          localStorage.removeItem('wizard_project_id');
        }
      } catch (e) {
        console.error('Failed to verify project:', e);
        wizard.projectId = null;
        localStorage.removeItem('wizard_project_id');
      }
    }

    const compilationLengthValue = (fd.get('compilation_length') || 'auto').toString();
    const payload = {
      name: (fd.get('name') || '').toString(),
      description: (fd.get('description') || '').toString(),
      max_clip_duration: parseInt(fd.get('max_len') || '300', 10),
      platform_preset: (fd.get('platform_preset') || 'youtube').toString(),
      compilation_length: compilationLengthValue,
      // audio normalization will be conditionally appended below
    };
    if (audioNormEnabled) {
      payload.audio_norm_profile = (fd.get('audio_norm_profile') || 'gaming').toString();
      const dbVal = (fd.get('audio_norm_db') || '').toString().trim();
      if (dbVal !== '') {
        payload.audio_norm_db = parseFloat(dbVal);
      }
    }
    // Create project first, then fetch full settings from API response
    try {
      const r = await api('/api/projects', { method: 'POST', body: JSON.stringify(payload) });
      wizard.projectId = r.project_id;

      // Fetch the created project to get actual output settings applied by preset
      const project = await api(`/api/projects/${r.project_id}`);

      // Persist settings for Compile summary from actual project data
      wizard.settings = {
        route: route,
        name: payload.name || '',
        description: payload.description,
        output_resolution: project.output_resolution,
        output_format: project.output_format,
        fps: project.fps || 60,
        platform_preset: fd.get('platform_preset') || 'custom',
        compilation_length: compilationLengthValue,
        max_clips: Math.max(1, Math.min(500, parseInt(fd.get('max_clips') || '20', 10))),
        min_len: parseInt(fd.get('min_len') || '5', 10),
        max_len: payload.max_clip_duration,
        start_date: fd.get('start_date') || '',
        end_date: fd.get('end_date') || '',
        min_views: fd.get('min_views') || '',
        audio_norm_profile: audioNormEnabled ? payload.audio_norm_profile : undefined,
        audio_norm_db: audioNormEnabled ? payload.audio_norm_db : undefined
      };
      // Save project ID to localStorage for persistence across page reloads
      try {
        localStorage.setItem('wizard_project_id', wizard.projectId);
        console.log('Saved project ID to localStorage:', wizard.projectId);
      } catch (e) {
        console.warn('Failed to save project ID to localStorage:', e);
      }
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
          // All clips now queue download tasks (even reused ones which will copy files)
          const hasDownloadTasks = (wizard.downloadTasks || []).some(t => t && t.task_id);
          setGcDone('queue');
          if (hasDownloadTasks) {
            setGcActive('download');
            setGcFill(40);
            await startDownloadPolling();
          } else {
            // No tasks to poll - all clips were reused from existing media
            setGcDone('download');
            setGcActive('import');
            setGcStatus('Importing artifacts from workers…');
            setGcFill(80);

            // Run ingest even if no downloads (clips might be from rsync)
            try {
              await runRawIngest({ shallow: false, regenThumbnails: true });
            } catch(e) {
              console.error('Ingest failed:', e);
            }
            setGcDone('import');

            // Verify all clips are ready before enabling Next
            setGcStatus('Verifying all clips are ready…');
            const verify = await verifyAllClipsReady();
            if (verify.ready && verify.total > 0) {
              setGcActive('done');
              setGcDone('done');
              setGcStatus('Ready.');
              setGcFill(100);
              document.getElementById('next-2').disabled = false;
            } else {
              setGcError('import');
              setGcStatus(`⚠ ${verify.missing || 0} clip(s) failed to import.`);
              setGcFill(95);
            }
            try { await populateClipsGrid(); } catch (_) {}
          }
        }
      } catch (autoRunErr) { console.error("Auto-run Get Clips failed:", autoRunErr); setGcError("fetch"); setGcStatus(`Error: ${autoRunErr.message || "Unknown error"}`); }
    } catch (e) {
      alert('Couldn’t create the project: ' + e.message);
    }
  });
  // Save as task: capture current setup form and create an Automation task with a timestamped name
  document.getElementById('save-as-task')?.addEventListener('click', async () => {
    const form = document.getElementById('setup-form');
    const fd = new FormData(form);
    const route = (document.getElementById('route-select')?.value || 'twitch');
    const nameRaw = (fd.get('name') || '').toString().trim();
    const description = (fd.get('description') || '').toString();
    const clip_limit = Math.max(1, Math.min(500, parseInt(fd.get('max_clips') || '10', 10) || 10));
    const output_resolution = (fd.get('resolution') || '1080p').toString();
    const output_format = (fd.get('format') || 'mp4').toString();
    const max_clip_duration = parseInt(fd.get('max_len') || '300', 10) || 300;
    const fps = parseInt(fd.get('fps') || '60', 10) || 60; // used for summary only, not sent to task for now
    const audioNormEnabled = !!document.getElementById('audio-norm-enabled')?.checked;
    const audio_norm_db_raw = (fd.get('audio_norm_db') || '').toString().trim();
    // Build timestamped name
    const now = new Date();
    const pad = (n)=>String(n).padStart(2,'0');
    const stamp = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
    const baseName = nameRaw || 'Compilation';
    const name = `${baseName} – ${stamp}`;
    // Optional date range → RFC3339 for Twitch API
    function toStartOfDayZ(d){ try{ return `${d}T00:00:00Z`; }catch{ return null; } }
    function toEndOfDayZ(d){ try{ return `${d}T23:59:59Z`; }catch{ return null; } }
    const start_date = (fd.get('start_date') || '').toString().trim();
    const end_date = (fd.get('end_date') || '').toString().trim();
    const started_at = start_date ? toStartOfDayZ(start_date) : undefined;
    const ended_at = end_date ? toEndOfDayZ(end_date) : undefined;
    // Task params
    const params = {
      source: 'twitch', // tasks currently support twitch only
      clip_limit,
      output: {
        output_resolution,
        output_format,
        max_clip_duration,
      },
    };
    if (audioNormEnabled && audio_norm_db_raw !== '' && !isNaN(parseFloat(audio_norm_db_raw))) {
      params.output.audio_norm_db = parseFloat(audio_norm_db_raw);
    }
    if (started_at) params.started_at = started_at;
    if (ended_at) params.ended_at = ended_at;
    // Submit to Automation API
    try {
      const resp = await fetch('/api/automation/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(CSRF ? { 'X-CSRFToken': CSRF } : {}) },
        body: JSON.stringify({ name, description, params })
      });
      const j = await resp.json().catch(()=>({}));
      if (resp.ok) {
        alert('Saved as task. You can run or schedule it from Automation.');
      } else {
        alert((j && j.error) ? j.error : 'Failed to save task');
      }
    } catch (e) {
      alert('Failed to save task');
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
      // Get Discord curation parameters from form
      const minReactions = parseInt(document.getElementById('min-reactions')?.value || '1', 10);
      const reactionEmoji = document.getElementById('reaction-emoji')?.value?.trim() || '';
      const channelId = document.getElementById('discord-channel-id')?.value?.trim() || '';

      // Build query parameters
      const params = new URLSearchParams({ limit: '200' });
      if (minReactions > 1) params.set('min_reactions', String(minReactions));
      if (reactionEmoji) params.set('reaction_emoji', reactionEmoji);
      if (channelId) params.set('channel_id', channelId);

      const res = await fetch(`/api/discord/messages?${params.toString()}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const items = data.items || [];
      const urls = (data.clip_urls || []).filter(Boolean);
      const filtered = data.filtered_count !== undefined ? data.filtered_count : items.length;

      setGcStatus(`Sifted ${filtered} messages • found ${urls.length} clip link(s)${minReactions > 1 ? ` (≥${minReactions} reactions)` : ''}.`);
      return urls;
    } catch (e) {
      setGcError('fetch');
      setGcStatus("Couldn't fetch Discord messages. Check DISCORD config.");
      return [];
    }
  }

  // Queue downloads
  async function queueDownloads(urls) {
    if (!wizard.projectId) { throw new Error('Project not created yet.'); }
    if (!urls || urls.length === 0) { throw new Error('No clip URLs to download.'); }

    // Calculate effective limit based on compilation_length
    let effectiveLimit = wizard.maxClips || urls.length;

    const compilationLength = wizard.settings?.compilation_length || 'auto';
    if (compilationLength !== 'auto') {
      const targetSeconds = parseInt(compilationLength, 10);
      if (!isNaN(targetSeconds) && targetSeconds > 0) {
        // Estimate average clip duration (45 seconds is typical for Twitch clips)
        const avgClipDuration = 45;
        const estimatedClipsNeeded = Math.ceil(targetSeconds / avgClipDuration);

        // Use the smaller of: calculated clips needed or max_clips hard limit
        effectiveLimit = Math.min(estimatedClipsNeeded, wizard.maxClips || estimatedClipsNeeded);

        console.log(`Compilation length target: ${targetSeconds}s, estimated clips needed: ${estimatedClipsNeeded}, effective limit: ${effectiveLimit}`);
      }
    }

    const limit = Math.max(1, Math.min(100, effectiveLimit));
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
    const actualCount = r.count !== undefined ? r.count : wizard.downloadTasks.length;
    const skipped = r.skipped || 0;
    const requested = r.requested || (wizard.maxClips || limit);
    console.log(`API created ${actualCount} clips from ${requested} requested (${skipped} skipped as duplicates)`);
    setGcStatus(`Queued ${wizard.downloadTasks.length} download${wizard.downloadTasks.length !== 1 ? 's' : ''} (${actualCount} clip${actualCount !== 1 ? 's' : ''}${skipped > 0 ? `, ${skipped} duplicate${skipped !== 1 ? 's' : ''} skipped` : ''}).`);
  }

  // Download progress/polling
  let dlTimer = null;
  async function startDownloadPolling() {
    setGcStatus('Pulling clips down…');
    // Poll all download tasks (including those that will reuse/copy existing files)
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
        setGcActive('import');
        setGcStatus('Importing artifacts from workers…');
        setGcFill(80);

        // Run ingest to import artifacts from /srv/ingest/
        // This picks up files that were rsync'd from workers
        try {
          await runRawIngest({ shallow: false, regenThumbnails: true });
        } catch(e) {
          console.error('Ingest failed:', e);
        }
        setGcDone('import');

        // Final verification: ensure all clips have media files and thumbnails
        setGcStatus('Verifying all clips are ready…');
        let retries = 0;
        const maxRetries = 3;
        let finalVerify = null;
        while (retries < maxRetries) {
          finalVerify = await verifyAllClipsReady();
          if (finalVerify.ready && finalVerify.total > 0) {
            break;
          }
          if (finalVerify.missing > 0) {
            console.log(`Verification attempt ${retries + 1}/${maxRetries}: ${finalVerify.missing} clips still missing`);
            setGcStatus(`Waiting for ${finalVerify.missing} clip(s) to finish processing... (${retries + 1}/${maxRetries})`);
            // Wait longer and retry ingest to pick up any late arrivals
            await new Promise(r => setTimeout(r, 3000));
            if (retries < maxRetries - 1) {
              try { await runRawIngest({ shallow: false, regenThumbnails: true }); } catch(_) {}
            }
          }
          retries++;
        }

        // Only enable Next button if all clips are verified ready
        if (finalVerify && finalVerify.ready && finalVerify.total > 0) {
          setGcActive('done');
          setGcDone('done');
          setGcStatus('Ready.');
          setGcFill(100);
          document.getElementById('next-2').disabled = false;
          try { await populateClipsGrid(); } catch (_) {}
        } else if (finalVerify && finalVerify.missing > 0) {
          // Verification failed after max retries
          setGcError('import');
          setGcStatus(`⚠ ${finalVerify.missing} clip(s) failed to import. Check worker logs or retry.`);
          setGcFill(95);
          console.error('Verification failed after max retries:', finalVerify);
          // Keep Next button disabled
        } else {
          // No clips found (edge case)
          setGcError('done');
          setGcStatus('⚠ No clips were imported. Please check your filters and try again.');
          setGcFill(100);
          console.warn('No clips found after verification');
          // Keep Next button disabled
        }
        return;
      }
    }
    dlTimer = setInterval(poll, 1000);
    await poll();
  }
  document.getElementById('next-2')?.addEventListener('click', async () => {
    // Navigate to Arrange without triggering another ingest here.
    // Step 3 already does a shallow import if no clips are present.
    gotoStep(3);
  });

  // Step 2 helpers: compact progress UI
  function setGcStatus(text){ const el = document.getElementById('gc-status'); if (el) el.textContent = text || ''; }
  function setGcFill(pct){ const el = document.getElementById('gc-fill'); if (el){ const v = Math.max(0, Math.min(100, Math.floor(pct||0))); el.style.width = v + '%'; el.setAttribute('aria-valuenow', String(v)); } }
  function getGcStepEl(key){ return document.querySelector(`#gc-steps li[data-key="${key}"]`); }

  // Verify clips are ready after downloads complete (HTTP upload workflow)
  async function runRawIngest(opts={}){
    if (!wizard.projectId) return;
    // Since HTTP upload happens automatically during download,
    // we just need to verify clips are ready
    setGcActive('import');
    setGcStatus('Verifying clips are ready…');
    try {
      const verifyResult = await verifyAllClipsReady();
      if (!verifyResult.ready) {
        console.warn('Some clips still not ready:', verifyResult);
        setGcStatus(`Waiting for ${verifyResult.missing} more clip(s)...`);
        // Wait a bit and check again
        await new Promise(r => setTimeout(r, 2000));
        const retryResult = await verifyAllClipsReady();
        if (!retryResult.ready) {
          setGcError('import');
          setGcStatus(`${retryResult.missing} clip(s) still not ready.`);
          return 'pending';
        }
      }
      setGcDone('import');
      setGcStatus('All clips ready.');
      return 'ok';
    } catch (e) {
      console.error('Verification error:', e);
      setGcError('import');
      setGcStatus('Verification failed.');
      return 'error';
    }
  }

  // Verify all expected clips have been imported and have thumbnails
  async function verifyAllClipsReady(){
    if (!wizard.projectId) return { ready: true, total: 0, missing: 0 };
    try {
      const data = await api(`/api/projects/${wizard.projectId}/clips`);
      const clips = (data && data.items) || [];
      let missing = 0;
      const missingDetails = [];
      for (const clip of clips) {
        // Check if clip has media file with thumbnail
        if (!clip.media || !clip.media.thumbnail_url) {
          missing++;
          missingDetails.push({
            id: clip.id,
            title: clip.title,
            hasMedia: !!clip.media,
            hasThumbnail: !!(clip.media && clip.media.thumbnail_url),
            mediaId: clip.media ? clip.media.id : null,
            url: clip.source_url
          });
          console.warn(`Clip ${clip.id} (${clip.title}) missing media or thumbnail:`, clip.media);
        }
      }
      console.log(`Verification: ${clips.length} total clips, ${missing} missing media/thumbnails, ${clips.length - missing} ready`);
      if (missingDetails.length > 0) {
        console.log('Missing details:', missingDetails);
        console.log('Full clip data for debugging:', clips);
      }
      return {
        ready: missing === 0,
        total: clips.length,
        missing: missing,
        clips: clips
      };
    } catch (e) {
      console.error('Failed to verify clips:', e);
      return { ready: true, total: 0, missing: 0 }; // Fail open to avoid blocking
    }
  }
  // On-demand compiled ingest helper: POST /api/projects/<id>/ingest/compiled and poll
  async function runCompiledIngest(opts={}){
    if (!wizard.projectId) return;
    const shallow = !!opts.shallow;
    try {
      const resp = await fetch(`/api/projects/${wizard.projectId}/ingest/compiled`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(CSRF ? { 'X-CSRFToken': CSRF } : {}) },
        body: JSON.stringify({ action: 'copy' })
      });
      if (!resp.ok) throw new Error('ingest compiled start failed');
      const j = await resp.json();
      const taskId = j.task_id;
      if (!taskId) return;
      const started = Date.now();
      async function poll(){
        const s = await api(`/api/tasks/${taskId}`);
        const st = String((s && (s.state || s.status)) || '').toUpperCase();
        if (st === 'SUCCESS') return 'ok';
        if (st === 'FAILURE') throw new Error('ingest compiled failed');
        if (shallow && (Date.now() - started) > 3000) return 'later';
        await new Promise(r => setTimeout(r, 800));
        return poll();
      }
      await poll();
    } catch (_) {
      // Non-fatal
    }
  }
  function clearGcStates(){ document.querySelectorAll('#gc-steps li').forEach(s => { s.classList.remove('active','error'); }); }
  function setGcActive(key){ clearGcStates(); const el = getGcStepEl(key); if (el) el.classList.add('active'); }
  function setGcDone(key){ const el = getGcStepEl(key); if (el){ el.classList.remove('error'); el.classList.add('done'); } }
  function setGcError(key){ const el = getGcStepEl(key); if (el){ el.classList.remove('active','done'); el.classList.add('error'); } }

  // Compile summary renderer
  async function renderCompileSummary(){
    const details = document.getElementById('compile-details');
    if (!details) return;

    // Fetch project data if we don't have settings cached
    let s = wizard.settings || {};
    if (wizard.projectId && (!s.output_resolution || !s.output_format)) {
      try {
        const project = await api(`/api/projects/${wizard.projectId}`);
        s = {
          ...s,
          output_resolution: project.output_resolution,
          output_format: project.output_format,
          fps: project.fps,
          platform_preset: project.platform_preset,
          audio_norm_profile: project.audio_norm_profile,
          audio_norm_db: project.audio_norm_db
        };
        wizard.settings = s; // Cache for next time
      } catch (e) {
        console.warn('Failed to fetch project settings for summary:', e);
      }
    }

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

    // Derive orientation from resolution (WxH format)
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
    // Clip mini list (thumb, title, length, creator, views)
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
          viewsLabel = v >= 1000000 ? `${(v/1000000).toFixed(1)}M views` :
                       v >= 1000 ? `${(v/1000).toFixed(1)}K views` :
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
          <div class="mb-1"><strong>Background Music:</strong> ${wizard.selectedMusicId ? `Yes (${document.getElementById('music-volume')?.value || 30}% volume)` : 'None'}</div>
          <div class="text-muted">Clip limits: min ${s.min_len || 0}s • max ${s.max_len || 0}s • max clips ${s.max_clips || 0}${s.compilation_length && s.compilation_length !== 'auto' ? ` • Target length: ${Math.floor(parseInt(s.compilation_length)/60)}m` : ''}${s.start_date || s.end_date ? ` • Dates: ${escapeHtml(s.start_date || '—')} → ${escapeHtml(s.end_date || '—')}` : ''}${s.min_views ? ` • Min views: ${escapeHtml(String(s.min_views))}` : ''}</div>
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
        // Use AddClipCommand for undo/redo support
        const clipData = {
          title: item.title || 'Clip',
          subtitle: [item.creator_name ? `By ${item.creator_name}` : '', item.game_name ? `• ${item.game_name}` : ''].filter(Boolean).join(' '),
          thumbUrl: (item.media && item.media.thumbnail_url) || '',
          durationSec: (typeof item.duration === 'number' ? item.duration : (item.media && (typeof item.media.duration === 'number') ? item.media.duration : undefined)),
          previewUrl: (item.media && item.media.preview_url) || '',
          viewCount: item.view_count,
          avatarUrl: item.avatar_url
        };

        const addCmd = AddClipCommand(item.id, clipData, -1);
        commandHistory.execute(addCmd);

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
  function makeTimelineCard({title, subtitle, thumbUrl, clipId, kind, durationSec, previewUrl, viewCount, avatarUrl}){
    const card = document.createElement('div');
    card.className = 'timeline-card';
    // Lock intro/outro from dragging
    card.draggable = !(kind === 'intro' || kind === 'outro');
    if (clipId) card.dataset.clipId = String(clipId);
    if (kind) card.dataset.kind = kind;
    if (typeof durationSec === 'number' && !isNaN(durationSec)) card.dataset.durationSec = String(durationSec);
    if (previewUrl) card.dataset.previewUrl = String(previewUrl);
    if (typeof viewCount === 'number') card.dataset.viewCount = String(viewCount);
    if (avatarUrl) card.dataset.avatarUrl = String(avatarUrl);
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

    // Remove button with undo/redo support
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

      // Use RemoveClipCommand for undo/redo support
      if (clipId) {
        const list = document.getElementById('timeline-list');
        const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
        const position = cards.indexOf(card);

        const clipData = {
          clip_id: clipId,
          title: title,
          subtitle: subtitle,
          thumbUrl: thumbUrl,
          kind: kind,
          durationSec: durationSec,
          previewUrl: previewUrl
        };

        const removeCmd = RemoveClipCommand(clipId, clipData, position);
        commandHistory.execute(removeCmd);
      } else {
        // No clip_id, just remove directly (intro/outro/transition)
        card.remove();
        rebuildSeparators();
        saveTimelineOrder().catch(()=>{});
      }

      // Update clips grid state
      if (clipId){
        const src = document.querySelector(`.clip-card[data-clip-id="${clipId}"]`);
        if (src) src.classList.remove('d-none');
        updateClipsGridState();
      }

      // Uncheck arranged confirmation if timeline empty
      const listCheck = document.getElementById('timeline-list');
      if (listCheck && listCheck.querySelectorAll('.timeline-card[data-clip-id]').length === 0) {
        const chk = document.getElementById('arranged-confirm');
        if (chk) { chk.checked = false; chk.dispatchEvent(new Event('change')); }
      }
    });
    card.appendChild(rm);

    // Bottom overlay title/subtitle
    const ov = document.createElement('div');
    ov.className = 'overlay';
    const h6 = document.createElement('div'); h6.className = 'title text-truncate'; h6.textContent = title || 'Item';
    const small = document.createElement('div'); small.className = 'subtitle text-truncate'; small.textContent = subtitle || '';
    ov.appendChild(h6); ov.appendChild(small);
    card.appendChild(ov);

    // DnD handlers with undo/redo support
    let dragStartIndex = -1;
    card.addEventListener('dragstart', (e) => {
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';

      // Track starting position for undo/redo
      if (clipId) {
        const list = document.getElementById('timeline-list');
        const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
        dragStartIndex = cards.indexOf(card);
      }
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      rebuildSeparators();

      // Track position change for undo/redo
      if (clipId && dragStartIndex !== -1) {
        const list = document.getElementById('timeline-list');
        const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
        const dragEndIndex = cards.indexOf(card);

        if (dragStartIndex !== dragEndIndex) {
          // Create and add move command to undo stack
          const moveCmd = MoveClipCommand(clipId, dragStartIndex, dragEndIndex);
          commandHistory.undoStack.push(moveCmd);
          commandHistory.redoStack = []; // Clear redo stack

          // Trim undo stack if exceeds max history
          if (commandHistory.undoStack.length > commandHistory.maxHistory) {
            commandHistory.undoStack.shift();
          }
        }
      }

      saveTimelineOrder().catch(()=>{});
    });
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

  // Preview generation removed - feature temporarily disabled during worker migration

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
      if (wizard.selectedMusicId) {
        body.background_music_id = wizard.selectedMusicId;
        body.music_volume = parseFloat((parseInt(document.getElementById('music-volume')?.value || '30', 10) / 100).toFixed(2));
        body.music_start_mode = document.getElementById('music-start-mode')?.value || 'after_intro';
        body.music_end_mode = document.getElementById('music-end-mode')?.value || 'before_outro';
      }
      // Extract the current timeline subset (ordered) so the backend renders exactly these clips
      const list = document.getElementById('timeline-list');
      const ids = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'))
        .map(el => parseInt(el.dataset.clipId, 10))
        .filter(v => Number.isFinite(v));
      if (!ids.length) {
        alert('Add at least one clip to the timeline.');
        document.getElementById('cancel-compile').disabled = true;
        if (startBtn) startBtn.disabled = false;
        return;
      }
      body.clip_ids = ids;
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
              // Fallback to owner-only download route
              dl.href = `/projects/${wizard.projectId}/download`;
            }
            // Kick off compiled-artifact ingest on the server so Export can show a download URL
            try {
              showExportIngestBanner('Importing final render…');
              await runCompiledIngest({ shallow: false });
              hideExportIngestBanner();
              await refreshExportInfo();
            } catch (_) {}
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
  document.getElementById('next-4')?.addEventListener('click', async () => {
    // Redirect to project details instead of Export step
    if (!wizard.projectId) {
      alert('No project loaded.');
      return;
    }
    try {
      const details = await api(`/api/projects/${wizard.projectId}`);
      if (details.public_id) {
        window.location.href = `/p/${details.public_id}`;
      } else {
        alert('Project does not have a public ID yet.');
      }
    } catch (e) {
      console.error('Failed to get project details:', e);
      alert('Failed to navigate to project.');
    }
  });

  // Default routing states on load
  gotoStep(1);
  updateTwitchWarning();
  // Render summary when entering Step 4
  document.querySelector('#wizard-chevrons li[data-step="4"]')?.addEventListener('click', () => {
    setTimeout(renderCompileSummary, 0);
  });



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
  async function refreshMusic(){
    const items = await loadMediaList('music');
    const container = document.getElementById('music-list');
    container.innerHTML = '';
    wizard.selectedMusicId = wizard.selectedMusicId || null;
    if (!items.length){ container.innerHTML = '<div class="text-muted">No music tracks found.</div>'; return; }
    items.forEach(it => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.width = '160px';
      card.style.cursor = 'pointer';
      const body = document.createElement('div');
      body.className = 'card-body p-2';
      const icon = document.createElement('div');
      icon.className = 'text-center mb-2';
      icon.innerHTML = '<i class="bi bi-music-note-beamed" style="font-size: 3rem;"></i>';
      const title = document.createElement('div');
      title.className = 'small text-truncate text-center';
      title.textContent = it.original_filename || it.filename;
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm btn-primary w-100 mt-2';
      btn.textContent = 'Select';
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        wizard.selectedMusicId = it.id;
        document.querySelectorAll('#music-list .card').forEach(c => c.classList.remove('border-primary'));
        card.classList.add('border', 'border-primary');
      });
      if (wizard.selectedMusicId === it.id) {
        card.classList.add('border', 'border-primary');
      }
      body.appendChild(icon);
      body.appendChild(title);
      body.appendChild(btn);
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
  // Music volume slider
  document.getElementById('music-volume')?.addEventListener('input', (e) => {
    const val = parseInt(e.target.value, 10);
    document.getElementById('music-volume-display').textContent = val + '%';
  });
  // When clicking the Arrange chevron, auto-refresh lists too (in case user navigates directly)
  document.querySelector('#wizard-chevrons li[data-step="3"]')?.addEventListener('click', () => {
    Promise.resolve().then(async () => {
      try { await refreshIntros(); } catch (_) {}
      try { await refreshOutros(); } catch (_) {}
      try { await refreshTransitions(); } catch (_) {}
      try { await refreshMusic(); } catch (_) {}
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



  // Platform Preset Integration
  (function initPlatformPresets(){
    const presetSelect = document.getElementById('platformPreset');
    if (!presetSelect) return;

    // Fetch available presets from API
    api('/api/presets')
      .then(presets => {
        if (!Array.isArray(presets)) return;

        // Populate dropdown with preset options
        presets.forEach(preset => {
          if (preset.value === 'custom') return; // Skip custom, already in HTML
          const option = document.createElement('option');
          option.value = preset.value;
          option.textContent = preset.name;
          option.dataset.settings = JSON.stringify(preset.settings);
          presetSelect.appendChild(option);
        });
      })
      .catch(err => console.error('Failed to load platform presets:', err));

    // Handle preset selection changes
    presetSelect.addEventListener('change', function() {
      const selectedOption = this.options[this.selectedIndex];
      if (this.value === 'custom') {
        // Reset to default custom values - don't override user choices
        return;
      }

      try {
        const settings = JSON.parse(selectedOption.dataset.settings || '{}');

        // Update orientation dropdown
        const orientationSelect = document.getElementById('orientation');
        if (orientationSelect && settings.orientation) {
          orientationSelect.value = settings.orientation;
        }

        // Update resolution dropdown
        const resolutionSelect = document.getElementById('resolution');
        if (resolutionSelect && settings.height) {
          const resValue = `${settings.height}p`;
          // Check if this resolution exists in dropdown, otherwise add it
          let resOption = Array.from(resolutionSelect.options).find(opt => opt.value === resValue);
          if (!resOption) {
            resOption = document.createElement('option');
            resOption.value = resValue;
            resOption.textContent = resValue;
            resolutionSelect.appendChild(resOption);
          }
          resolutionSelect.value = resValue;
        }

        // Update format dropdown
        const formatSelect = document.getElementById('format');
        if (formatSelect && settings.format) {
          formatSelect.value = settings.format;
        }

        // Update FPS dropdown
        const fpsSelect = document.getElementById('fps');
        if (fpsSelect && settings.fps) {
          const fpsValue = String(settings.fps);
          // Check if this FPS exists in dropdown, otherwise add it
          let fpsOption = Array.from(fpsSelect.options).find(opt => opt.value === fpsValue);
          if (!fpsOption) {
            fpsOption = document.createElement('option');
            fpsOption.value = fpsValue;
            fpsOption.textContent = `${fpsValue} fps`;
            fpsSelect.appendChild(fpsOption);
          }
          fpsSelect.value = fpsValue;
        }

        // Show feedback about preset application
        console.log(`Applied ${selectedOption.textContent} preset:`, settings);
      } catch (err) {
        console.error('Failed to apply preset settings:', err);
      }
    });
  })();

  // Keyboard Shortcuts for Timeline
  (function initKeyboardShortcuts() {
    let selectedClipCard = null;

    // Helper to get currently focused/selected timeline clip
    function getSelectedClip() {
      return selectedClipCard || document.querySelector('.timeline-card.selected');
    }

    // Helper to select a clip card
    function selectClip(card) {
      // Remove previous selection
      document.querySelectorAll('.timeline-card').forEach(c => c.classList.remove('selected'));
      if (card) {
        card.classList.add('selected');
        selectedClipCard = card;
        // Scroll into view if needed
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } else {
        selectedClipCard = null;
      }
    }

    // Click handler to select clips
    document.addEventListener('click', (e) => {
      const card = e.target.closest('.timeline-card');
      if (card && card.dataset.clipId) {
        selectClip(card);
      }
    });

    // Main keyboard event handler
    document.addEventListener('keydown', (e) => {
      // Don't interfere with form inputs
      if (e.target.matches('input, textarea, select')) {
        return;
      }

      // Check if we're on Step 3 (Arrange) - only enable shortcuts there
      const currentStep = document.querySelector('.wizard-step:not(.d-none)')?.dataset.step;

      // Only process timeline shortcuts on Step 3
      if (currentStep !== '3') {
        // Ctrl+Enter on Step 4 - Start compilation
        if (e.ctrlKey && e.code === 'Enter' && currentStep === '4') {
          e.preventDefault();
          const compileBtn = document.getElementById('start-compile');
          if (compileBtn && !compileBtn.disabled) {
            compileBtn.click();
          }
        }
        return;
      }

      const list = document.getElementById('timeline-list');
      if (!list) return;

      const allClips = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
      if (allClips.length === 0) return;

      // Delete - Remove selected clip
      if (e.code === 'Delete' || e.code === 'Backspace') {
        const selected = getSelectedClip();
        if (selected && selected.dataset.clipId) {
          e.preventDefault();
          const removeBtn = selected.querySelector('.remove-clip');
          if (removeBtn) {
            removeBtn.click();
          }
          selectedClipCard = null;
        }
        return;
      }

      // Arrow Up - Navigate to previous clip
      if (e.code === 'ArrowUp' || e.code === 'ArrowLeft') {
        e.preventDefault();
        const selected = getSelectedClip();
        if (!selected) {
          // Select first clip
          if (allClips.length > 0) {
            selectClip(allClips[0]);
          }
        } else {
          const currentIndex = allClips.indexOf(selected);
          if (currentIndex > 0) {
            selectClip(allClips[currentIndex - 1]);
          }
        }
        return;
      }

      // Arrow Down - Navigate to next clip
      if (e.code === 'ArrowDown' || e.code === 'ArrowRight') {
        e.preventDefault();
        const selected = getSelectedClip();
        if (!selected) {
          // Select first clip
          if (allClips.length > 0) {
            selectClip(allClips[0]);
          }
        } else {
          const currentIndex = allClips.indexOf(selected);
          if (currentIndex < allClips.length - 1) {
            selectClip(allClips[currentIndex + 1]);
          }
        }
        return;
      }

      // Ctrl+S - Save project (auto-save timeline order)
      if (e.ctrlKey && e.code === 'KeyS') {
        e.preventDefault();
        saveTimelineOrder().then(() => {
          // Show brief feedback
          const feedback = document.createElement('div');
          feedback.className = 'alert alert-success position-fixed top-0 start-50 translate-middle-x mt-3';
          feedback.style.zIndex = '9999';
          feedback.textContent = '✓ Timeline saved';
          document.body.appendChild(feedback);
          setTimeout(() => feedback.remove(), 2000);
        }).catch((err) => {
          console.error('Save failed:', err);
          const feedback = document.createElement('div');
          feedback.className = 'alert alert-danger position-fixed top-0 start-50 translate-middle-x mt-3';
          feedback.style.zIndex = '9999';
          feedback.textContent = '✗ Save failed';
          document.body.appendChild(feedback);
          setTimeout(() => feedback.remove(), 2000);
        });
        return;
      }

      // Ctrl+Z - Undo
      if (e.ctrlKey && e.code === 'KeyZ' && !e.shiftKey) {
        e.preventDefault();
        if (commandHistory.undo()) {
          showFeedback('↶ Undone', 'success');
        } else {
          showFeedback('Nothing to undo', 'info');
        }
        return;
      }

      // Ctrl+Shift+Z or Ctrl+Y - Redo
      if ((e.ctrlKey && e.shiftKey && e.code === 'KeyZ') || (e.ctrlKey && e.code === 'KeyY')) {
        e.preventDefault();
        if (commandHistory.redo()) {
          showFeedback('↷ Redone', 'success');
        } else {
          showFeedback('Nothing to redo', 'info');
        }
        return;
      }
    });

    // Helper to show feedback messages
    function showFeedback(message, type = 'success') {
      const feedback = document.createElement('div');
      feedback.className = `alert alert-${type} position-fixed top-0 start-50 translate-middle-x mt-3`;
      feedback.style.zIndex = '9999';
      feedback.textContent = message;
      document.body.appendChild(feedback);
      setTimeout(() => feedback.remove(), 1500);
    }
    // Visual feedback for selected clip
    const style = document.createElement('style');
    style.textContent = `
      .timeline-card.selected {
        outline: 3px solid #0d6efd;
        outline-offset: 2px;
        box-shadow: 0 0 12px rgba(13, 110, 253, 0.5);
      }
    `;
    document.head.appendChild(style);
  })();
})();
