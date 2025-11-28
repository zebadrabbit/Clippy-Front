/**
 * Step 2: Get Clips - Fetch, parse, download, and import clips
 * Handles the complete clip acquisition workflow with progress tracking
 */

let downloadPollTimer = null;
let autoRunInProgress = false; // Prevent multiple simultaneous auto-runs

export async function onEnter(wizard) {
  console.log('[step-clips] Entering clips step');

  // Setup navigation handlers
  setupNavigation(wizard);

  // CRITICAL: Prevent multiple auto-runs
  if (autoRunInProgress) {
    console.warn('[step-clips] Auto-run already in progress, skipping');
    return;
  }

  // Check wizard state to see if clips step was already completed
  const wizardState = wizard.loadWizardState();
  const clipsCompleted = wizardState?.clipsCompleted || false;

  console.log('[step-clips] Wizard state:', wizardState);
  console.log('[step-clips] Clips completed:', clipsCompleted);

  // Only auto-run if we haven't completed this step before
  if (wizard.projectId && !clipsCompleted) {
    console.log('[step-clips] First time on clips step, starting auto-run');
    autoRunInProgress = true;
    try {
      await autoRunGetClips(wizard);
    } finally {
      autoRunInProgress = false;
    }
  } else if (clipsCompleted) {
    console.log('[step-clips] Clips step already completed, skipping auto-run');
    setGcActive('done');
    setGcDone('fetch');
    setGcDone('extract');
    setGcDone('queue');
    setGcDone('download');
    setGcDone('import');
    setGcDone('done');
    setGcStatus('Ready.');
    setGcFill(100);
    document.getElementById('next-2').disabled = false;
  }
}

export function onExit(wizard) {
  console.log('[step-clips] Exiting clips step');

  // Cleanup polling timer
  if (downloadPollTimer) {
    clearInterval(downloadPollTimer);
    downloadPollTimer = null;
  }
}

/**
 * Setup navigation handlers
 */
function setupNavigation(wizard) {
  const prevBtn = document.querySelector('[data-prev="1"]');
  const nextBtn = document.getElementById('next-2');

  prevBtn?.addEventListener('click', () => wizard.gotoStep(1));
  nextBtn?.addEventListener('click', () => wizard.gotoStep(3));
}

/**
 * Auto-run the complete Get Clips flow
 */
async function autoRunGetClips(wizard) {
  console.log('[step-clips] Auto-running Get Clips workflow');

  setGcActive('fetch');
  setGcStatus('Casting a net for clips...');
  setGcFill(5);

  try {
    // Step 1: Fetch clip URLs
    let urls = [];
    const route = wizard.projectData?.route || 'twitch';

    if (route === 'discord') {
      urls = await fetchDiscordClips(wizard);
    } else {
      urls = await fetchTwitchClips(wizard);
    }

    if (!urls || urls.length === 0) {
      throw new Error('No clips found');
    }

    setGcDone('fetch');
    setGcActive('extract');
    setGcStatus(`Detected ${urls.length} clip URL(s).`);
    setGcFill(20);

    // Step 2: Queue downloads
    await queueDownloads(wizard, urls);
    setGcDone('extract');
    setGcActive('queue');
    setGcStatus(`Stacking ${wizard.downloadTasks.length} download(s)...`);
    setGcFill(35);

    const hasDownloadTasks = (wizard.downloadTasks || []).some(t => t && t.task_id);
    setGcDone('queue');

    if (hasDownloadTasks) {
      // Step 3: Poll download progress
      setGcActive('download');
      setGcFill(40);
      await startDownloadPolling(wizard);
    } else {
      // All clips were reused - skip to import
      setGcDone('download');
      setGcActive('import');
      setGcStatus('Importing artifacts from workers...');
      setGcFill(80);

      await runIngest(wizard);
      setGcDone('import');

      // Verify clips ready
      const verify = await verifyAllClipsReady(wizard);
      if (verify.ready && verify.total > 0) {
        setGcActive('done');
        setGcDone('done');
        setGcStatus('Ready.');
        setGcFill(100);
        document.getElementById('next-2').disabled = false;
        wizard.clipsProcessed = true;
      } else {
        setGcError('import');
        setGcStatus(`⚠ ${verify.missing || 0} clip(s) failed to import.`);
        setGcFill(95);
      }
    }
  } catch (err) {
    console.error('[step-clips] Auto-run failed:', err);
    setGcError('fetch');
    setGcStatus(`Error: ${err.message || 'Unknown error'}`);
  }
}

/**
 * Fetch clips from Twitch
 */
async function fetchTwitchClips(wizard) {
  try {
    const compilationLength = wizard.projectData?.compilation_length || 'auto';
    const maxClips = wizard.projectData?.max_clips || 20;

    let url = '/api/twitch/clips';
    const params = new URLSearchParams();

    // Use duration-based fetching if compilation_length is not 'auto'
    if (compilationLength !== 'auto') {
      const targetDuration = parseInt(compilationLength, 10);
      if (!isNaN(targetDuration) && targetDuration > 0) {
        params.set('target_duration', String(targetDuration));
        console.log(`[step-clips] Fetching clips for target duration: ${targetDuration}s`);
      }
    } else {
      // Use max_clips limit for 'auto' mode
      const first = Math.max(1, Math.min(100, maxClips));
      params.set('first', String(first));
      console.log(`[step-clips] Fetching up to ${first} clips (auto mode)`);
    }

    // Add date filters if present
    if (wizard.projectData?.start_date) {
      params.set('started_at', wizard.projectData.start_date);
    }
    if (wizard.projectData?.end_date) {
      params.set('ended_at', wizard.projectData.end_date);
    }

    const res = await fetch(`${url}?${params.toString()}`);
    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    const items = data.items || [];
    const urls = items.map(it => it.url).filter(Boolean);
    const totalDuration = data.total_duration;

    wizard.fetchedClips = items;

    let statusMsg = `Reeled in ${items.length} clips for @${data.username}.`;
    if (totalDuration !== undefined) {
      const minutes = Math.floor(totalDuration / 60);
      const seconds = Math.floor(totalDuration % 60);
      statusMsg += ` Total duration: ${minutes}m ${seconds}s`;
    }
    setGcStatus(statusMsg);

    return urls;
  } catch (e) {
    console.error('[step-clips] Twitch fetch failed:', e);
    setGcError('fetch');
    setGcStatus('Couldn\'t fetch clips. Check your Twitch settings.');
    throw e;
  }
}

/**
 * Fetch clips from Discord
 */
async function fetchDiscordClips(wizard) {
  try {
    const minReactions = wizard.projectData?.min_reactions || 0;
    const reactionEmoji = wizard.projectData?.reaction_emoji || '';
    const channelId = wizard.projectData?.discord_channel_id || '';

    const params = new URLSearchParams({ limit: '200' });
    if (minReactions >= 0) params.set('min_reactions', String(minReactions));
    if (reactionEmoji) params.set('reaction_emoji', reactionEmoji);
    if (channelId) params.set('channel_id', channelId);

    const res = await fetch(`/api/discord/messages?${params.toString()}`);
    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    const urls = (data.clip_urls || []).filter(Boolean);
    const filtered = data.filtered_count !== undefined ? data.filtered_count : (data.items || []).length;

    setGcStatus(`Sifted ${filtered} messages • found ${urls.length} clip link(s)${minReactions > 1 ? ` (≥${minReactions} reactions)` : ''}.`);

    return urls;
  } catch (e) {
    console.error('[step-clips] Discord fetch failed:', e);
    setGcError('fetch');
    setGcStatus("Couldn't fetch Discord messages. Check DISCORD config.");
    throw e;
  }
}

/**
 * Queue clip downloads
 */
async function queueDownloads(wizard, urls) {
  if (!wizard.projectId) {
    throw new Error('Project not created yet.');
  }
  if (!urls || urls.length === 0) {
    throw new Error('No clip URLs to download.');
  }

  // CRITICAL: Check if project already has clips to prevent duplicate downloads
  try {
    const checkRes = await wizard.api(`/api/projects/${wizard.projectId}/clips`);
    if (checkRes.ok) {
      const checkData = await checkRes.json();
      const existingClips = (checkData && checkData.items) || [];
      if (existingClips.length > 0) {
        console.warn(`[step-clips] Project already has ${existingClips.length} clips, aborting new downloads`);
        setGcStatus(`Using ${existingClips.length} existing clips.`);
        wizard.downloadTasks = []; // No new tasks
        return;
      }
    }
  } catch (e) {
    console.warn('[step-clips] Could not check existing clips:', e);
    // Continue anyway
  }

  // Calculate effective limit based on compilation_length
  const compilationLength = wizard.projectData?.compilation_length || 'auto';
  let effectiveLimit = urls.length; // Default to all fetched clips

  console.log(`[step-clips] max_clips from projectData: ${wizard.projectData?.max_clips}`);
  console.log(`[step-clips] Total URLs available: ${urls.length}`);
  console.log(`[step-clips] Compilation length: ${compilationLength}`);

  // Only apply max_clips limit when in 'auto' mode
  if (compilationLength === 'auto') {
    effectiveLimit = wizard.projectData?.max_clips || urls.length;
    console.log(`[step-clips] Auto mode - limiting to max_clips: ${effectiveLimit}`);
  } else {
    // Duration-based mode - use all fetched clips (backend already filtered by duration)
    effectiveLimit = urls.length;
    console.log(`[step-clips] Duration mode - using all ${effectiveLimit} fetched clips`);
  }

  const limit = Math.max(1, Math.min(100, effectiveLimit));
  console.log(`[step-clips] Final limit (capped 1-100): ${limit}`);

  let payload = { urls: urls.slice(0, limit), limit };

  // Include clip metadata if available
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

  const res = await wizard.api(`/api/projects/${wizard.projectId}/clips/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(errorText || 'Failed to queue downloads');
  }

  const r = await res.json();
  wizard.downloadTasks = r.items || [];

  const actualCount = r.count !== undefined ? r.count : wizard.downloadTasks.length;
  const skipped = r.skipped || 0;

  console.log(`[step-clips] API created ${actualCount} clips (${skipped} duplicates skipped)`);
  setGcStatus(`Queued ${wizard.downloadTasks.length} download${wizard.downloadTasks.length !== 1 ? 's' : ''} (${actualCount} clip${actualCount !== 1 ? 's' : ''}${skipped > 0 ? `, ${skipped} duplicate${skipped !== 1 ? 's' : ''} skipped` : ''}).`);
}

/**
 * Start polling download task progress
 */
async function startDownloadPolling(wizard) {
  setGcStatus('Pulling clips down...');

  const realTasks = (wizard.downloadTasks || []).filter(t => t && t.task_id);
  const total = realTasks.length || 1;

  async function poll() {
    let done = 0, failed = 0;

    for (const t of realTasks) {
      if (!t || !t.task_id) continue;
      if (t.done) { done++; continue; }

      try {
        const res = await fetch(`/api/tasks/${t.task_id}`);
        const s = await res.json();
        const st = String((s && (s.state || s.status)) || '').toUpperCase();

        if (st) t._lastState = st;

        if (st === 'SUCCESS' || (s && s.ready && st !== 'FAILURE')) {
          t.done = true;
          done++;
        } else if (st === 'FAILURE') {
          t.done = true;
          t.failed = true;
          done++;
          failed++;
        }
      } catch (_) {
        // Ignore polling errors, continue
      }
    }

    const pct = Math.floor((done / total) * 100);
    setGcStatus(`Pulling clips down... ${pct}% (${done - failed}/${total} ok${failed ? `, ${failed} hiccuped` : ''})`);

    // Map download progress: 40% → 95%
    const overall = 40 + Math.round((pct / 100) * 55);
    setGcFill(overall);

    if (done >= total) {
      clearInterval(downloadPollTimer);
      downloadPollTimer = null;

      setGcDone('download');
      setGcActive('import');
      setGcStatus('Importing artifacts from workers...');
      setGcFill(80);

      // Run ingest
      await runIngest(wizard);
      setGcDone('import');

      // Verify clips ready with retries
      setGcStatus('Verifying all clips are ready...');
      let retries = 0;
      const maxRetries = 3;
      let finalVerify = null;

      while (retries < maxRetries) {
        finalVerify = await verifyAllClipsReady(wizard);
        if (finalVerify.ready && finalVerify.total > 0) {
          break;
        }
        if (finalVerify.missing > 0) {
          console.log(`[step-clips] Verification attempt ${retries + 1}/${maxRetries}: ${finalVerify.missing} clips missing`);
          setGcStatus(`Waiting for ${finalVerify.missing} clip(s)... (${retries + 1}/${maxRetries})`);
          await new Promise(r => setTimeout(r, 3000));
          if (retries < maxRetries - 1) {
            await runIngest(wizard);
          }
        }
        retries++;
      }

      // Enable Next button if all verified
      if (finalVerify && finalVerify.ready && finalVerify.total > 0) {
        setGcActive('done');
        setGcDone('done');
        setGcStatus('Ready.');
        setGcFill(100);
        document.getElementById('next-2').disabled = false;

        // Mark clips step as completed in wizard state
        await wizard.saveWizardState({ clipsCompleted: true });
      } else if (finalVerify && finalVerify.missing > 0) {
        setGcError('import');
        setGcStatus(`⚠ ${finalVerify.missing} clip(s) failed to import. Check worker logs.`);
        setGcFill(95);
        console.error('[step-clips] Verification failed after retries:', finalVerify);
      } else {
        setGcError('done');
        setGcStatus('⚠ No clips were imported. Check your filters.');
        setGcFill(100);
        console.warn('[step-clips] No clips found after verification');
      }
    }
  }

  downloadPollTimer = setInterval(poll, 1000);
  await poll();
}

/**
 * Run ingest to import artifacts
 */
async function runIngest(wizard) {
  if (!wizard.projectId) return;

  setGcActive('import');
  setGcStatus('Importing artifacts from workers...');

  try {
    // Get worker IDs from config (passed from server)
    const workerIds = (window.INGEST_WORKER_IDS || 'gpu-worker-01').split(',').map(id => id.trim()).filter(Boolean);

    // Call ingest for each worker
    const ingestPromises = workerIds.map(async workerId => {
      try {
        const res = await wizard.api(`/api/projects/${wizard.projectId}/ingest-downloads`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            worker_id: workerId,
            action: 'copy'
          })
        });

        if (res.ok) {
          const data = await res.json();
          console.log(`[step-clips] Ingest started for worker ${workerId}:`, data.task_id);
          return { workerId, success: true, taskId: data.task_id };
        } else {
          console.warn(`[step-clips] Ingest failed for worker ${workerId}:`, res.status);
          return { workerId, success: false };
        }
      } catch (e) {
        console.error(`[step-clips] Ingest error for worker ${workerId}:`, e);
        return { workerId, success: false, error: e.message };
      }
    });

    const results = await Promise.all(ingestPromises);
    const successCount = results.filter(r => r.success).length;
    console.log(`[step-clips] Ingest tasks started: ${successCount}/${workerIds.length}`);

    // Wait a moment for ingest to process
    await new Promise(r => setTimeout(r, 2000));

    // Verify clips are ready
    const verifyResult = await verifyAllClipsReady(wizard);
    if (!verifyResult.ready) {
      console.warn('[step-clips] Some clips not ready after ingest:', verifyResult);
      setGcStatus(`Waiting for ${verifyResult.missing} more clip(s)...`);
      await new Promise(r => setTimeout(r, 2000));

      const retryResult = await verifyAllClipsReady(wizard);
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
    console.error('[step-clips] Ingest error:', e);
    setGcError('import');
    setGcStatus('Ingest failed.');
    return 'error';
  }
}

/**
 * Verify all clips have media and thumbnails
 */
async function verifyAllClipsReady(wizard) {
  if (!wizard.projectId) return { ready: true, total: 0, missing: 0 };

  try {
    const res = await wizard.api(`/api/projects/${wizard.projectId}/clips`);
    const data = await res.json();
    const clips = (data && data.items) || [];

    let missing = 0;
    const missingDetails = [];

    for (const clip of clips) {
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
        console.warn(`[step-clips] Clip ${clip.id} (${clip.title}) missing media or thumbnail:`, clip.media);
      }
    }

    console.log(`[step-clips] Verification: ${clips.length} total, ${missing} missing, ${clips.length - missing} ready`);
    if (missingDetails.length > 0) {
      console.log('[step-clips] Missing details:', missingDetails);
    }

    return {
      ready: missing === 0,
      total: clips.length,
      missing: missing,
      clips: clips
    };
  } catch (e) {
    console.error('[step-clips] Failed to verify:', e);
    return { ready: true, total: 0, missing: 0 }; // Fail open
  }
}

/**
 * Progress UI helpers
 */
function setGcStatus(text) {
  const el = document.getElementById('gc-status');
  if (el) el.textContent = text || '';
}

function setGcFill(pct) {
  const el = document.getElementById('gc-fill');
  if (el) {
    const v = Math.max(0, Math.min(100, Math.floor(pct || 0)));
    el.style.width = v + '%';
    el.setAttribute('aria-valuenow', String(v));
  }
}

function getGcStepEl(key) {
  return document.querySelector(`#gc-steps li[data-key="${key}"]`);
}

function clearGcStates() {
  document.querySelectorAll('#gc-steps li').forEach(s => {
    s.classList.remove('active', 'error');
  });
}

function setGcActive(key) {
  clearGcStates();
  const el = getGcStepEl(key);
  if (el) el.classList.add('active');
}

function setGcDone(key) {
  const el = getGcStepEl(key);
  if (el) {
    el.classList.remove('error');
    el.classList.add('done');
  }
}

function setGcError(key) {
  const el = getGcStepEl(key);
  if (el) {
    el.classList.remove('active', 'done');
    el.classList.add('error');
  }
}
