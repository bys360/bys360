# BYS360 CI — Step2 süresini azaltma planı (kanıta dayalı)

Durum: **yalnız plan**. Bu belgede önerilen hiçbir değişiklik uygulanmadı. Süre sınırını 240 dakikaya çıkaran kısa vadeli çözüm ayrı belgede: `BYS360_QUALITY_GATE_SURE_SINIRI.md`. Her adım ayrı Draft PR olacak; test seçimi, kapsam eşiği veya güvenlik denetimi değişiyorsa sahip onayı gerekir.

## 1. Ölçüm

**Kaynak:** taban commit `77b2f6d9` (`assistant-v2-full`) üzerindeki başarılı CI koşusu [38517750591](https://github.com/bys360/bys360/actions/runs/38517750591), GitHub'ın `ubuntu-latest` çalıştırıcısı.

**Yöntem:**
- Step2'nin pytest çıktısında her ilerleme satırı 72 testi kapsar ve GitHub her satıra zaman damgası basar (112 satır).
- Aynı commit'te aynı seçimle `pytest --collect-only` alındı: **8030 test**. CI'daki sayı da 8030 (8020 geçti, 10 atlandı). Sıra birebir eşleşiyor.
- Her satırın süresi, kapsadığı 72 teste eşit dağıtıldı ve dosya ile klasör bazında toplandı.

**Doğrulama:**
- Toplanan süre 169,1 dk. Adımın kendi süresi 169,4 dk (05:44:37 → 08:34:03). İkisi tutarlı.
- Sınır: bir satır içindeki testlerin eşit sürdüğü varsayıldı. Dosya düzeyindeki değerler bu yüzden yaklaşıktır. Klasör toplamları ve sıralama bu varsayıma duyarlı değil.

**Yerel bileşen ölçümü** (aynı commit, sahte anahtar, geçici SQLite):

| İşlem | Süre |
|---|---|
| `create_app()` | 1,0–3,0 sn (ilk çağrı yavaş) |
| `db.create_all()` | **2,8–2,9 sn** |
| `runtime_schema.provision_all()` | 0,01–0,6 sn |
| `User.set_password()` (1 kullanıcı) | 0,12 sn |

## 2. Bulgular

### 2.1 Klasör bazında Step2 (169 dk)

| Klasör | Süre | Pay | Test | sn/test |
|---|---|---|---|---|
| `tests/security` | 74,6 dk | %44,1 | 3072 | 1,46 |
| `tests/behavior` | 50,6 dk | %29,9 | 1807 | 1,68 |
| `tests/performance` | 15,1 dk | %8,9 | 464 | 1,95 |
| `tests/integration` | 8,8 dk | %5,2 | 265 | 1,99 |
| `tests/communication` | 6,6 dk | %3,9 | 79 | 4,99 |
| `tests/services` | 4,5 dk | %2,7 | 817 | 0,33 |
| `tests/architecture` | 4,5 dk | %2,7 | 583 | 0,46 |
| diğer (quality dosyası, kök dosyalar, release, critical, mobile, migrations) | 4,4 dk | %2,6 | 943 | — |

### 2.2 Yoğunlaşma

- 518 dosyanın en yavaş **30'u** sürenin yarısını alıyor.
- En yavaş dosya: `tests/security/test_k5q_f4_support_counter_scope_contract.py`, 114 testte yaklaşık 10,4 dk (5,5 sn/test).
- **Kök neden kalıbı:** her test için yeni uygulama ve sıfırdan şema kuran fikstür (`create_app()` + `db.create_all()`; module, session veya class kapsamı yok).
  - Bu kalıp **190 dosyada, 3229 testte** var.
  - Bu testler **124 dk (%74)** sürüyor. Kalan 328 dosya ve 4801 test toplam 45 dk.
- Bileşen ölçümüyle tutarlı: şema oluşturma tek başına test başına yaklaşık 2,9 sn. Buna uygulama kurulumu (~1 sn) ve kullanıcı başına parola hash'i (0,12 sn) ekleniyor.

### 2.3 Diğer adımlar

Step2 dışındaki bütün adımlar toplam yaklaşık 7 dk sürüyor. Bunlar:
- kurulum
- gizli bilgi kapısı, sürüm denetimi, Ruff
- Step1 (4,5 dk)
- PostgreSQL (30 sn)
- mypy (40 sn)
- `pip-audit` (10 sn)

Bu adımları bölmek kayda değer kazanç sağlamaz.

## 3. Seçenekler

### A. Şema şablonu: oturumda bir kez kur, her teste kopyala (en büyük kazanç)

- Şema (`create_all` + `provision_all`), oturum başında bir kez geçici bir SQLite dosyasına kurulur.
- Her test bu dosyanın kopyasını (`shutil.copyfile`, milisaniyeler) kendi benzersiz yolunda kullanır.
- **Test başına yalıtım korunur:** her test yine kendi boş veritabanı dosyasını alır. Test gövdeleri, iddiaları ve seçim aynı kalır.
- Tahmini kazanç: 3229 test × ~2,5 sn ≈ **~135 dk** CPU süresi. Bu Step2'nin büyük bölümü; kesin değer pilotla ölçülmeli.
- Risk ve sınıf: `CONTROLLED`. Fikstür davranışı değişir.
  - Şablonun, testin ortam değişkenleri ve yapılandırmasıyla aynı şemayı üretmesi gerekir.
  - Bazı dosyalar şemayı farklı yapılandırmayla kuruyor olabilir; bunlar pilotta ayrılır.
- Parola hash'i değiştirilmez. Daha ucuz hash kullanmak güvenlik testlerinin anlamını değiştirir; önerilmez.

### B. Step2'yi paralel işlere bölmek (matrix), test kodu değişmeden

- Örnek 3 parça:
  1. `tests/security` (~75 dk)
  2. `tests/behavior` (~51 dk)
  3. geri kalan (~44 dk)
- `tests/security` ikiye bölünürse 4 parça olur ve her biri ~40–50 dk sürer.
- Duvar saati süresi en uzun parça + ~7 dk olur: ~50–85 dk. Toplam CPU süresi değişmez.
- Gerekenler:
  - Her parça kendi kapsam verisini üretir. Son işte `coverage combine` yapılır, ardından kapsam ratchet'i, mypy, Quality9 ve `pip-audit` çalışır.
  - Şu an kapsam tek iş içinde `--cov-append` ile birikiyor.
  - İş akışını sabitleyen sözleşme testlerinin güncellenmesi gerekir: `test_postgres_migration_ci_enforcement_contract.py` (`STEP2_COMMAND_NEEDLE`), `test_ci_test_selection_blind_spot_contract.py`, `test_ci_coverage_scope_contract.py`, `bys360_quality9_ci_gate.py`, `bys360_ops_audit.py`. Bu bir test sözleşmesi değişikliği ve sahip onayı gerektirir.
- Risk ve sınıf: `CONTROLLED`. Seçim kayması olabilir, yani bir test hiçbir parçaya düşmeyebilir ya da iki parçaya birden düşebilir. Koruma: parçaların birleşiminin bugünkü seçimle aynı olduğunu ve çift kimlik bulunmadığını sınayan bir test.

### C. `pytest-xdist` (tek iş içinde 4 süreç)

- Yeni bağımlılık getirir (tedarik zinciri, `pip-audit`).
- Paylaşılan dosya yolları, ortam değişkenleri ve sıra bağımlılığı gibi yalıtım riskleri ölçülmedi.
- Kazanç çekirdek sayısıyla sınırlı (~3×).
- **Şimdilik önerilmez.** A ve B'den sonra gerekirse ayrıca değerlendirilir.

## 4. Önerilen sıra ve kabul ölçütleri

Her adım ayrı Draft PR olur. Her adımda şu ölçütler aranır:
- toplanan test sayısı (bugün 8030) ve test kimlikleri aynı;
- deselect ve atlanan test sayısı aynı;
- kapsam yüzdesi aynı commit'teki tabanla eşit;
- CI yeşil;
- süre ölçülmüş olarak raporlanmış.

1. **A-pilot:** en yavaş tek dosyada şablon fikstürü. Önce ve sonra süresi ölçülür, test sayısı ve sonuçları aynı kalır. Kabul: dosya süresi en az %50 kısalır, 0 davranış farkı.
2. **A-yayılım:** en yavaş 30 dosya (sürenin yarısı), dosya dosya veya küçük paketlerle. Her paketten sonra Step2 süresi ölçülür.
3. **B (gerekirse):** A'dan sonra Step2 hâlâ 60 dk'nın üstündeyse matrix'e bölünür. Sözleşme testi değişikliği için sahip onayı alınır.
4. Süre kalıcı olarak 120 dk'nın altına indiğinde, `timeout-minutes` değeri ölçüme göre yeniden ayarlanır. Bu da ayrı ve sahip onaylı bir PR olur.

## 5. Sahip kararı gereken konular

- A için: fikstür değişikliği (`CONTROLLED`). Pilot dosya seçimi ve kabul ölçütü.
- B için: iş akışını sabitleyen sözleşme testlerinin güncellenmesi.
- Ayrı bulgu (bkz. `BYS360_QUALITY_GATE_SURE_SINIRI.md` §5): süre alt sınırı testi gerçek değeri değil bir yorum satırını okuyor.
