# BYS360_CIC_V4_6_CELEBRATIONS_STUDIO_PRO_UI

Kutlamalar sayfasını taslak görünümden çıkarıp BYS360 kurumsal tasarım çizgisine yaklaştırır.

## İçerik
- Kutlamalar sayfası temiz ve tek parça profesyonel şablonla yeniden yazılır.
- Mavi link/Bootstrap link kalıntıları kaldırılır.
- Dağınık kartlar 12 kolonlu düzenli grid yapısına alınır.
- Excel yükleme alanı sayfa içinde kurumsal kart olarak yer alır.
- Genel Bakış/Kutlamalar aktiflik çakışması JS ile tam eşleşmeye çekilir.
- Eski "kuru çalışma / pilot" dili "Ön kontrol / Önizleme" diline çevrilir.

## Komut
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\repair_cic_v4_6_celebrations_studio_pro_ui.ps1 -ProjectRoot "C:\bys360\project"
python .\scripts\quality\check_cic_v4_6_celebrations_studio_pro_ui.py --project-root "C:\bys360\project"
python -m compileall app config.py scripts
```
