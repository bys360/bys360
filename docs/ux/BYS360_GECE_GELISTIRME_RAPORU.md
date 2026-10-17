# BYS360 GECE GELİŞTİRME RAPORU

Gece çalışması: 16–17 Ekim 2026. Son güncelleme: 17 Ekim 2026, 01:55 UTC (04:55 TSİ) — CI sonuçları geldikçe güncellenir. Görsel kanıt: https://claude.ai/artifact/VgkCUVna2ooZnmvEoW8HPc
Kapsam ve yetki: yalnız Draft PR; merge, canlıya geçiş, gerçek veri ve gerçek kullanıcı hesabı yok. Bütün yerel testler sahte kullanıcı ve sahte veriyle, geçici SQLite veritabanında.

## 1. Kaç ekran bulundu?

- **393 GET ekran rotası**, **289 farklı şablon** (depoda toplam 428 `.html`; kalanlar parça/ortak veya kullanılmayan dosyalar). Uygulama açılarak çıkarıldı: `docs/ux/BYS360_EKRAN_ENVANTERI.csv`.
- En büyük aileler: Performans Yönetimi 180, İletişim ve Anket 61, Sistem ayarları/kullanıcı/rol 44, Personel 35, Destek 14.

## 2. Kaç ekran incelendi?

- **Derinlemesine (kod + tarayıcı + rol):** Destek ailesinin 13 rotası / 10 şablonu — Yeni Talep Aç, Taleplerim, Bana Atananlar, Tüm Talepler, Talep Detayı, Yardım Merkezi, rehber makale / kategori / rol / arama, rehber formu (yeni/düzenle), destek kurulumu — ve her sayfada açılan **BYS360 Asistanı** bileşeni.
- **Otomatik tarama:** 393 rotanın tamamı envantere girdi (modül, şablon, menü anahtarı, erişim dekoratörleri, durum); pilot dışındaki 326 dosyada **1.796 aday İngilizce görünür metin** listelendi (`docs/ux/BYS360_INGILIZCE_ARAYUZ_ADAY_ENVANTERI.csv`, elle ayıklama gerekir).

## 3. Kaç ekran gerçekten geliştirildi?

**10 şablon / 13 rota + 1 ortak bileşen:**

| Ekran | PR |
|---|---|
| Destek → Yeni Talep Aç (`/support/new`) — pilot, görsel onay verildi | #75 |
| Destek → Taleplerim / Bana Atananlar / Tüm Talepler (`support/list.html`) | #77 |
| Destek → Talep Detayı (`/support/<id>`) | #79 |
| Destek → Yardım Merkezi (`/support`) | #80 |
| Destek → Rehber makale, kategori, rol yolu, arama (`/support/help/*`) | #81 |
| Destek → Rehber formu (yeni/düzenle) ve Destek kurulumu (yönetici) | #82 |
| BYS360 Asistanı (her sayfa, mobil) | #76 |

## 4. Kaç ekran otomatik testlerden geçti?

Yerel (sahte veri) — **hepsi geçti, 0 kaldı**:

| PR | İlgili test koşusu | Tarayıcı (Playwright + axe, zorlayıcı CSP) |
|---|---|---|
| #75 | pilot + CSP + ratchet sabitleri; CI `e23ddff1`: 4 kaçmış sabit → `5531f4a9` ile düzeltildi | 27/27 axe |
| #76 | yeni 8 test (7'si tabanda kırmızı, dalda yeşil) | klavye/odak/taşma ölçümleri, axe 0 kritik/ciddi |
| #77 | 707 geçti (+ `bf467aab` sonrası dalga 2 dosyası 11/11) | 76/76 |
| #79 | 775 geçti (18 dosya) | 55/55 |
| #80 | 831 geçti (21 dosya) | 52/52 |
| #81 | 859 geçti, 2 atlandı (22 dosya) | 82/82 |
| #82 | 876 geçti (23 dosya) | 37/37 |

GitHub CI (`Run tests / quality-gate`, ~3 saat):
- `score100-quality-gate`: #75, #76, #77, #78 yeşil; #79, #80 başladı.
- `quality-gate`: #75 (`5531f4a9`), #77, #78, #79, #80 çalışıyor. #76'nın ilk koşusu **180 dk iş sınırında iptal** oldu: 1112 + 8028 test geçti, 0 hata, migration ve coverage kapıları PASS; yalnız mypy adımı süre dolduğu için kesildi (değişen tek Python dosyasında yerel mypy temiz). Bir kez yeniden çalıştırıldı; PR'a açıklama yazıldı.

## 5. Kaç hata düzeltildi?

**21 hata** (hepsi testle sabitlendi):

1. Yeni Talep Aç: geçersiz dosya sonrası "dosya seçili" sanılması (D3) — yeniden seçim mesajı + önceki seçimin adı.
2. Yeni Talep Aç: İngilizce görünen metinler; "Raporlama ve Dashboard" → ekranda "Raporlama ve Gösterge Paneli" (kayıtlı değer aynı).
3. Asistan (mobil): 244×64 px boş kırmızı hap düğme, erişilebilir adı yok.
4. Asistan (mobil): ekran klavyesi açılınca mesaj kutusu/Gönder düğmesi klavyenin arkasında.
5. Asistan: panel 1366×768 ve 320 px'te ekrandan taşıyor; kapanınca odak kayboluyor.
6. Taleplerim: 11 sütun, 1.580 px tablo; mobilde yatay kaydırma → 5/6 sütun + mobil kart listesi.
7. Taleplerim: "…görünümü hazırlandı" gibi geliştirici metinleri, anlamsız sayaçlar ("Arama karakteri").
8. Liste/detay: 5+ sekmede (Bana Atananlar / Tüm Talepler izni) 768 px'te sekmeler 22 px'e düşüp satır ortasında kırılıyordu (dalga 2 gerilemesi, gece içinde bulundu ve düzeltildi).
9. Talep Detayı: form etiketleri alanlara bağlı değildi.
10. Talep Detayı: tarayıcının "Choose File / No file chosen" İngilizce dosya düğmesi.
11. Talep Detayı: 1 KB altı ekler "0 KB" görünüyordu.
12. Talep Detayı: "AI triage" İngilizce metinleri ve Font Awesome 6'da olmayan simge (boş kare).
13. Talep Detayı: ağ hatasında tarayıcının İngilizce iletisi ("Failed to fetch") ekrana yazılabiliyordu.
14. Talep Detayı: puan varsayılanı 1/5 — fark edilmeden 1 puan kaydedilebiliyordu.
15. Tasarım sistemi sayfaları: sağ sütunun son düğmesi sabit asistan düğmesinin altında kalıp tıklanamıyordu.
16. Yardım Merkezi: etiketsiz arama kutusu; tekrarlanan adım numaraları ("1. 1."); 13 satır içi stil.
17. Envanter belgesinde erişim sütunu ayrıştırma hatası (bütün satırlar "herkese açık olabilir" görünüyordu) — düzeltildi.
18. Rehber arama: etiketsiz kutu, "#AI özet" / "#CSRF" önerileri ve sonuç yokken İngilizce anahtar kelime listesi — Türkçe öneriler aynı rehberleri buluyor.
19. Rehber makale: mobilde araç çubuğu düğmeleri 42 px (44 px hedefin altında).
20. Rehber formu: etiketler alanlara bağlı değildi; "slug" İngilizce etiketleri.
21. Türkçe testleri talep numarasının rastgele onaltılık sonekini (ör. `DB7034`) kısaltma sayıp ara sıra kırılıyordu (CI riski) — #77'de düzeltildi, üst dallara birleştirmeyle taşındı.

## 6. Kaç hata hâlâ açık?

**13 açık konu** (bilerek bu PR'lara karıştırılmadı veya karar bekliyor):

1. Yapay zekâ talep özeti ham durum kodu ve İngilizce alan adı yazıyor ("mevcut durum open") — `app/services/ai`.
2. Talep notu eklerken dosya reddedilirse yazılan not da kayboluyor (rota davranışı).
3. Yardım içeriği verisinde İngilizce terimler: AI, Dashboard, URL, CSRF, CAPTCHA — terim kararı gerekiyor.
4. Talep Detayı'nın eski stil bloğu: taşıma, ratchet istisnasının (DISJOINT_RECLAIMS) genişletilmesini gerektiriyor — sahip onayı.
5. CI süre bütçesi: ana test adımı ~2 sa 53 dk, iş sınırı 180 dk; mypy adımı kesilebiliyor.
6. Pilot dil denetleyicisinin İngilizce kelime listesi sınırlı (ör. "quick", "start" yakalanmıyor).
7. Küresel bir arayüz betiği bazı bağlantılara kalıcı çerçeve ekliyor (`bys360-ux1-action-focus`) — tüm sitede, ayrı inceleme.
8. 3 rotada dekoratör görünmüyor (`/guest/files/<token>`, `/guest/upload/<token>`, `/offline`) — muhtemelen tasarım gereği; güvenlik hattında doğrulanmalı.
9. Talep türü detay ekranında gösterilmiyor (rota tür listesini geçirmiyor).
10. `base.html` ortak düzeni: "Dashboard" menü adı, "AI destekli" rozeti, flash mesajlarında `role` eksikliği — yüksek risk, ayrı PR.
11. Rehber araması şapkalı harfi eşlemiyor: "yapay zeka" 0 sonuç, "yapay zekâ" 3 sonuç (sunucu tarafı).
12. Rehber Yönetimi listesi eski tasarımda: stil bloğu Style-2A sahipliğinde (taşıma ratchet istisnası ister) ve silme onayı işaretlemesi sözleşmelerle sabit — sahip kararı.
13. Gerçek iPhone/Android ve NVDA/VoiceOver testleri yapılmadı.

## 7. Mobil BYS360 Asistanı sorunu çözüldü mü?

**Emülasyonda çözüldü, gerçek cihazda doğrulanmadı.** PR #76: kök neden v31 CSS'teki medya sorgusuz `min-width: 244px !important` kuralı ve panelin 520 px alt sınırı. Düzeltmeden sonra 390 ve 320 px'te klavye simülasyonuyla mesaj kutusu ve Gönder görünür, düğme 56 px yuvarlak ve adlı, odak geri dönüyor, axe 0 kritik/ciddi. Yeni bir `!important` eklenmedi. Gerçek iPhone (Safari, ana ekran uygulaması) ve Android Chrome testi **yapılmadı**.

## 8. Hangi PR'lar açıldı?

| PR | Konu | Bağımlılık |
|---|---|---|
| [#75](https://github.com/bys360/bys360/pull/75) | Yeni Talep Aç pilotu (önceki oturumdan; bu gece CSP test uyumu + ratchet düzeltmesi) | — |
| [#76](https://github.com/bys360/bys360/pull/76) | Mobil BYS360 Asistanı | bağımsız |
| [#77](https://github.com/bys360/bys360/pull/77) | Dalga 2: talep listesi | #75 |
| [#78](https://github.com/bys360/bys360/pull/78) | Durum belgesi, envanterler, bu rapor | bağımsız |
| [#79](https://github.com/bys360/bys360/pull/79) | Dalga 3: Talep Detayı | #77 |
| [#80](https://github.com/bys360/bys360/pull/80) | Dalga 4: Yardım Merkezi | #79 |
| [#81](https://github.com/bys360/bys360/pull/81) | Dalga 5: Rehber makale, kategori, rol, arama | #80 |
| [#82](https://github.com/bys360/bys360/pull/82) | Dalga 6: Rehber formu ve destek kurulumu | #81 |

Hepsi Draft; hiçbiri merge edilmedi, canlıya alınmadı.

## 9. Hangi PR'lar görsel onay bekliyor?

- **#77, #79, #80, #81, #82** — eski/yeni ekran görüntüleri (1366, 768, 390 px; aynı rol, aynı sahte veri) önizleme sayfasında.
- **#76** — emülasyon kanıtı hazır; gerçek cihaz kontrolü önerilir.
- **#75** — görsel onay verildi; merge kararı sizde.
- Ek kararlar: #79 stil bloğu taşıma (ratchet istisnası), #80 içerik terimleri.

## 10. Bir sonraki ekran hangisi?

**Ana sayfa / gösterge paneli** (`/dashboard` ailesi): en çok görülen ekran. Önce ortak bileşen ve `base.html` etkisi incelenecek, sonra ayrı dalga. Destek ailesinde yalnız Rehber Yönetimi listesi kaldı; o, stil bloğu kararınıza bağlı.
