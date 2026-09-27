from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

"""BYS360 Asistanı - Güncel Kullanım Kılavuzu Beyni V32.

Bu modül BYS360 Kullanım Kılavuzu Güncel v1.1 (Haziran 2026)
metnini asistanın güvenli, doğal dil anlayan rehber cevap katmanına çevirir.

Kritik sınır:
- İdari karar üretmez.
- Performans puanı, amir görüşü, mesaj/anket içeriği veya hassas kişisel veri göstermez.
- Yalnızca rehberlik, işlem adımı, doğru ekran ve yetki kontrollü genel özet mantığı sunar.
"""

VERSION = "BYS360_ASSISTANT_USAGE_MANUAL_BRAIN_V32"
SOURCE_LABEL = "BYS360 Kullanım Kılavuzu Güncel v1.1 · Haziran 2026"
NOTICE = (
    "BYS360 Asistanı idari karar vermez, performans puanı belirlemez, onay/ret işlemi yapmaz "
    "ve yetki dışı hassas verileri göstermez. Doğru ekranı, işlem sırasını ve güvenli kontrol adımlarını anlatır."
)

TR_MAP = str.maketrans({
    "ç": "c", "ğ": "g", "ı": "i", "i": "i", "ö": "o", "ş": "s", "ü": "u",
    "Ç": "c", "Ğ": "g", "İ": "i", "I": "i", "Ö": "o", "Ş": "s", "Ü": "u",
})

STOPWORDS = {
    "bir", "ve", "veya", "ile", "icin", "gibi", "nasil", "nerede", "nerden", "hangi", "ne", "nedir",
    "ben", "bana", "bunu", "su", "şu", "bu", "olarak", "mi", "mu", "mı", "mü", "var", "yok",
}


def norm(value: Any) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(TR_MAP).lower()
    text = re.sub(r"[^a-z0-9\s/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value: Any) -> set[str]:
    return {t for t in norm(value).split() if len(t) > 2 and t not in STOPWORDS}


def action(label: str, url: str, desc: str = "") -> dict[str, str]:
    return {
        "label": label,
        "title": label,
        "url": url,
        "route": url,
        "description": desc or label,
        "safety_level": "rehber_yonlendirme",
    }


@dataclass(frozen=True)
class Topic:
    key: str
    module: str
    title: str
    phrases: tuple[str, ...]
    keywords: tuple[str, ...]
    roles: tuple[str, ...]
    menu_path: str
    steps: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    actions: tuple[tuple[str, str, str], ...] = ()
    quick: tuple[str, ...] = ()
    custom_answer: str | None = None
    priority: int = 0

    @property
    def search_text(self) -> str:
        return " ".join((self.module, self.title, self.menu_path, *self.phrases, *self.keywords, *(self.custom_answer or "").split()))


WELCOME_INTRO = (
    "Ben BYS360 Asistanı’yım. BYS360 içinde doğru ekranı, işlem sırasını ve güvenli kontrol adımlarını anlatan "
    "kurumsal dijital yardımcıyım. Sorunuzu günlük cümleyle yazabilirsiniz; örneğin ‘dönem açacağım’, "
    "‘karnemi göremiyorum’, ‘rol matrisinden menü açacağım’, ‘destek talebi nasıl açılır?’ gibi."
)

TOPICS: tuple[Topic, ...] = (
    Topic(
        key="identity",
        module="BYS360 Asistanı",
        title="Asistan kimliği ve geliştirici bilgisi",
        phrases=("sen kimsin", "adın ne", "seni kim geliştirdi", "kim geliştirdi", "havva gülsen özden mi", "havva gulsen ozden mi"),
        keywords=("asistan", "geliştirdi", "gelistirdi", "havva", "gulsen", "gülsen", "ozden", "özden", "kimlik"),
        roles=("Tüm kullanıcılar",),
        menu_path="Sağ alt BYS360 Asistanı",
        steps=(
            "Asistan, BYS360 içinde kullanıcıyı doğru bilgiye ve doğru ekrana yönlendiren kurumsal yardımcıdır.",
            "Sistem kullanımı, görevler, karneler, destek, anket, ayarlar, AI Karar Destek ve KPI/Hedef konularında rehberlik eder.",
            "Geliştirici bilgisi yalnızca kullanıcı bu konuyu açıkça sorarsa cevaplanır; üst tanıtım metninde kişi adı gösterilmez.",
        ),
        warnings=("Asistan idari karar vermez; yetki dışı veri ve hassas içerik göstermez.",),
        checks=("Üst tanıtım metninde kişi adı olmamalı; ‘seni kim geliştirdi?’ sorusunda geliştirici Havva Gülsen Özden ve eş geliştirici Mustafa Bektaş cevabı verilmelidir.",),
        actions=(("Ana Sayfa", "/home", "BYS360 başlangıç ekranı"), ("Destek", "/support", "Destek ve Talepler")),
        quick=("BYS360 nedir?", "Ne yapabilirsin?", "Asistan neyi göstermez?"),
        custom_answer=(
            "Ben BYS360 Asistanı’yım. BYS360 içinde kullanıcıyı doğru ekrana yönlendirmek, işlem sırasını anlatmak "
            "ve yetki dahilindeki güvenli özetleri açıklamak için tasarlandım. BYS360 projesi Havva Gülsen Özden (geliştirici) "
            "ve Mustafa Bektaş (eş geliştirici) tarafından geliştirilmiştir; ben de bu yapının kullanıcı rehberliği katmanıyım."
        ),
        priority=100,
    ),
    Topic(
        key="bys360_overview",
        module="Genel",
        title="BYS360 nedir?",
        phrases=("bys360 nedir", "sistem nedir", "bu sistem ne işe yarar", "bys360 ne ise yarar", "ana kullanım alanları"),
        keywords=("bütünleşik", "butunlesik", "yönetim", "yonetim", "performans", "personel", "iletişim", "iletisim", "anket", "destek", "karar destek", "kpi", "hedef"),
        roles=("Tüm kullanıcılar",),
        menu_path="Ana Sayfa / Dashboard / Modüller",
        steps=(
            "BYS360, kurum içi yönetim, performans, personel, iletişim, anket, destek ve karar destek süreçlerini tek dijital omurgada toplar.",
            "Sistem yalnızca işlem yapılan yazılım değil; süreçleri kayıt altına alan, ölçen, raporlayan ve yetkiye göre görünür kılan kurumsal yönetim platformudur.",
            "Ana kullanım alanları: Performans Yönetimi, Personel Yönetimi, İletişim ve Katılım, Karar Destek, KPI/Hedef Takibi.",
        ),
        warnings=("Her kullanıcı aynı ekranları görmez; menü ve veri görünürlüğü rol, kişi, birim ve yetki kapsamına göre belirlenir.",),
        checks=("Kullanıcıya açık menüler rol matrisi, kişi bazlı yetki ve modül ayarlarıyla tutarlı olmalıdır.",),
        actions=(("Ana Sayfa", "/home", "Gün özeti"), ("Dashboard", "/dashboard", "Yönetici özetleri")),
        quick=("Roller ve yetkiler nelerdir?", "Performans modülünü anlat", "Ayarlar ne işe yarar?"),
        priority=95,
    ),
    Topic(
        key="roles_permissions",
        module="Roller ve Yetkiler",
        title="Rol, yetki ve menü görünürlüğü",
        phrases=("rol ve yetki", "hangi rol ne yapar", "menü görünmüyor", "menu gorunmuyor", "yetkim yok", "erişim engeli", "erisim engeli"),
        keywords=("personel", "amir", "koordinatör", "koordinator", "grup başkanı", "baskan", "başkan", "performans yetkilisi", "admin", "sistem yöneticisi", "menü", "menu", "rol matrisi"),
        roles=("Admin / Sistem Yöneticisi", "Yetki verilen yöneticiler", "Tüm kullanıcılar bilgi alabilir"),
        menu_path="Ayarlar > Rol Matrisi Merkezi / Menü Görünürlüğü",
        steps=(
            "Kullanıcının göreceği menüler rolüne, birimine, kişi bazlı özel yetkisine ve modül ayarlarına göre belirlenir.",
            "Rol Matrisi Merkezi’nde rol bazlı modül ve menü erişimleri kontrol edilir.",
            "Gerekirse kişi bazlı özel yetki veya birim bazlı menü profili tanımlanır.",
            "Menü görünse bile backend işlem yetkisi ayrıca kontrol edilir.",
        ),
        warnings=("Menü öğesini görememek çoğu zaman hata değildir; rolünüze veya yetki kapsamınıza kapalı olabilir.", "Yetkisiz erişimde veri gösterilmemelidir."),
        checks=("Admin/Sistem Yöneticisi kritik merkezlere erişebilmeli; personel yalnızca kendi kapsamındaki ekranları görmelidir.",),
        actions=(("Sistem Ayarları", "/settings", "Ayarlar"), ("Rol Matrisi", "/admin/role-matrix", "Rol matrisi")),
        quick=("Kişi bazlı yetki nedir?", "Birim bazlı menü profili nedir?", "URL yazınca erişim engeli neden olur?"),
        priority=94,
    ),
    Topic(
        key="login_security",
        module="Giriş ve Hesap Güvenliği",
        title="Sisteme giriş, şifre ve güvenli çıkış",
        phrases=("giriş yapamıyorum", "giris yapamiyorum", "şifremi unuttum", "sifremi unuttum", "hesap kilitlendi", "güvenli çıkış", "guvenli cikis", "ilk giriş"),
        keywords=("giriş", "giris", "captcha", "geçici şifre", "gecici sifre", "güvenlik sorusu", "guvenlik sorusu", "şifre", "sifre", "çıkış", "cikis"),
        roles=("Tüm kullanıcılar", "Admin / Sistem Yöneticisi şifre sıfırlayabilir"),
        menu_path="Giriş ekranı / Hesabım",
        steps=(
            "Kurumun BYS360 adresine gidin ve kullanıcı adı/şifre ile giriş yapın.",
            "İlk girişte geçici şifrenizi güçlü şifreyle değiştirin ve güvenlik sorunuzu belirleyin.",
            "Şifremi Unuttum bağlantısıyla kullanıcı adınızı girip güvenlik sorusunu yanıtlayın.",
            "Ortak bilgisayarda sekmeyi kapatmak yerine Güvenli Çıkış kullanın.",
        ),
        warnings=("Art arda hatalı girişlerde captcha veya geçici bekletme uygulanabilir.", "Güvenlik sorusu yanıtı bilinmiyorsa sistem yöneticisinden sıfırlama istenir."),
        checks=("Giriş sonrası rolünüze göre Ana Sayfa, Dashboard veya bekleyen görev alanına yönlenmelisiniz.",),
        actions=(("Giriş", "/login", "Giriş ekranı"), ("Hesabım", "/account", "Profil ve güvenlik")),
        quick=("Şifremi nasıl değiştiririm?", "Captcha neden çıkıyor?", "Güvenli çıkış neden önemli?"),
        priority=88,
    ),
    Topic(
        key="home_dashboard",
        module="Ana Sayfa ve Dashboard",
        title="Ana Sayfa, üst çubuk, sol menü ve yönetici özetleri",
        phrases=("ana sayfa", "anasayfa", "dashboard", "gün özeti", "gun ozeti", "hava paneli", "bildirim zili", "sol menü", "ust cubuk", "üst çubuk"),
        keywords=("hızlı erişim", "hizli erisim", "portal akışı", "portal akisi", "durum şeridi", "durum seridi", "tamamlanma oranı", "geciken değerlendirmeler", "kategori ortalaması", "kpi kartları"),
        roles=("Tüm kullanıcılar", "Yöneticiler yetki kapsamındaki grafik ve özetleri görür"),
        menu_path="Ana Sayfa / Dashboard",
        steps=(
            "Sol menü BYS360’ın ana navigasyon alanıdır; görünür başlıklar rolünüze göre değişir.",
            "Üst çubukta kurum kimliği, sayfa başlığı, bildirim zili ve hesap menüsü bulunur.",
            "Ana Sayfa gün özeti, hava paneli, hızlı erişim kartları, portal akışı ve durum şeridi sunar.",
            "Dashboard; tamamlanma oranı, geciken değerlendirmeler, düşük performans, kategori ortalaması ve KPI/Hedef kartlarını yetki kapsamına göre gösterir.",
        ),
        warnings=("Dashboarddaki sayı ve grafikler yalnızca yetki dahilindeki verilerden oluşur.", "Yetkisiz kullanıcı kişi detayı veya hassas performans içeriğine erişemez."),
        checks=("/home günlük başlangıç; /dashboard yönetici analiz ekranı olarak ayrı çalışmalıdır.",),
        actions=(("Ana Sayfa", "/home", "Gün özeti"), ("Dashboard", "/dashboard", "Yönetici özetleri"), ("Bildirimler", "/notifications", "Bildirimler")),
        quick=("Dashboard neden boş?", "Bildirim zili neyi gösterir?", "Kategori ortalaması nedir?"),
        priority=90,
    ),
    Topic(
        key="tasks_evaluation",
        module="Görevlerim ve Değerlendirme",
        title="Görevlerim ve değerlendirme formu doldurma",
        phrases=("görevlerim", "gorevlerim", "değerlendirme yap", "degerlendirme yap", "puanlama yap", "bekleyen görev", "bekleyen gorev", "form doldurma"),
        keywords=("değerlendir", "degerlendir", "1 5", "puan", "açıklama", "aciklama", "taslak", "gönder", "gonder", "amir zinciri"),
        roles=("Amir / Değerlendirici", "Performans Yetkilisi takip eder", "Personel kendi görevlerini görür"),
        menu_path="Genel > Görevlerim / Performans Yönetimi > Değerlendirme Görevleri",
        steps=(
            "Görevlerim listesinden ilgili görevin Değerlendir düğmesine tıklayın.",
            "Personel, dönem, son tarih ve görev durumunu kontrol edin.",
            "Her Değerlendirme Kriteri için 1-5 arası puan seçin.",
            "Açıklama alanı zorunluysa gerekçeyi kurumsal ve açık şekilde yazın.",
            "Yarıda bırakırsanız taslak olarak saklayın; tamamladıysanız Gönder ile sürece alın.",
        ),
        warnings=("1 ve 5 puan açıklama zorunluluğu sistem ayarına bağlıdır; 70 altı veya 90 üstü sonuçlarda ayrıntılı genel görüş ayrıca uygulanır.",),
        checks=("Gönderilen değerlendirme amir zinciri ve yayın/onay akışına göre ilerlemelidir.",),
        actions=(("Görevlerim", "/tasks", "Görev listesi"), ("Performans Görevleri", "/performance/tasks", "Performans görevleri")),
        quick=("Listede kişi yoksa ne yapmalıyım?", "1 ve 5 puan açıklaması zorunlu mu?", "Taslak nasıl kullanılır?"),
        priority=93,
    ),
    Topic(
        key="performance_period",
        module="Performans Yönetimi",
        title="Dönem Yönetimi ve dönem oluşturma",
        phrases=("dönem aç", "donem ac", "dönem nasıl açılır", "donem nasil acilir", "performans dönemi nasıl açılır", "performans donemi nasil acilir", "performans dönemi oluştur", "performans donemi olustur", "yeni dönem", "yeni donem", "2026 performans", "özel dönem", "ozel donem"),
        keywords=("dönem", "donem", "performans dönemi", "performans donemi", "dönem yönetimi", "donem yonetimi", "yıllık", "yillik", "6 aylık", "3 aylık", "aylık", "aylik", "tüm kurum", "birim", "üst birim", "kategori", "seçili personel"),
        roles=("Admin", "Sistem Yöneticisi", "Performans Yetkilisi", "Yetki verilmiş İK/personel kullanıcısı"),
        menu_path="Performans Yönetimi > Dönem Yönetimi",
        steps=(
            "Performans Yönetimi > Dönem Yönetimi ekranına girin.",
            "Yeni Dönem Oluştur seçeneğiyle dönem adını, türünü ve tarih aralığını belirleyin.",
            "Kapsam tipini seçin: tüm kurum, birim, üst birim, kategori/grup veya seçili personel.",
            "Aynı personel için aynı tarih aralığında çakışan dönem olup olmadığını kontrol edin.",
            "Dönem kaydı sonrası kriter, ağırlık ve görev üretimi adımlarına geçin.",
        ),
        warnings=("Dönem oluşturmak tek başına değerlendirmeyi başlatmaz; kriter, ağırlık ve görev üretimi de tamamlanmalıdır.",),
        checks=("Dönem listede görünmeli; kapsam, tarih ve aktiflik bilgileri doğru olmalıdır.",),
        actions=(("Dönem Yönetimi", "/performance/periods", "Performans dönemleri"), ("Görev Üretimi", "/performance/assignments", "Görev üretimi")),
        quick=("Kategoriye özel dönem nasıl açılır?", "Dönemden sonra ne yapılır?", "Çakışan dönem ne demek?"),
        priority=130,
    ),
    Topic(
        key="performance_rules",
        module="Performans Yönetimi",
        title="Değerlendirme Kriterleri, amir zinciri, 3. amir ve karne",
        phrases=("değerlendirme kriterleri", "degerlendirme kriterleri", "amir zinciri", "görev üretimi", "gorev uretimi", "3. amir", "üçüncü amir", "ucuncu amir", "karne", "arşiv", "arsiv"),
        keywords=("kriter", "sorular", "puan modu", "yorum modu", "ağırlık", "agirlik", "100", "geçmiş yıl", "gecmis yil", "gelişim önerisi", "gelisim onerisi"),
        roles=("Admin", "Performans Yetkilisi", "Amir", "Personel yayın sonrası kendi karnesini görür"),
        menu_path="Performans Yönetimi > Kriterler / Görev Üretimi / Karne ve Arşiv",
        steps=(
            "Değerlendirme Kriterleri ekranında aktif kriterleri kontrol edin; aktif dönemde kullanılan kriterleri silmeyin, gerekirse pasife alın.",
            "Personel, birim, unvan, yönetici, izin ve vekâlet verilerini doğrulayın.",
            "Hiyerarşi Atamaları ekranında değerlendirici-değerlendirilen ilişkilerini kontrol edin.",
            "Görev Üretimi ekranında dönem seçerek gerçek görevleri oluşturun.",
            "3. amir zorunlu değildir; yorum modundaysa puan alanı kapalı, puan modundaysa ağırlık hesabına dahildir.",
            "Karne, yayın tamamlandıktan sonra yetki sınırına göre görünür; geçmiş yıl puanları arşivden izlenir.",
        ),
        warnings=("Toplam ağırlık her durumda %100 olmalıdır.", "Personel karnesini yalnızca yayın tamamlandıktan sonra görür."),
        checks=("Sahte bekleme, eksik amir veya yanlış kapsam varsa personel/organizasyon verisi düzeltilmelidir.",),
        actions=(("Kriterler", "/performance/criteria", "Değerlendirme kriterleri"), ("Karne", "/performance/scorecard", "Karne"), ("Arşiv", "/performance/archive", "Geçmiş karneler")),
        quick=("3. amir zorunlu mu?", "Karne ne zaman görünür?", "KPI otomatik puan üretir mi?"),
        priority=94,
    ),
    Topic(
        key="low_performance_approval",
        module="Düşük Performans ve Başkan/Üst Onay",
        title="70 altı süreç, Başkan/Üst Onay ve yayın kilidi",
        phrases=("70 altı", "70 alti", "düşük performans", "dusuk performans", "başkan onayı", "baskan onayi", "üst onay", "ust onay", "yayın kilidi", "yayin kilidi", "başkan/üst onay bekliyor"),
        keywords=("nihai puan", "ik admin", "ön kontrol", "onay", "iade", "yayın ön onayı", "uyarı", "tekrarlayan düşük performans", "karne incelemesi"),
        roles=("Başkan / Üst Yönetim", "İK/Admin", "Performans Yetkilisi", "Personel ve Destek Hizmetleri Grup Başkanı"),
        menu_path="Performans Yönetimi > Başkan/Üst Onay / Yayın Ön Onayı",
        steps=(
            "Değerlendirme tamamlanır ve nihai puan hesaplanır.",
            "Puan 70 altındaysa kayıt Başkan/Üst Onay Bekliyor durumuna alınır.",
            "İK/Admin veya performans yetkilisi ön kontrol yapar.",
            "Başkan/Üst Onay ekranında karne ve gerekçeler incelenir.",
            "Onay veya iade yapılır; sonuç yayın kilidinde kalır.",
            "Gerekli onaylar tamamlanınca Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayına düşer.",
            "Final yayın sonrası karne personele açılır ve personel geçmişine kayıt düşer.",
        ),
        warnings=("70 altı sonuç, Başkan/Üst Onay ve yayın ön onayı tamamlanmadan personele yayınlanmış sonuç olarak gösterilmez.", "Sistem otomatik işten çıkarma veya pasife alma yapmaz; nihai idari işlem insan onayıyla yürür."),
        checks=("Karne inceleme ekranında personel, dönem, nihai puan, kriter bazlı puanlar, amir görüşleri, gerekçe, süreç geçmişi ve onay/iade alanı bulunmalıdır.",),
        actions=(("Başkan/Üst Onay", "/performance/president-approvals", "Düşük performans onayları"), ("Yayın Ön Onayı", "/performance/publish-preapproval", "Final yayın kontrolü")),
        quick=("Birinci düşük performans ne olur?", "İkinci 70 altı ne anlama gelir?", "Başkan onayı olmadan karne açılır mı?"),
        priority=100,
    ),
    Topic(
        key="personnel_management",
        module="Personel Yönetimi",
        title="Personel ekleme, kategori, birim, izin ve vekâlet etkisi",
        phrases=("personel ekle", "yeni personel", "sicil", "personel kartı", "personel karti", "kategori seçimi", "kategori secimi", "birim değişikliği", "birim degisikligi"),
        keywords=("sicil numarası", "ad soyad", "unvan", "görev", "gorev", "birim", "üst birim", "ust birim", "yönetici", "yonetici", "güvenlik", "temizlik", "idari personel", "teknik personel", "deneme süreli"),
        roles=("Admin", "Sistem Yöneticisi", "Personel Yönetimi yetkilisi", "Yetki verilmiş İK/personel kullanıcısı"),
        menu_path="Personel Yönetimi > Personel Listesi / Personel Ekle",
        steps=(
            "Personel Yönetimi > Personel Listesi veya Personel Ekle ekranına girin.",
            "Sicil numarası, ad, soyad, unvan, görev, birim, üst birim ve yönetici bilgilerini girin.",
            "Gerekliyse kategori/grup seçimini yapın: Güvenlik, Temizlik, İdari Personel, Teknik Personel, Deneme Süreli Personel veya Diğer.",
            "Kullanıcı hesabı, rol ve menü görünürlüğünü kontrol edin.",
            "Kaydettikten sonra personelin listede ve ilgili raporlarda göründüğünü kontrol edin.",
        ),
        warnings=("Personel verisi hatalıysa performans görevleri, bildirimler, yetkiler ve raporlar da hatalı üretilebilir.",),
        checks=("Birim, görev veya yönetici değişikliği performans amir zincirini etkileyebilir; izinli amir için vekâlet kontrol edilmelidir.",),
        actions=(("Personel Listesi", "/personnel", "Personel listesi"), ("Personel Ekle", "/personnel/create", "Yeni personel")),
        quick=("Personel kategorisi neden önemli?", "Vekâlet performansı etkiler mi?", "Sicil no neden kullanılıyor?"),
        priority=96,
    ),
    Topic(
        key="support",
        module="Destek ve Talepler",
        title="Destek talebi açma ve takip",
        phrases=("destek talebi", "talep aç", "talep ac", "hata bildir", "yardım", "yardim", "arıza", "ariza", "geliştirme önerisi", "gelistirme onerisi"),
        keywords=("kategori", "konu", "açıklama", "aciklama", "ekran görüntüsü", "ekran goruntusu", "açık", "islemde", "yanıtlandı", "kapandı"),
        roles=("Tüm kullanıcılar", "Destek yetkilileri", "Admin"),
        menu_path="Destek ve Talepler > Yeni Talep Aç",
        steps=(
            "Destek ve Talepler > Yeni Talep Aç ekranına girin.",
            "Kategori, konu ve açıklama alanlarını doldurun.",
            "Varsa ekran görüntüsü veya ek belge yükleyin.",
            "Kaydet/Gönder ile talebi oluşturun.",
            "Talep durumunu Açık, İşlemde, Yanıtlandı veya Kapandı gibi statülerden takip edin.",
        ),
        warnings=("Aynı konu için mükerrer talep açmayın; mevcut talep üzerinden cevap yazın.", "Ekran görüntüsünde kişisel/hassas veri varsa paylaşmadan önce gizleyin."),
        checks=("Talebe ekran görüntüsü, işlem adımı ve tarih/saat bilgisi eklemek çözümü hızlandırır.",),
        actions=(("Yeni Talep Aç", "/support/new", "Destek talebi"), ("Taleplerim", "/support", "Talep listesi")),
        quick=("Acil yetki talebi nasıl iletilir?", "Talep durumları ne demek?", "Teknik hata kodu görürsem ne yapmalıyım?"),
        priority=93,
    ),
    Topic(
        key="portal_press",
        module="Kurumsal Portal ve Basın Haberleri",
        title="Portal, duyuru ve Basında Tarihi Alan",
        phrases=("kurumsal portal", "portal", "basında tarihi alan", "basinda tarihi alan", "haber", "hero alanı", "hero alani", "duyuru yayını", "duyuru yayin"),
        keywords=("duyuru", "kurum içi paylaşım", "kurum ici paylasim", "haber", "yayın", "yayin", "moderasyon", "tarihi alan", "vitrin"),
        roles=("Tüm kullanıcılar yayınlanan içeriği görebilir", "Yetkili roller içerik oluşturabilir/düzenleyebilir"),
        menu_path="Kurumsal Portal / Basında Tarihi Alan",
        steps=(
            "Portal alanında yayınlanan duyuru ve portal içeriklerini okuyabilirsiniz.",
            "Yetkili roller yeni içerik oluşturabilir, düzenleyebilir veya yayından kaldırabilir.",
            "Basında Tarihi Alan bölümünde yalnızca Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı ile ilgili haberler vitrine taşınmalıdır.",
        ),
        warnings=("Tarihi Alan ile ilgisi olmayan haberler kurumsal vitrin/anasayfa hero içeriği olarak gösterilmemelidir.", "Canlıda kapalı portal sekmeleri kılavuzda aktif ekran gibi anlatılmamalıdır."),
        checks=("Yayın yetkisi, içerik ilgisi ve moderasyon durumu kontrol edilmelidir.",),
        actions=(("Portal", "/portal", "Kurumsal portal"), ("Basında Tarihi Alan", "/portal/press-news", "Basın haberleri")),
        quick=("Portal sekmeleri neden görünmüyor?", "Haber hero alanına nasıl çıkar?", "Uygunsuz içerik ne olur?"),
        priority=82,
    ),
    Topic(
        key="communication_survey_feedback",
        module="İletişim, Anket ve Geri Bildirim",
        title="Mesaj, duyuru, anket, nabız ve geri bildirim",
        phrases=("mesaj", "duyuru", "anket", "nabız", "nabiz", "geri bildirim", "popup duyuru", "günlük hava postası", "gunluk hava postasi"),
        keywords=("mesajlaşma", "mesajlasma", "hedef kitle", "görülme bilgisi", "gorulme bilgisi", "kampanya", "aksiyon planı", "aksiyon plani", "katılım", "katilim"),
        roles=("Personel", "Yöneticiler", "Yetkili birimler", "Admin / Sistem Yöneticisi"),
        menu_path="İletişim ve Anket Yönetimi",
        steps=(
            "Mesajlar bölümünde kullanıcılar arasında kurum içi birebir veya grup temelli mesajlaşma yapılır.",
            "Duyurular yetkili kullanıcılar tarafından hedef kitleye yayınlanır.",
            "Popup duyurular giriş sonrası açılır pencere olarak gösterilebilir ve görülme bilgisi raporlanabilir.",
            "Anketler, nabız yoklaması ve geri bildirim kampanyaları kurum içi görüş ve memnuniyet ölçümü için kullanılır.",
            "Geri bildirim sonuçları aksiyon planına bağlanabilir.",
        ),
        warnings=("Asistan mesaj içeriği, anket cevabı veya kişisel geri bildirim metnini doğrudan göstermez.",),
        checks=("Kullanıcı yalnızca kendisine atanan veya yetki kapsamındaki anket/duyuru/geri bildirim kayıtlarını görmelidir.",),
        actions=(("Mesajlar", "/messages", "Mesajlar"), ("Duyurular", "/announcements", "Duyurular"), ("Anketler", "/surveys", "Anketler"), ("Geri Bildirim", "/communication/feedback", "Geri bildirim")),
        quick=("Nabız yoklaması nedir?", "Popup duyuru nedir?", "Anket sonucunu kim görür?"),
        priority=90,
    ),
    Topic(
        key="assistant_safety",
        module="BYS360 Asistanı",
        title="Asistan ne yapar ve neyi göstermez?",
        phrases=("asistan ne yapar", "asistan yanıt vermiyor", "asistan neyi göstermez", "asistan hassas veri", "asistan karar verir mi", "karnemi nereden görürüm"),
        keywords=("doğru ekran", "dogru ekran", "sık sorulan", "sik sorulan", "güvenli bağlantı", "guvenli baglanti", "özet", "yetki", "idari karar", "performans puanı", "amir görüşü"),
        roles=("Tüm kullanıcılar",),
        menu_path="Sağ alt BYS360 Asistanı / AI Agent API",
        steps=(
            "Asistan sistem kullanımıyla ilgili sorulara cevap verir: ‘Karnemi nereden görürüm?’, ‘Dönem nasıl açılır?’ gibi.",
            "İlgili ekrana güvenli bağlantı veya yönlendirme kartı sunar.",
            "Bekleyen görev, okunmamış bildirim, açık destek talebi veya yanıt bekleyen anket sayısı gibi genel özetleri gösterebilir.",
            "Teknik/geliştirici dili yerine sade ve kurumsal Türkçe kullanır.",
        ),
        warnings=("Asistan idari karar üretmez, işlem tesis etmez, performans puanı/amir görüşü/mesaj içeriği/anket cevabı/hassas kişisel veri göstermez.", "Yetkiniz olmayan veriyi asistana sorsanız da göremezsiniz."),
        checks=("Asistan yanıt vermiyorsa sayfayı yenileyin, oturumu kontrol edin; sorun sürerse destek talebi açın.",),
        actions=(("BYS360 Asistanı", "/ai-agent/panel", "Asistan paneli"), ("Destek", "/support/new", "Destek talebi")),
        quick=("Dönem nasıl açılır?", "Karnemi neden göremiyorum?", "Yetkim yoksa ne olur?"),
        priority=96,
    ),
    Topic(
        key="ai_decision_support",
        module="AI Karar Destek Merkezi",
        title="AI Karar Destek ne yapar?",
        phrases=("ai karar destek", "yapay zeka", "yapay zekâ", "ai çıktı", "ai cikti", "yönetici brifingi", "yonetici brifingi", "risk farkındalığı", "risk farkindaligi"),
        keywords=("özetleme", "ozetleme", "önceliklendirme", "onceliklendirme", "rapor yorumu", "redaksiyon", "maskeleme", "inceleme kuyruğu", "nihai karar", "insan denetimi"),
        roles=("Başkan / Üst Yönetim", "Yöneticiler", "AI Karar Destek yetkilileri", "Admin"),
        menu_path="AI Karar Destek Merkezi",
        steps=(
            "AI Karar Destek yöneticilere veri özetleme, önceliklendirme, risk farkındalığı, rapor yorumu ve karar destek notları sunar.",
            "Performans, anket, geri bildirim ve destek verilerini güvenli özetler halinde anlamlandırır.",
            "Düşük katılım, geciken görev veya yoğun destek talebi gibi riskli alanları görünür kılar.",
            "AI çıktıları inceleme kuyruğu ve geri bildirim süreciyle kontrol edilir.",
        ),
        warnings=("AI hiçbir durumda tek başına personel, performans, disiplin, idari süreç veya yayın kararı vermez.", "AI çıktıları öneri, analiz veya dikkat notu niteliğindedir."),
        checks=("Redaksiyon, hassas veri maskeleme, loglama ve insan onayı kontrolleri açık olmalıdır.",),
        actions=(("AI Karar Destek", "/ai-agent/panel", "AI destek paneli"), ("Güvenlik Politikası", "/ai-agent/api/security-policy", "AI güvenlik sınırları")),
        quick=("AI karar verir mi?", "Redaksiyon nedir?", "Yönetici brifingi ne içerir?"),
        priority=93,
    ),
    Topic(
        key="account_settings",
        module="Hesabım, Ayarlar ve Yetkilendirme",
        title="Hesabım, sistem ayarları, rol matrisi ve audit log",
        phrases=("hesabım", "hesabim", "ayarlar", "sistem ayarları", "sistem ayarlari", "rol matrisi", "modül ayarları", "modul ayarlari", "audit log", "sağlık kontrolü", "saglik kontrolu"),
        keywords=("profil", "şifre değiştirme", "sifre degistirme", "güvenlik sorusu", "bildirim tercihleri", "kişi bazlı", "kisi bazli", "birim bazlı", "birim bazli", "modül", "menu görünürlüğü", "menü görünürlüğü"),
        roles=("Tüm kullanıcılar kendi hesabını yönetir", "Admin / Sistem Yöneticisi ayar ve yetki yönetir"),
        menu_path="Hesabım / Ayarlar > Rol Matrisi Merkezi / Sistem Sağlık Kontrolü",
        steps=(
            "Hesabım bölümünde profil, şifre, güvenlik sorusu ve bildirim tercihleri yönetilir.",
            "Rol Matrisi Merkezi’nde hangi rolün hangi modül, menü ve işlemlere erişeceği yönetilir.",
            "Kişi bazlı yetki standart rol dışında geçici veya özel görünürlük tanımlar.",
            "Birim bazlı menü profili bazı menüleri sadece ilgili birime veya yönetim kapsamına açabilir.",
            "Modül ayarları performans, iletişim, AI, bildirim ve destek ayarlarını merkezi şekilde yönetir.",
            "Audit log kritik ayar, yetki ve sistem değişikliklerini kim-ne zaman bilgisiyle izler.",
        ),
        warnings=("Menü görünürlüğü yalnızca tasarım tercihi değildir; güvenlik ve süreç kontrol unsurudur.", "Menü görünse bile işlem yetkisi ayrıca kontrol edilir."),
        checks=("Ayar değişikliği sonrası rol matrisi, menü görünürlüğü, backend yetki kontrolü ve audit log kaydı kontrol edilmelidir.",),
        actions=(("Hesabım", "/account", "Profil"), ("Ayarlar", "/settings", "Sistem ayarları"), ("Rol Matrisi", "/admin/role-matrix", "Rol matrisi")),
        quick=("Menü görünmüyor ne yapmalıyım?", "Kişi bazlı yetki nedir?", "Audit log ne işe yarar?"),
        priority=96,
    ),
    Topic(
        key="mobile_pwa_native",
        module="Mobil Web / PWA ve Native Mobil",
        title="Mobil kullanım, PWA ve Flutter native uygulama",
        phrases=("mobil", "pwa", "ana ekrana ekle", "telefonda kullan", "native mobil", "flutter", "android", "ios", "safari", "chrome"),
        keywords=("mobil web", "webview", "önbellek", "onbellek", "beyaz ekran", "sol menü", "hamburger", "api", "dashboard", "bildirim", "destek", "anket"),
        roles=("Tüm kullanıcılar", "Mobil geliştirme yetkilileri"),
        menu_path="Mobil tarayıcı / PWA / Native BYS360 Mobile",
        steps=(
            "Android Chrome’da BYS360 adresini açın ve tarayıcı menüsünden Ana ekrana ekle seçeneğini kullanın.",
            "iOS Safari’de Paylaş simgesi > Ana Ekrana Ekle seçeneğini kullanın.",
            "PWA tam ekran uygulama hissi verir; mobilde sol menü ☰ simgesiyle açılır.",
            "Ekran kayması veya beyaz ekran yaşarsanız tarayıcı/PWA önbelleğini temizleyip yeniden giriş yapın.",
            "Flutter tabanlı native mobil uygulama WebView yerine API üzerinden veri alan ayrı mobil yapı olacaktır.",
        ),
        warnings=("Bu kılavuz mevcut web/PWA kullanımını esas alır; native BYS360 Mobile yayınlanınca mobil ekran adımları ayrıca güncellenmelidir.",),
        checks=("Mobilde login, dashboard, bildirim, destek, anket, asistan ve performans ekranları ayrı ayrı test edilmelidir.",),
        actions=(("Ana Sayfa", "/home", "PWA başlangıç"), ("Destek", "/support/new", "Mobil sorun bildir")),
        quick=("PWA önbelleği nasıl temizlenir?", "Native mobil ne demek?", "Mobilde sol menü nerede?"),
        priority=84,
    ),
    Topic(
        key="faq_troubleshooting",
        module="Sık Karşılaşılan Sorunlar",
        title="Sık sorunlar ve çözüm yolları",
        phrases=("giriş yapamıyorum", "menu görünmüyor", "menü görünmüyor", "url yazınca erişim engeli", "görevlerimde kişi yok", "karnemi göremiyorum", "bildirim gelmiyor", "asistan yanıt vermiyor", "sayfa hatalı", "yarım görünüyor"),
        keywords=("hesap kilitlendi", "captcha", "yetki", "hiyerarşi", "hiyerarsi", "dönem kapsamı", "donem kapsami", "görev üretimi", "gorev uretimi", "başkan üst onay", "yayın ön onayı", "ctrl f5", "önbellek"),
        roles=("Tüm kullanıcılar", "Admin / Sistem Yöneticisi sorun çözümünde destek verir"),
        menu_path="Destek ve Talepler / İlgili modül ekranı",
        steps=(
            "Giriş sorunu varsa captcha/geçici bekletme, Şifremi Unuttum ve şifre sıfırlama akışı kontrol edilir.",
            "Menü görünmüyorsa rol, birim veya kişi bazlı yetki kapalı olabilir; sistem yöneticisine başvurun.",
            "Görevlerimde beklenen kişi yoksa hiyerarşi ataması, dönem kapsamı veya görev üretimi kontrol edilir.",
            "Karne görünmüyorsa süreç, onaylar ve yayın işlemi tamamlanmamış olabilir.",
            "Bildirim gelmiyorsa bildirimler sayfası ve tarayıcı/site izinleri kontrol edilir.",
            "Sayfa hatalı görünüyorsa Ctrl+F5 ile önbelleği yenileyin; mobilde PWA önbelleğini temizleyin.",
        ),
        warnings=("Sorun sürerse ekran görüntüsü, işlem adımı ve tarih/saat bilgisiyle destek talebi açın.",),
        checks=("Yetki, oturum, dönem kapsamı, görev üretimi, yayın/onay ve önbellek adımları sırayla kontrol edilmelidir.",),
        actions=(("Destek Talebi Aç", "/support/new", "Sorun bildir"), ("Bildirimler", "/notifications", "Bildirimler"), ("Görevlerim", "/tasks", "Görev listesi")),
        quick=("Başkan/Üst Onay Bekliyor ne demek?", "Yayın ön onayı bekliyor ne demek?", "Asistan yanıt vermiyor ne yapmalıyım?"),
        priority=92,
    ),
)

# Sık kısa sorular için doğrudan niyet eşleme.
ALIAS_TO_TOPIC: tuple[tuple[tuple[str, ...], str], ...] = (
    (("karnemi nereden gorurum", "karne nerede", "karnemi goremiyorum", "karnem yok"), "performance_rules"),
    (("baskan ust onay bekliyor ne demek", "baskan onay bekliyor", "ust onay bekliyor"), "low_performance_approval"),
    (("yayin on onayi bekliyor", "yayin onay bekliyor", "yayın ön onayı bekliyor"), "low_performance_approval"),
    (("url yazinca erisim engeli", "erisim yetkiniz bulunmamaktadir", "yetkim bulunmuyor"), "roles_permissions"),
    (("asistan yanit vermiyor", "asistan cevap vermiyor", "asistan acilmiyor"), "assistant_safety"),
    (("bildirim gelmiyor", "bildirim yok"), "faq_troubleshooting"),
    (("ai karar verir mi", "yapay zeka karar verir mi"), "ai_decision_support"),
    (("native mobil nedir", "flutter native nedir", "pwa nedir"), "mobile_pwa_native"),
)


def _role_note(user: Any) -> str:
    role = ""
    for attr in ("role_name", "role", "user_role", "profile_role", "title"):
        value = getattr(user, attr, None)
        if value:
            role = str(value)
            break
    if role:
        return f"Mevcut rolünüz: {role}. Menü ve veri görünürlüğü rol, kişi, birim ve yetki kapsamına göre değişebilir."
    return "Menü ve veri görünürlüğü rol, kişi, birim ve yetki kapsamına göre değişebilir."


def _render_list(items: Iterable[str], numbered: bool = False) -> str:
    lines: list[str] = []
    for idx, item in enumerate(items, start=1):
        if numbered:
            lines.append(f"{idx}. {item}")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _topic_by_key(key: str) -> Topic | None:
    for topic in TOPICS:
        if topic.key == key:
            return topic
    return None


def _match_alias(q_norm: str) -> Topic | None:
    for aliases, key in ALIAS_TO_TOPIC:
        if any(norm(alias) in q_norm for alias in aliases):
            return _topic_by_key(key)
    return None


def _score_topic(topic: Topic, question: str, q_norm: str, q_tokens: set[str]) -> int:
    score = topic.priority
    for phrase in topic.phrases:
        p = norm(phrase)
        if p and p in q_norm:
            score += 70 + min(len(p), 40)
    for keyword in topic.keywords:
        k = norm(keyword)
        if not k:
            continue
        if k in q_norm:
            score += 18
    topic_tokens = tokens(topic.search_text)
    overlap = q_tokens & topic_tokens
    score += len(overlap) * 6
    # Soru bir modül adını açıkça içeriyorsa küçük destek.
    if norm(topic.module) and norm(topic.module) in q_norm:
        score += 20
    return score


def find_best_topic(question: str) -> Topic | None:
    q_norm = norm(question)
    if not q_norm:
        return _topic_by_key("assistant_safety")
    alias = _match_alias(q_norm)
    if alias:
        return alias
    q_tokens = tokens(q_norm)
    best_topic = None
    best_score = -1
    for topic in TOPICS:
        s = _score_topic(topic, question, q_norm, q_tokens)
        if s > best_score:
            best_topic = topic
            best_score = s
    # Çok ilgisiz bir soru ise BYS360 dışına taşmamak için genel yardım verilir.
    if best_score < 25:
        return None
    return best_topic


def _render_topic_answer(topic: Topic, user: Any, question: str) -> str:
    role_note = _role_note(user)
    parts: list[str] = []
    parts.append(f"Anladım. Bu konu **{topic.module}** içindedir: **{topic.title}**.")
    if topic.custom_answer:
        parts.append(topic.custom_answer)
    parts.append("\n**Kim yapabilir?**")
    parts.append(_render_list(topic.roles))
    parts.append("\n**Adım adım:**")
    parts.append(_render_list(topic.steps, numbered=True))
    if topic.warnings:
        parts.append("\n**Dikkat:**")
        parts.append(_render_list(topic.warnings))
    if topic.checks:
        parts.append("\n**Kontrol:**")
        parts.append(_render_list(topic.checks))
    parts.append(f"\n**Yetki notu:** {role_note}")
    parts.append(f"\n**Kaynak:** {SOURCE_LABEL}")
    return "\n".join(parts)


def _fallback_answer(user: Any, question: str) -> str:
    role_note = _role_note(user)
    return (
        "Sorunuzu BYS360 kullanım rehberi kapsamında yorumladım; ancak hangi ekranı kastettiğiniz net değil. "
        "Bana işlemi günlük dille yazabilirsiniz: ‘personel ekleyeceğim’, ‘performans dönemi açacağım’, "
        "‘menü görünmüyor’, ‘karnemi göremiyorum’, ‘destek talebi açacağım’, ‘AI karar destek ne yapar?’ gibi.\n\n"
        "Ben BYS360 sınırları içinde doğru modülü, gerekli yetkiyi, işlem sırasını, dikkat edilmesi gereken güvenlik/onay noktasını "
        "ve son kontrol adımını anlatırım.\n\n"
        f"**Yetki notu:** {role_note}\n\n**Kaynak:** {SOURCE_LABEL}"
    )


def _payload(topic: Topic | None, answer_text: str) -> dict[str, Any]:
    actions = []
    quick = [
        "Performans dönemi nasıl açılır?",
        "Karnemi neden göremiyorum?",
        "Rol matrisinden menü nasıl açılır?",
        "Destek talebi nasıl açılır?",
    ]
    if topic:
        actions = [action(label, url, desc) for label, url, desc in topic.actions]
        if topic.quick:
            quick = list(topic.quick)
    if not actions:
        actions = [
            action("Ana Sayfa", "/home", "BYS360 ana sayfası"),
            action("Destek ve Talepler", "/support", "Yardım ve destek"),
            action("Ayarlar", "/settings", "Yetki ve ayarlar"),
        ]
    return {
        "ok": True,
        "version": VERSION,
        "mode": "Güncel kullanım kılavuzu tabanlı doğal dil rehberliği",
        "intent": topic.key if topic else "usage_manual_general_help",
        "assistant_name": "BYS360 Asistanı",
        "answer": answer_text,
        "actions": actions,
        "suggested_actions": actions,
        "quick_replies": quick,
        "notice": NOTICE,
        "source": SOURCE_LABEL,
        "safety_level": "rehber_yonlendirme",
    }


def build_bys360_assistant_usage_manual_reply_v32(
    user: Any,
    question: str,
    legacy_builder: Callable[..., dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Güncel kullanım kılavuzu tabanlı cevap üretir.

    BYS360 dışı ve çok ilgisiz sorularda da asistanın sınırını koruyan genel
    rehberlik döndürür. Bu davranış, sağ alt asistanın boş kalmasını engeller.
    """
    q = question or ""
    q_norm = norm(q)
    if not q_norm:
        return _payload(_topic_by_key("assistant_safety"), WELCOME_INTRO + "\n\n" + NOTICE + f"\n\n**Kaynak:** {SOURCE_LABEL}")

    topic = find_best_topic(q)
    if topic:
        return _payload(topic, _render_topic_answer(topic, user, q))

    # Eski motor daha iyi cevap üretebilecekse deneriz; ama ham hata veya boş dönüşte genel kılavuz cevabı verilir.
    if callable(legacy_builder):
        try:
            legacy = legacy_builder(user, question, context=context)
        except TypeError:
            try:
                legacy = legacy_builder(user, question)
            except Exception:
                legacy = None
        except Exception:
            legacy = None
        if isinstance(legacy, dict) and legacy.get("answer") and "güvenli mod" not in str(legacy.get("answer", "")).lower():
            legacy.setdefault("source", SOURCE_LABEL)
            legacy.setdefault("notice", NOTICE)
            return legacy

    return _payload(None, _fallback_answer(user, q))
