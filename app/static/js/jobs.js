// Lightweight notifications poller for background jobs and logs modal
(function(){
  const dropdown = document.getElementById('notificationsDropdown');
  if (!dropdown) return;
  const badge = document.getElementById('notifBadge');
  const menu = document.getElementById('notifMenu');
  let lastSeenIds = new Set();

  async function fetchJobs(){
    try {
      const recentUrl = document.body.dataset.recentJobsUrl;
      if (!recentUrl) return;
      const res = await fetch(recentUrl);
      if (!res.ok) return;
      const data = await res.json();
      const items = data.items || [];
      render(items);
    } catch (e) {
      // silent
    }
  }

  function render(items){
    dropdown.style.display = 'block';
    menu.innerHTML = '';
    const header = document.createElement('li');
    header.className = 'dropdown-header';
    header.textContent = 'Recent activity';
    menu.appendChild(header);
    menu.appendChild(document.createElement('li')).innerHTML = '<hr class="dropdown-divider">';

    if (!items.length){
      const empty = document.createElement('li');
      empty.className = 'px-3 py-2 text-muted small';
      empty.textContent = 'No recent jobs';
      menu.appendChild(empty);
      badge.style.display = 'none';
      return;
    }

    let unread = 0;
    items.forEach(j => {
      const li = document.createElement('li');
      const statusIcon = j.status === 'success' ? 'check-circle-fill text-success' : (j.status === 'failure' ? 'x-circle-fill text-danger' : 'hourglass-split text-warning');
      const proj = j.project_id ? ` · Project #${j.project_id}` : '';
      const title = `${(j.job_type || '').replace(/_/g, ' ')}${proj}`;
      const subtitle = j.last_log ? (j.last_log.message || j.last_log.status || '') : (j.error_message || '');
      const created = j.created_at ? new Date(j.created_at).toLocaleString() : '';
      li.innerHTML = `
        <a class="dropdown-item d-flex align-items-start gap-2" href="#" data-job-id="${j.id}" onclick="return window.showJobLogs(${j.id});">
          <i class="bi bi-${statusIcon} mt-1"></i>
          <div class="flex-grow-1">
            <div class="d-flex justify-content-between"><span>${title}</span><small class="text-muted">${j.progress || 0}%</small></div>
            <small class="text-muted">${subtitle || created}</small>
          </div>
        </a>`;
      menu.appendChild(li);
      if (!lastSeenIds.has(j.id) && (j.status === 'success' || j.status === 'failure')) unread++;
    });
    if (unread > 0){
      badge.textContent = unread.toString();
      badge.style.display = 'inline-block';
    } else {
      badge.style.display = 'none';
    }
    lastSeenIds = new Set(items.map(i => i.id));
  }

  // Expose a tiny helper to open logs modal
  window.showJobLogs = async function(jobId){
    try {
      const baseDetails = document.body.dataset.jobDetailsUrlTemplate;
      if (!baseDetails) return false;
      const url = baseDetails.replace(/\/0$/, '/' + jobId);
      const res = await fetch(url);
      if (!res.ok) return false;
      const data = await res.json();
      const modalEl = document.getElementById('jobLogsModal');
      if (!modalEl) return false;
      modalEl.querySelector('.modal-title').textContent = `${data.job_type} · ${data.project_name || ('Project #' + (data.project_id || ''))}`;
      const pre = modalEl.querySelector('pre');
      const logs = (data.result_data && data.result_data.logs) || [];
      pre.textContent = logs.map(l => {
        const ts = l.ts ? new Date(l.ts).toLocaleString() : '';
        const lvl = l.level ? `[${l.level.toUpperCase()}]` : '';
        const status = l.status ? `(${l.status})` : '';
        return `${ts} ${lvl} ${l.message || ''} ${status}`.trim();
      }).join('\n');
      const modal = new bootstrap.Modal(modalEl);
      modal.show();
    } catch (e) {}
    return false;
  }

  // Poll periodically
  if (document.body.dataset.recentJobsUrl){
    fetchJobs();
    setInterval(fetchJobs, 5000);
  }
})();
