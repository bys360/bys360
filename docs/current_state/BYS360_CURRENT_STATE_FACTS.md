# BYS360 — Mevcut Durum Kanonik Olgu Defteri (Canonical Facts Ledger)

Doküman Adı: BYS360 Mevcut Durum Kanonik Olgu Defteri
Doküman Türü: İç / Teknik — Tüm current_state belgelerinin kaynağı
Kurum: Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı
Sürüm: Current-State 1.0
Tarih: 2026-09-02
Durum: Puantaj Öncesi Mevcut Durum Dokümanı — NİHAİ (v2, teknik incelemeler + çapraz doğrulama sonrası)
Kaynak Kod Referansı: 873e6d3348e644c5384a33a99c517600a3346cfd
Uzak CI Referansı: 7d73ff4d468cad11d78d2339ba770f70b5ec0baf (uzaktan doğrulanmış tarihsel/mevcut kontrol noktası — yerel HEAD DEĞİL)
Son Güncelleme: 2026-09-02 (v2 — final birleştirme)

---

## Kanıt sınıflandırma anahtarı

`CODE_VERIFIED` (kod doğrudan okundu/çalıştırıldı) · `SCRIPT_VERIFIED` (release/ops script'i okundu) ·
`TEST_VERIFIED` (test/otomasyon çalıştırılarak doğrulandı) · `DOCUMENTATION_DERIVED` (mevcut belgeden alındı, bağımsız doğrulanmadı) ·
`PRODUCTION_HISTORICAL` (geçmiş/operatör beyanına dayalı) · `PLANNED_FUTURE` (henüz gerçekleşmemiş, planlanan).

---

## Kimlik ve Kapsam

| Alan | Değer | Kanıt |
|---|---|---|
| PROJECT_NAME | BYS360 — Bütünleşik Yönetim Sistemi 360 | DOCUMENTATION_DERIVED |
| INSTITUTION | Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı | DOCUMENTATION_DERIVED (`reports/executive/BYS360_Kurumsal_Rapor_Kaynak.md`) |
| CURRENT_LOCAL_SHA | `873e6d3348e644c5384a33a99c517600a3346cfd` | CODE_VERIFIED (`git rev-parse HEAD`) |
| REMOTE_VERIFIED_SHA | `7d73ff4d468cad11d78d2339ba770f70b5ec0baf` | PRODUCTION_HISTORICAL (kullanıcı beyanı; bu incelemede bağımsız doğrulanmadı, yerel HEAD ile birebir aynı değil) |
| CURRENT_BRANCH | `phase5-critical-lint-clean-v1` | CODE_VERIFIED |
| WORKTREE | `C:\bys360\worktrees\phase5-critical-lint-clean` | CODE_VERIFIED |
| WORKING_TREE_STATE | HEAD'de kaynak kod değişikliği yok; yalnızca izlenmeyen (untracked) rapor/script artefaktları + bu fazın ürettiği `docs/current_state/*` mevcut | CODE_VERIFIED (`git status --short`) |

**Üçüncü SHA — belge tutarsızlığı (kritik bulgu):** `docs/handover/BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md` ve `BYS360_FEATURE_COVERAGE_MATRIX.md`, kendi "Production Source SHA"sı olarak **`cb2e57c5d1829ea743c696ae78595a20755f3f07`** (2026-08-24) taşır ve `docs/handover/README.md` bu dosyayı hâlâ "CURRENT" olarak işaretler. Yani şu anda **üç farklı SHA** "güncel/aktif" olarak dolaşımdadır: yerel HEAD (`873e6d3`), uzak doğrulanmış kontrol noktası (`7d73ff4`) ve `docs/handover/`'ın kendi kanonik SHA'sı (`cb2e57c`). Bu current-state fazı bu farkı **çözmez**, yalnızca açıkça raporlar (bkz. DOC-07 §13). Final dokümantasyon yenilemesinde tek bir kanonik "aktif SHA" belirlenmelidir.

**İzlenmeyen (untracked) artefaktlar:** `AGENT2_REPORT.md`, `AGENT3_REPORT.md`, `reports/executive/BYS360_Kurumsal_Rapor_Kaynak.md`, `scripts/windows/deploy_bys360_ec4e56b_production_v1..v4.ps1` — bunlar **dördüncü bir SHA'ya** (`ec4e56b`) ait, bu current-state fazından tamamen bağımsız, ayrı bir "production deployment rebuild" sürecinin kalıntılarıdır. Silinmemiş/taşınmamıştır. `Kurumsal_Rapor_Kaynak.md` üslup referansı olarak kullanılmıştır ancak içindeki rakamlar (test ~4.600, coverage %18,85) güncel değildir.

---

## Kurumsal Konumlandırma — KYS İlişkisi (kullanıcı düzeltmesi, bu fazda eklendi)

| Alan | Değer | Kanıt |
|---|---|---|
| KYS_SYSTEM_TYPE | Kurumun hâlihazırda kullandığı **mevcut kurumsal ERP / Kurumsal Yönetim Sistemi**. **KYS "Kalite Yönetim Sistemi" DEĞİLDİR** — bu, önceki belge taslaklarında (DOC-01, DOC-17) hatalı biçimde kullanılmış bir açılımdı, kullanıcı tarafından düzeltilmiştir | PRODUCTION_HISTORICAL (kullanıcı beyanı — kurumsal bir olgu, kod/repo içinden doğrulanabilir değildir) |
| BYS360_KYS_RELATION | **Tamamlayıcı, ikame edici değil.** BYS360, KYS'nin yerine geçmek üzere geliştirilmemiştir; KYS'de bulunmayan veya kurumun ihtiyacına özel olarak BYS360 içinde ele alınan performans değerlendirme, personel iş akışları, iç iletişim, anket/geri bildirim, destek ve karar destek gibi operasyonel yönetim süreçlerini ele alır | Kullanıcı beyanı (kesin talimat) |
| KYS_CAPABILITY_CLAIMS_POLICY | BYS360, KYS'nin herhangi bir yeteneği yerine getiremediği yönünde bir iddiada bulunmaz — yalnızca kurumun bugün BYS360 üzerinden yürüttüğü süreçleri tarif eder; desteklenmeyen rekabetçi/karşılaştırmalı ifadeler kullanılmaz | Kullanıcı talimatı |

**Düzeltme kaydı:** Bu fazdan önce DOC-01 §3 ve DOC-17'nin açılış paragrafı, KYS'yi hatalı biçimde "Kalite Yönetim Sistemi" olarak tanımlıyor ve BYS360'ı bu (var olmayan) sisteme göre konumlandırıyordu. Kullanıcının doğrudan, yetkili düzeltmesi üzerine her iki belge de yukarıdaki kanonik tanıma göre güncellenmiştir. Repo genelinde tarama, bu iki belge dışında KYS'ye atıfta bulunan başka hiçbir current-state belgesi bulunmadığını doğrulamıştır.

---

## Uygulama Yığını (Application Stack)

| Alan | Değer | Kanıt |
|---|---|---|
| APPLICATION_STACK | Tek bir Flask uygulaması; "tek omurga (`main_bp`) + modüler route dosyası ekleme" mimarisi (klasik çoklu-Blueprint modeli değil) | CODE_VERIFIED (`app/route_registry.py`, `app/bootstrap/route_bootstrap.py`) |
| PYTHON_VERSION | 3.12 (pin) | CODE_VERIFIED (`pyproject.toml`) |
| FLASK_VERSION | 3.1.3 | CODE_VERIFIED (`requirements.txt`) |
| DİĞER ÇEKİRDEK BAĞIMLILIKLAR | Flask-Login 0.6.3, Flask-SQLAlchemy 3.1.1, Flask-WTF 1.2.1, Flask-Migrate 4.0.7, SQLAlchemy 2.0.36, psycopg2-binary 2.9.9, waitress 3.0.1, redis 5.0.8, rq 2.3.3, Flask-Limiter 3.5.0, sentry-sdk 2.20.0, gunicorn 25.3.0 | CODE_VERIFIED (`requirements.txt`, 24 doğrudan paket) |
| DATABASE | PostgreSQL 15 (canlı), SQLite (yerel/test/CI varsayılanı — `DATABASE_URL` boşsa bellek-içi SQLite'a düşer) | CODE_VERIFIED (`config.py:544`) |
| DATABASE_VERSION | PostgreSQL 15 | DOCUMENTATION_DERIVED (`docs/handover/LIVE_INSTALLATION.md`) — **düzeltme:** `postgresql-x64-15` Windows servis-adı kontrolü yalnızca eski/tarihsel `deploy_bys360_ec4e56b_production_v*.ps1` script'lerinde vardır; güncel `prepare_bys360_candidate.ps1`/`cutover_bys360_candidate.ps1` bu kontrolü **içermez**, yalnızca istemci ikili dosyalarının (`pg_dump.exe` vb.) varlığını doğrular (SCRIPT_VERIFIED, negatif grep — bağımsız olarak yeniden doğrulandı) |
| REDIS_USAGE | **Mimari olarak isteğe bağlı.** `REDIS_URL`/`CACHE_REDIS_URL` tanımlı değilse sistem dosya/JSON tabanlı veya bellek-içi yedek moda düşer; açılışı engellemez. 5 dosyada doğrudan kullanım tespit edildi (`app/core/healthcheck.py`, `async_job_queue.py`, `shared_cache_store.py`, `runtime_cache.py`, `app/security/rate_limit_store.py`) | CODE_VERIFIED (DOC-02 §6 — önceki DOCUMENTATION_DERIVED durumundan yükseltildi) |
| WINDOWS_RUNTIME_MODEL | Waitress WSGI, Windows Scheduled Task (`AtStartup`, SYSTEM/Highest) | CODE_VERIFIED + SCRIPT_VERIFIED |
| DEPLOYMENT_PROFILES | İki ayrı profil bir arada: (1) Windows/Waitress — fiili canlı model; (2) Docker/Gunicorn — `docker-compose.yml` yorumunda açıkça "Local/pilot compose profile" olarak tanımlı, üretim değil | CODE_VERIFIED |
| APPLICATION_SERVER | Waitress 3.0.1 (canlı), Gunicorn 25.3.0 + gevent (Docker/pilot) | CODE_VERIFIED |
| SCHEDULED_TASK_NAME | "BYS360 Live Waitress 80" | SCRIPT_VERIFIED (`install_bys360_live_waitress_80_task_v1.ps1:40`) |
| HEALTH_ENDPOINTS | `/healthz` (her zaman 200), `/readyz` (200/ready veya 503/degraded), `/versionz` (`source_sha`/`migration_head` yalnızca loopback'e) — tümü `main_bp`, giriş gerektirmez | CODE_VERIFIED (`app/routes.py:72-74,77-86,176-202,279-281`) |
| LIVE_DOMAIN | `bys360.canakkaletarihialan.gov.tr` (script varsayılan parametresi) | SCRIPT_VERIFIED (`cutover_bys360_candidate.ps1:131`, varsayılan değer) — DNS'te fiilen bu şekilde çözüldüğü bu incelemeden **doğrulanamaz**, NOT_YET_FINALIZED olarak kalır |
| PRODUCTION_HOSTNAME | `CATAB-BYS360` | SCRIPT_VERIFIED (`prepare_bys360_candidate.ps1:161`, `cutover_bys360_candidate.ps1:111`, `$ExpectedHostName` — tam eşleşme zorunlu) |
| MODULE_LIST | `app/` altında 973 Python dosyası, 20+ üst düzey modül paketi | CODE_VERIFIED — tam envanter DOC-12'de |
| PUANTAJ_IN_CODEBASE | **Bulunmadı.** `app/` genelinde "puantaj" yalnızca sanal asistanın arama anahtar kelimesi olarak (izin/devamsızlık ekranına eşanlamlı yönlendirme) geçer; "timesheet" hiç geçmez. Var olan `LeaveBalance`/`PersonnelLeave`/`AttendanceException`/`DelegationAssignment` modelleri yalnızca izin/devamsızlık **istisnası** takibidir, bağımsız bir mesai/vardiya sistemi değildir | CODE_VERIFIED (DOC-12 §11 — kapsamlı grep) |

---

## Veritabanı ve Migration

| Alan | Değer | Kanıt |
|---|---|---|
| DATABASE_MIGRATION_MODEL | Flask-Migrate / Alembic, tek zincir, merge-revizyonlu | CODE_VERIFIED |
| CURRENT_LOCAL_ALEMBIC_HEAD | `v1a2d3e4f5b6` (tek head) | CODE_VERIFIED/TEST_VERIFIED — bu incelemede `flask db heads` fiilen çalıştırıldı, iki kez teyit edildi |
| ALEMBIC_HEAD_CONTINUITY | `v1a2d3e4f5b6`'nın `down_revision`'ı doğrudan `c51c29032d4f`'dir — eski SHA `ec4e56b`'de doğrulanmış head'in **tek, doğrudan sonraki adımı**; zincir dallanmamış/kopmamış | CODE_VERIFIED (dosya satır 58-59) |
| MIGRATION_FILE_COUNT | 77 `.py` dosyası (eski SHA `cb2e57c` anında 74 idi — 3 yeni migration, doğal ilerleme) | CODE_VERIFIED |
| FILE_CENTER_TABLES | 19 tablo, Alembic'e migration `10858a18e9ac` ile "adopt" edilmiş | CODE_VERIFIED (`__tablename__` sayımı, bağımsız olarak iki kez doğrulandı) |
| SCHEMA_GUARD_MODEL | İki ayrı mekanizma: (a) boot-time salt-okunur sözleşme doğrulaması (`schema_contract.py`, yalnız PostgreSQL + `STRICT_SCHEMA_CHECK`'te), (b) isteğe bağlı, varsayılan-kapalı DDL onarım motoru (`schema_guard_engine.py`, yalnız `AUTO_REPAIR_SCHEMA=true` ile, SQLite'ta hiç çalışmaz) | CODE_VERIFIED (DOC-10 §4) |
| PRODUCTION_KNOWN_REVISION | NOT_YET_FINALIZED / REQUIRES_FINAL_REFRESH | Canlı sunucuya doğrudan erişim yok; eski handover belgesindeki `e0efcd07abf7` farklı/daha eski bir kontrol noktasına (SHA `cb2e57c`) ait, güncel referans değil |

---

## Test / Kalite Kanıtı

| Alan | Değer | Kanıt |
|---|---|---|
| LOCAL_TEST_RESULT (TRUE FULL) | 5684 passed, 4 skipped, 0 failed, 0 errors | PRODUCTION_HISTORICAL (önceki tur) — bu incelemede yeniden çalıştırılmadı |
| CANONICAL_STEP_1 | 619 passed, 1 skipped, 0 failed | PRODUCTION_HISTORICAL |
| CANONICAL_STEP_2 | 5065 passed, 3 skipped, 0 failed | PRODUCTION_HISTORICAL |
| FULL_MYPY | PASS, 0 hata | PRODUCTION_HISTORICAL |
| SECRET_GATE | PASS, 0 bulgu | PRODUCTION_HISTORICAL — **çapraz doğrulandı**: `reports/quality/BYS360_SECRET_REPO_GATE_V1_REPORT.json` (bu inceleme kapsamında üretilmiş rapor artefaktı, `generated_at: 2026-09-02T22:44:02`) `finding_count: 0`, `ok: true`, 3298 dosya |
| LOCAL_COVERAGE | %36,5722 | PRODUCTION_HISTORICAL — **çapraz doğrulandı**: `reports/quality/coverage.xml`'den ratchet formülüyle yeniden hesaplanan oran ≈ %36,57 (küçük yuvarlama farkı dışında birebir örtüşür) |
| COVERAGE_BASELINE | %27,62 (değişmedi) | PRODUCTION_HISTORICAL — **çapraz doğrulandı**: `reports/quality/coverage_baseline.json`: `combined_pct: 27.62` |
| PYTHON_FILE_COUNT | 973 (app/) | CODE_VERIFIED — **çapraz doğrulandı**: `reports/quality/BYS360_QUALITY9_CI_GATE_REPORT.json`: `python_files: 973` |
| TEST_FILE_COUNT | 384 `test_*.py` dosyası, 13 üst-düzey aile dizini | CODE_VERIFIED (bu incelemede sayıldı) |
| REMOTE_VERIFIED_CHECKPOINT | `7d73ff4d468cad11d78d2339ba770f70b5ec0baf` | PRODUCTION_HISTORICAL — yerel HEAD (`873e6d3`) ile **birebir aynı değildir**; exact-head kuralı gereği final teslim öncesi HEAD'e özel taze CI kanıtı gereklidir |

**Sonuç:** Bu incelemede `reports/quality/` altındaki mevcut artefaktlarla yapılan çapraz okuma, önceki tur rakamlarıyla **hiçbir çelişki bulmamış**, aksine güçlü biçimde desteklemiştir.

---

## Release / Deployment Modeli

| Alan | Değer | Kanıt |
|---|---|---|
| RELEASE_MODEL | `scripts/release/build_bys360_safe_release.py` — SHA256 doğrulamalı paket, `RELEASE_SOURCE_SHA.txt` ZIP içine gömülü (hash kapsamının içinde), sidecar manifest tek başına artık yeterli görülmüyor (BYS360 DEFECT AH'nin kapatılması) | CODE_VERIFIED |
| CANDIDATE_MODEL | `prepare_bys360_candidate.ps1` — 16 fazlı, canlıya yapısal olarak dokunmaz | CODE_VERIFIED (dosya mevcut, committed, 16 faz doğrulandı) |
| CANDIDATE_READY_JSON_SCHEMA | `SCHEMA_VERSION, RECEIPT_KIND, GENERATED_AT, SOURCE_SHA, PACKAGE_PATH, PACKAGE_SHA256, CANDIDATE_DIR, DEPENDENCY_LOCK_MODE, DEPENDENCY_LOCK_FILE, DEPENDENCY_LOCK_SHA256, WHEELHOUSE_IDENTITY_SHA256, PIP_CHECK, IMPORT_GATES, APP_FACTORY_CHECK, MIGRATION_HEAD, DB_BACKUP_PATH, SHADOW_REHEARSAL_RESULT, SCHEMA_CONTRACT_CHECK, FILE_CENTER_TABLES, HEALTH_BOOT_PORT, HEALTH_CHECK_RESULT, CANDIDATE_READY` | CODE_VERIFIED (`prepare_bys360_candidate.ps1:199-222`) |
| CUTOVER_MODEL | `cutover_bys360_candidate.ps1` — 20 fazlı, sert kapı (`Assert-ValidCandidateReceipt`), üçlü PID/sürüm/hazır-olma bağlama (DEFECT Z kapatması) | CODE_VERIFIED |
| ROLLBACK_MODEL | `rollback_bys360_candidate.ps1` — Alembic downgrade **hiçbir koşulda** otomatik çalışmaz; migration-öncesi/sonrası ayrımı yapısal (`Test-AppTreeDbCompatibilityGate`); ayrıca eski/tekil `rollback_bys360_live_release_v1.ps1` modeli de mevcut | CODE_VERIFIED |
| BACKUP_MODEL | İki `pg_dump` noktası (candidate-prep Faz 10, cutover Faz 5) — **bağımsız/zamanlanmış bir haftalık backup script'i YOK** (negatif SCRIPT_VERIFIED arama) — REQUIRES_INSTITUTIONAL_DECISION | SCRIPT_VERIFIED |
| DEPENDENCY_LOCK_STATUS | `requirements.lock` (170 satır/59 paket) ve `build/wheelhouse/` (59 `.whl`) bu HEAD'de **mevcuttur** ama kendi başlıklarına göre **eski SHA `ec4e56b`'ye karşı** üretilmiştir — güncel HEAD `873e6d3`'e karşı yeniden üretilmemiştir | CODE_VERIFIED (dosyalar mevcut, başlık tarihi/SHA'sı okundu — bağımsız olarak iki kez doğrulandı) |
| PT72H_HARDENING | **UYGULANMIŞ — canlı görevde.** Tekrarlayan 72 saatlik kesinti olayının ardından canlı Scheduled Task doğrudan sertleştirildi: mekanik olarak doğrulanan güncel ayarlar `ExecutionTimeLimit=PT0S` (sınırsız), `RestartCount=3`, `RestartInterval=PT1M`; değişiklik öncesi görev tanımı XML olarak yedeklendi. Bu, kaynak kodda/veritabanında bir değişiklik veya yeni bir uygulama release'i **değildir**. `install_bys360_live_waitress_80_task_v1.ps1`'in `New-ScheduledTaskSettingsSet` çağrısı bu parametreleri hâlâ geçirmez — görev script'ten yeniden kaydedilirse sertleştirme kaybolur; bu, ayrı ve düşük öncelikli açık bir takip maddesidir (bkz. DOC-13 §5, §11) | Canlı görev üzerinde mekanik doğrulama + SCRIPT_VERIFIED (negatif grep, tüm `scripts/windows/*.ps1`, script tarafı için) |

**Not:** `docs/handover/` (19 dosya, zaten committed) bu fazın doğrudan temelidir; current_state seti bunun yerini almaz, güncel HEAD'e göre yeniden ifade eden ek bir katmandır.

---

## Yetkilendirme / Denetim / Yönetişim

| Alan | Değer | Kanıt |
|---|---|---|
| ROLE_FAMILIES | `ADMIN_FAMILY_ROLES={admin, baskan, baskan_yardimcisi, grup_baskani, mali_musavir}`; `MANAGER_FAMILY_ROLES` bunlara `birim_sorumlusu, koordinator` ekler | CODE_VERIFIED (`app/route_support.py:66-70`) |
| MENU_AUTHORIZATION_MODEL | `menu_key_required` decorator'ı canlı DB menü haritasına (`build_menu_visibility_map`) bakar; **admin bypass'ı bilinçli olarak kaldırılmıştır** (`BYS360_SETTINGS_LIVE_AUTHORITY_V2`). UI görünürlüğü ile backend kararı **aynı fonksiyona** dayanır — "menü gizli ama route açık" senaryosu yapısal olarak mümkün değildir. Tek dar istisna: 3 spesifik performans-dönem menü anahtarı için admin-ailesi görünürlüğü zorlanır (yalnız menü, backend'i etkilemez) | CODE_VERIFIED (`app/route_support.py:424-436`, `app/services/settings/effective_menu_parts/public_build_context.py:9-27`) |
| AUDIT_MODEL | **Düzeltme (aşırı genellemeden kaçınılmalı):** `record_security_event()` yalnızca bootstrap guard'larından çağrılır; `write_audit_log()`/`AuditLog(` doğrudan kullanımı yalnızca 10 dosyada (Dosya Merkezi + Performans delegasyon/dönem/geri bildirim akışları). "Her state-change audit'lenir" iddiası **aşırı genellemedir**; doğru ifade: kritik/hassas akışlar hedeflenmiştir, blanket değildir. Ayrıca yetki/menü değişiklikleri için ayrı, rollback-izlenebilir bir günlük vardır: `SettingsChangeLog` | CODE_VERIFIED (`app/models/audit_misc_models.py`, `app/services/audit_event_service.py`, `app/models/settings_models.py:89-108`) |
| AI_GOVERNANCE_BOUNDARIES | `app/services/ai/visibility_gate.py` sözleşme sabitleri: `AI_FINAL_DECISION_ENABLED=False`, `AI_AUTO_APPLY_ENABLED=False`, `RAW_AI_EXPORT_ENABLED=False`, `HUMAN_REVIEW_REQUIRED=True`, `KVKK_MASKING_REQUIRED=True`. Varsayılan AI sağlayıcı modu `"stub"` — dış servise bağlı değil | CODE_VERIFIED (`app/services/ai/visibility_gate.py:31-40`, `config.py:722-724`) |
| SECRET_KEY_ENFORCEMENT | Boş/placeholder/kısa (<32 karakter) `SECRET_KEY`, `APP_ENV` production/staging'de sert `RuntimeError` ile engellenir | CODE_VERIFIED |
| ROLE_MATRIX_UI_DRIFT_RISK | `/admin/role-matrix` salt-okunur ekranı tamamen kod-içi sabit veri render eder, canlı DB durumunu **yansıtmaz** — gerçek karar her zaman DB tablolarına dayanır. Bu iki ekran arasında bir drift/yanlış-anlama riskidir | DOCUMENTATION_DERIVED + CODE_VERIFIED çapraz doğrulama |

---

## Kurumsal Görsel Kimlik (DOC-20 — dokümantasyon sertleştirme fazında eklendi)

| Alan | Değer | Kanıt |
|---|---|---|
| PRIMARY_INSTITUTIONAL_COLOR | `#8B0000` — adlandırılmış CSS değişkenleri (`--catab-red`, `--bys-hero-accent`, `--acu-red`) ve onlarca dosyada tutarlı kullanım | CODE_VERIFIED (`app/static/css/base_logo_refresh.css:2,224`, `analysis_center_ultra.css:1`, vb.) |
| BRAND_SELF_CHECK | Kurumun kendi `app/services/ui/brand_readiness_service.py` servisi, `base.html` içinde `#8B0000` ve `ay_yildiz` referanslarının varlığını otomatik denetler | CODE_VERIFIED |
| WATERMARK | `ay_yildiz.png`, `app.css` üzerinden sabit konumlu, %6 opaklık, `pointer-events:none` | CODE_VERIFIED |
| FONT_STACK | `Segoe UI, Arial, sans-serif` | CODE_VERIFIED (`app/static/css/app.css:17`) |
| COMPONENT_LIBRARY_STATUS | Ortak bileşen ailesi (PageShell/StatCard/vb.) kavramsal bir standarttır — kod tabanında merkezi, konsolide bir bileşen kütüphanesi olarak bu isimlerle **bulunamadı** | DESIGN_STANDARD (DOC-20), NOT_YET_FINALIZED (konsolidasyon) |
| DESIGN_DOC | `docs/current_state/20_BYS360_Kurumsal_Tasarim_ve_Arayuz_Standardi.md` | Bu fazda oluşturuldu |

---

## Puantaj ve Finalizasyon Sırası

| Alan | Değer | Kanıt |
|---|---|---|
| PUANTAJ_STATUS | PLANLANAN / ONAYLANAN SONRAKİ GELİŞTİRME — kod tabanında **bulunmadı** (kapsamlı grep ile doğrulandı, bkz. yukarı) | Kullanıcı beyanı + CODE_VERIFIED |
| PUANTAJ_INSTITUTIONAL_DECISION_GROUP_COUNT | **7** (Excel çizelgesi; normal/vardiyalı çalışma; fazla mesai genel süreç; Ek-28; 4/A kuralları; 4/D kuralları; aylık takvim) | DOC-18 §3 (bu fazda 10'luk düz tablodan yeniden gruplandı) |
| PUANTAJ_INDIVIDUAL_UNRESOLVED_QUESTION_COUNT | **22** (bkz. DOC-18 §3, tek tek numaralandırılmış) | DOC-18 §3 — önceki "10 institutional input" sayımı yanıltıcıydı (birden fazla soruyu tek satırda birleştiriyordu), bu fazda düzeltildi |
| PUANTAJ_DESIGN_STATUS | Personel Yönetimi'nin görsel uzantısı; semantik renk haritası henüz kilitlenmedi | DOC-18 §5, DOC-20 §13 |
| FINALIZATION_SEQUENCE | AK closure → CURRENT-STATE dokümantasyonu (bu faz + hardening fazı) → Puantaj geliştirme → Puantaj entegrasyon/güvenlik/devir doğrulama → kalan teknik/LOW/DRIFT/operasyon defteri (AL dahil) → bilinmeyen defekt taraması → final kaynak SHA → uzak CI → FINAL FULL → final dokümantasyon yenileme → kurumsal teslim | Kullanıcı beyanı (kesin talimat) |
| KNOWN_OPEN_TECHNICAL_LEDGER_SUMMARY | Bkz. DOC-19 — AL (açık), PT72H hardening (açık), requirements.lock/wheelhouse staleness (açık), üç-SHA belge tutarsızlığı (açık), role-matrix UI drift (açık gözlem), audit kapsamının aşırı genellenmemesi (açık gözlem), teknik dil politikasının mevcut ekranlarda taranmamış olması (açık gözlem, DOC-20 §10) | Teknik incelemelerin bulguları + çapraz doğrulama birleştirildi |

---

## Devredilebilirlik Notu

Eski `docs/handover/BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md` §26.1, **SHA `cb2e57c`'ye özel** `LIVE_READINESS_FINAL=98`, `TRANSFERABILITY_FINAL=95` puanlarını taşır. Bu puanlar, kendi hesaplama mantığı gereği **her yeni commit için otomatik miras alınmaz** — mevcut HEAD (`873e6d3`) için **geçerli değildir**, yalnızca PRIOR/CHECKPOINT tarihsel referans olarak anılabilir (bkz. DOC-08 §8). Bu current-state fazı yeni bir sayısal puan **üretmez**.

---

## İnceleme Süreci Özeti

Üç teknik alanda (Mimari/Veri/Modüller; Kurulum/Operasyon/Release; Güvenlik/Devir/Yönetişim) 15 teknik belge tamamlandı; tüm belgeler okunup çapraz doğrulandı, bir gerçek hata bulunup düzeltildi (DOC-10/DOC-16 — `postgresql-x64-15` servis kontrolünün yanlış dosyaya atfedilmesi), bu ledger v2 olarak birleştirildi.

## Düzeltme Kaydı — KYS Olgu Düzeltmesi + DOC-01 Numaralandırma (bu faz)

1. **KYS olgu düzeltmesi:** DOC-01 §3 ve DOC-17'nin açılış paragrafı, KYS'yi hatalı biçimde "Kalite Yönetim Sistemi" olarak tanımlıyordu. Kullanıcının yetkili düzeltmesi üzerine kanonik tanım (KYS = mevcut kurumsal ERP) uygulandı — bkz. yukarıdaki "Kurumsal Konumlandırma" bölümü.
2. **DOC-01 başlık numaralandırma düzeltmesi:** Önceki görsel kabul incelemesinde tespit edilen, iki bölümün "6." numarasını paylaştığı (ve sonrasındaki tüm bölümlerin bir kayık olduğu) kusur düzeltildi — bölümler artık 1'den 11'e kesintisiz ve tekrarsızdır.
