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
| `app/static/css/bys360_components.css` | Sayfa başlığı, sekmeler, kart, form bölümleri (fieldset/legend), alanlar, seçim kutusu, dosya bırakma bölgesi, hata özeti, düğmeler; dalga 2: özet şeridi, arama çubuğu, tablo, durum/öncelik çipleri, mobil kart listesi, boş durum; dalga 3: iki sütunlu detay düzeni, zaman çizelgesi, tanım listesi, dosya listesi; dalga 4: arama kartı, bağlantı çipleri, bağlantılı sayaçlar, makale listesi, rehber kartları, numaralı/simgeli adımlar, açılır bölüm; dalga 5: okuma kartı (prose), içindekiler, yan kartlar, kart listesi, yazdırma kuralı. Tasarım sistemi sayfalarında sabit asistan düğmesi için 96 px alt boşluk |
| `app/templates/_ui_form.html` | `text_field`, `textarea_field` (karakter sayacı), `select_field`, `file_field` (bırakma bölgesi, D3 mesajları), `error_summary` |
| `app/static/js/bys360_ui_form.js` | Hata özetine odak, çift gönderim koruması, dosya adı gösterimi, karakter sayacı (CSP uyumlu) |
| `app/static/js/bys360_support_detail.js` | Talep detayı: yapay zekâ ön değerlendirmesi (yalnız `textContent`, `aria-live`) |

Küresel mobil betikler (`mobile_global_hardening.js`) ızgaraları tek sütuna zorlar; tasarım sistemi alanları `skip-mobile-normalize` ile kendi duyarlı düzenini kullanır. Bazı küresel mobil stiller düğmelere `min-height: 42px !important` verir; bileşenler yüksekliği ayrıca padding ile sağlar.

## 3. Açık çalışmalar (Draft PR)

Bağımlılık sırası: #75 → #77 → #79 → #80 → #81 → #82 → #83 (her biri bir öncekinin üstüne kurulu; CI yalnız `assistant-v2-full` tabanlı PR'larda çalıştığı için hepsinin tabanı `assistant-v2-full`). #76 ve #78 bağımsız.

| PR | Dal | Konu | Durum |
|---|---|---|---|
| [#75](https://github.com/bys360/bys360/pull/75) | `ux/pilot-support-new-2026-10` | Destek → Yeni Talep Aç pilotu, Türkçe arayüz, görsel yeniden tasarım, CSP sözleşme testleri | Görsel onay verildi. CI yeşil (`5531f4a9`) |
| [#76](https://github.com/bys360/bys360/pull/76) | `fix/mobile-assistant-launcher-2026-10` | Mobil BYS360 Asistanı: boş hap düğme, ekran klavyesi, odak, taşma | İlk CI 180 dk sınırında iptal (8028 + 1112 test geçti, 0 hata; mypy adımı kesildi); yeniden koşu yeşil |
| [#77](https://github.com/bys360/bys360/pull/77) | `ux/wave2-support-list-2026-10` | Dalga 2: Taleplerim / Bana Atananlar / Tüm Talepler (+ `bf467aab` sekme satırı düzeltmesi) | CI yeşil (`03e96feb`). Sahip görsel onayı bekliyor |
| [#78](https://github.com/bys360/bys360/pull/78) | `docs/ux-modernization-status-2026-10` | Bu belge, ekran envanteri, İngilizce metin aday envanteri, gece raporu | Belge. Güncel HEAD'in CI'ı tamamlanınca durum yazılır |
| [#79](https://github.com/bys360/bys360/pull/79) | `ux/wave3-support-detail-2026-10` | Dalga 3: Talep Detayı | CI yeşil (`5da2bbba`). Sahip görsel onayı + stil bloğu taşıma kararı (DISJOINT_RECLAIMS) bekliyor |
| [#80](https://github.com/bys360/bys360/pull/80) | `ux/wave4-help-center-2026-10` | Dalga 4: Yardım Merkezi | CI yeşil (`8bc98cdc`). Sahip görsel onayı + içerik terimleri kararı bekliyor |
| [#81](https://github.com/bys360/bys360/pull/81) | `ux/wave5-help-pages-2026-10` | Dalga 5: rehber makale, kategori, rol, arama | İlk CI Ruff B007 ile kırmızı; `370d497e` ile düzeltildi, CI yeşil. Sahip görsel onayı bekliyor |
| [#82](https://github.com/bys360/bys360/pull/82) | `ux/wave6-help-form-setup-2026-10` | Dalga 6: rehber formu ve destek kurulumu (yönetici) | İlk CI #81'den miras Ruff hatasıyla kırmızı; `3b0d5c25` birleştirmesiyle düzeltildi; sonraki koşu 0 hatayla 180 dk sınırında iptal oldu, bir kez yeniden çalıştırıldı. Sahip görsel onayı bekliyor |
| [#83](https://github.com/bys360/bys360/pull/83) | `ux/wave7-help-admin-list-2026-10` | Dalga 7: Rehber Yönetimi listesi (yönetici) | İlk CI #81'den miras Ruff hatasıyla kırmızı; `edf49eb0` birleştirmesiyle düzeltildi, CI yeşil. Sahip görsel onayı + stil bloğu kararı bekliyor |
| [#84](https://github.com/bys360/bys360/pull/84) | `ci/quality-gate-timeout-240-2026-10` | CI: `quality-gate` süre sınırı 180 → 240 dk (sahip onaylı, kısa vadeli) | Draft; kendi CI koşusu bekleniyor |

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

Bilinen sınırlar:
- Envanter rota → şablon eşlemesini kaynak koddan çıkarır; şablonu yardımcı fonksiyonla seçen rotalar (ör. giriş ekranı) eksik sayılmış olabilir.
- `erisim_dekoratorleri` sütunu görünüm fonksiyonunun dekoratörlerini listeler (rol matrisi değil). İlk sürümde bu sütun ve `menu_anahtari` bir ayrıştırma hatası yüzünden bütün satırlarda boş/yanlış ("herkese açık olabilir") çıkmıştı; düzeltildi. 5 rotada dekoratör görünmüyor; ikisi elle kontrol edildi ve korumalı (`/hr-management/personnel-operations`: `add_url_rule` sarmalı; `/ai-agent/knowledge`: fonksiyon içi + `before_request`). Kalan üçü (`/guest/files/<token>`, `/guest/upload/<token>`, `/offline`) tasarım gereği misafir/çevrimdışı sayfalar olabilir; güvenlik hattında doğrulanmalı.

## 5. İngilizce metin aday envanteri

`docs/ux/BYS360_INGILIZCE_ARAYUZ_ADAY_ENVANTERI.csv`: pilot dışındaki **1.796 aday** (326 dosya; şablonlar, `flash()`/menü etiketleri, JS dizgeleri, mobil Flutter). Aday listesidir; JS'deki CSS sınıf adları gibi yanlış pozitifler elle ayıklanmalıdır. En sık: `AI` (Yapay Zekâ önerisi kurum kararına bağlı), `SLA`, `CSV`, `log`, `Dashboard`. Hiçbir dosya otomatik değiştirilmedi.

## 6. Sıradaki işler (öncelik sırası)

1. Sahip kararları: #75 merge; #77/#79/#80 görsel onay; #79 stil bloğu taşıma (DISJOINT_RECLAIMS ikinci giriş) onayı; yardım içeriği terimleri ("AI", "Dashboard", "URL", "CSRF", "CAPTCHA").
2. CI süre bütçesi: sahip 240 dk'yı kısa vadeli çözüm olarak onayladı → [#84](https://github.com/bys360/bys360/pull/84) (Draft; yalnız iş akışı değeri + açıklama belgesi). Bulgu: `test_quality_gate_job_timeout_has_an_evidence_backed_floor` gerçek değeri değil bir yorum satırını (45) okuyor — düzeltme sahip kararına bırakıldı. Kalıcı çözüm: Step2'yi bölme planı (ayrı, ölçüme dayalı).
3. Destek modülü tamamlandı (#75–#83). Talep Detayı ve Rehber Yönetimi listesindeki eski stil bloklarının taşınması sahip kararına bağlı. Rehber aramasında "yapay zeka" → "AI" eş anlamı yok (terim kararıyla birlikte).
4. Ana sayfa / gösterge paneli (yüksek görünürlük; ortak bileşen etkisi incelenmeli).
5. Ortak düzen (`base.html`): global flash mesajlarına `role`, "Dashboard" menü adı, "AI destekli" rozeti — **yüksek risk**, ayrı küçük PR ve kapsamlı regresyon testiyle.
6. Yapay zekâ özet servisi (`app/services/ai`): talep özetinde ham durum kodu ("open") ve İngilizce alan adı.
7. Giriş güvenliği G1–G8 ayrı güvenlik hattında (G6 → G1 → G7 → G3); UX PR'larına karıştırılmaz.

## 7. Yapılmayanlar

- Gerçek iPhone (Safari, ana ekran uygulaması) ve Android Chrome testleri.
- NVDA ve VoiceOver testleri.
- Canlı ortam, gerçek veri, merge ve dağıtım (yetki dışı).
