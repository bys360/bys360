# BYS360 BACKUP_RUNBOOK.md

Bu runbook, BYS360 canlı ortamında güncelleme, migration, kritik ayar değişikliği ve release öncesi alınacak yedekleri tarif eder.

## 1. Yedek alma ilkesi

- Kod yedeği ile veritabanı yedeği ayrı alınır.
- `.env` güvenli kanalda saklanır, release zipine konulmaz.
- Yedek dosyaları proje kökünde tutulmaz; `C:\bys360\backups` veya kurumun güvenli yedek alanı kullanılır.
- Her yedek tarih-saat damgası ve kısa açıklama taşır.

## 2. Güncelleme öncesi hızlı kontrol

```powershell
cd C:\bys360\project
git status --short
git branch --show-current
python -m compileall app config.py scripts migrations
```

Kirli çalışma ağacı varsa önce commit veya ayrı yedek alınır.

## 3. Kod yedeği

```powershell
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupRoot = "C:\bys360\backups\predeploy_$Stamp"
New-Item -ItemType Directory -Force $BackupRoot | Out-Null
robocopy "C:\bys360\project" "$BackupRoot\project" /E /XD .git .venv __pycache__ logs instance reports dist_secure uploads /XF .env .env.* *.pyc *.log *.sqlite *.sqlite3 *.db
```

Bu yalnız kod yedeğidir. Dizin/uzantı dışlamaları
[legacy / pre-candidate rollback scriptinin](scripts/windows/rollback_bys360_live_release_v1.ps1)
koruma listesini izler: `.git`, `.venv`, `__pycache__`, `logs`, `instance`, `reports`,
`dist_secure` ve `uploads` adlı dizinler (iç içe `app\static\uploads` dahil), ayrıca
`.pyc`, `.log`, `.sqlite`, `.sqlite3`, `.db` dosyaları kod yedeğine alınmaz.
`.env` ve `.env.*` dışlaması mevcut [.releaseignore](.releaseignore) ve
[güvenli release sözleşmesine](scripts/release/build_bys360_safe_release.py) dayanır;
bu kod-yedeği örneği `.env.*` şablonlarını da dışarıda bırakır. Korunan runtime/configuration
içeriği sıradan kod yedeği değildir; `.env` güvenli kanalda ayrı saklanır.
Bu filtreli kod yedeği, güncel candidate rollback'in ihtiyaç duyduğu `.venv` ve `.env`
içeren önceki uygulama ağacı (`PreviousDir`) yerine kullanılamaz; §6'daki yollar ayrıdır.

## 4. PostgreSQL yedeği

PostgreSQL 15 için PowerShell örneği; yalnız yetkili operatörün kurum güvenli terminalinde
kullanımı içindir. `$env:DATABASE_URL` önceden onaylı hedef için tanımlanmış, libpq uyumlu
bir bağlantı değeri olmalıdır (`postgresql://` veya `postgres://` URI biçimi; SQLAlchemy
driver eki içeren URI doğrudan kullanılamaz). Değer ekrana veya rapora yazılmaz; `.env`
dosyasının var olması PowerShell ortam değişkenini kendiliğinden yüklemez.

```powershell
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Out = "C:\bys360\backups\bys360_db_$Stamp.dump"
pg_dump --format=custom --file="$Out" --dbname="$env:DATABASE_URL"
```

`--dbname`, `--format=custom` ve `--file` seçenekleri
[PostgreSQL 15 pg_dump belgesi](https://www.postgresql.org/docs/15/app-pgdump.html),
bağlantı biçimi ise [libpq belgesi](https://www.postgresql.org/docs/15/libpq-connect.html#LIBPQ-CONNSTRING)
ile tanımlıdır. Bu örnek bir işlemin çalıştırıldığı veya yedeğin doğrulandığı beyanı değildir.

## 5. SQLite lokal yedeği

Lokal geliştirme SQLite kullanıyorsa:

```powershell
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "C:\bys360\project\instance\bys360_local_dev.sqlite3" "C:\bys360\backups\bys360_local_dev_$Stamp.sqlite3"
```

SQLite dosyası release paketine konulmaz.

## 6. Restore özeti

### Güncel candidate/cutover app-tree rollback

Güncel kanonik yol
[scripts\windows\rollback_bys360_candidate.ps1](scripts/windows/rollback_bys360_candidate.ps1)
ile [DEPLOYMENT.md §9](DEPLOYMENT.md#9-rollback)'daki app-tree sözleşmesidir.
İki zorunlu girdi vardır: `-PreviousDir` ve `-ActiveDeploymentReceiptPath`.
`PreviousDir`, izin verilen previous alanındaki önceki uygulama ağacıdır; uygulama
işaretçileri, `.venv\Scripts\python.exe`, `.env` ve receipt ile eşleşen kaynak SHA'yı
okuyabilmek için `CANDIDATE_READY.json` gerekir. §3'teki kod yedeği bu tam ağaç değildir.

Receipt dosyasının adı `DEPLOYMENT_RECEIPT.txt` olmalıdır. Başarılı cutover kaydında
`DEPLOY_EXIT_CODE=0` olmalı; `CANDIDATE_SOURCE_SHA` mevcut uygulama SHA'sına,
`PREVIOUS_SOURCE_SHA` seçilen önceki uygulama SHA'sına ve `PREVIOUS_DIR` seçilen dizine
bağlanmalıdır. Eksik/uyuşmayan receipt, servis durdurulmadan ve dizin taşınmadan reddedilir.
Otomatik latest/başka previous dizini seçimi yoktur. Başarılı receipt bulunmayan kısmi
cutover hatası için ayrı insan kontrollü recovery değerlendirmesi gerekir.

Bilinen DB revision'ı önceki ağacın migration head'i ile aynıysa pre-migration app-tree
rollback mümkündür. Revision eşleşmiyorsa veya eşleşme doğrulanamıyorsa (migration
ilerlemiş ya da revision/head bilinmiyor olabilir) insanın mevcut DB ile
önceki uygulamanın uyumluluğunu değerlendirmesi ve açık `-PostMigrationAppTreeCompatible`
beyanı gerekir; script bu uyumluluğu kendi başına kanıtlamaz.

Scriptte DRY-RUN veya `-Apply` modu yoktur. Yetkili insanın geri dönüş/kesinti onayı ve
ön koşulların incelenmesinden sonra gerçek işlem yapılır: mevcut ağaç quarantine alanına
taşınır, önceki ağaç kopyalanır ve mevcut `.env` ile `instance` korunur. Storage alanları
ve DB yedekleri değiştirilmez; servis başlatma ve healthcheck adımları uygulanır.
Bu yalnız app-tree rollback'tir; DB restore etmez, otomatik Alembic downgrade çalıştırmaz.
DB migration ilerlediyse database recovery kararı ve gerekiyorsa aşağıdaki PostgreSQL
restore işlemi ayrı, insan kontrollü süreçlerdir.

### Legacy / pre-candidate filtreli kod geri dönüşü

Eski TD-036 kod geri dönüş yolu
[scripts\windows\rollback_bys360_live_release_v1.ps1](scripts/windows/rollback_bys360_live_release_v1.ps1)
ile aşağıdaki legacy akıştır; güncel candidate/cutover rollback yolu değildir.
Bu eski script varsayılan olarak **DRY-RUN** çalışır: planı basar ve VERIFY
ön koşullarını denetler; dosya kopyalamaz, görev durdurup/başlatmaz, HTTP isteği yapmaz.
`BackupRoot` altında geçerli, boş olmayan `project` yedeği ve `run_server.py`, `config.py`,
`app\` işaretçileri bulunmalıdır. Örnekler doğrulanmış uygulama kaynak kökünden çalıştırılır.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\rollback_bys360_live_release_v1.ps1 `
  -BackupRoot "C:\bys360\backups\predeploy_YYYYMMDD_HHMMSS"
```

Gerçek uygulama, DRY-RUN incelemesi ve yetkili insanın geri dönüş/kesinti onayından sonra
yalnız açık **`-Apply`** ile yapılır. Uygun kod–DB sürüm eşleşmesi insan tarafından
değerlendirilir; script DB uyumluluğunu doğrulamaz veya DB restore etmez.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\rollback_bys360_live_release_v1.ps1 `
  -BackupRoot "C:\bys360\backups\predeploy_YYYYMMDD_HHMMSS" -Apply
```

Script önce filtreli staging kopyasını doğrular; sonra görev durdurma, filtreli kod
aktarma, görev başlatma ve healthcheck adımlarını yönetir. Koruma sözleşmesi gereği `.env`
ile `instance`, `logs`, `uploads` (`app\static\uploads` dahil) ve `reports` adlı runtime
dizinlerinin üzerine yazılmaz; §3'te listelenen diğer dizin/uzantı dışlamaları da uygulanır.
Filtre dışındaki `.env.*` varyantlarının korunduğu bu script için varsayılmaz; scriptin
sabit dosya-adı koruması `.env` içindir, kod yedeği ise §3 uyarınca `.env.*` içermez.
Eski bir yedek seçildiğinde, `-Apply` öncesinde dosya-adı envanterinin §3'teki kod-yedeği
kapsamına uyduğu insan tarafından doğrulanır; DRY-RUN bu secret/configuration envanterini
denetlediği anlamına gelmez.
Canlıda yedekte olmayan ek dosyalar silinmez; bu tam bir dizin aynalama işlemi değildir.

**Tarihsel / superseded yöntem:** Eski belgedeki filtresiz doğrudan `robocopy /E` kod
restore örneği, eski yedekten korunan configuration üzerine yazabildiği için kanonik
olmayan tarihsel bir yöntemdir. Eski proje yedeğini doğrudan canlı `C:\bys360\project`
köküne bu şekilde geri kopyalamak güncel onaylı restore prosedürü değildir.
PostgreSQL restore ayrı, insan kontrollü bir operasyondur; bu scriptin kapsamı dışındadır.

### PostgreSQL restore

```powershell
pg_restore --clean --if-exists --dbname="$env:DATABASE_URL" "C:\bys360\backups\bys360_db_YYYYMMDD_HHMMSS.dump"
```

Bu komut §4'teki PowerShell/libpq bağlantı ön koşullarını kullanır;
[PostgreSQL 15 pg_restore belgesi](https://www.postgresql.org/docs/15/app-pgrestore.html)
`--dbname`, `--clean` ve `--if-exists` seçeneklerini tanımlar. `--clean` hedef nesneleri
silip yeniden oluşturmayı içerir. Restore canlıda yapılacaksa öncesinde yetkili insan onayı,
doğru hedef/yedek doğrulaması ve kesinti planı gerekir; bu belge o onayın verildiği anlamına gelmez.

**Felaket kurtarma / production recovery için birincil yöntem onaylı PostgreSQL yedeğini
restore etmektir.** Fresh / clean-room kurulum, yeni/boş PostgreSQL 15 veritabanında ayrı
bir işlemdir: önce `flask db upgrade`, başarıyla tamamlandıktan sonra
`flask runtime-schema provision`. Bu iki adımlı kurulumun doğrulama kaydı
[SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md)'dedir; uygulama adımları
[DEPLOYMENT.md §4](DEPLOYMENT.md#4-veritabanı-hazırlığı)'te bulunur.
`runtime-schema provision` yedek restore'unun yerine geçmez ve production'ın sıfırdan
yeniden kurulduğu iddia edilmez.

> **Tarihsel / superseded not (2026-09-28):** O tarihte yalnız `flask db upgrade` boş
> veritabanında her ORM tablosunu üretmiyordu. Eski sınırlama ve sonraki güncelleme
> [BYS360_SCHEMA_RECOVERY_LIMITATION.md](docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md)
> §7–§8 dahil tarihsel kanıtıyla korunur; bu eski gözlem güncel fresh kurulum sınırlaması değildir.

## 7. Yedek sonrası doğrulama

- Yedek dosyası var mı?
- Dosya boyutu sıfırdan büyük mü?
- Restore komutu test ortamında denenmiş mi?
- Yedekte `.env`, token, kişisel veri ve gereksiz log var mı?
- Yedek konumu kurum güvenlik politikasına uygun mu?

## 8. Saklama politikası önerisi

| Yedek türü | Saklama |
|---|---:|
| Güncelleme öncesi kod yedeği | 30 gün |
| Kritik migration öncesi DB yedeği | 90 gün |
| Aylık güvenli arşiv | 1 yıl |
| KVKK açısından hassas geçici çıktılar | Gerektiği kadar, sonra güvenli silme |
