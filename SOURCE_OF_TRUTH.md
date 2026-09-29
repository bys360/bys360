# BYS360 Source of Truth

Bu belge tek bir soruya kısa ve doğrulanabilir cevap verir: **Bugün hangi branch ve hangi
exact commit SHA production gerçeğidir?**

Son doğrulama: 2026-09-29 (production cutover'ı 2026-09-29'da yapıldı ve doğrulandı; önceki production kimlikleri §7'de tarihçe olarak korunur).

## 1. Current Production Identity

| Alan | Değer | Kanıt |
|---|---|---|
| Verified production SHA | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` | Yönetişim gereği değişmez (immutable) production kimliği olarak kabul edilen annotated tag `bys360-prod-2026.09.29-a5bd8a38` ile işaretlidir (bkz. §6). Bu commit, `assistant-v2-full` üzerindeki PR #15 merge commit'idir. Ağacı (`a09f1b80ced7d5c587b596fdb3218b44a4caa5b2`), GitHub Actions run `36528716263` ve `36528716201` ile test edilen PR #15 head'inin ağacıyla birebir aynıdır (bkz. §3). |
| Production tag | `bys360-prod-2026.09.29-a5bd8a38` | Annotated tag. Tag nesnesi doğrudan production SHA'sını işaret eder (bkz. §6). GitHub Release: "BYS360 Production — 2026-09-29 (a5bd8a38)". |
| Production lineage branch | `assistant-v2-full` | Production SHA bu branch'tedir. **Branch ucu production kimliği değildir**; uç, sonraki değişikliklerle ilerleyebilir (bkz. §1.1). |
| Deployment date | 2026-09-29 | İnsan operatör tarafından yürütülen cutover kaydı. |
| Production migration head | `w2d8e1f4a6c3` | Bu SHA'daki Alembic migration grafiğinin tek head'i (79 revizyon). Canlı veritabanı revizyonu cutover öncesinde `v1a2d3e4f5b6`, sonrasında `w2d8e1f4a6c3`'tür (yol: `v1a2d3e4f5b6` → `w1c5a7d2e9b4` → `w2d8e1f4a6c3`). |
| Previous production SHA | `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9` | Tag `bys360-prod-2026.09.28-67f2a29d`; migration head `v1a2d3e4f5b6` (bkz. §7). |

**Production source of truth, herhangi bir branch'in ucu değil, doğrulanmış exact commit SHA'dır.**
Bu SHA, BYS360 yönetişiminde taşınmaması ve silinmemesi gereken annotated production tag ile
işaretlidir. Yeni bir SHA doğrulanıp insan kararıyla canlıya alınana ve bu belge güncellenene kadar
production kimliği yukarıdaki SHA'dır.

Cutover öncesi kontrollü maintenance (2026-09-29 cutover'ı için):
- `flask runtime-schema provision` gerekli 8 eksik kolonu sağladı.
- Ardından salt okuma `flask runtime-schema check`: 15/15 OK.

Cutover ve cutover sonrası doğrulama (2026-09-29):
- İnsan kontrollü cutover başarıyla tamamlandı (deployment exit code 0).
- Migration: PASS (`v1a2d3e4f5b6` → `w1c5a7d2e9b4` → `w2d8e1f4a6c3`).
- Schema contract: PASS. Dosya Merkezi tabloları: 19/19. Service/process binding: PASS.
- `/versionz`: `source_sha = a5bd8a389f2a978e2a07bb30d58a622bddea82df`,
  `migration_head = w2d8e1f4a6c3`, `schema_error_count = 0`.
- Local health: HTTP 200. Readiness: HTTP 200. Public health: HTTP 200.
- Smoke kontrolleri: PASS. Security-critical bulgu: 0.
- Ayrıntı: GitHub Release "BYS360 Production — 2026-09-29 (a5bd8a38)" (tag `bys360-prod-2026.09.29-a5bd8a38`).

Önceki cutover doğrulaması (2026-09-28, tarihsel; production `67f2a29d…`):
- İnsan kontrollü cutover başarıyla tamamlandı (`DEPLOY_EXIT_CODE = 0`).
- Cutover sonrasında loopback `/versionz`, çalışan kaynak SHA'nın `67f2a29d…` olduğunu bağımsız olarak doğruladı (release identity PASS).
- `/readyz`: `ready`, `schema_error_count = 0`. Public `/healthz`: 200.
- Dosya Merkezi tabloları: 19/19. Canlı schema-contract kontrolü: PASS.
- Production veritabanı revizyonu cutover öncesinde ve sonrasında `v1a2d3e4f5b6`'dır; migration revizyonu değişmedi.
- Ayrıntı: [docs/quality/BYS360_PRODUCTION_CUTOVER_2026-09-28.md](docs/quality/BYS360_PRODUCTION_CUTOVER_2026-09-28.md).

### 1.1 Candidate Status (2026-09-29)

Production kaydının alındığı noktada (`assistant-v2-full` ucu production SHA'sı ile aynı commit),
canlıya alınmamış ayrı bir uygulama kodu adayı yoktur.

`assistant-v2-full`'a daha sonra merge edilen yalnız dokümantasyon değişiklikleri production
kimliğini değiştirmez. Production kimliği her zaman §1'deki, yönetişim gereği taşınmaması ve
silinmemesi gereken production tag ve exact SHA'dır; varsayılan branch ucunun ileride aldığı değer
değildir. Yeni bir uygulama adayı oluştuğunda bu
bölüm tarihli bir anlık görüntü olarak yeniden doldurulur.

Bilinen şema sınırlaması
([docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md](docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md)):
2026-09-28 production sürümüne (`v1a2d3e4f5b6`) kadar boş veritabanında `flask db upgrade` her
ORM tablosunu üretmiyordu. Güncel production sürümünde (`w2d8e1f4a6c3`) sıfırdan kurulum iki ayrı
adımdır:
- `flask db upgrade`, boş bir PostgreSQL 15 veritabanında 164 ORM tablosunu ve 2061 ORM kolonunu
  üretir. ORM tablolarını üreten adım budur.
- `flask runtime-schema provision`, Alembic/ORM migration kapsamı dışında kalan 15 runtime-schema
  grubunu kontrollü bir maintenance komutu olarak sağlar.

Bu iki adımlı kurulum scratch/clean-room PostgreSQL 15 doğrulamasından geçti. Felaket kurtarmada
birincil yöntem hâlâ onaylı PostgreSQL yedeğini restore etmektir.

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

Current production (`a5bd8a38…`). Production commit'inin ağacı, aşağıdaki run'ların test ettiği
PR #15 head'i `5a2c254980275839d133c3796b14ca42b36de13d` ile aynıdır. Run'lar 2026-09-29'da
`pull_request` olayıyla çalıştı.

| Kontrol | Sonuç |
|---|---|
| `quality-gate` (run `36528716263`, job `109277338643`) | PASS |
| Secret/repository gate, safe release audit | PASS |
| Ruff (full-select ve syntax/import sanity), compile | PASS |
| Quality, integration ve architecture testleri | PASS |
| PostgreSQL 15 migration integrity (kritik kolon, ORM parity ve runtime-schema adımları dahil) | PASS |
| Coverage ratchet | PASS |
| mypy (service layer) | PASS |
| Operations audit, Quality 9 CI contract | PASS |
| Dependency vulnerability audit | PASS |
| `score100-quality-gate` (run `36528716201`) | PASS |

Adım sonuçları GitHub Actions'ın herkese açık API'sinden doğrulanabilir.

### 3.1 Önceki production kanıtı (tarihsel, `67f2a29d…`)

Production commit'inin ağacı, aşağıdaki run'ların test ettiği PR #13 head'i
`1cdd75f54324de20bdfed1faeb2e2d53a8bf0cb4` ile aynıdır. Run'lar 2026-09-28'de `pull_request`
olayıyla çalıştı.

| Kontrol | Sonuç |
|---|---|
| `quality-gate` (run `36395443907`, job `108840616146`) | PASS |
| Secret/repository gate, safe release audit | PASS |
| Ruff (full-select ve syntax/import sanity), compile | PASS |
| Quality, integration ve architecture testleri | PASS |
| PostgreSQL 15 migration integrity (kritik kolon kontrolü dahil) | PASS |
| Coverage ratchet | PASS |
| mypy (service layer) | PASS |
| Operations audit, Quality 9 CI contract | PASS |
| Dependency vulnerability audit | PASS |
| `score100-quality-gate` (run `36395443908`) | PASS |

Adım sonuçları GitHub Actions'ın herkese açık API'sinden doğrulanabilir.

### 3.2 Önceki production kanıtı (tarihsel, `1ea5c5dc…`)

GitHub Actions run `35823128265`, `quality-gate` işi, 2026-09-23, SHA `1ea5c5dc…`:

| Kontrol | Sonuç |
|---|---|
| quality-gate (iş) | PASS |
| Ruff (full-select ve syntax/import sanity) | PASS |
| mypy | PASS |
| PostgreSQL 15 migration integrity | PASS |
| Coverage ratchet | PASS |
| Dependency vulnerability audit | PASS |
| Secret/repository gate | PASS |

Adım sonuçları GitHub Actions'ın herkese açık API'sinden doğrulanabilir. İş akışında hata
maskeleyen yapı (`continue-on-error` vb.) yoktur.

| Coverage değeri | Anlam |
|---|---|
| Ölçülen combined coverage: **42.1228%** | GitHub Actions run `35823128265` quality-gate job logunda (job `107059056728`) doğrulanmış CI measurement; bu SHA üzerinde ölçülen anlık değerdir. |
| Kayıtlı ratchet baseline: **27.62%** | `reports/quality/coverage_baseline.json` içindeki regression floor. |
| Etkin eşik: **27.12%** | Baseline eksi 0.50 puan tolerans. Coverage ratchet adımının PASS olması, ölçümün bu eşiğin üzerinde olduğunu mekanik olarak kanıtlar. |

42.1228% yeni baseline, garanti edilen minimum, coverage hedefi veya `fail_under` değeri
değildir. Baseline otomatik yükseltilmez; yükseltme ayrı, insan tarafından incelenen bir işlemdir.

## 4. Release and Rollback Identity

- **Exact SHA:** canlıya alınan paket, üretildiği tam commit SHA'sı ile tanımlanır.
- **Deterministik release paketi:** tek yetkili builder `scripts/release/build_bys360_safe_release.py`
  yalnız Git'in takip ettiği dosyalardan paket üretir.
- **Dosya manifestosu ve SHA256 doğrulaması:** paketle birlikte manifest ve SHA256 listesi
  üretilir; `--verify` modu eksik, yasaklı veya fazla dosya ya da SHA256 uyuşmazlığında FAIL verir.
- **Aday hazırlığı ve shadow veritabanı provası:** paket, canlı servise dokunulmadan ayrı bir aday
  dizinine açılır; migration atılabilir bir shadow veritabanında prova edilir.
- **İnsan kontrollü cutover:** canlıya geçiş insan operatör tarafından yürütülür.
- **Rollback:** cutover öncesi kod yedeği ve veritabanı yedeği alınır; kod geri dönüş script'i
  varsayılan olarak DRY-RUN (yalnız plan) modunda çalışır.

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
| Production tag | `bys360-prod-2026.09.29-a5bd8a38` |
| Tag type | annotated |
| Tag object SHA | `4a9db6862e87ec6ea1f7bbb610d4e80e1a980584` |
| Target production SHA | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` |

Amaç: BYS360'ın 2026-09-29 doğrulanmış production kimliğini, kurumsal inceleme ve teknik devir
için sabit bir Git referansı olarak işaretlemek.

Tag object SHA, tag nesnesinin kendisidir; tag'in işaret ettiği commit (peeled target) yukarıdaki
production SHA'dır. Tag, bir branch adına veya sonraki bir dokümantasyon commit'ine değil,
doğrudan production SHA'sına bağlıdır. Tag mesajı dağıtım tarihini, kaynak SHA'yı ve migration
head'ini kaydeder.

Production tag'leri BYS360 yönetişiminde immutable production identity olarak kabul edilir;
taşınmamalı ve silinmemelidir. Önceki tag'ler değiştirilmeden korunur:

- `bys360-prod-2026.09.28-67f2a29d` (tag nesnesi `572d5de0bd6f5a527c340c4a558c35e43b2317bc` →
  `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9`). Tag mesajı dağıtım tarihini, migration head'ini,
  CI run'larını ve release paketinin SHA-256 değerini kaydeder.
- `bys360-prod-2026.09.23-1ea5c5dc` (tag nesnesi `1c6d9859efe856191f2f60245008ab6eb90f638c` →
  `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6`).

Şu anda ayrı bir GitHub tag koruma kuralı (tag ruleset) doğrulanmadığından, GitHub'ın tag
güncelleme veya silme işlemlerini teknik olarak engellediği iddia edilmez.

## 7. Production History

| Dağıtım tarihi | Production SHA | Tag | Durum |
|---|---|---|---|
| 2026-09-29 | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` | `bys360-prod-2026.09.29-a5bd8a38` | **Güncel production** |
| 2026-09-28 | `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9` | `bys360-prod-2026.09.28-67f2a29d` | Önceki production (tarihçe). Cutover kaydı: [docs/quality/BYS360_PRODUCTION_CUTOVER_2026-09-28.md](docs/quality/BYS360_PRODUCTION_CUTOVER_2026-09-28.md). |
| 2026-09-23 | `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6` | `bys360-prod-2026.09.23-1ea5c5dc` | Önceki production (tarihçe). Cutover öncesindeki canlı salt okuma doğrulaması bu sürümü anlatır: [docs/quality/BYS360_LIVE_READONLY_VALIDATION_2026-09-28.md](docs/quality/BYS360_LIVE_READONLY_VALIDATION_2026-09-28.md). |

2026-09-23 ve 2026-09-28 sürümlerinin migration head'i `v1a2d3e4f5b6`'dır; 2026-09-28 cutover'ı
veritabanı revizyonunu değiştirmedi. 2026-09-29 cutover'ı veritabanı revizyonunu
`v1a2d3e4f5b6` → `w1c5a7d2e9b4` → `w2d8e1f4a6c3` yoluyla `w2d8e1f4a6c3`'e yükseltti.
