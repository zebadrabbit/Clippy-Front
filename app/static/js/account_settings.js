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
});
