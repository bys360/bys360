# BYS360 Canlı Salt Okuma Doğrulaması — 2026-09-28

**Kapsam:** Production ortamının salt okuma doğrulaması ve bunun aday hatla (`assistant-v2-full`) karşılaştırılması.
**Yöntem:** İnsan operatör tarafından açılan oturumda, `BEGIN TRANSACTION READ ONLY … ROLLBACK` içinde yalnız katalog (`information_schema` / `pg_catalog`) sorguları; sunucuda yalnız okuma yapan komutlar.
**Değişiklik:** Production'da hiçbir dosya, ayar, servis, görev veya veritabanı satırı değiştirilmedi. Bu belge parola, bağlantı bilgisi, gizli anahtar, kişi adı veya performans verisi içermez.

## 1. Production kimliği

| Kontrol | Sonuç |
|---|---|
| Çalışan kaynak SHA | `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6`. Loopback `/versionz` ve terfi makbuzu (`CANDIDATE_READY.json`) ile doğrulandı. Etiket: `bys360-prod-2026.09.23-1ea5c5dc`. |
| Alembic revizyonu (canlı) | `v1a2d3e4f5b6`. Depodaki tek head ile **aynı**. |
| HTTPS / hazırlık | HTTPS ve HSTS etkin; `/healthz` 200; `/readyz` `ready`, `schema_error_count = 0`, `app_env = production`. |

## 2. Şema eşliği

| Kontrol | Sonuç |
|---|---|
| ORM tabloları | 164 tablonun 164'ü canlıda var. Dağılım: `MIGRATION_PRESENT` 131/131, `NO_REPRODUCIBLE_SOURCE_ACTIVE` 28/28, `NO_REPRODUCIBLE_SOURCE_CANDIDATE_DEAD` 2/2, `RUNTIME_DDL_ONLY` 3/3. |
| `performance_low_score_process_events` | Canlı şekil ORM modeliyle **aynı**: `id`, `process_id`, `step_key`, `title`, `status`, `sort_order`, `actor_user_id`, `note`, `created_at`, `updated_at`. Beklenen PK/FK kısıtları ve `UNIQUE(process_id, step_key)` mevcut. Canlı için değişiklik gerekmez. |
| `performance_periods.special_scenario_type` | Canlıda **var**. Migration gerekmez. |
| AI Faz 7 arşiv kolonları | `performance_archived_results` üzerindeki `user_id`, `personnel_id`, `registry_no`, `personnel_name`, `period_year`, `period_title`, `score_value`, `score_label`, `general_comment`, `visibility_status` kolonları canlıda var. Faz 7 değiştirilmedi. |
| Dosya Merkezi | Odak tablo karşılaştırmasında eksik ORM kolonu yok. Değiştirilmedi. |

## 3. Kanıtlanan iki uyumsuzluk ve düzeltmesi

Düzeltme PR'ı: `fix/live-schema-evidence-remediation-v1` → `assistant-v2-full`. Migration eklenmedi.

### A. `performance_president_approvals.rule_version`

- **Kanıt:** ORM'de 14 kolon vardı, canlıda bunların 13'ü mevcuttu. Eksik olan kolon `rule_version`.
- **Kök neden:**
  - Tablonun şema sahibi olan adoption migration'ı `6f2b8c4d1a90` bu kolonu hiç oluşturmaz; bu tablodaki sürüm alanı `process_version`'dır.
  - Hiçbir runtime DDL de bu kolonu eklemez.
  - Model, süreç motorunun diğer tablolarındaki `rule_version` alanını kopyalamıştı.
  - Uygulamada bu kolonu okuyan veya yazan hiçbir kod yoktur. Tabloya yazma işlemleri ham SQL ile yapılır ve bu kolonu kullanmaz.
- **Etkisi:** Varlığın her ORM okuması (`.query…count()` / `.all()`) hem canlıda hem boş veritabanından kurulan şemada `UndefinedColumn` hatası verdi. Mobil Başkan/Üst Onay sayaçları ve listesi hatayı yutup 0 veya boş gösterdi.
- **Düzeltme:** `rule_version`, `PerformancePresidentApproval` modelinden kaldırıldı. Model artık canlıda doğrulanan 13 kolonla birebir aynıdır. Veri etkisi yoktur ve DDL çalıştırılmaz.

### B. AI Faz 8 ham SQL'indeki var olmayan kolonlar

- **Kanıt:**
  - Canlıda `evaluation_assignments.evaluated_user_id` ve `performance_periods.period_name` yoktur.
  - Boş veritabanından migration ile kurulan PostgreSQL 15 şemasında bunlara ek olarak `scope_reference`, `category_id` ve `unit_id` da yoktur.
  - Bu sütunlar ORM modelinde de bulunmaz.
- **Etkisi:** Sorgular, hata yakalayıcıdan önce çalıştıkları için her iki Faz 8 uç noktası da her istekte 500 döndürdü.
- **Düzeltme:** Sütunlar isim benzerliğine göre değil, anlam kanıtına göre eşlendi:
  - Değerlendirilen kişi `EvaluationAssignment.employee_id` sütunudur (ilişki adı `employee`).
  - Dönem başlığı `title` sütunudur; `normalize_period` önce `title`'ı okur.
  - Kapsam hedefi, `period_forms` doğrulamasının her kapsam tipi için zorunlu tuttuğu sütundur:
    - `unit` / `upper_unit` → `scope_unit_label`
    - `category` → `scope_category_label`
    - `selected_personnel` → yalnız bir personel filtresinin tanımlı olduğu bilgisi. Filtre sicil numaraları içerdiği için değeri çıktıya aktarılmaz.
  - Değerlendirici `evaluator_id` sütunuyla okunmaya devam eder.

### Doğrulama

- **Regresyon testleri:**
  - Dosyalar: `tests/behavior/test_president_approval_live_schema_contract.py` ve `tests/behavior/test_ai_decision_faz8_canonical_schema_contract.py`.
  - Tablo, ORM ile değil gerçek adoption migration'ı ile kurulur. Böylece testler production şekline karşı çalışır.
  - Testler, çalıştırılan SQL'i yakalayıp var olmayan kolon adları için denetler.
  - Anlam eşlemesi ve sicil numarasının çıktıya sızmaması da doğrulanır.
  - Testler düzeltme öncesi kodda başarısız olur, düzeltmeden sonra geçer.
- **CI PostgreSQL 15 kapısı:**
  - `scripts/quality/bys360_postgres_migration_integrity_gate.py` artık boş veritabanından head'e yükseltmeden sonra `CRITICAL_COLUMNS` kontrolü yapar.
  - Kontrol, onay modelinin tüm kolonlarının ve Faz 8 SELECT listelerinin varlığını denetler (toplam 31 kolon).
  - Liste ile uygulama kodu arasındaki eşleşmeyi testler korur.
- **Yerel PostgreSQL 15 kanıtı:** Tek kullanımlık bir kümede, boş veritabanından `v1a2d3e4f5b6` sürümüne yükseltme yapıldı ve kapı PASS verdi.
  - Düzeltme öncesi kod: onay ORM okumaları ve Faz 8 sorguları `UndefinedColumn` hatası verdi.
  - Düzeltme sonrası kod: hepsi başarıyla çalıştı.

## 4. Envanter notu

`reports/quality/BYS360_SCHEMA_REPRODUCIBILITY_INVENTORY_V1.json`, `performance_president_approvals` tablosunu `NO_REPRODUCIBLE_SOURCE_ACTIVE` olarak sınıflar. Oysa tabloyu `6f2b8c4d1a90` migration'ı oluşturur. Envanter aracı tablo adını migration'da düz metin olarak arar; bu migration adı bir `_TABLE_NAME` sabitiyle verdiği için tablo tespit edilemedi. Bu yüzden modelle migration arasındaki kolon farkı da envanterde görünmedi. Sayılar bu PR'da değiştirilmedi. Bu açığı artık PostgreSQL kapısındaki kolon kontrolü kapatır.

## 5. Canlıya özgü, bu PR'da değiştirilmeyen konular

- **Künye ayarları:** Canlıda eski durumdadır. `kunye.developer_label` eski etiketi, `kunye.developer_name` ise eski yazım biçimini taşır. `about.developer_name` günceldir. Eş geliştirici ayar satırı yoktur. Depodaki varsayılanlar kanoniktir: Geliştirici "Havva Gülsen Özden", Eş Geliştirici (Co-developer) "Mustafa Bektaş". Canlı ayarlar, kontrollü dağıtımdan sonra ayrı bir işlemle ele alınır.
- **`system_admin` rolü:** Canlıda aktif `system_admin` sayısı 0'dır. Süreç raporlarındaki fail-closed davranış korunur.
- **P0-01 tarihsel kanıt:**
  - Mevcut istek loglarında süreç raporu adreslerine ait kayıt yoktur (0).
  - Denetim kaydında 2026-05 ayına ait 2 eşleşen satır vardır.
  - Tarihsel erişim/denetim kaydı mevcuttur, ancak **istismar kanıtlanmamıştır**.
  - Kişi veya içerik incelenmedi.
- **Boş veritabanından kurulum:** Aşağıdakiler depoda hâlâ DDL karşılığı olmayan alanlardır:
  - `performance_periods.special_scenario_type`
  - `performance_low_score_process_events` tablosunun ORM şekli
  - Envanterdeki DDL'siz tablolar

  Bunlar canlıda mevcuttur. `BYS360_SCHEMA_RECOVERY_LIMITATION.md` belgesindeki kural geçerlidir: felaket kurtarmada veritabanı yedekten geri yüklenir.
