/**
 * Step 1: Setup - Project configuration and search parameters
 * Handles form submission, validation, platform presets, and route selection
 */

export async function onEnter(wizard) {
  console.log('[step-setup] Entering setup step');

  // Pre-fill form if loading existing project
  if (wizard.projectId && wizard.projectData) {
    prefillForm(wizard.projectData);
  }

  // Initialize all UI components
  initRouteToggle();
  initCompilationLengthToggle();
  initAudioNormSlider();
  initPlatformPresets();
  initVerticalVideoControls();
  initTaskButton(); // Check tier permissions for save-as-task button

  // Setup form submission
  setupFormHandlers(wizard);
}

export function onExit(wizard) {
  console.log('[step-setup] Exiting setup step');
  // Cleanup if needed
}

/**
 * Pre-fill form with existing project data
 */
function prefillForm(projectData) {
  const form = document.getElementById('setup-form');
  if (!form) return;

  // Fill in text fields
  const nameInput = form.querySelector('input[name="name"]');
  const descInput = form.querySelector('textarea[name="description"]');
  const tagsInput = form.querySelector('input[name="tags"]');

  if (nameInput && projectData.name) nameInput.value = projectData.name;
  if (descInput && projectData.description) descInput.value = projectData.description;
  if (tagsInput && projectData.tags) tagsInput.value = projectData.tags;

  console.log('[step-setup] Pre-filled form with existing project data');
}

/**
 * Initialize route selection (Twitch/Discord) toggle
 */
function initRouteToggle() {
  const routeSelect = document.getElementById('route-select');
  const twitchWarn = document.getElementById('twitch-warning');
  const discordMinReactions = document.getElementById('discord-min-reactions');
  const discordEmoji = document.getElementById('discord-emoji');
  const discordSetupAlert = document.getElementById('discord-setup-alert');

  // Get user's Twitch connection status from data attribute
  const wizardData = document.getElementById('wizard-data');
  const userHasTwitch = wizardData?.dataset?.userHasTwitch === '1';

  function updateTwitchWarning() {
    const val = routeSelect?.value;
    const show = (val === 'twitch') && !userHasTwitch;
    if (twitchWarn) twitchWarn.classList.toggle('d-none', !show);

    // Disable Next button if Twitch selected but not configured
    disableControlsIfNeeded();
  }

  function disableControlsIfNeeded() {
    const val = routeSelect?.value;
    const shouldDisable = (val === 'twitch') && !userHasTwitch;

    // Disable the Next/Continue button
    const nextBtn = document.querySelector('.wizard-step[data-step="1"] .btn-primary');
    if (nextBtn) {
      nextBtn.disabled = shouldDisable;
      if (shouldDisable) {
        nextBtn.title = 'Connect your Twitch account first';
      } else {
        nextBtn.title = '';
      }
    }
  }

  function updateDiscordParams() {
    const val = routeSelect?.value;
    const shouldShow = val === 'discord';
    console.log('[step-setup] Route:', val, '| showing Discord params:', shouldShow);

    if (discordMinReactions) discordMinReactions.classList.toggle('d-none', !shouldShow);
    if (discordEmoji) discordEmoji.classList.toggle('d-none', !shouldShow);
    if (discordSetupAlert) discordSetupAlert.classList.toggle('d-none', !shouldShow);
  }

  routeSelect?.addEventListener('change', () => {
    console.log('[step-setup] Route changed:', routeSelect.value);
    updateTwitchWarning();
    updateDiscordParams();
  });

  // Initialize on load
  updateTwitchWarning();
  updateDiscordParams();
  disableControlsIfNeeded();
}

/**
 * Initialize save-as-task button based on tier permissions
 */
function initTaskButton() {
  const saveTaskBtn = document.getElementById('save-as-task');
  if (!saveTaskBtn) return;

  const wizardData = document.getElementById('wizard-data');
  const canScheduleTasks = wizardData?.dataset?.canScheduleTasks === '1';

  if (!canScheduleTasks) {
    saveTaskBtn.disabled = true;
    saveTaskBtn.title = 'Upgrade your tier to schedule tasks';
    saveTaskBtn.classList.add('opacity-50');
    console.log('[step-setup] Save-as-task button disabled (tier does not allow scheduling)');
  }
}

/**
 * Initialize compilation length selector to toggle max_clips field
 */
function initCompilationLengthToggle() {
  const compilationLengthSelect = document.getElementById('compilation-length');
  const maxClipsInput = document.querySelector('input[name="max_clips"]');

  if (!compilationLengthSelect || !maxClipsInput) return;

  function updateMaxClipsState() {
    const isAuto = compilationLengthSelect.value === 'auto';
    maxClipsInput.disabled = !isAuto;

    // Visual feedback
    if (isAuto) {
      maxClipsInput.parentElement?.classList.remove('opacity-50');
    } else {
      maxClipsInput.parentElement?.classList.add('opacity-50');
    }

    console.log('[step-setup] Compilation length:', compilationLengthSelect.value, '| max_clips', isAuto ? 'enabled' : 'disabled');
  }

  compilationLengthSelect.addEventListener('change', updateMaxClipsState);
  updateMaxClipsState(); // Initialize on load
}

/**
 * Initialize audio normalization slider
 */
function initAudioNormSlider() {
  const slider = document.getElementById('audio-norm-slider');
  if (!slider) return;

  const radios = Array.from(slider.querySelectorAll('input[type="radio"][name="audio_norm_profile"]'));
  const pos = slider.querySelector('.pos');
  const hiddenDb = document.getElementById('audio_norm_db');
  const enableCb = document.getElementById('audio-norm-enabled');
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

  if (enableCb) {
    enableCb.addEventListener('change', () => setEnabled(!!enableCb.checked));
    setEnabled(!!enableCb.checked);
  } else {
    setEnabled(true);
  }

  update();
}

/**
 * Initialize platform presets dropdown
 */
function initPlatformPresets() {
  const presetSelect = document.getElementById('platformPreset');
  if (!presetSelect) return;

  // Fetch available presets from API
  fetch('/api/presets')
    .then(res => res.json())
    .then(presets => {
      if (!Array.isArray(presets)) return;

      // Populate dropdown with preset options (skip custom, already in HTML)
      presets.forEach(preset => {
        if (preset.value === 'custom') return;
        const option = document.createElement('option');
        option.value = preset.value;
        option.textContent = preset.name;
        option.dataset.settings = JSON.stringify(preset.settings);
        presetSelect.appendChild(option);
      });
    })
    .catch(err => console.error('[step-setup] Failed to load platform presets:', err));

  // Handle preset selection changes
  presetSelect.addEventListener('change', function() {
    const selectedOption = this.options[this.selectedIndex];
    if (this.value === 'custom') return;

    try {
      const settings = JSON.parse(selectedOption.dataset.settings || '{}');

      // Update hidden output controls
      updateOutputControl('orientation', settings.orientation);
      updateOutputControl('resolution', settings.height ? `${settings.height}p` : null);
      updateOutputControl('format', settings.format);
      updateOutputControl('fps', settings.fps ? String(settings.fps) : null);

      console.log(`[step-setup] Applied ${selectedOption.textContent} preset:`, settings);

      // Show/hide vertical video controls for 9:16 presets
      toggleVerticalVideoControls(this.value);
    } catch (err) {
      console.error('[step-setup] Failed to apply preset settings:', err);
    }
  });

  // Initialize vertical video controls on page load
  toggleVerticalVideoControls(presetSelect.value);
}

/**
 * Update a hidden output control field
 */
function updateOutputControl(id, value) {
  const select = document.getElementById(id);
  if (!select || !value) return;

  // Check if option exists, create if needed
  let option = Array.from(select.options).find(opt => opt.value === value);
  if (!option) {
    option = document.createElement('option');
    option.value = value;
    option.textContent = id === 'fps' ? `${value} fps` : value;
    select.appendChild(option);
  }
  select.value = value;
}

/**
 * Show/hide vertical video controls based on platform preset
 */
function toggleVerticalVideoControls(presetValue) {
  const verticalControls = document.getElementById('verticalVideoControls');
  if (!verticalControls) return;

  const verticalPresets = ['youtube_shorts', 'tiktok', 'instagram_reel', 'instagram_story'];
  const isVertical = verticalPresets.includes(presetValue);

  verticalControls.classList.toggle('d-none', !isVertical);
}

/**
 * Initialize vertical video zoom controls
 */
function initVerticalVideoControls() {
  const zoomSlider = document.getElementById('verticalZoom');
  const zoomDisplay = document.getElementById('verticalZoomDisplay');

  if (!zoomSlider || !zoomDisplay) return;

  // Update zoom display value
  zoomSlider.addEventListener('input', function() {
    zoomDisplay.textContent = `${this.value}%`;
  });

  // Initialize display
  zoomDisplay.textContent = `${zoomSlider.value}%`;
}

/**
 * Setup form submission handlers
 */
function setupFormHandlers(wizard) {
  const nextBtn = document.getElementById('next-1');
  const saveBtn = document.getElementById('save-as-task');

  // Next button - create project and go to Get Clips
  nextBtn?.addEventListener('click', async () => {
    await handleNext(wizard);
  });

  // Save as task button - create project without proceeding
  saveBtn?.addEventListener('click', async () => {
    await handleSaveAsTask(wizard);
  });
}

/**
 * Handle Next button - create project and navigate to step 2
 */
async function handleNext(wizard) {
  const form = document.getElementById('setup-form');
  const routeSelect = document.getElementById('route-select');
  const fd = new FormData(form);

  const route = routeSelect?.value || 'twitch';
  const maxClips = parseInt(fd.get('max_clips') || '20', 10);
  const audioNormEnabled = !!document.getElementById('audio-norm-enabled')?.checked;

  // If project already exists, verify it exists before skipping
  if (wizard.projectId) {
    console.log('[step-setup] Project already loaded, verifying:', wizard.projectId);
    try {
      const checkResponse = await fetch(`/api/projects/${wizard.projectId}/clips`, {
        credentials: 'include'
      });

      if (checkResponse.ok) {
        console.log('[step-setup] Project verified, checking clip count');
        const clipsData = await checkResponse.json();
        const clipCount = (clipsData.items || []).length;

        if (clipCount > 0) {
          console.log('[step-setup] Project has clips, skipping to step 2');
          wizard.gotoStep(2);
          return;
        }
        console.log('[step-setup] Project exists but has no clips, will fetch');
      } else {
        console.warn('[step-setup] Project no longer exists, creating new one');
        wizard.projectId = null;
      }
    } catch (err) {
      console.error('[step-setup] Error verifying project:', err);
      wizard.projectId = null;
    }
  }

  // Create new project
  try {
    const payload = {
      name: fd.get('name') || 'Untitled Project',
      description: fd.get('description') || '',
      tags: fd.get('tags') || '',
      platform_preset: fd.get('platform_preset') || 'youtube',
      orientation: fd.get('orientation') || 'landscape',
      resolution: fd.get('resolution') || '1080p',
      format: fd.get('format') || 'mp4',
      fps: parseInt(fd.get('fps') || '60', 10),
      vertical_zoom: parseInt(fd.get('vertical_zoom') || '100', 10),
      vertical_align: fd.get('vertical_align') || 'center',
      compilation_length: fd.get('compilation_length') || 'auto',
      max_clips: maxClips,
      start_date: fd.get('start_date') || '',
      end_date: fd.get('end_date') || '',
      audio_norm_db: audioNormEnabled ? (fd.get('audio_norm_db') || '') : '',
      route: route,
      discord_channel_id: fd.get('discord_channel_id') || '',
      min_reactions: parseInt(fd.get('min_reactions') || '0', 10),
      reaction_emoji: fd.get('reaction_emoji') || ''
    };

    console.log('[step-setup] Creating project with payload:', payload);

    const res = await wizard.api('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(errorText || 'Failed to create project');
    }

    const data = await res.json();
    console.log('[step-setup] API response:', data);

    wizard.projectId = data.project_id || data.id; // API returns project_id
    // Merge API response with payload to preserve all form values
    wizard.projectData = {
      ...payload,  // Include all form data
      ...data,     // Overlay API response
      id: wizard.projectId
    };

    console.log('[step-setup] Project created:', wizard.projectId);
    console.log('[step-setup] Project data:', wizard.projectData);

    // Save to localStorage and URL
    wizard.saveState();

    // Show success toast and auto-advance
    wizard.showToast('Project created successfully! Proceeding to fetch clips...', 'success');
    setTimeout(() => {
      wizard.gotoStep(2);
    }, 1500);
  } catch (err) {
    console.error('[step-setup] Error creating project:', err);
    alert(`Error creating project: ${err.message}`);
  }
}

/**
 * Handle Save as Task button - create project without proceeding
 */
async function handleSaveAsTask(wizard) {
  const form = document.getElementById('setup-form');
  const fd = new FormData(form);

  try {
    const payload = {
      name: fd.get('name') || 'Untitled Task',
      description: fd.get('description') || '',
      tags: fd.get('tags') || '',
      status: 'DRAFT'
    };

    console.log('[step-setup] Saving as task:', payload);

    const res = await wizard.api('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(errorText || 'Failed to save task');
    }

    const data = await res.json();
    console.log('[step-setup] Task saved:', data.id);

    alert('Project saved as draft! You can continue editing it from the Projects page.');

    // Redirect to projects page
    window.location.href = '/projects';
  } catch (err) {
    console.error('[step-setup] Error saving task:', err);
    alert(`Error saving task: ${err.message}`);
  }
}
