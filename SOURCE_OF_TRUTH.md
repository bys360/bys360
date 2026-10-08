# BYS360 Source of Truth

Bu belge tek bir soruya kısa ve doğrulanabilir cevap verir: **Bugün hangi branch ve hangi
exact commit SHA production gerçeğidir?**

Son doğrulama: 2026-10-07 (production cutover'ı 2026-10-07'de insan operatör tarafından yürütüldü ve doğrulandı; önceki production kimlikleri §7'de tarihçe olarak korunur).

## 1. Current Production Identity

| Alan | Değer | Kanıt |
|---|---|---|
| Verified production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` | 2026-10-07 cutover'ında `/versionz`, process binding ve exact-SHA release zinciriyle doğrulandı. Annotated tag `bys360-prod-2026.10.07-cdae2795` doğrudan bu commit'i işaret eder. |
| Production tag | `bys360-prod-2026.10.07-cdae2795` | Annotated tag object `aa7b77ca21fe0a10ab9fd7f9cc5104743b4d1311`; peeled target `cdae27953adcbdd8270fe78dcd52351725d3aecd`. |
| Production lineage branch | `assistant-v2-full` | Production SHA bu branch soyundadır. Branch ucu production kimliği değildir. |
| Deployment date | 2026-10-07 | İnsan operatör tarafından yürütülen production cutover. |
| Production migration head | `x1f3a9c5e7b2` | Canlı DB cutover öncesinde `w2d8e1f4a6c3`, sonrasında `x1f3a9c5e7b2`. |
| Release package | `BYS360_FULL_cdae2795.zip` | SHA-256 `48d2572b3630e5c33bbf3cd337e9a9cf39f6b33d9d47aa3d7d17a54ec065f339`; iki bağımsız build byte-identical. |
| Previous production SHA | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` | Tag `bys360-prod-2026.09.29-a5bd8a38`; migration head `w2d8e1f4a6c3`. |

**Production source of truth herhangi bir branch'in ucu değil, doğrulanmış exact commit SHA'dır.**
Production tag'i bir dokümantasyon commit'ine değil doğrudan çalışan kaynak commit'ine bağlıdır.

### 1.1 2026-10-07 Candidate ve Cutover Kanıtı

- PR #47: `fix: adopt exact historical production interim-notes schema`.
- Test edilen PR head: `d529020641f8d4fd7da160b77d2ccab9e586c661`.
- Merge commit: `cdae27953adcbdd8270fe78dcd52351725d3aecd`.
- Test edilen head ağacı ve merge ağacı birebir aynı: `723da65df61f40eefefc12c853ae6177ad6dedb9`.
- GitHub Actions:
  - `Run tests`, run `37619199191`: SUCCESS.
  - `BYS360 Quality Assurance Gate V1`, run `37619199193`: SUCCESS.
- Final FULL ZIP SHA-256: `48d2572b3630e5c33bbf3cd337e9a9cf39f6b33d9d47aa3d7d17a54ec065f339`.
- Wheelhouse: 59 Windows CPython 3.12 wheel; identity
  `c372cc2512055ef4f48648769bd09ee2e28b194b556a81eb242cdaf7722d4a70`.
- Candidate preparation: PASS.
- Fresh disposable shadow PostgreSQL migration rehearsal: PASS.
- Candidate health: PASS.
- Canlı migration: `w2d8e1f4a6c3` → `x1f3a9c5e7b2` PASS.
- Live schema contract: PASS, error count 0.
- Dosya Merkezi: 19/19.
- Service/process binding: PASS.
- Local health: HTTP 200.
- Release identity: PASS.
- Readiness: PASS.
- Public health: HTTP 200.
- Smoke: PASS.
- Post-deploy security critical: 0.
- Cutover sonrası bağımsız kontrol: Scheduled Task Running; public `/healthz` HTTP 200.
- Rollback gerekmedi; önceki application tree ve fresh pre-cutover PostgreSQL backup korundu.

Ayrıntılı sanitised kanıt:
[docs/quality/BYS360_PRODUCTION_CUTOVER_2026-10-07.md](docs/quality/BYS360_PRODUCTION_CUTOVER_2026-10-07.md).

### 1.2 Candidate Status (2026-10-07)

Production cutover tamamlandıktan sonra uygulama kodu açısından ayrı, henüz canlıya alınmamış bir
aday kaydı bu belgede tanımlanmamıştır. Bu production kaydını güncelleyen dokümantasyon commit'i
production SHA'yı değiştirmez.

Scratch/clean-room PostgreSQL kurulumunda mevcut iki aşamalı model sürer:

- `flask db upgrade` Alembic'in sahip olduğu şemayı kurar.
- `flask runtime-schema provision` migration/ORM kapsamı dışındaki kontrollü runtime-schema
  gruplarını sağlar.

2026-10-07 migration'ı, production'da gözlenen exact historical
`performance_interim_notes` kataloğunu fail-closed biçimde tanır. Tanınan production varyantında
tablo DDL/DML veya alias normalizasyonu yapmadan Alembic ownership/revision ilerletilir.
Felaket kurtarmada birincil yöntem hâlâ onaylı PostgreSQL backup restore prosedürüdür.
## 2. Repository Branch Roles

| Branch | Rol |
|---|---|
| `assistant-v2-full` | Repository'nin varsayılan (default) branch'i; production soy hattı ve bir sonraki aday hattı. Güncel uygulama kodu, performans düzeltmeleri, CI düzeltmeleri ile LICENSE / NOTICE / README ve kurumsal dokümantasyon bu hatta birleşiktir. Varsayılan branch olması canlıda olduğu anlamına gelmez: ucu, insan kararıyla cutover yapılana kadar production değildir; production kimliği §1'deki exact SHA'dır. |
| `docs/ministry-review-readme` | Tarihsel dış/kurumsal teknik inceleme ve dokümantasyon branch'i; 2026-09-28'e kadar repository'nin varsayılan branch'iydi. Tüm commit'leri `assistant-v2-full` içinde yer alır; silinmemiştir ve korunur. Production branch'i değildir. |
| `main` | Production source of truth değildir. Ayrı bir tarihsel/entegrasyon soy hattı içerir; production SHA, `main`'in soyunda yer almaz. |

`assistant-v2-full` ve `docs/ministry-review-readme` GitHub ruleset'leri ile korunur: silme ve
force push engellidir; değişiklik yalnız pull request ile ve `quality-gate` ile
`score100-quality-gate` zorunlu kontrolleri geçerek girer.

## 3. Verified Quality Evidence

Current production (`cdae2795…`) PR #47 merge commit'idir. Merge tree `723da65df61f40eefefc12c853ae6177ad6dedb9`,
test edilen PR head `d529020641f8d4fd7da160b77d2ccab9e586c661` tree'siyle birebir aynıdır.

| Kontrol | Sonuç |
|---|---|
| `Run tests` / `quality-gate` — run `37619199191` | PASS |
| `BYS360 Quality Assurance Gate V1` / `score100-quality-gate` — run `37619199193` | PASS |
| PostgreSQL 15 historical production schema adoption rehearsal | PASS |
| Unknown/partial schema fail-closed regression | PASS |
| Mobile `note_type` 40/80 boundary regression | PASS |
| Ruff / mypy / compile / dependency checks | PASS |
| Release/security regression | PASS |
| Deterministic FULL release | PASS — two byte-identical builds |
| Final ZIP SHA-256 | `48d2572b3630e5c33bbf3cd337e9a9cf39f6b33d9d47aa3d7d17a54ec065f339` |

PR #47 yerel doğrulama kaydında migration/behavior regression paketi 323 test PASS ve
release/security paketi 126 test PASS olarak raporlanmıştır. Windows'ta symlink capability
bulunmadığı için önceden mevcut tek symlink-capability testi environment skip olarak kalmıştır;
PostgreSQL migration rehearsal skip edilmemiştir.

### 3.1 Önceki production kanıtı (tarihsel, `a5bd8a38…`)

2026-09-29 production commit'i `a5bd8a389f2a978e2a07bb30d58a622bddea82df` idi.

| Kontrol | Sonuç |
|---|---|
| `quality-gate` run `36528716263` | PASS |
| Secret/repository gate, safe release audit | PASS |
| Ruff, compile, quality/integration/architecture tests | PASS |
| PostgreSQL 15 migration integrity | PASS |
| Coverage ratchet | PASS |
| mypy | PASS |
| Dependency vulnerability audit | PASS |
| `score100-quality-gate` run `36528716201` | PASS |

### 3.2 Önceki production kanıtı (tarihsel, `67f2a29d…`)

| Kontrol | Sonuç |
|---|---|
| `quality-gate` run `36395443907` | PASS |
| PostgreSQL 15 migration integrity | PASS |
| Coverage ratchet | PASS |
| Ruff / mypy / dependency / secret gates | PASS |
| `score100-quality-gate` run `36395443908` | PASS |

### 3.3 Önceki production kanıtı (tarihsel, `1ea5c5dc…`)

GitHub Actions run `35823128265`, 2026-09-23:

| Kontrol | Sonuç |
|---|---|
| quality-gate | PASS |
| Ruff | PASS |
| mypy | PASS |
| PostgreSQL 15 migration integrity | PASS |
| Coverage ratchet | PASS |
| Dependency vulnerability audit | PASS |
| Secret/repository gate | PASS |

| Coverage değeri | Anlam |
|---|---|
| Ölçülen combined coverage: **42.1228%** | 2026-09-23 tarihli doğrulanmış CI snapshot'ı. |
| Kayıtlı ratchet baseline: **27.62%** | Regression floor; current measurement değildir. |
| Etkin eşik: **27.12%** | Baseline eksi 0.50 puan tolerans. |

42.1228% current production coverage iddiası değildir; tarihli snapshot'tır. Baseline otomatik
yükseltilmez.
## 4. Release and Rollback Identity

- **Exact SHA:** canlıya alınan paket, üretildiği tam commit SHA'sı ile tanımlanır.
- **Deterministik release paketi:** tek yetkili builder `scripts/release/build_bys360_safe_release.py`
  yalnız Git'in takip ettiği dosyalardan paket üretir.
- **Dosya manifestosu ve SHA256 doğrulaması:** paketle birlikte manifest ve SHA256 listesi
  üretilir; `--verify` modu eksik, yasaklı veya fazla dosya ya da SHA256 uyuşmazlığında FAIL verir.
- **Aday hazırlığı ve shadow veritabanı provası:** paket, canlı servise dokunulmadan ayrı bir aday
  dizinine açılır; migration atılabilir bir shadow veritabanında prova edilir.
- **İnsan kontrollü cutover:** canlıya geçiş insan operatör tarafından yürütülür.
- **Rollback:** cutover tooling önceki application tree'yi ve fresh DB backup'ını korur. `scripts/windows/rollback_bys360_candidate.ps1` app-tree-only geri dönüş yoludur ve otomatik Alembic downgrade çalıştırmaz; canlı migration DB revizyonunu değiştirmişse veritabanı recovery kararı ayrı ve insan kontrollüdür.

Ayrıntılar: [DEPLOYMENT.md](DEPLOYMENT.md), [BACKUP_RUNBOOK.md](BACKUP_RUNBOOK.md),
[SECURITY.md](SECURITY.md), [docs/handover/CANDIDATE_PREPARATION.md](docs/handover/CANDIDATE_PREPARATION.md).

## 5. Historical Documentation

`STATUS.md` ve `docs/current_state/` altındaki eski SHA ve tarih kayıtları tarihsel kanıt veya
snapshot niteliğindedir; güncel production source of truth değildir. Özellikle:

- `docs/current_state/BYS360_CURRENT_STATE_FACTS.md` (2026-09-02; `873e6d3`, `7d73ff4`)
- `docs/handover/BYS360_CURRENT_PRODUCTION_STATE.json` ve `docs/handover/README.md`'nin
  "CURRENT" olarak işaretlediği devir belgesi (2026-08-24; `cb2e57c5`)
- `docs/quality/BYS360_LIVE_READONLY_VALIDATION_2026-09-28.md`: cutover **öncesi** canlı salt
  okuma doğrulaması. Önceki production'ı (`1ea5c5dc…`) anlatır; cutover sonrası durumu
  anlatmaz.

Bu dosyalar kendi içlerinde "CANONICAL" veya "CURRENT" ifadeleri taşısa da, güncel production
kimliği açısından yerini bu belgeye bırakmıştır. Tarihsel kanıt olarak olduğu gibi korunurlar;
operasyonel içerikleri (runbook adımları vb.) ayrıca değerlendirilmelidir.

**SOURCE_OF_TRUTH.md, güncel production kimliği için kısa canonical giriş noktasıdır.** Yeni bir
production cutover yapıldığında bu belge güncellenir.

## 6. Production Tag — Yönetişimde Değişmez Kimlik

| Alan | Değer |
|---|---|
| Production tag | `bys360-prod-2026.10.07-cdae2795` |
| Tag type | annotated |
| Tag object SHA | `aa7b77ca21fe0a10ab9fd7f9cc5104743b4d1311` |
| Target production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` |

Amaç: BYS360'ın 2026-10-07 doğrulanmış production kimliğini kurumsal inceleme ve teknik devir
için sabit Git referansı olarak işaretlemektir.

Tag bir branch adına veya sonraki dokümantasyon commit'ine değil, doğrudan production SHA'sına
bağlıdır. Production tag'leri BYS360 yönetişiminde immutable production identity olarak kabul
edilir; taşınmamalı ve silinmemelidir.

Önceki production tag'leri değiştirilmeden korunur:

- `bys360-prod-2026.09.29-a5bd8a38` — `a5bd8a389f2a978e2a07bb30d58a622bddea82df`.
- `bys360-prod-2026.09.28-67f2a29d` — `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9`.
- `bys360-prod-2026.09.23-1ea5c5dc` — `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6`.

Ayrı bir GitHub tag ruleset'i doğrulanmadığından tag güncelleme/silme işlemlerinin GitHub
tarafından teknik olarak engellendiği iddia edilmez.

## 7. Production History

| Dağıtım tarihi | Production SHA | Tag | Durum |
|---|---|---|---|
| 2026-10-07 | `cdae27953adcbdd8270fe78dcd52351725d3aecd` | `bys360-prod-2026.10.07-cdae2795` | **Güncel production**. Cutover kaydı: [docs/quality/BYS360_PRODUCTION_CUTOVER_2026-10-07.md](docs/quality/BYS360_PRODUCTION_CUTOVER_2026-10-07.md). |
| 2026-09-29 | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` | `bys360-prod-2026.09.29-a5bd8a38` | Önceki production (tarihçe), migration head `w2d8e1f4a6c3`. |
| 2026-09-28 | `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9` | `bys360-prod-2026.09.28-67f2a29d` | Önceki production. Cutover kaydı: [docs/quality/BYS360_PRODUCTION_CUTOVER_2026-09-28.md](docs/quality/BYS360_PRODUCTION_CUTOVER_2026-09-28.md). |
| 2026-09-23 | `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6` | `bys360-prod-2026.09.23-1ea5c5dc` | Önceki production (tarihçe). |

2026-09-29 cutover'ı DB revision'ı `v1a2d3e4f5b6` → `w1c5a7d2e9b4` →
`w2d8e1f4a6c3` yoluyla yükseltti. 2026-10-07 cutover'ı `w2d8e1f4a6c3` →
`x1f3a9c5e7b2` migration'ını başarıyla tamamladı.
