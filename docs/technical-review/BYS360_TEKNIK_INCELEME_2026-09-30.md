# BYS360 — Teknik İnceleme

| Alan | Değer |
|---|---|
| Ürün | BYS360 — Bütünleşik Yönetim Sistemi 360 |
| Belge türü | Teknik İnceleme (giriş belgesi) |
| Tarih | 30.09.2026 |
| Varsayılan dal | `assistant-v2-full` @ `c03f9edc1dc20e58bca7c52f72aa5d1ee651264e` |
| Canlı kaynak | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` (`bys360-prod-2026.09.29-a5bd8a38`) |
| Biçimlendirilmiş kopya | [BYS360_Teknik_Inceleme_Paketi_2026-09-30.pdf](BYS360_Teknik_Inceleme_Paketi_2026-09-30.pdf) |

## 1. İnceleme Amacı

Bu belge, BYS360'ın teknik incelemesi için bir giriş noktasıdır. Aşağıdaki konuların tek yerden incelenebilmesi için özet ve kaynak bağlantıları sunar:

- mimari
- modüller
- güvenlik ve yetkilendirme
- testler ve CI
- migration ve release disiplini
- canlı sürüm (production) kimliği
- bilinen teknik borç
- insan kararı gerektiren konular
- sürdürülebilirlik ve devralma (handover)

> **Önemli:** Bu belge, Bakanlık veya başka bir makam tarafından verilmiş bir onay, sertifikasyon ya da değerlendirme kararı niteliği taşımaz. Teknik inceleme için hazırlanmış bir çalışma belgesidir.

## 2. Sistem Özeti

**BYS360 — Bütünleşik Yönetim Sistemi 360**, T.C. Kültür ve Turizm Bakanlığı Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı bünyesindeki kurumsal yönetim süreçleri için geliştirilmiştir.

Kurum içi yönetim süreçlerini tek merkezde toplayan, modüler bir kurumsal dijital yönetim platformudur. Kimlik, yetki, organizasyon, ayarlar, bildirim ve raporlama gibi ortak servisler merkezi bir omurga üzerinde çalışır.

Ana modüller:

| Modül | Kapsam (özet) |
|---|---|
| Personel Yönetimi | Personel ve organizasyon/birim ilişkileri, izin-devamsızlık, vekâlet; diğer modüller için temel veri |
| Performans Yönetimi | Dönem, kriter, amir zinciri, puanlama, görünürlük/yayın, geri bildirim ve raporlama |
| İletişim ve Anket Yönetimi | Mesajlaşma, duyuru, bildirim, anket ve geri bildirim |
| Destek / Yardım Merkezi | Talep kaydı, özel (private) talepler, yanıt, ekler ve durum yönetimi |
| Sistem Ayarları ve Yetkilendirme | Rol, kişi ve birim bazlı erişim; menü görünürlüğü; kritik ayarlar |
| KPI / Hedef | Hedef/KPI takibi ve gerçekleşme |
| AI Karar Destek | Kurumsal veriden özet/analiz ve karar destek çıktıları |
| BYS360 Sanal Asistan | Güvenlik/kapsam sınıflandırması, niyet yönlendirme ve yetkilendirme sonrası servis çağrısı |
| Dashboard / Raporlama | Yönetici görünümleri, durum kartları ve raporlar |
| Mobil istemci / API | Flutter istemci altyapısı ve `app/api/mobile` altındaki mobil API / PWA katmanı |

## 3. Teknik Mimari

Aşağıdaki bilgiler repodaki dosyalardan alınmıştır: `README.md`, `requirements.txt` ve `.github/workflows/`.

| Katman | Bileşen |
|---|---|
| Dil / çalışma zamanı | Python 3.12 (CI ortamı) |
| Web çatısı | Flask 3.1 (Blueprint yapısı), Flask-Login, Flask-WTF, Flask-Limiter |
| Veri erişimi | SQLAlchemy 2.0, Alembic (Flask-Migrate) |
| Veritabanı | PostgreSQL; local geliştirme için SQLite kullanılabilir |
| Sunum / işletim | Waitress; Windows servis veya görev zamanlayıcı yapısı |
| Yardımcı servis | Redis istemcisi (`requirements.txt`; `/health/deep` kontrolünde denetlenir) |
| Mobil | Flutter istemci altyapısı, mobil API ve PWA uç noktaları |
| Durum uç noktaları | `/healthz`, `/readyz`, `/versionz`, `/health/deep` |

**Ortak omurga:** kimlik, rol/yetki ve organizasyon yapısı tüm modüller tarafından paylaşılır. Personel/organizasyon verisi; performans, vekâlet, iletişim ve raporlama süreçlerinin ortak referansıdır.

**Migration disiplini:**
- Şema değişiklikleri Alembic migration'ları ile yönetilir. Tek bir migration head vardır: `w2d8e1f4a6c3`.
- CI'daki PostgreSQL 15 migration bütünlük kapısı her pull request'te şunları doğrular:
  - boş veritabanından head'e yükseltme;
  - ikinci yükseltmenin değişiklik yapmaması;
  - ORM–şema eşleşmesi (164 tablo, 2061 kolon);
  - runtime-schema grupları.

**Sanal Asistan:** yetki kontrolü her zaman servis çağrısından önce yapılır. Akış harici bir büyük dil modeli servisine bağımlı değildir (ayrıntı: `README.md`).

## 4. Güvenlik ve Yetkilendirme

Temel yaklaşım:

- **Menü görünürlüğü yetki sayılmaz.** Her backend route kendi yetki kontrolünü uygular (`SECURITY.md`).
- **Yetki kararının girdileri:** rol, birim, yönetici hiyerarşisi ve nesne kapsamı (object scope). Örneğin özel destek talebi birim kapsamı ve değerlendiricinin kendi görevi bu kontrollere girer.
- **Güvenlik hataları regresyon testleriyle kapatılır.** Her düzeltme önce hatayı yeniden üreten bir testle kanıtlanır (RED), ardından mevcut bir kural en dar değişiklikle uygulanır (GREEN).
- **Sözleşme testleri:**
  - Yetkilendirme matrisi sözleşmesi.
  - Anonim erişim sözleşmesi: her route'a anonim istek gönderilir ve yalnızca açık izin listesindekiler cevap verebilir.
- **Secret / repo kapısı:** `scripts/quality/bys360_secret_repo_gate.py` repoda gömülü secret değerlerini arar ve CI'da zorunludur.
- **Bağımlılık denetimi:** `pip-audit` CI'da çalışır.
- **Production işlemleri insan kontrollüdür.** Canlıya alma, veritabanı ve secret işlemleri açık insan onayı gerektirir (`AGENTS.md`, `AI_USAGE_POLICY.md`).

Güncel sertleştirme çalışması [BYS360_TECHNICAL_HARDENING_WAVE3_REVIEW.md](../../reports/quality/BYS360_TECHNICAL_HARDENING_WAVE3_REVIEW.md) belgesinde, bir önceki dalga ise [BYS360_TECHNICAL_HARDENING_WAVE2_REVIEW.md](../../reports/quality/BYS360_TECHNICAL_HARDENING_WAVE2_REVIEW.md) belgesinde kayıtlıdır.

Bu bölüm güvenliğin kusursuz olduğu ya da hiç açık bulunmadığı iddiasını taşımaz. Bilinen açık maddeler 8. ve 9. bölümlerde listelenmiştir.

## 5. Test ve CI Durumu

PR #18 (Wave 3), merge edilen head `3b7f568b28b8f13d9fe748bedaed442c672c70c9` üzerinde GitHub CI tarafından doğrulanmıştır.

| Kontrol | Sonuç |
|---|---|
| Step 1 (pytest) | 1104 passed, 14 skipped, 82 deselected, 0 failed |
| Step 2 (pytest) | 6473 passed, 8 skipped, 0 failed |
| PostgreSQL migration bütünlük kapısı | PostgreSQL 15.19 — PASS |
| Coverage | 46.3444% (etkin ratchet eşiği 27.12%) — PASS |
| quality-gate | PASS |
| score100-quality-gate | PASS |
| Ruff | PASS |
| mypy | PASS |
| Secret gate | PASS |
| pip-audit | PASS |
| Quality9 | PASS |
| Operations audit | PASS |

Test kapsamı %100 değildir. Coverage ratchet düşüşü engeller; yüksek riskli yetki ve iş akışları ayrıca davranışsal regresyon testleriyle korunur.

## 6. Kaynak Kod ve Canlı Sürüm Kimliği

Geliştirme dalı ile canlı sürüm ayrı kimliklerdir.

| Alan | Değer |
|---|---|
| Varsayılan (default) dal | `assistant-v2-full` |
| Varsayılan dal HEAD | `c03f9edc1dc20e58bca7c52f72aa5d1ee651264e` |
| Doğrulanmış canlı kaynak SHA | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` |
| Production tag | `bys360-prod-2026.09.29-a5bd8a38` |
| Canlı migration head | `w2d8e1f4a6c3` |

- Varsayılan dalın canlı sürümden daha yeni olması beklenen bir durumdur.
- Bir repository merge işlemi canlıya alma (deployment) değildir.
- Wave 3 değişiklikleri varsayılan dala alınmıştır, ancak canlıya alınmamıştır. Canlı kimlik hâlâ `a5bd8a38`'dir.
- Canlı kimlik ancak tam SHA'lı bir adayın insan kontrollü cutover süreciyle değişir (bkz. [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md)).

## 7. Teknik Sertleştirme — Wave 3

Doğrulanarak kapatılan alanlar:

**HIGH**
- Mobil KPI hedef ilerleme yetkilendirmesi
- Mobil performans puanı yazma yetkilendirmesi
- Mobil özel (private) destek talebi detay/yanıt yetkilendirmesi
- Feedback aftercare: yetki kontrolünden önce yazma hatası
- Mobil personel oluşturmada admin / admin-alias rolüyle yetki yükseltme

**MEDIUM**
- Mobil anket yanıtında atama (assignment) şartının uygulanması
- Özel talep listesinde gövde özetinin (snippet) açığa çıkması

**LOW-MED**
- HR işlemlerinde sayısal olmayan `user_id` ile oluşan 500 davranışı

Wave 3 kapanışında kanıtlanmış CRITICAL veya HIGH seviyesinde düzeltilmemiş bir hata bırakılmamıştır. Bu, sistemde hiç güvenlik sorunu bulunmadığı anlamına gelmez.

## 8. Bilinen Teknik Borç

### VERIFIED_TECHNICAL_DEBT

**MEDIUM**
- Mobil mesajlaşma yazma işlemleri sunucu hatası (500) döndürüyor.
- Faz 5 digest, geçersiz/var olmayan alan kullanımı nedeniyle 500 döndürüyor; beklenen davranışın anlamsal (semantic) olarak gözden geçirilmesi gerekiyor.

**LOW**
- Sıraya bağlı (order-dependent) test hatası.
- Mobil anketlerde yanıltıcı "yanıt bekleyen" sayacı.

## 9. İnsan Kararı Gerektiren Konular

Aşağıdaki başlıklar iş kuralı veya politika sorusudur. Sessizce teknik düzeltmeye dönüştürülmemelidir.

- Web ve mobil tarafta "global rol" tanımının tek bir politikaya bağlanması.
- Aynı birimdeki kullanıcıların başka personelin kişisel hedeflerini düzenleyebilmesinin istenen davranış olup olmadığı.
- Özel (private) destek talebi başlıklarının listelerde görünürlüğü.
- Mobil ve web destek kapsamı arasındaki farklar: mobil global roller ile web `support_all` yetkisi.
- HR kullanıcılarının mobil personel oluştururken hangi yönetici olmayan rolleri atayabileceği.

Önceki dalgalardan açık kalan politika soruları [Wave 2](../../reports/quality/BYS360_TECHNICAL_HARDENING_WAVE2_REVIEW.md) ve [Wave 3](../../reports/quality/BYS360_TECHNICAL_HARDENING_WAVE3_REVIEW.md) incelemelerinde kayıtlıdır.

## 10. Release ve Operasyon Disiplini

- **Exact-SHA canlı kimliği:** canlıya alınan paket, üretildiği tam commit SHA'sı ile izlenir. Belirleyici olan "hangi dal" değil, "hangi tam SHA" sorusudur.
- **Canonical safe-release builder:** paket yalnızca `scripts/release/build_bys360_safe_release.py` ile ve yalnızca Git'in takip ettiği dosyalardan üretilir.
- **Deterministik manifest / SHA256:**
  - Paket, kaynak commit SHA'sını, dosya manifestosunu ve her dosya için SHA256 özetini içerir.
  - `--verify` modu eksik, yasaklı veya fazla dosyada ve checksum uyuşmazlığında başarısız olur.
- **Release secret taraması:** `scripts/release/scan_bys360_release_secrets.py` paketi builder'dan bağımsız olarak yeniden tarar.
- **Shadow/disposable DB migration provası:** aday, canlı servise dokunmadan ayrı bir dizinde hazırlanır. Migration provası yalnızca bu amaçla oluşturulan atılabilir bir veritabanında yapılır (bkz. [CANDIDATE_PREPARATION.md](../handover/CANDIDATE_PREPARATION.md), [DATABASE_MIGRATION.md](../handover/DATABASE_MIGRATION.md)).
- **Health/readiness kontrolleri:** cutover, sağlık kontrolleri geçtikten sonra yapılır.
- **Kontrollü cutover:** cutover öncesinde kod ve veritabanı yedeği alınır.
- **Rollback tasarımı:** geri dönüş betiği varsayılan olarak DRY-RUN çalışır; gerçek uygulama açık `-Apply` gerektirir (bkz. [BACKUP_RUNBOOK.md](../../BACKUP_RUNBOOK.md)).
- **İnsan onayı:** production işlemleri (canlıya alma, migration, tag/release) açık insan onayıyla yapılır.

## 11. Lisans ve Hak Sahipliği

| Alan | Değer |
|---|---|
| Ürün | BYS360 — Bütünleşik Yönetim Sistemi 360 |
| Hak sahibi | T.C. Kültür ve Turizm Bakanlığı / Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı |
| Lisans | Proprietary / Institutional — BYS360 Kurumsal Yazılım Lisansı, Sürüm 1.0 ([LICENSE](../../LICENSE)) |
| Geliştirici | Havva Gülsen Özden |
| Eş Geliştirici (Co-developer) | Mustafa Bektaş |

Bağlayıcı hukuki metin [LICENSE](../../LICENSE) ve [NOTICE](../../NOTICE) dosyalarındadır. Üçüncü taraf ve açık kaynak bileşenler kendi lisanslarına tabidir.

## 12. Teknik İnceleme Kaynakları

- [README.md](../../README.md) — projeye giriş, teknik özet ve inceleme rehberi
- [LICENSE](../../LICENSE) — BYS360 Kurumsal Yazılım Lisansı
- [NOTICE](../../NOTICE) — telif ve geliştirici bildirimi
- [SECURITY.md](../../SECURITY.md) — güvenlik, secret ve paketleme kuralları
- [DEPLOYMENT.md](../../DEPLOYMENT.md) — yayına alma ve servis çalıştırma
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — geliştirme kuralları
- [BACKUP_RUNBOOK.md](../../BACKUP_RUNBOOK.md) — yedekleme ve geri dönüş
- [AI_USAGE_POLICY.md](../../AI_USAGE_POLICY.md) — yapay zekâ kullanım sınırları ve insan denetimi
- [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md) — güncel canlı kimlik ve dal rolleri
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — mimari kararlar ve modül yapısı
- [BYS360_TECHNICAL_HARDENING_WAVE3_REVIEW.md](../../reports/quality/BYS360_TECHNICAL_HARDENING_WAVE3_REVIEW.md) — Wave 3 teknik sertleştirme kaydı
- [BYS360_TECHNICAL_HARDENING_WAVE2_REVIEW.md](../../reports/quality/BYS360_TECHNICAL_HARDENING_WAVE2_REVIEW.md) — Wave 2 teknik sertleştirme kaydı
- [BYS360_SCHEMA_RECOVERY_LIMITATION.md](../quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md) — şema kurtarma sınırları
- [CANDIDATE_PREPARATION.md](../handover/CANDIDATE_PREPARATION.md) ve [DATABASE_MIGRATION.md](../handover/DATABASE_MIGRATION.md) — aday hazırlığı ve migration
- [BYS360_Teknik_Inceleme_Paketi_2026-09-30.pdf](BYS360_Teknik_Inceleme_Paketi_2026-09-30.pdf) — biçimlendirilmiş sunum kopyası

## 13. Sonuç

BYS360; mimarisi, güvenlik modeli, kaynak kod kalitesi, CI/test disiplini, release süreci, sürdürülebilirliği ve bilinen teknik borçları ile teknik incelemeye sunulmaya hazırdır.

Bilinen teknik borçlar (bölüm 8) ve insan kararı gerektiren konular (bölüm 9) incelemede ayrıca ele alınmalıdır.
