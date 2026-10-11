# 03 — BYS360 Modül Envanteri

| Alan | Değer |
|---|---|
| Kaynak (incelenen) | `origin/assistant-v2-full` @ `f796107fa6ab42096065a02d4724ec7e8d22f608` |
| Belgelenmiş production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` (`SOURCE_OF_TRUTH.md:12`) |
| Hazırlanma tarihi | 2026-10-11 |

## 1. Durum etiketlerinin kuralı

Bu envanter yeni durum üretmez; yalnız repodaki kanıtı sınıflandırır.

| Etiket | Kullanım koşulu |
|---|---|
| **Tamamlandı** | Bir repo belgesi modülü "uygulanmış" olarak kaydediyor **ve** modüle ait test dosyaları CI kapsamındaki dizinlerde bulunuyor. |
| **Kısmi** | Bir repo belgesi işlevsel boşluk, bilinen hata veya kopuk akış kaydediyor ve kapanışı production SHA'da gösterilmemiş. |
| **Bekleyen** | Bir repo belgesi özelliği planlanan / uygulanmamış olarak kaydediyor. |
| **Kapsam dışı** | `app/config/removed_modules.py` ile kasıtlı kaldırılmış. |
| **kanıt yok** | Yukarıdakilerden hiçbirini destekleyen belge/test bulunamadı. |

Önemli sınırlar:

- "Uygulanmış, canlı" ifadeleri `docs/current_state/12_BYS360_Modul_Envanteri_ve_Fonksiyonel_Kapsam.md` (DOC-12, tarih 2026-09-02, kaynak SHA `873e6d3`) belgesinden alınmıştır; bu envanter canlı sistemi doğrulamamıştır. Canlı doğrulama yalnız `SOURCE_OF_TRUTH.md:29-49`'daki cutover kontrolleriyle sınırlıdır (sağlık, smoke `ROUTE_COUNT=996`, Dosya Merkezi 19/19, şema sözleşmesi).
- "Test" sütunu, dosya adında modül anahtar kelimesi geçen `tests/**/test_*.py` sayısıdır (ör. `find tests -name "test_*performance*.py"`). Sayı, testlerin geçtiğini kanıtlamaz; CI'nin dal ucunda yeşil olduğu bu belgede doğrulanmadı.
- "Prod sonrası değişiklik" sütunu, production SHA ile dal ucu arasında birleşen PR'ları gösterir (`git log --merges cdae2795..f796107f`); bu değişiklikler **canlıda değildir**.
- `docs/handover/BYS360_FEATURE_COVERAGE_MATRIX.md` 2026-08-24 tarihli tarihsel snapshot'tır (dosyanın kendi başlığı); oradan alınan bulgular "(tarihsel)" olarak işaretlenmiştir.

## 2. Ana modüller

| # | Modül / alan | Kod yeri | Test (dosya adı) | Belgelenen durum | Prod sonrası değişiklik | Durum |
|---|---|---|---|---|---|---|
| 1 | Kimlik doğrulama, hesap | `app/auth/`, `app/account/`, `app/main_handlers/auth_handlers.py` | `tests/security/` (95 dosya, çoğu genel güvenlik) | DOC-12 §3.1–3.2 "Uygulanmış, canlı"; giriş denemeleri için ayrı `audit_logs` kaydı kanıtı bulunamadı (DOC-12 §3.1) | — | Tamamlandı (audit izi notuyla) |
| 2 | Personel / İK (kurumsal) | `app/institutional/` (23 dosya), `app/services/personnel/` | 16 (`*personnel*`) | DOC-12 §7.1 "Uygulanmış, canlı"; Puantaj bu modülde yok | PR #59 (B1-F1 kapsamlı personel erişimi), `app/services/personnel_read_grant.py` yeni | Tamamlandı |
| 3 | Performans yönetimi | `app/performance/` (63 dosya), `app/services/performance/` | 57 (`*performance*`) + `tests/performance/` 44 | DOC-12 §6.1 "Uygulanmış, canlı, en olgun" | PR #51, #59, #63, #64, #67 | Tamamlandı |
| 3a | Dönem içi notlar | `app/performance/interim_notes_manager_routes.py`, `app/services/performance/interim_notes_runtime.py` | `tests/security/test_f06a_interim_notes_technical_roles_contract.py` vb. | (tarihsel) Web ve karne farklı tablolar kullanıyor bulgusu (matris #21); 2026-10-07 migration tabloyu Alembic'e aldı (`migrations/versions/x1f3a9c5e7b2_...py:1-40`); `performance_interim_notes_live` dal ucunda hâlâ 3 dosyada geçiyor | PR #63 | Kısmi (bulgunun kapandığı doğrulanmadı) |
| 3b | Hatırlatmalar | `app/services/performance/reminder_notification_service.py` | kanıt yok (ayrı test bulunamadı) | (tarihsel) "gerçek bir tarama/üretim motoru YOK" (matris #22) | — | Kısmi |
| 3c | Stratejik performans v2 (KPI/hedef/yetkinlik) | `app/modules/strategic_performance/`, `app/performance/sp1_sidebar_routes.py` | 7 (`*kpi*`) | (tarihsel) `/performans/stratejik` altındaki 5 yolun 5'i `main` blueprint tarafından gölgeleniyor (matris #35); `strategic_performance_dashboard_bp` kayıt çağrısı bulunamadı (DOC-02 Ek §2) | PR #64 (F09 KPI hedefleri) | Kısmi |
| 4 | Geri bildirim / görüşmeler (feedback meetings) | `app/communication/feedback_*`, `app/services/performance/feedback_*` | 18 (`*feedback*`) | Matris #24 DOCUMENTED; görüşme gizlilik politikası 2026-10-10'da onaylandı (`app/services/performance/feedback_meeting_access.py:1-21`) | PR #57 (gizlilik, boş liste düzeltmesi) | Tamamlandı (gizlilik kuralı yalnız dal ucunda) |
| 5 | Destek talepleri / Yardım merkezi | `app/support/routes.py`, `app/services/support_ticket_access.py` | 19 (`*support*`) | DOC-12 §8.2 "Uygulanmış, canlı"; web/mobil `support_all` farkı insan kararı bekliyordu (`docs/technical-review/BYS360_TEKNIK_INCELEME_2026-09-30.md:164-172`) | PR #60 (K5: `support_all` web+mobil tek kural) | Tamamlandı (K5 kuralı canlıda değil) |
| 6 | İletişim: mesaj, duyuru, bildirim | `app/communication/` (38 dosya) | 11 (`*message*`), 11 (`*notification*`), `tests/communication/` 15 | DOC-12 §8.1 "Uygulanmış, canlı"; (tarihsel) `phase1..9d_routes.py` ailesi menüden kopuk (matris #8); Faz 5 digest 500 ve mobil mesaj yazma 500 MEDIUM borç (`TEKNIK_INCELEME_2026-09-30.md:156-158`) | PR #50 (digest), #56 (mobil thread), #54 (portal grup bildirimi) | Kısmi (MEDIUM borçların düzeltmesi canlıda değil) |
| 7 | Anket | `app/communication/surveys_routes.py`, `app/services/surveys/` | 14 (`*survey*`) | Matris #9 DOCUMENTED; mobil "yanıt bekleyen" sayacı LOW borç (`TEKNIK_INCELEME_2026-09-30.md:160-162`) | — | Tamamlandı (LOW borç açık) |
| 8 | Kurumsal Bilgilendirme Merkezi (CIC) | `app/services/cic/`, `corporate_information_center_routes.py` | 14 (`*cic*`) | Matris #25; iki installer aynı 5 görevi iki kez kurabiliyor (tarihsel bulgu) | — | Tamamlandı (operasyon notuyla) |
| 9 | Dosya Merkezi | `app/file_center/` (7 dosya), 19 tablo | 13 (`*file_center*`) | DOC-12 §9.1 "Uygulanmış, canlı"; canlıda "File Center 19/19" (`SOURCE_OF_TRUTH.md:40`) | PR #62 (F07a/F07b yetki daraltması) | Tamamlandı |
| 9a | Dosya Merkezi klasörleri | `FileStorageFolder` modeli | kanıt yok | Model var, UI/route yok — FUTURE (matris #37) | — | Bekleyen |
| 10 | Sanal Asistan (Assistant V2) | `app/ai_agent/`, `app/services/assistant_v2/`, `app/services/ai_agent/` | 34 (`*assistant*`) | DOC-12 §5.2 "Uygulanmış, canlı"; deterministik, harici LLM yok (`ARCHITECTURE.md:16-18`); `assistant_training_bank.json` hiçbir kod tarafından okunmuyor (matris #31, tarihsel) | — | Tamamlandı |
| 11 | AI karar desteği | `app/ai/`, `app/admin/ai_*_routes.py`, `app/services/ai/`, `app/services/ai_decision/` | 23 (`*ai_*`) | DOC-12 §5.1 "Uygulanmış"; varsayılan `AI_PROVIDER_MODE=stub` (`config.py:722`); faz10/11/12 alt-blueprint kaydı belirsiz (DOC-02 Ek §3) | PR #59 kapsamında `permission_guard.py`, `visibility_scope.py` | Kısmi (faz10-12 erişilebilirliği doğrulanmadı; production AI modu bilinmiyor) |
| 12 | Ayarlar / menü yetki matrisi | `app/services/settings/`, `app/main_handlers/account_settings_helpers.py`, `app/settings_center/` | 29 (`*settings*`), 10 (`*menu*`) | Matris #11/#12/#28 DOCUMENTED; `/admin/role-matrix` statik veri gösterir, DB ile sapabilir (DOC-11 §7) | PR #59 (`personnel_read_all` per-user yetkisi) | Tamamlandı (salt-okunur ekran sapma riskiyle) |
| 13 | Mobil API | `app/api/mobile/` (`domains/` 11 modül) | 64 (`*mobile*`) | Matris #23 DOCUMENTED; itsdangerous token (JWT değil) | PR #55, #56, #59, #60, #66 | Kısmi (mobil yazma 500 borcu canlıda açık olabilir, bkz. #6) |
| 14 | Flutter mobil uygulama | `mobile_flutter/bys360_mobile_native/` | 7 Dart test dosyası (CI dışı) | Mağaza yayın durumu doğrulanmadı (DOC-02 §7) | — | kanıt yok |
| 15 | PWA | `app/pwa/`, `app/pwa_routes.py` | 2 (`*pwa*`) | DOC-12 §10.2 "Uygulanmış, canlı"; `app/pwa_blueprint.py` ölü kod (matris #38, tarihsel) | — | Tamamlandı |
| 16 | Portal (kurumsal sosyal) | `app/portal/routes.py` | 8 (`*portal*`) | DOC-12 §10.1 "Uygulanmış, canlı"; `REMOVED_MODULES["portal"]=False` | PR #54 | Tamamlandı |
| 17 | Dashboard | `app/dashboard/`, `app/services/dashboard_rebuild_service.py` | kanıt yok (adı geçen ayrı test bulunamadı) | DOC-12 §10.3 "Uygulanmış, canlı"; `dashboard_expansion_service.py` ölü kod (matris #13, tarihsel) | — | kanıt yok (test eşleşmesi yok) |
| 18 | Raporlama (Excel/PDF) | `app/services/pdf_export_guard.py`, `openpyxl` kullanan modüller | 12 (`*report*`) | (tarihsel) PDF tarayıcı `window.print()` ile; `reportlab`/`XlsxWriter` bağımlı ama import edilmiyor (matris #14) | — | Tamamlandı (Excel); PDF tarayıcı yazdırmasına dayalı |
| 19 | Yönetici Özeti | `app/executive_summary/`, `app/services/executive_mail_center*.py` | 6 (`*executive*`) | DOC-12 §10.4 "Uygulanmış, canlı"; (tarihsel) ana ekran menüden kopuk, 3 paralel uygulama (matris #17) | — | Kısmi |
| 20 | Hava durumu / günlük mail | `app/services/daily_weather_mail.py` | 3 (`*weather*`) | Matris #18 DOCUMENTED; Scheduled Task ile çalışır | — | Tamamlandı |
| 21 | Bakım modu | `app/bootstrap/operational_guards.py` | kanıt yok | Matris #34: yalnız env değişkeniyle açılır, yönetim ekranı yok | — | kanıt yok |
| 22 | Onboarding servisi | `app/services/onboarding_service.py` | — | Fonksiyonun çağıranı yok (matris #29, FUTURE) | — | Bekleyen (kullanılmayan kod) |
| 23 | Puantaj (devam/mesai) | Yok | — | "Planlanan / onaylanan bir sonraki geliştirme" (DOC-12 §11; `docs/current_state/18_BYS360_Puantaj_Gelistirme_Gereksinim_Eki.md`) | — | Bekleyen |
| 24 | Belge/Medya (`repository`), Eğitim/İSG (`education`), Strateji (`strategy`) | Kod repoda duruyor | — | `app/config/removed_modules.py` ile kaldırılmış (DOC-02 §11) | — | Kapsam dışı |

## 3. Çapraz katmanlar (modül değil)

| Katman | Kod yeri | Kanıt |
|---|---|---|
| Şema koruma / runtime-schema | `app/bootstrap/schema_contract.py`, `app/schema_guard*.py`, `app/services/runtime_schema.py` | Canlı şema sözleşmesi PASS, hata sayısı 0 (`SOURCE_OF_TRUTH.md:39`) |
| Sağlık uçları | `app/routes.py:74-88,244-270`, `app/core/healthcheck.py:43-66` | Canlıda local/public health 200, readiness PASS (`SOURCE_OF_TRUTH.md:42-45`) |
| Rate limit | `app/security/api_rate_limit.py` | Kodda var |
| Prometheus metrikleri | `app/observability/prometheus_metrics.py` | Kodda var; `init_prometheus_metrics` için uygulama içinde çağrı noktası bulunamadı (`grep -rn init_prometheus_metrics`) — etkin olmadığı değerlendirilir |
| Release/paketleme | `scripts/release/build_bys360_safe_release.py` | Deterministik FULL paket iki kez byte-identical (`SOURCE_OF_TRUTH.md:96`) |

## 4. Production ile dal ucu arasındaki işlevsel farklar (özet)

Production'a alınmamış, dal ucunda birleşmiş PR'lar (`git log --merges --first-parent cdae2795..f796107f`):

| PR | Konu (dal adından) | Etkilenen modül |
|---|---|---|
| #50 | Faz 5 digest sözleşmesi | İletişim |
| #51 | Performans kayıt hatası geri bildirimi | Performans |
| #52 | Geniş `except` tavanı ratchet'i (CI) | Kalite |
| #54 | Portal grup gönderi bildirimleri | Portal |
| #55 | Mobil auth bozuk JSON | Mobil API |
| #56 | Mobil v1 thread bilinmeyen alıcı | Mobil API / İletişim |
| #57 | Geri bildirim sonrası boş listeler + görüşme gizliliği | Geri bildirim |
| #58 | CI'nin varsayılan dala push'ta çalışması | CI |
| #59 | B1-F1 kapsamlı personel/performans erişimi | Personel, Performans, Mobil |
| #60 | K5 `support_all` web+mobil | Destek |
| #62 | F07b Dosya Merkezi teknik roller içerik göremez | Dosya Merkezi |
| #63 | F06a dönem içi notlar teknik roller | Performans |
| #64 | F09 KPI hedefleri yalnız tam global rol | Stratejik performans |
| #66 | R06 mobil kişi seçicide sicil/unvan yok | Mobil API |
| #67 | F06d Faz 3 görünürlük teknik roller | Performans |
| #48, #49, #53 | Yalnız dokümantasyon | — |

Bu PR'lar canlıya alınana kadar ilgili modüllerin **canlı davranışı production SHA'daki koda** göre değerlendirilmelidir. Yetki etkileri için `04_ROL_VE_YETKI_MIMARISI.md` §9.

## 5. Envanterde kalan belirsizlikler

1. Matris (2026-08-24) ve DOC-12 (2026-09-02) bulgularının çoğu dal ucunda yeniden doğrulanmadı; özellikle #3a, #3b, #3c, #17, #19.
2. Flutter uygulaması için test/CI ve yayın kanıtı yok.
3. Dashboard ve bakım modu için adı eşleşen test bulunamadı (test olmadığı anlamına gelmez; içerik bazlı arama yapılmadı).
4. `docs/handover/BYS360_MODUL_ENVANTERI.md` iş alanı bazlı bir listedir ve "İzin ve devamsızlık", "Vekâlet" gibi alt kalemleri durum bilgisi olmadan sayar (`docs/handover/BYS360_MODUL_ENVANTERI.md:11-19`).
