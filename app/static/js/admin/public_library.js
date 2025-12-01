/**
 * Public Library Admin Page - Edit and Delete functionality
 */

(function() {
  'use strict';

  // Get URL templates from config
  const cfg = document.getElementById('media-config');
  const UPDATE_URL_TPL = cfg?.dataset.updateUrlTemplate || '';
  const DELETE_URL_TPL = cfg?.dataset.deleteUrlTemplate || '';

  // API helper
  async function apiPost(url, formData) {
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: formData instanceof FormData ? {} : { 'Content-Type': 'application/json' },
        body: formData instanceof FormData ? formData : JSON.stringify(formData)
      });
      return await resp.json();
    } catch (err) {
      console.error('API error:', err);
      return { success: false, error: 'Network error' };
    }
  }

  // Toast helper
  const toastWrap = document.createElement('div');
  toastWrap.className = 'position-fixed';
  toastWrap.style.zIndex = '1080';
  toastWrap.style.right = '1rem';
  toastWrap.style.bottom = '1rem';
  document.body.appendChild(toastWrap);

  function showToast(message, type = 'dark') {
    const el = document.createElement('div');
    el.className = `toast align-items-center text-bg-${type} border-0 show`;
    el.setAttribute('role', 'alert');
    el.setAttribute('aria-live', 'assertive');
    el.setAttribute('aria-atomic', 'true');
    el.innerHTML = `<div class="d-flex"><div class="toast-body">${message}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>`;
    toastWrap.appendChild(el);
    const t = new bootstrap.Toast(el, { autohide: false });
    t.show();
    setTimeout(() => el.remove(), 3000);
  }

  // Edit modal
  const editModalEl = document.createElement('div');
  editModalEl.className = 'modal fade';
  editModalEl.tabIndex = -1;
  editModalEl.innerHTML = `
    <div class="modal-dialog modal-lg">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Edit Media</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body">
          <form id="media-edit-form">
            <input type="hidden" name="media_id" />

            <div class="row">
              <div class="col-md-6 mb-3">
                <label class="form-label">Name</label>
                <input type="text" class="form-control" name="original_filename" />
              </div>
              <div class="col-md-6 mb-3">
                <label class="form-label">Type</label>
                <select class="form-select" name="media_type">
                  <option value="intro">Intro</option>
                  <option value="outro">Outro</option>
                  <option value="transition">Transition</option>
                  <option value="music">Music</option>
                </select>
              </div>
            </div>

            <div class="mb-3">
              <label class="form-label">Tags</label>
              <input type="text" class="form-control" name="tags" placeholder="comma,separated,tags" />
              <div class="form-text">Use commas to separate tags.</div>
            </div>

            <hr class="my-4">
            <h6 class="mb-3">Attribution & Metadata <small class="text-muted">(for music/audio)</small></h6>

            <div class="row">
              <div class="col-md-6 mb-3">
                <label class="form-label">Artist</label>
                <input type="text" class="form-control" name="artist" placeholder="Artist or performer name" />
              </div>
              <div class="col-md-6 mb-3">
                <label class="form-label">Title</label>
                <input type="text" class="form-control" name="title" placeholder="Track or media title" />
              </div>
            </div>

            <div class="row">
              <div class="col-md-6 mb-3">
                <label class="form-label">Album</label>
                <input type="text" class="form-control" name="album" placeholder="Album name" />
              </div>
              <div class="col-md-6 mb-3">
                <label class="form-label">License</label>
                <input type="text" class="form-control" name="license" placeholder="CC-BY, CC0, etc." />
                <div class="form-text">E.g., "CC-BY 4.0", "CC0", "Public Domain"</div>
              </div>
            </div>

            <div class="mb-3">
              <label class="form-label">Attribution URL</label>
              <input type="url" class="form-control" name="attribution_url" placeholder="https://..." />
              <div class="form-text">Link to original source or artist page</div>
            </div>

            <div class="mb-3">
              <label class="form-label">Attribution Text</label>
              <textarea class="form-control" name="attribution_text" rows="2" placeholder="Required attribution or copyright notice"></textarea>
              <div class="form-text">Exact text required for attribution (if any)</div>
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

  let bsModal;
  function ensureBsModal() {
    if (!bsModal) bsModal = new bootstrap.Modal(editModalEl);
    return bsModal;
  }

  function openEditModal(opts) {
    const form = editModalEl.querySelector('#media-edit-form');
    form.media_id.value = opts.id || '';
    form.original_filename.value = opts.name || '';
    form.media_type.value = opts.type || '';
    form.tags.value = opts.tags || '';
    form.artist.value = opts.artist || '';
    form.album.value = opts.album || '';
    form.title.value = opts.title || '';
    form.license.value = opts.license || '';
    form.attribution_url.value = opts.attributionUrl || '';
    form.attribution_text.value = opts.attributionText || '';
    ensureBsModal().show();
  }

  // Save handler
  document.getElementById('media-edit-save').addEventListener('click', async function() {
    const form = editModalEl.querySelector('#media-edit-form');
    const id = form.media_id.value;
    const fd = new FormData(form);

    const resp = await apiPost(UPDATE_URL_TPL.replace('0', id), fd);

    if (resp && resp.success) {
      const card = document.querySelector(`.media-card[data-id="${id}"]`);
      if (card) {
        // Update card data attributes
        card.dataset.name = form.original_filename.value;
        card.dataset.type = form.media_type.value;
        card.dataset.tags = form.tags.value;
        card.dataset.artist = form.artist.value;
        card.dataset.album = form.album.value;
        card.dataset.title = form.title.value;
        card.dataset.license = form.license.value;
        card.dataset.attributionUrl = form.attribution_url.value;
        card.dataset.attributionText = form.attribution_text.value;

        // Update visible title
        const titleEl = card.querySelector('.card-title');
        if (titleEl) titleEl.textContent = form.original_filename.value;

        // Update badge
        const badge = card.querySelector('[data-role="type-badge"], .badge');
        if (badge) {
          const oldType = badge.className.match(/text-bg-(\w+)/)?.[1];
          if (oldType) badge.classList.remove(`text-bg-${oldType}`);
          badge.classList.add(`text-bg-${form.media_type.value}`);
          badge.textContent = form.media_type.value.charAt(0).toUpperCase() + form.media_type.value.slice(1);
        }
      }

      ensureBsModal().hide();
      showToast('Media updated successfully', 'success');
    } else {
      if (typeof showToast === 'function') {
        showToast((resp && resp.error) || 'Update failed', 'error');
      }
    }
  });

  // Delete handler
  document.getElementById('media-edit-delete').addEventListener('click', async function() {
    const form = editModalEl.querySelector('#media-edit-form');
    const id = form.media_id.value;

    if (!confirm('Delete this media item? This action cannot be undone.')) return;

    const resp = await apiPost(DELETE_URL_TPL.replace('0', id), {});

    if (resp && resp.success) {
      const card = document.querySelector(`.media-card[data-id="${id}"]`);
      if (card) card.closest('.col').remove();
      ensureBsModal().hide();
      showToast('Media deleted successfully', 'success');
    } else {
      if (typeof showToast === 'function') {
        showToast((resp && resp.error) || 'Delete failed', 'error');
      }
    }
  });

  // Attach edit button handlers
  function onEditClick(e) {
    const id = e.currentTarget.getAttribute('data-id');
    const card = document.querySelector(`.media-card[data-id="${id}"]`);

    openEditModal({
      id: id,
      name: card?.dataset.name || '',
      type: card?.dataset.type || '',
      tags: card?.dataset.tags || '',
      artist: card?.dataset.artist || '',
      album: card?.dataset.album || '',
      title: card?.dataset.title || '',
      license: card?.dataset.license || '',
      attributionUrl: card?.dataset.attributionUrl || '',
      attributionText: card?.dataset.attributionText || ''
    });
  }

  // Attach delete button handlers
  async function onDeleteClick(e) {
    const id = e.currentTarget.getAttribute('data-id');

    if (!confirm('Delete this media item? This action cannot be undone.')) return;

    const resp = await apiPost(DELETE_URL_TPL.replace('0', id), {});

    if (resp && resp.success) {
      const card = document.querySelector(`.media-card[data-id="${id}"]`);
      if (card) card.closest('.col').remove();
      showToast('Media deleted successfully', 'success');
    } else {
      if (typeof showToast === 'function') {
        showToast((resp && resp.error) || 'Delete failed', 'error');
      }
    }
  }

  // Initialize
  document.querySelectorAll('.media-edit').forEach(btn => {
    btn.addEventListener('click', onEditClick);
  });

  document.querySelectorAll('.media-delete').forEach(btn => {
    btn.addEventListener('click', onDeleteClick);
  });
})();
