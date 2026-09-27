from __future__ import annotations

# BYS360_ASSISTANT_MASTER_KNOWLEDGE_V3
from typing import Any

VERSION = "BYS360 Asistanı Proje Hafızası V3"
MODE = "Kaynak dosya tabanlı rol, modül, süreç ve güvenlik rehberi"
ASSISTANT_NAME = "BYS360 Asistanı"
NOTICE = "BYS360 Asistanı idari karar üretmez, performans puanı belirlemez, onay/ret işlemi yapmaz ve yetki dışı hassas veri göstermez."
SECURITY_NOTICE = "Yanıtlar kullanım rehberi, süreç açıklaması ve güvenli yönlendirme amaçlıdır. Gerçek işlem ilgili BYS360 ekranında yetkili kullanıcı tarafından yapılır."

DEFAULT_QUICK_REPLIES = [
    "BYS360 nedir?",
    "70 altı süreç nasıl ilerler?",
    "Rol matrisi nasıl çalışır?",
    "Personel nasıl eklenir?",
    "KPI/Hedef ekranları nasıl kullanılır?",
    "AI Karar Destek ne yapar?",
    "Asistan neyi göstermez?",
]

def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    table = str.maketrans({"ı":"i","İ":"i","I":"i","ş":"s","Ş":"s","ğ":"g","Ğ":"g","ü":"u","Ü":"u","ö":"o","Ö":"o","ç":"c","Ç":"c","â":"a","î":"i","û":"u"})
    text = text.translate(table)
    for ch in "\n\r\t.,;:!?()[]{}<>/\\|+*=\"'`~":
        text = text.replace(ch, " ")
    return " ".join(text.split())


def _role_from_user(user: Any) -> str:
    candidates = []
    for attr in ("role", "role_name", "role_key", "user_role", "authority_role", "position", "title", "unvan", "job_title", "display_role"):
        try:
            value = getattr(user, attr, None)
            if value:
                candidates.append(str(value))
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/assistant_project_master_knowledge_v3.py)")
    try:
        if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
            return "admin"
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/assistant_project_master_knowledge_v3.py)")
    joined = _norm(" ".join(candidates))
    if any(x in joined for x in ("sistem", "admin", "yonetici", "superuser")):
        return "admin"
    if any(x in joined for x in ("personel ve destek", "insan kaynak", "ik", "performans yetkilisi")):
        return "hr_performance"
    if "baskan yardimcisi" in joined or "ust yonetim" in joined:
        return "upper_management"
    if "baskan" in joined:
        return "president"
    if "grup baskani" in joined:
        return "group_head"
    if "koordinator" in joined or "koordinat" in joined:
        return "coordinator"
    if "amir" in joined or "degerlendirici" in joined:
        return "supervisor"
    return "personnel"


def _role_label(role: str) -> str:
    return {
        "admin": "Sistem Yöneticisi/Admin",
        "president": "Başkan/Üst Yönetim",
        "upper_management": "Üst Yönetim",
        "group_head": "Grup Başkanı",
        "coordinator": "Koordinatör",
        "supervisor": "Amir/Değerlendirici",
        "hr_performance": "Personel/Performans Yetkilisi",
        "personnel": "Standart Kullanıcı/Personel",
    }.get(role, "Kullanıcı")


def _role_scope_note(role: str) -> str:
    if role in ("admin", "president", "upper_management"):
        return "Üst yönetim veya admin ekranları dahi sistemde tanımlı rol, kişi, birim ve menü yetkisiyle sınırlı çalışır."
    if role == "group_head":
        return "Grup Başkanı kendi grup/üst birim kapsamı dışındaki kişi detaylarına yönlendirilmemelidir."
    if role == "coordinator":
        return "Koordinatör yalnızca kendi çalışma grubu veya koordinasyon kapsamındaki kayıtları görmelidir."
    if role == "supervisor":
        return "Amir yalnızca kendisine atanmış değerlendirme görevlerini ve yetkili olduğu personeli görmelidir."
    if role == "hr_performance":
        return "Personel/Performans yetkilisinin kapsamı rol matrisi, kişi bazlı yetki ve menü görünürlüğüyle belirlenir."
    return "Standart kullanıcı yalnızca kendi hesabı, kendi bildirimleri, kendi talepleri ve yayınlanmış kendi karnesiyle sınırlıdır."


def _a(label: str, url: str, desc: str) -> dict[str, str]:
    return {"label": label, "title": label, "route": url, "url": url, "description": desc, "safety_level": "rehber_yonlendirme"}

TOPICS: list[dict[str, Any]] = [
    {
        "key": "identity_creator",
        "title": "BYS360 Asistanı kimdir ve kim geliştirdi?",
        "section": "Kimlik",
        "keywords": ["sen kimsin", "adın ne", "adin ne", "kim geliştirdi", "kim gelistirdi", "seni kim", "seni kim geliştirdi", "havva gülsen özden", "havva gulsen ozden", "gülsen özden", "gulsen ozden", "kurumsal geliştirme", "bys360 asistanı", "bys360 asistani"],
        "answer": """Ben BYS360 Asistanı. BYS360’ın kullanımını öğretmek, doğru ekranı göstermek, süreçleri sade anlatmak ve kullanıcıyı yetkisi dahilinde güvenli şekilde yönlendirmek için tasarlandım.

BYS360 projesi kurum içi ihtiyaçlara göre Havva Gülsen Özden (geliştirici) ve Mustafa Bektaş (eş geliştirici) tarafından geliştirilen kurumsal yönetim platformudur. Ben de bu yapının kullanıcı rehberliği katmanıyım.

Benim sınırım nettir: idari karar vermem, performans puanı belirlemem, onay/ret işlemi yapmam, mesaj içeriği, anket cevabı, amir görüşü veya yetki dışı hassas verileri doğrudan göstermem.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("BYS360 Asistanı Paneli", "/ai-agent/panel", "Asistan paneli"), ("Asistan Bilgi Bankası", "/ai-agent/knowledge", "Rehber kayıtları")],
        "quick": ["BYS360 nedir?", "Neleri öğretebilirsin?", "Asistan neyi göstermez?", "AI Karar Destek ne yapar?"],
        "priority": 100,
    },
    {
        "key": "greeting",
        "title": "Selamlama ve doğal karşılama",
        "section": "Kimlik",
        "keywords": ["merhaba", "selam", "iyi misin", "nasılsın", "nasilsin", "günaydın", "gunaydin", "iyi akşamlar", "iyi aksamlar"],
        "answer": """Merhaba, ben buradayım. BYS360’da hangi ekrana gideceğinizi, hangi işlemi hangi sırayla yapacağınızı veya bir kuralın ne anlama geldiğini birlikte netleştirebiliriz.

Bana örneğin “personel nasıl eklenir?”, “70 altı süreç nasıl ilerler?”, “rol matrisinden menü nasıl açılır?” veya “KPI hedefleri nerede?” diye sorabilirsiniz.

Yetki notu: {{ROLE_NOTE}}""",
        "quick": ["Personel nasıl eklenir?", "Performans dönemi nasıl açılır?", "Rol matrisi nasıl çalışır?", "Başkan onayları nerede?"],
        "priority": 92,
    },
    {
        "key": "project_overview",
        "title": "BYS360 nedir?",
        "section": "Ana Çatı",
        "keywords": ["bys360 nedir", "proje nedir", "bütünleşik yönetim", "butunlesik yonetim", "ana proje", "kurumsal platform", "kys alternatifi", "kys var", "neden bys360"],
        "answer": """BYS360, kurum içi yönetim süreçlerini tek merkezde toplayan; personel, performans, iletişim, anket, destek, bildirim, raporlama, KPI/Hedef ve AI Karar Destek süreçlerini bütünleşik şekilde yöneten kurumsal dijital yönetim platformudur.

KYS’nin alternatifi değildir. BYS360, KYS’nin doğal kapsamı dışında kalan kuruma özel iş akışlarını, performans değerlendirme mantığını, iç iletişimi, anket/geri bildirimi, destek taleplerini ve karar destek ihtiyacını tamamlayan sistemdir.

BYS360’ın temel mantığı üç katmandır: operasyon katmanı; ölçüm ve yönetim katmanı; analiz ve rehberlik katmanı.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Ana Sayfa", "/home", "BYS360 ana sayfası"), ("Yönetici Dashboard", "/performance/dashboard", "Yönetici görünürlüğü")],
        "quick": ["Canlı omurgada neler var?", "KYS ile farkı ne?", "Modülleri anlat", "AI Karar Destek ne yapar?"],
        "priority": 98,
    },
    {
        "key": "live_core",
        "title": "Canlı sistem omurgası",
        "section": "Ana Çatı",
        "keywords": ["canlı omurga", "canli omurga", "omurga", "hangi tablolar", "canlıda kalacak", "canlida kalacak", "aktif modüller", "aktif moduller", "kapsam dışı", "kapsam disi"],
        "answer": """Güncel canlı omurga şu ana yapılardan oluşur:

1. Kimlik, kullanıcı, yetki ve ayarlar: kullanıcılar, roller, menü görünürlüğü, sistem/modül ayarları, audit log ve değişiklik kayıtları.
2. Personel Yönetimi: kullanıcı/personel kayıtları, organizasyon birimleri, atama geçmişi, izin, devamsızlık ve vekâlet yapıları.
3. Performans Yönetimi: kriterler, dönemler, amir zinciri, değerlendirme görevleri, puanlama, karne, yayın, geçmiş, düşük performans ve rapor tabloları.
4. İletişim ve Anket: mesajlaşma, duyuru, bildirim, destek talepleri, anket, geri bildirim ve nabız yapıları.
5. AI Karar Destek: AI istek logları, öneriler, redaksiyon kuralları, özet önbelleği ve geri bildirim logları.
6. KPI/Hedef: hedef kartları, KPI ölçüm motoru, yetkinlik/öz değerlendirme ve stratejik dashboard yaklaşımı.

Canlı kapsamda olmayan modüller ileride yeni planla tekrar eklenebilir; mevcut canlı asistan bunları aktif omurga gibi anlatmamalıdır.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Sistem Ayarları", "/settings", "Ayar ve görünürlük kontrolleri"), ("Rol Matrisi", "/admin/role-matrix", "Rol bazlı menü yönetimi")],
        "quick": ["Personel modülü ne yapar?", "Performans omurgası nedir?", "AI tabloları ne işe yarar?", "Rol matrisi nasıl çalışır?"],
        "priority": 90,
    },
    {
        "key": "assistant_safety",
        "title": "Asistanın güvenlik ve veri sınırları",
        "section": "Güvenlik",
        "keywords": ["asistan neyi göstermez", "hassas veri", "gizlilik", "kvkk", "puan göster", "mesaj oku", "anket cevabı", "amir görüşü", "yetki dışı", "yetki disi", "karar verir mi", "puan verir mi"],
        "answer": """BYS360 Asistanı güvenli rehberlik katmanıdır. İşlem adımlarını anlatır, doğru ekrana yönlendirir, yetki kapsamındaki sayı/genel özetleri açıklayabilir ve kuralları öğretir.

Şunları yapmaz: idari karar üretmez, performans puanı vermez veya değiştirmez, onay/ret işlemi yapmaz, amir görüşü, personel puanı, mesaj metni, anket cevabı, destek talebi içeriği veya ek dosya gibi hassas içerikleri doğrudan göstermez.

Doğru kullanım: “Nereye gideceğim, hangi adımı izleyeceğim, bu kural ne demek?” sorularını cevaplamaktır.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Güvenlik Politikası", "/ai-agent/api/security-policy", "Asistan güvenlik özeti"), ("Sistem Ayarları", "/settings", "Güvenlik ayarları")],
        "quick": ["AI Karar Destek karar verir mi?", "Rol matrisi neyi korur?", "Özet kartlarında ne görünür?", "CAPTCHA nereden ayarlanır?"],
        "priority": 100,
    },
    {
        "key": "personnel",
        "title": "Personel Yönetimi nasıl çalışır?",
        "section": "Personel Yönetimi",
        "keywords": ["personel yönetimi", "personel yonetimi", "personel modülü", "personel modulu", "personel ekle", "personel kaydı", "personel kaydi", "sicil", "unvan", "birim", "üst birim", "ust birim", "personel kartı", "personel karti"],
        "answer": """Personel Yönetimi, BYS360’ın “kim, nerede, hangi görevde, kime bağlı, hangi yetkiye sahip?” sorularına verdiği ana cevaptır.

Personel ekleme/düzenleme genel adımları: Personel Yönetimi ekranını açın; yeni personel/personel kartı ekranına girin; Sicil No, ad-soyad, unvan, birim, üst birim, yönetici ve aktiflik bilgilerini doldurun; kategori alanı varsa Güvenlik, Temizlik, İdari Personel, Teknik Personel, Deneme Süreli Personel veya Diğer seçin; kullanıcı hesabı, rol ve menü görünürlüğünü Sistem Ayarları/Rol Matrisi tarafında kontrol edin.

BYS360’da TC yerine Sicil No tercih edilir. Personel verisi performans, izin, vekâlet, bildirim, rapor ve AI özetlerini besleyen temel veri merkezidir.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Personel Yönetimi", "/personnel", "Personel kayıtları"), ("Rol Matrisi", "/admin/role-matrix", "Kullanıcı menü yetkileri")],
        "quick": ["Personel kategorisi ne işe yarar?", "İzin ve vekâlet nasıl çalışır?", "Organizasyon geçmişi nedir?", "Rol matrisi nasıl ayarlanır?"],
        "priority": 93,
    },
    {
        "key": "leave_delegation",
        "title": "İzin, devamsızlık ve vekâlet",
        "section": "Personel Yönetimi",
        "keywords": ["izin", "devamsızlık", "devamsizlik", "vekâlet", "vekalet", "vekil", "izin talebi", "izin kaydı", "izin kaydi", "görev devri", "gorev devri", "amir izinli", "attendance"],
        "answer": """İzin, devamsızlık ve vekâlet BYS360’da personel süreçlerinin performans ve görev akışına bağlanmasını sağlar.

Genel kullanım: Personel Yönetimi altında İzin / Devamsızlık / Vekâlet ekranını açın; ilgili personeli, tarih aralığını, işlem türünü ve açıklamayı girin; amir izinliyse veya görev devri gerekiyorsa vekil tanımlayın; vekâlet başlangıç-bitiş tarihleri ve kapsamını doğru girin. Performans döneminde amir görevleri boşa düşmemeli; vekâlet akışı görev ve bildirimleri etkileyebilir.

Asistan izin onayı vermez; sadece ekran ve süreç adımlarını anlatır.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("İzin İşlemleri", "/personnel/leaves", "İzin kayıtları"), ("Vekâlet İşlemleri", "/personnel/delegations", "Vekâlet kayıtları")],
        "quick": ["Amir izinliyse ne olur?", "Vekâlet performansı etkiler mi?", "Devamsızlık nereden girilir?", "Personel kartı nerede?"],
        "priority": 82,
    },
    {
        "key": "performance_overview",
        "title": "Performans Yönetimi genel akışı",
        "section": "Performans Yönetimi",
        "keywords": ["performans yönetimi", "performans yonetimi", "performans nasıl çalışır", "performans nasil calisir", "değerlendirme", "degerlendirme", "karne", "puanlama", "performans süreci", "performans sureci"],
        "answer": """Performans Yönetimi BYS360’ın çekirdek modüllerinden biridir. Klasik form mantığı değil; dönem, kriter, amir zinciri, puanlama, onay, yayın, karne, arşiv, gelişim ve raporlama motorudur.

Genel akış: dönem hazırlanır; Değerlendirme Kriterleri kontrol edilir; personel, birim, kategori, amir, izin ve vekâlet verileri doğrulanır; sistem gerçek amir zincirine göre görev üretir; amirler işlem sırasına göre puan ve görüş girer; sistem nihai puan, açıklama zorunluluğu, 70 altı/90 üstü eşikleri ve onay ihtiyacını kontrol eder; gerekli onaylardan sonra yayın yapılır.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Performans Yönetimi", "/performance", "Performans ana ekranı"), ("Performans Dashboard", "/performance/dashboard", "Yönetici görünürlüğü")],
        "quick": ["Dönem nasıl açılır?", "Amir zinciri nasıl çalışır?", "70 altı süreç nedir?", "Karne ne zaman görünür?"],
        "priority": 98,
    },
    {
        "key": "period_scope",
        "title": "Dönem yönetimi ve kapsam tipleri",
        "section": "Performans Yönetimi",
        "keywords": ["dönem", "donem", "dönem aç", "donem ac", "özel dönem", "ozel donem", "aylık", "aylik", "3 aylık", "6 aylık", "kapsam tipi", "kategori dönemi", "kategori donemi", "seçili personel", "secili personel"],
        "answer": """Güncel performans yapısı tek yıllık dönemle sınırlı değildir. Dönem türleri yıllık, 6 aylık, 3 aylık, aylık veya özel dönem olabilir.

Dönem açma adımları: Performans Yönetimi > Dönem Yönetimi ekranına girin; dönem adını, türünü ve tarih aralığını tanımlayın; kapsam tipini seçin: tüm kurum, birim, üst birim, kategori/grup veya seçili personel. Güvenlik/Temizlik gibi kategoriye özel dönem açıldığında görevler yalnızca bu kapsamdaki personele üretilmelidir.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Dönem Yönetimi", "/performance/periods", "Performans dönemleri"), ("Görev Üretimi", "/performance/assignments", "Değerlendirme görevleri")],
        "quick": ["Kategoriye özel dönem nasıl açılır?", "Görev üretimi nasıl yapılır?", "Kriterler nereden tanımlanır?", "Çakışan dönem ne demek?"],
        "priority": 94,
    },
    {
        "key": "supervisor_rules",
        "title": "Amir zinciri ve işlem sırası",
        "section": "Performans Yönetimi",
        "keywords": ["amir zinciri", "1. amir", "2. amir", "3. amir", "işlem sırası", "islem sirasi", "kör değerlendirme", "kor degerlendirme", "koordinatör", "koordinator", "grup başkanı", "grup baskani", "başkan yardımcısı", "baskan yardimcisi"],
        "answer": """BYS360’da amir numarası ile işlem sırası aynı şey değildir. 1. amir hiyerarşik ana amirdir; 2. amir ikinci seviyedir; 3. amir varsa üçüncü seviyedir. Çok seviyeli yapılarda işlem sırası çoğunlukla 3 → 2 → 1 şeklindedir.

Kesin ilkeler: kör değerlendirme yoktur; sonraki amir önceki amirin puanını ve kanaatini görebilir. Çalışma grubu personelinde 1. amir Grup Başkanı, 2. amir Koordinatör, varsa 3. amir koordinatöre bağlı birim amiridir. Koordinatörde 1. amir Başkan Yardımcısı, 2. amir Grup Başkanıdır. Grup Başkanı ve Başkanlık seviyesi için işlem sırası 2 → 1 mantığıyla ilerler. Hukuk Müşavirliği ve Başkanın tek puanladığı özel rollerin istisnaları korunur.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Görev Üretimi", "/performance/assignments", "Amir zinciri ve görevler"), ("Performans Ayarları", "/settings/performance", "3. amir ve ağırlık ayarları")],
        "quick": ["3. amir ne zaman çalışır?", "Hukuk Müşavirliği kuralı nedir?", "Başkan onayı ne zaman gerekir?", "Puanlama sırası nasıl?"],
        "priority": 100,
    },
    {
        "key": "third_supervisor",
        "title": "3. amir kuralı",
        "section": "Performans Yönetimi",
        "keywords": ["3. amir", "üçüncü amir", "ucuncu amir", "yorum modu", "puan modu", "3 amir sütunu", "3 amir sutunu", "opsiyonel amir", "ağırlık", "agirlik"],
        "answer": """3. amir BYS360’da zorunlu değildir; yalnızca yapıda gerçekten ihtiyaç varsa kullanılır.

Yorum modunda 3. amir yalnızca görüş yazar, puana etkisi %0’dır ve puan alanı kapalıdır. Puan modunda 3. amir puana katkı verir ve ağırlık hesabına dahil olur. Ağırlık toplamı her durumda %100 olmalıdır. 3. amir yoksa tablo/formda boş sütun, boş görev veya yanlış “bekliyor” statüsü görünmemelidir.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Performans Ayarları", "/settings/performance", "3. amir modu ve görünürlük")],
        "quick": ["3. amir puan verir mi?", "3. amir olmayan yerde ne görünür?", "Ağırlık toplamı nasıl olur?", "Amir zincirini anlat"],
        "priority": 94,
    },
    {
        "key": "low_performance",
        "title": "70 altı düşük performans ve Başkan/Üst Onay süreci",
        "section": "Performans Yönetimi",
        "keywords": ["70 altı", "70 alti", "düşük performans", "dusuk performans", "başkan onayı", "baskan onayi", "başkan onayları", "baskan onaylari", "uyarı", "uyari", "ikinci kez", "tekrarlayan düşük", "tekrarlayan dusuk", "işten çıkarma", "isten cikarma"],
        "answer": """BYS360’da nihai performans puanı 70’in altına düşerse sonuç doğrudan kesinleşmez ve personele normal yayın gibi açılmaz.

Zorunlu akış: değerlendirme tamamlanır; sistem nihai puanı hesaplar; nihai puan 70 altındaysa kayıt Başkan/Üst Onay sürecine alınır; Başkan/Üst Onay tamamlanmadan sonuç kesinleşmiş sayılmaz. İlk 70 altı sonuçta düşük performans uyarısı ve personel süreç kaydı oluşur. Aynı takvim yılında ikinci 70 altı sonuçta “tekrarlayan düşük performans süreci” başlatılır. Sistem otomatik idari işlem yapmazma yapmaz; yalnızca idari süreç statüsü ve yetkili onay akışı üretir.

Gerekli üst onaylardan sonra Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı ve Admin/İK nihai yayın adımı tamamlanır.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Başkan Onayları", "/performans/baskan-onaylari", "70 altı kayıtların üst onay takibi"), ("Süreç Takibi", "/performans/surec-takibi", "Performans süreç zinciri")],
        "quick": ["Başkan onayı olmadan yayınlanır mı?", "İlk 70 altı olursa ne olur?", "İkinci 70 altı olursa ne olur?", "Karne ne zaman görünür?"],
        "priority": 100,
    },
    {
        "key": "scorecard_publish",
        "title": "Karne, yayın ve görünürlük kuralları",
        "section": "Performans Yönetimi",
        "keywords": ["karne", "not karnesi", "yayın", "yayin", "karne görünür", "karne gorunur", "yayın ön onayı", "yayin on onayi", "personel ve destek", "sonuçlar ne zaman", "sonuclar ne zaman", "personel karnesi"],
        "answer": """BYS360’da personel performans sonucunu süreç tamamlanmadan göremez.

Karne/yayın kuralı: tüm değerlendirme görevleri tamamlanır; açıklama ve eşik kontrolleri yapılır; 70 altı varsa Başkan/Üst Onay tamamlanır; süreç kayıtları oluşur; Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı verir; Admin/İK nihai yayını yapar. Yayından sonra personel kendi karnesini ve yetkili olduğu kişi detayı içermeyen özetleri görebilir.

Görünürlük disiplini: personel kendi karnesini, koordinatör kendi kapsamını, grup başkanı kendi grup/üst birim kapsamını, Başkan/Admin sistemde tanımlı genel kapsamını görür.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Karne Arşivi", "/performans/gecmis-karne-arsivi", "Yayınlanmış/geçmiş karneler"), ("Yayın Onayları", "/performance/personnel-support-publish-approvals", "Yayın ön onayı")],
        "quick": ["Başkan onayı ne zaman gerekir?", "Personel neyi görebilir?", "Koordinatör neyi görür?", "Teknik statüler görünür mü?"],
        "priority": 96,
    },
    {
        "key": "explanation_rules",
        "title": "Puanlama ve açıklama zorunlulukları",
        "section": "Performans Yönetimi",
        "keywords": ["1 puan", "5 puan", "açıklama", "aciklama", "90 üstü", "90 ustu", "genel görüş", "genel gorus", "puanlama", "100 lük", "100luk", "kriter puanı", "kriter puani"],
        "answer": """Performans puanlama 1-5 kriter puanları üzerinden yürür ve sistem bu puanları 100’lük skala mantığıyla nihai başarı puanına dönüştürür.

Açıklama kuralları: 70 altı sonuçta ayrıntılı genel görüş zorunlu olmalıdır. 90 üstü sonuçta ayrıntılı genel görüş kuralı korunabilir veya sistem ayarıyla yönetilebilir. 1 ve 5 puan açıklama zorunluluğu mevcut kurallarda önemlidir; güncel toplantı kararlarıyla çakışmaması için sistem ayarına bağlanmalıdır. Kullanıcı ekranlarında “Yetkinlik” ana terimi yerine “Değerlendirme Kriterleri” kullanılmalıdır.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Puanlama Görevleri", "/performance/scoring", "Değerlendirme ekranı"), ("Performans Ayarları", "/settings/performance", "Açıklama kuralları")],
        "quick": ["70 altı açıklama zorunlu mu?", "1 ve 5 açıklama ayarı nerede?", "90 üstü ne olur?", "Kriterler nerede?"],
        "priority": 90,
    },
    {
        "key": "archive_notes_development",
        "title": "Geçmiş karne, dönem içi not ve gelişim önerisi",
        "section": "Performans Yönetimi",
        "keywords": ["geçmiş karne", "gecmis karne", "karne arşivi", "karne arsivi", "geçmiş puan", "gecmis puan", "dönem içi not", "donem ici not", "ara geri bildirim", "gelişim önerisi", "gelisim onerisi", "olumlu not", "olumsuz not"],
        "answer": """Güncel BYS360 performans yapısında sonuç yalnızca puanla kapanmaz; geçmiş, not, gelişim ve arşiv mantığıyla izlenir.

Geçmiş yıl karne/puan arşivinde eski puanlar manuel veya import yoluyla sisteme alınabilir. Personel kendi geçmişini, yönetici yetkili kapsamını görmelidir. Dönem içi notlarda olumlu/olumsuz olay, başarı, gelişim ihtiyacı veya genel gözlem tutulabilir. Bu notlar amire hatırlatma sağlar; otomatik puan üretmez. Gelişim önerisi düşük performans veya gelişim alanları için rehber not üretir.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Geçmiş Karne Arşivi", "/performans/gecmis-karne-arsivi", "Geçmiş karne/puanlar"), ("Dönem İçi Notlar", "/performance/in-period-notes", "Ara not ve geri bildirimler")],
        "quick": ["Eski puan nasıl eklenir?", "Dönem içi not puanı etkiler mi?", "Gelişim önerisi nereden yazılır?", "Personel geçmişini görebilir mi?"],
        "priority": 86,
    },
    {
        "key": "communication_survey_support",
        "title": "İletişim, anket, geri bildirim ve destek",
        "section": "İletişim ve Anket",
        "keywords": ["iletişim", "iletisim", "mesaj", "duyuru", "bildirim", "anket", "geri bildirim", "nabız", "nabiz", "destek", "yardım merkezi", "yardim merkezi", "ticket", "talep"],
        "answer": """İletişim ve Anket Yönetimi; mesajlaşma, duyuru, bildirim, anket, geri bildirim, destek talebi ve kullanıcı yönlendirme süreçlerini tek merkezde toplar.

Mesajlaşma kurum içi yazışmaları kayıtlı hale getirir. Duyuru ve bildirimler hedef kitleye gider. Anketler atanır ve katılım oranı izlenir. Geri bildirim/nabız yapıları personel görüşlerini analiz edilebilir hale getirir. Destek talepleri açılır, yanıtlanır, kapanır ve memnuniyet ile izlenir.

Asistan mesaj metni, anket cevabı veya destek talebi içeriğini göstermez; yalnızca süreç ve sayı/özet mantığıyla yönlendirir.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Destek Talepleri", "/support", "Yardım/destek ekranı"), ("Anketler", "/surveys", "Anket ekranı"), ("Mesajlar", "/messages", "Kurum içi mesajlaşma")],
        "quick": ["Destek talebi nasıl açılır?", "Anket nasıl cevaplanır?", "Duyuru kimlere görünür?", "Asistan mesajları okur mu?"],
        "priority": 88,
    },
    {
        "key": "settings_role_matrix",
        "title": "Sistem Ayarları, rol matrisi ve menü görünürlüğü",
        "section": "Sistem Ayarları",
        "keywords": ["ayarlar", "sistem ayarları", "sistem ayarlari", "rol matrisi", "menü görünürlüğü", "menu gorunurlugu", "yetki", "yetkilendirme", "kişi bazlı", "kisi bazli", "birim bazlı", "birim bazli", "modül bazlı", "modul bazli", "aç kapa", "ac kapa", "görünmüyor", "gorunmuyor", "erişim engeli"],
        "answer": """Sistem Ayarları ve Yetkilendirme Yönetimi BYS360’ın merkezi kontrol katmanıdır. Kim hangi modülü görecek, hangi işlemi yapacak, hangi güvenlik kuralı çalışacak ve hangi değişiklik loglanacak burada yönetilir.

Rol matrisi/menü görünürlüğü mantığı: canlı kapsam kontrol edilir; rol bazlı varsayılan menü yetkileri belirlenir; gerekirse kişi bazlı veya birim bazlı özel görünürlük uygulanır. Menü kapalıysa kullanıcı sol menüde sekmeyi hiç görmemelidir; yalnızca tıklayınca erişim engeli vermek yeterli değildir. URL elle yazılırsa backend route yetkisi yine veriyi korumalıdır. Ayar değişiklikleri audit log/değişiklik geçmişiyle izlenmelidir.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Sistem Ayarları", "/settings", "Merkezi ayar yönetimi"), ("Rol Matrisi", "/admin/role-matrix", "Rol/menü görünürlüğü"), ("Audit Log", "/admin/audit-logs", "Denetim kayıtları")],
        "quick": ["Menü kapalıysa ne olmalı?", "Kişi bazlı yetki nasıl çalışır?", "CAPTCHA nereden ayarlanır?", "Ayar değişikliği loglanır mı?"],
        "priority": 100,
    },
    {
        "key": "ai_decision_support",
        "title": "AI Karar Destek Merkezi ne yapar?",
        "section": "AI Karar Destek",
        "keywords": ["ai karar destek", "yapay zeka", "karar destek", "risk farkındalığı", "risk farkindaligi", "özetleme", "ozetleme", "öneri", "oneri", "ai karar verir mi", "karar verir", "redaksiyon", "maskeleme", "ai log"],
        "answer": """AI Karar Destek Merkezi, BYS360 verilerini yöneticinin daha hızlı anlamasına yardımcı olan kontrollü analiz katmanıdır. Karar veren mekanizma değildir.

Performans, personel, anket, geri bildirim, destek ve bildirim verilerini özetleyebilir; düşük performans, düşük katılım, yoğun destek talebi gibi risk alanlarına dikkat çekebilir; açık uçlu geri bildirimlerde tekrar eden temaları görünür kılabilir; yönetici için kısa karar destek notu üretebilir. İdari karar vermez, performans puanı belirlemez, insan onayı yerine geçmez, hassas veriyi maskeleme ve yetki kuralı olmadan göstermez.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("AI Karar Destek", "/ai/decision-support", "Karar destek merkezi"), ("AI Sağlık Kontrolü", "/ai/decision-support/faz1/health", "Güvenli sağlık/ilke ekranı")],
        "quick": ["AI karar verir mi?", "Hangi verileri özetler?", "Redaksiyon ne demek?", "Asistan ile AI farkı ne?"],
        "priority": 96,
    },
    {
        "key": "assistant_ai_difference",
        "title": "BYS360 Asistanı ile AI Karar Destek farkı",
        "section": "AI Karar Destek",
        "keywords": ["asistan ai farkı", "asistan ai farki", "ai karar destek farkı", "ai karar destek farki", "asistan karar destek", "asistan ne yapar", "ai ne yapar"],
        "answer": """BYS360 Asistanı ile AI Karar Destek birbirini tamamlar ama aynı şey değildir.

BYS360 Asistanı kullanıcı arayüzünde rehberlik verir, hangi işlem için hangi ekrana gidileceğini anlatır, yetki kontrollü sayı/özet ve güvenli link sunar. AI Karar Destek ise veriyi özetler, anlamlandırır, önceliklendirir ve risk farkındalığı üretir. Kısa kural: Asistan “nasıl kullanırım?” sorusuna, AI Karar Destek “bu veride neye dikkat etmeliyim?” sorusuna yardımcı olur. İkisi de idari karar vermez.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("BYS360 Asistanı Paneli", "/ai-agent/panel", "Kullanım rehberi"), ("AI Karar Destek", "/ai/decision-support", "Analiz ve özetleme")],
        "quick": ["Asistan neyi göstermez?", "AI hangi verileri kullanır?", "Yetki kontrollü özet nedir?", "Karar desteği nedir?"],
        "priority": 92,
    },
    {
        "key": "kpi_target",
        "title": "KPI ve Hedef Yönetimi",
        "section": "KPI/Hedef",
        "keywords": ["kpi", "hedef", "hedef yönetimi", "hedef yonetimi", "hedef kartı", "hedef karti", "stratejik performans", "yetkinlik kütüphanesi", "yetkinlik kutuphanesi", "öz değerlendirme", "oz degerlendirme", "dashboard", "başkan dashboard", "baskan dashboard"],
        "answer": """KPI/Hedef Yönetimi, BYS360’ın stratejik ölçüm motorudur. Bu katmanla sistem yalnızca işlem yapan yapı olmaktan çıkıp kurumu ölçen, hedefleyen ve yönetsel görünürlük sağlayan platforma dönüşür.

Temel yapılar: hedef dönemi, hedef kartı, KPI ölçüm motoru, yetkinlik kütüphanesi, öz değerlendirme ve yönetici dashboardlarıdır. Hedef kartında hedef kodu, hedef adı, sahip, kapsam, ağırlık, hedef değer, gerçekleşen değer, durum ve risk seviyesi tutulur. Öz değerlendirme otomatik puan üretmez; amire destek verisi sağlar.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("KPI Dashboard", "/performance/dashboard", "Yönetici KPI/performans görünümü"), ("Hedef Yönetimi", "/performance/targets", "Hedef kartları")],
        "quick": ["Hedef kartı nedir?", "KPI başarı oranı nasıl hesaplanır?", "Öz değerlendirme puan üretir mi?", "Başkan dashboard ne gösterir?"],
        "priority": 90,
    },
    {
        "key": "dashboard_reports",
        "title": "Dashboard, raporlar ve risk görünürlüğü",
        "section": "Raporlama",
        "keywords": ["dashboard", "rapor", "riskli personel", "risk analizi", "performans haritası", "performans haritasi", "aksatan amir", "geciken amir", "düşük performans yoğunluğu", "dusuk performans yogunlugu", "kategori ortalaması", "kategori ortalamasi", "yönetici görünürlüğü", "yonetici gorunurlugu"],
        "answer": """BYS360 dashboard ve raporları yöneticinin süreçleri tek tek aramadan görmesini sağlar.

Kalıcı görünürlük alanları: canlı performans haritası, en geciken/aksatan amirler, riskli personel analizi, düşük performans yoğunluğu, Başkan onayı bekleyenler, yayın kilidi olan karneler, dönem bazlı tamamlanma oranları, birim/kategori/grup ortalamaları ve KPI/Hedef gerçekleşme-risk haritasıdır.

Raporlarda yetki sınırı esastır: personel kişi detayı görmez; koordinatör ve grup başkanı kendi kapsamını, Başkan/Admin genel yetkiyi sistemde tanımlı ölçüde görür.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Performans Dashboard", "/performance/dashboard", "Yönetici görünürlüğü"), ("Performans Raporları", "/performance/reports", "Raporlar")],
        "quick": ["Riskli personel ne demek?", "Aksatan amir raporu nerede?", "Kategori ortalaması kimlere görünür?", "KPI dashboard nedir?"],
        "priority": 88,
    },
    {
        "key": "operations_hardening",
        "title": "Canlı operasyon sertleştirme",
        "section": "Operasyon",
        "keywords": ["canlı sertleştirme", "canli sertlestirme", "operasyon", "yük testi", "yuk testi", "performans optimizasyonu", "cache", "query", "log rotasyonu", "release", "pipeline", "1000 kullanıcı", "1000 kullanici", "büyük kullanıcı", "buyuk kullanici", "postgresql tuning"],
        "answer": """BYS360’ın modül mimarisi güçlü hale geldiği için sonraki kritik alan operasyon sertleştirmedir.

Öncelikli kontrol listesi: performans optimizasyonu ve yavaş sorgu analizi; PostgreSQL bağlantı havuzu ve tuning; dashboard ve büyük rapor yük testi; cache ve özet önbelleği; audit log yoğunluk testi; rol kaçak testi; upload güvenliği; canlı log yönetimi ve log rotasyonu; background worker/görev kuyruğu; temiz release paketi. Temiz pakete .env, .venv, yedek, log, upload ve dump dosyaları girmemelidir.

Yetki notu: {{ROLE_NOTE}}""",
        "actions": [("Sistem Sağlık", "/admin/ops", "Operasyon ve sağlık kontrolleri"), ("AI Sağlık Kontrolü", "/ai/decision-support/faz1/health", "Karar destek sağlık ekranı")],
        "quick": ["Temiz canlı paket nasıl olmalı?", "Rol kaçak testi nedir?", "Yük testi neden gerekli?", "Log rotasyonu nedir?"],
        "priority": 84,
    },
]


def _score(topic: dict[str, Any], qn: str) -> int:
    score = 0
    for kw in topic.get("keywords", []):
        nkw = _norm(kw)
        if not nkw:
            continue
        if nkw in qn:
            score += max(12, len(nkw.split()) * 8) + int(topic.get("priority", 50)) // 10
        else:
            parts = [p for p in nkw.split() if len(p) >= 3]
            if parts and all(p in qn for p in parts):
                score += 8 + len(parts) * 2
    for token in _norm(str(topic.get("title", "")) + " " + str(topic.get("section", ""))).split():
        if len(token) >= 4 and token in qn:
            score += 1
    return score


def _reply(topic: dict[str, Any], user: Any, question: str) -> dict[str, Any]:
    role = _role_from_user(user)
    answer = str(topic.get("answer", "")).strip().replace("{{ROLE_NOTE}}", _role_scope_note(role))
    return {
        "ok": True,
        "version": VERSION,
        "mode": MODE,
        "assistant_name": ASSISTANT_NAME,
        "intent": topic.get("key"),
        "topic_title": topic.get("title"),
        "section": topic.get("section"),
        "detected_role": role,
        "detected_role_label": _role_label(role),
        "question": str(question or ""),
        "answer": answer,
        "actions": [_a(*a) for a in topic.get("actions", [])],
        "quick_replies": list(topic.get("quick") or DEFAULT_QUICK_REPLIES),
        "notice": NOTICE,
        "security_notice": SECURITY_NOTICE,
        "knowledge_source": "BYS360 proje kaynakları, modül proje dosyaları, canlı omurga ve kesin performans kuralları",
        "assistant_panel_notice": "Merhaba, ben BYS360 Asistanı. BYS360’ı modül, süreç ve yetki mantığıyla adım adım anlatırım.",
    }


def _master_map_reply(user: Any, question: str) -> dict[str, Any] | None:
    qn = _norm(question)
    if any(x in qn for x in ("her sey", "herseyi", "tum bys360", "butun bys360", "kaynak", "proje kaynak", "ne biliyorsun", "neleri biliyorsun", "her seyi biliyor", "en zeki")):
        topic = {
            "key": "master_project_map",
            "title": "BYS360 proje hafızası genel haritası",
            "section": "Ana Çatı",
            "answer": """BYS360 Asistanı V3 bilgi bankası şu ana kaynak başlıklarını bilir ve öğretir:

1. Ana proje mantığı: BYS360’ın KYS’nin alternatifi değil, tamamlayıcı bütünleşik yönetim platformu olması.
2. Canlı omurga: kimlik, kullanıcı, yetki, ayarlar, audit log, personel, performans, iletişim/anket/destek, AI karar destek ve KPI/Hedef yapıları.
3. Personel Yönetimi: sicil, birim, üst birim, yönetici, kategori, organizasyon geçmişi, izin, devamsızlık ve vekâlet.
4. Performans Yönetimi: dönem, kapsam, kategori, kriter, amir zinciri, 3. amir, puanlama, 70 altı Başkan/Üst Onay, yayın ön onayı, karne, arşiv, notlar, gelişim önerisi ve raporlar.
5. Sistem Ayarları: rol matrisi, kişi/birim/rol bazlı görünürlük, modül ayarları, güvenlik, CAPTCHA, oturum, bildirim ve audit log.
6. İletişim ve Anket: mesaj, duyuru, bildirim, anket, geri bildirim, destek talebi ve raporlama.
7. AI Karar Destek: özetleme, önceliklendirme, risk farkındalığı, redaksiyon, loglama ve insan denetimli karar destek.
8. Sanal Asistan sınırları: karar vermez, puan üretmez, hassas içerik göstermez; rehberlik, güvenli özet ve yönlendirme yapar.
9. KPI/Hedef: hedef dönemleri, hedef kartları, KPI ölçüm, yetkinlik kütüphanesi, öz değerlendirme ve stratejik dashboard.
10. Operasyon sertleştirme: yük testi, rol kaçak testi, release hijyeni, log yönetimi, cache ve PostgreSQL performansı.

Bana modül adıyla veya işlem adıyla sorarsanız adım adım anlatırım. Örnek: “70 altı süreç nasıl ilerler?”, “Personel kategorisi ne işe yarar?”, “Rol matrisinden menü nasıl açılır?”, “AI Karar Destek karar verir mi?”

Yetki notu: {{ROLE_NOTE}}""",
            "actions": [("BYS360 Asistanı Paneli", "/ai-agent/panel", "Asistan paneli"), ("Asistan Bilgi Bankası", "/ai-agent/knowledge", "Bilgi bankası"), ("Sistem Ayarları", "/settings", "Ayarlar")],
            "quick": DEFAULT_QUICK_REPLIES,
        }
        return _reply(topic, user, question)
    return None


def find_bys360_master_topic(question: str) -> dict[str, Any] | None:
    qn = _norm(question)
    if not qn:
        return TOPICS[0]
    scored = sorted(((_score(topic, qn), int(topic.get("priority", 50)), topic) for topic in TOPICS), key=lambda x: (x[0], x[1]), reverse=True)
    best_score, _, best_topic = scored[0]
    return best_topic if best_score >= 10 else None


def build_bys360_assistant_master_reply(user: Any, question: str) -> dict[str, Any] | None:
    mapped = _master_map_reply(user, question or "")
    if mapped:
        return mapped
    topic = find_bys360_master_topic(question or "")
    if not topic:
        return None
    return _reply(topic, user, question)


def get_bys360_assistant_master_knowledge_index() -> list[dict[str, Any]]:
    return [
        {
            "key": t["key"],
            "title": t["title"],
            "section": t["section"],
            "keywords": list(t.get("keywords", [])[:12]),
            "actions": [{"label": a[0], "url": a[1], "description": a[2]} for a in t.get("actions", [])],
            "quick_replies": list(t.get("quick") or DEFAULT_QUICK_REPLIES),
            "priority": t.get("priority", 50),
        }
        for t in TOPICS
    ]

__all__ = ["VERSION", "MODE", "ASSISTANT_NAME", "build_bys360_assistant_master_reply", "find_bys360_master_topic", "get_bys360_assistant_master_knowledge_index"]
