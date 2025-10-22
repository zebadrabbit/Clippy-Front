(function(){
  try {
    document.querySelectorAll('.toast').forEach(function(el){
      var inst = bootstrap.Toast.getOrCreateInstance(el);
      inst.show();
    });
  } catch (e) { /* no-op */ }
})();
