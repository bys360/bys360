# 09 — Kurulum, İşletim, İzleme, Yedekleme ve Geri Dönüş

| Alan | Değer |
|---|---|
| Kaynak (incelenen) | `origin/assistant-v2-full` @ `f796107fa6ab42096065a02d4724ec7e8d22f608` |
| Belgelenmiş production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` (`SOURCE_OF_TRUTH.md:12`) |
| Hazırlanma tarihi | 2026-10-11 |

Bu belge yalnız repodaki belgelerin ve script'lerin söylediklerini özetler. Hiçbir komut bu çalışma kapsamında canlı ya da test sunucusunda çalıştırılmamıştır. Eksik veya doğrulanamayan noktalar **EKSİK/DOĞRULANMADI** olarak işaretlenmiştir.

---

## 1. Belge haritası

| Konu | Birincil belge | Destekleyici |
|---|---|---|
| Ortamlar, ilk kurulum, DB hazırlığı, release, rollback özeti | `DEPLOYMENT.md` | `CONTRIBUTING.md` §1–5 |
| Canlı host önkoşulları, dizin yapısı | `docs/handover/LIVE_INSTALLATION.md` | `docs/current_state/03_BYS360_Kurulum_Yapilandirma_ve_Canliya_Gecis_Kilavuzu.md` |
| Aday hazırlama | `docs/handover/CANDIDATE_PREPARATION.md` | `scripts/windows/prepare_bys360_candidate.ps1` (1956 satır) |
| Cutover | `docs/handover/CUTOVER.md` | `scripts/windows/cutover_bys360_candidate.ps1` (1499 satır) |
| Rollback | `docs/handover/ROLLBACK.md`, `DEPLOYMENT.md` §9 | `scripts/windows/rollback_bys360_candidate.ps1` (907 satır) |
| Yedek / restore | `BACKUP_RUNBOOK.md` | `docs/current_state/06_..._Felaket_Kurtarma_Kilavuzu.md`, `docs/handover/DISASTER_RECOVERY.md`, `docs/handover/DATABASE_MIGRATION.md` |
| Secret ve kalıcı veri sözleşmesi | `docs/handover/SECRETS_AND_PERSISTENCE.md` | — |
| Scheduled Task işletimi | `docs/current_state/13_..._ScheduledTask_ve_Servis_Yonetimi.md` | `scripts/windows/install_bys360_live_waitress_80_task_v1.ps1` |
| Bakım rutinleri | `docs/handover/BYS360_BAKIM_RUNBOOK.md` | `docs/current_state/04_..._Isletim_Bakim_ve_Guncelleme_Kilavuzu.md` |
| Sorun giderme | `docs/current_state/15_BYS360_Sorun_Giderme_ve_Mudahale_Kilavuzu.md` | — |
| Production kimliği ve son cutover kanıtı | `SOURCE_OF_TRUTH.md` | `docs/quality/BYS360_PRODUCTION_CUTOVER_2026-10-07.md`, `STATUS.md` |

`docs/current_state/*` belgeleri 2026-09-02 tarihli ve `873e6d3` SHA'sına aittir; `SOURCE_OF_TRUTH.md:166-180` bunları tarihsel snapshot olarak sınıflandırır.

## 2. Kurulum

### 2.1 Yerel geliştirme

- Python 3.12 venv, `requirements.txt` (+ kalite araçları için `requirements-dev.txt`), `.env.example`'dan `.env` (`DEPLOYMENT.md:21-36`; `CONTRIBUTING.md:38-57`).
- Smoke: `python -m compileall ...`, `python run.py`, `http://127.0.0.1:8000/login` (`DEPLOYMENT.md:69-83`).
- Docker profili: `docker-compose up -d --build` (`CONTRIBUTING.md:59-65`) — yerel/pilot amaçlı.

### 2.2 Veritabanı (yeni/boş PostgreSQL 15)

`flask db upgrade` → `flask runtime-schema provision` (`DEPLOYMENT.md:40-55`). PostgreSQL 15 üzerinde scratch/clean-room doğrulaması `SOURCE_OF_TRUTH.md:60-64`'te kayıtlıdır. Production'ın sıfırdan kurulduğu iddia edilmez (`DEPLOYMENT.md:54-55`).

### 2.3 Canlı host önkoşulları (`docs/handover/LIVE_INSTALLATION.md`)

- Windows Server, yükseltilmiş (Administrator) PowerShell (§1).
- Mutlak yol ile çözülmüş Python 3.12 yorumlayıcısı; PATH'teki `python`'a güvenilmez (§2).
- PostgreSQL 15 Windows servisi; `pg_dump`/`pg_restore`/`psql` istemci araçları; `CREATEDB` yetkisi olmayan uygulama rolü + yalnız shadow DB için etkileşimli girilen admin rolü (§3).
- Scheduled Task `BYS360 Live Waitress 80` **önceden var olmalıdır**; cutover araçları görevi oluşturmaz (§4).
- Dizin yapısı: `C:\bys360\{project, candidate\<SHA>, previous\<ts_SHA>, storage, local_storage, backups, logs, releases, deploy_logs}` (§5).
- Dışarıdan sağlanması gerekenler: gerçek `.env`, PostgreSQL rol kimlik bilgileri, `instance/` içeriği, PostgreSQL kurulumu, Scheduled Task (§6).
- Task kurulumu: `install_bys360_live_waitress_80_task_v1.ps1` varsayılan dry-run; `-Apply`, mevcut görev için `-ConfirmReplace` (script başlığı satır 7-19).

**EKSİK/DOĞRULANMADI:** Belgelerde geçen tarihsel host kimliği kontrollerini içeren `scripts/windows/deploy_bys360_ec4e56b_production_v4.ps1` repoda yoktur (`LIVE_INSTALLATION.md:21-23` bunu açıkça belirtir; `docs/handover/DISASTER_RECOVERY.md` hâlâ bu dosyaya atıf yapar). Ters vekil/TLS katmanının kurulumu hiçbir belgede yoktur.

## 3. Release ve canlıya alma süreci

1. **Paket:** `scripts/release/build_bys360_wheelhouse.py` (Windows x64/CPython 3.12 wheelhouse) → `scripts/release/build_bys360_safe_release.py --source-sha <SHA> --wheelhouse-dir ...` (FULL paket, manifest `schema_version=3`) → `--verify` (`DEPLOYMENT.md:155-217`). Yalnız Git'in izlediği dosyalar; `.env`, `tests/`, `mobile_flutter/`, `.codex/`, `.claude/` yasak (`DEPLOYMENT.md:214-216`).
2. **Aday hazırlama:** canlıya dokunmadan `C:\bys360\candidate\<SHA>\`; offline bağımlılık kurulumu, shadow PostgreSQL provası, aday sağlık açılışı → `CANDIDATE_READY.json` (`docs/handover/CANDIDATE_PREPARATION.md`).
3. **Cutover (20 faz):** receipt doğrulama → host önkoşulları → canlı kimlik → DB revizyonu → **pg_dump yedeği (Faz 5)** → `.env`/`instance` koruma (Faz 6) → görevi durdur (7) → port 80 kapandı mı (8) → ağaç taşı/aday yükselt (9) → `.env`/`instance` geri koy (10) → kimlik (11) → **canlı migration (12)** → revizyon + Dosya Merkezi doğrulaması (13) → görevi başlat (15) → yerel `/healthz` (16), `/versionz` kimlik bağlama (16a), `/readyz` (16b) → genel `https://.../healthz` (17) → smoke (18) → güvenlik/log kapısı (19) → `DEPLOYMENT_RECEIPT.txt` (20) (`scripts/windows/cutover_bys360_candidate.ps1:546-1398`).
4. **Kesinti penceresi:** tasarım hedefi faz 6–15 ile sınırlıdır (`docs/handover/CUTOVER.md:130-141`); süre ölçümü belgelenmemiştir.

Canlıda doğrulandı (yalnız belgelenen kayıt): 2026-10-07 cutover'ında tüm bu adımlar PASS (`SOURCE_OF_TRUTH.md:35-49`; `STATUS.md` 2026-10-07).

**EKSİK/DOĞRULANMADI:** Cutover script'inde "Phase 14/20" log satırı bulunmadı (Faz 13'ten 15'e geçiyor; `grep "14/20"` boş) — numaralandırma tutarsızlığı; `CUTOVER.md` adım numaralandırması (ör. "step 4 final backup") script'in faz numaralarıyla (Faz 5) birebir örtüşmüyor.

## 4. Sağlık uçları

| Uç | Davranış | Kimlik doğrulama | Kaynak |
|---|---|---|---|
| `GET /healthz` | Her zaman `200 {"status":"ok"}`; DB'yi kontrol etmez | Yok | `app/routes.py:74-76` |
| `GET /readyz` | Şema kontrol hatası yoksa 200 `ready`, varsa 503 `degraded` | Yok | `app/routes.py:79-88` |
| `GET /versionz` | `app_env`, `route_count`, `schema_error_count`; `source_sha` ve `migration_head` yalnız loopback isteklerinde | Yok | `app/routes.py:244-270` |
| `GET /health` | Sabit 200 | Yok | `app/core/healthcheck.py:43-45` |
| `GET /health/deep` | `SELECT 1` + Redis ping (tanımlıysa); hata varsa 503 | Yok | `app/core/healthcheck.py:48-66` |
| `GET /ai-agent/healthz`, `/ai-agent/health` | Asistan alt sistemi | — | `app/ai_agent/routes.py:75,93` |
| `GET /api/mobile/health` | Mobil API | — | `app/api/mobile/utility_routes.py:18` |

Not: Doğrudan `http://127.0.0.1/healthz` çağrısı `Host`/şema beklentisi nedeniyle 400 dönebilir; yerel kontrol proxy başlıkları taklit edilerek yapılır (`docs/handover/BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md:342-345`; cutover Faz 16).

Gözlem (kodda var): `/versionz` `route_count` alanı `len(runtime_route_manifest)` değerini döndürür; manifest 6 anahtarlı bir sözlüktür (`app/route_registry.py:64-72`), dolayısıyla bu alan route sayısını değil anahtar sayısını gösterir.

## 5. İzleme ve loglama

| Bileşen | Durum | Kaynak |
|---|---|---|
| Uygulama logları | `LOG_FOLDER` altında `bys360-app.log`, `bys360-ops.log`, `RotatingFileHandler` (varsayılan 2 MB × 5) | `app/bootstrap/operational_logging.py:62,93-94`; `config.py:589,649-653` |
| Waitress stdout/stderr | `C:\bys360\logs\bys360_live_waitress_80.log`, append; rotasyon yok | `install_bys360_live_waitress_80_task_v1.ps1:42`; `docs/current_state/04_...md:32` |
| Deploy logları ve makbuzlar | `C:\bys360\deploy_logs\<run>\` (`FAILURE_RECEIPT.txt`, `DEPLOYMENT_RECEIPT.txt`) | `docs/current_state/04_...md:48-53` |
| Sentry | Opsiyonel, `SENTRY_DSN` boşsa kapalı | `app/core/monitoring.py:27-75`; `config.py:673-674` |
| Prometheus `/metrics` | Kod var; uygulama içinde `init_prometheus_metrics` çağrısı bulunamadı | `app/observability/prometheus_metrics.py:17` |
| Bakım runbook'u | Günlük/haftalık/aylık manuel kontrol listesi | `docs/handover/BYS360_BAKIM_RUNBOOK.md:1-39` |

**EKSİK/DOĞRULANMADI:**
- Dış uptime izleme, alarm/uyarı kanalı, nöbet (on-call) süreci — hiçbir belgede yok.
- Production'da Sentry'nin etkin olup olmadığı — belgelenmemiş.
- Waitress log dosyası için rotasyon — yok olarak raporlanmış (`docs/current_state/04_...md:32`).
- Prometheus metrikleri — etkin bir bağlantı noktası bulunamadı.

## 6. Yedekleme

### 6.1 PostgreSQL

- Otomatik yedek **yalnız** iki noktada alınır: aday hazırlamada kaynak DB dump'ı ve cutover Faz 5'te canlı DB dump'ı (`pg_dump -F c`), dosyanın varlığı ve sıfırdan büyük olduğu doğrulanır (`docs/current_state/06_...md:17-26`; `cutover_bys360_candidate.ps1:783-804`). Hedef: `C:\bys360\backups\predeploy_cutover_<DeployId>\`.
- Manuel örnek: `pg_dump --format=custom --file=... --dbname="$env:DATABASE_URL"` (`BACKUP_RUNBOOK.md:44-61`).
- Saklama **önerisi**: kod yedeği 30 gün, kritik migration öncesi DB 90 gün, aylık arşiv 1 yıl (`BACKUP_RUNBOOK.md:182-189`).

### 6.2 Dosyalar ve yapılandırma

- Kod yedeği: `robocopy` ile filtreli (`.env`, `.venv`, `logs`, `instance`, `uploads` vb. hariç) (`BACKUP_RUNBOOK.md:23-42`).
- `.env` ve `instance\`: cutover Faz 6'da `C:\bys360\backups\cutover_state_<DeployId>\` altına kopyalanır (`docs/current_state/06_...md:33`).
- `C:\bys360\storage\`, `C:\bys360\local_storage\` (Dosya Merkezi içeriği): hiçbir script tarafından yedeklenmez; dosya sunucusu düzeyinde yedek "deployment modelinin kapsamı dışında" (`docs/current_state/06_...md:36-38`).

**EKSİK/DOĞRULANMADI:**
- Cutover'lar arası **zamanlanmış** düzenli DB yedeği — repoda yok (`docs/current_state/06_...md:26`; aktif `scripts/windows/` altında backup scheduler yok).
- Dosya Merkezi depolama alanlarının yedeği — tanımsız, kurumsal karar bekliyor.
- RPO ve RTO — tanımlanmamış (`docs/current_state/06_...md:44-51`).
- Yedeklerin şifrelenmesi, site dışı kopya, restore tatbikatı kaydı — belgelenmemiş. `BACKUP_RUNBOOK.md:174-180` restore'un test ortamında denenmesini kontrol listesinde sorar, ama kayıt yoktur.

## 7. Restore

- PostgreSQL: `pg_restore --clean --if-exists --dbname="$env:DATABASE_URL" <dump>`; yetkili insan onayı, hedef/yedek doğrulaması ve kesinti planı gerekir (`BACKUP_RUNBOOK.md:148-158`).
- Felaket kurtarmada birincil yöntem onaylı PostgreSQL yedeğinin restore'udur; `runtime-schema provision` yerine geçmez (`BACKUP_RUNBOOK.md:160-167`; `SOURCE_OF_TRUTH.md:69`).
- Kısmi migration sonrası: önce mevcut durumun yedeği, `flask db current` ile gerçek revizyonun sorgulanması, `--no-owner --no-privileges` ile restore, exit code 0 zorunlu (`docs/handover/DISASTER_RECOVERY.md`, "Recovering the database from the pre-cutover backup").

**EKSİK/DOĞRULANMADI:** İki belge farklı `pg_restore` bayrakları önerir (`BACKUP_RUNBOOK.md:151` `--clean --if-exists`; `DISASTER_RECOVERY.md` ve DOC-06 §6 `--no-owner --no-privileges`). Tek kanonik restore komutu belirlenmemiştir.

## 8. Rollback

- **Kanonik app-tree rollback:** `scripts/windows/rollback_bys360_candidate.ps1`; zorunlu `-PreviousDir` ve `-ActiveDeploymentReceiptPath`; receipt alanları (`DEPLOY_EXIT_CODE=0`, `CANDIDATE_SOURCE_SHA`, `PREVIOUS_SOURCE_SHA`, `PREVIOUS_DIR`) eşleşmezse servis durdurulmadan reddedilir; DRY-RUN modu yoktur (`DEPLOYMENT.md:219-251`; `BACKUP_RUNBOOK.md:76-105`).
- **Migration sonrası:** DB revizyonu önceki ağacın head'inden farklıysa açık `-PostMigrationAppTreeCompatible` insan beyanı gerekir; script uyumluluğu kanıtlamaz (`DEPLOYMENT.md:237-241`). Önceki/aday kaynağın diff'lenmesi ve migration'ın yalnız ekleyici olduğunun okunması istenir (`docs/handover/ROLLBACK.md:33-60`).
- **Alembic downgrade otomatik çalıştırılmaz**; DB backup'ları rollback ile silinmez (`docs/handover/ROLLBACK.md:77-97`).
- **Legacy yol:** `rollback_bys360_live_release_v1.ps1` (varsayılan DRY-RUN, `-Apply`) yalnız pre-candidate dönem içindir (`BACKUP_RUNBOOK.md:107-146`).
- Güncel durum: 2026-10-07 sürümü DB revizyonunu ilerlettiği için yalnız app-tree rollback'i tam DB rollback'i sayılmaz (`STATUS.md` 2026-10-07 "Rollback" maddesi).

**EKSİK/DOĞRULANMADI:** Kanonik rollback script'inin production üzerinde (veya production benzeri ortamda) uçtan uca prova kaydı repoda bulunamadı; 2026-10-07 ve 2026-09-28 cutover'larında rollback "gerekmedi" (`SOURCE_OF_TRUTH.md:49`).

## 9. Diğer zamanlanmış görevler

Repoda mail, CIC, yönetici özeti, sosyal içe aktarma görevleri için kurulum script'leri vardır (ör. `install_bys360_daily_mail_tasks_v1_4.ps1`, `install_bys360_cic_auto_mail_scheduler_task.ps1`, `register_bys360_executive_summary_tasks_v2_14_3.ps1`, `install_bys360_social_auto_import_v3b2_task.ps1`). Bazı görevler için birden çok sürümlü installer bulunur (ör. daily mail v1_4 ve v1_6; executive summary v2_14_1 ve v2_14_3).

**EKSİK/DOĞRULANMADI:** Hangi installer'ın kanonik olduğu ve canlıda hangi görevlerin kurulu olduğu belgelenmemiş (`docs/current_state/13_...md:115-117`). Uygulama içi `BYS360_FEEDBACK_FOLLOWUP_SCHEDULER` env bayrağıyla açılan bir zamanlayıcı da vardır (`app/services/performance/feedback_followup_scheduler.py:52`); canlıdaki değeri belgelenmemiş. Dosya Merkezi periyodik bakım (süresi dolan link/istek kapatma, kota, tarama) yalnız Linux cron örneği olarak verilmiştir (`deployment/file_center_cron_v1l.example`, `scripts/local/file_center_ops_tick_v1l.py`); Windows canlı ortamı için karşılık gelen bir görev installer'ı bulunamadı.

## 10. Özet: eksikler listesi

| # | Eksik / doğrulanmamış | Kaynak |
|---|---|---|
| 1 | Düzenli zamanlanmış DB yedeği yok | DOC-06 §1 |
| 2 | Dosya Merkezi depolama yedeği tanımsız | DOC-06 §3 |
| 3 | RPO/RTO tanımsız | DOC-06 §5 |
| 4 | Alarm/uptime izleme ve nöbet süreci yok | — |
| 5 | Ters vekil/TLS kurulum ve yapılandırması belgelenmemiş | DOC-13 §1 |
| 6 | Waitress log rotasyonu yok | DOC-04 |
| 7 | Restore komutunda belgeler arası tutarsızlık | §7 |
| 8 | Rollback prova kaydı yok | §8 |
| 9 | Kanonik zamanlanmış görev seti belirsiz | §9 |
| 10 | Cutover belge/script faz numaralandırması tutarsız; atıf yapılan tarihsel script repoda yok | §2.3, §3 |
