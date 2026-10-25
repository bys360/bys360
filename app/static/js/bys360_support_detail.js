/*
 * BYS360 Destek talep detayı: yapay zekâ ön değerlendirmesi (UX dalga 3, 2026-10).
 *
 * support/detail.html içindeki satır içi betiğin CSP uyumlu dış dosya hâli.
 * Uç nokta kartın data-triage-url özniteliğinden okunur; yanıt metin olarak
 * (textContent) yazılır, HTML olarak yorumlanmaz. Satır içi stil veya işleyici
 * kullanılmaz; durum yalnız sınıf ve aria-busy ile gösterilir.
 */
(function () {
  'use strict';

  var FALLBACK_ERROR = 'Ön değerlendirme alınamadı. Lütfen daha sonra yeniden deneyin.';

  function init() {
    var card = document.getElementById('ai-support-triage-card');
    var trigger = document.getElementById('ai-support-triage-trigger');
    var output = document.getElementById('ai-support-triage-output');
    var url = card ? card.getAttribute('data-triage-url') : '';
    if (!card || !trigger || !output || !url) {
      return;
    }

    function renderLines(value) {
      output.textContent = '';
      String(value || '-').split('\n').forEach(function (line) {
        if (!line.trim()) {
          return;
        }
        var row = document.createElement('p');
        row.className = 'bys-triage-output__line';
        row.textContent = line;
        output.appendChild(row);
      });
    }

    function setState(state) {
      card.classList.toggle('is-loading', state === 'loading');
      card.classList.toggle('is-error', state === 'error');
      card.classList.toggle('is-ready', state === 'ready');
      output.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
    }

    trigger.addEventListener('click', function () {
      trigger.disabled = true;
      setState('loading');
      output.textContent = 'Ön değerlendirme hazırlanıyor…';
      fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
        .then(function (resp) {
          return resp.json().catch(function () { return {}; }).then(function (data) {
            if (!resp.ok || !data || !data.ok) {
              var serverError = new Error((data && data.error) || FALLBACK_ERROR);
              serverError.fromServer = true;
              throw serverError;
            }
            return ((data.data || {}).summary) || '-';
          });
        })
        .then(function (summary) {
          renderLines(summary);
          setState('ready');
        })
        .catch(function (err) {
          // Ağ hatasında tarayıcının (İngilizce) iletisi gösterilmez.
          output.textContent = (err && err.fromServer && err.message) || FALLBACK_ERROR;
          setState('error');
        })
        .then(function () {
          trigger.disabled = false;
        });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
