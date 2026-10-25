# BYS360 — Destek UX zinciri ve ilgili PR'lar için güvenli birleştirme planı

Durum: **plan**. Hiçbir PR birleştirilmedi. Birleştirme kararı ve işlemi proje sahibine aittir. Bu belge 17 Ekim 2026'da GitHub ve yerel git geçmişi üzerinden doğrulanan durumu anlatır.

## 1. Doğrulanan zincir

Hedef dal: `assistant-v2-full` @ `77b2f6d9`. Bütün PR'ların hedefi bu dal. Taban ilerlemediği için hiçbir dal tabanın gerisinde değil.

| Sıra | PR | Dal | HEAD | Tabandan önde | Bir önceki dalın HEAD'ini içeriyor mu? | Kendi commit'leri |
|---|---|---|---|---|---|---|
| 1 | #75 | `ux/pilot-support-new-2026-10` | `5531f4a9` | 11 | — (tabandan) | 11 |
| 2 | #77 | `ux/wave2-support-list-2026-10` | `03e96feb` | 15 | Evet (#75) | 4 |
| 3 | #79 | `ux/wave3-support-detail-2026-10` | `5da2bbba` | 17 | Evet (#77) | 2 |
| 4 | #80 | `ux/wave4-help-center-2026-10` | `8bc98cdc` | 19 | Evet (#79) | 2 |
| 5 | #81 | `ux/wave5-help-pages-2026-10` | `370d497e` | 22 | Evet (#80) | 3 |
| 6 | #82 | `ux/wave6-help-form-setup-2026-10` | `3b0d5c25` | 24 | Evet (#81) | 2 |
| 7 | #83 | `ux/wave7-help-admin-list-2026-10` | `edf49eb0` | 26 | Evet (#82) | 2 |

Komut: `git merge-base --is-ancestor origin/<önceki> origin/<sonraki>` (yedisi de başarılı) ve `git rev-list --count`.

**Önemli:** GitHub'daki her PR'ın farkı, hedef dala göre hesaplanır. Bu yüzden örneğin #83'ün "Files changed" sekmesi bugün #75–#83'ün **tamamını** gösterir. Bir PR'ın kendi değişikliği yalnız önündeki PR birleştikten sonra görünür hâle gelir.

## 2. Ortak dosyalar (çatışma riski)

Zincirdeki 37 dosyanın 15'ini birden fazla dalga değiştiriyor:

| Dosya | Değiştiren dalgalar |
|---|---|
| `app/static/css/bys360_components.css` | 7 dalganın hepsi |
| `tests/behavior/test_pilot_support_new_ux_contract.py` | 7 dalganın hepsi |
| Stil ratchet sabit dosyaları (10 test dosyası; `EXPECTED_ACTIVE_STYLE_TOTAL*`, `EXPECTED_STYLE_BLOCK_TOTAL*`) ve `test_csp_style_migration_cumulative_inventory_contract.py` | #75, #77, #80, #81, #82 |
| `app/templates/_ui_form.html`, `app/static/js/bys360_ui_form.js` | #75, #79, #82 |

Zincir içinde bu dosyalar **sırayla** değişti; her dalga bir öncekinin sonucunun üstüne yazıldı. Sırayla ve birleştirme commit'iyle birleştirildiğinde çatışma çıkmaz.

**Stil ratchet sabitleri tam sayıdır** (taban 1032/221 → #83'te 1003/217). Bu sayıyı değiştiren başka bir PR, dosya çakışması olmasa bile zincirin testlerini kırar. Bugünkü açık PR'lar için ölçüldü (`compute_inventory_at_git_ref`): #76, #72 ve #74 tabandaki 1032/221 değerini değiştirmiyor. Risk yok.

## 3. Zincir dışındaki açık PR'lar

| PR | Zincirle ortak dosya | Not |
|---|---|---|
| #76 Mobil asistan | Yok | Birleşik ağaç (#83 + #76) çatışmasız. İlgili testlerin birleşik ağaçtaki sonucu §6'da. |
| #78 Belgeler | Yok | Durum belgesi; en son birleştirilmeli (son durumu anlatır). |
| #84 CI süre sınırı | Yok | Yalnız iş akışı + açıklama belgeleri. |
| #85 Süre testi düzeltmesi | Yok | Yalnız `tests/architecture/test_postgres_migration_ci_enforcement_contract.py`. #84 ile birleşik ağaçta 21/21 geçiyor. |
| #86 Ana Sayfa, #87 Gösterge Paneli | Zincirin devamı | #83'ün üstüne sırayla kurulu (#83 → #86 → #87). İkisi de `bys360_components.css`'e dokunmuyor; sayfaya özel CSS dosyaları var. Pilot testindeki `DESIGN_SYSTEM_TEMPLATES` listesine birer satır ekliyorlar. |
| #69, #71, #72, #73, #74 (bu oturumun dışında açılmış) | Yok | Bu planın kapsamı dışında; dokunulmadı. #72 ve #74 şablon değiştiriyor ama stil ratchet toplamını değiştirmiyor. #69–#73'ün tabanı daha eski (`f796107f`, tabanın atası). |

## 4. Birleştirme yönteminin etkisi

**Önerilen: "Create a merge commit" (birleştirme commit'i), sırayla.**

- Commit SHA'ları korunur. #75 birleşince #77'nin farkı otomatik olarak yalnız kendi 4 commit'ine iner; aynı değişiklik ikinci kez uygulanmaz.
- Zincirdeki dallar zaten birbirinin birleştirme commit'lerini içeriyor (düzeltmeler üst dallara birleştirmeyle taşındı). Birleştirme commit'i yöntemi bu yapıyla uyumludur.

**Squash (tek commit'e sıkıştırma): önerilmez.**

- #75 squash edilirse hedef dala yeni bir commit (S1) girer. #77 ise #75'in **orijinal** commit'lerini taşımaya devam eder.
- GitHub #77'nin farkını yine eski ortak atadan (`77b2f6d9`) hesaplar. #75'in değişiklikleri #77'de yeniden görünür ve birleştirmede ikinci kez uygulanmaya çalışılır.
- Bu durumda çatışma ortak dosyalarda kesin çıkar: CSS'te, pilot testte ve ratchet sabitlerinde, çünkü sonraki dalgalar aynı satırları yeniden değiştirdi.
- Squash zorunluysa her birleştirmeden sonra bir sonraki dala hedef dalı birleştirip çatışmaları elle çözmek ve CI'ı yeniden koşturmak gerekir. Bu, 7 × ~3 saat CI ve elle çatışma çözümü demektir.

**Rebase ile birleştirme: önerilmez.**

- Commit'ler yeni SHA'larla yeniden yazılır, squash'taki sorun aynen oluşur.
- Dallarda birleştirme commit'leri bulunduğundan GitHub'ın rebase seçeneği reddedebilir ya da geçmiş düzleşir.
- Force-push gerektiren her yol kapsam dışıdır.

**Alternatif (önerilmez): yalnız #83'ü birleştirmek.**

- #83 bütün zinciri içerir. GitHub, HEAD commit'i hedef dala giren diğer PR'ları otomatik "merged" işaretler.
- Ancak bu, PR başına ayrı inceleme ve onay adımını atlar.

## 5. Önerilen sıra ve CI kuralı

Ön koşul: her PR'ın **kendi güncel HEAD'inde** iki zorunlu kontrol yeşil olmalı ve sahibin görsel onayı alınmış olmalı (#75 hariç, onay verildi).

1. **#84 + #85** (CI düzeltmesi, birlikte). Bunlar önce girerse, sonraki her yeniden koşu 240 dk sınırıyla ve gerçek değeri okuyan bir koruma testiyle çalışır.
   - Bedel: hedef dal değişeceği için zincirin her PR'ı birleşmeden önce yeni hedefe karşı bir kez daha CI'dan geçmeli.
2. **#75 → #77 → #79 → #80 → #81 → #82 → #83 → #86 → #87**, birleştirme commit'iyle, sırayla. Bir PR birleşince sonrakinin farkı otomatik daralır.
3. **#76** (asistan). Zincirden bağımsız; birleşik ağaç çatışmasız.
4. **#78** (belgeler) en son.

**CI ne zaman yeniden koşmalı?**

- Hedef dala zincir dışından bir değişiklik girdiyse (ör. önce #84/#85 birleştiyse), sıradaki PR'ın birleşim sonucu artık daha önce test edilen ağaç değildir.
  - O PR'a hedef dal **birleştirme commit'iyle** alınmalı (GitHub "Update branch" düğmesinin birleştirme seçeneği; force-push yok) ve CI yeniden koşmalı.
- Zincir arka arkaya, arada başka birleştirme olmadan girerse, sıradaki PR'ın birleşim sonucu kendi HEAD ağacıyla **birebir aynıdır**, çünkü önceki PR'ın bütün commit'lerini zaten içerir.
  - Bu durumda mevcut yeşil CI aynı ağacı test etmiştir. Yine de dal koruması "güncel olma" şartı istiyorsa GitHub yeniden koşturur.
- 180 dk sınırı geçerliyken yeniden koşular sınıra takılabilir. #84 önce birleşirse bu risk kalkar.

**Önerilen karar:**
- #84/#85 hızlıca incelenip önce birleşsin.
- Ardından zincir sırayla, her biri "Update branch (merge)" sonrası yeşil CI ile birleşsin.
- Bu, en güvenli (her birleşim ağacı test edilmiş) ama en uzun yoldur.
- Hız öncelikliyse zincir, #84'ten önce ve arada başka birleştirme olmadan, mevcut yeşil CI ile birleştirilebilir.

## 6. Birleşik ağaç doğrulaması (yerel)

Yerel ve push edilmeyen bir dalda `#83 + #76` birleştirildi (ağaç `534e86c2`); çatışma çıkmadı. Bu ağaçta zincirin değiştirdiği bütün test dosyaları, #76'nın testi ve CSP/asistan sözleşme testleri çalıştırıldı: **850 geçti, 2 atlandı, 0 kaldı.** (İlk denemede ağaç git geçmişi olmadan çıkarıldığı için git'e başvuran testler 136 hata verdi; gerçek yerel birleştirmede tekrarlanmadı.)

## 7. Birleştirmeden önce yapılması gerekenler

- #82: kendi HEAD'inde (`3b0d5c25`) `quality-gate` yeşil olmalı. #83'teki yeşil sonuç yardımcı kanıttır; #82'nin yerine geçmez.
- #77, #79, #80, #81, #82, #83: sahip görsel onayı (karşılaştırma sayfası).
- #79/#83 stil bloğu kararı (taşınmayacaksa ek iş yok).
- #80 terim kararı (birleştirmeyi engellemez; ayrı PR).
- #76: gerçek iPhone/Android denemesi önerilir. Emülasyon kanıtı tamamlanmış sayılmadı.
