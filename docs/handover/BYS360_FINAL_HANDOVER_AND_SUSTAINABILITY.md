# BYS360 — Nihai Devir ve Sürdürülebilirlik Ana Dosyası

> **Tarihsel snapshot — 2026-08-24:** Bu belge, o tarihteki üretim/devir kaydının dondurulmuş görüntüsüdür. Sonraki tarihli açıklamalar kendi tarihsel bağlamlarıyla korunur. Aşağıdaki SHA, revizyon, paket, doğrulama ve hazır olma kayıtları güncel üretim beyanı değildir. Güncel üretim kimliği için [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md) esas alınır; tarihsel kanıtlar değiştirilmemiştir.

```
Document Status: HISTORICAL_SNAPSHOT (frozen 2026-08-24)
Production Source SHA: cb2e57c5d1829ea743c696ae78595a20755f3f07
Production Package: BYS360_FULL_LIVE_cb2e57c.zip
Package SHA256: 895dc9d57021a0107682edb06fd2b99e2f6d17d1d7e6db97fcf6edb9274c476c
Package File Count: 2136
Database Revision: e0efcd07abf7 (single head, independently verified against migrations/versions/*.py — 74 migration files, no branch points)
Last Production Validation: 2026-08-24
Handover Status: READY
```

> **Revizyon terminolojisi netleştirmesi (2026-08-25 eklendi — el kitabının ilerleyen
> bölümlerinde `e0efcd07abf7`/`10858a18e9ac` bir arada geçtiğinde karışıklığı önlemek için):**
> yukarıdaki başlık bloğundaki `Database Revision: e0efcd07abf7` alanı, o zamanki **son
> doğrulanmış canlı üretim dağıtımının** (`Production Source SHA: cb2e57c...`) veritabanı
> revizyonudur — repository'nin migration zincirinin o anki en son (head) revizyonu
> **değildir**. Karışıklığı önlemek için üç ayrı, açıkça adlandırılmış değer kullanılmalıdır:
> - **`PRODUCTION_CURRENT_DB_REVISION`** — canlı üretim veritabanının fiilen bulunduğu
>   revizyon. Bu belgenin başlığı bunu `e0efcd07abf7` olarak kaydeder (OPERATOR-ATTESTED; bu
>   oturumun canlıya doğrudan erişimi yoktur).
> - **`FILE_CENTER_MIGRATION_REVISION`** — Dosya Merkezi'nin 19 tablosunu Alembic'e dahil eden
>   sabit tarihsel migration: `10858a18e9ac`. §34.7'deki "HISTORICAL/RESOLVED" ibaresi bu
>   migration'ın **repository'nin migration zincirinde zaten tanımlı olduğu** anlamına gelir
>   — canlı veritabanının fiilen bu revizyona **dağıtıldığı** anlamına gelmez; o adım ayrı bir
>   cutover'ın konusudur.
> - **`RELEASE_TARGET_DB_REVISION`** — hazırlanmakta olan güncel release'in migration zinciri
>   head'i. Bu, candidate/cutover araçlarında (`prepare_bys360_candidate.ps1`) hiçbir yerde
>   sabit kodlanmamıştır; her zaman gerçek migration zincirinden dinamik olarak çözümlenir.
>   2026-08-25 itibarıyla, bu worktree'de `flask db heads` ile doğrudan doğrulanan güncel
>   değer `c51c29032d4f`'dir (schema-contract drift kapatma migration'ı, ayrıntı:
>   `docs/handover/DATABASE_MIGRATION.md`). Bu değer yeni migration eklendikçe değişir —
>   kalıcı bir gerçek olarak değil, kontrol talimatı olarak okuyun.
>
> Bu belgenin geri kalanındaki `10858a18e9ac` referansları (§34.7 ve ilgili bölümler) repo'nun
> migration zincirine dahil edilme tarihini doğru şekilde anlatır ve **değiştirilmemiştir** —
> yalnızca yukarıdaki üç terim ile hangi "revizyon"dan bahsedildiğini netleştiriniz.

**Bu belge kimdir için yazıldı:** Bu dosyayı ve repository'yi teslim alan yeni bir profesyonel geliştirici, sistem yöneticisi veya dış firma — bu sohbete, önceki geliştiriciye, ya da başka bir AI asistanına erişimi olmadan — BYS360'ı anlayabilmeli, kurabilmeli, test edebilmeli, geliştirebilmeli, release üretebilmeli, canlıya güvenli şekilde deploy edebilmeli ve bir sonraki kişiye devredebilmelidir.

**Kanıt disiplini notu (bu belgenin kendi metodolojisi):** Bu belgedeki her iddia iki kategoriden birine aittir ve açıkça öyle işaretlenmiştir:
- **REPO-VERIFIED** — repository kaynak kodu, git geçmişi, migration zinciri veya bu devir dalgası sırasında gerçekten çalıştırılan komutlardan doğrudan doğrulanmış.
- **OPERATOR-ATTESTED** — canlı sunucuya (RDP, PowerShell, DB, dosya sistemi) bu dokümantasyon oturumunun hiçbir zaman erişimi olmadığı için, yalnızca sistemi işleten operatörün sağladığı kanıt/beyan olarak kaydedilmiş. Bu dokümantasyon oturumu üretim ortamına doğrudan erişmedi ve erişmeyecek.

Bu ayrım, belgenin geri kalanında tutarlı şekilde korunmuştur.

---

## 0. Tarihsel Üretim Durumu (2026-08-24) — Provenance ile

**Verification provenance:** Production deployment of `cb2e57c` was completed and validated on 2026-08-24 based on operator-supplied production deployment logs and live user-acceptance evidence. The documentation-generation session itself did not have direct RDP or production access.

| Alan | Değer | Kaynak |
|---|---|---|
| Deployment token | `PASS_BYS360_CB2E57C_CLEAN_PRODUCTION_DEPLOYMENT` | OPERATOR-ATTESTED |
| Production state | `BYS360_PRODUCTION=UPDATED` | OPERATOR-ATTESTED |
| Active source SHA | `cb2e57c5d1829ea743c696ae78595a20755f3f07` | OPERATOR-ATTESTED (deployment) + REPO-VERIFIED (SHA exists, is the pushed HEAD of `phase5-critical-lint-clean-v1`, and passed exact-head Quality + Score100 CI — see §13) |
| Active package | `BYS360_FULL_LIVE_cb2e57c.zip`, SHA256 `895dc9d57021a0107682edb06fd2b99e2f6d17d1d7e6db97fcf6edb9274c476c`, 2136 dosya | REPO-VERIFIED (built by this session's canonical builder, independently SHA256-verified, deterministic Build #2 byte-identical) |
| Database | PostgreSQL 15, revizyon `e0efcd07abf7`, migration NOT_REQUIRED | Revizyon numarası REPO-VERIFIED (migration zinciri tek head, dallanma yok); "canlıda bu revizyonda çalışıyor" kısmı OPERATOR-ATTESTED |
| Service / Local health / Public health | PASS / 200 / 200 | OPERATOR-ATTESTED |
| Smoke / Security critical / New critical errors | PASS / 0 / 0 | OPERATOR-ATTESTED |
| UTF-8 Windows startup | PASS | OPERATOR-ATTESTED (canlı davranış); mekanizmanın kendisi REPO-VERIFIED (bkz. §7) |
| Live task | `BYS360 Live Waitress 80`, Running | OPERATOR-ATTESTED |
| Portal external video acceptance | PASS — canlı Portal composer'da Fotoğraf ekle / Video dosyası / Video bağlantısı üçü de görünür, video-link alanı operatör tarafından manuel test edildi | OPERATOR-ATTESTED (canlı); kök neden ve CSS düzeltmesi REPO-VERIFIED (bkz. §16) |

**Bu dokümantasyon oturumunun kendi doğrudan doğruladığı en son durum** (RDP olmadan, yalnız repo/CI kanıtıyla): `cb2e57c` HEAD'i `origin/phase5-critical-lint-clean-v1`'e push edilmiş, `git ls-remote` ile teyit edilmiş; aynı exact-head SHA için Quality ve Score100 GitHub Actions workflow'ları operatör tarafından sağlanan taze ekran görüntülerinde `succeeded` durumda ve Checkout log satırında `cb2e57c5d1829ea743c696ae78595a20755f3f07` görünüyor; `BYS360_FULL_LIVE_cb2e57c.zip` bu oturumda üretilip clean-room extract ile doğrulanmış. Bunun ötesindeki (gerçek sunucuya kurulum, canlı health, canlı kullanıcı ekranı) her şey operatör beyanıdır.

---

## 1. Executive Summary (Teknik Olmayan Yönetici İçin)

**BYS360 nedir:** Bir Türk kamu kurumu (T.C. Kültür ve Turizm Bakanlığı'na bağlı; `.env.example` varsayılan e-posta alan adı `ktb.gov.tr`) için geliştirilmiş, kurumsal bir personel/performans/iletişim yönetim platformudur.

**Ne çözer:** Tek bir web uygulamasında şunları bir araya getirir — personel/İK kayıtları ve izin/devam yönetimi, performans değerlendirme süreçleri (amir onay zincirleri dahil), kurum içi sosyal "Portal" (paylaşım/duyuru/yorum), anketler, destek/talep (helpdesk), iç iletişim/bildirim, karar-destek amaçlı yapay zekâ panelleri, sanal asistan sohbet arayüzü, dosya merkezi (güvenli dosya paylaşımı), ve bir yönetim panosu (dashboard).

**Hangi modülleri var:** Personel/İK, Performans, Portal, Anketler, İletişim, Destek, Ayarlar/Yetki Matrisi, Dosya Merkezi, Yönetim Panosu, AI Karar Destek, Sanal Asistan. Her birinin ayrıntısı §2'de.

**Kuruma ne kazandırır:** Dağınık Excel/e-posta/kağıt süreçlerini tek, denetlenebilir (audit-logged), rol-tabanlı yetkilendirmeli bir sisteme taşır; performans değerlendirme sürecini (amir görüşü → üst amir → Başkan onayı) sistematik ve izlenebilir hale getirir; KVKK'ya duyarlı veri erişim sınırları uygular (bkz. §15).

**Neden devredilebilir:** Sistem tek bir kişinin hafızasına değil — sürüm kontrolüne (git), otomatik testlere (4000+ test), CI kalite kapılarına (Ruff/mypy/secret-gate/Step1/Step2/Score100), deterministik release paketlerine (SHA256 doğrulanabilir), ve bu belge dahil yazılı runbook'lara dayanır. Ayrıntılı kanıt için bkz. §25 "Bus Factor".

**Neden sürdürülebilir:** Her değişiklik dalgası aynı disiplinle ilerler — odaklı testler → tam kalite kapıları (Step1 + Step2, 4000+ test) → commit → push → exact-head CI doğrulaması → deterministik paket üretimi → kontrollü deployment → canlı kullanıcı kabulü. Bu belge bu döngünün her adımını §21'de anlatır.

---

## 2. Sistem Mimarisi

**Kaynak:** Flask 3.1.3 / Python 3.12 backend, Jinja2 şablonlar, PostgreSQL 15 (canlı) / SQLite (local dev), SQLAlchemy 2.0 ORM, Flask-Migrate/Alembic migration, Flask-Login + rol-tabanlı yetkilendirme, Flask-WTF CSRF, özel CSP (Content-Security-Policy) katmanı, Waitress WSGI sunucusu (canlı), Windows Scheduled Task ile process yönetimi.

Kimlik doğrulama, yetkilendirme, dosya depolama, arka plan işleri, mail gibi ortak altyapı bileşenleri aşağıda; ardından iş modülleri tablo halinde.

### Ortak altyapı

| Bileşen | Nerede | Not |
|---|---|---|
| **Authentication** | `app/auth/routes.py` → `app/main_handlers/auth_handlers.py` (`login`, `forgot_password`, `logout`, `setup_admin`) | Web login IP+kimlik bazlı throttle + CAPTCHA (`get_auth_throttle_state`/`record_auth_failure`); mobil login (`/api/mobile/auth/login`) için ayrı bir throttle YOK, yalnız genel Flask-Limiter varsayılanına (200/dk) tabi — bilinen, kabul edilmiş bir risk (STATUS.md Faz 2B). |
| **Authorization** | `app/route_support.py` | Rol aileleri: `ADMIN_FAMILY_ROLES = {admin, baskan, baskan_yardimcisi, grup_baskani, mali_musavir}`, `MANAGER_FAMILY_ROLES = ADMIN_FAMILY_ROLES ∪ {birim_sorumlusu, koordinator}`. Ana guard: `menu_key_required(menu_key)` → `app.services.settings.effective_menu.build_menu_visibility_map(user)`'a bakar. **Admin bypass'i kaldırılmıştır** — admin dahil herkes canlı menü görünürlük haritasına tabidir (kod içi not: `BYS360_SETTINGS_LIVE_AUTHORITY_V2`). |
| **CSRF** | `app/extensions.py` (`csrf = CSRFProtect()`), özel PWA/iOS oturum-yenileme hata işleyicisi `app/__init__.py` içinde | — |
| **CSP** | `app/security/headers.py` (`build_csp_header`, `DEFAULT_CSP`), env üzerinden `config.py:685-704` | P0 hedefi: script-src için varsayılan `unsafe-inline` YOK; nonce inline/harici `<script>`/`<style>` etiketlerine uygulanır. |
| **Rate limiting** | `app/security/api_rate_limit.py` (Flask-Limiter, varsayılan `200 per minute`) | — |
| **Dosya yükleme güvenliği** | `app/security/upload_security.py` (`validate_upload`, `safe_store_filename`) | `UPLOAD_STRICT_MIME_VALIDATION=true` varsayılan |
| **Arka plan işleri** | `app/tasks/{core_background_tasks.py, feedback_tasks.py}` | Redis+RQ destekli, hem worker içinde hem inline fallback modda çalışabilir (`_ensure_app_context()`) |
| **Mail** | `app/services/mail_service.py`, `notification_mailer.py`, `daily_weather_mail.py`, `executive_mail_center_v2.py` | Varsayılan SMTP `smtp.office365.com:587`, TLS |
| **Raporlama** | `reportlab`, `openpyxl`, `XlsxWriter`; `app/services/pdf_export_guard.py` | PDF satır limiti varsayılan 250 (inline export) |
| **Reverse proxy farkındalığı** | `app/core/reverse_proxy.py` (`apply_reverse_proxy_fix`, Werkzeug `ProxyFix`, prod/staging'de varsayılan aktif, 1 hop) | `X-Forwarded-Proto/Host` tek güvenilir proxy adımından okunur |

### İş modülleri

| Modül | Amaç | Ana route/service/model | Yetki modeli | Kritik operasyon notu |
|---|---|---|---|---|
| **Personnel/İK** | Personel kaydı, izin/devam, delegasyon, organizasyon birimleri | `app/institutional/routes.py` (facade) + `hr_personnel_operations_routes.py`, `hr_personnel_leave_routes.py`, `hr_personnel_delegation_routes.py`, `hr_leave_attendance_routes.py`, `org_unit_routes.py`; servisler `app/services/hr_operations_service.py`, `hierarchy_*_service.py`; modeller `app/models/hr_models.py`, `org_models.py` | `menu_key_required` + rol aileleri | `hr_scope_helpers.py` "otomatik wildcard-import dönüşümü için güvenli değil, manuel refactor gerekli" olarak işaretli (ARCHITECTURE.md). |
| **Performance** | Değerlendirme dönemleri, ağırlıklandırma, amir onay hiyerarşisi | `app/performance/routes.py`, `phase10_development_guidance_ui.py`, `app/routes_performance_admin.py`; servisler `app/services/performance_service.py`, `app/services/performance/*` (`process_engine_phase6_president_approvals.py` dahil); modeller `performance_models.py`, `performance_process_engine_models.py`, `performance_low_score_models.py`, `performance_archive_models.py` | `admin_required`/`manager_required`/`menu_key_required` | İş kuralları için bkz. §17. |
| **Portal** | Kurum-içi sosyal akış: gönderi, fotoğraf, video dosyası, harici video linki, yorum, moderasyon | `app/portal/routes.py` (862 satır) | `menu_key_required`; ayrıca `PORTAL_EDITOR_ROLES`/`PORTAL_GROUP_MANAGER_ROLES`/`PORTAL_PROFILE_ADMIN_ROLES` | Video-URL görünürlük geçmişi ve backend detayları için bkz. §16. |
| **Anketler (Surveys)** | Anket oluşturma/atama/sonuç | `app/communication/surveys_routes.py` (1074 satır) | `menu_key_required` + `consume_form_token` (çift-gönderim önleyici) | — |
| **İletişim (Communication)** | Mesaj, bildirim, duyuru, popup | `app/communication/routes.py` (uyumluluk hub'ı) + `communication_phase2..9_service.py` (çok sayıda faz-numaralı servis dosyası) | `menu_key_required` | Okunmamış bildirim sayısı için `app_context_processor` kaydı var. |
| **Nabız Yoklaması (Feedback/Pulse)** | Kurum-içi periyodik geri bildirim anketleri, kampanya/aksiyon takibi, yönetici görünümü | `app/communication/feedback_*_routes.py` (action-plan, analytics, campaign, core, meeting); servisler `app/services/feedback_*` | `menu_key_required` (menü anahtarları `feedback_dashboard`/`feedback_pulse`/`feedback_campaigns`/`feedback_results`/`feedback_actions`/`feedback_manager`/`feedback_admin`) | Genel Anketler (Surveys) modülünden AYRI, kendi analitik/kampanya altyapısına sahip bir alt sistemdir. |
| **Kurumsal Bilgilendirme Merkezi (CIC)** | Doğum günü/yıldönümü gibi kurumsal otomatik bilgilendirme e-postaları | `app/communication/corporate_information_center_routes.py`; servisler `app/services/cic/*` (kendi README.md'si var) | admin/yönetici | Ayrı Scheduled Task ailesi var (bkz. §18); `app/services/corporate_information_center.py` (2764 satır) repodaki "kritik dev dosya" örneklerinden biri (bkz. bu bölümün altındaki "Bilinen mimari borç" notu). |
| **Yönetici Özeti (Executive Summary)** | Yöneticiler için otomatik özet raporu + test-mail | `app/executive_summary/routes.py` (`/yonetici-ozeti`, `/yonetici-ozeti/data`, `/yonetici-ozeti/test-mail`); servisler `app/services/executive_mail_center.py` + `_v2.py` | admin/sistem yöneticisi (menü bölümü `executive_summary`) | Sabah/gece otomatik mail görevleri için bkz. §18 (Executive Summary 0001/0830). |
| **Mobil API / PWA** | Flutter mobil istemci için salt-okunur+sınırlı-yazma JSON API; web tarafında Progressive Web App desteği | `app/api/mobile/` (blueprint `/api/mobile`, `domains/*` alt paketleri — iletişim, performans, destek, anket, AI özet, asistan); PWA: `app/pwa/routes.py` **ve** `app/pwa_blueprint.py` | Mobil auth guard (`app/api/mobile/domains/auth.py`) — mobil login için ayrı brute-force throttle YOK (bkz. yukarıdaki Authentication notu) | **⚠️ İki ayrı PWA implementasyonu bulundu** (`app/pwa/` ve `app/pwa_blueprint.py`, ikisi de `/manifest.webmanifest` benzeri uçlar kaydediyor) — hangisinin kanonik olduğu bu tur içinde netleştirilemedi, ayrı bir teknik-borç maddesi olarak §26'da işaretlendi. |
| **Destek (Support)** | Talep/bilet, yardım makaleleri | `app/support/routes.py` (1213 satır), `help_center_content.py` (1061 satır) | `admin_required`/`is_admin_family_user`/`is_manager_family_user`/`menu_key_required` | Ek dosyası doğrulaması `app/security/upload_security.py` üzerinden. |
| **Ayarlar/Yetki Matrisi** | Menü görünürlüğü, rol/yetki motoru, kataloglar | Admin UI `app/admin/role_matrix_routes.py` vb.; **asıl mantık bir servis paketi**: `app/services/settings/*` | Kendisi yetkilendirmenin kaynağı | `effective_menu.py` (2111 satır) — repodaki tek "kritik dev dosya" işaretli modüllerden biri; canlı menü görünürlüğünün otoriter kaynağı. |
| **Dashboard** | Ana HTML pano + JSON veri/grafik uçları | `app/dashboard/routes.py` | `login_required` + `menu_key_required("dashboard")` | Rotalar: `/dashboard`, `/performance/dashboard` (alias), `/dashboard/rebuild-data`. |
| **Sanal Asistan (AI Agent)** | Sohbet tabanlı asistan | `app/ai_agent/routes.py` (ayrı `Blueprint`, `/ai-agent` öneki) | Kendi `before_request` guard'ı; `/healthz` hariç kimlik doğrulama zorunlu | Bkz. §28. |
| **AI Karar Destek** | Performans/analiz panellerinde öneri/analiz | `app/ai/routes.py`, `app/admin/ai_*_routes.py` (çok sayıda faz dosyası); `app/services/ai/*` | Admin/yönetici erişimi | **Varsayılan olarak `AI_PROVIDER_MODE=stub`** — gerçek bir LLM'e bağlanmaz, deterministik `StubAIClient` kullanır. Gerçek sağlayıcı için `AI_API_KEY`/`AI_PROVIDER_MODE` açıkça ayarlanmalı. Bkz. §28. |
| **Dosya Merkezi (File Center)** | Kurum-içi güvenli dosya paylaşımı ve büyük dosya transferi (upload/download, şifreli süreli guest link, guest upload talebi, chunked büyük dosya yükleme, transfer paketleri, kota, güvenlik taraması) | `app/file_center/{routes,services,mail_service,settings_service,maintenance_service,permissions}.py` (44 route, 1154+1268 satır); 19 model `app/models/file_center_models.py` | Kendi rol-matrisi tabanlı izin modeli (`app/file_center/permissions.py`, 14 `can_*` bayrak) + guest link/upload akışları için ayrı token+parola katmanı | ClamAV entegrasyonu opsiyonel (`FILE_CENTER_CLAMAV_ENABLED`), varsayılan kapalı — devre dışıyken yalnız uzantı/MIME sezgisel kontrolü çalışır, gerçek virüs taraması yapılmaz. 19 tablosu artık Alembic migration'ına dahil (`10858a18e9ac`, bkz. §34.7 — HISTORICAL/RESOLVED). Tam ayrıntı: **§34**. |

**Veri akışı özeti:** İstemci (tarayıcı/mobil) → Flask route (yetki guard'ı) → servis katmanı (iş mantığı; CONTRIBUTING.md kuralı: route dosyaları iş mantığı İÇERMEMELİ, servis katmanını çağırmalı) → SQLAlchemy ORM → PostgreSQL. Şablon render'da CSP nonce enjekte edilir. Dosya yüklemeleri `app/security/upload_security.py`'den geçer.

**Bilinen mimari borç:** `app/services/corporate_information_center.py` (2764 satır) ve birkaç başka dosya, 2026-06-09 tarihli bir envanterde (`docs/architecture/BYS360_ROUTE_ARCHITECTURE_INVENTORY_P1A.md`) "kritik dev dosya" (god file) olarak işaretlenmişti; mobil API route dosyası (`app/api/mobile/routes.py`) benzer bir bölünmeden geçirilerek 2379→235 satıra indirildi (P1B-P1E dalgaları, `app/api/mobile/domains/*`). Bu, gelecekteki "büyük dosya bölme" çalışmaları için kanıtlanmış bir şablon sunar.

**Kod tabanında mevcut ama aktif olmayan modüller:** `app/config/removed_modules.py`'deki `REMOVED_MODULES` sözlüğü, üç modülün kodunun repoda TAM olarak durduğunu ama route/menü/AI bağlamından ÇIKARILDIĞINI gösterir: `repository` (Belge/Medya Merkezi), `education` (Eğitim/İSG), `strategy` (Strateji) — üçü de `True` (kaldırılmış); `portal` açıkça `False` (aktif) olarak işaretlenmiştir, karışıklığı önlemek için. Bu üç modülün kodu silinmemiştir ama bu belge onları CURRENT/aktif özellik olarak SUNMAZ.

**Menüde görünmeyen ama operasyonel açıdan önemli sistemler** (bu turun kod taraması ile bulundu, önceki devir dosyasında hiç geçmiyordu):

| Sistem | Ne işe yarar | Kod konumu |
|---|---|---|
| **Schema Guard** | DB şema kendiliğinden onarım/kontrol katmanı, `AUTO_REPAIR_SCHEMA` env bayrağına bağlı | `app/schema_guard*.py` (app kökünde 5 dosya) |
| **Query Health** | DB/sorgu sağlığı gözlem paneli, statik sorgu koruması, index sözleşmeleri | `app/services/query_health/` |
| **Settings Snapshot/Rollback** | Ayarların versiyonlanması ve geri alınabilmesi | `app/services/settings/snapshots.py`, `rollback_handler.py` |
| **Onboarding servisi** | Kullanıcı ilk-kullanım/karşılama akışı | `app/services/onboarding_service.py` |
| **Excel toplu içe/dışa aktarma** | Personel/hiyerarşi/karne verisi için toplu Excel import-export | `app/services/excel_import_pipeline_service.py`, `app/services/personnel/excel_import.py`, `app/services/hierarchy_excel_preview_service.py` |
| **Asistan eğitim bankası / adım-adım tutor** | Sanal Asistan'ın rehberli kullanım kılavuzu/eğitim katmanı, sohbet Q&A'dan AYRI | `app/assistant_training_bank/`, `app/services/ai_agent/assistant_*_tutor*.py`, `assistant_knowledge_bank_v1.py` |
| **Otomatik Hiyerarşi / yönetici zinciri senkronu** | Organizasyon şemasının otomatik türetilmesi | `app/services/auto_hierarchy_service.py`, `explicit_manager_chain_service.py`, `assignment_sync_service.py` |
| **Portal Sosyal Otomatik İçe Aktarma (Instagram)** | Instagram içeriğinin Portal'a otomatik aktarımı — menüde SAYFASI yok, yalnız arka-plan otomasyonu (bilinçli olarak; kod içi not: link havuzu sayfası kasıtlı olarak geri getirilmedi) | `app/services/instagram_portal_sync.py`, `app/services/portal_social_task_service.py`; Scheduled Task için bkz. §18 |
| **Maintenance Mode** | Genel bakım-modu banner'ı/kilidi | `MAINTENANCE_MODE`/`MAINTENANCE_MESSAGE` env bayrakları |

Bunların HER BİRİ yalnız yukarıdaki tek satırla belgelenmiştir (PARTIAL kapsam) — derinlemesine akış/güvenlik/DB detayı bu dokümantasyon dalgasının kapsamı dışındadır. **Tam, repo-türetilmiş özellik envanteri ve her özelliğin gerçek devir-kapsam durumu (DOCUMENTED/PARTIAL/UNDOCUMENTED/HISTORICAL) için bkz. `docs/handover/BYS360_FEATURE_COVERAGE_MATRIX.md`.**

---

## 3. Dizin Haritası

### C:\bys360 — REPO-VERIFIED kısım (bu geliştirme/build makinesinden doğrudan gözlemlendi)

Bu makine (bu belgenin hazırlandığı geliştirme/build ortamı) `C:\bys360` altında şunları içeriyor:

| Klasör | Ne işe yarar | Persistent mi | Silinebilir mi |
|---|---|---|---|
| `C:\bys360\project` | Kanonik ana git checkout — `.env.example`'daki `BYS360_PROJECT_ROOT` varsayılanı da bu yoldur; kurulum belgeleri (`BYS360_KURULUM_REHBERI.md`) release paketinin buraya extract edilmesini öngörür | Evet | Hayır — ana kod tabanı |
| `C:\bys360\worktrees\*` | Geliştirme sürecinde kullanılan izole git worktree'leri (her biri ayrı bir branch/çalışma için) | Hayır, geliştirme sırasında geçici | Kullanım bitince evet, `git worktree remove` ile |
| `C:\bys360\backups` | `BACKUP_RUNBOOK.md`'de tanımlı kod/DB yedekleri (`predeploy_<timestamp>` alt klasörleri) | Evet | Hayır — retention politikasına göre yönetilir (bkz. §10) |
| `C:\bys360\logs` | Uygulama/deployment logları | Evet | Log rotasyonu ile yönetilir, tamamen silinmez |
| `C:\bys360\releases` | Bu süreçte üretilen release paketleri (zip + manifest + sha256sums) | Evet (bilinçli tutulur) | Eski paketler retention politikasına göre temizlenebilir |
| `C:\bys360\reports` | Kalite/audit raporları | Yarı-persistent | Evet, tekrar üretilebilir |
| `C:\bys360\scratchpad`, `\tmp`, `\pytest-temp`, `\_pytest_tmp_phase12b`, `\audit_tmp`, `\release_out`, `\.pytest_cache` | Geliştirme/test/build sırasında oluşan geçici çalışma alanları | Hayır | Evet, güvenle silinebilir |

**Önemli epistemik not:** Bu tablo, bu belgenin hazırlandığı geliştirme/build makinesinin gerçek `C:\bys360` yapısını yansıtır — bu, CANLI ÜRETİM Windows Server'ının dosya sistemi ile AYNI makine DEĞİLDİR. Bu devir sürecinde adı geçen `overlays`, `archive`, `storage`, `local_storage`, `deploy_logs`, `staging` klasörleri bu geliştirme makinesinde **gözlemlenmedi** ve repository içindeki hiçbir belgede (DEPLOYMENT.md, BACKUP_RUNBOOK.md, docs/handover/*) bu isimlerle doğrulanmadı. Bunlar üretim sunucusunda gerçekten var olabilir (örn. `FILE_CENTER_STORAGE_ROOT` ortam değişkeni Dosya Merkezi için ayrı bir disk/volume yolu öngörür — `.env.example` örneği: `D:/bys360_storage/file_center`), ancak bu belge onları REPO-VERIFIED olarak sunmaz. **Yeni operatör: üretim sunucusunun gerçek dizin yapısını doğrudan RDP ile kontrol edip bu tabloyu güncellemelidir.**

### Uygulama kaynağı ile persistent veri ayrımı

`BYS360_DEVIR_PAKETI_V1.md` ve `scripts/release/build_bys360_safe_release.py`'nin dışlama kuralları, bu ayrımı somutlaştırır:

- **Uygulama kaynağı** (release paketine girer, git-tracked): `app/`, `migrations/`, `requirements.txt`, `wsgi.py`, `run_server.py`, `config.py`, `DEPLOYMENT.md` (builder'ın `REQUIRED_PACKAGE_PATH_PREFIXES`'i).
- **Persistent/hassas veri** (release paketine ASLA girmez, builder tarafından dışlanır): `.env*` (yalnız `.env.example`/`.env.docker.example` istisna), `instance/`, `logs/`, `uploads/`, `reports/`, `backups/`, `.git/`, SQLite/dump/bak/log/anahtar dosyaları, **Dosya Merkezi storage kökü** (`FILE_CENTER_STORAGE_ROOT`, tanımlıysa — bkz. §34.6).

---

## 4. Local Development

**Gereksinimler (REPO-VERIFIED, üç bağımsız kaynaktan doğrulandı — README.md, CONTRIBUTING.md, `.github/workflows/bys360-ci.yml`):** Python **3.12**, PostgreSQL 15 (opsiyonel — local'de SQLite yeterli), Git.

```bash
git clone <repo-url>
cd bys360
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt   # yalnız geliştirme/test için

copy .env.example .env
```

`.env` içinde en azından şunları ayarlayın (değerler `.env.example`'da örneklenmiştir, gerçek secret DEĞİL):

```
DATABASE_URL=sqlite:///instance/bys360_local_dev.sqlite3
SECRET_KEY=<local-gelistirme-icin-rastgele-bir-deger>
APP_ENV=development
```

**⚠️ Önemli varsayılan davranış:** `config.py`, `DATABASE_URL` ortam değişkeni tanımlı DEĞİLSE `sqlite:///:memory:` (bellek-içi, kalıcı OLMAYAN) veritabanına düşer. `.env` dosyanızda `DATABASE_URL`'i mutlaka açıkça ayarlayın, aksi halde her `flask db upgrade` / yeniden başlatma döngüsünde veri kaybedersiniz.

```bash
python -m compileall app config.py scripts migrations
flask db upgrade
python run.py
# tarayıcıda http://127.0.0.1:8000/login
```

`run.py`, `run_server.py` ve `wsgi.py` FARKLI amaçlara hizmet eder — birbirinin yerine kullanmayın:

| Dosya | Amaç | Waitress kullanır mı |
|---|---|---|
| `run.py` | Sade geliştirme girişi (`app.run(debug=False)`) | Hayır |
| `run_server.py` | Gerçek operasyonel giriş — UTF-8 stdio sağlamlaştırması (bkz. §7), `APP_ENV` production/staging ise Waitress'e geçer | Evet (yalnız prod/staging'de) |
| `wsgi.py` | Harici WSGI sunucuları için (`application = create_app()`) — doğrudan çalıştırıldığında hiçbir şey yapmaz | Hayır (kendisi başlatmaz) |

**Test/kalite komutları (copy/paste, `.github/workflows/bys360-ci.yml`'in gerçek CI adımlarıyla birebir):**

```bash
# Secret gate
python scripts/quality/bys360_secret_repo_gate.py --root .

# Ruff (tam select seti)
python -m ruff check app config.py wsgi.py run.py scripts tests

# mypy
python -m mypy app tests scripts --ignore-missing-imports --no-error-summary

# Step1 (hızlı, ~60-65 sn)
python -m pytest tests/quality -m "ci_safe" --cov=app --cov-report= --cov-fail-under=0 --tb=short -q

# Step2 (kapsamlı, ~26-28 dk) — tam komut çok uzun olduğu için .github/workflows/bys360-ci.yml
# dosyasındaki "Run integration and architecture tests" adımını KAYNAK olarak kullanın; özet:
python -m pytest tests/integration tests/architecture tests/security tests/critical \
  tests/services tests/migrations tests/release tests/communication tests/behavior \
  tests/mobile tests/performance \
  tests/quality/test_workflow_orphan_presentation_subsystem_cleanup_contract.py \
  [+ ~38 ayrı isimlendirilmiş tests/test_*.py dosyası — tam liste workflow dosyasında] \
  --cov=app --cov-append --cov-report=term-missing \
  --cov-report=xml:reports/quality/coverage.xml --cov-fail-under=0 --tb=short -q
```

**Yeni geliştirici için önemli uyarı:** Yukarıdaki Step2 komutunu ELLE yeniden yazmaya ÇALIŞMAYIN — dosya adı listesi çok uzun ve zamanla değişebilir. `.github/workflows/bys360-ci.yml` dosyasının kendisi TEK GÜVENİLİR KAYNAKTIR (README.md bunu açıkça söyler); local komutlar yalnız basitleştirilmiş alt kümelerdir.

---

## 5. Configuration / Environment

**Kural: bu bölümde hiçbir gerçek secret DEĞERİ yoktur — yalnız değişken adı, zorunluluk durumu, amaç ve local/production farkı.**

| Değişken | Zorunlu mu | Amaç | Local/Production farkı |
|---|---|---|---|
| `APP_ENV` | Evet | `development`/`testing`/`staging`/`production` | prod/staging'de güvenlik fail-fast kapıları devreye girer (bkz. §6) |
| `APP_BASE_URL` | Prod/staging'de fiilen zorunlu | Dış erişim URL'i, şema çözümlemesi için kaynak | prod/staging'de HTTPS harici host'a çözümlenmezse `RuntimeError` ile boot engellenir |
| `DATABASE_URL` / `SQLALCHEMY_DATABASE_URI` | Evet (prod'da) | ORM bağlantı dizesi | Boşsa `sqlite:///:memory:`'e düşer — prod'da bu KABUL EDİLEMEZ, `DATABASE_URL` her zaman açıkça ayarlanmalı |
| `SECRET_KEY` | Evet (prod'da fail-fast) | Flask session/CSRF imzalama | Boşsa `validate_live_security_defaults` prod/staging'de boot'u engeller |
| `TCKN_ENCRYPTION_KEY` | Şiddetle önerilir (yalnız uyarı, fail-fast değil) | TCKN/kimlik verisinin şifrelenmesi | Eksikse yalnız log uyarısı — ama KVKK açısından prod'da ASLA eksik bırakılmamalı |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`, `MAIL_USE_TLS` | Mail özellikleri için | SMTP yapılandırması | Varsayılan `smtp.office365.com:587`, TLS açık |
| `CSP_ENABLED`, `CSP_REPORT_ONLY`, `CSP_NONCE_ENABLED`, `CSP_*_SRC` | Hayır (güvenli varsayılanlar var) | Content-Security-Policy ince ayarı | `CSP_REPORT_ONLY` prod/staging dışında varsayılan `true`; prod/staging'de zorlanır |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE` | Hayır (`SENTRY_REQUIRED_IN_PRODUCTION=false` varsayılan) | Hata izleme | Boş bırakılabilir; bırakılırsa hata izleme kapalı olur (log ile bildirilir) |
| `RATELIMIT_STORAGE_URI`, `SECURITY_RATE_LIMIT_BACKEND` | Hayır | Rate-limit deposu (memory/redis/file) | Prod'da redis önerilir |
| `FILE_CENTER_STORAGE_ROOT` | Dosya Merkezi aktifse zorunlu | Kalıcı disk/volume yolu | Prod'da gerçek, ayrı bir volume; local'de boş bırakılabilir (`FILE_CENTER_ENABLED=false` varsayılan) |
| `SESSION_COOKIE_SECURE`, `REMEMBER_COOKIE_SECURE` | Hayır (akıllı varsayılan var) | Çerez güvenliği | "Akıllı downgrade" mantığı — bkz. §6, açıkça `true` istenip HTTPS/harici host koşulu sağlanmazsa otomatik `false`'a düşürülür (uyarı ile) |
| `TRUSTED_HOSTS` | Hayır (otomatik seed edilir) | Host header doğrulaması | Prod/staging'de literal `'*'` YASAK — `RuntimeError` |

**Secret değerleri bu belgeye veya herhangi bir repo dosyasına ASLA yazılmaz.** Gerçek teslim yöntemi için bkz. §31.

---

## 6. Production Architecture

**Platform:** Windows Server, Python 3.12, Flask, Waitress WSGI, Windows Görev Zamanlayıcı (Scheduled Task) ile process yönetimi.

**Not — repoda iki ayrı deployment hikayesi bulundu:** `docker-compose.yml`, `.env.docker.example` ve `docker/entrypoint.sh` bir Docker+gunicorn+Postgres+Redis yolu tanımlar; ancak `DEPLOYMENT.md` ve `run_server.py` yalnız Windows/Waitress/Scheduled-Task yolunu "canlı" olarak belgeler. **Bu belge, operatörün onayladığı gerçek canlı mimariyi (Windows/Waitress) kanonik kabul eder**; Docker yolu muhtemelen alternatif/test amaçlıdır ve iki yolu tek bir dokümanda uzlaştıran bir kaynak repoda bulunamadı — yeni operatör bunu netleştirmelidir.

### Scheduled Task: `BYS360 Live Waitress 80`

Kanonik installer: **`scripts/windows/install_bys360_live_waitress_80_task_v1.ps1`** (TD-034, plan/apply modlu — `-Apply` VERİLMEDEN çalıştırıldığında hiçbir sistem değişikliği yapmaz, yalnız planı basar).

```powershell
# DRY-RUN (varsayılan, güvenli):
.\scripts\windows\install_bys360_live_waitress_80_task_v1.ps1 `
  -ProjectRoot "C:\bys360\project" -Port 80

# GERÇEK UYGULAMA:
.\scripts\windows\install_bys360_live_waitress_80_task_v1.ps1 `
  -ProjectRoot "C:\bys360\project" -Port 80 -Apply -ConfirmReplace
```

İç komut (script tarafından tam olarak inşa edilir):

```
$env:APP_PORT = '80'; $env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'; & '<venv>\Scripts\python.exe' '<ProjectRoot>\run_server.py' *>> 'C:\bys360\logs\bys360_live_waitress_80.log'
```

Tetikleyici: `-AtStartup` (sistem açılışında, saat bazlı değil). Ayarlar: `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable`.

**⚠️ Doğrulanması gereken nokta:** Bu installer script'i, kendi içinde `-RunLevel Highest` / SYSTEM principal'ı AÇIKÇA ayarlamıyor (`New-ScheduledTaskPrincipal` çağrısı script içinde yok). Bu devir sürecinde "SYSTEM, Highest" varsayılmıştı — **yeni operatör, canlı sunucudaki görevin gerçek çalıştırma düzeyini `Get-ScheduledTask -TaskName "BYS360 Live Waitress 80" | Select-Object -ExpandProperty Principal` ile doğrudan kontrol etmelidir.**

Task yeniden başlatma (DEPLOYMENT.md §7):

```powershell
Stop-ScheduledTask -TaskName "BYS360 Live Waitress 80"
# port 80'e bağlı kalıntı python/waitress process'i varsa sonlandır
Start-ScheduledTask -TaskName "BYS360 Live Waitress 80"
Start-Sleep -Seconds 8
Invoke-WebRequest http://127.0.0.1/login
```

---

## 7. Windows UTF-8 Hardening (Historical Incident + Kalıcı Çözüm)

**HISTORICAL olay:** Canlı Windows Server 2019 "BYS360 Live Waitress 80" Scheduled Task'ında, yönlendirilmiş stdout varsayılan olarak sistem ANSI kod sayfasına (cp1252) düşüyordu. `run_server.py`'nin Türkçe başlangıç mesajı (`"BYS360 başlatılıyor..."`) bu kod sayfasında kodlanamayan karakterler içerdiği için `UnicodeEncodeError` fırlatılıyor ve process, Waitress port'a bağlanamadan çöküyordu. Görev Zamanlayıcı'da task "Running" görünüyordu ama port 80 hiç açılmıyordu — health check'ler başarısız oluyordu.

**Kalıcı çözüm (REPO-VERIFIED, commit `18bf31a`, 2026-08-24), iki katman:**

1. **Uygulama seviyesi** — `run_server.py:_ensure_utf8_stdio()`: `sys.stdout`/`sys.stderr` için `.reconfigure(encoding="utf-8")` çağrılır, modül import edilir edilmez (`create_app` import'undan ÖNCE, `# noqa: E402` ile bilinçli olarak). Fail-safe: reconfigure başarısız olsa bile process çökmez (`contextlib.suppress`).
2. **Scheduled Task seviyesi** — installer script'in inşa ettiği komuta `PYTHONUTF8=1` ve `PYTHONIOENCODING=utf-8` ortam değişkenleri eklendi (yukarıdaki §6'daki komut satırına bakın).

**⚠️ GELECEKTE BU MEKANİZMAYI KALDIRMAYIN.** Her iki katman da bilinçli olarak birlikte tutulur (defense-in-depth): uygulama seviyesi tek başına yeterli olsa da, Scheduled Task seviyesindeki env değişkenleri Python'un KENDİ başlatma aşamasını da güvence altına alır (uygulama kodu çalışmaya başlamadan önce). İkisinden birini kaldırmak, bu tam üretim kesintisi senaryosunu yeniden açar. Yeni test kanıtı: `tests/quality/test_run_server_utf8_stdio_hardening_v1.py` — gerçek negatif kontrol (cp1252'ye zorlanmış bir subprocess düzeltme olmadan gerçekten çöküyor, düzeltmeyle çökmüyor).

---

## 8. Health Check

`app/routes.py:72-74`:
```python
@main_bp.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "bys360"}), 200
```

**Bu sığ bir liveness check'tir — DB bağlantısı KONTROL ETMEZ, kimlik doğrulama gerektirmez.** "healthz OK" tek başına veritabanının erişilebilir olduğunun kanıtı DEĞİLDİR.

**Doğru kullanım:**

- **Local/backend-doğrudan health check:** `http://127.0.0.1/healthz` — 400 dönebilir; bu bir kesinti (outage) DEĞİLDİR, `Host` header'ının reverse-proxy'siz doğrudan çağrıda `TRUSTED_HOSTS`/scheme beklentisiyle uyuşmamasından kaynaklanır. Doğru local doğrulama, gerçek proxy header'larını taklit ederek yapılmalı: `Host: bys360.canakkaletarihialan.gov.tr` ve `X-Forwarded-Proto: https`.
- **Public health check (asıl kanonik doğrulama):** `https://bys360.canakkaletarihialan.gov.tr/healthz` → beklenen: `200`.

**Neden böyle:** `config.py` içindeki `SESSION_COOKIE_SECURE`/HTTPS fail-fast mantığı, process başlangıcında `APP_BASE_URL`/`PREFERRED_URL_SCHEME` env değişkenlerinden çözümlenir — canlı isteğin `Host`/`X-Forwarded-Proto` header'larından DEĞİL. Ancak `ProxyFix` (prod/staging'de varsayılan aktif, 1 hop) sayesinde `request.scheme`/`request.host`, reverse proxy'nin ilettiği header'ları YANSITIR — bu yüzden gerçek genel HTTPS yolundan geçen bir health check, backend'e doğrudan (proxy'yi atlayarak) yapılan bir problamdan FARKLI davranır. Bir health probu proxy'yi atlarsa, uygulamaya `http`/iç host olarak görünür.

Ayrıca ikinci, ayrı bir health endpoint daha vardır: `app/ai_agent/routes.py` → `@ai_agent_bp.get("/healthz")` — Sanal Asistan alt sistemi için, dış smoke testler amaçlı, hassas veri sızdırmayan filtrelenmiş bir `status` payload'u döner.

---

## 9. Database

**PostgreSQL 15**, Windows service adı: `postgresql-x64-15` (operatör kurulumuna göre; repo bu servis adını doğrudan belgelemez, standart PostgreSQL 15 Windows kurulum adıdır — OPERATOR-ATTESTED doğrulama önerilir).

**Güncel migration head (REPO-VERIFIED, bu oturumda migration zinciri bağımsız olarak ayrıştırılarak doğrulandı):** `e0efcd07abf7` (`migrations/versions/e0efcd07abf7_add_user_security_stamp.py`). Toplam 74 migration dosyası, tek head, dallanma yok.

**Alembic kullanımı:** `alembic.ini` yalnız `script_location = migrations` belirtir; `sqlalchemy.url` alanı bilinçli olarak bir yer tutucudur (`sqlite:///:memory:`), gerçek bağlantı `.env`/`DATABASE_URL` üzerinden Flask-Migrate tarafından sağlanır. **Migration her zaman `flask db upgrade` (Flask-Migrate sarmalayıcısı) ile çalıştırılır — çıplak `alembic upgrade` KOMUTU repo genelinde HİÇBİR YERDE kullanılmaz.**

### Migration karar ağacı

```
Yeni bir deployment yapılacak
        │
        ▼
Kaynak kod migration dosyası eklendi mi?
(migrations/versions/ altında yeni dosya var mı?)
        │
   ┌────┴────┐
  Evet       Hayır
   │           │
   ▼           ▼
DB YEDEĞİ AL   Migration ATLANIR
(pg_dump)      (NOT_REQUIRED)
   │
   ▼
Staging'de dene (mümkünse)
   │
   ▼
Canlı task'i DURDUR
   │
   ▼
`flask db upgrade` çalıştır
   │
   ▼
Başarılı mı?
   │
 ┌─┴─┐
Evet  Hayır
 │      │
 ▼      ▼
Task'i   DB'yi yedekten geri yükle,
BAŞLAT   deployment'ı DURDUR, kök nedeni
         araştır — asla "biraz daha dene"
         mantığıyla ilerleme
```

**NE ZAMAN `flask db upgrade` çalıştırılır:** Yalnız yeni bir migration dosyası deployment kapsamına girdiğinde. Bu handover dalgasının kendisi (`cb2e57c`) migration İÇERMİYOR — `Database migration: NOT_REQUIRED` bu yüzden doğrudur.

**NE ZAMAN çalıştırılMAZ:** Kod değişikliği yalnız template/CSS/JS/route/servis seviyesindeyse ve `migrations/versions/` altında yeni dosya yoksa.

**Schema'yı manuel değiştirme YASAĞI:** Şema değişiklikleri YALNIZ Alembic migration dosyaları üzerinden yapılır. Doğrudan `ALTER TABLE`/`CREATE TABLE` gibi manuel SQL komutlarıyla canlı şemayı değiştirmek, migration zincirini geçmişte-doğrulanamaz hale getirir ve sonraki `flask db upgrade` çalıştırmalarını bozabilir.

**Deployment öncesi DB backup kuralı:** Her deployment'tan ÖNCE, migration içersin içermesin, `BACKUP_RUNBOOK.md`'de tanımlı `pg_dump` prosedürü çalıştırılır (bkz. §10). Migration içeren deployment'lar için bu ZORUNLUDUR, atlanamaz.

---

## 10. Backup / Restore

**Kod ile DB yedeği birbirinden AYRIDIR.** `.env` güvenli, ayrı bir kanalda tutulur — asla release paketine veya kod yedeğine girmez.

### Kod yedeği

```powershell
robocopy "C:\bys360\project" "C:\bys360\backups\predeploy_<timestamp>\project" /E `
  /XD .git .venv __pycache__ logs instance reports dist_secure `
  /XF *.pyc *.log *.sqlite *.sqlite3 *.db
```

### PostgreSQL yedeği

```powershell
pg_dump --format=custom --file=$Out "%DATABASE_URL%"
```
`DATABASE_URL` ASLA ekrana yazdırılmaz/loglanmaz; güvenli bir kurumsal terminalde çalıştırılır.

### Restore — kod

```powershell
Stop-ScheduledTask -TaskName "BYS360 Live Waitress 80"
# yedeği project üzerine geri kopyala (robocopy, ters yönde)
Start-ScheduledTask -TaskName "BYS360 Live Waitress 80"
```

Otomatikleştirilmiş bir yardımcı script mevcuttur: **`scripts\windows\rollback_bys360_live_release_v1.ps1`** (TD-036) — **varsayılan olarak DRY-RUN**'dur (yalnız planı basar, hiçbir dosya kopyalamaz); gerçekten uygulamak için `-Apply` gerekir. `.env`, `instance\`, `logs\`, `uploads` (`app\static\uploads` dahil), `reports\` her zaman KORUNUR, asla üzerine yazılmaz.

```powershell
.\scripts\windows\rollback_bys360_live_release_v1.ps1 `
  -BackupRoot "C:\bys360\backups\predeploy_YYYYMMDD_HHMMSS" -Apply
```

### Restore — PostgreSQL

```powershell
pg_restore --clean --if-exists --dbname "%DATABASE_URL%" "<dump-dosyasi>"
```
Canlı restore, yetkili onay + planlı kesinti gerektirir — bu otomatikleştirilmemiştir, manuel ve kontrollü bir adımdır.

### Hangi veri ayrı korunur

| Veri | Nerede | Release paketine girer mi |
|---|---|---|
| `.env` | Sunucu üzerinde, güvenli kanal | Hayır |
| `instance/` | Uygulama çalışma dizini | Hayır |
| `logs/` | `C:\bys360\logs` | Hayır |
| Yüklenen dosyalar (`app/static/uploads`) | Ayrı, kalıcı disk/volume (git-ignored) | Hayır |
| **Dosya Merkezi storage** (`FILE_CENTER_STORAGE_ROOT`) | Ayrı, kalıcı disk/volume — DB yalnız metadata tutar, dosya baytları burada | Hayır — ayrı, dosya-sistemi-seviyeli yedek gerekir (bkz. §34.6/§34.10) |
| PostgreSQL verisi | PostgreSQL sunucu instance'ı, ayrı `pg_dump` yedeği | Hayır (kod paketinden tamamen bağımsız) |

### Saklama (retention) politikası

| Yedek türü | Saklama süresi |
|---|---|
| Deployment-öncesi kod yedeği | 30 gün |
| Kritik migration-öncesi DB yedeği | 90 gün |
| Aylık güvenli arşiv | 1 yıl |
| KVKK-hassas geçici çıktılar | Yalnız gerekli olduğu sürece, sonra güvenli silme |

### Restore drill (doğrulama)

Yedek doğrulama şu adımları içermeli: dosya var mı ve boyutu sıfır değil mi, restore bir TEST ortamında gerçekten denendi mi, yedekte `.env`/token/PII/gereksiz log yok mu, saklama konumu politikaya uygun mu.

---

## 11. Clean Production Deployment (Kanonik Runbook)

Bu runbook, bu oturumda gerçekten kullanılan modeli (release paketi üretimi, exact-head CI doğrulaması, SHA256 zinciri) ve `DEPLOYMENT.md`/`BACKUP_RUNBOOK.md`'nin belgelediği prosedürleri birleştirir.

**⚠️ Interactive PowerShell riski:** Bu runbook'un tamamını canlı bir PowerShell oturumuna satır satır YAPIŞTIRMAYIN. Uzun deployment akışları bir `.ps1` dosyası olarak kaydedilip **ayrı bir PowerShell process'inde** (`powershell.exe -File deploy.ps1`) çalıştırılmalıdır — interaktif olarak yapıştırılan uzun bloklar, terminal buffer/paste-throttling sorunları veya kısmi yapıştırma nedeniyle sessizce yarım kalabilir. **İç içe (nested), AYNI sınırlayıcıyı (delimiter) kullanan here-string ASLA kullanmayın** (`@'...'@` içinde başka bir `@'...'@` — bu bir parse hatasına yol açar).

| # | Aşama | Komut/Kontrol |
|---|---|---|
| 1 | Precheck | `git status --short`, `git rev-parse HEAD` — çalışma ağacı temiz mi, doğru SHA mı |
| 2 | Package SHA256 | `Get-FileHash BYS360_FULL_LIVE_<sha>.zip -Algorithm SHA256` — manifest'teki değerle eşleşmeli |
| 3 | Current health | `Invoke-WebRequest https://<domain>/healthz` — deployment ÖNCESİ mevcut durum kaydı |
| 4 | Config preserve | `.env`, `instance\`, `logs\`, storage konumlarının yolu not edilir (üzerine yazılmayacaklar) |
| 5 | Tasks quiesce | İlgili tüm Scheduled Task'ler (mail scheduler'lar dahil) durum kontrolü — deployment sırasında çakışma önlenir |
| 6 | Port 80 stop | `Stop-ScheduledTask -TaskName "BYS360 Live Waitress 80"`; kalıntı process varsa sonlandır |
| 7 | Old app remove | Eski `project` içeriği yedeklenip (bkz. §10) temizlenir |
| 8 | Full ZIP extract | `BYS360_FULL_LIVE_<sha>.zip` → `C:\bys360\project` |
| 9 | .env restore | Güvenli kanaldan `.env` geri konur (ASLA pakette gelmez) |
| 10 | instance restore | `instance\` klasörü korunur/geri konur |
| 11 | storage preserve | Yükleme/Dosya Merkezi storage yolu DOKUNULMADAN bırakılır |
| 12 | Fresh venv | `python -m venv .venv` (temiz) |
| 13 | Dependencies | `pip install -r requirements.txt` |
| 14 | Compile | `python -m compileall app config.py scripts migrations` |
| 15 | Runtime validator | Uygulama import edilebiliyor mu (`python -c "from app import create_app; create_app()"` benzeri bir kontrol, prod env değişkenleriyle) |
| 16 | DB revision | `flask db current` — canlı DB'nin hangi revizyonda olduğu kontrol edilir |
| 17 | Migration decision | §9'daki karar ağacına göre `flask db upgrade` gerekli mi belirlenir |
| 18 | Canonical installer dry run | `install_bys360_live_waitress_80_task_v1.ps1` **`-Apply` OLMADAN** çalıştırılır — plan gözden geçirilir |
| 19 | Apply | Gerekliyse `-Apply -ConfirmReplace` ile gerçek uygulama |
| 20 | Health | `/healthz` — hem local (proxy header taklidiyle) hem public |
| 21 | Process identity | Task'in gerçekten doğru Python/venv'i çalıştırdığı doğrulanır |
| 22 | Smoke | `/login`, ana modül ekranları (performans, personel, mesajlaşma, anket/destek, admin dashboard) |
| 23 | Fresh log gate | `bys360_live_waitress_80.log` içinde §21'de listelenen kritik pattern'ler taranır (bkz. §19) |
| 24 | Task states | İlgili tüm Scheduled Task'lerin son durumu kaydedilir |
| 25 | Final health | Son bir `/healthz` + kritik ekran taraması |
| 26 | Deployment receipt | SHA, paket adı, SHA256, saat, health sonucu, smoke sonucu bir "deployment receipt" olarak `C:\bys360\logs` veya `deploy_logs` altına yazılır |

---

## 12. Release Build

**Kanonik builder:** `scripts/release/build_bys360_safe_release.py` (`PACKAGE = "BYS360_SAFE_RELEASE_BUILDER_PHASE2_V3_DETERMINISTIC"`, `SCHEMA_VERSION = 2`).

**Mekanizma (REPO-VERIFIED, bu oturumda gerçekten çalıştırılıp doğrulandı):**

- **Kaynak:** yalnız `git ls-files -z` — **filesystem fallback YOK**; git kullanılamazsa `GitDiscoveryError` ile build durur (fail-closed).
- **Dirty tree fail-closed:** `git status --porcelain=v1` ile tracked/staged herhangi bir değişiklik varsa `DirtySourceError`.
- **Kaynak SHA sabitleme:** `--source-sha` verilirse `git rev-parse HEAD` ile birebir eşleşmeli, aksi halde hata.
- **Yasaklı dizin/dosya kuralları:** `.git`, `.venv`, `node_modules`, `__pycache__`, `instance`, `logs`, `uploads`, `reports`, `backups`, `releases`, `.github`, `tests`, `mobile_flutter`, `.codex`, `.claude` her zaman dışlanır. `"archive"` özel muamele görür: `app/` altındaki `archive` (örn. `app/templates/performance/archive/`, gerçek bir canlı özellik dizini) DIŞLANMAZ; `app/` DIŞINDAKİ her `archive` segmenti (örn. `docs/archive/`) dışlanır. `.env*` regex'i yalnız `ALLOWED_ENV_TEMPLATE_BASENAMES = {.env.example, .env.docker.example}` istisnasıyla çalışır — başka hiçbir `.env*` varyantı sızamaz. (Bu iki kural, 2026-08-23/24 tarihli gerçek bir hata düzeltmesinin sonucudur — önceki versiyon `app/templates/performance/archive/`'i ve `.env.example`'ı yanlışlıkla paketten düşürüyordu.)
- **Determinizm:** Her zip girdisi için sabit tarih/saat (kaynak commit'in `git show -s --format=%ct` epoch'undan, build makinesinin saatinden DEĞİL), sabit external attribute, sıralı dosya yazımı — **aynı commit için byte-birebir aynı zip garantisi.**
- **Manifest + SHA256SUMS:** `<ad>.manifest.json` (source_sha, included/excluded sayıları, sıralı dosya listesi — mutlak yol/kullanıcı adı/secret İÇERMEZ) ve `<ad>.sha256sums.txt`.
- **Required/forbidden audit:** `--verify` modu, `REQUIRED_PACKAGE_PATH_PREFIXES = (app/, migrations/, requirements.txt, wsgi.py, run_server.py, config.py, DEPLOYMENT.md)`'in varlığını, yasaklı dizinlerin YOKLUĞUNU, manifest↔zip SHA256 tutarlılığını, beklenmeyen ekstra/eksik dosya olmadığını kontrol eder.
- **Clean-room extraction:** Bağımsız bir geçici dizine extract edilip içerik doğrudan denetlenir.
- **Build #2 determinism:** Aynı komut ikinci kez çalıştırılıp iki zip'in SHA256'sı karşılaştırılır — bu oturumda `cb2e57c` için ikisi de **`895dc9d57021a0107682edb06fd2b99e2f6d17d1d7e6db97fcf6edb9274c476c`** çıkardı, birebir aynı.

**CLI kullanımı:**

```bash
python scripts/release/build_bys360_safe_release.py \
  --root . \
  --output C:/bys360/releases/BYS360_FULL_LIVE_<sha>/BYS360_FULL_LIVE_<sha>.zip \
  --source-sha <tam-git-sha>

# Doğrulama:
python scripts/release/build_bys360_safe_release.py \
  --verify C:/bys360/releases/BYS360_FULL_LIVE_<sha>/BYS360_FULL_LIVE_<sha>.zip \
  --expected-source-sha <tam-git-sha>
```

**Örnek nihai paket (bu belgenin kanonik SHA'sı):** `BYS360_FULL_LIVE_cb2e57c.zip` — 2136 dosya, SHA256 `895dc9d57021a0107682edb06fd2b99e2f6d17d1d7e6db97fcf6edb9274c476c`.

`scripts\security\build_bys360_secure_release_v1_5.py` ve eski PowerShell sarmalayıcıları **DEPRECATED**'dir — kullanılmamalıdır.

---

## 13. CI / Quality Gates

İki AYRI, birbirini tamamlayan GitHub Actions workflow'u:

### Quality (`.github/workflows/bys360-ci.yml`, job: `quality-gate`)

`ubuntu-latest`, Python 3.12, `postgres:15` servis konteyneri, `timeout-minutes: 45`, checkout `fetch-depth: 0`. Sırayla: secret/repo gate → safe-release audit → Ruff (tam select seti) → compileall → safe-release audit (tekrar) → **Step1** → **Step2** → gerçek PostgreSQL 15 migration-integrity gate → coverage ratchet gate → mypy → operations audit → Quality9 CI contract gate → Ruff syntax sanity → `pip-audit` bağımlılık zafiyeti taraması. Ölçülen yaklaşık süre: Step1 ~60-65sn, Step2 ~26-28dk.

### Score100 (`.github/workflows/bys360-score100-quality-gate-v1.yml`)

`windows-latest`, Python 3.12, `workflow_dispatch` + `pull_request` (master/main) tetikleyicili. Tek adım: `scripts\windows\repair_bys360_score100_quality_gate_v1.ps1 -Mode gate -RunPipAudit -RunRuff` → gerçek uygulaması `scripts/quality/bys360_score100_quality_gate_v1.py`. Kontroller: bağımlılık pinleme, Android imzalama, git-tracked `.env`, secret pattern'ler, TCKN şifreleme varlığı, exec route'lar, duplicate endpoint/test skip, app-factory duplicate kural, wildcard import, broad except, repo şekli.

### Exact-head kuralı (KRİTİK — ASLA ihmal edilmez)

**Bir workflow'un "succeeded" olması TEK BAŞINA yeterli DEĞİLDİR.** Checkout adımının log çıktısındaki gerçek SHA (`git log -1 --format=%H` satırı), doğrulanmak istenen commit ile **birebir** eşleşmelidir. Eski bir workflow çalıştırması (farklı bir commit için, hatta bir önceki commit için) yeni commit için kanıt SAYILMAZ. Bu belgenin kendi hazırlanışında (bkz. §0) bu kural harfiyen uygulandı: `cb2e57c` için hem Quality hem Score100'ün Checkout log satırında tam olarak `cb2e57c5d1829ea743c696ae78595a20755f3f07` görülmeden attestation verilmedi.

**GitHub Actions doğrudan okunamıyorsa** (bu oturumun kendi durumu — `gh` CLI kurulu değil, doğrudan API/browser erişimi yok), operatörden TAZE ekran görüntüsü istenmelidir; Checkout SHA görünmeden hiçbir PASS token'ı verilmemelidir.

---

## 14. Test Strategy

| Aile | Dizin | Ne test eder |
|---|---|---|
| Unit/static (loose) | `tests/test_*.py` (~34 dosya) | AST/statik kontroller, route smoke, yardımcı fonksiyon testleri |
| Behavior | `tests/behavior/` (6) | Gerçek servis/model davranışı |
| Security | `tests/security/` (~70) | CSP dalgaları, auth/CAPTCHA/rate-limit, negatif/injection testleri |
| Service | `tests/services/` (~80, en büyük alt dizin) | Servis katmanı birim testleri |
| Quality | `tests/quality/` (36) | Kalite-kapısı script'lerinin KENDİ meta-testleri (secret gate, scoring, debt registry, coverage ratchet) |
| Integration | `tests/integration/` (13) | Gerçek HTTP/DB akış testleri |
| Architecture | `tests/architecture/` (~70) | Route mimarisi/refactor-dalga sözleşme testleri |
| Migrations | `tests/migrations/` (7) | Gerçek Alembic `upgrade()`/`downgrade()` testleri, izole SQLite |
| Release | `tests/release/` (2) | Release-paketleme/audit testleri |
| Communication | `tests/communication/` (7) | İletişim route kayıt sözleşmesi (0-import statik kontrol) |
| Mobile | `tests/mobile/` (1) | Mobil domain sözleşmesi |
| Performance | `tests/performance/` (8) | **Performans YÖNETİM MODÜLÜ** testleri (yük/benchmark testi DEĞİL) |
| Critical | `tests/critical/` (7) | Geniş smoke/sözleşme kapıları |
| Load | `tests/load/` (6) | Locust yük testi script'leri — **CI'da ÇALIŞTIRILMAZ**, kapsam dışı |

**Negative controls:** Güvenlik testlerinde (host-spoof reddi, CSRF, rate-limit aşımı vb.) sistematik olarak kullanılır — "olumlu" testin yanında "bu girdi REDDEDİLMELİ" testleri de yazılır.

### Portal video düzeltmesi — test-harness false-positive olayı (HISTORICAL LESSON)

2026-08-24 tarihinde, Portal video-URL alanının canlıda görünmediği bulunup düzeltildi (CSS grid taşma hatası, bkz. §16). Bu düzeltme, **kendisiyle hiç ilgisi olmayan** iki eski test dosyasında yanlış-pozitif FAIL'e yol açtı:

- `test_no_important_declaration_added_by_this_pilot_precise_diff_check` — minified bir CSS satırında yapılan küçük bir değişiklik, aynı fiziksel satırdaki DOKUNULMAMIŞ bir `!important` kuralını "yeni eklenmiş" gibi raporluyordu (satır-bazlı, kaba `git diff` taraması nedeniyle).
- İki adet `test_no_new_css_file_was_added` (Meeting Final Gate ve P0 Completion testleri) — `git status --porcelain -- app/static/css/` dizininin TAMAMEN boş olmasını şart koşuyordu; bu, Meeting özelliğiyle HİÇ ilgisi olmayan herhangi bir CSS değişikliğinde yanlış FAIL veriyordu.

**Kanıtlanan çözüm:** Her iki mekanizma da, gerçek false-positive olduğu KANITLANDIKTAN sonra (senkron negatif-kontrol fixture'larıyla — bkz. commit `32517cf`), AYRI bir "test-harness düzeltme" turunda, minimal ve kapsamı sıkı tutularak düzeltildi: satır-bazlı diff yerine git'in kendi token/word-level diff algoritması (`git diff --no-index --word-diff=porcelain`), ve repo-geneli git-status kontrolü yerine "sahip olunan" (owned-scope) şablon dosyalarının kendi içeriğine bakan bir kontrol.

**Kural (bu olaydan çıkarılan, kalıcı):**
1. Test ASLA bypass edilmez (skip/xfail ile borç gizlenmez).
2. Bir testin false-positive olduğu İDDİA edilmez — senkron/izole negatif-kontrol fixture'larıyla KANITLANIR (gerçek pozitif senaryonun hâlâ yakalandığı da ayrıca kanıtlanır).
3. Harness düzeltmesi, onu tetikleyen özellik değişikliğinden AYRI bir commit/dalgada, dar kapsamda yapılır — özellik değişikliğiyle karıştırılmaz.

---

## 15. Security

- **Authentication/Authorization/Role matrix:** bkz. §2 "Ortak altyapı" tablosu.
- **CSRF:** Flask-WTF `CSRFProtect`, PWA/iOS için özel oturum-yenileme hata işleyicisi.
- **CSP + nonce:** `app/security/headers.py` — script-src varsayılan olarak `unsafe-inline` içermez, nonce inline etiketlere uygulanır.
- **Host validation:** `TRUSTED_HOSTS`, prod/staging'de literal `'*'` yasak; `ProxyFix` tek güvenilir proxy hop'u onurlandırır.
- **Rate limiting:** Flask-Limiter, varsayılan `200/dk`; ayrıca login-özel throttle (`LOGIN_IP_MAX_ATTEMPTS=12`, `LOGIN_IDENTITY_MAX_ATTEMPTS=6`, `LOGIN_LOCKOUT_MINUTES=15`, `LOGIN_CAPTCHA_THRESHOLD≥3`).
- **Secret gate:** `scripts/quality/bys360_secret_repo_gate.py` — git-native aday modeli (tracked + staged + untracked-ama-gitignore'da-olmayan), hardcoded secret-key atamalarını (`SECRET_KEY`, `DATABASE_URL`, `TCKN_ENCRYPTION_KEY`, `SENTRY_DSN`, vb.) ve yasaklı repo eserlerini (gerçek `.env` vb.) tarar; placeholder kelime allowlist'i (yanlış-pozitifleri önlemek için) ve `len(value)<16` sezgisiyle çalışır.
- **TCKN encryption:** `TCKN_ENCRYPTION_KEY` ile şifreleme; eksikse yalnız uyarı (fail-fast değil) — prod'da mutlaka ayarlanmalı.
- **Audit trail:** `app/security/audit.py` (kritik operasyonlar için).
- **File upload validation:** `app/security/upload_security.py` — `UPLOAD_STRICT_MIME_VALIDATION=true` varsayılan; Dosya Merkezi'nde opsiyonel ClamAV taraması.
- **Video URL host validation / YouTube spoof koruması:** bkz. §16.
- **Sentry opsiyonel davranış:** `SENTRY_REQUIRED_IN_PRODUCTION=false` varsayılan — DSN boşsa hata izleme sessizce kapalı kalır, boot engellenmez; DSN ayarlanırsa placeholder-görünümlü değerler reddedilir.

**KVKK bağlamı (repo belgeleriyle desteklenen):** `docs/handover/BYS360_GUVENLIK_KVKK_NOTLARI.md` — minimum veri toplama, RBAC, performans verisinin yayınlanana/onaylanana kadar gizli tutulması, AI'nin yalnız danışma amaçlı (insan denetimli) olması, kritik operasyonlarda audit log, `.env`/DB dump/logların release paketine ASLA girmemesi. Rol bazlı görünürlük tablosu mevcuttur (Personel/Amir/Koordinatör-Grup Başkanı/Başkan-Admin).

**⚠️ Kanıtsız iddia uyarısı:** Repository içinde resmi bir **ISO 27001** veya **ISO 42001** sertifikasyon kanıtı (denetim raporu, sertifika numarası, sertifikasyon kuruluşu adı) BULUNAMADI. Bu belge böyle bir sertifikasyonun VAR olduğunu iddia ETMEZ — yalnız KVKK'ya duyarlı tasarım pratiklerinin repo belgelerinde desteklendiğini belirtir.

---

## 16. Portal Video

**Canlı davranış (bu dalganın konusu):** Portal composer'da üç medya seçeneği yan yana durur — **Fotoğraf ekle**, **Video dosyası**, **Video bağlantısı**. Video bağlantısı YouTube (`youtube.com`, `youtu.be`, `youtube-nocookie.com`, `m.youtube.com`, `music.youtube.com`) ve Vimeo (`vimeo.com`, `player.vimeo.com`) linklerini kabul eder.

**Backend (REPO-VERIFIED, `app/portal/routes.py`):** `_portal_video_embed_url(raw_url)` — host allowlist doğrulaması yapar, güvenli embed URL'i üretir (`youtube-nocookie.com` kullanır, izleme çerezlerini azaltmak için). `_save_portal_video_link(post, raw_url)` — doğrulanmış linki `PortalPostAttachment` olarak kaydeder. Feed render'ında `<iframe>` `sandbox` ve `referrerpolicy` ile güvenli şekilde gömülür (`app/templates/portal/_post_card.html`).

**Host spoof koruması:** `youtube.com.attacker.example` gibi prefix-spoof denemeleri, `notyoutube.com` gibi lookalike host'lar, `javascript:`/`data:` şema denemeleri, raw `<iframe>` markup enjeksiyonu — hepsi reddedilir (`tests/security/test_portal_video_link_host_validation_negative.py`, 31 test).

**CSS görünürlük kök nedeni (HISTORICAL, bu dalgada bulunup düzeltildi):** `.portal-media-tools` ve `.bys360-v2121-media-tools` grid container'ları çıplak `1fr` track kullanıyordu. CSS spec'ine göre çıplak `1fr`, `minmax(auto,1fr)`'e çözümlenir ve track, içeriğin min-content genişliğinin ALTINA küçülemez. İki dosya-yükleme `<input type="file">` alanının geniş min-content genişliği yüzünden grid'in TOPLAM hesaplanan genişliği container'ı aşıyor, üçüncü sütunu (video bağlantısı) ekran dışına itiyor ve `.portal-composer-card{overflow:hidden}` tarafından görünmez şekilde kırpıyordu. Alan `display:block`/`visibility:visible` kalıyordu — yüzeysel görünürlük kontrolleri geçiyordu — ama gerçek layout konumunda kullanıcı tarafından erişilemezdi.

**Düzeltme:** `grid-template-columns` bildirimlerinde `1fr` → `minmax(0,1fr)` (standart grid-track-taşma düzeltmesi). Gerçek render edilmiş DOM üzerinde hem masaüstü (1440px, 3 eşit 125px sütun) hem mobil (375px, tek sütun, sıfır yatay taşma) genişlikte doğrulandı; `getBoundingClientRect()` VE daha katı `checkVisibility()` API'si ile.

**Canlı kullanıcı kabulü:** OPERATOR-ATTESTED (bkz. §0) — canlı Portal composer'da üç alan da görünür, video-link alanı operatör tarafından manuel test edildi.

---

## 17. Performance Module Rules

**Kanıt kaynağı sınırlaması:** Bu bölüm yalnız repository'de doğrudan bulunan/onaylanmış iş kurallarını içerir. Repoda AÇIKÇA doğrulanmamış hiçbir iş kuralı burada iddia EDİLMEZ.

- **Değerlendirme sırası ve amir görüşü zinciri:** `app/services/performance/process_engine_phase6_president_approvals.py` dosya adı, sürecin "Başkan Onayları" adımı içerdiğini doğrular — süreç motoru, çok-adımlı bir amir/yönetici onay zinciri olarak modellenmiştir (`app/services/performance/*` altında `reason_codes`, `low_score_process_service` gibi ayrı modüller de mevcuttur).
- **Düşük skor süreci:** `app/models/performance_low_score_models.py` ve `app/services/performance/low_score_process_service.py` dosyalarının varlığı, sistemde ayrı bir "düşük skor" (repoda "<70" için özel bir sayısal eşik doğrudan doğrulanamadı — YALNIZ ayrı bir süreç/model dosyasının VARLIĞI doğrulanabildi) sürecinin ayrı bir iş akışı olarak ele alındığını gösterir.
- **Arşiv (archive):** `app/models/performance_archive_models.py` ve `app/templates/performance/archive/` (5 şablon dosyası, release builder'ın açıkça KORUDUĞU bir dizin — bkz. §12) — geçmiş değerlendirme dönemlerinin arşivlendiği ayrı bir alt sistem doğrulanmıştır.
- **Vekalet:** `app/institutional/hr_personnel_delegation_routes.py` dosyasının varlığı, personel/İK tarafında bir vekalet (delegasyon) mekanizması olduğunu doğrular; bu mekanizmanın Performans modülünün amir-onay zincirine NASIL entegre olduğu bu araştırma turunda tek tek doğrulanmadı.
- **Dönemler (periods), gelişim önerileri (development suggestions):** `phase10_development_guidance_ui.py` dosya adı "gelişim rehberliği" (development guidance) özelliğinin var olduğunu doğrular; menü anahtarı `performance_development_guidance`.
- **Hatırlatmalar (reminders):** menü anahtarı `performance_meeting_p3_reminders` ("Hatırlatma ve Aksatan Amirler"), `app/services/performance/reminder_notification_service.py`, `phase9_reminder_policy.py`, `phase10_reminder_notification_center.py`, ayrıca `app/services/ai_decision/reminder_integration.py`/`reminder_policy.py` (AI Karar Destek entegrasyonu).
- **Notlar (interim notes):** menü anahtarı `performance_interim_notes` ("Dönem İçi Notlar"), `app/services/performance/scorecard_midterm_notes.py`, `interim_notes_runtime.py`, `interim_feedback_policy.py`.

**⚠️ Bu belge, "<70 süreci", ">90 çok başarılı" gibi SAYISAL eşikleri veya "üçüncü amir" gibi organizasyonel detayları, bu araştırma turunda repo içinde doğrudan doğrulanan bir kaynak (config değeri, sabit tanım, veya açık dokümantasyon cümlesi) BULUNAMADIĞI için İDDİA ETMEZ.** Yeni operatör, bu spesifik sayısal eşikleri ve organizasyonel akış detaylarını `app/services/performance/` içindeki servis kodunu doğrudan okuyarak veya sistemin mevcut iş sahibiyle (product owner) doğrulayarak tamamlamalıdır.

---

## 18. Scheduled Task Envanteri

**⚠️ OPERATOR-ATTESTED bölüm — bu dokümantasyon oturumunun canlı Windows Görev Zamanlayıcı'ya erişimi YOKTUR.** Aşağıdaki durum tablosu operatör tarafından bildirilmiştir; repo'daki installer script kanıtlarıyla çapraz referanslanmıştır.

| Görev Adı | Bildirilen Durum | Repo'da installer kanıtı |
|---|---|---|
| BYS360 CIC Auto Mail Scheduler | Ready | `install_bys360_cic_auto_mail_scheduler_task.ps1` — REPO-VERIFIED |
| BYS360 CIC Staff Noon Mail 1300 | Disabled | — (adı bu araştırma turunda tek başına doğrulanamadı) |
| BYS360 Daily Weather Personnel Mail | Ready | `install_bys360_daily_mail_tasks_v1_4.ps1` / `install_bys360_daily_weather_mail_task.ps1` — REPO-VERIFIED |
| BYS360 Executive Summary 0001 | Ready | `register_bys360_executive_summary_tasks_v2_14_3.ps1` (kanonik; `_v2_14_1.ps1` eski/devreden) — REPO-VERIFIED |
| BYS360 Executive Summary 0830 | Ready | `register_bys360_executive_summary_tasks_v2_14_3.ps1` (kanonik; `_v2_14_1.ps1` eski/devreden) — REPO-VERIFIED |
| BYS360 Internal Test | Disabled | — |
| BYS360 Live 80 | Disabled | — (muhtemelen `BYS360 Live Waitress 80`'in öncülü/eski versiyonu) |
| **BYS360 Live Waitress 80** | **Running** | `install_bys360_live_waitress_80_task_v1.ps1` — REPO-VERIFIED, KANONİK canlı task |
| BYS360 Live Watchdog 80 | Disabled | **Repo'da BU İSİMLE HİÇBİR installer/referans bulunamadı** — yalnız operatör beyanına dayanır |
| BYS360 Performance Mail Reminder 09 | Disabled | **Repo'da BU İSİMLE HİÇBİR installer/referans bulunamadı** — yalnız operatör beyanına dayanır |

**⚠️ KRİTİK UYARI:**
- **Watchdog** (`BYS360 Live Watchdog 80`) **deprecated ve disabled** olarak bildirilmiştir — yanlışlıkla yeniden AKTİF EDİLMEMELİDİR.
- **Performance Mail Reminder 09** disabled olarak bildirilmiştir — yanlışlıkla yeniden AKTİF EDİLMEMELİDİR.

**Ek tarihsel not (REPO-VERIFIED, `HANDOVER_10_10_EVIDENCE_20260708.md`, 2026-07-08 tarihli anlık görüntü):** "BYS360 Portal Press News Scan V3A" görevi o tarihte artık YOKTU ("görev artık yok") — bu envanterde de görünmemelidir. Bu 2026-07-08 belgesi güncel bir kaynak DEĞİLDİR, yalnız tarihsel bir kontrol noktasıdır; canlı görev envanteri her zaman doğrudan Görev Zamanlayıcı'dan (`Get-ScheduledTask`) teyit edilmelidir.

---

## 19. Logging / Incident Response

**Log yolları:**

| Log | Yol |
|---|---|
| Live Waitress startup/runtime log | `C:\bys360\logs\bys360_live_waitress_80.log` (installer script'te sabit tanımlı) |
| Deployment receipts | `C:\bys360\logs` altında (§11 adım 26) |
| Uygulama genel logu | `.env`'deki `BYS360_LOG_DIR` (varsayılan `logs`) |
| Kalite/CI raporları | `reports/quality/` (repo içi, geçici) |

**Kritik pattern'ler (bir deployment/health taramasında ARANMALI):**

```
Traceback
UnicodeEncodeError
TemplateNotFound
OperationalError
ModuleNotFoundError
ImportError
RuntimeError
PermissionError
Address already in use
```

**Güvenlik-kritik regex:** `critical=[1-9][0-9]*` — yalnız 1 veya daha büyük bir sayı eşleşmelidir. **`critical=0` bir eşleşme DEĞİLDİR ve yanlış-pozitif olarak SAYILMAMALIDIR** — sıfır kritik hata, temiz bir durumun beklenen ifadesidir, alarm tetiklememelidir.

**İlk müdahale (BYS360_BAKIM_RUNBOOK.md'den, "beyaz ekran" senaryosu):** `/healthz` kontrolü → task durumu (`Get-ScheduledTask`) → log'da yukarıdaki pattern'ler → gerekirse §20 rollback prosedürü.

---

## 20. Rollback

**Application rollback ve DB rollback KESİN OLARAK AYRIDIR — birbirine karıştırılmaz.**

- **Migration çalışmadıysa (veya deployment migration İÇERMİYORSA): DB rollback YAPILMAZ.** Yalnız kod (application) rollback yeterlidir.
- **Migration çalışıp başarısız olduysa:** Önce kodu geri al (aşağıya bakın), sonra §10'daki `pg_restore` prosedürüyle DB'yi migration-öncesi yedekten geri yükle — bu YETKİLİ ONAY ve planlı kesinti gerektirir, otomatik değildir.

### Release rollback karar ağacı

```
Sorun tespit edildi
        │
        ▼
Sorun kod mu, DB mi, yoksa altyapı mı (Redis/SMTP/vb.)?
        │
   ┌────┼────┐
  Kod   DB   Altyapı
   │     │      │
   ▼     ▼      ▼
 Aşağı  Migration  Task/servis
 bak    rollback   yeniden
        (yukarı)   başlat,
                   DB/kod'a
                   DOKUNMA
```

**Kod rollback:** Körlemesine "eski bir zip'i geri yükle" YAPILMAZ. **Yalnız daha önce `--verify` ile doğrulanmış, geçerliliği kanıtlanmış bir release paketi kullanılır** (SHA256 + manifest doğrulaması geçmiş). `scripts\windows\rollback_bys360_live_release_v1.ps1 -Apply` ile, en son `predeploy_<timestamp>` yedeğinden geri dönülür.

---

## 21. GitHub / Branch / Release Workflow

Bu proje boyunca fiilen kullanılan ve doğrulanmış geliştirici akışı:

```
1. branch     → yeni/mevcut bir çalışma dalı (worktree ile izole edilebilir)
2. change     → kod değişikliği (minimal, kapsamı net)
3. focused    → değişikliğin doğrudan etkilediği testler
   tests
4. full gates → Ruff, mypy, secret gate, Step1, Step2 (TAM, 0 failed şart)
5. commit     → açık pathspec ile stage (`git add -- <dosya>`, ASLA `git add -A`/`.`)
6. push       → normal push (force/rebase/amend YASAK), yalnız açık kullanıcı onayıyla
7. exact-head → Quality + Score100 workflow'ları, checkout SHA'sı hedef commit ile
   CI            BİREBİR eşleşmeli (bkz. §13)
8. package    → scripts/release/build_bys360_safe_release.py, deterministik doğrulama
9. parallel   → independent SHA256, clean-room extraction, required/forbidden audit
   proof
10. deployment → §11'deki runbook, yalnız açık onayla
11. live       → canlı ortamda gerçek kullanıcı ekranı/DOM doğrulaması (string-grep
   acceptance    YETERLİ DEĞİL)
```

**Force push yasağı:** Bu proje boyunca hiçbir aşamada `--force`/`--force-with-lease` kullanılmadı. **Kontrollü fast-forward:** Bir dalga diğerinin üzerine, `git merge --ff-only <sha>` ile entegre edilir (merge commit/rebase/cherry-pick OLMADAN) — yalnız hedef commit gerçekten mevcut HEAD'in doğrudan devamıysa çalışır, aksi halde DURUR.

**Scope verification:** Her commit'ten önce `git diff --stat` ile değişen dosya listesi, beklenen kapsamla (yalnız ilgili modülün dosyaları) karşılaştırılır — beklenmeyen bir dosya varsa commit YAPILMAZ.

---

## 22. Documentation Map

| Belge | Amaç | Kim okumalı | Bu ana dosyayla ilişkisi |
|---|---|---|---|
| `README.md` | Hızlı genel bakış, kurulum özeti | Herkes (ilk okuma) | Bu belge daha kapsamlı bir SÜPERSET'tir |
| `ARCHITECTURE.md` | **DİKKAT: gerçek bir mimari belge DEĞİL** — 2026-06-13 tarihli iki süreç-disiplini kararı (wildcard-import temizliği, SAFE/HOTFIX/OVERLAY belge üretiminin durdurulması) | Süreç geçmişi merak eden | Bu ana dosyanın §2'si asıl mimari kaynaktır |
| `STATUS.md` | Kronolojik "Faz" değişiklik günlüğü — **son kayıtlı girdi 2026-07-15, bu worktree'nin (`phase5-*`) daha sonraki işini YANSITMIYOR, güncelliği şüpheli** | Geçmiş faz kararlarının detayını arayan | Güncel durum için bu ana dosya + `git log` kullanılmalı |
| `CONTRIBUTING.md` | Yeni geliştirici onboarding, modül haritası, kod kuralları | Yeni geliştirici | Bu ana dosyanın §4/§23'ü ile örtüşür, tamamlayıcıdır |
| `SECURITY.md` | Güvenlik ilkeleri (bu turda içerik detaylı okunmadı — varlığı doğrulandı) | Güvenlik incelemesi yapan | §15 ile birlikte okunmalı |
| `DEPLOYMENT.md` | **Kanonik, GÜNCEL (2026-08-23) deployment prosedürü** | Deployment yapan operatör | Bu ana dosyanın §11'i DEPLOYMENT.md'yi temel alır ve genişletir |
| `BACKUP_RUNBOOK.md` | **Kanonik, GÜNCEL (2026-08-15) yedekleme/restore prosedürü** | Operatör | Bu ana dosyanın §10'u bunu temel alır |
| `docs/handover/*.md` (BAKIM_RUNBOOK, CANLIYA_ALMA_REHBERI, RISK_VE_SUREKLILIK_PLANI, KURULUM_REHBERI, MODUL_ENVANTERI, GUVENLIK_KVKK_NOTLARI, DEVIR_PAKETI_V1) | **SUPERSEDED** — 2026-06-24 tarihli, kök dizindeki DEPLOYMENT.md/BACKUP_RUNBOOK.md'nin daha eski/hafif versiyonları. İçerik ÇELİŞKİLİ değil, yalnız daha eski. | Tarihsel bağlam | Bu ana dosya bunların yerini alır (bkz. §33 index) |
| `docs/handover/HANDOVER_10_10_EVIDENCE_20260708.md` | **HISTORICAL** — 2026-07-08 tarihli, "10/10 V6" anlık kanıt görüntüsü | Tarihsel kanıt arşivi | Güncel değil, yalnız o tarihki durumun kaydı |
| `docs/governance/*` | Kalite puanlama metodolojisi, teknik borç politikası, historical governance kararları | Kalite/skor sorularını inceleyen | §26'da özetlenmiştir |
| `docs/security/BYS360_SECRET_ROTATION_AND_HISTORY_CLEANUP_RUNBOOK.md` | Secret sızıntısı durumunda git-history temizleme prosedürü | Güvenlik olayı müdahalesi | §15/§31 ile birlikte okunmalı |
| `docs/architecture/*` | Route mimarisi envanteri ve mobil route bölme raporları (P1A-P1E) | Refactor geçmişini inceleyen | §2'de özetlenmiştir |

---

## 23. New Developer First Day — İlk Gün Kontrol Listesi

```
[ ] 1. Repo clone edildi
[ ] 2. Python 3.12 doğrulandı (`python --version`)
[ ] 3. venv oluşturuldu ve aktive edildi
[ ] 4. `pip install -r requirements.txt` ve `requirements-dev.txt` tamamlandı
[ ] 5. `.env.example` → `.env` kopyalandı, en az DATABASE_URL/SECRET_KEY/APP_ENV dolduruldu
[ ] 6. Local DB erişimi kuruldu (SQLite dosya-tabanlı, `:memory:` DEĞİL)
[ ] 7. `flask db upgrade` çalıştırıldı
[ ] 8. `python run.py` ile local başlatma başarılı, `/login` açılıyor
[ ] 9. `/healthz` 200 dönüyor
[ ] 10. Step1 + odaklı bir test dosyası çalıştırıldı, PASS görüldü
[ ] 11. Bu ana dosyanın §2 (Mimari) ve §4 (Local Dev) bölümleri okundu
[ ] 12. SECURITY.md ve bu dosyanın §15'i okundu
[ ] 13. §12 (Release Builder) çalışma mantığı anlaşıldı (henüz kendisi çalıştırılmadı)
[ ] 14. Üretim erişimi almadan ÖNCE §11 (Deployment Runbook) ve §20 (Rollback) baştan sona okundu
[ ] 15. §34 (Dosya Merkezi) okundu; Dosya Merkezi storage yapısı ve 19 tablosunun `10858a18e9ac` migration'ı ile Alembic'e dahil edildiği (§34.7, HISTORICAL/RESOLVED) anlaşıldı
[ ] 16. Dosya Merkezi guest/share güvenlik mekanizması (token+parola, `app/file_center/permissions.py`) incelendi
[ ] 17. Dosya Merkezi ile ilgili mevcut testler çalıştırıldı: `python -m pytest tests/security/test_file_center_v1l_hardening_static.py tests/security/test_file_center_sidebar_v1n_static.py tests/security/test_csp_wave9_file_center_contract.py -v`
```

---

## 24. 30 / 60 / 90 Gün Bakım Planı

**30 gün:**
- Loglar taranır (§19'daki kritik pattern'ler için)
- `/healthz` (local + public) manuel kontrol
- Son yedeklerin (`C:\bys360\backups`) varlığı ve boyutu doğrulanır
- Bağımlılık taraması gözden geçirilir (`pip-audit` CI çıktısı)

**60 gün:**
- Gerçek bir **restore drill** yapılır (bir TEST ortamında, hem kod hem DB restore denenir — yalnız dosyanın var olduğunu kontrol etmek YETERLİ DEĞİLDİR)
- İzin/rol matrisi spot-check (Ayarlar > Yetki Matrisi üzerinden birkaç kullanıcı örneklem kontrolü)
- CI workflow'larının (Quality, Score100) son durumları gözden geçirilir
- Dokümantasyon drift kontrolü — bu ana dosyadaki komutlar/yollar hâlâ doğru mu

**90 gün:**
- Tam bir **disaster recovery simülasyonu** (bkz. §28)
- Güvenlik incelemesi (CSP/CSRF/rate-limit ayarları, secret rotasyon ihtiyacı)
- Teknik borç kaydı gözden geçirilir (`docs/governance/BYS360_TECHNICAL_DEBT_POLICY.md`, `config/quality/bys360_technical_debt_registry.json`)
- Tam bir **handover simülasyonu** — yeni/farklı bir kişi bu belgeyi takip ederek sıfırdan local kurulum yapabiliyor mu

---

## 25. Bus Factor / Devredilebilirlik

**"BYS360 neden kişiye bağlı değildir":**

| Kanıt | Nerede |
|---|---|
| Kaynak kontrolü | Git, tam commit geçmişi, `origin/phase5-critical-lint-clean-v1` |
| Deterministik release | `scripts/release/build_bys360_safe_release.py` — aynı commit için byte-birebir aynı zip (bu oturumda ampirik olarak kanıtlandı) |
| Dokümante edilmiş deployment | `DEPLOYMENT.md`, `BACKUP_RUNBOOK.md`, bu ana dosyanın §11'i |
| Database migration geçmişi | `migrations/versions/` — 74 dosya, tam Alembic zinciri, tek head |
| Otomatik testler | 4000+ test (Step1 554 + Step2 ~4049), 14 ayrı test ailesi |
| CI kapıları | Quality + Score100, exact-head kuralıyla |
| Operasyonel runbook'lar | Bu ana dosyanın §9-§20 arası bölümleri |
| Backup/restore | `BACKUP_RUNBOOK.md` + `rollback_bys360_live_release_v1.ps1` (dry-run varsayılan, kanıtlanmış otomasyon) |
| Ortam dokümantasyonu | `.env.example`, `.env.docker.example`, bu ana dosyanın §5'i |
| Modül dokümantasyonu | Bu ana dosyanın §2'si |
| Release receipt'leri | Manifest + SHA256SUMS her paket için, `C:\bys360\releases` |
| Exact-head doğrulama | §13 — "succeeded" tek başına yetmez, SHA eşleşmesi zorunlu |

---

## 26. Known Limitations / Debt

**CURRENT (aktif, bilinen):**
- `app/services/settings/effective_menu.py` (2111 satır) ve `app/services/corporate_information_center.py` (2764 satır) hâlâ "kritik dev dosya" (god file) sınıfında — mobil route'larda yapılan başarılı bölme (P1B-P1E) örneği henüz bunlara uygulanmadı.
- `docs/handover/*.md` seti (§22'de listelenen 7 dosya) 2026-06-24'ten beri güncellenmemiş — kök dizindeki `DEPLOYMENT.md`/`BACKUP_RUNBOOK.md` ile içerik olarak çelişmiyor ama daha eski/hafif.
- STATUS.md son girdisi 2026-07-15 — mevcut `phase5-critical-lint-clean` dalgasının işini yansıtmıyor.
- Mobil login (`/api/mobile/auth/login`) için özel bir throttle mekanizması YOK, yalnız genel 200/dk rate-limit'e tabi (bilinçli kabul edilmiş risk, STATUS.md Faz 2B).
- Windows/Waitress ve Docker/gunicorn olmak üzere iki ayrı deployment yolu repoda bir arada bulunuyor, tek bir belgede uzlaştırılmamış — hangisinin ne zaman kullanılacağı netleştirilmeli.
- `install_bys360_live_waitress_80_task_v1.ps1`, SYSTEM/Highest çalıştırma düzeyini script içinde açıkça ayarlamıyor — canlı görevin gerçek principal'ı doğrudan doğrulanmalı.
- **[HISTORICAL / RESOLVED]** Dosya Merkezi'nin 19 tablosu (önceki bir belge turunda yanlışlıkla 15 olarak sayılmıştı — gerçek sayı `app/models/file_center_models.py` içindeki `__tablename__` sayımıyla 19'dur) tarihsel olarak arşivlenmiş bir tek-seferlik `db.create_all()` script'i (`scripts/archive/pre_handover_20260708/local/create_file_center_tables_local_v1.py`) ile oluşturulmuştu ve hiçbir Alembic migration dosyasında yer almıyordu. Bu boşluk, "Transferability Gap Closure" dalgasında `migrations/versions/10858a18e9ac_adopt_file_center_schema_into_alembic_.py` (parent: `e0efcd07abf7`) ile kapatıldı: sıfırdan bir ortamda `flask db upgrade` artık 19 tabloyu da oluşturur; mevcut/canlı bir veritabanında (tablolar zaten `db.create_all()` ile var) migration'ı `flask db upgrade` çalıştırmak şemayı doğrular ve veri kaybı olmadan "adopt" eder — şema eksik/uyumsuzsa (beklenen kolon/PK yoksa) migration **fail-closed** olarak açık bir hata ile durur, sessizce kabul etmez. Ayrıntı: §34.7.
- **İki ayrı, örtüşen PWA implementasyonu** bulundu: `app/pwa/routes.py` ve `app/pwa_blueprint.py`, ikisi de benzer manifest/service-worker uçları kaydediyor gibi görünüyor — hangisinin kanonik/aktif olduğu bu dokümantasyon dalgası kapsamında netleştirilemedi (kod davranışı değiştirilmedi, yalnız tespit edildi).
- Menü kayıt sistemi (`app/menu_registry.py`, 1514 satır) çalışma zamanında onlarca ardışık `BEGIN/END` blok yamasıyla mutasyona uğratılıyor — statik dosya okuması "gerçek" canlı menüyü tam yansıtmayabilir, yalnız kodu ÇALIŞTIRARAK kesin doğrulanabilir.
- Repoda kodu TAM duran ama aktif olmayan üç modül var (`repository`/Belge-Medya, `education`/Eğitim-İSG, `strategy`/Strateji — `app/config/removed_modules.py`) — bunlar CURRENT/aktif özellik SAYILMAZ, yeni operatör bunları yanlışlıkla aktifleştirmemelidir.

**HISTORICAL (kapanmış, artık aktif borç DEĞİL — aktif borçmuş gibi gösterilmez):**
- Windows UTF-8 cp1252 startup çökmesi — kalıcı olarak düzeltildi (§7), iki katmanlı korumayla.
- Portal video-URL CSS görünürlük hatası — kök nedeni bulunup düzeltildi (§16).
- Release builder'ın `app/templates/performance/archive/` ve `.env.example`'ı yanlışlıkla dışlaması — düzeltildi (§12).
- Test-harness false-positive'leri (Style-2A `!important` diff kontrolü, Meeting "no new CSS" kontrolü) — ayrı, dar kapsamlı bir dalgada düzeltildi (§14).

**Governance/skorlama (HISTORICAL_UNRECONSTRUCTABLE durumu — bkz. §26.1):**
- Documentation-Handover skoru = 85.
- `cb2e57c` (Production Source SHA) için, taze exact-head Quality+Score100 CI kanıtıyla: `LIVE_READINESS_FINAL=98`, `TRANSFERABILITY_FINAL=95` — bu, GERÇEKTEN onaylı bir governance kararı (`BYS360-GOV-CEILING-WAIVER-001`, registry JSON'da `APPROVED`) ile GERÇEK exact-head CI kanıtının bir arada bulunmasından kaynaklanır. Bu kanıt YALNIZ `cb2e57c`'ye özeldir — ondan sonraki her yeni commit (bu dokümantasyon commit'leri dahil), skoru korumak için KENDİ taze exact-head kanıtını ayrıca sağlamalıdır (ayrıntı ve tam kanıt zinciri için bkz. §26.1).

**Bu belge "her şey kusursuz" gibi gerçeği aşan hiçbir ifade KULLANMAZ.** Yukarıdaki liste kasıtlı olarak eksiksiz tutulmaya çalışılmıştır.

### 26.1 Historical Governance Truth (KESİNLİKLE DEĞİŞTİRİLMEDEN KORUNUR)

- **Onaylı durum adı:** `HISTORICAL_UNRECONSTRUCTABLE` (kaynak: `docs/governance/BYS360_GOV_LEGACY_001_DECISION_RECORD.md`, satır 23) — bu durum **ASLA** `FULLY_RECONCILED` olarak yeniden yazılmaz.
- **Yasal borç sayıları:** `historical_legacy_total = 38` (`P0:0, P1:0, P2:17, P3:21`); `MAPPED_LEGACY_OPEN_COUNT = 0`; `UNMAPPED_LEGACY_OPEN_COUNT = 38`.
- **Onaylı karar kaydı:** `BYS360-GOV-LEGACY-001` (2026-08-21/22/23) — bu kararın skor üzerindeki tek başına etkisi `governance_only_final_score_delta = 0`.

- **⚠️ İKİNCİ DÜZELTME — bu bölümün BİR ÖNCEKİ versiyonu da hatalıydı.** Bu ana dosyanın ikinci versiyonu, `BYS360-GOV-CEILING-WAIVER-001`'in "onaylı/aktif bir waiver OLARAK DOĞRULANAMADI" dediğinde, yalnız `docs/governance/BYS360_GOV_HISTORICAL_GAP_ACCEPTANCE_POLICY_V1.md` (politika BELGESİ) okunmuştu — asıl KARAR KAYDININ, bu politika belgesinden SONRA, `config/quality/bys360_technical_debt_registry.json` (registry_version 1.1.0) dosyasının `reconciliation_ceiling_waiver_decision` alanına YAPISAL/makine-okunur bir onay olarak (Markdown değil, JSON alanı olarak) işlendiği GÖZDEN KAÇIRILMIŞTI. Bu, eksik araştırmanın sonucuydu — belge dosyaları tarandı, registry JSON'ının bu spesifik alanı taranmadı.

- **GERÇEK, TAM DOĞRULANMIŞ DURUM (registry dosyasından doğrudan okunmuştur):**
  ```
  config/quality/bys360_technical_debt_registry.json → reconciliation_ceiling_waiver_decision:
    decision_id            = BYS360-GOV-CEILING-WAIVER-001
    decision_status         = APPROVED
    approval_mode           = HUMAN_EXPLICIT_TOKEN
    approval_token          = "APPROVE BYS360-GOV-CEILING-WAIVER-001"
    approval_date           = 2026-08-23
    approver_role           = HUMAN_PROJECT_OWNER
    policy_id                = FORMAL_HISTORICAL_GAP_ACCEPTANCE_POLICY_V1
    decision_record_reference = docs/governance/BYS360_GOV_HISTORICAL_GAP_ACCEPTANCE_POLICY_V1.md
  ```
  Bu karar kaydı **GERÇEK ve ONAYLI**dır — insan proje sahibi tarafından açık bir onay token'ıyla onaylanmış. **Ancak** kaydın kendi `canonical_eligibility_note` alanı çok açık: *"DECISION_RECORD_PRESENT=YES, CANONICAL_WAIVER_ELIGIBILITY ile AYNI ŞEY DEĞİLDİR."* Karar kaydının VAR OLMASI tek başına hiçbir commit için tavanı kaldırmaz — `scripts/quality/bys360_score_reconcile_v1.py`'nin `waiver_active` hesaplaması (satır 851-861), skorlanan HER COMMIT için AYRI AYRI, aşağıdaki 8 koşulun TAMAMININ bağımsız ve taze şekilde sağlanmasını şart koşar:

  ```python
  waiver_active = (
      fully_verified                                                  # 1) hiçbir kapı UNKNOWN değil
      and registry_structurally_valid                                 # 2) registry kendi şemasını geçiyor
      and registry_commit_verified                                    # 3) registry içeriği skorlanan commit'in GERÇEK git tree'siyle eşleşiyor
      and isinstance(ceiling_waiver, dict)                             # 4) karar kaydı VAR
      and ceiling_waiver.get("decision_status") == "APPROVED"          # 5) karar ONAYLI
      and registry.get("reconciliation_status") == "HISTORICAL_UNRECONSTRUCTABLE"  # 6)
      and registry_validation.registry_counts.get("REGISTRY_ACTIVE_COUNT") == 0    # 7) açık teknik borç yok
      and _score100_evidence_verified(canonical_manifest, scored_commit)          # 8) SKORLANAN COMMIT'İN KENDİ taze, exact-head Score100 kanıtı
  )
  ```

- **§3 sorusunun KESİN, DOĞRULANMIŞ cevabı — bu sefer gerçekten kanıtla:** `cb2e57c5d1829ea743c696ae78595a20755f3f07` için hesaplayıcı **İKİ KEZ, bizzat** çalıştırıldı — bir kez dış kanıt OLMADAN (Run A), bir kez `--evidence-file` ile gerçek, genuinely-inspected exact-head Quality+Score100 CI ekran görüntüsü kanıtı (§13'te zaten doğrulanmış olan aynı ekran görüntüleri, `evidence_type=REMOTE_CI_VERIFIED`, `provenance=USER_SUPPLIED_REMOTE_PROOF`) verilerek (Run B). Yukarıdaki 8 koşulun TAMAMI bağımsız olarak doğrulandı: `registry_structurally_valid` (registry gate: 0 finding), `registry_commit_verified=True` (uygulama dosyaları `cb2e57c` ile mevcut HEAD arasında `git diff --stat` ile birebir aynı — dokümantasyon-only commitler registry'yi değiştirmedi), `REGISTRY_ACTIVE_COUNT=0` (14/14 kapalı, doğrudan sayıldı), `approval_baseline_commit=fe984cf1...` gerçek bir commit (`git cat-file -t` ile doğrulandı).

  **Sonuç: `waiver_active=True` GERÇEKTEN ve MEŞRU şekilde hesaplanıyor — bu bir "var olmayan waiver'ı diriltme" değil, gerçekten onaylı bir kararın, kendi tasarlanmış koşullarını GERÇEKTEN karşılayan bir commit için GERÇEKTEN tetiklenmesidir.**

- **Kanıtsız (Run A, evidence-less) vs. kanıtlı (Run B, evidence-aware) tam karşılaştırma — `cb2e57c` için:**

  | Metrik | Evidence-limited (Run A) | Evidence-aware RAW (Run B) | Governance FINAL (Run B) |
  |---|---|---|---|
  | Code Quality | 100.0 | 100.0 | 100.0 |
  | Test Assurance | 91.05 | 91.05 | 91.05 |
  | Security | 60.0 (dependency_audit=UNKNOWN) | 100.0 (dependency_audit=PASS, REMOTE_CI_VERIFIED) | 100.0 |
  | CI-Release | 60.0 (postgres_migration_integrity_gate=UNKNOWN) | 100.0 (PASS, REMOTE_CI_VERIFIED) | 100.0 |
  | Operations | 100.0 | 100.0 | 100.0 |
  | Documentation-Handover | 85.0 | 85.0 | 85.0 |
  | Maintainability | 100.0 | 100.0 | 100.0 |
  | **LIVE_READINESS** | raw=80.4705, final=**80** | raw=**97.6705** | final=**98** |
  | **TRANSFERABILITY** | raw=88.289, final=**88** | raw=**95.089** | final=**95** |

  ```
  CURRENT_CEILING        = 89 (metodolojide sabit, değişmedi)
  CEILING_APPLIED         = Run A: True (numerik olarak bağlayıcı değildi, ikisi de zaten 89 altındaydı) / Run B: False (waiver_active=True olduğu için tavan hiç uygulanmadı)
  ACTIVE_WAIVER (bu commit için) = Run A: False / Run B: True
  GOVERNANCE_RECORD        = BYS360-GOV-CEILING-WAIVER-001 (APPROVED, registry JSON'da), BYS360-GOV-LEGACY-001 (APPROVED, ayrı ve öncül karar)
  CANONICAL_EVIDENCE_COMPOSITION (Run B) = 10 REMOTE_CI_VERIFIED gate + 1 REGISTRY_DERIVED gate, 0 UNKNOWN, 0 EVIDENCE_CONFLICT, completeness=FULL
  ```

  Rapor dosyaları (bu makineye özel geçici konum, komutlarla yeniden üretilebilir):
  - Run A: `C:/bys360_pytest_tmp/score_evidenceless_cb2e57c.json`
  - Run B: `C:/bys360_pytest_tmp/score_evidenceaware_cb2e57c.json`
  - Kanıt dosyası: `C:/bys360_pytest_tmp/bys360_canonical_evidence_cb2e57c.json`

- **⚠️ Bu waiver'ın kapsamı — GENELLEŞTİRİLMEMELİDİR:** `waiver_active`, registry'deki karar kaydının VARLIĞINA rağmen, HER commit için OTOMATİK DEĞİLDİR. Koşul #8 (`_score100_evidence_verified`), skorlanan COMMIT'İN KENDİ taze exact-head Score100 kanıtını gerektirir. Gelecekte yeni bir commit geldiğinde (örn. bu dokümantasyon dalgasının kendi commit'leri `6188d39`/`9cb91d2`/bu düzeltme), o commit için AYRI, TAZE exact-head Quality+Score100 CI kanıtı sağlanmadan `waiver_active` tekrar `False`'a düşer (nitekim `6188d39` için evidence-less çalıştırıldığında tam olarak bu gözlemlendi: `waiver_active=False`, final=80/88). **Bu belgenin CURRENT olarak sunduğu `LIVE_FINAL=98`/`TRANSFER_FINAL=95`, özellikle ve yalnızca `cb2e57c5d1829ea743c696ae78595a20755f3f07` (Production Source SHA) için, o commit'in kendi exact-head CI kanıtıyla birlikte geçerlidir** — dokümantasyon-only commit'ler (`6188d39`, `9cb91d2` ve bu düzeltme) uygulama hazırlık skorunu ARTIRMAZ/DEĞİŞTİRMEZ, çünkü uygulama dosyaları (`app/`, `tests/`, `scripts/`, `config.py`, vb.) `cb2e57c` ile bu belgenin kendisi de dahil sonraki tüm commit'ler arasında birebir aynıdır (`git diff --stat` ile doğrulandı).

---

## 27. Mobile

**Repo kanıtı:** `app/api/mobile/` (REST API, `domains/*` alt paketlerine bölünmüş — bkz. §2), README.md'de "Flutter mobil istemci" ifadesi geçiyor, `mobile_flutter` adlı bir dizin/referans release builder'ın yasaklı-dizin listesinde mevcut (yani repo içinde bir Flutter proje dizini VAR, ancak bu araştırma turunda içeriği detaylı incelenmedi).

**Bu belgenin net ayrımı:**
- **Mevcut, çalışan:** Mobil REST API (`app/api/mobile/routes.py` + `domains/*`, mobil auth/dashboard/notification/personel-okuma/support-anket-yazma/assistant-chat/communication/personel-yazma/KPI uçları) — bu, gerçek, canlı bir API yüzeyidir.
- **Responsive web:** Ana web arayüzünün mobil tarayıcıda kullanılabilirliği (bu belgede ayrıca doğrulanmadı, ancak modern bir Flask/Jinja + CSS stack'inde tipik olarak beklenir).
- **Flutter/native:** Repo içinde bir Flutter proje dizini referansı bulunsa da, **bu belge bunun üretim durumunu (tamamlanmış mı, App Store/Play Store'da mı, hangi aşamada) İDDİA ETMEZ** — bu araştırma turunda doğrulanmadı. **Tamamlanmamış/gelecekteki bir iş, üretim yeteneği gibi SUNULMAZ.**

Yeni operatör, mobil istemcinin (Flutter) gerçek dağıtım durumunu ayrı olarak doğrulamalıdır.

---

## 28. AI / Decision Support

**Rolü:** BYS360'daki AI, **öneri, analiz ve rehberlik** sağlar — **nihai kurumsal karar verici DEĞİLDİR**. İki ayrı alt sistem:

1. **AI Karar Destek** (`app/ai/`, `app/admin/ai_*_routes.py`, `app/services/ai/*`) — performans/analiz panellerinde öneri üretir.
2. **Sanal Asistan** (`app/ai_agent/`, `app/services/ai_agent/*`) — sohbet arayüzü.

**Kritik mimari gerçek (REPO-VERIFIED):** `config.py`'de `AI_PROVIDER_MODE` **varsayılan olarak `'stub'`**dır — yani AI özellikleri **varsayılan kurulumda gerçek bir LLM'e BAĞLANMAZ**, `StubAIClient` adlı deterministik bir sınıf kullanır. Gerçek bir sağlayıcıya (`OpenAICompatibleAIClient`) bağlanmak için `AI_API_KEY` ve `AI_PROVIDER_MODE` açıkça ayarlanmalıdır.

**İnsan onayı / yetki modeli korunur:** Performans modülündeki amir-onay zinciri (`process_engine_phase6_president_approvals.py`) ve genel yetki matrisi (`app/services/settings/effective_menu.py`), AI önerilerinden BAĞIMSIZ olarak çalışır — AI hiçbir yerde otomatik onay/red kararı VERMEZ, yalnız insan karar vericiye girdi sağlar.

---

## 29. Disaster Recovery Checklist

Sunucu tamamen kaybedildiğinde, sıfırdan geri dönüş sıralı adımları:

```
1.  Yeni Windows Server kurulumu hazırlanır
2.  Python 3.12 kurulur
3.  PostgreSQL 15 kurulur (Windows service: postgresql-x64-15 — OPERATOR-ATTESTED
    doğrulama gerekir)
4.  En son geçerli PostgreSQL yedeği (§10) yeni sunucuya taşınır, henüz restore
    EDİLMEZ
5.  En son doğrulanmış release paketi (SHA256 + manifest ile teyit edilmiş) veya
    repo/git bundle'ı temin edilir
6.  `.env` GÜVENLİ KANALDAN (§31) geri alınır — repo/pakette ASLA yoktur
7.  `instance\` klasörü (varsa ayrı yedeği) geri konur
8.  `app/static/uploads` (varsa) VE **Dosya Merkezi storage kökü**
    (`FILE_CENTER_STORAGE_ROOT`, ayrı kalıcı disk/volume) dosya-sistemi
    seviyesinde geri konur — DB restore'undan (adım 9) BAĞIMSIZ, ayrı bir
    dosya-kopyalama işlemidir (bkz. §34.10)
9.  PostgreSQL restore: `pg_restore --clean --if-exists --dbname "%DATABASE_URL%" <dump>`
10. `python -m venv .venv` + `pip install -r requirements.txt`
11. `flask db current` ile restore edilen DB'nin revizyonu doğrulanır — canonical
    handover-sonrası ortamlarda (`10858a18e9ac` ve sonrası dahil edilmiş) tek head ile
    eşleşmeli (veya paketle birlikte gelen migration'lar varsa `flask db upgrade`).
    **[HISTORICAL]** `10858a18e9ac` öncesi paketlerde (örn. `cb2e57c`, head `e0efcd07abf7`)
    Dosya Merkezi'nin 19 tablosu revizyon zincirinde YOKTU (§34.7) — sıfırdan bir DB +
    yalnız `flask db upgrade` senaryosunda o tablolar OLUŞMAZDI, yalnız gerçek bir
    yedekten restore ediliyorsa geri gelirlerdi. `10858a18e9ac` ve sonrasını içeren bir
    paketle bu artık geçerli değildir: sıfırdan bir DB + `flask db upgrade` 19 tablonun
    hepsini de oluşturur; mevcut/legacy bir DB'de ise migration şemayı doğrulayıp
    veri kaybı olmadan adopt eder (uyuşmazlık varsa fail-closed durur).
12. `scripts\windows\install_bys360_live_waitress_80_task_v1.ps1` (önce dry-run,
    sonra `-Apply -ConfirmReplace`) ile Scheduled Task kurulur
13. `/healthz` (local, proxy header taklidiyle + public) doğrulanır
14. §11'deki smoke listesi (login, ana modül ekranları) çalıştırılır — Dosya Merkezi
    için ayrıca `/file-center` sayfasının açıldığı ve mevcut kayıtların (varsa)
    göründüğü doğrulanır
15. Log gate (§19) taranır — kritik pattern YOK doğrulanır
```

---

## 30. Handover Acceptance Checklist

```
[ ] Repo erişimi sağlandı
[ ] Bu ana dosyanın §2 (Architecture) bölümü okundu
[ ] Local kurulum başarılı (§4)
[ ] Step1 + odaklı testler çalıştırıldı, PASS görüldü
[ ] DB bağlantısı (local + production revizyon kavramı) anlaşıldı (§9)
[ ] Bir yedek gerçekten alındı (§10)
[ ] Restore yöntemi anlaşıldı (dry-run script'i test edildi) (§10)
[ ] Release build üretildi (`--audit-only` veya gerçek build ile) (§12)
[ ] CI gate (exact-head kuralı dahil) anlaşıldı (§13)
[ ] Deployment dry-run (installer script `-Apply` OLMADAN) anlaşıldı (§11, §6)
[ ] Scheduled Task'ler incelendi, Watchdog/Performance-Reminder'ın disabled
    kalması gerektiği anlaşıldı (§18)
[ ] Health check doğru yöntemle (proxy header'larıyla) çalıştırıldı (§8)
[ ] Incident runbook (§19) okundu
[ ] Secret teslim prosedürü tamamlandı (§31)
[ ] Production erişim prosedürü tamamlandı (operatörle koordineli, ayrı kanal)
```

---

## 31. Secret Handover

**Bu belgeye veya repodaki hiçbir dosyaya gerçek secret DEĞERİ yazılmaz.** Aşağıdaki liste yalnız secret ADLARINI ve teslim YÖNTEM KATEGORİSİNİ belirtir — değerlerin kendisini DEĞİL.

| Secret | Teslim yöntemi kategorisi |
|---|---|
| Production `.env` (tüm içeriği) | Güvenli, ayrı kurumsal kanal (örn. şifreli parola yöneticisi paylaşımı, kurumsal secret-vault) — ASLA e-posta/chat düz metin |
| PostgreSQL DB kimlik bilgileri | Güvenli kanal; DB erişim yetkisi ayrıca DBA/yetkili onayı gerektirir |
| SMTP kimlik bilgileri | Güvenli kanal |
| `SECRET_KEY` | Güvenli kanal; rotasyon gerekiyorsa `docs/security/BYS360_SECRET_ROTATION_AND_HISTORY_CLEANUP_RUNBOOK.md` izlenir |
| `TCKN_ENCRYPTION_KEY` | Güvenli kanal — KVKK açısından özellikle hassas, erişim en dar çevrede tutulmalı |
| Sentry DSN (varsa) | Güvenli kanal |
| GitHub kimlik bilgileri/erişim | Kurumsal GitHub organizasyon erişim prosedürü (SSO/2FA), repo sahibi onayı ile |
| Sunucu/VPN/RDP kimlik bilgileri | Kurumsal IT güvenlik prosedürü; RDP erişimi ayrı, denetlenebilir bir onay akışı gerektirir |

Bir secret'in repoya yanlışlıkla girdiğinden şüpheleniliyorsa, `docs/security/BYS360_SECRET_ROTATION_AND_HISTORY_CLEANUP_RUNBOOK.md` prosedürü İZLENİR (secret'i rotate et → `git filter-repo` ile geçmişten temizle → doğrulama komutlarını çalıştır).

---

## 32. Source of Truth Kuralı

| Konu | Kaynak |
|---|---|
| Kod davranışı | Repository source code (bu belge DEĞİL — belge kodu AÇIKLAR, EZMEZ) |
| DB şeması | Alembic migrations (`migrations/versions/`) + canlı DB'nin gerçek revizyonu (`flask db current`) |
| Production binary/source | Doğrulanmış (`--verify` geçmiş) FULL release paketi + kaynak SHA |
| Operasyon | Bu handover dosyası + `DEPLOYMENT.md`/`BACKUP_RUNBOOK.md` (kanonik runbook'lar) |
| CI | Taze, exact-head workflow kanıtı (bkz. §13) — eski bir çalıştırma kanıt SAYILMAZ |
| Historical governance | `docs/governance/` registry (§26.1) |

---

## 33. Eski Belgeler — Index

Eski handover paketleri/belgeleri SİLİNMEMİŞTİR — aşağıda CURRENT/SUPERSEDED/HISTORICAL olarak etiketlenmiştir.

| Belge | Etiket | Not |
|---|---|---|
| **`docs/handover/BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md`** (bu dosya) | **CURRENT** | Tek kanonik devir belgesi |
| `README.md`, `DEPLOYMENT.md`, `BACKUP_RUNBOOK.md`, `CONTRIBUTING.md` (kök dizin) | CURRENT | Bu ana dosyanın dayandığı, güncel (Ağustos 2026) kaynak belgeler |
| `docs/handover/BYS360_BAKIM_RUNBOOK.md`, `BYS360_CANLIYA_ALMA_REHBERI.md`, `BYS360_RISK_VE_SUREKLILIK_PLANI.md`, `BYS360_KURULUM_REHBERI.md`, `BYS360_MODUL_ENVANTERI.md`, `BYS360_GUVENLIK_KVKK_NOTLARI.md`, `BYS360_DEVIR_PAKETI_V1.md`, eski `docs/handover/README.md` | **SUPERSEDED** | 2026-06-24 tarihli; kök dizindeki güncel belgelerin daha eski/hafif versiyonları; içerik ÇELİŞKİLİ değil |
| `docs/handover/HANDOVER_10_10_EVIDENCE_20260708.md` | **HISTORICAL** | 2026-07-08 tarihli, "10/10 V6" anlık kanıt görüntüsü — o tarihin kaydı, güncel durum DEĞİL |
| `docs/archive/pre_handover_20260708/**` (217 dosya) | **HISTORICAL** | 2026-07-08 öncesi dönemin geniş özellik/refactor notu arşivi |
| `docs/archive/legacy-root/*.json` | **HISTORICAL** | Eski manifest/rapor dosyaları |

**Not:** Bu devir sürecinde örnek olarak verilen `BYS360_HANDOVER_10_10_SOURCE_V6_20260708` adlı bir paket, tam repo taramasıyla ARANDI ve **bu isimle repoda hiçbir dosya/paket bulunamadı**. En yakın gerçek eşleşme `HANDOVER_10_10_EVIDENCE_20260708.md`'dir (farklı isim, aynı tarih) — bu belge yukarıdaki tabloda HISTORICAL olarak zaten doğru şekilde işaretlenmiştir. Var olmayan bir dosya adı bu index'e gerçekmiş gibi eklenmemiştir.

---

## 34. Dosya Merkezi / Güvenli Dosya Transferi

**Not — bu bölümün eklenme gerekçesi:** İlk devir dalgasında Dosya Merkezi yalnız §2'nin modül tablosunda tek bir satırla ve birkaç dağınık cümleyle geçiyordu (kanıt: bu turun kendi araştırma ajanı, 9 ayrı satır/cümle buldu, hiçbiri Portal Video (§16) veya Performance (§17) kadar derinlikli değildi). Bu bölüm o boşluğu kapatır. **WeTransfer benzeri bir ürün değildir** — tüm "guest" akışları hâlâ kimliği doğrulanmış bir sahip kullanıcı tarafından BAŞLATILIR (link/talep oluşturma authenticated bir işlemdir); bu belge Dosya Merkezi'ni **"kurum içi güvenli dosya paylaşımı ve büyük dosya transferi"** olarak tanımlar.

### 34.1 Amaç

Kurum-içi kullanıcıların dosya yüklemesi/indirmesi, parola korumalı süreli misafir bağlantılarıyla dış kişilerle güvenli paylaşım yapması, misafirlerden dosya talep etmesi, büyük dosyaları parçalı (chunked) yüklemesi ve bunların hepsinin kota/güvenlik/denetim kaydı altında yönetilmesi.

### 34.2 Kaynak dosyalar

| Katman | Dosya(lar) |
|---|---|
| Route'lar (44 endpoint) | `app/file_center/routes.py` (1154 satır) |
| Servisler | `app/file_center/services.py` (1268 satır, çekirdek mantık), `mail_service.py` (SMTP), `settings_service.py` (DB-destekli ayarlar), `maintenance_service.py` (bakım/kota/expiry), `permissions.py` (rol-matrisi yetkilendirme) |
| Modeller | `app/models/file_center_models.py` (348 satır, 19 model sınıfı) |
| Şablonlar (13 dosya) | `app/templates/file_center/{index,chunk_upload,guest_download,guest_upload,admin,logs,maintenance,quota,requests,role_matrix,security,settings,transfers}.html` |
| JS | **Ayrı `app/static/js/*file_center*` dosyası YOK** — tüm istemci JS'i şablonlar içinde inline `<script>` bloklarıdır (`chunk_upload.html:20-51`, `index.html:178-187`) |
| Menü | `app/templates/base.html:613-640` (ayrı `menu_registry.py` dosyası YOK — bu repoda menü ana olarak `base.html` içinde tanımlıdır); alt-öğeler: Dosyalarım, Transfer Paketleri, Dosya Talepleri, Büyük Dosya Yükleme, Dosya Merkezi Yönetimi, Güvenlik Taraması, Kota Yönetimi, Bakım Merkezi, Ayarlar, Rol Matrisi |
| Operasyon script'leri | `scripts/local/file_center_ops_tick_v1l.py` (bakım tick'i), `scripts/local/audit_file_center_secret_hygiene_v1l.py`, `scripts/windows/repair_file_center_secret_hygiene_v1l.ps1` |

Tüm route'lar `main_bp` üzerinde kayıtlıdır (ayrı bir Blueprint DEĞİL), `app/routes.py:304`'te import edilir. Guest-olmayan HER route, `_enabled_or_message()` ile hem `can_use_file_center(current_user)` hem `file_center_enabled()` (DB/env destekli kapatma anahtarı) kontrolünden geçer.

### 34.3 Kullanıcı akışı (authenticated)

| Akış | Route | Metod | Durum |
|---|---|---|---|
| Dosya yükleme | `/file-center/upload` | POST | **IMPLEMENTED** — tek dosya, `FILE_CENTER_MAX_FILE_GB` (varsayılan 5GB) sınırlı |
| Dosya indirme (sahip) | `/file-center/download/<id>` | GET | **IMPLEMENTED** |
| Dosya silme | `/file-center/delete/<id>` | POST | **IMPLEMENTED** — soft-delete, aktif guest linkleri de iptal eder |
| Guest link oluşturma | `/file-center/share/<id>` | POST | **IMPLEMENTED** — zorunlu parola (route seviyesinde min 6 karakter) |
| Guest link iptali | `/file-center/share/<id>/revoke` | POST | **IMPLEMENTED** |
| Transfer paketi (çoklu dosya gruplama) | `/file-center/transfers*` | GET/POST | **CONDITIONAL** — birden fazla ZATEN-yüklenmiş dosyayı gruplar; alıcı (`FileTransferRecipient`) satırları kaydedilir ama route'larda onları GERÇEKTEN e-postalayan bir adım BULUNAMADI (bkz. §34.13) |
| Misafirden dosya talebi oluşturma | `/file-center/requests/create` | POST | **IMPLEMENTED** — parola, expiry, izinli uzantı listesi, istek-özel boyut sınırı |
| Talep daveti e-postası gönderme | `/file-center/requests/<id>/send-email` | POST | **IMPLEMENTED** — sahip tarafından tetiklenir, otomatik DEĞİL |
| Klasörler | — | — | **NOT_IMPLEMENTED (kullanıcı arayüzünde)** — `FileStorageFolder` modeli var ama onu oluşturan/listeleyen hiçbir route bulunamadı; muhtemelen gelecekteki bir özellik için hazırlanmış taslak |

### 34.4 Guest/share akışı (kimlik doğrulama gerektirmeyen kısım)

**Guest download** (`GET/POST /guest/files/<token>`, `file_center_guest_download`, giriş GEREKMEZ):
- Token: sahip kullanıcı `create_guest_link()` çağırır → `secrets.token_urlsafe(32)` üretilir; DB'de yalnız `sha256(token)` (`token_hash`, unique+indexed) saklanır. **Ayrıca** düz-metin `public_token` da ayrı bir kolonda tutulur (sahibin arayüzünde linki tekrar gösterebilmesi için) — yani token tamamen hash-only değildir.
- **Parola:** zorunlu, `werkzeug.security.generate_password_hash` ile saklanır.
- **Süre sonu (expiry):** `expires_at = now + gün` (varsayılan 7 gün, `FILE_CENTER_GUEST_DEFAULT_EXPIRES_DAYS`).
- **İndirme sayacı:** `download_count` vs `max_downloads` (varsayılan 5, `FILE_CENTER_DEFAULT_DOWNLOAD_LIMIT`).
- **Not/mesaj alanı:** `FileShareLink` modelinde YOK.
- Kullanılabilirlik: `is_active AND expires_at >= now AND download_count < max_downloads`.
- Her indirme denemesi `FileDownloadLog`'a yazılır (`wrong_password`/`blocked_by_security`/`success`).

**Guest upload** (`GET/POST /guest/upload/<token>`, `file_center_guest_upload`, giriş GEREKMEZ):
- Aynı token/hash/parola deseni, `FileRequest` üzerinde.
- İstek-özel `max_file_gb` ve `allowed_extensions` (global sınırla birlikte, daha KISITLAYICI olan uygulanır).
- Guest'ten `guest_name`/`guest_email` (opsiyonel) toplanır, `FileRequestUpload` satırına IP+user-agent ile birlikte kaydedilir.
- Talep sahibinin kotasına yazılır (dosya sahibi=talep sahibi, guest DEĞİL).
- İndirme sayacı kavramı YOK (bu bir yükleme ucu); `upload_count`/`last_upload_at` sayaç olarak tutulur.

**Genel durum özeti:** Guest download = **IMPLEMENTED**; Guest upload = **IMPLEMENTED**; Parola = **IMPLEMENTED** (zorunlu); Expiry = **IMPLEMENTED**; İndirme sayısı = **IMPLEMENTED** (yalnız download tarafında); Not alanı = **NOT_IMPLEMENTED**; Bildirim (guest'e otomatik mail) = **CONDITIONAL** (yalnız sahip elle tetiklerse).

### 34.5 Chunk (parçalı) büyük dosya yükleme — tam akış

Sayfa: `/file-center/chunk-upload` (`chunk_upload.html`). Üç adım:

1. **Session create** — `POST /file-center/chunk-upload/session-json` (JS/AJAX; form-encoded `/session` varyantı da var) → `create_chunk_upload_session()`: `total_size_bytes`, `chunk_size_bytes` (varsayılan `FILE_CENTER_DEFAULT_CHUNK_MB`=10MB), opsiyonel bütün-dosya `sha256_hash` alır; `token_urlsafe(32)` session token üretir, `storage_root()/temp/chunk_sessions/<owner_id>/<token>` geçici dizinini açar, `expires_at = now+24h`.
2. **Part upload** — `POST .../chunk/<index>` → her parça `{index:08d}.part.tmp` olarak stream edilir, atomik `.replace()` ile `.part`'a dönüşür. **Parçalar salt `chunk_index` ile sıralanır/kimliklenir** (client hash'i DEĞİL). Her parçanın SHA256+boyutu ayrıca hesaplanıp `FileUploadChunk` satırına yazılır; son parça hariç her parçanın boyutu `chunk_size_bytes`'ı AŞAMAZ.
3. **Finalize** — `POST .../finalize` → `finalize_chunk_upload_session()`:
   - **Eksik-parça kontrolü:** `range(total_chunks)` içindeki her index karşılığı bir satır var mı — yoksa `ValueError` ile temiz başarısızlık (eksik index listesi hata mesajında).
   - Kota tekrar kontrol edilir (tam `total_size_bytes` için).
   - Yasaklı uzantı reddi.
   - Parçalar **sırayla** birleştirilirken YENİDEN bir SHA256 ve toplam bayt hesaplanır.
   - **Boyut doğrulaması:** `total != expected` ise → durum `failed`, kısmi dosya SİLİNİR, hata fırlatılır.
   - **Hash doğrulaması:** session-create'te client bir `sha256_hash` verdiyse, hesaplanan hash ile karşılaştırılır; UYUŞMAZSA → `failed`, dosya SİLİNİR. Client hash vermediyse bu kontrol ATLANIR (durum `verified` yerine `completed` olur).
   - Başarıda: yeni `FileStorageItem` (`scan_status="pending"`), bir `FileSecurityScan` kaydı kuyruğa alınır, geçici dizin silinir.

**Client-side resume:** `chunk_upload.html`'in inline JS'i, önce status endpoint'ini sorgular, zaten alınmış index'leri bir `Set`'e koyar ve onları tekrar göndermez — "bağlantı kopunca devam" tamamen istemci-taraflı bir davranıştır, sunucu tarafında idempotent parça saklaması dışında zorunlu kılınmaz.

**Chunk bütünlüğü — özet:** parça-boyutu kontrolü VAR, eksik-parça kontrolü VAR, toplam-boyut kontrolü VAR, TÜM-DOSYA SHA256 kontrolü VAR (ama yalnız client bunu session-create'te sağladıysa) — **parça-bazlı client-declared hash karşılaştırması YOK** (parça hash'i hesaplanıp saklanır ama hiçbir şeyle karşılaştırılmaz).

### 34.6 Storage

- Kök: `storage_root()` — `FILE_CENTER_STORAGE_ROOT` env/config değerinden okunur. **Prod'da (APP_ENV/FLASK_ENV/ENV `production`/`prod`/`canli`/`live` veya `BYS360_PRODUCTION` bayrağı) tanımsızsa `RuntimeError` fırlatır** — üretimde bu değişken ZORUNLUDUR. Local'de `<instance_path>/file_center_storage`'a düşer. Alt klasörler: `uploads/`, `deleted/`, `quarantine/`, `temp/`.
- `.env.example` örnekleri: Windows `D:/bys360_storage/file_center`, Linux `/var/lib/bys360/file_center` — gerçek değer BOŞ gönderilir (repo hiçbir gerçek yol içermez).
- **DB yalnız metadata tutar** (`storage_path`, `original_filename`, `stored_filename`, `content_type`, `extension`, `size_bytes`, `sha256_hash`) — dosya baytları YALNIZ diskte yaşar; `FileStorageItem` modelinde BLOB/bytes kolonu YOK.
- Path-traversal koruması: `secure_file_path()` sonuçlanan yolu `.relative_to(root)` ile kontrol eder — kök dışına çıkan bir yol `ValueError` fırlatır.
- Güvenlik-işaretli dosyalar `uploads/`↔`quarantine/` arasında fiziksel olarak TAŞINIR (kopyalanmaz).
- **Cleanup:** `run_file_center_maintenance_tick()` (linkler/talepler expiry + kota yeniden hesaplama + bekleyen tarama + disk-doluluk özeti) tek çağrıda çalışır, `scripts/local/file_center_ops_tick_v1l.py` ile tetiklenir. **Bu script uygulama-içi bir zamanlayıcıya (Celery/RQ) BAĞLI DEĞİL** — harici bir Windows Görev Zamanlayıcı girişi gerektirir; bu turda böyle bir görevin repoda AKTİF şekilde kurulu olduğuna dair kanıt bulunamadı (yalnız arşivlenmiş `install_file_center_scheduled_tasks_v1l.ps1` var). **Yeni operatör bunu doğrulamalı ve gerekiyorsa kurmalıdır.**
- **Orphan-file taraması YOK** — bakım tick'i link/talep süre-dolumu ve kota hesabı yapar ama diskte DB kaydı olmayan dosyaları ARAMAZ.

### 34.7 Database (gerçek modeller, yalnız var olan alanlar)

19 model, hepsi `app/models/file_center_models.py`, hepsi `TimestampMixin` (created_at/updated_at) miras alır (bu sayı, önceki bir belge turunda yanlışlıkla 15 olarak raporlanmıştı — doğrusu `grep -c "__tablename__" app/models/file_center_models.py` ile doğrulanan 19'dur):

| Model | Tablo | Ana alanlar |
|---|---|---|
| `FileStorageFolder` | `file_storage_folders` | id, owner_user_id, parent_id, name, is_deleted *(route'suz — kullanılmıyor)* |
| `FileStorageItem` | `file_storage_items` | id, owner_user_id, folder_id, original_filename, stored_filename, storage_path, content_type, extension, size_bytes, sha256_hash, status, **scan_status**, is_deleted, deleted_at, deleted_by_user_id |
| `FileTransfer` | `file_transfers` | id, owner_user_id, title, message, status, expires_at |
| `FileTransferItem` | `file_transfer_items` | id, transfer_id, file_id |
| `FileTransferRecipient` | `file_transfer_recipients` | id, transfer_id, recipient_user_id, recipient_email, recipient_name, status |
| `FileShareLink` | `file_share_links` | id, file_id, **token_hash** (unique), **public_token**, password_hash, expires_at, max_downloads, download_count, is_active, revoked_at/by |
| `FileRequest` | `file_requests` | id, owner_user_id, title, description, recipient_name/email, token_hash, public_token, password_hash, expires_at, max_file_gb, allowed_extensions, status, upload_count, closed_at, revoked_at/by |
| `FileRequestUpload` | `file_request_uploads` | id, request_id, file_id, guest_name, guest_email, ip_address, user_agent, status |
| `FileDownloadLog` | `file_download_logs` | id, file_id, share_link_id, downloaded_by_user_id, guest_label, ip_address, user_agent, status |
| `FileAccessLog` | `file_access_logs` | id, file_id, actor_user_id, action, ip_address, user_agent, detail |
| `FileQuotaUsage` | `file_quota_usage` | id, user_id (unique), used_bytes, file_count |
| `FileSecurityScan` | `file_security_scans` | id, file_id, status, scanner, result_message, scanned_at |
| `FileAuditLog` | `file_audit_logs` | id, actor_user_id, file_id, action, message, ip_address, user_agent |
| `FileQuotaPolicy` | `file_quota_policies` | id, scope_type, scope_value, max_storage_gb, max_single_file_gb, max_transfer_gb, warning_threshold_percent, **hard_stop_enabled** |
| `FileUploadSession` | `file_upload_sessions` | id, owner_user_id, session_token, total_size_bytes, chunk_size_bytes, total_chunks, sha256_hash, status, temp_dir, finalized_file_id, expires_at |
| `FileUploadChunk` | `file_upload_chunks` | id, session_id, chunk_index, size_bytes, sha256_hash, storage_path, status |
| `FileCenterMailLog` | `file_center_mail_logs` | id, request_id, actor_user_id, recipient_email, subject, body, purpose, status, error_message, sent_at |
| `FileCenterRolePermission` | `file_center_role_permissions` | id, role_key (unique), 14 adet `can_*` boolean bayrak |
| `FileCenterSetting` | `file_center_settings` | id, key (unique), value, value_type, group_key |

**✅ [HISTORICAL / RESOLVED TRANSFERABILITY GAP]** Bu 19 tablo (önceki belge turunda yanlışlıkla 15 raporlanmıştı) daha önce `migrations/versions/` altında hiçbir Alembic dosyasına sahip DEĞİLDİ. Repo geçmişinde bunlar bir kerelik, artık **arşivlenmiş** bir script (`scripts/archive/pre_handover_20260708/local/create_file_center_tables_local_v1.py`, `db.create_all()` çağıran) ile oluşturulmuştu, ve sıfırdan bir ortamda yalnız `flask db upgrade` çalıştırmak bu tabloları OLUŞTURMUYORDU.

**Çözüm (Transferability Gap Closure dalgası):** `migrations/versions/10858a18e9ac_adopt_file_center_schema_into_alembic_.py` (revision `10858a18e9ac`, parent `e0efcd07abf7`, artık tek Alembic head'i) eklendi. Bu migration **kör bir `CREATE TABLE` veya sessiz bir "varsa atla" değildir** — aynı migration iki gerçek senaryoyu güvenle ele alır:

- **Sıfırdan (fresh) veritabanı:** 19 tablonun hiçbiri yoksa, hepsi tam beklenen şema ile (`app/models/file_center_models.py` ile birebir kolon/PK eşleşmesi) oluşturulur.
- **Legacy/canlı-tarzı veritabanı:** tablolar zaten (tarihsel `db.create_all()` bootstrap'ından) mevcutsa, migration onları **adopt eder** — veri dokunulmadan bırakılır, tablo tekrar oluşturulmaz/kopyalanmaz. Eğer mevcut şema beklenen kolon setiyle veya birincil anahtarla eşleşmiyorsa migration **fail-closed** olarak açık, kolon/PK adlarını içeren bir `SchemaAdoptionError` ile durur — sessizce kabul etmez. (Bu, repo'nun `29fee38a97e1` emsalinin "yalnız uyar" davranışından kasıtlı bir sapmadır: Dosya Merkezi çok daha büyük, misafir-erişimli bir yüzey olduğu için bir şema kayması burada deploy'u durdurmalı, istek anında sessizce bozulmamalı.)
- **Downgrade:** repo'nun veri-taşıyan adopte edilmiş tablolar için yerleşik kuralına uygun, kasıtlı olarak no-op (yıkıcı değil) — `29fee38a97e1` emsaliyle aynı politika.

**Doğrulama:** hem izole SQLite hem de gerçek yerel PostgreSQL 15 üzerinde üç senaryo da (fresh/legacy-adoption/negative-mismatch) ayrı ayrı test edildi; `tests/migrations/test_file_center_schema_adoption_migration.py` (7 test) bu davranışın kalıcı regresyon koruması altında olmasını sağlar. Mevcut canlı veritabanını (zaten `db.create_all()` ile oluşturulmuş olduğu için) bu değişiklik BOZMAZ — bir sonraki `flask db upgrade` çalıştırıldığında şemayı doğrulayıp sessizce adopt edecektir.

### 34.8 Security

| Kontrol | Mekanizma |
|---|---|
| Auth/ownership | `@login_required` + `_can_manage_file()`/`_can_manage_request()` (owner_user_id eşleşmesi veya admin-benzeri) |
| Rol-bazlı yetki | `app/file_center/permissions.py`, rol-matrisi tabanlı (`can_manage_file_center_admin`, `can_create_guest_links`, `can_create_guest_upload_requests`, `can_use_chunk_upload`, `can_manage_file_center_settings`, `can_manage_file_center_quota_policy`, `can_manage_file_center_role_matrix` dahil) |
| Guest token üretimi | `secrets.token_urlsafe(32)`; yalnız SHA256 hash sorgulanır (`token_hash`), ama düz metin de `public_token` kolonunda AYRICA saklanır |
| Parola | `werkzeug.security.generate_password_hash`/`check_password_hash` (salted); minimum 6 karakter route seviyesinde |
| Path traversal | `werkzeug.utils.secure_filename()` + `secure_file_path()`'in `.relative_to(root)` kontrolü |
| Uzantı/MIME | `blocked_extensions()` (varsayılan `.exe,.bat,.cmd,.ps1,.vbs,.scr,.dll,.msi,.js,.jar,.com,.pif`, `FILE_CENTER_BLOCKED_EXTENSIONS` ile genişletilebilir), opsiyonel allow-list (`FILE_CENTER_ALLOWED_EXTENSIONS`), çift-uzantı sezgisi, şüpheli MIME prefix listesi |
| Boyut sınırı | `FILE_CENTER_MAX_FILE_GB` (varsayılan 5.0), `FILE_CENTER_MAX_TRANSFER_GB` (varsayılan 20.0) — hem `Content-Length` ön-kontrolü hem stream-sırasında sayaç |
| Virüs taraması | **Opsiyonel ClamAV** (`FILE_CENTER_CLAMAV_ENABLED`, varsayılan `false`) — `subprocess.run` ile `FILE_CENTER_CLAMAV_COMMAND` (varsayılan `clamscan --no-summary --infected`) çalıştırır, timeout `FILE_CENTER_CLAMAV_TIMEOUT_SECONDS` (varsayılan 60). **Kapalıyken yalnız sezgisel (uzantı/MIME/çift-uzantı/boş-dosya) kontrol yapılır — GERÇEK virüs taraması YOKTUR** (kod içi literal mesaj: "Temel dosya türü ve güvenlik ön kontrolü geçti. Gerçek antivirüs taraması etkin değil.", `tests/security/test_file_center_v1l_hardening_static.py:51`'de de doğrulanmıştır). |
| Rate limiting | Bkz. §34.9 |
| CSRF | Global `CSRFProtect()`; iki misafir şablonu dahil TÜM formlarda `csrf_token`; chunk-upload AJAX JS'i her `FormData` POST'una `csrf_token` ekler |
| İndirme yetkisi | Her indirmede `can_download_file()` (silinmiş/karantinada/bloklu/tarama-temiz-değil → engellenir) |
| Audit logging | `FileAuditLog` (hemen hemen her durum-değiştiren işlemde), ayrıca `FileAccessLog`/`FileDownloadLog` (okuma/indirme-özel) |
| Süresi dolmuş/iptal token | `is_available()` kontrolü (`is_active`, `expires_at`, sayaç) her erişimde tekrar değerlendirilir |

### 34.9 Rate limit'ler (gerçek config key'leri)

Dinamik olarak, route-dekoratörü DEĞİL, `app/security/api_rate_limit.py::_apply_file_center_limits()` ile uygulanır (`app/__init__.py:294`'ten çağrılır):

| Endpoint | Config key | Varsayılan |
|---|---|---|
| `file_center_guest_download` | `FILE_CENTER_GUEST_DOWNLOAD_RATE_LIMIT` | 20/saat |
| `file_center_guest_upload` | `FILE_CENTER_GUEST_UPLOAD_RATE_LIMIT` | 10/saat |
| `file_center_upload` | `FILE_CENTER_AUTH_UPLOAD_RATE_LIMIT` | 30/saat |
| `file_center_chunk_upload_session_create` **ve** `..._session_create_json` | `FILE_CENTER_CHUNK_SESSION_RATE_LIMIT` (İKİSİ AYNI KEY'İ PAYLAŞIR) | 20/saat |
| `file_center_chunk_upload_part` | `FILE_CENTER_CHUNK_PART_RATE_LIMIT` | 240/saat |
| `file_center_chunk_upload_finalize` | `FILE_CENTER_CHUNK_FINALIZE_RATE_LIMIT` | 60/saat |

`ENABLE_API_RATE_LIMIT=true` (varsayılan) ve `flask-limiter` paketi gerektirir; paket eksikse sessizce no-op olur.

### 34.10 Backup / Restore

- **DB backup TEK BAŞINA YETERLİ DEĞİLDİR.** DB yalnız metadata tutar (§34.6) — dosya baytları `FILE_CENTER_STORAGE_ROOT` altında, PostgreSQL'in tamamen dışında yaşar.
- Doğru sıra: (1) `pg_dump` (DB metadata), (2) `FILE_CENTER_STORAGE_ROOT` kökünün dosya-sistemi seviyeli yedeği (örn. `robocopy`/benzeri, `uploads/`+`deleted/`+`quarantine/` alt klasörleri dahil — `temp/` hariç tutulabilir, oturum-geçicidir).
- Restore sırası: PostgreSQL restore + storage-kökü restore BİRLİKTE, tutarlı bir zaman noktasından yapılmalı — biri diğerinden farklı bir zaman noktasından gelirse DB'de dosya kaydı olup fiziksel dosyanın olmaması (veya tersi) riski oluşur (bkz. §34.13 incident sınıfları).
- §10'daki genel "Hangi veri ayrı korunur" tablosu artık Dosya Merkezi storage'ı ayrı bir satır olarak listeler.

### 34.11 Operasyon (yeni sistem yöneticisi için)

- **Storage kapasitesi takibi:** `storage_health_summary()` (bakım tick'inin bir parçası) disk doluluk yüzdesini hesaplar, `FILE_CENTER_DISK_ALERT_PERCENT` (varsayılan 85) aşılırsa `file_center_disk_alert` audit kaydı YAZAR — **bu yalnız bir UYARI mekanizmasıdır, upload'ları ENGELLEMEZ.**
- **Hangi klasör yedeklenir:** `FILE_CENTER_STORAGE_ROOT` kökünün tamamı (temp/ hariç tutulabilir).
- **Orphan file riski:** VAR — bakım tick'i diskte DB kaydı olmayan dosyaları ARAMAZ (§34.6). Periyodik manuel/scripted bir çapraz-kontrol henüz yoktur.
- **Cleanup nasıl çalışır:** `run_file_center_maintenance_tick()` → link/talep expiry + kota yeniden hesaplama + bekleyen güvenlik taraması + disk özeti; harici bir zamanlayıcı (Windows Görev Zamanlayıcı) gerektirir, uygulama-içi otomatik DEĞİLDİR (§34.6).
- **DB restore sonrası storage neden AYRICA gerekir:** çünkü DB yalnız "bu dosya şu yolda, şu boyutta" der — dosyanın kendisi PostgreSQL'in içinde DEĞİLDİR; DB'yi geri yükleyip storage'ı geri yüklemezseniz, uygulama var olmayan dosyalara işaret eden kayıtlarla dolu olur (indirme denemeleri 404/500 verir).
- **Kota:** `FileQuotaPolicy.hard_stop_enabled=True` DEĞİLSE (varsayılan `False`), kota aşımı upload'u ENGELLEMEZ — yalnız arayüzde uyarı/tehlike rengi gösterir. Gerçek bir sert-durdurma istiyorsanız ilgili politikada bu bayrağı açık ayarlamak gerekir.

### 34.12 Troubleshooting — gerçek anlamlı incident sınıfları

| Sınıf | Muhtemel neden |
|---|---|
| Upload 413 / boyut reddi | `FILE_CENTER_MAX_FILE_GB`/`_MAX_TRANSFER_GB` aşıldı, veya ters-proxy'nin kendi `client_max_body_size`'ı |
| Chunk finalize başarısız — "Eksik parçalar var" | Bir veya daha fazla `chunk_index` hiç yüklenmedi/timeout oldu — istemci JS'in resume mantığını tetiklemesi gerekir |
| Chunk finalize başarısız — hash uyuşmazlığı | Ağ bozulması veya istemcinin gönderdiği `sha256_hash` yanlış — dosya SİLİNMİŞ, yeniden yüklenmesi gerekir |
| Süresi dolmuş guest link/talep | `expires_at` geçmiş — `is_available()` `False` döner, kullanıcıya "süresi doldu" mesajı |
| Geçersiz token | Yanlış/eski link, ya da veritabanında hiç eşleşme yok (`token_hash` bulunamadı) |
| Storage path erişilemez | `FILE_CENTER_STORAGE_ROOT` yanlış yapılandırılmış, disk bağlı değil, veya izin sorunu — prod'da bu env eksikse `RuntimeError` ile BAŞLANGIÇTA engellenir |
| Disk dolu | `storage_health_summary()`'nin `file_center_disk_alert` audit kaydı loglarda aranmalı |
| DB kaydı var, dosya yok | Storage restore'u DB restore'undan farklı bir zaman noktasından yapıldıysa (bkz. §34.10) — indirme `send_file` seviyesinde hata verir |
| Dosya var, DB kaydı yok | Manuel dosya-sistemi müdahalesi veya kısmi restore sonrası — orphan file, hiçbir otomatik tarama bunu bulmaz (§34.6) |
| Guest-link parola/erişim sorunu | Yanlış parola denemeleri `FileDownloadLog`'da `wrong_password` olarak görünür — brute-force paterni için loglar taranmalı |

### 34.13 Known Limitations (yalnız kod tarafından gerçekten desteklenen sınırlamalar)

- Maksimum dosya boyutu: `FILE_CENTER_MAX_FILE_GB` (varsayılan 5GB); transfer paketi toplamı: `FILE_CENTER_MAX_TRANSFER_GB` (varsayılan 20GB) — sabit değil, DB'den de override edilebilir (`settings_service.py`).
- Desteklenen dosya türleri: allow-list boşsa (varsayılan) hemen hemen her tür kabul edilir, yalnız sabit bir blocked-list (`.exe,.bat,.cmd,.ps1,.vbs,.scr,.dll,.msi,.js,.jar,.com,.pif`) reddedilir.
- Expiry davranışı: guest link/talep süresi dolunca erişim otomatik kapanır (`is_available()`), ama fiziksel dosya/DB kaydı OTOMATİK silinmez — yalnız erişim engellenir.
- Guest kısıtlamaları: parola ZORUNLU, not/mesaj alanı YOK, indirme sayacı yalnız download tarafında var (upload tarafında yok).
- **Quota:** varsayılan olarak yalnız advisory (uyarı) — `hard_stop_enabled=True` açıkça ayarlanmadıkça sert bir engelleme YOKTUR.
- **Virüs taraması:** varsayılan olarak YOKTUR (yalnız ClamAV açıkça etkinleştirilirse gerçek tarama olur; aksi halde yalnız sezgisel kontrol).
- **Harici obje depolama (S3/Azure Blob/GCS) desteği YOKTUR** — yalnız yerel dosya sistemi (`storage_root()` altında).
- **Çoklu dosya tek-istekte yükleme YOKTUR** — hem normal upload hem guest upload tam olarak bir dosya/istek kabul eder; "Transfer Paketleri" özelliği zaten-yüklenmiş dosyaları GRUPLAR, tek-istekte çoklu yükleme değildir.
- **Klasör (folder) özelliği kullanıcı arayüzünde YOKTUR** — model var, route/servis desteği yok.
- **Transfer alıcılarına (`FileTransferRecipient`) otomatik e-posta bildirimi bulunamadı** — kayıtlar oluşturulur ama route'larda onları e-postalayan bir adım tespit edilemedi.
- ~~19 tablonun hiçbiri Alembic migration'da DEĞİLDİR~~ **[RESOLVED]** — bkz. §34.7 (`10858a18e9ac`, HISTORICAL/RESOLVED TRANSFERABILITY GAP).

### 34.14 Source of Truth (Dosya Merkezi için, §32'nin genel kuralına ek)

| Konu | Kaynak |
|---|---|
| Davranış | `app/file_center/routes.py` + `services.py` (bu bölümdeki HER iddia bunlardan doğrudan okunmuştur) |
| DB | `app/models/file_center_models.py` — **Alembic migration'a `10858a18e9ac` ile dahil edildi** (HISTORICAL/RESOLVED — önceden yalnız model tanımı + tarihsel bir kerelik bootstrap script'i vardı, bkz. §34.7) |
| Storage | `FILE_CENTER_STORAGE_ROOT` ortam değişkeni/DB ayarı — gerçek üretim yolu bu dokümantasyon oturumunda doğrulanmadı, operatör tarafından RDP ile teyit edilmelidir |
| Security | `app/file_center/permissions.py`, `app/security/api_rate_limit.py`, `tests/security/test_file_center_*.py` |
| Production state | OPERATOR-ATTESTED dağıtım kanıtı (bkz. §0) — bu bölüm Dosya Merkezi'nin CANLIDA gerçekten hangi verilerle dolu olduğunu İDDİA ETMEZ, yalnız KODUN neyi desteklediğini belgeler |

## 35. Stratejik Performans v2 (KPI Dashboard / Yetkinlik Kütüphanesi / Hedefler)

**Not — bu bölümün eklenme gerekçesi:** Bu özellik, `BYS360_FEATURE_COVERAGE_MATRIX.md`'de 38 özellik arasında tek başına **UNDOCUMENTED** olarak işaretlenmişti (ana handover dosyasında sıfır gerçek mention — genel "Performans Yönetimi" (§17) şemsiyesinin içinde tamamen görünmezdi). Bu bölüm, o boşluğu ilk kez sıfırdan kod okunarak kapatır. Araştırma sırasında, özelliğin kendisinden daha önemli, canlıya doğrudan etkisi olan bir **route çakışması** bulunmuştur (bkz. 35.3) — bu bulgu, repository'nin kendi iç denetim mekanizması (Phase 12A/12B route-conflict testleri) tarafından da bağımsız olarak doğrulanmıştır.

### 35.1 Amaç

Kurumsal/birim/personel düzeyinde KPI ve hedef kartları oluşturma-izleme ("Hedefler"), bu hedeflerin canlı özet göstergesi ("KPI Dashboardu"), yetkinlik tanımlarının kurumsal kütüphanesi ("Yetkinlik Kütüphanesi"), personelin dönemsel öz-değerlendirme formu ("Öz Değerlendirme") ve yönetici karar-destek metin özeti ("KPI Analiz Merkezi / AI KPI Analiz"). Ayrı bir Performans **süreç motoru** (karne/onay/itiraz akışı, §17) DEĞİLDİR — mevcut karne (scorecard) sürecine paralel, stratejik/kurumsal hedef takibi katmanıdır.

### 35.2 Kaynak dosyalar (gerçek dosya ağacı — hint'teki varsayımlar burada düzeltilmiştir)

Görev tanımındaki başlangıç ipucu `app/modules/strategic_performance/_dashboard/routes.py` gibi bir alt-paket öngörüyordu; bu YANLIŞTIR. Gerçek ağaç, aralarında hiçbiri diğerini import etmeyen **üç ayrı, paralel implementasyon katmanı** içerir:

| Katman | Durum | Dosyalar |
|---|---|---|
| **A — Canlı kazanan (main blueprint)** | **GERÇEKTEN ÇALIŞAN** | `app/performance/sp1_sidebar_routes.py` (238 satır) — `main_bp` üzerine kayıtlı, `app/routes.py` tarafından import edilir |
| **B — Kayıtlı ama gölgelenen (dedike blueprint)** | **KISMEN GÖLGELİ** (bkz. 35.3) | `app/modules/strategic_performance/routes.py` (176 satır), `models.py` (94 satır), `__init__.py` (19 satır) — `app/bootstrap/route_bootstrap.py`'de `CORE_BLUEPRINT_SEQUENCE` içinde kayıtlı (`required=False`) |
| **C — Ölü/hiç kayıtlı değil (ikinci blueprint denemesi)** | **ASLA ÇALIŞMIYOR** | `app/modules/strategic_performance_dashboard/routes.py` (51 satır) + `services/dashboard_service.py` (56), `services/ai_summary_service.py` (16) + kendi `templates/`/`static/` klasörleri — `app.register_blueprint(strategic_performance_dashboard_bp)` çağrısı repo genelinde HİÇBİR YERDE bulunamadı (`app/__init__.py`, `route_bootstrap.py` dahil tüm `register_blueprint` çağrıları grep edildi) |

Ortak/paylaşılan servis katmanı (Katman A ve B'nin GERÇEKTEN kullandığı):

| Servis | Satır | Kullanan |
|---|---|---|
| `app/services/sp1c_kpi_dashboard_service.py` (`build_sp1c_kpi_dashboard_context`) | 79 | Katman A (kazanan) — `performance_targets` tablosuna ham SQL (`text()`), basit özet |
| `app/services/sp1d_target_management_service.py` (liste/oluştur/düzenle) | 288 | Katman A + Katman B (ikisi de aynı fonksiyonları import eder) — `performance_targets`/`performance_target_periods`'e ham SQL |
| `app/services/sp3a_kpi_dashboard_live_service.py` (`build_sp3a_kpi_dashboard_context`) | 264 | **Yalnız Katman B** (gölgelenen taraf) — şema-adaptif (`inspect()` ile tablo/kolon var mı kontrol eder), ağırlıklı başarı + risk grupları hesaplar |
| `app/services/role_guards.py` (`is_top_or_manager`, `can_manage_strategic_targets`, `can_view_strategic_performance`) | 55 | Katman A + Katman B (ikisi de aynı fonksiyonları çağırır) |

Ayrıca **kullanılmayan (dead) yardımcı dosyalar** doğrulandı (hiçbir route/servis tarafından import edilmedikleri grep ile teyit edildi — yalnızca `tests/services/test_sp_kpi_services.py` bunları saf birim testi olarak çağırıyor):
- `app/modules/strategic_performance/services/{kpi_service.py, target_service.py, analytics_service.py, competency_service.py, kpi_performance_link_service.py}` ve bunların `app/modules/strategic_performance/templates/strategic_performance/{dashboard.html, kpi_performance_link.html}` şablonları — Blueprint tanımında (`Blueprint("strategic_performance", __name__, url_prefix=...)`) `template_folder` parametresi VERİLMEDİĞİ için bu şablon klasörü Flask'in Jinja arama yoluna hiç girmez; dolayısıyla bu iki şablon fiilen erişilemez.
- `app/services/strategic_performance/competency_library_service.py` (17 satır, `build_competency_summary`) — hiçbir route/servis tarafından import edilmiyor.
- `app/templates/strategic_performance/{role_competency_templates.html, self_review_manager.html, sp1j_final_marker.html}` — üçü de hiçbir route'ta `render_template()` argümanı olarak geçmiyor (grep ile doğrulandı); muhtemelen tamamlanmamış SP-1F/SP-1J taslakları.

### 35.3 KRİTİK BULGU — Route çakışması: menünün gösterdiği blueprint, çalışan kod DEĞİL

Bu, bu araştırmanın en önemli bulgusudur ve repository'nin kendi CI-kilitli testi tarafından (`tests/quality/test_route_conflict_runtime_contract.py`, `KNOWN_CONFLICTS` sözlüğü, "Phase 12A/12B" denetimi) bağımsız olarak da doğrulanmıştır — bu bölümdeki iddia yalnız bu araştırma oturumunun kendi okumasına değil, repo'nun kendi runtime `app.url_map` + `MapAdapter.match()` testine dayanır.

`app/modules/strategic_performance/routes.py` (Blueprint `strategic_performance`, prefix `/performans/stratejik`) ve `app/performance/sp1_sidebar_routes.py` (main blueprint üzerinde, AYNI Türkçe path'lerle ikinci kayıt) **birebir aynı 5 URL path'ini** tanımlar:

| Path | main (Katman A) endpoint | strategic_performance (Katman B) endpoint | Runtime kazanan |
|---|---|---|---|
| `/performans/stratejik/kpi-dashboard` | `main.sp1_kpi_dashboard_tr` | `strategic_performance.kpi_dashboard` | **main** (gölgeleyen, `sp1c` pipeline) |
| `/performans/stratejik/hedefler` | `main.sp1_kpi_targets_tr` | `strategic_performance.target_list` | **main** |
| `/performans/stratejik/yetkinlik-kutuphanesi` | `main.sp1_competency_library_tr` | `strategic_performance.competency_library` | **main** |
| `/performans/stratejik/oz-degerlendirme` (GET+POST) | `main.sp1_self_review_tr` | `strategic_performance.self_review` | **main** |
| `/performans/stratejik/ai-kpi-analiz` | `main.sp1_ai_kpi_analysis_tr` | `strategic_performance.ai_kpi_analysis` | **main** |

Kazananın "main" olması rastgele değil, deterministiktir: `app/bootstrap/route_bootstrap.py`'deki `CORE_BLUEPRINT_SEQUENCE` sırasına göre `main` (index 0) `strategic_performance` (index 2)'den ÖNCE `app.register_blueprint()` ile kaydedilir; Werkzeug aynı statik path'e sahip iki rule arasında **ilk-kaydedilen kazanır** kuralını uygular (Flask insertion-order tie-break). `strategic_performance.target_create` (`/hedefler/yeni`) ve `strategic_performance.target_edit` (`/hedefler/<id>/duzenle`) BU listede DEĞİLDİR — bu ikisi main tarafında Türkçe path olarak tekrarlanmamıştır, dolayısıyla GERÇEKTEN `strategic_performance` blueprint'ine ulaşır (create/edit linkleri `target_list.html` şablonunda `url_for('strategic_performance.target_create', ...)` ile üretilir ve bu path çakışmaz).

**Somut, doğrulanabilir sonucu (fonksiyonel bug):** KPI Dashboard ekranını gerçek kullanıcı `/performans/stratejik/kpi-dashboard`'a gittiğinde `main.sp1_kpi_dashboard_tr` kazanır, o da `build_sp1c_kpi_dashboard_context()` (SP-1C, basit pipeline) kullanır. Bu fonksiyonun döndürdüğü `summary` sözlüğünde **`weighted_completion` alanı YOKTUR** ve context'te ayrı bir **`risk_counts` anahtarı hiç YOKTUR**. Ancak gösterilen şablon (`strategic_performance/kpi_dashboard.html`) `summary.get('weighted_completion', 0)` ve `risk_counts.get('Düşük'/'Orta'/'Yüksek', 0)` okur — bu alanları YALNIZ gölgelenen `strategic_performance.kpi_dashboard` (SP-3A, `sp3a_kpi_dashboard_live_service.py`, şema-adaptif, ağırlıklı hesap + risk grupları) üretir. Sonuç: canlı ekranda "Ağırlıklı Başarı" HER ZAMAN **%0** görünür ve "Risk Dağılımı" kartındaki Düşük/Orta/Yüksek sayaçları HER ZAMAN **0** görünür — gerçek veri var olsa bile — çünkü onları hesaplayan kod yolu hiçbir zaman çalıştırılmaz. Bu, repo'nun kendi testinde de `DISTINCT_BUSINESS_FLOW` notuyla teyit edilmiştir: *"main winner sabit performance_targets/SP1C pipeline'ını, shadowed handler dinamik tablo/kolon, aktiflik, ağırlıklı başarı ve risk grupları içeren SP3A pipeline'ını kullanır. Aynı template'e farklı veri sözleşmeleri verirler."*

İkincil davranış farkı: main tarafı `safe_render()` (`app/route_support.py:116`) kullanır — şablon patlarsa hatayı yutar, flash mesajı + fallback HTML döner; `strategic_performance` blueprint'i doğrudan Flask `render_template()` çağırır — şablon hatasında 500 döner. Bu da testte ayrıca not edilmiştir (`ROUTE_OWNERSHIP_AMBIGUOUS`, `SHADOWED_BUT_NOT_SAFE_TO_REMOVE`).

Bu durum "kasıtlı, incelenmiş, CI'da kilitli" bir bilinen durumdur — repo, bunu sessizce bir hata olarak değil, insan tarafından incelenmiş bir ratchet-baseline olarak taşımaktadır (`test_known_conflict_winners_have_not_silently_changed` — kazanan sessizce değişirse CI FAIL verir). Bu belge onu YİNELEMEZ, yalnız handover'a ilk kez taşır. **Bu, bu dokümantasyon dalgasının düzeltme kapsamı DIŞINDADIR** (yalnız belgeleniyor) — düzeltmek bir ürün kararı (iki route'tan hangisi kanonik olmalı) ve gerçek kod değişikliği gerektirir.

### 35.4 Kullanıcı girişi / navigasyon

`app/templates/base.html:543-547`, `menu_map` anahtarlarına göre koşullu 5 nav linki üretir (hepsi `safe_url_for('strategic_performance.<endpoint>', fallback=...)` ile — yani **href'ler blueprint B'nin endpoint adlarını kullanır**, ama tarayıcı o path'e gittiğinde yukarıdaki tabloya göre gerçekte blueprint A çalışır; bu kullanıcı için görünmezdir çünkü ikisi de aynı şablonu, aynı temel servisleri kullanır):

| Menü anahtarı | Etiket | Path |
|---|---|---|
| `performance_kpi_dashboard` | KPI Dashboardu | `/performans/stratejik/kpi-dashboard` |
| `performance_kpi_management` | KPI ve Hedef Yönetimi | `/performans/stratejik/hedefler` |
| `performance_competency_library` | Yetkinlik Kütüphanesi | `/performans/stratejik/yetkinlik-kutuphanesi` |
| `performance_self_assessment` | Öz Değerlendirme | `/performans/stratejik/oz-degerlendirme` |
| `performance_kpi_analysis` | KPI Analiz Merkezi | `/performans/stratejik/ai-kpi-analiz` |

Bu 5 anahtar `app/menu_registry_data_performance.py`'de rol bazlı görünürlük listelerinde (satır 68-73, 118-122, vb.) ve merkezi `MENU_KEY_ROLES` haritasında (satır 421-425) gerçekten tanımlıdır — navigasyon **GERÇEK ve çalışır durumdadır** (menü linki ölü değildir, sayfa 403/404 vermez).

### 35.5 Roller / erişim

**Görev tanımındaki varsayım YANLIŞ/DOĞRULANMADI:** Bu özellik, repo'nun diğer bölümlerinde yaygın olan `admin_required`/`manager_required`/`menu_key_required` dekoratör ailesini KULLANMAZ. Bunun yerine `app/services/role_guards.py`'de tanımlı, kendine özgü, **rol-adı alt-string eşleştirmesi** yapan bir yardımcı kullanır:

```python
TOP_OR_MANAGER_TOKENS = ("admin","sistem","başkan","baskan","yardımc","yardimc","grup","koordinat","performans","ik","mali","yönetici","yonetici")
def is_top_or_manager(user): ...  # role string'inde bu token'lardan biri VAR MI, veya is_admin/is_superuser
def can_view_strategic_performance(user): return is_top_or_manager(user)
def can_manage_strategic_targets(user): return is_top_or_manager(user)
```

Route seviyesinde uygulama (hem Katman A `sp1_sidebar_routes.py` hem Katman B `routes.py`'de birebir aynı desen):
- `kpi_dashboard`, `competency_library`, `target_list`, `ai_kpi_analysis` → `_is_top_or_manager()` / `_can_view_kpi_dashboard()` (ikisi de `is_top_or_manager` sarmalayıcısı) — 403 (`access_denied.html` / `render_access_denied()`) döner, guard başarısızsa.
- `target_create`, `target_edit` → `can_manage_strategic_targets()` (aynı `is_top_or_manager`) — yani "görüntüleme" ve "yönetme" yetkisi kod düzeyinde AYNI fonksiyona indirgenir (menü tarafında `performance_kpi_management` rol listesi biraz daha dar olsa da, route seviyesinde ayrım YOKTUR).
- **`self_review` (Öz Değerlendirme) route'unun İKİ kopyası da (main VE strategic_performance) HİÇBİR rol kontrolü yapmaz** — yalnız `@login_required`. Menü tarafında `performance_self_assessment` anahtarı `personel` rolüne de açıktır (bu rol `is_top_or_manager` testinden geçmez) ve bu tutarlıdır (personel öz değerlendirme yapabilmeli); ama route'un kendisi login olan HERKESE açıktır — menüde görünmese bile URL'yi bilen herhangi bir giriş yapmış kullanıcı GET/POST edebilir. Objekt-seviyeli bir yetki denetimi olmadığı için bu route seviyesinde bir "yalnız menü ile gizleme" (security-through-obscurity) durumudur.

### 35.6 Routes/API (gerçek path + HTTP metodu — Katman A, kazanan taraf)

| Path | Metod | Endpoint (main) | Guard |
|---|---|---|---|
| `/performance/kpi/dashboard`, `/performans/stratejik/kpi-dashboard` | GET | `sp1_kpi_dashboard(_tr)` | `is_top_or_manager` |
| `/performance/kpi/targets`, `/performans/stratejik/hedefler` | GET | `sp1_kpi_targets(_tr)` | `is_top_or_manager` |
| `/performance/kpi/targets/new`, `/performance/kpi/targets/yeni` | GET, POST | `sp1_kpi_target_create(_tr)` | `can_manage_strategic_targets` |
| `/performance/kpi/targets/<int:target_id>/edit`, `/duzenle` | GET, POST | `sp1_kpi_target_edit(_tr)` | `can_manage_strategic_targets` |
| `/performance/competencies`, `/performans/stratejik/yetkinlik-kutuphanesi` | GET | `sp1_competency_library(_tr)` | `is_top_or_manager` |
| `/performance/self-review`, `/performans/stratejik/oz-degerlendirme` | GET, POST | `sp1_self_review(_tr)` | yalnız `login_required` |
| `/performance/kpi/ai-analysis`, `/performans/stratejik/ai-kpi-analiz` | GET | `sp1_ai_kpi_analysis(_tr)` | `is_top_or_manager` |

Katman B (`app/modules/strategic_performance/routes.py`, prefix `/performans/stratejik`) yalnız `/hedefler/yeni` (GET,POST) ve `/hedefler/<int:target_id>/duzenle` (GET,POST) için GERÇEKTEN çalışır; `kpi-dashboard`, `hedefler` (liste), `yetkinlik-kutuphanesi`, `oz-degerlendirme`, `kpi-analiz`/`ai-kpi-analiz` GET rotaları yukarıdaki 35.3 nedeniyle runtime'da hiç seçilmez.

**Mobil API (ayrı, ek bir yüzey — görev tanımındaki hint'te YOKTU, bu araştırmada bulundu):** `app/api/mobile/domains/kpi_target_management.py` (237 satır), `mobile_api_bp` üzerinde:
- `GET /kpi/target-management` — kapsam-filtreli KPI/hedef listesi + özet metrikler
- `POST /kpi/target-management` — yeni hedef oluşturma
- `POST /kpi/target-management/<int:target_id>/progress` — gerçekleşme güncelleme

Bu üçü, repo genelinde **`PerformanceTarget`/`PerformanceTargetPeriod` ORM modellerinin (`app/modules/strategic_performance/models.py`) fiilen kullanıldığı TEK yerdir** (`Target.query`, `db.session.add(target)`) — web tarafındaki tüm CRUD ham SQL (`text()`) ile yapılırken, mobil taraf ORM kullanır; ikisi de aynı `performance_targets` tablosuna yazar.

### 35.7 Core service/model

- **Modeller** (`app/modules/strategic_performance/models.py`, 94 satır, 5 sınıf): `PerformanceTargetPeriod`, `PerformanceTarget`, `CompetencyLibrary`, `RoleCompetencyTemplate`, `SelfReview`. **Web tarafındaki CRUD bu ORM sınıflarını KULLANMAZ** — `sp1c_kpi_dashboard_service.py`/`sp1d_target_management_service.py`/`sp3a_kpi_dashboard_live_service.py` hepsi ham `sqlalchemy.text()` SQL çalıştırır; ORM sınıfları yalnız (a) Alembic migration'ın karşılık geldiği şema tanımı ve (b) mobil API'nin gerçek kullanım noktası olarak işlev görür.
- **Servisler:** bkz. 35.2 tablosu. `sp1d_target_management_service.py`'deki `_is_global_role()` fonksiyonu, `role_guards.py`'deki `is_top_or_manager`'dan BAĞIMSIZ, KENDİ token listesiyle (`admin, sistem, başkan, baskan, performans, ik` — `role_guards`'daki `yardımc/grup/koordinat/mali/yönetici` token'ları BURADA YOK) veri-görünürlük kapsamını (global mi, yoksa yalnız kendi `owner_user_id`/`owner_unit_id` mi) belirler — yani "sayfayı görebilme" ve "hangi satırları görebilme" yetkisi FARKLI, birbirinden bağımsız iki token listesiyle kontrol edilir; bu iki liste sürüklenirse (biri güncellenip diğeri unutulursa) tutarsızlık riski vardır.
- **AI notları:** Hem `sp1c` hem `sp3a` servisleri, gerçek LLM çağrısı YAPMAZ — sabit Türkçe kural-tabanlı (if/else eşik) cümleler üretir (`"Kritik seviyede hedefler bulunuyor…"` vb.). "AI KPI Analiz Merkezi" adındaki ekran da context'siz statik bir kabuktur (bkz. 35.15).

### 35.8 DB bağımlılığı

5 tablo, gerçek bir Alembic migration ile oluşturulur ve doğrulanmıştır: `migrations/versions/20260508_sp1a_strategic_performance.py` (revision `20260508_sp1a`, `down_revision=None` — bağımsız bir dal olarak başlamış), sonradan `migrations/versions/20260513_perf_live_gate_merge_sp1a_v58.py` (`down_revision=("v58a1c2d3e4f", "20260508_sp1a")`) ile ana canlı zincire **merge edilmiştir** — yani bu tablolar tek Alembic head'inin bir parçasıdır, ayrı/unutulmuş bir dal DEĞİLDİR:

| Tablo | Index | Kullanan |
|---|---|---|
| `performance_target_periods` | — | `sp1d_target_management_service.build_target_form_context` |
| `performance_targets` | `owner_user_id`, `owner_unit_id`, `period_id` | `sp1c`, `sp1d`, `sp3a` (aday tablolardan biri), mobil API (ORM) |
| `competency_library` | — | **Hiçbir route/servis tarafından sorgulanmıyor** — yalnız migration'da tablo olarak var |
| `role_competency_templates` | — | **Hiçbir route/servis tarafından sorgulanmıyor** |
| `self_reviews` | — | **`SelfReview` ORM sınıfı hiçbir yerde instantiate edilmiyor; öz değerlendirme POST'u bu tabloya HİÇBİR ŞEY YAZMAZ** (bkz. 35.9) |

`sp3a_kpi_dashboard_live_service.py`, `performance_targets`'a ek olarak `strategic_targets`, `kpi_targets`, `target_cards`, `sp1_target_cards`, `sp1_targets` isimli 5 alternatif tablo adını da "aday" olarak dener (`inspect(db.engine).get_table_names()`) — bunlardan hiçbiri migration'da yaratılmaz; yalnız `performance_targets` gerçekte var olduğu için pratikte hep o kullanılır.

### 35.9 Kalıcı depolama

Dosya/blob depolama YOKTUR — tüm veri yukarıdaki 5 PostgreSQL tablosunda tutulur (standart uygulama DB'si, ayrı bir depolama alanı gerekmez).

**Önemli, doğrulanmış eksiklik:** "Öz Değerlendirme" formu (`self_review()` route, hem Katman A hem B'de) POST edildiğinde YALNIZ bir `flash("Öz değerlendirme kaydı alındı. Bu kayıt otomatik puan üretmez.", "success")` çağırır ve aynı sayfaya redirect eder — **`SelfReview` tablosuna hiçbir INSERT/UPDATE çalıştırılmaz**. Form verisi (`general_summary`, `strengths`, `development_needs`, `evidence_note`, `additional_note` — şablonda gerçek `<textarea name=...>` alanları olarak mevcut) sunucu tarafında tamamen atılır. Kullanıcıya "kaydedildi" mesajı gösterilmesine rağmen kalıcılık YOKTUR — bu, kullanıcıyı doğrudan yanıltan bir bulgudur. **Bu, bu dokümantasyon dalgasının düzeltme kapsamı DIŞINDADIR** (yalnız belgeleniyor).

### 35.10 Security controls

- **Auth:** `@login_required` (Flask-Login) tüm route'larda VAR.
- **Yetkilendirme:** 35.5'te açıklanan bespoke `is_top_or_manager`/`can_manage_strategic_targets` (rol-adı substring eşleştirmesi) — repo genelindeki standart `menu_key_required` desenine UYMAZ.
- **CSRF:** Global `CSRFProtect()` (`app/extensions.py` + `app/bootstrap/factory_bootstrap.py`, dosya merkezi §34.8'de de doğrulanan aynı mekanizma) — `self_review_form.html` ve `target_form.html` şablonlarında `{% if csrf_token is defined %}<input type="hidden" name="csrf_token" ...>{% endif %}` ile korunur.
- **SQL injection:** Tüm ham SQL, parametreli `sqlalchemy.text()` + bind-parametreler (`:user_id` vb.) kullanır; kullanıcı girdisi doğrudan string-interpolate EDİLMEZ (yalnız `sp1d_target_management_service.py`'de `where` KOŞUL İFADESİ dinamik seçilir, ama koşulun içindeki DEĞERLER hep parametrelidir).
- **Girdi doğrulama:** `_validate_payload()` (`sp1d_target_management_service.py:208`) — hedef kodu/adı zorunlu, hedef değeri >0, ağırlık 0-100 aralığı. Öz değerlendirme formunda SUNUCU TARAFI hiçbir doğrulama/persistans YOK (bkz. 35.9).
- **Rate limiting:** Bu route ailesine özel bir rate-limit bulunamadı (Dosya Merkezi'ndeki gibi `_apply_file_center_limits()` benzeri dedike bir mekanizma YOK); yalnız uygulama genelindeki genel login/oturum korumasına tabidir.

### 35.11 Operasyonel bağımlılık

- Harici bir servise (SMTP, S3, üçüncü parti API) bağımlılık YOK.
- **Performans karne (scorecard) sürecinden VERİ OKUMAZ** — `performance_targets` tamamen ayrı, kendi başına bir tablodur; mevcut karne/onay sürecinin (`performance_models.py`) tablolarına hiçbir foreign key veya JOIN YOKTUR. Yani "Stratejik Performans" ve "Performans Yönetimi" (§17) kod düzeyinde birbirinden İZOLEDİR — şablonlardaki metinler ("KPI kartları performans değerlendirme sürecine kanıt sağlar") yalnız açıklayıcı metindir, gerçek bir veri entegrasyonu YOKTUR.
- HR/org verisiyle bağlantı: yalnız `owner_unit_id`/`owner_user_id` integer kolonları üzerinden (foreign key tanımlı DEĞİL, yalnız konvansiyonel int referans).
- Mobil API (`app/api/mobile/domains/kpi_target_management.py`) aynı `performance_targets` tablosuna paralel bir yazma/okuma yüzeyi açar (bkz. 35.6).

### 35.12 Backup/restore ilgisi

Tamamen standart PostgreSQL yedeği (`pg_dump`) kapsamındadır — ayrı bir dosya sistemi/blob deposu YOKTUR, Dosya Merkezi'ndeki (§34.10) gibi ek bir "storage kökü" yedekleme adımına gerek yoktur. 5 tablo tek Alembic head zincirinin parçası olduğu için `flask db upgrade` sıfırdan bir ortamda bunları doğru şekilde oluşturur.

### 35.13 Zamanlanmış/arkaplan davranış

YOKTUR. Bu özellik için Windows Scheduled Task, Celery/RQ job veya periyodik bakım script'i bulunamadı (`scripts/windows/`, `scripts/local/` içinde "strategic_performance"/"sp1"/"sp3a" adı geçen hiçbir kurulum script'i yok).

### 35.14 Troubleshooting

| Belirti | Muhtemel neden |
|---|---|
| KPI Dashboard'da "Ağırlıklı Başarı" hep %0, risk dağılımı hep 0/0/0 görünüyor | Beklenen davranış DEĞİL, bilinen bir çakışma bulgusu — bkz. 35.3. Düzeltmek için ürün kararı gerekir (main tarafı da `sp3a` servisine geçirilmeli veya iki route'tan biri kaldırılmalı) |
| Öz Değerlendirme "kaydedildi" diyor ama hiçbir yerde göremiyorum | Beklenen davranış DEĞİL — route veriyi hiç yazmıyor, bkz. 35.9. Kod değişikliği olmadan çözülemez |
| Yetkinlik Kütüphanesi sayfası hep boş görünüyor | Route hiçbir context/veri geçmiyor (`competency_library()` render_template'e hiç argüman vermiyor) — `competency_library` tablosunda satır olsa bile ekranda GÖRÜNMEZ, kod değişikliği gerekir |
| "KPI Analiz Merkezi" hep boş/placeholder gösteriyor | Aynı neden — `ai_kpi_analysis()` route'u `insights`/`risky_targets` geçmiyor, şablon her zaman default boş listelere düşer |
| Bir kullanıcı beklenmedik şekilde 403 alıyor | `is_top_or_manager()` rol-adı substring kontrolü — kullanıcının `role`/`role_name` alanı `TOP_OR_MANAGER_TOKENS` listesindeki hiçbir kelimeyi içermiyor olabilir; rol adları veri tabanında serbest metin olduğundan yazım farkı (`"Birim Sorumlusu"` vs `"birim_sorumlusu"`) davranışı değiştirebilir |

### 35.15 Known Limitations (yalnız kod tarafından gerçekten doğrulanan)

- **Route çakışması (bkz. 35.3):** menünün işaret ettiği "gelişmiş" (SP-3A, ağırlıklı+risk-grup) KPI Dashboard implementasyonu canlıda hiçbir zaman çalışmaz; her zaman daha basit SP-1C implementasyonu çalışır.
- **Öz Değerlendirme kalıcılığı YOKTUR** — form verisi atılır, kullanıcıya yanlış "kaydedildi" geri bildirimi verilir.
- **Yetkinlik Kütüphanesi ve KPI Analiz Merkezi ekranları context'siz statik kabuklardır** — `CompetencyLibrary` tablosu dolu olsa bile ekranda hiçbir zaman veri görünmez (route context geçmiyor).
- **`competency_library`, `role_competency_templates`, `self_reviews` tabloları migration'da var ama repoda hiçbir CRUD kod yolu bu tabloları okumaz/yazmaz** (yalnız `SelfReview`/`CompetencyLibrary`/`RoleCompetencyTemplate` sınıf tanımları var, hiç instantiate edilmiyor).
- **İkinci, hiç kayıtlı olmayan bir blueprint (`app/modules/strategic_performance_dashboard/`) repoda duruyor** — kendi şablonu, CSS/JS'i, servisleri var ama `register_blueprint()` çağrısı yok; ölü kod, silinmeye/aktifleştirilmeye dair bir ürün kararı bekliyor.
- **Beş adet kullanılmayan servis dosyası** (`app/modules/strategic_performance/services/{kpi_service,target_service,analytics_service,competency_service,kpi_performance_link_service}.py`) yalnız birim testleri tarafından çağrılıyor, hiçbir gerçek route tarafından değil.
- **Veri görünürlük kapsamı (`_is_global_role`) ve sayfa-erişim yetkisi (`is_top_or_manager`) BAĞIMSIZ token listeleriyle** kontrol edilir — biri güncellenip diğeri unutulursa tutarsızlık riski var.
- **Stratejik Performans, mevcut Performans karne/onay sürecinden (§17) veri OKUMAZ** — iki sistem kod düzeyinde izoledir, şablonlardaki "entegrasyon" metni yalnız açıklayıcıdır.
- **Rate limiting YOKTUR** bu route ailesine özel.

### 35.16 Source of Truth (kesin dosya listesi, gerçek satır sayılarıyla)

| Katman | Dosya | Satır |
|---|---|---|
| Canlı kazanan route'lar | `app/performance/sp1_sidebar_routes.py` | 238 |
| Gölgelenen dedike blueprint | `app/modules/strategic_performance/routes.py` | 176 |
| Gölgelenen blueprint modelleri | `app/modules/strategic_performance/models.py` | 94 |
| Gölgelenen blueprint init | `app/modules/strategic_performance/__init__.py` | 19 |
| Ortak rol yardımcıları | `app/services/role_guards.py` | 55 |
| KPI dashboard servisi (kazanan, basit) | `app/services/sp1c_kpi_dashboard_service.py` | 79 |
| Hedef CRUD servisi (her iki katman da kullanır) | `app/services/sp1d_target_management_service.py` | 288 |
| KPI dashboard servisi (gölgelenen, şema-adaptif) | `app/services/sp3a_kpi_dashboard_live_service.py` | 264 |
| Mobil API | `app/api/mobile/domains/kpi_target_management.py` | 237 |
| Ölü ikinci blueprint | `app/modules/strategic_performance_dashboard/routes.py` + `services/{dashboard_service,ai_summary_service}.py` | 51 + 56 + 16 |
| Kayıt (bootstrap) | `app/bootstrap/route_bootstrap.py` (`CORE_BLUEPRINT_SEQUENCE`) | 195 |
| Migration (tablo oluşturma) | `migrations/versions/20260508_sp1a_strategic_performance.py` | 32 |
| Migration (head merge) | `migrations/versions/20260513_perf_live_gate_merge_sp1a_v58.py` | 29 |
| Menü tanımı | `app/templates/base.html:543-547`, `app/menu_registry_data_performance.py` (665 satır, ilgili anahtarlar 68-73/118-122/165-171/213-219/261-267/304-308/345-351/419-427) | — |
| Şablonlar (gerçekten erişilebilir, 8 dosya) | `app/templates/strategic_performance/{kpi_dashboard,target_list,target_form,competency_library,self_review_form,ai_kpi_analysis,access_denied}.html` | 10+10+99+9+9+9+11 |
| Şablonlar (yazılmış ama erişilemez/orphan, 3 dosya) | `app/templates/strategic_performance/{role_competency_templates,self_review_manager,sp1j_final_marker}.html` | 13+16+1 |
| Route-çakışması testi (bağımsız doğrulama) | `tests/quality/test_route_conflict_runtime_contract.py` | 334 |
| Route-sahiplik testi (bağımsız doğrulama) | `tests/quality/test_phase12b_route_ownership_contract.py` | 477 |
| Birim testleri (yalnız ölü servis katmanını kapsıyor) | `tests/services/test_sp_kpi_services.py` | 59 |

---

## 36. Sistem Ayarları (Genel Ayarlar Merkezi)

**Not — bu bölümün eklenme gerekçesi:** Önceki turda Sistem Ayarları yalnızca §2 modül tablosunda tek satırla geçiyordu ("Ayar kataloğu tabloları (tek tek sayılmadı)"). Bu turda kod gerçekten okundu: `/settings` ekranı aslında bu matrisin **hem #11 hem #12 hem #28** numaralı satırlarının ortak fiziksel ekranıdır — yani Sistem Ayarları, Rol Matrisi (düzenlenebilir kısmı) ve Ayar Geçmişi/Rollback aynı tek route'ta (`settings_page()`) ve aynı tek şablonda (`settings.html`, 1487 satır) birlikte render edilir. Bu üç özellik ayrı bölümler olarak belgelense de, okuyucunun bunun TEK bir ekran olduğunu bilmesi gerekir.

### 36.1 Amaç
Sistemin kurumsal kimlik bilgilerini (sistem/kurum adı, tarih-saat biçimi, Sistem Künyesi sayfası içeriği), modül bazlı davranış anahtarlarını, rol/birim/kişi bazlı menü görünürlüğü varsayımlarını ve bunların değişiklik geçmişini tek bir admin-only ekranda toplamak. Canlı sistemde kod değişikliği gerektirmeden "Sistem adı", "Künye" gibi görünen metinleri ve modül davranışlarını değiştirebilme.

### 36.2 Kullanıcı entry/navigasyon
- Menü: üst navigasyon "Kullanıcı" açılır menüsünde **"Ayarlar"** öğesi, yalnız `menu_map.get('settings', False)` doğruysa görünür (`app/templates/base.html:707,774`).
- URL: `/settings` (kanonik), ayrıca `/admin/settings`, `/admin/settings/performance`, `/admin/settings/security` aynı view'a bağlı takma adlar.
- Ekran içi gezinme: sayfa üstünde 15 adet bölüm-içi çapa linki (`settings_section_links` — Genel Sistem, Hakkımızda, Sistem Künyesi, Modül Ayarları, Genel/Personel/Performans/İletişim/Portal/AI/Ayarlar Rol Matrisi, Rol Varsayılanları, Birim Profilleri, Tanılama, Ayar Geçmişi; bir kullanıcı seçiliyse ayrıca Personel Bazlı Rol Matrisi ve Şablon Arşivi).

### 36.3 Roller/erişim
`@login_required` + `@admin_required` (`app/account/routes.py:31-32`) → `admin_required = _require_role_family(ADMIN_FAMILY_ROLES, ...)` (`app/route_support.py:458`), `ADMIN_FAMILY_ROLES = {"admin","baskan","baskan_yardimcisi","grup_baskani","mali_musavir"}` (`app/route_support.py:66`). Menü görünürlüğü ayrıca `settings` menu_key ile kontrol edilir ama route seviyesinde asıl karar `admin_required`'dır — yani menü anahtarı bir şekilde açılsa bile route kendi kendini korur.

### 36.4 Route'lar/API
| Route | Metod | Not |
|---|---|---|
| `/settings`, `/admin/settings`, `/admin/settings/performance`, `/admin/settings/security` | GET/POST | Hepsi aynı `settings_page()` view'ına bağlı (`app/account/routes.py:27-33`) |
| POST `form_action` dispatch (tek route içinde ~15 dallanma) | POST | `save_system_foundation`, `save_module_foundation`, `sync_role_defaults`, `save_role_matrix_group__*`, `reset_role_matrix_group__*`, `save_communication_role_matrix`, `save_assistant_role_matrix`, `rollback_settings_change_entry`, `bulk_apply_profile`, `export_visibility_template`, `import_visibility_template`, `save_named_archive`, `apply_named_archive`, `delete_named_archive`, ve eşleşmeyen her `form_action` için `_handle_user_scoped_profile_action` (kullanıcı bazlı görünürlük kaydı) — hepsi `app/main_handlers/account_settings_helpers.py:148-265` içindeki tek dispatch bloğunda |

Route katmanı ince: gerçek dallanma mantığı `app/main_handlers/account_settings_helpers.py` (856 satır) içinde.

### 36.5 Çekirdek servis/model
- `app/main_handlers/account_settings_helpers.py` (856 satır) — `settings_page()` + 16 adet `_handle_*` POST işleyicisi.
- `app/services/settings/` paketi (23 dosya, toplam ~4763 satır) — bunların GERÇEKTEN canlı akışta kullanılan alt kümesi: `catalog.py` (1332 satır, 113 `setting_key` tanımı + Künye alt-kataloğu), `menu_profile_access.py` (507 satır — `build_effective_user_menu_context_handler`, `save_role_menu_defaults_handler`, `save_unit_menu_profile_handler`, `save_user_menu_overrides_handler`), `menu_permissions.py` (111 satır — canlı-menü filtreleme/snapshot yardımcıları), `menu_rules.py` (65 satır — kural normalize), `change_logs.py` (105 satır), `rollback_handler.py` (310 satır — bkz. §42), `effective_menu.py` (bkz. §37), `foundation_access.py`, `form_pipeline.py`, `ui_panel.py`, `diagnostics.py`, `validation_defaults.py`, `value_codec.py`, `serialization.py`, `contracts.py`, `snapshots.py`, `quality_gate.py`, `final_hardening.py`.
- **Doğrulanmış ölü kod:** `app/services/settings/constants.py` (51 satır) ve `app/services/settings/definitions.py` (45 satır) — her ikisi de kendi docstring'inde "Faz 1'de pasiftir, settings_service.py bu modülü çağırmaz" diye açıkça belirtiyor; grep ile repo genelinde bu iki dosyayı import eden TEK bir yer bulunamadı. Yani paket içinde gerçekten ölü, kasıtlı olarak bırakılmış iskelet dosyalar var.

### 36.6 DB bağımlılığı
`app/models/settings_models.py`: `SystemSetting` (`system_settings`), `ModuleSetting` (`module_settings`), `RoleMenuDefault` (`role_menu_defaults`), `UnitMenuProfile` (`unit_menu_profiles`), `SettingsChangeLog` (`settings_change_logs`, bkz. §42). Ayrıca `app/models/core_models.py:386` `UserMenuPermission` (`user_menu_permissions`, `UniqueConstraint(user_id, menu_key)`).

### 36.7 Kalıcı depolama (dosya sistemi)
Doğrudan dosya yazımı yok — "Şablon Arşivi" (`save_named_archive`/`apply_named_archive`) bile bir `SystemSetting` satırında JSON olarak saklanır (`SETTINGS_ARCHIVE_GROUP_KEY`/`SETTINGS_ARCHIVE_KEY_PREFIX`), ayrı dosya YOK. `export_visibility_template` bir indirme (`send_file`/binary response) üretir ama bunu diskte kalıcı tutmaz — istek anında bellekte üretilir.

### 36.8 Güvenlik kontrolleri
- Flask-WTF `CSRFProtect` app genelinde aktif (`app/extensions.py:9`, `csrf.init_app(app)` → `app/bootstrap/factory_bootstrap.py:54`); `settings.html` içindeki HER form `{{ csrf_token() }}` gizli alanı taşır (en az 9 ayrı form bloğunda doğrulandı).
- `admin_required` (rol ailesi), ayrıca route içi `try/except` "güvenli fallback" — `settings_page()` beklenmedik hata fırlatırsa 200 durum koduyla kırmızı-vurgulu bir "güvenli modda açıldı" HTML'i döner (`app/account/routes.py:34-61`), 500 hata sayfası yerine.
- Girdi doğrulama: form action string'leri whitelist mantığıyla dallanıyor (bilinmeyen `form_action` sessizce `_handle_user_scoped_profile_action`'a düşer — bu bir tasarım kararı, "unknown action" hata vermek yerine varsayılan bir işleyiciye yönlendiriyor; kötüye kullanım riski düşük çünkü hedef işleyici zaten sadece kullanıcı-bazlı görünürlük kaydı yapıyor).

### 36.9 Operasyonel bağımlılık
Yok — SMTP/Celery/harici servis gerektirmez. Tamamen istek-anlık (request-time) DB okuma/yazma. `phase1_seed_summary = ensure_settings_phase1_seeded(...)` (`app/services/settings/bootstrap.py` üzerinden) her `settings_page()` çağrısında ayar tablolarının migration ile geldiğini doğrular; eksikse kullanıcıya "flask db upgrade çalıştırın" uyarısı flash edilir (kod çökmez, güvenli mod).

### 36.10 Backup/restore ilişkisi
Standart PostgreSQL DB yedeğine dahildir (`system_settings`, `module_settings`, `role_menu_defaults`, `unit_menu_profiles`, `settings_change_logs`, `user_menu_permissions` — hepsi normal tablo, ayrı bir yedekleme stratejisi gerekmez).

### 36.11 Zamanlanmış/arka plan davranış
YOK. `scripts/windows/` altında bu özellikle ilgili herhangi bir `install_*`/`register_*` script bulunamadı (grep "settings" için sıfır sonuç) — tamamen istek-anlık, zamanlayıcıya bağımlı değil.

### 36.12 Sorun giderme
1. Ayarlar sayfası "güvenli modda açıldı" kırmızı kutusu gösteriyorsa → uygulama loglarında `Ayarlar sayfası güvenli fallback ile açıldı: %s` satırını arayın (`app/account/routes.py:37`), genelde eksik migration (`flask db upgrade`) veya `settings_page()` içinde beklenmeyen bir DB şema uyumsuzluğudur.
2. "Ayarlar altyapısı henüz veritabanına uygulanmamış" flash mesajı → `ensure_settings_phase1_seeded()` eksik tablo tespit etti; `flask db upgrade` çalıştırın.
3. Bir ayar formu kaydedilmiyor/sessizce hiçbir şey olmuyor gibi görünüyorsa → gönderilen `form_action` değerinin `settings_page()` içindeki (`account_settings_helpers.py:208-265`) whitelist'te GERÇEKTEN var olduğunu kontrol edin; yazım hatası olan bir `form_action` sessizce `_handle_user_scoped_profile_action`'a düşer ve beklenmeyen bir kaydetme türü tetikler.

### 36.13 Bilinen kısıt
`app/services/settings/` paketinde 23 dosyadan en az 2'si (`constants.py`, `definitions.py`) kod tarafından hiç import edilmeyen, kendi docstring'inde "pasif" diye işaretlenmiş ölü iskelet dosyalardır — bu paket, adım adım "Faz 1…Faz 12" servis ayrıştırması geçirmiş ve arkasında kullanılmayan ara-adım dosyaları bırakmış. Yeni bir geliştirici bu paketi ilk gördüğünde hangi dosyanın canlı olduğunu ayırt etmek için gerçekten `settings_page()`'in import zincirini takip etmesi gerekir — dosya adı tek başına güvenilir bir rehber değildir.

### 36.14 Kaynak dosyalar
- Route: `app/account/routes.py` (85 satır, `/settings` + 3 takma ad)
- Handler: `app/main_handlers/account_settings_helpers.py` (856 satır)
- Servis paketi: `app/services/settings/` (23 dosya, ~4763 satır — bkz. §36.5 için canlı alt küme)
- Modeller: `app/models/settings_models.py` (110 satır, 5 sınıf), `app/models/core_models.py:386-406` (`UserMenuPermission`)
- Şablon: `app/templates/settings.html` (1487 satır)

---

## 37. Yetkilendirme / Rol Matrisi

**Not — bu bölümün eklenme gerekçesi:** Önceki tur yalnızca "`effective_menu.py`, 2111 satır, kritik dev dosya" diye bir dosya boyutu iddiası bırakmıştı. Bu tur dosyayı gerçekten açtı: **bu sayı artık yanlıştır.** `app/services/settings/effective_menu.py` bugün yalnız **299 satırlık bir facade**'dır; gerçek mantık `app/services/settings/effective_menu_parts/` alt paketine (12 dosya, 3064 satır) taşınmış durumda. Toplam (299+3064=3363 satır, 13 dosya) önceki iddiadan (2111, tek dosya) daha BÜYÜK ama artık tek dosyada değil — yani "kritik dev dosya" etiketi hâlâ doğru ama somut sayı ve dosya sayısı yanlıştı, bu turda düzeltildi.

Ayrıca bu turda ikinci, bağımsız bir "kritik dev dosya" daha bulundu: `app/services/role_matrix_ui_service.py` (797 satır) içinde `build_role_matrix_ui_context` fonksiyonu **üç kez** art arda yeniden tanımlanıyor (`# type: ignore[no-redef]` yorumlarıyla, satır 425/550/731) — her yeni tanım bir öncekini "wrap" ediyor (decorator-benzeri patch zinciri). `effective_menu.py`'deki desenin birebir aynısı, ayrı bir dosyada.

### 37.1 Amaç
Hangi rolün/birimin/kişinin hangi menü öğesini (dolayısıyla hangi route ailesini) görebileceğine karar veren tek karar zincirini işletmek; hem çalışma-zamanı menü görünürlük haritasını üretmek (`build_menu_visibility_map`) hem de bu politikayı insan-okunur bir referans ekranda (`/admin/role-matrix`) göstermek.

### 37.2 Kullanıcı entry/navigasyon
İki AYRI ekran vardır, birbirine karıştırılmamalı:
1. **Düzenlenebilir rol/birim/kişi matrisi** — `/settings` sayfasının İÇİNDE, "Genel Rol Matrisi", "Personel Rol Matrisi", "Performans Rol Matrisi", "İletişim Rol Matrisi", "Portal Rol Matrisi", "AI Rol Matrisi", "Ayarlar Rol Matrisi", "Rol Varsayılanları", "Birim Profilleri", "Personel Bazlı Rol Matrisi" bölüm-çapaları olarak (bkz. §36.2). Buradan DB'ye yazılır.
2. **Salt-okunur referans matris** — `/admin/role-matrix` (`admin_role_matrix_center`). Girişi: Ayarlar sayfası üstündeki "Rol Matrisi" butonu (`settings.html:22`, `{{ safe_url_for('main.admin_role_matrix_center') }}`). Bu route base.html navigasyonunda AYRI bir menü öğesi olarak YOK — yalnız Ayarlar sayfası içinden erişilir.

### 37.3 Roller/erişim
- `/admin/role-matrix`: `@login_required` + `@admin_required` (`app/admin/role_matrix_routes.py:18-19`).
- `/settings` içindeki düzenlenebilir matris: yine `@admin_required` (aynı route, §36.3).
- Çalışma-zamanı karar mekanizması (`menu_key_required` dekoratörü, `app/route_support.py:424-440`): **admin bypass'ı bilerek kaldırılmış** — kod yorumunda açıkça yazıyor: *"Admin/üst rol bypassı kaldırıldı. Bir route menu_key_required ile korunuyorsa son karar da Ayarlar > Rol Matrisi / kişi-birim görünürlüğünden gelen canlı menü haritasıdır."* Yani rol matrisi kendisi yetkilendirmenin KAYNAĞIDIR — admin rolü otomatik olarak her `menu_key_required` route'a giremez, DB'deki canlı görünürlük haritası son sözü söyler.

### 37.4 Route'lar/API
| Route | Metod | Ne yapar |
|---|---|---|
| `/admin/role-matrix` | GET | Salt-okunur referans matris (`app/admin/role_matrix_routes.py:17-27`) |
| `/settings` (form_action=`save_role_matrix_group__*`, `reset_role_matrix_group__*`, `sync_role_defaults`, `save_communication_role_matrix`, `save_assistant_role_matrix`, kullanıcı-bazlı override) | POST | Gerçek DB yazımı (bkz. §36.4) |

### 37.5 Çekirdek servis/model
- **Karar motoru (çalışma zamanı):** `app/route_support.py::build_menu_visibility_map(user)` (satır 404-415) → ince köprü → `app/services/settings/effective_menu.py::build_menu_visibility_map` (facade, 299 satır) → `app/services/settings/effective_menu_parts/` (12 dosya, 3064 satır): `apply_context.py` (396), `bys360_context.py` (517), `runtime_policy_context.py` (756 — en büyük tekil parça), `build_context.py` (316), `build_wrapper_context.py` (200), `block_context.py` (214), `bys360_constants.py` (428), `user_context.py`, `phase3_constants.py`, `core_policy_constants.py`, `role_constants.py`, `public_build_context.py`. Zincir, `build_menu_visibility_map`'i ardışık olarak "sarmalayan" (wrap eden) ~8 ayrı fonksiyon çağrısından oluşuyor (`apply_v213c_category_menu_wrapper`, `apply_v214_category_scope_wrapper`, `apply_v215_category_period_scope_wrapper`, `apply_v216_category_period_integration_wrapper`, `apply_period_center_key_roles_block`, `apply_admin_period_reminder_public_build_wrapper` — her biri `effective_menu.py:174-299` arasında sırayla `build_menu_visibility_map` değişkenini yeniden atıyor).
- **Yazma katmanı (DB'ye kaydetme):** `app/services/settings/menu_profile_access.py` (507 satır) — `build_effective_user_menu_context_handler`, `save_role_menu_defaults_handler`, `save_unit_menu_profile_handler`, `save_user_menu_overrides_handler`, `clear_user_menu_overrides_handler`.
- **Salt-okunur referans ekran:** `app/services/role_matrix_ui_service.py` (797 satır) — `ROLES`/`GROUPS`/`MatrixRow`/`MatrixGroup` tamamen Python kodunda SABİT (hardcoded) dataclass tuple'ları; **DB'ye hiç bağlanmaz**. `build_role_matrix_ui_context` 3 kez yeniden tanımlanıyor (satır 425, 550, 731 — her biri bir öncekini saran patch).
- `app/services/settings/menu_permissions.py` (111 satır) — canlı-menü filtreleme (`filter_live_menu_keys`) ve DB snapshot yardımcıları (`snapshot_role_menu_state`, `snapshot_unit_menu_state`, `snapshot_user_override_state`).
- `app/services/settings/menu_rules.py` (65 satır) — `MenuPermissionRule` normalize yardımcıları.

### 37.6 DB bağımlılığı
`role_menu_defaults`, `unit_menu_profiles`, `user_menu_permissions` (bkz. §36.6) — `/admin/role-matrix` ekranı ise HİÇBİR tabloya dokunmaz (tamamen statik Python verisi render eder).

### 37.7 Kalıcı depolama
N/A — dosya sistemi kullanılmaz, karar tamamen DB satırları + kod-içi statik politika sabitleri (`CORE_MENU_VISIBILITY_POLICY`, `PHASE3_PERFORMANCE_MENU_POLICY` vb.) üzerinden üretilir.

### 37.8 Güvenlik kontrolleri
- `admin_required` (rol ailesi) route seviyesinde; `menu_key_required` dekoratörü admin bypass'ı OLMADAN canlı DB haritasına bakar (§37.3).
- CSRF: `/settings` içindeki matris formları için geçerli (bkz. §36.8); `/admin/role-matrix` salt-okunur GET olduğu için CSRF konusu yok.

### 37.9 Operasyonel bağımlılık
Yok.

### 37.10 Backup/restore ilişkisi
`role_menu_defaults`/`unit_menu_profiles`/`user_menu_permissions` standart DB yedeğine dahil. `/admin/role-matrix`'in statik `ROLES`/`GROUPS` verisi kod ile birlikte deploy edilir, ayrı yedek gerektirmez.

### 37.11 Zamanlanmış/arka plan davranış
N/A.

### 37.12 Sorun giderme
1. Bir kullanıcı beklenen bir menüyü göremiyor ama rolü/DB kaydı doğru görünüyorsa → `effective_menu_parts/runtime_policy_context.py` (756 satır) içindeki wrapper zincirini kontrol edin; sıralı patch'lerden biri geç bir aşamada menüyü tekrar kapatıyor olabilir (özellikle Dönem Yönetim Merkezi / Performans kategori-kapsam wrapper'ları `effective_menu.py:189-257` arasında).
2. `/admin/role-matrix` ekranındaki matris ile `/settings`'teki GERÇEK DB durumu birbirini tutmuyorsa → bu BEKLENEN bir durumdur, bkz. §37.13 (referans ekran statiktir, canlı override'ları yansıtmaz).
3. Rol matrisi ile ilgili bir regresyon sonrası "hangi patch bunu yaptı" sorusu için → `effective_menu.py` içindeki `# Phase4J V*C` yorumlu import bloklarının kronolojik sırası, hangi wrapper'ın hangi sırada uygulandığının kaydıdır (dosya kendi değişim geçmişini yorum satırlarında taşıyor).

### 37.13 Bilinen kısıt
`/admin/role-matrix` ekranı **canlı DB durumunu yansıtmaz** — `role_matrix_ui_service.py`'deki `ROLES`/`GROUPS` tamamen kod-içi sabit veridir (dosyanın kendi docstring'i bunu itiraf ediyor: *"Gerçek login, şifre, CAPTCHA, veritabanı bağlantısı veya endpoint yetki kontrol akışına dokunmaz"*). Yani bir admin bu ekrana bakıp "personel rolü X menüsünü görüyor" sonucuna varabilir, ama gerçek görünürlük `role_menu_defaults`/`unit_menu_profiles`/`user_menu_permissions` tablolarındaki override'lara göre FARKLI olabilir. Bu, dokümantasyon ile davranış arasında değil, **iki ayrı ekran arasında** bir drift riskidir ve mevcut kodda hiçbir yerde açıkça uyarılmaz.

### 37.14 Kaynak dosyalar
- Route (salt-okunur): `app/admin/role_matrix_routes.py` (27 satır)
- Route (düzenlenebilir, paylaşımlı): `app/account/routes.py` (bkz. §36.14)
- Karar motoru: `app/services/settings/effective_menu.py` (299 satır, facade) + `app/services/settings/effective_menu_parts/` (12 dosya, 3064 satır)
- Yazma katmanı: `app/services/settings/menu_profile_access.py` (507 satır), `menu_permissions.py` (111 satır), `menu_rules.py` (65 satır)
- Salt-okunur UI servis: `app/services/role_matrix_ui_service.py` (797 satır)
- Köprü: `app/route_support.py:404-440` (`build_menu_visibility_map`, `can_access_menu`, `menu_key_required`, `admin_required`)
- Şablon: `app/templates/admin/role_matrix_center.html` (257 satır), `app/templates/settings.html` (ilgili bölümler)

---

## 38. Dashboard

**Not — bu bölümün eklenme gerekçesi:** Önceki tur yalnızca §2 modül tablosunda tek satır bırakmıştı. Bu tur, başlangıç işaretçisi olarak verilen `app/services/dashboard_expansion_service.py`'yi açıp okudu ve önemli bir düzeltme buldu: **bu dosya kullanılmıyor.**

### 38.1 Amaç
Giriş yapan her kullanıcıya (role göre farklılaşan) tek bir özet ekranda performans dönem sağlığı, açık görev/toplantı/anket/destek/geri bildirim özetleri ve (yetkiliyse) AI karar destek panelini göstermek; ayrıca DB bağlantı/şema durumunu gösteren admin-only bir "db-check" alt ekranı sunmak.

### 38.2 Kullanıcı entry/navigasyon
Menü: `dashboard` menu_key'i ile korunan bir nav öğesi (adı base.html'de doğrulanmadı ama route decoratörü doğrulandı). URL'ler: `/dashboard` (kanonik) ve tarihsel takma ad `/performance/dashboard` — ikisi de aynı view.

### 38.3 Roller/erişim
- `/dashboard`, `/dashboard/rebuild-data`, `/dashboard/rebuild-chart/<chart_key>`, `/dashboard/heavy-panels`: `@login_required` + `@menu_key_required("dashboard")` (`app/dashboard/routes.py:29-58`).
- `/db-check`: `@login_required` + `@admin_required` + `@menu_key_required("db_check")` (`app/dashboard/routes.py:63-66`) — hem rol ailesi hem menü anahtarı ile ÇİFT korumalı.

### 38.4 Route'lar/API
| Route | Metod | Amaç |
|---|---|---|
| `/dashboard`, `/performance/dashboard` | GET | Ana HTML dashboard |
| `/dashboard/rebuild-data`, `/performance/dashboard/rebuild-data` | GET | JSON veri ucu (`build_dashboard_json_payload`) |
| `/dashboard/rebuild-chart/<chart_key>`, `/performance/dashboard/rebuild-chart/<chart_key>` | GET | Tek grafik JSON ucu |
| `/dashboard/heavy-panels`, `/performance/dashboard/heavy-panels` | GET | Ağır/yavaş panellerin gecikmeli (lazy) HTML parçası, 45 saniyelik runtime cache ile |
| `/db-check` | GET | DB/şema kontrol paneli (admin-only) |

### 38.5 Çekirdek servis/model
- `app/dashboard/routes.py` (71 satır) — ince route katmanı.
- `app/main_handlers/dashboard_handlers.py` (104 satır) — gerçek orkestrasyon: `dashboard()`, `dashboard_heavy_panels()`, `db_check()`, cache-key üretimi (`_dashboard_cache_key`, kullanıcı+scope bazlı), `build_dashboard_rebuild_context` için 45 sn TTL runtime cache sarmalayıcı (`app/services/runtime_cache.py::get_or_set`).
- `app/services/dashboard_rebuild_service.py` (898 satır) — **asıl veri motoru**; SQLAlchemy ORM değil, doğrudan `sqlalchemy.text()` ile ham SQL sorguları çalıştırıyor (aşağıda §38.6), tablo/kolon eksikliğine karşı savunmalı (`sa_inspect` ile şema kontrolü) — dosyanın kendi docstring'i: *"Sorgular tablo/kolon farklılıklarına karşı korumalıdır; eksik tablo veya boş veri dashboard'u beyaz ekrana düşürmez."*
- `app/view_helpers.py::build_dashboard_context`, `build_db_check_context` — temel bağlam üretimi.
- `app/services/ai/dashboard_panels.py` — AI panel/köprü içerikleri (yalnız `ADMIN_FAMILY_ROLES` üyeleri için `can_view_admin_ai=True`).
- **Doğrulanmış ölü kod:** `app/services/dashboard_expansion_service.py` (42 satır, tek fonksiyon `build_dashboard_catalog()`) — repo genelinde grep edildiğinde bu fonksiyonu çağıran TEK bir yer yok (yalnız kendi dosyasında tanımlı). Dosyanın kendi içindeki not bunu doğruluyor: *"Bu katalog Faz 8 sonrası dashboard genişletme backlogunu tek yerde toplar"* — yani hiç uygulanmamış bir gelecek-özellik listesi, canlı dashboard'un render ettiği hiçbir şeye bağlı değil.

### 38.6 DB bağımlılığı
`dashboard_rebuild_service.py` içinde ham SQL `FROM` ifadeleriyle doğrulanan tablolar: `evaluation_assignments`, `feedback_action_plans`, `feedback_campaign_assignments`, `feedback_requests`, `feedback_submissions`, `notifications`, `performance_evaluations`, `performance_low_score_processes`, `performance_periods`, `support_tickets`, `survey_assignments`, `survey_responses`, `surveys`, `users`. `query_health.dashboard` modülü (bkz. §41) ayrıca ORM tarafında `EvaluationAssignment`/`FeedbackMeeting` için N+1-güvenli sorgu yardımcıları sağlıyor.

### 38.7 Kalıcı depolama
N/A — dashboard hiçbir dosya üretmez/okumaz; tamamen DB + runtime bellek cache.

### 38.8 Güvenlik kontrolleri
Tüm uçlar GET (form/CSRF konusu yok). `menu_key_required` canlı menü haritasına bağlı (bkz. §37.3 — admin bypass'sız). `/db-check` ayrıca `admin_required` ile ikinci bir katman taşıyor.

### 38.9 Operasyonel bağımlılık
Yok — SMTP/Celery/harici servis gerektirmez. `app/services/runtime_cache.py` üzerinden 45 saniyelik in-process TTL cache kullanılır (Redis değil, `try/except` ile korumalı — cache başarısız olursa `_factory()` doğrudan çağrılır, sayfa çökmez).

### 38.10 Backup/restore ilişkisi
Dashboard kendi verisini üretmez, yalnız yukarıdaki tabloları okur — bu tablolar zaten kendi feature'larının (Performans, Destek, Anket, Bildirim vb.) yedeğine dahildir. Dashboard'a özel ayrı bir yedekleme gereksinimi yoktur.

### 38.11 Zamanlanmış/arka plan davranış
N/A — tamamen istek-anlık, `scripts/windows/` altında dashboard'a özel bir Scheduled Task bulunamadı.

### 38.12 Sorun giderme
1. Dashboard yavaş açılıyorsa → önce `/dashboard/heavy-panels` ucunun ayrı, gecikmeli yüklendiğini doğrulayın (ana `/dashboard` yalnız `detail_level="core"` bağlamı render eder); asıl ağır sorgular `_build_dashboard_heavy_context` içinde, 45 sn cache'li.
2. Bir dashboard kartı sürekli boş/sıfır görünüyorsa → `dashboard_rebuild_service.py`'nin ilgili `_Reader` sorgusunun `sa_inspect` ile tablo/kolon varlığını kontrol ettiğini, eksikse SESSİZCE boş döndüğünü unutmayın — loglarda hata olmayabilir, önce ilgili tablonun gerçekten migration ile geldiğini doğrulayın.
3. `/db-check` "DB Kontrol" sonucu beklenmedik hata gösteriyorsa → `current_app.extensions["schema_check_errors"]` listesine bakın; bu liste Schema Guard'ın boot-time doğrulamasından geliyor (bkz. §40).

### 38.13 Bilinen kısıt
`app/services/dashboard_expansion_service.py` tamamen ölü koddur — hiçbir route, template veya başka servis tarafından çağrılmaz. "Faz 8 sonrası backlog kataloğu" olarak yazılmış ama hiç uygulamaya bağlanmamış. Bu dosya matrisin orijinal başlangıç işaretçisinde (`_rebuild_service.py`nin yanında) dashboard'un gerçek bir parçası gibi listelenmişti — DEĞİL; gerçek motor yalnız `dashboard_rebuild_service.py`'dir.

### 38.14 Kaynak dosyalar
- Route: `app/dashboard/routes.py` (71 satır)
- Handler: `app/main_handlers/dashboard_handlers.py` (104 satır)
- Servis (gerçek motor): `app/services/dashboard_rebuild_service.py` (898 satır)
- Servis (ölü kod): `app/services/dashboard_expansion_service.py` (42 satır — kullanılmıyor)
- Şablon: `app/templates/dashboard.html` (225 satır), `app/templates/partials/dashboard_heavy_panels.html`, `app/templates/db_check.html`

---

## 39. Raporlama (PDF/Excel Dışa Aktarma)

**Not — bu bölümün eklenme gerekçesi:** Önceki tur yalnızca kütüphane bağımlılıklarını (`reportlab`/`openpyxl`/`XlsxWriter`) listelemişti, bunların GERÇEKTEN kullanılıp kullanılmadığını doğrulamamıştı. Bu tur bunu doğruladı ve önemli bir düzeltme buldu.

### 39.1 Amaç
Performans değerlendirme raporları, yayın geçmişi, mail geçmişi ve çeşitli modül ekranlarındaki listeleri kullanıcının indirebileceği/yazdırabileceği biçimlere (Excel dosyası veya yazdırmaya-hazır HTML) dönüştürmek.

### 39.2 Kullanıcı entry/navigasyon
Merkezi bir "Raporlama" menü öğesi YOK — dışa aktarma butonları ilgili modülün kendi ekranına dağılmış (ör. Performans Raporları ekranındaki "PDF" ve "Excel" butonları, `/performance/reports/export/pdf` ve Excel indirme ucu). Kullanıcı bu butonlara kendi modülünün ekranından ulaşır.

### 39.3 Roller/erişim
Modüle göre değişir; doğrulanan örnek: `/performance/reports/export/pdf` → `@login_required` + `@manager_required` + ayrıca `phase3_can_open_performance_reports(current_user)` özel kontrolü (`app/performance/reporting_routes.py:417-422`).

### 39.4 Route'lar/API
Tek bir route ailesi YOK, modül başına dağınık. Doğrulanan örnekler:
| Route | Metod | Mekanizma |
|---|---|---|
| `/performance/reports/export/pdf` | GET | `validate_inline_pdf_export()` satır sınırı kontrolü + `reports_pdf.html` render (tarayıcı `window.print()` ile PDF'e çevrilir) |
| Performans raporu Excel indirme (`build_performance_report_excel_download_response`) | GET | `openpyxl.Workbook` ile bellekte `.xlsx` üretilip `send_file` ile indirilir |

Repo genelinde `send_file()` çağıran **20 ayrı dosya** bulundu (`app/admin/*`, `app/communication/*`, `app/institutional/*`, `app/performance/*`, `app/file_center/routes.py`, `app/main_handlers/account_settings_helpers.py` vb.) — yani dışa aktarma tek bir modülün değil, neredeyse her ana modülün kendi Excel/CSV/binary indirme ucuna sahip olduğu, kasıtlı olarak dağınık bir mimari.

### 39.5 Çekirdek servis/model
- `app/services/pdf_export_guard.py` (23 satır) — tek işi `PDF_EXPORT_MAX_ROWS_INLINE` (varsayılan 250) sınırını kontrol etmek (`max_inline_pdf_rows`, `validate_inline_pdf_export`); dosya kendisi PDF ÜRETMEZ.
- `app/services/performance/export_service.py` — en eksiksiz doğrulanan örnek: `build_styled_excel_bytes` (openpyxl `Workbook`+`styles`), `build_excel_download_response`, `build_csv_text_download_response`, `build_binary_download_response`, `build_publish_log_export_response`, `build_mail_history_export_response`, `build_performance_report_excel_download_response`.
- Diğer benzer örnekler (isim deseni doğrulandı, içerik tek tek incelenmedi): `app/services/sp4c_export_notification_service.py`, `app/services/feedback_pro_export_service.py`, `app/services/performance_v2/export_workspace.py`.

### 39.6 DB bağımlılığı
Dışa aktarılan her modülün kendi tabloları (ör. performans raporu için `performance_evaluations`) — Raporlama'nın kendine ait bir tablosu YOK, salt-okuma katmanıdır.

### 39.7 Kalıcı depolama
**YOK** — hem Excel hem "PDF" çıktısı istek-anlık bellekte (`BytesIO`) üretilir, diske hiçbir dosya YAZILMAZ; kullanıcı indirdikten sonra sunucu tarafında iz bırakmaz.

### 39.8 Güvenlik kontrolleri
`PDF_EXPORT_MAX_ROWS_INLINE` (varsayılan 250) — büyük satır sayısında canlı sistemde zaman aşımı riskini önlemek için PDF/print-view üretimini reddedip kullanıcıyı Excel'e yönlendiren bir "guard" (`pdf_export_guard.py`). Rol bazlı erişim modül bazında değişir (§39.3).

### 39.9 Operasyonel bağımlılık
Yok.

### 39.10 Backup/restore ilişkisi
N/A — üretilen dosyalar kalıcı değildir, kaynak veri zaten ilgili modülün DB yedeğine dahildir.

### 39.11 Zamanlanmış/arka plan davranış
N/A.

### 39.12 Sorun giderme
1. "PDF" indirme çalışmıyor/boş sayfa geliyor gibi şikayet gelirse → önce şunu doğrulayın: bu sistemde **sunucu tarafında gerçek bir PDF motoru YOK** (aşağıya bakın); kullanıcı muhtemelen tarayıcının "Yazdır > PDF olarak kaydet" diyaloğunu tetiklemesi gerekiyor, `reports_pdf.html` bunun için `window.print()` çağırıyor.
2. Excel dosyası bozuk/açılmıyor şikayeti → `openpyxl` sürüm uyumsuzluğu veya `build_styled_excel_bytes` içindeki stil (`Font`/`Border`/`PatternFill`) tanımlarını kontrol edin.
3. "250 kayıttan fazla" uyarısı çıkıyorsa → bu kasıtlı bir korumadır (`PDF_EXPORT_MAX_ROWS_INLINE`), config'ten değiştirilebilir ama artırmak canlıda zaman aşımı riskini artırır.

### 39.13 Bilinen kısıt
**`requirements.txt`'te bildirilen `reportlab==4.4.10` ve `XlsxWriter==3.2.0` bağımlılıkları `app/` içinde HİÇBİR YERDE import edilmiyor** (`grep -rl "reportlab" app --include=*.py` → sıfır sonuç; `xlsxwriter`/`XlsxWriter` için de sıfır sonuç). Gerçek Excel üretimi tamamen `openpyxl` ile yapılıyor (14 dosyada kullanılıyor); "PDF" dışa aktarımı ise sunucu tarafında PDF üretmiyor, `reports_pdf.html`'i print-CSS (`@media print`) ile döndürüp tarayıcının `window.print()`'ine (`reports_pdf.html:99`) bırakıyor. Yani matrisin önceki turda "PDF/Excel export bağımlılıkları" diye listelediği üç kütüphaneden biri (`reportlab`) fiilen ölü bir bağımlılık, ikincisi (`XlsxWriter`) de aynı şekilde kullanılmıyor — bu, gelecekte bağımlılık temizliği yapılırken dikkat edilmesi gereken somut bir bulgu.

### 39.14 Kaynak dosyalar
- Guard: `app/services/pdf_export_guard.py` (23 satır)
- Örnek route: `app/performance/reporting_routes.py` (satır 417-451 civarı)
- Örnek servis: `app/services/performance/export_service.py`
- Diğer export servisleri (isim deseni ile bulunan, tek tek incelenmeyen): `app/services/sp4c_export_notification_service.py`, `app/services/feedback_pro_export_service.py`, `app/services/performance_v2/export_workspace.py`
- `send_file()` kullanan 20 dosyalık tam liste bu araştırmada çıkarıldı, ana handover'a eklenmesi gerekirse `grep -rl "send_file(" app --include=*.py` ile tekrar üretilebilir.

---

## 40. Schema Guard

**Not — bu bölümün eklenme gerekçesi:** Önceki turda hiç mention yoktu, yalnızca §2'ye tek satır eklenmişti. Bu tur mekanizmayı uçtan uca okudu.

### 40.1 Amaç
Uygulama açılışında (boot-time) veritabanı şemasının beklenen tablo/kolon/index setiyle uyumlu olup olmadığını kontrol etmek ve — yalnızca açıkça izin verilmişse — eksik tablo/kolon/index'i canlı DDL ile (idempotent, `IF NOT EXISTS` desenli) onarmak. Migration'ın (Alembic) yerini TUTMAZ; onun bir güvenlik ağıdır.

### 40.2 Kullanıcı entry/navigasyon
**Kullanıcı-görünür DEĞİL.** Tamamen arka plan/boot-time mekanizması; hiçbir route, menü öğesi veya template'i yoktur. Tek dolaylı görünür etkisi: `/db-check` ekranındaki (§38) `schema_check_errors` listesi, Schema Guard'ın `validate_required_schema()` adımının sonucudur.

### 40.3 Roller/erişim
N/A — bir route olmadığı için rol/decorator kontrolü yok. Devreye girip girmeyeceği tamamen ortam değişkenleriyle (env var) belirlenir (bkz. §40.9).

### 40.4 Route'lar/API
N/A — saf arka plan mekanizması, hiçbir HTTP route'u yok. (Dolaylı: `/db-check` route'u §38.4'te belgelendi ve Schema Guard'ın ürettiği hata listesini gösteriyor.)

### 40.5 Çekirdek servis/model
5 dosyalık paket (matris işaretçisi doğrulandı, DOĞRU):
- `app/schema_guard.py` (43 satır) — geriye dönük uyumluluk için tüm public sembolleri tek noktadan re-export eden orkestratör/facade.
- `app/schema_guard_types.py` (18 satır) — `TableRepair` dataclass.
- `app/schema_guard_core_repairs.py` (13 satır) — **kendisi de bir compatibility wrapper**, gerçek `TABLE_REPAIRS` listesini `app/schema_guard_core_maintenances.py`'den (621 satır — asıl tanım dosyası, matris işaretçisinde ADI GEÇMİYORDU, bu turda bulundu) re-export ediyor.
- `app/schema_guard_patches.py` (99 satır) — `SCHEMA_PATCHES`: `performance_evaluations`/`performance_periods` tablolarına eklenen ~20 adet `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` delta'sı.
- `app/schema_guard_engine.py` (283 satır) — asıl mantık: `should_auto_repair_schema()` ve `repair_runtime_schema(app)`.
- **Ayrı, farklı amaçlı bir dosya:** `app/services/ai/schema_guard.py` — bu 5 dosyanın PARÇASI DEĞİL, AI karar destek tarafında ayrı bir "auto_repair_hint" mesajı üreten farklı bir modül; isim benzerliği kafa karıştırıcı olabilir.

**Boot akışı:** `app/bootstrap/application_bootstrap.py:76` → `run_schema_guard_bootstrap(app, validate_required_schema)` (`app/startup_checks.py:87-99`) → `should_run_schema_validation_on_boot(app)` (migration komutuysa veya `TESTING`/SQLite ise ATLA) → eğer `AUTO_REPAIR_SCHEMA=true` VE `should_auto_repair_schema()` True ise `repair_runtime_schema(app)` çalışır → HER durumda `validate_required_schema(app)` çalışıp sonucu `app.extensions["schema_check_errors"]`'a yazar (bu, `/db-check` ekranının veri kaynağıdır).

### 40.6 DB bağımlılığı
`schema_guard_core_maintenances.py`'deki `TABLE_REPAIRS` listesinde tanımlı tüm tablolar (621 satırlık dosya — tek tek sayılmadı, ama kapsamı geniş çekirdek tablo ailesi); `schema_guard_patches.py`'de özel olarak `performance_evaluations`, `performance_periods`.

### 40.7 Kalıcı depolama
N/A.

### 40.8 Güvenlik kontrolleri
- **Migration komutu tespiti:** `sys.argv`'de `flask db`/`alembic`/`db upgrade` vb. varsa Schema Guard KESİNLİKLE devreye girmez (`should_auto_repair_schema()`, `schema_guard_engine.py:25-49`).
- **Varsayılan KAPALI:** `AUTO_REPAIR_SCHEMA` config'te `False` varsayılan (`app/bootstrap/factory_bootstrap.py:35`); yalnız açıkça `true` verilirse DDL çalışabilir.
- **Prod uyarısı:** `APP_ENV` production/staging iken `AUTO_REPAIR_SCHEMA=true` açıksa `app.logger.warning("AUTO_REPAIR_SCHEMA acik. Canli ortamda migration sonrasi gecici kullanim disinda onerilmez.")` uyarısı loglanır (`app/schema_guard_core_maintenances.py` çağrı zinciri, `app/startup_checks.py:90-93`) — engellenmiyor, sadece uyarılıyor.
- **Sahiplik (ownership) kontrolü:** `repair_runtime_schema` her tablo için `pg_tables`'dan `tableowner` okuyup aktif DB kullanıcısıyla karşılaştırıyor; sahip uyuşmazsa o tablo için ALTER/INDEX SESSIZCE atlanıyor (yetkisiz DDL denemeyip loglanıyor) — `_is_insufficient_privilege`/`_is_duplicate_object` ile PostgreSQL hata kodlarını (`42501`, `42P07`, `42710`) tanıyıp güvenli şekilde yutuyor.
- **SQLite'ta tamamen pasif:** `dialect_name == "sqlite"` ise fonksiyon hiçbir DDL çalıştırmadan erken çıkıyor (satır 152-154) — yalnız PostgreSQL için tasarlanmış.
- **Acil durum kaçışı:** `BYS_FORCE_SCHEMA_GUARD=1` migration komutu algılansa bile zorla çalıştırabilir; `BYS_SKIP_SCHEMA_GUARD=1` her koşulda kapatır.

### 40.9 Operasyonel bağımlılık
Yok — dış servise ihtiyaç duymaz, PostgreSQL bağlantısı zaten mevcut olmalı (SQLite'ta pasif). Tamamen `app.config`/env değişkenleriyle (`AUTO_REPAIR_SCHEMA`, `BYS_FORCE_SCHEMA_GUARD`, `BYS_SKIP_SCHEMA_GUARD`, `APP_ENV`) kontrol edilir.

### 40.10 Backup/restore ilişkisi
Dolaylı: DDL onarımı öncesi/sonrası ayrı bir yedek ALMAZ — bu bilinçli bir tasarımdır (idempotent `IF NOT EXISTS` deseni geri alınabilir DDL'dir), ama gerçek şema DÜZELTMESİ canlıda önerilen yol yine kontrollü migration'dır (dosya içi anchor yorumu: *"Üretimde şema düzeltme akışı otomatik onarım yerine kontrollü migration / db upgrade süreciyle yürütülmelidir."*).

### 40.11 Zamanlanmış/arka plan davranış
**Yalnızca boot-time** — her uygulama başlangıcında bir kez çalışır (Windows Scheduled Task veya cron DEĞİL, Flask app factory'nin bir parçası). `scripts/windows/` altında bu özellik için ayrı bir Scheduled Task bulunamadı (gerek de yok, zaten her process start'ta otomatik tetikleniyor).

### 40.12 Sorun giderme
1. Uygulama açılışında beklenmedik DDL hataları loglanıyorsa → `app.logger` içinde `"Schema guard DDL calistirirken kritik hata verdi."` (kritik, `except Exception` ile yutuluyor, app YİNE DE açılır) veya `"Schema guard atladi: ..."` (beklenen, sahiplik/yetki nedeniyle atlanan) satırlarını ayırt edin.
2. `/db-check` ekranı hata gösteriyorsa → `app.extensions["schema_check_errors"]` — bu `validate_required_schema()`'nın çıktısıdır (`app/bootstrap/schema_validation.py`), Schema Guard'ın DDL onarım kısmından BAĞIMSIZ çalışır (onarım kapalı olsa bile doğrulama her zaman çalışır).
3. Yeni bir ortamda tablo eksik hatası alınıyorsa → önce `flask db upgrade` çalıştırın; `AUTO_REPAIR_SCHEMA=true` yalnız GEÇİCİ, tek seferlik bir kurtarma anahtarıdır, kalıcı çözüm değildir.

### 40.13 Bilinen kısıt
Schema Guard SQLite'ta TAMAMEN pasiftir (`repair_runtime_schema` erken return eder) — yani yerel geliştirmede SQLite kullanan bir geliştirici bu mekanizmanın DDL onarım kısmını hiç göremez, yalnız PostgreSQL'de (prod/staging benzeri ortamlarda) test edilebilir. Ayrıca `schema_guard_core_repairs.py`'nin kendisi bir "compatibility wrapper" olup gerçek `TABLE_REPAIRS` tanımını 621 satırlık `schema_guard_core_maintenances.py`'ye devrediyor — bu isim/içerik ayrışması ilk bakışta kafa karıştırıcıdır (`core_repairs.py` küçük, gerçek büyük dosya `core_maintenances.py`).

### 40.14 Kaynak dosyalar
- `app/schema_guard.py` (43 satır, facade)
- `app/schema_guard_types.py` (18 satır)
- `app/schema_guard_core_repairs.py` (13 satır, wrapper) → `app/schema_guard_core_maintenances.py` (621 satır, asıl `TABLE_REPAIRS`)
- `app/schema_guard_patches.py` (99 satır, `SCHEMA_PATCHES`)
- `app/schema_guard_engine.py` (283 satır, `repair_runtime_schema`/`should_auto_repair_schema`)
- Boot entegrasyonu: `app/startup_checks.py` (106 satır), `app/bootstrap/application_bootstrap.py:76`, `app/bootstrap/schema_validation.py`
- İlgisiz ama isim-benzer dosya (karıştırılmamalı): `app/services/ai/schema_guard.py`

---

## 41. Query Health

**Not — bu bölümün eklenme gerekçesi:** Önceki turda "DB gözlem paneli (admin-only)" diye tanımlanmıştı. Bu tur kodu okuyunca bunun **YANLIŞ bir karakterizasyon** olduğunu tespit etti — düzeltiliyor.

### 41.1 Amaç
**Bu bir DB gözlem/izleme PANELİ DEĞİLDİR** (önceki turun karakterizasyonu hatalıydı — düzeltiliyor). Gerçekte iki ayrı, geliştirici/CI-odaklı yardımcı bir arada:
1. N+1 sorgu riskini azaltan, `joinedload` önceden uygulanmış hazır sorgu inşa fonksiyonları (dashboard ve performans görev panosu için).
2. Veritabanına HİÇ bağlanmayan, kaynak kodunu metin olarak tarayan statik bir "sorgu riski" analiz aracı + tavsiye niteliğinde (uygulanmayan) index kataloğu.

### 41.2 Kullanıcı entry/navigasyon
**Kullanıcı-görünür DEĞİL, admin panel de DEĞİL.** Repo genelinde `query_health` string'i için yapılan arama hiçbir route veya template ortaya çıkarmadı — yalnızca Python import zincirleri var. Bu tamamen bir backend mühendislik kütüphanesidir; dolaylı etkisi, onu KULLANAN route'ların (ör. Dashboard, Performans Görev Panosu) daha hızlı/N+1-güvenli çalışmasıdır.

### 41.3 Roller/erişim
N/A — route olmadığı için doğrudan rol kontrolü yok. Onu çağıran route'ların kendi yetkilendirmesi geçerlidir (ör. `app/performance/evaluation_core_routes.py` içindeki görev panosu route'ları).

### 41.4 Route'lar/API
**N/A (gerekçe: saf arka-plan/geliştirme mekanizması, kendi route'u yok).** `app/services/query_health_service.py` (38 satır) — eski import yolunu koruyan bir facade, `app.services.query_health` paketine yönlendiriyor; kendisi de route değil.

### 41.5 Çekirdek servis/model
`app/services/query_health/` paketi (7 dosya, 510 satır):
- `assignment_board.py` (75 satır) — Performans görev panosu için filtre/sıralama sorgu inşacıları.
- `constants.py` (44 satır) — `ALLOWED_ASSIGNMENT_STATUSES`, `WORKFLOW_FILTERS` vb.
- `dashboard.py` (37 satır) — `build_dashboard_assignment_query`/`build_dashboard_meeting_query`: `EvaluationAssignment`/`FeedbackMeeting` için `joinedload` önceden uygulanmış ORM sorguları (N+1 önleme).
- `index_contracts.py` (130 satır) — `RECOMMENDED_INDEXES`: DB'ye HİÇ dokunmayan, yalnız tavsiye SQL METNİ üreten (`to_sql()`) statik bir katalog; dosyanın kendi docstring'i: *"Bu modul veritabaninda otomatik DDL calistirmaz... Uretilecek SQL DBA/admin kontrolunden sonra manuel calistirilmalidir."*
- `static_query_guard.py` (104 satır) — `collect_query_risk_findings(root)`: `app/services`, `app/performance`, `app/communication`, `app/institutional`, `app/admin`, `app/support` altındaki `.py` dosyalarını METİN olarak tarayıp `.all()` kullanımı, `len(query.all())` deseni ve olası döngü-içi-sorgu (N+1) desenlerini bulan bir statik analiz aracı; dosyanın kendi docstring'i: *"Bu tarayici veritabanina baglanmaz."*
- `workflow_meta.py` (66 satır) — görev panosu filtre etiketleri.
- `__init__.py` (54 satır) — paket facade.
- **Tüketiciler (gerçek çağıranlar):** `app/performance/evaluation_core_routes.py` (görev panosu filtreleme), `app/services/ui_context/dashboard.py`, `app/services/query_health_service.py` (geriye dönük uyum facade'ı).
- **CI/kalite kapısı bağlantısı:** `app/services/go_live/final_quality_contracts.py` (satır 114-118), `index_contracts.py` ve `static_query_guard.py`'yi "Faz 6 sorgu sağlığı" kalite sözleşmesinin ZORUNLU dosyaları olarak listeliyor; bu sözleşme `tests/critical/test_claude_phase7_final_gate_contracts.py` tarafından test edilip go-live kalite kapısının bir parçası yapılıyor — yani bu iki dosyanın VAR OLMASI, CI'da otomatik doğrulanan bir kalite kontratı.

### 41.6 DB bağımlılığı
`dashboard.py`/`assignment_board.py` üzerinden `EvaluationAssignment`, `FeedbackMeeting` (ve görev panosu tablolarının) ORM sorgularını inşa eder; kendisi tablo eklemez/değiştirmez. `static_query_guard.py` ve `index_contracts.py` DB'ye HİÇ bağlanmaz (ikisi de kendi docstring'inde bunu açıkça belirtiyor).

### 41.7 Kalıcı depolama
N/A.

### 41.8 Güvenlik kontrolleri
N/A (route/kullanıcı girdisi yok) — tek "güvenlik" ile ilişkili yönü, `index_contracts.py`'nin ürettiği ALTER/CREATE INDEX SQL'inin OTOMATİK çalıştırılmaması, yalnız metin olarak üretilip DBA onayına bırakılmasıdır (kasıtlı insan-denetimli tasarım).

### 41.9 Operasyonel bağımlılık
Yok.

### 41.10 Backup/restore ilişkisi
N/A — kendi verisi yok.

### 41.11 Zamanlanmış/arka plan behavior
N/A — istek-anlık (sorgu inşacıları) veya geliştirici/CI-tetiklemeli (statik tarayıcı) çalışır, zamanlanmış bir görev değildir.

### 41.12 Sorun giderme
1. Performans görev panosu (assignment board) beklenmeyen/eksik satır gösteriyorsa → `app/services/query_health/assignment_board.py`'deki filtre mantığını ve `ALLOWED_ASSIGNMENT_STATUSES` (`constants.py`) listesini kontrol edin.
2. Dashboard'da N+1 sorgu şüphesi varsa (yavaşlık) → `dashboard.py`'deki `joinedload` seçeneklerinin gerçekten kullanılan route'a bağlı olup olmadığını doğrulayın; `static_query_guard.collect_query_risk_findings()`'i lokal çalıştırıp (`python -c "from pathlib import Path; from app.services.query_health.static_query_guard import collect_query_risk_findings; print(collect_query_risk_findings(Path('.')))"`) yeni riskli desen eklenip eklenmediğine bakın.
3. `tests/critical/test_claude_phase7_final_gate_contracts.py` başarısız oluyorsa → `index_contracts.py`/`static_query_guard.py` dosyalarının silinmediğini/yeniden adlandırılmadığını kontrol edin — bunlar go-live kalite kontratının doğrudan bir parçası.

### 41.13 Bilinen kısıt
Bu "özellik" bir kullanıcı arayüzüne sahip değildir ve **isminin çağrıştırdığı "gözlem paneli" hiçbir yerde mevcut değildir** — önceki devir turu bunu yanlış karakterize etmişti. `static_query_guard.py`'nin tespit yöntemi de kabaca metin-tabanlıdır (`.all()` string'i arıyor, gerçek AST analizi yapmıyor) — bu nedenle hem yanlış-pozitif (ör. yorum satırındaki `.all()`) hem yanlış-negatif (ör. `.all()` çağrısı bir yardımcı fonksiyonun içinde gizliyse) üretebilir; dosyanın kendi yorumunda da "bulgu üretmesi tek başına build'i düşürmez" diye bu sınırlama zaten kabul ediliyor.

### 41.14 Kaynak dosyalar
- Paket: `app/services/query_health/` (7 dosya, 510 satır: `__init__.py` 54, `assignment_board.py` 75, `constants.py` 44, `dashboard.py` 37, `index_contracts.py` 130, `static_query_guard.py` 104, `workflow_meta.py` 66)
- Geriye dönük uyum facade'ı: `app/services/query_health_service.py` (38 satır)
- CI kontrat bağlantısı: `app/services/go_live/final_quality_contracts.py` (satır 114-118), `tests/critical/test_claude_phase7_final_gate_contracts.py`
- Tüketiciler: `app/performance/evaluation_core_routes.py`, `app/services/ui_context/dashboard.py`

---

## 42. Settings Snapshot / Rollback (Ayar Geçmişi ve Geri Alma)

**Not — bu bölümün eklenme gerekçesi:** Önceki turda hiç mention yoktu. "Snapshot" kelimesi dosya-tabanlı bir yedek çağrıştırabilir — bu tur bunun YANLIŞ olduğunu, mekanizmanın aslında DB-satırı bazlı bir değişiklik-günlüğü (change log) + geri-yazma olduğunu doğruladı.

### 42.1 Amaç
Ayarlar ekranında (§36) yapılan HER değişikliği (genel sistem ayarı, modül ayarı, rol menü varsayımı, birim profili, kullanıcı bazlı override) öncesi/sonrası durumuyla birlikte denetlenebilir bir günlüğe kaydetmek ve istenirse tek tıkla önceki duruma geri almak — geri alma işleminin KENDİSİ de yeni bir günlük kaydı olarak saklanır (yani geri alma da geri alınabilir, sonsuz bir denetim izi zinciri).

### 42.2 Kullanıcı entry/navigasyon
Ayrı bir sayfa/route YOK — `/settings` ekranının "Ayar Geçmişi" (`settings-history`) bölüm-çapası (`settings_section_links`, §36.2) altında görüntülenir; her kayıt satırında bir "geri al" formu (`form_action=rollback_settings_change_entry`) vardır.

### 42.3 Roller/erişim
`/settings` ile aynı: `@admin_required` (bkz. §36.3) — ayrı bir yetki katmanı yok, tamamen Ayarlar ekranının bir parçası.

### 42.4 Route'lar/API
Ayrı bir route YOK — `/settings` POST'unun `form_action=rollback_settings_change_entry` dalı (`app/main_handlers/account_settings_helpers.py:244-245,513-526`). Girdi: `change_log_id` (int), opsiyonel `keep_user_id`.

### 42.5 Çekirdek servis/model
- `app/services/settings/change_logs.py` (105 satır) — `create_settings_change_log()` (yeni günlük satırı ekler, `db.session.add`, COMMIT ETMEZ — commit üst katmanda), `serialize_settings_state`/`deserialize_settings_state` (JSON, `sort_keys=True` ile deterministik), `list_recent_settings_change_logs()`.
- `app/services/settings/rollback_handler.py` (310 satır) — `rollback_settings_change_handler(log_id, ...)`: `row.change_scope`'a göre 5 ayrı geri-alma stratejisi dispatch eder (`ROLLBACK_SUPPORTED_SCOPES = ("system_settings","module_settings","role_menu_defaults","unit_menu_profiles","user_menu_overrides")`), her biri kendi `_rollback_*` fonksiyonuna sahiptir; işlem sonunda YENİ bir `SettingsChangeLog` satırı (`is_rollback=True`, `reverted_from_log_id=<orijinal>`) oluşturup TEK bir `db.session.commit()` ile kapatır.
- `app/services/settings/snapshots.py` (155 satır) — **isim "snapshot" olsa da bu dosya yan-etkisiz salt-okuma yardımcılarıdır** (kendi docstring'i: *"Bu dosya veritabanı bağlantısı kurmaz. Commit/rollback/log oluşturmaz."*), yalnız DB satırlarını (`SystemSetting`/`ModuleSetting`/`UserMenuPermission` query sonuçlarını) ekranda gösterilecek özet sözlüklere dönüştürür — DOSYA/DİSK snapshot'ı DEĞİLDİR.

### 42.6 DB bağımlılığı
`settings_change_logs` (`SettingsChangeLog` modeli, `app/models/settings_models.py:89-108`): `actor_user_id`, `target_user_id`, `target_role_name`, `target_unit_name`, `change_scope`, `action_type`, `summary`, `previous_state_json`, `new_state_json` (her ikisi de `db.Text`, serbest-form JSON), `reverted_from_log_id` (kendine referans FK), `is_rollback`. Geri alma işlemi ayrıca hedef scope'a göre `system_settings`/`module_settings`/`role_menu_defaults`/`unit_menu_profiles`/`user_menu_permissions` tablolarına YAZAR.

### 42.7 Kalıcı depolama
**Dosya sistemi YOK.** "Snapshot" tamamen `settings_change_logs.previous_state_json`/`new_state_json` kolonlarında saklanan JSON metnidir — DB dışında hiçbir yerde durmaz.

### 42.8 Güvenlik kontrolleri
- Tablonun kendisi yoksa (migration eksikse) `create_settings_change_log()` `None` döner ve `rollback_settings_change_handler` bunu `RuntimeError("settings_change_logs tablosu yok. Önce flask db upgrade çalıştırın.")` ile açıkça fail eder (sessiz veri kaybı yok).
- Geri alınacak `log_id` bulunamazsa `ValueError("Geri alınacak kayıt bulunamadı.")`.
- `row.change_scope` desteklenen 5 tipin dışındaysa `ValueError("Bu kayıt tipi geri alınamıyor.")` — whitelist mantığı.
- CSRF: `/settings` formlarıyla aynı korumaya tabi (§36.8).

### 42.9 Operasyonel bağımlılık
Yok.

### 42.10 Backup/restore ilişkisi
`settings_change_logs` tablosu standart DB yedeğine dahildir — yani ayar geçmişi/geri-alma yeteneği DB restore ile birlikte otomatik olarak geri gelir, ayrı bir dosya/arşiv yedeği GEREKMEZ.

### 42.11 Zamanlanmış/arka plan davranış
N/A — tamamen istek-anlık, kullanıcı tetiklemeli.

### 42.12 Sorun giderme
1. "Geri al" butonu "Bu kayıt tipi geri alınamıyor" hatası veriyorsa → `SettingsChangeLog.change_scope` değerinin `ROLLBACK_SUPPORTED_SCOPES` (`rollback_handler.py:40-46`) listesindeki 5 değerden biri olduğunu doğrulayın; olası "communication_role_matrix" veya "assistant_role_matrix" gibi başka scope'lar bu mekanizma tarafından DESTEKLENMİYOR (kendi `_handle_save_communication_role_matrix`/`_handle_save_assistant_role_matrix` yolları var ama rollback zinciri bunları KAPSAMIYOR — bkz. §42.13).
2. "settings_change_logs tablosu yok" hatası → `flask db upgrade` çalıştırın.
3. Bir rol/birim profili geri alma işlemi beklenmeyen menü anahtarlarını etkiliyorsa → `_live_menu_keys()` (`rollback_handler.py:49-50`) yalnız `filter_live_menu_keys` ile "canlı" (kaldırılmamış) menü anahtarlarını işler; kaldırılmış (`is_removed_menu_key`) bir anahtar geri almadan ETKİLENMEZ — bu kasıtlıdır.

### 42.13 Bilinen kısıt
Rollback zinciri yalnız 5 scope'u destekler (`system_settings`, `module_settings`, `role_menu_defaults`, `unit_menu_profiles`, `user_menu_overrides`). Ayarlar ekranında GERÇEKTE kaydedilebilen bazı diğer form_action'lar (`save_communication_role_matrix`, `save_assistant_role_matrix`, `save_named_archive`/`apply_named_archive` şablon arşivi) bu değişiklik günlüğü/geri-alma mekanizmasının KAPSAMI DIŞINDADIR — yani bir admin İletişim Rol Matrisi'ni veya Sanal Asistan Rol Matrisi'ni yanlışlıkla değiştirirse, bunun için "Ayar Geçmişi" ekranından tek tıkla geri alma YOKTUR (elle düzeltmek gerekir).

### 42.14 Kaynak dosyalar
- `app/services/settings/change_logs.py` (105 satır)
- `app/services/settings/rollback_handler.py` (310 satır)
- `app/services/settings/snapshots.py` (155 satır — yalnız okuma/özet, gerçek "snapshot" verisi burada DEĞİL)
- `app/services/settings/menu_permissions.py` (111 satır — `snapshot_role_menu_state`/`snapshot_unit_menu_state`/`snapshot_user_override_state`, rollback_handler'ın kullandığı DB-okuma yardımcıları)
- Model: `app/models/settings_models.py:89-108` (`SettingsChangeLog`)
- Handler: `app/main_handlers/account_settings_helpers.py:244-245,513-526` (`_handle_rollback_settings_change_entry`)

---

## 43. Maintenance Mode (Bakım Modu)

**Not — bu bölümün eklenme gerekçesi:** Önceki turda hiç mention yoktu, matris satırında "Evet (genel bakım banner'ı)" diye kullanıcı-görünürlüğü tanımlanmıştı. Bu tur kodu okuyunca bir DÜZELTME buldu: bu mekanizma bir "banner" (sayfa üstünde bilgilendirme şeridi) DEĞİL, aktifken normal sayfaların yerine geçen TAM SAYFA 503 kilitlemesidir.

### 43.1 Amaç
Planlı bakım penceresinde (ör. deploy, migration) sistemi normal kullanıcılara KAPATMAK — tüm HTTP isteklerini (istisnalar hariç) 503 durum koduyla, kurumsal bir hata sayfasıyla reddetmek; operasyonel roller (admin ailesi + koordinatör) için erişimi AÇIK tutmak.

### 43.2 Kullanıcı entry/navigasyon
**Kullanıcının tetiklediği bir ekran/menü YOK.** Yalnız bir env değişkeni/`app.config` bayrağıdır (`MAINTENANCE_MODE`); ekranda görünen tek şey, aktifken normal kullanıcıların gördüğü `errors/503.html` tam sayfa hata ekranıdır — bu bir "banner" değil, TÜM sayfanın yerini alan bir kilit ekranıdır. Ayarlar ekranında (§36) bunu açıp kapatan bir form/toggle bulunamadı (`app/services/settings/catalog.py` içinde `MAINTENANCE` anahtarlı hiçbir setting_key yok) — yani DB-destekli, admin-panelinden değiştirilebilir bir ayar DEĞİL, yalnız ortam değişkeni/deploy-zamanı yapılandırmasıdır.

### 43.3 Roller/erişim
Route decorator'ı yok (bir `before_request` hook'u). Bypass mantığı `is_ops_bypass_user()` (`app/bootstrap/request_context.py:45-49`): `role in {"admin","baskan","baskan_yardimcisi","grup_baskani","koordinator"}` ise bakım modunda dahi erişim serbest. Bu set, `ADMIN_FAMILY_ROLES`'tan farklıdır — ayrıca `koordinator` içeriyor, `mali_musavir` içermiyor.

### 43.4 Route'lar/API
**N/A (gerekçe: bu bir route değil, tüm route'ları kapsayan bir `before_request` guard'ıdır).** `register_operational_guards(app)` içindeki `prepare_request_context()` fonksiyonunun bir parçası (`app/bootstrap/operational_guards.py:97-176`).

### 43.5 Çekirdek servis/model
- `app/bootstrap/operational_guards.py:152-176` — asıl guard mantığı: `maintenance_mode` bayrağını okur, istisna endpoint'lerini (`main.healthz`, `main.readyz`, `main.versionz`, `health.health`, `main.login`, `static`) hariç tutar, `is_ops_bypass_user` kontrolü yapar, geri kalan HER isteği `render_error_page(503, "Bakım Modu", ...)` ile reddeder.
- `app/bootstrap/startup.py:32,44-53` — `log_startup_summary()`: açılışta bakım modu durumunu (`on`/`off`) tek satır log özetine yazar; davranışı DEĞİŞTİRMEZ, yalnız gözlemlenebilirlik.
- `app/error_handlers.py:243` — 503 hata handler'ının GENEL (guard dışı, ör. gerçek bir 503 exception fırlarsa) fallback mesajı da aynı `MAINTENANCE_MESSAGE` config değerini kullanır.
- Kök `config.py:681-682` — `MAINTENANCE_MODE = str_to_bool(os.getenv('MAINTENANCE_MODE'), False)`, `MAINTENANCE_MESSAGE = os.getenv('MAINTENANCE_MESSAGE', '<varsayılan TR mesaj>').strip()`.
- `app/services/go_live_readiness_service.py:105-107` — go-live hazırlık kontrol listesinde "MAINTENANCE_MODE kapalı" bir kalem olarak GEÇİYOR (yani deploy öncesi kontrol listesi bu bayrağın kapalı olduğunu doğruluyor).

### 43.6 DB bağımlılığı
Yok — tamamen `app.config`/env tabanlı, hiçbir tabloya dokunmaz.

### 43.7 Kalıcı depolama
N/A.

### 43.8 Güvenlik kontrolleri
- İstisna endpoint whitelist'i (`healthz`/`readyz`/`versionz`/`health`/`login`/`static`) — health-check'lerin ve login sayfasının kilitlenmemesi için kasıtlı.
- Bakım modunda reddedilen her istek `record_security_event("maintenance_request_denied", ...)` ile güvenlik olay günlüğüne yazılır ve `current_app.logger.warning` ile loglanır — sessiz değil, izlenebilir.
- Rol-bazlı bypass (`is_ops_bypass_user`) — operasyonel roller bakım sırasında da sisteme girip doğrulama/deploy sonrası kontrol yapabilir.

### 43.9 Operasyonel bağımlılık
Yok — dış servise ihtiyaç duymaz. Devreye alma/kapatma tamamen ortam değişkeni değişikliği + uygulama yeniden başlatma (veya `app.config` çalışma-zamanı değişikliği varsa, ki kodda bunu yapan bir runtime-toggle uç bulunamadı — yani pratikte MAINTENANCE_MODE değiştirmek için süreç YENİDEN BAŞLATILMALI).

### 43.10 Backup/restore ilişkisi
N/A — kendine ait veri yok.

### 43.11 Zamanlanmış/arka plan davranış
N/A — bir zamanlayıcı değil, tüm istekler için çalışan bir `before_request` guard'ıdır (yani her istekte, sürekli aktif).

### 43.12 Sorun giderme
1. Bakım modu kapatılamıyor/hâlâ 503 dönüyor gibi görünüyorsa → `MAINTENANCE_MODE` env değişkeninin ayarlandığı yerde (ör. Windows servis ortam değişkeni, `.env`) değiştirilip uygulamanın YENİDEN BAŞLATILDIĞINDAN emin olun — kodda çalışma-zamanı (restart'sız) bir toggle mekanizması YOK.
2. Bir admin kullanıcı bakım modunda dahi giremiyor şikayeti → rolünün `is_ops_bypass_user`'daki 5 rolden (`admin`,`baskan`,`baskan_yardimcisi`,`grup_baskani`,`koordinator`) biri olduğunu doğrulayın — ör. `mali_musavir` rolü bu bypass listesinde YOKTUR (ADMIN_FAMILY_ROLES'ta olmasına rağmen).
3. Health-check'ler bakım modunda başarısız oluyorsa → `exempt_endpoints` set'inin (`operational_guards.py:156-163`) doğru endpoint isimlerini (`main.healthz` vb.) içerdiğini, izleme sisteminizin gerçekten bu path'lere istek attığını doğrulayın.

### 43.13 Bilinen kısıt
Matrisin önceki turdaki "genel bakım banner'ı" tanımı YANLIŞTIR — gerçek davranış bir banner değil, TÜM siteyi (istisnalar hariç) 503 ile kilitleyen bir tam-sayfa guard'dır. Ayrıca: (1) `.env.example` dosyasında `MAINTENANCE_MODE`/`MAINTENANCE_MESSAGE` için HİÇBİR örnek/dokümantasyon satırı yok — yeni bir operatör bu iki değişkenin var olduğunu ancak kaynak kodu okuyarak öğrenebilir; (2) bu davranışı doğrudan test eden ayrı bir test dosyası bulunamadı (yalnız `tests/conftest.py:30` içinde testlerin yanlışlıkla bakım moduna takılmaması için `os.environ.setdefault("MAINTENANCE_MODE","false")` var — guard'ın kendi davranışını (exempt endpoint'ler, bypass rolleri, 503 mesajı) doğrulayan bir regresyon testi YOK); (3) runtime toggle yok, her açma/kapama bir restart gerektirir.

### 43.14 Kaynak dosyalar
- Guard: `app/bootstrap/operational_guards.py` (satır 97-176 civarı, `register_operational_guards`/`prepare_request_context`)
- Bypass rol tanımı: `app/bootstrap/request_context.py:45-49` (`is_ops_bypass_user`)
- Başlangıç özeti: `app/bootstrap/startup.py:29-53` (`log_startup_summary`)
- Genel 503 fallback: `app/error_handlers.py:243`
- Config kaynağı: kök `config.py:681-682`
- Go-live kontrol listesi entegrasyonu: `app/services/go_live_readiness_service.py:105-107`
- Template: `app/templates/errors/503.html` (26 satır)
- Test: `tests/conftest.py:30` (yalnız varsayılan değer ataması, davranış testi değil)

---

## 44. İletişim Merkezi (Mesaj / Duyuru / Pop-up Duyuru)

*(Feature Coverage Matrix satır **#8**, önceki durum **PARTIAL**)*

### 44.1 Amaç

Kurum-içi kullanıcılar arası birebir/grup mesajlaşma (okundu takibi, tepki/emoji, arşiv, sabitleme,
sessize alma, canlı "yazıyor…" göstergesi), yöneticiden tüm personele **video/görsel destekli
pop-up duyuru** yayınlama (okundu-kapat takibi ile), ve daha eski bir "mesaj-akışı tabanlı toplu
duyuru" moduna geriye dönük erişim.

### 44.2 Kullanıcı akışı / navigasyon

`app/templates/base.html:590-611`, **"İletişim ve Anket Yönetimi"** akordeonu:
- **Mesajlar** → `/messages` (`main.messages_inbox`)
- **Kendime Notlar** → `/messages?scope=self` (aynı endpoint, `thread_type="self"`)
- **Duyurular** → `/announcements` (`main.announcements_list`)
- **Duyuru Gönder** → `/announcements/new` (`main.announcements_new`)

**Kritik davranış (kod okunarak doğrulandı, `announcements_routes.py:145-158,298-306`):**
Menüdeki "Duyurular"/"Duyuru Gönder" bugün fiilen **pop-up duyuru sistemine yönlendirir** —
`GET /announcements` → `redirect(url_for("main.announcement_popup_manage"))`, `GET /announcements/new`
→ `redirect(url_for("main.announcement_popup_new"))`, meğer ki `?mode=flow`/`?mode=legacy` veya
`?view=`/`?q=` parametresi verilsin. Yani menüdeki iki tıklanabilir öğe artık "video destekli pop-up
duyuru yönetimi" ekranına gider; eski `MessageThread(thread_type="announcement")` tabanlı toplu-mesaj
duyurusu hâlâ kodda çalışır durumda ama yalnız açıkça `mode=flow` ile istenirse.

### 44.3 Roller / erişim

- Tüm route'lar: `@login_required` + `@menu_key_required("messages")` veya `@menu_key_required("announcements")`.
  Bu decorator `app/route_support.py:424` içinde `can_access_menu(current_user, menu_key)`'e delege
  eder — **admin/üst-rol bypass'ı yoktur** (`BYS360_SETTINGS_LIVE_AUTHORITY_V2` notu); nihai karar
  Ayarlar > Rol Matrisi'nden gelen canlı menü haritasıdır.
- Eski "flow" duyuru gönderme akışı EK olarak `_can_use_announcement_tools(current_user)` kontrolü
  yapar (`app/services/message_service.py:392-393`), sabit kodlu
  `_ALLOWED_ANNOUNCEMENT_ROLES = {"admin","baskan","baskan_yardimcisi","grup_baskani","koordinator","mali_musavir"}`
  listesine bakar — yani pop-up duyuru ekranından farklı olarak bu ikinci katman rol-matrisine değil
  sabit bir listeye bağlıdır.
- Pop-up duyuru "acknowledge"/"dismiss" uçları (`/announcements/popup/<id>/acknowledge|dismiss`)
  `@csrf.exempt` + `@login_required`'dır — CSRF token yerine kendi oturum-bağlı HMAC token'ını kullanır
  (bkz. 44.8).

### 44.4 Routes / API (gerçek dosyadan doğrulandı)

| Route | Metod | Fonksiyon | Dosya |
|---|---|---|---|
| `/messages` | GET | `messages_inbox` | messages_routes.py:607 |
| `/messages/new` | GET/POST | `messages_new` | messages_routes.py:614 |
| `/messages/thread/<id>` | GET | `messages_thread` | messages_routes.py:621 |
| `/messages/thread/<id>/activity` | GET | `messages_thread_activity` | messages_routes.py:628 |
| `/messages/thread/<id>/live` | GET | `messages_thread_live` | messages_routes.py:635 |
| `/messages/thread/<id>/typing` | POST | `messages_thread_typing` | messages_routes.py:642 |
| `/messages/<id>/react` | POST | `messages_react` | messages_routes.py:649 |
| `/messages/<id>/comment` | POST | (yorum) | messages_routes.py:656 |
| `/messages/thread/<id>/send` | POST | `messages_thread_send` | messages_routes.py:665 |
| `/messages/thread/<id>/mark-read` | POST | `messages_thread_mark_read` | messages_routes.py:672 |
| `/messages/thread/<id>/mute-toggle` | POST | `messages_toggle_mute` | messages_routes.py:679 |
| `/messages/thread/<id>/archive-toggle` | POST | `messages_toggle_archive` | messages_routes.py:686 |
| `/messages/thread/<id>/pin-toggle` | POST | `messages_toggle_pin` | messages_routes.py:693 |
| `/messages/<id>/edit` | POST | `messages_edit` | messages_routes.py:700 |
| `/messages/<id>/delete` | POST | `messages_delete` | messages_routes.py:707 |
| `/messages/attachments/<filename>` | GET | `message_attachment_download` | messages_routes.py:714 |
| `/announcements` | GET | `announcements_list` (bkz. 44.2 yönlendirme) | announcements_routes.py:145 |
| `/announcements/new` | GET/POST | `announcements_new` (bkz. 44.2 yönlendirme) | announcements_routes.py:298 |
| `/announcements/popup/manage`, `/announcements/popup`, `/announcements/manage` | GET | `announcement_popup_manage` | announcement_popup_routes.py:169-171 |
| `/announcements/popup/new`, `/announcements/manage/new` | GET/POST | `announcement_popup_new` | announcement_popup_routes.py:210-211 |
| `/announcements/popup/<id>/edit`, `/announcements/manage/<id>/edit` | GET/POST | `announcement_popup_edit` | announcement_popup_routes.py:248-249 |
| `/announcements/popup/<id>/toggle` | POST | `announcement_popup_toggle` | announcement_popup_routes.py:285-286 |
| `/announcements/popup/<id>/target-count` | GET | `announcement_popup_target_count` | announcement_popup_routes.py:302-303 |
| `/announcements/popup/<id>/report[.csv]` | GET | `announcement_popup_report[_csv]` | announcement_popup_routes.py:312-346 |
| `/announcements/popup/media/<path:filename>` | GET | `announcement_popup_media` | announcement_popup_routes.py:359 |
| `/announcements/popup/runtime/pending` | GET | `announcement_popup_runtime_pending` | announcement_popup_routes.py:372 |
| `/announcements/popup/<id>/acknowledge` | POST (csrf-exempt) | `announcement_popup_acknowledge` | announcement_popup_routes.py:394 |
| `/announcements/popup/<id>/dismiss` | POST (csrf-exempt) | `announcement_popup_dismiss` | announcement_popup_routes.py:409 |

Not: Bu sayım (35 route) önceki turun "hub (routes.py) + phase-service" tanımından farklıdır;
gerçek route'lar `messages_routes.py`/`announcements_routes.py`/`announcement_popup_routes.py`
içindedir, `app/communication/routes.py` (218 satır) yalnız bunları import edip
`main_bp`'ye kaydeden bir **uyum omurgası**dır — kendi route'u yoktur.

### 44.5 Çekirdek servis / model

- **Servisler:** `app/services/message_service.py` (569 satır — mesaj thread CRUD, okundu takibi,
  `can_use_announcement_tools`), `app/services/announcement_popup_service.py` (782 satır — pop-up
  duyuru formu, medya yükleme, okundu/kapatma özet raporu, CSV export).
- **Modeller (`app/models/communication_models.py`, 619 satır):** `MessageThread`,
  `MessageThreadParticipant`, `Message`, `MessageReaction`, `MessageComment`, `MessageTypingState`,
  `MessageAttachment`.
- **Pop-up duyuru modelleri — AYRI dosyada (`app/models/announcement_popup_models.py`, 96 satır):**
  `Announcement` (`announcements` tablosu — title/body/type/is_required/show_rule/target_scope/
  target_role/target_unit_id/publish_start_at/publish_end_at/media_type/media_url/media_file_path/
  cta_url), `AnnouncementRead` (`announcement_reads` — first_seen_at/last_seen_at/dismissed_at/
  acknowledged_at/seen_count/ip_address/user_agent, `UniqueConstraint(announcement_id,user_id)`).
  **Düzeltme:** matrisin "communication_*_models.py" işaretçisi bu iki gerçek tabloyu KAÇIRIYORDU —
  pop-up duyuru şeması `communication_models.py` dosyasında değil, ayrı `announcement_popup_models.py`
  dosyasındadır.

### 44.6 DB bağımlılığı

`message_threads`, `message_thread_participants`, `messages`, `message_reactions`,
`message_comments`, `message_typing_states`, `message_attachments`, `announcements`,
`announcement_reads` — standart Alembic migration ile yönetilir (bu tablolar için ayrı bir adoption
sorunu bulunmadı, Dosya Merkezi'nin aksine).

### 44.7 Kalıcı depolama

Mesaj ekleri ve pop-up duyuru medyası (video/görsel/PDF) dosya sistemine yazılır
(`announcement_media_root()`, `app/services/announcement_popup_service.py`); indirme
`message_attachment_download_impl()` → `resolve_message_attachment_download_for_user()` ile
kullanıcı bazlı yetki kontrolünden geçirilerek `send_from_directory` üzerinden servis edilir.

### 44.8 Güvenlik kontrolleri

- Standart CSRF (`flask_wtf.CSRFProtect`, app genelinde aktif) tüm POST formlarında.
- Pop-up duyuru "okundu/kapat" uçları **istisna**: `@csrf.exempt`, bunun yerine kendi oturum-bağlı
  `_get_runtime_token()`/`_consume_runtime_token()` mekanizmasını kullanır — `hmac.compare_digest`
  ile karşılaştırılan, tek-kullanımlık OLMAYAN (sayfa yenilemede bozulmasın diye) bir session token'ı.
  Gerekçe kod içi yorumda açık: eski tek-kullanımlık token, dashboard/anasayfa arası gezinmede popup
  action'larını gereksiz yere reddediyordu.
- Duyuru gönderiminde çift-gönderim koruması: `issue_form_token`/`consume_form_token("announcement_send", scope=user_id)`.
- Anket/mesaj gövdesi `_clean_message_body()` ile temizlenir (script/markup sanitizasyonu).

### 44.9 Operasyonel bağımlılık

Doğrudan SMTP/Celery/Scheduled Task bağımlılığı YOK — mesaj/duyuru gönderimi senkron, HTTP isteği
içinde tamamlanır. Duyuru/mesaj bildirimi `_notify_user()` üzerinden `Notification` satırı yaratır;
bu satır oluşunca (bkz. §47/§48) **arka planda otomatik e-posta** tetiklenir — yani dolaylı bir SMTP
bağımlılığı vardır (e-posta gönderilemezse kullanıcı yine de uygulama-içi bildirimi görür, akış
kesilmez).

### 44.10 Yedekleme/restore ilgisi

Standart DB yedeğine dahildir (ayrı bir dosya/disk yedeği gerekmez, medya dosyaları hariç — pop-up
duyuru medyası `announcement_media_root()` altında diskte durur ve DB yedeğinin kapsamı dışındadır).

### 44.11 Zamanlanmış/arka plan davranış

YOK. Tüm işlemler kullanıcı etkileşimiyle tetiklenir.

### 44.12 Sorun giderme

1. Menüde "Duyurular" tıklanınca beklenmedik şekilde pop-up yönetim ekranı açılıyorsa — bu bir hata
   DEĞİL, `announcements_routes.py:145-158`'deki kasıtlı yönlendirmedir; eski akışa ulaşmak için
   `?mode=flow` eklenmelidir.
2. Pop-up duyuru "okundu" işaretlenmiyorsa — önce tarayıcı konsolunda `runtime_token`/
   `X-BYS360-Announcement-Token` header'ının gönderilip gönderilmediğine bakın; `_consume_runtime_token()`
   `hmac.compare_digest` ile session'daki `form_token:announcement_popup_runtime:<user_id>` değeriyle
   eşleşmezse sessizce 400 döner.
3. Mesaj eki indirilemiyorsa — `resolve_message_attachment_download_for_user()` içindeki yetki
   kontrolü (yalnız thread katılımcıları) veya diskteki dosyanın silinmiş/taşınmış olma ihtimaline
   bakın.

### 44.13 Bilinen kısıt

`app/communication/` altında ~19 "faz" route dosyası (phase1..phase9d) ve bunlara "anlamlı isim"
vermek için yazılmış ~10 alias-shim dosyası (`messages_core_routes.py`,
`notifications_core_routes.py` vb.) mevcut ama **hiçbiri app/templates/base.html'den erişilebilir
değil** (bkz. bölüm başındaki çapraz-kesen bulgu). Bu, aktif geliştirmenin bir kısmının kullanıcıya
hiç ulaşmadığı, dokümantasyon okuyan bir mühendisin "notifications_core_routes.py" gibi bir isme
bakıp yanlışlıkla gerçek bildirim kodu sanabileceği somut bir kod-tabanı risk/karışıklık kaynağıdır.

### 44.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| Route (hub/omurga) | `app/communication/routes.py` | 218 |
| Route (mesajlar) | `app/communication/messages_routes.py` | 725 |
| Route (duyuru-legacy) | `app/communication/announcements_routes.py` | 469 |
| Route (pop-up duyuru) | `app/communication/announcement_popup_routes.py` | 423 |
| Route yardımcıları | `app/communication/shared.py` | 230 |
| Servis | `app/services/message_service.py` | 569 |
| Servis | `app/services/announcement_popup_service.py` | 782 |
| Model (mesaj) | `app/models/communication_models.py` | 619 (yalnız Message* sınıfları bu bölümle ilgili) |
| Model (pop-up duyuru) | `app/models/announcement_popup_models.py` | 96 |
| Şablonlar | `app/templates/{messages_inbox,messages_new,messages_thread,announcement_new,announcements_list}.html`, `app/templates/communication/{announcement_popup_manage,announcement_popup_form,announcement_popup_report,_announcement_popup_runtime}.html` | — |
| Menü | `app/templates/base.html:590-611` | — |

---

## 45. Anket (Surveys)

*(Feature Coverage Matrix satır **#9**, önceki durum **PARTIAL**)*

### 45.1 Amaç

Yönetim tarafından oluşturulan, hedef kitleye (tümü/rol/birim/kişi) atanan çoktan-seçmeli/serbest-
metin anketlerin yayınlanması, personel tarafından doldurulması (tek seferlik, çift-gönderim korumalı),
ve sonuçların yönetici tarafında (yanıt oranı, dağılım, CSV export) izlenmesi.

### 45.2 Kullanıcı akışı / navigasyon

`base.html:596-598`, "İletişim ve Anket Yönetimi" akordeonu içinde:
- **Anketler** → `/surveys` (`main.surveys_list`, menu_key `surveys`)
- **Anket Yönetimi** → `/survey-manage` (`main.survey_manage`, menu_key `survey_manage`)
- **Anket Sonuçları** → `/survey-results` (`main.survey_results`, menu_key `survey_results`)

Anket doldurma: `/surveys/<id>/take` → `/surveys/<id>/submit` (POST).

### 45.3 Roller / erişim

- Tüm route'lar `@login_required` + `@menu_key_required(...)` — üç ayrı menü anahtarı
  (`surveys`, `survey_manage`, `survey_results`) kullanılır, yani "doldurma" ile "yönetim/sonuç"
  görme yetkisi Rol Matrisi'nde bağımsız olarak açılıp kapatılabilir.
- Anket yönetimi ayrıca `_service_survey_manager_allowed` (= `message_service.survey_manager_allowed`
  → `can_use_announcement_tools`) ile aynı sabit rol listesini (`admin, baskan, baskan_yardimcisi,
  grup_baskani, koordinator, mali_musavir`) tekrar kontrol eder — Duyuru Gönder (§44.3) ile aynı
  ikinci katman.
- Hedef kitle eşleştirmesi `user_matches_assignment()` (`message_service.py:527-542`) ile `all`/
  `user`/`role`/`unit` tiplerinde yapılır.

### 45.4 Routes / API

| Route | Metod | menu_key |
|---|---|---|
| `/surveys` | GET | `surveys` |
| `/surveys/<id>/take` | GET | `surveys` |
| `/surveys/<id>/submit` | POST | `surveys` |
| `/survey-target-users` | GET | `survey_manage` |
| `/survey-manage` | GET | `survey_manage` |
| `/survey-create` | GET/POST | `survey_manage` |
| `/survey-edit/<id>` | GET/POST | `survey_manage` |
| `/survey-publish/<id>` | POST | `survey_manage` |
| `/survey-unpublish/<id>` | POST | `survey_manage` |
| `/survey-close/<id>` | POST | `survey_manage` |
| `/survey-archive/<id>` | POST | `survey_manage` |
| `/survey-restore/<id>` | POST | `survey_manage` |
| `/survey-bulk-action` | POST | `survey_manage` |
| `/survey-delete/<id>` | POST | `survey_manage` |
| `/survey-results` | GET | `survey_results` |
| `/survey-results/export-csv` | GET | `survey_results` |

Kaynak: `app/communication/surveys_routes.py`, 1082 satır (görev tanımındaki başlangıç işaretçisi
"1074 satır" diyordu; bu turda `wc -l` ile 1082 doğrulandı — küçük fark, muhtemelen dosyanın bu
aralıkta ufak bir düzenleme geçirmiş olmasından).

### 45.5 Çekirdek servis / model

- **Servis paketi — `app/services/surveys/` (13 modül, 2691 satır toplam):** `authoring.py` (234),
  `contracts.py` (90), `listing.py` (193), `metrics.py` (53), `normalizers.py` (113),
  `questions.py` (193), `repository.py` (197), `results.py` (353), `schema.py` (64), `state.py`
  (193), `submission.py` (213), `submission_contract.py` (171), `targets.py` (393),
  `time_utils.py` (63), artı `__init__.py` (168, kamuya açık re-export yüzeyi).
- **Modeller (`app/models/communication_models.py` satır 431-582):** `Survey`, `SurveyQuestion`,
  `SurveyQuestionOption`, `SurveyAssignment`, `SurveyResponse`, `SurveyAnswer`. **Düzeltme:** görev
  tanımının listesi `SurveyQuestionOption` ve `SurveyAnswer`'ı atlamıştı — gerçekte 6 model var, 4 değil.

### 45.6 DB bağımlılığı

`surveys`, `survey_questions`, `survey_question_options`, `survey_assignments`, `survey_responses`,
`survey_answers` — hepsi `communication_models.py` içinde, standart Alembic akışıyla yönetilir.

### 45.7 Kalıcı depolama

N/A — anket soru/yanıt verisi tamamen DB'de tutulur, dosya sistemine yazılan bir öge yok (dosya
yükleme tipi soru bulunamadı).

### 45.8 Güvenlik kontrolleri

Standart CSRF + `@login_required` + `@menu_key_required`. Çift-gönderim koruması:
`issue_form_token("survey_submit", scope=f"{user_id}:{survey_id}")` /
`consume_form_token(...)` (`surveys_routes.py:97-99,388`) — yani her kullanıcı-anket çifti için ayrı
token scope'u, iki farklı anketi aynı anda doldururken birbirini bloklamaz.

### 45.9 Operasyonel bağımlılık

YOK — tamamen senkron, kullanıcı etkileşimiyle çalışan bir özellik.

### 45.10 Yedekleme/restore ilgisi

Standart DB yedeğine dahildir.

### 45.11 Zamanlanmış/arka plan davranış

N/A — anket dağıtımı/hatırlatması için ayrı bir Scheduled Task veya arka plan görevi bulunamadı
(`communication_survey_reminder_logs` adlı bir tablo `communication_phase3_models.py` içinde
tanımlı duruyor, ama bu tablo yalnız orphan "faz3" ailesine ait — gerçek `surveys_routes.py` akışı
bu tabloyu hiç kullanmıyor; muhtemelen tamamlanmamış bir hatırlatma özelliğinin kalıntısı).

### 45.12 Sorun giderme

1. Anket bir kullanıcıya görünmüyorsa — `SurveyAssignment.target_type`/`target_value` ile kullanıcının
   `role`/`birim` alanlarının `user_matches_assignment()` mantığına göre eşleştiğini kontrol edin
   (case-insensitive `strip().lower()` karşılaştırması).
2. "Bu anket zaten işleme alınmış" hatası tekrarlıyorsa — form-token scope'u `user_id:survey_id`
   olduğu için tarayıcıda önbelleğe alınmış eski bir form sayfası kullanılıyor olabilir; sayfayı
   yeniden yükleyin.
3. Sonuç CSV export'u boşsa — `survey_results_export_csv` yetkisi `survey_results` menu_key'ine
   bağlıdır, `survey_manage` yetkisinden bağımsızdır; kullanıcının doğru role sahip olduğunu doğrulayın.

### 45.13 Bilinen kısıt

Anket hatırlatma/otomasyon altyapısı (`communication_survey_reminder_logs`) modelde var ama hiçbir
route veya servis onu üretmiyor/tüketmiyor — pratikte anket dağıtımı tamamen manuel, hatırlatma
otomasyonu YOKTUR.

### 45.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| Route | `app/communication/surveys_routes.py` | 1082 |
| Servis paketi | `app/services/surveys/*.py` (14 dosya) | 2691 |
| Model | `app/models/communication_models.py` (Survey* sınıfları) | 619 (paylaşımlı dosya) |
| Şablonlar | `app/templates/{surveys_list,survey_take,survey_create,survey_edit,survey_manage,survey_results}.html` | 6 dosya |
| Menü | `app/templates/base.html:596-598` | — |

---

## 46. Destek / Yardım Merkezi

*(Feature Coverage Matrix satır **#10**, önceki durum **PARTIAL**)*

### 46.1 Amaç

Personelin destek talebi (ticket) açması, atanan kişi/ekip tarafından yanıtlanması/durumunun
takip edilmesi, çözüm sonrası değerlendirilmesi; ayrıca kategori/rol bazlı, aranabilir bir statik
**Yardım Merkezi** (help center) makale kütüphanesi.

### 46.2 Kullanıcı akışı / navigasyon

Route bulguları: `support_index` (`/support`), `support_new` (`/support/new`), `support_my_tickets`
(`/support/my-tickets`), `support_assigned` (`/support/assigned`), `support_all` (`/support/all`) —
bunların hepsi ayrı `menu_key`'lerle korunur (aşağıya bakınız), yani menüde görünen alt-öğe sayısı
kullanıcının rolüne göre değişir. Yardım Merkezi: `/support/help/search`,
`/support/help/category/<slug>`, `/support/help/role/<slug>`, `/support/help/article/<slug>`.

### 46.3 Roller / erişim

| Route grubu | Decorator zinciri |
|---|---|
| `/support`, `/support/help/*`, ticket detay/yorum/ek indirme | `@login_required` + `@menu_key_required("support_index")` |
| `/support/help-admin*` (makale CRUD, seed, sync) | `@login_required` + `@menu_key_required("support_index")` + **`@admin_required`** |
| `/support/setup` | aynı üçlü (admin_required dahil) |
| `/support/new` | `@login_required` + `@menu_key_required("support_new")` |
| `/support/my-tickets` | `@login_required` + `@menu_key_required("support_my_tickets")` |
| `/support/assigned` | `@login_required` + `@menu_key_required("support_assigned")` |
| `/support/all`, `/support/<id>/status`, `/support/<id>/assign` | `@login_required` + `@menu_key_required("support_all")` |
| `/support/<id>/rate` | `@login_required` + `@menu_key_required("support_my_tickets")` |

Yani "tüm talepleri gör/durum değiştir/ata" (`support_all`) ile "bana atananlar" (`support_assigned`)
ile "kendi taleplerim" (`support_my_tickets`) birbirinden bağımsız üç menü anahtarıdır — Rol
Matrisi'nde ayrı ayrı açılabilir/kapatılabilir.

### 46.4 Routes / API

24 route `app/support/routes.py` (1214 satır) içinde `main_bp` üzerinde kayıtlı; en önemlileri:
`GET/POST /support/new`, `GET /support/<id>`, `POST /support/<id>/comment`, `POST /support/<id>/status`,
`POST /support/<id>/assign`, `POST /support/<id>/rate`, `GET /support/<id>/attachments/<attachment_id>`,
`GET/POST /support/help-admin/new`, `GET/POST /support/help-admin/<id>/edit`,
`POST /support/help-admin/<id>/toggle-publish`, `POST /support/help-admin/<id>/delete`,
`POST /support/help-admin/seed`, `POST /support/help-admin/sync`.

### 46.5 Çekirdek servis / model

Bu modülde ayrı bir `services/support_*.py` yok — iş mantığı doğrudan `app/support/routes.py` içinde
yazılı (view fonksiyonlarının kendisi CRUD yapıyor). Statik Yardım Merkezi içeriği
`app/support/help_center_content.py` (1060 satır) içinde Python literal'leri olarak tanımlı
(`HELP_CATEGORIES` ve devamı) ve `/support/help-admin/seed` ile `SupportHelpArticle` tablosuna
yazılır (idempotent upsert, `/support/help-admin/sync`).

### 46.6 DB bağımlılığı (`app/models/support_models.py`, 255 satır)

`SupportCategory` (`support_categories`), `SupportTicket` (`support_tickets`),
`SupportTicketMessage` (`support_ticket_messages`), `SupportTicketAttachment`
(`support_ticket_attachments`), `SupportTicketStatusHistory` (`support_ticket_status_history`),
`SupportFeedbackRating` (`support_feedback_ratings`), `SupportHelpArticle` (`support_help_articles`).

### 46.7 Kalıcı depolama

Ticket ekleri diske yazılır (`_store_ticket_attachment()`, `support/routes.py:334`), izin verilen
uzantılar `{png, jpg, jpeg, pdf, docx, xlsx, txt, webp}`, boyut sınırı `MAX_CONTENT_LENGTH`
(varsayılan 16MB). İndirme `support_attachment_download` → `send_from_directory` +
`stored_name`/`filename` ayrımı (rastgele token'lı depolama adı, orijinal ad yalnız indirme
başlığında).

### 46.8 Güvenlik kontrolleri

`app/security/upload_security.py::validate_upload()` — dosya-uzantısı allowlist + **tehlikeli
uzantı blocklist** + **magic-byte imza doğrulaması** (`%PDF`, `PK\x03\x04` [docx/xlsx], PNG/JPEG/
GIF/WEBP imzaları) + `safe_store_filename()` (rastgele `secrets.token_hex(16)` tabanlı depolama adı,
path-traversal'a kapalı) + boyut sınırı. Standart CSRF + login + menu_key.

### 46.9 Operasyonel bağımlılık

Doğrudan SMTP/Scheduled Task bağımlılığı **YOK** (`scripts/windows/*.ps1` içinde "support" geçen
hiçbir script bulunamadı). Talep açılması/atanması/durum değişikliği `bys360_notification_bridge.py`
üzerinden `Notification` satırı üretir (`notify_support_ticket_created/comment/status_changed/
assigned/rating`), bu da dolaylı olarak §48'daki otomatik e-posta köprüsünü tetikler.

### 46.10 Yedekleme/restore ilgisi

Ticket/kategori/makale verisi standart DB yedeğine dahildir; ticket ekleri (dosya) DB dışıdır, ayrı
disk yedeği gerektirir (Dosya Merkezi'ndeki storage_root ile aynı prensip, ama bu modülün kendi ayrı
bir depolama kökü var — `current_app.config` üzerinden çözülen bir `UPLOAD_FOLDER` türevi;
Dosya Merkezi'nin storage_root() mekanizmasıyla PAYLAŞILMIYOR).

### 46.11 Zamanlanmış/arka plan davranış

N/A.

### 46.12 Sorun giderme

1. Ticket eki reddediliyorsa — önce uzantı allowlist'ini (`{png,jpg,jpeg,pdf,docx,xlsx,txt,webp}`)
   sonra `MAX_CONTENT_LENGTH` config değerini kontrol edin; magic-byte uyuşmazlığı da sessiz ret
   sebebi olabilir (dosya uzantısı doğru ama içerik imzası eşleşmiyorsa).
2. Yardım Merkezi makaleleri boşsa — `/support/help-admin/seed` hiç çalıştırılmamış olabilir (yeni
   ortam kurulumunda otomatik tetiklenmez, admin'in elle tetiklemesi gerekir).
3. "support_all" ekranı bir yöneticiye görünmüyorsa — bu üç menü anahtarından yalnızca biridir
   (`support_my_tickets`/`support_assigned`/`support_all`); Rol Matrisi'nde doğru anahtarın açık
   olduğunu doğrulayın.

### 46.13 Bilinen kısıt

Yardım Merkezi'nin "seed" içeriği kod içinde Python literal'i olarak gömülü (`help_center_content.py`,
1060 satır) — içerik güncellemesi bir kod değişikliği + deploy gerektirir, admin ekranından serbest
metin düzenleme mümkün olsa da (help-admin CRUD var) **varsayılan/seed içerik** için bu böyledir.
Ayrıca SLA politikası/atama-log modelleri (`CommunicationSupportSlaPolicy`,
`CommunicationSupportAssignmentLog`) `communication_phase3_models.py` içinde tanımlı ama bunlar da
orphan "faz3" ailesine ait — gerçek `support_models.py`/`support/routes.py` akışı bu tabloları
KULLANMIYOR, yani üretimde aktif bir SLA takip mekanizması yoktur.

### 46.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| Route | `app/support/routes.py` | 1214 |
| Yardım içeriği | `app/support/help_center_content.py` | 1060 |
| Model | `app/models/support_models.py` | 255 |
| Güvenlik | `app/security/upload_security.py` | (paylaşımlı, Dosya Merkezi ve Portal ile ortak) |
| Şablonlar | `app/templates/support/{detail,help_admin_form,help_admin_list,help_article,help_category,help_role,help_search,index,list,new,setup,_tabs}.html` | 12 dosya |
| Menü | menu_key'ler `support_index/new/my_tickets/assigned/all` (base.html "Genel" bölümü) | — |

---

## 47. Bildirimler (Notifications)

*(Feature Coverage Matrix satır **#15**, önceki durum **PARTIAL**)*

### 47.1 Amaç

Uygulama-içi tek merkezi bildirim kutusu: destek talebi, geri bildirim kampanyası, portal paylaşımı/
tepki/yorum/rapor, duyuru gibi olaylardan üretilen bildirimlerin okunması, filtrelenmesi
(okunmamış/öncelikli/anket/sistem/destek/performans), toplu okundu-yapma/silme.

### 47.2 Kullanıcı akışı / navigasyon

`base.html`'de doğrudan bir nav_item olarak görünmüyor (İletişim akordeonunun DIŞINDA, muhtemelen
üst bar'daki zil ikonuyla erişilir — `unread_notification_count` context processor'ı
`app/communication/routes.py:34-38`'de tüm sayfalara enjekte edilir). Ana ekran: `/notifications`
(`main.notifications_list`, menu_key `notifications`).

**Düzeltme:** Görev tanımının başlangıç işaretçisi `notifications_core_routes.py`'ı bu özelliğin
kaynağı olarak gösteriyordu — bu YANLIŞ. `app/communication/notifications_core_routes.py` gerçekte
`phase2_routes.py`'a (anket/bulletin yönetim paneli) aliaslanan 34 satırlık boş bir shim'dir,
bildirim kutusuyla hiçbir ilgisi yoktur (bkz. bölüm başındaki çapraz-kesen bulgu). Gerçek
implementasyon `app/communication/notifications_routes.py` (411 satır) dosyasındadır.

### 47.3 Roller / erişim

`@login_required` + `@menu_key_required("notifications")` — tüm 8 route için aynı tek menü anahtarı
(liste, tekli okundu/okunmadı işaretleme, tümünü okundu yap, toplu okundu/okunmadı/sil). Yalnız
`/notifications/unread-count` (rozet sayacı, AJAX polling için) `menu_key_required` OLMADAN yalnız
`@login_required` ile korunur — kasıtlı, çünkü bu uç her sayfada sessizce çağrılabilmeli.

### 47.4 Routes / API

| Route | Metod |
|---|---|
| `/notifications` | GET |
| `/notifications/unread-count` | GET |
| `/notifications/<id>/read` | POST |
| `/notifications/<id>/unread` | POST |
| `/notifications/mark-all-read` | POST |
| `/notifications/bulk-mark-read` | POST |
| `/notifications/bulk-mark-unread` | POST |
| `/notifications/bulk-delete` | POST |

### 47.5 Çekirdek servis / model

- **Model:** `Notification` (`app/models/communication_models.py:408-429`, `notifications` tablosu —
  user_id, title, body, notification_type, source_type, source_id, link_url, priority, is_read,
  read_at).
- **Üretici (fan-out) köprü:** `app/services/bys360_notification_bridge.py` (515 satır) — destek
  talebi (`notify_support_ticket_created/comment/status_changed/assigned/rating`), geri bildirim
  kampanyası (`notify_feedback_campaign_created/status_changed`, `notify_feedback_submission_received`,
  `notify_feedback_action_plan_created/status_changed`), portal (`notify_portal_post_created`,
  `notify_portal_reaction`, `notify_portal_comment_added`, `notify_portal_post_report`) olaylarını
  tek bir `create_notification[s]()` API'sine indirger. Bu servis `db.session.add()` yapar ama
  **commit çağırmaz** — commit'i çağıran işlem üstlenir (yorum: "Bildirim üretimi ana işlemi
  düşürmemeli").
- Bunun yanında genel amaçlı `_notify_user()` (`app/services/message_service.py`) mesaj/duyuru
  akışlarından çağrılır.

### 47.6 DB bağımlılığı

`notifications` tablosu (tek tablo, indeksli `user_id`+`is_read`+`created_at` sorgu deseni;
`notifications_routes.py` filtre/özet sorguları tek bir SQL aggregate ile 8 sayaç üretir —
`_notification_summary_counts()`).

### 47.7 Kalıcı depolama

N/A — tamamen DB satırı, dosya sistemi kullanılmaz.

### 47.8 Güvenlik kontrolleri

Standart CSRF + login + menu_key. Tüm sorgular `Notification.user_id == current_user.id` ile
filtrelenir (yatay yetki sızıntısı yok — bir kullanıcı başka birinin bildirimini ID tahmin ederek
göremez/işaretleyemez, çünkü `filter_by(id=..., user_id=current_user.id)` ikilisi kullanılır).
Okunmamış sayaç cache'i `app/services/runtime_cache.py` üzerinden invalide edilir
(`_invalidate_user_notification_cache`).

### 47.9 Operasyonel bağımlılık

Doğrudan yok, ama her `Notification` satırı oluşumu **otomatik olarak** §48'daki
`notification_mailer.py` SQLAlchemy event-listener'ını tetikler → SMTP'ye bağımlı hale gelir
(SMTP başarısız olursa yalnız log'a düşer, bildirim satırı ve uygulama akışı etkilenmez).

### 47.10 Yedekleme/restore ilgisi

Standart DB yedeğine dahildir.

### 47.11 Zamanlanmış/arka plan davranış

N/A — üretim tamamen olay-tetiklemeli (event-driven), zamanlanmış bir tarama/toplu-üretim yok.

### 47.12 Sorun giderme

1. Bir olay (örn. ticket ataması) bildirim üretmiyorsa — önce `bys360_notification_bridge.py`
   içindeki ilgili `notify_*` fonksiyonunun çağıran route'ta gerçekten çağrıldığını, sonra
   `create_notification()`'ın `db.session.add()` sonrası çağıran taraf tarafından **commit
   edildiğini** doğrulayın (bridge kendi commit etmiyor).
2. Rozet sayacı yanlış görünüyorsa — `runtime_cache` invalidation'ının okundu-işaretleme akışının
   her dalında (tekli/toplu/tümü) çağrıldığını kontrol edin.
3. `notifications_core_routes.py` adlı dosyaya bakıp burada gerçek kod arayan bir mühendis boşa
   zaman harcar — gerçek kod `notifications_routes.py`'dadır (bkz. 47.2 düzeltme notu).

### 47.13 Bilinen kısıt

Bildirim önceliği/tipi metin tabanlı serbest alanlardır (`notification_type`, `source_type` —
sabit bir enum/CHECK constraint yok); `_category_filter_expr()` bunları `ilike` ile eşleştirir,
yani yeni bir `notify_*` üretici eklenirken tip adı yanlış yazılırsa sessizce "system" kategorisine
düşer, hata vermez.

### 47.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| Route (gerçek) | `app/communication/notifications_routes.py` | 411 |
| Route (YANLIŞ işaretçi — kullanmayın) | `app/communication/notifications_core_routes.py` | 34 (phase2_routes alias'ı, ilgisiz) |
| Üretici köprü | `app/services/bys360_notification_bridge.py` | 515 |
| Model | `app/models/communication_models.py` (Notification sınıfı) | 619 (paylaşımlı dosya) |
| Şablon | `app/templates/notifications_list.html` | 1 dosya |

---

## 48. E-posta Otomasyonları

*(Feature Coverage Matrix satır **#16**, önceki durum **PARTIAL**)*

### 48.1 Amaç

Uygulamanın SMTP gönderim çekirdeği + üzerine kurulu otomasyonlar: performans hatırlatma/sonuç
mailleri, geri bildirim talep/yanıt mailleri, ve **her yeni `Notification` satırı için otomatik
e-posta bildirimi**. Kendi başına bir "kullanıcı özelliği" değil, diğer modüllerin (İK/Performans,
Destek, Portal, Anket, İletişim) kullandığı **ortak altyapıdır**.

### 48.2 Kullanıcı entry/navigasyon

**N/A** — bu bir kullanıcı-tıklanır ekran değil, çapraz-kesen bir altyapı katmanıdır. Kullanıcı bu
kodu dolaylı olarak, üstündeki gerçek özellik ekranlarından (Performans Mail Merkezi, Destek,
Duyuru Gönder, vb.) tetikler. `app/services/mail_performance_sender.py` içindeki fonksiyonlar
Performans modülünün admin ekranlarından çağrılır (bu belgenin kapsamı dışında, §17/Performans
bölümünde belgeli).

### 48.3 Roller / erişim

Doğrudan route/decorator YOK (bu bir servis katmanı). Üstündeki her çağıran ekran kendi
`admin_required`/`menu_key_required` kontrolünü uygular.

### 48.4 Routes / API

N/A (route içermez). Fonksiyon API'si:
- `app.services.mail_core.send_email(to_email, subject, body) -> (bool, str)` — **tek gerçek SMTP
  gönderim noktası**; `smtplib.SMTP` + STARTTLS, `current_app.config`'ten `MAIL_SERVER/MAIL_PORT/
  MAIL_USERNAME/MAIL_PASSWORD/MAIL_USE_TLS/MAIL_DEFAULT_SENDER` okur.
- `app.services.mail_core.create_mail_log(...)` — her gönderim denemesini `MailLog` tablosuna yazar
  (başarı/hata farketmeksizin).
- `app.services.mail_service` — **geriye-dönük uyum shim'i** (kendi kodu yok), `mail_feedback.py`
  (ki o da `mail_core.py`'den re-export eder) ve `mail_performance_sender.py`'den re-export eder.
  **Düzeltme:** görev tanımı `mail_service.py`'yi ayrı bir implementasyon gibi listeliyordu — gerçekte
  yalnızca bir import-uyum katmanıdır, gerçek kod `mail_core.py`/`mail_feedback.py`/
  `mail_performance_sender.py`'dedir.

### 48.5 Çekirdek servis / model

- `app/services/mail_core.py` (500 satır) — SMTP çekirdeği, mail şablon tanımları (performans
  hatırlatma/sonuç mailleri, `MAIL_TEMPLATE_DEFINITIONS`), `SystemSetting` tablosundan
  özelleştirilebilir konu/gövde şablonu okuma.
- `app/services/mail_feedback.py` (357 satır) — `mail_core`'dan re-export + geri bildirim talep/
  yanıt/toplantı mailleri (`send_feedback_request_mail`, `send_feedback_response_mail`,
  `send_feedback_meeting_created_mail`, `send_feedback_meeting_status_update_mail`).
- `app/services/mail_performance_builder.py` (392) + `mail_performance_sender.py` (831) —
  performans hatırlatma/sonuç-yayın maillerinin içerik üretimi ve toplu gönderim orkestrasyonu
  (bu belgenin kapsamı dışındaki §17/Performans konusudur, burada yalnız SMTP-tüketici olarak anılır).
- **`app/services/notification_mailer.py` (229 satır) — en kritik otomasyon parçası:** SQLAlchemy
  `Session` event listener'ları (`after_flush`, `after_commit`, `after_rollback`) kaydeder
  (`register_notification_mailer()`). Her commit edilen yeni `Notification` satırı için, kullanıcının
  DB'deki e-posta adresine otomatik bir "yeni bildiriminiz var" maili gönderir ve `mail_logs` tablosuna
  düz SQL `INSERT` ile log yazar (`text(...)` ile, ORM session'ı bypass ederek — kasıtlı, ana
  transaction'dan bağımsız olsun diye). `BYS360_NOTIFICATION_EMAILS_ENABLED` config bayrağıyla
  kapatılabilir (varsayılan açık).

### 48.6 DB bağımlılığı

`mail_logs` (`MailLog` modeli, `app/models/communication_models.py:114-158`) — tüm gönderim
denemelerinin (performans/geri-bildirim/bildirim-köprüsü) ortak log tablosu. `system_settings` —
özelleştirilebilir mail şablonları için.

### 48.7 Kalıcı depolama

N/A.

### 48.8 Güvenlik kontrolleri

- SMTP kimlik bilgileri (`MAIL_USERNAME`/`MAIL_PASSWORD`) yalnız Flask config/env üzerinden okunur,
  kod içinde sabit değer YOK.
- Header injection koruması: `_clean_header_value()` `\r`/`\n` karakterlerini temizler (konu/alıcı
  alanlarında CRLF injection'a kapalı).
- E-posta adresi doğrulama: `_normalize_email_address()` boşluk/`@` kontrolü yapar.
- `notification_mailer.py` kayıt işlemi **isteğe bağlı başlangıç kaydı** olarak çalışır
  (`app/__init__.py:36-41`, `OPTIONAL_STARTUP_REGISTRATIONS`) — kayıt başarısız olursa uygulama
  açılışını ENGELLEMEZ, yalnız stack trace ile loglanır (`_run_optional_startup`).

### 48.9 Operasyonel bağımlılık

**SMTP sunucusu zorunlu** (`MAIL_SERVER` boşsa `send_email()` sessizce `(False, "MAIL_SERVER ayarı
bulunamadı.")` döner — hata fırlatmaz, çağıran taraf sonucu kontrol etmezse mail sessizce
gönderilmemiş olur). Windows Scheduled Task bağımlılığı YOK bu katmanın kendisinde (tetikleyiciler
diğer modüllerin scheduled task'leridir — §50/§52).

### 48.10 Yedekleme/restore ilgisi

`mail_logs` ve `system_settings` standart DB yedeğine dahildir.

### 48.11 Zamanlanmış/arka plan davranış

Bu katmanın kendisi zamanlanmış değildir — event-tetiklemeli (`notification_mailer`) veya
diğer modüllerin scheduled task'lerinden (§50 Weather, §52 CIC, §49 Executive Summary) çağrılır.

**Somut, doğrulanmış bir çakışma bulgusu:** Aynı "günlük personel bilgilendirme" Scheduled Task'i
("BYS360 Daily Weather Personnel Mail" ve "BYS360 Daily Pulse Check Mail") en az **iki farklı**
installer script kuşağı tarafından kurulabilir durumda repoda duruyor:
`scripts/windows/install_bys360_daily_mail_tasks_v1_4.ps1` (launcher-doğrulamalı, kaynak-kontrollü
`.ps1` launcher zorunlu kılan güvenli sürüm) VE `scripts/windows/install_bys360_daily_weather_mail_task.ps1`
(aynı görev adlarını, aynı launcher desenini tekrar kuran neredeyse birebir kopya script) VE ayrıca
`scripts/windows/install_bys360_daily_pulse_mail_task.ps1` (yalnız pulse görevini tek başına kuran
üçüncü bir script). Bunların hangisinin "kanonik" olduğuna dair repo içinde bir işaretleme
bulunamadı (Executive Summary 0001/0830 görevlerinde olduğu gibi bir "bu TEK kaynak" yorumu YOK) —
operatör hangisini çalıştırdığını kendisi takip etmek zorunda.

### 48.12 Sorun giderme

1. Hiçbir mail gitmiyor — önce `current_app.config['MAIL_SERVER']` boş mu diye bakın; `send_email()`
   bunu sessizce False döndürür, exception fırlatmaz.
2. Bildirimler geliyor ama mail gitmiyor — `BYS360_NOTIFICATION_EMAILS_ENABLED` config değerini ve
   uygulama loglarında "BYS360 Notification Mailer V1 aktif edildi." satırının açılışta göründüğünü
   kontrol edin (görünmüyorsa `register_notification_mailer` optional-startup aşamasında
   sessizce başarısız olmuş olabilir — `app/__init__.py::_run_optional_startup` log'una bakın).
3. Performans/geri-bildirim mail şablonu beklenmedik metin gösteriyor — `SystemSetting` tablosunda
   `performance.mail_template.*` anahtarlarını kontrol edin, özelleştirme DB'den geliyor olabilir.

### 48.13 Bilinen kısıt

`send_email()` başarısızlığında exception fırlatmaz, `(False, mesaj)` tuple'ı döner — bu deseni
takip etmeyen (dönüş değerini kontrol etmeyen) bir çağıran nokta olursa mail sessizce kaybolur.
Ayrıca yukarıda belgelenen installer-script çoğullanması (48.11), aynı görev adının farklı
mekanizmalarla defalarca kurulup üzerine yazılabileceği anlamına gelir — bu Dosya Merkezi
bölümündeki (§34.6) benzer bir "arşivlenmiş script" riskiyle aynı kategoridedir.

### 48.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| SMTP çekirdeği | `app/services/mail_core.py` | 500 |
| Uyum shim'i | `app/services/mail_service.py` | 196 |
| Geri bildirim mailleri | `app/services/mail_feedback.py` | 357 |
| Performans mail üretimi | `app/services/mail_performance_builder.py` | 392 |
| Performans mail gönderim orkestrasyonu | `app/services/mail_performance_sender.py` | 831 |
| Otomatik bildirim-mail köprüsü | `app/services/notification_mailer.py` | 229 |
| Model | `app/models/communication_models.py` (MailLog sınıfı) | 619 (paylaşımlı) |
| Scheduled Task installer'ları (çoğullanmış) | `scripts/windows/install_bys360_daily_mail_tasks_v1_4.ps1`, `install_bys360_daily_weather_mail_task.ps1`, `install_bys360_daily_pulse_mail_task.ps1` | — |

---

## 49. Yönetici Özeti (Executive Summary)

*(Feature Coverage Matrix satır **#17**, önceki durum **PARTIAL**)*

### 49.1 Amaç

Sistem yöneticisine günlük özet e-postası (gece 00:01 "sistem kontrolü" + sabah 08:30 "günaydın
özeti") ve/veya ekran üzerinde canlı bir özet paneli: bekleyen geri bildirim/destek/performans/
onay/anket sayıları, hava durumu, sistem durumu.

### 49.2 Kullanıcı akışı / navigasyon — **kritik bulgu**

`app/templates/base.html` içinde `yonetici-ozeti`, `executive_summary`, `mail-center` veya
`executive_mail_center` dizgilerinden HİÇBİRİ geçmiyor (`grep` doğrulandı, 0 sonuç). Menü kaydı
ayrı bir mekanizmada, `app/menu_registry_data_sections.py:747-772`:

```
"key": "executive_summary", "label": "Yönetici Özeti",
"required_roles": ['admin','super_admin','system_admin','sistem_yoneticisi'],
"items": [ { "key": "daily_weather_mail", "label": "Günlük Personel Bilgilendirme", ... } ]
```

Yani **"Yönetici Özeti" menü bölümünün TEK alt-öğesi Günlük Personel Bilgilendirme (Hava Durumu
Maili) ayarlarıdır (§50)** — bizzat yönetici özeti ekranı (`/dashboard/yonetici-ozeti`) VE yeni
"Executive Mail Center v2" admin konsolu (`/executive-summary/mail-center/*`) menüden **hiç
bağlanmamış**, yalnız URL'i bilen bir admin tarafından doğrudan ziyaret edilerek erişilebilir.
Bu, önceki devir turunun "Evet (menü bölümü executive_summary, admin-only)" ifadesini kısmen
yanlışlar: menü bölümü GERÇEKTEN var ve admin-only, ama içindeki tek tıklanabilir öğe bu bölümün
kendi adını taşıyan özelliğe değil, komşu bir özelliğe (§50) gidiyor.

### 49.3 Roller / erişim

- `/dashboard/yonetici-ozeti`, `/yonetici-ozeti/data`, `/yonetici-ozeti/test-mail`:
  `@menu_key_required("executive_summary")` (`app/executive_summary/routes.py`). Kod içi yorum
  (satır 17-21) bunun bir **güvenlik düzeltmesi** olduğunu belirtiyor: "Phase 13B AUTH-002,
  confirmed anonim read + test-mail write" — yani bu route bir noktada **hiçbir yetkilendirme
  olmadan** anonim erişime açıktı, sonradan `menu_key_required` eklenerek kapatıldı.
- `/executive-summary/mail-center/*` (v2 konsolu): `@login_required` + kendi elle-yazılmış
  `_can_manage()`/`_require()` fonksiyonu (`executive_mail_center_v2_routes.py:16-30`), sabit
  `ADMIN_ROLES = {"admin","sistem_yoneticisi","system_admin","super_admin"}` — **`menu_key_required`
  kullanmıyor**, kendi rol kontrolünü tekrar yazmış (Rol Matrisi'nden bağımsız, sabit kodlu).

### 49.4 Routes / API

| Route | Metod | Sistem |
|---|---|---|
| `/dashboard/yonetici-ozeti` | GET | Eski/basit (`executive_summary/routes.py`) |
| `/yonetici-ozeti/data` | GET (JSON) | Eski/basit |
| `/yonetici-ozeti/test-mail` | POST | Eski/basit |
| `/executive-summary/mail-center` (+2 alias URL) | GET | v2 konsolu |
| `/executive-summary/mail-center/tasks` | GET/POST | v2 konsolu |
| `/executive-summary/mail-center/recipients` | GET/POST | v2 konsolu |
| `/executive-summary/mail-center/location` | POST | v2 konsolu |
| `/executive-summary/mail-center/test` | GET/POST | v2 konsolu |
| `/executive-summary/mail-center/send/<task_key>` | POST | v2 konsolu |
| `/executive-summary/mail-center/logs`, `/scheduler` | GET | v2 konsolu |

### 49.5 Çekirdek servis / model — **üç paralel implementasyon**

1. **`app/executive_summary/service.py`** (74 satır) — `build_executive_summary_payload()`.
   **Önemli bulgu:** bu fonksiyonun "metrics" alanı GERÇEK DB sorgusu YAPMAZ — `pending_feedback`,
   `open_support`, `pending_performance_tasks`, `pending_approvals`, `active_surveys` değerleri
   doğrudan `os.getenv("BYS360_SUMMARY_*", 0)` ile okunur; hava durumu da benzer şekilde
   `os.getenv("BYS360_WEATHER_*", "--")`. Yani ekran/mail **canlı veri değil, ortam değişkeni
   placeholder'ı** gösterir (kod içi yorum bunu doğruluyor: "intentionally defensive... before every
   module count query is wired to live tables").
2. **`app/executive_summary/mail_engine.py`** (162 satır) — `send_executive_summary_email()`,
   gece/sabah Scheduled Task'lerinin (§49.9) çağırdığı gerçek fonksiyon; yukarıdaki stub payload'ı
   kullanır.
3. **`app/services/executive_mail_center_v2.py`** (337 satır) — TAMAMEN AYRI, daha yeni bir
   "manager/staff sabah-öğlen-akşam mail" sistemi: `TASK_DEFINITIONS` (manager_morning/evening,
   staff_morning/midday/evening — 5 görev), `SystemSetting` tabanlı ayar deposu
   (`executive_mail_center.v2.*` anahtar öneki), `pilot_mode` bayrağı. Bu, aynı "personel sabah/akşam
   bilgilendirme + amir özeti" ihtiyacını **§52 CIC'in 5 görevine (staff_morning/noon/evening,
   manager_morning/evening) neredeyse birebir aynı isimlerle** ayrı bir sistemde tekrar uyguluyor.

**Düzeltme:** görev tanımının başlangıç işaretçisi yalnız `executive_mail_center.py`+`_v2.py`'yi
işaret ediyordu; gerçekte kullanıcıya görünen ekranın ARKASINDAKİ üçüncü, daha eski bir katman
(`app/executive_summary/{routes,service,mail_engine}.py`) de var ve asıl 0001/0830 Scheduled
Task'lerini besleyen odur.

### 49.6 DB bağımlılığı

`system_settings` (v2 konsolu ayarları), `mail_logs` (gönderim kayıtları,
`app.services.mail_core.create_mail_log` üzerinden). Ayrı bir "executive summary" tablosu YOK.

### 49.7 Kalıcı depolama

N/A.

### 49.8 Güvenlik kontrolleri

CSRF + login zorunlu tüm yollarda. `/dashboard/yonetici-ozeti` ailesi geçmişte (Phase 13B AUTH-002)
yetkilendirmesiz anonim erişime açıktı, artık `menu_key_required` ile kapatıldı (bkz. 49.3) — bu,
kod içinde açıkça belgelenmiş, düzeltilmiş bir geçmiş güvenlik açığıdır.

### 49.9 Operasyonel bağımlılık

**SMTP zorunlu.** Windows Scheduled Task: `"BYS360 Executive Summary 0830"` (`run_executive_summary_0830.ps1`
→ `scripts/executive/send_daily_executive_summary.py --type morning` → `mail_engine.send_executive_summary_email`)
ve `"BYS360 Executive Summary 0001"` (aynı desende `--type night`). Kurulum script'i
(`register_bys360_executive_summary_tasks_v2_14_3.ps1`) kod içi yorumda **kendini önceki kuşağın
(v2_14_1) yerine "TEK kanonik kaynak"** olarak tanımlıyor ve v2_14_1'in artık yalnız buna delege
ettiğini belirtiyor — yani bu ikisi için (48.11'deki weather/pulse installer çoğullanmasının aksine)
duplike kurulum riski repo içinde zaten kapatılmış.

Ayrıca "BYS360 Mail Center Manager/Staff Morning/Evening/Midday" (5 ayrı görev,
`install_bys360_executive_mail_center_v2_tasks.ps1`, `run_executive_mail_center_v2.py`) — v2
konsolunun kendi bağımsız Scheduled Task ailesi.

### 49.10 Yedekleme/restore ilgisi

Standart DB yedeğine dahildir (`system_settings`, `mail_logs`).

### 49.11 Zamanlanmış/arka plan davranış

Bkz. 49.9 — iki BAĞIMSIZ Scheduled Task grubu (eski "0001/0830" ikilisi + yeni "Mail Center
Manager/Staff ×5" beşlisi) aynı anda kurulu olabilir, ikisi de "yönetici özeti" şemsiyesi altında
ama farklı kod yollarını (farklı payload üretimini) çalıştırır.

### 49.12 Sorun giderme

1. Yönetici özeti mailinde hep "--" veya 0 görünüyorsa — bu bir hata değildir, `service.py`'nin
   ortam-değişkeni tabanlı stub davranışıdır (bkz. 49.5/49.13); gerçek sayı istiyorsanız v2 konsolunun
   (`executive_mail_center_v2.py`) kullanıldığından emin olun, o da kendi metrik toplama mantığına
   sahip (bu belgenin kapsamında derinlemesine incelenmedi).
2. "Executive Summary 0830/0001" görevi çalışmıyor — `scripts/windows/run_executive_summary_0830.ps1`
   içindeki `$ProjectRoot`'un gerçek kurulum yoluyla eşleştiğini (script sabit `C:\bys360\project`
   varsayıyor) ve `.venv\Scripts\python.exe`'nin var olduğunu doğrulayın.
3. Admin "Yönetici Özeti" menüsüne tıklayıp yalnız hava durumu ayarları görüyorsa — bu beklenen
   davranıştır (bkz. 49.2), gerçek özet ekranına gitmek için `/dashboard/yonetici-ozeti`'ni doğrudan
   ziyaret etmek gerekir.

### 49.13 Bilinen kısıt

**En önemli kısıt:** `build_executive_summary_payload()`'daki "metrics" alanı gerçek DB sorgusu
DEĞİL, ortam değişkeni okur — yani Scheduled Task'lerle (0001/0830) giden mailin içeriği,
`BYS360_SUMMARY_*` env değişkenleri elle ayarlanmadığı sürece anlamlı sayı taşımaz (varsayılan 0).
Bu, "otomatik yönetici özeti" özelliğinin ADI ile GERÇEK canlı-veri kapsamı arasında belirgin bir
fark olduğu, dürüstçe belgelenmesi gereken bir noktadır. İkinci kısıt: üç paralel implementasyon
(eski `executive_summary/`, `executive_mail_center.py` v1, `executive_mail_center_v2.py`) ve buna
ek CIC (§52) ile işlevsel örtüşme — kurumda kaç farklı "sabah/akşam personel maili" sisteminin AYNI
ANDA aktif olduğu operatör tarafından elle doğrulanmalıdır, kod bunu tek bir yerden göstermez.

### 49.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| Route (eski/basit) | `app/executive_summary/routes.py` | 49 |
| Servis (stub metrik) | `app/executive_summary/service.py` | 74 |
| Mail motoru (0001/0830) | `app/executive_summary/mail_engine.py` | 162 |
| Servis v1 | `app/services/executive_mail_center.py` | 227 |
| Servis v2 | `app/services/executive_mail_center_v2.py` | 337 |
| Route v2 | `app/communication/executive_mail_center_v2_routes.py` | 100 |
| Şablonlar | `app/templates/executive_summary/{yonetici_ozeti.html, mail_center/{base,overview,tasks,recipients,test,logs,scheduler}.html}` | 8 dosya |
| Menü kaydı | `app/menu_registry_data_sections.py:747-772` (yalnız hava durumu alt-öğesi) | — |
| Scheduled Task installer | `scripts/windows/register_bys360_executive_summary_tasks_v2_14_3.ps1`, `install_bys360_executive_mail_center_v2_tasks.ps1` | — |

---

## 50. Hava Durumu / Personel Mail Akışları

*(Feature Coverage Matrix satır **#18**, önceki durum **PARTIAL**)*

### 50.1 Amaç

Personele günaydın/iyi-akşamlar mesajı + güncel/yarınki hava durumu + kıyafet önerisi + motivasyon
notu içeren otomatik günlük e-posta; ayrıca portal ana sayfasında canlı bir hava durumu widget'ı.

### 50.2 Kullanıcı akışı / navigasyon

Menüden erişim: **"Yönetici Özeti" → "Günlük Personel Bilgilendirme"**
(`app/menu_registry_data_sections.py:754-769`, `endpoint: main.daily_weather_mail_settings`,
`system_admin_only: True`). Ekran 4 eşdeğer URL'den erişilebilir (tarihsel isim değişiklikleri
korunmuş): `/executive-summary/daily-weather-mail`, `/yonetici-ozeti/gunluk-hava-maili`,
`/communication/daily-weather-mail`, `/iletisim/gunluk-hava-maili`.

### 50.3 Roller / erişim

`@login_required` + kendi `_require_manage_permission()` (`daily_weather_mail_routes.py:96-104`),
sabit `_ALLOWED_ROLES = {"admin","super_admin","system_admin","sistem_yoneticisi"}` — **menü kaydı
seviyesinde de (`system_admin_only`), route seviyesinde de (`_can_manage_daily_weather_mail`) çift
kilitli**, `menu_key_required`/Rol Matrisi kullanılmıyor (CIC ve Executive Mail Center v2 ile aynı
"sabit rol listesi" deseni).

### 50.4 Routes / API

| Route (4 alias URL öneki hepsinde) | Metod |
|---|---|
| `.../daily-weather-mail` | GET |
| `.../daily-weather-mail/settings` | POST |
| `.../daily-weather-mail/send-now` | POST |
| `.../daily-weather-mail/dry-run` | POST |

### 50.5 Çekirdek servis / model

- `app/services/daily_weather_mail.py` (661 satır) — `current_config()`, `save_config()`,
  `run_daily_weather_mail()`, `preview_daily_weather_mail()`, `ensure_daily_weather_defaults()`,
  `get_recipient_users()`. Ayarlar `SystemSetting` üzerinde saklanır (ayrı tablo yok).
- `app/services/weather_service.py` (241 satır) — **dış API entegrasyonu:**
  `https://api.open-meteo.com/v1/forecast` (Open-Meteo, **API anahtarı gerektirmeyen** ücretsiz
  servis), `urllib.request.urlopen(..., timeout=4)`. Aynı zamanda `build_portal_weather_widget()`
  ile Portal ana sayfasındaki widget'ı da besler (§44/Portal ile ortak kullanım — çift amaçlı servis).
- `app/services/weather_recommendation_service.py` (341 satır) — hava koduna göre kıyafet/motivasyon
  metni üretimi (`_build_tip()` mantığının genişletilmiş hali).
- Route katmanı (`daily_weather_mail_routes.py`) servis import'unu `try/except` ile sarar; servis
  yüklenemezse **sayfa yine de açılır**, ama tüm işlemler "servis bağlı değil" mesajıyla no-op döner
  (kasıtlı "sistem düşmesin" fallback deseni, kod yorumunda açık).

### 50.6 DB bağımlılığı

`system_settings` (ayarlar), `mail_logs` (gönderim kayıtları, `MailLog` üzerinden).

### 50.7 Kalıcı depolama

N/A.

### 50.8 Güvenlik kontrolleri

CSRF + login + sabit rol kontrolü. Dış API çağrısı `timeout=4` ile sınırlı (hava durumu servisi
yanıt vermezse istek asılı kalmaz). API anahtarı YOK, dolayısıyla sızdırılacak bir SMTP-dışı sır
bulunmuyor.

### 50.9 Operasyonel bağımlılık

**SMTP zorunlu** + **Open-Meteo dış API'sine internet erişimi zorunlu** (kapalı/air-gapped bir
üretim ortamında hava durumu verisi alınamaz, mail muhtemelen "--" değerleriyle veya hatayla gider —
bu turda `_fetch_open_meteo()`'nun ağ hatasında ne döndüğü ayrıca doğrulanmadı, ancak `try/except`
deseni tüm dosyada tutarlı olduğu için sessiz fallback beklenir).

**Windows Scheduled Task: "BYS360 Daily Weather Personnel Mail"** — `scripts/communication/
send_daily_weather_personnel_mail.py`, sabah ~08:15 çalışacak şekilde kurulur. **En az 2 farklı
installer script bunu kurabilir** (bkz. §48.11 çakışma bulgusu) — `install_bys360_daily_mail_tasks_v1_4.ps1`
ve `install_bys360_daily_weather_mail_task.ps1`, ikisi de aynı görev adını hedefliyor.

### 50.10 Yedekleme/restore ilgisi

Standart DB yedeğine dahildir (`system_settings`, `mail_logs`); dış hava durumu verisi hiç
saklanmaz (her seferinde yeniden çekilir), yedeklemeyle ilgisi yok.

### 50.11 Zamanlanmış/arka plan davranış

Günlük ~08:15 (yapılandırılabilir `run_hour`/`run_minute`, `SystemSetting` üzerinden) — Windows
Scheduled Task ile. Ayrıca admin panelinden elle "Şimdi Gönder" (`send-now`) veya "Kuru Çalışma"
(`dry-run`, mail göndermeden alıcı sayısını doğrular) tetiklenebilir.

### 50.12 Sorun giderme

1. Mail gitmiyor ama ekran açılıyorsa — önce sayfadaki "Durum: ..." satırında `_SERVICE_ERROR`
   metnini kontrol edin (servis import hatası varsa burada görünür); sonra SMTP ayarlarına, sonra
   Open-Meteo'ya internet erişimine bakın.
2. Scheduled Task hiç çalışmamış görünüyorsa — `C:\bys360\logs\daily_weather_personnel_mail.log`
   dosyasını kontrol edin (installer script'i bu log dosyasını tanımlar).
3. Aynı isimde görevin iki kez kurulmuş/üzerine yazılmış olabileceğinden şüpheleniyorsanız —
   `Get-ScheduledTask -TaskName "BYS360 Daily Weather Personnel Mail" | Get-ScheduledTaskInfo` ile
   `LastTaskResult`/`NextRunTime` tek bir görev olarak göründüğünü doğrulayın (Windows Scheduled
   Task API'si aynı isimle yalnız bir görev tutar, ama HANGİ installer'ın onu SON kurduğu belirsizdir).

### 50.13 Bilinen kısıt

Bkz. §48.11 — bu görevin kurulumu için birden fazla, birbirinden habersiz installer script kuşağı
repoda duruyor; hangisinin son çalıştırılan/kanonik olduğu kod içinde işaretlenmemiş. Ayrıca
`executive_mail_center_v2.py`'nin `staff_morning`/`staff_evening` görevleri de kavramsal olarak
aynı "personele sabah/akşam bilgilendirme + hava durumu" işlevini ayrı bir sistemde tekrar
uyguluyor (bkz. §49.5) — kurumda hangi sistemin fiilen aktif tutulduğu operatör bilgisi gerektirir.

### 50.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| Route | `app/communication/daily_weather_mail_routes.py` | 226 |
| Servis (ayar/gönderim) | `app/services/daily_weather_mail.py` | 661 |
| Servis (dış API) | `app/services/weather_service.py` | 241 |
| Servis (öneri metni) | `app/services/weather_recommendation_service.py` | 341 |
| Menü kaydı | `app/menu_registry_data_sections.py:747-772` | — |
| Scheduled Task installer (çoğullanmış) | `scripts/windows/install_bys360_daily_mail_tasks_v1_4.ps1`, `install_bys360_daily_weather_mail_task.ps1` | — |

---

## 51. Nabız Yoklaması (Feedback / Pulse)

*(Feature Coverage Matrix satır **#24**, önceki durum **PARTIAL**)*

### 51.1 Amaç

Kurumsal Geri Bildirim çatısı altında: (a) günlük hızlı "nabız" girişi (tek tıkla ruh hali/durum),
(b) yönetim tarafından oluşturulan geri bildirim kampanyaları (soru-cevap), (c) sonuçların
analitik/trend görünümü, (d) sonuçlardan doğan iyileştirme aksiyon planları.

### 51.2 Kullanıcı akışı / navigasyon

`base.html:599-606`: **Kurumsal Geri Bildirim** (`/feedback`) → **Nabız Yoklaması** (`/feedback/pulse`)
→ **Nabız Analizi** (`/feedback/pulse/analytics` veya `/feedback/admin/pulse-analytics`,
`feedback_manager`/`feedback_admin` yetkisi) → **Geri Bildirim Anketleri** (`/feedback/campaigns`)
→ **Sonuçlar ve Eğilimler** (`/feedback/results`) → **İyileştirme Aksiyonları** (`/feedback/actions`)
→ **Yönetici Görünümü** (`/feedback/manager`) → **Kampanya Yönetimi** (`/feedback/admin/campaigns`).

### 51.3 Roller / erişim

7 ayrı menü anahtarı: `feedback_dashboard`, `feedback_pulse`, `feedback_manager`, `feedback_campaigns`,
`feedback_results`, `feedback_actions`, `feedback_admin` — hepsi `@menu_key_required(...)`, Rol
Matrisi'nden bağımsız yönetilir. Ayrıca bazı fonksiyonlarda `manager_required` decorator'ı da
import edilmiş (`feedback_routes.py:10`) — kampanya/analitik ekranlarında ek bir yönetici-seviyesi
kontrolü olarak kullanılıyor.

### 51.4 Routes / API (19 route, `app/communication/feedback_routes.py`)

`/feedback`, `/feedback/pulse` (GET/POST), `/feedback/pulse/history`, `/feedback/pulse/analytics`,
`/feedback/admin/pulse-analytics`, `/feedback/campaigns`, `/feedback/campaigns/<id>` (GET/POST),
`/feedback/results`, `/feedback/actions` (GET/POST), `/feedback/actions/new` (POST),
`/feedback/manager`, `/feedback/admin/campaigns`, `/feedback/admin/campaigns/new` (GET/POST),
`/feedback/admin/campaigns/<id>/status|publish|close` (POST),
`/feedback/results/<id>/export.csv`, `/feedback/pulse/analytics/export.csv`,
`/feedback/manager/export.csv`.

**Düzeltme:** görev tanımının işaretçisi `app/communication/feedback_*_routes.py` (çoğul) demişti;
gerçekte yalnız `feedback_routes.py` (399 satır) gerçek koddur. `feedback_action_plan_routes.py`,
`feedback_analytics_routes.py`, `feedback_campaign_routes.py`, `feedback_core_routes.py`,
`feedback_meeting_routes.py` (her biri 34 satır) yine "Core Refactor Faz 8" alias shim'leridir
(`phase9a/9b/9c/9d_routes.py`'a aliaslanır) — Nabız Yoklaması ile ilgisi YOKTUR.

### 51.5 Çekirdek servis / model

- `app/services/feedback_service.py` (919 satır) — `build_dashboard_data`, `build_pulse_analytics`,
  `save_pulse_entry`, `get_today_pulse_entry`, `get_pulse_history`, `create_campaign_from_form`,
  `submit_campaign_answers`, `build_campaign_results`, `create_action_plan`, `build_manager_summary`,
  `is_manager_family`, `list_visible_campaigns_for_user`.
- `app/services/feedback_action_service.py` (27), `feedback_report_service.py` (60),
  `feedback_pro_export_service.py` (31) — küçük yardımcı modüller.
- `app/services/ai/feedback_decision_support.py` — AI karar-destek panelleri (`build_manager_decision_support`,
  `build_pulse_analytics_decision_support`, `build_pulse_form_guidance`, `build_results_decision_support`);
  §28 AI Karar Destek ile kesişim.
- **Modeller (`app/models/feedback_models.py`, 219 satır):** `FeedbackCampaign`, `FeedbackQuestion`,
  `FeedbackQuestionOption`, `FeedbackCampaignAssignment`, `FeedbackSubmission`, `FeedbackAnswer`,
  `FeedbackPulseEntry`, `FeedbackActionPlan`.

### 51.6 DB bağımlılığı

`feedback_campaigns`, `feedback_questions`, `feedback_question_options`,
`feedback_campaign_assignments`, `feedback_submissions`, `feedback_answers`,
`feedback_pulse_entries`, `feedback_action_plans`.

### 51.7 Kalıcı depolama

N/A.

### 51.8 Güvenlik kontrolleri

Standart CSRF + login + menu_key. CSV export'larda **oturum-bazlı rate limit** var
(`_can_export_feedback_now()`, `feedback_routes.py:48-58`) — aynı kullanıcı 12 saniye içinde ikinci
kez export isteyemez (`session[f"feedback_results_export_at_{user_id}"]` zaman damgası kontrolü).
Bu, incelenen 9 özellik arasında rastlanan **tek elle-yazılmış rate-limit örneğidir** (diğerlerinde
Flask-Limiter gibi merkezi bir mekanizma yok).

### 51.9 Operasyonel bağımlılık

Doğrudan yok (senkron, kullanıcı etkileşimli). Kampanya/aksiyon planı oluşturma
`bys360_notification_bridge.py::notify_feedback_campaign_created/status_changed/
notify_feedback_submission_received/notify_feedback_action_plan_created/status_changed` üzerinden
§47/§48 bildirim+mail zincirini tetikler.

### 51.10 Yedekleme/restore ilgisi

Standart DB yedeğine dahildir.

### 51.11 Zamanlanmış/arka plan davranış — **doğrulanmış boşluk**

`app/tasks/feedback_tasks.py::refresh_pulse_analytics_for_unit()` ve
`app/tasks/core_background_tasks.py::refresh_feedback_pulse_analytics()` RQ-worker uyumlu şekilde
yazılmış ("Bu görevler RQ worker içinde de, kontrollü inline fallback içinde de çalışabilecek şekilde
yazılmıştır" — dosya başlığı) analitik-cache-yenileme fonksiyonlarıdır. **Ancak** `grep -rn
"refresh_feedback_pulse_analytics\|run_nightly_maintenance_bundle" app/` hiçbir çağıran nokta
BULAMADI — ne bir Scheduled Task installer, ne bir RQ `enqueue()`/`.delay()` çağrısı, ne bir
`app/tasks/` içi zamanlayıcı kaydı. Yani bu fonksiyonlar **tanımlı ama şu an hiçbir yerden
tetiklenmiyor**; pratikte `build_pulse_analytics()` her istek için `/feedback/pulse/analytics`
route'unda **senkron/on-demand** hesaplanıyor (route import listesinde doğrudan
`_service_build_pulse_analytics_decision_support`/`build_pulse_analytics` çağrısı var).

### 51.12 Sorun giderme

1. "Nabız Analizi" ekranı yavaşsa — bu beklenir, analitik her istekte senkron hesaplanıyor (51.11);
   bir arka plan cache mekanizması aktif DEĞİL.
2. Export butonu tepki vermiyorsa — 12 saniyelik `_can_export_feedback_now()` rate-limit'e takılmış
   olabilir, kullanıcıya "az sonra tekrar deneyin" mesajı beklenmelidir (kod tarafında sessiz ret
   olup olmadığı bu turda ayrıca UI'dan doğrulanmadı).
3. Aksiyon planı bildirimi gitmiyorsa — `notify_feedback_action_plan_created`'ın `assigned_manager_id`
   alanının dolu olduğunu kontrol edin; boşsa alıcı listesi boş kalır.

### 51.13 Bilinen kısıt

Arka plan analitik-yenileme görevleri (RQ worker için hazırlanmış) tanımlı ama BAĞLANMAMIŞ —
gelecekte bir RQ worker/scheduler kurulursa devreye girecek şekilde yazılmış ama şu an ölü koddur.
Ayrıca "BYS360 Daily Pulse Check Mail" adlı Scheduled Task'in (§50.9'da bahsi geçen) bu özellikle
**hiçbir ilgisi yoktur** — isim benzerliği yanıltıcıdır; o görev `app.services.executive_mail_center`
(v1, §49) ailesine ait, `scripts/communication/send_daily_pulse_check_mail.py` script'inin `main()`
fonksiyonu ise yalnızca bir `print()` yapar ve gerçek mail gönderme kodu kasıtlı olarak eksik
bırakılmıştır (kod içi yorum: "Gerçek mail gönderim fonksiyonu... Şimdilik log/test çıktısı
üretir") — yani bu görev günlük çalışsa bile üretim ortamında fiilen hiçbir mail göndermez, yalnız
konsola/log dosyasına bir özet yazar.

### 51.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| Route (gerçek) | `app/communication/feedback_routes.py` | 399 |
| Route (YANLIŞ işaretçiler — alias, ilgisiz) | `feedback_{action_plan,analytics,campaign,core,meeting}_routes.py` | 34×5 |
| Servis | `app/services/feedback_service.py` | 919 |
| Servis (küçük yardımcılar) | `feedback_action_service.py`, `feedback_report_service.py`, `feedback_pro_export_service.py` | 27+60+31 |
| Model | `app/models/feedback_models.py` | 219 |
| Arka plan görevi (bağlanmamış) | `app/tasks/feedback_tasks.py` | 45 |
| Şablonlar | `app/templates/feedback/{dashboard,pulse_form,pulse_history,pulse_analytics,campaign_list,campaign_form,campaign_manage,campaign_take,results,action_list,manager_view,quick_feedback,quick_feedback_success,admin_campaign_new_bys360_live}.html` | 14 dosya |
| Menü | `app/templates/base.html:599-606` | — |

---

## 52. Kurumsal Bilgilendirme Merkezi (CIC)

*(Feature Coverage Matrix satır **#25**, önceki durum **PARTIAL**)*

### 52.1 Amaç

Personel/yöneticiye günün üç diliminde (sabah/öğlen/akşam personel, sabah/akşam yönetici) otomatik
kurumsal bilgilendirme maili + doğum günü/iş yıldönümü/özel gün "akıllı kutlama" maili gönderimi;
Excel ile toplu kutlama-tarihi içe aktarma; test-gönderim merkezi; gönderim geçmişi/log ekranı.

### 52.2 Kullanıcı akışı / navigasyon

`base.html:715-739`, ayrı bir üst-seviye akordeon (**İletişim akordeonunun İÇİNDE DEĞİL**),
`{% if (role_name|default('')|string|lower) in [...] %}` ile şablon seviyesinde gösterilir:
**Genel Bakış** (`/dashboard/kurumsal-bilgilendirme`) → **Kutlamalar** (`.../kutlamalar`) →
**Görev Yönetimi** (`.../gorevler`) → **Alıcı Yönetimi** (`.../alicilar`) → **Şablon Yönetimi**
(`.../sablonlar`) → **Test Merkezi** (`.../test`) → **Gönderim Geçmişi** (`.../loglar`) →
**Sistem Durumu** (`.../sistem`).

### 52.3 Roller / erişim

Menü seviyesinde inline Jinja rol kontrolü (`admin, administrator, sistem_yoneticisi, super_admin,
system_admin`) VE route seviyesinde `app/services/cic/access_policy.py::can_manage()` — **aynı 5
rolü** ayrı bir modülde (`ADMIN_ROLES` frozenset) tekrar tanımlar; her route `_guard()` yardımcı
fonksiyonu ile bunu çağırıp `abort(403)` yapar. `menu_key_required`/Rol Matrisi kullanılmaz — bu
CIC'i, Executive Mail Center v2 ve Weather Mail ile aynı "sabit-rol, Rol Matrisi'nden bağımsız"
gruba sokar.

### 52.4 Routes / API (`app/communication/corporate_information_center_routes.py`, 276 satır)

`GET /dashboard/kurumsal-bilgilendirme`, `GET/POST .../gorevler`, `POST .../gorevler/<key>/calistir`,
`GET/POST .../alicilar`, `GET/POST .../sablonlar`, `GET/POST .../test`, `GET .../loglar`,
`GET/POST .../sistem`, `GET/POST .../kutlamalar`, `POST .../kutlamalar/<key>/calistir`,
`GET .../kutlamalar/excel-sablon` (openpyxl ile örnek Excel şablonu üretir), `POST
.../kutlamalar/excel-yukle` (ön-kontrol/uygula iki modlu Excel içe aktarma).

### 52.5 Çekirdek servis / model

`app/services/cic/` paketi (3985 satır, 13 modül) — **kanonik giriş noktası**
`app.services.cic.service.send_task` (kendi `README.md`'sinde açıkça belirtilmiş ve
`tests/architecture/test_cic_service_entrypoint_v1.py` ile korunan bir sözleşme):
- `service.py` (37) — yalnız 13 operasyonu dışa açan ince cephe.
- `facade.py` (232) — **"tarihsel uyumluluk cephesi"**, README'de "artık aktif üretim kodu
  import ETMEMELİ" diye işaretli, ~100 isimlik eski import yüzeyini korumak için tutuluyor.
- `mail_service.py` (424) — SMTP gönderim (önce `app.services.mail_core.send_email`'i dener, o
  yoksa kendi `SystemSetting`-tabanlı SMTP ayarlarını okuyup doğrudan `smtplib` kullanır).
- `scheduler_service.py` (215), `query_service.py` (137), `template_service.py` (268),
  `celebration_service.py` (391), `celebration_dates.py` (130), `config_context.py` (376),
  `misc_context.py` (500), `cic_context.py` (496), `save_context.py` (224), `task_contract.py` (234),
  `access_policy.py` (22).

### 52.6 DB bağımlılığı

**Kendine ait bir model/tablo dosyası YOK** — tüm ayarlar `SystemSetting` tablosunda anahtar-değer
olarak saklanır (`app/services/cic/config_context.py:15`, `from app.models import SystemSetting`).
Kutlama tarihleri (doğum günü, işe başlama) mevcut `User` tablosundaki alanlara yazılır (Excel
"Uygula" modu personel kartındaki tarih alanlarını günceller — ayrı bir "celebration" tablosu yok).

### 52.7 Kalıcı depolama

N/A (Excel şablon indirme/yükleme bellek-içi `BytesIO` ile yapılır, diske kalıcı yazılmaz).

### 52.8 Güvenlik kontrolleri

CSRF + login + çift-katmanlı admin rol kontrolü (menü + route, bkz. 52.3). Excel içe aktarma iki
modludur: önce **ön-kontrol** (`apply=False`, veri yazmaz, yalnız eşleşme raporu üretir), sonra
ayrı bir onayla **uygula** (`apply=True`) — kazara toplu veri bozulmasına karşı bir güvenlik adımı.

### 52.9 Operasyonel bağımlılık

**SMTP zorunlu.** İki AYRI Scheduled Task kuşağı bulundu, aynı 5 görevi (`staff_morning/noon/
evening`, `manager_morning/evening`) farklı isim ve mekanizmayla kuruyor:
1. `install_bys360_corporate_information_tasks_v3_0.ps1` → görev adları "BYS360 Corporate Info
   Staff Morning" vb., `scripts/communication/run_corporate_information_task.py --task <key>`.
2. `install_corporate_information_center_tasks_v3_0_phase2.ps1` → görev adları "BYS360 CIC Personel
   Sabah" vb. (FARKLI isimler, AYNI saatler: 08:00/12:30/17:30/07:45/17:45),
   `scripts/communication/run_corporate_information_center_task_v3_0_phase2.py --task-key <KEY>`.

Bu iki script **farklı TaskName kullandığı için** Windows'ta ikisi de aynı anda kurulu kalabilir —
yani aynı personel grubuna, aynı saatte, iki farklı Python script'inden **iki kez** kurumsal
bilgilendirme maili gidebilir (installer'lar birbirini override etmiyor, ismen ayrı görevler).
Ayrıca `install_bys360_cic_auto_mail_scheduler_task.ps1` — "BYS360 CIC Auto Mail Scheduler" adında,
**5 dakikada bir sonsuza kadar tekrar eden** (`RepetitionInterval 5min, RepetitionDuration 3650 gün`)
ÜÇÜNCÜ bir görev; `run_cic_auto_mail_scheduler.ps1`'i çalıştırır (bu script bu turda ayrıca
incelenmedi, ama kurulum açıklamasına göre "hafta içi kuralı nedeniyle hafta sonu otomatik mail
göndermeyen bir yoklama görevi").

### 52.10 Yedekleme/restore ilgisi

`system_settings` standart DB yedeğine dahildir. Kutlama tarihleri `users` tablosunun bir parçası
olduğu için İK/Personel modülünün yedek kapsamına zaten dahildir, ayrı bir yedek gerekmez.

### 52.11 Zamanlanmış/arka plan davranış

Bkz. 52.9 — üç bağımsız Scheduled Task mekanizması (2 farklı "5 görev" installer'ı + 1 "5 dakikada
bir" auto-scheduler).

### 52.12 Sorun giderme

1. Kurumsal bilgilendirme maili İKİ KEZ gidiyorsa — önce hangi installer'ların (52.9'daki 1 ve 2)
   kurulu olduğunu `Get-ScheduledTask | Where-Object {$_.TaskName -like "*Corporate Info*" -or
   $_.TaskName -like "*CIC*"}` ile listeleyin; muhtemelen ikisi birden kurulu.
2. Excel kutlama tarihi içe aktarma eşleşme bulamıyorsa — önce Sicil No, sonra e-posta, sonra ad-soyad
   sırasıyla eşleştirme denendiğini unutmayın (`_cic_v45_*` fonksiyonları); şablon dosyasındaki
   "Sicil No" sütununun boş bırakılmadığından emin olun.
3. Test Merkezi'nden gönderilen mail gelmiyor — `send_task(..., dry_run=True)` ile önce alıcı
   sayısını doğrulayın (gerçek mail göndermez), sonra SMTP ayarlarını (`SystemSetting` üzerinden,
   `MAIL_SERVER`/`SMTP_SERVER` vb. birden fazla anahtar adı denenir) kontrol edin.

### 52.13 Bilinen kısıt

**En önemli kısıt:** 52.9'da belgelenen görev-adı çoğullanması — CIC kendi içinde bile aynı 5 görevi
iki kez kurabilen iki ayrı installer script'ine sahip; bu Executive Mail Center v2 (§49) ile olan
kavramsal örtüşmeye ek, CIC'in KENDİ İÇİNDEKİ bir tekrar sorunudur. `facade.py`'nin README'de "artık
üretim bağımlılığı olmamalı" diye işaretlenmiş olması da, bu paketin geçmişte bir temizlik/refactor
sürecinden geçtiğini ama tam bitirilmediğini gösteriyor (facade hâlâ 232 satır ve ~100 isim taşıyor).

### 52.14 Kaynak dosyalar

| Katman | Dosya | Satır |
|---|---|---|
| Route | `app/communication/corporate_information_center_routes.py` | 276 |
| Servis (giriş noktası) | `app/services/cic/service.py` | 37 |
| Servis (uyumluluk cephesi) | `app/services/cic/facade.py` | 232 |
| Servis (SMTP) | `app/services/cic/mail_service.py` | 424 |
| Servis (diğer 9 modül) | `app/services/cic/{scheduler_service,query_service,template_service,celebration_service,celebration_dates,config_context,misc_context,cic_context,save_context,task_contract,access_policy}.py` | 3025 (toplam) |
| Şablonlar | `app/templates/corporate_information_center/{base,overview,tasks,recipients,templates,test,logs,system,celebrations}.html` | 9 dosya |
| Menü | `app/templates/base.html:715-739` | — |
| Scheduled Task installer (çoğullanmış) | `scripts/windows/install_bys360_corporate_information_tasks_v3_0.ps1`, `install_corporate_information_center_tasks_v3_0_phase2.ps1`, `install_bys360_cic_auto_mail_scheduler_task.ps1` | — |
| Belge | `app/services/cic/README.md` | — |

---

## 53. Arşiv (Performance Archive) — Geçmiş Karne Arşivi

**Düzeltme:** Görev tanımındaki `archive_visibility_policy.py`, `scorecard_archive_import.py`,
`scorecard_archive_service.py` dosyaları okundu ve üçü de **12 satırlık boş köprü (bridge) dosyalarıdır**
(`try: pass / except: log`) — hiçbir gerçek kod içermezler. Gerçek iş mantığının TAMAMI
`app/services/performance/archive_service.py` (688 satır) içindedir. Aşağıdaki belge bu gerçek dosyaya dayanır.

### 53.1 Amaç
Geçmiş yıllara (2024/2025 gibi) ait eski performans puan cetvellerini/karnelerini, canlı değerlendirme sürecinden
ayrı bir arşiv tablosuna (manuel giriş veya Excel import ile) almak; personelin ve yöneticilerin bu geçmişi
kendi yetki kapsamlarına göre görebilmesini sağlamak.

### 53.2 Kullanıcı girişi / navigasyon
Menü: Performans Yönetimi → "Geçmiş Karne Arşivi" (menü anahtarı `performance_archive`).
URL'ler (hepsi TR/EN alias çifti olarak kayıtlı, `app/performance/performance_archive_routes.py`):
- `GET /performance/archive` ≡ `/performans/gecmis-karne-arsivi` — liste/özet ekranı
- `GET /performance/archive/<int:result_id>` ≡ `/performans/gecmis-karne-arsivi/<id>` — detay
- `GET+POST /performance/archive/new` ≡ `/performans/gecmis-karne-arsivi/yeni` — manuel kayıt ekleme
- `GET+POST /performance/archive/import` ≡ `/performans/gecmis-karne-arsivi/excel` — Excel toplu import
- `GET /performance/archive/import/template` ≡ `/performans/gecmis-karne-arsivi/excel-sablon` — boş Excel şablonu indirme
- `GET /performance/archive/template` — Faz 7.6'da eklenen alias (`performance_archive_import_template`'i çağırır)

### 53.3 Roller/erişim
**Sapma tespit edildi:** Parent özelliğin (#2 Performans Yönetimi) genel `admin_required`/`manager_required`/
`menu_key_required` üçlüsü Arşiv route'larında KULLANILMAZ. Route'larda tek decorator `@login_required`'dır;
gerçek yetkilendirme fonksiyon-içi rol-seti kontrolleriyle yapılır (`archive_service.py`):
- `can_manage_archive(user)` — `is_admin`/`is_superuser` VEYA rol `MANUAL_ENTRY_ROLES` içinde
  (`admin, super_admin, system_admin, sistem_yoneticisi, baskan, baskan_yardimcisi, performans_yetkilisi,
  personel_yonetimi, ik, insan_kaynaklari` — TR karakter varyantlarıyla birlikte) → manuel kayıt ekleme + Excel import yetkisi.
- Görünürlük kapsamı `allowed_archive_employee_ids(user)` ile hesaplanır:
  - `can_manage_archive` ise → TÜM personel (genel arşiv yönetimi).
  - `PERSONNEL_ONLY_ROLES` (personel/standart/user/employee/calisan) ise → yalnız kendi `employee_id`'si.
  - `MANAGER_ARCHIVE_ROLES` (grup_baskani, mali_musavir, koordinator, birim_sorumlusu, yonetici, amir vb.) ise →
    `manager_archive_allowed_employee_ids()` ile hesaplanan yetki kapsamı.
  - Bilinmeyen/tanımsız rol → **güvenli varsayılan: yalnız kendi kaydı** (satır 309-310, kasıtlı fail-closed).
  - Boş kapsam asla "herkes" anlamına gelmez — `apply_archive_visibility_filter()` boş sette
    `employee_id == -1` filtresi uygular (satır 315-316), yani sıfır sonuç döner.
- Detay sayfası (`performance_archive_detail`) `can_view_archived_result()` ile ayrıca kontrol edilir — doğrudan
  URL ile kapsam dışı bir kayda erişim `render_access_denied()` ile engellenir.
- Menü görünürlüğü ayrıca `menu_registry.py`/`effective_menu_parts` katmanında `performance_archive` anahtarıyla
  rol bazlı filtrelenir (route-level decorator değil, ama nav görünürlüğü ayrı bir katmanda gerçekten var).

### 53.4 Routes/API
Yukarıdaki §53.2 tablosu ile aynı — 6 GET/POST endpoint, tamamı `main_bp` üzerinde, `app/performance/performance_archive_routes.py` (209 satır) içinde tanımlı.

### 53.5 Core service/model
- Route: `app/performance/performance_archive_routes.py` (209 satır)
- Servis (gerçek mantık): `app/services/performance/archive_service.py` (688 satır) — rol/görünürlük kontrolü,
  Excel header-alias eşleme (`HEADER_ALIASES`, TR karakter normalizasyonu), Excel şablon üretimi
  (`build_archive_excel_template_bytes`), manuel kayıt oluşturma (`create_manual_archive_result`), Excel import
  (`import_archive_results_from_excel`), arama/filtre (`apply_archive_search_filters`).
- Köprü (boş) dosyalar: `archive_visibility_policy.py`, `scorecard_archive_import.py`, `scorecard_archive_service.py` (her biri 12 satır, no-op).
- Model: `app/models/performance_archive_models.py` (110 satır), tek sınıf `PerformanceArchivedResult`.

### 53.6 DB bağımlılığı
Tablo: `performance_archived_results` (tek model/tek tablo). Alanlar: `employee_id` (FK `users.id`, CASCADE),
`result_year`, `period_label`, `score` (Numeric(5,2), `CHECK score BETWEEN 0 AND 100`), `description`,
`source_document`/`source_document_name`, `source_type` (default `"manual"`), `created_by_user_id` (FK, SET NULL).
3 composite index (`employee_id+result_year`, `result_year+period_label`, `created_by_user_id+created_at`).
Bu, Performans modülünün CANLI değerlendirme tablolarından (`performance_evaluations` vb.) tamamen AYRI bir
tablodur — Excel import canlı değerlendirme sonuçlarını değiştirmez (servis dosyasının kendi docstring garantisi).

### 53.7 Kalıcı depolama
Excel import dosyası kalıcı olarak diske YAZILMAZ — `openpyxl` ile bellekte (`upload` stream) okunur, satırlar
parse edilip DB'ye yazılır, dosyanın kendisi saklanmaz. Excel şablon indirme (`build_archive_excel_template_bytes`)
`BytesIO` ile bellekte üretilir, diske yazılmaz. **Kalıcı dosya depolama YOK.**

### 53.8 Security controls
- `@login_required` (route seviyesi) + fonksiyon-içi rol kontrolü (yukarı bakınız).
- Detay sayfası kapsam-dışı erişimde `render_access_denied()`.
- Excel import: yalnız `can_manage_archive` yetkisi olanlar; puan `CHECK` kısıtı DB seviyesinde (0-100 aralığı,
  `parse_score()` fonksiyonu da uygulama seviyesinde `Decimal` ile doğrular).
- CSRF: global `CSRFProtect()` (Flask-WTF), formlar üzerinden.
- Fail-closed görünürlük: bilinmeyen rol veya boş kapsam → sıfır kayıt (yukarı bakınız).

### 53.9 Operasyonel bağımlılık
Yok — SMTP/Celery/Scheduled Task bağımlılığı YOK. `scripts/windows/*.ps1` içinde "arsiv"/"archive"
anahtar kelimesiyle bu özelliğe özel bir installer script BULUNAMADI (bu turda ayrıca doğrulandı).
Tamamen senkron, kullanıcı-tetiklemeli (request-response) bir özelliktir.

### 53.10 Backup/restore ilişkisi
Standart PostgreSQL `pg_dump`/`pg_restore` prosedürü ile tam kapsanır — dosya sistemi bağımlılığı yok, tüm veri
`performance_archived_results` tablosunda. Özel bir yedekleme adımı gerekmez.

### 53.11 Zamanlanmış/arkaplan davranış
N/A — bu özellik tamamen istek-yanıt (senkron) çalışır, hiçbir zamanlanmış görev/arkaplan işi yoktur.

### 53.12 Troubleshooting
- **Excel import "atlandı" satırları çok:** `HEADER_ALIASES` eşlemesi başlık adlarını tanımıyor olabilir —
  `TEMPLATE_HEADERS` ile karşılaştırın, gerekirse resmi şablonu (`/performance/archive/import/template`) kullanın.
- **Kullanıcı arşivi görmüyor ama görmesi gerekiyor:** rolü `MANAGER_ARCHIVE_ROLES`/`GENERAL_VIEW_ROLES` setlerinde
  mi kontrol edin — bilinmeyen/yanlış yazılmış rol adı fail-closed davranışla kullanıcıyı yalnız kendi kaydına düşürür.
  TR karakter varyantı eksikse (örn. sadece `"başkan"` var, `"baskan"` yoksa) normalize edilmiş rol eşleşmeyebilir
  — ancak kod her iki varyantı da (Türkçe karakterli/karaktersiz) sabit listelerde tutuyor, bu nedenle asıl neden
  genelde rol alanının bu iki setin DIŞINDA bir değer içermesidir.
- **Manuel puan ekleme "Kayıt eklenemedi" hatası:** `parse_score`/`parse_year` `ValueError` fırlatır (0-100 dışı
  puan, 2000-2100 dışı yıl) — flash mesajı gerçek istisna adını (`exc`) doğrudan gösterir.

### 53.13 Bilinen kısıtlama
Görünürlük ve yetki tamamen **rol adı string eşleşmesine** dayanır (`normalize_role()` ile küçük harfe çevrilip
boşluklar `_`'a çevrilir) — merkezi bir rol-matrisi/permission tablosu değil, `archive_service.py` içinde
hardcoded Python set'leridir. Yeni bir rol eklenip bu üç set (`MANUAL_ENTRY_ROLES`/`GENERAL_VIEW_ROLES`/
`MANAGER_ARCHIVE_ROLES`/`PERSONNEL_ONLY_ROLES`) güncellenmezse, o rol otomatik olarak en dar kapsama
(yalnız kendi kaydı) düşer — bu güvenli bir varsayılan olsa da, yöneticiler için sessiz bir erişim kaybına yol açabilir.

### 53.14 Kaynak dosyalar
| Katman | Dosya | Satır |
|---|---|---|
| Route | `app/performance/performance_archive_routes.py` | 209 |
| Servis (gerçek) | `app/services/performance/archive_service.py` | 688 |
| Servis (boş köprü) | `app/services/performance/archive_visibility_policy.py`, `scorecard_archive_import.py`, `scorecard_archive_service.py` | 12+12+12 |
| Model | `app/models/performance_archive_models.py` | 110 |
| Şablonlar | `app/templates/performance/archive/{index,detail,form,import,_premium_styles}.html` | 5 dosya |

---

## 54. Başkan Onayları (President Approvals)

### 54.1 Amaç
70 altı (düşük) nihai performans sonuçlarının, üst yönetici (amir) zincirinden sonra son adım olarak
Başkan/yetkili sistem yöneticisi tarafından onaylanması veya iade edilmesi süreci. Bu, çok-adımlı bir
amir-onay zincirinin (process engine) son halkasıdır.

### 54.2 Kullanıcı girişi / navigasyon
Menü anahtarı `performance_president_approvals` ("Başkan Onayları"). URL'ler
(`app/performance/process_engine_phase6_president_approvals_routes.py`):
- `GET+POST /performans/baskan-onaylari` ≡ `GET /performance/president-approvals` — onay bekleyen/karar
  verilmiş kayıt listesi (`status` query parametresiyle filtrelenir, varsayılan `pending`)
- `GET /performans/baskan-onaylari/<id>/karne` ≡ `/performance/president-approvals/<id>/scorecard` ≡
  `/performance/president-approvals/<id>/card` — tek kayıt karne/detay incelemesi
- `POST /performance/president-approvals/<id>/approve` ≡ `/performans/baskan-onaylari/<id>/onayla` — onayla
- `POST /performance/president-approvals/<id>/return` ≡ `/performans/baskan-onaylari/<id>/iade` — iade et
- `POST /performance/president-approvals/<id>/delete` ≡ `/performans/baskan-onaylari/<id>/sil` — kayıt temizliği (sıfırlama sonrası yetim kayıt)

### 54.3 Roller/erişim
Yine parent'ın genel decorator üçlüsü KULLANILMAZ; `@login_required` + fonksiyon-içi kontrol:
- **Görüntüleme/onay/iade:** `can_view_president_approvals(user) = is_admin_user(user) or is_president_user(user)`
  (`process_engine_phase6_president_approvals.py:204`) — Başkan/Başkan Yardımcısı ve admin ailesi.
- **Kayıt silme (temizlik):** AYRICA DAR bir yetki — `can_delete_president_approval_records(user) = is_admin_user(user)`
  (satır 208-215) — kod içi yorum açıkça şunu belirtir: *"Başkan onayı vermek ile kayıt silmek farklı yetkidir...
  eski/sıfırlama sonrası kalan kayıt temizliği sistem yöneticisi/admin tarafından yapılır."* Yani Başkan rolü
  onaylayabilir ama SİLEMEZ; yalnız admin silebilir.
- Yetkisiz erişimde özel bir 403 şablonu döner (`_render_president_approvals_access_denied()`,
  `errors/403.html`, mesaj: *"Bu sayfa yalnızca Başkan ve yetkili sistem yöneticileri tarafından görüntülenebilir."*)

### 54.4 Routes/API
Yukarı §54.2 — 5 endpoint (1 GET/POST çoklu-alias, 1 GET detay, 3 POST aksiyon), hepsi `main_bp`.

### 54.5 Core service/model
- Route: `app/performance/process_engine_phase6_president_approvals_routes.py` (98 satır)
- Servis: `app/services/performance/process_engine_phase6_president_approvals.py` (1019 satır) — `Phase6ActionResult`
  dataclass, `can_view_president_approvals`, `delete_president_approval_record`, `build_president_approval_workspace`,
  `decide_president_approval`.
- Detay/karne servis: `app/services/performance/president_card_review_service.py` (659 satır) —
  `build_president_card_review_context()`.
- İlişkili: `process_engine_phase7_president_rule.py` (706 satır, kural motoru — bu turda yalnız varlığı
  doğrulandı, iş kuralları tek tek okunmadı), `president_menu_card_access.py` (222 satır, menü/kart erişim yardımcıları).
- **Mimari not:** servis katmanı ORM modeli yerine ÇOĞUNLUKLA `sqlalchemy.text()` ile HAM SQL kullanır
  (`db.session.execute(text("SELECT ... FROM performance_president_approvals ..."))`), `information_schema`
  sorgularıyla tablo/kolon varlığını kontrol eder (`table_exists()`, `column_exists()`). Bu, üstteki `db.Model`
  tanımının VAR olmasına rağmen (bkz. §54.6), servis kodunun ORM'i bypass ederek doğrudan SQL yazdığı anlamına gelir
  — muhtemelen şema evrimi (kolon eklemeleri) sırasında geriye dönük uyumluluğu korumak için savunmacı bir tercih.

### 54.6 DB bağımlılığı
Tablo: `performance_president_approvals`, model `PerformancePresidentApproval`
(`app/models/performance_process_engine_models.py:87-109`, docstring: *"70 altı nihai sonuçlar için Başkan onayı
kaydı"*). İlişkili: `performance_process_flows`/`performance_process_flow_steps` (aynı dosyada, süreç akışı
adımları — onay verildiğinde `current_status`/`current_stage` güncellenir). Migration kanıtı VAR:
`migrations/versions/6f2b8c4d1a90_adopt_workflow_president_approval_schema.py` ve
`9a5e1f4c2d60_performance_completion_phase6_low_score_approval.py` (File Center'daki §34.7 "adoption" desenine
benzer şekilde şema kabul/migrate mantığı).

### 54.7 Kalıcı depolama
N/A — yalnız DB, dosya sistemi bağımlılığı yok.

### 54.8 Security controls
- `@login_required` + rol-fonksiyonu kontrolü (yukarı §54.3).
- Silme işlemi AYRI ve DAHA DAR bir yetkiye tabi (yalnız admin) — onaylama yetkisinden kasıtlı olarak ayrılmış.
- CSRF: global CSRFProtect, POST formları üzerinden.
- Ham SQL kullanımı `text()` + parametre bağlama (`:approval_id` vb.) ile yapılır — SQL injection riski
  görülmedi (parametreler her yerde bind edilmiş, string interpolation yalnız tablo/kolon ADLARI için,
  kullanıcı girdisi için DEĞİL).

### 54.9 Operasyonel bağımlılık
Yok — SMTP/Celery/Scheduled Task bağımlılığı bulunamadı; `scripts/windows/*.ps1` içinde "baskan"/"president"
anahtar kelimesiyle bu özelliğe özel installer script YOK (bu turda doğrulandı).

### 54.10 Backup/restore ilişkisi
Standart DB backup ile kapsanır (yalnız ilişkisel tablo verisi, dosya yok).

### 54.11 Zamanlanmış/arkaplan davranış
N/A — tamamen kullanıcı-tetiklemeli senkron işlemler.

### 54.12 Troubleshooting
- **"Başkan onayı kaydı bulunamadı" hatası approve/return sırasında:** kayıt muhtemelen daha önce silinmiş
  (temizlik akışı, §54.2 delete endpoint) veya `approval_id` yanlış — `performance_president_approvals` tablosunda
  doğrudan `SELECT ... WHERE id=` ile doğrulanabilir.
  - Bu hata AYRICA yönetici tarafında yaygın bir yanlış anlamaya işaret edebilir: personel özlük sıfırlaması
  sonrası ekranda "yetim" (orphan) kayıt kalabilir — kod içi yorum bunu açıkça öngörür (§54.2 delete route docstring).
- **Silme butonu görünmüyor/403:** kullanıcı Başkan rolünde olabilir ama admin DEĞİL — silme yalnız admin'e açık
  (§54.3), bu KASITLI bir kısıtlamadır, hata değildir.
- **Ham SQL sorgusu `information_schema` kontrolü başarısız:** `table_exists()`/`column_exists()` PostgreSQL'e
  özgü `information_schema.tables/columns` sorgusu kullanır — SQLite gibi farklı bir motorda bu kontroller
  hatalı davranabilir (yalnız PostgreSQL için doğrulandı).

### 54.13 Bilinen kısıtlama
Servis katmanının büyük kısmı ORM modelini (`PerformancePresidentApproval`) BYPASS EDİP ham `text()` SQL
kullanıyor olması, ileride model şeması değiştiğinde (örn. Alembic ile bir kolon yeniden adlandırılırsa) servis
kodundaki SQL string'lerinin senkron kalmasını GEREKTİRİR — ORM'in sağladığı otomatik şema-kod tutarlılığı burada
yoktur, bu kasıtlı ama kırılgan bir tasarım tercihidir.

### 54.14 Kaynak dosyalar
| Katman | Dosya | Satır |
|---|---|---|
| Route | `app/performance/process_engine_phase6_president_approvals_routes.py` | 98 |
| Servis (onay motoru) | `app/services/performance/process_engine_phase6_president_approvals.py` | 1019 |
| Servis (karne/kart) | `app/services/performance/president_card_review_service.py` | 659 |
| Servis (kural) | `app/services/performance/process_engine_phase7_president_rule.py` | 706 |
| Servis (menü/kart erişim) | `app/services/performance/president_menu_card_access.py` | 222 |
| Model | `app/models/performance_process_engine_models.py` (`PerformancePresidentApproval`, satır 87-109) | — |
| Migration | `migrations/versions/6f2b8c4d1a90_...py`, `9a5e1f4c2d60_...py` | — |
| Şablonlar | `app/templates/performance/{process_engine_president_approvals,president_card_review,president_approvals_v2,president_approval_scorecard,president_approval_scorecard_v2}.html` | 5 dosya |

---

## 55. Notlar (Interim Notes / Dönem İçi Notlar)

**⚠️ Bu bölüm bu turda tespit edilen ÖNEMLİ bir mimari tutarsızlığı belgeler — bkz. §55.13.**

### 55.1 Amaç
Değerlendirme dönemi İÇİNDE (ara dönemde) bir yöneticinin bir personel hakkında gözlem/olay notu düşmesi
(olumlu olay, olumsuz olay, başarı, gelişim ihtiyacı, genel gözlem). Bu notlar **otomatik puan üretmez** —
yalnız değerlendirme sırasında hatırlatma/süreç hafızası sağlar; yalnız "Karne detayında gösterilsin" işaretli
olanlar karne/PDF'de görünür.

### 55.2 Kullanıcı girişi / navigasyon
Menü: Performans Yönetimi → "Dönem İçi Notlar" (menü anahtarı `performance_interim_notes`).
URL: `GET+POST /performance/interim-notes` ≡ `/performans/donem-ici-notlar`
(`app/performance/interim_notes_manager_routes.py`, endpoint `main.performance_interim_notes`).
Ayrıca kayıtlı ama **UI'da hiçbir yerden çağrılmayan** bir POST-only endpoint çifti var: bkz §55.13.

### 55.3 Roller/erişim
Parent'ın decorator üçlüsü yine KULLANILMAZ; `@login_required` + fonksiyon-içi `_can_access()`:
`_is_admin_like()` (is_admin/is_superuser veya rol `ADMIN_ROLES` içinde) VEYA rol `ALLOWED_ROLES` içinde
(`admin, super_admin, ..., baskan, baskan_yardimcisi, grup_baskani, mali_musavir, koordinator, birim_sorumlusu`).

**⚠️ Belgelenen geçmiş güvenlik açığı (kod içi yorum, `BYS360_P13B_NEW13B01_FIX`, satır 257-266 ve 376-401):**
Bu route eskiden `@login_required` DIŞINDA HİÇBİR yetki/kapsam kontrolü yapmıyordu — *"birimi ilgilendirmeyen bir
personel, tüm çalışanların gizli olumsuz performans notlarını okuyup başka bir çalışan adına sahte not
ekleyebiliyordu"* (Phase 13B, confirmed). Düzeltme: `_can_access()`/`_people()`/`_allowed_employee()` kapsam
yardımcıları artık zorunlu kılınıyor; personel listesi ve not sorgusu artık yönetici-hiyerarşisi kapsamıyla
(`scoped_ids`) sınırlanıyor, admin-benzeri roller hariç. Bu, bu turda yalnız kod okunarak doğrulanmış GERÇEK bir
geçmiş bulgu/düzeltmedir — uydurulmamıştır.

### 55.4 Routes/API
- `GET+POST /performance/interim-notes` ≡ `/performans/donem-ici-notlar` — liste + form-içi ekleme (aynı sayfa)
- `POST /performance/interim-notes/create` ≡ `/performans/donem-ici-notlar/kaydet` — **kayıtlı ama UI'dan
  hiçbir yerden çağrılmıyor** (bkz §55.13)

### 55.5 Core service/model
- Route (asıl çalışan akış): `app/performance/interim_notes_manager_routes.py` (501 satır)
- Değerlendirme/karne entegrasyonu: `app/services/performance/interim_notes_runtime.py` (365 satır) —
  `build_interim_notes_context()` (Faz 3 değerlendirme ekranı), `build_scorecard_interim_notes()` (karne/PDF)
- Köprü (boş) dosya: `app/services/performance/interim_feedback_policy.py` (12 satır, no-op).
- İlişkili ama AYRI amaçlı: `midterm_feedback_service.py`, `phase8_midterm_feedback_center.py`,
  `meeting_p2_archive_notes.py` (bu turda derinlemesine okunmadı, isimlerinden "ara dönem geri bildirim toplantısı"
  ile ilgili göründüler — Dönem İçi Notlar'dan kavramsal olarak farklı bir alt akış).

### 55.6 DB bağımlılığı
**⚠️ İKİ AYRI, PARALEL TABLO VAR — bkz §55.13 için tam açıklama:**
- `performance_interim_notes` — "gerçek"/zengin şema (employee_id, employee_user_id, manager_id, created_by,
  created_by_id, note_type, title, note_title, note, note_body, note_text, content, description,
  visibility_level, visibility_scope, remind_in_evaluation, remind_during_scoring, include_in_scorecard,
  visible_on_scorecard, is_active, active, occurred_at, created_at, updated_at — çoğu alan İKİ-ÜÇ eşanlamlı
  kolonla, `interim_notes_runtime.py`'nin `ensure_interim_notes_table()` fonksiyonu tarafından idempotent
  yaratılır/genişletilir).
- `performance_interim_notes_live` — daha basit şema (personnel_id, period_id, note_type, title, note,
  scorecard_visible, created_by_user_id, created_at), `interim_notes_manager_routes.py`'nin `_ensure_table()`
  fonksiyonu tarafından yaratılır.

**Her iki tablo da hiçbir Alembic migration'da tanımlı DEĞİLDİR** — ikisi de yalnız runtime
`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN` (idempotent, uygulama ilk erişimde) ile var olur.

### 55.7 Kalıcı depolama
N/A — yalnız DB (yukarıdaki iki tablo), dosya sistemi bağımlılığı yok.

### 55.8 Security controls
`@login_required` + `_can_access()` rol kontrolü + `_allowed_employee()` kapsam kontrolü (§55.3'teki
geçmiş-açık-düzeltmesiyle birlikte). CSRF: global CSRFProtect. Girdi: `request.form` değerleri `.strip()` ve
uzunluk sınırlarıyla (`title[:255]`) temizlenir; ham SQL `text()` ile parametre-bind edilir (injection riski
görülmedi).

### 55.9 Operasyonel bağımlılık
Yok — SMTP/Celery/Scheduled Task bağımlılığı yok; senkron request-response.

### 55.10 Backup/restore ilişkisi
Standart DB backup kapsar (yalnız DB, dosya yok) — **ancak** her iki tablo da Alembic migration dışı olduğu
için (§55.6), sıfırdan bir ortamda yalnız `flask db upgrade` çalıştırmak bu tabloları OLUŞTURMAZ; tablolar
yalnız uygulama ilk kez ilgili route'a/fonksiyona erişildiğinde (`ensure_interim_notes_table()`/`_ensure_table()`
çağrıldığında) kendiliğinden oluşur. Bu, File Center'ın (§34.7, ana handover) daha önce çözülmüş
"Alembic'e dahil değildi" sorununun ÇÖZÜLMEMİŞ bir benzeridir.

### 55.11 Zamanlanmış/arkaplan davranış
N/A.

### 55.12 Troubleshooting
- **Yönetim sayfasında eklenen not, değerlendirme/karne ekranında GÖRÜNMÜYOR:** bu BEKLENEN bir davranıştır,
  hata değildir — bkz §55.13, iki tablo birbirinden bağımsızdır.
- **"Bu personel için not ekleme yetkiniz yok" uyarısı:** `_allowed_employee()` kapsam dışı — kullanıcının rolü
  `ALLOWED_ROLES` içinde olsa bile, hedef personel o yöneticinin hiyerarşi kapsamında olmayabilir.
- **Tablo yok hatası (ilk kurulum sonrası):** `ensure_interim_notes_table()`/`_ensure_table()` bir DB hatasıyla
  sessizce başarısız olmuş olabilir (`db.session.rollback()` + `warnings.append(...)`) — uygulama loglarında
  `"... kolonu eklenemedi"`/`"... tablosu hazırlanamadı"` mesajları aranmalı.

### 55.13 Bilinen kısıtlama — **KRİTİK, bu turda tespit edilen mimari kopukluk**
"Dönem İçi Notlar" yönetim sayfası (`/performance/interim-notes`) ve bu notların değerlendirme/karne
ekranlarında GÖSTERİLMESİ **iki farklı tabloya bağlı, birbirinden kopuk iki alt sistemdir**:

1. **Web yönetim sayfası** (`interim_notes_manager_routes.py`, kullanıcının tıkladığı GERÇEK form) yalnız
   `performance_interim_notes_live` tablosuna yazar VE yalnız o tablodan okur (form `action="{{ request.path }}"`
   ile kendi GET/POST endpoint'ine post eder — `interim_notes_manager.html:472`).
2. **Değerlendirme/karne gösterimi** (`interim_notes_runtime.py`, `build_interim_notes_context()`/
   `build_scorecard_interim_notes()`) yalnız `performance_interim_notes` (canonical, zengin şemalı) tablosundan
   OKUR — docstring'i açıkça *"Aynı /performance/interim-notes sayfasının kullandığı tablodan okur"* der, ama
   bu YANLIŞTIR/GÜNCEL DEĞİLDİR: o sayfa artık `_live` tablosunu kullanıyor.
3. `performance_interim_notes` tablosuna GERÇEKTEN yazan tek route (`performance_interim_notes_create`,
   `/performance/interim-notes/create`) **hiçbir template'ten `url_for`/form action ile çağrılmıyor** — menü
   sisteminde yalnız "aktif endpoint" listesinde geçiyor (`menu_registry_data_sections.py:290`, sekme
   vurgulaması için), gerçek bir form/buton YOK.
4. `performance_interim_notes` tablosuna GERÇEKTEN yazan tek canlı yol **Mobil API'dir**
  (`app/api/mobile/services/performance_note_route_services.py:112`, `INSERT INTO performance_interim_notes`).

**Sonuç:** Web arayüzünden ("Dönem İçi Notlar" sayfası) eklenen bir not, kaydedildiği andan itibaren yalnız O
SAYFADA görünür — değerlendirme ekranında veya karnede GÖRÜNMEZ (çünkü değerlendirme/karne farklı bir tablo
okur). Mobil uygulamadan eklenen bir not ise değerlendirme/karnede görünür ama web yönetim sayfasında GÖRÜNMEZ
(çünkü web sayfası farklı bir tablo okur). Bu, iki ayrı geliştirme dalgasının aynı özelliği farklı tablolarla
yeniden inşa etmesinden kaynaklanan GERÇEK, kod-doğrulanmış bir fonksiyonel kopukluktur — tahmin veya varsayım
DEĞİLDİR (`feedback_integration.py:297` de her iki tabloyu ayrı ayrı listeleyerek bu ikiliği zaten kabul eder).

### 55.14 Kaynak dosyalar
| Katman | Dosya | Satır |
|---|---|---|
| Route (web, `_live` tablosu) | `app/performance/interim_notes_manager_routes.py` | 501 |
| Servis (değerlendirme/karne gösterimi, `performance_interim_notes` tablosu) | `app/services/performance/interim_notes_runtime.py` | 365 |
| Servis (boş köprü) | `app/services/performance/interim_feedback_policy.py` | 12 |
| Mobil yazma yolu | `app/api/mobile/services/performance_note_route_services.py` (satır ~112) | — |
| Şablon | `app/templates/performance/interim_notes_manager.html` | — |

---

## 56. Hatırlatmalar (Reminders — Faz 9/10)

### 56.1 Amaç
Bekleyen değerlendirme görevleri için son-tarih-öncesi hatırlatma ve son tarihi geçmiş ("aksatan") amirlerin
tespiti/özetlenmesi için altyapı. Servisin kendi docstring'i açıkça belirtir: *"Faz 9 bilinçli olarak e-posta
göndermez; gönderim için denetlenebilir kuyruk, ayar, mail log bağlantısı ve aksatan amir özetini kurar."*

### 56.2 Kullanıcı girişi / navigasyon
Menü anahtarı `performance_meeting_p3_reminders` ("Hatırlatma ve Aksatan Amirler").
URL: `GET /performance/meeting-development/faz9` ≡ `/performans/toplanti-gelistirme/faz9-hatirlatma`
(endpoint `performance_meeting_p3_reminders`); "Uygula" butonu →
`POST /performance/meeting-development/faz9/apply` ≡ `.../faz9-hatirlatma/uygula`.

### 56.3 Roller/erişim
**Bu, incelenen dört Performans alt-modülü arasında PARENT'IN gerçek decorator zincirini birebir kullanan TEK
olandır:** `@login_required @manager_required` (`app/performance/meeting_p3_reminders_routes.py:16-17,27-28`).
Diğer üç alt-modülün (Arşiv, Başkan Onayları, Notlar) aksine burada fonksiyon-içi özel bir rol-seti kontrolü YOK
— doğrudan merkezi `manager_required` decoratorüne güvenilir.

### 56.4 Routes/API
- `GET /performance/meeting-development/faz9` — durum panosu (checklist + kuyruk + aksatan amir özeti)
- `POST /performance/meeting-development/faz9/apply` — altyapıyı "hazırla" (ayar tohumlama + tablo oluşturma +
  1 adet DEMO kayıt, bkz §56.13)

### 56.5 Core service/model
- Route: `app/performance/meeting_p3_reminders_routes.py` (34 satır)
- Servis (Faz 9, ana): `app/services/performance/meeting_p3_reminders.py` (248 satır)
- Servis (Faz 10, bildirim merkezi — saf karar/biçimlendirme fonksiyonları, DB yan etkisi yok):
  `app/services/performance/phase10_reminder_notification_center.py` (536 satır)
- Köprü (yalnız re-export, kod içermez): `app/services/performance/reminder_notification_service.py` (22 satır,
  Faz 10'daki isimleri `__all__` ile yeniden dışa verir).
- AI Karar Destek entegrasyonu (kural/politika, DB'siz saf fonksiyonlar): `app/services/ai_decision/reminder_policy.py`
  (236 satır, `ReminderPolicy` dataclass, `is_overdue`/`is_due_soon`/`classify_assignment_status`),
  `app/services/ai_decision/reminder_integration.py` (172 satır, `build_reminder_summary_payload` vb.) —
  bu iki dosya AI panellerine veri hazırlar, `AI_PROVIDER_MODE=stub` deseniyle tutarlı (kural-tabanlı, gerçek LLM değil).
- İlişkili ama bu turda derinlemesine okunmayan: `v2_1_11_evaluator_reminder_center.py` (428 satır),
  `v2_1_17_reminder_approval_prep.py` (344 satır).

### 56.6 DB bağımlılığı
İki tablo, **hiçbiri Alembic migration'da yok** (yalnız runtime `inspect(db.engine).has_table()`/`CREATE TABLE`
ile idempotent oluşturulur, `meeting_p3_reminders.py` içindeki `ensure_reminder_queue_table()`/
`ensure_overdue_snapshot_table()`):
- `performance_reminder_queue` — id, assignment_id, period_id, manager_user_id, employee_user_id, reminder_type,
  channel, due_at, status, title, message, created_by, created_at, sent_at, mail_log_id, notification_id.
- `performance_overdue_manager_snapshots` — id, period_id, manager_user_id, overdue_count, oldest_due_at,
  scope_label, created_by, created_at.
- Ayrıca `module_settings` tablosunda 10 ayar anahtarı (`P3_REQUIRED_SETTINGS`) tohumlanır — en önemlisi
  `performance_email_reminders_enabled` (**varsayılan `"false"`**, kod içi açıklama: *"E-posta gönderimini
  ayara bağlar; varsayılan kapalıdır, canlıda bilinçli açılır"*).

### 56.7 Kalıcı depolama
N/A — yalnız DB.

### 56.8 Security controls
`@login_required @manager_required` (merkezi decorator). Hatırlatma metinlerinde puan/amir görüşü gibi hassas
içerik gösterilmeyeceği ayrıca bir ayar/kontrol maddesi olarak tanımlıdır
(`performance_reminder_no_sensitive_content`, satır 33). CSRF: global CSRFProtect (POST formu).

### 56.9 Operasyonel bağımlılık
**Gerçek e-posta gönderimi YOKTUR** — `performance_email_reminders_enabled` varsayılan kapalı; Faz 9 kasıtlı
olarak yalnız kuyruk/log ALTYAPISINI hazırlar. `scripts/windows/*.ps1` içinde "hatirlatma"/"reminder" anahtar
kelimesiyle bu özelliğe özel bir installer script BULUNAMADI (bu turda doğrulandı) — yani bu kuyruğu düzenli
işleyecek bir Windows Scheduled Task da YOK. (Ana handover §18'de "BYS360 Performance Mail Reminder 09" adlı bir
görev DISABLED olarak listelidir ve repoda bu isimle installer kanıtı YOKTUR — muhtemelen operatör beyanına göre
bu tam olarak bu özelliğe atıfta bulunuyor olabilir, ancak bu turda doğrudan bir kod bağlantısı KURULAMADI.)

### 56.10 Backup/restore ilişkisi
Standart DB backup kapsar — ancak §56.6'daki gibi iki tablo da Alembic dışıdır, aynı riski taşır (§55.10 ile
aynı desen: sıfırdan ortamda `flask db upgrade` bu tabloları oluşturmaz, yalnız "Uygula" butonuna ilk basıldığında oluşurlar).

### 56.11 Zamanlanmış/arkaplan davranış
**YOK — bu kritik bir bulgudur.** "Uygula" butonu (`run_p3_reminders()`) gerçek bir "geciken amirleri tara ve
hatırlatma üret" işlemi YAPMAZ; yalnızca (1) ayarları tohumlar, (2) iki tabloyu hazırlar, (3)
`seed_demo_reminder()` ile TEK BİR statik "draft" kaydı ekler (mesaj metni: *"Bu kayıt, hatırlatma kuyruğunun
hazır olduğunu gösterir. Puan, amir görüşü veya hassas personel içeriği içermez."*). Gerçek, dönemsel bir
son-tarih taraması yapan hiçbir zamanlanmış görev/servis bu turda BULUNAMADI.

### 56.12 Troubleshooting
- **"Hatırlatma" ekranında hep aynı tek kayıt görünüyor, yeni hatırlatma üretilmiyor:** BEKLENEN davranış —
  §56.11'e bakın, bu ekran bir "altyapı hazır mı" self-check panosudur, gerçek bir otomatik hatırlatma motoru
  DEĞİLDİR.
- **E-posta hatırlatması gelmiyor:** `performance_email_reminders_enabled` ayarı kontrol edilmeli — varsayılan
  kapalı, kasıtlı olarak canlıda ayrıca açılması gerekir; açık olsa bile gerçek gönderim kodu bu turda
  DOĞRULANAMADI (yalnız altyapı/kayıt hazırlığı var).
- **Checklist'te kırmızı/eksik madde:** `p3_status_checks()` her maddeyi ayrı ayrı test eder (ayar var mı, tablo
  var mı, gerekli kolonlar var mı) — eksik madde adı doğrudan hangi ayar/tablonun eksik olduğunu gösterir.

### 56.13 Bilinen kısıtlama
Bu özellik, adının ve menü konumunun ("Hatırlatma ve Aksatan Amirler") ima ettiğinin aksine, **gerçek bir
otomatik hatırlatma/eskalasyon motoru DEĞİLDİR** — yalnız bunun için gereken veritabanı/ayar iskeletini
kurar ve tek bir gösterim amaçlı örnek kayıt ekler. Gerçek "son tarihi X gün geçen görevleri bul, ilgili amire
bildirim oluştur" iş mantığı bu turda kodda BULUNAMADI. AI Karar Destek tarafındaki `reminder_policy.py`/
`reminder_integration.py` saf sınıflandırma fonksiyonları sağlar (`is_overdue`, `classify_assignment_status`)
ama bunların hangi ekranda/hangi tetikleyiciyle gerçek assignment verisi üzerinde çağrıldığı bu turda ayrıca
doğrulanmadı — muhtemelen AI Kontrol Merkezi panellerinden (feature #5) tüketiliyorlar.

### 56.14 Kaynak dosyalar
| Katman | Dosya | Satır |
|---|---|---|
| Route | `app/performance/meeting_p3_reminders_routes.py` | 34 |
| Servis (Faz 9) | `app/services/performance/meeting_p3_reminders.py` | 248 |
| Servis (Faz 10) | `app/services/performance/phase10_reminder_notification_center.py` | 536 |
| Servis (köprü) | `app/services/performance/reminder_notification_service.py` | 22 |
| AI entegrasyon | `app/services/ai_decision/reminder_policy.py` (236), `reminder_integration.py` (172) | — |
| Şablon | `app/templates/performance/meeting_p3_reminders.html`, `_phase10_reminder_notification_panel.html` | — |

---

## 57. Mobil API / PWA

### 57.1 Amaç
İki ayrı istemci yüzeyine hizmet eder: (a) native Flutter mobil uygulaması için JSON+Bearer-token tabanlı bir
REST API (`/api/mobile/*`), (b) tarayıcı tabanlı Progressive Web App (PWA) altyapısı (manifest, service worker,
offline sayfası) — masaüstü/mobil tarayıcıda "ana ekrana ekle" ile yüklenebilir bir web-app deneyimi.

### 57.2 Kullanıcı girişi / navigasyon
- **Mobil API:** Doğrudan bir "menü öğesi" YOKTUR — Flutter uygulaması `/api/mobile/auth/login`'e kullanıcı
  adı/şifre POST ederek oturum açar, sonraki tüm isteklerde `Authorization: Bearer <token>` header'ı kullanır.
  Web arayüzünde bu API'ye dair bir sayfa yoktur (backend-only, admin dışı bir istemci içindir).
- **PWA:** Kullanıcı tarayıcıda BYS360'ı ziyaret ettiğinde `base.html`'deki `<link rel="manifest"
  href="/manifest.webmanifest">` etiketi sayesinde tarayıcı "ana ekrana ekle" seçeneği sunar; ayrı bir menü
  öğesi yoktur, bu bir tarayıcı-native davranışıdır.

### 57.3 Roller/erişim
- **Mobil API:** `require_mobile_user` decorator'ü (`app/api/mobile/shared.py:574-581`) — `Authorization: Bearer`
  header'ındaki token `itsdangerous.URLSafeTimedSerializer` ile doğrulanır (bkz §57.8, **JWT DEĞİLDİR**), geçerli
  kullanıcı `fn(user, *args, **kwargs)` olarak view fonksiyonuna enjekte edilir. Rol bazlı erişim mobil tarafında
  ayrıca `_has_global_scope()`/`_GLOBAL_ROLES` ile bazı endpoint'lerde daraltılır (`shared.py:65-85`).
- **PWA route'ları:** Kimlik doğrulaması gerektirmez (manifest/service-worker/offline sayfası herkese açık
  statik/yarı-statik içeriktir) — `app/pwa/routes.py` içinde hiçbir `@login_required` yoktur.

### 57.4 Routes/API
**Mobil API** — `mobile_api_bp` (`url_prefix="/api/mobile"`), CSRF'ten muaf (`csrf.exempt(mobile_api_bp)`,
JSON+Bearer kullandığı için). Alt-domainler: `domains/{auth,dashboard,assistant_chat,communication_v1_write,
communication_v2_write,kpi_target_management,notifications,personnel_read,personnel_write_all,
push_notifications,support_survey_write}.py` + kök seviyede `performance_routes.py`, `performance_read_routes.py`,
`communication_read_routes.py`, `communication_v2_read_routes.py`, `detail_read_routes.py`, `light_read_routes.py`,
`support_survey_read_routes.py`, `utility_routes.py`, `routes.py` (~20 route dosyası). Örnek uçlar:
`POST /api/mobile/auth/login`, `POST /api/mobile/auth/refresh`, `GET /api/mobile/me`.

**PWA (§63 ile çapraz-referans — bkz o bölüm için tam URL çakışma analizi):**
- `GET /manifest.webmanifest` — **ÇAKIŞAN, iki kayıtlı tanım var** (`app/pwa/routes.py` VE `app/routes.py`);
  gerçek istekte KAZANAN `main.bys360_pwa_manifest` (`app/routes.py`), bu turda `create_app()` çalıştırılıp
  `url_map.bind().match()` ile ampirik doğrulandı.
- `GET /service-worker.js` → `pwa.service_worker_js` (yalnız `app/pwa/routes.py`, çakışma yok)
- `GET /bys360-sw.js` → `main.bys360_pwa_service_worker` (yalnız `app/routes.py`, çakışma yok)
- `GET /offline` → `pwa.pwa_offline` (yalnız `app/pwa/routes.py`, canlı; `app/pwa_blueprint.py`'nin aynı-isimli
  route'u asla kayıtlı DEĞİL, bkz §63)
- `GET /pwa/csrf-refresh` → yalnız `app/pwa/routes.py`, Safari/PWA'da bayat CSRF token sorunu için

### 57.5 Core service/model
- Mobil API çekirdeği: `app/api/mobile/shared.py` (732 satır — token üretim/doğrulama, rol/kapsam yardımcıları,
  ortak response builder'lar) + `app/api/mobile/services/*` (~20 dosya, domain-özel iş mantığı: performans,
  kişi/personel, destek, anket, asistan sohbeti vb.)
- PWA: `app/pwa/routes.py` (93 satır, CANLI/kayıtlı) + `app/routes.py` satır 265-283 (main_bp üzerinde ikinci,
  rakip manifest/service-worker çifti) + `app/pwa_routes.py` (2 satır, geriye-uyum re-export shim) +
  `app/pwa_blueprint.py` (49 satır, **KAYITLI DEĞİL**, bkz §63).

### 57.6 DB bağımlılığı
Mobil API kendi ayrı tablolarına sahip DEĞİLDİR — mevcut domain tablolarını (User, performans, iletişim,
destek/anket modelleri) okur/yazar, aynı ORM modellerini web tarafıyla paylaşır. PWA route'larının DB bağımlılığı YOKTUR.

### 57.7 Kalıcı depolama
PWA statik dosyaları `app/static/pwa/` altında diskte durur (`manifest.webmanifest`, `service-worker.js`/
`bys360-sw.js`, ikonlar) — bunlar repo/deploy paketinin bir parçasıdır, kullanıcı verisi değildir. Mobil API'nin
kendine özgü bir dosya depolaması yoktur (varsa ilgili domain servisinin — örn. profil fotoğrafı — genel dosya
depolama mekanizması kullanılır).

### 57.8 Security controls
- **Token mekanizması JWT DEĞİL** — `itsdangerous.URLSafeTimedSerializer` (Flask'ın imzalı-token kütüphanesi),
  ayrı salt'lar (`_TOKEN_SALT="bys360-mobile-api-v1"`, `_REFRESH_TOKEN_SALT="bys360-mobile-refresh-v1"`).
  Access token ömrü: 24 saat (`_MOBILE_ACCESS_MAX_AGE_SECONDS = 86400`). Refresh token ömrü: 30 gün
  (`_MOBILE_REFRESH_MAX_AGE_SECONDS = 2592000`). İmza anahtarı `SECRET_KEY`/`WTF_CSRF_SECRET_KEY`'den türetilir,
  ikisi de yoksa sabit bir yerel fallback (`"bys360-mobile-local-secret"`) kullanılır — **prod'da `SECRET_KEY`
  MUTLAKA ayarlı olmalıdır**, aksi halde token güvenliği zayıflar.
  yoksa sabit fallback.
- **Mobil login için ayrı rate-limit YOKTUR** (bu turda `app/security/api_rate_limit.py` içinde "mobile"/
  "api/mobile" anahtar kelimesiyle hiçbir giriş bulunamadı) — matrisin önceki turda bildirdiği "bilinen risk"
  bu turda da doğrulandı, düzeltilmedi.
- CSRF: mobil blueprint tamamen MUAF (JSON+Bearer kullandığı için tasarım gereği); PWA route'ları CSRF'siz
  statik içerik döner (`/pwa/csrf-refresh` PWA'nın KENDİSİNİN bayat CSRF token sorununu çözmesi içindir).
- iOS Safari web-preview CORS izin listesi (`_bys360_mobile_preview_allowed_origin`) yalnız localhost/özel IP
  aralıklarına (`192.168.`, `10.`, `172.16-23.`) izin verir — genel internet origin'lerine kapalı.

### 57.9 Operasyonel bağımlılık
Yok — mobil API ve PWA route'ları harici bir servise (SMTP/Celery/Scheduled Task) bağımlı DEĞİLDİR, tamamen
senkron HTTP request-response.

### 57.10 Backup/restore ilişkisi
Mobil API'nin kendine özgü tablosu olmadığından ayrı bir yedekleme gerektirmez (ilgili domain verisiyle birlikte
yedeklenir). PWA statik dosyaları repo/deploy paketiyle birlikte gelir, ayrı bir "kullanıcı verisi" yedeklemesi
gerektirmez.

### 57.11 Zamanlanmış/arkaplan davranış
N/A.

### 57.12 Troubleshooting
- **Mobil uygulama "oturum bulunamadı" hatası (401):** access token süresi dolmuş olabilir (24 saat) — istemci
  `refresh_token` ile `/api/mobile/auth/refresh`'i çağırmalı; refresh token da dolmuşsa (30 gün) yeniden login gerekir.
- **PWA "ana ekrana ekle" görünmüyor:** `/manifest.webmanifest`'in gerçekte HANGİ handler'dan döndüğünü kontrol
  edin — `main.bys360_pwa_manifest` (app/routes.py) kazanıyor, `app/pwa/routes.py`'nin manifest'i DEĞİL; ikisinin
  içeriği farklıysa (ikon listesi, tema rengi) kafa karıştırıcı olabilir, bkz §63.
- **Service worker güncellenmiyor:** iki farklı service-worker ucu var (`/service-worker.js` vs `/bys360-sw.js`)
  — istemci JS'in HANGİSİNE register olduğu (`bys360_ios_pwa_v2.js` dosyasında `/service-worker.js` kayıtlı,
  test kanıtı: `tests/quality/test_phase12b_route_ownership_contract.py:331`) karıştırılmamalı.

### 57.13 Bilinen kısıtlama
Mobil login endpoint'i için ayrı bir brute-force rate-limit YOKTUR (§57.8) — bu, File Center'ın guest
endpoint'lerinde olduğu gibi bir `api_rate_limit.py` girdisi almamıştır. Ayrıca PWA tarafında iki ayrı,
kısmen çakışan manifest/service-worker implementasyonu VARDIR (bkz §63 için tam kanıt ve çözüm).

### 57.14 Kaynak dosyalar
| Katman | Dosya | Not |
|---|---|---|
| Mobil API çekirdek | `app/api/mobile/shared.py` (732 satır), `app/api/mobile/__init__.py` (35 satır) | |
| Mobil API domain route'ları | `app/api/mobile/domains/*.py` (11 dosya) + kök seviye `*.py` (~9 dosya) | ~20 route dosyası |
| Mobil API servisleri | `app/api/mobile/services/*.py` | ~20 dosya |
| PWA (canlı) | `app/pwa/routes.py` (93 satır) | Blueprint `pwa`, kayıtlı |
| PWA (main_bp'de ikinci implementasyon) | `app/routes.py` satır 265-283 | Kayıtlı, `/manifest.webmanifest` için KAZANAN |
| PWA (kayıtlı DEĞİL) | `app/pwa_blueprint.py` (49 satır) | Bkz §63 |
| PWA (geri-uyum shim) | `app/pwa_routes.py` (2 satır) | Yalnız re-export |

---

## 58. Onboarding Servisi — EXPLICITLY_CLASSIFIED_NON_CURRENT (FUTURE)

**Bu satır için FULLY_DOCUMENTED yerine dürüst bir sınıflandırma tercih edildi — gerekçesi aşağıdadır.**

### Bulgular
`app/services/onboarding_service.py` (24 satır) TEK bir fonksiyon içerir: `generate_secure_temporary_password(length=14)`
— `secrets` modülüyle kriptografik olarak güvenli, en az 1 büyük/küçük harf/rakam/sembol garantili rastgele
geçici şifre üretir.

**Bu fonksiyonun repoda HİÇBİR çağırıcısı yoktur** — bu turda `app/`, `tests/`, `scripts/` altında tam-repo arama
yapıldı; tek eşleşme fonksiyonun kendi tanımıdır. Test dosyası da yoktur. `git log --follow` yalnız 2 commit
gösterir: bir "baseline" commit'i ve "chore: stabilize onboarding service package" (2 satır silen, kozmetik bir
kalite-geçidi commit'i) — hiçbiri gerçek bir entegrasyon eklemez.

**Karıştırılmaması gereken AYRI bir kavram:** HR Personel Yaşam Döngüsü Merkezi'nde (`app/models/hr_models.py:675`,
`HrPersonnelLifecycle.lifecycle_type`) `"onboarding"` ("İşe Başlatma") diye bir yaşam-döngüsü TÜRÜ vardır — ama bu
TAMAMEN AYRI bir modeldir/route ailesidir (`app/institutional/hr_personnel_phase11_routes.py`,
`hr_personnel_phase12_routes.py`), zaten matrisin #1 (Personel Yönetimi/İK) satırının kapsamındadır (DOCUMENTED),
ve `app/services/onboarding_service.py` ile HİÇBİR kod bağlantısı yoktur.

### Sınıflandırma: FUTURE
**Gerekçe:** Kod repoda duruyor, sözdizimsel olarak sağlam ve güvenli bir yardımcı fonksiyon, ancak hiçbir
route/servis/script tarafından çağrılmıyor — yani kullanıcıya açık bir uç (yeni personel oluşturma akışında
"geçici şifre üret ve göster" gibi bir kullanım noktası) YOKTUR. Bu, matrisin kendi "FUTURE" tanımına birebir
uyar: *"Model/altyapı var ama kullanıcıya açık bir uç (route/UI) YOK; muhtemelen tamamlanmamış bir özellik
taslağı."* Muhtemel niyet: yeni kullanıcı oluşturma akışına (`app/admin/routes.py` içindeki personel ekleme
formu, ki orada zaten `get_default_first_login_password()` adlı BAŞKA bir fonksiyon kullanılıyor — bkz
`app/admin/ops_helpers.py`) daha güçlü bir rastgele şifre üretici entegre etmek, ama bu entegrasyon hiç
yapılmamış/tamamlanmamış görünüyor.

### Kaynak dosyalar
| Katman | Dosya | Satır |
|---|---|---|
| Servis (kullanılmayan) | `app/services/onboarding_service.py` | 24 |
| Gerçek kullanılan alternatif (yeni kullanıcı ilk şifresi) | `app/admin/ops_helpers.py::get_default_first_login_password` | — |

---

## 59. Excel Toplu İçe/Dışa Aktarma

**Düzeltme — ÖNEMLİ:** Görev tanımındaki üç başlangıç işaretçisinden İKİSİ bu turda **çağrılmayan (dead) kod**
olarak doğrulandı; gerçek, canlı personel Excel import akışı FARKLI dosyalardadır. Aşağıda hem gerçek akış hem
de bu iki ölü dosya ayrı ayrı belgelenmiştir.

### 59.1 Amaç
Personel/hiyerarşi verisinin Excel dosyasından toplu olarak sisteme aktarılması (yeni kullanıcı oluşturma/mevcut
kullanıcı güncelleme, birim/amir ataması dahil), artı boş bir Excel şablonunun indirilmesi ("dışa aktarma" bu
şablon indirme ile sınırlıdır — ayrı bir "tüm personeli Excel'e dök" özelliği bu turda BULUNAMADI, bkz §59.13).

### 59.2 Kullanıcı girişi / navigasyon
Menü: Admin/Sistem Ayarları → Kullanıcı İçe Aktarma. URL: `GET+POST /admin/users/import`
(endpoint `admin_user_import`, `app/admin/ops_routes.py:172-177`). Şablon indirme:
`personnel_excel_template_download` (`app/admin/routes.py:867`, tam URL bu turda ayrıca doğrulanmadı ama
endpoint adı ve `build_personnel_import_template_bytes()` çağrısı doğrulandı).

Ayrıca **kayıtlı DEĞİL, dolayısıyla kullanıcıya kapalı** bir ikinci önizleme aracı vardır: "Hiyerarşi Yönetişimi"
(`/admin/hierarchy-governance`, blueprint `hierarchy_governance`) — bkz §59.13.

### 59.3 Roller/erişim
Gerçek/canlı akış: `@login_required @admin_required @menu_key_required("admin_users")`
(`app/admin/ops_routes.py:173-175`) — **parent'ın (#1 Personel Yönetimi) genel decorator desenine TAM uygun.**

Kayıtlı-olmayan hiyerarşi-önizleme blueprint'i (`hierarchy_governance_routes.py`) farklı, özel bir kontrol
kullanır: `_is_admin_like() = role in {"admin","baskan","baskan_yardimcisi"}`, `before_request` ile uygulanır —
ancak bu blueprint hiç kayıtlı olmadığı için (§59.13) bu kontrol pratikte hiç ÇALIŞMAZ.

### 59.4 Routes/API
- `GET+POST /admin/users/import` — Excel yükleme, ön-kontrol (preflight), opsiyonel AI-destekli başlık
  düzeltme (`apply_ai_fixes` form alanı), gerçek yazma
- Şablon indirme endpoint'i (personnel_excel_template_download)
- (Kayıtlı değil) `POST /admin/hierarchy-governance/preview` — yalnız ÖNİZLEME raporu üretir, DB'ye yazmaz

### 59.5 Core service/model
**Gerçek/canlı akış:**
- Route body: `app/admin/ops_import_services.py` (`admin_user_import_impl()`) — `openpyxl.load_workbook` ile
  okuma, başlık normalizasyonu (`ops_helpers.py::_canonicalize_import_headers`), ön-kontrol
  (`app/services/personnel/excel_import_guard.py::validate_personnel_import_rows_for_commit`, 204 satır —
  zorunlu alan/mojibake/mükerrer-sütun kontrolü), amir-zinciri senkronu
  (`app/services/personnel/import_manager_chain_sync.py::sync_touched_users_manager_ids_from_sicils`, 115 satır)
  VEYA otomatik hiyerarşi kurma (`app/services/auto_hierarchy_service.py::auto_apply_manager_chains` — bkz #32),
  kategori atama (`app/services/personnel/categories.py`).
- Şablon üretimi: `app/services/personnel/excel_template.py::build_personnel_import_template_bytes`.

**Görev tanımındaki iki dosya — DOĞRULANMIŞ ÖLÜ KOD:**
- `app/services/excel_import_pipeline_service.py` (205 satır) — `run_excel_post_import_pipeline()` fonksiyonu
  tanımlı ama **repoda hiçbir yerden çağrılmıyor** (tam-repo arama, tests dahil, sıfır sonuç). İçeriği yine de
  anlamlı: Excel-sonrası otomatik hiyerarşi + görev/atama yenileme akışını orkestre etmek için yazılmış
  görünüyor, ama entegre edilmemiş.
- `app/services/personnel/excel_import.py` (278 satır) — `PersonnelExcelPreflightResult`,
  `normalize_personnel_excel_headers()`, `build_personnel_excel_row_payload()` gibi zengin bir preflight/parse
  API'si tanımlı ama **repoda hiçbir yerden çağrılmıyor** (tam-repo arama, sıfır sonuç). Canlı akış bunun yerine
  paralel/benzer bir işi yapan `excel_import_guard.py`'yi kullanıyor.

### 59.6 DB bağımlılığı
`User` tablosu (personel alanları: sicil_no, ad, soyad, email, unvan, birim, rol, yonetici_sicil/
ikinci_yonetici_sicil/ucuncu_yonetici_sicil, personnel_category vb.) — özel bir "import log" tablosu bu turda
görülmedi (yalnız flash-mesaj seviyesinde sonuç raporlanıyor, kalıcı bir import geçmişi tablosu bulunamadı).

### 59.7 Kalıcı depolama
Yüklenen Excel dosyası KALICI OLARAK SAKLANMAZ — `openpyxl.load_workbook(f, ...)` doğrudan upload stream'inden
belleğe okunur, diske yazılmaz.

### 59.8 Security controls
`admin_required` + `menu_key_required("admin_users")`; ön-kontrol aşaması (`validate_personnel_import_rows_for_commit`)
**hiçbir kayıt DB'ye yazılmadan önce** çalışır — hatalı/eksik veri varsa "Hiçbir kayıt veritabanına yazılmadı"
mesajıyla TÜM işlem reddedilir (tüm-ya-da-hiç, kısmi yazma yok). Mojibake (bozuk encoding) tespiti ayrıca yapılır
(`MOJIBAKE_MARKERS`). CSRF: global CSRFProtect.

### 59.9 Operasyonel bağımlılık
Yok — senkron, kullanıcı-tetiklemeli. Excel import sonrası otomatik hiyerarşi kurma adımı (#32) da senkron
olarak AYNI istek içinde çalışır (arka plan görevi değildir).

### 59.10 Backup/restore ilişkisi
Standart DB backup kapsar (yalnız `users` tablosu değişikliği, dosya sistemi bağımlılığı yok).

### 59.11 Zamanlanmış/arkaplan davranış
N/A.

### 59.12 Troubleshooting
- **"Excel ön kontrolü başarısız. Hiçbir kayıt veritabanına yazılmadı":** `import_preflight["errors"]` listesi
  ekranda gösterilir — genelde eksik zorunlu alan (`sicil_no, ad, soyad, email, unvan, birim`) veya mükerrer sütun.
- **Amir ataması Excel'den gelmiyor/yanlış:** `_has_explicit_manager_columns()` kontrolü — Excel'de 1./2./3. amir
  sicil sütunları VARSA `sync_touched_users_manager_ids_from_sicils()` çalışır (mevcut veri EZİLMEZ); YOKSA
  `auto_apply_manager_chains()` devreye girer (bkz #32).
- **"Hiyerarşi Yönetişimi" önizleme sayfası 404 veriyor:** BEKLENEN — `hierarchy_governance_bp` hiçbir yerde
  `app.register_blueprint()` ile kayıtlı DEĞİL (bu turda `create_app()` çalıştırılıp `app.blueprints` listesi
  ampirik olarak kontrol edildi, bu blueprint listede YOK).

### 59.13 Bilinen kısıtlama
(1) Görev tanımındaki iki dosyadan biri (`excel_import_pipeline_service.py`) ve ayrıca üçüncü işaretçi
(`hierarchy_excel_preview_service.py`, gerçek konumu `app/services/hierarchy_excel_preview_service.py`, 128
satır) yalnızca kayıtlı-olmayan `hierarchy_governance_bp` blueprint'i tarafından kullanılıyor — yani bu önizleme
aracı tamamen ERİŞİLEMEZ durumdadır (dead route). (2) Ayrı bir "personel listesini Excel'e dışa aktar" (tam veri
export) özelliği bu turda BULUNAMADI — yalnız BOŞ ŞABLON indirilebiliyor; gerçek veri exportu muhtemelen genel
Raporlama altyapısının (#14 PDF/Excel export, matrisin ayrı satırı) kapsamındadır, bu satırın kapsamı DIŞINDA.
(3) Kalıcı bir "import geçmişi/denetim kaydı" tablosu yok — hangi Excel dosyasının ne zaman, kim tarafından,
kaç satır etkileyerek yüklendiği yalnız uygulama loglarında (varsa) izlenebilir, DB'de özel bir audit tablosu yok.

### 59.14 Kaynak dosyalar
| Katman | Dosya | Satır | Durum |
|---|---|---|---|
| Route body (canlı) | `app/admin/ops_import_services.py` | — | CANLI |
| Route decorator (canlı) | `app/admin/ops_routes.py:172-177` | — | CANLI |
| Ön-kontrol (canlı) | `app/services/personnel/excel_import_guard.py` | 204 | CANLI |
| Amir senkronu (canlı) | `app/services/personnel/import_manager_chain_sync.py` | 115 | CANLI |
| Şablon üretimi (canlı) | `app/services/personnel/excel_template.py` | — | CANLI |
| Yardımcılar (canlı) | `app/admin/ops_helpers.py` | 213 | CANLI |
| Excel-sonrası pipeline (görev işaretçisi) | `app/services/excel_import_pipeline_service.py` | 205 | **ÖLÜ — çağrılmıyor** |
| Personel Excel preflight (görev işaretçisi) | `app/services/personnel/excel_import.py` | 278 | **ÖLÜ — çağrılmıyor** |
| Hiyerarşi Excel önizleme (görev işaretçisi, düzeltilmiş konum) | `app/services/hierarchy_excel_preview_service.py` | 128 | **ERİŞİLEMEZ — blueprint kayıtlı değil** |
| Hiyerarşi önizleme route (kayıtlı değil) | `app/admin/hierarchy_governance_routes.py` | 89 | **ERİŞİLEMEZ** |

---

## 60. Asistan Eğitim Bankası / Adım-Adım Tutor

**Düzeltme:** `app/assistant_training_bank/` dizini yalnız TEK bir JSON veri dosyası içerir
(`assistant_training_bank.json`, 278 satır) — bu dizinde HİÇ Python kodu yoktur. Bu JSON dosyası bu turda
**tam-repo arama ile hiçbir Python dosyasından/route'tan/template'ten okunduğu tespit EDİLEMEDİ** (dosya adı
`assistant_training_bank.json` için sıfır referans, kendisi hariç). Asistanın gerçek "eğitim/tutor" içeriği
TAMAMEN `app/services/ai_agent/assistant_*.py` dosyalarında Python `dataclass`/dict yapıları olarak
hardcode edilmiştir — bu turda gerçek belge bu canlı Python içeriğine dayanır.

### 60.1 Amaç
BYS360 Sanal Asistan'ın (feature #6) kural-tabanlı (LLM olmayan, `AI_PROVIDER_MODE=stub` deseniyle tutarlı)
soru-cevap/adım-adım rehberlik motoru — kullanıcının sorduğu soruyu anahtar kelime/skor eşleştirmesiyle
önceden tanımlanmış "konu" (Guide/GuideTopic) kütüphanesiyle eşler, kullanıcının ROLÜNE göre uyarlanmış
(rol-etiketli) bir cevap + ilgili ekran linkleri (`_action`/`_a` yardımcı fonksiyonları) üretir.

### 60.2 Kullanıcı girişi / navigasyon
- **Asistan sohbeti içinde şeffaf olarak:** kullanıcı BYS360 Asistanı panelinde (menü `ai_agent_panel`, feature
  #6 kapsamı) herhangi bir soru sorduğunda, `service.py`'deki büyük fallback zinciri (bkz §60.5) bu tutor
  modüllerini sırayla dener — ayrı bir "tutor" ekranı DEĞİL, aynı sohbet arayüzünün bir parçasıdır.
- **Ayrı "Öğretim Merkezi" sayfası da VAR ve ana navigasyonda linklidir** (`base.html`'de referans doğrulandı):
  `GET /ai-agent/teaching-center` (endpoint `assistant_teaching_center`, `app/ai_agent/routes.py:298-302`,
  yalnız `@login_required`) — "BYS360 Asistanı Öğretim Merkezi: güvenli eğitim bankası ekranı" (statik/salt-okunur referans ekranı).
- Ek bir API: `POST /ai-agent/api/knowledge-search` — bilgi bankasında serbest metin arama (`search_knowledge_answer`).

### 60.3 Roller/erişim
`@login_required` — Sanal Asistan'ın genel `before_request` guard'ı ile aynı (parent feature #6, ayrı bir rol
kısıtlaması bu alt-özellikte görülmedi; tüm kimliği doğrulanmış kullanıcılara açık).

### 60.4 Routes/API
- `GET /ai-agent/teaching-center` — eğitim bankası ekranı
- `POST /ai-agent/api/knowledge-search` — bilgi arama API'si
- Asistan sohbeti kendisi (feature #6 kapsamında, ayrı bir route değil, aynı `/ai-agent` sohbet ucu üzerinden)

### 60.5 Core service/model
Sıralı fallback zinciri (`app/services/ai_agent/service.py`'nin ana mesaj-işleme fonksiyonu içinde, `try/except`
zinciriyle, her biri başarısız olursa bir SONRAKİsi denenir):
1. `knowledge.py::build_knowledge_reply`
2. `assistant_step_guide.py::build_bys360_assistant_step_reply`
3. `assistant_knowledge_bank_v1.py` (719 satır) — `GuideTopic` dataclass, rol-farkında cevap üretimi
   (`build_bys360_assistant_knowledge_reply`), skor-tabanlı konu bulma (`find_bys360_guide_topic`)
4. `assistant_full_live_usage_guide_v2.py`
5. `assistant_project_master_knowledge_v3.py`
6. `assistant_stepwise_tutor_v4.py` (697 satır)
7. `assistant_visible_tutor_v6.py` (483 satır)
8. `assistant_full_stepwise_tutor_v5.py` (888 satır) — `Guide` dataclass, `build_bys360_assistant_full_tutor_reply_v5`,
   sözcük-tabanlı skorlama (`_score_guide`/`_select_guide`)
9. `assistant_chatgpt_like_v31.py`
10. `assistant_usage_manual_brain_v32.py` (son/en güncel katman — hata durumunda "V32 legacy cevap motoruna dönme" fallback'i var)

Bu, tek bir modül değil, **art arda eklenmiş çok katmanlı bir "sürüm yığını"dır** — her `vN` dosyası muhtemelen
bir öncekini büyük ölçüde SÜPERSEDE eder ama eskisi silinmemiştir, hâlâ fallback zincirinde canlı kalmıştır.

### 60.6 DB bağımlılığı
Bu turda incelenen tutor dosyalarının içeriği (Guide/GuideTopic tanımları) **kod içinde sabit (hardcoded)
Python veri yapılarıdır**, ayrı bir DB tablosundan okunmaz. `knowledge.py::search_knowledge_answer` ve genel
asistan altyapısı (`repository.py::table_exists` vb.) bazı sayaç/log tabloları kullanıyor olabilir ancak bu
turda derinlemesine tek tek doğrulanmadı (feature #6'nın genel kapsamı, DOCUMENTED).

### 60.7 Kalıcı depolama
`assistant_training_bank.json` (278 satır) diskte durur ama **hiçbir kod tarafından okunmadığı için** işlevsel
olarak kalıcı depolama rolü OYNAMAMAKTADIR — bkz §60.13.

### 60.8 Security controls
`@login_required`; cevap üretimi tamamen sunucu-taraflı kural motoruyla yapılır (harici bir LLM API çağrısı
YOK — `AI_PROVIDER_MODE=stub` deseniyle tutarlı, feature #5/#6 ile aynı). CSRF: global CSRFProtect
(`/api/knowledge-search` POST ucu için).

### 60.9 Operasyonel bağımlılık
Yok — SMTP/Celery/Scheduled Task bağımlılığı yok, tamamen senkron/kural-tabanlı, harici servise gerek duymaz.

### 60.10 Backup/restore ilişkisi
Tutor içeriği kod içinde olduğu için (DB'de değil), normal KOD dağıtımıyla (release paketi) taşınır — ayrı bir
DB/dosya yedeği gerektirmez. `assistant_training_bank.json` da kod-repoyla birlikte gelir (kullanıcı verisi değil).

### 60.11 Zamanlanmış/arkaplan davranış
N/A.

### 60.12 Troubleshooting
- **Asistan beklenmedik/eski bir cevap veriyor:** hangi katmanın (v1...v32) cevabı ürettiğini anlamak için
  `service.py`'deki try/except zincirini takip edin — bir üstteki katman `None` dönerse/istisna fırlatırsa bir
  SONRAKİ katman devreye girer; sorun genelde en ERKEN eşleşen katmandadır (zincirin en başındaki tanımlar önceliklidir).
  - Not: `assistant_usage_manual_brain_v32.py`'ye özel bir hata mesajı VAR ("V32 kullanım kılavuzu beyni
  çalışırken hata oluştu" / "V32 legacy cevap motoruna dönerken hata oluştu") — bu iki log satırı en yeni
  katmanın çöküp çökmediğini doğrudan gösterir.
- **`assistant_training_bank.json` içeriğini güncelledim ama asistan davranışı değişmedi:** BEKLENEN — bu dosya
  hiçbir kod tarafından okunmuyor (§60.13), içerik değişikliği hiçbir etkiye sahip olmayacaktır; gerçek içerik
  ilgili `assistant_*.py` dosyasında Python kodu olarak düzenlenmelidir.

### 60.13 Bilinen kısıtlama
`app/assistant_training_bank/assistant_training_bank.json` **ölü/erişilemeyen bir veri dosyasıdır** — muhtemelen
erken bir tasarım aşamasında "içerik dışsallaştırılsın" (JSON'dan yüklensin) fikriyle oluşturulmuş, ama sonraki
geliştirme dalgalarında içerik doğrudan Python koduna (v1...v32 tutor dosyaları) taşınmış ve JSON dosyası
güncellenmeden/bağlanmadan geride kalmıştır. Ayrıca 10 katmanlı fallback zinciri (§60.5) bakım açısından
karmaşıktır — yeni bir geliştirici hangi katmanın "canonical/güncel" olduğunu kod okumadan anlayamaz (isimlendirme
kuralı `vN` sürüm numarasına dayanıyor ama en yüksek sürüm numarası her zaman zincirin SONUNDA değildir — örn.
v6 zincirde v5'ten ÖNCE denenir, satır 1169 vs 1244).

### 60.14 Kaynak dosyalar
| Katman | Dosya | Satır | Durum |
|---|---|---|---|
| Route | `app/ai_agent/routes.py` (ilgili kısım, satır 284-302) | — | CANLI |
| Ana dispatcher | `app/services/ai_agent/service.py` | 1300+ | CANLI |
| Tutor v1 (knowledge bank) | `app/services/ai_agent/assistant_knowledge_bank_v1.py` | 719 | CANLI |
| Tutor v4 | `app/services/ai_agent/assistant_stepwise_tutor_v4.py` | 697 | CANLI |
| Tutor v5 | `app/services/ai_agent/assistant_full_stepwise_tutor_v5.py` | 888 | CANLI |
| Tutor v6 | `app/services/ai_agent/assistant_visible_tutor_v6.py` | 483 | CANLI |
| Eğitim bankası veri dosyası (görev işaretçisi) | `app/assistant_training_bank/assistant_training_bank.json` | 278 | **ÖLÜ — okunmuyor** |
| Şablon | `app/templates/assistant_training_bank.html` | — | CANLI |

---

## 61. Otomatik Hiyerarşi / Yönetici Zinciri Senkronu

### 61.1 Amaç
Bir personelin rolü/unvanı/birimi/üst-birimi bilgisinden 1./2./3. seviye amir zincirini (`yonetici_sicil`,
`ikinci_yonetici_sicil`, `ucuncu_yonetici_sicil`) OTOMATİK türetmek — Excel toplu import sonrası (#30) veya
elle tetiklenen "Zinciri Yeniden Kur" aksiyonuyla, mevcut açık/elle-girilmiş (explicit) amir atamalarını EZMEDEN.

### 61.2 Kullanıcı girişi / navigasyon
- **Doğrudan bir menü sayfası YOKTUR** — arka plan/admin bir yardımcı işlevdir, iki yerden tetiklenir:
  1. Personel Excel import akışının (#30, `/admin/users/import`) bir PARÇASI olarak OTOMATİK (Excel'de açık
     amir sütunları yoksa).
  2. Performans Yönetimi → Amir Zinciri Ayarları ekranındaki "Zinciri Otomatik Kur" formu:
     `GET+POST /performance/hierarchy-settings` ≡ `/performance/hierarchy/settings`
     (endpoint `performance_hierarchy_settings`, `app/performance/routes.py:377-382`), form POST
     `action=auto_build_chains`.

### 61.3 Roller/erişim
`@login_required @admin_required @menu_key_required("performance_hierarchy_assignments")`
(`app/performance/routes.py:379-381`) — **parent'ın (#2 Performans Yönetimi) genel decorator desenine TAM
uygun** (Arşiv/Başkan-Onayları/Notlar'ın fonksiyon-içi özel rol-seti deseninden FARKLI olarak).

### 61.4 Routes/API
- `GET+POST /performance/hierarchy-settings` ≡ `/performance/hierarchy/settings` — amir zinciri ayar ekranı +
  `action=auto_build_chains` POST aksiyonu (elle tetikleme)
- Ayrıca Excel import route'unun (`/admin/users/import`) İÇİNDE dolaylı, otomatik çağrı (kullanıcıya ayrı bir uç
  olarak görünmez)

### 61.5 Core service/model
- Ana servis: `app/services/auto_hierarchy_service.py` (137 satır) — `auto_apply_manager_chains()`,
  `infer_role_from_profile()`. Rol/unvan → kanonik rol değeri dönüşümü için
  `app/services/personnel_sync_service.py::canonical_role_value/canonical_role_label`'a bağımlı (import
  başarısız olursa yerel bir fallback tanımı devreye girer, satır 28-46 — savunmacı programlama).
- Açık-atama tespiti: `app/services/explicit_manager_chain_service.py` (47 satır) — `has_explicit_manager_fields()`,
  `current_manager_tuple()` — bir kullanıcının 1./2./3. amir alanlarından herhangi biri doluysa "açık atama var"
  sayılır ve (varsayılan `preserve_explicit_chain=True` ile) OTOMATİK mantık tarafından EZİLMEZ.
- Zincir çözümleme motoru: `app/services/performance/chain_rule_engine.py::resolve_authoritative_desired_chain`
  (bu turda yalnız çağrıldığı doğrulandı, iç mantığı derinlemesine okunmadı) + `app/services/hierarchy_rulebook_service.py`
  (`build_lookup`, `infer_role_from_profile`, `is_system_user`).
- İlişkili: `app/services/assignment_sync_service.py` (524 satır) — hiyerarşi değişikliği sonrası performans
  değerlendirme ATAMALARININ (`EvaluationAssignment`) yeniden senkronu (ayrı ama bağlantılı bir sorumluluk;
  Excel-sonrası pipeline'da — dead olan `excel_import_pipeline_service.py`'de — ikisi birlikte orkestre edilmesi
  amaçlanmış görünüyor, ama canlı akışta ayrı ayrı çağrılıyorlar).

### 61.6 DB bağımlılığı
Ayrı bir tablo YOK — doğrudan `User` modelinin alanlarını günceller: `role`, `role_label`, `yonetici_sicil`,
`ikinci_yonetici_sicil`, `ucuncu_yonetici_sicil`. `commit=False` varsayılanıyla çağrılır (çağıran taraf —
Excel import veya hierarchy-settings route'u — kendi transaction'ını yönetir).

### 61.7 Kalıcı depolama
N/A — yalnız DB (`User` tablosu alanları).

### 61.8 Security controls
`admin_required` + `menu_key_required` (elle tetikleme ucu için). Sistem kullanıcıları (`is_system_user()`)
otomatik zincir kurmadan HARİÇ tutulur — bu bir güvenlik değil veri-bütünlüğü kontrolüdür ama yanlışlıkla
sistem hesaplarının hiyerarşiye dahil edilmesini önler. CSRF: global CSRFProtect.

### 61.9 Operasyonel bağımlılık
Yok — senkron, ya Excel import isteğinin bir parçası ya da elle tetiklenen bir form POST'u içinde çalışır.
Zamanlanmış görev YOK (`scripts/windows/*.ps1` içinde "hiyerarsi"/"hierarchy" anahtar kelimesiyle arama bu turda
sıfır sonuç verdi).

### 61.10 Backup/restore ilişkisi
Standart DB backup kapsar (yalnız `users` tablosu alan güncellemeleri).

### 61.11 Zamanlanmış/arkaplan davranış
N/A — tamamen kullanıcı-tetiklemeli (Excel import anı veya "Zinciri Otomatik Kur" butonu).

### 61.12 Troubleshooting
- **Excel'den gelen amir ataması bekleniyor ama otomatik mantık onu EZDİ:** `preserve_explicit_chain=True`
  (varsayılan) olsa bile, eğer `fill_only_missing=True` VE alan zaten DOLU değilse otomatik değer yazılır —
  `has_explicit_manager_fields()` YALNIZ herhangi bir amir alanı doluysa `True` döner, bu nedenle 1. amir dolu
  ama 3. amir boşsa, 3. amir alanı otomatik doldurulabilir (satır 98-100'deki `preserve_explicit_chain` kontrolü
  KULLANICI SEVİYESİNDEDİR, alan-seviyesinde değil — yani bir kullanıcının HERHANGİ bir açık amir alanı varsa o
  kullanıcı TAMAMEN atlanır, kısmi doldurma yapılmaz. Bu davranış §61.13'te netleştirilmiştir.)
- **"Zinciri Otomatik Kur" butonu bazı kullanıcıları atlıyor:** `skipped_count` — ya `is_system_user()` ya da
  `has_explicit_manager_fields()` nedeniyle (açık atama korunuyor) atlanmış olabilir; `warnings` listesi
  `chain_rule_engine`'den gelen kullanıcı-özel uyarıları içerir.

### 61.13 Bilinen kısıtlama
`preserve_explicit_chain` kontrolü KULLANICI-SEVİYESİNDEDİR, ALAN-SEVİYESİNDE DEĞİLDİR: bir kullanıcının 1./2./3.
amir alanlarından SADECE BİRİ bile elle doldurulmuşsa (`has_explicit_manager_fields()` `True` döner), o kullanıcı
otomatik zincir kurma mantığından TAMAMEN atlanır — yani örneğin yalnız 1. amiri elle girilmiş, 2. ve 3. amiri
boş bırakılmış bir kullanıcının 2./3. amirleri OTOMATİK OLARAK DOLDURULMAZ, kullanıcı tamamen "skip" edilir. Bu
kasıtlı bir güvenli-taraf tercihi olabilir (kısmi otomatik/kısmi elle karışık veri riskini önlemek için) ama
belgelenmemiş bir davranıştır ve yöneticiler için şaşırtıcı olabilir.

### 61.14 Kaynak dosyalar
| Katman | Dosya | Satır |
|---|---|---|
| Ana servis | `app/services/auto_hierarchy_service.py` | 137 |
| Açık-atama tespiti | `app/services/explicit_manager_chain_service.py` | 47 |
| Zincir çözümleme motoru | `app/services/performance/chain_rule_engine.py` | — (bu turda tek tek satır sayılmadı) |
| Kural kitabı | `app/services/hierarchy_rulebook_service.py` | — |
| İlişkili (atama senkronu) | `app/services/assignment_sync_service.py` | 524 |
| Route (elle tetikleme) | `app/performance/routes.py` (satır 377-403) | — |

---

## 62. Portal Sosyal Otomatik İçe Aktarma (Instagram)

**Düzeltme — ÖNEMLİ:** Matrisin önceki turda bildirdiği *"Scheduled Task: BYS360 Portal Social Auto Import
V3B2"* operasyonel bağımlılığı bu özelliğe YANLIŞ ATFEDİLMİŞ olabilir — bu turda doğrulandı ki bu zamanlanmış
görev, `instagram_portal_sync.py`'yi DEĞİL, TAMAMEN AYRI bir servisi (`portal_social_embed_service.py`,
genel "sosyal medya embed tarama" özelliği) çalıştırıyor. Instagram senkronu bu turda yalnız MANUEL (kullanıcı
tetiklemeli) bir buton olarak doğrulanabildi. Ayrıntı §62.9/§62.13'te.

### 62.1 Amaç
Kurumun Instagram hesap(lar)ındaki gönderi (media) ve aktif hikaye (story) içeriklerini, Meta Graph API
üzerinden çekip mevcut Portal akışına (PortalPost yapısına) normal gönderi gibi aktarmak — yeni bir DB tablosu
GEREKTİRMEDEN, mevcut `PortalPost`/`PortalPostAttachment` yapısını özel MIME-tipi işaretleyicilerle
("text/x-instagram-external-id" vb.) etiketleyerek.

### 62.2 Kullanıcı girişi / navigasyon
**Ayrı/kasıtlı bir menü sayfası YOKTUR** (matrisin bu kısmı DOĞRU) — ancak Portal akış ekranında (feed.html)
yetkili bir kullanıcının tetikleyebileceği bir buton/aksiyon VARDIR: `POST /portal/instagram/sync`
(`app/portal/routes.py:874-880`, endpoint `portal_instagram_sync`). Yani "yalnız arka-plan" tanımı yalnız
KISMEN doğrudur — bu turda bir Scheduled Task tarafından OTOMATİK tetiklendiği KANITLANAMADI (bkz §62.9), ama
tamamen "arayüzsüz/erişilemez" de değildir; Portal Moderasyon yetkisi olan bir kullanıcı manuel tetikleyebilir.

### 62.3 Roller/erişim
`@login_required @menu_key_required("portal_moderation")` + fonksiyon-içi `can_manage_portal(current_user)`
kontrolü (`app/portal/routes.py:875-879`) — Portal modülünün (feature #3, DOCUMENTED) genel moderasyon yetki
modeliyle AYNIDIR, ayrı bir yetki kümesi icat edilmemiş.

### 62.4 Routes/API
`POST /portal/instagram/sync` — tek endpoint, `sync_instagram_to_portal(actor_user=current_user)` çağırır.
Ayrıca `app/services/portal_social_task_service.py` içinde admin-kontrol fonksiyonları TANIMLI ama **hiçbir
route'tan çağrılmıyor** (bkz §62.13): `get_social_auto_task_status()`, `install_social_auto_task()`,
`remove_social_auto_task()`, `run_social_auto_import_now()`.

### 62.5 Core service/model
- Ana senkron mantığı: `app/services/instagram_portal_sync.py` (312 satır) — `fetch_account_media()`,
  `fetch_account_stories()` (Meta Graph API HTTP çağrıları, `urllib.request` ile, `graph.facebook.com`),
  `import_item_to_portal()` (PortalPost + PortalPostAttachment oluşturma, mükerrer-import önleme
  `_already_imported()` ile media_id bazlı), `expire_old_story_posts()` (24 saatlik hikaye ömrü sonrası
  otomatik pasifleştirme), `sync_instagram_to_portal()` (orkestratör).
- Yardımcı (kullanılmayan uç fonksiyonlar dışında): `app/services/portal_social_task_service.py` (163 satır) —
  Windows Scheduled Task durumu/kurulum/kaldırma/manuel-çalıştırma yardımcıları, ama route'suz (§62.13).
- Model: özel bir model YOK — mevcut `PortalPost`/`PortalPostAttachment`/`PortalActivityLog`/`User` modelleri
  kullanılıyor (`app/models` içinden import, Portal modülünün — feature #3 — genel modelleri).

### 62.6 DB bağımlılığı
Yeni tablo YOK. `PortalPost` (yeni gönderi olarak, `source`/işaretleyici alanlarla Instagram kökenli olduğu
belirtiliyor), `PortalPostAttachment` (medya URL'si, MIME tipi özel `text/x-instagram-*` sabitleriyle — bkz
§62.1), `PortalActivityLog` (aktivite kaydı) — tümü Portal modülünün (feature #3) MEVCUT tabloları.

### 62.7 Kalıcı depolama
Instagram medyasının kendisi (görsel/video dosyası) BYS360 tarafında diske İNDİRİLMEZ — yalnız Instagram'ın
kendi CDN URL'si (`media_url`/`thumbnail_url`) `PortalPostAttachment`'a MIME-etiketli metin olarak kaydedilir;
portal akışı bu URL'yi doğrudan Instagram CDN'inden render eder (hotlinking). **BYS360 tarafında kalıcı medya
depolama YOKTUR.**

### 62.8 Security controls
- Route: `login_required` + `menu_key_required` + `can_manage_portal()` (Portal'ın genel yetki modeli).
- Erişim token'ı (`BYS360_INSTAGRAM_ACCESS_TOKEN`) ortam değişkeninden okunur, KODA GÖMÜLÜ DEĞİLDİR.
- Servis "safe-by-default" tasarlanmış: gerekli env değişkenleri (özellikle access token) yoksa hiçbir şey
  yapmaz (docstring, satır 4-7) — bu turda `sync_instagram_to_portal()` içinde bu erken-çıkış davranışı ayrıca
  satır satır doğrulanmadı ama modülün genel tasarım ilkesi olarak dosya başında AÇIKÇA belgelenmiştir.
- Girdi temizliği: tüm dış (Instagram API'den gelen) metin `sanitize_free_text()` ile temizlenir (`_clean()` sarmalayıcı).
- CSRF: global CSRFProtect (POST route).

### 62.9 Operasyonel bağımlılık
**Meta/Facebook Graph API kimlik bilgileri GEREKİR** — env değişkenleri: `BYS360_INSTAGRAM_ACCESS_TOKEN`
(zorunlu, boşsa muhtemelen no-op), `BYS360_INSTAGRAM_API_VERSION` (varsayılan `v25.0`),
`BYS360_INSTAGRAM_ACCOUNTS` (virgülle ayrılmış `username:ig_user_id` listesi), artı iki sabit hesap için
fallback env'ler (`BYS360_INSTAGRAM_TARIHIALAN_ID`, `BYS360_INSTAGRAM_CASAMER_ID`).

**Zamanlanmış görev DÜZELTMESİ:** `scripts/windows/install_bys360_social_auto_import_v3b2_task.ps1` GERÇEKTEN
VAR ve "BYS360 Portal Social Auto Import V3B2" adlı bir Windows Scheduled Task kuruyor (günde 3 kez: 09:00,
13:00, 17:00) — AMA bu görev `scripts\portal\run_bys360_social_media_embed_scan_v3b.py`'yi çalıştırıyor, ki bu
script `app.services.portal_social_embed_service::run_social_embed_scan`/`queue_social_urls`'i import ediyor
(**`instagram_portal_sync.py` DEĞİL**). Yani bu belgenin kapsamındaki `sync_instagram_to_portal()` fonksiyonunun
bu Scheduled Task tarafından çağrıldığına dair BU TURDA HİÇBİR KOD KANITI bulunamadı — tam-repo arama
(`sync_instagram_to_portal` fonksiyon adı için `app/`, `scripts/` dahil) yalnız `app/portal/routes.py`'deki
manuel-tetikleme çağrısını buldu.

### 62.10 Backup/restore ilişkisi
Standart DB backup kapsar (PortalPost/PortalPostAttachment, Portal modülünün genel yedekleme kapsamında) —
medya dosyaları BYS360'da SAKLANMADIĞI için (§62.7) ayrı bir dosya-sistemi yedeği GEREKMEZ. **Ancak** bu şu
anlama gelir: eğer Instagram'daki orijinal gönderi/hikaye silinirse veya CDN URL'si süresi dolarsa, BYS360
portal akışındaki görsel/video de KIRILIR (hotlink çürümesi) — DB backup bunu KORUYAMAZ.

### 62.11 Zamanlanmış/arkaplan davranış
Bu belgenin kapsamındaki servis (`instagram_portal_sync.py`) için **DOĞRULANMIŞ bir otomatik/zamanlanmış
tetikleme YOKTUR** (§62.9) — yalnız manuel `POST /portal/instagram/sync` ile çalışır. `expire_old_story_posts()`
fonksiyonu da yalnız `sync_instagram_to_portal()` çağrıldığında (yani manuel tetiklemede) yan-etki olarak
çalışır, ayrı bir zamanlanmış "hikaye süresi dolsun" görevi YOKTUR.

### 62.12 Troubleshooting
- **"Instagram Senkronize Et" butonu hiçbir şey yapmıyor gibi görünüyor:** `BYS360_INSTAGRAM_ACCESS_TOKEN` env
  değişkeni tanımlı mı kontrol edin — tanımsızsa servis tasarım gereği sessizce no-op olabilir (§62.8).
- **Yeni Instagram gönderisi portalda GÖRÜNMÜYOR ve kimse butona basmadı:** BEKLENEN — bu özellik otomatik
  ÇALIŞMIYOR (§62.9/§62.11), yalnız manuel tetikleme ile senkronize olur; "otomatik" beklentisi bu kod tabanında
  YANLIŞTIR.
- **Görsel/video kırık (broken image) görünüyor:** Instagram CDN URL'si süresi dolmuş olabilir (hotlink,
  §62.7/§62.10) — BYS360 tarafında bir "yeniden indir" mekanizması bu turda BULUNAMADI.
- **Mükerrer gönderi import edilmiyor (beklenen):** `_already_imported(media_id, kind=...)` kontrolü — aynı
  Instagram media_id ikinci kez import edilmez, bu KASITLI bir korumadır, hata değildir.

### 62.13 Bilinen kısıtlama
(1) `instagram_portal_sync.py`'nin gerçek zamanlanmış bir tetikleyicisi bu turda DOĞRULANAMADI — özellik adının
("Otomatik İçe Aktarma") ima ettiğinin aksine, kod kanıtı yalnız MANUEL bir tetikleme yolu gösteriyor; "otomatik"
kelimesi muhtemelen kurulu-ama-farklı-bir-servisi-çalıştıran Scheduled Task ile karıştırılmıştır. Repo'nun asıl
otomatik/zamanlanmış sosyal medya işi `portal_social_embed_service.py` üzerinden yürüyor (bu servis bu görevin
KAPSAMI DIŞINDA, ayrı bir araştırma gerektirir). (2) `portal_social_task_service.py`'deki
install/remove/status/run-now yardımcı fonksiyonları hiçbir route'tan ÇAĞRILMIYOR — muhtemelen bir yönetim
CLI'sı/script'i için hazırlanmış ama web arayüzüne hiç bağlanmamış. (3) Medya CDN-hotlink olduğu için
Instagram tarafında silinen/süresi dolan içerik BYS360'da kırık görünebilir, bir önbellekleme/yeniden-indirme
mekanizması yok.

### 62.14 Kaynak dosyalar
| Katman | Dosya | Satır | Not |
|---|---|---|---|
| Ana senkron servisi | `app/services/instagram_portal_sync.py` | 312 | CANLI, yalnız manuel tetiklenir |
| Route | `app/portal/routes.py` (satır 874-880) | — | CANLI |
| Admin yardımcıları (kullanılmayan) | `app/services/portal_social_task_service.py` | 163 | **route'suz, çağrılmıyor** |
| Zamanlanmış görev installer | `scripts/windows/install_bys360_social_auto_import_v3b2_task.ps1` | — | VAR ama FARKLI bir script'i (`run_bys360_social_media_embed_scan_v3b.py` → `portal_social_embed_service.py`) çalıştırıyor |

---

## 63. İki Ayrı, Örtüşen PWA İmplementasyonu — Bulgu Çözümü

**Durum: BU TURDA KOD-KANITLI OLARAK ÇÖZÜLDİ (kısmi çakışma tespiti dahil).** Aşağıdaki tüm bulgular
`create_app()` gerçekten çalıştırılıp `app.blueprints`/`app.url_map.iter_rules()`/`url_map.bind().match()`
canlı olarak incelenerek ampirik biçimde doğrulandı (yalnız statik kod okuması değil).

### Yöntem
```python
from app import create_app
app = create_app()
adapter = app.url_map.bind('localhost', url_scheme='http')
adapter.match('/manifest.webmanifest', method='GET')  # -> hangi endpoint GERÇEKTEN cevap veriyor?
app.blueprints  # -> hangi blueprint'ler GERÇEKTEN kayıtlı?
'app.pwa_blueprint' in sys.modules  # -> bu modül hiç İMPORT EDİLİYOR mu?
```

### Bulgular (ampirik olarak doğrulanmış)
1. **`app.blueprints` = `['ai_agent', 'executive_summary', 'health', 'main', 'mobile_api', 'pwa',
   'strategic_performance']`** — `bys360_pwa` (yani `app/pwa_blueprint.py`'nin tanımladığı blueprint) bu listede
   **YOKTUR**.
2. **`'app.pwa_blueprint' in sys.modules` → `False`** — bu modül uygulama başlatılırken hiçbir yerden
   IMPORT DAHİ EDİLMİYOR. `app/__init__.py` içinde `app.pwa.routes`'tan `pwa_bp` import edilip
   `_register_pwa_routes()` ile kaydediliyor (satır 93-97, `if "pwa" not in app.blueprints"` korumalı) — ama
   `app/pwa_blueprint.py` için BENZER bir çağrı HİÇBİR YERDE yok.
3. **Bu, repo'nun KENDİ test paketi tarafından da bilinçli olarak doğrulanan bir durumdur:**
   `tests/quality/test_phase12b_route_ownership_contract.py::test_source_only_route_candidates_are_absent_from_fresh_production_runtime`
   `"app.pwa_blueprint"` modülünü `app.workflow.routes`, `app.routes_president_scorecard_v2` gibi diğer bilinen
   "yalnız-kaynakta-var, canlı runtime'da YOK" (source-only) adaylarıyla birlikte AÇIKÇA listeler ve taze bir
   `create_app()` sonrası `sys.modules` içinde YÜKLENMEMİŞ olduğunu assert eder. Yani proje EKİBİ zaten bu
   dosyanın ölü olduğunun FARKINDA ve bunu bir regresyon testiyle korumaya almış.
4. **`/manifest.webmanifest` için GERÇEK, canlı bir ÇAKIŞMA VAR — ama `pwa_blueprint.py` ile DEĞİL:**
   Bu yol İKİ KEZ kayıtlıdır — biri `app/pwa/routes.py` (`pwa.manifest_webmanifest`, blueprint `pwa`, canlı ve
   kayıtlı), diğeri `app/routes.py` satır 265-272 (`main.bys360_pwa_manifest`, doğrudan `main_bp` üzerinde,
   yorum etiketi `BYS360_MOBILE_PWA_FAZ2_V1_ROUTES`, iOS Safari desteği için sonradan eklenmiş). İkisi de
   `app.url_map.iter_rules()` çıktısında GERÇEKTEN mevcut — Werkzeug aynı statik path için birden fazla Rule'a
   izin verir. `adapter.match('/manifest.webmanifest', 'GET')` GERÇEK isteklerde **`main.bys360_pwa_manifest`**'i
   döndürüyor — yani `app/routes.py`'deki (main_bp) implementasyon KAZANIYOR, `app/pwa/routes.py`'nin manifest
   handler'ı bu YOL için fiilen GÖLGEDE KALIYOR (`pwa.manifest_webmanifest` url_map'te var ama hiçbir isteğe
   asla cevap vermiyor).
5. **`/service-worker.js` → yalnız `pwa.service_worker_js`** (çakışma yok, yalnız `app/pwa/routes.py`'de tanımlı).
6. **`/bys360-sw.js` → yalnız `main.bys360_pwa_service_worker`** (çakışma yok, yalnız `app/routes.py`'de tanımlı;
   `app/pwa_blueprint.py`'nin `/sw.js`'i zaten FARKLI bir path VE kayıtlı değil).
7. **`/offline` → `pwa.pwa_offline`** (yalnız `app/pwa/routes.py`, canlı) — `app/pwa_blueprint.py`'nin aynı-isimli
   `/offline` route'u kayıtlı olmadığı için pratikte hiç çakışmıyor.
8. **`app.utils.url_map_dedupe.dedupe_identical_url_rules(app)`** — `app/__init__.py` sonunda çağrılan bu
   fonksiyon YALNIZ (endpoint, path, HTTP-metod) ÜÇLÜSÜ TAM AYNI olan kayıtları temizler (satır 25-26 içindeki
   `_rule_key()`). `main.bys360_pwa_manifest` ile `pwa.manifest_webmanifest` FARKLI endpoint adlarına sahip
   olduğu için bu dedup mekanizması onları BİRLEŞTİRMEZ/TEMİZLEMEZ — ikisi de url_map'te kalıcı olarak durur,
   yalnız biri (main_bp'nin) fiilen isteklere cevap verir.
9. `app/pwa_routes.py` (2 satır) yalnız `app/pwa/routes.py`'den `pwa_bp`'yi geriye-uyum için re-export eden bir
   shim'dir — kendi başına bir route kaynağı DEĞİLDİR, kafa karıştırıcı olmaması için ayrıca not düşülür.

### Sonuç / Çözüm
**Sorulan soru ("hangisi kanonik, belirsiz") artık KOD-KANITLI olarak cevaplanabilir:**
- **`app/pwa_blueprint.py` kanonik DEĞİLDİR — tamamen ÖLÜ KODDUR.** Hiç import edilmiyor, hiç kayıtlı değil,
  hiçbir isteğe cevap veremez. Projenin kendi testi bu ölü-durumu zaten bir sözleşme olarak koruyor. Bu dosya
  güvenle SİLİNEBİLİR bir temizlik adayıdır (kod bu turda DEĞİŞTİRİLMEDİ, yalnız TESPİT edildi).
- **Gerçek canlı çakışma `app/pwa/routes.py` (blueprint `pwa`) İLE `app/routes.py`'nin (main_bp) satır 265-283
  aralığındaki iOS-özel PWA route'ları ARASINDADIR** — `/manifest.webmanifest` için main_bp KAZANIR (kayıt
  sırası: `create_bys360_application()` içinde main_bp'nin route'ları `app/__init__.py::create_app()`'ın EN
  BAŞINDA, `pwa` blueprint'i ise `_register_pwa_routes()` ile DAHA SONRA kaydedilir — Werkzeug'un statik-path
  eşleştirmesinde erken-kayıtlı kural kazanıyor, bu turda ampirik olarak doğrulandı ama bu spesifik davranış
  KASITLI TASARLANMIŞ değil, muhtemelen fark edilmemiş bir yan etkidir). Bu, `dedupe_identical_url_rules()`
  tarafından da YAKALANMAZ çünkü endpoint adları farklı. **Bu, bu turda tespit edilen YENİ, daha DAR kapsamlı
  bir teknik-borç bulgusudur** — orijinal bulgu ("pwa/routes.py vs pwa_blueprint.py hangisi kanonik") ÇÖZÜLDÜ,
  ama onun yerine "main_bp'nin inline PWA route'ları, pwa blueprint'inin manifest handler'ını sessizce
  gölgeliyor" şeklinde DAHA KESİN, kod-kanıtlı bir ikinci-derece bulgu ortaya çıktı.

### Önerilen (uygulanmadı — yalnız araştırma bulgusu)
1. `app/pwa_blueprint.py` dosyasını (ve varsa `app/pwa_routes.py` üzerinden ona işaret eden atıfları) kaldırmak
   güvenli bir temizliktir — hiçbir çalışan davranışı DEĞİŞTİRMEZ (zaten ölü kod).
2. `/manifest.webmanifest` için iki implementasyondan birini (muhtemelen `app/routes.py`'deki, çünkü fiilen
   kazanıyor ve iOS-özel davranış içeriyor) kanonik ilan edip `app/pwa/routes.py::manifest_webmanifest()`'i
   kaldırmak veya ikisini BİRLEŞTİRMEK, gelecekte kayıt sırası değişirse (örn. `_register_pwa_routes()`'un
   çağrılma noktası taşınırsa) sessizce DAVRANIŞ DEĞİŞTİRME riskini ortadan kaldırır.

### Kaynak dosyalar (kanıt)
| Dosya | Rol | Kayıtlı mı? |
|---|---|---|
| `app/pwa/routes.py` (93 satır) | Blueprint `pwa` — `/service-worker.js`, `/offline`, `/pwa/csrf-refresh` CANLI; `/manifest.webmanifest` tanımlı ama gölgede | EVET (`app/__init__.py:93-97`) |
| `app/routes.py` (satır 265-283) | main_bp üzerinde `/manifest.webmanifest` (KAZANAN) + `/bys360-sw.js` | EVET (main_bp her zaman kayıtlı) |
| `app/pwa_blueprint.py` (49 satır) | Blueprint `bys360_pwa` — `/manifest.webmanifest`, `/sw.js`, `/offline` | **HAYIR — hiç import/register edilmiyor** |
| `app/pwa_routes.py` (2 satır) | Yalnız re-export shim | N/A (route kaynağı değil) |
| `app/utils/url_map_dedupe.py` (101 satır) | Yalnız TAM AYNI (endpoint+path+metod) kuralları temizler, bu vakayı KAPSAMAZ | — |
| `tests/quality/test_phase12b_route_ownership_contract.py` (satır 320-360) | `pwa_blueprint`'in ölü olduğunu ZATEN doğrulayan mevcut test | — |

---
