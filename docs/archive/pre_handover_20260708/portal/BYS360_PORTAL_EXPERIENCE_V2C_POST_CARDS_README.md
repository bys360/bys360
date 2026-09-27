# BYS360 Portal Deneyimi V2C — Paylaşım Kutusu ve Gönderi Kartları

Bu paket yayın akışındaki paylaşım kutusunu ve gönderi kartlarını daha canlı, sade ve kurumsal sosyal akış görünümüne taşır.

## Özellikler

- Paylaşım kutusu daha doğal ve kullanıcı dostu hale gelir.
- Duyuru, bilgilendirme, teşekkür, iyi uygulama ve etkinlik kısa etiketleri görünür.
- Gönderi kartlarında profil, tarih, görünürlük, paylaşım türü ve etkileşim alanları daha okunur hale gelir.
- Tepki, yorum ve kaydetme alanları daha temiz görünür.
- Mobilde gönderi kartları daha rahat okunur.
- Veritabanına dokunmaz, yeni tablo açmaz.

## Kurulum

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_PORTAL_EXPERIENCE_V2C_POST_CARDS_OVERLAY.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_portal_experience_v2c_post_cards.ps1 -ProjectRoot "C:\bys360\project" -Mode all
```

Başarılı çıktı:

```text
BYS360_PORTAL_EXPERIENCE_V2C_POST_CARDS_OK
```
