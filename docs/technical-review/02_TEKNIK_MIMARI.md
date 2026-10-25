# 02 — BYS360 Teknik Mimari

| Alan | Değer |
|---|---|
| Kaynak (incelenen) | `origin/assistant-v2-full` @ `f796107fa6ab42096065a02d4724ec7e8d22f608` |
| Belgelenmiş production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` (tag `bys360-prod-2026.10.07-cdae2795`) — `SOURCE_OF_TRUTH.md:12-13` |
| Production ile dal ucu farkı | 81 dosya, +5760/−405 satır; 18 PR birleşmesi (#48–#67), migration değişikliği yok (`git diff --stat cdae2795..f796107f`) |
| Hazırlanma tarihi | 2026-10-11 |

**Kanıt sınıfları:** *Kodda var* = dal ucundaki kaynakta okundu. *Testli* = ilgili test dosyası var ve CI kapsamında (CI'nin dal ucunda geçtiği bu belgede yeniden doğrulanmadı). *Canlıda doğrulandı* = yalnız `SOURCE_OF_TRUTH.md` ve `docs/quality/BYS360_PRODUCTION_CUTOVER_2026-10-07.md` kayıtlarına dayanır; bu belge canlı sistemi doğrulamamıştır.

> Önemli: Dal ucu production değildir (`SOURCE_OF_TRUTH.md:14,20,74`). Aşağıda dal ucunda olup production SHA'da olmayan davranışlar ayrıca işaretlenmiştir.

---

## 1. Genel yaklaşım

- Tek Flask uygulaması, sunucu taraflı Jinja2 render; ek olarak PWA katmanı ve aynı süreçte çalışan JSON mobil API. Mikroservis değildir (`docs/current_state/02_BYS360_Sistem_Mimarisi_ve_Teknik_Tasarim.md:19`, tarih 2026-09-02, tarihsel kaynak SHA `873e6d3`).
- Çekirdek bağımlılıklar (pinli): Flask 3.1.3, Flask-Login 0.6.3, Flask-SQLAlchemy 3.1.1, Flask-WTF 1.2.1, Flask-Migrate 4.0.7, SQLAlchemy 2.0.36, psycopg2-binary 2.9.9, waitress 3.0.1, gunicorn 25.3.0, sentry-sdk 2.20.0, redis 5.0.8, rq 2.3.3, Flask-Limiter 3.5.0 (`requirements.txt:1-26`). Kilitli/hash'li sürümler `requirements.lock`.
- Python 3.12 (`CONTRIBUTING.md:36`; CI `actions/setup-python` 3.12 — `.github/workflows/bys360-ci.yml:70-73`).

## 2. Uygulama fabrikası (app factory)

Kodda var:

1. `app/__init__.py:277` `create_app()` → `app/bootstrap/application_bootstrap.py:40-49` `create_bys360_application()`.
2. Sıra: `create_configured_flask_app` → `run_preflight_checks` (ProxyFix burada uygulanır, `app/bootstrap/factory_bootstrap.py:43-44`) → `initialize_core_extensions` (`db`, `login_manager`, `migrate`, `csrf` — `app/extensions.py:6-9`) → `configure_route_bootstrap` → `configure_runtime_services` (Sentry, loglama, hata yöneticileri, guard'lar, response hardening, `register_runtime_schema_cli` — `application_bootstrap.py:52-69`) → `run_startup_validation_pipeline` (startup security audit + şema doğrulaması — `application_bootstrap.py:72-77`).
3. `create_app()` sonrasında opsiyonel kayıtlar `_run_optional_startup` sarmalayıcısıyla yapılır: asistan rol matrisi, modül erişimi, kısayol görünürlüğü, notification mailer (`app/__init__.py:36-41`), PWA, CSRF yenileme, mobil API, API/Dosya Merkezi rate limit, Yönetici Özeti (`app/__init__.py:285-302`).

Gözlem (kodda var): Opsiyonel kayıtlar hata durumunda uygulamayı durdurmaz; örneğin Yönetici Özeti blueprint'i hata alırsa yalnız uyarı loglanır (`app/__init__.py:210-221`). Bir modülün sessizce kayıt dışı kalması bu nedenle başlangıçta görünür hata üretmez.

## 3. Blueprint / route mimarisi

Kodda var — "tek omurga + modüler route dosyası" modeli:

- Birincil blueprint `main_bp = Blueprint("main", ...)` (`app/route_registry.py:61`). Modüller kendi view'larını `@main_bp.route` ile bu nesneye ekler: `app.auth.routes`, `app.account.routes`, `app.admin.routes`, `app.performance.routes`, `app.dashboard.routes`, `app.institutional.routes`, `app.communication.routes`, `app.support.routes`, `app.settings_center.routes` ve kaldırılmamışsa `app.portal.routes` (`app/route_registry.py:16-38`).
- Dosya Merkezi route'ları `app/routes.py:435-436` içindeki import ile `main_bp`'ye bağlanır.
- Ayrı blueprint olarak kaydedilenler: `main`, `health` (zorunlu), `strategic_performance`, `ai_agent` (opsiyonel) — `app/bootstrap/route_bootstrap.py:31-56`; `mobile_api` (`/api/mobile`, `app/api/mobile/__init__.py:5,24-34`); `pwa` (`app/__init__.py:93-97`); `executive_summary` (`/dashboard` öneki, `app/executive_summary/routes.py:10-13`).
- URL önekleri: `ai_agent` → `/ai-agent` (`app/ai_agent/routes.py:20-23`), `strategic_performance` → `/performans/stratejik` (`app/modules/strategic_performance/routes.py:44-47`).
- Uyumluluk katmanları: `LEGACY_SHIM_MODULES` ve `LEGACY_ARCHIVE_MODULES` (`app/route_registry.py:40-59`).
- Kopya endpoint koruması yalnız `main.performance_low_score_president_reject` için gevşetilmiştir (`app/bootstrap/route_bootstrap.py:60-62`).

Canlıda doğrulandı (kayıt düzeyinde): 2026-10-07 cutover smoke adımı `ROUTE_COUNT=996` raporlamıştır (`STATUS.md` 2026-10-07 girdisi).

Tarihsel olarak açık bırakılmış gözlemler (DOC-02 Ek, 2026-09-02; bu belgede yeniden doğrulanmadı): `admin_bp` kayıtsız (kasıtlı), `strategic_performance_dashboard_bp` için `register_blueprint` çağrısı bulunamadı, `app/ai/routes.py` faz10/11/12 alt-blueprint guard'ı muhtemelen etkisiz (`docs/current_state/02_...md:194-196`).

## 4. Veritabanı: PostgreSQL, SQLAlchemy, Alembic

- Production: PostgreSQL 15; yerel geliştirme: SQLite (`ARCHITECTURE.md:11-12`, `DEPLOYMENT.md:16`). CI'da gerçek PostgreSQL 15 servis konteyneri ile migration bütünlüğü kapısı çalışır (`.github/workflows/bys360-ci.yml:38-51,246-249`).
- ORM: Flask-SQLAlchemy / SQLAlchemy 2.0; modeller `app/models/`.
- Migration: Flask-Migrate/Alembic, `migrations/versions/` altında 80 revizyon dosyası (dal ucu sayımı). Dal ucu head'i `x1f3a9c5e7b2`, `down_revision = "w2d8e1f4a6c3"` (`migrations/versions/x1f3a9c5e7b2_adopt_performance_interim_notes_into_alembic.py:66-67`); ardılı yok.
- **Migration head (SOURCE_OF_TRUTH'a göre):** production `x1f3a9c5e7b2`; canlı DB 2026-10-07'de `w2d8e1f4a6c3` → `x1f3a9c5e7b2` (`SOURCE_OF_TRUTH.md:16,38`). Dal ucu ile production arasında migration farkı yok (diff'te `migrations/` yok).
- İki aşamalı temiz kurulum: `flask db upgrade` + `flask runtime-schema provision` (`DEPLOYMENT.md:44-55`; CLI tanımı `app/services/runtime_schema.py:129-149`). Alembic dışındaki "runtime-schema" grupları servis modüllerinde kayıtlıdır (ör. `app/services/performance/feedback_aftercare.py:272`).
- Ham SQL dosyaları: `migrations/sql/` (19 dosya) — kullanım bağlamı bu belgede incelenmedi.
- Şema koruma: başlangıçta beklenen şema sözleşmesi (`app/bootstrap/schema_contract.py`) doğrulanır; hata sayısı `/readyz` ve `/versionz` yanıtında yer alır (`app/routes.py:79-88,244-252`). Otomatik DDL onarımı varsayılan kapalıdır (`AUTO_REPAIR_SCHEMA`, DOC-02 §8).

## 5. Redis — kullanım amacı

Kodda var: Redis **isteğe bağlıdır**; Flask extension nesnesi yoktur.

| Kullanım | Davranış | Kaynak |
|---|---|---|
| Önbellek | `CACHE_BACKEND` = Redis URL varsa `redis`, yoksa `file` | `config.py:617-619` |
| Güvenlik rate-limit sayaçları | `SECURITY_RATE_LIMIT_BACKEND` = Redis varsa `redis`, yoksa `file` | `config.py:625-628` |
| Flask-Limiter deposu | `RATELIMIT_STORAGE_URI` → `REDIS_URL` → `memory://` | `app/security/api_rate_limit.py:14-15` |
| Asenkron iş kuyruğu (RQ) | Redis yoksa veya kapalıysa `inline` çalışır | `app/services/async_job_queue.py` (DOC-02 §6) |
| Sağlık kontrolü | `/health/deep` Redis tanımlı değilse `not_configured` | `app/core/healthcheck.py:30-40` |

**Production'da Redis kullanılıp kullanılmadığı: belgelenmemiş / doğrulanmadı.** `DEPLOYMENT.md:17` yalnız "kullanılıyorsa" der; cutover kayıtları Redis'ten söz etmez. `docker-compose.yml` `redis:7-alpine` içerir ancak bu profil "local/pilot" olarak tanımlıdır (DOC-02 §10).

## 6. Sunum katmanı: Waitress + Windows Scheduled Task

- Tek Waitress giriş noktası `run_server.py`; `APP_ENV` production/staging ise `waitress.serve` çağrılır; `APP_HOST`, `APP_PORT` (varsayılan 8000), `WAITRESS_THREADS` (varsayılan 8) (`DEPLOYMENT.md:101`; `run_server.py:41-63`). `run.py` yalnız yerel geliştirme içindir.
- Süreç yönetimi bir **Windows Service değil, Scheduled Task**'tır: `BYS360 Live Waitress 80`, `AtStartup` tetikleyici, SYSTEM/ServiceAccount, RunLevel Highest, `ExecutionTimeLimit=0`, `RestartCount=3`, `RestartInterval=1 dk`, çıktı `C:\bys360\logs\bys360_live_waitress_80.log` (`scripts/windows/install_bys360_live_waitress_80_task_v1.ps1:38-46,129-157`). Installer varsayılan olarak yalnız plan basar; `-Apply` ve mevcut görev için `-ConfirmReplace` ister (aynı dosya 7-19).
- Not: `docs/current_state/13_...md:119-129` (2026-09-02) repo script'inin `RestartCount`/`ExecutionTimeLimit` geçirmediğini yazar; dal ucundaki script bu parametreleri geçirmektedir (yukarıdaki satırlar). Belge bu açıdan eskimiştir.
- Canlıda doğrulandı: cutover sonrası "Scheduled Task Running" (`SOURCE_OF_TRUTH.md:48`).
- Diğer zamanlanmış görev kurulum script'leri (mail, CIC, yönetici özeti, sosyal içe aktarma) `scripts/windows/install_*.ps1`, `register_*.ps1` altındadır; canlıda kurulu oldukları bu belgede doğrulanmadı.
- Alternatif profil: `Dockerfile` (Gunicorn, `docker/gunicorn.conf.py`) ve `docker-compose.yml` — yerel/pilot (DOC-02 §10).

## 7. Ters vekil (reverse proxy) / TLS

- Kodda var: Werkzeug `ProxyFix`, `PROXY_FIX_ENABLED` ise 1 hop (`app/core/reverse_proxy.py:13-28`); `APP_ENV` production/staging ise varsayılan açık (`config.py:655`).
- Cutover script'i yerel `/healthz`'i `X-Forwarded-Proto: https` başlığıyla, genel uç noktayı `https://` ile kontrol eder (`scripts/windows/cutover_bys360_candidate.ps1` Faz 16–17).
- **Ters vekilin türü (IIS, nginx, yük dengeleyici vb.): belgelenmemiş / doğrulanmadı.** Repo belgeleri yalnız önünde bir TLS sonlandırıcı katman bulunduğuna dair dolaylı kanıttan söz eder ve kimliğini "repo kapsamı dışında" sayar (`docs/current_state/13_...md:21`, `docs/handover/BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md:342-345`). Kod yorumlarında "ters-proxy/IIS zinciri" ifadesi bir olasılık olarak geçer (`app/__init__.py:104`), yapılandırma kanıtı değildir. Repoda yalnız örnek bir nginx yapılandırması vardır (`docker/nginx.conf.example:1-5`, SSL sonlandırma örneği, yer tutucu `server_name`); canlıda kullanıldığına dair kanıt yoktur.

## 8. Mobil: Flutter uygulaması ve PWA

- Flutter projesi: `mobile_flutter/bys360_mobile_native/`, sürüm `2.8.87+87`, SDK `>=3.2.0 <4.0.0`; bağımlılıklar `http`, `go_router`, `flutter_secure_storage`, `webview_flutter`, `firebase_core`, `firebase_messaging` (`pubspec.yaml:4-20`). İstemci `/api/mobile/...` yollarını çağırır (ör. `lib/features/performance/performance_tasks_screen.dart:30`).
- Flutter testleri `mobile_flutter/bys360_mobile_native/test/` altında vardır (7 dosya) ancak hiçbir CI workflow'u Flutter çalıştırmaz (`.github/workflows/` iki dosya, ikisi de Python). Mağaza yayını, Firebase proje yapılandırması: **doğrulanmadı** (DOC-02 §7, §14).
- Release paketi `mobile_flutter/` yolunu yasaklı sayar (`DEPLOYMENT.md:214-216`); mobil derleme/dağıtım süreci **belgelenmemiş**.
- PWA: `pwa_bp` (`app/pwa/routes.py:17`, kayıt `app/__init__.py:93-97`). `app/pwa_blueprint.py` için 2026-08-24 tarihli matris "ölü kod" der (`docs/handover/BYS360_FEATURE_COVERAGE_MATRIX.md` #38).

## 9. Mobil API kimlik doğrulama

Kodda var — **JWT değildir**; `itsdangerous.URLSafeTimedSerializer` imzalı token:

- Access token: salt `bys360-mobile-api-v1`, ömür 24 saat; refresh token: salt `bys360-mobile-refresh-v1`, ömür 30 gün (`app/api/mobile/shared.py:70-73,551-562`).
- Gönderim: `Authorization: Bearer <token>`; `require_mobile_user` dekoratörü (`shared.py:582-607`).
- Uç noktalar: `POST /api/mobile/auth/login`, `POST /api/mobile/auth/refresh`, `GET /api/mobile/me` (`app/api/mobile/domains/auth.py:23-55`).
- İptal: token içine `security_stamp` gömülür; parola sıfırlama stamp'i değiştirince tokenlar geçersizleşir (`shared.py:542-548`). Sunucu tarafı token kara listesi/logout iptali bulunamadı.
- CSRF muafiyeti: `mobile_api_bp` (`app/api/mobile/__init__.py:14-33`).
- Gözlemler (kodda var, düzeltilmedi):
  - `_token_stamp_matches` stamp alanı olmayan tokenları kabul eder (`shared.py:546-548`).
  - `SECRET_KEY` yoksa sabit bir yedek anahtara düşer (`shared.py:90-92`); production/staging'de `SECRET_KEY` zorunlu tutulur (`config.py:524-541`), bu yüzden yedek anahtar yalnız geliştirme senaryosunda devrededir.
  - Mobil login yolunda hesap bazlı başarısız deneme sayacı/kilidi yok; yalnız global Flask-Limiter varsayılanı (`200 per minute`, IP bazlı) uygulanır (`app/api/mobile/services/auth_service.py:30-56`; `app/security/api_rate_limit.py:18-19,66-72`). 2026-09-02 defteri de mobil girişte daha gevşek deneme sınırını not eder (`docs/current_state/19_...md:78`).

## 10. Entegrasyonlar

| Entegrasyon | Durum | Kaynak |
|---|---|---|
| E-posta (SMTP) | Kodda var; `MAIL_SERVER` varsayılanı `smtp.office365.com`; çekirdek `app/services/mail_core.py`, modül postacıları (yönetici özeti, Dosya Merkezi, CIC) | `config.py:713`; DOC-02 §12 |
| AI karar desteği / LLM | Kodda var; `AI_PROVIDER_MODE` varsayılanı `stub` (deterministik, harici LLM yok); `openai_compatible` modu `AI_BASE_URL`+`AI_API_KEY` ile HTTP çağrısı yapar, varsayılan model adı `gpt-4.1-mini`, başarısızlıkta stub'a düşebilir | `config.py:721-727`; `app/services/ai/client.py:161-185` |
| Sanal Asistan (Assistant V2) | Deterministik; harici LLM bağımlılığı yok | `ARCHITECTURE.md:16-18` |
| Production'daki AI modu | **Belgelenmemiş / doğrulanmadı** | — |
| Dosya Merkezi | Kodda var; 19 tablo; ayrı rol matrisi; Dosya Merkezi'ne özel rate limit'ler | `app/file_center/`; `app/security/api_rate_limit.py:22-31`; canlıda "File Center 19/19" (`SOURCE_OF_TRUTH.md:40`) |
| Hava durumu (Open-Meteo, anahtarsız) | Kodda var | `docs/handover/BYS360_FEATURE_COVERAGE_MATRIX.md` #18 |
| Sentry | Opsiyonel; DSN yoksa kapalı | `app/core/monitoring.py:27-75` |
| Firebase (push) | Yalnız Flutter bağımlılığı; sunucu tarafı `push_notifications.py` domain modülü var; canlı yapılandırma doğrulanmadı | `pubspec.yaml`; `app/api/mobile/domains/push_notifications.py` |

## 11. Güvenlik altyapısı (özet)

CSRFProtect (web), `security_stamp` tabanlı oturum geçersizleştirme (`app/__init__.py:45-58`), oturum ömrü varsayılan 30 dk (`config.py:607`), güvenlik başlıkları (`app/bootstrap/response_hardening.py`), başlangıç güvenlik denetimi (`app/security/startup_audit.py:41-43`). Yetkilendirme ayrıntıları: `04_ROL_VE_YETKI_MIMARISI.md`.

## 12. Açık noktalar (bu belge kapsamında)

1. Ters vekil türü ve TLS yapılandırması — belgelenmemiş.
2. Production'da Redis, AI sağlayıcı modu ve SMTP sunucusu — doğrulanmadı.
3. Flutter derleme/dağıtım ve CI — belgelenmemiş, CI dışı.
4. Dal ucundaki 18 PR (çoğu yetki daraltması) production'da değil; canlı davranış production SHA'ya göre değerlendirilmelidir.
5. Opsiyonel modül kayıtlarının sessiz başarısızlığa açık olması (§2).
