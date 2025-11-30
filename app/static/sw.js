/**
 * Service Worker for ClippyFront
 * Handles push notifications and offline functionality
 */

const CACHE_VERSION = 'v1';
const CACHE_NAME = `clippy-${CACHE_VERSION}`;

// Install service worker
self.addEventListener('install', (event) => {
  console.log('[SW] Installing service worker');
  self.skipWaiting();
});

// Activate service worker
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating service worker');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
  return self.clients.claim();
});

// Handle push notifications
self.addEventListener('push', (event) => {
  console.log('[SW] Push received:', event);

  let data = {
    title: 'ClippyFront Notification',
    body: 'You have a new notification',
    icon: '/static/img/logo.png',
    badge: '/static/img/badge.png',
    tag: 'clippy-notification',
    requireInteraction: false
  };

  if (event.data) {
    try {
      const payload = event.data.json();
      data = {
        ...data,
        ...payload,
        // Ensure we have required fields
        title: payload.title || data.title,
        body: payload.body || payload.message || data.body,
        icon: payload.icon || data.icon,
        badge: payload.badge || data.badge,
        tag: payload.tag || `notification-${payload.id || Date.now()}`,
        data: payload.data || {}
      };
    } catch (e) {
      console.error('[SW] Failed to parse push data:', e);
      data.body = event.data.text();
    }
  }

  const promiseChain = self.registration.showNotification(data.title, {
    body: data.body,
    icon: data.icon,
    badge: data.badge,
    tag: data.tag,
    requireInteraction: data.requireInteraction,
    data: data.data,
    actions: data.actions || []
  });

  event.waitUntil(promiseChain);
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
  console.log('[SW] Notification clicked:', event);

  event.notification.close();

  // Determine URL to open
  let url = '/notifications';

  if (event.notification.data) {
    const { type, project_id, team_id } = event.notification.data;

    if (type === 'COMPILATION_COMPLETED' || type === 'COMPILATION_FAILED') {
      if (project_id) {
        url = `/projects/${project_id}`;
      }
    } else if (type === 'PROJECT_SHARED') {
      if (project_id) {
        url = `/projects/${project_id}`;
      }
    } else if (type === 'MEMBER_ADDED') {
      if (team_id) {
        url = `/teams/${team_id}`;
      }
    } else if (type === 'INVITATION_RECEIVED') {
      url = '/invitations';
    }
  }

  // Open or focus the app
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Check if there's already a window open
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      // Otherwise, open a new window
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});

// Handle notification close
self.addEventListener('notificationclose', (event) => {
  console.log('[SW] Notification closed:', event);
  // Could track analytics here
});
