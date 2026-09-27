# BYS360 Kritik İşlemlerde Eşzamanlılık Matrisi (P2-05)

**Durum tarihi:** 2026-09-28 (final pre-live denetim düzeltme kampanyası V1)
**Sözleşme testi:** `tests/performance/test_critical_operation_idempotency_contract.py`

Denetim yapısal bir risk tespit etti: kod tabanında `SELECT ... FOR UPDATE` kullanılmıyor. Aynı kayıt üzerinde eşzamanlı onay, yayın ve yeniden puanlamada son yazan kazanır. Bu bir **yapısal risktir**, yeniden üretilmiş bir veri bozulması değildir.

Bu kampanyada satır kilidi eklenmedi. Gerekçe: kilit davranışı yalnız PostgreSQL üzerinde doğrulanabilir; yerelde kullanılabilir bir PostgreSQL yok. Mevcut koruyucu kısıtlar ise bir sözleşme testiyle sabitlendi.

## Matris

| İşlem | Mevcut koruma | Kalan yarış | Sınıf |
|---|---|---|---|
| Değerlendirme açma | `uq_period_employee_evaluation` (dönem, personel) | Yok. İkinci kayıt `IntegrityError` alır. | KORUNUYOR (test) |
| Puan kalemi yazma | `uq_eval_criteria_level_item` (değerlendirme, kriter, seviye) | Aynı kalemin eşzamanlı güncellemesinde son yazan kazanır. | KORUNUYOR (çift kayıt yok, test) |
| Görev ataması | `uq_period_employee_evaluator_level_assignment` | Yok. | KORUNUYOR (test) |
| Snapshot / güncel sürüm | `uq_snapshot_period_employee_version` (dönem, personel, sürüm) | Aynı sonraki sürümü hesaplayan iki yayından biri commit edemez, yani çift "güncel" satır oluşmaz. Kısmi tekil indeks (`is_current`) yok. | KORUNUYOR (test) + indeks için CANLI DOĞRULAMA gerekli (mevcut veride çift güncel satır var mı) |
| Süreç akışı / 70 altı süreci | `evaluation_id` tekil | Yok. | KORUNUYOR (test) |
| Yayın (toplu / tekil) | Yayın politikası (`is_evaluation_publishable`); eski tekil rota `ensure_state_change` ile yeniden yayını reddeder | Eşzamanlı iki yayında bayraklar aynı değere yazılır. Yayın defterine ve bildirime iki kez gidebilir. | TEKNİK BORÇ (PostgreSQL eşzamanlılık düzeneği gerekir) |
| v2 tekil yayın servisi (`publish_single_evaluation`) | Yok. Yayında olan kartı yeniden damgalar ve bildirimi yeniden gönderir. | Bugün hiçbir rota bu fonksiyonu çağırmıyor, risk gizli. | ROTAYA BAĞLAMADAN ÖNCE: eski rotadaki `ensure_state_change` koruması eklenmeli |
| Yayın ön onayı / Başkan onayı kararı | Yetki kontrolü; `approved` üzerine tekrar `approved` kısa devre | Servisler onaylanmış veya iade edilmiş kaydın yeniden karara bağlanmasına bilinçli olarak izin veriyor. Eşzamanlı onay + iadede son yazan kazanır. | **İNSAN KARARI GEREKLİ** (ilk karar mı kazanır, yeniden karar serbest mi) |
| Yayınlanmış kartın yeniden puanlanması | P0.2S / P0.2T / P8: istek başında yayın durumu kontrolü | Yayın ile yeniden puanlama aynı anda gelirse, kontrol ile yazma arasında yarış penceresi var. | TEKNİK BORÇ (değerlendirme satırı kilidi; PostgreSQL eşzamanlılık testiyle) |

## Önerilen ayrı paket

1. CI'daki PostgreSQL 15 servisiyle iki bağlantılı bir eşzamanlılık test düzeneği kurulur.
2. Yayın ve yeniden puanlama yollarında aynı sırayla `with_for_update()` kullanılır: önce değerlendirme, sonra dönem. Böylece kilitlenme sırası sabit kalır. Değişiklik yalnız bu düzenek altında yapılır.
3. Onay kararları için kurum, ilk kararın mı kazanacağına yoksa yeniden kararın serbest mi olacağına karar verir. Karar verilmeden koşullu güncelleme (`WHERE status = 'pending'`) eklenmez; bu, bugün izin verilen yeniden kararı yasaklar.
4. Snapshot için `(period_id, employee_id) WHERE is_current` kısmi tekil indeksi, canlıda çift güncel satır olmadığı salt okuma sorgusuyla doğrulandıktan sonra eklenir.
