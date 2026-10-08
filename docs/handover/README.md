# BYS360 Devir ve Operasyon Dokümanları — Index

> **Tarihsel snapshot — 2026-08-24:** Ana devir belgesi, özellik matrisi ve `BYS360_CURRENT_PRODUCTION_STATE.json`, bu tarihteki üretim/devir kaydının dondurulmuş görüntüsüdür. Sonraki tarihli açıklamalar kendi tarihsel bağlamlarıyla korunur. Güncel üretim kimliği için [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md) esas alınır; bu belgelerdeki eski SHA ve kanıtlar güncel üretim beyanı değildir.

```
FROZEN HISTORICAL HANDOVER SNAPSHOT (2026-08-24):
BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md

Historical Production SHA:
cb2e57c5d1829ea743c696ae78595a20755f3f07
```

Bu klasör, BYS360 projesinin kurulum, canlıya alma, bakım, güvenlik, modül envanteri ve süreklilik planı dokümanlarını içerir.

[BYS360_CURRENT_PRODUCTION_STATE.json](BYS360_CURRENT_PRODUCTION_STATE.json), adında
`CURRENT` geçmesine rağmen **2026-08-24 frozen historical snapshot**'ıdır.
`document_status: HISTORICAL_FROZEN` tüm tarihsel içeriği sınıflandırır;
`superseded_by: SOURCE_OF_TRUTH.md` repository kökündeki güncel üretim referansına işaret eder.
Eski SHA, tarihler, sayılar, score ve evidence alanları tarihsel kayıt olarak korunur.

## Okuma Sırası (Yeni Operatör İçin)

1. **[SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md)** — güncel üretim kimliği ve kayıtlı doğrulama kanıtlarının referansı.
2. **[BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md](BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md)** — 2026-08-24 üretim/devir snapshot'ı; mimari, deployment, DB, backup, CI, güvenlik, Scheduled Task, rollback ve disaster-recovery kayıtları tarihsel bağlamıyla korunur.
3. **[BYS360_FEATURE_COVERAGE_MATRIX.md](BYS360_FEATURE_COVERAGE_MATRIX.md)** — aynı tarihsel snapshot'ın repo-türetilmiş özellik envanteri (38 feature) ve devir-kapsam sınıflandırması (DOCUMENTED/PARTIAL/UNDOCUMENTED/HISTORICAL/FUTURE).
4. Kök dizindeki [DEPLOYMENT.md](../../DEPLOYMENT.md) ve [BACKUP_RUNBOOK.md](../../BACKUP_RUNBOOK.md) — tarihsel ana dosyanın dayandığı operasyonel referanslar; snapshot etiketlemesi bu prosedürlerin yeniden doğrulandığı anlamına gelmez.
5. Kök dizindeki [README.md](../../README.md), [CONTRIBUTING.md](../../CONTRIBUTING.md) ve [SECURITY.md](../../SECURITY.md) — genel bakış ve katkı kuralları.

Aşağıdaki listedeki dosyalar **SUPERSEDED** veya **HISTORICAL**'dir (silinmemiştir; eski belgelerin tarihsel sınıflandırması için ana devir snapshot'ının §33 "Eski Belgeler" bölümüne bakın):

| Belge | Durum | Tarih |
|---|---|---|
| `BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md` | **HISTORICAL / FROZEN SNAPSHOT** | 2026-08-24 |
| `BYS360_FEATURE_COVERAGE_MATRIX.md` | **HISTORICAL / FROZEN SNAPSHOT** (companion) | 2026-08-24 |
| `BYS360_CURRENT_PRODUCTION_STATE.json` | **HISTORICAL_FROZEN** (dosya adındaki CURRENT güncel üretim anlamına gelmez) | 2026-08-24 |
| `BYS360_DEVIR_PAKETI_V1.md` | SUPERSEDED | 2026-06-24 |
| `BYS360_KURULUM_REHBERI.md` | SUPERSEDED | 2026-06-24 |
| `BYS360_CANLIYA_ALMA_REHBERI.md` | SUPERSEDED | 2026-06-24 |
| `BYS360_BAKIM_RUNBOOK.md` | SUPERSEDED | 2026-06-24 |
| `BYS360_GUVENLIK_KVKK_NOTLARI.md` | SUPERSEDED | 2026-06-24 |
| `BYS360_MODUL_ENVANTERI.md` | SUPERSEDED | 2026-06-24 |
| `BYS360_RISK_VE_SUREKLILIK_PLANI.md` | SUPERSEDED | 2026-06-24 |
| `HANDOVER_10_10_EVIDENCE_20260708.md` | HISTORICAL | 2026-07-08 |

## Temiz Kaynak Noktası (Tarihsel)

- Temizlik etiketi: `local-clean-ai-traces-complete-20260624`
- Devir doküman dalı: `handover-docs-v1`
- Bu etiket/dal referansı bu index güncellemesi sırasında repo içinde bağımsız olarak yeniden doğrulanmamıştır. Ana belgedeki `Production Source SHA`, 2026-08-24 tarihsel snapshot'ına aittir; güncel üretim kimliği için [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md) kullanılır.

## Devir Notu

Bu dokümanlar, kaynak kodun yanında teslim edilmesi gereken operasyonel bilgi setidir. Gerçek parola, token, gizli anahtar, veritabanı şifresi veya kişisel veri içermez.
