(function(){
  "use strict";

  const V12 = {
    version: "V12",
    canonicalName: "BYS360 Asistanı",
    canonicalFullName: "BYS360 Asistanı — Kurumsal Rehberlik, Akıllı Yönlendirme ve Yetki Kontrollü Dijital Yardımcı",
    forbiddenPhrases: [
      "Dönemler",
      "/hr-management/leave",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      ""
    ],
    safeMenu: {
      "home": { title: "Ana Sayfa", url: "/home" },
      "personnel": { title: "Personel Yönetimi", url: "/hr-management" },
      "leave": { title: "İzin ve Devamsızlık Takibi", url: "/hr-management/leave" },
      "delegation": { title: "Devamsızlık ve Vekâlet", url: "/hr-management/attendance" },
      "performance": { title: "Performans Yönetimi", url: "/performance" },
      "periods": { title: "Dönemler", url: "/performance/periods" },
      "criteria": { title: "Değerlendirme Kriterleri", url: "/performance/criteria" },
      "assignments": { title: "Görev Üretimi", url: "/performance/assignments" },
      "my_tasks": { title: "Değerlendirme Görevlerim", url: "/performance/my-tasks" },
      "scorecards": { title: "Karne", url: "/performance/scorecards" },
      "president_approvals": { title: "Başkan Onayları", url: "/performance/president-approvals" },
      "reports": { title: "Raporlar", url: "/performance/reports" },
      "settings": { title: "Sistem Ayarları", url: "/settings" },
      "role_matrix": { title: "Rol Matrisi", url: "/settings/role-matrix" },
      "support": { title: "Destek Talepleri", url: "/support" },
      "survey": { title: "Anketler", url: "/surveys" },
      "notifications": { title: "Bildirimler", url: "/notifications" },
      "ai_decision": { title: "AI Karar Destek Merkezi", url: "/ai/decision-support" }
    },
    legacyRedirects: {
      "/hr-management/leave": "/hr-management/leave",
      "/personnel/leave": "/hr-management/leave",
      "/personnel/delegation": "/hr-management/attendance",
      "/personnel/attendance": "/hr-management/attendance",
      "/performance/period-management": "/performance/periods",
      "/performans/donem-yonetimi": "/performance/periods"
    }
  };

  function cleanText(text){
    let out = String(text || "");
    out = out.replaceAll("Dönemler", "Dönemler");
    out = out.replaceAll("/hr-management/leave", "/hr-management/leave");
    V12.forbiddenPhrases.forEach(function(p){
      if (p === "Dönemler" || p === "/hr-management/leave") return;
      out = out.split(p).join("");
    });
    return out.replace(/\n{3,}/g, "\n\n").trim();
  }

  function weatherConsistency(text){
    let out = cleanText(text);
    const hasWarm = /\b(1[5-9]|2[0-9]|3[0-9])\s*°?\s*C\b/i.test(out);
    const hasSnow = /(karlı|kar yağış|snow)/i.test(out);
    if (hasWarm && hasSnow) {
      out = out.replace(/durum\s*:?\s*karlı\.?/ig, "");
      out = out.replace(/karlı hava[^.]*\./ig, "");
      out += "\n\nHava açıklaması sıcaklık bilgisiyle uyumlu görünmediği için yalnızca doğrulanabilen bilgileri dikkate almanız önerilir.";
    }
    return cleanText(out);
  }

  function answerLocal(question){
    const q = String(question || "").toLocaleLowerCase("tr-TR");

    if (/v12|final|12 adım|canlı test|son kontrol/.test(q)) {
      return [
        "V12 final kontrol için şu başlıkları sınayabilirim:",
        "1. Gerçek menü ve sekme adları",
        "2. Güvenli yönlendirme ve kırık link engeli",
        "3. Personel Yönetimi",
        "4. İzin, devamsızlık ve vekâlet",
        "5. Performans Yönetimi",
        "6. Rol matrisi ve menü görünürlüğü",
        "7. Dashboard ve raporlar",
        "8. İletişim, anket, destek ve bildirimler",
        "9. AI Karar Destek ayrımı",
        "10. Kendini tanıtma ve günlük konuşma",
        "11. Oturum ve sayfa geçişi koruma",
        "12. Final canlı test senaryoları"
      ].join("\n");
    }

    if (/sen kimsin|seni kim gelistirdi|seni kim geliştirdi|kim gelistirdi|kim geliştirdi|kim yaptı|kim yapti|havva gulsen ozden|havva gülsen özden|gulsen ozden|gülsen özden|nasıl çalışıyorsun|yapay zekaya bağlı mısın|chatgpt misin/.test(q)) {
      return "Ben BYS360 Asistanı’yım. BYS360 için Havva Gülsen Özden (geliştirici) ve Mustafa Bektaş (eş geliştirici) tarafından geliştirildim. Görevim, BYS360 içinde yetkiniz dâhilindeki işlemleri sade, güvenli ve doğru sırayla anlatmak; sizi gerçek ekranlara yönlendirmek ve sistemi daha kolay kullanmanıza yardımcı olmaktır. İdari karar üretmem, performans puanı belirlemem ve hassas veri göstermem.";
    }

    if (/neler yapabiliyorsun|hangi konularda yardımcı|bana nasıl yardımcı/.test(q)) {
      return "BYS360 içinde personel işlemleri, izin-devamsızlık-vekalet süreçleri, performans dönemleri, Değerlendirme Kriterleri, görev üretimi, Başkan Onayları, karne-yayın süreci, rol matrisi, menü görünürlüğü, raporlar, destek talepleri, anketler, bildirimler ve AI Karar Destek Merkezi hakkında adım adım yardımcı olurum.";
    }

    if (/izin|devamsızlık|vekalet|vekâlet/.test(q)) {
      return [
        "Bu konu Personel Yönetimi içindedir.",
        "",
        "Doğru ekranlar:",
        "- İzin işlemleri: Personel Yönetimi > İzin ve Devamsızlık Takibi",
        "- Vekâlet ve devamsızlık takibi: Personel Yönetimi > Devamsızlık ve Vekâlet",
        "",
        "Adım adım:",
        "1. Sol şeritten Personel Yönetimi bölümünü açın.",
        "2. İşleme göre İzin ve Devamsızlık Takibi veya Devamsızlık ve Vekâlet ekranına girin.",
        "3. Personeli Sicil No, ad-soyad veya birim bilgisiyle bulun.",
        "4. İzin, devamsızlık veya vekâlet bilgilerini tarih aralığıyla kaydedin.",
        "5. İşlemden sonra kayıt listesinde durumun oluştuğunu kontrol edin.",
        "",
        "Dikkat: İzinli amir varsa performans, onay veya görev akışları vekâlet tanımından etkilenebilir."
      ].join("\n");
    }

    if (/dönem|donem|performans dönemi|dönemler/.test(q)) {
      return [
        "Bu işlem Performans Yönetimi > Dönemler ekranından yapılır.",
        "",
        "Adım adım:",
        "1. Sol şeritten Performans Yönetimi bölümünü açın.",
        "2. Dönemler sekmesine girin.",
        "3. Yeni dönem oluşturma butonunu kullanın.",
        "4. Dönem adı, türü, başlangıç-bitiş tarihi ve kapsam bilgisini doldurun.",
        "5. Kaydettikten sonra Değerlendirme Kriterleri, ağırlıklar ve görev üretimini kontrol edin."
      ].join("\n");
    }

    if (/başkan onay|70 alt|düşük performans/.test(q)) {
      return [
        "Başkan Onayları, 70 altı performans sonuçlarının üst onay sürecini takip etmek için kullanılır.",
        "",
        "Temel akış:",
        "1. Değerlendirme tamamlanır.",
        "2. Nihai puan 70 altındaysa sonuç doğrudan yayınlanmaz.",
        "3. Kayıt Başkan Onayları ekranına düşer.",
        "4. Onay süreci tamamlanmadan karne personele açılmaz.",
        "5. Süreç tamamlandığında yayın ve personel geçmişi kayıtları yetki sınırına göre görünür."
      ].join("\n");
    }

    if (/rol matrisi|menü görünmüyor|menüm yok|yetki|görünürlük/.test(q)) {
      return [
        "Bu konu Sistem Ayarları ve yetki görünürlüğüyle ilgilidir.",
        "",
        "Kontrol sırası:",
        "1. Modül bazlı rol matrisi açık mı kontrol edin.",
        "2. Performans rol matrisi ilgili rol için doğru mu bakın.",
        "3. Kişi bazlı menü görünürlüğü kapalı mı kontrol edin.",
        "4. Birim bazlı profil ilgili kullanıcıyı etkiliyor mu bakın.",
        "5. Menü görünse bile erişim yoksa backend route yetkisi ayrıca kontrol edilmelidir.",
        "",
        "Dikkat: Yetkisi olmayan kullanıcı menüyü görmemeli; linki yazsa bile veri alamamalıdır."
      ].join("\n");
    }

    if (/bu sayfada|bu ekran|nereden devam|kaldığımız yer|az önceki konu/.test(q)) {
      const path = window.location ? window.location.pathname : "";
      return "Şu an bulunduğunuz ekranı dikkate alarak yardımcı olabilirim. Sayfa yolu: " + path + ". Sorunuzu bu ekran üzerinden sorarsanız ilgili işlem adımlarını buradan devam ettiririm.";
    }

    return null;
  }

  function install(){
    window.BYS360AssistantV12 = V12;
    window.BYS360AssistantCleanText = weatherConsistency;
    window.BYS360AssistantLocalAnswer = answerLocal;

    const oldSend = window.BYS360AssistantModule && window.BYS360AssistantModule.answer;
    if (window.BYS360AssistantModule) {
      window.BYS360AssistantModule.version = "V12";
      window.BYS360AssistantModule.cleanText = weatherConsistency;
      window.BYS360AssistantModule.localAnswer = answerLocal;
      if (typeof oldSend === "function") {
        window.BYS360AssistantModule.answer = function(question){
          const local = answerLocal(question);
          if (local) return weatherConsistency(local);
          const result = oldSend.apply(this, arguments);
          if (typeof result === "string") return weatherConsistency(result);
          return result;
        };
      }
      window.BYS360AssistantModule.runFinalTest = function(){
        const tests = [
          "izin nasıl çalışır",
          "Dönemler nerede",
          "Başkan Onayları nasıl çalışır",
          "rol matrisi görünmüyor",
          "neler yapabiliyorsun",
          "seni kim geliştirdi",
          "bu sayfada ne yapabilirim",
          "hava nasıl"
        ];
        return tests.map(function(t){
          return { question: t, answer: weatherConsistency(answerLocal(t) || "Sunucu cevabı beklenir.") };
        });
      };
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }
})();
/* BYS360_ASISTANI_MODULU_V12_FINAL_GATE_END */

/* BYS360_V14_INTENT_ENGINE_START */
(function(){
  "use strict";

  const intentMap = [
    {
      intent: "performance_periods",
      phrases: [
        "dönem açacağım",
        "performansı başlat",
        "2026 değerlendirmesini oluştur",
        "puanlama sürecini başlatacağım",
        "dönemler nerede"
      ],
      target: "Performans Yönetimi > Dönemler",
      url: "/performance/periods"
    },
    {
      intent: "leave_management",
      phrases: [
        "izin",
        "izin gireceğim",
        "personel izinli",
        "amir izne çıktı"
      ],
      target: "Personel Yönetimi > İzin ve Devamsızlık Takibi",
      url: "/hr-management/leave"
    },
    {
      intent: "delegation_management",
      phrases: [
        "vekalet olacak",
        "vekalet",
        "vekâlet"
      ],
      target: "Personel Yönetimi > Devamsızlık ve Vekâlet",
      url: "/hr-management/attendance"
    },
    {
      intent: "role_matrix",
      phrases: [
        "menüm yok",
        "rol matrisi görünmüyor",
        "yetkim yok"
      ],
      target: "Sistem Ayarları > Rol Matrisi",
      url: "/settings/role-matrix"
    }
  ];

  function detectIntent(question){
    const q = String(question || "").toLocaleLowerCase("tr-TR");

    for (const item of intentMap){
      for (const phrase of item.phrases){
        if (q.includes(phrase.toLocaleLowerCase("tr-TR"))){
          return item;
        }
      }
    }

    return null;
  }

  window.BYS360IntentEngine = {
    version: "V14",
    detectIntent,
    intentMap
  };

})();
/* BYS360_V14_INTENT_ENGINE_END */


/* BYS360_V15_PAGE_CONTEXT_HELP_START */
(function(){
  "use strict";

  const pageHelpMap = [
    {
      match: ["/performance/periods", "/performans/donemler"],
      title: "Dönemler",
      bölüm: "Performans Yönetimi",
      help: [
        "Şu an Dönemler ekranındasınız.",
        "Bu ekrandan performans dönemleri oluşturulur, tarih aralıkları kontrol edilir ve dönem kapsamı yönetilir.",
        "",
        "Burada yapılabilecekler:",
        "1. Yeni performans dönemi oluşturma",
        "2. Dönem başlangıç ve bitiş tarihlerini kontrol etme",
        "3. Dönem kapsamını belirleme",
        "4. Dönem aktiflik durumunu izleme",
        "",
        "Dikkat: Dönem oluşturmak tek başına değerlendirmeyi başlatmaz. Değerlendirme Kriterleri, ağırlıklar ve görev üretimi de kontrol edilmelidir."
      ].join("\n")
    },
    {
      match: ["/performance/president-approvals", "/performans/baskan-onaylari"],
      title: "Başkan Onayları",
      bölüm: "Performans Yönetimi",
      help: [
        "Şu an Başkan Onayları ekranındasınız.",
        "Bu ekran 70 altı performans sonuçlarının üst onay sürecini takip etmek için kullanılır.",
        "",
        "Burada yapılabilecekler:",
        "1. Başkan onayı bekleyen düşük performans kayıtlarını görüntüleme",
        "2. Karne inceleme detayına geçme",
        "3. Yayın kilidi veya süreç durumunu kontrol etme",
        "4. Yetkiniz varsa onay/ret sürecini yürütme",
        "",
        "Dikkat: Başkan onayı tamamlanmadan 70 altı karne personele kesin/yayınlanmış sonuç olarak açılmamalıdır."
      ].join("\n")
    },
    {
      match: ["/hr-management/leave"],
      title: "İzin ve Devamsızlık Takibi",
      bölüm: "Personel Yönetimi",
      help: [
        "Şu an İzin ve Devamsızlık Takibi ekranındasınız.",
        "Bu ekrandan personelin izin kayıtları, izin tarihleri ve devamsızlık bilgileri takip edilir.",
        "",
        "Burada yapılabilecekler:",
        "1. Personel izin kaydı oluşturma veya görüntüleme",
        "2. İzin başlangıç ve bitiş tarihlerini kontrol etme",
        "3. İzin durumunun personel ve süreçlere etkisini izleme",
        "",
        "Dikkat: İzinli amir varsa performans/onay akışlarında vekâlet ilişkisi ayrıca kontrol edilmelidir."
      ].join("\n")
    },
    {
      match: ["/hr-management/attendance"],
      title: "Devamsızlık ve Vekâlet",
      bölüm: "Personel Yönetimi",
      help: [
        "Şu an Devamsızlık ve Vekâlet ekranındasınız.",
        "Bu ekran devamsızlık kayıtları ve vekâlet tanımları için kullanılır.",
        "",
        "Burada yapılabilecekler:",
        "1. Devamsızlık bilgisini kontrol etme",
        "2. Vekâlet ilişkisi tanımlama veya izleme",
        "3. Amir izinliyse sürecin kime devredileceğini kontrol etme",
        "",
        "Dikkat: Vekâlet kaydı doğru değilse onay ve değerlendirme akışları yanlış kişiye düşebilir."
      ].join("\n")
    },
    {
      match: ["/settings/role-matrix", "/settings"],
      title: "Rol Matrisi ve Sistem Ayarları",
      bölüm: "Sistem Ayarları",
      help: [
        "Şu an Sistem Ayarları / Rol Matrisi alanındasınız.",
        "Bu alan kullanıcıların hangi modül, sekme ve işlemleri görebileceğini yönetmek için kullanılır.",
        "",
        "Burada yapılabilecekler:",
        "1. Modül bazlı rol görünürlüğünü kontrol etme",
        "2. Performans rol matrisi ayarlarını kontrol etme",
        "3. Kişi bazlı menü görünürlüğünü inceleme",
        "4. Birim bazlı profil etkisini değerlendirme",
        "",
        "Dikkat: Menü görünürlüğü ile backend erişim yetkisi birlikte çalışmalıdır. Sadece menüyü gizlemek güvenlik için yeterli değildir."
      ].join("\n")
    },
    {
      match: ["/performance/reports", "/reports"],
      title: "Raporlar",
      bölüm: "Raporlar ve Dashboard",
      help: [
        "Şu an Raporlar alanındasınız.",
        "Bu ekranda performans, süreç, risk, tamamlanma ve yönetici görünürlüğü raporları izlenir.",
        "",
        "Burada yapılabilecekler:",
        "1. Dönem bazlı performans raporlarını inceleme",
        "2. Başkan onayı bekleyenleri takip etme",
        "3. Aksatan amirleri ve yayın kilitlerini kontrol etme",
        "4. Birim, grup veya kategori ortalamalarını değerlendirme",
        "",
        "Dikkat: Raporlarda kişi detayı yalnızca yetki kapsamına göre gösterilmelidir."
      ].join("\n")
    },
    {
      match: ["/support"],
      title: "Destek Talepleri",
      bölüm: "İletişim ve Destek",
      help: [
        "Şu an Destek Talepleri ekranındasınız.",
        "Bu ekrandan kullanıcı yardım talepleri oluşturulur, izlenir ve sonuçlandırılır.",
        "",
        "Burada yapılabilecekler:",
        "1. Yeni destek talebi oluşturma",
        "2. Açık talepleri takip etme",
        "3. Talep durumunu ve cevapları kontrol etme",
        "",
        "Dikkat: Destek talebine hassas kişisel veri eklenmemelidir."
      ].join("\n")
    },
    {
      match: ["/surveys"],
      title: "Anketler",
      bölüm: "İletişim ve Anket",
      help: [
        "Şu an Anketler ekranındasınız.",
        "Bu ekrandan anketler görüntülenir, yanıtlanır veya yetkiniz varsa yönetilir.",
        "",
        "Burada yapılabilecekler:",
        "1. Size atanmış anketleri görüntüleme",
        "2. Anket yanıtı verme",
        "3. Yetkiniz varsa anket oluşturma veya sonuçları izleme",
        "",
        "Dikkat: Anket cevapları yetki ve gizlilik kurallarına göre korunmalıdır."
      ].join("\n")
    },
    {
      match: ["/ai/decision-support"],
      title: "AI Karar Destek Merkezi",
      bölüm: "AI Karar Destek",
      help: [
        "Şu an AI Karar Destek Merkezi alanındasınız.",
        "Bu alan verileri özetleme, önceliklendirme, risk farkındalığı ve yönetici içgörüsü için kullanılır.",
        "",
        "Dikkat: AI Karar Destek idari karar vermez. Nihai karar yetkili insan kullanıcıdadır.",
        "BYS360 Asistanı ise bu merkezi kullanmayı ve doğru ekrana ulaşmayı öğretir."
      ].join("\n")
    },
    {
      match: ["/home", "/"],
      title: "Ana Sayfa",
      bölüm: "Genel",
      help: [
        "Şu an Ana Sayfa alanındasınız.",
        "Bu ekran BYS360 içindeki genel durum, bildirimler, bekleyen işler ve hızlı yönlendirmeler için başlangıç noktasıdır.",
        "",
        "Burada yapılabilecekler:",
        "1. Bekleyen bildirimleri kontrol etme",
        "2. Açık görev veya süreçleri görme",
        "3. İlgili modüle hızlı geçiş yapma"
      ].join("\n")
    }
  ];

  function getCurrentPath(){
    try { return window.location.pathname || "/"; } catch(e){ return "/"; }
  }

  function getPageHelp(path){
    const current = String(path || getCurrentPath());
    let best = null;
    for (const item of pageHelpMap){
      for (const m of item.match){
        if (current === m || current.startsWith(m + "/") || current.indexOf(m) === 0){
          if (!best || m.length > best._matchLength){
            best = Object.assign({_matchLength: m.length}, item);
          }
        }
      }
    }
    if (best) return best.help;
    return [
      "Bu ekran için özel yardım kaydı henüz bulunmuyor.",
      "Yine de bulunduğunuz sayfaya göre işlem adımlarını birlikte netleştirebilirim.",
      "Sayfanın adını veya yapmak istediğiniz işlemi yazarsanız sizi ilgili modül ve doğru adımlarla yönlendiririm."
    ].join("\n");
  }

  function isPageContextQuestion(question){
    const q = String(question || "").toLocaleLowerCase("tr-TR");
    return [
      "bu sayfada ne yapabilirim",
      "bu ekran ne işe yarar",
      "burada ne yapacağım",
      "bu sayfa ne",
      "şu an neredeyim",
      "nereden devam edeceğim",
      "ekranı anlat",
      "bu ekranı anlat"
    ].some(p => q.includes(p));
  }

  window.BYS360PageContextHelp = {
    version: "V15",
    pageHelpMap,
    getCurrentPath,
    getPageHelp,
    isPageContextQuestion
  };

  const oldLocal = window.BYS360AssistantLocalAnswer;
  window.BYS360AssistantLocalAnswer = function(question){
    if (isPageContextQuestion(question)){
      return getPageHelp();
    }
    if (typeof oldLocal === "function"){
      return oldLocal(question);
    }
    return null;
  };

  if (window.BYS360AssistantModule){
    window.BYS360AssistantModule.pageContextHelp = window.BYS360PageContextHelp;
  }
})();
/* BYS360_V15_PAGE_CONTEXT_HELP_END */


/* BYS360_V16_TROUBLESHOOTING_GUIDE_START */
(function(){
  "use strict";

  const troubleshootingMap = [
    {
      key: "white_screen",
      phrases: ["beyaz ekran", "sayfa beyaz", "ekran null", "500 hata", "sayfa açılmıyor"],
      answer: [
        "Bu durum sayfanın yüklenirken hata aldığını gösterir.",
        "",
        "Olası sebepler:",
        "1. Sayfa yolu eski veya kırık olabilir.",
        "2. Yetki kontrolü doğru ekran yerine hatalı sonuç döndürmüş olabilir.",
        "3. Template/Jinja hatası oluşmuş olabilir.",
        "4. Backend route hata vermiş olabilir.",
        "",
        "Kontrol sırası:",
        "1. Önce sayfa URL’sinin güvenli menü haritasında olup olmadığını kontrol edin.",
        "2. Aynı sayfaya yetkili Admin kullanıcısıyla erişmeyi deneyin.",
        "3. Waitress/uygulama loglarında ilgili route hatasını kontrol edin.",
        "4. Son yapılan overlay sonrası compileall çalıştırın.",
        "",
        "Güvenli çözüm:",
        "Kırık veya eski link kullanılıyorsa asistan bu linki önermemelidir. Gerçek canlı ekran adı ve güvenli URL kullanılmalıdır."
      ].join("\n")
    },
    {
      key: "menu_missing",
      phrases: ["menü görünmüyor", "menüm yok", "sekme görünmüyor", "sol şeritte yok", "menü yok"],
      answer: [
        "Menü görünmüyorsa konu genellikle rol matrisi veya kişi/birim bazlı görünürlük ayarıyla ilgilidir.",
        "",
        "Kontrol sırası:",
        "1. Sistem Ayarları içindeki rol matrisi ilgili rol için açık mı kontrol edin.",
        "2. Performans rol matrisi ayrıca bu sekmeyi kapatıyor mu bakın.",
        "3. Kişi bazlı menü görünürlüğü kullanıcı için kapalı mı kontrol edin.",
        "4. Birim bazlı profil bu kullanıcıyı etkiliyor mu inceleyin.",
        "5. Menü açık görünse bile backend route yetkisi ayrıca kontrol edilmelidir.",
        "",
        "Dikkat:",
        "Yetkisi olmayan kullanıcı menüyü hiç görmemeli; URL yazsa bile veri alamamalıdır."
      ].join("\n")
    },
    {
      key: "button_not_opening",
      phrases: ["buton açılmıyor", "tıklıyorum açılmıyor", "baloncuk açılmıyor", "asistan açılmıyor", "panel açılmıyor"],
      answer: [
        "Butona basınca açılmıyorsa tıklama olayı, sürükleme davranışı veya JavaScript yükleme sırası etkilenmiş olabilir.",
        "",
        "Kontrol sırası:",
        "1. Sayfada Ctrl + F5 ile cache temizleyerek yenileyin.",
        "2. Tarayıcı konsolunda JavaScript hatası var mı kontrol edin.",
        "3. Asistan JS dosyası sayfaya tek kez yükleniyor mu bakın.",
        "4. Baloncuk sürükleme ile kısa tıklama birbirine karışıyor mu test edin.",
        "5. base.html içinde eski basit asistan include’u kalmadığından emin olun.",
        "",
        "Güvenli çözüm:",
        "Kısa tıklama paneli açmalı, basılı tutup sürükleme sadece konumu değiştirmelidir."
      ].join("\n")
    },
    {
      key: "role_matrix_not_applied",
      phrases: ["rol matrisi yansımıyor", "açıyorum kapanmıyor", "kapattım görünmeye devam ediyor", "rol matrisi çalışmıyor"],
      answer: [
        "Rol matrisi değişikliği ekrana yansımıyorsa görünürlük katmanı ve backend yetki katmanı birlikte kontrol edilmelidir.",
        "",
        "Kontrol sırası:",
        "1. Modül bazlı rol matrisi kaydı gerçekten değişmiş mi kontrol edin.",
        "2. Performans rol matrisi aynı alanı tekrar açıyor mu bakın.",
        "3. Kişi bazlı menü izni rol ayarının üstüne yazıyor olabilir.",
        "4. Birim bazlı profil kullanıcıya farklı görünürlük veriyor olabilir.",
        "5. Menü cache veya session içinde eski görünürlük tutuluyor olabilir.",
        "6. Backend route yetkisi menüden bağımsız şekilde ayrıca kontrol edilmelidir.",
        "",
        "Dikkat:",
        "Doğru davranış: kapalı menü görünmemeli; URL yazılırsa da güvenli erişim engeli ekranı gösterilmelidir."
      ].join("\n")
    },
    {
      key: "performance_task_missing",
      phrases: ["görev oluşmadı", "performans görevi yok", "değerlendirme görevi oluşmadı", "amir görevi yok"],
      answer: [
        "Performans görevi oluşmadıysa dönem, kapsam, personel verisi ve amir zinciri birlikte kontrol edilmelidir.",
        "",
        "Kontrol sırası:",
        "1. Dönemler ekranında ilgili dönem aktif mi kontrol edin.",
        "2. Dönem kapsamına personel giriyor mu bakın.",
        "3. Personelin birim, üst birim, yönetici ve kategori bilgisi doğru mu kontrol edin.",
        "4. Değerlendirme Kriterleri ve ağırlıklar hazır mı bakın.",
        "5. 3. amir zorunlu olmayan yerde sahte görev oluşmamalıdır.",
        "6. Görev üretimi tekrar çalıştırıldıysa eski görevlerle çakışma var mı kontrol edin.",
        "",
        "Güvenli çözüm:",
        "Personel ve organizasyon verisi düzeltilmeden görev üretimi tekrarlandığında yanlış amir zinciri oluşabilir."
      ].join("\n")
    },
    {
      key: "wrong_supervisor",
      phrases: ["amir yanlış", "1. amir yanlış", "2. amir yanlış", "3. amir yanlış", "yönetici yanlış"],
      answer: [
        "Amir yanlış görünüyorsa personel organizasyon kaydı ve BYS360 performans hiyerarşi kuralları kontrol edilmelidir.",
        "",
        "Kontrol sırası:",
        "1. Personelin bağlı olduğu birim ve üst birim doğru mu kontrol edin.",
        "2. Personelin yöneticisi/personel organizasyon geçmişi güncel mi bakın.",
        "3. Koordinatör, Grup Başkanı ve Başkan Yardımcısı zinciri doğru tanımlı mı kontrol edin.",
        "4. 3. amir sadece gerçekten tanımlı yapılarda görünmelidir.",
        "5. Hukuk Müşavirliği ve özel roller için istisna kuralları ayrıca kontrol edilmelidir.",
        "",
        "Dikkat:",
        "Amir numarası ile işlem sırası aynı şey değildir. Çok seviyeli yapılarda işlem sırası yapılandırmaya göre ilerler."
      ].join("\n")
    },
    {
      key: "president_approvals_empty",
      phrases: ["başkan onayları null", "başkan onayı görünmüyor", "70 altı görünmüyor"],
      answer: [
        "Başkan Onayları ekranı boşsa önce gerçekten 70 altı ve onay bekleyen kayıt olup olmadığı kontrol edilmelidir.",
        "",
        "Kontrol sırası:",
        "1. Değerlendirme tamamlandı mı kontrol edin.",
        "2. Nihai puan gerçekten 70 altında mı bakın.",
        "3. Kayıt yayınlanmadan önce üst onay sürecine alınmış mı kontrol edin.",
        "4. Kullanıcı Başkan veya Admin/Sistem Yöneticisi yetkisine sahip mi bakın.",
        "5. Sahte Başkan onayı kaydı üretilmemelidir; yalnızca gerçek düşük performans kayıtları görünmelidir.",
        "",
        "Dikkat:",
        "70 üstü veya puanı oluşmamış personele Başkan onayı üretmek yanlış kabul edilir."
      ].join("\n")
    },
    {
      key: "scorecard_not_published",
      phrases: ["karne yayınlanmadı", "personel karnesi yok", "karne görünmüyor", "sonuç görünmüyor"],
      answer: [
        "Karne görünmüyorsa yayın ve onay süreci tamamlanmamış olabilir.",
        "",
        "Kontrol sırası:",
        "1. Tüm amir değerlendirmeleri tamamlandı mı kontrol edin.",
        "2. 70 altı sonuç varsa Başkan Onayı tamamlandı mı bakın.",
        "3. Yayın ön onayı gerekiyorsa Personel ve Destek Hizmetleri Grup Başkanı onayı tamamlandı mı kontrol edin.",
        "4. Admin/İK nihai yayın işlemini yaptı mı bakın.",
        "5. Personelin kendi karne görünürlüğü yetki sınırına göre açık mı kontrol edin.",
        "",
        "Dikkat:",
        "Sonuçlar yetkili yayın/onay tamamlanmadan personele kesin sonuç olarak açılmamalıdır."
      ].join("\n")
    },
    {
      key: "report_not_opening",
      phrases: ["rapor açılmıyor", "rapor gelmiyor", "dashboard null", "grafik görünmüyor"],
      answer: [
        "Rapor veya dashboard açılmıyorsa veri, yetki ve route/template katmanı birlikte kontrol edilmelidir.",
        "",
        "Kontrol sırası:",
        "1. İlgili dönem veya rapor verisi oluşmuş mu kontrol edin.",
        "2. Kullanıcının rapor kapsamını görme yetkisi var mı bakın.",
        "3. Rapor URL’si güvenli menü haritasında mı kontrol edin.",
        "4. Backend loglarında rapor route hatası var mı inceleyin.",
        "5. Grafik için gereken veri boşsa kullanıcıya anlaşılır null durum mesajı gösterilmelidir.",
        "",
        "Dikkat:",
        "Raporlarda kişi detayları yalnızca yetki kapsamına göre gösterilmelidir."
      ].join("\n")
    },
    {
      key: "assistant_session_lost",
      phrases: ["asistan sıfırlanıyor", "sayfa değişince kapanıyor", "konuşma kayboluyor", "sohbet gidiyor"],
      answer: [
        "Asistan sayfa değişince sıfırlanıyorsa oturum ve panel durumu tarayıcı tarafında korunmuyor olabilir.",
        "",
        "Kontrol sırası:",
        "1. Aynı tarayıcı sekmesinde session/localStorage kayıtları tutuluyor mu kontrol edin.",
        "2. Linke tıklamadan önce asistan konuşma geçmişi kaydediliyor mu bakın.",
        "3. Yeni sayfada panel açık/kapalı durumu geri yükleniyor mu test edin.",
        "4. Eski JS dosyası cache’ten geliyorsa Ctrl + F5 ile yenileyin.",
        "",
        "Beklenen davranış:",
        "Panel açıksa sayfa değişince yine açık gelmeli; konuşma aynı oturum içinde korunmalıdır."
      ].join("\n")
    },
    {
      key: "broken_leave_link",
      phrases: ["izin linki yanlış", "vekalet linki yanlış", "yanlış yere gidiyor", "kırık link"],
      answer: [
        "Yanlış link sorunu güvenli menü haritasıyla düzeltilmelidir.",
        "",
        "Doğru ekranlar:",
        "- İzin: Personel Yönetimi > İzin ve Devamsızlık Takibi",
        "- Vekâlet: Personel Yönetimi > Devamsızlık ve Vekâlet",
        "",
        "Kullanılmaması gereken eski örnek:",
        "- eski izin bağlantısı",
        "",
        "Güvenli çözüm:",
        "Asistan eski veya kırık link vermemeli; gerekiyorsa güvenli canlı URL’ye yönlendirmelidir."
      ].join("\n")
    }
  ];

  function findTroubleshooting(question){
    const q = String(question || "").toLocaleLowerCase("tr-TR");
    for (const item of troubleshootingMap){
      for (const phrase of item.phrases){
        if (q.includes(phrase.toLocaleLowerCase("tr-TR"))){
          return item.answer;
        }
      }
    }
    return null;
  }

  window.BYS360TroubleshootingGuide = {
    version: "V16",
    troubleshootingMap,
    findTroubleshooting
  };

  const previousLocal = window.BYS360AssistantLocalAnswer;
  window.BYS360AssistantLocalAnswer = function(question){
    const hit = findTroubleshooting(question);
    if (hit) return hit;
    if (typeof previousLocal === "function") return previousLocal(question);
    return null;
  };

  if (window.BYS360AssistantModule){
    window.BYS360AssistantModule.troubleshootingGuide = window.BYS360TroubleshootingGuide;
  }
})();
/* BYS360_V16_TROUBLESHOOTING_GUIDE_END */


/* BYS360_V18_2_PAGE_RECOGNITION_START */
(function(){
  "use strict";

  const pageRecognitionMap = [
    {
      key: "home",
      urls: ["/", "/home", "/dashboard"],
      titles: ["Ana Sayfa", "Dashboard"],
      name: "Ana Sayfa",
      bölüm: "Genel",
      help: "Şu an Ana Sayfa ekranındasınız. Bu ekran BYS360 içindeki genel durum, bildirimler, bekleyen işler ve hızlı yönlendirmeler için başlangıç alanıdır."
    },
    {
      key: "performance_dashboard",
      urls: ["/performance/dashboard", "/performans/dashboard"],
      titles: ["Performans Dashboard", "Yönetici Dashboard"],
      name: "Performans Dashboard",
      bölüm: "Performans Yönetimi",
      help: "Şu an Performans Dashboard ekranındasınız. Buradan dönem tamamlanma durumu, performans dağılımı, riskli personel, Başkan onayı bekleyenler ve yönetici görünürlük özetleri takip edilir."
    },
    {
      key: "performance_periods",
      urls: ["/performance/periods", "/performans/donemler", "/performance/periods/create"],
      titles: ["Dönemler", "Yeni Dönem"],
      name: "Dönemler",
      bölüm: "Performans Yönetimi",
      help: "Şu an Dönemler ekranındasınız. Buradan performans dönemleri oluşturulur, dönem tarihleri ve kapsam tipi yönetilir. Dönem oluşturduktan sonra Değerlendirme Kriterleri, ağırlıklar ve görev üretimi kontrol edilmelidir."
    },
    {
      key: "performance_criteria",
      urls: ["/performance/criteria", "/performans/kriterler"],
      titles: ["Değerlendirme Kriterleri", "Kriterler"],
      name: "Değerlendirme Kriterleri",
      bölüm: "Performans Yönetimi",
      help: "Şu an Değerlendirme Kriterleri ekranındasınız. Buradan performans dönemlerinde kullanılacak kriterler tanımlanır, düzenlenir ve aktiflik durumları kontrol edilir."
    },
    {
      key: "performance_assignments",
      urls: ["/performance/assignments", "/performance/task-generation", "/performans/gorev-uretimi"],
      titles: ["Görev Üretimi", "Değerlendirme Görevleri"],
      name: "Görev Üretimi",
      bölüm: "Performans Yönetimi",
      help: "Şu an Görev Üretimi ekranındasınız. Burada seçilen dönem ve kapsam için gerçek amir zincirine göre değerlendirme görevleri oluşturulur. Personel, birim, yönetici, kategori ve vekâlet bilgileri doğru olmalıdır."
    },
    {
      key: "my_evaluation_tasks",
      urls: ["/performance/my-tasks", "/performance/evaluation-tasks", "/performans/gorevlerim"],
      titles: ["Değerlendirme Görevlerim", "Görevlerim"],
      name: "Değerlendirme Görevlerim",
      bölüm: "Performans Yönetimi",
      help: "Şu an Değerlendirme Görevlerim ekranındasınız. Size atanmış değerlendirme görevlerini buradan puanlayabilir ve gerekli görüşleri girebilirsiniz."
    },
    {
      key: "scorecards",
      urls: ["/performance/scorecards", "/performans/karne", "/performans/v2/faz5/scorecard"],
      titles: ["Karne", "Not Karnesi", "Performans Karnesi"],
      name: "Karne",
      bölüm: "Performans Yönetimi",
      help: "Şu an Karne ekranındasınız. Yayınlanmış veya yetkiniz dahilindeki performans karnesi, kriter puanları, amir görüşleri ve süreç bilgileri burada görüntülenir."
    },
    {
      key: "president_approvals",
      urls: ["/performance/president-approvals", "/performans/baskan-onaylari"],
      titles: ["Başkan Onayları", "Başkan Onayı"],
      name: "Başkan Onayları",
      bölüm: "Performans Yönetimi",
      help: "Şu an Başkan Onayları ekranındasınız. Bu ekran 70 altı performans sonuçlarının üst onay sürecini takip etmek için kullanılır. Onay tamamlanmadan karne personele kesin/yayınlanmış sonuç olarak açılmamalıdır."
    },
    {
      key: "process_tracking",
      urls: ["/performance/process-tracking", "/performans/surec-takibi"],
      titles: ["Süreç Takibi", "Performans Süreç Takibi"],
      name: "Süreç Takibi",
      bölüm: "Performans Yönetimi",
      help: "Şu an Süreç Takibi ekranındasınız. Değerlendirme, onay, yayın kilidi, düşük performans ve süreç durumları buradan izlenir."
    },
    {
      key: "process_reports",
      urls: ["/performance/process-reports", "/performans/surec-raporlari"],
      titles: ["Süreç Raporları", "Performans Süreç Raporları"],
      name: "Süreç Raporları",
      bölüm: "Performans Yönetimi",
      help: "Şu an Süreç Raporları ekranındasınız. Dönem, amir, yayın, onay ve gecikme durumlarına ilişkin süreç raporları burada görüntülenir."
    },
    {
      key: "personnel_support_publish_approvals",
      urls: ["/performance/personnel-support-publish-approvals"],
      titles: ["Yayın Ön Onayı", "Personel ve Destek Hizmetleri"],
      name: "Yayın Ön Onayı",
      bölüm: "Performans Yönetimi",
      help: "Şu an Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı ekranındasınız. Değerlendirme ve gerekli üst onaylar tamamlandıktan sonra sonuçlar nihai yayından önce burada kontrol edilir."
    },
    {
      key: "meeting_development",
      urls: ["/performance/meeting-development/faz9", "/performance/meeting-development"],
      titles: ["Hatırlatma", "Aksatan Amirler", "Gelişim Takibi"],
      name: "Hatırlatma ve Aksatan Amirler",
      bölüm: "Performans Yönetimi",
      help: "Şu an Hatırlatma ve Aksatan Amirler ekranındasınız. Bekleyen değerlendirme görevleri, süresi yaklaşan işler ve aksatan amirler bu alandan takip edilir."
    },
    {
      key: "historical_scorecards",
      urls: ["/performans/gecmis-karne-arsivi", "/performance/archive", "/performance/scorecard-archive"],
      titles: ["Geçmiş Karne Arşivi", "Karne Arşivi"],
      name: "Geçmiş Karne Arşivi",
      bölüm: "Performans Yönetimi",
      help: "Şu an Geçmiş Karne Arşivi ekranındasınız. Eski yıllara ait performans puanları ve karneler yetki sınırına göre burada görüntülenir."
    },
    {
      key: "hr_leave",
      urls: ["/hr-management/leave"],
      titles: ["İzin ve Devamsızlık Takibi", "İzin"],
      name: "İzin ve Devamsızlık Takibi",
      bölüm: "Personel Yönetimi",
      help: "Şu an İzin ve Devamsızlık Takibi ekranındasınız. Personelin izin kayıtları, izin tarihleri ve devamsızlık bilgileri buradan takip edilir."
    },
    {
      key: "hr_attendance_delegation",
      urls: ["/hr-management/attendance"],
      titles: ["Devamsızlık ve Vekâlet", "Vekâlet"],
      name: "Devamsızlık ve Vekâlet",
      bölüm: "Personel Yönetimi",
      help: "Şu an Devamsızlık ve Vekâlet ekranındasınız. Devamsızlık bilgileri ve vekâlet ilişkileri buradan takip edilir. İzinli amir varsa süreçlerin doğru kişiye devredildiği kontrol edilmelidir."
    },
    {
      key: "settings_role_matrix",
      urls: ["/settings/role-matrix", "/settings/roles", "/admin/role-matrix"],
      titles: ["Rol Matrisi", "Menü Görünürlüğü"],
      name: "Rol Matrisi",
      bölüm: "Sistem Ayarları",
      help: "Şu an Rol Matrisi ekranındasınız. Modül, sekme ve menü görünürlükleri rol, kişi ve birim profiline göre buradan yönetilir."
    },
    {
      key: "ai_decision_health",
      urls: ["/ai/decision-support/faz1/health"],
      titles: ["AI Karar Destek", "Faz 1 Health"],
      name: "AI Karar Destek Sağlık Durumu",
      bölüm: "AI Karar Destek Merkezi",
      help: "Şu an AI Karar Destek sağlık durumu ekranındasınız. Bu ekran AI Karar Destek katmanının çalışma durumunu ve güvenli karar destek sözleşmelerini kontrol etmek için kullanılır."
    },
    {
      key: "ai_agent_panel",
      urls: ["/ai-agent/panel"],
      titles: ["Asistan Paneli", "AI Ajan Paneli"],
      name: "BYS360 Asistanı Paneli",
      bölüm: "BYS360 Asistanı",
      help: "Şu an BYS360 Asistanı panelindesiniz. Bu alan asistanın yönlendirme, rehberlik ve bilgi bankası davranışlarını yönetmek için kullanılır."
    },
    {
      key: "ai_agent_knowledge",
      urls: ["/ai-agent/knowledge"],
      titles: ["Asistan Bilgi Bankası", "Öğretim Merkezi"],
      name: "Asistan Bilgi Bankası",
      bölüm: "BYS360 Asistanı",
      help: "Şu an Asistan Bilgi Bankası ekranındasınız. Burada asistanın soru-cevap, güvenli URL, yasaklı URL ve ekran bilgileri yönetilir."
    },
    {
      key: "assistant_training_bank",
      urls: ["/assistant-training-bank", "/assistant/training-bank"],
      titles: ["BYS360 Asistanı Eğitim Bankası"],
      name: "BYS360 Asistanı Eğitim Bankası",
      bölüm: "BYS360 Asistanı",
      help: "Şu an BYS360 Asistanı Eğitim Bankası ekranındasınız. Soru-cevap kayıtları, güvenli URL’ler, yasaklı URL’ler ve yetkili rol bilgileri bu alanda yönetilir."
    },
    {
      key: "support",
      urls: ["/support", "/support/tickets"],
      titles: ["Destek Talepleri", "Yardım Merkezi"],
      name: "Destek Talepleri",
      bölüm: "İletişim ve Destek",
      help: "Şu an Destek Talepleri ekranındasınız. Kullanıcı destek talepleri bu ekrandan oluşturulur, takip edilir ve sonuçlandırılır."
    },
    {
      key: "surveys",
      urls: ["/surveys", "/survey"],
      titles: ["Anketler", "Anket Yönetimi"],
      name: "Anketler",
      bölüm: "İletişim ve Anket",
      help: "Şu an Anketler ekranındasınız. Size atanmış anketleri yanıtlayabilir veya yetkiniz varsa anketleri yönetebilirsiniz."
    },
    {
      key: "notifications",
      urls: ["/notifications", "/bildirimler"],
      titles: ["Bildirimler"],
      name: "Bildirimler",
      bölüm: "Genel",
      help: "Şu an Bildirimler ekranındasınız. Sistem içi uyarılar, görev hatırlatmaları ve süreç bilgilendirmeleri burada görüntülenir."
    }
  ];

  function norm(v){
    return String(v || "").toLocaleLowerCase("tr-TR").trim();
  }

  function getTextCandidates(){
    const arr = [];
    try { arr.push(window.location.pathname || ""); } catch(e){}
    try { arr.push(document.title || ""); } catch(e){}
    try {
      const h1 = document.querySelector("h1");
      if (h1) arr.push(h1.textContent || "");
    } catch(e){}
    try {
      const h2 = document.querySelector("h2");
      if (h2) arr.push(h2.textContent || "");
    } catch(e){}
    try {
      document.querySelectorAll(".active, .is-active, [aria-current='page'], .sidebar .active, .nav-link.active").forEach(function(el){
        arr.push(el.textContent || "");
        arr.push(el.getAttribute("href") || "");
      });
    } catch(e){}
    return arr;
  }

  function recognizePage(){
    const path = (() => { try { return window.location.pathname || "/"; } catch(e){ return "/"; }})();
    const candidates = getTextCandidates().map(norm);
    let best = null;
    let bestScore = 0;

    pageRecognitionMap.forEach(function(page){
      let score = 0;

      (page.urls || []).forEach(function(u){
        const up = norm(u);
        const pp = norm(path);
        if (pp === up) score += 100;
        else if (pp.startsWith(up + "/")) score += 80;
        else if (pp.indexOf(up) === 0) score += 60;
      });

      (page.titles || []).forEach(function(t){
        const tt = norm(t);
        candidates.forEach(function(c){
          if (!tt) return;
          if (c === tt) score += 40;
          else if (c.includes(tt)) score += 20;
        });
      });

      if (score > bestScore){
        bestScore = score;
        best = page;
      }
    });

    if (!best || bestScore < 20){
      return {
        key: "unknown",
        name: "Tanımlanamayan Ekran",
        bölüm: "BYS360",
        score: bestScore,
        help: "Bu ekran için özel tanıma kaydı bulunamadı. Sayfa adı veya yapmak istediğiniz işlemi yazarsanız sizi ilgili BYS360 modülüne göre yönlendirebilirim."
      };
    }

    return Object.assign({score: bestScore}, best);
  }

  function answerPageQuestion(question){
    const q = norm(question);
    const asked = [
      "bu sayfada ne yapabilirim",
      "bu ekran ne işe yarar",
      "hangi ekrandayım",
      "şu an hangi ekrandayım",
      "neredeyim",
      "bu ekranı tanıyor musun",
      "bu sayfayı tanıyor musun",
      "bu ekranı anlat",
      "sayfayı tanı"
    ].some(function(p){ return q.includes(p); });

    if (!asked) return null;

    const page = recognizePage();
    return [
      "Bulunduğunuz ekran: " + page.name,
      "Alan: " + page.bölüm,
      "",
      page.help
    ].join("\n");
  }

  window.BYS360PageRecognition = {
    version: "V18.2",
    pageRecognitionMap: pageRecognitionMap,
    recognizePage: recognizePage,
    answerPageQuestion: answerPageQuestion
  };

  const previousLocal = window.BYS360AssistantLocalAnswer;
  window.BYS360AssistantLocalAnswer = function(question){
    const pageAnswer = answerPageQuestion(question);
    if (pageAnswer) return pageAnswer;
    if (typeof previousLocal === "function") return previousLocal(question);
    return null;
  };

  if (window.BYS360AssistantModule){
    window.BYS360AssistantModule.pageRecognition = window.BYS360PageRecognition;
    window.BYS360AssistantModule.recognizeCurrentPage = recognizePage;
  }
})();
/* BYS360_V18_2_PAGE_RECOGNITION_END */


/* BYS360_V18_3_FALLBACK_PRIORITY_START */
(function(){
  "use strict";

  const GENERIC_FALLBACK_START = "Sorunuzu BYS360 kapsamında yorumlayacağım";

  function norm(v){
    return String(v || "").toLocaleLowerCase("tr-TR").trim();
  }

  function isGenericFallback(answer){
    return String(answer || "").toLocaleLowerCase("tr-TR").includes(GENERIC_FALLBACK_START.toLocaleLowerCase("tr-TR"));
  }

  function cleanAnswer(answer){
    let out = String(answer || "").trim();
    out = out.replaceAll("Dönemler", "Dönemler");
    out = out.replaceAll("/personnel/leaves", "/hr-management/leave");
    [
      "işlemler sıcak",
      "Hava koşulları kendini göstermiş",
      "Şemsiye gerekebilir",
      "Hava durumu değişken",
      "işi aksatmadan",
      "menüler karışmasın",
      "sevimli yorum",
      "Kurumsal rehberlik mantığıyla çalışır",
      "Eski basit asistanlarla karışmaz"
    ].forEach(function(bad){
      out = out.split(bad).join("");
    });
    return out.replace(/\n{3,}/g, "\n\n").trim();
  }

  function answerFromIntent(question){
    try {
      if (window.BYS360IntentEngine && typeof window.BYS360IntentEngine.detectIntent === "function") {
        const hit = window.BYS360IntentEngine.detectIntent(question);
        if (hit) {
          return [
            "Anladım. Bu işlem " + hit.target + " alanındadır.",
            "",
            "Doğru yol:",
            hit.target,
            "",
            "Güvenli bağlantı:",
            hit.url,
            "",
            "İşleme başlamadan önce yetkinizin bu ekran için açık olduğundan emin olun."
          ].join("\n");
        }
      }
    } catch(e){}
    return null;
  }

  function answerFromPage(question){
    try {
      if (window.BYS360PageRecognition && typeof window.BYS360PageRecognition.answerPageQuestion === "function") {
        const ans = window.BYS360PageRecognition.answerPageQuestion(question);
        if (ans) return ans;
      }
      if (window.BYS360PageContextHelp && typeof window.BYS360PageContextHelp.isPageContextQuestion === "function" && window.BYS360PageContextHelp.isPageContextQuestion(question)) {
        return window.BYS360PageContextHelp.getPageHelp();
      }
    } catch(e){}
    return null;
  }

  function answerFromTroubleshooting(question){
    try {
      if (window.BYS360TroubleshootingGuide && typeof window.BYS360TroubleshootingGuide.findTroubleshooting === "function") {
        return window.BYS360TroubleshootingGuide.findTroubleshooting(question);
      }
    } catch(e){}
    return null;
  }

  function answerFromTrainingBank(question){
    try {
      const q = norm(question);
      const rawData = document.getElementById("trainingBankSeed") ? document.getElementById("trainingBankSeed").textContent : null;
      if (!rawData) return null;
      const bank = JSON.parse(rawData);
      const items = bank.knowledge || [];
      for (const item of items) {
        const questionText = norm(item.question);
        const intent = norm(item.intent);
        const category = norm(item.category);
        const menu = norm(item.menu_path);
        if (
          (questionText && (q.includes(questionText) || questionText.includes(q))) ||
          (intent && q.includes(intent)) ||
          (category && q.includes(category)) ||
          (menu && q.includes(menu))
        ) {
          return [
            item.answer || "",
            item.menu_path ? "\nDoğru yol: " + item.menu_path : "",
            item.safe_url ? "\nGüvenli bağlantı: " + item.safe_url : ""
          ].join("").trim();
        }
      }
    } catch(e){}
    return null;
  }

  function answerDirect(question){
    const q = norm(question);

    if (q.includes("hangi ekrandayım") || q.includes("bu sayfada") || q.includes("bu ekran") || q.includes("sayfayı tanı")) {
      return answerFromPage(question);
    }

    if (q.includes("beyaz ekran") || q.includes("menü görünmüyor") || q.includes("buton açılmıyor") || q.includes("görev oluşmadı") || q.includes("karne yayınlanmadı") || q.includes("rapor açılmıyor") || q.includes("asistan sıfırlanıyor")) {
      return answerFromTroubleshooting(question);
    }

    if (q.includes("izin")) {
      return [
        "Bu konu Personel Yönetimi içindedir.",
        "",
        "Doğru yol:",
        "Personel Yönetimi > İzin ve Devamsızlık Takibi",
        "",
        "Adım adım:",
        "1. Sol şeritten Personel Yönetimi bölümünü açın.",
        "2. İzin ve Devamsızlık Takibi ekranına girin.",
        "3. Personeli bulun.",
        "4. İzin türü ve tarih aralığını kontrol edin.",
        "5. Kaydı oluşturun veya mevcut kaydı takip edin.",
        "",
        "Dikkat: İzinli amir varsa vekâlet ve performans/onay akışları ayrıca kontrol edilmelidir."
      ].join("\n");
    }

    if (q.includes("vekalet") || q.includes("vekâlet") || q.includes("devamsızlık")) {
      return [
        "Bu konu Personel Yönetimi içindedir.",
        "",
        "Doğru yol:",
        "Personel Yönetimi > Devamsızlık ve Vekâlet",
        "",
        "Adım adım:",
        "1. Sol şeritten Personel Yönetimi bölümünü açın.",
        "2. Devamsızlık ve Vekâlet ekranına girin.",
        "3. Asıl kişi ve vekil olacak kişiyi kontrol edin.",
        "4. Başlangıç ve bitiş tarihlerini girin.",
        "5. Kaydı oluşturun ve ilgili süreçte doğru kişiye yansıdığını kontrol edin."
      ].join("\n");
    }

    if (q.includes("dönem") || q.includes("donem") || q.includes("performansı başlat")) {
      return [
        "Bu işlem Performans Yönetimi içindedir.",
        "",
        "Doğru yol:",
        "Performans Yönetimi > Dönemler",
        "",
        "Adım adım:",
        "1. Sol şeritten Performans Yönetimi bölümünü açın.",
        "2. Dönemler sekmesine girin.",
        "3. Yeni dönem oluşturma butonunu kullanın.",
        "4. Dönem adı, türü, tarih aralığı ve kapsam bilgilerini doldurun.",
        "5. Kaydettikten sonra Değerlendirme Kriterleri, ağırlıklar ve görev üretimini kontrol edin."
      ].join("\n");
    }

    if (q.includes("başkan onay") || q.includes("70 alt")) {
      return [
        "Bu konu Performans Yönetimi > Başkan Onayları ekranıyla ilgilidir.",
        "",
        "Başkan Onayları, 70 altı performans sonuçlarının üst onay sürecini takip etmek için kullanılır.",
        "Başkan/üst onay tamamlanmadan karne personele kesin sonuç olarak açılmamalıdır."
      ].join("\n");
    }

    if (q.includes("rol matrisi") || q.includes("menüm yok") || q.includes("yetki")) {
      return [
        "Bu konu Sistem Ayarları > Rol Matrisi alanıyla ilgilidir.",
        "",
        "Kontrol sırası:",
        "1. Modül bazlı rol matrisi açık mı kontrol edin.",
        "2. Performans rol matrisi aynı sekmeyi kapatıyor mu bakın.",
        "3. Kişi bazlı menü görünürlüğü var mı kontrol edin.",
        "4. Birim bazlı profil kullanıcıyı etkiliyor mu inceleyin.",
        "5. Backend route yetkisi ayrıca korunmalıdır."
      ].join("\n");
    }

    if (q.includes("seni kim geliştirdi") || q.includes("seni kim gelistirdi") || q.includes("kim geliştirdi") || q.includes("kim gelistirdi") || q.includes("havva gülsen özden") || q.includes("havva gulsen ozden") || q.includes("gülsen özden") || q.includes("gulsen ozden") || q.includes("sen kimsin") || q.includes("chatgpt misin") || q.includes("nasıl çalışıyorsun")) {
      return "Ben BYS360 Asistanı’yım. BYS360 için Havva Gülsen Özden (geliştirici) ve Mustafa Bektaş (eş geliştirici) tarafından geliştirildim. Görevim, BYS360 içinde yetkiniz dâhilindeki işlemleri sade, güvenli ve doğru sırayla anlatmak; sizi gerçek ekranlara yönlendirmek ve sistemi daha kolay kullanmanıza yardımcı olmaktır.";
    }

    if (q.includes("neler yapabiliyorsun") || q.includes("hangi konularda yardımcı")) {
      return "BYS360 içinde personel işlemleri, izin-devamsızlık-vekalet süreçleri, performans dönemleri, Değerlendirme Kriterleri, görev üretimi, Başkan Onayları, karne-yayın süreci, rol matrisi, menü görünürlüğü, raporlar, destek talepleri, anketler, bildirimler ve AI Karar Destek Merkezi hakkında adım adım yardımcı olurum.";
    }

    return null;
  }

  function smartAnswer(question, previousAnswer){
    const candidates = [
      answerFromPage(question),
      answerFromTroubleshooting(question),
      answerDirect(question),
      answerFromIntent(question),
      answerFromTrainingBank(question)
    ].filter(Boolean).map(cleanAnswer);

    for (const ans of candidates){
      if (ans && !isGenericFallback(ans)) return ans;
    }

    if (previousAnswer && !isGenericFallback(previousAnswer)) return cleanAnswer(previousAnswer);

    return [
      "Bu konuda size yardımcı olabilmem için yapmak istediğiniz işlemi biraz daha net yazabilir misiniz?",
      "Örneğin: izin işlemi, Dönemler, Başkan Onayları, rol matrisi, karne, raporlar veya destek talebi gibi bir başlık yazabilirsiniz."
    ].join("\n");
  }

  window.BYS360FallbackPriority = {
    version: "V18.3",
    smartAnswer,
    cleanAnswer,
    isGenericFallback
  };

  const previousLocal = window.BYS360AssistantLocalAnswer;
  window.BYS360AssistantLocalAnswer = function(question){
    const local = smartAnswer(question, null);
    if (local && !isGenericFallback(local)) return local;

    if (typeof previousLocal === "function") {
      const old = previousLocal(question);
      return smartAnswer(question, old);
    }

    return local;
  };

  if (window.BYS360AssistantModule){
    window.BYS360AssistantModule.fallbackPriority = window.BYS360FallbackPriority;
    const oldAnswer = window.BYS360AssistantModule.answer;
    if (typeof oldAnswer === "function") {
      window.BYS360AssistantModule.answer = function(question){
        const local = smartAnswer(question, null);
        if (local && !isGenericFallback(local)) return local;
        const old = oldAnswer.apply(this, arguments);
        return smartAnswer(question, old);
      };
    }
  }
})();
/* BYS360_V18_3_FALLBACK_PRIORITY_END */


/* BYS360_V18_4_DEEP_PAGE_ANALYSIS_START */
(function(){
  "use strict";

  const genericTitles = [
    "kontrol paneli",
    "dashboard",
    "panel",
    "yönetim paneli",
    "ana ekran"
  ];

  const deepPageMap = [
    {
      key: "competency_library",
      name: "Yetkinlik Kütüphanesi",
      bölüm: "KPI ve Hedef Yönetimi / Performans Yönetimi",
      urls: ["/competency", "/competencies", "/kpi/competency", "/performance/competency", "/performance/competency-library", "/targets/competency"],
      keywords: ["yetkinlik kütüphanesi", "yetkinlik", "yetkinlik adı", "minimum seviye", "varsayılan ağırlık", "yetkinlik kategorisi", "liderlik", "takım çalışması", "analitik düşünme", "teknik uzmanlık"],
      help: [
        "Şu an Yetkinlik Kütüphanesi ekranındasınız.",
        "Bu ekran, BYS360’da görev, rol, hedef, gelişim önerisi ve performans bağlantılarında kullanılacak yetkinlikleri tanımlamak için kullanılır.",
        "",
        "Burada yapılabilecekler:",
        "1. Yeni yetkinlik tanımlama",
        "2. Yetkinlik kategorisi ve açıklamasını düzenleme",
        "3. Minimum seviye veya varsayılan ağırlık bilgisini kontrol etme",
        "4. Aktif/pasif durumunu yönetme",
        "5. Yetkinliklerin performans, gelişim önerisi ve AI analiz tarafında kullanılmasını sağlama",
        "",
        "Dikkat: Bu ekran genel Kontrol Paneli başlığı altında görünse bile gerçek işlem alanı Yetkinlik Kütüphanesi’dir."
      ].join("\n")
    },
    {
      key: "kpi_targets",
      name: "KPI ve Hedef Yönetimi",
      bölüm: "KPI ve Hedef Yönetimi",
      urls: ["/kpi", "/targets", "/goals", "/performance/kpi", "/target-management"],
      keywords: ["kpi", "hedef kartı", "hedef dönemi", "hedef değeri", "gerçekleşen", "başarı oranı", "risk seviyesi", "hedef yönetimi"],
      help: [
        "Şu an KPI ve Hedef Yönetimi ekranındasınız.",
        "Bu ekran hedef dönemi, Hedef Kartı, gerçekleşme değeri ve KPI başarı oranlarını takip etmek için kullanılır.",
        "",
        "Burada yapılabilecekler:",
        "1. Hedef dönemi oluşturma veya izleme",
        "2. Hedef kartı tanımlama",
        "3. Hedef değer ve gerçekleşen değeri kontrol etme",
        "4. Başarı oranı ve risk seviyesini izleme",
        "5. Yönetici dashboardlarına veri sağlayan KPI kayıtlarını yönetme"
      ].join("\n")
    },
    {
      key: "self_assessment",
      name: "Öz Değerlendirme",
      bölüm: "Performans Yönetimi",
      urls: ["/self-assessment", "/performance/self-assessment", "/oz-degerlendirme"],
      keywords: ["öz değerlendirme", "dönem özeti", "başarılarım", "zorlandığım alanlar", "gelişim ihtiyacı"],
      help: [
        "Şu an Öz Değerlendirme ekranındasınız.",
        "Bu ekran personelin dönem özeti, başarıları, zorlandığı alanlar ve gelişim ihtiyacını yazması için kullanılır.",
        "",
        "Dikkat: Öz değerlendirme otomatik puan üretmez; amire destek verisi sağlar."
      ].join("\n")
    },
    {
      key: "role_competency_map",
      name: "Görev Bazlı Yetkinlik Şablonu",
      bölüm: "KPI ve Hedef Yönetimi / Performans Yönetimi",
      urls: ["/role-competency", "/competency-map", "/performance/role-competency"],
      keywords: ["görev bazlı yetkinlik", "rol yetkinlik", "koordinatör yetkinlik", "grup başkanı yetkinlik", "rol şablonu", "yetkinlik şablonu"],
      help: [
        "Şu an Görev Bazlı Yetkinlik Şablonu ekranındasınız.",
        "Bu ekran rol veya görev türlerine göre hangi yetkinliklerin kullanılacağını belirlemek için kullanılır.",
        "",
        "Burada yapılabilecekler:",
        "1. Rol seçimi yapma",
        "2. Role bağlı yetkinlikleri belirleme",
        "3. Performans kriteri, gelişim önerisi ve AI analiz bağlantısını destekleme"
      ].join("\n")
    },
    {
      key: "training_bank",
      name: "BYS360 Asistanı Eğitim Bankası",
      bölüm: "BYS360 Asistanı",
      urls: ["/assistant-training-bank", "/assistant/training-bank", "/ai-agent/knowledge"],
      keywords: ["asistan eğitim bankası", "bilgi bankası", "soru-cevap", "yasaklı url", "güvenli url", "menü yolu", "yetkili roller"],
      help: [
        "Şu an BYS360 Asistanı Eğitim Bankası ekranındasınız.",
        "Bu ekran, asistanın soru-cevap kayıtlarını, güvenli URL’leri, yasaklı URL’leri, menü yollarını ve yetkili rol bilgilerini yönetmek için kullanılır."
      ].join("\n")
    }
  ];

  function norm(v){
    return String(v || "").toLocaleLowerCase("tr-TR").replace(/\s+/g, " ").trim();
  }

  function collectSignals(){
    const signals = [];
    function add(value, weight, source){
      const n = norm(value);
      if (n) signals.push({value:n, weight:weight || 1, source:source || "unknown"});
    }

    try { add(window.location.pathname, 120, "url"); } catch(e){}
    try { add(document.title, 10, "title"); } catch(e){}

    try {
      document.querySelectorAll("h1,h2,h3,.page-title,.card-title,.section-title,.breadcrumb,.breadcrumb-item,.active,.is-active,[aria-current='page'],.nav-link.active,.sidebar .active").forEach(function(el){
        add(el.textContent, 18, "heading-or-active");
        add(el.getAttribute("href"), 50, "active-href");
      });
    } catch(e){}

    try {
      document.querySelectorAll("label,th,button,a.btn,.btn,[data-page-title],[data-module],[data-screen]").forEach(function(el){
        add(el.textContent, 8, "content");
        add(el.getAttribute("data-page-title"), 40, "data-page-title");
        add(el.getAttribute("data-module"), 30, "data-module");
        add(el.getAttribute("data-screen"), 35, "data-screen");
      });
    } catch(e){}

    try {
      const bodyText = document.body ? document.body.innerText : "";
      add(bodyText.slice(0, 5000), 4, "body");
    } catch(e){}

    return signals;
  }

  function isGenericSignal(value){
    const v = norm(value);
    return genericTitles.some(function(g){ return v === g || v.includes(g); });
  }

  function recognizeDeepPage(){
    const signals = collectSignals();
    let best = null;
    let bestScore = 0;
    let details = [];

    deepPageMap.forEach(function(page){
      let score = 0;
      let matched = [];

      signals.forEach(function(sig){
        const v = sig.value;
        let localWeight = sig.weight;

        if (isGenericSignal(v)) {
          localWeight = Math.min(localWeight, 2);
        }

        (page.urls || []).forEach(function(u){
          const uu = norm(u);
          if (!uu) return;
          if (v === uu) { score += 150; matched.push("url:" + u); }
          else if (v.includes(uu)) { score += 90; matched.push("url-part:" + u); }
        });

        (page.keywords || []).forEach(function(k){
          const kk = norm(k);
          if (!kk) return;
          if (v === kk) { score += 80 + localWeight; matched.push("exact:" + k); }
          else if (v.includes(kk)) { score += 18 + localWeight; matched.push("keyword:" + k); }
        });

        if (v.includes(norm(page.name))) {
          score += 100 + localWeight;
          matched.push("name:" + page.name);
        }
      });

      if (score > bestScore){
        bestScore = score;
        best = page;
        details = matched.slice(0, 12);
      }
    });

    if (best && bestScore >= 35) {
      return Object.assign({score: bestScore, matched: details}, best);
    }

    return null;
  }

  function answerDeepPageQuestion(question){
    const q = norm(question);
    const asked = [
      "hangi ekrandayım",
      "bu sayfada ne yapabilirim",
      "bu ekran ne işe yarar",
      "bu sayfayı tanıyor musun",
      "bu ekranı anlat",
      "sayfayı tanı",
      "burada ne yapacağım"
    ].some(function(p){ return q.includes(p); });

    if (!asked) return null;

    const page = recognizeDeepPage();
    if (!page) return null;

    return [
      "Bulunduğunuz ekran: " + page.name,
      "Alan: " + page.bölüm,
      "",
      page.help
    ].join("\n");
  }

  window.BYS360DeepPageAnalysis = {
    version: "V18.4",
    deepPageMap: deepPageMap,
    collectSignals: collectSignals,
    recognizeDeepPage: recognizeDeepPage,
    answerDeepPageQuestion: answerDeepPageQuestion
  };

  const prevPageRecognition = window.BYS360PageRecognition;
  if (prevPageRecognition && typeof prevPageRecognition.recognizePage === "function") {
    const oldRecognize = prevPageRecognition.recognizePage;
    prevPageRecognition.recognizePage = function(){
      const deep = recognizeDeepPage();
      if (deep) return deep;
      return oldRecognize.apply(this, arguments);
    };
  }

  const previousLocal = window.BYS360AssistantLocalAnswer;
  window.BYS360AssistantLocalAnswer = function(question){
    const deepAnswer = answerDeepPageQuestion(question);
    if (deepAnswer) return deepAnswer;
    if (typeof previousLocal === "function") return previousLocal(question);
    return null;
  };

  if (window.BYS360AssistantModule){
    window.BYS360AssistantModule.deepPageAnalysis = window.BYS360DeepPageAnalysis;
    window.BYS360AssistantModule.recognizeDeepPage = recognizeDeepPage;
  }
})();
/* BYS360_V18_4_DEEP_PAGE_ANALYSIS_END */


/* BYS360_V18_4_1_GATE_MARKER: Hedef Kartı */


/* BYS360_V18_5_CONTENT_FIRST_PAGE_RECOGNITION_START */
(function(){
  "use strict";

  const genericWords = [
    "kontrol paneli",
    "dashboard",
    "panel",
    "yönetim paneli",
    "ana ekran",
    "genel bakış"
  ];

  const pages = [
    {
      key: "competency_library",
      name: "Yetkinlik Kütüphanesi",
      bölüm: "KPI ve Hedef Yönetimi / Performans Yönetimi",
      urlHints: ["competency", "competencies", "yetkinlik", "yetkinlik-kutuphanesi", "competency-library"],
      strongKeywords: ["yetkinlik kütüphanesi", "yetkinlik adı", "yetkinlik kategorisi", "minimum seviye", "varsayılan ağırlık", "liderlik", "takım çalışması", "analitik düşünme", "teknik uzmanlık", "kriz yönetimi"],
      weakKeywords: ["yetkinlik", "seviye", "ağırlık", "aktif", "pasif"],
      help: "Şu an Yetkinlik Kütüphanesi ekranındasınız. Bu ekran görev, rol, performans, gelişim önerisi ve AI analiz tarafında kullanılacak yetkinlikleri tanımlamak için kullanılır. Burada yetkinlik adı, kategori, açıklama, minimum seviye, varsayılan ağırlık ve aktiflik bilgileri yönetilir."
    },
    {
      key: "kpi_targets",
      name: "KPI ve Hedef Yönetimi",
      bölüm: "KPI ve Hedef Yönetimi",
      urlHints: ["kpi", "target", "targets", "hedef", "hedefler", "goal", "goals"],
      strongKeywords: ["hedef kartı", "hedef dönemi", "hedef değeri", "gerçekleşen", "başarı oranı", "risk seviyesi", "kpi", "hedef yönetimi"],
      weakKeywords: ["hedef", "risk", "başarı", "dönem", "gerçekleşme"],
      help: "Şu an KPI ve Hedef Yönetimi ekranındasınız. Bu ekran hedef dönemi, Hedef Kartı, gerçekleşen değer, başarı oranı ve risk seviyesini takip etmek için kullanılır."
    },
    {
      key: "performance_periods",
      name: "Dönemler",
      bölüm: "Performans Yönetimi",
      urlHints: ["period", "periods", "donem", "donemler", "dönem"],
      strongKeywords: ["dönemler", "yeni dönem", "dönem türü", "başlangıç tarihi", "bitiş tarihi", "kapsam tipi"],
      weakKeywords: ["dönem", "tarih", "kapsam", "aktif"],
      help: "Şu an Dönemler ekranındasınız. Buradan performans dönemleri oluşturulur, tarih aralığı ve kapsam tipi yönetilir."
    },
    {
      key: "criteria",
      name: "Değerlendirme Kriterleri",
      bölüm: "Performans Yönetimi",
      urlHints: ["criteria", "criterion", "kriter", "kriterler"],
      strongKeywords: ["değerlendirme kriterleri", "kriter adı", "kriter açıklaması", "puan aralığı"],
      weakKeywords: ["kriter", "değerlendirme"],
      help: "Şu an Değerlendirme Kriterleri ekranındasınız. Performans dönemlerinde kullanılacak kriterler burada tanımlanır ve yönetilir."
    },
    {
      key: "president_approvals",
      name: "Başkan Onayları",
      bölüm: "Performans Yönetimi",
      urlHints: ["president-approvals", "baskan-onay", "başkan-onay"],
      strongKeywords: ["başkan onayları", "başkan onayı", "70 altı", "yayın kilidi", "düşük performans"],
      weakKeywords: ["onay", "başkan", "kilit"],
      help: "Şu an Başkan Onayları ekranındasınız. Bu ekran 70 altı performans sonuçlarının üst onay sürecini takip etmek için kullanılır."
    },
    {
      key: "leave",
      name: "İzin ve Devamsızlık Takibi",
      bölüm: "Personel Yönetimi",
      urlHints: ["leave", "izin"],
      strongKeywords: ["izin ve devamsızlık takibi", "izin türü", "izin başlangıç", "izin bitiş", "izin kaydı"],
      weakKeywords: ["izin", "devamsızlık"],
      help: "Şu an İzin ve Devamsızlık Takibi ekranındasınız. Personelin izin kayıtları ve devamsızlık bilgileri buradan takip edilir."
    },
    {
      key: "delegation",
      name: "Devamsızlık ve Vekâlet",
      bölüm: "Personel Yönetimi",
      urlHints: ["attendance", "delegation", "vekalet", "vekâlet", "devamsizlik"],
      strongKeywords: ["devamsızlık ve vekâlet", "vekil", "asıl kişi", "vekâlet başlangıç", "vekâlet bitiş"],
      weakKeywords: ["devamsızlık", "vekalet", "vekâlet", "vekil"],
      help: "Şu an Devamsızlık ve Vekâlet ekranındasınız. Devamsızlık ve vekâlet ilişkileri bu ekrandan takip edilir."
    },
    {
      key: "role_matrix",
      name: "Rol Matrisi",
      bölüm: "Sistem Ayarları",
      urlHints: ["role-matrix", "roles", "rol-matrisi"],
      strongKeywords: ["rol matrisi", "menü görünürlüğü", "modül bazlı rol", "kişi bazlı menü", "birim bazlı profil"],
      weakKeywords: ["rol", "yetki", "görünürlük", "menü"],
      help: "Şu an Rol Matrisi ekranındasınız. Modül, sekme ve menü görünürlükleri rol, kişi ve birim profiline göre buradan yönetilir."
    },
    {
      key: "assistant_training_bank",
      name: "BYS360 Asistanı Eğitim Bankası",
      bölüm: "BYS360 Asistanı",
      urlHints: ["assistant-training-bank", "training-bank", "ai-agent/knowledge", "knowledge"],
      strongKeywords: ["asistan eğitim bankası", "bilgi bankası", "soru-cevap", "güvenli url", "yasaklı url", "menü yolu", "yetkili roller"],
      weakKeywords: ["asistan", "eğitim", "bilgi", "url"],
      help: "Şu an BYS360 Asistanı Eğitim Bankası ekranındasınız. Asistanın soru-cevap kayıtları, güvenli URL’leri, yasaklı URL’leri ve menü yolları burada yönetilir."
    }
  ];

  function norm(v){
    return String(v || "").toLocaleLowerCase("tr-TR").replace(/\s+/g, " ").trim();
  }

  function isGeneric(v){
    const n = norm(v);
    return genericWords.some(g => n === g || n.includes(g));
  }

  function addSignal(signals, value, weight, source){
    const n = norm(value);
    if (!n) return;
    if (isGeneric(n)) {
      weight = Math.min(weight, 1); // genel üst başlıklar neredeyse yok sayılır
    }
    signals.push({value:n, weight, source});
  }

  function getSignals(){
    const signals = [];
    try {
      const path = window.location.pathname || "";
      addSignal(signals, path, 180, "url");
      path.split(/[\/\-_]+/).forEach(part => addSignal(signals, part, 45, "url-part"));
    } catch(e){}

    try {
      document.querySelectorAll(".sidebar .active, .nav-link.active, .active[href], [aria-current='page'], .menu-item.active, .submenu .active").forEach(el => {
        addSignal(signals, el.textContent, 95, "active-menu-text");
        addSignal(signals, el.getAttribute("href"), 140, "active-menu-href");
        addSignal(signals, el.getAttribute("data-url"), 140, "active-menu-data-url");
      });
    } catch(e){}

    try {
      document.querySelectorAll(".breadcrumb, .breadcrumb-item, nav[aria-label='breadcrumb'], .page-breadcrumb").forEach(el => {
        addSignal(signals, el.textContent, 75, "breadcrumb");
      });
    } catch(e){}

    try {
      document.querySelectorAll("main h2, main h3, .content h2, .content h3, .card h2, .card h3, .section-title, .card-title, .table-title").forEach(el => {
        addSignal(signals, el.textContent, 60, "content-heading");
      });
    } catch(e){}

    try {
      document.querySelectorAll("label, th, button, .btn, input[placeholder], textarea[placeholder], select").forEach(el => {
        addSignal(signals, el.textContent, 25, "field-text");
        addSignal(signals, el.getAttribute("placeholder"), 35, "placeholder");
        addSignal(signals, el.getAttribute("name"), 30, "field-name");
        addSignal(signals, el.getAttribute("id"), 30, "field-id");
      });
    } catch(e){}

    try {
      document.querySelectorAll("[data-page-title],[data-screen],[data-module],[data-feature]").forEach(el => {
        addSignal(signals, el.getAttribute("data-page-title"), 170, "data-page-title");
        addSignal(signals, el.getAttribute("data-screen"), 170, "data-screen");
        addSignal(signals, el.getAttribute("data-module"), 130, "data-module");
        addSignal(signals, el.getAttribute("data-feature"), 130, "data-feature");
      });
    } catch(e){}

    try {
      addSignal(signals, document.title, 5, "document-title");
      document.querySelectorAll("h1,.page-title").forEach(el => addSignal(signals, el.textContent, 5, "top-title"));
    } catch(e){}

    try {
      const main = document.querySelector("main,.content,.page-content,.container-fluid") || document.body;
      const bodyText = main ? main.innerText.slice(0, 8000) : "";
      addSignal(signals, bodyText, 8, "main-body");
    } catch(e){}

    return signals;
  }

  function scorePage(page, signals){
    let score = 0;
    const matched = [];

    for (const sig of signals) {
      for (const hint of page.urlHints || []) {
        const h = norm(hint);
        if (!h) continue;
        if (sig.value === h) { score += 120 + sig.weight; matched.push(sig.source + ":url=" + hint); }
        else if (sig.value.includes(h)) { score += 45 + sig.weight; matched.push(sig.source + ":urlPart=" + hint); }
      }

      for (const kw of page.strongKeywords || []) {
        const k = norm(kw);
        if (!k) continue;
        if (sig.value === k) { score += 100 + sig.weight; matched.push(sig.source + ":strongExact=" + kw); }
        else if (sig.value.includes(k)) { score += 60 + sig.weight; matched.push(sig.source + ":strong=" + kw); }
      }

      for (const kw of page.weakKeywords || []) {
        const k = norm(kw);
        if (!k) continue;
        if (sig.value === k) { score += 30 + sig.weight; matched.push(sig.source + ":weakExact=" + kw); }
        else if (sig.value.includes(k)) { score += 10 + Math.min(sig.weight, 20); matched.push(sig.source + ":weak=" + kw); }
      }

      if (sig.value.includes(norm(page.name))) {
        score += 100 + sig.weight;
        matched.push(sig.source + ":name=" + page.name);
      }
    }

    return {score, matched: matched.slice(0, 8)};
  }

  function recognizeContentFirstPage(){
    const signals = getSignals();
    let best = null;
    let bestScore = 0;
    let bestMatched = [];

    for (const page of pages) {
      const result = scorePage(page, signals);
      if (result.score > bestScore) {
        best = page;
        bestScore = result.score;
        bestMatched = result.matched;
      }
    }

    if (best && bestScore >= 80) {
      return Object.assign({score: Math.round(bestScore), matched: bestMatched}, best);
    }

    return {
      key: "unknown",
      name: "Tanımlanamayan Ekran",
      bölüm: "BYS360",
      score: Math.round(bestScore),
      matched: bestMatched,
      help: "Bu ekranı güvenli şekilde tanımlayamadım. Sayfanın aktif menü adı, tablo başlıkları veya form alanları eğitim bankasına eklenirse bu ekranı da doğru tanıyabilirim."
    };
  }

  function answerContentFirstQuestion(question){
    const q = norm(question);
    const asked = [
      "hangi ekrandayım",
      "bu sayfada ne yapabilirim",
      "bu ekran ne işe yarar",
      "bu sayfayı tanıyor musun",
      "bu ekranı anlat",
      "sayfayı tanı",
      "burada ne yapacağım"
    ].some(p => q.includes(p));

    if (!asked) return null;

    const page = recognizeContentFirstPage();
    return [
      "Bulunduğunuz ekran: " + page.name,
      "Alan: " + page.bölüm,
      "",
      page.help,
      "",
      "Tanıma puanı: " + page.score
    ].join("\n");
  }

  window.BYS360ContentFirstPageRecognition = {
    version: "V18.5",
    pages,
    getSignals,
    recognizeContentFirstPage,
    answerContentFirstQuestion
  };

  // En son yüklendiği için önceki sayfa tanıma motorlarının üstüne yazar.
  window.BYS360AssistantLocalAnswer = (function(previous){
    return function(question){
      const ans = answerContentFirstQuestion(question);
      if (ans) return ans;
      if (typeof previous === "function") return previous(question);
      return null;
    };
  })(window.BYS360AssistantLocalAnswer);

  if (window.BYS360AssistantModule) {
    window.BYS360AssistantModule.contentFirstPageRecognition = window.BYS360ContentFirstPageRecognition;
    window.BYS360AssistantModule.recognizeCurrentPage = recognizeContentFirstPage;
  }
})();
/* BYS360_V18_5_CONTENT_FIRST_PAGE_RECOGNITION_END */


/* BYS360_V18_7_OFFICIAL_SCREEN_IDENTITY_START */
(function(){
  "use strict";

  const officialScreenIdentityMap = {
    "/performans/stratejik/kpi-dashboard": {
      screen: "KPI Dashboardu",
      bölüm: "KPI ve Hedef Yönetimi",
      helpKey: "strategic_kpi_dashboard",
      help: "Şu an KPI Dashboardu ekranındasınız. Bu ekran hedef gerçekleşmeleri, KPI başarı oranları, risk seviyesi ve yönetici özetlerini takip etmek için kullanılır."
    },
    "/performans/stratejik/hedefler": {
      screen: "Hedefler",
      bölüm: "KPI ve Hedef Yönetimi",
      helpKey: "strategic_targets",
      help: "Şu an Hedefler ekranındasınız. Bu ekran hedef dönemleri, hedef kartları, hedef değerleri, gerçekleşen değerleri ve hedef durumlarını yönetmek için kullanılır."
    },
    "/performans/stratejik/yetkinlik-kutuphanesi": {
      screen: "Yetkinlik Kütüphanesi",
      bölüm: "KPI ve Hedef Yönetimi",
      helpKey: "competency_library",
      help: "Şu an Yetkinlik Kütüphanesi ekranındasınız. Bu ekran görev, rol, performans, gelişim önerisi ve AI analiz tarafında kullanılacak yetkinlikleri tanımlamak için kullanılır."
    },
    "/performans/stratejik/oz-degerlendirme": {
      screen: "Öz Değerlendirme",
      bölüm: "KPI ve Hedef Yönetimi / Performans Yönetimi",
      helpKey: "self_assessment",
      help: "Şu an Öz Değerlendirme ekranındasınız. Bu ekran personelin dönem özeti, başarıları, zorlandığı alanlar ve gelişim ihtiyacını yazması için kullanılır. Öz değerlendirme otomatik puan üretmez."
    },
    "/performans/stratejik/ai-kpi-analiz": {
      screen: "KPI Analiz Merkezi",
      bölüm: "AI Karar Destek / KPI ve Hedef Yönetimi",
      helpKey: "ai_kpi_analysis",
      help: "Şu an KPI Analiz Merkezi ekranındasınız. Bu ekran KPI ve hedef verilerini güvenli karar destek mantığıyla özetlemek, riskli hedefleri görünür kılmak ve yöneticiye analiz desteği sunmak için kullanılır. Nihai karar insan kullanıcıya aittir."
    },
    "/performance/meeting-development/faz10": {
      screen: "Dönem İçi Notlar",
      bölüm: "Performans Yönetimi",
      helpKey: "interim_notes_faz10",
      help: "Şu an Dönem İçi Notlar ekranındasınız. Bu ekran performans dönemi içinde olumlu/olumsuz olay, başarı, gelişim ihtiyacı ve genel gözlem notlarını kaydetmek için kullanılır."
    },
    "/performance/interim-notes": {
      screen: "Dönem İçi Notlar",
      bölüm: "Performans Yönetimi",
      helpKey: "interim_notes",
      help: "Şu an Dönem İçi Notlar ekranındasınız. Bu ekran dönem içindeki notları ve ara geri bildirimleri takip etmek için kullanılır."
    },
    "/performance/meeting-development/faz9": {
      screen: "Hatırlatma ve Aksatan Amirler",
      bölüm: "Performans Yönetimi",
      helpKey: "reminders_delayed_supervisors_faz9",
      help: "Şu an Hatırlatma ve Aksatan Amirler ekranındasınız. Bu ekran bekleyen değerlendirme görevlerini, yaklaşan son tarihleri ve aksatan amirleri takip etmek için kullanılır."
    },
    "/performance/personnel-support-publish-approvals": {
      screen: "Yayın Ön Onayı",
      bölüm: "Performans Yönetimi",
      helpKey: "personnel_support_publish_approvals",
      help: "Şu an Yayın Ön Onayı ekranındasınız. Değerlendirme ve gerekli üst onaylar tamamlandıktan sonra sonuçlar nihai yayından önce Personel ve Destek Hizmetleri Grup Başkanı kontrolüne düşer."
    },
    "/performance/process-reports": {
      screen: "Süreç Raporları",
      bölüm: "Performans Yönetimi",
      helpKey: "process_reports",
      help: "Şu an Süreç Raporları ekranındasınız. Bu ekran dönem, amir, yayın, onay, gecikme ve süreç durumlarına ilişkin raporları görüntülemek için kullanılır."
    },
    "/performance/process-tracking": {
      screen: "Süreç Takibi",
      bölüm: "Performans Yönetimi",
      helpKey: "process_tracking",
      help: "Şu an Süreç Takibi ekranındasınız. Bu ekran değerlendirme, onay, yayın kilidi, düşük performans ve süreç durumlarını takip etmek için kullanılır."
    }
  };

  function normalizePath(path){
    let p = String(path || "").trim();
    try {
      if (p.startsWith("http://") || p.startsWith("https://")) {
        p = new URL(p).pathname;
      }
    } catch(e){}
    if (p.length > 1 && p.endsWith("/")) p = p.slice(0, -1);
    return p;
  }

  function getOfficialIdentity(path){
    const p = normalizePath(path || (window.location && window.location.pathname) || "/");
    if (officialScreenIdentityMap[p]) return officialScreenIdentityMap[p];

    // Alt detay sayfalarında da ana ekranı tanısın.
    const keys = Object.keys(officialScreenIdentityMap).sort((a,b) => b.length - a.length);
    for (const key of keys) {
      if (p.startsWith(key + "/")) return officialScreenIdentityMap[key];
    }
    return null;
  }

  function ensureIdentityNode(identity){
    if (!identity) return null;

    let node = document.getElementById("bys360-official-screen-identity");
    if (!node) {
      node = document.createElement("div");
      node.id = "bys360-official-screen-identity";
      node.hidden = true;
      node.style.display = "none";
      document.body.appendChild(node);
    }

    node.setAttribute("data-bys360-screen", identity.screen);
    node.setAttribute("data-bys360-module", identity.bölüm);
    node.setAttribute("data-bys360-help-key", identity.helpKey);
    node.setAttribute("data-bys360-help", identity.help);

    document.body.setAttribute("data-bys360-screen", identity.screen);
    document.body.setAttribute("data-bys360-module", identity.bölüm);
    document.body.setAttribute("data-bys360-help-key", identity.helpKey);

    return node;
  }

  function applyOfficialIdentity(){
    const identity = getOfficialIdentity();
    ensureIdentityNode(identity);
    return identity;
  }

  function answerOfficialScreenQuestion(question){
    const q = String(question || "").toLocaleLowerCase("tr-TR");
    const asked = [
      "hangi ekrandayım",
      "hangi sayfadayım",
      "bu sayfada ne yapabilirim",
      "bu ekran ne işe yarar",
      "bu sayfayı tanıyor musun",
      "bu ekranı anlat",
      "sayfayı tanı",
      "burada ne yapacağım"
    ].some(p => q.includes(p));

    if (!asked) return null;

    const identity = applyOfficialIdentity();
    if (!identity) return null;

    return [
      "Bulunduğunuz ekran: " + identity.screen,
      "Alan: " + identity.bölüm,
      "",
      identity.help
    ].join("\n");
  }

  window.BYS360OfficialScreenIdentity = {
    version: "V18.7",
    officialScreenIdentityMap,
    normalizePath,
    getOfficialIdentity,
    applyOfficialIdentity,
    answerOfficialScreenQuestion
  };

  function install(){
    applyOfficialIdentity();

    const previousLocal = window.BYS360AssistantLocalAnswer;
    window.BYS360AssistantLocalAnswer = function(question){
      const official = answerOfficialScreenQuestion(question);
      if (official) return official;
      if (typeof previousLocal === "function") return previousLocal(question);
      return null;
    };

    if (window.BYS360AssistantModule) {
      window.BYS360AssistantModule.officialScreenIdentity = window.BYS360OfficialScreenIdentity;
      window.BYS360AssistantModule.getOfficialScreenIdentity = getOfficialIdentity;
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }

  // SPA benzeri sayfa değişimlerinde tekrar uygula.
  window.addEventListener("popstate", applyOfficialIdentity);
  setTimeout(applyOfficialIdentity, 300);
  setTimeout(applyOfficialIdentity, 1200);
})();
/* BYS360_V18_7_OFFICIAL_SCREEN_IDENTITY_END */


/* BYS360_V18_8_2_KPI_ANALIZ_MERKEZI_FIX_START */
(function(){
  "use strict";

  const KPI_PATH = "/performans/stratejik/ai-kpi-analiz";
  const KPI_INFO = {
    title: "KPI Analiz Merkezi",
    screen: "KPI Analiz Merkezi",
    bölüm: "Stratejik Performans",
    helpKey: "kpi_analysis_center",
    help: "Şu an KPI Analiz Merkezi ekranındasınız. Bu ekran KPI gerçekleşmeleri, riskli hedefler, yönetici önerileri ve performans bağlantıları için karar destek ekranıdır."
  };

  function normPath(v){
    let p = String(v || "").trim();
    try {
      if (p.startsWith("http://") || p.startsWith("https://")) p = new URL(p).pathname;
    } catch(e){}
    if (p.length > 1 && p.endsWith("/")) p = p.slice(0, -1);
    return p;
  }

  function isKpiPage(){
    const path = normPath(window.location && window.location.pathname || "");
    return path === KPI_PATH || path.startsWith(KPI_PATH + "/");
  }

  function isPageQuestion(question){
    const q = String(question || "").toLocaleLowerCase("tr-TR");
    return [
      "hangi ekrandayım",
      "hangi sayfadayım",
      "bu sayfada ne yapabilirim",
      "bu ekran ne işe yarar",
      "bu ekranı anlat",
      "bu sayfayı tanıyor musun",
      "sayfayı tanı",
      "burada ne yapacağım"
    ].some(function(p){ return q.includes(p); });
  }

  function applyKpiIdentity(){
    if (!isKpiPage()) return null;

    document.body.setAttribute("data-bys360-screen", KPI_INFO.screen);
    document.body.setAttribute("data-bys360-module", KPI_INFO.bölüm);
    document.body.setAttribute("data-bys360-help-key", KPI_INFO.helpKey);

    let node = document.getElementById("bys360-official-screen-identity");
    if (!node) {
      node = document.createElement("div");
      node.id = "bys360-official-screen-identity";
      node.hidden = true;
      node.style.display = "none";
      document.body.appendChild(node);
    }
    node.setAttribute("data-bys360-screen", KPI_INFO.screen);
    node.setAttribute("data-bys360-module", KPI_INFO.bölüm);
    node.setAttribute("data-bys360-help-key", KPI_INFO.helpKey);
    node.setAttribute("data-bys360-help", KPI_INFO.help);

    return KPI_INFO;
  }

  function replaceKpiTitle(){
    if (!isKpiPage()) return;

    const selectors = [
      "h1","h2",".page-title",".content-title",".module-title",".dashboard-title",
      ".page-header-title",".section-title","[data-page-title]","[data-title]"
    ];

    document.querySelectorAll(selectors.join(",")).forEach(function(el){
      const text = (el.textContent || "").trim();
      if (
        text === "KPI Analiz Merkezi" ||
        text === "Kontrol Paneli" ||
        text === "Dashboard" ||
        text.includes("KPI Analiz Merkezi")
      ) {
        el.textContent = KPI_INFO.title;
        el.setAttribute("data-bys360-title-fixed", "kpi-analysis-center");
      }
    });

    // Sayfada eski KPI Analiz Merkezi metni küçük kart/başlık içinde geçiyorsa kullanıcıya görünen yerde düzelt.
    document.querySelectorAll("main *,.content *,.page-content *,.container-fluid *").forEach(function(el){
      if (el.children && el.children.length > 0) return;
      const t = (el.textContent || "").trim();
      if (t === "KPI Analiz Merkezi") {
        el.textContent = KPI_INFO.title;
        el.setAttribute("data-bys360-title-fixed", "kpi-analysis-center");
      }
    });

    if (document.title && document.title.includes("KPI Analiz Merkezi")) {
      document.title = document.title.replaceAll("KPI Analiz Merkezi", KPI_INFO.title);
    }
  }

  function kpiAnswer(){
    return [
      "Bulunduğunuz ekran: KPI Analiz Merkezi",
      "Alan: Stratejik Performans",
      "",
      "Bu ekran KPI gerçekleşmeleri, riskli hedefler, yönetici önerileri ve performans bağlantıları için karar destek ekranıdır.",
      "",
      "Burada yapılabilecekler:",
      "1. KPI gerçekleşmelerini inceleme",
      "2. Riskli hedefleri görme",
      "3. Yönetici önerilerini değerlendirme",
      "4. Performans bağlantılarını kontrol etme"
    ].join("\n");
  }

  function install(){
    applyKpiIdentity();
    replaceKpiTitle();

    // V18.7 resmi ekran kimliği haritasına runtime ekle.
    if (window.BYS360OfficialScreenIdentity && window.BYS360OfficialScreenIdentity.officialScreenIdentityMap) {
      window.BYS360OfficialScreenIdentity.officialScreenIdentityMap[KPI_PATH] = {
        screen: KPI_INFO.screen,
        module: KPI_INFO.module,
        helpKey: KPI_INFO.helpKey,
        help: KPI_INFO.help
      };
    }

    // V18.8 title fix haritasına runtime ekle.
    if (window.BYS360ScreenTitleFixV18_8 && window.BYS360ScreenTitleFixV18_8.screenTitleMap) {
      window.BYS360ScreenTitleFixV18_8.screenTitleMap[KPI_PATH] = {
        title: KPI_INFO.title,
        module: KPI_INFO.module,
        helpKey: KPI_INFO.helpKey
      };
    }

    const previousLocal = window.BYS360AssistantLocalAnswer;
    window.BYS360AssistantLocalAnswer = function(question){
      if (isKpiPage() && isPageQuestion(question)) {
        applyKpiIdentity();
        replaceKpiTitle();
        return kpiAnswer();
      }

      const q = String(question || "").toLocaleLowerCase("tr-TR");
      if (q.includes("kpi analiz") || q.includes("kpi analiz merkezi") || q.includes("riskli hedef")) {
        return kpiAnswer();
      }

      if (typeof previousLocal === "function") {
        const ans = previousLocal(question);
        if (isKpiPage() && ans && (
          ans.includes("KPI Analiz Merkezi") ||
          ans.includes("güvenli menü haritasında özel bir başlıkla eşleşmedi") ||
          ans.includes("Kontrol Paneli")
        )) {
          return kpiAnswer();
        }
        if (typeof ans === "string") {
          return ans.replaceAll("KPI Analiz Merkezi", "KPI Analiz Merkezi");
        }
        return ans;
      }
      return null;
    };

    if (window.BYS360AssistantModule) {
      window.BYS360AssistantModule.kpiAnalysisCenterFix = {
        version: "V18.8.2",
        info: KPI_INFO,
        apply: function(){ applyKpiIdentity(); replaceKpiTitle(); }
      };
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }

  setTimeout(function(){ applyKpiIdentity(); replaceKpiTitle(); }, 300);
  setTimeout(function(){ applyKpiIdentity(); replaceKpiTitle(); }, 1200);
})();
/* BYS360_V18_8_2_KPI_ANALIZ_MERKEZI_FIX_END */


(function(){
  "use strict";

  const safeMenuFullMap = {
  "/performans/stratejik/kpi-dashboard": {
    "title": "KPI Dashboardu",
    "module": "Stratejik Performans",
    "help_key": "strategic_kpi_dashboard",
    "summary": "KPI gerçekleşmeleri, hedef durumu, risk seviyeleri ve yönetici özetlerinin takip edildiği ekrandır."
  },
  "/performans/stratejik/hedefler": {
    "title": "Hedefler",
    "module": "Stratejik Performans",
    "help_key": "strategic_targets",
    "summary": "Hedef dönemleri, hedef kartları, hedef değerleri, gerçekleşen değerler ve hedef durumları burada yönetilir."
  },
  "/performans/stratejik/yetkinlik-kutuphanesi": {
    "title": "Yetkinlik Kütüphanesi",
    "module": "Stratejik Performans",
    "help_key": "competency_library",
    "summary": "Görev, rol, performans, gelişim önerisi ve analiz süreçlerinde kullanılacak yetkinlikler burada tanımlanır."
  },
  "/performans/stratejik/oz-degerlendirme": {
    "title": "Öz Değerlendirme",
    "module": "Stratejik Performans",
    "help_key": "self_assessment",
    "summary": "Personelin dönem özeti, başarıları, zorlandığı alanlar ve gelişim ihtiyacını yazdığı ekrandır."
  },
  "/performans/stratejik/ai-kpi-analiz": {
    "title": "KPI Analiz Merkezi",
    "module": "Stratejik Performans",
    "help_key": "kpi_analysis_center",
    "summary": "KPI gerçekleşmeleri, riskli hedefler, yönetici önerileri ve performans bağlantıları için karar destek ekranıdır."
  },
  "/performance/meeting-development/faz10": {
    "title": "Dönem İçi Notlar",
    "module": "Performans Yönetimi",
    "help_key": "interim_notes_faz10",
    "summary": "Dönem içinde olumlu/olumsuz olay, başarı, gelişim ihtiyacı ve genel gözlem notlarının tutulduğu ekrandır."
  },
  "/performance/interim-notes": {
    "title": "Dönem İçi Notlar",
    "module": "Performans Yönetimi",
    "help_key": "interim_notes",
    "summary": "Dönem içi notlar ve ara geri bildirimlerin takip edildiği ekrandır."
  },
  "/performance/meeting-development/faz9": {
    "title": "Hatırlatma ve Aksatan Amirler",
    "module": "Performans Yönetimi",
    "help_key": "reminders_delayed_supervisors_faz9",
    "summary": "Bekleyen değerlendirme görevleri, yaklaşan son tarihler ve aksatan amirlerin takip edildiği ekrandır."
  },
  "/performance/personnel-support-publish-approvals": {
    "title": "Yayın Ön Onayı",
    "module": "Performans Yönetimi",
    "help_key": "personnel_support_publish_approvals",
    "summary": "Sonuçların nihai yayından önce Personel ve Destek Hizmetleri Grup Başkanı tarafından kontrol edildiği ekrandır."
  },
  "/performance/process-reports": {
    "title": "Süreç Raporları",
    "module": "Performans Yönetimi",
    "help_key": "process_reports",
    "summary": "Dönem, amir, yayın, onay, gecikme ve süreç durumlarına ilişkin raporların görüntülendiği ekrandır."
  },
  "/performance/process-tracking": {
    "title": "Süreç Takibi",
    "module": "Performans Yönetimi",
    "help_key": "process_tracking",
    "summary": "Değerlendirme, onay, yayın kilidi, düşük performans ve süreç durumlarının takip edildiği ekrandır."
  }
};

  const BAD_FALLBACK_PARTS = [
    "güvenli menü haritasında özel bir başlıkla eşleşmedi",
    "yanlış linke yönlendirmemek için ekran adını doğrulamadan",
    "Yapmak istediğiniz işlemi yazarsanız sizi güvenli BYS360 ekranına yönlendiririm"
  ];

  function normalizePath(path){
    let p = String(path || "").trim();
    try {
      if (p.startsWith("http://") || p.startsWith("https://")) p = new URL(p).pathname;
    } catch(e){}
    if (p.length > 1 && p.endsWith("/")) p = p.slice(0, -1);
    return p;
  }

  function getSafeScreen(path){
    const p = normalizePath(path || (window.location && window.location.pathname) || "/");
    if (safeMenuFullMap[p]) return Object.assign({url:p}, safeMenuFullMap[p]);

    const keys = Object.keys(safeMenuFullMap).sort((a,b) => b.length - a.length);
    for (const key of keys) {
      if (p.startsWith(key + "/")) return Object.assign({url:key}, safeMenuFullMap[key]);
    }
    return null;
  }

  function isBadFallback(answer){
    const a = String(answer || "");
    return BAD_FALLBACK_PARTS.some(function(p){ return a.includes(p); });
  }

  function isPageQuestion(question){
    const q = String(question || "").toLocaleLowerCase("tr-TR");
    return [
      "hangi ekrandayım",
      "hangi sayfadayım",
      "bu sayfada ne yapabilirim",
      "bu ekran ne işe yarar",
      "bu ekranı anlat",
      "bu sayfayı tanıyor musun",
      "sayfayı tanı",
      "burada ne yapacağım",
      "kpi analiz merkezi"
    ].some(function(p){ return q.includes(p); });
  }

  function applySafeScreenIdentity(){
    const screen = getSafeScreen();
    if (!screen) return null;

    document.body.setAttribute("data-bys360-screen", screen.title);
    document.body.setAttribute("data-bys360-module", screen.bölüm);
    document.body.setAttribute("data-bys360-help-key", screen.help_key);
    document.body.setAttribute("data-bys360-safe-url", screen.url);

    let node = document.getElementById("bys360-official-screen-identity");
    if (!node) {
      node = document.createElement("div");
      node.id = "bys360-official-screen-identity";
      node.hidden = true;
      node.style.display = "none";
      document.body.appendChild(node);
    }

    node.setAttribute("data-bys360-screen", screen.title);
    node.setAttribute("data-bys360-module", screen.bölüm);
    node.setAttribute("data-bys360-help-key", screen.help_key);
    node.setAttribute("data-bys360-safe-url", screen.url);
    node.setAttribute("data-bys360-summary", screen.summary);

    return screen;
  }

  function replaceVisibleTitle(){
    const screen = applySafeScreenIdentity();
    if (!screen) return null;

    const selectors = "h1,h2,.page-title,.content-title,.module-title,.dashboard-title,.page-header-title,.section-title,[data-page-title],[data-title]";
    document.querySelectorAll(selectors).forEach(function(el){
      const t = (el.textContent || "").trim();
      if (
        t === "Kontrol Paneli" ||
        t === "Dashboard" ||
        t === "AI KPI Analiz" ||
        (screen.title === "KPI Analiz Merkezi" && t.includes("AI KPI Analiz"))
      ) {
        el.textContent = screen.title;
        el.setAttribute("data-bys360-title-fixed", "v19-safe-menu");
      }
    });

    return screen;
  }

  function safeScreenAnswer(){
    const screen = replaceVisibleTitle() || applySafeScreenIdentity();
    if (!screen) return null;

    return [
      "Bulunduğunuz ekran: " + screen.title,
      "Alan: " + screen.bölüm,
      "",
      screen.summary,
      "",
      "Güvenli ekran yolu: " + screen.url
    ].join("\n");
  }

  function install(){
    replaceVisibleTitle();

    // Güvenli menü haritasını önceki global haritalara da ekle.
    window.BYS360SafeMenuFullMapV19 = {
      version: "V19",
      safeMenuFullMap: safeMenuFullMap,
      getSafeScreen: getSafeScreen,
      applySafeScreenIdentity: applySafeScreenIdentity,
      safeScreenAnswer: safeScreenAnswer
    };

    if (window.BYS360OfficialScreenIdentity && window.BYS360OfficialScreenIdentity.officialScreenIdentityMap) {
      Object.keys(safeMenuFullMap).forEach(function(url){
        const item = safeMenuFullMap[url];
        window.BYS360OfficialScreenIdentity.officialScreenIdentityMap[url] = {
          screen: item.title,
          module: item.module,
          helpKey: item.help_key,
          help: item.summary
        };
      });
    }

    if (window.BYS360ScreenTitleFixV18_8 && window.BYS360ScreenTitleFixV18_8.screenTitleMap) {
      Object.keys(safeMenuFullMap).forEach(function(url){
        const item = safeMenuFullMap[url];
        window.BYS360ScreenTitleFixV18_8.screenTitleMap[url] = {
          title: item.title,
          module: item.module,
          helpKey: item.help_key
        };
      });
    }

    const previousLocal = window.BYS360AssistantLocalAnswer;
    window.BYS360AssistantLocalAnswer = function(question){
      if (isPageQuestion(question)) {
        const ans = safeScreenAnswer();
        if (ans) return ans;
      }

      if (typeof previousLocal === "function") {
        const old = previousLocal(question);
        if (isBadFallback(old)) {
          const ans = safeScreenAnswer();
          if (ans) return ans;
        }
        if (typeof old === "string") {
          return old.replaceAll("AI KPI Analiz", "KPI Analiz Merkezi");
        }
        return old;
      }

      return null;
    };

    if (window.BYS360AssistantModule) {
      window.BYS360AssistantModule.safeMenuFullMapV19 = window.BYS360SafeMenuFullMapV19;
      const oldAnswer = window.BYS360AssistantModule.answer;
      if (typeof oldAnswer === "function") {
        window.BYS360AssistantModule.answer = function(question){
          if (isPageQuestion(question)) {
            const ans = safeScreenAnswer();
            if (ans) return ans;
          }
          const old = oldAnswer.apply(this, arguments);
          if (isBadFallback(old)) {
            const ans = safeScreenAnswer();
            if (ans) return ans;
          }
          return typeof old === "string" ? old.replaceAll("AI KPI Analiz", "KPI Analiz Merkezi") : old;
        };
      }
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();

  setTimeout(replaceVisibleTitle, 250);
  setTimeout(replaceVisibleTitle, 900);
  setTimeout(replaceVisibleTitle, 1800);
})();

/* BYS360_ASSISTANT_SCREEN_MAP_V20_START */
