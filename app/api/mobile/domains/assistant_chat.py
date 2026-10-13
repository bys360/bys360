from __future__ import annotations

# BYS360_P1D_MOBILE_ROUTES_COMM_ASSISTANT_SPLIT
# Domain: assistant_chat
# Bu modül mobil API endpoint sözleşmesini domain bazlı taşır.
# URL/endpoint isimleri korunur; ortak yardımcılar shared.py içinden gelir.
from app.api.mobile.shared import (
    EvaluationAssignment,
    Notification,
    SupportTicket,
    User,
    _clean_mobile_text,
    _full_name,
    _metric,
    _safe_count,
    jsonify,
    mobile_api_bp,
    request,
    require_mobile_user,
)
from app.services.support_ticket_access import (
    can_view_all_support_tickets,
    support_ticket_visibility_clause,
)


# BYS360_MOBILE_V2_8_49_ASSISTANT_CHAT_API
# Mobil BYS360 Asistanı: doğal dil soru-cevap, güvenli yönlendirme ve yetki kontrollü rehberlik.
def _b49_norm(value):
    text = str(value or '').strip().lower()
    table = str.maketrans({'ı': 'i', 'İ': 'i', 'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u', 'ş': 's', 'Ş': 's', 'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c'})
    return text.translate(table)


def _b49_pack(intent, module, answer, route_hint, roles, steps, warnings=None, controls=None, suggestions=None):
    return {
        'source': 'bys360_mobile_assistant_v2_8_49',
        'intent': intent,
        'module': module,
        'answer': answer,
        'route_hint': route_hint,
        'required_roles': roles or ['Yetkinize göre değişir'],
        'steps': steps or [],
        'warnings': warnings or ['Asistan idari karar üretmez, hassas veri göstermez ve yetki sınırını aşmaz.'],
        'control_items': controls or [],
        'suggested_questions': suggestions or [
            'Performans dönemi nasıl oluşturulur?',
            'Puanlama görevimi nasıl tamamlarım?',
            'Karne neden görünmüyor?',
            'Yeni mesaj nasıl gönderilir?',
        ],
    }


def _b49_safe_summary(user):
    try:
        unread = _safe_count(Notification.query.filter_by(user_id=user.id, is_read=False))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/assistant_chat.py:42")
        unread = 0
    try:
        support_q = SupportTicket.query.order_by(SupportTicket.created_at.desc())
        if can_view_all_support_tickets(user):  # K5: counts only tickets inside the viewer's scope
            support_q = support_q.filter(support_ticket_visibility_clause(user))
        else:
            support_q = support_q.filter(SupportTicket.created_by_user_id == user.id)
        open_support = _safe_count(support_q.filter(~SupportTicket.status.in_(['closed', 'kapalı', 'kapali', 'resolved'])))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/assistant_chat.py:49")
        open_support = 0
    try:
        pending_perf = _safe_count(EvaluationAssignment.query.filter(
            EvaluationAssignment.evaluator_id == user.id,
            EvaluationAssignment.status.in_(['bekliyor', 'kismen_tamamlandi']),
        ))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/domains/assistant_chat.py:53")
        pending_perf = 0
    return [
        _metric('Bildirim', unread, 'Okunmamış bildirim', 'red', 'notifications'),
        _metric('Destek', open_support, 'Açık destek talebi', 'blue', 'support'),
        _metric('Performans', pending_perf, 'Bekleyen değerlendirme görevi', 'red', 'assignment'),
    ]


def _b49_sensitive_response(q):
    sensitive_terms = ['puanini goster', 'puan göster', 'puan goster', 'amir gorusunu goster', 'gorusunu goster', 'mesaj icerigini goster', 'mesaj içeriğini göster', 'anket cevabini goster', 'anket cevabı', 'tc kimlik', 'maas', 'şifre', 'sifre']
    if any(term in q for term in sensitive_terms):
        return _b49_pack(
            'GUVENLI_SINIR',
            'BYS360 Asistanı',
            'Bu bilgi hassas veri kapsamına girebilir. Asistan kişisel performans puanı, amir görüşü, mesaj içeriği, anket cevabı veya benzeri mahrem içeriği doğrudan göstermez. Sizi yetkili olduğunuz ilgili ekrana yönlendirebilir.',
            'Sol menü > ilgili modül',
            ['Yetkili kullanıcılar kendi ekranlarından işlem yapabilir'],
            ['İlgili modülü açın.', 'Yetkiniz varsa kayıtları kendi ekranında görüntüleyin.', 'Yetkiniz yoksa yetkili birimden destek isteyin.'],
            ['Asistan idari karar üretmez ve hassas veriyi sohbet içinde açıklamaz.'],
            ['Yetkili ekrana erişebiliyor musunuz?', 'Kayıt yayın/onay sürecinden geçmiş mi?'],
        )
    return None


@mobile_api_bp.post('/assistant/v2/ask')
@require_mobile_user
def mobile_b49_assistant_v2_ask(user):
    from app.api.mobile.services.assistant_service import delegate_mobile_b49_assistant_v2_ask
    return delegate_mobile_b49_assistant_v2_ask(user)

def _bys360_legacy_mobile_b49_assistant_v2_ask(user: User):
    payload = request.get_json(silent=True) or {}
    question = _clean_mobile_text(payload.get('question') or payload.get('q') or payload.get('message'), limit=800)
    q = _b49_norm(question)
    if not question:
        return jsonify(_b49_pack(
            'BOS_SORU', 'BYS360 Asistanı',
            'Sorunuzu yazarsanız size BYS360 içinde doğru ekranı ve işlem adımlarını gösterebilirim.',
            'BYS360 Asistanı', ['Tüm kullanıcılar'],
            ['Sorunuzu günlük dille yazın.', 'Örneğin: performans dönemi nasıl açılır?'],
            controls=['Cevap gelmezse internet bağlantınızı ve oturumunuzu kontrol edin.'],
        ) | {'metrics': _b49_safe_summary(user)})

    sensitive = _b49_sensitive_response(q)
    if sensitive:
        sensitive['metrics'] = _b49_safe_summary(user)
        return jsonify(sensitive)

    if 'bys360 nedir' in q or 'nereden baslay' in q or 'nereden başlay' in q or 'ne ise yarar' in q:
        data = _b49_pack(
            'GENEL_BYS360_REHBERLIK',
            'Genel BYS360 Kullanımı',
            'BYS360; personel, performans, iletişim, anket, destek, bildirim, raporlama, KPI/Hedef ve karar destek süreçlerini tek çatı altında toplayan kurumsal yönetim sistemidir. Mobilde asistan, size doğru ekranı ve işlem sırasını gösterir.',
            'Ana Sayfa / Sol Menü',
            ['Tüm kullanıcılar'],
            ['Ana Sayfa ekranında genel durum kartlarını kontrol edin.', 'Sol menüden yapacağınız işleme ait modülü açın.', 'Bekleyen bildirim, görev, destek talebi veya anket varsa önce bunları tamamlayın.'],
            ['Asistan karar vermez; yalnızca rehberlik ve güvenli yönlendirme sağlar.'],
            ['Hangi modüle gitmeniz gerektiği netleşti mi?', 'Bekleyen iş kartlarınızı kontrol ettiniz mi?'],
        )
    elif 'performans' in q and ('donem' in q or 'dönem' in q or 'olustur' in q or 'oluştur' in q or 'ac' in q or 'aç' in q):
        data = _b49_pack(
            'PERFORMANS_DONEMI_OLUSTURMA',
            'Performans Yönetimi',
            'Bu işlem Performans Yönetimi içindedir. Dönem açıldıktan sonra kriter, ağırlık, kapsam ve görev üretimi de kontrol edilmelidir.',
            'Sol menü > Performans Yönetimi > Dönem Yönetimi',
            ['Admin', 'Sistem Yöneticisi', 'Performans Yetkilisi', 'Yetki verilmiş İK/personel kullanıcısı'],
            ['Performans Yönetimi ekranını açın.', 'Dönem Yönetimi veya Performans Dönemleri sekmesine girin.', 'Yeni Dönem Oluştur butonuna basın.', 'Dönem adı, dönem türü, başlangıç ve bitiş tarihlerini girin.', 'Kapsam tipini seçin: tüm kurum, birim, üst birim, kategori veya seçili personel.', 'Kaydedin ve görev üretimi ekranında zincirleri kontrol edin.'],
            ['Aynı personel için çakışan dönem varsa sistem uyarı vermelidir.', 'Dönem oluşturmak tek başına değerlendirmeyi başlatmaz.'],
            ['Dönem listede görünüyor mu?', 'Kapsama giren personel doğru mu?', 'Eksik amir zinciri uyarısı var mı?'],
        )
    elif 'puan' in q or 'degerlendirme' in q or 'değerlendirme' in q or 'gorev' in q or 'görev' in q:
        data = _b49_pack(
            'PERFORMANS_PUANLAMA_REHBERI',
            'Performans Yönetimi',
            'Puanlama işlemi Değerlendirme Görevlerim alanından yapılır. Mobilde görev kartına girip kriter bazlı puan, genel görüş ve tamamla işlemi yapılır.',
            'Sol menü > Performans Yönetimi > Değerlendirme Görevlerim',
            ['Atanmış amir/değerlendirici', 'Yetkili performans kullanıcısı'],
            ['Performans Yönetimi ekranını açın.', 'Değerlendirme Görevlerim listesinden personel görevini seçin.', 'Kriterler için 1-5 arası puan girin veya hızlı puanlama butonlarını kullanın.', 'Genel görüş alanını doldurun.', 'Taslak Kaydet veya Tamamla butonuna basın.'],
            ['Kör değerlendirme yoktur; sonraki amir önceki amirin puan ve kanaatini görebilmelidir.', '70 altı ve 90 üstü sonuçlarda genel görüş kuralı korunur.'],
            ['Görev tamamlandı durumuna geçti mi?', 'Eksik kriter kaldı mı?', 'İade veya geri çekme gerekiyorsa uygun buton görünüyor mu?'],
        )
    elif 'karne' in q or 'sonuc' in q or 'sonuç' in q or 'yayın' in q or 'yayin' in q:
        data = _b49_pack(
            'KARNE_GORUNURLUK_REHBERI',
            'Performans Yönetimi',
            'Personel karneyi süreç tamamlanıp yetkili yayın/onay yapıldıktan sonra görür. Yayınlanmadan, Başkan/Üst Onay gerekiyorsa onay tamamlanmadan sonuç personele açılmaz.',
            'Sol menü > Performans Yönetimi > Karne / Sonuçlar',
            ['Personel kendi yayınlanmış karnesini görür', 'Admin/Performans Yetkilisi yayın ve kontrol ekranlarını görür'],
            ['Dönemde tüm değerlendirme görevlerinin tamamlandığını kontrol edin.', '70 altı varsa Başkan/Üst Onay durumunu kontrol edin.', 'Yayın ön onayı gerekiyorsa ilgili onayın tamamlanmasını bekleyin.', 'Admin/İK nihai yayını yaptıktan sonra personel karneyi görebilir.'],
            ['Yayınlanmamış sonuç personele gösterilmez.', 'Asistan puan veya amir görüşü açıklamaz; sadece görünürlük sürecini anlatır.'],
            ['Dönem tamamlandı mı?', 'Başkan/Üst Onay bekleyen kayıt var mı?', 'Nihai yayın yapıldı mı?'],
        )
    elif 'personel' in q or 'sicil' in q or 'birim' in q or 'yonetici' in q or 'yönetici' in q:
        data = _b49_pack(
            'PERSONEL_YONETIMI_REHBERI',
            'Personel Yönetimi',
            'Personel verisi BYS360’ın temel omurgasıdır. Sicil, birim, üst birim, unvan ve yönetici bilgisi doğru olmazsa performans zinciri ve yetki görünürlüğü de etkilenir.',
            'Sol menü > Personel Yönetimi',
            ['Admin', 'Sistem Yöneticisi', 'Personel Yönetimi yetkilisi', 'Yetki verilmiş İK/personel kullanıcısı'],
            ['Personel Yönetimi ekranını açın.', 'Personel Listesi veya Personel Ekle alanına girin.', 'Sicil No, ad, soyad, unvan, görev, birim, üst birim ve yönetici bilgilerini doldurun.', 'Rol ve menü görünürlüğünü kontrol edin.', 'Kaydedin ve listede göründüğünü kontrol edin.'],
            ['TC yerine Sicil No kullanılmalıdır.', 'Personel kaydı yanlışsa performans amir zinciri de yanlış üretilebilir.'],
            ['Personel listede görünüyor mu?', 'Birim ve yönetici doğru mu?', 'Rol/menü yetkisi doğru mu?'],
        )
    elif 'mesaj' in q or 'iletisim' in q or 'iletişim' in q or 'konusma' in q or 'konuşma' in q:
        data = _b49_pack(
            'ILETISIM_MESAJLASMA_REHBERI',
            'İletişim ve Mesajlaşma',
            'Yeni mesaj için İletişim ekranında alıcı seçilir, ilk mesaj yazılır ve konuşma başlatılır. Asistan mesaj içeriğini göstermez; yalnızca kullanım yolunu anlatır.',
            'Sol menü > İletişim > Yeni Mesaj',
            ['Sisteme giriş yapmış yetkili kullanıcı'],
            ['İletişim ekranını açın.', 'Yeni Mesaj butonuna basın.', 'Personel listesinden alıcı seçin.', 'İlk mesajı yazın.', 'Konuşmayı Başlat butonuna basın.'],
            ['Mesaj içeriği hassas olabilir; asistan sohbet içeriğini açıklamaz.', 'Alıcı listesi gelmezse oturum ve internet bağlantısı kontrol edilmelidir.'],
            ['Alıcı listesi açıldı mı?', 'Konuşma listede oluştu mu?', 'Mesaj balonu gönderildi mi?'],
        )
    elif 'destek' in q or 'talep' in q or 'hata' in q or 'sorun' in q:
        data = _b49_pack(
            'DESTEK_TALEBI_REHBERI',
            'Destek Talepleri',
            'Teknik hata, kullanım sorunu veya geliştirme talebi için Destek Talepleri ekranından kayıt açılır.',
            'Sol menü > Destek Talepleri > Yeni Talep',
            ['Tüm kullanıcılar', 'Yetkili destek/personel kullanıcıları'],
            ['Destek Talepleri ekranını açın.', 'Yeni Talep butonuna basın.', 'Başlık, açıklama, modül ve öncelik alanlarını doldurun.', 'Varsa ekran görüntüsü veya hata metnini ekleyin.', 'Kaydedin ve talep numarasını takip edin.'],
            ['Hata metninde şifre veya gizli bilgi varsa paylaşmadan önce temizleyin.'],
            ['Talep numarası oluştu mu?', 'Durum açık/işlemde görünüyor mu?'],
        )
    elif 'anket' in q or 'duyuru' in q or 'bildirim' in q:
        data = _b49_pack(
            'ANKET_BILDIRIM_REHBERI',
            'İletişim ve Anket Yönetimi',
            'Anket, duyuru ve bildirim süreçleri İletişim/Anket alanlarından takip edilir. Size atanmış anket varsa mobilde cevaplayabilirsiniz.',
            'Sol menü > Anketler / Bildirimler',
            ['Tüm kullanıcılar', 'Anket/duyuru yetkisi verilmiş kullanıcılar'],
            ['Anketler veya Bildirimler ekranını açın.', 'Size atanmış kayıtları kontrol edin.', 'Anket varsa soruları cevaplayın.', 'Kaydet/Gönder butonuna basın.'],
            ['Asistan kişisel anket cevabını göstermez.', 'Duyuru hedefleme yetkiye bağlıdır.'],
            ['Anket gönderildi mi?', 'Bildirim okundu durumuna geçti mi?'],
        )
    elif 'yetki' in q or 'rol' in q or 'menu' in q or 'menü' in q or 'ayar' in q:
        data = _b49_pack(
            'YETKI_MENU_REHBERI',
            'Sistem Ayarları',
            'Rol, yetki ve menü görünürlüğü Sistem Ayarları alanından yönetilir. Kullanıcının görmemesi gereken menü hiç görünmemelidir; URL ile girilirse de erişim engellenmelidir.',
            'Sol menü > Sistem Ayarları > Rol / Menü Görünürlüğü',
            ['Admin', 'Sistem Yöneticisi', 'Yetkilendirme sorumlusu'],
            ['Sistem Ayarları ekranını açın.', 'Rol/Yetki veya Menü Görünürlüğü alanına girin.', 'Kullanıcı, rol veya birim kapsamını seçin.', 'Gerekli menüleri açıp kapatın.', 'Kaydedin ve kullanıcıyla test edin.'],
            ['Yetki değişiklikleri audit log ile izlenmelidir.', 'Yetkisiz kullanıcı beyaz sayfaya düşmemeli; kurumsal erişim engeli görmelidir.'],
            ['Menü görünürlüğü doğru mu?', 'Backend erişim kontrolü çalışıyor mu?', 'Kullanıcı çıkış-giriş yaptı mı?'],
        )
    elif 'kpi' in q or 'hedef' in q or 'dashboard' in q or 'rapor' in q:
        data = _b49_pack(
            'KPI_RAPOR_REHBERI',
            'KPI / Hedef ve Raporlar',
            'KPI, hedef ve rapor ekranları yöneticilere hedef gerçekleşme, risk ve performans görünürlüğü sağlar. Yetki kapsamına göre veri görünür.',
            'Sol menü > KPI / Hedef veya Raporlar',
            ['Başkan/Üst Yönetim', 'Admin', 'Yetkili yönetici', 'Performans/KPI yetkilisi'],
            ['KPI / Hedef ekranını açın.', 'Dönem veya kapsam filtresini seçin.', 'Hedef kartlarını, gerçekleşme oranlarını ve risk durumunu kontrol edin.', 'Gerekirse Raporlar ekranından çıktı alın.'],
            ['Asistan karar destek notu verebilir; nihai idari karar üretmez.'],
            ['Kapsam filtresi doğru mu?', 'Riskli hedefler görünüyor mu?', 'Rapor yetkiniz var mı?'],
        )
    else:
        data = _b49_pack(
            'GENEL_REHBERLIK',
            'BYS360 Asistanı',
            'Sorunuzu BYS360 kapsamında yorumladım. Daha net sonuç için yapmak istediğiniz işlemi günlük dille yazabilirsiniz: dönem açacağım, personel ekleyeceğim, mesaj göndereceğim, karne görünmüyor gibi.',
            'Sol menü > ilgili modül',
            ['İşleme göre yetkili kullanıcı'],
            ['Ana Sayfa veya Sol Menüden ilgili modülü açın.', 'İşleminize ait sekme veya butonu seçin.', 'Zorunlu alanları doldurun.', 'Kaydedin ve kayıt/listede kontrol edin.'],
            ['Asistan hassas veri göstermez, puan belirlemez ve idari karar üretmez.'],
            ['Hangi modülde olduğunuzu kontrol edin.', 'Yetkiniz yoksa yetkili birimden destek isteyin.'],
        )

    try:
        data['metrics'] = _b49_safe_summary(user)
        data['user_label'] = _full_name(user)
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/routes.py:2361)")
    return jsonify(data)

