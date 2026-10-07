# BYS360 — Bütünleşik Yönetim Sistemi 360

BYS360, T.C. Kültür ve Turizm Bakanlığı Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı bünyesindeki kurumsal yönetim süreçleri için geliştirilmiştir. Kurum içi yönetim süreçlerini tek merkezde toplayan; personel, performans, iletişim, anket, destek, raporlama, KPI/hedef ve karar destek süreçlerini modüler şekilde yöneten kurumsal dijital yönetim platformudur.

## Lisans ve Hak Sahipliği

BYS360 — Bütünleşik Yönetim Sistemi 360, proprietary / kurumsal bir yazılımdır; açık kaynak lisansı altında sunulmaz.

- **Kurumsal hak sahibi:** T.C. Kültür ve Turizm Bakanlığı / Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı
- **Geliştirici:** Havva Gülsen Özden
- **Eş Geliştirici (Co-developer):** Mustafa Bektaş
- **Proje iletişimi:** bys360@ktb.gov.tr

Copyright © 2026 T.C. Kültür ve Turizm Bakanlığı Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı. Tüm hakları saklıdır.

Kullanım, çoğaltma, değiştirme ve dağıtım koşulları [`LICENSE`](LICENSE) dosyasında, telif bildirimi [`NOTICE`](NOTICE) dosyasında yer alır. Üçüncü taraf ve açık kaynak bileşenler kendi lisanslarına tabidir.

## Ana Modüller

- Personel Yönetimi
- Performans Yönetimi
- İletişim ve Anket Yönetimi
- Dosya Merkezi
- Kurumsal Portal
- Destek / Yardım Merkezi
- Sistem Ayarları ve Yetkilendirme
- AI Karar Destek
- BYS360 Sanal Asistan
- Dashboard ve Raporlama
- Mobil istemci / Flutter altyapısı

## Teknik Özet

- Backend: Python / Flask
- Veritabanı: PostgreSQL; local geliştirme için SQLite kullanılabilir
- Sunum: Waitress / Windows servis veya görev zamanlayıcı yapısı
- Mobil: Flutter istemci altyapısı (PWA/mobil API katmanı `app/api/mobile` altında)
- CI: Ruff, mypy, pytest, pip-audit ve özel secret/security gate kontrolleri

### BYS360 Sanal Asistan (Assistant V2) Mimarisi

Sanal Asistan; serbest metin girişini önce native, deterministik bir güvenlik/kapsam
sınıflandırıcısından (`safety_classifier.py`), ardından yine native bir niyet
yönlendiricisinden (`intent_router.py` + `domain_vocabulary.py`) geçirir. Eşleşen istek,
merkezi bir yetenek kaydı (`capability_registry.py`) üzerinden tek bir yetkilendirme
kapısına (`capability_dispatcher.py`) düşer; yetki kontrolü her zaman ilgili servis
çağrısından **önce** yapılır ve herhangi bir çalışma zamanı hatası "sistem hatası" olarak
kapatılır (sessiz yeniden deneme veya yorum yapma yoktur). Yanıt, ham servis verisini
insan-okur Türkçe metne çeviren ayrı bir sunum katmanından (`response_composer.py`) geçer.
Bu akışın hiçbir adımı harici bir büyük dil modeli servisine bağımlı değildir; mimari,
bunu doğrulayan kendi otomatik testine (`test_assistant_v2_external_ai_absence_contract_v1.py`)
sahiptir.

### Yetkilendirme Modeli

- Menü görünürlüğü tek başına yetki değildir; her backend route ayrıca kendi yetki
  kontrolünü uygular (bkz. `SECURITY.md`).
- Rol tabanlı görünürlük (`role_display.py`, admin/başkan/grup başkanı/mali müşavir/hukuk
  müşaviri vb. kapalı rol sözlüğü) ile modül bazlı politika ayarları (ör. Sanal Asistan'ın
  kendi rol matrisi) ayrı katmanlardır; bir modülün kendi sunum etiketi, merkezi rol
  sözlüğünü değiştirmeden özelleştirilebilir. Örnek: merkezi sözlükte `mali_musavir` →
  "Mali Müşavir" ve `hukuk_musaviri` → "Hukuk Müşaviri" ayrı rollerdir; yalnız Sanal Asistan
  rol matrisi, `mali_musavir` iç rol anahtarını kendi ekranında "Hukuk Müşaviri" etiketiyle
  gösterir. Bu, anahtarı sistem genelinde yeniden tanımlamaz.
- Performans verisi, anket cevapları ve mesaj içerikleri gibi hassas alanlar için ayrı,
  regex/anahtar-kelime tabanlı bir "hassas istek" sınıflandırması vardır; bu sınıflandırma
  eşleştiğinde yanıt üretilmez.

## Local Kurulum

Desteklenen Python sürümü: **3.12** (CI'daki `actions/setup-python@v5` adımı ve `pyproject.toml` `[tool.mypy] python_version` ile aynı).

```powershell
cd C:\bys360\project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
copy .env.example .env
```

`requirements-dev.txt`, CI ile birebir aynı sürümlerde kalite araçlarını (ruff, mypy, pytest, pytest-cov, pip-audit) kurar; production bağımlılıklarından (`requirements.txt`) ayrı tutulur. Bu adım atlanırsa aşağıdaki kalite komutları çalışmaz.

`.env` dosyasını local ortama göre doldurun. Gerçek gizli değerler repoya eklenmez.

## Local Çalıştırma

```powershell
cd C:\bys360\project
.\.venv\Scripts\Activate.ps1
$env:FLASK_ENV = "development"
$env:APP_ENV = "development"
python run.py
```

Alternatif Waitress/local çalıştırma için proje içindeki güncel deployment dokümanına bakın.

## Test ve Kalite Kontrol

Aşağıdaki komutlar gerçek, çalışan komutlardır ve CI'daki (`.github/workflows/bys360-ci.yml`) karşılıklarına dayanır. `requirements-dev.txt` kurulmadan hiçbiri çalışmaz (bkz. yukarıdaki Local Kurulum).

```powershell
# Secret / repo hijyen gate'i
python scripts\quality\bys360_secret_repo_gate.py --root .

# Ruff -- CI'daki asıl gate ("Ruff full-select gate"; pyproject.toml [tool.ruff.lint]
# select = E,F,I,UP,B,SIM kapsamını uygular)
python -m ruff check app config.py wsgi.py run.py scripts tests

# mypy -- CI'daki asıl komut ("Type check service layer" adımı)
python -m mypy app tests scripts --ignore-missing-imports --no-error-summary

# pytest -- CI'daki "Run quality tests" adımının sadeleştirilmiş, coverage'lı hali
python -m pytest tests/quality -m "ci_safe" --cov=app --cov-report=term-missing --tb=short -q
```

Bu, ortak kullanım için doğrudan kopyalanıp çalıştırılabilecek bir alt kümedir; CI'nin gerçekte çalıştırdığı tam pytest komutları (entegrasyon/mimari/servis/migration testlerinin tamamı ve coverage ratchet gate'i dahil) çok daha uzundur ve sık değişebilir, bu yüzden burada birebir kopyalanmamıştır -- birebir güncel hali için `.github/workflows/bys360-ci.yml` tek doğru kaynaktır. Adım adım, açıklamalı kurulum ve kalite kontrol akışı (venv, `.env`, seed data, tam kalite koşumu) için `CONTRIBUTING.md` içindeki "Yeni geliştirici başlangıç akışı" bölümüne bakın.

## Doğrulanmış Coverage Durumu (Verified Coverage Snapshot)

Bu tablo, 2026-09-23 production sürümü (`1ea5c5dc…`) üzerinde alınmış tarihli bir coverage
ölçümüdür. Güncel production sürümü (`cdae2795…`, 2026-10-07) için ayrı bir coverage anlık
görüntüsü bu bölüme işlenmemiştir; güncel production kimliği için aşağıdaki "Mevcut Doğrulanmış
Canlı Kaynak" bölümüne ve `SOURCE_OF_TRUTH.md`'ye bakın.

| Alan | Değer |
|---|---|
| Ölçüm yapılan SHA (2026-09-23 production, tarihsel) | `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6` |
| GitHub Actions run | `35823128265` (`quality-gate` işi) |
| CI ölçüm tarihi | 2026-09-23 |
| Ölçülen combined coverage | 42.1228% |
| Kayıtlı ratchet baseline | 27.62% |
| Tolerans | 0.50 yüzde puan |
| Etkin eşik | 27.12% |

- **42.1228%**, CI'nın bu production SHA üzerinde gerçekten ölçtüğü combined (line + branch)
  coverage değeridir. Tarihli bir ölçüm anlık görüntüsüdür; coverage hedefi, garanti edilen
  alt sınır veya yeni baseline değildir.
- **27.62%**, `reports/quality/coverage_baseline.json` içinde kayıtlı regression floor'dur
  (2026-08-11 ölçümü). `scripts/quality/bys360_coverage_ratchet.py`, CI ölçümünü bu değerin
  0.50 puan altıyla (27.12%) karşılaştırır; bunun altına düşen ölçüm CI'yı başarısız kılar.
- Baseline, mevcut ölçüme otomatik olarak yükseltilmez; yükseltme yalnız ayrı, insan
  tarafından incelenen bir yeniden-baseline işlemiyle yapılır.
- `pyproject.toml` içindeki `fail_under = 18`, Campaign 1B (2026-07-24, ölçüm 18.85%)
  döneminden kalan tarihsel alt sınırdır; güncel regression kapısı yukarıdaki ratchet
  mekanizmasıdır.

## CI ve Deterministik Release Süreci

- CI, iki zorunlu kalite işinden oluşur: `.github/workflows/bys360-ci.yml` (`quality-gate`) ve
  `.github/workflows/bys360-score100-quality-gate-v1.yml` (`score100-quality-gate`). Korunan
  production-kaynak ve teknik inceleme dallarını hedefleyen pull request'ler bu iki zorunlu
  kontrolü otomatik olarak çalıştırır. Daha geniş CI hattı Ruff, mypy, pytest, PostgreSQL
  migration bütünlüğü, coverage ratchet, dependency audit ve projeye özel security/release
  kapılarını kapsar -- ancak bu iki iş akışının HER BİRİ tüm bu araçları ayrı ayrı çalıştırmaz;
  tam kapsam ve güncel tetikleyici koşulları için `.github/workflows/bys360-ci.yml` ve
  `.github/workflows/bys360-score100-quality-gate-v1.yml` tek doğru kaynaktır.
- Yayına alınacak paket, doğrudan klasör zip'lenerek değil, tek yetkili (canonical) builder
  ile üretilir: `scripts/release/build_bys360_safe_release.py`. Kaynak dosya listesi
  yalnızca Git'in takip ettiği dosyalardan gelir (dosya sistemine fallback yoktur); çalışma
  ağacı HEAD ile birebir örtüşmüyorsa build başarısız olur. Üretilen paket, kaynak commit
  SHA'sını (`RELEASE_SOURCE_SHA.txt`), deterministik bir dosya manifestosunu ve her dosya
  için SHA256 özet listesini içerir; aynı SHA'dan yapılan iki bağımsız build birebir aynı
  SHA256'yı üretir (bkz. `DEPLOYMENT.md` bölüm 8, `SECURITY.md` bölüm 4).
- Paket, kendi doğrulama modu (`--verify`) ile ayrıca kontrol edilir: eksik dosya, yasaklı
  yol (`.env`, `tests/`, sertifika/anahtar uzantıları vb.), beklenmeyen ekstra dosya veya
  SHA256 uyuşmazlığı varsa doğrulama FAIL verir.
- Ayrı, bağımsız bir secret tarayıcı (`scripts/release/scan_bys360_release_secrets.py`)
  paketlenmiş her dosyayı tekrar tarar; bu adım builder'ın kendi iç kontrolünden bağımsızdır.
- **Exact-SHA dağıtım modeli**: canlıya alınan her paket, üretildiği tam Git commit SHA'sı ile
  etiketlenir ve iz sürülür; "hangi dal" değil "hangi tam SHA" sorusu tek doğruluk kaynağıdır.
- **Aday hazırlığı (candidate preparation) ve shadow-DB migration provası**: release paketi
  canlıya geçmeden önce, canlı servise hiç dokunmadan ayrı bir aday dizinine açılır, kendi
  sanal ortamını kurar ve veritabanı migration'ını **atılabilir (disposable), yalnızca bu
  amaçla oluşturulup provanın sonunda silinen bir "shadow" veritabanına** karşı prova eder;
  bu adım production veritabanına asla yazmaz (bkz. `docs/handover/CANDIDATE_PREPARATION.md`,
  `docs/handover/DATABASE_MIGRATION.md`).
- **Health/readiness kontrolü**: aday, canlıya alınmadan önce kendi sağlık uç noktası
  (`/healthz`) üzerinden ayağa kalkma testinden geçer; cutover yalnızca bu kontrol
  geçtikten sonra gerçekleşir.
- **Rollback tasarımı**: cutover öncesinde önceki uygulama ağacı ve fresh PostgreSQL
  yedeği korunur. Güncel candidate/cutover mimarisindeki
  `scripts/windows/rollback_bys360_candidate.ps1` uygulama-ağacı geri dönüş yoludur ve
  otomatik Alembic downgrade çalıştırmaz. Canlı migration veritabanı revizyonunu değiştirmişse
  veritabanı geri dönüşü ayrı ve insan kontrollü bir karardır (bkz. `BACKUP_RUNBOOK.md`).

Geliştirme sürecinde AI destekli araçlar kullanılmış olabilir; bu, kod kabulünü tek başına
belirlemez. Her değişiklik repo inceleme akışından, otomatik testlerden, CI kapılarından,
exact-SHA release doğrulamasından ve açık, insan tarafından yürütülen canlıya alma
adımlarından geçer.

AI destekli çalışma `AGENTS.md` ile yönetilir. Repo, açık insan talimatı olmadan otonom
production, veritabanı, migration, secret, push/deploy ve geçmiş yeniden yazma işlemlerini
açıkça engeller ve önerilen değişiklikleri otomatik uygulamadan önce SAFE, CONTROLLED,
REVIEW veya BLOCKED olarak sınıflandırır.

Yapay zekâ kullanım sınırları ve insan denetimi için `AI_USAGE_POLICY.md`; güncel production
kimliği ve branch rolleri için `SOURCE_OF_TRUTH.md` esas kısa referanstır.

## Mevcut Doğrulanmış Canlı Kaynak (Current Verified Production Source)

| Alan | Değer |
|---|---|
| SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` |
| Production tag | `bys360-prod-2026.10.07-cdae2795` |
| Dağıtım tarihi | 2026-10-07 |
| Migration head | `x1f3a9c5e7b2` (`w2d8e1f4a6c3` → `x1f3a9c5e7b2`) |
| Release paketi | `BYS360_FULL_cdae2795.zip` — SHA-256 `48d2572b3630e5c33bbf3cd337e9a9cf39f6b33d9d47aa3d7d17a54ec065f339` |
| Önceki production SHA | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` (tag `bys360-prod-2026.09.29-a5bd8a38`, migration head `w2d8e1f4a6c3`) |

Bu, 2026-10-07 insan kontrollü production cutover'ında doğrulanan kaynak kod kimliğidir.
SHA, PR #47 merge commit'idir. Merge ağacı (`723da65df61f40eefefc12c853ae6177ad6dedb9`), iki zorunlu GitHub Actions
iş akışının başarıyla çalıştığı PR #47 head'i `d529020641f8d4fd7da160b77d2ccab9e586c661` ağacıyla birebir aynıdır.

- **PR/CI:** `Run tests` run `37619199191` SUCCESS; `BYS360 Quality Assurance Gate V1`
  run `37619199193` SUCCESS.
- **Deterministik FULL release:** iki bağımsız build byte-identical; 2.288 dosya;
  59 Windows CPython 3.12 wheel; wheelhouse identity
  `c372cc2512055ef4f48648769bd09ee2e28b194b556a81eb242cdaf7722d4a70`.
- **Candidate preparation:** fresh backup, disposable shadow PostgreSQL rehearsal ve
  candidate health PASS.
- **Cutover:** canlı migration `w2d8e1f4a6c3` → `x1f3a9c5e7b2` PASS; schema contract
  error count 0; Dosya Merkezi 19/19; service/process binding PASS; local health,
  release identity, readiness ve public health PASS; smoke PASS; security-critical 0.
- **`/versionz`:** `source_sha = cdae27953adcbdd8270fe78dcd52351725d3aecd`, `migration_head = x1f3a9c5e7b2`.
- **Cutover sonrası bağımsız kontrol:** Scheduled Task Running; public `/healthz` HTTP 200.
- Ayrıntılı sanitised kanıt:
  `docs/quality/BYS360_PRODUCTION_CUTOVER_2026-10-07.md`.

Branş koruması tarafından kullanılan teknik kontrol bağlamları korunur; production kimliği
branch ucu değil, yukarıdaki exact SHA ve annotated production tag'idir.

**Varsayılan dal ve production soy hattı:** `assistant-v2-full`. Varsayılan dalın ucu ileride
dokümantasyon veya yeni aday değişiklikleriyle ilerleyebilir; bu, production kimliğini tek başına
değiştirmez.

**`main`:** production source of truth değildir. Production kimliği her zaman doğrulanmış exact
SHA ve production tag üzerinden belirlenir.
## İnceleme Rehberi (Review Guidance)

Dış teknik incelemeciler için:

- **Canlı kaynak kodu:** `bys360-prod-2026.10.07-cdae2795` annotated tag'i doğrudan çalışan production commit'i
  `cdae27953adcbdd8270fe78dcd52351725d3aecd` üzerine bağlıdır.
- **Güncel geliştirme hattı:** varsayılan `assistant-v2-full` branch'i. Branch ucu production
  kimliği değildir; `SOURCE_OF_TRUTH.md` esas referanstır.
- **Kaynak kod ve commit geçmişi:** `git log`, `git blame`, `git branch -a` ve `git tag`
  ile tam geçmiş incelenebilir; production kimliği exact SHA ile izlenir.
- **CI kanıtı:** PR #47 head'i `d529020641f8d4fd7da160b77d2ccab9e586c661` için GitHub Actions run
  `37619199191` ve `37619199193` SUCCESS'tir. Production merge ağacı test edilen head ağacıyla
  birebir aynıdır.
- **Testler:** `tests/quality`, `tests/behavior`, `tests/migrations`, `tests/release`,
  `tests/integration`, `tests/architecture` ve ilgili güvenlik testleri.
- **Release kanıtı:** canonical builder
  `scripts/release/build_bys360_safe_release.py`; final FULL ZIP SHA-256
  `48d2572b3630e5c33bbf3cd337e9a9cf39f6b33d9d47aa3d7d17a54ec065f339`.
- **Production cutover kanıtı:**
  `docs/quality/BYS360_PRODUCTION_CUTOVER_2026-10-07.md`.
- **Tarihsel production tag'leri:** `bys360-prod-2026.09.29-a5bd8a38`,
  `bys360-prod-2026.09.28-67f2a29d` ve `bys360-prod-2026.09.23-1ea5c5dc`
  değiştirilmeden tarihçe olarak korunur.
## Teknik İnceleme

BYS360'ın mimari, güvenlik, test/CI, release, canlı sürüm kimliği, teknik borç ve sürdürülebilirlik durumunun toplu teknik incelemesi:

- [BYS360 Teknik İnceleme — 30.09.2026](docs/technical-review/BYS360_TEKNIK_INCELEME_2026-09-30.md)
- [PDF Teknik İnceleme Paketi](docs/technical-review/BYS360_Teknik_Inceleme_Paketi_2026-09-30.pdf)

## Doküman Haritası

- `README.md`: Projeye giriş ve hızlı kurulum
- `ARCHITECTURE.md`: Mimari kararlar ve modül yapısı
- `STATUS.md`: Güncel durum ve son kararlar
- `CONTRIBUTING.md`: Geliştirme kuralları
- `SECURITY.md`: Güvenlik, secret ve paketleme kuralları
- `DEPLOYMENT.md`: Yayına alma ve servis çalıştırma notları
- `BACKUP_RUNBOOK.md`: Yedekleme ve geri dönüş prosedürü
- `SOURCE_OF_TRUTH.md`: Güncel production kimliği ve branch rolleri (kısa canonical referans)
- `AI_USAGE_POLICY.md`: Yapay zekâ kullanım sınırları ve insan denetimi
- `LICENSE`: BYS360 Kurumsal Yazılım Lisansı
- `NOTICE`: Telif ve geliştirici bildirimi

## Kaynak Paket Kuralları

Kaynak pakete şu dosyalar girmez:

- `.git/`
- `.env`, `.env.local`, gerçek secret içeren ortam dosyaları
- `backups/`, `logs/`, local `instance/*.sqlite*`
- `.bak`, `.tmp`, cache ve derleme kalıntıları
- iç içe `project/project/` kopyaları

## Geliştirme İlkesi

Yeni geliştirmeler geçici overlay/hotfix kalıntısı üretmeden, mevcut dosyalar üzerinde normal commit akışıyla yapılır. Tek kullanımlık scriptler ana ağaçta bırakılmaz; gerekiyorsa arşiv branch'i veya dokümante edilmiş `docs/archive/` alanı kullanılır.
