# BYS360 Yapay Zekâ Kullanım ve İnsan Denetimi Politikası

**Kapsam:** Bu politika, BYS360'ın **yazılım geliştirme sürecinde** kullanılan yapay zekâ (AI)
destekli araçları kapsar. Uygulamanın kendi içindeki AI karar destek özelliklerinin sınırları ayrı
bir konudur; bkz. [SECURITY.md](SECURITY.md), "AI karar destek güvenliği".

## 1. Amaç

BYS360 geliştirme sürecinde AI destekli geliştirme araçları kullanılmaktadır. Bu belge, bu
araçların ne için kullanılabileceğini, neyi yapamayacağını ve kararların nasıl insan kontrolünde
kaldığını açıklar.

AI araçları tek başına şu kararları veremez:

- kod kabul kararı
- merge kararı
- production kararı
- deployment kararı

## 2. AI Nerede Kullanılabilir

- kod önerisi
- test önerisi ve test senaryosu önerisi
- dokümantasyon taslağı
- hata araştırması
- statik analiz bulgularının yorumlanması
- küçük, davranış değiştirmeyen (SAFE) refactor önerileri
- kod açıklama ve analiz desteği

Bunlar karar değil, öneridir. Her öneri, kaynağı ne olursa olsun, aynı kalite ve kabul sürecinden
geçer.

## 3. AI Ne Yapamaz

Açık insan talimatı olmadan AI:

- production deploy yapamaz
- production cutover yapamaz
- veritabanında değişiklik yapamaz
- migration uygulayamaz
- secret okuyamaz veya değiştiremez
- branch geçmişini yeniden yazamaz (history rewrite)
- force push yapamaz
- release oluşturamaz
- tag oluşturamaz
- kalite kapılarını düşüremez
- başarısız testleri gizleyemez
- test kapsamını yapay şekilde daraltamaz
- güvenlik veya yetkilendirme değişikliğini kendiliğinden kabul edemez
- production branch'ini kendi kararıyla değiştiremez

Bu sınırlar [AGENTS.md](AGENTS.md)'de tanımlanan çalışma kurallarıdır. Korunan branch'lerde
(`assistant-v2-full`, `docs/ministry-review-readme`) force push ve silme ayrıca GitHub ruleset'leri
ile teknik olarak engellenir. Diğer sınırlar kural, zorunlu CI kapıları ve insan tarafından
yürütülen deployment süreci ile uygulanır.

## 4. İnsan Kontrolü

İlke:

- **AI önerir.**
- **CI doğrular.**
- **İnsan kabul eder.**
- **İnsan production cutover kararını verir.**

Bu model "human-controlled acceptance" (insan kontrollü kabul) olarak adlandırılabilir. Ancak bu
ifade, her satırın bağımsız ikinci bir geliştirici tarafından manuel olarak incelendiği anlamına
**gelmez**.

Mevcut modelde:

- kabul kararı insan tarafından verilir
- zorunlu CI kalite kapıları çalışır
- pull request ve merge işlemi insan tarafından yürütülür
- production cutover insan tarafından gerçekleştirilir

BYS360 şu anda tek geliştirici tarafından yürütülmektedir. Branch kurallarında bağımsız ikinci bir
geliştiricinin onayı zorunlu değildir (gereken onay sayısı: 0). Zorunlu CI kapıları ve insan kabulü
bu boşluğu kısmen dengeler; ancak bağımsız insan incelemesinin yerini tutmaz.

## 5. Zorunlu Mekanik Kontroller

Korunan branch'lere pull request ile giren her değişiklik için CI kapıları:

- Ruff
- mypy
- pytest
- PostgreSQL migration integrity
- coverage ratchet
- secret/repository gate
- dependency audit

Production'a çıkış için release kontrolleri:

- deterministik release paketi doğrulaması
- exact-SHA takibi

Değişikliğin kaynağı insan ya da AI olsun, aynı kontrollerden ve aynı kabul sürecinden geçer. AI
tarafından üretilmiş olması bir değişikliği otomatik olarak güvenilir kılmaz ve bu kontrollerden
muaf tutmaz.

## 6. Risk Sınıflandırması

AGENTS.md her değişiklik adayını uygulamadan önce şu sınıflardan birine ayırır:

| Sınıf | Anlamı | AI'ın yapacağı |
|---|---|---|
| SAFE | Davranışın değişmediği kanıtlanmış küçük düzeltme | Tam inceleme ve hedefli testten sonra uygulayabilir |
| CONTROLLED | Davranış veya sözleşme etkisi olabilecek düzeltme | Değişiklik yapmadan durur |
| REVIEW | Niyet veya uyumluluk belirsiz | Yalnız analiz eder |
| BLOCKED | Gerekli ortam, test veya karar bulunmuyor | Değişiklik yapmaz |

Otomatik düzeltme yalnız SAFE adaylarda yapılabilir. SAFE dışındaki, davranışı etkileyebilecek
değişiklikler insan değerlendirmesi gerektirir.

## 7. Production Yetkisi

AI agent'ın production ortamında otonom işlem yapma veya kendi başına deployment ya da cutover
gerçekleştirme yetkisi yoktur. Deployment ve cutover insan tarafından yürütülür. Rollback,
kontrollü bir insan işlemi olarak yürütülür.

Bu bir yetki ve süreç sınırıdır: AGENTS.md, canlı sunucu, Waitress, PostgreSQL, zamanlanmış
görevler ve canlı dağıtım işlemlerini açık kullanıcı talimatı olmadan yasaklar. Bu belge,
geliştirme ortamı ile production sunucusu arasında ayrı bir teknik ağ veya sistem izolasyonu
bulunduğunu iddia etmez.

## 8. İzlenebilirlik

AI desteği commit metadata'sında `Co-Authored-By` satırlarıyla görülebilir; repository geçmişinde
bu tür kayıtlar bulunur ve bilinçli olarak gizlenmez veya silinmez. AI araçlarının çalışma kuralları
(`AGENTS.md`) ve yapılandırması (`.codex`) da repository'de açıkça yer alır.

Sınırlama: `Co-Authored-By` metadata'sı, bir commit içindeki hangi satırın AI veya insan
tarafından üretildiğini tek başına kanıtlamaz. Yalnız geliştirme sürecinde AI desteğinin
kullanıldığını gösteren bir izlenebilirlik bilgisidir. Bu satırın bulunmaması da o commit'te AI
desteği kullanılmadığını kanıtlamaz.

## 9. Sorumluluk

Teknik sorumluluk AI modeline ait değildir. Sorumluluk; insan geliştiricide, yetkili insan karar
süreçlerinde ve kurumsal yönetişimdedir ve zorunlu kalite ve deployment süreçleri çerçevesinde
yürütülür.

AI araçları karar verici, yetki sahibi, hukuki sorumlu aktör veya production sahibi olarak
tanımlanamaz.

## 10. İlgili Belgeler

- [AGENTS.md](AGENTS.md)
- [SECURITY.md](SECURITY.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [BACKUP_RUNBOOK.md](BACKUP_RUNBOOK.md)
- [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md)
