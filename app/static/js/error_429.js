document.addEventListener('DOMContentLoaded', function() {
  var countdown = 10;
  var retryBtn = document.getElementById('retryBtn');
  var retryText = document.getElementById('retryText');
  var cooldownBar = document.getElementById('cooldownBar');

  var timer = setInterval(function() {
    countdown--;
    retryText.textContent = 'Retry in ' + countdown + 's';

    var percentage = (countdown / 10) * 100;
    cooldownBar.style.width = percentage + '%';

    if (countdown <= 0) {
      clearInterval(timer);
      retryBtn.disabled = false;
      retryText.textContent = 'Retry Now';
      cooldownBar.style.width = '0%';
      cooldownBar.classList.remove('progress-bar-animated');
    }
  }, 1000);
});
