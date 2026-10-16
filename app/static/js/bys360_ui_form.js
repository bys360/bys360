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

  function init() {
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
