# BYS360 Şema Yeniden Kurulum Sınırlaması (P1-02 / P2-06)

**Durum tarihi:** 2026-09-28 (final pre-live denetim düzeltme kampanyası V1; canlı salt okuma doğrulaması sonucu §6'da)
**Kaynak:** `reports/quality/BYS360_SCHEMA_REPRODUCIBILITY_INVENTORY_V1.json` / `.md`
**Üretici:** `scripts/quality/bys360_schema_reproducibility_inventory_v1.py` (salt okuma; canlı veya PostgreSQL veritabanına bağlanmaz)
**CI sözleşmesi:** `tests/architecture/test_schema_reproducibility_inventory_contract.py`

Bu belge bilinen bir sınırlamayı dürüstçe kayda geçirir. Bir düzeltme veya migration içermez.

## 1. Ne doğru, ne eksik

- **Doğru:** Alembic zinciri sağlıklıdır: tek head, boş veritabanından head'e yükseltme ve ikinci yükseltmenin no-op olması CI'da PostgreSQL 15 ile doğrulanır. `bys360-prod-2026.09.23-1ea5c5dc` etiketinden bu yana yeni migration yoktur; bir sonraki adayın cutover'ı mevcut canlı şemayı değiştirmez.
- **Eksik:** Belgelenen kurulum ve felaket kurtarma yöntemi yalnız `flask db upgrade`'dir. Bu yöntem her ORM tablosunu üretmez:

| Sınıf | Tablo | Anlamı |
|---|---:|---|
| `MIGRATION_PRESENT` | 131 | Bir Alembic revizyonu tabloyu oluşturur. |
| `RUNTIME_DDL_ONLY` | 3 | Yalnız uygulama çalışırken `CREATE TABLE` ile oluşur (`message_comments`, `message_reactions`, `message_typing_states`). |
| `NO_REPRODUCIBLE_SOURCE_ACTIVE` | 28 | Depoda hiçbir DDL yok, uygulama kullanıyor. Bu tablolar yalnız geçmişteki `db.create_all()` veya onarım çalışmalarının yapıldığı veritabanlarında vardır. |
| `NO_REPRODUCIBLE_SOURCE_CANDIDATE_DEAD` | 2 | Depoda DDL yok, `app/models` dışında referans yok (`portal_comment_reactions`, `portal_pinned_posts`). Silinmedi; ölü olduğu canlıda doğrulanmadan kaldırılamaz. |

28 aktif tablo şunlardır:
- performans süreç motoru: `performance_process_flows`, `performance_process_flow_steps`, `performance_president_approvals`, `performance_low_score_processes`, `performance_process_notifications`;
- performans tarihçe ve arşiv: `performance_archived_results`, `performance_evaluation_history`, `performance_scoring_history`;
- geri bildirim: 8 `feedback_*` tablosu ve `performance_feedback_pipeline_flows` / `_steps`;
- portal: 9 `portal_*` tablosu;
- `publication_issues`.

**Şekil uyuşmazlığı:** `performance_low_score_process_events`, `9a5e1f4c2d60` migration'ı tarafından modelden farklı kolonlarla oluşturulur. Modelin `process_id`, `step_key`, `title`, `status`, `actor_user_id`, `note` kolonlarını depodaki hiçbir DDL üretmez. `performance_periods.special_scenario_type` için de depoda DDL yoktur.

Test paketi şemayı `db.create_all()` ile kurduğu için bu eksikleri göremez. CI'daki PostgreSQL kapısı da model ile şema arasındaki uyumu karşılaştırmaz.

## 2. Bu kampanyada yapılanlar (yalnız depo tarafı)

1. Envanter makine tarafından okunabilir hale getirildi (JSON ve Markdown rapor).
2. CI'ya sapma sözleşmesi eklendi. Şunlarda test kırılır:
   - yeni bir ORM tablosu migration'sız eklenirse;
   - listedeki bir tablo migration kazanırsa (liste açıkça küçültülmelidir);
   - yeni bir tablo, hiçbir DDL'in üretmediği ORM kolonları kazanırsa.
3. Hiçbir migration eklenmedi, hiçbir runtime DDL silinmedi, hiçbir model kaldırılmadı.

## 3. Canlıya geçişten önce gereken salt okuma doğrulaması

**Durum:** 2026-09-28'de tamamlandı; sonuç §6'da.

Canlı şema görülmeden adoption migration'ı yazılmaz. Aşağıdaki sorgular yalnız `SELECT` içerir. Açık yetkiyle ve salt okuma bir hesapla çalıştırılmalı, sonuç raporlanmalıdır:

```sql
SELECT version_num FROM alembic_version;                      -- beklenen: v1a2d3e4f5b6

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (/* rapordaki no_migration_tables listesi */);

SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('performance_low_score_process_events', 'performance_low_score_processes',
                     'performance_periods', 'performance_process_flows')
ORDER BY table_name, ordinal_position;
```

Karar kuralları:
- Tablo canlıda yoksa, ilgili ekranın canlıda çalışmadığı kabul edilir; bu ayrıca raporlanır.
- Tablo canlıda farklı kolonlarla varsa, adoption migration'ı canlıdaki şekle göre yazılır. Şekil tahmin edilmez.
- Canlıdaki şekil modelden farklıysa, önce kod ile canlı arasındaki anlam farkı bir insan tarafından karara bağlanır.

## 4. Düzeltme planı (ayrı paket, canlı kanıttan sonra)

1. Aktif 28 tablo ve 3 runtime-only tablo için adoption migration'ları yazılır. Emsal: Dosya Merkezi için `10858a18e9ac`. Migration'lar idempotent olur (`has_table` kontrolü) ve mevcut canlı tablolara dokunmaz.
2. `performance_low_score_process_events` için uzlaştırma migration'ı yazılır. Canlı şekil ORM ile aynıdır (§6). Bu migration yalnız boş veritabanından kurulumun da aynı şekli üretmesi içindir; canlı tabloyu değiştirmez.
3. CI'ya, PostgreSQL'e upgrade sonrası `db.metadata` ile gerçek şemayı kolon düzeyinde karşılaştıran bir kontrol eklenir. İlk adım atıldı: kapı artık kritik okuma yollarının kolonlarını (`CRITICAL_COLUMNS`) denetliyor (§6).
4. GET istekleriyle çalışan runtime DDL (P2-06) kaldırılır. Denetim taramasında 28 GET adresi, yani takma adlarıyla birlikte yaklaşık 18 endpoint, çalışırken `CREATE TABLE` / `CREATE INDEX IF NOT EXISTS` üretti; örnekler `/performance/v2-1-4-category-scope` ve `/performans/donem-yonetim-merkezi`. Bu kaldırma ancak 1–3 tamamlandıktan sonra yapılabilir. O zamana kadar uygulama veritabanı kullanıcısı DDL yetkisine ihtiyaç duyar.
5. Olası ölü iki portal modeli canlıda boş ve kullanılmıyor olarak doğrulandıktan sonra ayrı bir paketle kaldırılır.

## 5. Felaket kurtarma için geçici kural

Planlı geri dönüş ve felaket kurtarmada **veritabanı yedekten geri yüklenir** (`BACKUP_RUNBOOK.md`). Boş bir veritabanında `flask db upgrade` çalıştırmak bugün çalışan bir BYS360 kurulumu **üretmez**. Yukarıdaki plan tamamlanana kadar sıfırdan kurulum bir geri dönüş yöntemi olarak kullanılmaz.

## 6. Canlı salt okuma doğrulaması sonucu (2026-09-28)

Ayrıntı: [BYS360_LIVE_READONLY_VALIDATION_2026-09-28.md](BYS360_LIVE_READONLY_VALIDATION_2026-09-28.md).

- Canlı Alembic revizyonu `v1a2d3e4f5b6`'dır ve depodaki head ile aynıdır.
- 164 ORM tablosunun 164'ü canlıda vardır. Dağılım: 131 migration'lı, 28 aktif DDL'siz, 2 ölü aday ve 3 runtime-only tablo. Bu nedenle canlı için eksik tablo yoktur.
- `performance_low_score_process_events` tablosunun canlı şekli ORM ile aynıdır. `performance_periods.special_scenario_type` canlıda vardır. Canlı için migration gerekmez.
- Kanıtlanan iki uyumsuzluk migration'sız, kod tarafında düzeltildi:
  - `PerformancePresidentApproval.rule_version` modelden kaldırıldı. Bu kolonu ne canlı tablo ne de şema sahibi olan `6f2b8c4d1a90` migration'ı içerir.
  - AI Faz 8 ham SQL'i kanonik kolonlara taşındı.
- `performance_president_approvals` aslında `6f2b8c4d1a90` migration'ı ile oluşturulur. Envanter bu tabloyu migration'sız sınıflar, çünkü migration tablo adını bir sabitle verir. Bu yüzden modelle migration arasındaki kolon farkı envanterde görünmedi.
- Bu belgedeki boş veritabanı sınırlaması (§1, §5) değişmedi: canlıda bulunan şema, depodan sıfırdan üretilemez.

## 7. Gece düzeltme paketi sonrası durum (2026-09-28, yerel dal, canlıya alınmadı)

§4'teki planın 1–3. adımları ve 4. adımın büyük kısmı `fix/schema-runtime-ddl-wave1` dalında yerel olarak tamamlandı:

- **Adım 1–2:** `w2d8e1f4a6c3` migration'ı, hiçbir revizyonun oluşturmadığı 29 ORM tablosunu (28 aktif tablo ve runtime-only `message_*` tabloları dahil) yalnız yoksa ORM tanımıyla oluşturur. `performance_periods.special_scenario_type` kolonunu yalnız yoksa ekler. Boş ve 6. faz şeklindeki `performance_low_score_process_events` tablosuna ORM kolonlarını, yabancı anahtarları, tekil kısıtı ve indeksleri ekler. Satır içeren eski şekilli tabloya dokunmaz ve uyarı yazar. Canlıda bu nesnelerin hepsi var olduğu için (§6) migration canlıda hiçbir şeyi değiştirmez.
- **Adım 3:** PostgreSQL kapısına `POSTGRES15_ORM_PARITY` adımı eklendi. Boş veritabanından head'e yükseltmeden sonra 164 ORM tablosunun ve 2061 kolonun tamamı aranır. Eksik varsa kapı kırılır. Önceki head (`w1c5a7d2e9b4`) ile yapılan negatif kontrolde 29 tablo eksik bulunur.
- **Adım 4:** GET isteklerindeki runtime DDL kaldırıldı. Kalan ham SQL tabloları `flask runtime-schema check` ile salt okuma denetlenir ve yalnız `flask runtime-schema provision` ile açıkça oluşturulur.
- Envanter aracı, tablo adını sabitle veren migration'ları görmediği için 4 tabloyu hâlâ `NO_REPRODUCIBLE_SOURCE_ACTIVE` gösterir (`performance_president_approvals`, `performance_process_flows`, `performance_process_flow_steps`, `performance_process_notifications`). PostgreSQL kapısının ORM karşılaştırması bu tabloların boş kurulumda oluştuğunu kanıtlar.

**Kalan açıklar:**
- 6 tabloda 12 kolonun tipi veya NULL kuralı modelden farklıdır (örneğin `announcements.media_url`, `evaluation_assignments.due_date`). Mevcut kolonu değiştirmek ekleyici bir işlem olmadığı için bu migration'a alınmadı.
- `performance_interim_notes` ve yönetici kurulum eylemlerinin oluşturduğu tablolar insan kararı bekler.

**§5 için güncelleme:** Boş veritabanında `flask db upgrade` ve ardından `flask runtime-schema provision` artık ORM şemasının tamamını üretir. Bu yol üretime benzer uçtan uca bir kurulumla henüz denenmediği için felaket kurtarmada birincil yöntem yedekten geri yüklemedir.
