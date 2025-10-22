document.addEventListener('DOMContentLoaded', function() {
  const togglePassword = document.querySelector('#togglePassword');
  const password = document.querySelector('#password');
  const togglePasswordIcon = document.querySelector('#togglePasswordIcon');
  if (!togglePassword || !password || !togglePasswordIcon) return;
  togglePassword.addEventListener('click', function () {
    const type = password.getAttribute('type') === 'password' ? 'text' : 'password';
    password.setAttribute('type', type);
    if (type === 'password') {
      togglePasswordIcon.classList.remove('bi-eye-slash');
      togglePasswordIcon.classList.add('bi-eye');
    } else {
      togglePasswordIcon.classList.remove('bi-eye');
      togglePasswordIcon.classList.add('bi-eye-slash');
    }
  });
});
