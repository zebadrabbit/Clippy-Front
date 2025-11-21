// Notification system for real-time updates using Server-Sent Events (SSE)
(function() {
    'use strict';

    // Configuration
    const MAX_NOTIFICATIONS_DISPLAY = 10;
    const SSE_RECONNECT_INTERVAL = 5000; // 5 seconds

    // State
    let eventSource = null;
    let reconnectTimer = null;
    let unreadCount = 0;

    // DOM elements
    const badgeEl = document.getElementById('notifBadge');
    const listEl = document.getElementById('notificationsList');
    const markAllBtn = document.getElementById('markAllReadBtn');

    // Initialize SSE connection for real-time notifications
    function initSSE() {
        // Close existing connection if any
        if (eventSource) {
            eventSource.close();
        }

        try {
            eventSource = new EventSource('/api/notifications/stream');

            eventSource.onopen = function() {
                console.log('Notification stream connected');
                // Clear reconnect timer if set
                if (reconnectTimer) {
                    clearTimeout(reconnectTimer);
                    reconnectTimer = null;
                }
            };

            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);

                    // Handle connection confirmation
                    if (data.type === 'connected') {
                        console.log('Notifications stream ready');
                        // Fetch initial unread count
                        fetchUnreadCount();
                        return;
                    }

                    // Handle new notification
                    if (data.id) {
                        handleNewNotification(data);
                    }
                } catch (err) {
                    console.error('Error parsing notification:', err);
                }
            };

            eventSource.onerror = function(err) {
                console.error('SSE connection error:', err);
                eventSource.close();

                // Attempt to reconnect after delay
                if (!reconnectTimer) {
                    reconnectTimer = setTimeout(() => {
                        console.log('Attempting to reconnect notification stream...');
                        initSSE();
                    }, SSE_RECONNECT_INTERVAL);
                }
            };
        } catch (err) {
            console.error('Failed to initialize SSE:', err);
            // Fallback to polling if SSE fails
            fallbackToPolling();
        }
    }

    // Handle incoming notification
    function handleNewNotification(notification) {
        // Update unread count if notification is unread
        if (!notification.is_read) {
            fetchUnreadCount();
        }

        // Show browser notification if user has granted permission
        if ('Notification' in window && Notification.permission === 'granted') {
            showBrowserNotification(notification);
        }
    }

    // Show browser notification
    function showBrowserNotification(notif) {
        const icon = getNotificationIcon(notif.type);
        const notification = new Notification('ClippyFront', {
            body: notif.message,
            icon: `/static/img/icon-${icon}.png`, // Optional: add icons
            tag: `notif-${notif.id}`,
        });

        notification.onclick = function() {
            window.focus();
            notification.close();
            // Optionally navigate to related page
        };
    }

    // Fallback to polling if SSE is not supported or fails
    function fallbackToPolling() {
        console.warn('Falling back to polling for notifications');
        const POLL_INTERVAL = 30000; // 30 seconds

        fetchUnreadCount();
        setInterval(fetchUnreadCount, POLL_INTERVAL);
    }

    // Fetch unread count
    async function fetchUnreadCount() {
        try {
            const response = await fetch('/api/notifications/unread-count');
            if (!response.ok) return;

            const data = await response.json();
            updateBadge(data.count);
        } catch (err) {
            console.error('Failed to fetch unread count:', err);
        }
    }

    // Fetch recent notifications
    async function fetchNotifications() {
        try {
            const response = await fetch(`/api/notifications?limit=${MAX_NOTIFICATIONS_DISPLAY}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            displayNotifications(data.notifications);
            updateBadge(data.unread_count);
        } catch (err) {
            console.error('Failed to fetch notifications:', err);
            listEl.innerHTML = `
                <div class="px-3 py-2 text-danger small text-center">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    Failed to load notifications
                </div>
            `;
        }
    }

    // Update badge
    function updateBadge(count) {
        unreadCount = count;

        if (count > 0) {
            badgeEl.textContent = count > 99 ? '99+' : count;
            badgeEl.style.display = 'block';
        } else {
            badgeEl.style.display = 'none';
        }
    }

    // Display notifications
    function displayNotifications(notifications) {
        if (!notifications || notifications.length === 0) {
            listEl.innerHTML = `
                <div class="px-3 py-2 text-muted small text-center">
                    <i class="bi bi-inbox me-2"></i>
                    No notifications
                </div>
            `;
            return;
        }

        const html = notifications.map(notif => renderNotification(notif)).join('');
        listEl.innerHTML = html;

        // Attach click handlers for mark as read
        notifications.forEach(notif => {
            const el = document.getElementById(`notif-${notif.id}`);
            if (el && !notif.is_read) {
                el.addEventListener('click', () => markAsRead(notif.id));
            }
        });
    }

    // Render single notification
    function renderNotification(notif) {
        const isRead = notif.is_read;
        const bgClass = isRead ? 'bg-light' : 'bg-white';
        const icon = getNotificationIcon(notif.type);
        const time = formatTime(notif.created_at);

        let actorName = '';
        if (notif.actor) {
            actorName = notif.actor.username;
        }

        return `
            <li>
                <a class="dropdown-item ${bgClass} py-2 px-3" href="#" id="notif-${notif.id}" style="cursor: pointer;">
                    <div class="d-flex align-items-start">
                        <i class="bi bi-${icon} me-2 mt-1" style="font-size: 1.2rem;"></i>
                        <div class="flex-grow-1 small">
                            <div class="${isRead ? 'text-muted' : 'fw-bold'}">
                                ${escapeHtml(notif.message)}
                            </div>
                            <div class="text-muted mt-1" style="font-size: 0.75rem;">
                                ${time}
                                ${actorName ? ` &middot; by ${escapeHtml(actorName)}` : ''}
                            </div>
                        </div>
                        ${!isRead ? '<span class="badge bg-primary rounded-circle" style="width: 8px; height: 8px; padding: 0;"></span>' : ''}
                    </div>
                </a>
            </li>
        `;
    }

    // Get icon based on notification type
    function getNotificationIcon(type) {
        const icons = {
            'member_added': 'person-plus',
            'member_removed': 'person-dash',
            'member_role_changed': 'person-gear',
            'project_shared': 'folder-symlink',
            'compilation_completed': 'check-circle',
            'compilation_failed': 'exclamation-triangle',
            'team_created': 'people',
            'team_updated': 'pencil',
            'team_deleted': 'trash'
        };
        return icons[type] || 'bell';
    }

    // Format time relative to now
    function formatTime(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffSecs = Math.floor(diffMs / 1000);
        const diffMins = Math.floor(diffSecs / 60);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffSecs < 60) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;

        return date.toLocaleDateString();
    }

    // Escape HTML
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Mark notification as read
    async function markAsRead(notifId) {
        try {
            const response = await fetch(`/api/notifications/${notifId}/read`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                // Refresh notifications
                await fetchNotifications();
            }
        } catch (err) {
            console.error('Failed to mark notification as read:', err);
        }
    }

    // Mark all as read
    async function markAllAsRead() {
        if (unreadCount === 0) return;

        try {
            const response = await fetch('/api/notifications/read-all', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                await fetchNotifications();
            }
        } catch (err) {
            console.error('Failed to mark all as read:', err);
        }
    }

    // Request browser notification permission
    function requestNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission().then(permission => {
                console.log('Notification permission:', permission);
            });
        }
    }

    // Initialize
    function init() {
        // Check if user is authenticated (notification elements exist)
        if (!badgeEl || !listEl) return;

        // Initialize Server-Sent Events for real-time updates
        if (typeof EventSource !== 'undefined') {
            initSSE();
        } else {
            console.warn('EventSource not supported, falling back to polling');
            fallbackToPolling();
        }

        // Fetch notifications when dropdown is opened
        const dropdown = document.getElementById('notificationsDropdown');
        if (dropdown) {
            dropdown.addEventListener('show.bs.dropdown', fetchNotifications);
        }

        // Mark all as read button
        if (markAllBtn) {
            markAllBtn.addEventListener('click', (e) => {
                e.preventDefault();
                markAllAsRead();
            });
        }

        // Request browser notification permission (optional)
        // Uncomment to enable browser notifications
        // requestNotificationPermission();
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        if (eventSource) {
            eventSource.close();
        }
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
        }
    });
})();
