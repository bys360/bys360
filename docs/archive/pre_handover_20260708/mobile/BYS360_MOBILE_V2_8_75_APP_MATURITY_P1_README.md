# BYS360 Mobile V2.8.75 App Maturity P1 Overlay

Bu overlay, V2.8.74 ile gecen Android release hazirligini bozmadan mobil uygulamayi canli kullanim olgunluguna tasir.

## Neden bu paket?

V2.8.74 P0 ile release imzalama ve FCM guvenli ac/kapat yapisi tamamlandi. V2.8.75 P1 ise kullanici deneyimi ve canli takip eksiklerini kapatir:

- Sistem karanlik moda gectiginde uygulama tema yapisi hazir olur.
- Ana sayfa, internet kesintisi veya gecici API sorunu yasandiginda son 5 dakikadaki guvenli ozeti gosterebilir.
- Kullanici ekraninda endpoint, JSON, debug, stack trace gibi teknik ifadeler gorunmez.
- Uygulama cokme/hata bilgisini dis servise bagimli olmadan yerel olarak yakalar.
- Gate, paketin dogru uygulandigini ve P0 release imza yapisinin bozulmadigini kontrol eder.

## Uygulama

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_MOBILE_V2_8_75_APP_MATURITY_P1_OVERLAY.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_mobile_v2_8_75_app_maturity_p1.ps1 -ProjectRoot "C:\bys360\project"
powershell -ExecutionPolicy Bypass -File .\scripts\windows\check_bys360_mobile_v2_8_75_app_maturity_p1.ps1 -ProjectRoot "C:\bys360\project"
```

Beklenen cikti:

```text
BYS360_MOBILE_V2_8_75_APP_MATURITY_P1_GATE_OK
```

## APK uretimi

FCM kapali release APK:

```powershell
cd C:\bys360\project
powershell -ExecutionPolicy Bypass -File .\scripts\windows\build_bys360_mobile_v2_8_75_release_apk.ps1 -ProjectRoot "C:\bys360\project" -EnableFcm:$false
```

APK cikisi:

```text
C:\bys360\project\mobile_flutter\bys360_mobile_native\build\app\outputs\flutter-apk\app-release.apk
```

## Onemli notlar

- Bu paket `android/key.properties` veya `.jks` dosyasini degistirmez.
- Keystore ve sifreler yine yerel/gizli kalmalidir.
- Firebase dosyasi yoksa FCM kapali build alinmaya devam edebilir.
- Sentry gibi dis crash reporting bu pakette zorunlu bagimlilik olarak eklenmedi; once guvenli yerel crash kaydi kuruldu.
