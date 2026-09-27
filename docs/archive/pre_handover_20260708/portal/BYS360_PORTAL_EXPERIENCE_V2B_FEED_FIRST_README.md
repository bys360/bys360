# BYS360 Portal Deneyimi V2B — Yayın Akışı Öncelikli Düzen

Bu paket `/portal` yayın akışı sayfasını paylaşım odaklı hale getirir.

## Amaç

- Paylaşım kutusu ve paylaşımlar sayfanın üst/ana alanında kalır.
- Büyük portal vitrin kartları yayın akışının üstünden kaldırılır.
- Duyuru, teşekkür, iyi uygulama ve portal özeti sağ yan destek alanına taşınır.
- Mobilde önce paylaşım akışı, sonra destek kartları görünür.
- Yeni tablo açmaz, veritabanına dokunmaz.

## Komut

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_PORTAL_EXPERIENCE_V2B_FEED_FIRST_OVERLAY.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_portal_experience_v2b_feed_first.ps1 -ProjectRoot "C:\bys360\project" -Mode all
```

Başarılı çıktı:

```text
BYS360_PORTAL_EXPERIENCE_V2B_FEED_FIRST_OK
```
