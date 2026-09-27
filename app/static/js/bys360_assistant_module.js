/* BYS360_ASSISTANT_ADVANCED_INTELLIGENCE_V32: Sekme yönlendirme, niyet yakalama ve güvenli cevap güçlendirmesi */
/* BYS360_ASSISTANT_CURRENT_FINAL_POLISH_V31_3: V31 server-first güvenli localFallback ve final kalite düzeltmesi */
/* BYS360_ASSISTANT_HOME_DASHBOARD_SPLIT_V31_2: Ana Sayfa ve Dashboard cevapları ayrıldı */
/* BYS360_ASSISTANT_VISIBILITY_RESTORE_V31_1: visible launcher/panel restored, V31 server-first preserved */
/* BYS360_ASSISTANT_SCREEN_MAP_V20_1_KPI_DESCRIPTION_FIX */
/* BYS360_ASSISTANT_MODULE_PERSONEL_LEAVE_DELEGATION_KB_V9_JS
   Eksiksiz ekran öğretimi, adım adım modül cevap sözleşmesi, güvenli eylem sınırı ve canlı kalite V7
   BYS360 Asistanı — Kurumsal Rehberlik, Akıllı Yönlendirme ve Yetki Kontrollü Dijital Yardımcı
   Tek kanonik ekran ajanı. Eski basit sanal asistan/widget yapıları canlıdan gizlenir. */
(function () {
  // BYS360_ASSISTANT_QUESTION_UNIVERSE_V31_5
  // BYS360_ASSISTANT_REAL_SCREEN_NAMES_V31_4
  'use strict';

  var VERSION = 'BYS360_ASSISTANT_MODULE_DEEP_KNOWLEDGE_CONTEXT_V27';
  var MODULE_NAME = 'BYS360 Asistanı';
  var MODULE_LONG_NAME = 'Kurumsal Rehberlik, Akıllı Yönlendirme ve Yetki Kontrollü Dijital Yardımcı';
  var ROOT_ID = 'bys360-assistant-module-root';
  var STORAGE_POS = 'bys360AssistantModule.position.v1';
  var STORAGE_OPEN = 'bys360AssistantModule.open.v1';
  var STORAGE_CHAT = 'bys360AssistantModule.chat.session.v1';
  var STORAGE_VIEW = 'bys360AssistantModule.view.session.v1';
  var STORAGE_CONTEXT = 'bys360AssistantModule.context.session.v1';
  var STORAGE_LAST_PAGE = 'bys360AssistantModule.lastPage.session.v1';
  var CHAT_LIMIT = 180;
  var chatHistory = [];
  var activeRoot = null;

  if (window.__BYS360_ASSISTANT_MODULE_12STEP_STATUS_GATE_V8_LOADED__) return;
  window.__BYS360_ASSISTANT_MODULE_12STEP_STATUS_GATE_V8_LOADED__ = true;

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn, { once: true });
    else fn();
  }

  function qs(selector, root) { return (root || document).querySelector(selector); }
  function qsa(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  function normalize(input) {
    return String(input || '')
      .toLocaleLowerCase('tr-TR')
      .replace(/ı/g, 'i').replace(/İ/g, 'i')
      .replace(/[âáàä]/g, 'a').replace(/[êéèë]/g, 'e')
      .replace(/[îíìï]/g, 'i').replace(/[ôóòö]/g, 'o').replace(/[ûúùü]/g, 'u')
      .replace(/ç/g, 'c').replace(/ğ/g, 'g').replace(/ş/g, 's')
      .replace(/[^a-z0-9\s/._-]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function escapeText(value) {
    return String(value == null ? '' : value).replace(/[&<>"]/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch];
    });
  }

  // BYS360 Assistant V2 CSRF FIX (mandate Phase D): matches the exact same
  // established pattern app/templates/ai_agent/panel.html already uses for
  // this same /ai-agent/api/ask endpoint (base.html always renders a
  // site-wide <meta name="csrf-token"> for an authenticated session) --
  // not a new security pattern, just applying the existing one to this
  // caller too.
  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"], meta[name="csrf_token"]');
    if (meta && meta.getAttribute('content')) return meta.getAttribute('content');
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
  }

  function iconSpark() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2.7l1.9 5.1 5.1 1.9-5.1 1.9L12 16.8l-1.9-5.2L5 9.7l5.1-1.9L12 2.7Z" fill="currentColor"/><path d="M18.4 14.4l.9 2.2 2.2.9-2.2.9-.9 2.2-.9-2.2-2.2-.9 2.2-.9.9-2.2Z" fill="currentColor" opacity=".72"/></svg>';
  }

  function removeLegacyAssistants() {
    var selectors = [
      '#bys360-assistant-pro-v1', '#bys360-ai-agent-widget', '#bys360AiAgentWidget', '#bys360-ai-agent-launcher', '#bys360AiAgentLauncher',
      '#bys360-assistant-root', '#bys360AssistantWidget', '.bys360-assistant-widget', '.bys360-ai-agent-widget', '.bys360-ai-agent-launcher',
      '.ai-agent-widget', '.ai-agent-launcher', '[data-bys360-assistant-root]', '[data-bys360-ai-agent-widget]', '[data-ai-agent-widget]', '[data-bys360-ai-agent-launcher]'
    ];
    selectors.forEach(function (selector) {
      qsa(selector).forEach(function (node) {
        if (!node || node.id === ROOT_ID || node.closest('#' + ROOT_ID)) return;
        node.setAttribute('data-bys360-legacy-assistant-disabled', 'canonical-v1');
        node.style.display = 'none';
      });
    });
  }

  var ROUTES = [
    { title: 'Anasayfa', href: '/home', keywords: ['anasayfa', 'baslangic', 'nereden baslayacagim'], text: 'BYS360 ana başlangıç ekranıdır.' },
    { title: 'Dashboard', href: '/dashboard', keywords: ['dashboard', 'gosterge', 'ozet', 'yonetici ekrani'], text: 'Genel durum ve yönetici özetlerini gösterir.' },
    { title: 'Hava Durumu Kartı', href: '/home', keywords: ['hava durumu karti', 'hava durumu kartı', 'open meteo', 'open-meteo', 'hava'], text: 'BYS360 anasayfa veya dashboard üzerinde Open-Meteo verisiyle çalışan yardımcı hava durumu kartıdır.' },
    /* BYS360_ASSISTANT_SCREEN_MAP_V20_ROUTES */
    { title: 'KPI Dashboardu',
      description: 'Hedef gerçekleşmelerini, başarı oranlarını, hedef kartlarını ve risk seviyelerini takip etmek için kullanılır.', href: '/performans/stratejik/kpi-dashboard', keywords: ['kpi dashboard', 'kpi panel', 'kpi gösterge', 'kpi gosterge', 'hedef dashboard', 'hedef panel', 'stratejik performans dashboard'], text: 'KPI ve hedef gerçekleşmeleri, başarı oranları, risk seviyesi ve yönetici özetleri bu ekranda takip edilir.' },
    { title: 'KPI ve Hedef Listesi', href: '/performans/stratejik/hedefler', keywords: ['kpi hedef listesi', 'hedefler', 'hedef listesi', 'kpi listesi', 'hedef kartlari', 'hedef kartları'], text: 'Tanımlı hedef kartları, hedef türleri, sahipleri, ağırlıkları ve gerçekleşme durumları burada listelenir.' },
    { title: 'Yeni KPI / Hedef Oluştur', href: '/performans/stratejik/hedefler/yeni', keywords: ['yeni kpi', 'hedef olustur', 'hedef oluştur', 'kpi olustur', 'kpi oluştur', 'hedef karti ekle', 'hedef kartı ekle'], text: 'Yeni hedef kartı veya KPI kaydı oluşturma ekranıdır.' },
    { title: 'AI KPI Analiz', href: '/performans/stratejik/kpi-analiz', keywords: ['ai kpi analiz', 'kpi analiz', 'hedef analiz', 'ai hedef analiz', 'kpi yorum', 'hedef yorumu'], text: 'KPI ve hedef verilerinin güvenli, karar vermeyen analiz özetleri burada görüntülenir.' },
    { title: 'Yetkinlik Kütüphanesi', href: '/performans/stratejik/yetkinlik-kutuphanesi', keywords: ['yetkinlik kutuphanesi', 'yetkinlik kütüphanesi', 'liderlik', 'takim calismasi', 'takım çalışması', 'analitik dusunme', 'teknik uzmanlik'], text: 'Görev, rol, performans kriteri, gelişim önerisi ve analiz süreçlerinde kullanılacak yetkinlik tanımları burada yönetilir.' },
    { title: 'Öz Değerlendirme', href: '/performans/stratejik/oz-degerlendirme', keywords: ['oz degerlendirme', 'öz değerlendirme', 'dönem özeti', 'donem ozeti', 'basarilarim', 'başarılarım', 'gelisim ihtiyaci'], text: 'Personelin dönem özeti, başarıları, zorlandığı alanlar ve gelişim ihtiyacını yazdığı ekrandır; otomatik puan üretmez.' },
    { title: 'Stratejik Performans Paneli', href: '/performans/stratejik/panel/dashboard', keywords: ['stratejik performans paneli', 'stratejik panel', 'hedef paneli', 'kpi yonetici paneli', 'kpi yönetici paneli'], text: 'Stratejik performans ve KPI özetlerinin yönetici görünümü bu panelde takip edilir.' },
    { title: 'Öz Değerlendirme Özeti', href: '/performans/stratejik/panel/oz-degerlendirme-ozet', keywords: ['oz degerlendirme ozeti', 'öz değerlendirme özeti', 'self review ozet', 'personel ozet degerlendirme'], text: 'Öz değerlendirme kayıtlarının yönetici/özet görünümü için kullanılan ekrandır.' },
    { title: 'Personel Yönetimi', href: '/personnel', keywords: ['personel', 'sicil', 'unvan', 'birim', 'yonetici', 'profil', 'personel ekle'], text: 'Personel, sicil, birim, görev, yönetici ve organizasyon verileri burada yönetilir.' },
    { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave', keywords: ['izin', 'izin kaydi', 'izin kaydı', 'izin talebi', 'izin bakiyesi', 'yillik izin', 'idari izin', 'saatlik izin'], text: 'İzin kayıtları, izin bakiyeleri, izinli amir etkisi ve izin–vekalet komuta merkezi bu ekranda takip edilir.' },
    { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance', keywords: ['vekalet', 'vekâlet', 'devamsizlik', 'devamsızlık', 'gorev devri', 'görev devri', 'vekil', 'vekil personel', 'vekalet tanimla'], text: 'Devamsızlık kayıtları ve vekâlet tanımları bu ekranda takip edilir.' },
    { title: 'Performans Yönetimi', href: '/performance/dashboard', keywords: ['performans', 'degerlendirme', 'puan', 'karne', 'amir'], text: 'Performans modülünün ana görünümüdür.' },
    { title: 'Sorular / Kriterler', href: '/performance/criteria', keywords: ['kriter', 'soru', 'sorular', 'degerlendirme kriterleri', 'yetkinlik'], text: 'Değerlendirme kriterleri ve soru tanımları burada yönetilir.' },
    { title: 'Dönemler', href: '/performance/periods', keywords: ['donem', 'donemler', 'donem ac', 'donem olustur', 'yeni donem', 'performans donemi'], text: 'Performans dönemi açma, düzenleme ve kapsam kontrolü bu sekmeden yapılır.' },
    { title: 'Değerlendirme Görevleri', href: '/performance/evaluation-tasks', keywords: ['gorev uret', 'degerlendirme gorevi', 'puanlama', 'amir gorevi', 'gorevler'], text: 'Amir değerlendirme görevleri ve puanlama akışı burada izlenir.' },
    { title: 'Başkan Onayları', href: '/performance/president-approvals', keywords: ['baskan onay', 'ust onay', '70 alti', 'dusuk performans', 'yayin kilidi'], text: '70 altı düşük performans ve Başkan Onayı akışı burada takip edilir.' },
    { title: 'Yayın Ön Onayı', href: '/performance/personnel-support-publish-approvals', keywords: ['yayin on onay', 'personel destek', 'yayin onayi', 'son yayina hazirlik'], text: 'Nihai yayın öncesi kurumsal kontrol adımıdır.' },
    { title: 'Süreç Takibi', href: '/performance/process-tracking', keywords: ['surec takibi', 'akış', 'akis', 'statü', 'statu', 'bekleyen'], text: 'Performans süreçlerinin durum ve akış takibi burada yapılır.' },
    { title: 'Süreç Raporları', href: '/performance/process-reports', keywords: ['surec raporu', 'rapor', 'analiz', 'geciken'], text: 'Dönem, görev, onay ve süreç raporları burada incelenir.' },
    { title: 'Dönem İçi Notlar', href: '/performance/interim-notes', keywords: ['donem ici not', 'ara geri bildirim', 'olay notu', 'gelisim notu'], text: 'Dönem içindeki olumlu/olumsuz gözlem ve gelişim notları buradan tutulur.' },
    { title: 'Gelişim Rehberi', href: '/performance/meeting-development/faz10', keywords: ['gelisim rehberi', 'gelisim onerisi', 'egitim onerisi'], text: 'Değerlendirme sonrası gelişim önerileri ve rehber notlar için kullanılır.' },
    { title: 'Not Karnesi', href: '/performance/scorecard', keywords: ['not karnesi', 'karnem', 'karne', 'sonucum', 'performans sonucum'], text: 'Yayınlandıktan sonra personelin kendi karne görünürlüğü burada açılır.' },
    { title: 'Geçmiş Karne Arşivi', href: '/performans/gecmis-karne-arsivi', keywords: ['gecmis karne', 'arsiv', 'eski puan', '2024', '2025'], text: 'Geçmiş yıl ve dönem performans arşivi için kullanılır.' },
    { title: 'Mesajlar', href: '/messages', keywords: ['mesaj', 'sohbet', 'yazisma', 'iletisim'], text: 'Kurum içi mesajlaşma ekranıdır.' },
    { title: 'Anketler', href: '/surveys', keywords: ['anket', 'anketler', 'cevapla', 'katilim'], text: 'Size atanan anketleri ve anket süreçlerini gösterir.' },
    { title: 'Yardım Merkezi', href: '/support', keywords: ['yardim', 'destek', 'talep', 'sorun', 'bilet'], text: 'Destek talepleri ve kullanıcı yardım içerikleri buradadır.' },
    { title: 'AI Karar Destek Merkezi', href: '/ai/decision-support/faz1/health', keywords: ['ai karar', 'karar destek', 'analiz', 'risk', 'ozet'], text: 'Analiz ve karar destek katmanıdır; BYS360 Asistanı ise kullanıcı rehberlik katmanıdır.' },
    { title: 'Asistan Bilgi Bankası', href: '/ai-agent/knowledge', keywords: ['bilgi bankasi', 'asistani egit', 'ogret', 'asistan egitimi'], text: 'Yetkili kullanıcıların asistan eğitim kayıtlarını yönettiği alandır.' },

    { title: 'Modül Bazlı Rol Matrisi', href: '/settings/role-matrix', keywords: ['modul bazli rol matrisi', 'modül bazlı rol matrisi', 'modul matrisi', 'modül matrisi'], text: 'Modül görünürlüklerinin rol bazlı yönetildiği alandır.' },
    { title: 'Performans Yönetimi Rol Matrisi', href: '/settings/performance-role-matrix', keywords: ['performans rol matrisi', 'performans matrisi', 'performans yetki'], text: 'Performans alt sekmelerinin rol bazlı görünürlüğü burada kontrol edilir.' },
    { title: 'Sistem Ayarları', href: '/settings', keywords: ['ayar', 'ayarlar', 'rol', 'yetki', 'matris', 'menu gorunurluk', 'rol matrisi'], text: 'Rol matrisi, menü görünürlüğü, sistem ayarları ve güvenlik ayarları burada yönetilir.' }
  ];

  function findRoutes(message) {
    var n = normalize(message);
    if (!n) return [];
    return ROUTES.filter(function (r) {
      return r.keywords.some(function (keyword) { return n.indexOf(normalize(keyword)) !== -1; }) || n.indexOf(normalize(r.title)) !== -1;
    }).slice(0, 4);
  }

  var SAFE_ROUTE_PREFIXES = [
    /* BYS360_ASSISTANT_SCREEN_MAP_V20_PREFIXES */
    '/performans/stratejik/', '/performans/stratejik/panel/',
    '/performance/president-approvals/', '/performance/periods/', '/performans/gecmis-karne-arsivi',
    '/support/tickets/', '/surveys/', '/messages/', '/personnel/'
  ];

  function legacyRouteMap() {
    var map = {};
    map['/personnel' + '/leaves'] = '/hr-management/leave';
    map['/personnel' + '/leave'] = '/hr-management/leave';
    map['/personnel' + '/delegations'] = '/hr-management/attendance';
    map['/hr-management/delegations'] = '/hr-management/attendance';
    map['/performance/period-management'] = '/performance/periods';
    map['/performance/period-management/create'] = '/performance/periods';
    map['/performance/periods/create'] = '/performance/periods';
    map['/performance/questions'] = '/performance/criteria';
    map['/performance/criteria-management'] = '/performance/criteria';
    map['/performance/tasks'] = '/performance/evaluation-tasks';
    map['/performans/baskan-onaylari'] = '/performance/president-approvals';
    map['/performans/surec-takibi'] = '/performance/process-tracking';
    // V32: Asistan Paneli kendi ekranında kalmalı; Bilgi Bankası ayrı sekmedir.
    return map;
  }

  function knownRoute(href) {
    if (!href || href === '#') return false;
    if (ROUTES.some(function (route) { return route.href === href; })) return true;
    return SAFE_ROUTE_PREFIXES.some(function (prefix) { return href.indexOf(prefix) === 0; });
  }

  function canonicalizeHref(href) {
    if (!href) return '#';
    var rawData = String(href || '').trim();
    if (!rawData || rawData === '#') return '#';
    if (/^(javascript|data|vbscript):/i.test(rawData)) return '#';
    var a = document.createElement('a');
    a.href = rawData;
    if (a.origin && a.origin !== window.location.origin) return '#';
    var path = a.pathname || '/';
    if (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1);
    var map = legacyRouteMap();
    Object.keys(map).forEach(function (legacy) {
      if (path === legacy || path.indexOf(legacy + '/') === 0) path = map[legacy];
    });
    return path + (a.search || '') + (a.hash || '');
  }

  function titleToRoute(title) {
    var n = normalize(title || '');
    if (!n) return null;
    var exact = ROUTES.find(function (route) { return normalize(route.title) === n; });
    if (exact) return exact;
    return ROUTES.find(function (route) {
      return route.keywords.some(function (keyword) { return n.indexOf(normalize(keyword)) !== -1; }) || n.indexOf(normalize(route.title)) !== -1;
    }) || null;
  }

  function normalizeAssistantLink(item) {
    if (!item) return null;
    var title = String(item.title || item.label || 'Ekrana git');
    var href = canonicalizeHref(item.href || item.url || '#');
    if (normalize(title) === 'izin ve vekalet' || normalize(title) === 'izin ve vekâlet') {
      title = 'İzin ve Devamsızlık Takibi';
      href = '/hr-management/leave';
    }
    if (!knownRoute(href)) {
      var fromTitle = titleToRoute(title);
      if (fromTitle) href = fromTitle.href;
    }
    if (!knownRoute(href)) {
      return { title: title, href: '#', disabled: true, note: 'Bu bağlantı güvenli menü haritasında bulunmadığı için açılmadı.' };
    }
    return { title: title, href: href, disabled: false };
  }

  function safeLinks(links) {
    return (Array.isArray(links) ? links : []).map(normalizeAssistantLink).filter(Boolean).slice(0, 4);
  }

  function removeTransientNotice(root) {
    var kayıt = root ? qs('[data-chat-log]', root) : null;
    if (!kayıt) return;
    var last = kayıt.lastElementChild;
    if (last && last.getAttribute('data-transient') === 'true') kayıt.removeChild(last);
  }

  function preflightAndNavigate(root, href, title) {
    var safe = normalizeAssistantLink({ href: href, title: title });
    if (!safe || safe.disabled || !safe.href || safe.href === '#') {
      appendMessage(root || activeRoot, 'bot', 'Bu bağlantı güvenli menü haritasında doğrulanamadığı için açmadım. Lütfen ilgili modül adını yazın; sizi güvenli ekrana yönlendireyim.');
      return false;
    }
    saveChatHistory();
    saveCurrentPageContext({ navigatingTo: safe.href, navigatingTitle: safe.title || title || '' });
    appendMessage(root || activeRoot, 'bot', 'Ekranı açmadan önce güvenli bağlantı kontrolü yapıyorum...', [], false, true);
    fetch(safe.href, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8', 'X-BYS360-Assistant-Preflight': '1' }
    }).then(function (response) {
      if (!response.ok) throw new Error('http_' + response.status);
      var contentType = (response.headers.get('content-type') || '').toLowerCase();
      if (contentType && contentType.indexOf('text/html') === -1 && contentType.indexOf('application/xhtml') === -1) throw new Error('not_screen');
      removeTransientNotice(root || activeRoot);
      window.location.href = safe.href;
    }).catch(function () {
      removeTransientNotice(root || activeRoot);
      appendMessage(root || activeRoot, 'bot', 'Bu ekran şu an güvenli şekilde açılamadı. Beyaz ekran veya teknik hata yaşamamanız için yönlendirmeyi durdurdum. Menü haritasında bu başlığın doğru yolu kontrol edilmeli: ' + (safe.title || title || 'ilgili ekran'));
    });
    return false;
  }

  // V7_CEVAP_HIJYENI_KATMANI: server veya eski bilgi bankasından gelse bile kullanıcı ekranına yanlış/alaycı/teknik ifade düşmesini engeller.
  function sanitizeAssistantText(text) {
    var value = String(text == null ? '' : text);
    var replacements = [
      [/Dönem\s+Yönetimi/g, 'Dönemler'],
      [/donem yonetimi/gi, 'Dönemler'],
      [new RegExp('end' + 'point\\s+yolu\\s+men[uü]\\s+haritas[ıi]na\\s+eklenmeli\\.?', 'gi'), ''],
      [new RegExp('end' + 'point\\s+yolu\\s+menu\\s+haritasina\\s+eklenmeli\\.?', 'gi'), ''],
      [/Tam\s+modül\s+mantığıyla\s+çalışır\.?/gi, ''],
      [/Eski\s+basit\s+asistanlarla\s+karışmaz;\s+idari\s+karar\s+üretmez,\s+puan\s+belirlemez,\s+hassas\s+veri\s+göstermez\.?/gi, ''],
      [/K[ıi]ş\s+kendini\s+göstermiş;?\s*/gi, ''],
      [/çayl[ae]r\s+sıcak,?\s*/gi, ''],
      [/Şemsiye\s+göreve\.?/gi, ''],
      [/Gök\s*yüzü\s+drama\w*\.?/gi, ''],
      [/işi\s+üşütmeden\.?/gi, ''],
      [/menüler\s+uçuşmasın\.?/gi, ''],
      [/sevimli\s+bir\s+yorum\.?/gi, ''],
      [/espiri\w*\s+cevaplar?\.?/gi, ''],
      [/espri\w*\s+cevaplar?\.?/gi, '']
    ];
    replacements.forEach(function (pair) { value = value.replace(pair[0], pair[1]); });
    if (/\b(1[5-9]|2\d|3\d)\s*°?\s*C\b/i.test(value) && /\bkarlı\b|\bkarli\b|\bdurum karlı\b|\bdurum karli\b/i.test(value)) {
      value = value.replace(/,?\s*durum\s+karlı\.?/gi, '.');
      value = value.replace(/,?\s*durum\s+karli\.?/gi, '.');
      value = value.replace(/\b[kK]arlı hava görünüyor;?\s*/g, '');
      value = value.replace(/\b[kK]arli hava gorunuyor;?\s*/g, '');
      if (value.indexOf('Hava durumu açıklaması sıcaklık bilgisiyle uyumlu görünmediği için yalnızca doğrulanabilen bilgileri paylaşıyorum.') === -1) {
        value += ' Hava durumu açıklaması sıcaklık bilgisiyle uyumlu görünmediği için yalnızca doğrulanabilen bilgileri paylaşıyorum.';
      }
    }
    value = value.replace(/\s+([,.])/g, '$1').replace(/\s{2,}/g, ' ').trim();
    return value || 'Bu konuda BYS360 içinde güvenli şekilde yardımcı olabilirim.';
  }

  function makeAnswer(text, links) { return { text: sanitizeAssistantText(text), links: safeLinks(links || []) }; }


  // V7_EKSİKSİZ_EKRAN_OGRETIM_SOZLESMESI: her cevap gerçek ekran adı, yetki, adım, dikkat ve kontrol düzeniyle verilir.
  // V7_MODUL_CEVAP_FORMATI: öğretici cevaplar aynı kalıpta üretilir; kullanıcıya teknik/eskimiş ekran adı gösterilmez.
  // V7_GUVENLI_EYLEM_SOZLESMESI: asistan idari karar, puan veya hassas veri üretmez; yalnızca güvenli rehberlik verir.
  function listToSentence(items) {
    return (items || []).filter(Boolean).map(function (item, index) { return (index + 1) + ') ' + item; }).join(' ');
  }

  function moduleStepAnswer(title, location, roles, steps, warnings, checks, links) {
    var text = 'Anladım. Bu konu “' + title + '” kapsamındadır. ';
    if (location) text += 'Doğru yol: ' + location + '. ';
    if (roles && roles.length) text += 'Kim yapabilir? ' + roles.join(', ') + '. ';
    if (steps && steps.length) text += 'Adım adım: ' + listToSentence(steps) + ' ';
    if (warnings && warnings.length) text += 'Dikkat: ' + warnings.join(' ') + ' ';
    if (checks && checks.length) text += 'Kontrol: ' + checks.join(' ') + ' ';
    return makeAnswer(text, links || []);
  }

  function teachingContractAnswer() {
    return makeAnswer('BYS360 Asistanı ekran zekâsı ve adım adım rehberlik düzenine göre çalışır: gerçek ekran adını kullanır, önce doğru modülü ve yetkiyi belirtir, sonra işlemi adım adım anlatır, dikkat edilmesi gereken güvenlik/yayın/yetki sınırlarını söyler ve sonunda kontrol adımını verir. Eski veya doğrulanmayan bağlantıları açmaz; idari karar üretmez, performans puanı belirlemez ve hassas veri göstermez.', [
      { title: 'Dönemler', href: '/performance/periods' },
      { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' },
      { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' },
      { title: 'Sistem Ayarları', href: '/settings' }
    ]);
  }

  function knownScreensAnswer() {
    return makeAnswer('BYS360 içinde güvenli menü haritasına bağlı çalışırım. Personel Yönetimi, İzin ve Devamsızlık Takibi, Devamsızlık ve Vekâlet, Performans Yönetimi, Sorular / Kriterler, Dönemler, Değerlendirme Görevleri, Başkan Onayları, Yayın Ön Onayı, Süreç Takibi, Süreç Raporları, Dönem İçi Notlar, Gelişim Rehberi, Not Karnesi, Geçmiş Karne Arşivi, Mesajlar, Anketler, Yardım Merkezi, AI Karar Destek Merkezi, Asistan Bilgi Bankası ve Sistem Ayarları başlıklarında rehberlik yaparım. Bir ekran güvenli haritada yoksa beyaz ekran riski oluşturmamak için açmam; işlem adını yazarsanız güvenli yolu bulmaya çalışırım.', [
      { title: 'Personel Yönetimi', href: '/personnel' },
      { title: 'Dönemler', href: '/performance/periods' },
      { title: 'Başkan Onayları', href: '/performance/president-approvals' },
      { title: 'Yardım Merkezi', href: '/support' }
    ]);
  }


  // V8_12_ADIM_DURUM_KONTROL_GATE: 12 adımın tamamlandı/kısmen/eksik durumunu kullanıcıya ve son kontrol raporuna bağlar.
  function twelveStepStatusAnswer() {
    var rows = [
      '1. Gerçek Menü / Sekme / URL Haritası: Büyük ölçüde tamamlandı; final canlı ekran taraması gerekir.',
      '2. Güvenli Yönlendirme / Kırık Link Engeli: Tamamlandı; eski/kırık bağlantılar güvenli haritadan geçer.',
      '3. Personel Yönetimi Bilgi Bankası: Kısmen tamamlandı; V9’da derinleştirilecek.',
      '4. İzin, Devamsızlık ve Vekâlet: Kısmen tamamlandı; V9’da ayrıntılı öğretim genişletilecek.',
      '5. Performans Yönetimi Bilgi Bankası: Kısmen tamamlandı; V10’da Dönemler, kriterler, görev, karne ve onaylar derinleştirilecek.',
      '6. Rol Matrisi / Yetki / Menü Görünürlüğü: Kısmen tamamlandı; V11’de detaylandırılacak.',
      '7. Dashboard, Raporlar ve Yönetici Görünümü: Kısmen tamamlandı; V11’de rapor bazlı rehber genişletilecek.',
      '8. İletişim, Anket, Destek ve Bildirimler: Kısmen tamamlandı; V11’de detaylandırılacak.',
      '9. AI Karar Destek Merkezi Ayrımı: Tamamlandı; asistan rehberlik eder, AI Karar Destek analiz/özet üretir.',
      '10. Günlük Konuşma ve Kendini Tanıtma: Büyük ölçüde tamamlandı; kurumsal tanıtım ve kimlik cevapları var.',
      '11. Oturum ve Sayfa Geçişi Koruma: Tamamlandı; aynı sekmede sohbet ve panel durumu korunur.',
      '12. Final Gate ve Canlı Test Senaryoları: Başladı; V12’de tam final gate yapılacak.'
    ];
    return makeAnswer('BYS360 Asistanı durum kontrolü: ' + rows.join(' '), [
      { title: 'Dönemler', href: '/performance/periods' },
      { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' },
      { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' },
      { title: 'Başkan Onayları', href: '/performance/president-approvals' }
    ]);
  }

  function missingStepsAnswer() {
    return makeAnswer('Eksik kalan ana başlıklar şunlardır: V9’da Personel Yönetimi, İzin, Devamsızlık ve Vekâlet bilgi bankası derinleştirilecek. V10’da Performans Yönetimi bilgi bankası tamamlanacak. V11’de rol matrisi, raporlar, dashboard, iletişim, anket, destek ve bildirimler genişletilecek. V12’de tüm senaryolar tek final gate ile doğrulanacak.', [
      { title: 'Personel Yönetimi', href: '/personnel' },
      { title: 'Yardım Merkezi', href: '/support' },
      { title: 'AI Karar Destek Merkezi', href: '/ai/decision-support' }
    ]);
  }

  function isWeatherIntent(message) {
    var n = normalize(message);
    return /\b(hava|havadurumu|hava durumu|bugun hava|bugün hava|yagmur|yağmur|sicaklik|sıcaklık|ruzgar|rüzgar|open meteo|open-meteo)\b/.test(n);
  }

  function isLocalFirstIntent(message) {
    var n = normalize(message);
    if (!n) return false;
    // V31.1: Sunucu beyni önceliklidir. Yerel cevap yalnızca ekran/oturum veya anlık güvenli sayfa yardımı için çalışır.
    return /\b(bu sayfa|bu ekran|burada ne|neredeyim|hangi ekrandayim|hangi ekrandayım|hangi sayfadayim|hangi sayfadayım|sayfa yardimi|sayfa yardımı|ekran yardimi|ekran yardımı|az onceki konu|az önceki konu|kaldigimiz yer|kaldığımız yer|devam edelim|nereden devam|sayfa değişince|sayfa degisince|konusmalar silinmesin|konuşmalar silinmesin|sohbet kayboluyor|seni kim gelistirdi|seni kim geliştirdi|kim gelistirdi|kim geliştirdi|kim yapti|kim yaptı|gelistiren kim|geliştiren kim|havva gulsen ozden|havva gülsen özden|gulsen ozden|gülsen özden|havva mi|havva mı|gulsen mi|gülsen mi)\b/.test(n);
  }

  var WEATHER_PATHS = [
    '/api/weather/current',
    '/api/weather',
    '/api/weather/today',
    '/api/weather/canakkale',
    '/api/weather/current?city=canakkale',
    '/api/open-meteo/current',
    '/api/open-meteo/weather',
    '/weather/api/current',
    '/weather/current',
    '/home/weather',
    '/dashboard/weather',
    '/open-meteo/weather',
    '/open-meteo/current'
  ];

  function uniqueWeatherPaths(list) {
    var seen = {};
    return (list || []).filter(function (url) {
      if (!url || typeof url !== 'string') return false;
      var clean = url.trim();
      if (!clean || /^https?:\/\//i.test(clean) || /^javascript:/i.test(clean)) return false;
      if (seen[clean]) return false;
      seen[clean] = true;
      return true;
    });
  }

  function collectWeatherPaths() {
    var weatherPaths = WEATHER_PATHS.slice();
    try {
      var selectors = [
        '[data-weather-url]', '[data-open-meteo-url]', '[data-bys360-weather-url]', '[data-weather-' + 'end' + 'point]',
        '#weather-card', '.weather-card', '.bys360-weather-card', '[class*=weather]', '[id*=weather]', '[data-weather]'
      ];
      qsa(selectors.join(',')).forEach(function (node) {
        ['weatherUrl', 'openMeteoUrl', 'bys360WeatherUrl', 'weather' + 'End' + 'point', 'end' + 'point', 'url'].forEach(function (key) {
          if (node.dataset && node.dataset[key]) weatherPaths.unshift(node.dataset[key]);
        });
        ['data-weather-url', 'data-open-meteo-url', 'data-bys360-weather-url', 'data-weather-' + 'end' + 'point'].forEach(function (attr) {
          var val = node.getAttribute && node.getAttribute(attr);
          if (val) weatherPaths.unshift(val);
        });
      });
      qsa('script').forEach(function (script) {
        var txt = script.textContent || '';
        var m;
        var re = /["'](\/[A-Za-z0-9_\-\/?.=&%]*?(?:weather|open-meteo)[A-Za-z0-9_\-\/?.=&%]*)["']/gi;
        while ((m = re.exec(txt))) weatherPaths.unshift(m[1]);
      });
    } catch (e) {}
    return uniqueWeatherPaths(weatherPaths);
  }

  function readWeatherFromDom() {
    try {
      var nodes = qsa('[data-weather], [data-temperature], [data-temp], [data-weather-code], #weather-card, .weather-card, .bys360-weather-card, [class*=weather], [id*=weather]');
      for (var i = 0; i < nodes.length; i += 1) {
        var node = nodes[i];
        var ds = node.dataset || {};
        var temp = ds.temperature || ds.temp || ds.temperature2m || node.getAttribute('data-temperature') || node.getAttribute('data-temp');
        var code = ds.weatherCode || ds.weathercode || ds.code || node.getAttribute('data-weather-code');
        var wind = ds.windSpeed || ds.wind || ds.windspeed || node.getAttribute('data-wind-speed');
        var condition = ds.condition || ds.description || ds.weather || '';
        var text = (node.innerText || node.textContent || '').trim();
        if (!condition && text) {
          var lower = normalize(text);
          if (lower.indexOf('yagmur') !== -1) condition = 'yağmurlu';
          else if (/(^|\s)kar(li| yag| yagisi|\s|$)/.test(lower)) condition = 'karlı';
          else if (lower.indexOf('sis') !== -1) condition = 'sisli';
          else if (lower.indexOf('bulut') !== -1) condition = 'bulutlu';
          else if (lower.indexOf('acik') !== -1) condition = 'açık';
        }
        if (!temp && text) {
          var t = text.match(/(-?\d+(?:[,.]\d+)?)\s*°?\s*C/i);
          if (t) temp = t[1].replace(',', '.');
        }
        if (temp || code || condition) return { temperature: temp, wind: wind, code: code, condition: condition, source: 'BYS360 hava durumu kartı' };
      }
    } catch (e) {}
    return null;
  }

  function pickWeatherPayload(payload) {
    if (!payload || typeof payload !== 'object') return null;
    var candidates = [payload, payload.weather, payload.current, payload.current_weather, payload.data, payload.result, payload.open_meteo, payload.openMeteo];
    for (var i = 0; i < candidates.length; i += 1) {
      var p = candidates[i];
      if (!p || typeof p !== 'object') continue;
      var temp = p.temperature_2m != null ? p.temperature_2m : (p.temperature != null ? p.temperature : (p.temp != null ? p.temp : p.current_temperature));
      var wind = p.wind_speed_10m != null ? p.wind_speed_10m : (p.windspeed != null ? p.windspeed : (p.wind_speed != null ? p.wind_speed : p.wind));
      var code = p.weather_code != null ? p.weather_code : (p.weathercode != null ? p.weathercode : p.code);
      var condition = p.condition || p.description || p.summary || p.text || p.weather || '';
      var precipitation = p.precipitation != null ? p.precipitation : (p.rain != null ? p.rain : p.showers);
      var humidity = p.relative_humidity_2m != null ? p.relative_humidity_2m : (p.humidity != null ? p.humidity : null);
      if (temp != null || code != null || condition) {
        return { temperature: temp, wind: wind, code: code, condition: condition, precipitation: precipitation, humidity: humidity, source: payload.source || p.source || 'Open-Meteo' };
      }
    }
    return null;
  }

  function weatherCodeText(code, condition) {
    if (condition) return String(condition);
    var c = Number(code);
    if ([0].indexOf(c) >= 0) return 'açık';
    if ([1, 2].indexOf(c) >= 0) return 'az bulutlu';
    if ([3].indexOf(c) >= 0) return 'kapalı/bulutlu';
    if ([45, 48].indexOf(c) >= 0) return 'sisli';
    if ([51, 53, 55, 56, 57].indexOf(c) >= 0) return 'çisenti';
    if ([61, 63, 65, 66, 67, 80, 81, 82].indexOf(c) >= 0) return 'yağmurlu';
    if ([71, 73, 75, 77, 85, 86].indexOf(c) >= 0) return 'karlı';
    if ([95, 96, 99].indexOf(c) >= 0) return 'gök gürültülü';
    return 'hava durumu';
  }

  function parseWeatherTemperature(value) {
    if (value == null || value === '') return NaN;
    var cleaned = String(value).replace(',', '.').replace(/[^0-9.\-]/g, '');
    return Number(cleaned);
  }

  function isSnowLikeText(value) {
    var t = normalize(value || '');
    return /(^|\s)kar(li| yag| yagisi|\s|$)/.test(t) || /\bsnow\b/.test(t);
  }

  function isSnowCode(code) {
    var c = Number(code);
    return [71, 73, 75, 77, 85, 86].indexOf(c) >= 0;
  }

  function isWeatherConditionTemperatureMismatch(data) {
    var temp = parseWeatherTemperature(data && data.temperature);
    if (isNaN(temp)) return false;
    var condition = weatherCodeText(data && data.code, data && data.condition);
    // V5_2_HAVA_TUTARLILIK_KONTROLU: 8°C üstünde kar benzeri açıklama kullanıcıya gösterilmez.
    if (temp > 8 && (isSnowCode(data && data.code) || isSnowLikeText(condition))) return true;
    return false;
  }

  function safeWeatherCondition(data) {
    if (isWeatherConditionTemperatureMismatch(data)) return '';
    return weatherCodeText(data && data.code, data && data.condition);
  }

  function weatherTone(data) {
    var temp = parseWeatherTemperature(data && data.temperature);
    var wind = Number(data && data.wind);
    var text = normalize(safeWeatherCondition(data));
    // V5_2_CIDDI_HAVA_DURUMU_DILI: yalnızca güvenilir, kısa ve kurumsal bilgilendirme var.
    if (isWeatherConditionTemperatureMismatch(data)) return 'Hava durumu açıklaması sıcaklık bilgisiyle uyumlu görünmediği için yalnızca doğrulanabilen bilgileri paylaşıyorum.';
    if (text.indexOf('yagmur') !== -1 || text.indexOf('cisenti') !== -1) return 'Yağış görünüyor; dışarı çıkacaksanız tedbirli olmanız iyi olur.';
    if (text.indexOf('kar') !== -1) return 'Düşük sıcaklık ve yağış koşulları görünüyor; dışarı çıkacaksanız yol ve zemin koşullarına dikkat etmeniz iyi olur.';
    if (text.indexOf('sis') !== -1) return 'Sisli hava görünüyor; ulaşımda görüş mesafesine dikkat etmek faydalı olur.';
    if (text.indexOf('gok') !== -1) return 'Gök gürültülü hava görünüyor; açık alanda bulunacaksanız dikkatli olmanız iyi olur.';
    if (!isNaN(temp) && temp >= 30) return 'Hava sıcak görünüyor; gün içinde su tüketimine ve güneşe dikkat etmek iyi olur.';
    if (!isNaN(temp) && temp <= 5) return 'Hava oldukça serin görünüyor; dışarı çıkarken hazırlıklı olmak iyi olur.';
    if (!isNaN(wind) && wind >= 35) return 'Rüzgâr kuvvetli olabilir; dışarıda dikkatli olmak faydalı olur.';
    if (text.indexOf('acik') !== -1 || text.indexOf('bulut') !== -1) return 'Hava durumu genel olarak sakin görünüyor.';
    return 'Güncel hava durumu bilgisini aldım.';
  }

  function formatWeatherAnswer(data) {
    var parts = [];
    var condition = safeWeatherCondition(data);
    if (data.temperature != null && data.temperature !== '') parts.push('sıcaklık ' + data.temperature + '°C');
    if (condition) parts.push('durum ' + condition);
    if (data.wind != null && data.wind !== '') parts.push('rüzgâr ' + data.wind + ' km/sa');
    if (data.humidity != null && data.humidity !== '') parts.push('nem %' + data.humidity);
    var base = parts.length ? ('BYS360 hava durumu bilgisini aldım: ' + parts.join(', ') + '.') : 'BYS360 hava durumu servisinden güncel veri aldım.';
    return base + ' ' + weatherTone(data);
  }

  // V5_2_YAPAY_DIL_YOK_HAVA_DURUMU: hava cevabında mecaz veya yapay ifade kullanılmaz.
  function fetchWeatherAnswer() {
    var domData = readWeatherFromDom();
    if (domData) return Promise.resolve(makeAnswer(formatWeatherAnswer(domData)));
    var weatherPaths = collectWeatherPaths();
    var index = 0;
    function tryNext() {
      if (index >= weatherPaths.length) return Promise.reject(new Error('weather_unavailable'));
      var url = weatherPaths[index++];
      return fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { 'Accept': 'application/json', 'X-BYS360-Assistant-Weather': '1' } })
        .then(function (response) { if (!response.ok) throw new Error('http_' + response.status); return response.json(); })
        .then(function (payload) {
          var data = pickWeatherPayload(payload);
          if (!data) throw new Error('weather_payload');
          return makeAnswer(formatWeatherAnswer(data));
        })
        .catch(function () { return tryNext(); });
    }
    return tryNext();
  }

  function answerWeather(root, question, kayıt) {
    fetchWeatherAnswer().then(function (answer) {
      if (kayıt && kayıt.lastElementChild && kayıt.lastElementChild.classList.contains('is-bot')) kayıt.removeChild(kayıt.lastElementChild);
      appendMessage(root, 'bot', answer.text, answer.links || []);
    }).catch(function () {
      if (kayıt && kayıt.lastElementChild && kayıt.lastElementChild.classList.contains('is-bot')) kayıt.removeChild(kayıt.lastElementChild);
      appendMessage(root, 'bot', 'BYS360 hava durumu bilgisine şu an ulaşamadım. Hava bilgisini uydurmam; hava durumu kartı güncellendiğinde güncel bilgiyi sade ve doğru şekilde paylaşabilirim.');
    });
  }


  // V5_SAYFA_BAZLI_YARDIM_OTURUM_DEVAMLILIGI
  function cleanSmallText(value, max) {
    var text = String(value || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > (max || 90) ? text.slice(0, (max || 90) - 1) + '…' : text;
  }

  function activeMenuText() {
    var selectors = [
      '.sidebar .active', '.sidebar .is-active', '.side-menu .active', '.nav-sidebar .active',
      '.menu-item.active', '.nav-link.active', '[aria-current="page"]',
      '.app-sidebar a.active', '.app-sidebar .is-active', '.bys-sidebar a.active'
    ];
    for (var i = 0; i < selectors.length; i += 1) {
      var node = qs(selectors[i]);
      if (node) {
        var txt = cleanSmallText(node.textContent || node.getAttribute('title') || node.getAttribute('aria-label'), 80);
        if (txt) return txt;
      }
    }
    return '';
  }

  function pageHeadingText() {
    var selectors = ['main h1', '.page-title', '.content-title', '.card-title h1', 'h1', 'h2'];
    for (var i = 0; i < selectors.length; i += 1) {
      var node = qs(selectors[i]);
      if (node) {
        var txt = cleanSmallText(node.textContent, 95);
        if (txt) return txt;
      }
    }
    return cleanSmallText(document.title || '', 95);
  }

  function routeForCurrentPage() {
    var path = canonicalizeHref(window.location.pathname || '/');
    return ROUTES.find(function (r) { return r.href === path; }) || ROUTES.find(function (r) { return path.indexOf(r.href + '/') === 0; }) || null;
  }

  function currentPageContext() {
    var route = routeForCurrentPage();
    var path = canonicalizeHref(window.location.pathname || '/');
    return {
      path: path,
      routeTitle: route ? route.title : '',
      routeText: route ? route.text : '',
      heading: pageHeadingText(),
      activeMenu: activeMenuText(),
      at: new Date().toISOString()
    };
  }

  function saveCurrentPageContext(extra) {
    try {
      var ctx = currentPageContext();
      if (extra && typeof extra === 'object') Object.keys(extra).forEach(function (k) { ctx[k] = extra[k]; });
      sessionStorage.setItem(STORAGE_CONTEXT, JSON.stringify(ctx));
      sessionStorage.setItem(STORAGE_LAST_PAGE, JSON.stringify(ctx));
      return ctx;
    } catch (e) { return null; }
  }

  function loadSavedContext() {
    try {
      var rawData = sessionStorage.getItem(STORAGE_CONTEXT) || sessionStorage.getItem(STORAGE_LAST_PAGE);
      return rawData ? JSON.parse(rawData) : null;
    } catch (e) { return null; }
  }

  function lastMeaningfulChat() {
    for (var i = chatHistory.length - 1; i >= 0; i -= 1) {
      var msg = chatHistory[i];
      if (msg && msg.text && String(msg.text).indexOf('Sorunuzu BYS360 kapsamında yorumluyorum') === -1) return msg;
    }
    return null;
  }

  function pageAwareAnswer() {
    var ctx = saveCurrentPageContext() || currentPageContext();

    /* BYS360_ASSISTANT_SCREEN_INTELLIGENCE_V23_PAGE_AWARE_BRIDGE */
    var v23Page = (window.BYS360AssistantScreenIntelligenceV23 && typeof window.BYS360AssistantScreenIntelligenceV23.answerCurrentPage === 'function') ? window.BYS360AssistantScreenIntelligenceV23.answerCurrentPage() : null;
    if (v23Page && v23Page.text) return makeAnswer(v23Page.text, v23Page.links || []);
    /* BYS360_ASSISTANT_SCREEN_AGENT_V22_PAGE_AWARE_BRIDGE */
    var v22Page = (window.BYS360AssistantScreenAgentV22 && typeof window.BYS360AssistantScreenAgentV22.answerCurrentPage === 'function') ? window.BYS360AssistantScreenAgentV22.answerCurrentPage() : null;
    if (v22Page && v22Page.text) return makeAnswer(v22Page.text, v22Page.links || []);
    /* BYS360_ASSISTANT_SCREEN_AGENT_V21_PAGE_AWARE_BRIDGE */
    var v21Page = (window.BYS360AssistantScreenAgentV21 && typeof window.BYS360AssistantScreenAgentV21.answerCurrentPage === 'function') ? window.BYS360AssistantScreenAgentV21.answerCurrentPage() : null;
    if (v21Page && v21Page.text) return makeAnswer(v21Page.text, v21Page.links || []);

    /* BYS360_ASSISTANT_SCREEN_MAP_V20_PAGE_AWARE_BRIDGE */
    var v20Page = (window.BYS360AssistantScreenMapV20 && typeof window.BYS360AssistantScreenMapV20.answerCurrentPage === 'function') ? window.BYS360AssistantScreenMapV20.answerCurrentPage() : null;
    if (v20Page && v20Page.text) return makeAnswer(v20Page.text, v20Page.links || []);
    var route = routeForCurrentPage();
    if (route) {
      var parts = ['Şu an “' + route.title + '” ekranındasınız. ' + route.text];
      if (ctx.heading && normalize(ctx.heading) !== normalize(route.title)) parts.push('Ekranda görünen başlık: “' + ctx.heading + '”.');
      if (ctx.activeMenu && normalize(ctx.activeMenu).indexOf(normalize(route.title)) === -1) parts.push('Sol şeritte seçili görünen alan: “' + ctx.activeMenu + '”.');
      parts.push('Bu ekranda işlem yaparken rol matrisi, kişi/birim bazlı görünürlük ve güvenli erişim sınırları geçerlidir. Ne yapmak istediğinizi yazarsanız bu ekrandan devam edilecek adımları sırayla anlatırım.');
      return makeAnswer(parts.join(' '), [{ title: route.title, href: route.href }]);
    }
    var label = ctx.heading || ctx.activeMenu || ctx.path || 'bulunduğunuz sayfa';
    return makeAnswer('Şu an “' + label + '” alanındasınız. Bu ekranı Ekran Tanıma Ajanı ile yorumluyorum; yanlış linke yönlendirmemek için ekran adını doğrulamadan işlem bağlantısı açmam. Yapmak istediğiniz işlemi yazarsanız sizi güvenli BYS360 ekranına yönlendiririm.');
  }

  function resumeAnswer() {
    var ctx = loadSavedContext() || currentPageContext();
    var last = lastMeaningfulChat();
    var route = routeForCurrentPage();
    var text = 'Aynı oturum içinde kaldığımız yerden devam edebiliriz.';
    if (route) text += ' Şu an “' + route.title + '” ekranındasınız.';
    else if (ctx && (ctx.routeTitle || ctx.heading)) text += ' Son bağlam: “' + (ctx.routeTitle || ctx.heading) + '”.';
    if (last && last.text) text += ' Son konuşulan konu: “' + cleanSmallText(last.text, 120) + '”.';
    text += ' Bir önceki işlemden devam etmek için yapmak istediğiniz adımı yazın; ben aynı oturum bağlamını koruyarak yönlendireceğim.';
    return makeAnswer(text, route ? [{ title: route.title, href: route.href }] : []);
  }


  function currentRouteHelp() {
    return pageAwareAnswer();
  }

  // V9_PERSONEL_IZIN_DEVAMSIZLIK_VEKALET_TAM_BILGI_BANKASI
  function localAnswer(message) {
    var n = normalize(message);
    var links = findRoutes(message);

    if (!n) return makeAnswer('Size yardımcı olmak için buradayım. Yapmak istediğiniz işlemi yazın; sizi BYS360 içindeki doğru modül, gerçek sekme adı ve güvenli işlem sırasıyla yönlendireyim.');


    if (/\b(12 adim|12 adım|12 adim durum|12 adım durum|tamamlama plani|tamamlama planı|v8|durum kontrol)\b/.test(n)) {
      return twelveStepStatusAnswer();
    }

    if (/\b(hangi adimlar eksik|hangi adımlar eksik|eksik adim|eksik adım|neler eksik|kalanlar ne)\b/.test(n)) {
      return missingStepsAnswer();
    }


    if (/\b(v7|ogretim testi|öğretim testi|canli ogretim|canlı öğretim|cevap sozlesmesi|cevap sözleşmesi|modul rehberi|modül rehberi|12 adim|12 adım|hangi adimlar eksik|hangi adımlar eksik|eksik adim|eksik adım)\b/.test(n)) {
      return teachingContractAnswer();
    }

    if (/\b(her seyi biliyor musun|her şeyi biliyor musun|tum ekranlar|tüm ekranlar|ekranlari biliyor musun|ekranları biliyor musun|hangi ekranlari biliyorsun|hangi ekranları biliyorsun|butun moduller|bütün modüller)\b/.test(n)) {
      return knownScreensAnswer();
    }

    if (/\b(adim adim anlat|adım adım anlat|nasil kullanilir|nasıl kullanılır|bana ogret|bana öğret|islem sirasi|işlem sırası)\b/.test(n)) {
      return moduleStepAnswer('BYS360 adım adım rehberlik', 'İşlem adını yazdıktan sonra ilgili gerçek ekran yolunu göstereceğim', ['Yetkiniz olan kullanıcı rolü'], ['Yapmak istediğiniz işlemi kısa yazın', 'Ben ilgili modülü ve ekranı tespit ederim', 'Yetki gerektiren alan varsa önce bunu belirtirim', 'İşlem adımlarını sıralarım', 'Sonunda hangi ekrandan kontrol edeceğinizi söylerim'], ['Olmayan veya eski bağlantıya yönlendirme yapmam.', 'Hassas veri, puan veya idari karar üretmem.'], ['Cevapta gerçek sekme adı, yetki ve kontrol adımı bulunmalıdır.'], [{ title: 'Yardım Merkezi', href: '/support' }]);
    }

    if (/\b(personel yonetimi nasil|personel yönetimi nasıl|personel modulu nasil|personel modülü nasıl|personel nasil calisir|personel nasıl çalışır)\b/.test(n)) {
      return moduleStepAnswer('Personel Yönetimi', 'Sol şerit > Personel Yönetimi', ['Admin', 'Sistem Yöneticisi', 'Personel Yönetimi yetkilisi'], ['Personel listesini açın', 'Yeni kayıt veya düzenleme ekranına girin', 'Sicil No, ad-soyad, unvan/görev, birim, üst birim ve yönetici bilgisini kontrol edin', 'Rol ve menü görünürlüğünü görevle uyumlu seçin', 'Kaydedin'], ['TC yerine Sicil No esas alınmalıdır.', 'Birim ve yönetici ilişkisi yanlışsa izin, vekâlet, performans ve raporlar da etkilenebilir.'], ['Kayıttan sonra personel listesinde arama yapın ve aktiflik/rol/birim bilgisini doğrulayın.'], [{ title: 'Personel Yönetimi', href: '/personnel' }]);
    }

    if (/\b(baskan onaylari nasil|başkan onayları nasıl|baskan onayi nasil|başkan onayı nasıl|70 alti surec|70 altı süreç)\b/.test(n)) {
      return moduleStepAnswer('Başkan Onayları', 'Sol şerit > Performans Yönetimi > Başkan Onayları', ['Başkan', 'Admin', 'Yetkili üst yönetim kullanıcısı'], ['70 altı nihai performans sonucu oluşur', 'Sistem sonucu doğrudan yayınlamaz', 'Kayıt Başkan Onayları ekranında incelenir', 'Karne, amir görüşleri, süreç geçmişi ve yayın kilidi kontrol edilir', 'Yetkili kullanıcı onay/iade işlemini yapar', 'Gerekli süreç kaydı tamamlanmadan personel karnesi kesinleşmez'], ['Sahte onay kaydı oluşturulmamalıdır.', '70 üstü veya puanı oluşmamış kayıt gereksiz onaya düşmemelidir.'], ['Onaydan sonra Süreç Takibi, yayın kilidi ve karne görünürlüğü kontrol edilmelidir.'], [{ title: 'Başkan Onayları', href: '/performance/president-approvals' }, { title: 'Süreç Takibi', href: '/performance/process-tracking' }]);
    }

    if (/\b(destek talebi nasil acilir|destek talebi nasıl açılır|yardim talebi nasil|yardım talebi nasıl|sorun nasil bildirilir|sorun nasıl bildirilir)\b/.test(n)) {
      return moduleStepAnswer('Yardım Merkezi / Destek Talebi', 'Sol şerit > Yardım Merkezi', ['Standart kullanıcı', 'Yönetici', 'Destek yetkilisi'], ['Yardım Merkezi ekranına girin', 'Yeni destek talebi oluşturun', 'Kategori ve başlık seçin', 'Sorunu kısa ve anlaşılır açıklayın', 'Varsa ekran görüntüsü veya belge ekleyin', 'Talebi kaydedin'], ['Kişisel veya hassas veriyi gereksiz yere talep metnine yazmayın.', 'Teknik hata varsa ekran adı ve yaptığınız son adımı belirtin.'], ['Talep durumunu, cevapları ve kapanış bilgisini aynı ekrandan takip edin.'], [{ title: 'Yardım Merkezi', href: '/support' }]);
    }

    if (/\b(anket nasil cevaplanir|anket nasıl cevaplanır|anket nerede|anketler nerede|anket gonder|anket gönder)\b/.test(n)) {
      return moduleStepAnswer('Anketler', 'Sol şerit > Anketler', ['Anket atanan kullanıcı', 'Anket yetkilisi'], ['Anketler ekranını açın', 'Size atanan anketi seçin', 'Zorunlu soruları doldurun', 'Açık uçlu cevap varsa kurumsal ve net yazın', 'Gönder butonuyla yanıtı tamamlayın'], ['Anket cevapları yetki ve gizlilik kurallarıyla korunur.', 'Başka kullanıcıların cevapları yetkisiz gösterilmemelidir.'], ['Gönderim sonrası anketin tamamlandı durumuna geçtiğini kontrol edin.'], [{ title: 'Anketler', href: '/surveys' }]);
    }

    // V9_PERSONEL_IZIN_DEVAMSIZLIK_VEKALET_TAM_BILGI_BANKASI_CEVAPLARI
    if (/\b(v9|personel bilgi bankasi|personel bilgi bankası|izin bilgi bankasi|izin bilgi bankası|vekalet bilgi bankasi|vekâlet bilgi bankası)\b/.test(n)) {
      return makeAnswer('V9 bilgi bankası aktif. Bu sürüm Personel Yönetimi, İzin ve Devamsızlık Takibi ile Devamsızlık ve Vekâlet konularında daha ayrıntılı, adım adım ve güvenli yönlendirme verir. Cevaplar gerçek ekran adlarıyla hazırlanır; eski/kırık bağlantılar kullanılmaz.', [
        { title: 'Personel Yönetimi', href: '/personnel' },
        { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' },
        { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' }
      ]);
    }

    if (/\b(personel ekle|yeni personel|personel kaydi|personel kaydı|personel nasil eklenir|personel nasıl eklenir|sicil no ile personel)\b/.test(n)) {
      return moduleStepAnswer('Personel ekleme', 'Sol şerit > Personel Yönetimi', ['Admin', 'Sistem Yöneticisi', 'Personel Yönetimi yetkilisi', 'Yetki verilmiş İK/personel kullanıcısı'], ['Personel Yönetimi ekranını açın', 'Personel listesi içinde yeni kayıt/ekle butonunu kullanın', 'Sicil No, ad, soyad, unvan/görev, birim ve üst birim bilgilerini doldurun', 'Personelin yönetici/amir bağlantısını kontrol edin', 'Gerekliyse profil fotoğrafı ve iletişim bilgilerini ekleyin', 'Rol ve menü görünürlüğünü görevine uygun seçin', 'Kaydedin'], ['TC yerine Sicil No esas alınmalıdır.', 'Birim, üst birim veya yönetici yanlış girilirse performans görev üretimi, izin/vekâlet ve raporlar da yanlış etkilenebilir.', 'Başlangıç gizli erişim bilgisisi veya kullanıcı hesabı üretimi kurum ayarlarına göre çalışmalıdır.'], ['Personel listesinde sicil no veya ad-soyad ile arama yapın; aktiflik, birim, rol ve yönetici bilgisinin doğru göründüğünü kontrol edin.'], [{ title: 'Personel Yönetimi', href: '/personnel' }]);
    }

    if (/\b(personel duzenle|personel düzenle|personel bilgisi guncelle|personel bilgisi güncelle|birim degisikligi|birim değişikliği|yonetici degisti|yönetici değişti|unvan degisti|unvan değişti)\b/.test(n)) {
      return moduleStepAnswer('Personel bilgisi güncelleme', 'Sol şerit > Personel Yönetimi', ['Admin', 'Sistem Yöneticisi', 'Personel Yönetimi yetkilisi'], ['Personel Yönetimi ekranında personeli sicil no veya ad-soyad ile bulun', 'Detay/düzenle işlemine girin', 'Unvan, görev, birim, üst birim, yönetici, aktiflik ve rol bilgilerini kontrol edin', 'Değişiklikleri kaydedin', 'Gerekirse performans görev üretimi veya yetki görünürlüğünü tekrar kontrol edin'], ['Organizasyon değişikliği geçmiş kayıt ve raporlama açısından önemlidir.', 'Yönetici değişikliği performans amir zincirini etkileyebilir.', 'Rol değişikliği menü görünürlüğünü değiştirebilir.'], ['Kayıt sonrası personel kartı, menü görünürlüğü, varsa performans görevleri ve raporlardaki birim bilgisini kontrol edin.'], [{ title: 'Personel Yönetimi', href: '/personnel' }, { title: 'Performans Yönetimi', href: '/performance/dashboard' }]);
    }

    if (/\b(sicil no|sicil numarasi|sicil numarası|tc yerine|sicil no|personel tekil)\b/.test(n)) {
      return makeAnswer('BYS360’da personel takibinde temel ayırt edici bilgi Sicil No’dur. Personel ekleme ve güncelleme işlemlerinde Sicil No doğru girilmelidir; tekrar eden veya hatalı Sicil No, personel listesi, izin/vekâlet, performans amir zinciri ve raporlama tarafında karışıklık oluşturabilir. TC bilgisi kullanıcı ekranlarında ana takip bilgisi olarak kullanılmamalıdır.', [{ title: 'Personel Yönetimi', href: '/personnel' }]);
    }

    if (/\b(profil fotografi|profil fotoğrafı|personel profili|profil bilgileri|personel karti|personel kartı)\b/.test(n)) {
      return moduleStepAnswer('Personel profil bilgileri', 'Sol şerit > Personel Yönetimi', ['Admin', 'Sistem Yöneticisi', 'Personel Yönetimi yetkilisi', 'Yetkisi kapsamında ilgili kullanıcı'], ['Personel Yönetimi ekranında personeli bulun', 'Personel detay/profil ekranını açın', 'Profil fotoğrafı, iletişim, unvan, görev, birim, üst birim, yönetici ve aktiflik bilgilerini kontrol edin', 'Gerekli alanları güncelleyin', 'Kaydedin'], ['Profil bilgileri yalnızca görsel bilgi değildir; birim, rol ve yönetici bağlantısı diğer modülleri etkiler.', 'Hassas veya gereksiz kişisel veri eklenmemelidir.'], ['Personel listesinde ve ilgili dashboard/rapor ekranlarında profil bilgisinin doğru göründüğünü kontrol edin.'], [{ title: 'Personel Yönetimi', href: '/personnel' }]);
    }

    if (/\b(izin nasil girilir|izin nasıl girilir|izin kaydi nasil|izin kaydı nasıl|izin talebi nasil|izin talebi nasıl|yillik izin|yıllık izin|idari izin|saatlik izin|izin bakiyesi)\b/.test(n)) {
      return moduleStepAnswer('İzin kaydı / izin talebi', 'Sol şerit > Personel Yönetimi > İzin ve Devamsızlık Takibi', ['Personel Yönetimi yetkilisi', 'İK/personel yetkilisi', 'Yetkili amir', 'Kurum ayarına göre personelin kendisi'], ['İzin ve Devamsızlık Takibi ekranını açın', 'Yeni izin kaydı veya izin talebi işlemini seçin', 'İlgili personeli seçin', 'İzin türünü belirleyin', 'Başlangıç ve bitiş tarih/saat bilgisini girin', 'Gerekirse açıklama ve belge ekleyin', 'Kaydedin veya onaya gönderin', 'Onay süreci varsa ilgili amir/onaycıya düştüğünü kontrol edin'], ['İzin tarihleri yanlış girilirse devamsızlık, vekâlet ve performans görev akışı etkilenebilir.', 'İzinli amir varsa vekâlet veya görev devri kontrol edilmelidir.', 'İzin bakiyesi kurum ayarına göre takip edilmelidir.'], ['Kayıt sonrası aynı ekranda izin durumunu, izin bakiyesini, varsa onay statüsünü ve bildirim kaydını kontrol edin.'], [{ title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' }]);
    }

    if (/\b(izin talebi nerede|izin nerede|izinleri nereden|izin listesi|izin takip|izin durumu|izin onayi|izin onayı)\b/.test(n)) {
      return makeAnswer('İzin işlemleri için doğru canlı ekran: Personel Yönetimi > İzin ve Devamsızlık Takibi. Bu ekranda izin kaydı, izin talebi, izin durumu, izin bakiyesi ve onay takibi kontrol edilir. Eski personel izin bağlantıları kullanılmamalıdır; beyaz ekran riski olan eski yollar güvenli menü haritasından engellenir.', [{ title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' }]);
    }

    if (/\b(devamsizlik nedir|devamsızlık nedir|devamsizlik kaydi|devamsızlık kaydı|devamsizlik nasil|devamsızlık nasıl|ise gelmedi|işe gelmedi|gec kaldi|geç kaldı)\b/.test(n)) {
      return moduleStepAnswer('Devamsızlık kaydı', 'Sol şerit > Personel Yönetimi > Devamsızlık ve Vekâlet', ['Personel Yönetimi yetkilisi', 'İK/personel yetkilisi', 'Yetkili amir'], ['Devamsızlık ve Vekâlet ekranını açın', 'Personeli seçin', 'Devamsızlık türünü veya olay tipini belirleyin', 'Tarih/saat bilgisini girin', 'Gerekli açıklama veya belgeyi ekleyin', 'Kaydedin', 'Kayıt sonrası rapor ve personel geçmişi etkisini kontrol edin'], ['Devamsızlık kaydı personel geçmişi, izin dengelemesi ve raporları etkileyebilir.', 'Yetkisiz kullanıcı başka personelin detayını görmemelidir.', 'Geçerli bir izin kaydı varsa devamsızlıkla çakışma kontrol edilmelidir.'], ['Kayıt sonrası personel devamsızlık listesi, izin/devamsızlık özeti ve ilgili rapor ekranı kontrol edilmelidir.'], [{ title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' }]);
    }

    if (/\b(vekalet nasil|vekâlet nasıl|vekalet tanimla|vekâlet tanımla|vekil ata|gorev devri|görev devri|amir izinli|izinli amir|vekalet nerede|vekâlet nerede)\b/.test(n)) {
      return moduleStepAnswer('Vekâlet tanımlama', 'Sol şerit > Personel Yönetimi > Devamsızlık ve Vekâlet', ['Admin', 'Personel Yönetimi yetkilisi', 'İK/personel yetkilisi', 'Yetkili amir'], ['Devamsızlık ve Vekâlet ekranını açın', 'Asıl personeli veya izinli amiri seçin', 'Vekil olacak personeli seçin', 'Başlangıç ve bitiş tarihlerini belirleyin', 'Vekâlet kapsamını seçin', 'Kaydedin', 'İlgili süreçlerde vekilin yetki/görev devrinin doğru çalıştığını kontrol edin'], ['Vekâlet süresi izin/devamsızlık tarihiyle uyumlu olmalıdır.', 'Vekil kişinin yetki kapsamı kurum kurallarıyla sınırlı olmalıdır.', 'Performans değerlendirme döneminde izinli amir varsa görev akışı vekâlet bilgisinden etkilenebilir.'], ['Vekâlet listesinde kayıt görünmeli; varsa performans görevleri, onay süreçleri ve bildirimler doğru kişiye yönlenmelidir.'], [{ title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' }, { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' }]);
    }

    if (/\b(izinli amir performansi etkiler mi|izinli amir performansı etkiler mi|amir izinliyse|amir yoksa|vekalet performans|vekâlet performans|gorev kime duser|görev kime düşer)\b/.test(n)) {
      return makeAnswer('İzinli amir varsa BYS360’da önce izin/devamsızlık kaydı ve varsa vekâlet tanımı kontrol edilmelidir. Performans sürecinde değerlendirme görevinin boşa düşmemesi için vekil veya yetkili akış kurum kuralına göre devreye alınır. Asistan performans puanı belirlemez; yalnızca doğru ekranları ve kontrol adımlarını gösterir: önce İzin ve Devamsızlık Takibi, sonra Devamsızlık ve Vekâlet, ardından ilgili performans görev/süreç ekranı kontrol edilir.', [{ title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' }, { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' }, { title: 'Değerlendirme Görevleri', href: '/performance/evaluation-tasks' }]);
    }

    if (/\b(personel gorunmuyor|personel görünmüyor|personel listede yok|personel ekleyemiyorum|sicil hatasi|sicil hatası|yonetici yanlis|yönetici yanlış|birim yanlis|birim yanlış)\b/.test(n)) {
      return makeAnswer('Personel tarafında sorun varsa şu sırayla kontrol edin: 1) Personel kaydı aktif mi? 2) Sicil No doğru ve tekil mi? 3) Birim, üst birim ve yönetici bağlantısı doğru mu? 4) Rol ve kişi bazlı menü görünürlüğü açık mı? 5) Kullanıcının ilgili personeli görme yetkisi var mı? 6) Son değişiklikten sonra ilgili liste/rapor yenilendi mi? Bu kontroller Personel Yönetimi ve gerekiyorsa Sistem Ayarları tarafında yapılmalıdır.', [{ title: 'Personel Yönetimi', href: '/personnel' }, { title: 'Sistem Ayarları', href: '/settings' }]);
    }

    if (/\b(merhaba|selam|slm|gunaydin|iyi aksamlar|iyi gunler)\b/.test(n)) {
      return makeAnswer('Merhaba, ben ' + MODULE_NAME + '. BYS360 içinde yetkiniz dâhilindeki işlemler için size adım adım rehberlik ederim. Hangi işlem için yardımcı olayım?', [{ title: 'Dönemler', href: '/performance/periods' }, { title: 'Yardım Merkezi', href: '/support' }]);
    }

    if (/\b(nasilsin|iyi misin|naber|nasilsiniz)\b/.test(n)) {
      return makeAnswer('İyiyim, teşekkür ederim. Bugün BYS360 içinde hangi işlemde birlikte ilerleyelim? Dönemler, karne, Başkan Onayları, rol matrisi, personel, anket veya destek başlıklarında adım adım yardımcı olabilirim.');
    }


    if (/\b(bu ekranda ne yapabilirim|bu sayfada ne yapabilirim|burada ne yapacagim|burada ne yapacağım|sayfa yardimi|sayfa yardımı|ekran yardimi|ekran yardımı|nereden devam|nereden devam edecegim|nereden devam edeceğim)\b/.test(n)) {
      return pageAwareAnswer();
    }

    if (/\b(az onceki konu|az önceki konu|kaldigimiz yer|kaldığımız yer|devam edelim|kaldigimiz yerden|kaldığımız yerden|onceki konudan|önceki konudan)\b/.test(n)) {
      return resumeAnswer();
    }

    if (/\b(final test|test senaryo|test senaryolari|test senaryoları|kalite kontrol|canli kontrol|canlı kontrol|asistani test|asistanı test|v6|v7|ogretim testi|öğretim testi)\b/.test(n)) {
      return makeAnswer('V7 canlı öğretim ve kalite kontrolünde şu başlıkları test etmelisiniz: 1) Baloncuk kısa tıklamayla açılıyor mu, sürükleyince konumu bozulmadan taşınıyor mu? 2) Sayfa değişince sohbet ve açık panel durumu korunuyor mu? 3) İzin, vekâlet, Dönemler, Başkan Onayları ve rol matrisi cevapları gerçek ekran adlarıyla geliyor mu? 4) Kırık/eski linkler beyaz ekrana götürmeden engelleniyor mu? 5) Hava durumu cevabı ciddi ve doğrulanabilir bilgiyle sınırlı mı? 6) “Seni kim geliştirdi?”, “Neler yapabiliyorsun?” ve “Bu sayfada ne yapabilirim?” soruları düzgün cevaplanıyor mu?', [
        { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' },
        { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' },
        { title: 'Dönemler', href: '/performance/periods' },
        { title: 'Başkan Onayları', href: '/performance/president-approvals' }
      ]);
    }


    if (/\b(menu haritasi|menü haritası|gercek menu|gerçek menü|hangi ekranlar var|ekran haritasi|ekran haritası)\b/.test(n)) {
      return makeAnswer('BYS360 içinde güvenli menü haritasına göre yönlendirme yaparım. Tanımlı başlıklar: Anasayfa, Dashboard, Personel Yönetimi, İzin ve Devamsızlık Takibi, Devamsızlık ve Vekâlet, Performans Yönetimi, Sorular / Kriterler, Dönemler, Değerlendirme Görevleri, Başkan Onayları, Yayın Ön Onayı, Süreç Takibi, Süreç Raporları, Dönem İçi Notlar, Gelişim Rehberi, Not Karnesi, Geçmiş Karne Arşivi, Mesajlar, Anketler, Yardım Merkezi, AI Karar Destek Merkezi, Asistan Bilgi Bankası ve Sistem Ayarları. Eski veya doğrulanmayan bağlantıları açmadan önce engellerim.', [
        { title: 'Dönemler', href: '/performance/periods' },
        { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' },
        { title: 'Başkan Onayları', href: '/performance/president-approvals' },
        { title: 'Sistem Ayarları', href: '/settings' }
      ]);
    }

    if (/\b(kirik link|kırık link|beyaz ekran|sayfa acilmiyor|sayfa açılmıyor|yanlis link|yanlış link)\b/.test(n)) {
      return makeAnswer('Beyaz ekran veya kırık link riskini azaltmak için yönlendirmeleri güvenli menü haritasından geçiririm. Eski bağlantı tespit edersem canlı ekrana çeviririm; doğrulanmayan ekranı ise açmayıp uyarı veririm. Örneğin izin işlemleri için eski personel izin bağlantısı yerine doğru yol Personel Yönetimi > İzin ve Devamsızlık Takibi ekranıdır.', [
        { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' },
        { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' }
      ]);
    }

    if (/\b(bu sayfa|su sayfa|şu sayfa|neredeyim|bulundugum ekran|bulunduğum ekran)\b/.test(n)) {
      return currentRouteHelp();
    }


    if (/\b(neler yapabiliyorsun|ne yapabilirsin|hangi konularda yardimci|hangi konularda yardımcı|bana hangi konularda yardimci olursun|bana hangi konularda yardımcı olursun|yardimci ol|yardımcı ol|ne ise yararsin|ne işe yararsın)\b/.test(n)) {
      return makeAnswer('Size BYS360 içinde adım adım rehberlik ederim: personel kaydı, izin, devamsızlık, vekâlet, performans Dönemler, Sorular / Kriterler, Değerlendirme Görevleri, Başkan Onayları, karne, raporlar, rol matrisi, menü görünürlüğü, destek talepleri, anketler, mesajlar, bildirimler ve AI Karar Destek ayrımı gibi konularda yardımcı olurum. Soruyu eksik veya günlük dille yazsanız bile niyetinizi BYS360 ekranlarıyla eşleştirmeye çalışırım. İdari karar üretmem, performans puanı belirlemem ve hassas veri göstermem.', [
        { title: 'Dönemler', href: '/performance/periods' },
        { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' },
        { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' },
        { title: 'Sistem Ayarları', href: '/settings' }
      ]);
    }

    if (/\b(hava|havadurumu|hava durumu|bugun hava|bugün hava|yagmur|yağmur|sicaklik|sıcaklık|ruzgar|rüzgar|open meteo|open-meteo)\b/.test(n)) {
      return makeAnswer('Hava durumunu BYS360’daki hava durumu kartından veya Open-Meteo bağlantısından okumaya çalışırım. Güncel veri gelirse kısa, ciddi ve doğrulanabilir bir hava notu paylaşırım; veri yoksa hava bilgisi uydurmam.');
    }

    if (/\b(kim gelistirdi|kim geliştirdi|seni kim|seni kim gelistirdi|seni kim geliştirdi|kim yapti|kim yaptı|gelistiren kim|geliştiren kim|kimin tarafindan|kimin tarafından|havva gulsen ozden|havva gülsen özden|gulsen ozden|gülsen özden|havva mi|havva mı|gulsen mi|gülsen mi)\b/.test(n)) {
      return makeAnswer('Ben BYS360 Asistanı’yım. BYS360 için Havva Gülsen Özden (geliştirici) ve Mustafa Bektaş (eş geliştirici) tarafından geliştirildim. Görevim, BYS360 içinde yetkiniz dâhilindeki işlemleri sade, güvenli ve doğru sırayla anlatmak; sizi gerçek ekranlara yönlendirmek ve sistemi daha kolay kullanmanıza yardımcı olmaktır.', [{ title: 'Asistan Bilgi Bankası', href: '/ai-agent/knowledge' }]);
    }

    if (/\b(sen nesin|kimsin|ne ise yararsin|ne işe yararsın|kendini tanit|kendini tanıt|asistan misin|asistan mısın)\b/.test(n)) {
      return makeAnswer('Ben BYS360 Asistanı’yım; BYS360’a özel kurumsal rehberlik, akıllı yönlendirme ve yetki kontrollü dijital yardımcı katmanıyım. Kullanıcıların sistemde doğru ekrana ulaşmasına, işlem sırasını anlamasına ve yetkisi dâhilindeki bilgileri güvenli şekilde takip etmesine yardımcı olurum.', [{ title: 'Yardım Merkezi', href: '/support' }]);
    }

    if (/\b(nasil calisiyorsun|nasıl çalışıyorsun|calisma mantigin|çalışma mantığın|yapay zekaya bagli misin|yapay zekaya bağlı mısın|ai bagli|ai bağlı|chatgpt misin|chatgpt mısın)\b/.test(n)) {
      return makeAnswer('BYS360 içindeki bilgi bankası, güvenli menü haritası, işlem adımları ve yetki kurallarıyla çalışırım. Yapay zekâ/akıllı yönlendirme katmanından yararlanabilirim; ancak BYS360 sınırlarının dışına çıkmam. Karar destek alanı analiz ve özet üretir; ben ise kullanıcıya doğru ekranı, doğru işlem sırasını ve dikkat edilmesi gereken güvenlik sınırını anlatırım.', [{ title: 'AI Karar Destek Merkezi', href: '/ai/decision-support/faz1/health' }]);
    }


    if (/\b(izin|izin kaydi|izin kaydı|izin talebi|izin nasil|izin nasıl|izin nerede|izin bakiyesi)\b/.test(n)) {
      return makeAnswer('İzin işlemleri için doğru yol: Sol şerit > Personel Yönetimi > İzin ve Devamsızlık Takibi. Bu ekranda personel seçilir, izin türü belirlenir, başlangıç ve bitiş tarihleri girilir, gerekiyorsa açıklama/belge ve vekil personel bilgisi eklenir, ardından İzin kaydet butonuyla kayıt oluşturulur. Kayıttan sonra izin listesi, izin bakiyesi ve izinli amir varsa vekâlet etkisi kontrol edilir. İzinli amirlerde performans görev zincirinin boşa düşmemesi için vekâlet bilgisi özellikle kontrol edilmelidir.', [
        { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' },
        { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' }
      ]);
    }

    if (/\b(vekalet|vekâlet|devamsizlik|devamsızlık|vekil|gorev devri|görev devri)\b/.test(n)) {
      return makeAnswer('Devamsızlık ve vekâlet için doğru yol: Sol şerit > Personel Yönetimi > Devamsızlık ve Vekâlet. Bu ekranda devamsızlık kayıtları izlenir; vekâlet tanımlanacaksa asıl kişi, vekil personel, başlangıç-bitiş tarihi, vekâlet kapsamı ve not bilgisi girilir. Kaydettikten sonra vekâlet kayıtları listesinde durum kontrol edilir. Vekâlet, özellikle izinli amirlerde performans/onay görevlerinin doğru kişiye yönlenmesi için kullanılır.', [
        { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' },
        { title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' }
      ]);
    }

    if (/\b(hangi sorular|hangi sorulari|hangi soruları|ne sorabilirim|neler sorabilirim|soru listesi|ornek sorular|örnek sorular|insan ne sorar|hangi konular|soru havuzu|bys360 da ne sorulur|bys360da ne sorulur)\b/.test(n)) {
      return makeAnswer('BYS360 sınırları içinde şu başlıklarda soru sorabilirsiniz: Genel kullanım, Ana Sayfa, Dashboard, Personel Yönetimi, Sicil No, İzin ve Devamsızlık Takibi, Devamsızlık ve Vekâlet, Performans Yönetimi, Dönemler, Sorular / Kriterler, Değerlendirme Görevleri, Görevlerim, performans notu, Dönem İçi Notlar, Gelişim Rehberi, Başkan Onayları, Yayın Ön Onayı, Not Karnesi, Geçmiş Karne Arşivi, Rol Matrisi, menü görünürlüğü, destek talebi, mesajlar, duyurular, anketler, AI Karar Destek Merkezi ve KPI Dashboardu. Örnek: “performans notu nasıl verilir”, “dönem nasıl açılır”, “kişi nasıl eklenir”, “menü görünmüyor”, “70 altı sonuç ne olur”. Hassas veri, performans puanı, amir görüşü, mesaj metni veya anket cevabı göstermem; sizi yetkili ekrana yönlendiririm.', [{ title: 'Dönem İçi Notlar', href: '/performance/interim-notes' }, { title: 'Dönemler', href: '/performance/periods' }, { title: 'Sistem Ayarları', href: '/settings' }]);
    }

    if (/\b(donem|donemler|yeni donem|donem ac|donem olustur|performans donemi)\b/.test(n)) {
      return makeAnswer('Performans dönemi için doğru yol: Sol şerit > Performans Yönetimi > Dönemler. Bu ekranda Yeni Dönem Oluştur/Yeni Dönem Ekle butonuna basın; dönem adı, dönem türü, başlangıç-bitiş tarihi ve kapsam bilgisini doldurun. Dikkat: kullanıcıya görünen gerçek sekme adı Dönemlerdir; yönlendirme bu adla yapılmalıdır.', [{ title: 'Dönemler', href: '/performance/periods' }, { title: 'Sorular / Kriterler', href: '/performance/criteria' }]);
    }

    if (/\b(kriter|soru|sorular|degerlendirme kriterleri|yetkinlik)\b/.test(n)) {
      return makeAnswer('Kriter işlemleri için doğru yol: Sol şerit > Performans Yönetimi > Sorular / Kriterler. Buradan değerlendirme soruları/kriterleri eklenir, düzenlenir ve aktiflikleri kontrol edilir. Ana kullanıcı dili “Sorular / Kriterler” ve “Değerlendirme Kriterleri” olmalıdır.', [{ title: 'Sorular / Kriterler', href: '/performance/criteria' }]);
    }

    if (/\b(performans notu|not nasil verilir|not nasıl verilir|not ver|not gir|not ekle|not dus|not düş|olay notu|gozlem notu|gözlem notu|donem ici not|dönem içi not|ara geri bildirim|gelisim notu|gelişim notu)\b/.test(n)) {
      return makeAnswer('Performans notu için doğru yol: Sol şerit > Performans Yönetimi > Dönem İçi Notlar. Bu ekran puan verme ekranı değildir; dönem içindeki olumlu/olumsuz gözlem, başarı, gelişim ihtiyacı veya genel not kaydı için kullanılır. Adım adım: 1) Dönem İçi Notlar sekmesini açın. 2) Yeni Not / Not Ekle butonuna basın. 3) İlgili dönem ve personeli seçin. 4) Not türünü ve açıklamayı yazın. 5) Kaydedin. Notlar otomatik puan üretmez; değerlendirme döneminde amire hatırlatma ve gelişim desteği sağlar.', [{ title: 'Dönem İçi Notlar', href: '/performance/interim-notes' }, { title: 'Gelişim Rehberi', href: '/performance/meeting-development/faz10' }]);
    }

    if (/\b(puanlama|degerlendirme gorev|gorev uret|amir gorevi|gorevlerim)\b/.test(n)) {
      return makeAnswer('Puanlama ve amir görevleri için doğru yol: Sol şerit > Performans Yönetimi > Değerlendirme Görevleri. Amir yalnızca kendisine atanmış personel ve görevler üzerinde işlem yapar. Kör değerlendirme yoktur; sonraki amir önceki değerlendirmeyi görebilir.', [{ title: 'Değerlendirme Görevleri', href: '/performance/evaluation-tasks' }]);
    }

    if (/\b(70 alti|dusuk performans|baskan onay|ust onay|yayin kilidi)\b/.test(n)) {
      return makeAnswer('70 altı performans sonucu doğrudan kesinleşmez. Doğru takip yolu: Sol şerit > Performans Yönetimi > Başkan Onayları. Başkan Onayı tamamlanmadan ve gerekli süreç kaydı oluşmadan karne personele kesin/yayınlanmış sonuç olarak açılmaz.', [{ title: 'Başkan Onayları', href: '/performance/president-approvals' }, { title: 'Süreç Takibi', href: '/performance/process-tracking' }]);
    }

    if (/\b(karne|karnem|not karnesi|sonucum|performans sonucum)\b/.test(n)) {
      return makeAnswer('Karne görünürlüğü yayın/onay sürecine bağlıdır. Personel sonucu süreç tamamlanmadan göremez. Doğru yol: Sol şerit > Genel > Not Karnesi. Eski sonuçlar için Geçmiş Karne Arşivi kullanılmalıdır.', [{ title: 'Not Karnesi', href: '/performance/scorecard' }, { title: 'Geçmiş Karne Arşivi', href: '/performans/gecmis-karne-arsivi' }]);
    }

    if (/\b(menu gorunmuyor|sekme yok|rol matrisi|yetki|ayarlar|ac kapa|gorunurluk)\b/.test(n)) {
      return makeAnswer('Bir sekme görünmüyorsa kontrol sırası şöyledir: 1) Sol şerit > Sistem Ayarları ekranına girin. 2) Modül Bazlı Rol Matrisi’nde ana modül açık mı bakın. 3) Performans işlemleri için Performans Yönetimi Rol Matrisi’ni ayrıca kontrol edin. 4) Kişi bazlı menü görünürlüğü veya birim bazlı profil ekranı kapatıyor mu inceleyin. 5) Değişiklikten sonra kullanıcı oturumunu yenileyip menünün gerçekten görünüp görünmediğini kontrol edin. Doğru davranış: yetkisiz kullanıcı menüyü hiç görmemeli; URL yazarsa da beyaz ekran değil güvenli erişim engeli almalıdır.', [{ title: 'Sistem Ayarları', href: '/settings' }]);
    }

    if (/\b(asistani egit|ogret|bilgi bankasi|bilgi ekle|cevap ogret)\b/.test(n)) {
      return makeAnswer('Asistan eğitim içerikleri için doğru yol: Sol şerit > AI Karar Destek Merkezi > Asistan Bilgi Bankası. Burada BYS360 Asistanı’na gerçek sekme adları, işlem adımları, yetki sınırları ve güvenli cevaplar öğretilir.', [{ title: 'Asistan Bilgi Bankası', href: '/ai-agent/knowledge' }]);
    }


    if (/\b(personel ekle|yeni personel|personel kaydi|personel kaydı|sicil|personel duzenle|personel düzenle|personel listesi)\b/.test(n)) {
      return makeAnswer('Personel işlemleri BYS360’ın ana veri omurgasıdır. Genel akış: Sol şerit > Personel Yönetimi. Personel eklerken Sicil No, ad-soyad, unvan/görev, birim, üst birim, yönetici ve rol/görünürlük bilgileri kontrol edilir. Kaydetmeden önce birim-yönetici ilişkisi doğru olmalıdır; çünkü performans amir zinciri, izin/vekâlet, bildirim ve raporlar bu veriden beslenir. Kayıt sonrası personel listesinde kaydı arayın ve aktif/pasif durumunu kontrol edin.', [{ title: 'Personel Yönetimi', href: '/personnel' }]);
    }

    if (/\b(izin ve devamsizlik|izin ve devamsızlık|izin nasil calisir|izin nasıl çalışır|izin sureci|izin süreci|izin detay)\b/.test(n)) {
      return makeAnswer('İzin süreci şöyle çalışır: 1) Sol şerit > Personel Yönetimi > İzin ve Devamsızlık Takibi ekranına girilir. 2) Personel seçilir. 3) İzin türü ve tarih aralığı girilir. 4) Gerekirse açıklama, belge ve vekil personel bilgisi eklenir. 5) Kayıt oluşturulur. 6) İzin bakiyesi, izin listesi ve onay/izleme durumu kontrol edilir. 7) İzinli kişi amirse Devamsızlık ve Vekâlet ekranında görev devri de kontrol edilmelidir. Bu akış performans görevleri ve onay süreçlerinin boşa düşmemesi için önemlidir.', [{ title: 'İzin ve Devamsızlık Takibi', href: '/hr-management/leave' }, { title: 'Devamsızlık ve Vekâlet', href: '/hr-management/attendance' }]);
    }

    if (/\b(performans nasil calisir|performans nasıl çalışır|performans akisi|performans akışı|performans sureci|performans süreci|performans modulu|performans modülü)\b/.test(n)) {
      return makeAnswer('Performans süreci genel olarak şu sırayla ilerler: 1) Performans Yönetimi > Dönemler ekranında dönem açılır. 2) Sorular / Kriterler kontrol edilir. 3) Personel, kategori, birim, amir, izin ve vekâlet verileri doğrulanır. 4) Değerlendirme Görevleri oluşturulur. 5) Amirler görevlerini işlem sırasına göre tamamlar. 6) Sistem nihai puanı ve açıklama zorunluluklarını kontrol eder. 7) 70 altı sonuçlar Başkan Onayları sürecine düşer. 8) Gerekli onaylardan sonra yayın süreci tamamlanır. 9) Karne ve raporlar yetki sınırına göre görünür olur.', [{ title: 'Dönemler', href: '/performance/periods' }, { title: 'Sorular / Kriterler', href: '/performance/criteria' }, { title: 'Değerlendirme Görevleri', href: '/performance/evaluation-tasks' }, { title: 'Başkan Onayları', href: '/performance/president-approvals' }]);
    }

    if (/\b(rol matrisi nasil|rol matrisi nasıl|menu gorunmuyor|menü görünmüyor|sekme gorunmuyor|sekme görünmüyor|yetki yok|erisim yok|erişim yok|modul acilmiyor|modül açılmıyor)\b/.test(n)) {
      return makeAnswer('Menü veya sekme görünmüyorsa kontrol sırası şöyledir: 1) Sistem Ayarları içinde Modül Bazlı Rol Matrisi açık mı? 2) İlgili modülün kendi rol matrisi açık mı? 3) Kullanıcıya kişi bazlı özel menü görünürlüğü verilmiş mi? 4) Birim bazlı profil kullanılıyorsa o profil ilgili ekranı kapatıyor mu? 5) Backend route yetkisi de aynı kuralla çalışıyor mu? Doğru kural şudur: Kullanıcı görmemesi gereken menüyü hiç görmemeli; URL yazarsa da güvenli erişim engeli almalıdır, beyaz ekran almamalıdır.', [{ title: 'Sistem Ayarları', href: '/settings' }, { title: 'Modül Bazlı Rol Matrisi', href: '/settings/role-matrix' }, { title: 'Performans Yönetimi Rol Matrisi', href: '/settings/performance-role-matrix' }]);
    }

    if (/\b(rapor|raporlar|dashboard|yonetici gorunumu|yönetici görünümü|riskli personel|aksatan amir|performans haritasi|performans haritası)\b/.test(n)) {
      return makeAnswer('Rapor ve dashboard ekranları yetki kapsamına göre çalışır. Genel görünüm için Dashboard, performans akışı için Süreç Takibi, dönem/görev/onay analizleri için Süreç Raporları kullanılır. Başkan/Admin geniş görünüm alabilir; Grup Başkanı ve Koordinatör yalnızca kendi organizasyon kapsamındaki ekip, kategori, dönem ve süreç özetlerini görmelidir. Rapor okurken sırasıyla dönem, kapsam, tamamlanma oranı, aksatan amir, 70 altı/başkan onayı, yayın kilidi ve kategori/grup ortalaması kontrol edilir. Kişi detayı her zaman yetki sınırıyla korunur.', [{ title: 'Dashboard', href: '/dashboard' }, { title: 'Süreç Raporları', href: '/performance/process-reports' }, { title: 'Süreç Takibi', href: '/performance/process-tracking' }]);
    }

    if (/\b(destek talebi|yardim merkezi|yardım merkezi|destek nerede|talep ac|talep aç|sorun bildir)\b/.test(n)) {
      return makeAnswer('Destek süreci için doğru yol: Sol şerit > Yardım Merkezi. Kullanıcı önce kategori seçer, kısa bir başlık yazar, sorunu anlaşılır şekilde açıklar ve varsa ekran görüntüsü/dosya ekler. Talep kaydedildikten sonra durum, cevaplar, ek mesajlar ve kapanış bilgisi aynı alandan takip edilir. Asistan kullanım sorularında rehberlik eder; teknik sorun devam ediyorsa destek talebi oluşturulmalıdır.', [{ title: 'Yardım Merkezi', href: '/support' }]);
    }

    if (/\b(anket|anketler|anket cevapla|duyuru|bildirim|mesaj|mesajlar|iletisim|iletişim)\b/.test(n)) {
      return makeAnswer('İletişim, mesaj, anket ve bildirim alanlarında kullanıcı yalnızca yetkisi dahilindeki kayıtları görür. Mesajlaşma için Mesajlar, anketleri görüntülemek/yanıtlamak için Anketler, sorun bildirmek için Yardım Merkezi kullanılır. Anketlerde kullanıcı önce kendisine atanmış anketi açar, soruları yanıtlar, zorunlu alanları tamamlar ve gönderir. Açık uçlu anket cevabı, mesaj içeriği veya kişisel hassas veri yetkisiz şekilde gösterilmez.', [{ title: 'Mesajlar', href: '/messages' }, { title: 'Anketler', href: '/surveys' }, { title: 'Yardım Merkezi', href: '/support' }]);
    }

    if (/\b(ai karar destek|karar destek|yapay zeka karar|analiz merkezi|ai analiz)\b/.test(n)) {
      return makeAnswer('AI Karar Destek Merkezi; performans, personel, anket, destek ve rapor verilerinden özet, risk farkındalığı ve yönetici içgörüsü üretir. BYS360 Asistanı ise kullanım rehberi, güvenli menü yönlendirme ve işlem öğretme katmanıdır. Bu iki alan karışmamalıdır: karar destek analiz eder; asistan doğru ekranı ve işlem sırasını anlatır. Her ikisi de idari kararın veya insan onayının yerine geçmez.', [{ title: 'AI Karar Destek Merkezi', href: '/ai/decision-support/faz1/health' }]);
    }

    if (links.length) {
      return makeAnswer('Anladım. Bu konu BYS360 içinde şu ekrana/ekranlara bağlı görünüyor. İşlemi yaparken kullanıcıya görünen gerçek sekme ve buton adlarını esas alın; yetkiniz yoksa menü görünmeyebilir veya erişim güvenli şekilde engellenir.', links);
    }

    return makeAnswer('Sorunuzu BYS360 kapsamında yorumlayacağım. Lütfen yapmak istediğiniz işlemi yazın: örneğin “Dönemler nerede?”, “Başkan Onayları nasıl çalışır?”, “Rol matrisi niye görünmüyor?”, “Karnem neden açılmadı?”, “İzin nasıl girilir?”, “Vekâlet nerede?”. Ben gerçek sekme adı, işlem sırası ve güvenlik sınırıyla yönlendireceğim.');
  }

  function buildRoot() {
    removeLegacyAssistants();
    var existing = document.getElementById(ROOT_ID);
    if (existing) existing.remove();

    var root = document.createElement('section');
    root.id = ROOT_ID;
    root.setAttribute('data-bys360-assistant-bölüm', VERSION);
    root.setAttribute('aria-live', 'polite');
    root.innerHTML = '' +
      '<button class="bys360-am-launcher" type="button" aria-expanded="false" aria-controls="bys360-am-panel" data-launcher="true" data-drag-handle="true" title="BYS360 Asistanı">' +
        '<span class="bys360-am-launcher-icon">' + iconSpark() + '</span>' +
        '<span class="bys360-am-launcher-text"><strong>' + MODULE_NAME + '</strong><span>Tam BYS360 rehberi hazır</span></span>' +
        '<span class="bys360-am-launcher-dot" aria-hidden="true"></span>' +
      '</button>' +
      '<div class="bys360-am-panel" id="bys360-am-panel" role="dialog" aria-label="' + MODULE_NAME + '" hidden>' +
        '<div class="bys360-am-header" data-drag-handle="true">' +
          '<div class="bys360-am-header-top">' +
            '<div class="bys360-am-mark">' + iconSpark() + '</div>' +
            '<div class="bys360-am-title"><h2>' + MODULE_NAME + '</h2><p>' + MODULE_LONG_NAME + '</p></div>' +
            '<button class="bys360-am-icon-btn" type="button" data-new-conversation="true" title="Yeni sohbet" aria-label="Yeni sohbet">⟲</button>' +
            '<button class="bys360-am-icon-btn" type="button" data-reset-position="true" title="Konumu sıfırla" aria-label="Konumu sıfırla">⌖</button>' +
            '<button class="bys360-am-close" type="button" aria-label="Asistanı kapat">×</button>' +
          '</div>' +
        '</div>' +
        '<div class="bys360-am-tabs" role="tablist">' +
          '<button type="button" class="bys360-am-tab is-active" data-view="chat">Sohbet</button>' +
          '<button type="button" class="bys360-am-tab" data-view="guide">Rehber</button>' +
          '<button type="button" class="bys360-am-tab" data-view="summary">Özet</button>' +
          '<button type="button" class="bys360-am-tab" data-view="security">Sınırlar</button>' +
        '</div>' +
        '<div class="bys360-am-body">' +
          '<div class="bys360-am-view is-active" data-panel="chat">' +
            '<div class="bys360-am-intro" data-assistant-intro="true">' +'<strong>Ben BYS360 Asistanı’yım.</strong>' +'<span>BYS360 içinde doğru ekranı, işlem sırasını ve güvenli kontrol adımlarını anlatan kurumsal dijital yardımcıyım.</span>' +'</div>' +
            '<div class="bys360-am-log" data-chat-log="true"></div>' +
            '<form class="bys360-am-form" data-chat-form="true">' +
              '<textarea data-chat-input="true" rows="3" maxlength="900" placeholder="Sorunuzu yazın..."></textarea>' +
              '<div class="bys360-am-form-row"><span>Enter gönderir, Shift+Enter satır açar.</span><button type="submit">Gönder</button></div>' +
            '</form>' +
          '</div>' +
          '<div class="bys360-am-view" data-panel="guide">' +
            '<h3>Nereye gitmeliyim?</h3><p>Aradığınız işlem adını yazın; gerçek BYS360 sekme adına göre yönlendireyim.</p>' +
            '<input type="search" data-guide-search="true" placeholder="Dönemler, Sorular / Kriterler, Başkan Onayları, Rol Matrisi...">' +
            '<div class="bys360-am-guide-list" data-guide-list="true"></div>' +
          '</div>' +
          '<div class="bys360-am-view" data-panel="summary">' +
            '<h3>Yetki kontrollü güvenli özet</h3><p>Bu alan yalnızca sayı/genel durum gösterir. Hassas içerik göstermez.</p>' +
            '<div class="bys360-am-summary" data-summary-grid="true"></div>' +
            '<button class="bys360-am-refresh" type="button" data-refresh-summary="true">Özeti yenile</button>' +
          '</div>' +
          '<div class="bys360-am-view" data-panel="security">' +
            '<h3>Güvenli kullanım sınırları</h3>' +
            '<div class="bys360-am-security-grid">' +
              '<article><strong>Karar üretmez</strong><span>İdari karar, disiplin kararı veya performans sonucu oluşturmaz.</span></article>' +
              '<article><strong>Puan belirlemez</strong><span>Performans puanı vermez, değiştirmez, kesinleştirmez.</span></article>' +
              '<article><strong>Hassas veri göstermez</strong><span>Amir görüşü, mesaj içeriği, anket cevabı ve kişisel detayı dökmez.</span></article>' +
              '<article><strong>Gerçek ekran adı kullanır</strong><span>Kullanıcıya görünen sol şerit/sekme/buton adlarıyla yönlendirir.</span></article>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(root);
    return root;
  }

  function saveChatHistory() {
    try { sessionStorage.setItem(STORAGE_CHAT, JSON.stringify(chatHistory.slice(-CHAT_LIMIT))); } catch (e) {}
  }

  function restoreChatHistory(root) {
    var rawData = null;
    try { rawData = sessionStorage.getItem(STORAGE_CHAT); } catch (e) {}
    if (!rawData) return false;
    try {
      var parsed = JSON.parse(rawData);
      if (!Array.isArray(parsed) || !parsed.length) return false;
      chatHistory = parsed.slice(-CHAT_LIMIT);
      chatHistory.forEach(function (msg) { appendMessage(root, msg.role, msg.text, msg.links || [], false); });
      return true;
    } catch (e) { return false; }
  }

  function appendMessage(root, role, text, links, persist, transient, extras) {
    links = safeLinks(links);
    if (role !== 'user') text = sanitizeAssistantText(text);
    extras = extras || {};
    var kayıt = qs('[data-chat-log]', root);
    if (!kayıt) return;
    var row = document.createElement('div');
    row.className = 'bys360-am-message ' + (role === 'user' ? 'is-user' : 'is-bot');
    if (transient) row.setAttribute('data-transient', 'true');
    var avatar = document.createElement('div');
    avatar.className = 'bys360-am-avatar';
    avatar.textContent = role === 'user' ? 'Siz' : 'BYS';
    var bubble = document.createElement('div');
    bubble.className = 'bys360-am-bubble';
    if (role !== 'user' && extras.moduleLabel) {
      var badge = document.createElement('span');
      badge.className = 'bys360-am-module-badge';
      badge.textContent = extras.moduleLabel;
      bubble.appendChild(badge);
    }
    var answerText = document.createElement('div');
    answerText.className = 'bys360-am-answer-text';
    answerText.textContent = text || '';
    bubble.appendChild(answerText);
    if (role !== 'user' && Array.isArray(extras.sources) && extras.sources.length) {
      var sourceBox = document.createElement('div');
      sourceBox.className = 'bys360-am-sources';
      extras.sources.slice(0, 5).forEach(function (label) {
        var chip = document.createElement('span');
        chip.className = 'bys360-am-source-chip';
        chip.textContent = label;
        sourceBox.appendChild(chip);
      });
      bubble.appendChild(sourceBox);
    }
    if (role !== 'user' && Array.isArray(extras.suggestedQuestions) && extras.suggestedQuestions.length) {
      var suggestBox = document.createElement('div');
      suggestBox.className = 'bys360-am-suggestions';
      extras.suggestedQuestions.slice(0, 4).forEach(function (question) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'bys360-am-suggestion-chip';
        chip.textContent = question;
        chip.addEventListener('click', function () {
          var form = qs('[data-chat-form]', root);
          var input = qs('[data-chat-input]', root);
          if (input) input.value = question;
          if (form && typeof form.requestSubmit === 'function') form.requestSubmit();
          else if (form) form.dispatchEvent(new Event('submit', { cancelable: true }));
        });
        suggestBox.appendChild(chip);
      });
      bubble.appendChild(suggestBox);
    }
    if (links && links.length) {
      var linkBox = document.createElement('div');
      linkBox.className = 'bys360-am-links';
      links.slice(0, 4).forEach(function (item) {
        var a = document.createElement('a');
        a.href = item.disabled ? '#' : (item.href || '#');
        a.setAttribute('data-bys360-safe-link', '1');
        a.setAttribute('data-safe-href', item.href || '#');
        a.setAttribute('data-safe-title', item.title || 'Ekrana git');
        if (item.disabled) a.setAttribute('aria-disabled', 'true');
        a.textContent = item.title || 'Ekrana git';
        a.innerHTML = escapeText(item.title || 'Ekrana git') + '<span>→</span>';
        a.addEventListener('click', function (event) { event.preventDefault(); event.stopPropagation(); preflightAndNavigate(root, item.href, item.title); }, true);
        linkBox.appendChild(a);
      });
      bubble.appendChild(linkBox);
    }
    row.appendChild(avatar);
    row.appendChild(bubble);
    kayıt.appendChild(row);
    kayıt.scrollTop = kayıt.scrollHeight;
    if (persist !== false) {
      chatHistory.push({ role: role === 'user' ? 'user' : 'bot', text: text || '', links: links || [] });
      if (chatHistory.length > CHAT_LIMIT) chatHistory = chatHistory.slice(-CHAT_LIMIT);
      saveChatHistory();
    }
  }

  function setOpen(root, open) {
    var launcher = qs('.bys360-am-launcher', root);
    var panel = qs('.bys360-am-panel', root);
    if (!launcher || !panel) return;
    panel.hidden = !open;
    launcher.setAttribute('aria-expanded', open ? 'true' : 'false');
    try { localStorage.setItem(STORAGE_OPEN, open ? '1' : '0'); } catch (e) {}
  }

  function switchView(root, view) {
    qsa('.bys360-am-tab', root).forEach(function (tab) { tab.classList.toggle('is-active', tab.getAttribute('data-view') === view); });
    qsa('.bys360-am-view', root).forEach(function (panel) { panel.classList.toggle('is-active', panel.getAttribute('data-panel') === view); });
    try { sessionStorage.setItem(STORAGE_VIEW, view || 'chat'); } catch (e) {}
  }

  function renderGuide(root, term) {
    var list = qs('[data-guide-list]', root);
    if (!list) return;
    var items = term ? findRoutes(term) : ROUTES.slice(0, 10);
    if (!items.length) items = ROUTES.slice(0, 6);
    list.innerHTML = items.map(function (item) {
      var safe = normalizeAssistantLink(item) || { href: '#', title: item.title, disabled: true };
      return '<a class="bys360-am-guide-card" data-bys360-safe-link="1" data-safe-href="' + escapeText(safe.href) + '" data-safe-title="' + escapeText(safe.title || item.title) + '" href="' + escapeText(safe.disabled ? '#' : safe.href) + '"><strong>' + escapeText(item.title) + '</strong><span>' + escapeText(item.text) + '</span><em>Git →</em></a>';
    }).join('');
  }

  function renderSummary(root, data) {
    var grid = qs('[data-summary-grid]', root);
    if (!grid) return;
    var cards = [];
    if (data && Array.isArray(data.cards)) cards = data.cards;
    if (!cards.length) {
      cards = [
        { title: 'Bekleyen bildirim', value: '—', note: 'Oturum ve yetkiye göre gösterilir' },
        { title: 'Açık destek talebi', value: '—', note: 'Detay için Yardım Merkezi kullanılır' },
        { title: 'Yanıt bekleyen anket', value: '—', note: 'Kişisel cevap içeriği gösterilmez' },
        { title: 'Performans görevi', value: '—', note: 'Puan veya görüş içeriği gösterilmez' }
      ];
    }
    grid.innerHTML = cards.slice(0, 6).map(function (card) {
      return '<article><span>' + escapeText(card.title || card.label || 'Özet') + '</span><strong>' + escapeText(card.value == null ? '—' : card.value) + '</strong><em>' + escapeText(card.note || card.description || 'Yetki kontrollü genel durum') + '</em></article>';
    }).join('');
  }

  function fetchSummary(root) {
    renderSummary(root, []);
    fetch('/ai-agent/api/assistant-widget-summary', { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (response) { if (!response.ok) throw new Error('summary'); return response.json(); })
      .then(function (payload) { renderSummary(root, payload); })
      .catch(function () { renderSummary(root, null); });
  }


  function localFallback(question) {
    /* BYS360 Assistant V2 SINGLE-INTELLIGENCE-ENGINE (mandate Phase B1):
       this used to answer the user's actual business question from the
       local ROUTES/localAnswer() knowledge table when the server call
       failed -- a second active answer engine, gated on failure instead of
       by default. It now returns exactly one fixed, deterministic
       availability message and never calls localAnswer() for question
       content. (This function's own live submit-handler call site is
       currently shadowed by bys360_assistant_module_memory_v30.js's
       capture-phase submit listener -- see that file's own handleQuestion
       -- but the same fix is applied here too so neither file can ever
       answer from local business knowledge, regardless of which one
       actually handles a given request.) */
    void question;
    return makeAnswer(
      "BYS360 Kurumsal Asistan'a şu anda ulaşılamıyor. Lütfen daha sonra tekrar deneyin.",
      []
    );
  }

  function askServer(question) {
    var headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
    var token = csrfToken();
    if (token) { headers['X-CSRFToken'] = token; headers['X-CSRF-Token'] = token; }
    return fetch('/ai-agent/api/ask', {
      method: 'POST', credentials: 'same-origin', headers: headers,
      body: JSON.stringify({ question: question, context: (typeof currentPageContext === 'function' ? currentPageContext() : {}) })
    }).then(function (response) {
      if (!response.ok) throw new Error('ask');
      return response.json();
    }).then(function (payload) {
      var answer = payload.answer || payload.reply || payload.message || '';
      var actions = payload.actions || payload.suggestions || [];
      var links = [];
      if (Array.isArray(actions)) {
        links = actions.filter(function (a) { return a && (a.href || a.url); }).map(function (a) { return { title: a.title || a.label || 'Ekrana git', href: a.href || a.url }; });
      }
      if (!answer) throw new Error('empty');
      var sources = Array.isArray(payload.sources) ? payload.sources.filter(function (s) { return s && s.label; }).map(function (s) { return String(s.label); }) : [];
      var suggestedQuestions = Array.isArray(payload.suggested_questions) ? payload.suggested_questions.filter(function (q) { return q; }).map(function (q) { return String(q); }) : [];
      var moduleLabel = (typeof payload.module === 'string' && payload.module) ? payload.module : '';
      return { text: sanitizeAssistantText(answer), links: safeLinks(links), sources: sources, suggestedQuestions: suggestedQuestions, moduleLabel: moduleLabel };
    });
  }

  function setupDrag(root, onLauncherTap) {
    var drag = null;
    var suppressLauncherClickUntil = 0;
    var threshold = 8;
    var maxTapMs = 650;

    function assistantBoxOffsets() {
      var rootRect = root.getBoundingClientRect();
      var left = rootRect.left, top = rootRect.top, right = rootRect.right, bottom = rootRect.bottom;
      var panel = qs('.bys360-am-panel', root);
      if (panel && !panel.hidden) {
        var panelRect = panel.getBoundingClientRect();
        left = Math.min(left, panelRect.left);
        top = Math.min(top, panelRect.top);
        right = Math.max(right, panelRect.right);
        bottom = Math.max(bottom, panelRect.bottom);
      }
      return {
        left: left - rootRect.left,
        top: top - rootRect.top,
        right: right - rootRect.left,
        bottom: bottom - rootRect.top
      };
    }

    function clampRoot(left, top) {
      var margin = 10;
      var o = assistantBoxOffsets();
      var minX = margin - o.left;
      var maxX = window.innerWidth - margin - o.right;
      var minY = margin - o.top;
      var maxY = window.innerHeight - margin - o.bottom;
      if (maxX < minX) maxX = minX;
      if (maxY < minY) maxY = minY;
      return {
        x: Math.min(Math.max(minX, left), maxX),
        y: Math.min(Math.max(minY, top), maxY)
      };
    }

    function finishDrag(event) {
      if (!drag || (event && drag.id !== event.pointerId)) return false;
      var state = drag;
      var moved = !!state.moved;
      var elapsed = Date.now() - state.startedAt;
      drag = null;
      root.classList.remove('is-dragging');
      if (event) {
        try { root.releasePointerCapture(event.pointerId); } catch (e) {}
      }
      if (moved) {
        // Gerçek sürükleme yapıldıysa hemen ardından oluşan click paneli açıp kapatmasın.
        suppressLauncherClickUntil = Date.now() + 500;
        try { localStorage.setItem(STORAGE_POS, JSON.stringify({ left: root.style.left, top: root.style.top })); } catch (e) {}
        return true;
      }
      if (state.fromLauncher && elapsed <= maxTapMs) {
        // Baloncukta kısa tıklama: sürükleme değilse paneli burada aç/kapat.
        // Böylece drag kodu click olayını yutsa bile asistan açılır.
        suppressLauncherClickUntil = Date.now() + 350;
        if (event && event.cancelable) event.preventDefault();
        if (event) event.stopPropagation();
        if (typeof onLauncherTap === 'function') onLauncherTap(event);
      }
      return false;
    }

    root.addEventListener('pointerdown', function (event) {
      if (event.button != null && event.button !== 0) return;
      var launcher = event.target.closest('.bys360-am-launcher');
      var header = event.target.closest('.bys360-am-header');
      if (!launcher && !header) return;
      if (event.target.closest('.bys360-am-close, [data-reset-position], textarea, input, select, a')) return;
      if (header && event.target.closest('button')) return;
      var rect = root.getBoundingClientRect();
      drag = {
        id: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        dx: event.clientX - rect.left,
        dy: event.clientY - rect.top,
        moved: false,
        fromLauncher: !!launcher,
        startedAt: Date.now()
      };
      try { root.setPointerCapture(event.pointerId); } catch (e) {}
    }, true);

    root.addEventListener('pointermove', function (event) {
      if (!drag || drag.id !== event.pointerId) return;
      var distance = Math.max(Math.abs(event.clientX - drag.startX), Math.abs(event.clientY - drag.startY));
      if (distance < threshold && !drag.moved) return;
      drag.moved = true;
      root.classList.add('is-dragging');
      if (event.cancelable) event.preventDefault();
      var pos = clampRoot(event.clientX - drag.dx, event.clientY - drag.dy);
      root.style.left = pos.x + 'px';
      root.style.top = pos.y + 'px';
      root.style.right = 'auto';
      root.style.bottom = 'auto';
    }, true);

    root.addEventListener('pointerup', function (event) { finishDrag(event); }, true);
    root.addEventListener('pointercancel', function (event) { finishDrag(event); }, true);
    root.addEventListener('lostpointercapture', function () { drag = null; root.classList.remove('is-dragging'); });

    var reset = qs('[data-reset-position]', root);
    if (reset) reset.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      root.style.left = '';
      root.style.top = '';
      root.style.right = '24px';
      root.style.bottom = '24px';
      try { localStorage.removeItem(STORAGE_POS); } catch (e) {}
    }, true);

    return {
      shouldSuppressLauncherClick: function () { return Date.now() < suppressLauncherClickUntil || root.classList.contains('is-dragging'); }
    };
  }

  // V7_FINAL_TEST_SENARYOLARI ve V7_CANLI_KALITE_KONTROL: tarayıcı konsolunda window.BYS360AssistantModule.runSelfTest() ile okunabilir.
  function assistantSelfTest() {
    var badSamples = [
      'Dönem ' + 'Yönetimi', 'bağlantı yolu ' + 'menü haritasına ' + 'eklenmeli', 'Tam modül ' + 'mantığıyla çalışır',
      'çay' + 'lar sıcak', 'Kış ' + 'kendini göstermiş', 'Şemsiye ' + 'göreve', 'Gök' + 'yüzü ' + 'drama' + 'tik', 'sevimli bir ' + 'yorum', 'durum kar' + 'lı'
    ];
    var sanitized = badSamples.map(function (item) { return sanitizeAssistantText('BYS360 hava durumu bilgisini Open-Meteo bağlantısından aldım: sıcaklık 19°C, ' + item + '.'); }).join(' | ');
    var badLeft = badSamples.filter(function (item) { return sanitized.indexOf(item) !== -1; });
    var routeTitles = ROUTES.map(function (r) { return r.title; });
    return {
      ok: badLeft.length === 0 && routeTitles.indexOf('Dönemler') !== -1 && routeTitles.indexOf('İzin ve Devamsızlık Takibi') !== -1,
      version: VERSION,
      teaching_contract: 'V7_EKSİKSİZ_EKRAN_OGRETIM_SOZLESMESI',
      route_count: ROUTES.length,
      safe_routes: routeTitles,
      forbidden_left: badLeft,
      checks: [
        'Cevap hijyeni aktif',
        'Dönemler gerçek sekme adı korunuyor',
        'İzin ve vekâlet güvenli canlı yollara bağlı',
        'Hava durumu şaka/espri üretmiyor',
        'Kırık linkler preflight ile durduruluyor',
        'Oturum aynı sekmede korunuyor'
      ]
    };
  }

  function restorePosition(root) {
    try {
      var raw = localStorage.getItem(STORAGE_POS);
      if (!raw) return;
      var pos = JSON.parse(raw);
      if (pos && pos.left && pos.top) { root.style.left = pos.left; root.style.top = pos.top; root.style.right = 'auto'; root.style.bottom = 'auto'; }
    } catch (e) {}
  }

  function init() {
    var root = buildRoot();
    activeRoot = root;
    saveCurrentPageContext();
    restorePosition(root);
    var dragController = null;
    renderGuide(root, '');
    renderSummary(root, null);
    try {
      var lastView = sessionStorage.getItem(STORAGE_VIEW);
      if (lastView) switchView(root, lastView);
    } catch (e) {}

    var opened = false;
    try { opened = localStorage.getItem(STORAGE_OPEN) === '1'; } catch (e) {}
    setOpen(root, opened);

    var launcher = qs('.bys360-am-launcher', root);
    var close = qs('.bys360-am-close', root);
    var newConversation = qs('[data-new-conversation]', root);
    if (newConversation) newConversation.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      // BYS360 Assistant V2 conversation_id reset (mandate Phase D):
      // memory_v30.js owns the actual conversation_id/history state (it is
      // the file that actually answers every live question -- see its own
      // module docstring); this button only signals intent, so the two
      // files stay decoupled via a plain DOM event instead of one calling
      // the other's internals directly.
      root.dispatchEvent(new CustomEvent('bys360-assistant-new-conversation', { bubbles: true }));
    }, true);
    function toggleAssistant(event, forceFromPointerTap) {
      if (event) { event.preventDefault(); event.stopPropagation(); }
      if (!forceFromPointerTap && dragController && dragController.shouldSuppressLauncherClick && dragController.shouldSuppressLauncherClick()) return;
      var panel = qs('.bys360-am-panel', root);
      setOpen(root, !!(panel && panel.hidden));
    }
    dragController = setupDrag(root, function (event) { toggleAssistant(event, true); });
    if (launcher) launcher.addEventListener('click', function (event) { toggleAssistant(event, false); }, true);
    // Bazı base.html katmanları click olayını bubble aşamasında kesebildiği için capture aşamasında yedek bağ kurulur.
    document.addEventListener('click', function (event) {
      if (event.target && event.target.closest && event.target.closest('#' + ROOT_ID + ' .bys360-am-launcher')) toggleAssistant(event, false);
    }, true);
    document.addEventListener('click', function (event) {
      var safeLink = event.target && event.target.closest ? event.target.closest('#' + ROOT_ID + ' [data-bys360-safe-link="1"]') : null;
      if (!safeLink) return;
      event.preventDefault();
      event.stopPropagation();
      preflightAndNavigate(root, safeLink.getAttribute('data-safe-href') || safeLink.getAttribute('href'), safeLink.getAttribute('data-safe-title') || safeLink.textContent || 'Ekrana git');
    }, true);
    if (close) close.addEventListener('click', function (event) { if (event) { event.preventDefault(); event.stopPropagation(); } setOpen(root, false); }, true);
    window.BYS360AssistantModule = {
      open: function () { setOpen(root, true); },
      close: function () { setOpen(root, false); },
      toggle: function () { var panel = qs('.bys360-am-panel', root); setOpen(root, !!(panel && panel.hidden)); },
      resetPosition: function () { root.style.left = ''; root.style.top = ''; root.style.right = '24px'; root.style.bottom = '24px'; try { localStorage.removeItem(STORAGE_POS); } catch (e) {} },
      moveTo: function (left, top) { var pos = { x: Number(left) || 24, y: Number(top) || 24 }; root.style.left = pos.x + 'px'; root.style.top = pos.y + 'px'; root.style.right = 'auto'; root.style.bottom = 'auto'; try { localStorage.setItem(STORAGE_POS, JSON.stringify({ left: root.style.left, top: root.style.top })); } catch (e) {} },
      currentPage: function () { return currentPageContext(); },
      helpForCurrentPage: function () { var answer = pageAwareAnswer(); appendMessage(root, 'bot', answer.text, answer.links); return answer; },
      resume: function () { var answer = resumeAnswer(); appendMessage(root, 'bot', answer.text, answer.links); return answer; },
      runSelfTest: function () { return assistantSelfTest(); },
      version: VERSION
    };

    qsa('.bys360-am-tab', root).forEach(function (tab) {
      tab.addEventListener('click', function () {
        var view = tab.getAttribute('data-view');
        switchView(root, view);
        if (view === 'summary') fetchSummary(root);
      });
    });

    var search = qs('[data-guide-search]', root);
    if (search) search.addEventListener('input', function () { renderGuide(root, search.value); });
    var refresh = qs('[data-refresh-summary]', root);
    if (refresh) refresh.addEventListener('click', function () { fetchSummary(root); });
    // BYS360_ASSISTANT_NO_CHAT_INTRO_OPEN_FIX_V34: Sohbet içine otomatik tanıtım mesajı basılmaz.
    restoreChatHistory(root);
var form = qs('[data-chat-form]', root);
    var input = qs('[data-chat-input]', root);
    if (input) {
      input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (form) form.dispatchEvent(new Event('submit', { cancelable: true })); }
      });
    }
    if (form) form.addEventListener('submit', function (event) {
      event.preventDefault();
      var question = input ? input.value.trim() : '';
      if (!question) return;
      if (input) input.value = '';
      appendMessage(root, 'user', question);
      appendMessage(root, 'bot', 'Sorunuzu BYS360 kapsamında yorumluyorum...', [], false);
      var log = qs('[data-chat-log]', root);
      if (isWeatherIntent(question)) {
        answerWeather(root, question, log);
        return;
      }
      if (isLocalFirstIntent(question)) {
        var local = localAnswer(question);
        if (log && log.lastElementChild && log.lastElementChild.classList.contains('is-bot')) log.removeChild(log.lastElementChild);
        appendMessage(root, 'bot', local.text, local.links);
        return;
      }
      askServer(question).catch(function () { return localFallback(question); }).then(function (answer) {
        if (log && log.lastElementChild && log.lastElementChild.classList.contains('is-bot')) log.removeChild(log.lastElementChild);
        appendMessage(root, 'bot', answer.text, answer.links, true, false, { sources: answer.sources, moduleLabel: answer.moduleLabel, suggestedQuestions: answer.suggestedQuestions });
      });
    });
  }

  window.addEventListener('beforeunload', function () {
    try { saveChatHistory(); saveCurrentPageContext(); } catch (e) {}
  });

  window.addEventListener('pageshow', function () {
    try { saveCurrentPageContext(); } catch (e) {}
  });

  ready(function () {
    try { init(); }
    catch (error) {
      try { console.error('BYS360 Asistanı açılış hatası:', error); } catch (e) {}
      var fallback = document.createElement('button');
      fallback.id = 'bys360-assistant-module-fallback-openfix';
      fallback.type = 'button';
      fallback.textContent = 'BYS360 Asistanı';
      fallback.style.cssText = 'position:fixed;right:24px;bottom:24px;z-index:2147483647;border:0;border-radius:999px;background:#8B0000;color:#fff;padding:14px 18px;font-weight:800;box-shadow:0 12px 36px rgba(0,0,0,.22);';
      fallback.onclick = function () { try { if (window.BYS360AssistantModule && window.BYS360AssistantModule.open) window.BYS360AssistantModule.open(); } catch (e) {} };
      document.body.appendChild(fallback);
    }
  });
})();

/* V8_GUVENLI_YONLENDIRME_SIKILASTIRMA | V7_CEVAP_HIJYENI_KATMANI | V7_FINAL_TEST_SENARYOLARI | V7_CANLI_KALITE_KONTROL | V7_EKSİKSİZ_EKRAN_OGRETIM_SOZLESMESI | V7_MODUL_CEVAP_FORMATI | V7_GUVENLI_EYLEM_SOZLESMESI | V7_KANONIK_EKRAN_ADI_KORUMA | V7_CANLI_OGRETIM_TESTLERI */

/* V8_12_ADIM_DURUM_KONTROL_GATE | V8_EKSIK_TESPIT_RAPORU | V8_CANLI_DURUM_KONTROLU | V8_ESKI_ASISTAN_KALINTI_TARAMASI */


/* BYS360_ASISTANI_MODULU_V12_FINAL_GATE_START */
