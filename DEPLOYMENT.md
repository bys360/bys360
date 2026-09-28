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

```powershell
cd C:\bys360\project
.\.venv\Scripts\Activate.ps1
flask db upgrade
```

Migration öncesinde mutlaka yedek alınır. Yedek prosedürü için `BACKUP_RUNBOOK.md` dosyasına bakılır.

> **Bilinen sınırlama (2026-09-28):** `flask db upgrade` mevcut canlı veritabanını güncel tutar, ancak boş bir
> veritabanında her ORM tablosunu üretmez (Alembic'siz 30 tablo, yalnız runtime DDL ile oluşan 3 tablo, bir şekil
> uyuşmazlığı). Geri dönüş ve felaket kurtarmada veritabanı yedekten geri yüklenir; ayrıntı ve salt okuma canlı
> doğrulama adımları: `docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md`.

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

foreach ($pid in $owners) {
    $p = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -match "python|waitress") {
        Stop-Process -Id $pid -Force
    }
}

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 8
Invoke-WebRequest -Uri "http://127.0.0.1/login" -UseBasicParsing
```

## 8. Temiz release üretimi

Doğrudan proje klasörünü zip yapmak yasaktır. Çünkü `.env`, `.git`, `instance`, `logs`, SQLite dosyaları veya geçici raporlar pakete girebilir.

Tek yetkili (canonical) production release builder: `scripts\release\build_bys360_safe_release.py`.
(`scripts\security\build_bys360_secure_release_v1_5.py` ve ona bağlı eski PowerShell
sarmalayıcıları/preflight betiği artık DEPRECATED'dır -- bkz. o dosyanın başındaki not.)

Kaynak dosya listesi yalnızca Git'in takip ettiği (tracked) dosyalardan üretilir; dosya
sistemine geri düşüş (fallback) yoktur -- git kullanılamıyorsa build başarısız olur (fail
closed). Build, HEAD ile tracked/staged çalışma ağacı tamamen temiz değilse de başarısız olur.

Güvenli release için:

```powershell
cd C:\bys360\project
.\.venv\Scripts\Activate.ps1
python scripts\release\build_bys360_safe_release.py --root . --output "C:\bys360\dist\bys360_release.zip"
```

Bu komut zip'in yanına iki ek dosya üretir: `bys360_release.manifest.json` (source SHA, paket
içeriğinin göreli yol listesi, deterministik sıralama) ve `bys360_release.sha256sums.txt`
(her paketlenmiş dosyanın SHA256'sı, göreli yol, sabit sıralama). Hiçbiri mutlak yerel yol,
Windows kullanıcı adı, geçici dizin yolu veya secret içermez.

Üretilen zip ayrıca kendi doğrulama modu ile kontrol edilir:

```powershell
python scripts\release\build_bys360_safe_release.py --verify "C:\bys360\dist\bys360_release.zip"
```

`--verify` şunları FAIL eder: eksik gerekli dosya, yasaklı yol (ör. `.env`, `tests/`,
`mobile_flutter/`, `.codex/`, `.claude/`, sertifika/anahtar uzantıları), beklenmeyen ekstra
dosya, SHA256 uyuşmazlığı, güvensiz/traversal yol adı. Zip'in sadece açılabiliyor olması
paketin geçerli olduğu anlamına gelmez -- her release bu komutla doğrulanmalıdır.

## 9. Rollback

Canlıya alma sonrası 5xx, beyaz sayfa, migration hatası veya yetki bozulması görülürse:

1. Canlı görev durdurulur.
2. Son çalışan kod yedeği geri alınır.
3. Gerekirse DB yedeği restore edilir.
4. Canlı görev başlatılır.
5. `/login`, `/healthz`, performans ana ekranı ve mesaj/anket ekranları kontrol edilir.

Detaylı geri dönüş prosedürü `BACKUP_RUNBOOK.md` içindedir.

## Git Geçmişi ve Kaynak Teslim Notu

Handover kaynak zip paketleri `.git/` klasörü içermez. Teslim doğrulaması manifestteki commit, tag ve SHA256 değerleriyle yapılır. Tam Git geçmişi gerektiğinde kurum Git uzak deposu veya ayrıca üretilecek `git bundle` üzerinden teslim edilir.

