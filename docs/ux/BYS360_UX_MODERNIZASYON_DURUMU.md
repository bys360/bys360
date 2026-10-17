# BYS360 Arayüz Modernizasyonu — Durum ve Devir Belgesi

Son güncelleme: 17 Ekim 2026, gece çalışması. Bu dosya her çalışma dalgasında güncellenir; sonraki oturum buradan devam eder.

## 1. Kurallar (değişmez kabul kriterleri)

1. **Tasarım referansı:** PR #75 (Destek → Yeni Talep Aç), proje sahibinin görsel onayıyla (16 Ekim 2026).
2. **Kurumsal renk:** Bordo `#8B0000`; beyaz ve nötr griler; erişilebilir durum renkleri (`app/static/css/bys360_tokens.css`). Gradyan, gösterişli animasyon ve süs yok.
3. **Tamamen Türkçe arayüz:** Kullanıcıya görünen hiçbir metinde İngilizce kelime yok. Kayıtlı değerler, URL'ler, rol/yetki anahtarları ve kod adları değişmez; gerekirse yalnız **görünen ad** eşlenir (ör. `Raporlama ve Dashboard` → ekranda `Raporlama ve Gösterge Paneli`). Otomatik dil testi: `tests/behavior/test_pilot_support_new_ux_contract.py` (`UI_ENGLISH_DENYLIST`, gerekçeli `UI_ACRONYM_EXCEPTIONS`).
4. **CSP:** Şablonlarda satır içi `style`, `<style>` bloğu ve `on*=` işleyici yok. Taşınan her `<style>` bloğu stil ratchet manifestine (`tests/security/test_csp_style_migration_cumulative_inventory_contract.py`, `STYLE_MIGRATION_WAVES`) dalga olarak yazılır ve repo geneli sabitler **yalnız düşer**.
5. **Kapsam:** Her bileşen seçicisi `.bys-ui` ile başlar; `:root` ve `!important` yok. Tasarım sistemini yükleyen şablonlar `DESIGN_SYSTEM_TEMPLATES` izin listesinde açıkça yazılıdır.
6. **İşlev ve güvenlik korunur:** Rotalar, dekoratörler, sorgular, görünürlük kapsamı, CSRF ve iş kuralları değişmez. Test silinmez, atlanmaz, gevşetilmez.
7. **Kanıt:** Aynı rol, aynı sahte veri, aynı ekran boyutuyla eski/yeni görüntü; üretimle aynı CDN sürümleri (Bootstrap 5.3.3, Font Awesome 6.5.2, Inter) yerelden yüklenir; zorlayıcı CSP açık. Gerçek cihaz ve ekran okuyucu testleri emülasyonla eşdeğer sayılmaz.

## 2. Ortak bileşenler (tasarım sistemi)

| Dosya | İçerik |
|---|---|
| `app/static/css/bys360_tokens.css` | Renk, tipografi, boşluk, köşe, gölge, odak tokenları (`.bys-ui` altında) |
| `app/static/css/bys360_components.css` | Sayfa başlığı, sekmeler, kart, form bölümleri (fieldset/legend), alanlar, seçim kutusu, dosya bırakma bölgesi, hata özeti, düğmeler; dalga 2: özet şeridi, arama çubuğu, tablo, durum/öncelik çipleri, mobil kart listesi, boş durum |
| `app/templates/_ui_form.html` | `text_field`, `textarea_field` (karakter sayacı), `select_field`, `file_field` (bırakma bölgesi, D3 mesajları), `error_summary` |
| `app/static/js/bys360_ui_form.js` | Hata özetine odak, çift gönderim koruması, dosya adı gösterimi, karakter sayacı (CSP uyumlu) |

Küresel mobil betikler (`mobile_global_hardening.js`) ızgaraları tek sütuna zorlar; tasarım sistemi alanları `skip-mobile-normalize` ile kendi duyarlı düzenini kullanır. Bazı küresel mobil stiller düğmelere `min-height: 42px !important` verir; bileşenler yüksekliği ayrıca padding ile sağlar.

## 3. Açık çalışmalar (Draft PR)

| PR | Dal | Konu | Durum |
|---|---|---|---|
| [#75](https://github.com/bys360/bys360/pull/75) | `ux/pilot-support-new-2026-10` | Destek → Yeni Talep Aç pilotu, Türkçe arayüz, görsel yeniden tasarım, CSP sözleşme testleri | Görsel onay verildi. CI `e23ddff1`: 4 ratchet sabiti kaçmıştı; `5531f4a9` ile düzeltildi, CI yeniden çalışıyor |
| [#76](https://github.com/bys360/bys360/pull/76) | `fix/mobile-assistant-launcher-2026-10` | Mobil BYS360 Asistanı: boş hap düğme, ekran klavyesi, odak, taşma | Bağımsız; CI çalışıyor |
| [#77](https://github.com/bys360/bys360/pull/77) | `ux/wave2-support-list-2026-10` | Dalga 2: Taleplerim / Bana Atananlar / Tüm Talepler | #75'e bağımlı; CI çalışıyor; sahip görsel onayı bekliyor |

## 4. Ekran envanteri

`docs/ux/BYS360_EKRAN_ENVANTERI.csv`: uygulama açılarak çıkarılan **393 GET ekran rotası**, **289 farklı şablon** (depoda toplam 428 `.html`; kalanlar parça/ortak veya kullanılmayan dosyalar). Sütunlar: modül, rota, endpoint, şablon, menü anahtarı, roller (rol matrisinden), durum.

Durum adımları: `İncelenmedi → İncelendi → Geliştirildi → Test Edildi → Görsel Kanıt Hazır → Sahip Onayı Bekliyor`. Kanıt olmadan ileri adıma geçilmez.

| Modül ailesi | Ekran rotası |
|---|---|
| Performans Yönetimi | 180 |
| İletişim ve Anket Yönetimi | 61 |
| Sistem ayarları · Kullanıcı, rol, yetki | 44 |
| Personel Yönetimi | 35 |
| Destek ve Talep Yönetimi | 14 |
| Performans · Amir değerlendirme ve geri bildirim toplantıları | 12 |
| Dosya Merkezi | 11 |
| Duyurular ve bildirimler | 10 |
| Ana sayfa ve gösterge panelleri | 9 |
| Kurumsal Portal | 7 |
| BYS360 Sanal Asistanı | 3 |
| Misafir / dış erişim | 2 |
| Raporlama ve analiz | 2 |
| Yapay Zekâ Karar Destek | 2 |
| Oturum, hesap ve sistem sayfaları | 1 |

Bilinen sınır: envanter rota → şablon eşlemesini kaynak koddan çıkarır; şablonu yardımcı fonksiyonla seçen rotalar (ör. giriş ekranı) eksik sayılmış olabilir.

## 5. İngilizce metin aday envanteri

`docs/ux/BYS360_INGILIZCE_ARAYUZ_ADAY_ENVANTERI.csv`: pilot dışındaki **1.796 aday** (326 dosya; şablonlar, `flash()`/menü etiketleri, JS dizgeleri, mobil Flutter). Aday listesidir; JS'deki CSS sınıf adları gibi yanlış pozitifler elle ayıklanmalıdır. En sık: `AI` (Yapay Zekâ önerisi kurum kararına bağlı), `SLA`, `CSV`, `log`, `Dashboard`. Hiçbir dosya otomatik değiştirilmedi.

## 6. Sıradaki işler (öncelik sırası)

1. PR #75 CI yeşil → sahip merge kararı.
2. Destek → Talep Detayı (`support/detail.html`): yorum, durum, atama, puanlama, ekler; ayrı dalga.
3. Destek → Yardım Merkezi (`support/index.html` ve yardım makaleleri).
4. Ana sayfa / gösterge paneli (yüksek görünürlük; ortak bileşen etkisi incelenmeli).
5. Ortak düzen (`base.html`): global flash mesajlarına `role`, "Dashboard" menü adı, "AI destekli" rozeti — **yüksek risk**, ayrı küçük PR ve kapsamlı regresyon testiyle.
6. Giriş güvenliği G1–G8 ayrı güvenlik hattında (G6 → G1 → G7 → G3); UX PR'larına karıştırılmaz.

## 7. Yapılmayanlar

- Gerçek iPhone (Safari, ana ekran uygulaması) ve Android Chrome testleri.
- NVDA ve VoiceOver testleri.
- Canlı ortam, gerçek veri, merge ve dağıtım (yetki dışı).
