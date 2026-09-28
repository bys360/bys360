# BYS360 Portal V2D1 — Profil Kartı Görsel Düzeltme

Bu overlay, yayın akışındaki profil kartının fotoğraf ve metin yerleşimini düzeltir.

## Kapsam
- Profil fotoğrafı merkezlenir.
- İsim, görev, birim ve rol yazıları daha düzgün hizalanır.
- Sol profil kartındaki fazla kalabalık küçük etiket gizlenir.
- Mobil görünümde avatar ve metin düzeni korunur.
- Veritabanına dokunmaz, yeni tablo açmaz.

## Komut
```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_PORTAL_EXPERIENCE_V2D1_PROFILE_VISUAL_FIX_OVERLAY.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_portal_experience_v2d1_profile_visual_fix.ps1 -ProjectRoot "C:\bys360\project" -Mode all
```
