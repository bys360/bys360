# BYS360 — Teknik İnceleme ve Devir Raporu

**Hazırlanma:** 11–12 Ekim 2026 · **Durum:** TASLAK. `PENDING` olarak işaretli alanlar henüz doğrulanmadı.
**Son güncelleme:** 12 Ekim 2026 (bkz. §7 zaman damgaları)

| Kimlik | Değer | Kanıt |
|---|---|---|
| Geliştirme dalı | `assistant-v2-full` @ `f796107fa6ab42096065a02d4724ec7e8d22f608` | GitHub, 11.10.2026 23:29 (+03) |
| Son belgelenmiş production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` (tag `bys360-prod-2026.10.07-cdae2795`) | `SOURCE_OF_TRUTH.md` §1. Bu rapor canlıyı ayrıca doğrulamadı. |

Bu rapor bir onay veya sertifika değildir. Her iddia, belirtilen commit'e ve komut çıktısına dayanır.

**Durum etiketleri** birbirinden ayrıdır. Her biri ayrı kanıt ister ve birbirinin yerine kullanılmaz:

| Kısaltma | Anlamı |
|---|---|
| **K** | Kod hazır |
| **HT** | Hedefli test PASS |
| **GR** | Geniş regresyon PASS |
| **CI** | İki zorunlu CI SUCCESS (aynı exact HEAD'de) |
| **BI** | Bağımsız güvenlik incelemesi PASS |
| **M** | Merge edildi |
| **P** | Production'a alındı |
| **CD** | Canlıda doğrulandı |

## 0. Yönetici özeti

- **Production** hâlâ `cdae2795` sürümünü çalıştırıyor. 9–11 Ekim'de birleştirilen yetki düzeltmeleri (#57, #59, #60, #62–#64, #66, #67) **canlıda değildir**; canlıya geçmeleri için ayrı bir cutover kararı gerekir.
- **Açık güvenlik PR'ları** (#70, #65, #68, #69, admin PR'ı ve #57 takip PR'ı) taslak hâlindedir. **Hiçbiri merge edilmedi.**
- **Kritik bağımlılık:** #70 (hesap yönetiminde ayrıcalık yükseltme) ile #65 (açık `support_all` yetkisi) birlikte değerlendirilmelidir. #70 tek başına P1b'yi kapatmaz.
  - Birleşik kodda 430 güvenlik sözleşme testi geçti.
  - Birleşik kodun bağımsız güvenlik incelemesi **henüz yapılmadı**.
- **Açık politika kararı (P2c):** Personel ve Destek Hizmetleri yayın onayını veren grup başkanı hâlâ **unvanla** tanınıyor. Kapatmak için karar gerekiyor (belge 14).
- **Production için engel (#68):** Canlıdaki ön katmanın (IIS/proxy/LB) `/static` yolunu doğrudan diskten sunup sunmadığı bilinmiyor.
  - Bu doğrulanmadan ve eski dosyaların taşınması ile geri dönüş prova edilmeden özel dosya değişikliği canlıya alınamaz.
- **Production GO/NO-GO:** **NO-GO** (bkz. §11).

## 1. Proje amacı ve kurumsal kapsam

BYS360, kurumun bütünleşik yönetim sistemidir. Kapsamı:

- personel ve organizasyon;
- performans değerlendirme, geri bildirim ve görüşmeler;
- destek talepleri ve iletişim;
- Dosya Merkezi;
- yapay zekâ asistanı;
- mobil uygulama ve PWA.

Ayrıntı: `README.md`, `ARCHITECTURE.md` ve [03_MODUL_ENVANTERI.md](03_MODUL_ENVANTERI.md).

## 2. Güncel teknik mimari

Bileşenler:

- Flask uygulama fabrikası ve blueprint'ler;
- PostgreSQL ile SQLAlchemy/Alembic (production migration head `x1f3a9c5e7b2`);
- isteğe bağlı Redis;
- Windows Scheduled Task ile çalışan Waitress;
- kimliği belgelenmemiş bir TLS ön katmanı;
- Flutter mobil uygulama ve PWA;
- imzalı mobil API token'ları.

Ayrıntı ve kaynak satırları: [02_TEKNIK_MIMARI.md](02_TEKNIK_MIMARI.md).

## 3. Modül ve işlev envanteri

[03_MODUL_ENVANTERI.md](03_MODUL_ENVANTERI.md) dosyasında 24 modül listelenir. Bir modülün durumu yalnız doküman veya test kanıtı varsa yazılır; kanıt yoksa "kanıt yok" denir.

## 4. Yönetim, rol ve erişim kontrolü

Ayrıntı: [04_ROL_VE_YETKI_MIMARISI.md](04_ROL_VE_YETKI_MIMARISI.md). Özet:

- **Tek rol.** Her hesabın tek bir saklı rolü vardır (`User.role`).
- **`admin_required`** admin ailesinin tamamını kabul eder: admin, başkan, başkan yardımcısı, grup başkanı, mali müşavir. Gerçek admin, saklı rolü tam `admin` olan hesaptır.
- **Menü matrisi** üç katmandan oluşur: rol varsayılanı → birim profili → kişi bazlı ayar.
- **Açık kişi bazlı yetkiler.** Kurum geneli personel okuma (`personnel_read_all`) ve tüm destek talepleri (`support_all`, #65) yetkileri yalnız gerçek admin tarafından, başka bir kişiye verilir.
- **Onaylı politikalar (insan onayı, 9–10 Ekim 2026):**
  - en az yetki;
  - teknik sistem yöneticiliği kurum verisine erişim vermez;
  - unvan veya serbest metin yetki oluşturmaz;
  - geniş veri yetkisi açık, kişi bazlı ve denetlenebilir olur;
  - kapsamı belirsiz durumda erişim reddedilir.
- **Çoklu görev ihtiyacı** için tasarım önerisi hazırlandı; migration yok: [13_COKLU_ROL_TASARIM_ONERISI.md](13_COKLU_ROL_TASARIM_ONERISI.md).

## 5. Güvenlik bulguları çözüm matrisi

| Bulgu | PR | K | HT | GR | CI | BI | M | P | CD |
|---|---|---|---|---|---|---|---|---|---|
| R05 (F1, F3, F4, F5, R1, D3): admin olmayanın rol değiştirmesi ve korunan hesabı ele geçirmesi | #70 | ✔ | ✔ | Kısmi¹ | PENDING² | ✘³ | ✘ | ✘ | ✘ |
| R05 yeniden inceleme P1/P1c, P2 (dönem, hatırlatma, izleme, yönetici görünümü), P3, P4, P5 | #70 | ✔ | ✔ | Kısmi¹ | PENDING² | ✘³ | ✘ | ✘ | ✘ |
| **P1b:** admin olmayanın `support_all` vermesi | #65 | ✔ | ✔ (birleşik 430) | Kısmi⁴ | PENDING | ✘³ | ✘ | ✘ | ✘ |
| **P2c:** yayın onayı başkanının unvanla tanınması | — | ✘ **OPEN** | — | — | — | — | — | — | — |
| K5-Q: `support_all` yalnız açık kişi bazlı yetki; kapsam dışı talep bilgisinin sızmaması | #65 | ✔ | ✔ (308) | Kısmi⁴ | PENDING | ✘³ | ✘ | ✘ | ✘ |
| F06b: teknik rollerin geri bildirim entegrasyon sayfasında kurum verisi görmesi | #69 | ✔ | ✔ (42) | Codex: PENDING | ✔ `21a40fa8` | ✔ (AI, `0e190ee2`)⁵ | ✘ | ✘ | ✘ |
| B2-F06: özel dosyaların `/static` altında herkese açık olması | #68 | ✔ | ✔ (141) | ✘ | PENDING | **CHANGES-NEEDED** | ✘ | ✘ | ✘ |
| #57 takip: geri bildirim görüşme ve talep web ekranlarında 15 sızıntı | #57 takip | ✔ | PENDING | PENDING | ✘ | ✘ | ✘ | ✘ | ✘ |
| Canlı admin hesabı bulunamıyor / ilk giriş / kurtarma | admin PR | ✔ | ✔ (92) | PENDING | ✘ | ✘ | ✘ | ✘ | ✘ |
| B2-F01…F05: oturum ve kimlik doğrulama yaşam döngüsü | — | Tanımı bulunamadı⁶ | — | — | — | — | — | — | — |

Dipnotlar:

1. 36 dosyalık modül regresyonu `f8c6df9f` üzerinde çalıştı. P2c geri alındıktan sonra etkilenen 14 dosya ve R05b `d8068ae0` üzerinde 229/229 geçti. Tam regresyon çalışmadı.
2. `d8068ae0` için: score100 SUCCESS; Run tests son kontrolde çalışıyordu.
3. `e2832218` sürümünün bağımsız incelemesi CHANGES-NEEDED verdi; bulgular `f8c6df9f`'de düzeltildi. Son sürümün ve #70 ile #65'in birleşik kodunun bağımsız incelemesi **yapılmadı**.
4. #65'in önceki sürümü (`866d8c63`) için 104 dosyalık regresyon: 2271 geçti, 0 kaldı (PR açıklaması). Güncel `fb1acdc4` için: 308 sözleşme testi geçti; geniş regresyon çalışmadı.
5. Codex'in bağımsız yapay zekâ incelemesi `0e190ee2` üzerinde yapıldı. `21a40fa8`, bundan yalnız bir test satırıyla ayrılır; uygulama kodu aynıdır.
6. Depoda, PR'larda ve issue'larda B2-F01…F05 için tanım bulunamadı. Bu kimlikler yalnız #59 açıklamasında, kararları ayrıca verilecek bir başlık olarak geçiyor.

## 6. PR'lar ve exact SHA'lar

| PR | Konu | Exact HEAD | Durum |
|---|---|---|---|
| [#70](https://github.com/bys360/bys360/pull/70) | R05 hesap yönetimi yetkisi | `d8068ae04250ad366fd2e17151d5a652744da7be` | Draft |
| [#65](https://github.com/bys360/bys360/pull/65) | K5-Q `support_all` | `fb1acdc4802a0d2a26eef43fcf686c5b67a1eb82` (ana dal birleştirildi) | Draft |
| [#69](https://github.com/bys360/bys360/pull/69) | F06b | `21a40fa8813cc5501e7f83a2b511bfc2161025fa` | Draft |
| [#68](https://github.com/bys360/bys360/pull/68) | B2-F06 özel dosyalar | `f79ab0a3709c018666e7f2b9975d223725f103ce` | Open |
| Admin PR | Admin hesap yönetimi | PENDING | Henüz açılmadı |
| #57 takip PR | Geri bildirim web ekranları | PENDING | Henüz açılmadı |

## 7. GitHub CI ve test kanıtları

PENDING. Son okumada her PR'ın iki zorunlu CI sonucu buraya yazılacak.

## 8. Bağımsız güvenlik incelemeleri

| PR | İncelenen SHA | Sonuç | Not |
|---|---|---|---|
| #70 | `e2832218` | CHANGES-NEEDED | 13 sonda testi 7 açığı doğruladı. P1/P1c, P2, P3, P4 ve P5 `f8c6df9f`'de kapandı; P1b #65'te, P2c OPEN. Son sürüm incelenmedi. |
| #65 | `866d8c63` | Önceki oturumda adversarial inceleme yapıldı | Birleşik #70 + #65 incelemesi yapılmadı. |
| #69 | `0e190ee2` | Codex: engelleyici bulgu yok | Uygulama kodu güncel HEAD ile aynı. |
| #68 | `582c1a76` | CHANGES-NEEDED | F1 ve F3 kapalı. F2 kısmi (portal, mesaj ve yayın yazımları). F4 kısmi (statik altındaki bağlantının özel köke işaret etmesi; publications alt dizini). Ön katman bilinmiyor. Eski dosya taşıma betiği yok. |

## 9. Açık güvenlik riskleri

1. **P2c:** yayın onayı başkanı unvanla tanınıyor (OPEN, karar gerekiyor; belge 14).
2. **#70 + #65 bağımlılığı:** biri diğeri olmadan merge edilirse açık kalır.
3. **#68 ön katman ve dosyalar:** IIS/proxy davranışı, eski dosyaların taşınması ve geri dönüşte erişilemez kalacak yüklemeler.
4. **Rol tanımı:** `User.role` serbest metin. Bazı hiyerarşi yardımcıları (`is_system_user`, `is_president`) hâlâ unvana bakıyor. Bunlar performans kapsamını ve değerlendirici zincirini etkiler (belge 04 §8).
5. **Unvana bakan diğer kontroller:** phase7 arşiv, phase11 raporlama ve Dosya Merkezi'nin unvana bakan kontrolleri (REVIEW).
6. **Production:** yukarıdaki düzeltmelerin hiçbiri canlıda değil (bkz. §11).

## 10. Admin hesap yönetiminin durumu

PENDING. Doldurulacak: PR, testler ve CI.

Kök neden (yerel olarak yeniden üretildi, canlıya dokunulmadı):

- Genel listeler `role == "admin"` olan hesapları gizliyor.
- Hesap araması tam eşleşmeyle yapılıyor.
- Yeni hesabın gizli sorusu olmadığı için şifremi unuttum akışı çalışmıyor.
- Başlangıç şifresi yalnız flash mesajında gösteriliyor.

Çözüm (kod hazır):

- Admin hesapları görünümü yalnız gerçek admine açık: `/admin/users?view=admins`.
- Yeni başlangıç şifresi verilirken işlemi yapan admin kendi şifresini yeniden girer; işlem denetim kaydına yazılır ve şifre tek seferlik gösterilir.
- Arama normalleştirildi.

## 11. Canlı sürüm ile GitHub farkları

- `cdae2795..f796107f`: 18 PR merge'ü; 81 dosya, +5760 / −405 satır.
- **Migration, model veya şema değişikliği yok.**

Ayrıntı: belge 04 §9.

**Production GO/NO-GO: NO-GO.** Gerekçeler:

- Açık güvenlik PR'ları henüz merge edilmedi.
- P2c ve #68 ön katman doğrulaması açık.
- Bu gece shadow DB provası yapılmadı.
- Rutin dosya yedeği tanımlı değil.

## 12. Veritabanı / şema uyumluluğu

- `cdae2795` ile `f796107f` arasında migration farkı yok.
- Açık PR'ların hiçbiri migration içermiyor.

## 13. Dosya depolama ve reverse proxy riskleri

Kaynak: #68 bağımsız incelemesi (§8).

- **Ön katman:** IIS/proxy/LB'nin `/static`'i diskten sunup sunmadığı doğrulanmalı. Gereken salt-okunur komutlar belge 09'da.
- **Özel kök:** mutlak bir yolda ve proje ağacının dışında olmalı.
- **NTFS:** ACL'ler yalnız servis hesabı ve Administrators'a izin vermeli. Junction, symlink ve deduplication taraması yapılmalı.
- **Eski dosyalar:** önce kopyalayıp hash ile doğrulayan, sonra silen bir taşıma betiği gerekiyor (henüz yok).
- **Geri dönüş:** `cdae2795`'e dönülürse yeni yüklemeler erişilemez olur ve açık yeniden ortaya çıkar.

## 14. Yedekleme, rollback ve felaket kurtarma

Ayrıntı: [09_KURULUM_ISLETIM_IZLEME_YEDEK_ROLLBACK.md](09_KURULUM_ISLETIM_IZLEME_YEDEK_ROLLBACK.md).

- **Veritabanı yedeği** yalnız aday hazırlığında ve cutover'da alınıyor.
- **Dosya Merkezi ve özel kök için** rutin yedek yok.
- **RPO ve RTO** tanımlı değil.

## 15. Yapay zekâ destekli geliştirme süreci

[10_YAPAY_ZEKA_DESTEKLI_GELISTIRME_VE_INSAN_ONAYI.md](10_YAPAY_ZEKA_DESTEKLI_GELISTIRME_VE_INSAN_ONAYI.md) dosyasına ve `AI_USAGE_POLICY.md` belgesine bakınız.

## 16. Teknik devir ve sürdürülebilirlik

[11_TEKNIK_DEVIR_VE_BAKIM.md](11_TEKNIK_DEVIR_VE_BAKIM.md) dosyasına bakınız.

## 17. İnsan onayı bekleyen kararlar

1. Her PR için merge onayı. #70 ile #65 birlikte değerlendirilmeli.
2. P2c politika ve geçiş kararı (belge 14).
3. #68 için ön katman doğrulaması, eski dosyaların taşınması ve yedekleme kararı.
4. Production release ve cutover onayı (şu an NO-GO).
5. Çoklu görev tasarımının onayı (belge 13).
