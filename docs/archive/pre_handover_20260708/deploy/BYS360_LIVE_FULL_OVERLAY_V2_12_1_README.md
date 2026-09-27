# BYS360 LIVE FULL OVERLAY V2.12.1

Bu paket canlıya uygun web overlay paketidir. `.env`, `.venv`, `app/static/uploads`, yedek klasörleri ve kullanıcı yüklemeleri pakete alınmamıştır.

## Kapsam

- Kurumsal Portal ana sayfa iPhone/dar ekran uyumluluğu.
- Instagram/Meta akış kartlarının canlıda gizli kalması.
- Portal paylaşım kartında Instagram ve Instagram Story kayıtlarının akıştan gizlenmesi.
- Kurumsal Portal rol matrisi anahtarlarının Ayarlar / Rol Matrisi kapsamına alınması.
- Personel Yönetimi ve kişi bazlı rol matrisi görünürlüğünün korunması.
- Python compile ve gate kontrol scriptleri.

## Canlı uygulama sırası

PowerShell ile proje kökünde çalıştırın:

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_LIVE_FULL_OVERLAY_V2_12_1.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_live_full_overlay_v2_12_1.ps1 -ProjectRoot "C:\bys360\project"
powershell -ExecutionPolicy Bypass -File .\scripts\windows\check_bys360_live_full_overlay_v2_12_1.ps1 -ProjectRoot "C:\bys360\project"
```

Gate OK sonrası canlı servis:

```powershell
Stop-ScheduledTask -TaskName "BYS360 Live Waitress 80"
Start-ScheduledTask -TaskName "BYS360 Live Waitress 80"
```

## Kontrol ekranları

- `/portal`
- `/portal/people`
- `/settings`
- `/admin/role-matrix`
- `/support`
- `/performance/scorecard`

## Not

Paket canlı gizli bilgilerine dokunmaz. Veritabanı migration çalıştırmaz. Yedekler `.overlay_backup/live_full_v2_12_1_*` altına alınır.
