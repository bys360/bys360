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
robocopy "C:\bys360\project" "$BackupRoot\project" /E /XD .git .venv __pycache__ logs instance reports dist_secure /XF *.pyc *.log *.sqlite *.sqlite3 *.db
```

## 4. PostgreSQL yedeği

Canlı veritabanı PostgreSQL ise örnek:

```powershell
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Out = "C:\bys360\backups\bys360_db_$Stamp.dump"
pg_dump --format=custom --file=$Out "%DATABASE_URL%"
```

`DATABASE_URL` doğrudan ekrana veya rapora yazılmaz. Komut kurum güvenli terminalinde çalıştırılır.

## 5. SQLite lokal yedeği

Lokal geliştirme SQLite kullanıyorsa:

```powershell
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "C:\bys360\project\instance\bys360_local_dev.sqlite3" "C:\bys360\backups\bys360_local_dev_$Stamp.sqlite3"
```

SQLite dosyası release paketine konulmaz.

## 6. Restore özeti

### Kod geri dönüşü

```powershell
Stop-ScheduledTask -TaskName "BYS360 Live Waitress 80" -ErrorAction SilentlyContinue
robocopy "C:\bys360\backups\predeploy_YYYYMMDD_HHMMSS\project" "C:\bys360\project" /E
Start-ScheduledTask -TaskName "BYS360 Live Waitress 80"
```

Yukarıdaki adımların otomasyonu için `scripts\windows\rollback_bys360_live_release_v1.ps1`
kullanılabilir (TD-036). Script, varsayılan olarak DRY-RUN çalışır (sadece
plan basar, hiçbir dosya kopyalamaz); gerçek uygulamak için `-Apply` verilir.
`.env`, `instance\`, `logs\`, `uploads` (`app\static\uploads` dahil) ve
`reports\` her koşulda korunur, hiçbir zaman üzerine yazılmaz. Örnek:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\rollback_bys360_live_release_v1.ps1 `
  -BackupRoot "C:\bys360\backups\predeploy_YYYYMMDD_HHMMSS" -Apply
```

Bu script sadece KOD geri dönüşünü kapsar; PostgreSQL restore'u yukarıdaki
manuel adım olarak ayrı kalır (aşağıya bakınız).

### PostgreSQL restore

```powershell
pg_restore --clean --if-exists --dbname "%DATABASE_URL%" "C:\bys360\backups\bys360_db_YYYYMMDD_HHMMSS.dump"
```

Restore canlıda yapılacaksa öncesinde yetkili onay ve kesinti planı gerekir.

Yedekten geri yükleme, boş veritabanında `flask db upgrade` ile yeniden kurulumun yerine geçer; ikincisi bugün
her ORM tablosunu üretmez (`docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md`).

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
