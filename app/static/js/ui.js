// UI helpers: tooltips, popovers, and auto-hide alerts
(function(){
  if (typeof bootstrap === 'undefined') return;
  // Initialize tooltips
  var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
  // Initialize popovers
  var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
  popoverTriggerList.map(function (popoverTriggerEl) {
    return new bootstrap.Popover(popoverTriggerEl);
  });
  // Auto-hide flash alerts after 5 seconds (but NOT announcements, profile alerts, or wizard warnings)
  setTimeout(function() {
    var alerts = document.querySelectorAll('.alert:not([id^="announcement-"]):not(#profile-setup-alert):not(#twitch-warning):not(#discord-setup-alert)');
    alerts.forEach(function(alert) {
      try {
        var bsAlert = new bootstrap.Alert(alert);
        bsAlert.close();
      } catch (_) {}
    });
  }, 5000);
})();
