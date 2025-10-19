document.addEventListener('DOMContentLoaded', function() {
  function initToggle(btnSel, inputSel, iconSel){
    const btn = document.querySelector(btnSel);
    const input = document.querySelector(inputSel);
    const icon = document.querySelector(iconSel);
    if (!btn || !input || !icon) return;
    btn.addEventListener('click', function(){
      const type = input.getAttribute('type') === 'password' ? 'text' : 'password';
      input.setAttribute('type', type);
      if (type === 'password') { icon.classList.remove('bi-eye-slash'); icon.classList.add('bi-eye'); }
      else { icon.classList.remove('bi-eye'); icon.classList.add('bi-eye-slash'); }
    });
  }
  initToggle('#togglePassword', '#password', '#togglePasswordIcon');
  initToggle('#togglePasswordConfirm', '#passwordConfirm', '#togglePasswordConfirmIcon');

  const passwordField = document.querySelector('#password');
  if (passwordField){
    passwordField.addEventListener('input', function(){
      const v = this.value || '';
      let strength = 0;
      if (v.length >= 8) strength++;
      if (/[a-z]/.test(v)) strength++;
      if (/[A-Z]/.test(v)) strength++;
      if (/[0-9]/.test(v)) strength++;
      if (/[^a-zA-Z0-9]/.test(v)) strength++;
      // Hook: update a strength meter if added in future
      // const meter = document.querySelector('#passwordStrength');
      // if (meter) meter.value = strength;
    });
  }
});
