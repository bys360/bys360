# BYS360 Operasyonel Sağlamlaştırma V2 — Kalite Triage

Bu overlay, V1 sonrasında görülen yüksek `print()` ve `except Exception` sayılarını doğru kapsama ayırır.

## Neden gerekli?

V1 toplam repo taraması yaptığı için `scripts`, testler, migration dosyaları ve bakım araçları da sayıya dahil olur. Canlı riski doğru görebilmek için şu ayrım yapılır:

- `app_live_candidate`: `app/` ve canlıya çalışan ana uygulama dosyaları
- `scripts_tools`: repair, audit, maintenance scriptleri
- `tests`: test dosyaları
- `migrations`: alembic/migration dosyaları
- `root_config`: config/wsgi/run dosyaları

## Uygulama

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_OPS_HARDENING_V2_TRIAGE_OVERLAY.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_ops_hardening_v2_triage.ps1 -ProjectRoot "C:\bys360\project" -Mode all
```

## Raporlar

- `reports/quality/BYS360_OPS_HARDENING_V2_TRIAGE_REPORT.md`
- `reports/quality/BYS360_OPS_HARDENING_V2_TRIAGE_REPORT.json`

## Güvenlik Notu

Secret taraması değerleri rapora yazmaz. `.env` veya `.env.docker.local` dosyası varsa içeriğini okumaz, yalnızca varlığını bildirir.

## Sonraki adım

Bu rapor çıktıktan sonra V3 paketi yalnızca canlı aday dosyalardaki hedefli `print()` ve `except Exception` temizliklerini yapmalıdır.
