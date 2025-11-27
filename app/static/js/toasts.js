/**
 * Toast notification system
 * Compatible with Bootstrap 5 toast component
 */

// Show existing toasts on page load
(function(){
  try {
    document.querySelectorAll('.toast').forEach(function(el){
      var inst = bootstrap.Toast.getOrCreateInstance(el);
      inst.show();
    });
  } catch (e) { /* no-op */ }
})();

/**
 * Show a toast notification
 * @param {string} message - The message to display
 * @param {string} type - Toast type: 'success', 'danger', 'warning', 'info', 'primary'
 * @param {number} delay - Auto-hide delay in ms (default: 5000, 0 = no auto-hide)
 */
window.showToast = function(message, type = 'info', delay = 5000) {
  const container = document.getElementById('toast-container');
  if (!container) {
    console.warn('Toast container not found');
    return;
  }

  // Map types to Bootstrap background classes
  const bgClass = {
    success: 'success',
    danger: 'danger',
    warning: 'warning',
    info: 'info',
    primary: 'primary',
    error: 'danger' // alias
  }[type] || 'info';

  // Create toast element
  const toastId = 'toast-' + Date.now();
  const toastHtml = `
    <div id="${toastId}" class="toast text-bg-${bgClass} border-0 mb-2" role="alert" aria-live="assertive" aria-atomic="true" data-bs-autohide="${delay > 0}" data-bs-delay="${delay}">
      <div class="d-flex align-items-center">
        <div class="toast-body">
          ${message}
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    </div>
  `;

  // Add to container
  container.insertAdjacentHTML('beforeend', toastHtml);

  // Get toast element and show it
  const toastElement = document.getElementById(toastId);
  const toast = new bootstrap.Toast(toastElement);
  toast.show();

  // Remove from DOM after hidden
  toastElement.addEventListener('hidden.bs.toast', () => {
    toastElement.remove();
  });

  return toast;
};
