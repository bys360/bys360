# BYS360 DEPLOYMENT.md

Bu dosya BYS360’ın yerel geliştirme, test, canlıya alma ve geri dönüş adımlarını tek yerde toplar. Gizli bilgi, parola, token veya canlı bağlantı değeri içermez.

## 1. Ortamlar

| Ortam | Amaç | Not |
|---|---|---|
| Lokal geliştirme | Kod geliştirme ve hızlı smoke test | Varsayılan port 8000/8003 olabilir. |
| Test / staging | Migration, rol-yetki ve kritik akış denemesi | Canlı veriyle karıştırılmamalıdır. |
| Canlı | Kurumsal kullanım | Windows Görev Zamanlayıcı + Waitress omurgası. |

## 2. Temel bağımlılıklar

- Python 3.12
- PostgreSQL 15 veya lokal geliştirme için SQLite
- Redis, kullanılıyorsa cache / rate-limit / queue için
- Windows Server üzerinde Waitress servis/görev yapısı
- PowerShell 5+ veya PowerShell 7+

## 3. İlk kurulum

```powershell
cd C:\bys360\project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Lokal test için gerçek canlı `.env` kopyalanmaz. `.env.example` üzerinden yeni değerler oluşturulur.

```powershell
Copy-Item .env.example .env
notepad .env
```

## 4. Veritabanı hazırlığı

**Yeni / boş PostgreSQL 15 veritabanı (fresh / clean-room kurulum):** Hedef bağlantı yeni,
boş veritabanına ait olmalıdır; bu adımlar canlı veritabanını yeniden kurma talimatı değildir.
Kurulum sırasıyla iki adımdır; ilk adım başarıyla tamamlandıktan sonra ikinci adım uygulanır:

```powershell
cd C:\bys360\project
.\.venv\Scripts\Activate.ps1
flask db upgrade
flask runtime-schema provision
```

`flask db upgrade` ORM şemasını, `flask runtime-schema provision` ise Alembic/ORM migration
kapsamı dışındaki runtime-schema gruplarını sağlar. Bu iki adımlı kurulumun PostgreSQL 15
scratch/clean-room doğrulaması [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md)'de kayıtlıdır;
güncel üretim kimliği için de bu belge esas alınır. Bu kayıt, production'ın sıfırdan
yeniden kurulduğu anlamına gelmez.

**Felaket kurtarma / production recovery:** Birincil yöntem onaylı PostgreSQL yedeğini
restore etmektir; `flask runtime-schema provision` yedek geri yüklemenin yerine geçmez.
Mevcut veritabanında migration öncesinde mutlaka yedek alınır. Yedek ve ayrı insan kontrollü
DB restore prosedürü için [BACKUP_RUNBOOK.md](BACKUP_RUNBOOK.md) kullanılır.

> **Tarihsel / superseded sınırlama (2026-09-28):** O tarihte `flask db upgrade` boş bir
> veritabanında her ORM tablosunu üretmiyordu (Alembic'siz 30 tablo, yalnız runtime DDL ile
> oluşan 3 tablo, bir şekil uyuşmazlığı). Bu gözlem tarihsel kanıttır; güncel iki adımlı
> fresh kurulumun sınırlaması olarak kullanılmaz. Eski bulgular ve sonraki güncelleme
> [BYS360_SCHEMA_RECOVERY_LIMITATION.md](docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md)
> içinde korunur; güncel durum için o belgenin §7–§8 bölümlerine bakılır.

## 5. Lokal smoke test

```powershell
cd C:\bys360\project
.\.venv\Scripts\Activate.ps1
$env:APP_ENV="development"
python -m compileall app config.py scripts migrations
python run.py
```

Ayrı PowerShell penceresinde:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/login" -UseBasicParsing
```

## 6. Canlıya alma özeti

1. Kod değişikliği temiz branch üzerinde hazırlanır.
2. `python -m compileall app config.py scripts migrations` çalıştırılır.
3. Kritik testler çalıştırılır.
4. Veritabanı yedeği alınır.
5. Dosya yedeği alınır.
6. Migration varsa staging’de denenir.
7. Canlı görev durdurulur.
8. Kod aktarılır.
9. Migration uygulanır.
10. Canlı görev başlatılır.
11. `/login`, `/healthz` ve kritik ekranlar kontrol edilir.

## 7. Canlı yeniden başlatma örneği

Not: `run.py` yalnızca yerel geliştirme içindir (`app.run`, Waitress kullanmaz). Depodaki tek Waitress giriş noktası `run_server.py`dır; `APP_ENV` değeri `production` veya `staging` olduğunda `waitress.serve` çağrılır ve `APP_HOST`, `APP_PORT` (varsayılan 8000), `WAITRESS_THREADS` (varsayılan 8) ortam değişkenlerini kullanır. `.env` dosyası `config.py` tarafından otomatik yüklenir.

```powershell
$ErrorActionPreference = "Stop"
$ProjectRoot = "C:\bys360\project"
$TaskName = "BYS360 Live Waitress 80"

cd $ProjectRoot
.\.venv\Scripts\Activate.ps1

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

$owners = Get-NetTCPConnection -LocalPort 80 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

foreach ($ownerPid in $owners) {
    $p = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -match "python|waitress") {
        Stop-Process -Id $ownerPid -Force
    }
}

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 8
Invoke-WebRequest -Uri "http://127.0.0.1/login" -UseBasicParsing
```

## 7a. Ters proxy arkasında Waitress (`WAITRESS_TRUSTED_PROXY*`)

Waitress varsayılan olarak hiçbir bağlantının proxy başlıklarına güvenmez ve `X-Forwarded-For`, `-Proto`, `-Host`, `-Port` başlıklarını siler. Waitress'in önünde IIS veya başka bir ters proxy varsa bu durumda uygulama:

- istemci yerine proxy'nin IP adresini görür (denetim kaydı ve hız sınırı);
- isteği `http` sanır ve HSTS göndermez;
- dış URL'leri iç host ve portla üretir.

`run_server.py` bu ortam değişkenlerini okur (`app/core/waitress_proxy.py`):

| Değişken | Anlamı |
|---|---|
| `WAITRESS_TRUSTED_PROXY` | Proxy'nin Waitress'e bağlandığı **tek** IP adresi. Boş = güven yok. `*`, liste, ağ veya host adı reddedilir. |
| `WAITRESS_TRUSTED_PROXY_COUNT` | Waitress önündeki proxy katmanı sayısı (1–10, varsayılan 1). |
| `WAITRESS_TRUSTED_PROXY_HEADERS` | Proxy'nin yazdığı başlıklar; yalnız `x-forwarded-for`, `x-forwarded-proto`, `x-forwarded-host`, `x-forwarded-port`. Proxy ayarlıysa zorunlu. |

- Geçersiz veya eksik değer `run_server.py`'nin başlamasını durdurur; güven sessizce genişletilmez.
- Güven ayarlandığında bu dört başlığı yalnız Waitress yorumlar; uygulamadaki ProxyFix bunları ikinci kez okumaz.
- **Alt dizin yayını (`X-Forwarded-Prefix`):** varsayılan olarak yok sayılır (`PROXY_FIX_X_PREFIX=0`). Uygulama örneğin `https://kurum/bys/` altında yayınlanacaksa aşağıdakilerin üçü birden gerekir:
  - `WAITRESS_TRUSTED_PROXY` ayarlı olmalı;
  - `PROXY_FIX_X_PREFIX=1` olmalı;
  - Waitress'e bağlanan proxy (IIS) istemcinin gönderdiği `X-Forwarded-Prefix` başlığını silmeli ve kendi **tek** değerini yazmalıdır (`X-Forwarded-Prefix: /bys`). Ekleme yapan (append) ayar kullanılmamalıdır.

  Başlık yalnız güvenilen proxy adresinden gelirse ve tek bir düz yol ise (`/bys`, `/a/b`; `//`, şema, `.`/`..` segmenti yok) okunur. Virgüllü liste (`/evil, /bys`) veya iki ayrı başlık satırı geçersiz sayılır ve başlık Waitress'e varmadan silinir; uygulama kök dizinde çalışır. Güven ayarlı değilken başlık hiçbir koşulda okunmaz. `PROXY_FIX_X_PREFIX` yalnız 0 veya 1 olabilir; 2 ve üstünde `run_server.py` başlamaz. Bu değer `WAITRESS_TRUSTED_PROXY_COUNT`'tan bağımsızdır: iki proxy katmanında da öneki yalnız Waitress'e bağlanan proxy yazar ve değer 1 kalır.

  Canlı IIS'in bu başlığı silip üzerine yazdığı henüz doğrulanmadı (operatör kontrol listesi madde 4).
- Değerleri ancak operatör gerçek proxy adresini ve katman sayısını doğruladıktan sonra girin. `.env.example`'daki örnek canlı değer değildir. Waitress'in önünde proxy yoksa değişkenleri boş bırakın.
- Proxy, istemcinin gönderdiği `X-Forwarded-*` başlıklarını silmeli veya üzerine yazmalı. Waitress portuna proxy dışından doğrudan erişim kapatılmalıdır.

## 8. Temiz release üretimi

Doğrudan proje klasörünü zip yapmak yasaktır. Çünkü `.env`, `.git`, `instance`, `logs`, SQLite dosyaları veya geçici raporlar pakete girebilir.

Kanonik release builder: [scripts\release\build_bys360_safe_release.py](scripts/release/build_bys360_safe_release.py).
(`scripts\security\build_bys360_secure_release_v1_5.py` ve ona bağlı eski PowerShell
sarmalayıcıları/preflight betiği artık DEPRECATED'dır -- bkz. o dosyanın başındaki not.)

Kaynak dosya listesi yalnızca Git'in takip ettiği (tracked) dosyalardan üretilir; dosya
sistemine geri düşüş (fallback) yoktur -- git kullanılamıyorsa build başarısız olur (fail
closed). Build, HEAD ile tracked/staged çalışma ağacı tamamen temiz değilse de başarısız olur.

Builder'ın iki paket modu birbirinden ayrılır:

| Mod | Tetikleyici | Manifest | Kullanım |
|---|---|---|---|
| Audit / legacy | `--wheelhouse-dir` verilmez | `schema_version = 2` | Tarihsel/kaynak paket denetimi; kanonik FULL production candidate paketi değildir. |
| FULL production candidate | `--wheelhouse-dir` verilir | `schema_version = 3` | Doğrulanmış Windows x64 / CPython 3.12 wheelhouse ve `requirements.lock` gerektirir; candidate preparation/cutover için kanonik paket budur. |

**İnsan kontrollü kaynak seçimi:** Build öncesinde release süreci onaylı exact commit'i
seçmeli ve doğrulamalıdır (**HUMAN_DECISION_REQUIRED**). Aşağıdaki
`<APPROVED_EXACT_40_CHAR_SOURCE_SHA>` yer tutucusu, onaylı 40 küçük harfli hex SHA ile;
`<FULL_RELEASE_ZIP>` ise seçilen FULL zip çıktı yolu ile değiştirilir. Örnekler bu exact
commit'in checkout edildiği temiz kaynak kökünde, uygun Python ortamında kullanılır.
Builder `--source-sha` ile HEAD eşleşmesini denetler; mevcut HEAD'de çalıştırmak tek başına
o commit'i onaylı yapmaz. Bu belgede sabit bir gelecek release SHA'sı tanımlanmaz.

**Kilit dosyası (`requirements.lock`) üretimi:** Kilit elle düzenlenmez;
[generate_bys360_requirements_lock.py](scripts/release/generate_bys360_requirements_lock.py)
ile CPython 3.12 altında üretilir. Hedef Windows x64 / CPython 3.12'dir; ortam işaretleri
(marker) Windows için değerlendirilir, bu yüzden `colorama` gibi yalnız Windows'ta gereken
paketler Linux'ta üretimde de korunur. Mevcut kilitteki sürümler kısıt olarak tutulur: yalnız
`requirements.txt` sabitleri ve açıkça verilen `--upgrade-package` sürümleri değişebilir; yeni
paket veya açıklanmayan sürüm değişikliği üretimi durdurur. Çıktı deterministiktir (tarih,
commit veya pip sürümü içermez).

```powershell
python scripts\release\generate_bys360_requirements_lock.py                          # yeniden üret
python scripts\release\generate_bys360_requirements_lock.py --check                  # yalnız doğrula
python scripts\release\generate_bys360_requirements_lock.py --upgrade-package NAME==SÜRÜM
```

CI her PR'da kilidi iki yerden denetler: Linux'ta `scripts/quality/bys360_dependency_lock_gate.py`
kilidin yapısını ve sabitlenmiş sürümlerin pip-audit sonucunu (sıfır açık) denetler; Windows'ta
`--check` ile kilidin bayt düzeyinde yeniden üretildiği, wheelhouse hash'lerinin eşleştiği ve
temiz bir venv'e `--require-hashes` ile offline kurulabildiği doğrulanır.

**A. Wheelhouse üretimi ve doğrulaması:**
[build_bys360_wheelhouse.py](scripts/release/build_bys360_wheelhouse.py), onaylı kaynak
kökteki [requirements.lock](requirements.lock) üzerinden Windows x64 / CPython 3.12
wheel'lerini indirip doğrular; aday ortamın kurulumu daha sonra offline yapılır.
Varsayılan hedef `win_amd64`, Python `3.12`, implementation `cp`, ABI `cp312`'dir.

```powershell
python scripts\release\build_bys360_wheelhouse.py --root . --clean
```

Varsayılan çıktılar `build\wheelhouse` ve
`reports\quality\BYS360_WHEELHOUSE_BUILD_REPORT.json`'dur. `--clean`, mevcut wheelhouse
çıktı dizinini silip yeniden üretir; bu yol operatör tarafından önceden doğrulanır.
Başarılı raporda `ok = true`, beklenen hedef, wheel envanteri ve SHA256 kimliği bulunmalıdır.
Araç kilitli paketleri/hash'leri ve wheel uyumluluğunu doğrular; kaynak paket derlemesine
sessizce düşmez. Başarısız veya sonradan değiştirilmiş wheelhouse ile FULL build'e devam edilmez.

**B. Kanonik FULL production candidate paketi:**

```powershell
python scripts\release\build_bys360_safe_release.py --root . `
  --source-sha "<APPROVED_EXACT_40_CHAR_SOURCE_SHA>" `
  --wheelhouse-dir build\wheelhouse `
  --output "<FULL_RELEASE_ZIP>"
```

FULL build varsayılan olarak `requirements.lock` ve yukarıdaki wheelhouse raporunu kullanır;
wheelhouse dosyalarını raporun envanter/hash'leriyle karşılaştırır. Paket `requirements.lock`
ve `wheelhouse\` içeriğini taşır. Manifest `schema_version = 3`, `migration_head`,
`candidate_script_sha256`, `cutover_script_sha256`, `rollback_script_sha256` ve bağımlılık
kimliklerini kaydeder. Tam olarak birleştirilmiş FULL paket ağacı secret taramasından geçirilir;
başarılı sonuç `secret_scan_status = PASS`, `secret_scan_findings = 0` olarak kaydedilir.

Zip ile aynı dizinde, zip'in uzantısız adına göre `<zip-name>.manifest.json` ve
`<zip-name>.sha256sums.txt` yan dosyaları üretilir; zip ve yan dosyalar birlikte korunur.

**C. Paket doğrulaması ve FULL kabul ölçütleri:**

```powershell
python scripts\release\build_bys360_safe_release.py --verify "<FULL_RELEASE_ZIP>" `
  --expected-source-sha "<APPROVED_EXACT_40_CHAR_SOURCE_SHA>"
```

Production FULL kabulünde en az aşağıdakiler birlikte doğrulanır:

- Manifest `schema_version = 3` olmalıdır.
- Paket içindeki `RELEASE_SOURCE_SHA.txt` onaylı exact SHA ile eşleşmelidir; manifest
  `source_sha` ve verifier'ın `embedded_source_sha` / `sidecar_source_sha` değerleri de aynı olmalıdır.
- `requirements.lock` ve doğrulanmış `wheelhouse\` içeriği bulunmalıdır; wheel sayısı,
  dosya hash'leri ve build raporu/manifest kimlikleri tutarlı olmalıdır.
- Manifest `secret_scan_status = PASS`, `secret_scan_findings = 0` göstermelidir.
- `migration_head` ile candidate/cutover/rollback script SHA256 kimlikleri mevcut olmalıdır.
- Verify çıktısında `ok = true` ve başarılı exit code bulunmalıdır.

Genel `--verify` legacy schema-v2 paketlerini de kabul edebilir; yalnız `ok = true`
sonucu FULL production kabulü değildir. Schema-v3 ve FULL manifest alanları ayrıca
incelenir. Candidate preparation daha sonra bu kimlikleri gerçek paket içeriğiyle
karşılaştırır; bu belge candidate preparation veya cutover'ın çalıştırıldığı beyanı değildir.

`--verify` şunları FAIL eder: eksik gerekli dosya, yasaklı yol (ör. `.env`, `tests/`,
`mobile_flutter/`, `.codex/`, `.claude/`, sertifika/anahtar uzantıları), beklenmeyen ekstra
dosya, SHA256 uyuşmazlığı, güvensiz/traversal yol adı. Zip'in sadece açılabiliyor olması
paketin geçerli olduğu anlamına gelmez -- her release bu komutla doğrulanmalıdır.

## 9. Rollback

Canlıya alma sonrası 5xx, beyaz sayfa, migration hatası veya yetki bozulması görülürse:

Güncel candidate/cutover modelinin kanonik **app-tree rollback** yolu
[rollback_bys360_candidate.ps1](scripts/windows/rollback_bys360_candidate.ps1)'dir;
[BACKUP_RUNBOOK.md §6](BACKUP_RUNBOOK.md#6-restore-özeti) aynı sözleşmeyi açıklar.
Yetkili insanın geri dönüş/kesinti kararından önce şu girdiler ve kod–DB uyumluluğu incelenir:

- Zorunlu `-PreviousDir`, izin verilen previous alanındaki önceki uygulama ağacını seçer.
  Bu ağaç uygulama işaretçilerini, `.venv\Scripts\python.exe` ve `.env` dosyasını taşımalıdır;
  receipt eşleşmesi için `CANDIDATE_READY.json` içindeki kaynak SHA da okunabilir olmalıdır.
  Yalnız filtreli kod yedeği bu sözleşmeyi karşılamaz.
- Zorunlu `-ActiveDeploymentReceiptPath`, başarılı cutover'ın `DEPLOYMENT_RECEIPT.txt`
  dosyasını seçer. `DEPLOY_EXIT_CODE=0`, mevcut uygulamanın SHA'sı ile `CANDIDATE_SOURCE_SHA`,
  seçilen önceki ağacın SHA'sı ile `PREVIOUS_SOURCE_SHA` ve tam dizini ile `PREVIOUS_DIR`
  eşleşmelidir. Eksik veya uyuşmayan receipt, servis durdurulmadan/dizin taşınmadan reddedilir;
  script kendiliğinden başka bir previous dizini seçmez.
- Bilinen mevcut DB revision'ı önceki ağacın migration head'i ile aynıysa pre-migration
  app-tree yolu kullanılabilir. Revision eşleşmiyorsa veya eşleşme doğrulanamıyorsa
  (migration ilerlemiş ya da revision/head bilinmiyor olabilir) açık
  `-PostMigrationAppTreeCompatible` insan beyanı gerekir. Bu bayrak uyumluluk kanıtı üretmez;
  önceki uygulamanın mevcut DB ile çalışabildiği ayrıca değerlendirilmelidir.

Bu scriptte DRY-RUN veya `-Apply` modu yoktur; ön koşullar sağlandığında gerçek rollback
akışını yürütür. Mevcut uygulama ağacını quarantine alanına taşır, seçilen önceki ağacı
kopyalar, mevcut `.env` ve `instance` içeriğini korur; storage alanlarına dokunmaz.
Servisi yeniden başlatır ve healthcheck yapar. Başarılı cutover receipt'i olmayan kısmi
cutover hatalarında bu yolun çalışacağı varsayılmaz; ayrı insan kontrollü recovery kararı gerekir.

**DB restore ve migration recovery ayrı, insan kontrollü işlemlerdir.** App-tree rollback
DB restore etmez ve otomatik Alembic downgrade çalıştırmaz. Sonrasında `/login`, `/healthz`,
performans ana ekranı ve mesaj/anket ekranları kontrol edilir.

[rollback_bys360_live_release_v1.ps1](scripts/windows/rollback_bys360_live_release_v1.ps1)
repository'de **legacy / pre-candidate** filtreli kod geri dönüş yolu olarak korunur;
varsayılan DRY-RUN ve `-Apply` sözleşmesi yalnız bu eski yola aittir. Güncel candidate
rollback ile karıştırılmamalıdır; ayrıntıları BACKUP_RUNBOOK.md §6'daki legacy bölümündedir.

## Git Geçmişi ve Kaynak Teslim Notu

Handover kaynak zip paketleri `.git/` klasörü içermez. Teslim doğrulaması manifestteki commit, tag ve SHA256 değerleriyle yapılır. Tam Git geçmişi gerektiğinde kurum Git uzak deposu veya ayrıca üretilecek `git bundle` üzerinden teslim edilir.

