/**
 * Step 2: Get Clips - Fetch, parse, download, and import clips
 * Handles the complete clip acquisition workflow with progress tracking
 */

let downloadPollTimer = null;

export async function onEnter(wizard) {
  console.log('[step-clips] Entering clips step');

  // Setup navigation handlers
  setupNavigation(wizard);

  // Auto-run fetch and download if we just came from Step 1
  if (wizard.projectId && !wizard.clipsProcessed) {
    await autoRunGetClips(wizard);
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
  setGcStatus('Casting a net for clips…');
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
    setGcStatus(`Stacking ${wizard.downloadTasks.length} download(s)…`);
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
      setGcStatus('Importing artifacts from workers…');
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
    const maxClips = wizard.projectData?.max_clips || 20;
    const first = Math.max(1, Math.min(100, maxClips));

    const res = await fetch(`/api/twitch/clips?first=${first}`);
    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    const items = data.items || [];
    const urls = items.map(it => it.url).filter(Boolean);

    wizard.fetchedClips = items;
    setGcStatus(`Reeled in ${items.length} clips for @${data.username}.`);

    return urls;
  } catch (e) {
    console.error('[step-clips] Twitch fetch failed:', e);
    setGcError('fetch');
    setGcStatus('Couldn't fetch clips. Check your Twitch settings.');
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

  // Calculate effective limit based on compilation_length
  let effectiveLimit = wizard.projectData?.max_clips || urls.length;

  const compilationLength = wizard.projectData?.compilation_length || 'auto';
  if (compilationLength !== 'auto') {
    const targetSeconds = parseInt(compilationLength, 10);
    if (!isNaN(targetSeconds) && targetSeconds > 0) {
      const avgClipDuration = parseInt(document.body.dataset.avgClipDuration || '45', 10);
      const estimatedClipsNeeded = Math.ceil(targetSeconds / avgClipDuration);
      effectiveLimit = Math.min(estimatedClipsNeeded, wizard.projectData?.max_clips || estimatedClipsNeeded);
      console.log(`[step-clips] Compilation length target: ${targetSeconds}s, estimated clips: ${estimatedClipsNeeded}, effective limit: ${effectiveLimit}`);
    }
  }

  const limit = Math.max(1, Math.min(100, effectiveLimit));
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
  setGcStatus('Pulling clips down…');

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
    setGcStatus(`Pulling clips down… ${pct}% (${done - failed}/${total} ok${failed ? `, ${failed} hiccuped` : ''})`);

    // Map download progress: 40% → 95%
    const overall = 40 + Math.round((pct / 100) * 55);
    setGcFill(overall);

    if (done >= total) {
      clearInterval(downloadPollTimer);
      downloadPollTimer = null;

      setGcDone('download');
      setGcActive('import');
      setGcStatus('Importing artifacts from workers…');
      setGcFill(80);

      // Run ingest
      await runIngest(wizard);
      setGcDone('import');

      // Verify clips ready with retries
      setGcStatus('Verifying all clips are ready…');
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
        wizard.clipsProcessed = true;
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
  setGcStatus('Verifying clips are ready…');

  try {
    const verifyResult = await verifyAllClipsReady(wizard);
    if (!verifyResult.ready) {
      console.warn('[step-clips] Some clips not ready:', verifyResult);
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
    console.error('[step-clips] Verification error:', e);
    setGcError('import');
    setGcStatus('Verification failed.');
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
