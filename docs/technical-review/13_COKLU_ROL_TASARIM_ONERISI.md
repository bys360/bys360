# BYS360 — Çoklu Kurumsal Görev (Çoklu Rol) Tasarım Önerisi

**Durum:** TASARIM ÖNERİSİ, onaylanmadı. Bu gece kod, şema veya migration değişikliği **yapılmadı**.
**Tarih:** 2026-10-11 · **Kaynak:** `assistant-v2-full` @ `f796107f`

## 1. Sorun

- Bugün her kullanıcının tek bir saklı rolü vardır: `User.role` (bkz. `app/admin/routes.py` `ROLE_CHOICES`).
- Gerçek kurumda bir kişi aynı anda birden fazla görev taşıyabilir. Örnekler: bir grup başkanı başkan yardımcılığına vekâlet ederken, bir birim sorumlusu ayrıca İK yayın yetkilisi olabilir.
- Tek rol modelinde bu ihtiyaç bugüne kadar unvan, `role_label` veya serbest metinle karşılanmaya çalışıldı.
- Onaylı politika açıktır: **unvan, role_label veya serbest metin yetki oluşturmaz.** R05/R1 düzeltmeleri bu gece unvana dayalı yetki yollarını kapattı. Bu yüzden çoklu görev ihtiyacı açık ve denetlenebilir bir modelle karşılanmalıdır.

## 2. Tasarım ilkeleri (onaylı politikalardan türetildi)

1. **En az yetki.** Kişinin etkin yetkisi, kendisine açıkça verilmiş görevlerin birleşimidir. Varsayılan "yetki yok"tur.
2. **Teknik yöneticilik ≠ kurum verisine erişim.** `admin` (sistem yöneticisi) görevi personel ve performans verisi okuma yetkisi taşımaz. Bu tür yetkiler ayrı ve açık kişi bazlı izinlerle verilir (`personnel_read_all`, `support_all`).
3. **Yalnız gerçek admin atar.** Görev atama ve kaldırma yalnız saklı rolü tam `admin` olan hesap tarafından yapılır. Kişi kendine görev atayamaz.
4. **Kişi bazlı, süreli, denetlenebilir.** Her görevin başlangıcı, isteğe bağlı bitişi, atayanı ve gerekçesi saklanır. Her değişiklik `audit_logs` kaydı yazar.
5. **Belirsiz kapsam = ret.** Tanınmayan bir görev kodu hiçbir yetki vermez (fail closed).

## 3. Önerilen veri modeli (taslak; migration onayı gerekir)

```
user_duties
  id              PK
  user_id         FK users.id, NOT NULL
  duty_code       VARCHAR(64) NOT NULL   -- kapalı liste (enum tablosu veya CHECK)
  scope_unit_id   FK organization_units.id NULL  -- görevin geçerli olduğu birim; NULL = kurum
  is_acting       BOOLEAN NOT NULL DEFAULT FALSE -- vekâlet
  valid_from      DATE NOT NULL
  valid_until     DATE NULL
  granted_by      FK users.id NOT NULL   -- yalnız role='admin'
  grant_reason    TEXT NOT NULL
  revoked_at      TIMESTAMP NULL
  revoked_by      FK users.id NULL
  UNIQUE (user_id, duty_code, scope_unit_id, valid_from)
```

- `User.role` **kalır** ve "birincil görev" anlamını korur. Mevcut tüm kod onu okumaya devam eder (geriye uyumluluk).
- `duty_code` kapalı listesi: mevcut `ROLE_CHOICES` değerleri ve açıkça onaylanacak yeni görevler (ör. `ik_yayin_yetkilisi`, `personel_destek_grup_baskani`). Yayın onayında bugün unvanla ayırt edilen "hangi grup başkanı" bilgisi bu kodla saklı görev olur.
- Açık geniş veri yetkileri (`personnel_read_all`, `support_all`) **görev değildir**. Mevcut kişi bazlı `UserMenuPermission` grant modeli değişmeden kalır.

## 4. Yetki karar noktası

- Tek bir servis eklenir: `effective_duties(user, *, at=None, unit=None) -> frozenset[str]`.
- Döndürdüğü küme: `{User.role}` ile o tarihte geçerli ve iptal edilmemiş `user_duties.duty_code` değerlerinin birleşimi.
- Unvan, `role_label`, `position`, `gorev` veya `username` **hiçbir koşulda okunmaz**.
- `admin_required`, menü matrisi, performans değerlendirici zinciri, başkan onayları ve yayın onayı adım adım bu servise taşınır. Her taşıma kendi PR'ında, RED→GREEN testleriyle yapılır.
- Rol menü varsayılanları (`RoleMenuDefault`) her görev için ayrı uygulanır. Etkin menü, görevlerin menülerinin birleşimidir. Açık grant anahtarları rol varsayılanlarından hiçbir zaman gelmez (B1-F1 / K5-Q).

## 5. Yetki geçişleri ve riskler

| Geçiş | Risk | Önlem |
|---|---|---|
| Görev ekleme | Dolaylı ayrıcalık yükseltme | Yalnız gerçek admin; kendine atama yok; R05 korumalı hesap kuralları görev sahiplerini de kapsar. |
| Görev kaldırma / süresi dolma | Açık oturumda eski yetki | Kaldırmada `security_stamp` döndürülür; oturum yeniden kurulur. |
| Vekâlet | Süresiz kalan vekâlet | `valid_until` zorunlu; süresi dolan kayıt otomatik etkisizleşir. |
| Değerlendirici zinciri | Görevle kendini amir yapma | R05 P5 kuralı: admin dışı kullanıcı zincire kendini ekleyemez. |

## 6. Uyumluluk ve migration planı (onay sonrası)

1. **Faz 0 — onay:** Görev listesi ve kapsam kuralları insan onayıyla kesinleşir.
2. **Faz 1 — şema (yalnız ekleme):** `user_duties` tablosu Alembic migration'ıyla eklenir. Mevcut tablolara dokunulmaz.
   - Önce izole shadow DB'de prova yapılır.
   - Geri dönüş: tabloyu düşüren downgrade.
3. **Faz 2 — okuma servisi:** `effective_duties()` eklenir. Başlangıçta yalnız `User.role` döndürür; davranış değişmez.
4. **Faz 3 — yönetim ekranı:** Görev atama ve kaldırma ekranı eklenir. Erişim yalnız gerçek admine açıktır; yeniden doğrulama ve `audit_logs` kaydı istenir. Geri alma için tablo kayıtları iptal edilir; satır silinmez.
5. **Faz 4 — karar noktaları:** Karar noktaları birer birer taşınır. Her adımda negatif testler ve tam regresyon çalıştırılır.
6. **Veri taşıma:** Unvandan otomatik görev **türetilmez**. Gerçek görevler insan tarafından listelenir ve admin tarafından girilir.

## 7. Açık sorular (karar gerekli)

- Görev kodu listesi ve hangi görevin hangi menü ve onay yetkisini verdiği.
- Vekâletin azami süresi.
- Birim kapsamlı görevlerde alt birimlerin kapsama dahil olup olmadığı.
- Mobil API'nin çoklu görevi aynı fazda mı yoksa sonra mı destekleyeceği.
