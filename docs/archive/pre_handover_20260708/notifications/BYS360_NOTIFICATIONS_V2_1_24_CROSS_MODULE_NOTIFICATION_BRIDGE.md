# BYS360 Notifications V2.1.24 — Modüller Arası Bildirim Köprüsü

Bu overlay; destek/talep, hızlı geri bildirim, kurumsal geri bildirim kampanyaları ve portal etkileşimlerini mevcut `notifications` omurgasına bağlar.

## Kapsam

- Destek talebi oluşturma
- Talebe yorum/not ekleme
- Talep durum güncelleme
- Talep atama
- Talep memnuniyet/değerlendirme
- Hızlı BYS360 geri bildirimi
- Kurumsal geri bildirim kampanyası oluşturma/yayınlama/yanıt alma
- Geri bildirim aksiyon planı oluşturma/güncelleme
- Portal paylaşımı, tepki, yorum, etiket, cevap ve paylaşım bildirimi

## Kurulum

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_NOTIFICATIONS_V2_1_24_CROSS_MODULE_NOTIFICATION_BRIDGE_OVERLAY.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_notifications_v2_1_24_cross_module_bridge.ps1 -ProjectRoot "C:\bys360\project" -Mode all
python -m compileall app scripts
```
