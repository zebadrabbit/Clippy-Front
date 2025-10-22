(function(){
  if (typeof Dropzone === 'undefined') {
    console.error('Dropzone failed to load. Uploads are disabled on this page.');
    return;
  }
  Dropzone.autoDiscover = false;
  const dzEl = document.getElementById('media-dropzone');
  let grid = document.getElementById('media-grid');
  const bulkBar = document.getElementById('bulk-toolbar');
  const bulkCount = document.getElementById('bulk-count');
  const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
  const mediaTypeSel = document.getElementById('dz-media-type');
  const cfg = document.getElementById('media-config');
  if (!dzEl || !cfg) return;
  const UPLOAD_URL = cfg.dataset.uploadUrl;
  const BULK_URL = cfg.dataset.bulkUrl;
  const DELETE_URL_TPL = cfg.dataset.deleteUrlTemplate;
  const UPDATE_URL_TPL = cfg.dataset.updateUrlTemplate;
  const PREVIEW_URL_TPL = cfg.dataset.previewUrlTemplate;
  const THUMB_URL_TPL = cfg.dataset.thumbnailUrlTemplate;

  const dz = new Dropzone(dzEl, {
    url: UPLOAD_URL,
    headers: { 'X-CSRFToken': csrfToken },
    paramName: 'file',
    maxFilesize: 1024,
    acceptedFiles: 'image/*,video/*',
    parallelUploads: 2,
    previewsContainer: dzEl.querySelector('.dz-previews'),
    addRemoveLinks: false,
    createImageThumbnails: false,
    previewTemplate: '<div></div>',
    init: function() {
      this.on('sending', function(file, xhr, formData) {
        formData.append('media_type', mediaTypeSel.value || 'clip');
      });
      this.on('success', function(file, resp){
        if (!resp || !resp.success) return;
        const col = createMediaCard(resp);
        // Ensure grid exists even if the page initially had no media
        if (!grid) {
          const placeholder = Array.from(document.querySelectorAll('p.text-muted'))
            .find(p => /No media files yet\./i.test(p.textContent || ''));
          const newGrid = document.createElement('div');
          newGrid.id = 'media-grid';
          newGrid.className = 'row row-cols-1 row-cols-sm-2 row-cols-md-3 row-cols-lg-4 g-3';
          if (placeholder && placeholder.parentElement) {
            placeholder.replaceWith(newGrid);
          } else {
            const container = document.querySelector('.container.py-4');
            if (container) { container.appendChild(newGrid); }
          }
          grid = document.getElementById('media-grid') || newGrid;
        }
        if (grid && col) { grid.prepend(col); attachCardHandlers(col); updateBulkBar(); }
        // Clear Dropzone preview/icon and reset state for a clean area
        try { dz.removeFile(file); } catch (_) {}
      });
    }
  });

  function createMediaCard(item){
    const col = document.createElement('div'); col.className = 'col';
    const card = document.createElement('div'); card.className = 'card h-100 position-relative media-card';
    card.dataset.id = item.id; card.dataset.mime = item.mime || ''; card.dataset.type = item.type || ''; card.dataset.name = item.original_filename || item.filename; card.dataset.previewUrl = item.preview_url; card.dataset.thumbUrl = item.thumbnail_url || ''; card.dataset.tags = item.tags || '';
    const selWrap = document.createElement('div'); selWrap.className = 'position-absolute top-0 start-0 p-2'; selWrap.innerHTML = '<input class="form-check-input media-select" type="checkbox" value="' + item.id + '">'; card.appendChild(selWrap);
    let mediaHtml = '';
    if ((item.mime||'').startsWith('image')) mediaHtml = '<img src="' + item.preview_url + '" class="card-img-top" alt="' + escapeHtml(card.dataset.name) + '">';
  else if ((item.mime||'').startsWith('video')) mediaHtml = '<button type="button" class="btn p-0 border-0 text-start w-100 video-open position-relative" data-id="' + item.id + '" style="background: var(--bs-card-bg);"><img src="' + THUMB_URL_TPL.replace('0', item.id) + '" class="img-fluid" alt="' + escapeHtml(card.dataset.name) + '"><i class="bi bi-play-circle-fill position-absolute top-50 start-50 translate-middle" style="font-size:2.5rem; opacity:0.85;"></i></button>';
  else mediaHtml = '<div class="card-img-top d-flex align-items-center justify-content-center" style="height:160px; background: var(--bs-card-bg);"><i class="bi bi-file-earmark-text" style="font-size:2rem;"></i></div>';
    card.insertAdjacentHTML('beforeend', mediaHtml);
    const body = document.createElement('div'); body.className = 'card-body';
    body.innerHTML = '<div class="fw-semibold text-truncate" title="' + escapeHtml(card.dataset.name) + '">' + escapeHtml(card.dataset.name) + '</div><small class="text-muted">' + (item.type || '') + '</small>';
    if ((item.tags||'').trim()) {
      const tagsHtml = (item.tags||'').split(',').map(function(s){ s=s.trim(); return s? '<span class="badge bg-secondary me-1">'+s+'</span>':''; }).join('');
      const div = document.createElement('div'); div.className = 'mt-1 small'; div.innerHTML = tagsHtml; body.appendChild(div);
    }
    card.appendChild(body);
    const footer = document.createElement('div'); footer.className = 'card-footer d-flex justify-content-between align-items-center';
    footer.innerHTML = '<button type="button" class="btn btn-sm btn-outline-secondary media-edit" data-id="' + item.id + '">Edit</button><button type="button" class="btn btn-sm btn-outline-danger media-delete" data-id="' + item.id + '">Delete</button>';
    card.appendChild(footer);
    col.appendChild(card);
    return col;
  }

  function escapeHtml(str){ return (str||'').replace(/[&<>"]/g, function(c){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]); }); }

  function attachHandlers(){
    document.querySelectorAll('.media-edit').forEach(function(btn){ btn.addEventListener('click', onEditClick); });
    document.querySelectorAll('.media-delete').forEach(function(btn){ btn.addEventListener('click', onDeleteClick); });
    document.querySelectorAll('.media-select').forEach(function(cb){ cb.addEventListener('change', updateBulkBar); });
    document.querySelectorAll('.video-open').forEach(function(btn){ btn.addEventListener('click', onOpenVideo); });
    var selAll = document.getElementById('bulk-select-all'); if (selAll) selAll.addEventListener('click', function(){ document.querySelectorAll('.media-select').forEach(function(cb){ cb.checked=true; }); updateBulkBar(); });
    var clearBtn = document.getElementById('bulk-clear'); if (clearBtn) clearBtn.addEventListener('click', function(){ document.querySelectorAll('.media-select').forEach(function(cb){ cb.checked=false; }); updateBulkBar(); });
    var delBtn = document.getElementById('bulk-delete'); if (delBtn) delBtn.addEventListener('click', onBulkDelete);
    var applyBtn = document.getElementById('bulk-apply-type'); if (applyBtn) applyBtn.addEventListener('click', onBulkChangeType);
    var applyTagsBtn = document.getElementById('bulk-apply-tags'); if (applyTagsBtn) applyTagsBtn.addEventListener('click', onBulkSetTags);
  }

  function attachCardHandlers(col){
    var edit = col.querySelector('.media-edit'); if (edit) edit.addEventListener('click', onEditClick);
    var del = col.querySelector('.media-delete'); if (del) del.addEventListener('click', onDeleteClick);
    var cb = col.querySelector('.media-select'); if (cb) cb.addEventListener('change', updateBulkBar);
    var open = col.querySelector('.video-open'); if (open) open.addEventListener('click', onOpenVideo);
  }

  function selectedIds(){ return Array.from(document.querySelectorAll('.media-select:checked')).map(function(cb){ return cb.value; }); }
  function updateBulkBar(){ const count = selectedIds().length; bulkCount.textContent = count; bulkBar.classList.toggle('d-none', count===0); }
  async function apiPost(url, data){ const body = (data instanceof FormData) ? data : new URLSearchParams(data); const res = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body }); return res.json(); }

  async function onBulkDelete(){
    const ids = selectedIds(); if (!ids.length) return; if (!confirm('Delete ' + ids.length + ' selected item(s)?')) return;
    const fd = new FormData(); fd.append('action','delete'); ids.forEach(function(id){ fd.append('ids[]', id); });
    const resp = await apiPost(BULK_URL, fd);
    if (resp && resp.success){ ids.forEach(function(id){ const el = document.querySelector('.media-card[data-id="' + id + '"]'); el && el.closest('.col').remove(); }); updateBulkBar(); showToast('Deleted ' + ids.length + ' item(s).'); }
    else alert((resp && resp.error) || 'Bulk delete failed');
  }

  async function onBulkChangeType(){
    const ids = selectedIds(); const typeSel = document.getElementById('bulk-type'); const newType = typeSel && typeSel.value; if (!ids.length || !newType) return;
    const fd = new FormData(); fd.append('action','change_type'); fd.append('media_type', newType); ids.forEach(function(id){ fd.append('ids[]', id); });
    const resp = await apiPost(BULK_URL, fd);
    if (resp && resp.success){ ids.forEach(function(id){ const card = document.querySelector('.media-card[data-id="' + id + '"]'); if (card){ card.dataset.type = newType; const small = card.querySelector('.card-body small'); if (small) small.textContent = newType; } }); showToast('Type updated for ' + ids.length + ' item(s).'); }
    else alert((resp && resp.error) || 'Bulk update failed');
  }

  function normalizeTags(raw){
    return Array.from(new Set((raw||'')
      .split(',')
      .map(function(s){ return s.trim().toLowerCase(); })
      .filter(function(s){ return s.length>0; })))
      .join(',');
  }

  async function onBulkSetTags(){
    const ids = selectedIds(); const input = document.getElementById('bulk-tags'); let tags = (input && input.value) || ''; if (!ids.length) return;
    tags = normalizeTags(tags);
    const fd = new FormData(); fd.append('action','set_tags'); fd.append('tags', tags); ids.forEach(function(id){ fd.append('ids[]', id); });
    const resp = await apiPost(BULK_URL, fd);
    if (resp && resp.success){ ids.forEach(function(id){ const card = document.querySelector('.media-card[data-id="' + id + '"]'); if (!card) return; const body = card.querySelector('.card-body'); if (!body) return; let tagsWrap = body.querySelector('.mt-1.small'); const html = (tags||'').split(',').map(function(s){ s=s.trim(); return s? '<span class=\"badge bg-secondary me-1\">'+s+'</span>':''; }).join(''); if (tagsWrap) tagsWrap.innerHTML = html; else if (html){ const div = document.createElement('div'); div.className = 'mt-1 small'; div.innerHTML = html; body.appendChild(div);} card.dataset.tags = tags; }); showToast('Tags updated for ' + ids.length + ' item(s).'); }
    else alert((resp && resp.error) || 'Bulk tag update failed');
  }

  function onEditClick(e){ const id = e.currentTarget.getAttribute('data-id'); const card = document.querySelector('.media-card[data-id="' + id + '"]'); openEditModal({ id: id, name: (card && card.dataset.name)||'', type: (card && card.dataset.type)||'', tags: (card && card.dataset.tags)||'' }); }
  async function onDeleteClick(e){ const id = e.currentTarget.getAttribute('data-id'); if (!confirm('Delete this media item?')) return; const resp = await apiPost(DELETE_URL_TPL.replace('0', id), {}); if (resp && resp.success){ const el = document.querySelector('.media-card[data-id="' + id + '"]'); el && el.closest('.col').remove(); updateBulkBar(); showToast('Item deleted.'); } else alert((resp && resp.error) || 'Delete failed'); }

  // Edit modal
  const editModalEl = document.createElement('div'); editModalEl.className = 'modal fade'; editModalEl.tabIndex = -1; editModalEl.innerHTML = `
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Edit Media</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body">
          <form id="media-edit-form">
            <input type="hidden" name="media_id" />
            <div class="mb-3">
              <label class="form-label">Name</label>
              <input type="text" class="form-control" name="original_filename" />
            </div>
            <div class="mb-3">
              <label class="form-label">Type</label>
              <select class="form-select" name="media_type">
                ${(function(){
                  const sel = document.getElementById('bulk-type');
                  if (!sel) return '';
                  return Array.from(sel.options).filter(o => o.value).map(o => `<option value="${o.value}">${o.textContent}</option>`).join('');
                })()}
              </select>
            </div>
            <div class="mb-1">
              <label class="form-label">Tags</label>
              <input type="text" class="form-control" name="tags" placeholder="comma,separated,tags" />
              <div class="form-text">Use commas to separate tags.</div>
            </div>
          </form>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-danger" id="media-edit-delete">Delete</button>
          <button type="button" class="btn btn-primary" id="media-edit-save">Save</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(editModalEl);
  let bsModal; function ensureBsModal(){ if (!bsModal) bsModal = new bootstrap.Modal(editModalEl); return bsModal; }
  function openEditModal(opts){ const form = editModalEl.querySelector('#media-edit-form'); form.media_id.value = opts.id; form.original_filename.value = opts.name || ''; form.media_type.value = opts.type || ''; form.tags.value = opts.tags || ''; ensureBsModal().show(); }
  document.getElementById('media-edit-save').addEventListener('click', async function(){ const form = editModalEl.querySelector('#media-edit-form'); const id = form.media_id.value; form.tags.value = normalizeTags(form.tags.value); const fd = new FormData(form); const resp = await apiPost(UPDATE_URL_TPL.replace('0', id), fd); if (resp && resp.success){ const card = document.querySelector('.media-card[data-id="' + id + '"]'); if (card){ card.dataset.name = form.original_filename.value; card.dataset.type = form.media_type.value; card.dataset.tags = form.tags.value; const titleEl = card.querySelector('.card-body .fw-semibold'); const small = card.querySelector('.card-body small'); if (titleEl) titleEl.textContent = form.original_filename.value; if (small) small.textContent = form.media_type.value; const body = card.querySelector('.card-body'); if (body){ let tagsWrap = body.querySelector('.mt-1.small'); const html = (form.tags.value||'').split(',').map(function(s){ s=s.trim(); return s? '<span class=\"badge bg-secondary me-1\">'+s+'</span>':''; }).join(''); if (tagsWrap) tagsWrap.innerHTML = html; else if (html){ const div = document.createElement('div'); div.className = 'mt-1 small'; div.innerHTML = html; body.appendChild(div);} } } ensureBsModal().hide(); if (typeof showToast === 'function') { showToast('Media updated.'); } } else alert((resp && resp.error) || 'Update failed'); });
  document.getElementById('media-edit-delete').addEventListener('click', async function(){ const form = editModalEl.querySelector('#media-edit-form'); const id = form.media_id.value; if (!confirm('Delete this media item?')) return; const resp = await apiPost(DELETE_URL_TPL.replace('0', id), {}); if (resp && resp.success){ const el = document.querySelector('.media-card[data-id="' + id + '"]'); el && el.closest('.col').remove(); ensureBsModal().hide(); updateBulkBar(); } else alert((resp && resp.error) || 'Delete failed'); });

  // Toast helper
  const toastWrap = document.createElement('div'); toastWrap.className = 'position-fixed'; toastWrap.style.zIndex='1080'; toastWrap.style.right='1rem'; toastWrap.style.bottom='1rem'; document.body.appendChild(toastWrap);
  function showToast(message){
    const el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-dark border-0 show';
    el.setAttribute('role','alert'); el.setAttribute('aria-live','assertive'); el.setAttribute('aria-atomic','true');
    el.innerHTML = '<div class="d-flex"><div class="toast-body">'+message+'</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
    toastWrap.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 2500 });
    t.show();
    setTimeout(function(){ el.remove(); }, 3000);
  }

  // Video playback modal
  const playerModalEl = document.createElement('div'); playerModalEl.className = 'modal fade'; playerModalEl.tabIndex = -1; playerModalEl.innerHTML = `
    <div class="modal-dialog modal-lg">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Preview</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body">
          <video id="inline-player" class="video-js vjs-default-skin vjs-16-9" controls preload="auto" data-setup='{}'></video>
        </div>
      </div>
    </div>`;
  document.body.appendChild(playerModalEl);
  let bsPlayerModal; function ensurePlayerModal(){ if (!bsPlayerModal) bsPlayerModal = new bootstrap.Modal(playerModalEl); return bsPlayerModal; }
  let vjs;
  function onOpenVideo(e){
    const id = e.currentTarget.getAttribute('data-id');
    const card = document.querySelector('.media-card[data-id="' + id + '"]');
    const rawMime = (card && card.dataset.mime) || '';
    const name = (card && card.dataset.name) || '';
    const validMime = /^video\/[\w.+-]+$/.test(rawMime);
    const ext = (name.split('.').pop() || '').toLowerCase();
    const guessedMime = (function(){
      switch(ext){
        case 'mp4': return 'video/mp4';
        case 'webm': return 'video/webm';
        case 'mov': return 'video/quicktime';
        case 'mkv': return 'video/x-matroska';
        case 'avi': return 'video/x-msvideo';
        default: return '';
      }
    })();
    const mime = validMime ? rawMime : (guessedMime || '');
    const src = PREVIEW_URL_TPL.replace('0', id);
    const probe = document.createElement('video');
    if (mime && probe.canPlayType && !probe.canPlayType(mime)){
      showToast('This format is not supported by your browser. Downloading instead.');
      window.open(src, '_blank');
      return;
    }
    ensurePlayerModal().show();
    const el = document.getElementById('inline-player');
    if (vjs){
      if (mime) vjs.src({ src, type: mime }); else vjs.src(src);
      vjs.play();
    } else {
      vjs = videojs(el);
      if (mime) vjs.src({ src, type: mime }); else vjs.src(src);
      vjs.on('error', function(){
        const err = vjs.error();
        console.error('Video.js playback error', err);
        showToast('Playback failed; opening the file directly.');
        window.open(src, '_blank');
      });
      vjs.play();
    }
  }

  // Ensure playback stops when modal closes
  playerModalEl.addEventListener('hidden.bs.modal', function(){
    try {
      if (vjs) { vjs.pause(); }
      const el = document.getElementById('inline-player');
      if (el) { el.pause?.(); el.removeAttribute('src'); el.load?.(); }
    } catch (_) {}
  });

  // Wire for existing cards
  attachHandlers();
})();
