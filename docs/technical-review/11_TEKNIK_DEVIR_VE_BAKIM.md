# 11 — Teknik Devir ve Bakım

| Alan | Değer |
|---|---|
| Kaynak (incelenen) | `origin/assistant-v2-full` @ `f796107fa6ab42096065a02d4724ec7e8d22f608` (3547 izlenen dosya) |
| Belgelenmiş production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` (`SOURCE_OF_TRUTH.md:12`) |
| Hazırlanma tarihi | 2026-10-11 |

---

## 1. Depo yapısı

| Yol | İçerik | Not |
|---|---|---|
| `app/` | Flask uygulaması: 1001 `.py`, 427 Jinja2 şablonu | Modüller: `auth`, `account`, `admin`, `performance`, `institutional`, `communication`, `support`, `file_center`, `portal`, `dashboard`, `executive_summary`, `ai`, `ai_agent`, `api/mobile`, `pwa`, `settings_center`, `modules/strategic_performance*` |
| `app/services/` | İş mantığı (153 giriş, alt paketler dahil) | En büyük dizin |
| `app/bootstrap/` | App factory hattı, route kaydı, şema sözleşmesi | `application_bootstrap.py`, `route_bootstrap.py`, `schema_contract.py` |
| `app/security/` | CSRF, CAPTCHA, parola, TCKN şifreleme, rate limit, başlangıç denetimi | — |
| `migrations/` | Alembic (`versions/` 80 revizyon) + `migrations/sql/` 19 ham SQL | Head `x1f3a9c5e7b2` |
| `sql/` | Tarihli onarım/şema SQL dosyaları (22 dosya) | Kullanım durumu belgelenmemiş |
| `config/` | JSON politika/hiyerarşi kural dosyaları; `config/quality/` kalite kapısı yapılandırması ve teknik borç kaydı | `config/quality/bys360_technical_debt_registry.json` |
| `scripts/` | `release/` (paketleme), `quality/` (55 kalite kapısı), `windows/` (27 PowerShell), `security/`, `local/`, `scheduled/`, `archive/` (228 dosya) | Kanonik release: `scripts/release/build_bys360_safe_release.py` (`scripts/README.md`) |
| `tests/` | 575 `test_*.py` (§4) | `pytest.ini` |
| `mobile_flutter/bys360_mobile_native/` | Flutter istemci | Release paketine girmez |
| `docs/` | `current_state/` (20 numaralı belge + README, FACTS, tutarlılık matrisi; 2026-09-02), `handover/`, `quality/`, `governance/`, `technical-review/`, `architecture/`, `archive/` (217) | Güncel kimlik için `SOURCE_OF_TRUTH.md` |
| `reports/` | `quality/` (coverage baseline, debt envanterleri), `security/`, `architecture/`, `archive/` | — |
| `docker/`, `Dockerfile`, `docker-compose.yml` | Gunicorn + örnek nginx; yerel/pilot profil | — |
| `deployment/` | Dosya Merkezi Linux cron örneği | — |
| `seeds/` | Sahte/demo veri (`fake_seed.py`) | Canlıda çalıştırılmaz (`CONTRIBUTING.md:69-77`) |
| `.codex/agents/` | Teknik borç ajan yapılandırmaları (4 dosya) | `AGENTS.md` kuralları |
| Kök | `run.py` (yerel), `run_server.py` (Waitress), `wsgi.py`, `config.py`, `alembic.ini`, `requirements*.txt`, `requirements.lock`, `pyproject.toml`, `pytest.ini` | — |

Kök yönetişim belgeleri: `SOURCE_OF_TRUTH.md`, `STATUS.md`, `ARCHITECTURE.md`, `DEPLOYMENT.md`, `BACKUP_RUNBOOK.md`, `SECURITY.md`, `CONTRIBUTING.md`, `AI_USAGE_POLICY.md`, `AGENTS.md`, `LICENSE`, `NOTICE`.

Gözlem: `scripts/archive/`, `docs/archive/`, `reports/archive/` toplam ~500 dosya tarihsel içerik taşır; `pytest.ini` `archive` dizinlerini test toplamasından hariç tutar (`pytest.ini` `norecursedirs`).

## 2. CI iş akışları

Yalnız iki workflow vardır (`.github/workflows/`).

### 2.1 `bys360-ci.yml` — workflow adı "Run tests", job `quality-gate`

- Tetikleyiciler: push → `main`, `master`, `develop`, `assistant-v2-full`; pull_request → aynı dallar + `docs/ministry-review-readme`; manuel (`bys360-ci.yml:3-8`). Varsayılan dala push tetikleyicisi PR #58 ile eklendi (production sonrası).
- Ortam: `ubuntu-latest`, Python 3.12, `postgres:15` servis konteyneri, `timeout-minutes: 180` (`:11-51`).
- Adımlar (sırayla, `:65-283`):
  1. Checkout (`fetch-depth: 0`), bağımlılık kurulumu (`requirements.txt` + `requirements-dev.txt`).
  2. `scripts/quality/bys360_secret_repo_gate.py --root .` — secret/repo kapısı.
  3. `build_bys360_safe_release.py --audit-only` — release denetimi (iki kez).
  4. `ruff check app config.py wsgi.py run.py scripts tests` — `E,F,I,UP,B,SIM` (`pyproject.toml` `[tool.ruff.lint]`).
  5. `compileall`.
  6. `pytest tests/quality -m "ci_safe"` (Step 1).
  7. `pytest` geniş kapsam: `tests/integration`, `architecture`, `security`, `critical`, `services`, `migrations`, `release`, `communication`, `behavior`, `mobile`, `performance` + adıyla listelenen üst düzey test dosyaları, coverage XML ile (Step 2, `:194-195`).
  8. Geçici PostgreSQL 15 DB oluşturma + `bys360_postgres_migration_integrity_gate.py` (boş DB → upgrade → head eşleşmesi → ikinci upgrade no-op → şema introspeksiyonu).
  9. `bys360_coverage_ratchet.py` — coverage tabanı.
  10. `mypy app tests scripts --ignore-missing-imports`.
  11. `bys360_ops_audit.py --mode ci --max-print 0 --max-broad-except 2064`.
  12. `bys360_quality9_ci_gate.py` — CI sözleşme kapısı.
  13. `ruff --select E9,F63,F7,F82` sağlık kontrolü.
  14. `pip_audit -r requirements.txt` — bağımlılık zafiyet denetimi.
  15. `reports/quality` artifact yüklemesi.
- Coverage: tek uygulama noktası ratchet'tir; taban `combined_pct=27.62`, tolerans 0.5 → etkin eşik 27.12 (`reports/quality/coverage_baseline.json`; `SOURCE_OF_TRUTH.md:143-150`). Son belgelenen ölçüm 42.1228% (2026-09-23, tarihli snapshot, `SOURCE_OF_TRUTH.md:145`). Taban otomatik yükseltilmez.
- Kapsam dışı: `tests/load/` (Locust betikleri, `test_*.py` yok), Flutter testleri.
- Gözlem: Workflow yorumu "90 minutes" bütçesinden söz ederken değer `180`'dir (`bys360-ci.yml:30-32`); yorum/değer tutarsızlığı.

### 2.2 `bys360-score100-quality-gate-v1.yml` — "BYS360 Quality Assurance Gate V1", job `score100-quality-gate`

- Tetikleyiciler: push → `assistant-v2-full`; pull_request → `master`, `main`, `assistant-v2-full`, `docs/ministry-review-readme`; manuel.
- Ortam: `windows-latest`, Python 3.12.
- Adım: `scripts/windows/repair_bys360_score100_quality_gate_v1.ps1 -Mode gate -RunPipAudit -RunRuff` → `scripts/quality/bys360_score100_quality_gate_v1.py`. Kontroller: bağımlılık pinleri, Android imzalama, Git'te izlenen `.env`, secret desenleri, TCKN şifreleme, exec route'ları, kopya endpoint test-skip'i, app factory kopya kuralları (opsiyonel), wildcard import, geniş `except`, ruff, repo şekli (`bys360_score100_quality_gate_v1.py:364-1154`). Rapor `reports/quality/score100_quality_gate_v1/`.

### 2.3 Son belgelenen CI kanıtı

Production SHA için `Run tests` run `37619199191` ve `Quality Assurance Gate V1` run `37619199193` SUCCESS (`SOURCE_OF_TRUTH.md:29-31,89-90`). **Dal ucu (`f796107f`) için CI sonucu bu belgede doğrulanmadı.**

## 3. Kalite script'leri (seçme)

| Script | Amaç |
|---|---|
| `scripts/quality/bys360_secret_repo_gate.py` | Secret / repo hijyeni |
| `scripts/quality/bys360_postgres_migration_integrity_gate.py` | Gerçek PostgreSQL 15 üzerinde migration bütünlüğü |
| `scripts/quality/bys360_coverage_ratchet.py` | Coverage gerileme kapısı |
| `scripts/quality/bys360_ops_audit.py` | `print`, geniş `except` sayısı vb. operasyon denetimi |
| `scripts/quality/bys360_quality9_ci_gate.py` | CI workflow sözleşmesi |
| `scripts/quality/bys360_score100_quality_gate_v1.py` | Score100 kalite kapısı |
| `scripts/quality/bys360_technical_debt_registry_gate.py` | Teknik borç kaydı doğrulayıcı (`docs/governance/BYS360_TECHNICAL_DEBT_POLICY.md`) |
| `scripts/quality/bys360_authorization_matrix.py` | Yetki matrisi raporu (`reports/quality/BYS360_AUTHORIZATION_MATRIX_V1.json`) |
| `scripts/release/build_bys360_safe_release.py`, `build_bys360_wheelhouse.py`, `scan_bys360_release_secrets.py` | Deterministik paket, wheelhouse, paket secret taraması |

`scripts/quality/` altında 55 dosya vardır; çoğu fazlara özgü (`*_p3b_v2.py`, `*_phase3c_*` vb.) kapılardır. Hangilerinin hâlâ kullanımda olduğu belgelenmemiştir. Teknik borç kaydı (`config/quality/bys360_technical_debt_registry.json`) 14 öğe içerir; tamamı `CLOSED` (bu belgede sayıldı). Kaydın kendi `legacy_ledger` bloğu eşlenemeyen tarihsel bir defteri ayrıca korur (`BYS360_TECHNICAL_DEBT_POLICY.md:8-15`).

## 4. Test organizasyonu

| Dizin | `test_*.py` | CI'da | Not |
|---|---:|---|---|
| `tests/quality/` | 70 | Yalnız `ci_safe` işaretliler (Step 1) + 1 dosya adıyla | — |
| `tests/architecture/` | 76 | Evet | Mimari/statik sözleşmeler |
| `tests/security/` | 95 | Evet | Yetki sözleşmeleri (B1-F1, K5, F06–F09, P57 vb.) |
| `tests/services/` | 86 | Evet | — |
| `tests/behavior/` | 110 | Evet | Gerçek `app.services` import eder |
| `tests/performance/` | 44 | Evet | Performans modülü (yük testi değil) |
| `tests/integration/` | 17 | Evet | — |
| `tests/migrations/` | 15 | Evet | In-memory SQLite üzerinde upgrade/downgrade |
| `tests/communication/` | 15 | Evet | Statik/AST sözleşmeleri |
| `tests/critical/` | 6 | Evet | — |
| `tests/release/` | 4 | Evet | — |
| `tests/mobile/` | 1 | Evet | — |
| `tests/` (üst düzey) | 36 | Adıyla listelenenler | `tests/architecture/test_ci_test_selection_blind_spot_contract.py` dışarıda kalanı yakalamak için (`bys360-ci.yml:189-193`) |
| `tests/load/` | 0 | Hayır | Locust betikleri |

İşaretleyiciler: `ci_safe`, `live`, `realdb`, `slow`, `mobile`, `uat`, `source_smoke`, `legacy_integration`; `--strict-markers` (`pytest.ini`). Toplam 575 test dosyası; test sayısı (fonksiyon düzeyi) bu belgede toplanmadı. PR #47 yerel kaydında migration/behavior paketi 323, release/security paketi 126 test PASS raporlanmıştır (`SOURCE_OF_TRUTH.md:99-102`).

## 5. Testleri yerelde çalıştırma

Kaynak: `CONTRIBUTING.md:79-109`, `README.md` §"Test ve Kalite Kontrol".

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt      # ruff 0.16.0, mypy 2.3.0, pytest 9.0.3, pytest-cov 7.1.0, pip-audit 2.10.1
python -m compileall -q app config.py wsgi.py run.py scripts
python scripts\quality\bys360_secret_repo_gate.py --root .
python -m ruff check app config.py wsgi.py run.py scripts tests
python -m mypy app tests scripts --ignore-missing-imports --no-error-summary
python -m pytest tests/quality -m "ci_safe" --tb=short -q
python -m pytest tests/integration tests/architecture tests/security tests/critical --tb=short -q
```

- CI'daki Step 2 komutunun birebir hali `bys360-ci.yml:195`'tedir; `CONTRIBUTING.md:81` CI dosyasını tek doğru kaynak sayar.
- PostgreSQL migration kapısı için tek kullanımlık bir PostgreSQL 15 veritabanı ve `BYS360_REALDB_MIGRATION_TEST_URL` gerekir (`bys360-ci.yml:246-249`); kapı, host/DB adı korumalarını kendi içinde zorunlu tutar.
- Proje kuralları (`AGENTS.md`) Windows'ta `C:\bys360\project\.venv\Scripts\python.exe` yorumlayıcısını ve sıralı doğrulamayı (hedefli ruff → compile → hedefli testler → toplama → tam paket → coverage → dependency audit) öngörür; ayrıca test toplamanın testlerin geçtiği anlamına gelmediğini vurgular.
- CI "full step 2" süresi bir ölçümde ~1 saat 5 dakika olarak kaydedilmiştir (`bys360-ci.yml:25-31`).

## 6. Dal koruması (belgelendiği kadarıyla)

- `assistant-v2-full` (varsayılan dal) ve `docs/ministry-review-readme` GitHub ruleset'leri ile korunur: silme ve force push engelli; değişiklik yalnız pull request ile; zorunlu kontroller `quality-gate` ve `score100-quality-gate` (`SOURCE_OF_TRUTH.md:78-80`).
- Production tag'leri yönetişimde değişmez kabul edilir, ancak ayrı bir tag ruleset'i doğrulanmadığından teknik olarak engellendiği iddia edilmez (`SOURCE_OF_TRUTH.md:197-208`).
- `main` production kaynağı değildir; production SHA `main` soyunda değildir (`SOURCE_OF_TRUTH.md:76`).
- Onay sayısı (required reviewers), CODEOWNERS, imzalı commit zorunluluğu: **belgelenmemiş**. Repoda `.github/CODEOWNERS` yoktur.
- Bu belge ruleset ayarlarını GitHub üzerinden doğrulamamıştır.

## 7. Değişiklik ve yayın disiplini (belgelenen)

- Odaklı testler → tam kalite kapıları → commit → push → exact-head CI → deterministik paket → kontrollü deployment → canlı kabul (`docs/current_state/07_..._Surdurulebilirlik_Raporu.md:154-156`, `BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md:83` kaynaklı).
- Production kimliği branch ucu değil, exact SHA + annotated tag; her cutover'da `SOURCE_OF_TRUTH.md` güncellenir (`SOURCE_OF_TRUTH.md:182-183`).
- Release kaynağı seçimi insan kararıdır (`HUMAN_DECISION_REQUIRED`, `DEPLOYMENT.md:147-153`).
- AI destekli geliştirme araçları kod kabul, merge, production ve deployment kararı veremez; deploy/cutover/DB/migration işlemleri açık insan talimatı ister (`AI_USAGE_POLICY.md` §1, §3).
- Teknik borç: kanıta dayalı kayıt, kapanış için kalite kapısı (`docs/governance/BYS360_TECHNICAL_DEBT_POLICY.md`; `AGENTS.md`).
- Yeni script açmak yerine mevcut altyapının genişletilmesi beklenir (`CONTRIBUTING.md:123-125`).

## 8. Bakım sorumlulukları

Belgelenen:

- Rutin kontrol listesi (günlük: `/login`, `/healthz`, 5xx, mail görevleri, loglar; haftalık: yedek, disk, log rotasyonu, bekleyen migration, rol değişikliği audit'i; aylık: release preflight, yetki matrisi örnek testi, kritik akışlar, temizlik) — `docs/handover/BYS360_BAKIM_RUNBOOK.md:1-26`. Kontrolleri **kimin** yapacağı yazılı değildir.
- Risk planı "Tek geliştirici bilgisi" ve "Firma/kişi bağımlılığı"nı kritik risk olarak listeler (`docs/handover/BYS360_RISK_VE_SUREKLILIK_PLANI.md:5-13`); 2026-09-02 devir raporu da bus factor riskini not eder (`docs/current_state/07_...md:150`).
- İş kurallarının bir kısmının yalnız kodla değil iş sahibiyle doğrulanması gerektiği belirtilir (`docs/current_state/08_..._Kurumsal_Bagimsizlik_Dokumani.md:30`).

**Belgelenmemiş:** İsimli/rol bazlı sistem sahibi, uygulama sorumlusu, DB yöneticisi, güvenlik olay sorumlusu, nöbet/eskalasyon zinciri, hizmet seviyesi (SLA), yedek doğrulama sorumlusu, bağımlılık güncelleme takvimi, secret rotasyon takvimi. 30/60/90 gün bakım planının varlığı `BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md` §24'e atfedilir ancak içeriği 2026-09-02 incelemesinde okunmamıştır (`docs/current_state/07_...md:152`); bu belgede de doğrulanmadı.

## 9. Devralan ekip için ilk adımlar (belgelerden derlenmiş)

1. `SOURCE_OF_TRUTH.md` ile production SHA/tag/migration head'i doğrulayın; dal ucunun production olmadığını not edin.
2. `docs/handover/README.md` okuma sırasını izleyin; "CURRENT" etiketli eski belgelerin tarihsel olduğunu unutmayın (`SOURCE_OF_TRUTH.md:166-180`).
3. Yerel kurulum + §5 komutları; `flask db heads` ile tek head (`x1f3a9c5e7b2`) kontrolü.
4. Production SHA ile dal ucu arasındaki 18 PR'ı (çoğu yetki daraltması) bir sonraki aday olarak değerlendirin (`03_MODUL_ENVANTERI.md` §4, `04_ROL_VE_YETKI_MIMARISI.md` §9).
5. `09_KURULUM_ISLETIM_IZLEME_YEDEK_ROLLBACK.md` §10'daki eksikler için kurumsal karar alın (yedek, RPO/RTO, izleme, sorumluluklar).

## 10. Açık noktalar

1. Dal ucu için CI sonucu ve test geçme durumu bu belgede doğrulanmadı.
2. Flutter istemcisi CI dışında; derleme/yayın süreci yok.
3. 55 kalite script'inden hangilerinin aktif olduğu belirsiz; arşiv dizinleri büyük.
4. Sorumluluk ataması ve nöbet süreci belgelenmemiş.
5. Dal koruması yalnız `SOURCE_OF_TRUTH.md` beyanına dayanıyor; CODEOWNERS/onay sayısı bilinmiyor.
