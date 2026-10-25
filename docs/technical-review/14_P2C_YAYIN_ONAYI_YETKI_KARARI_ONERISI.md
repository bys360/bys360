# P2c — Personel ve Destek Hizmetleri Yayın Onayı Yetkisi: Karar Önerisi

**Durum:** OPEN. Karar ve geçiş onayı bekliyor; bu gece kod değişikliği yapılmadı.
**Kaynak:** PR #70 @ `d8068ae0`, `app/services/performance/personnel_support_publish_approval_service.py`

## 1. Bulgu

Bağımsız inceleme (#70, `e2832218`) bunu bir sonda testiyle doğruladı (`test_probe_p2c`):

- Admin ailesinden bir kullanıcı (başkan, başkan yardımcısı, grup başkanı, mali müşavir) kendi `unvan` alanını ya da başka bir hesabınkini "Personel ve Destek Hizmetleri Grup Başkanı" yapabiliyor.
- Unvanı değişen hesap şunları elde ediyor:
  - yayın onayı ekranını görme (personel puanları dahil);
  - onaylama veya iade kararı verme.

## 2. Yetkiyi veren fonksiyonlar

| Fonksiyon | Okuduğu alanlar | Verdiği yetki |
|---|---|---|
| `is_personnel_support_group_chair_user` | role, role_name, user_type, **unvan, title, position, gorev** (kesin yazım listesi) | Karar verme (`can_decide_…`) ve görüntüleme |
| `is_hr_publish_user` | role, role_name, user_type, **unvan, title** | Görüntüleme |
| `is_admin_user` | role, role_name, user_type, is_admin | Görüntüleme |

`unvan` alanını yazan yollar şunlardır. Hiçbiri R05 korumasında değil, çünkü unvan bir hesap durumu alanı sayılmıyor:

- `/admin/users/<id>/edit`
- `/personnel/<id>/edit`
- Excel içe aktarmaları

## 3. Güvenilir görev kaynağı var mı?

- **Yok.** Kodda "Personel ve Destek Hizmetleri Grup Başkanı" görevini saklayan, admin tarafından atanan bir kayıt bulunmuyor.
- `OrganizationUnit.manager_user_id` aday olabilir. Ancak kimin yazabildiği ve canlıdaki doluluğu doğrulanmadı; onay akışı da bu alanı okumuyor.
- Mevcut onaylı sözleşme testleri (14 dosya) başkanı `role='personel'` ve unvanla tanımlıyor. Bu, mevcut davranışın test edilmiş hâli; güvenli bir yetki modeli değil.

## 4. Önerilen güvenli geçiş (onay gerekli)

1. **Açık kişi bazlı yetki anahtarı.**
   - `UserMenuPermission` (user_override) içinde `personnel_support_publish_approve` anahtarı tanımlanır.
   - `personnel_read_all` ve `support_all` ile aynı kurallar geçerlidir:
     - yalnız gerçek admin, başka bir kişiye verir;
     - rol varsayılanı, birim profili, şablon, arşiv veya geri alma bu yetkiyi oluşturmaz;
     - her değişiklik kayda geçer.
   - Yeni tablo veya migration gerekmez.
2. **Geçiş dönemi** (davranış değişmez). Unvanla tanınan mevcut başkanlar bir salt-okunur raporla listelenir. Gerçek admin, doğrulanmış başkana açık yetkiyi verir.
3. **Kapanış.** Unvan yolu kaldırılır; karar ve görüntüleme yalnız açık yetkiyle açılır. 14 sözleşme dosyası, onaylanmış yeni politikaya göre güncellenir.
   - Her değişiklik test silmeden yapılır.
   - Unvanın tek başına yetki vermediğini gösteren negatif testler eklenir.
4. **İK yayın görüntüleme yetkisi (`is_hr_publish_user`)** aynı yöntemle ele alınır: açık yetki ya da saklı `ik` rolü.
5. **Canlı ön koşul.** Canlıdaki gerçek başkanın hesabı salt-okunur doğrulanır. Açık yetki, adım 3'ten önce verilmiş olmalıdır; aksi hâlde yayın onayı akışı durur.

## 5. Karar gereken sorular

- Yayın onayında açık kişi bazlı yetki modeli kabul ediliyor mu?
- Geçiş dönemi ne kadar sürecek? Unvan yolu hangi tarihte kapanacak?
- Vekâlet nasıl tanımlanacak? Çoklu rol tasarımı (belge 13) ile ilişkisi.
