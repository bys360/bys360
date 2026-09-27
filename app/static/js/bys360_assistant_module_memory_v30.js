(function () {
  'use strict';
  if (window.__BYS360_ASSISTANT_STABLE_SCROLL_MEMORY_V30_LOADED__) return;
  window.__BYS360_ASSISTANT_STABLE_SCROLL_MEMORY_V30_LOADED__ = true;

  var VERSION = 'assistant-stable-scroll-memory-v30';
  var ROOT_ID = 'bys360-assistant-module-root';
  var HISTORY_KEY = 'bys360Assistant.conversation.current.v30';
  var STATE_KEY = 'bys360Assistant.conversation.state.v30';
  // BYS360 Assistant V2 conversation_id (mandate Phase B): sessionStorage
  // only (never localStorage) -- matches this file's own existing
  // HISTORY_KEY/STATE_KEY convention, so it survives same-tab page
  // navigation (needed for a real multi-turn follow-up to work while the
  // user browses the app) but is gone the moment the browser tab closes.
  // Cleared explicitly on logout (see the logoutForm hook below) so a
  // second user logging in on the same tab never inherits it.
  var CONVERSATION_ID_KEY = 'bys360Assistant.conversation.id.v30';
  var LEGACY_KEYS = [
    'bys360Assistant.conversation.current.v29',
    'bys360Assistant.history.session.v28',
    'bys360Assistant.history.session.v27',
    'bys360Assistant.history.session.v26'
  ];
  var MAX_HISTORY = 260;
  var history = [];
  var lastTopic = '';
  var restoredOnce = false;
  var restoreTimer = null;
  var isRestoring = false;
  var suppressRestoreUntil = 0;
  var lastRestoreSignature = '';
  var TR = { 'ç':'c','ğ':'g','ı':'i','ö':'o','ş':'s','ü':'u','â':'a','î':'i','û':'u','Ç':'c','Ğ':'g','İ':'i','I':'i','Ö':'o','Ş':'s','Ü':'u','':'a','Î':'i','Û':'u' };

  function normalize(value) {
    return String(value || '')
      .replace(/[çğıöşüâîûÇĞİIÖŞÜÎÛ]/g, function (ch) { return TR[ch] || ch; })
      .toLowerCase()
      .replace(/[^a-z0-9\s/_-]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }
  function escapeText(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[ch];
    });
  }
  // BYS360 Assistant V2 CSRF FIX (mandate Phase D): same established
  // pattern as app/templates/ai_agent/panel.html for this same endpoint.
  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"], meta[name="csrf_token"]');
    if (meta && meta.getAttribute('content')) return meta.getAttribute('content');
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
  }
  function safeParse(raw) {
    if (!raw) return [];
    try {
      var parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(function (m) {
        return m && (m.role === 'user' || m.role === 'bot') && typeof m.text === 'string';
      }).slice(-MAX_HISTORY);
    } catch (e) { return []; }
  }
  function loadHistory() {
    var raw = null, i, migrated;
    try { raw = sessionStorage.getItem(HISTORY_KEY); } catch (e) {}
    if (!raw) {
      for (i = 0; i < LEGACY_KEYS.length; i++) {
        try { migrated = sessionStorage.getItem(LEGACY_KEYS[i]); } catch (e2) { migrated = null; }
        if (migrated) { raw = migrated; break; }
      }
    }
    if (!raw) {
      try { raw = window.name && window.name.indexOf('BYS360_ASSISTANT_HISTORY=') === 0 ? window.name.slice(25) : null; } catch (e3) {}
    }
    return safeParse(raw);
  }
  function saveHistory() {
    var data = JSON.stringify(history.slice(-MAX_HISTORY));
    try { sessionStorage.setItem(HISTORY_KEY, data); } catch (e) {}
    try { window.name = 'BYS360_ASSISTANT_HISTORY=' + data; } catch (e2) {}
  }
  function saveState(topic) {
    lastTopic = topic || lastTopic || '';
    try { sessionStorage.setItem(STATE_KEY, JSON.stringify({ topic:lastTopic, path:location.pathname, ts:Date.now() })); } catch (e) {}
  }
  function loadState() {
    try { return JSON.parse(sessionStorage.getItem(STATE_KEY) || 'null'); } catch (e) { return null; }
  }
  function loadConversationId() {
    try { return sessionStorage.getItem(CONVERSATION_ID_KEY) || null; } catch (e) { return null; }
  }
  function saveConversationId(id) {
    try {
      if (id) sessionStorage.setItem(CONVERSATION_ID_KEY, id);
      else sessionStorage.removeItem(CONVERSATION_ID_KEY);
    } catch (e) {}
  }
  function clearConversation() {
    // Phase D (conversation reset): clears conversation_id, the visible
    // history, and the window.name cross-navigation fallback -- never
    // touches server-side authorization state, which AssistantV2Service
    // re-checks independently on every call regardless of client state.
    history = [];
    lastTopic = '';
    saveConversationId(null);
    try { sessionStorage.removeItem(HISTORY_KEY); } catch (e) {}
    try { sessionStorage.removeItem(STATE_KEY); } catch (e) {}
    try { window.name = ''; } catch (e2) {}
    var root = rootEl();
    if (root) clearOnlyChatLog(root);
  }
  function rootEl() {
    return document.getElementById(ROOT_ID)
      || document.querySelector('[data-bys360-assistant-module]')
      || document.querySelector('.bys360-assistant-module')
      || document.querySelector('.bys360-am-root');
  }
  function formEl(root) {
    return root ? (root.querySelector('[data-chat-form]') || root.querySelector('.bys360-am-form') || root.querySelector('form')) : null;
  }
  function inputEl(root) {
    return root ? (root.querySelector('[data-chat-input]') || root.querySelector('textarea') || root.querySelector('input[type="text"]') || root.querySelector('input:not([type])')) : null;
  }
  function ensureLog(root) {
    if (!root) return null;
    var log = root.querySelector('[data-chat-log]') || root.querySelector('.bys360-am-log') || root.querySelector('[data-chat-list]') || root.querySelector('.bys360-assistant-chat-log') || root.querySelector('[data-assistant-log]');
    if (log) return log;
    var body = root.querySelector('.bys360-am-body') || root.querySelector('.bys360-assistant-body') || root.querySelector('[data-chat-body]') || root;
    log = document.createElement('div');
    log.className = 'bys360-am-log';
    log.setAttribute('data-chat-log', '1');
    log.setAttribute('data-v30-created-log', '1');
    var form = formEl(root);
    if (form && form.parentNode === body) body.insertBefore(log, form);
    else body.appendChild(log);
    return log;
  }
  function visibleText() {
    return normalize([
      document.title,
      document.querySelector('h1') && document.querySelector('h1').textContent,
      document.querySelector('.page-title') && document.querySelector('.page-title').textContent,
      document.querySelector('.active') && document.querySelector('.active').textContent,
      location.pathname
    ].filter(Boolean).join(' '));
  }
  function toLinks(items) {
    return (items || []).map(function (item) {
      if (Array.isArray(item)) return { title:item[0], href:item[1] };
      return { title:item.title || item.label || 'Ekrana git', href:item.href || item.url || '#' };
    }).filter(function (item) { return item.title && item.href; });
  }
  function renderMessage(root, msg, persist) {
    var log = ensureLog(root);
    if (!log) return false;
    var row = document.createElement('div');
    row.className = 'bys360-am-message ' + (msg.role === 'user' ? 'is-user' : 'is-bot');
    row.setAttribute('data-v30-message', '1');
    var avatar = document.createElement('div');
    avatar.className = 'bys360-am-avatar';
    avatar.textContent = msg.role === 'user' ? 'Siz' : 'BYS';
    var bubble = document.createElement('div');
    bubble.className = 'bys360-am-bubble';
    if (msg.role !== 'user' && msg.moduleLabel) {
      var badge = document.createElement('span');
      badge.className = 'bys360-am-module-badge';
      badge.textContent = msg.moduleLabel;
      bubble.appendChild(badge);
    }
    var answerText = document.createElement('div');
    answerText.className = 'bys360-am-answer-text';
    answerText.innerHTML = escapeText(msg.text || '').replace(/\n/g, '<br>');
    bubble.appendChild(answerText);
    if (msg.role !== 'user' && Array.isArray(msg.sources) && msg.sources.length) {
      var sourceBox = document.createElement('div');
      sourceBox.className = 'bys360-am-sources';
      msg.sources.slice(0, 5).forEach(function (label) {
        var chip = document.createElement('span');
        chip.className = 'bys360-am-source-chip';
        chip.textContent = label;
        sourceBox.appendChild(chip);
      });
      bubble.appendChild(sourceBox);
    }
    if (msg.role !== 'user' && Array.isArray(msg.suggestedQuestions) && msg.suggestedQuestions.length) {
      var suggestBox = document.createElement('div');
      suggestBox.className = 'bys360-am-suggestions';
      msg.suggestedQuestions.slice(0, 4).forEach(function (question) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'bys360-am-suggestion-chip';
        chip.textContent = question;
        chip.addEventListener('click', function () { handleQuestion(question); });
        suggestBox.appendChild(chip);
      });
      bubble.appendChild(suggestBox);
    }
    var links = toLinks(msg.links || []);
    if (links.length) {
      var linkBox = document.createElement('div');
      linkBox.className = 'bys360-am-links';
      links.slice(0, 6).forEach(function (item) {
        var a = document.createElement('a');
        a.href = item.href || '#';
        a.setAttribute('data-bys360-safe-link', '1');
        a.innerHTML = escapeText(item.title || 'Ekrana git') + '<span>→</span>';
        linkBox.appendChild(a);
      });
      bubble.appendChild(linkBox);
    }
    row.appendChild(avatar);
    row.appendChild(bubble);
    log.appendChild(row);
    if (persist !== false) {
      window.requestAnimationFrame(function () { log.scrollTop = log.scrollHeight; });
    }
    if (persist !== false) {
      history.push({
        role:msg.role === 'user' ? 'user' : 'bot', text:msg.text || '', links:links, ts:Date.now(),
        sources: Array.isArray(msg.sources) ? msg.sources : undefined,
        moduleLabel: msg.moduleLabel || undefined,
        suggestedQuestions: Array.isArray(msg.suggestedQuestions) ? msg.suggestedQuestions : undefined
      });
      if (history.length > MAX_HISTORY) history = history.slice(-MAX_HISTORY);
      saveHistory();
    }
    return true;
  }
  function clearOnlyChatLog(root) {
    var log = ensureLog(root);
    if (!log) return;
    log.innerHTML = '';
  }
  function restoreIntoUi(reason) {
    if (isRestoring || Date.now() < suppressRestoreUntil) return false;
    var root = rootEl();
    if (!root) return false;
    var loaded = loadHistory();
    if (!loaded.length) return false;
    history = loaded.slice(-MAX_HISTORY);
    var signature = String(history.length) + ':' + String(history.length ? (history[history.length - 1].ts || history[history.length - 1].text.length) : 0);
    var log = ensureLog(root);
    if (log && log.getAttribute('data-v30-signature') === signature && log.querySelector('[data-v30-message="1"]')) {
      restoredOnce = true;
      return true;
    }
    isRestoring = true;
    suppressRestoreUntil = Date.now() + 650;
    try {
      clearOnlyChatLog(root);
      history.forEach(function (m) { renderMessage(root, m, false); });
      log = ensureLog(root);
      if (log) {
        log.setAttribute('data-v30-signature', signature);
        lastRestoreSignature = signature;
        log.scrollTop = log.scrollHeight;
      }
      restoredOnce = true;
    } finally {
      window.setTimeout(function () { isRestoring = false; }, 120);
    }
    return true;
  }
  function addUser(root, text) { return renderMessage(root, { role:'user', text:text, links:[] }, true); }
  function addBot(root, text, links, extras) {
    extras = extras || {};
    return renderMessage(root, { role:'bot', text:text, links:toLinks(links), sources:extras.sources, moduleLabel:extras.moduleLabel, suggestedQuestions:extras.suggestedQuestions }, true);
  }
  function scheduleRestore(reason) {
    if (isRestoring || Date.now() < suppressRestoreUntil) return;
    if (restoreTimer) clearTimeout(restoreTimer);
    restoreTimer = setTimeout(function () {
      if (isRestoring || Date.now() < suppressRestoreUntil) return;
      restoreIntoUi(reason);
      bindForm();
    }, 160);
  }

  var KNOWLEDGE = [
    {id:'home',module:'Genel',screen:'Ana Sayfa',href:'/home',keys:['anasayfa','ana sayfa','başlangıç','baslangic','bugün ne var','bugun ne var','nereden başlayacağım','nereden baslayacagim','günlük özet','gunluk ozet'],who:['Tüm kullanıcılar, yalnızca kendisine açık kartları ve modül geçişlerini görür.'],steps:['Ana Sayfa ekranını açın.','Bugünkü kısa özetleri, bekleyen bildirimleri, size ait görevleri ve modül geçişlerini kontrol edin.','İşlem yapmak için ilgili modülün gerçek ekranına geçin.'],watch:['Ana Sayfa günlük başlangıç ve hızlı geçiş ekranıdır; yönetici analizleri için Dashboard ekranı kullanılmalıdır.']},
    {id:'general_dashboard',module:'Yönetici Dashboard',screen:'Dashboard',href:'/dashboard',keys:['dashboard','genel dashboard','yönetici dashboard','yonetici dashboard','gösterge paneli','gosterge paneli','yönetici görünümü','yonetici gorunumu'],who:['Başkan, Admin, yöneticiler ve rol matrisinde yetki verilmiş kullanıcılar; herkes yalnızca yetkili olduğu kartları görür.'],steps:['Dashboard ekranını açın.','Yönetici özet kartlarını, grafik/gösterge alanlarını ve yetki kapsamındaki analizleri inceleyin.','Performans, KPI, destek veya anket gibi ayrıntı gereken başlıklarda ilgili modül ekranına geçin.'],watch:['Dashboard analiz ve yönetici görünürlüğü ekranıdır; Ana Sayfa ile aynı cevap verilmemelidir. Kart görünmüyorsa rol matrisi, kişi bazlı menü izni veya modül ayarı kontrol edilmelidir.']},
    {id:'person_add',module:'Personel Yönetimi',screen:'Personel Özlük Dosyaları / Personel Ekle',href:'/admin/users',keys:['kişi ekle','kisi ekle','kişi nasıl eklenir','personel ekle','personel nasıl eklenir','çalışan ekle','calisan ekle','yeni kişi','yeni kisi','yeni personel','kullanıcı ekle','kullanici ekle','hesap aç','hesap ac','personel kaydı','personel kaydi','sicil no','profil fotoğrafı','profil fotografi'],who:['Admin','Sistem Yöneticisi','Personel Yönetimi yetkilisi','Yetki verilmiş İK/personel kullanıcısı'],steps:['Sol menüden Personel Yönetimi bölümüne girin.','Personel Özlük Dosyaları / Personel Listesi ekranını açın.','Yeni Personel Ekle veya Yeni Kayıt butonuna basın.','Sicil No, ad, soyad, unvan, görev, birim, üst birim ve yönetici alanlarını doldurun.','Gerekliyse profil fotoğrafı, kullanıcı hesabı ve rol bilgisini belirleyin.','Kaydedin ve personelin listede göründüğünü kontrol edin.'],watch:['TC yerine Sicil No kullanılmalı.','Birim, üst birim, unvan ve yönetici null kalırsa performans amir zinciri yanlış üretilebilir.','Rol ve menü görünürlüğü ayrıca kontrol edilmelidir.']},
    {id:'person_update',module:'Personel Yönetimi',screen:'Personel Bilgisi Güncelleme',href:'/admin/users',keys:['personel güncelle','personel guncelle','kişi bilgisi değiştir','kisi bilgisi degistir','birim değiştir','unvan değiştir','yönetici değiştir','personel pasif','aktif pasif'],who:['Admin','Sistem Yöneticisi','Personel Yönetimi yetkilisi'],steps:['Personel Yönetimi > Personel Özlük Dosyaları ekranına girin.','Personeli ad, soyad veya sicil no ile arayın.','Detay / Düzenle butonuna basın.','Birim, üst birim, görev, unvan, yönetici, rol veya aktiflik bilgisini güncelleyin.','Kaydedin.'],watch:['Bu değişiklik performans görev üretimi, rol matrisi, raporlar ve bildirim hedeflerini etkileyebilir.']},
    {id:'org',module:'Personel Yönetimi',screen:'Birim ve Organizasyon Yönetimi',href:'/admin/org-units',keys:['birim ekle','üst birim','ust birim','organizasyon','çalışma grubu','calisma grubu','koordinatör','koordinator','grup başkanlığı','grup baskanligi','pozisyon'],who:['Admin','Sistem Yöneticisi','Organizasyon/personel yetkilisi'],steps:['Birim ve Organizasyon Yönetimi ekranını açın.','Üst birimi ve bağlı birimi tanımlayın.','Çalışma grubu, koordinatör ve yönetici ilişkilerini kurun.','Personel atamalarını doğru birime bağlayın.'],watch:['Organizasyon yanlışsa performans amir zinciri, yetki görünürlüğü ve rapor kırılımları da yanlış olur.']},
    {id:'leave',module:'Personel Yönetimi',screen:'İzin ve Devamsızlık Takibi',href:'/hr-management/leave',keys:['izin','izin nasıl girilir','izin nasil girilir','izin talebi','izin kaydı','izin kaydi','izin bakiyesi','devamsızlık','devamsizlik','rapor izin'],who:['Personel yetkilisi','İK/Admin','Yetki verilmiş yönetici'],steps:['Personel Yönetimi veya İzin Yönetimi bölümüne girin.','İzin Talebi / İzin Kaydı ekranını açın.','Personeli seçin.','İzin türünü, başlangıç ve bitiş tarihini girin.','Gerekli açıklama veya belge varsa ekleyin.','Kaydedin ve onay sürecini kontrol edin.'],watch:['İzinli kişi amirse vekâlet ve performans görev devri etkilenebilir.']},
    {id:'delegation',module:'Personel Yönetimi',screen:'Vekâlet Yönetimi',href:'/hr-management/attendance',keys:['vekâlet','vekalet','vekil ata','görev devri','gorev devri','asıl kişi','asil kisi','vekil kim olacak'],who:['Admin','Personel/İK yetkilisi','Yetki verilmiş yönetici'],steps:['Vekâlet Yönetimi ekranına girin.','Asıl kişiyi seçin.','Vekil olacak kişiyi seçin.','Başlangıç ve bitiş tarihini belirleyin.','Vekâlet kapsamını seçin.','Kaydedin ve ilgili süreçlerde vekilin görünüp görünmediğini kontrol edin.'],watch:['Vekâlet açık değilse izinli amirin görevleri aksayabilir.']},
    {id:'period',module:'Performans Yönetimi',screen:'Dönemler',href:'/performance/periods',keys:['dönem aç','donem ac','dönem oluştur','donem olustur','performans dönemi','performans donemi','2026 performans','değerlendirme dönemi','degerlendirme donemi','özel dönem','ozel donem','güvenlik dönem','temizlik dönem'],who:['Admin','Sistem Yöneticisi','Performans Yetkilisi','Yetki verilmiş İK/personel birimi kullanıcısı'],steps:['Performans Yönetimi > Dönemler ekranına girin.','Yeni Dönem Oluştur butonuna basın.','Dönem adı, dönem türü ve tarih aralığını girin.','Kapsam tipini seçin: tüm kurum, birim, üst birim, kategori veya seçili personel.','Kaydedin.','Ardından kriter, ağırlık ve görev üretimi adımlarını tamamlayın.'],watch:['Dönem oluşturmak tek başına değerlendirmeyi başlatmaz.','Aynı personel için çakışan tarih aralığı varsa sistem uyarı vermelidir.']},
    {id:'criteria',module:'Performans Yönetimi',screen:'Değerlendirme Kriterleri',href:'/performance/criteria',keys:['kriter','değerlendirme kriteri','degerlendirme kriteri','kriter ekle','yetkinlik değil','yetkinlik degil'],who:['Admin','Performans Yetkilisi'],steps:['Performans Yönetimi > Sorular / Kriterler ekranına girin.','Yeni kriter ekle butonuna basın.','Kriter adı, açıklama ve aktiflik bilgisini girin.','Gerekirse dönem/kategori bağlantısını kurun.','Kaydedin.'],watch:['Ana ekran dili “Değerlendirme Kriterleri” olmalı; “Yetkinlik” ana terim olarak kullanılmamalı.']},
    {id:'weights',module:'Performans Yönetimi',screen:'Ağırlık Ayarları',href:'/performance/weights',keys:['ağırlık','agirlik','puan ağırlığı','amir ağırlığı','1 amir','2 amir','3 amir','yüzde yüz','%100'],who:['Admin','Performans Yetkilisi'],steps:['Ağırlık Ayarları ekranına girin.','Dönem veya rol grubunu seçin.','1. amir, 2. amir ve varsa 3. amir ağırlıklarını girin.','Toplamın %100 olduğunu kontrol edin.','Kaydedin.'],watch:['3. amir yorum modundaysa puan ağırlığı %0 olmalıdır.']},
    {id:'task_generation',module:'Performans Yönetimi',screen:'Görev Üretimi',href:'/performance/assignments',keys:['görev üret','gorev uret','değerlendirme görevi','degerlendirme gorevi','amir zinciri','görevler oluşmadı','gorevler olusmadi','eksik amir'],who:['Admin','Performans Yetkilisi'],steps:['Değerlendirme Görevleri ekranına girin.','Dönemi seçin.','Personel, birim, kategori ve amir verilerini doğrulayın.','Görevleri Oluştur butonuna basın.','Oluşan görevlerde eksik amir veya yanlış zincir var mı kontrol edin.'],watch:['Sistem sahte 3. amir görevi veya gereksiz bekleme durumu üretmemelidir.']},
    {id:'evaluation',module:'Performans Yönetimi',screen:'Değerlendirme Görevlerim',href:'/performance/evaluation-tasks',keys:['puan gir','puanlama','değerlendirme yap','degerlendirme yap','görevlerim','gorevlerim','amir değerlendirmesi','amir degerlendirmesi'],who:['Kendisine görev atanmış amir/değerlendirici'],steps:['Değerlendirme Görevlerim ekranına girin.','Değerlendirilecek personeli seçin.','Kriter bazlı 1–5 arası puan girin.','Gerekli açıklama ve genel görüş alanlarını doldurun.','Kaydet / Tamamla butonuna basın.'],watch:['Sistem kör değerlendirme yapmaz; sonraki amir önceki puan ve görüşü görebilir.']},
    {id:'scorecard',module:'Performans Yönetimi',screen:'Karne / Not Karnesi',href:'/performance/scorecard',keys:['karne','karnem','not karnesi','puanım görünmüyor','puanim gorunmuyor','karne görünmüyor','karne gorunmuyor','sonucum yok','performans sonucum'],who:['Personel kendi yayınlanmış karnesini görür; yönetici yetkisi kapsamındaki karneleri görür.'],steps:['Önce değerlendirme görevlerinin tamamlandığını kontrol edin.','70 altı sonuç varsa Başkan Onayı tamamlandı mı bakın.','Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı tamamlandı mı kontrol edin.','Admin/İK final yayın yaptı mı bakın.','Rol matrisi ve karne görünürlüğü açık mı kontrol edin.'],watch:['Süreç tamamlanmadan karne personele açılmaz.']},
    {id:'president',module:'Performans Yönetimi',screen:'Başkan / Üst Onayları',href:'/performance/president-approvals',keys:['başkan onayı','baskan onayi','üst onay','ust onay','70 altı','70 alti','düşük performans','dusuk performans','yayın kilidi','yayin kilidi'],who:['Başkan','Admin/Sistem Yöneticisi','Yetkili üst onay kullanıcısı'],steps:['Başkan / Üst Onayları ekranına girin.','Yalnızca gerçek 70 altı kayıtları inceleyin.','Karne incelemesinde nihai puan, kriterler, amir görüşleri ve süreç geçmişini kontrol edin.','Onay veya iade işlemini yetkiniz dahilinde tamamlayın.'],watch:['Başkan onayı tamamlanmadan düşük performans sonucu personele kesin yayınlanmış sayılmaz.']},
    {id:'publish',module:'Performans Yönetimi',screen:'Yayın Ön Onayı ve Final Yayın',href:'/performance/personnel-support-publish-approvals',keys:['yayın','yayin','yayınla','yayinla','final yayın','final yayin','yayın ön onayı','personel destek onayı','personel destek onayi'],who:['Personel ve Destek Hizmetleri Grup Başkanı','Admin/İK yetkilisi'],steps:['Tüm değerlendirme görevlerinin tamamlandığını kontrol edin.','70 altı kayıtların Başkan Onayı sürecini tamamlayın.','Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayını alın.','Admin/İK final yayını yapar.'],watch:['Final yayın öncesi onay zinciri atlanmamalıdır.']},
    {id:'process',module:'Performans Yönetimi',screen:'Süreç Takibi',href:'/performance/process-tracking',keys:['süreç takibi','surec takibi','akış','akis','bekleyen görev','bekleyen gorev','aksatan amir','geciken amir','hatırlatma','hatirlatma'],who:['Admin','Performans yetkilisi','Yetkili yönetici'],steps:['Süreç Takibi ekranına girin.','Dönemi seçin.','Bekleyen değerlendirme, onay, yayın ve gecikme durumlarını kontrol edin.','Geciken amirler için hatırlatma akışını takip edin.'],watch:['Teknik statü değil, Türkçe kurumsal süreç durumu görünmelidir.']},
    {id:'reports',module:'Dashboard ve Raporlar',screen:'Raporlar',href:'/performance/reports',keys:['rapor','rapor al','analiz','performans raporu','personel raporu','süreç raporu','surec raporu','dışa aktar','disa aktar'],who:['Yetkisi olan kullanıcılar; kapsam rol, kişi ve birim yetkisine göre değişir.'],steps:['Raporlar ekranına girin.','Dönem, birim, kategori, amir veya personel filtresini seçin.','Raporu oluşturun.','Yetkiniz varsa dışa aktarın veya paylaşın.'],watch:['Kişi detayları yetkiye göre görünmelidir; kategori ortalaması kişi detayı olmadan sunulabilir.']},
    {id:'archive',module:'Performans Yönetimi',screen:'Geçmiş Karne Arşivi',href:'/performans/gecmis-karne-arsivi',keys:['geçmiş karne','gecmis karne','arşiv','arsiv','eski puan','2024 puan','2025 puan','geçmiş performans'],who:['Personel kendi geçmişini; yönetici yetkili kapsamını; Başkan/Admin genel görünümü görür.'],steps:['Geçmiş Karne Arşivi ekranına girin.','Yıl veya dönem filtresini seçin.','Yetkiniz dahilindeki karne/puan kayıtlarını inceleyin.'],watch:['Başka personelin detayları yetkisiz görünmemelidir.']},
    {id:'notes',module:'Performans Yönetimi',screen:'Dönem İçi Notlar',href:'/performance/interim-notes',keys:['dönem içi not','donem ici not','ara geri bildirim','olay notu','başarı notu','basari notu','gelişim notu','gelisim notu'],who:['Yetkili amir/yönetici ve performans yetkilisi'],steps:['Dönem İçi Notlar ekranına girin.','Personel ve dönem bilgisini seçin.','Olumlu/olumsuz olay, başarı veya gelişim ihtiyacını yazın.','Kaydedin.'],watch:['Bu notlar otomatik puan üretmez; puanlama döneminde destekleyici hatırlatma olabilir.']},
    {id:'development',module:'Performans Yönetimi',screen:'Gelişim Önerisi',href:'/performance/development-guidance',keys:['gelişim önerisi','gelisim onerisi','rehber alan','eğitim önerisi','egitim onerisi','gelişim planı'],who:['Amirler, performans yetkilileri ve yetkili yöneticiler'],steps:['Gelişim Önerisi / Rehber Alan ekranına girin.','Personel veya dönem bağlamını seçin.','Güçlü yön, gelişim alanı ve takip önerisini yazın.','Kaydedin ve karne/yayın görünürlüğünü kontrol edin.'],watch:['Öneri dili idari karar gibi kesin hüküm içermemelidir.']},
    {id:'role_matrix',module:'Sistem Ayarları ve Yetkilendirme',screen:'Rol Matrisi ve Menü Görünürlüğü',href:'/settings/role-matrix',keys:['rol matrisi','menü görünmüyor','menu gorunmuyor','sekme yok','yetki aç','yetki ac','yetki kapat','menü yetkisi','menu yetkisi','kişi bazlı yetki','kisi bazli yetki','birim profili'],who:['Admin','Sistem Yöneticisi','Yetkilendirme yöneticisi'],steps:['Sistem Ayarları > Rol Matrisi ekranına girin.','Kullanıcının rolünü seçin.','İlgili modül ve alt sekmenin açık/kapalı durumunu kontrol edin.','Kişi bazlı menü izni ve birim profilini kontrol edin.','Kaydedip kullanıcıyla çıkış-giriş yapın.'],watch:['Yetkisi olmayan kullanıcı menüyü hiç görmemelidir; sadece tıklayınca erişim engeli vermek yeterli değildir.']},
    {id:'settings',module:'Sistem Ayarları ve Yetkilendirme',screen:'Sistem Ayarları',href:'/settings',keys:['ayarlar','sistem ayarları','sistem ayarlari','modül ayarı','modul ayari','captcha','oturum','smtp','e-posta','bildirim ayarı','audit kayıt','güvenlik ayarı'],who:['Admin','Sistem Yöneticisi'],steps:['Sistem Ayarları ekranına girin.','İlgili ayar grubunu açın.','Değiştireceğiniz ayarın hangi modülü etkilediğini kontrol edin.','Kaydedin ve değişiklik logunun oluştuğunu doğrulayın.'],watch:['Canlıda küçük bir ayar değişikliği tüm sistem davranışını etkileyebilir.']},
    {id:'support',module:'İletişim ve Anket Yönetimi',screen:'Yardım Merkezi / Destek Talepleri',href:'/support',keys:['yardım','yardim','destek','talep aç','talep ac','sorun bildir','ticket','bilet','destek talebi'],who:['Tüm kullanıcılar talep açabilir; yönetim yetkiye göre takip eder.'],steps:['Yardım Merkezi / Destek ekranına girin.','Destek Talebi Aç butonuna basın.','Kategori, konu ve açıklamayı girin.','Gerekirse dosya ekleyin.','Talebin durumunu takip edin.'],watch:['Gereksiz kişisel veya hassas veri paylaşmayın.']},
    {id:'messages',module:'İletişim ve Anket Yönetimi',screen:'Mesajlar',href:'/messages',keys:['mesaj','sohbet','yazışma','yazisma','okunmamış mesaj','okunmamis mesaj','kendime not'],who:['Yetkisi açık kullanıcılar'],steps:['Mesajlar ekranına girin.','Kişi, grup veya konu seçin.','Mesajınızı yazıp gönderin.','Gerekirse dosya ekleyin.'],watch:['Asistan mesaj içeriğini yetkisiz gösteremez.']},
    {id:'surveys',module:'İletişim ve Anket Yönetimi',screen:'Anketler ve Geri Bildirim',href:'/surveys',keys:['anket','anketi cevapla','anket sonucu','geri bildirim','nabız','nabiz','yanıt bekleyen'],who:['Personel atanmış anketi cevaplar; yetkililer anket yönetir.'],steps:['Anketler ekranına girin.','Yanıt bekleyen anketi açın.','Zorunlu soruları tamamlayın.','Gönderin.'],watch:['Anket cevabı kişisel/hassas olabilir; yetkisiz gösterilmemelidir.']},
    {id:'announcements',module:'İletişim ve Anket Yönetimi',screen:'Duyurular / Bildirimler',href:'/announcements',keys:['duyuru','duyuru gönder','duyuru gonder','bildirim','kurumsal duyuru','mail gönder','mail gonder'],who:['Yetkili birimler ve sistem yöneticileri'],steps:['Duyurular ekranına girin.','Yeni duyuru oluşturun.','Hedef kitleyi belirleyin.','Metni girip yayınlayın.','Bildirim durumunu kontrol edin.'],watch:['Hedef kitle ve görünürlük yetkisi doğru seçilmelidir.']},
    {id:'ai',module:'AI Karar Destek Merkezi',screen:'Karar Destek Merkezi',href:'/ai/decision-support/faz1/health',keys:['ai karar','karar destek','yapay zeka','analiz','risk notu','özet','ozet','ai öneri','ai oneri'],who:['Yetki verilen yönetici ve analiz kullanıcıları'],steps:['AI Karar Destek Merkezi ekranına girin.','Yetkiniz dahilindeki analiz/özet kartını açın.','Çıktıyı karar değil, destek notu olarak değerlendirin.'],watch:['AI idari karar vermez, performans puanı belirlemez, hassas veri göstermemelidir.']},
    {id:'kpi',module:'KPI ve Hedef Yönetimi',screen:'KPI / Hedef Yönetimi',href:'/performans/stratejik/hedefler',keys:['kpi','hedef','hedef kartı','hedef karti','hedef dönemi','hedef donemi','gerçekleşme','gerceklesme','riskli hedef','başarı oranı','basari orani'],who:['Başkan/Admin genel; koordinatör ve yöneticiler yetki kapsamına göre görür.'],steps:['KPI / Hedef Yönetimi ekranına girin.','Hedef dönemi veya hedef kartı oluşturun.','Hedef tipi, kategori, sahip, hedef değer, gerçekleşen değer ve ağırlığı girin.','Kaydedin ve dashboard’da başarı/risk durumunu kontrol edin.'],watch:['KPI otomatik idari karar üretmez; ölçüm ve karar destek verisi sağlar.']},
    {id:'assistant_knowledge',module:'BYS360 Asistanı',screen:'Asistan Bilgi Bankası / Öğretim Merkezi',href:'/ai-agent/knowledge',keys:['asistan öğret','asistan ogret','bilgi bankası','bilgi bankasi','öğretim merkezi','ogretim merkezi','asistan eğit','asistan egit'],who:['Admin','Sistem Yöneticisi','Asistan bilgi yöneticisi'],steps:['Asistan Bilgi Bankası / Öğretim Merkezi ekranına girin.','Yeni soru-cevap veya rehber kaydı ekleyin.','Dili sade, kurumsal ve gerçek ekran adlarıyla yazın.','Test sorusuyla cevabı kontrol edin.'],watch:['Asistan idari karar ve hassas veri içeriği öğrenmemelidir.']},
    {id:'profile',module:'Kullanıcı Hesabı',screen:'Profil / Şifre / Oturum',href:'/account',keys:['profilim','hesabım','hesabim','şifre','sifre','parola','çıkış','cikis','oturum','giriş yapamıyorum','giris yapamiyorum'],who:['Kullanıcı kendi hesabında; Admin yetkili kullanıcı hesaplarında işlem yapar.'],steps:['Profil / Hesabım ekranına girin.','Yetkiniz dahilindeki bilgileri kontrol edin.','Şifre/parola işlemlerinde güvenlik kurallarına uyun.'],watch:['3 hatalı giriş gibi güvenlik kuralları devreye girebilir.']},
    {id:'live',module:'Canlı/Pilot Operasyon',screen:'Canlı Kontrol ve Yayın',href:'/home',keys:['canlı','canli','pilot','yayın','yayin','beyaz ekran','servis başlat','scheduled task','waitress','ctrl f5','cache'],who:['Sistem yöneticisi / teknik yetkili'],steps:['Önce son kontrol scriptlerini çalıştırın.','Python compileall ile sözdizimi kontrolü yapın.','Pilot/canlı scheduled task görevini yeniden başlatın.','Tarayıcıda Ctrl+F5 ile cache temizleyerek test edin.'],watch:['base.html hatası tüm sayfaları beyaz ekrana düşürebilir; önce şablon sözdizimini kontrol edin.']}
  ];

  function canonicalUiTextV31_4(value) {
    var out = String(value == null ? '' : value);
    var pairs = [
      ['Dönemler', 'Dönemler'],
      ['Dönemler', 'Dönemler'],
      ['Dönemler', 'Dönemler'],
      ['Başkan Onayları', 'Başkan Onayları'],
      ['Başkan Onayı', 'Başkan Onayı'],
      ['Yayın Ön Onayı', 'Yayın Ön Onayı'],
      ['Dönem İçi Notlar / Gelişim Rehberi', 'Dönem İçi Notlar / Gelişim Rehberi'],
      ['Sorular / Kriterler ekranına', 'Sorular / Kriterler ekranına'],
      ['Sorular / Kriterler sekmesini', 'Sorular / Kriterler sekmesini'],
      ['Performans Yönetimi > Sorular / Kriterler', 'Performans Yönetimi > Sorular / Kriterler'],
      ['Değerlendirme Görevleri ekranına', 'Değerlendirme Görevleri ekranına'],
      ['Performans Yönetimi > Değerlendirme Görevleri', 'Performans Yönetimi > Değerlendirme Görevleri'],
      ['Not Karnesi / Geçmiş Karne Arşivi', 'Not Karnesi / Geçmiş Karne Arşivi'],
      ['Performans Yönetimi > Not Karnesi / Geçmiş Karne Arşivi', 'Performans Yönetimi > Not Karnesi / Geçmiş Karne Arşivi'],
      ['KPI Dashboardu', 'KPI Dashboardu']
    ];
    pairs.forEach(function (p) { out = out.split(p[0]).join(p[1]); });
    return out;
  }
  function response(title, text, links) { return { title:title, text:text, links:toLinks(links || []) }; }
  function formatItem(item, extra) {
    var parts = [];
    parts.push('Anladım. Bu işlem ' + canonicalUiTextV31_4(item.module) + ' içinde, ' + canonicalUiTextV31_4(item.screen) + ' ekranı ile ilgilidir.');
    if (item.who && item.who.length) parts.push('\nKim yapabilir?\n- ' + item.who.join('\n- '));
    if (item.steps && item.steps.length) parts.push('\nAdım adım:\n' + item.steps.map(function (s, i) { return (i + 1) + '. ' + canonicalUiTextV31_4(s); }).join('\n'));
    if (item.watch && item.watch.length) parts.push('\nDikkat:\n- ' + item.watch.map(canonicalUiTextV31_4).join('\n- '));
    parts.push('\nKontrol:\n- İşlemden sonra ilgili ekranda kayıt/durum doğru görünmelidir. Menü görünmüyorsa Rol Matrisi ve kişi bazlı menü iznini kontrol edin.');
    if (extra) parts.push('\n' + extra);
    return response(canonicalUiTextV31_4(item.screen), canonicalUiTextV31_4(parts.join('\n')), [[canonicalUiTextV31_4(item.screen), item.href || '#']]);
  }
  function safetyAnswer(q) {
    var n = normalize(q);
    /* BYS360_ASSISTANT_V32_2_SENSITIVE_CONTENT_GUARD */
    var directAccessAction = /\b(goster|gostermek|ver|ac|goruntule|goruntulemek|gormek|bak|listele|paylas|oku|indir|kopyala)\b/.test(n);
    var sensitiveDataTerm = /\b(performans\s+puan\w*|performans\s+sonuc\w*|puan\w*|notun\w*|notunu\w*|karnesin\w*|karne\w*|amir\s+gorus\w*|yonetici\s+gorus\w*|anket\s+cevab\w*|anket\s+yanit\w*|mesaj\s+icerig\w*|mesaj\s+metn\w*|mesaj\s+yazism\w*|mesajlar\w*|ozel\s+mesaj\w*|tc\b|kimlik\s+no\w*|telefon\w*|adres\w*|maas\w*|dogum\s+tarih\w*)\b/.test(n);
    var wantsSensitiveValue = directAccessAction && sensitiveDataTerm;
    var wantsAdministrativeDecision = /\b(performans puani belirle|performans puanı belirle|isimi sonlandir|işten çıkar|isten cikar|otomatik isten cikar|idari karar ver)\b/.test(n);
    if (wantsSensitiveValue || wantsAdministrativeDecision) {
      return response('Güvenli sınır', 'Bu bilgiyi doğrudan gösteremem. BYS360 Asistanı; performans puanı, amir görüşü, mesaj içeriği, anket cevabı, TC/telefon/adres gibi kişisel veya hassas verileri paylaşmaz.\n\nYapabileceğim şey şu: yetkiniz varsa ilgili modül ekranına yönlendirebilirim. Performans sonucu için Performans Yönetimi > Not Karnesi / Geçmiş Karne Arşivi veya yetkili yönetici ekranı kullanılmalıdır. Yetki yoksa Rol Matrisi ve kişi bazlı menü izni kontrol edilmelidir.', [['Not Karnesi / Geçmiş Karne Arşivi','/performans/v2/faz5/scorecard'], ['Rol Matrisi','/settings/role-matrix'], ['Performans Yönetimi','/performance/dashboard']]);
    }
    return null;
  }
  function smallTalk(q) {
    var n = normalize(q);
    if (/^(merhaba|selam|slm|iyi misin|nasilsin|nasılsın)/.test(n)) return response('Merhaba', 'Merhaba. Personel ekleme, izin, vekâlet, performans dönemi, karne, Başkan Onayı, rol matrisi, destek, anket, KPI/Hedef ve AI Karar Destek konularında sizi doğru ekrana ve işlem sırasına yönlendirebilirim.', [['Ana Sayfa','/home']]);
    if (/(ne yapabilirsin|ne ise yararsin|yardim et|yardım et|bys360 asistan)/.test(n)) return response('BYS360 Asistanı', 'BYS360 içinde gerçek ekran adlarıyla rehberlik yaparım. Sorunuzu günlük dille yazabilirsiniz: “kişi nasıl eklenir”, “dönem açacağım”, “karne görünmüyor”, “menü yok”, “izin nasıl girilir”, “KPI hedef kartı oluşturacağım” gibi.', [['Asistan Bilgi Bankası','/ai-agent/knowledge']]);
    if (/(seni kim gelistirdi|seni kim geliştirdi|kim gelistirdi|kim geliştirdi|kim yapti|kim yaptı|gelistiren kim|geliştiren kim|havva gulsen ozden|havva gülsen özden|gulsen ozden|gülsen özden|havva mi|havva mı|gulsen mi|gülsen mi)/.test(n)) return response('Geliştiren bilgi', 'Ben BYS360 Asistanı’yım. BYS360 için Havva Gülsen Özden (geliştirici) ve Mustafa Bektaş (eş geliştirici) tarafından geliştirildim. Görevim, BYS360 içinde yetkiniz dâhilindeki işlemleri sade, güvenli ve doğru sırayla anlatmak; sizi gerçek ekranlara yönlendirmek ve sistemi daha kolay kullanmanıza yardımcı olmaktır.', []);
    if (/(kaldigimiz yer|kaldığımız yer|devam edelim|son konu)/.test(n)) {
      var st = loadState();
      return response('Kaldığımız yer', st && st.topic ? ('Son konuştuğumuz konu: ' + st.topic + '. Aynı konu üzerinden devam edebiliriz; yapmak istediğiniz adımı yazmanız yeterli.') : 'Bu oturumda kayıtlı son konu bulamadım. Yapmak istediğiniz işlemi yazarsanız kaldığınız yerden yönlendiririm.', []);
    }
    return null;
  }
  function scoreItem(item, qn) {
    var score = 0;
    item.keys.forEach(function (k) {
      var nk = normalize(k);
      if (!nk) return;
      if (qn === nk) score += 40;
      else if (qn.indexOf(nk) >= 0) score += 20 + Math.min(10, nk.length / 4);
      else {
        var words = nk.split(' ').filter(function (w) { return w.length > 2; });
        var hits = words.filter(function (w) { return qn.indexOf(w) >= 0; }).length;
        if (hits >= Math.min(2, words.length)) score += hits * 4;
      }
    });
    if (normalize(item.module + ' ' + item.screen).split(' ').some(function (w) { return w.length > 3 && qn.indexOf(w) >= 0; })) score += 2;
    return score;
  }
  function questionToItem(q) {
    var qn = normalize(q), best = null, bestScore = 0;
    KNOWLEDGE.forEach(function (item) {
      var s = scoreItem(item, qn);
      if (s > bestScore) { bestScore = s; best = item; }
    });
    return bestScore >= 8 ? best : null;
  }
  function detectCurrentItem() {
    var path = normalize(location.pathname), vt = visibleText(), best = null, bestScore = 0;
    KNOWLEDGE.forEach(function (item) {
      var s = 0;
      var href = normalize(item.href || '');
      if (href && (path === href || path.indexOf(href) === 0 || href.indexOf(path) === 0)) s += 35;
      s += scoreItem(item, vt);
      if (s > bestScore) { bestScore = s; best = item; }
    });
    return best || KNOWLEDGE[0];
  }
  function generalAnswer(q) {
    var n = normalize(q);
    if (/(bys360 nedir|bu sistem nedir|sistem ne ise yarar|proje nedir)/.test(n)) return response('BYS360 nedir?', 'BYS360; personel, performans, iletişim, anket, destek, raporlama, KPI/Hedef ve karar destek süreçlerini tek çatı altında yöneten kurumsal dijital yönetim sistemidir. Amaç yalnızca işlem yapmak değil; süreçleri ölçmek, izlemek, raporlamak ve kurumsal hafıza oluşturmaktır.', [['Ana Sayfa','/home']]);
    if (/(sayfa degisince|sayfa değişince|konusmalar silinmesin|konuşmalar silinmesin|sohbet kayboluyor|gecmis kayboluyor|geçmiş kayboluyor)/.test(n)) return response('Konuşma hafızası', 'Bu sürümde konuşma geçmişi aynı tarayıcı sekmesi oturumu boyunca korunur. Sayfa değiştirseniz bile asistan tekrar açıldığında önceki soru-cevaplar geri yüklenmelidir. Oturum/sekme kapanırsa geçmiş temizlenebilir; bu güvenli kullanım için doğru davranıştır.', []);
    return null;
  }
  function answer(q) {
    var safe = safetyAnswer(q); if (safe) return safe;
    var st = smallTalk(q); if (st) return st;
    var gen = generalAnswer(q); if (gen) return gen;
    var n = normalize(q);
    if (/(bu sayfa|bu ekran|burada ne|ne yapilir|ne yapılır|hangi ekran|sayfayı tanıt|sayfayi tanit|neredeyim)/.test(n)) {
      var cur = detectCurrentItem(); saveState(cur.screen); return formatItem(cur, 'Bulunduğunuz sayfayı URL, başlık ve aktif menü bilgisine göre yorumladım.');
    }
    var item = questionToItem(q);
    if (item) { saveState(item.screen); return formatItem(item); }
    var cur2 = detectCurrentItem(); saveState(cur2.screen);
    return response('BYS360 yönlendirme', 'Sorunuzu BYS360 kapsamında yorumladım; doğrudan net eşleşme bulamadım. Bulunduğunuz ekran: ' + cur2.screen + ' (' + cur2.module + ').\n\nDaha net yönlendirme için günlük dille yazabilirsiniz: “kişi nasıl eklenir”, “dönem açacağım”, “karne görünmüyor”, “menü yok”, “izin nasıl girilir”, “destek talebi açacağım”, “KPI hedef kartı oluşturacağım”.\n\nGenel sınır: Yetkiniz olan ekranı anlatırım, işlem sırasını veririm; hassas veri veya idari karar üretmem.', [[cur2.screen, cur2.href || '/home']]);
  }
  // BYS360 Assistant V2 SINGLE-INTELLIGENCE-ENGINE FIX: this layer used to
  // answer every question entirely from the local KNOWLEDGE table above,
  // NEVER calling the server -- meaning the real, authorized, auditable
  // AssistantV2Service backend (see app/ai_agent/routes.py's /api/ask
  // cutover) was silently unreachable from the live chat widget, no matter
  // what the backend did. The local KNOWLEDGE table is now used ONLY as an
  // offline/network-failure fallback (mirrors the exact same fallback
  // pattern already used elsewhere in this widget), matching the mandate's
  // "one intelligence engine" architecture goal.
  function askServerV30(q) {
    var context = {};
    try { context = { path: location.pathname }; } catch (e) {}
    var headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
    var token = csrfToken();
    if (token) { headers['X-CSRFToken'] = token; headers['X-CSRF-Token'] = token; }
    // BYS360 Assistant V2 conversation_id (mandate Phase B/C): sends
    // whatever id this tab last received from the server (or none, on the
    // very first question) -- AssistantV2Service.ask() is the only thing
    // that ever decides whether that id is honored, re-resolved fresh, or
    // discarded as foreign/unknown; this file never assumes it was valid,
    // it only ever stores back exactly what the server returns.
    var body = { question: q, context: context };
    var conversationId = loadConversationId();
    if (conversationId) body.conversation_id = conversationId;
    return fetch('/ai-agent/api/ask', {
      method: 'POST', credentials: 'same-origin', headers: headers,
      body: JSON.stringify(body)
    }).then(function (response) {
      if (!response.ok) throw new Error('ask');
      return response.json();
    }).then(function (payload) {
      var text = payload.answer || payload.reply || payload.message || '';
      if (!text) throw new Error('empty');
      saveConversationId(typeof payload.conversation_id === 'string' ? payload.conversation_id : null);
      var actions = payload.actions || payload.suggestions || [];
      var links = Array.isArray(actions) ? actions.filter(function (a) { return a && (a.href || a.url); }).map(function (a) { return { title: a.title || a.label || 'Ekrana git', href: a.href || a.url }; }) : [];
      var sources = Array.isArray(payload.sources) ? payload.sources.filter(function (s) { return s && s.label; }).map(function (s) { return String(s.label); }) : [];
      var suggestedQuestions = Array.isArray(payload.suggested_questions) ? payload.suggested_questions.filter(function (sq) { return sq; }).map(function (sq) { return String(sq); }) : [];
      var moduleLabel = (typeof payload.module === 'string' && payload.module) ? payload.module : '';
      return { text: text, links: links, sources: sources, suggestedQuestions: suggestedQuestions, moduleLabel: moduleLabel };
    });
  }
  // BYS360 Assistant V2 SINGLE-INTELLIGENCE-ENGINE (mandate Phase B1): on a
  // network/server failure this NEVER falls back to the local KNOWLEDGE
  // table's own business answer -- that would still be a second active
  // answer engine, just gated on failure instead of by default. The only
  // failure response is one fixed, deterministic availability message.
  // KNOWLEDGE/answer()/scoreItem() etc. are kept as dead compatibility data
  // (still exercised by selfTest() below, never by a real user question).
  var SERVER_UNAVAILABLE_MESSAGE = "BYS360 Kurumsal Asistan'a şu anda ulaşılamıyor. Lütfen daha sonra tekrar deneyin.";
  function handleQuestion(q) {
    var root = rootEl();
    if (!root) return false;
    history = loadHistory();
    if (history.length) restoreIntoUi('before-question');
    addUser(root, q);
    askServerV30(q).catch(function () {
      return { text: SERVER_UNAVAILABLE_MESSAGE, links: [], sources: [], suggestedQuestions: [], moduleLabel: '' };
    }).then(function (result) {
      addBot(root, result.text, result.links || [], { sources: result.sources, moduleLabel: result.moduleLabel, suggestedQuestions: result.suggestedQuestions });
    });
    return true;
  }
  function interceptSubmit(event) {
    var root = rootEl();
    if (!root || !event.target || !root.contains(event.target)) return;
    var form = event.target.closest ? event.target.closest('form') : event.target;
    if (!form || !root.contains(form)) return;
    var input = inputEl(root);
    if (!input) return;
    var q = String(input.value || '').trim();
    if (!q) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.stopImmediatePropagation) event.stopImmediatePropagation();
    input.value = '';
    handleQuestion(q);
  }
  function bindForm() {
    var root = rootEl();
    if (!root) return false;
    ensureLog(root);
    var input = inputEl(root);
    var form = formEl(root);
    if (input && form && input.getAttribute('data-v30-enter-bound') !== '1') {
      input.setAttribute('data-v30-enter-bound', '1');
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          form.dispatchEvent(new Event('submit', { bubbles:true, cancelable:true }));
        }
      }, true);
    }
    return true;
  }
  function install() {
    document.removeEventListener('submit', interceptSubmit, true);
    document.addEventListener('submit', interceptSubmit, true);
    bindForm();
    scheduleRestore('install');
  }
  function bootLoop() {
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      install();
      if ((rootEl() && (restoredOnce || !loadHistory().length)) || tries > 80) clearInterval(timer);
    }, 350);
  }
  try {
    var lastRootSeen = null;
    var mo = new MutationObserver(function () {
      if (isRestoring || Date.now() < suppressRestoreUntil) return;
      var root = rootEl();
      if (root !== lastRootSeen) { lastRootSeen = root; scheduleRestore('mutation-root'); return; }
      if (root && !root.querySelector('[data-chat-log], .bys360-am-log, [data-chat-list], .bys360-assistant-chat-log, [data-assistant-log]')) {
        scheduleRestore('mutation-log-missing');
      }
    });
    mo.observe(document.body || document.documentElement, { childList:true, subtree:true });
  } catch (e) {}
  try {
    var oldPush = window.history && window.history.pushState;
    if (oldPush) window.history.pushState = function () { var r = oldPush.apply(window.history, arguments); scheduleRestore('pushState'); return r; };
    var oldReplace = window.history && window.history.replaceState;
    if (oldReplace) window.history.replaceState = function () { var r2 = oldReplace.apply(window.history, arguments); scheduleRestore('replaceState'); return r2; };
  } catch (e2) {}
  document.addEventListener('click', function (ev) {
    var t = ev && ev.target;
    if (t && t.closest && (t.closest('#bys360-assistant-module-root') || t.closest('[data-bys360-assistant-module]'))) {
      window.setTimeout(function () { bindForm(); }, 60);
    }
  }, true);
  // Phase D: the header's "Yeni sohbet" button (bys360_assistant_module.js)
  // only dispatches intent; this file owns the actual conversation state.
  document.addEventListener('bys360-assistant-new-conversation', function () {
    suppressRestoreUntil = Date.now() + 1000;
    clearConversation();
  });
  // Phase B: logout must not let a second user on the same tab inherit the
  // first user's conversation_id/history -- base.html's hidden logoutForm
  // is the one reliable place every logout path (menu link or the
  // top-right dropdown) funnels through.
  try {
    var logoutForm = document.getElementById('logoutForm');
    if (logoutForm) logoutForm.addEventListener('submit', function () { clearConversation(); }, true);
  } catch (eLogout) {}
  window.addEventListener('pagehide', function () { saveHistory(); saveState(lastTopic); });
  window.addEventListener('beforeunload', function () { saveHistory(); saveState(lastTopic); });
  window.addEventListener('pageshow', function () { install(); scheduleRestore('pageshow'); });
  window.addEventListener('popstate', function () { scheduleRestore('popstate'); });
  window.addEventListener('hashchange', function () { scheduleRestore('hashchange'); });
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') saveHistory(); else scheduleRestore('visible'); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { install(); bootLoop(); });
  else { install(); bootLoop(); }

  window.BYS360AssistantStableScrollMemoryV30 = {
    version: VERSION,
    knowledgeCount: KNOWLEDGE.length,
    answer: answer,
    restore: restoreIntoUi,
    clearSession: function () { history = []; saveHistory(); var root = rootEl(); if (root) clearOnlyChatLog(root); },
    selfTest: function () {
      var person = answer('kişi nasıl eklenir').text;
      var mem = answer('sayfa değişince konuşmalar silinmesin').text;
      return {
        ok: person.indexOf('Personel Yönetimi') >= 0 && mem.indexOf('aynı tarayıcı sekmesi') >= 0 && KNOWLEDGE.length >= 30,
        version: VERSION,
        knowledgeCount: KNOWLEDGE.length,
        samplePerson: person.slice(0, 140),
        sampleMemory: mem.slice(0, 140)
      };
    }
  };
  window.BYS360AssistantModule = Object.assign(window.BYS360AssistantModule || {}, {
    stableScrollMemoryVersion: VERSION,
    answerBYS360Question: answer,
    restoreConversation: restoreIntoUi,
    runV30SelfTest: window.BYS360AssistantStableScrollMemoryV30.selfTest
  });
})();
/* BYS360_ASSISTANT_STABLE_SCROLL_MEMORY_V30_END */
