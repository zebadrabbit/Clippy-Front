(function(){
  function normalizeHex(val){
    if (!val) return null;
    var s = String(val).trim();
    if (s[0] !== '#') s = '#' + s;
    var m3 = /^#([0-9a-fA-F]{3})$/;
    var m6 = /^#([0-9a-fA-F]{6})$/;
    if (m6.test(s)) return s.toLowerCase();
    var m = s.match(m3);
    if (m){
      var c = m[1];
      return ('#' + c[0]+c[0] + c[1]+c[1] + c[2]+c[2]).toLowerCase();
    }
    return null;
  }
  function bindSync(row){
    var text = row.querySelector('.color-text-input');
    var colorName = text && text.getAttribute('data-target-name');
    var color = colorName && document.getElementById('color-' + colorName);
    if (!text || !color) return;
    text.addEventListener('input', function(){
      var norm = normalizeHex(text.value);
      if (norm){
        color.value = norm;
        text.classList.remove('is-invalid');
      } else {
        text.classList.add('is-invalid');
      }
    });
    color.addEventListener('input', function(){
      text.value = color.value;
      text.classList.remove('is-invalid');
    });
  }
  try {
    document.querySelectorAll('.card .card-header + .card-body .row.align-items-center').forEach(bindSync);
  } catch (e) { /* no-op */ }
})();
