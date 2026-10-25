# Yapay Zekâ Destekli Geliştirme ve İnsan Onayı

**Bağlayıcı politika:** depo kökündeki `AI_USAGE_POLICY.md` ve `AGENTS.md` (`assistant-v2-full` @ `f796107f`). Bu belge, 9–12 Ekim 2026 güvenlik çalışmasında bu politikanın nasıl uygulandığını özetler.

## 1. Kullanılan araçlar ve roller

| Araç | Rol | Yetki sınırı |
|---|---|---|
| Claude Code (bulut oturumu) | Güvenlik düzeltmeleri, RED→GREEN testleri, bağımsız inceleme ajanları, teslim belgeleri. İlgili PR'lar: #70 (R05), admin hesap yönetimi PR'ı, #57 takip PR'ı, #68'deki secret-gate düzeltmesi. | Yalnız atanmış dallara push yapar. Merge, deploy, tag, release, migration ve canlı veri işlemi yapmaz. |
| Codex | #68 (B2-F06) ve #69 (F06b) geliştirmeleri. | Aynı politika. Codex'in yerel worktree'leri bu bulut oturumundan görülemez. |
| İnsan proje sahibi | Politika onayı, merge kararı, canlıya geçiş kararı. | Tek karar mercii. |

## 2. Uygulanan kontroller

- **Onaylı politika önce gelir.** Yetki kuralları insan tarafından onaylandı (2026-10-09/10: en az yetki, unvan yetki vermez, açık kişi bazlı geniş yetki, belirsiz kapsam = ret). Kod bu kurallara göre yazıldı ve test edildi.
- **RED→GREEN kanıtı.** Her güvenlik düzeltmesinde önce düzeltilmemiş kodda başarısız olan test yazıldı (RED), sonra düzeltme yapıldı (GREEN). RED ve GREEN çıktıları PR gövdelerinde ve teslim raporunda commit SHA ile birlikte verilir.
- **Bağımsız inceleme.** Düzeltmeyi yazan ajandan ayrı ajanlar, düzeltilmiş kodu kötü niyetli kullanıcı gözüyle denedi.
  - Örnek: #70'in `e2832218` sürümünde bağımsız inceleme 13 sonda testiyle 5 yüksek önem dereceli açık buldu ve PR'ı "CHANGES-NEEDED" ile geri çevirdi. Bulgular sonraki commit'te düzeltildi ve yeniden test edildi.
- **CI kapıları.** Her PR'da `quality-gate` (tam test, secret/repo gate, lint) ve `score100-quality-gate` zorunludur. Bir commit'in CI sonucu başka bir commit için kanıt sayılmaz.
- **Kalite kapısı düşürülmedi.** #68'deki secret-gate hatası tarayıcıyı gevşeterek veya allowlist ekleyerek değil, test fixture'ındaki sabit anahtarı çalışma anında üretilen anahtarla değiştirerek giderildi.
- **Yapılmayanlar.** Production deploy, servis yeniden başlatma, canlı veritabanı değişikliği, migration, dosya taşıma, tag ve release yapılmadı. Hiçbir PR insan onayı olmadan merge edilmedi.

## 3. Sınırlamalar (dürüst beyan)

- Yapay zekâ ajanlarının yazdığı testler, ajanların düşünebildiği saldırı yollarını kapsar. Bağımsız insan güvenlik incelemesinin yerini tutmaz.
- Canlı ortam (IIS/nginx, Windows ACL, gerçek veri) bu oturumdan görülemez. Canlıya ilişkin her ifade ya `SOURCE_OF_TRUTH.md`'deki insan doğrulamasına dayanır ya da "doğrulanmadı" diye işaretlenmiştir.
- Merge, canlıya alma ve canlı doğrulama kararları insana aittir.
