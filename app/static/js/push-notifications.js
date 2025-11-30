/**
 * Push Notification Manager
 * Handles browser push notification subscription and management
 */

(function() {
  'use strict';

  // Check if push notifications are supported
  const isPushSupported = 'serviceWorker' in navigator && 'PushManager' in window;

  // VAPID public key (needs to be generated and configured)
  // To generate: python -c "from py_vapid import Vapid; vapid = Vapid(); vapid.generate_keys(); print('Public:', vapid.public_key.decode()); print('Private:', vapid.private_key.decode())"
  const VAPID_PUBLIC_KEY = window.VAPID_PUBLIC_KEY || null;

  /**
   * Initialize push notifications
   */
  async function init() {
    if (!isPushSupported) {
      console.log('[Push] Push notifications not supported');
      return;
    }

    try {
      // Register service worker
      const registration = await navigator.serviceWorker.register('/static/sw.js');
      console.log('[Push] Service worker registered:', registration);

      // Check current subscription status
      const subscription = await registration.pushManager.getSubscription();
      updateUI(subscription);

      // Set up event listeners
      setupEventListeners(registration);
    } catch (error) {
      console.error('[Push] Service worker registration failed:', error);
    }
  }

  /**
   * Setup event listeners for push notification controls
   */
  function setupEventListeners(registration) {
    const enableBtn = document.getElementById('enable-push-notifications');
    const disableBtn = document.getElementById('disable-push-notifications');

    if (enableBtn) {
      enableBtn.addEventListener('click', () => subscribeToPush(registration));
    }

    if (disableBtn) {
      disableBtn.addEventListener('click', () => unsubscribeFromPush(registration));
    }
  }

  /**
   * Subscribe to push notifications
   */
  async function subscribeToPush(registration) {
    if (!VAPID_PUBLIC_KEY) {
      console.error('[Push] VAPID public key not configured');
      alert('Push notifications are not configured on this server.');
      return;
    }

    try {
      // Request notification permission
      const permission = await Notification.requestPermission();

      if (permission !== 'granted') {
        console.log('[Push] Notification permission denied');
        alert('Please allow notifications to enable push notifications.');
        return;
      }

      // Subscribe to push
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
      });

      console.log('[Push] Subscribed to push:', subscription);

      // Send subscription to server
      await sendSubscriptionToServer(subscription);

      updateUI(subscription);
      showToast('Push notifications enabled!', 'success');
    } catch (error) {
      console.error('[Push] Failed to subscribe:', error);
      alert('Failed to enable push notifications. Please try again.');
    }
  }

  /**
   * Unsubscribe from push notifications
   */
  async function unsubscribeFromPush(registration) {
    try {
      const subscription = await registration.pushManager.getSubscription();

      if (subscription) {
        await subscription.unsubscribe();
        console.log('[Push] Unsubscribed from push');

        // Remove subscription from server
        await removeSubscriptionFromServer(subscription);

        updateUI(null);
        showToast('Push notifications disabled', 'info');
      }
    } catch (error) {
      console.error('[Push] Failed to unsubscribe:', error);
      alert('Failed to disable push notifications. Please try again.');
    }
  }

  /**
   * Send subscription to server
   */
  async function sendSubscriptionToServer(subscription) {
    const response = await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(subscription.toJSON())
    });

    if (!response.ok) {
      throw new Error('Failed to save subscription on server');
    }

    return response.json();
  }

  /**
   * Remove subscription from server
   */
  async function removeSubscriptionFromServer(subscription) {
    const response = await fetch('/api/push/unsubscribe', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(subscription.toJSON())
    });

    if (!response.ok) {
      throw new Error('Failed to remove subscription from server');
    }

    return response.json();
  }

  /**
   * Update UI based on subscription status
   */
  function updateUI(subscription) {
    const enableBtn = document.getElementById('enable-push-notifications');
    const disableBtn = document.getElementById('disable-push-notifications');
    const statusEl = document.getElementById('push-status');

    if (!enableBtn || !disableBtn) {
      return;
    }

    if (subscription) {
      enableBtn.style.display = 'none';
      disableBtn.style.display = 'inline-block';
      if (statusEl) {
        statusEl.textContent = 'Enabled';
        statusEl.className = 'badge bg-success';
      }
    } else {
      enableBtn.style.display = 'inline-block';
      disableBtn.style.display = 'none';
      if (statusEl) {
        statusEl.textContent = 'Disabled';
        statusEl.className = 'badge bg-secondary';
      }
    }
  }

  /**
   * Convert VAPID key from base64 to Uint8Array
   */
  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
      .replace(/\-/g, '+')
      .replace(/_/g, '/');

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  /**
   * Show toast notification
   */
  function showToast(message, type = 'info') {
    // Create toast element
    const toast = document.createElement('div');
    const bgClass = type === 'success' ? 'bg-success' : type === 'danger' ? 'bg-danger' : 'bg-info';

    toast.className = `toast text-bg-${type === 'success' ? 'success' : type === 'danger' ? 'danger' : 'info'} border-0 mb-2`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');

    toast.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;

    // Add to container
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'position-fixed bottom-0 end-0 p-3';
      container.style.zIndex = '1080';
      document.body.appendChild(container);
    }
    container.appendChild(toast);

    // Show toast
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();

    // Remove from DOM after hidden
    toast.addEventListener('hidden.bs.toast', () => {
      toast.remove();
    });
  }

  // Auto-initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose public API
  window.PushNotifications = {
    init,
    subscribe: subscribeToPush,
    unsubscribe: unsubscribeFromPush,
    isSupported: isPushSupported
  };
})();
