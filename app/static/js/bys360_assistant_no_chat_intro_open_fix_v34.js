/* BYS360_ASSISTANT_NO_CHAT_INTRO_OPEN_FIX_V34
   Amaç: Üst tanıtım kartı kalsın; sohbet içinde otomatik tanıtım mesajı/boş beyaz kart olmasın.
   Ayrıca launcher/close tıklamasını yedek olarak garanti eder. Yeni asistan oluşturmaz. */
(function () {
  'use strict';
  var ROOT_ID = 'bys360-assistant-module-root';
  var STORAGE_OPEN = 'bys360AssistantModule.open.v1';
  var STORAGE_CHAT = 'bys360AssistantModule.chat.session.v1';

  function norm(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function isBadIntroText(text) {
    var t = norm(text);
    if (!t) return false;
    // Otomatik tanıtım mesajı kişi adına değil, tanıtımın kendi kalıplarına
    // göre tanınır; geliştirici metni değişse de davranış aynı kalır.
    var isGreeting = t.indexOf('Merhaba, ben BYS360 Asistanı') !== -1;
    var mentionsDeveloper = t.indexOf('tarafından geliştirildim') !== -1;
    var asksForQuestion = t.indexOf('sorunuzu yazabilirsiniz') !== -1;
    var isScreenPrompt = t.indexOf('Bulunduğunuz ekrana göre') !== -1;
    return (isGreeting && (mentionsDeveloper || isScreenPrompt || asksForQuestion)) ||
      (mentionsDeveloper && asksForQuestion);
  }

  function rootEl() { return document.getElementById(ROOT_ID); }
  function panelEl(root) { return root ? root.querySelector('.bys360-am-panel, [role="dialog"]') : null; }
  function launcherEl(root) { return root ? root.querySelector('.bys360-am-launcher, [data-launcher]') : null; }
  function logEl(root) { return root ? root.querySelector('[data-chat-log], .bys360-am-log, [data-assistant-log], .bys360-assistant-chat-log') : null; }

  function setOpen(open) {
    var root = rootEl();
    var panel = panelEl(root);
    var launcher = launcherEl(root);
    if (!root || !panel) return false;
    if (open) {
      panel.hidden = false;
      panel.removeAttribute('hidden');
      root.classList.add('is-open');
    } else {
      panel.hidden = true;
      panel.setAttribute('hidden', '');
      root.classList.remove('is-open');
    }
    if (launcher) launcher.setAttribute('aria-expanded', open ? 'true' : 'false');
    try { localStorage.setItem(STORAGE_OPEN, open ? '1' : '0'); } catch (e) {}
    scrub();
    return true;
  }

  function toggle() {
    var root = rootEl();
    var panel = panelEl(root);
    var isClosed = !panel || panel.hidden || panel.hasAttribute('hidden') || getComputedStyle(panel).display === 'none';
    return setOpen(isClosed);
  }

  function cleanStoredIntro() {
    try {
      var raw = sessionStorage.getItem(STORAGE_CHAT);
      if (!raw) return;
      var list = JSON.parse(raw);
      if (!Array.isArray(list)) return;
      var cleaned = list.filter(function (m) { return !isBadIntroText(m && m.text); });
      if (cleaned.length !== list.length) {
        if (cleaned.length) sessionStorage.setItem(STORAGE_CHAT, JSON.stringify(cleaned));
        else sessionStorage.removeItem(STORAGE_CHAT);
      }
    } catch (e) {}
  }

  function removeNodeSafely(node) {
    if (!node || !node.parentNode) return;
    node.parentNode.removeChild(node);
  }

  function scrubBadIntro(root) {
    root = root || rootEl();
    if (!root) return;
    var nodes = root.querySelectorAll('.bys360-am-message, .bys360-am-bubble, [data-chat-message], .chat-message, .message, div, p, span');
    Array.prototype.forEach.call(nodes, function (node) {
      if (!node || !node.textContent || !isBadIntroText(node.textContent)) return;
      var row = node.closest && node.closest('.bys360-am-message, [data-chat-message], .chat-message, .message');
      removeNodeSafely(row || node);
    });
  }

  function scrubEmptyArtifacts(root) {
    root = root || rootEl();
    if (!root) return;
    var rows = root.querySelectorAll('.bys360-am-message, [data-chat-message], .chat-message, .message-row');
    Array.prototype.forEach.call(rows, function (row) {
      var text = norm(row.textContent);
      var hasLinks = !!row.querySelector('a, button, input, textarea');
      if (!text && !hasLinks) removeNodeSafely(row);
      if (row.querySelector && row.querySelector('.bys360-am-bubble') && !norm(row.querySelector('.bys360-am-bubble').textContent) && !row.querySelector('.bys360-am-bubble a, .bys360-am-bubble button')) {
        removeNodeSafely(row);
      }
    });
    var log = logEl(root);
    if (log) {
      var hasRealMessage = false;
      Array.prototype.forEach.call(log.children || [], function (child) {
        if (norm(child.textContent) || child.querySelector('a, button, input, textarea')) hasRealMessage = true;
      });
      log.classList.toggle('is-empty', !hasRealMessage);
      log.setAttribute('data-empty', hasRealMessage ? 'false' : 'true');
    }
  }

  function hideForeignAssistantRoots() {
    var selectors = ['#bys360-ai-agent-widget-root', '#bys360-floating-assistant-force-root', '#bys360-ai-agent-widget', '#bys360AiAgentWidget'];
    selectors.forEach(function (sel) {
      var node = document.querySelector(sel);
      if (node) {
        node.setAttribute('aria-hidden', 'true');
        node.style.display = 'none';
      }
    });
  }

  function scrub() {
    cleanStoredIntro();
    hideForeignAssistantRoots();
    var root = rootEl();
    if (!root) return;
    scrubBadIntro(root);
    scrubEmptyArtifacts(root);
  }

  function bind() {
    scrub();
    document.removeEventListener('click', onClick, true);
    document.addEventListener('click', onClick, true);
  }

  function onClick(event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var root = rootEl();
    if (!root) return;
    var launcher = target.closest('#' + ROOT_ID + ' .bys360-am-launcher, #' + ROOT_ID + ' [data-launcher]');
    if (launcher) {
      event.preventDefault();
      event.stopPropagation();
      if (event.stopImmediatePropagation) event.stopImmediatePropagation();
      toggle();
      return;
    }
    var close = target.closest('#' + ROOT_ID + ' .bys360-am-close, #' + ROOT_ID + ' [data-assistant-close]');
    if (close) {
      event.preventDefault();
      event.stopPropagation();
      if (event.stopImmediatePropagation) event.stopImmediatePropagation();
      setOpen(false);
      return;
    }
  }

  function boot() {
    bind();
    var tries = 0;
    var timer = window.setInterval(function () {
      tries += 1;
      scrub();
      if (tries > 40) window.clearInterval(timer);
    }, 250);
    try {
      var mo = new MutationObserver(function () { scrub(); });
      mo.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
    } catch (e) {}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
  window.BYS360AssistantNoChatIntroOpenFixV34 = { open: function () { return setOpen(true); }, close: function () { return setOpen(false); }, toggle: toggle, scrub: scrub, isBadIntroText: isBadIntroText };
}());
