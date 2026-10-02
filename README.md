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
ölçümüdür. Güncel production sürümü (`a5bd8a38…`, 2026-09-29) için ayrı bir coverage anlık
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
- **Rollback tasarımı**: her cutover öncesi kod ve veritabanı yedeği alınır; geri dönüş,
  ayrı bir script (`scripts/windows/rollback_bys360_live_release_v1.ps1`) ile
  varsayılan olarak önce DRY-RUN (yalnızca plan) modunda çalışır, gerçek uygulama için
  açık `-Apply` bayrağı gerektirir; `.env`, `instance/`, `logs/`, `uploads/` ve `reports/`
  her koşulda korunur ve asla üzerine yazılmaz (bkz. `BACKUP_RUNBOOK.md`).

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
| SHA | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` |
| Production tag | `bys360-prod-2026.09.29-a5bd8a38` |
| Dağıtım tarihi | 2026-09-29 |
| Migration head | `w2d8e1f4a6c3` (`v1a2d3e4f5b6` → `w1c5a7d2e9b4` → `w2d8e1f4a6c3`) |
| GitHub Release | BYS360 Production — 2026-09-29 (a5bd8a38) |
| Önceki production SHA | `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9` (tag `bys360-prod-2026.09.28-67f2a29d`, migration head `v1a2d3e4f5b6`) |

Bu, en son canlıya alma (deployment) sırasında doğrulanan kaynak kod kimliğidir. Bu SHA, PR #15'in
merge commit'idir; ağacı, iki zorunlu CI iş akışının (BYS360 Quality Assurance Gate V1 ve
quality-gate) başarıyla çalıştığı PR #15 head'inin ağacıyla birebir aynıdır (bkz.
`SOURCE_OF_TRUTH.md` §3).

- **Cutover öncesi kontrollü maintenance:** `flask runtime-schema provision` gerekli 8 eksik
  kolonu sağladı; ardından salt okuma `flask runtime-schema check` 15/15 OK verdi.
- **Cutover ve cutover sonrası doğrulama:** deployment exit code 0, migration PASS, schema
  contract PASS, Dosya Merkezi 19/19, service/process binding PASS, local health, readiness ve
  public health HTTP 200, smoke PASS, security-critical bulgu 0. `/versionz`:
  `source_sha = a5bd8a389f2a978e2a07bb30d58a622bddea82df`, `migration_head = w2d8e1f4a6c3`,
  `schema_error_count = 0`.

Branş koruması tarafından zorunlu kılınan teknik kontrol bağlamı (required check context) hâlâ
tarihsel/kararlı ad olan `score100-quality-gate`'tir -- yukarıdaki "BYS360 Quality Assurance
Gate V1" yalnızca insan-okur iş akışı adıdır.

**Varsayılan dal ve production soy hattı (default / production lineage branch):**
`assistant-v2-full` — repodaki güncel varsayılan (default) daldır; production SHA bu dalın
soyundadır. Dalın ucu, insan kararıyla cutover yapılana kadar production değildir; bir sonraki
adayı taşır (bkz. `SOURCE_OF_TRUTH.md` §1.1).

**`main`:** production kaynak doğruluğu (source of truth) değildir. PR #1 birleştirmesi nedeniyle
ayrı bir tarihsel/entegrasyon soy hattı (lineage) içerir; production kimliği her zaman yukarıdaki
tam SHA'dır.

## İnceleme Rehberi (Review Guidance)

Dış teknik incelemeciler için:

- **Kaynak kod:** canlıdaki kaynak kodu birebir incelemek için `bys360-prod-2026.09.29-a5bd8a38`
  tag'ini; güncel uygulama hattını ve bir sonraki adayı incelemek için varsayılan dal olan
  `assistant-v2-full`'u (LICENSE, NOTICE ve kurumsal dokümantasyon bu dalda bulunur) kullanın.
- **Kaynak kod ve commit geçmişi:** repoyu klonlayıp `git log`, `git blame` ve tam dal/etiket
  listesiyle (`git branch -a`, `git tag`) inceleyin; hiçbir geçmiş yeniden yazılmamıştır
  (`filter-repo`/force-push kullanılmamıştır).
- **CI kanıtı:** GitHub "Actions" sekmesinden yukarıdaki iki zorunlu iş akışının geçmiş
  koşumlarını, hangi tam SHA'yı checkout ettiklerini ve sonuçlarını doğrudan görebilirsiniz.
- **Testler:** `tests/` dizini; hedefli kalite testleri için `tests/quality`, davranış
  sözleşmeleri için `tests/behavior`, release paketleme testleri için `tests/release`.
- **Release/paket kanıtı:** `scripts/release/build_bys360_safe_release.py --verify <zip>`
  komutu ve paketle birlikte üretilen manifest/SHA256 dosyaları.
- **Canlı kaynak anlık görüntüsü (production snapshot):** yukarıdaki "Mevcut Doğrulanmış
  Canlı Kaynak" bölümündeki tam SHA. Doğrulanmış production SHA,
  `bys360-prod-2026.09.29-a5bd8a38` adlı annotated production tag ile işaretlenmiştir; tag,
  yönetişim gereği taşınmaması ve silinmemesi gereken production kimliği olarak kullanılır.
  Önceki production tag'leri (`bys360-prod-2026.09.28-67f2a29d`,
  `bys360-prod-2026.09.23-1ea5c5dc`) tarihçe olarak değiştirilmeden korunur.

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
