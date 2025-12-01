document.addEventListener('DOMContentLoaded', function() {
  // Password confirmation validation
  const newPassword = document.getElementById('newPassword');
  const confirmPassword = document.getElementById('confirmPassword');
  function validatePasswords() {
    if (!newPassword || !confirmPassword) return;
    if (newPassword.value !== confirmPassword.value) {
      confirmPassword.setCustomValidity("Passwords don't match");
    } else {
      confirmPassword.setCustomValidity('');
    }
  }
  if (newPassword) newPassword.addEventListener('input', validatePasswords);
  if (confirmPassword) confirmPassword.addEventListener('input', validatePasswords);

  // Username confirmation for account deletion
  const cfgEl = document.getElementById('account-settings-config');
  let expectedUsername = '';
  if (cfgEl) { try { const cfg = JSON.parse(cfgEl.textContent || '{}'); expectedUsername = cfg.expectedUsername || ''; } catch(_){} }
  const confirmUsername = document.getElementById('confirmUsername');
  const deleteAccountBtn = document.getElementById('deleteAccountBtn');
  if (confirmUsername && deleteAccountBtn) {
    confirmUsername.addEventListener('input', function() {
      deleteAccountBtn.disabled = (this.value !== expectedUsername);
    });
  }

  // Resend verification email handler
  const resendBtn = document.getElementById('resendVerificationBtn');
  if (resendBtn) {
    resendBtn.addEventListener('click', function() {
      const btn = this;
      const originalHTML = btn.innerHTML;

      // Disable button and show loading state
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Sending...';

      fetch('/auth/resend-verification', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin'
      })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          // Show success message
          if (typeof showToast === 'function') {
            showToast('Verification email sent! Please check your inbox.', 'success');
          }
          // Update button state
          btn.innerHTML = '<i class="bi bi-check"></i> Email Sent';
          btn.className = 'btn btn-sm btn-success ms-2';

          // Re-enable after 5 seconds
          setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
            btn.className = 'btn btn-sm btn-outline-warning ms-2';
          }, 5000);
        } else {
          throw new Error(data.error || 'Failed to send email');
        }
      })
      .catch(error => {
        console.error('Error:', error);
        // Show error toast
        if (typeof showToast === 'function') {
          showToast('Failed to send verification email. Please try again.', 'error');
        }
        // Reset button
        btn.disabled = false;
        btn.innerHTML = originalHTML;
      });
    });
  }
});
