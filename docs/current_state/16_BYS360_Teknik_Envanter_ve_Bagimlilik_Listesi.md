Doküman Adı: BYS360 Teknik Envanter ve Bağımlılık Listesi
Doküman Türü: Teknik / Envanter
Kurum: Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı
Sürüm: Current-State 1.0
Tarih: 2026-09-02
Durum: Puantaj Öncesi Mevcut Durum Dokümanı
Kaynak Kod Referansı: 873e6d3348e644c5384a33a99c517600a3346cfd
Uzak CI Referansı: 7d73ff4d468cad11d78d2339ba770f70b5ec0baf (uzaktan doğrulanmış tarihsel/mevcut kontrol noktası, yerel HEAD değil)
Son Güncelleme: 2026-09-02

---

## 1. Dil, çalışma zamanı, çerçeve

| Bileşen | Değer | Kanıt |
|---|---|---|
| Programlama dili | Python 3.12 (sabit) | `CODE_VERIFIED` — `pyproject.toml`: `python_version = "3.12"`; `Dockerfile`: `FROM python:3.12-slim` |
| Web çerçevesi | Flask 3.1.3 | `CODE_VERIFIED` — `requirements.txt` |
| Şablon motoru | Jinja2 (Flask'a gömülü) | `CODE_VERIFIED` — `app/templates/` |
| ORM | SQLAlchemy 2.0.36 (Flask-SQLAlchemy 3.1.1 üzerinden) | `CODE_VERIFIED` |
| Migration çerçevesi | Flask-Migrate 4.0.7 (Alembic üzerine) | `CODE_VERIFIED` — Alembic sürümü doğrudan sabitlenmemiş, bkz. DOC-10 §10 |
| Kimlik doğrulama | Flask-Login 0.6.3 | `CODE_VERIFIED` |
| Form/CSRF | Flask-WTF 1.2.1 (`CSRFProtect`), WTForms 3.1.2 | `CODE_VERIFIED` |

## 2. `requirements.txt` — doğrudan üretim bağımlılıkları (tam liste, 24 paket)

| Paket | Sürüm |
|---|---|
| Flask | 3.1.3 |
| Flask-Login | 0.6.3 |
| Flask-SQLAlchemy | 3.1.1 |
| Flask-WTF | 1.2.1 |
| Flask-Migrate | 4.0.7 |
| SQLAlchemy | 2.0.36 |
| psycopg2-binary | 2.9.9 |
| python-dotenv | 1.2.2 |
| WTForms | 3.1.2 |
| email-validator | 2.2.0 |
| openpyxl | 3.1.5 |
| pandas | 2.2.3 |
| waitress | 3.0.1 |
| XlsxWriter | 3.2.0 |
| Pillow | 13.0.0 |
| cryptography | 50.0.0 |
| reportlab | 4.4.10 |
| gunicorn | 25.3.0 |
| gevent | 24.11.1 |
| sentry-sdk[flask] | 2.20.0 |
| redis | 5.0.8 |
| rq | 2.3.3 |
| prometheus-client | 0.20.0 |
| Flask-Limiter | 3.5.0 |

(`CODE_VERIFIED` — `requirements.txt` bu oturumda tam okundu.)

## 3. Bağımlılık kilitleme (lock) modeli — üç ayrı katman, biri güncel değil

Bu worktree'de üç ayrı bağımlılık dosyası/kaynağı bulunmaktadır ve **ikisi güncel HEAD'e ait değildir**:

1. **`requirements.txt`** — doğrudan bağımlılıklar, gevşek olmayan `==` sabitlemeli (yukarıdaki tablo). Bu dosya güncel HEAD `873e6d3`'te mevcuttur ve doğrudan okunmuştur (`CODE_VERIFIED`).
2. **`requirements.lock`** (59 paket — 24 doğrudan + 35 geçişli) — pip'in hash-doğrulamalı (`--require-hashes` uyumlu) tam düz kilidi. **Güncelleme (21 Ekim 2026):** kilit artık `scripts/release/generate_bys360_requirements_lock.py` ile deterministik olarak üretilir; başlıkta tarih/SHA yerine makine okunur `# bys360-lock: packages=59 direct=24 transitive=35` satırı vardır. Bu yenilemede yalnız güvenlik sürümleri değişti: Pillow 13.0.0, urllib3 2.8.0, Werkzeug 3.1.9, certifi 2026.10.19. CI kilidi Linux'ta pip-audit ile (sabitlenmiş sürümler) ve Windows'ta yeniden üretim, wheelhouse hash ve `--require-hashes` kurulumu ile denetler.
3. **`build/wheelhouse/`** — 59 önceden indirilmiş `.whl` dosyası (çevrimdışı kurulum için, CPython 3.12 / win_amd64 hedefli); izlenen bir dosya değildir, `scripts/release/build_bys360_wheelhouse.py` ile kilitten üretilir. Canlıdaki release `cdae2795`'in wheelhouse kimliği (`c372cc25…`) eski kilide aittir; 21 Ekim kilidiyle üretilecek wheelhouse'un kimliği farklı olacaktır (yerel doğrulamada `3c3acbd8…`).
4. **`requirements-dev.txt`** (CI/kalite araç zinciri, `requirements.txt`'ten ayrı tutulur, kendi başlığında bunu açıkça belirtir): `mypy==2.3.0`, `pip-audit==2.10.1`, `pytest==9.0.3`, `pytest-cov==7.1.0`, `ruff==0.16.0` — bu dosya **güncel** görünmektedir, eski SHA referansı taşımaz (`CODE_VERIFIED`).

**Açık teknik bulgu (21 Ekim 2026 güncellemesi):** `requirements.lock` güncel `requirements.txt`'e karşı yeniden üretildi ve CI'da denetleniyor. Yeni kilitle FULL paket/wheelhouse henüz üretilmedi ve canlıya alınmadı; bu, ayrı release kabul sürecinin işidir. (`requirements.txt`'in kendisi iki SHA arasında değişmiş olabilir ya da olmayabilir — bu oturumda `git log -p requirements.txt` ile tarihsel fark analizi yapılmadı, `NOT_YET_FINALIZED`.)

## 4. Veritabanı ve önbellek

| Bileşen | Değer | Kanıt |
|---|---|---|
| Canlı veritabanı | PostgreSQL 15, Windows servis adı `postgresql-x64-15` | `DOCUMENTATION_DERIVED` — bu servis adı yalnızca eski/tarihsel, bu fazın kapsamı dışındaki `deploy_bys360_ec4e56b_production_v1..v4.ps1` script'lerinde geçer; güncel `prepare_bys360_candidate.ps1`/`cutover_bys360_candidate.ps1` bu kontrolü içermez (bkz. DOC-03 §3) |
| Yerel/test/CI varsayılanı | SQLite (`DATABASE_URL` boşsa `sqlite:///:memory:`) | `CODE_VERIFIED` — `config.py:544` |
| Yerel kalıcı geliştirme örneği | `sqlite:///instance/bys360_local_dev.sqlite3` | `CODE_VERIFIED` — `.env.example` |
| Docker/pilot profili DB imajı | `postgres:15-alpine` | `CODE_VERIFIED` — `docker-compose.yml` |
| Önbellek/kuyruk | Redis 5.0.8 + RQ 2.3.3, **isteğe bağlı** (`REDIS_URL`/`CACHE_REDIS_URL` tanımlı değilse dosya/JSON veya bellek içi yedek moda düşer) | `CODE_VERIFIED` — bkz. DOC-02 §6 |
| Docker/pilot profili cache imajı | `redis:7-alpine` | `CODE_VERIFIED` — `docker-compose.yml` |

## 5. Uygulama sunucusu, süreç yönetimi, portlar

| Ortam | Sunucu | Port | Süreç yönetimi | Kanıt |
|---|---|---|---|---|
| Windows canlı | Waitress 3.0.1 (`run_server.py` giriş noktası) | **80** (varsayılan `-Port` parametresi) | Windows Scheduled Task, görev adı **"BYS360 Live Waitress 80"**, en yüksek çalışma seviyesiyle (ayrıcalıklı port 80'e bağlanmak için) | `SCRIPT_VERIFIED` — `scripts/windows/install_bys360_live_waitress_80_task_v1.ps1:39-40,133,140` |
| Yerel geliştirme | Flask geliştirme sunucusu / Waitress | `APP_PORT` (varsayılan `8000`), `APP_HOST` varsayılan `127.0.0.1` | Elle / IDE | `CODE_VERIFIED` — `.env.example` |
| Docker/konteyner | Gunicorn 25.3.0 (`gevent` worker sınıfı bağımlılığı mevcut) + `docker/gunicorn.conf.py` | `PORT` (varsayılan `8000`, dışa `BYS360_HOST_PORT` ile eşlenir) | Docker Compose / container orkestrasyon | `CODE_VERIFIED` — `Dockerfile`, `docker-compose.yml` |

`GUNICORN_BIND` ortam değişkeni `APP_HOST:APP_PORT` biçiminde otomatik türetilir (`config.py:663`, `CODE_VERIFIED`).

## 6. Windows bileşenleri ve PowerShell

- İşletim sistemi: Windows (üretim sunucusu), Windows 11 (bu geliştirme worktree'sinin çalıştığı istasyon — ortam bilgisinden, kurumsal sunucunun kendisi ayrı doğrulanmalı).
- PowerShell tabanlı operasyon script ekosistemi: `scripts/windows/` altında 27+ `.ps1` dosyası (aday hazırlama, cutover, rollback, Scheduled Task kurulumları, e-posta zamanlayıcı görevleri, kalite/onarım scriptleri) (`CODE_VERIFIED` — dizin sayımı).
- Windows Scheduled Task, kurumun canlı süreç yönetim modelidir (systemd/Docker orkestrasyonu değil) — bkz. §5.

## 7. Flutter / mobil uygulama durumu

| Alan | Değer | Kanıt |
|---|---|---|
| Dizin | `mobile_flutter/bys360_mobile_native/` | `CODE_VERIFIED` |
| Uygulama adı | `bys360_mobile_native` — "BYS360 Mobile V2 gerçek native Flutter uygulaması" | `CODE_VERIFIED` — `pubspec.yaml` |
| Sürüm | `2.8.87+87` | `CODE_VERIFIED` |
| Flutter/Dart SDK gereksinimi | `>=3.2.0 <4.0.0` (Dart SDK) | `CODE_VERIFIED` |
| Temel bağımlılıklar | `http`, `shared_preferences`, `webview_flutter`, `go_router`, `provider`, `firebase_core`, `firebase_messaging`, `flutter_secure_storage`, `cupertino_icons` | `CODE_VERIFIED` |
| Platform klasörleri | `android/`, `ios/`, `web/`, `keystores/` mevcut | `CODE_VERIFIED` — dizin listesi |
| Sunucu tarafı sözleşme testi | `tests/mobile/test_mobile_domain_contract_p2a.py` | `CODE_VERIFIED` |
| Mağaza yayın durumu (App Store/Play Store) | Bu incelemenin kapsamında doğrulanamadı | `NOT_YET_FINALIZED` |

## 8. Git, sürüm kontrolü, CI

| Alan | Değer | Kanıt |
|---|---|---|
| Sürüm kontrolü | Git | `CODE_VERIFIED` |
| Mevcut dal | `phase5-critical-lint-clean-v1` | `CODE_VERIFIED` — `git branch --show-current` |
| Güncel HEAD | `873e6d3348e644c5384a33a99c517600a3346cfd` | `CODE_VERIFIED` |
| CI iş akışları | `.github/workflows/bys360-ci.yml`, `.github/workflows/bys360-score100-quality-gate-v1.yml` | `CODE_VERIFIED` — dosyalar mevcut, içerik bu oturumda ayrıntılı yeniden çalıştırılmadı |
| CI ortamı (eski handover belgesine göre) | `ubuntu-latest`, Python 3.12, `postgres:15` servis konteyneri, `timeout-minutes: 45` | `DOCUMENTATION_DERIVED` — `docs/handover/BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md:551`, bu oturumda iş akışı dosyasının tam içeriğiyle satır satır karşılaştırılmadı |

## 9. Test çerçevesi ve kalite araçları

| Alan | Değer | Kanıt |
|---|---|---|
| Test çerçevesi | pytest 9.0.3 (`requirements-dev.txt`), `pytest.ini` içinde `minversion = 8.0` | `CODE_VERIFIED` |
| Test dosya sayısı | `tests/` altında 384 `test_*.py` dosyası | `CODE_VERIFIED` — bu oturumda sayıldı (**dosya sayısıdır, ayrı test fonksiyon/senaryo sayısı değildir**; diğer raporlarda bildirilen "5684 passed" rakamıyla karıştırılmamalıdır) |
| Test işaretleyicileri (markers) | `ci_safe`, `legacy_integration`, `live`, `mobile`, `realdb`, `slow`, `source_smoke`, `uat` | `CODE_VERIFIED` — `pytest.ini` |
| Kapsam (coverage) aracı | `pytest-cov` 7.1.0, `[tool.coverage.run]`/`[tool.coverage.report]` `pyproject.toml`'da tanımlı | `CODE_VERIFIED` |
| Statik tip kontrolü | mypy 2.3.0, `[tool.mypy]` + çok sayıda `[[tool.mypy.overrides]]` bloğu `pyproject.toml`'da | `CODE_VERIFIED` |
| Lint/format | ruff 0.16.0 (`[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.lint.isort]`, `[tool.ruff.format]`), ayrıca `black`/`isort` bölümleri de `pyproject.toml`'da tanımlı (araç seçimi netleştirilmemiş — hem black/isort hem ruff format bölümleri bir arada bulunuyor) | `CODE_VERIFIED` |
| Bağımlılık zafiyeti taraması | `pip-audit` 2.10.1 | `CODE_VERIFIED` |

## 10. Migration/şema araçları

Bkz. DOC-10 için ayrıntı. Özet: Flask-Migrate 4.0.7 (Alembic), `migrations/versions/` altında 77 dosya, `alembic.ini` repo kökünde, `migrations/env.py` Flask uygulama bağlamından motor/URL alır.

## 11. Önemli dizinler (repo kökü)

| Dizin/Dosya | İşlev |
|---|---|
| `app/` | Ana uygulama kaynak kodu (973 Python dosyası) |
| `migrations/` | Alembic migration zinciri |
| `tests/` | Test paketi (384 test dosyası) |
| `scripts/windows/` | PowerShell operasyon/deploy/kalite scriptleri |
| `scripts/release/` | Release paketleme scriptleri (`build_bys360_safe_release.py`) |
| `scripts/quality/` | Kalite kapıları (coverage ratchet vb.) |
| `docs/handover/` | Devir/operasyon belgeleri (bu current-state fazının temeli) |
| `docs/current_state/` | Bu fazda üretilen mevcut durum belgeleri |
| `build/wheelhouse/` | Çevrimdışı kurulum için önceden indirilmiş `.whl` dosyaları (eski SHA'ya ait, bkz. §3) |
| `mobile_flutter/` | Flutter native mobil uygulama kaynak kodu |
| `docker/` | `entrypoint.sh`, `gunicorn.conf.py` |
| `instance/` | Çalışma zamanı örnek verisi (`portal` alt klasörü tespit edildi) |
| `logs/` | Uygulama log dosyaları |
| `data/`, `seeds/` | Örnek/başlangıç veri dosyaları (`fake_seed.py`, `fake_users_seed.csv`, `sp1a_competencies.json`) |
| `sql/` | Elle yazılmış SQL onarım/düzeltme betikleri (örn. `2026-04-15_comm_role_matrix_repair.sql`) |
| `reports/` | Kalite/denetim/executive rapor çıktıları |
| `config.py`, `alembic.ini`, `pytest.ini`, `pyproject.toml` | Kök yapılandırma dosyaları |
| `wsgi.py`, `run.py`, `run_server.py` | Uygulama giriş noktaları (WSGI/Waitress) |

## 11a. Görsel kimlik dosyaları (özet — ayrıntı DOC-20'de)

Ana kurumsal renk (`#8B0000`, `app/static/css/base_logo_refresh.css` içindeki `--catab-red`/`--bys-hero-accent` değişkenleri), filigran görseli (`app/static/img/ay_yildiz.png`, `app/static/css/app.css` üzerinden %6 opaklıkla kullanılır) ve ortak yazı tipi yığını (`Segoe UI, Arial, sans-serif`, `app/static/css/app.css:17`) `CODE_VERIFIED` olarak doğrulanmıştır. Tam tasarım standardı: `docs/current_state/20_BYS360_Kurumsal_Tasarim_ve_Arayuz_Standardi.md`.

## 12. Yapılandırma dosyaları ve ortam değişkenleri (özet)

- `.env.example` repoda tutulur, gerçek gizli bilgi içermez (`CODE_VERIFIED`, dosya başlığı bunu açıkça belirtir).
- `config.py`, `python-dotenv` yoksa bile çalışmaya devam eden minimal bir `.env` okuyucu içerir (bağımlılık eksikliğinde uygulamanın düşmemesi için savunma amaçlı) (`CODE_VERIFIED`, satır 9-35).
- Öne çıkan ortam değişkeni grupları (`.env.example`'dan, `CODE_VERIFIED`): `DATABASE_URL`; `FILE_CENTER_*` (depolama kökü, güvenlik taraması, ClamAV entegrasyonu, hız sınırları); `MAIL_SERVER`/`MAIL_PORT`(varsayılan 25)/`MAIL_USERNAME`/`MAIL_PASSWORD`/`MAIL_DEFAULT_SENDER`/`MAIL_USE_TLS`/`MAIL_USE_SSL`; `APP_BASE_URL`, `APP_ENV`, `APP_HOST`, `APP_PORT`; `BYS360_DEPLOYMENT_MODE`; `BYS360_EXECUTIVE_SUMMARY_RECIPIENTS`; `BYS360_FEEDBACK_FOLLOWUP_SCHEDULER*`; `BYS360_INSTAGRAM_*` (sosyal medya otomatik içe aktarma entegrasyonu — canlı kullanım durumu bu incelemede doğrulanmadı, `NOT_YET_FINALIZED`); `RATELIMIT_STORAGE_URI`; `ENABLE_API_RATE_LIMIT`.
- `AUTO_REPAIR_SCHEMA`, `STRICT_SCHEMA_CHECK`, `BYS_SKIP_SCHEMA_GUARD`, `BYS_FORCE_SCHEMA_GUARD` — şema koruma davranış anahtarları (bkz. DOC-10 §4).

## 13. Dış servisler

| Servis | Kullanım amacı | Durum |
|---|---|---|
| SMTP sunucusu (kurum e-posta altyapısı) | Performans hatırlatmaları, yönetici özeti dağıtımı, dosya merkezi bildirimleri, kurumsal bilgi merkezi (CIC) e-postaları, anket/hatırlatma e-postaları | Yapılandırma noktaları (`MAIL_SERVER`/`SMTP_HOST` vb.) `CODE_VERIFIED`; gerçek canlı SMTP sunucu adı/sağlayıcısı bu incelemede doğrulanmadı — `NOT_YET_FINALIZED` |
| Redis | Opsiyonel önbellek/hız sınırlama/asenkron kuyruk | `CODE_VERIFIED` — isteğe bağlı, bkz. §4 |
| Sentry | Opsiyonel hata izleme (`sentry-sdk[flask]` 2.20.0) | `CODE_VERIFIED` bağımlılık düzeyinde; canlı DSN yapılandırması bu incelemede doğrulanmadı — `NOT_YET_FINALIZED` |
| Firebase (Core + Messaging) | Yalnızca mobil uygulama tarafında (push bildirim altyapısı) | `CODE_VERIFIED` bağımlılık düzeyinde; canlı proje yapılandırması doğrulanmadı — `NOT_YET_FINALIZED` |
| Instagram API entegrasyonu | Sosyal medya otomatik içe aktarma (`BYS360_INSTAGRAM_*` env değişkenleri, `scripts/windows/install_bys360_social_auto_import_v3b2_task.ps1`) | `SCRIPT_VERIFIED` yapılandırma noktası düzeyinde; fiili kullanım/aktiflik durumu doğrulanmadı — `NOT_YET_FINALIZED` |

## 14. Runtime hesapları / kullanıcı bağlamı

Windows canlı görev, "Highest run level" (yükseltilmiş yetki) ile çalışacak şekilde kaydedilir çünkü ayrıcalıklı port 80'e bağlanması gerekir (`SCRIPT_VERIFIED` — `install_bys360_live_waitress_80_task_v1.ps1:133`). Docker imajında ise uygulama **ayrıcalıksız** bir kullanıcı olarak çalışır: `adduser --disabled-password --uid 10001 bys360`, `USER bys360` (`CODE_VERIFIED` — `Dockerfile:28,32`). PostgreSQL uygulama rolünün ayrıcalıkları kasıtlı olarak sınırlıdır — `CREATE DATABASE`/`DROP DATABASE` yapamaz (yalnızca admin rolü yapabilir), şema koruma motoru bu nedenle sahiplik/yetki uyuşmazlıklarını güvenli biçimde atlar (bkz. DOC-10 §4b) (`DOCUMENTATION_DERIVED` + `CODE_VERIFIED` çapraz doğrulama).

---

## Ek — Bu belgede tespit edilen açık teknik bulgular

1. `requirements.lock` 21 Ekim 2026'da güncel `requirements.txt`'e karşı yeniden üretildi (güvenlik sürümleri); yeni kilitle wheelhouse/FULL paket henüz üretilmedi ve canlıya alınmadı — final release kabulünde ele alınmalıdır.
2. `pyproject.toml` içinde hem `[tool.black]`/`[tool.isort]` hem de `[tool.ruff.format]`/`[tool.ruff.lint.isort]` bölümleri bir arada tanımlıdır; fiilen hangi formatlayıcının CI'da otoriter kabul edildiği bu incelemenin kapsamında netleştirilmedi (`requirements-dev.txt` yalnızca `ruff`'ı listeler, `black` içermez — bu, ruff'ın fiilen kullanılan araç olduğuna işaret eder ama kesin değildir).
3. Canlı SMTP sunucusu, Sentry DSN, Firebase proje yapılandırması ve Instagram entegrasyonunun fiili aktiflik durumu bu incelemede doğrulanamadı — hepsi `NOT_YET_FINALIZED` olarak işaretlenmiştir.
