# BYS360 CI — `quality-gate` süre sınırı: 180 → 240 dakika

Durum: kısa vadeli çözüm, proje sahibi onayıyla (17 Ekim 2026). Draft PR; merge ve canlıya geçiş yok.

## 1. Değişiklik

| | Önce | Sonra |
|---|---|---|
| `.github/workflows/bys360-ci.yml` → `jobs.quality-gate.timeout-minutes` | 180 | 240 |

Başka hiçbir şey değişmedi: test seçimi, test komutları, kapsam eşikleri, CSRF/CSP denetimleri, PostgreSQL 15 doğrulaması, mypy, Ruff, `pip-audit` ve diğer adımlar aynı. Ayrıştırılmış iş akışı (YAML) `timeout-minutes` dışında tabandakiyle birebir aynı (bkz. §4).

GitHub'ın barındırdığı çalıştırıcılarda bir işin üst sınırı 360 dakikadır; 240 bu sınırın altındadır.

## 2. Gerekçe: 180 dakika yetmiyor

### 2.1 180 dakika sınırında iptal olan koşular (0 test hatası)

| Koşu | PR / commit | Ne oldu |
|---|---|---|
| [38967292704](https://github.com/bys360/bys360/actions/runs/38967292704), deneme 1 | #76 / `335b3b6d` | Ana test adımı (Step2) 2 sa 53 dk'da **başarılı** bitti; PostgreSQL ve kapsam kapıları geçti; mypy adımı 41. saniyesinde iş sınırıyla kesildi (toplam 180 dk). Aynı commit'in 2. denemesi 117 dk'da yeşil. |
| [38992501593](https://github.com/bys360/bys360/actions/runs/38992501593) | #78 / `17a50281` | Step2 2 sa 54 dk çalıştı, iş sınırında iptal; sonraki adımlar atlandı. Belge dalı; bir sonraki commit'ler yeşil. |
| [39004392842](https://github.com/bys360/bys360/actions/runs/39004392842), deneme 1 | #82 / `3b0d5c25` | Step2 %92'deyken 0 hata ile iş sınırında iptal (07:56:20). Aynı kodu içeren #83 (`edf49eb0`) 146 dk'da yeşil. 2. deneme çalışıyor. |

Aynı dönemde `failure` sonuçlu koşular gerçek test veya lint hatalarıdır (ör. Ruff B007, CSP sabitleri); süre sınırıyla ilgileri yoktur ve bu tabloya alınmadı. Erken iptal edilen iki koşu (3 dk ve 15 dk; `fix/personnel-bulk-delete-archive-2026-1`) süre sınırı değildir.

### 2.2 Başarılı koşu süreleri (13–17 Ekim 2026, son 40 koşudaki başarılı 28 koşu)

- En kısa 103 dk, ortanca **160 dk**, en uzun **178 dk**.
- 28 koşunun 8'i 170 dk'nın üstünde, yani 180 sınırına 10 dk'dan az pay bıraktı. Taban dalın kendisi (`assistant-v2-full`, `77b2f6d9`) 177 dk sürdü.
- Süreyi neredeyse tamamen Step2 belirliyor (ör. #76 2. deneme: işin 117 dk'sının 112 dk'sı Step2; diğer bütün adımlar toplam ~5 dk). Aynı commit'in iki denemesi 180 (iptal) ve 117 dk sürdü: çalıştırıcı hızı koşudan koşuya büyük ölçüde değişiyor.

Süre: iş akışı koşusunun başlangıcı ile son güncellenmesi arası (GitHub Actions API, `run_started_at` → `updated_at`).

| Koşu | Deneme | Dal | Commit | Başlangıç (UTC) | Süre (dk) | Sonuç |
|---|---|---|---|---|---|---|
| [38333311730](https://github.com/bys360/bys360/actions/runs/38333311730) | 1 | `security/k5q-support-all-explicit-grant-2026-10-10` | `cbdfcd36` | 2026-10-13 01:41 | 162 | başarılı |
| [38350882602](https://github.com/bys360/bys360/actions/runs/38350882602) | 1 | `security/k5q-support-all-explicit-grant-2026-10-10` | `a4be996d` | 2026-10-13 05:20 | 104 | başarılı |
| [38357493503](https://github.com/bys360/bys360/actions/runs/38357493503) | 1 | `security/k5q-support-all-explicit-grant-2026-10-10` | `fa57879e` | 2026-10-13 06:34 | 154 | başarılı |
| [38376203876](https://github.com/bys360/bys360/actions/runs/38376203876) | 1 | `assistant-v2-full` | `7afeb9d3` | 2026-10-13 09:25 | 137 | başarılı |
| [38391302284](https://github.com/bys360/bys360/actions/runs/38391302284) | 1 | `claude/lucid-hawking-u4gpp0` | `edf00cfb` | 2026-10-13 11:35 | 166 | başarılı |
| [38403813636](https://github.com/bys360/bys360/actions/runs/38403813636) | 1 | `claude/lucid-hawking-u4gpp0` | `475baa4e` | 2026-10-13 13:17 | 173 | başarılı |
| [38463099446](https://github.com/bys360/bys360/actions/runs/38463099446) | 1 | `claude/lucid-hawking-u4gpp0` | `48a8e2e7` | 2026-10-13 20:28 | 137 | başarılı |
| [38517750591](https://github.com/bys360/bys360/actions/runs/38517750591) | 1 | `assistant-v2-full` | `77b2f6d9` | 2026-10-14 05:38 | 177 | başarılı |
| [38914564355](https://github.com/bys360/bys360/actions/runs/38914564355) | 2 | `fix/personnel-bulk-delete-archive-2026-10-16` | `c5e85655` | 2026-10-16 17:22 | 120 | başarılı |
| [38983866418](https://github.com/bys360/bys360/actions/runs/38983866418) | 1 | `ux/pilot-support-new-2026-10` | `5531f4a9` | 2026-10-16 23:54 | 165 | başarılı |
| [38984242390](https://github.com/bys360/bys360/actions/runs/38984242390) | 1 | `ux/wave2-support-list-2026-10` | `c09c2638` | 2026-10-16 23:59 | 178 | başarılı |
| [38984518818](https://github.com/bys360/bys360/actions/runs/38984518818) | 1 | `docs/ux-modernization-status-2026-10` | `6ab61f2d` | 2026-10-17 00:02 | 175 | başarılı |
| [38985923117](https://github.com/bys360/bys360/actions/runs/38985923117) | 1 | `ux/wave2-support-list-2026-10` | `bf467aab` | 2026-10-17 00:20 | 168 | başarılı |
| [38967292704](https://github.com/bys360/bys360/actions/runs/38967292704) | 2 | `fix/mobile-assistant-launcher-2026-10` | `335b3b6d` | 2026-10-17 00:26 | 117 | başarılı |
| [38986662192](https://github.com/bys360/bys360/actions/runs/38986662192) | 1 | `ux/wave3-support-detail-2026-10` | `1f7968b5` | 2026-10-17 00:30 | 114 | başarılı |
| [38987954932](https://github.com/bys360/bys360/actions/runs/38987954932) | 1 | `ux/wave4-help-center-2026-10` | `6f48b9bf` | 2026-10-17 00:47 | 147 | başarılı |
| [38988156167](https://github.com/bys360/bys360/actions/runs/38988156167) | 1 | `docs/ux-modernization-status-2026-10` | `a8357c92` | 2026-10-17 00:49 | 174 | başarılı |
| [38990013200](https://github.com/bys360/bys360/actions/runs/38990013200) | 1 | `ux/wave2-support-list-2026-10` | `03e96feb` | 2026-10-17 01:14 | 165 | başarılı |
| [38990438766](https://github.com/bys360/bys360/actions/runs/38990438766) | 1 | `ux/wave3-support-detail-2026-10` | `5da2bbba` | 2026-10-17 01:20 | 178 | başarılı |
| [38990440580](https://github.com/bys360/bys360/actions/runs/38990440580) | 1 | `ux/wave4-help-center-2026-10` | `8bc98cdc` | 2026-10-17 01:20 | 178 | başarılı |
| [38991288057](https://github.com/bys360/bys360/actions/runs/38991288057) | 1 | `docs/ux-modernization-status-2026-10` | `dfcf0039` | 2026-10-17 01:32 | 103 | başarılı |
| [38991310492](https://github.com/bys360/bys360/actions/runs/38991310492) | 1 | `docs/ux-modernization-status-2026-10` | `a70f3f28` | 2026-10-17 01:32 | 137 | başarılı |
| [38992491079](https://github.com/bys360/bys360/actions/runs/38992491079) | 1 | `docs/ux-modernization-status-2026-10` | `2becfef5` | 2026-10-17 01:49 | 169 | başarılı |
| [38992612881](https://github.com/bys360/bys360/actions/runs/38992612881) | 1 | `docs/ux-modernization-status-2026-10` | `526fa4ab` | 2026-10-17 01:51 | 114 | başarılı |
| [38993792162](https://github.com/bys360/bys360/actions/runs/38993792162) | 1 | `docs/ux-modernization-status-2026-10` | `b0b5d286` | 2026-10-17 02:09 | 131 | başarılı |
| [39004380889](https://github.com/bys360/bys360/actions/runs/39004380889) | 1 | `ux/wave5-help-pages-2026-10` | `370d497e` | 2026-10-17 04:55 | 158 | başarılı |
| [39004519256](https://github.com/bys360/bys360/actions/runs/39004519256) | 1 | `ux/wave7-help-admin-list-2026-10` | `edf49eb0` | 2026-10-17 04:58 | 146 | başarılı |
| [39004576274](https://github.com/bys360/bys360/actions/runs/39004576274) | 1 | `docs/ux-modernization-status-2026-10` | `b876032b` | 2026-10-17 04:59 | 177 | başarılı |

### 2.3 Neden 240

En yavaş başarılı koşunun (178 dk) üstünde ~60 dk pay. #82'nin iptal edilen koşusu %92'de 175 dk Step2 harcamıştı; aynı hızla tamamlanması ~195 dk sürerdi, 240 içinde kalır. Daha büyük bir değer, takılan bir koşunun çalıştırıcıyı gereksiz yere uzun tutmasına yol açar; bu yüzden üst sınır (360) seçilmedi.

## 3. Bu kısa vadeli bir çözümdür

Asıl sorun Step2'nin tek bir işte sıralı çalışması. Süreyi kalıcı olarak düşürme planı ayrı belgede: `docs/ci/BYS360_CI_TEST_BOLME_PLANI.md`. CI günlüğünden test dosyası başına ölçüm, Step2 süresinin %74'ünün test başına uygulama ve şema kuran 190 dosyada olduğunu gösteriyor. Plan uygulanana kadar bu sınır korunmalı.

## 4. Regresyon kontrolü (yerel, bu dalda)

1. Fark yalnız tek değer + açıklama yorumu: `git diff` → `-    timeout-minutes: 180` / `+    timeout-minutes: 240`, geri kalan eklemeler `#` yorum satırı.
2. YAML ayrıştırma: taban 180, yeni 240; `timeout-minutes` çıkarıldığında iki iş akışı birebir aynı (`True`).
3. İş akışını okuyan testler: `tests/architecture/test_postgres_migration_ci_enforcement_contract.py`, `test_ci_coverage_scope_contract.py`, `test_ci_default_branch_push_trigger_contract.py`, `test_ci_test_selection_blind_spot_contract.py`, `tests/quality/test_broad_except_ceiling_ratchet_contract.py`, `test_quality9_ci_safe_contract.py` → **357 geçti, 0 kaldı**.
4. Test dosyası değiştirilmedi, silinmedi, atlanmadı.

## 5. Karar gerektiren bulgu: süre testi gerçek değeri okumuyor

`test_quality_gate_job_timeout_has_an_evidence_backed_floor` iş başlığındaki **ilk** `timeout-minutes:\s*(\d+)` eşleşmesini alıyor. İş akışında bu eşleşme bir yorum satırına düşüyor (`# cancelled by its own timeout-minutes: 45 mid-Step2`). Test bu yüzden her zaman 45 okuyor, gerçek ayarı değil.

Kanıt (depoya dokunmadan, kopya üzerinde): gerçek değer `timeout-minutes: 10` yapıldığında test mantığı yine 45 okuyor ve **geçiyor**. Yani bugün gerçek süre 40 dk'nın altına düşürülse bu koruma yakalamaz.

Talimat gereği test bu PR'da değiştirilmedi. Önerilen küçük düzeltme (sahip onayı gerekir; ayrı commit/PR): eşleşmeyi yorum olmayan satırla sınırlamak, örneğin `re.compile(r"^\s*timeout-minutes:\s*(\d+)", re.MULTILINE)`. Alt sınır (40) ve testin amacı aynı kalır.

## 6. Güncel olmayan belgeler (bu PR'da değiştirilmedi)

- `docs/handover/BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md:553` ve `docs/current_state/16_BYS360_Teknik_Envanter_ve_Bagimlilik_Listesi.md:115` hâlâ `timeout-minutes: 45` yazıyor (değer zaten 180 iken). İkincisi kendini "belgeden türetilmiş, satır satır karşılaştırılmadı" olarak işaretliyor. Kapsamı dar tutmak için dokunulmadı; ayrı belge düzeltmesi olarak önerilir.
