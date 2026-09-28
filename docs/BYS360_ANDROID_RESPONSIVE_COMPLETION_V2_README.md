# BYS360 Android Responsive Completion V2

Bu paket Android tarafı V1 genel kaldığı için hazırlanmış daha güçlü responsive tamamlama paketidir.

## Ne yapar?

- Android Chrome / Android WebView / Capacitor benzeri mobil kabukları algılar.
- `html` ve `body` üzerine `bys360-android-responsive-v2` sınıfını ekler.
- JS sınıfı geç gelirse bile `@media (max-width:760px)` ile class beklemeden temel mobil koruma uygular.
- Geniş tablo ekranlarını Android'de kart görünümüne dönüştürür.
- Inline `width/min-width` yüzünden taşan alanları tarayıp sınırlar.
- Dashboard, performans, personel, destek, anket, ayarlar, KPI, AI ve asistan panelinde tek kolon davranışı güçlendirir.
- Android WebView klavye/viewport yüksekliği için `--bys360-android-v2-vh` değişkenini günceller.

## Kurulum

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_ANDROID_RESPONSIVE_COMPLETION_V2_OVERLAY.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_android_responsive_completion_v2.ps1 -ProjectRoot "C:\bys360\project" -Mode all
```

## Kontrol

```powershell
.\.venv\Scripts\python.exe .\scripts\quality\check_bys360_android_responsive_completion_v2.py "C:\bys360\project"
```

Beklenen sonuç: `BYS360_ANDROID_RESPONSIVE_COMPLETION_V2_OK`
