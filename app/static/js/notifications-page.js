/**
 * Notifications Page JavaScript
 * Handles filtering, pagination, bulk actions, and AJAX updates
 */

(function() {
  'use strict';

  // State
  const state = {
    currentPage: 1,
    perPage: 20,
    filters: {
      type: 'all',
      status: 'all',
      dateRange: 'week'
    },
    selectedIds: new Set(),
    totalCount: 0
  };

  // DOM Elements
  const elements = {
    notificationsList: document.getElementById('notificationsList'),
    loadingState: document.getElementById('loadingState'),
    emptyState: document.getElementById('emptyState'),
    paginationContainer: document.getElementById('paginationContainer'),
    paginationInfo: document.getElementById('paginationInfo'),
    pagination: document.getElementById('pagination'),
    typeFilters: document.querySelectorAll('#typeFilters .filter-chip'),
    statusFilters: document.querySelectorAll('#statusFilters .filter-chip'),
    dateRangeSelect: document.getElementById('dateRange'),
    selectAllBtn: document.getElementById('selectAllBtn'),
    bulkMarkReadBtn: document.getElementById('bulkMarkReadBtn'),
    bulkDeleteBtn: document.getElementById('bulkDeleteBtn')
  };

  /**
   * Initialize the page
   */
  function init() {
    setupEventListeners();
    loadNotifications();
  }

  /**
   * Setup event listeners
   */
  function setupEventListeners() {
    // Type filters
    elements.typeFilters.forEach(chip => {
      chip.addEventListener('click', () => {
        elements.typeFilters.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        state.filters.type = chip.dataset.type;
        state.currentPage = 1;
        loadNotifications();
      });
    });

    // Status filters
    elements.statusFilters.forEach(chip => {
      chip.addEventListener('click', () => {
        elements.statusFilters.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        state.filters.status = chip.dataset.status;
        state.currentPage = 1;
        loadNotifications();
      });
    });

    // Date range
    elements.dateRangeSelect.addEventListener('change', (e) => {
      state.filters.dateRange = e.target.value;
      state.currentPage = 1;
      loadNotifications();
    });

    // Bulk actions
    elements.selectAllBtn.addEventListener('click', toggleSelectAll);
    elements.bulkMarkReadBtn.addEventListener('click', bulkMarkRead);
    elements.bulkDeleteBtn.addEventListener('click', bulkDelete);
  }

  /**
   * Load notifications from API
   */
  async function loadNotifications() {
    showLoading();

    const params = new URLSearchParams({
      limit: state.perPage,
      offset: (state.currentPage - 1) * state.perPage
    });

    if (state.filters.type !== 'all') {
      params.append('type', state.filters.type);
    }

    if (state.filters.status === 'unread') {
      params.append('unread_only', 'true');
    } else if (state.filters.status === 'read') {
      params.append('unread_only', 'false');
    }

    if (state.filters.dateRange !== 'all') {
      params.append('date_range', state.filters.dateRange);
    }

    try {
      const response = await fetch(`/api/notifications?${params}`);
      const data = await response.json();

      if (data.error) {
        showError(data.error);
        return;
      }

      state.totalCount = data.filtered_count || 0;
      renderNotifications(data.notifications);
      renderPagination();
    } catch (error) {
      console.error('Failed to load notifications:', error);
      showError('Failed to load notifications. Please try again.');
    }
  }

  /**
   * Render notifications list
   */
  function renderNotifications(notifications) {
    if (!notifications || notifications.length === 0) {
      showEmpty();
      return;
    }

    elements.loadingState.classList.add('d-none');
    elements.emptyState.classList.add('d-none');
    elements.notificationsList.classList.remove('d-none');

    const html = notifications.map(notification => {
      const actionButtons = getActionButtons(notification);

      return `
      <div class="notification-item p-3 border-bottom ${notification.is_read ? '' : 'unread'}" data-id="${notification.id}">
        <div class="d-flex align-items-start gap-3">
          <input type="checkbox" class="form-check-input notification-checkbox mt-1" data-id="${notification.id}">
          <div class="flex-grow-1">
            <div class="d-flex align-items-start justify-content-between">
              <div>
                ${getNotificationIcon(notification.type)}
                <strong>${escapeHtml(notification.message)}</strong>
                ${notification.is_read ? '' : '<span class="badge bg-primary ms-2">New</span>'}
              </div>
              <small class="text-muted">${formatDate(notification.created_at)}</small>
            </div>
            ${notification.context && notification.context.project_name ? `
              <small class="text-muted d-block mt-1">
                <i class="bi bi-folder"></i> ${escapeHtml(notification.context.project_name)}
              </small>
            ` : ''}
            ${notification.project ? `
              <small class="text-muted d-block mt-1">
                <i class="bi bi-folder"></i> ${escapeHtml(notification.project.name)}
              </small>
            ` : ''}
            ${notification.team ? `
              <small class="text-muted d-block mt-1">
                <i class="bi bi-people"></i> ${escapeHtml(notification.team.name)}
              </small>
            ` : ''}
            <div class="mt-2 d-flex gap-2 flex-wrap">
              ${actionButtons}
              ${!notification.is_read ? `
                <button class="btn btn-sm btn-outline-primary mark-read-btn" data-id="${notification.id}">
                  <i class="bi bi-eye"></i> Mark Read
                </button>
              ` : ''}
              <button class="btn btn-sm btn-outline-danger delete-btn" data-id="${notification.id}">
                <i class="bi bi-trash"></i> Delete
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
    }).join('');

    elements.notificationsList.innerHTML = html;

    // Add event listeners to action buttons
    elements.notificationsList.querySelectorAll('.mark-read-btn').forEach(btn => {
      btn.addEventListener('click', () => markAsRead(parseInt(btn.dataset.id)));
    });

    elements.notificationsList.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', () => deleteNotification(parseInt(btn.dataset.id)));
    });

    elements.notificationsList.querySelectorAll('.notification-checkbox').forEach(checkbox => {
      checkbox.addEventListener('change', updateBulkActions);
    });
  }

  /**
   * Render pagination
   */
  function renderPagination() {
    const totalPages = Math.ceil(state.totalCount / state.perPage);

    if (totalPages <= 1) {
      elements.paginationContainer.style.display = 'none';
      return;
    }

    elements.paginationContainer.style.display = 'block';

    // Info text
    const start = (state.currentPage - 1) * state.perPage + 1;
    const end = Math.min(state.currentPage * state.perPage, state.totalCount);
    elements.paginationInfo.textContent = `Showing ${start}-${end} of ${state.totalCount}`;

    // Pagination buttons
    let paginationHTML = '';

    // Previous button
    paginationHTML += `
      <li class="page-item ${state.currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${state.currentPage - 1}">Previous</a>
      </li>
    `;

    // Page numbers
    const maxButtons = 5;
    let startPage = Math.max(1, state.currentPage - Math.floor(maxButtons / 2));
    let endPage = Math.min(totalPages, startPage + maxButtons - 1);

    if (endPage - startPage < maxButtons - 1) {
      startPage = Math.max(1, endPage - maxButtons + 1);
    }

    if (startPage > 1) {
      paginationHTML += `<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`;
      if (startPage > 2) {
        paginationHTML += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
      }
    }

    for (let i = startPage; i <= endPage; i++) {
      paginationHTML += `
        <li class="page-item ${i === state.currentPage ? 'active' : ''}">
          <a class="page-link" href="#" data-page="${i}">${i}</a>
        </li>
      `;
    }

    if (endPage < totalPages) {
      if (endPage < totalPages - 1) {
        paginationHTML += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
      }
      paginationHTML += `<li class="page-item"><a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a></li>`;
    }

    // Next button
    paginationHTML += `
      <li class="page-item ${state.currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${state.currentPage + 1}">Next</a>
      </li>
    `;

    elements.pagination.innerHTML = paginationHTML;

    // Add click listeners
    elements.pagination.querySelectorAll('a.page-link').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const page = parseInt(link.dataset.page);
        if (page && page !== state.currentPage && page >= 1 && page <= totalPages) {
          state.currentPage = page;
          loadNotifications();
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
      });
    });
  }

  /**
   * Mark single notification as read
   */
  async function markAsRead(id) {
    try {
      const response = await fetch(`/api/notifications/${id}/read`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });

      if (response.ok) {
        loadNotifications();
      }
    } catch (error) {
      console.error('Failed to mark as read:', error);
    }
  }

  /**
   * Delete single notification
   */
  async function deleteNotification(id) {
    if (!confirm('Are you sure you want to delete this notification?')) {
      return;
    }

    try {
      const response = await fetch('/api/notifications/bulk-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [id] })
      });

      if (response.ok) {
        loadNotifications();
      }
    } catch (error) {
      console.error('Failed to delete notification:', error);
    }
  }

  /**
   * Toggle select all checkboxes
   */
  function toggleSelectAll() {
    const checkboxes = elements.notificationsList.querySelectorAll('.notification-checkbox');
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);

    checkboxes.forEach(cb => {
      cb.checked = !allChecked;
    });

    updateBulkActions();
  }

  /**
   * Update bulk action button states
   */
  function updateBulkActions() {
    const checkboxes = Array.from(elements.notificationsList.querySelectorAll('.notification-checkbox:checked'));
    state.selectedIds = new Set(checkboxes.map(cb => parseInt(cb.dataset.id)));

    const hasSelection = state.selectedIds.size > 0;
    elements.bulkMarkReadBtn.disabled = !hasSelection;
    elements.bulkDeleteBtn.disabled = !hasSelection;

    if (hasSelection) {
      elements.selectAllBtn.innerHTML = '<i class="bi bi-x-square"></i> Deselect All';
    } else {
      elements.selectAllBtn.innerHTML = '<i class="bi bi-check2-square"></i> Select All';
    }
  }

  /**
   * Bulk mark as read
   */
  async function bulkMarkRead() {
    if (state.selectedIds.size === 0) return;

    try {
      const response = await fetch('/api/notifications/bulk-mark-read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(state.selectedIds) })
      });

      if (response.ok) {
        state.selectedIds.clear();
        loadNotifications();
      }
    } catch (error) {
      console.error('Failed to bulk mark read:', error);
    }
  }

  /**
   * Bulk delete
   */
  async function bulkDelete() {
    if (state.selectedIds.size === 0) return;

    if (!confirm(`Are you sure you want to delete ${state.selectedIds.size} notification(s)?`)) {
      return;
    }

    try {
      const response = await fetch('/api/notifications/bulk-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(state.selectedIds) })
      });

      if (response.ok) {
        state.selectedIds.clear();
        loadNotifications();
      }
    } catch (error) {
      console.error('Failed to bulk delete:', error);
    }
  }

  /**
   * Show loading state
   */
  function showLoading() {
    elements.loadingState.classList.remove('d-none');
    elements.emptyState.classList.add('d-none');
    elements.notificationsList.classList.add('d-none');
  }

  /**
   * Show empty state
   */
  function showEmpty() {
    elements.loadingState.classList.add('d-none');
    elements.emptyState.classList.remove('d-none');
    elements.notificationsList.classList.add('d-none');
    elements.paginationContainer.style.display = 'none';
  }

  /**
   * Show error message
   */
  function showError(message) {
    elements.loadingState.classList.add('d-none');
    elements.emptyState.classList.remove('d-none');
    elements.emptyState.innerHTML = `
      <i class="bi bi-exclamation-triangle display-1 text-danger"></i>
      <p class="mt-3 text-danger">${escapeHtml(message)}</p>
    `;
  }

  /**
   * Get icon for notification type
   */
  function getNotificationIcon(type) {
    const icons = {
      COMPILATION_COMPLETED: '<i class="bi bi-check-circle text-success"></i>',
      COMPILATION_FAILED: '<i class="bi bi-x-circle text-danger"></i>',
      MEMBER_ADDED: '<i class="bi bi-person-plus text-primary"></i>',
      PROJECT_SHARED: '<i class="bi bi-share text-info"></i>',
      INVITATION_RECEIVED: '<i class="bi bi-envelope text-warning"></i>'
    };
    return icons[type] || '<i class="bi bi-bell"></i>';
  }

  /**
   * Get contextual action buttons for notification
   */
  function getActionButtons(notification) {
    const buttons = [];

    // Compilation completed/failed - link to project
    if ((notification.type === 'COMPILATION_COMPLETED' || notification.type === 'COMPILATION_FAILED') && notification.project) {
      buttons.push(`
        <a href="/projects/${notification.project.id}" class="btn btn-sm btn-primary">
          <i class="bi bi-folder-open"></i> View Project
        </a>
      `);
    }

    // Project shared - link to project
    if (notification.type === 'PROJECT_SHARED' && notification.project) {
      buttons.push(`
        <a href="/projects/${notification.project.id}" class="btn btn-sm btn-primary">
          <i class="bi bi-eye"></i> See Details
        </a>
      `);
    }

    // Member added - link to team
    if (notification.type === 'MEMBER_ADDED' && notification.team) {
      buttons.push(`
        <a href="/teams/${notification.team.id}" class="btn btn-sm btn-primary">
          <i class="bi bi-people"></i> Go to Team
        </a>
      `);
    }

    // Invitation received - link to invitations page
    if (notification.type === 'INVITATION_RECEIVED') {
      buttons.push(`
        <a href="/invitations" class="btn btn-sm btn-success">
          <i class="bi bi-envelope-check"></i> View Invitation
        </a>
      `);
    }

    return buttons.join('');
  }

  /**
   * Format date for display
   */
  function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;

    // Less than 1 minute
    if (diff < 60000) {
      return 'Just now';
    }

    // Less than 1 hour
    if (diff < 3600000) {
      const minutes = Math.floor(diff / 60000);
      return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
    }

    // Less than 24 hours
    if (diff < 86400000) {
      const hours = Math.floor(diff / 3600000);
      return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    }

    // Less than 7 days
    if (diff < 604800000) {
      const days = Math.floor(diff / 86400000);
      return `${days} day${days > 1 ? 's' : ''} ago`;
    }

    // Default to formatted date
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
    });
  }

  /**
   * Escape HTML to prevent XSS
   */
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
