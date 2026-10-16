/*
 * BYS360 erişilebilir form davranışları (UX pilotu, 2026-10).
 *
 * - Sunucu doğrulama hatasıyla dönen sayfada odağı hata özetine taşır
 *   (#bysErrorSummary, tabindex="-1").
 * - Hata özetindeki bağlantılar ilgili alana odaklar.
 * - Geçerli bir gönderimde gönderim düğmesini devre dışı bırakır ve
 *   "Kaydediliyor…" yazar (çift gönderimi önler); tarayıcı geri tuşuyla
 *   dönüldüğünde düğmeyi yeniden etkinleştirir.
 *
 * - Dosya bırakma bölgesi: seçilen dosyanın adını gösterir, sürükleme
 *   sırasında bölgeyi vurgular. Gerçek dosya girdisi değişmez.
 * - data-bys-counter taşıyan metin alanının altına görsel karakter sayacı
 *   ekler (ekran okuyucudan gizli; sınır yardım metninde yazılıdır).
 *
 * JavaScript kapalıysa form ve hata özeti yine çalışır. Satır içi işleyici
 * kullanılmaz (CSP). Yalnız support/new.html bu dosyayı yükler.
 */
(function () {
  'use strict';

  function focusSummary() {
    var summary = document.getElementById('bysErrorSummary');
    if (!summary) {
      return;
    }
    summary.focus();
  }

  function bindSummaryLinks() {
    var links = document.querySelectorAll('#bysErrorSummary [data-bys-focus-target]');
    Array.prototype.forEach.call(links, function (link) {
      link.addEventListener('click', function (event) {
        var target = document.getElementById(link.getAttribute('data-bys-focus-target'));
        if (!target) {
          return;
        }
        event.preventDefault();
        target.focus();
        if (typeof target.scrollIntoView === 'function') {
          target.scrollIntoView({ block: 'center' });
        }
      });
    });
  }

  function bindSubmitGuard() {
    var forms = document.querySelectorAll('form[data-bys-submit-guard]');
    Array.prototype.forEach.call(forms, function (form) {
      var button = form.querySelector('[data-bys-submit-button]');
      if (!button) {
        return;
      }
      var label = button.querySelector('[data-bys-submit-label]');
      var defaultText = label ? label.textContent : '';
      var busyText = button.getAttribute('data-bys-busy-text') || 'Kaydediliyor…';

      form.addEventListener('submit', function (event) {
        if (event.defaultPrevented) {
          return;
        }
        if (typeof form.checkValidity === 'function' && !form.checkValidity()) {
          return;
        }
        if (button.getAttribute('aria-disabled') === 'true') {
          event.preventDefault();
          return;
        }
        button.setAttribute('aria-disabled', 'true');
        if (label) {
          label.textContent = busyText;
        }
      });

      window.addEventListener('pageshow', function () {
        button.removeAttribute('aria-disabled');
        if (label) {
          label.textContent = defaultText;
        }
      });
    });
  }

  function formatCount(value) {
    return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  function bindCounters() {
    var fields = document.querySelectorAll('textarea[data-bys-counter][maxlength]');
    Array.prototype.forEach.call(fields, function (field) {
      var max = parseInt(field.getAttribute('maxlength'), 10);
      var counter = document.createElement('p');
      counter.className = 'bys-field__counter';
      counter.setAttribute('aria-hidden', 'true');
      field.insertAdjacentElement('afterend', counter);
      function update() {
        var used = field.value.length;
        counter.textContent = formatCount(used) + ' / ' + formatCount(max) + ' karakter';
        counter.classList.toggle('is-near-limit', used >= max * 0.9);
      }
      field.addEventListener('input', update);
      update();
    });
  }

  function bindDropzones() {
    var zones = document.querySelectorAll('[data-bys-dropzone]');
    Array.prototype.forEach.call(zones, function (zone) {
      var input = zone.querySelector('input[type="file"]');
      var nameEl = zone.querySelector('[data-bys-file-name]');
      if (!input || !nameEl) {
        return;
      }
      var emptyText = nameEl.getAttribute('data-bys-empty-text') || '';
      function showName() {
        var file = input.files && input.files[0];
        nameEl.textContent = file ? 'Seçilen dosya: ' + file.name : emptyText;
        zone.classList.toggle('has-file', Boolean(file));
      }
      input.addEventListener('change', showName);
      ['dragenter', 'dragover'].forEach(function (type) {
        input.addEventListener(type, function () { zone.classList.add('is-dragover'); });
      });
      ['dragleave', 'drop'].forEach(function (type) {
        input.addEventListener(type, function () { zone.classList.remove('is-dragover'); });
      });
      showName();
    });
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll('.bys-ui'), function (root) {
      root.classList.add('bys-js');
    });
    bindCounters();
    bindDropzones();
    bindSummaryLinks();
    bindSubmitGuard();
    focusSummary();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
