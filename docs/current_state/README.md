# BYS360 Current-State Dokümantasyon Paketi — Dizin

> **Dondurulmuş tarihsel snapshot — 2026-09-02:** Bu dizindeki paket, aşağıdaki tarih ve kaynak kod referanslarıyla sınırlı tarihsel kayıttır. "Yerel HEAD", "bu worktree", "CURRENT" ve mevcut durum ifadeleri o tarihteki bağlamı anlatır. Güncel üretim kimliği için [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md), sonraki teknik değerlendirme için [2026-09-30 teknik incelemesi](../technical-review/BYS360_TEKNIK_INCELEME_2026-09-30.md) kullanılır.
>
> Puantaj dahil gelecekteki modüllere ilişkin planlar **tarihsel planlamadır; güncel geliştirme yetkisi değildir**. Projenin mevcut kapanış kapsamı yeni modül, yeni özellik veya kapsam genişlemesi içermez. Aşağıdaki tarihsel kayıt ve kanıtlar korunmuştur.

Doküman Adı: BYS360 Current-State Dokümantasyon Paketi Dizini
Doküman Türü: İndeks
Kurum: Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı
Sürüm: Current-State 1.0 (v2 — dokümantasyon sertleştirme fazı: DOC-20 eklendi, belgeler arası çapraz doğrulama tamamlandı, Puantaj soru sayımı düzeltildi)
Tarih: 2026-09-02
Durum: Puantaj Öncesi Mevcut Durum Dokümanı
Kaynak Kod Referansı: 873e6d3348e644c5384a33a99c517600a3346cfd
Uzak CI Referansı: 7d73ff4d468cad11d78d2339ba770f70b5ec0baf (uzaktan doğrulanmış tarihsel/mevcut kontrol noktası, yerel HEAD değil)
Son Güncelleme: 2026-09-02

---

## Bu paketin amacı

Bu dizin (`docs/current_state/`), BYS360'ın AK defektinin kapatılmasından sonra, Puantaj geliştirmesi başlamadan önce hazırlanan **kurumsal devir-teslim ve teknik belge setidir**. Amacı, sistemin mevcut durumunu — mimari, kurulum, işletim, güvenlik, test kanıtı, devredilebilirlik ve açık teknik maddeler dahil — kaynak koddan doğrudan doğrulanmış, kanıta dayalı biçimde kayıt altına almaktır.

**Bu paket şu anlama GELMEZ:** final proje kapanışı, uzak sunucuda (CI) bu HEAD için tazelenmiş sonuçlanmış bir doğrulama turu, veya nihai üretim kabulü. Bkz. "Statü ve sınırlar" bölümü.

## Kanonik SHA notu — üç farklı SHA aynı anda dolaşımda

Bu paketin tamamı **yerel HEAD `873e6d3348e644c5384a33a99c517600a3346cfd`** için yazılmıştır. Ayrıca dolaşımda iki başka SHA daha vardır: önceki bir doğrulama turunda bildirilen **uzak doğrulanmış kontrol noktası `7d73ff4d468cad11d78d2339ba770f70b5ec0baf`** (yerel HEAD ile birebir aynı değildir) ve `docs/handover/BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md`'nin kendi kanonik SHA'sı **`cb2e57c5d1829ea743c696ae78595a20755f3f07`** (2026-08-24, `docs/handover/README.md` tarafından hâlâ "CURRENT" işaretli). Bu current-state paketi, bu üç SHA'yı birbirine karıştırmaz; her belgede hangi SHA'ya ait bilgi olduğu açıkça belirtilir. Final dokümantasyon yenilemesinde tek bir kanonik "aktif SHA" belirlenmesi önerilir (bkz. `BYS360_CURRENT_STATE_FACTS.md`).

Ayrıca bu worktree'de, bu pakete tamamen yabancı, **dördüncü bir SHA'ya** (`ec4e56b...`) ait, izlenmeyen (untracked) kalıntı dosyalar bulunmaktadır (`AGENT2_REPORT.md`, `AGENT3_REPORT.md`, `reports/executive/BYS360_Kurumsal_Rapor_Kaynak.md`, `scripts/windows/deploy_bys360_ec4e56b_production_v*.ps1`). Bunlar farklı, bağımsız bir çalışma dalgasının kalıntılarıdır; bu paketin bir parçası değildir, silinmemiş/taşınmamıştır.

## Belge listesi

### Kurumsal / Yönetici belgeleri (jargon içermez, Başkanlık'a sunulabilir)

| # | Belge | Kapsam |
|---|---|---|
| 01 | [01_BYS360_Kurumsal_Proje_ve_Yonetici_Raporu.md](01_BYS360_Kurumsal_Proje_ve_Yonetici_Raporu.md) | Kurumsal genel bakış, değer, modüller, yönetişim, olgunluk, Puantaj, final adımlar |
| 17 | [17_BYS360_Baskanlik_Yonetici_Ozet_Raporu.md](17_BYS360_Baskanlik_Yonetici_Ozet_Raporu.md) | 2-4 sayfalık en kısa özet (Başkanlık) |

### Teknik / Mimari

| # | Belge | Kapsam |
|---|---|---|
| 02 | [02_BYS360_Sistem_Mimarisi_ve_Teknik_Tasarim.md](02_BYS360_Sistem_Mimarisi_ve_Teknik_Tasarim.md) | Uygulama mimarisi, route modeli, Redis, mobil/API, dağıtım topolojisi |
| 10 | [10_BYS360_Veritabani_ve_Migration_Yonetimi.md](10_BYS360_Veritabani_ve_Migration_Yonetimi.md) | PostgreSQL, Alembic, şema koruma, migration disiplini |
| 12 | [12_BYS360_Modul_Envanteri_ve_Fonksiyonel_Kapsam.md](12_BYS360_Modul_Envanteri_ve_Fonksiyonel_Kapsam.md) | Her modülün tam envanteri; Puantaj netleştirmesi |
| 16 | [16_BYS360_Teknik_Envanter_ve_Bagimlilik_Listesi.md](16_BYS360_Teknik_Envanter_ve_Bagimlilik_Listesi.md) | Dil/çerçeve/bağımlılık/port/dizin envanteri |
| 20 | [20_BYS360_Kurumsal_Tasarim_ve_Arayuz_Standardi.md](20_BYS360_Kurumsal_Tasarim_ve_Arayuz_Standardi.md) | Kurumsal görsel kimlik (ana renk, filigran), bileşen/form/tablo standardı, teknik dil yasağı, Puantaj tasarım sözleşmesi |

### Operasyon / Kurulum / Release

| # | Belge | Kapsam |
|---|---|---|
| 03 | [03_BYS360_Kurulum_Yapilandirma_ve_Canliya_Gecis_Kilavuzu.md](03_BYS360_Kurulum_Yapilandirma_ve_Canliya_Gecis_Kilavuzu.md) | Kurulum önkoşulları, ortam, çevrimdışı bağımlılık, canlıya geçiş |
| 04 | [04_BYS360_Isletim_Bakim_ve_Guncelleme_Kilavuzu.md](04_BYS360_Isletim_Bakim_ve_Guncelleme_Kilavuzu.md) | Günlük/haftalık/aylık bakım, log, sürüm takibi |
| 06 | [06_BYS360_Yedekleme_Geri_Donus_ve_Felaket_Kurtarma_Kilavuzu.md](06_BYS360_Yedekleme_Geri_Donus_ve_Felaket_Kurtarma_Kilavuzu.md) | Yedekleme, RPO/RTO, restore, felaket kurtarma |
| 13 | [13_BYS360_Operasyon_ScheduledTask_ve_Servis_Yonetimi.md](13_BYS360_Operasyon_ScheduledTask_ve_Servis_Yonetimi.md) | Windows Scheduled Task modeli, PT72H sertleştirmesi (canlı görevde uygulanmış) |
| 14 | [14_BYS360_Release_Candidate_Cutover_ve_Rollback.md](14_BYS360_Release_Candidate_Cutover_ve_Rollback.md) | Release/candidate/cutover/rollback tam akışı |
| 15 | [15_BYS360_Sorun_Giderme_ve_Mudahale_Kilavuzu.md](15_BYS360_Sorun_Giderme_ve_Mudahale_Kilavuzu.md) | Sorun giderme senaryoları |

### Güvenlik / Devir / Kalite

| # | Belge | Kapsam |
|---|---|---|
| 05 | [05_BYS360_Guvenlik_Yetkilendirme_KVKK_ve_Denetim.md](05_BYS360_Guvenlik_Yetkilendirme_KVKK_ve_Denetim.md) | Kimlik doğrulama, yetkilendirme, KVKK, audit |
| 07 | [07_BYS360_Teknik_Devir_Teslim_ve_Surdurulebilirlik_Raporu.md](07_BYS360_Teknik_Devir_Teslim_ve_Surdurulebilirlik_Raporu.md) | Devir kapsamı, build/run/test komutları, SHA tutarsızlığı bulgusu |
| 08 | [08_BYS360_Devredilebilirlik_ve_Kurumsal_Bagimsizlik_Dokumani.md](08_BYS360_Devredilebilirlik_ve_Kurumsal_Bagimsizlik_Dokumani.md) | Tek-geliştirici riski, vendor bağımsızlığı |
| 09 | [09_BYS360_Test_Kalite_Guvencesi_ve_Dogrulama_Raporu.md](09_BYS360_Test_Kalite_Guvencesi_ve_Dogrulama_Raporu.md) | Test/kalite kanıtı, LOCAL rakamlar, exact-head kuralı |
| 11 | [11_BYS360_Rol_Yetki_ve_Erisim_Kontrol_Modeli.md](11_BYS360_Rol_Yetki_ve_Erisim_Kontrol_Modeli.md) | Rol/menü/erişim kontrol modeli, "menü gizleme tek başına güvenlik değildir" doğrulaması |

### Puantaj ve Açık Madde Defteri

| # | Belge | Kapsam |
|---|---|---|
| 18 | [18_BYS360_Puantaj_Gelistirme_Gereksinim_Eki.md](18_BYS360_Puantaj_Gelistirme_Gereksinim_Eki.md) | Puantaj onaylı kapsam + kurumdan beklenen netleştirmeler (uygulama belgesi DEĞİL) |
| 19 | [19_BYS360_Acik_Teknik_Madde_ve_Finalizasyon_Defteri.md](19_BYS360_Acik_Teknik_Madde_ve_Finalizasyon_Defteri.md) | **İç/teknik**, Başkanlığa sunulmaz. AL, PT72H, requirements.lock staleness, SHA tutarsızlığı vb. |

### Referans / Uzlaştırma

| Belge | Kapsam |
|---|---|
| [BYS360_CURRENT_STATE_FACTS.md](BYS360_CURRENT_STATE_FACTS.md) | Kanonik olgu defteri — tüm rakamların/iddiaların tek kaynağı |
| [BYS360_DOCUMENT_CONSISTENCY_MATRIX.md](BYS360_DOCUMENT_CONSISTENCY_MATRIX.md) | Belgeler arası tutarlılık kontrol tablosu |

## Paket büyüklüğü

**23 dosya:** 20 numaralı belge (01–20) + `BYS360_CURRENT_STATE_FACTS.md` + `BYS360_DOCUMENT_CONSISTENCY_MATRIX.md` + bu `README.md`.

## Statü ve sınırlar

- **Kaynak kod referansı:** `873e6d3348e644c5384a33a99c517600a3346cfd` (bu paketin tamamı bu HEAD için geçerlidir).
- **Bu paket final değildir.** "Tüm bilinen defektler kapandı" veya "üretim bu SHA'yı çalıştırıyor" gibi ifadeler bu pakette kullanılmamıştır ve final teslime kadar kullanılmamalıdır.
- **Puantaj henüz uygulanmamıştır.** Kod tabanında kapsamlı biçimde doğrulanmıştır (DOC-12 §11); bu paketteki hiçbir belge Puantaj'ı mevcut bir özellik olarak sunmaz. Kurumdan beklenen netleştirmeler artık 7 karar grubu altında **22 ayrı soru** olarak sayılmıştır (DOC-18 §3 — önceki "10 madde" sayımı yanıltıcıydı, bu fazda düzeltildi).
- **Kurumsal tasarım standardı eklendi (bu fazda):** DOC-20, BYS360'ın görsel kimliğini (ana renk `#8B0000`, ay-yıldız filigranı — ikisi de kod taramasıyla doğrulandı) ve arayüz/dil standardını tanımlar.
- **Belgeler arası çapraz doğrulama tamamlandı (bu fazda):** Doküman seti üzerinde çapraz tutarlılık incelemesi yürütüldü, bulgular `BYS360_DOCUMENT_CONSISTENCY_MATRIX.md`'de kayıtlıdır; tüm bulgular kaynağında düzeltilmiştir.
- **Scheduled Task PT72H sertleştirmesi uygulandı (bu fazda):** canlı görev doğrudan sertleştirildi — `ExecutionTimeLimit=PT0S`, `RestartCount=3`, `RestartInterval=PT1M`, mekanik olarak doğrulandı (bkz. DOC-13 §5, DOC-15 §3, DOC-19). Kaynak kod, veritabanı değişmedi; yeni bir release dağıtılmadı. Repo kurulum script'inin bu parametreleri geçirecek şekilde güncellenmesi ayrı, düşük öncelikli bir açık madde olarak kalıyor.
- **Değişmeyen alanlar (final SHA/uzak CI/FULL sonrası yenilenmeli):** üretimde fiilen çalışan Alembic revizyonu, canlı domain adının DNS doğrulaması, `requirements.lock`/`build/wheelhouse/`'ın güncel HEAD'e karşı yeniden üretilip üretilmeyeceği, üç-SHA tutarsızlığının çözümü, devredilebilirlik puanının yeniden hesaplanması, mevcut ekranların DOC-20 §10 (teknik dil yasağı) ilkesine uyumunun taranması.
- **Puantaj sonrası yenilenmeli:** modül envanteri (DOC-12), yetki modeli (DOC-11), açık teknik defter (DOC-19), kurumsal özet (DOC-01/17), Puantaj'ın semantik renk haritası (DOC-20 §13).

## Hangi belgeler kurumsal, hangileri teknik/iç?

- **Kurumsal (Başkanlığa sunulabilir, harf kodlu defekt referansı içermez):** DOC-01, DOC-17.
- **Teknik (geliştirme/operasyon ekibi için, defekt kodları ve dosya:satır referansları içerir):** DOC-02 – DOC-16, DOC-18, DOC-20.
- **İç/teknik, Başkanlığa sunulmaz:** DOC-19 (Açık Teknik Madde ve Finalizasyon Defteri), `BYS360_CURRENT_STATE_FACTS.md`, `BYS360_DOCUMENT_CONSISTENCY_MATRIX.md`.

## Bu pakette NO olan işlemler

Bu paketin hazırlanması sırasında hiçbir kaynak kod dosyası değiştirilmemiş, `git add`/`commit`/`push` yapılmamış, GitHub Actions tetiklenmemiş, üretime dokunulmamış, Puantaj uygulanmamış, AL veya başka bir defekt düzeltilmemiş, final FULL paket üretilmemiştir.
