/*
 * BYS360 UX dalga 8 — ana sayfa: yüklenemeyen profil fotoğrafı yerine boş avatar.
 * Satır içi onerror yerine (CSP); portal/_experience_v2_hub.html'deki davranışın aynısı.
 */
(function () {
  'use strict';
  function fallback(img) {
    var cls = img.getAttribute('data-fallback-class');
    var parent = img.parentElement;
    img.remove();
    if (parent && cls) {
      parent.classList.add(cls);
    }
  }
  document.querySelectorAll('.home-page img[data-fallback-class]').forEach(function (img) {
    if (img.complete && img.naturalWidth === 0 && img.getAttribute('src')) {
      fallback(img);
      return;
    }
    img.addEventListener('error', function () { fallback(img); });
  });
})();
