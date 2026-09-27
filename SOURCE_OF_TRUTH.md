# BYS360 Source of Truth

Bu belge tek bir soruya kısa ve doğrulanabilir cevap verir: **Bugün hangi branch ve hangi
exact commit SHA production gerçeğidir?**

Son doğrulama: 2026-09-24.

## 1. Current Production Identity

| Alan | Değer | Kanıt |
|---|---|---|
| Stable production source branch | `assistant-v2-full` | Branch ucu aşağıdaki SHA'dır (`git ls-remote origin refs/heads/assistant-v2-full`). |
| Verified production SHA | `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6` | `assistant-v2-full` ucu; GitHub Actions run `35823128265` bu SHA'yı checkout etmiş ve başarıyla tamamlanmıştır. |
| Deployment date | 2026-09-23 | İnsan operatör tarafından yürütülen cutover kaydı. |
| Production migration head | `v1a2d3e4f5b6` | Bu SHA'daki Alembic migration grafiğinin tek head'i (77 revizyon). CI'daki PostgreSQL 15 migration integrity gate, boş bir veritabanından bu head'e yükseltmeyi doğrulamıştır. |

**Production source of truth, repository'nin varsayılan (default) branch'i değil, doğrulanmış
exact commit SHA'dır.** Branch'ler bu SHA'ya ulaşmanın yoludur. Bir branch'in ucu ilerlese bile,
yeni bir SHA doğrulanıp insan kararıyla canlıya alınana kadar production kimliği yukarıdaki SHA'dır.

Not: Canlı veritabanının revizyonu bu belge hazırlanırken doğrudan sorgulanmamıştır. Yukarıdaki
migration head, production SHA'nın beklediği şema revizyonudur.

## 2. Repository Branch Roles

| Branch | Rol |
|---|---|
| `assistant-v2-full` | Doğrulanmış production kaynak branch'i; production kaynak kodu soy hattı. |
| `docs/ministry-review-readme` | Dış/kurumsal teknik inceleme ve dokümantasyon yüzeyi; repository'nin varsayılan (default) branch'i. Production branch'i değildir: production SHA'sının üzerine inceleme dokümantasyonu ve CI tetikleyici hizalaması ekler. |
| `main` | Production source of truth değildir. Ayrı bir tarihsel/entegrasyon soy hattı içerir; production SHA, `main`'in soyunda yer almaz. |

`assistant-v2-full` ve `docs/ministry-review-readme` GitHub ruleset'leri ile korunur: silme ve
force push engellidir; değişiklik yalnız pull request ile ve `quality-gate` ile
`score100-quality-gate` zorunlu kontrolleri geçerek girer.

## 3. Verified Quality Evidence

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

Bu dosyalar kendi içlerinde "CANONICAL" veya "CURRENT" ifadeleri taşısa da, güncel production
kimliği açısından yerini bu belgeye bırakmıştır. Tarihsel kanıt olarak olduğu gibi korunurlar;
operasyonel içerikleri (runbook adımları vb.) ayrıca değerlendirilmelidir.

**SOURCE_OF_TRUTH.md, güncel production kimliği için kısa canonical giriş noktasıdır.** Yeni bir
production cutover yapıldığında bu belge güncellenir.

## 6. Immutable Production Tag

| Alan | Değer |
|---|---|
| Production tag | `bys360-prod-2026.09.23-1ea5c5dc` |
| Tag type | annotated |
| Tag object SHA | `1c6d9859efe856191f2f60245008ab6eb90f638c` |
| Target production SHA | `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6` |

Amaç: BYS360'ın 2026-09-23 doğrulanmış production kimliğini, kurumsal inceleme ve teknik devir
için sabit bir Git referansı olarak işaretlemek.

Tag object SHA, tag nesnesinin kendisidir; tag'in işaret ettiği commit (peeled target) yukarıdaki
production SHA'dır. Tag, review branch'inin merge commit'ine değil, doğrudan production SHA'sına
bağlıdır.

Bu tag BYS360 yönetişiminde immutable production identity olarak kabul edilir; taşınmamalı ve
silinmemelidir. Şu anda ayrı bir GitHub tag koruma kuralı (tag ruleset) doğrulanmadığından,
GitHub'ın tag güncelleme veya silme işlemlerini teknik olarak engellediği iddia edilmez.
