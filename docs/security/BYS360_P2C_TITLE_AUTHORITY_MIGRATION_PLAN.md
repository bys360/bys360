# P2c — Unvana bağlı yetkiden açık kişi atamasına geçiş planı

Durum: **YALNIZ PLAN (K6, 2026-10-13).** Bu belge PR #70 içinde hiçbir kodu, şemayı veya veriyi değiştirmez. Uygulama ayrı bir PR'da ve proje sahibinin ayrı onayıyla yapılacaktır.

## 1. Bulgu

`app/services/performance/personnel_support_publish_approval_service.py` içinde iki yetki kararı serbest metin alanlarından türetiliyor:

| Fonksiyon | Okuduğu alanlar | Verdiği yetki |
|---|---|---|
| `is_personnel_support_group_chair_user` | `role`, `role_name`, `user_type`, `unvan`, `title`, `position`, `gorev` | Yayın ön onayını **verme** (`can_decide_personnel_support_publish_approval`) |
| `is_hr_publish_user` | `role`, `role_name`, `user_type`, `unvan`, `title` | Onay kayıtlarını görme |
| `is_admin_user` (aynı modül) | `role`, `role_name`, `user_type`, `is_admin`, `is_superuser` | Onay kayıtlarını görme; `sistem_yoneticisi` da admin sayılır |

Risk: `unvan`/`title` alanını düzenleyebilen biri, bir hesaba "Personel ve Destek Hizmetleri Grup Başkanı" unvanı yazarak o hesaba onay verme yetkisi kazandırabilir. Bu, onaylı politikaya aykırıdır: "role_label, unvan veya serbest metin yetki üretmez; geniş yetkiler kişiye özel, açık ve denetlenebilir olur".

R05 ve R05c bu riski daraltır, ancak kapatmaz:

- Yönetici olmayan biri korumalı hesapların kimlik alanlarını değiştiremez.
- Yönetici olmayan biri sıradan (`personel`) bir hesabın unvanını hâlâ değiştirebilir. Mevcut onay sözleşmeleri başkanı tam da `role='personel'` olan bir hesapta unvanla tanıdığı için bu yol açık kalır.

## 2. Hedef model

1. Yayın ön onayı yetkisi, açık bir kişi atamasıyla verilir: `user_menu_permissions` satırı, `menu_key = "perf_ps_publish_chair"`, `source_type = "user_override"`, `is_visible = true`. Bu, `personnel_read_all` ve `support_all` ile aynı modeldir. Yeni tablo ve migration gerekmez.
2. Atamayı yalnız gerçek admin yapar (saklanan rol tam olarak `admin`), yalnız başka bir kullanıcı için. Mevcut `_can_change_explicit_grants` kuralı kullanılır.
3. Her atama ve geri alma `settings_change_logs` ve `audit_logs` kaydı üretir.
4. Atama sahibi R05/K1 anlamında korumalı hesaptır: anahtar `EXPLICIT_GRANT_KEYS` listesine eklenir.
5. Karar tek bir merkezi sunucu fonksiyonundan çıkar (`has_explicit_grant(user, "perf_ps_publish_chair")`); unvan, title, position ve gorev hiçbir yetki kararına girmez.

## 3. Geçiş adımları

| Adım | İş | Geri dönüş |
|---|---|---|
| 0 | Proje sahibi, yetkinin kişi bazlı atanacağını ve kimlere verileceğini onaylar. | — |
| 1 | Yeni anahtar `perf_ps_publish_chair`; `EXPLICIT_GRANT_KEYS` ve korumalı hesap kuralına eklenir; yalnız admin atama/geri alma ekranı. Karar mantığı **değişmez**. | Kod geri alınır (veri yok) |
| 2 | Salt-okunur rapor: bugün unvanla başkan sayılan aktif hesaplar ile açık atama sahipleri yan yana listelenir. Sahip kişi bazında onaylar. | — |
| 3 | Admin, onaylanan kişilere açık atamayı ekranda verir (audit kaydıyla). | Atamalar ekrandan geri alınır |
| 4 | Çift çalışma (en az bir yayın dönemi): karar hâlâ eski kuralla verilir; eski ve yeni sonuç farklı olduğunda uyarı loglanır. | Loglama kapatılır |
| 5 | Geçiş: `is_personnel_support_group_chair_user` ve `is_hr_publish_user` yalnız açık atama + saklanan rol ile karar verir; unvan/title/position/gorev okunmaz. Başkanı unvanla tanımlayan onay sözleşmesi testlerinin fikstürleri unvan yerine atama kullanacak şekilde güncellenir (2026-10-13 itibarıyla 40 test dosyası bu fonksiyonlara veya başkan unvanlarına referans veriyor; kesin liste uygulama PR'ında çıkarılır). | Bu adımın commit'i geri alınır |
| 6 | Eski unvan kümeleri ve `is_admin_user` içindeki `sistem_yoneticisi`/`is_superuser` kısayolları kaldırılır (ayrı karar). | Commit geri alınır |

## 4. Test planı

- RED: `role='personel'`, `unvan='Personel ve Destek Hizmetleri Grup Başkanı'`, atama yok → bugün onay verebiliyor; geçişten sonra veremez.
- Pozitif: atama sahibi onay verebilir; atama geri alınınca veremez.
- Yönetici olmayan biri atamayı veremez; kendi hesabına admin de veremez.
- Atama sahibi korumalı hesaptır: yönetici olmayan biri parolasını, aktifliğini ve matrisini değiştiremez.
- Rollback ve toplu işlemler atamaya dokunmaz (B1-F1 ve K5-Q2 ile aynı).

## 5. Açık kararlar (proje sahibi)

1. Yetkinin kimlere verileceği: kişi listesi ve vekâlet durumu.
2. `is_hr_publish_user` için de aynı modelin uygulanıp uygulanmayacağı (`ik`/`performans_yetkilisi` rolleri saklanan rol olarak kalabilir).
3. Çift çalışma süresi.
4. `is_admin_user` içindeki `sistem_yoneticisi` kısayolunun kaldırılıp kaldırılmayacağı.
