# BYS360 Agent Rules

## Amaç

Yeni özellik geliştirmeden önce teknik borçları küçük, ölçülebilir ve kanıtlanabilir paketlerle kapat.

Bir bulgu yalnız kod değiştirildiğinde değil, ilgili kalite kapıları geçtiğinde kapalı sayılır.

## Çalışma alanı

- Yalnız mevcut Git worktree içinde çalış.
- Korunan ana çalışma alanı: `C:\bys360\project`
- Ana çalışma alanına yazma; yalnız Python sanal ortamını çalıştırmak için şu dosya kullanılabilir:
  `C:\bys360\project\.venv\Scripts\python.exe`
- Her görev başlamadan önce mevcut dalı, izin verilen hedef dalı, HEAD'i ve `git status --short` sonucunu doğrula.
- Görev talimatında açıkça belirtilen dal dışında çalışma yapma.
- Beklenen dal veya HEAD doğrulanamıyorsa `OPEN` raporla ve değişiklik yapma.
- Yeni paket başlatmadan önce dalı, HEAD'i ve `git status --short` sonucunu kaydet.
- Yeni paket başlangıcında beklenmeyen değişiklik varsa dur ve `OPEN` raporla.

## Kesin yasaklar

Aşağıdaki alanlara veya işlemlere açık kullanıcı talimatı olmadan dokunma:

- canlı sunucu, Waitress, port 80 ve yük dengeleyici
- PostgreSQL, Redis ve gerçek kurum verileri
- `instance`, `backups`, release paketleri ve veritabanı dosyaları
- `.env`, secret, parola, token ve bağlantı bilgileri
- migration dosyaları ve veritabanı şeması
- zamanlanmış görevler ve Windows servisleri
- canlı dağıtım, push ve uzak depo işlemleri
- `git reset`, `git clean`, toplu geri alma ve geçmişi yeniden yazma
- toplu Ruff autofix veya geniş kapsamlı otomatik formatlama
- kullanıcının ilgisiz mevcut değişiklikleri

Gizli değerleri terminal çıktısına, rapora veya konuşmaya yazma.

## Teknik borç sınıfları

Her adayı değişiklikten önce sınıflandır:

- `SAFE`: Davranışın değişmediği kanıtlanmış küçük düzeltme.
- `CONTROLLED`: Davranış veya sözleşme etkisi olabilecek düzeltme; değişiklik yapmadan dur.
- `REVIEW`: Niyet veya uyumluluk belirsiz; yalnız analiz et.
- `BLOCKED`: Gerekli ortam, test veya karar bulunmuyor; değişiklik yapma.

Otomatik düzeltme yalnız `SAFE` adaylarda yapılabilir.

## SAFE örnekleri

Aşağıdakiler ancak tam inceleme ve hedefli test sonrasında SAFE olabilir:

- kullanılmayan yerel değişken
- `zip(strict=...)` eksikliği
- birebir aynı ve gerçekten gölgelenmiş fonksiyon tanımı
- davranış değiştirmeyen kullanılmayan import
- açıkça erişilemeyen ve kullanılmayan kod

Farklı gövdeli fonksiyonlar, farklı sözlük değerleri, exception zinciri, API sözleşmesi, yetkilendirme, güvenlik ve migration değişiklikleri SAFE kabul edilemez.

## Paket sınırı

- Bir paket yalnız bir lint kuralı, bir alt sistem ve mümkünse bir dosya içersin.
- İlk pilot pakette en fazla beş bulgu değiştir.
- İlgisiz refactor yapma.
- Paralel ajanlar aynı dosyayı değiştiremez.
- `STATUS.md` yalnız koordinatör tarafından değiştirilir.
- Her ajan yalnız kendisine açıkça atanan dosyalara yazabilir.

## Doğrulama

BYS360 Python çalıştırıcısı:

`C:\bys360\project\.venv\Scripts\python.exe`

Her değişiklikten sonra uygun olanları sırayla çalıştır:

1. hedefli Ruff kuralı
2. Python compile kontrolü
3. ilgili hedefli testler
4. test toplama kontrolü
5. gerekli olduğunda tam test paketi
6. coverage regression
7. dependency audit

Test toplama işlemi testlerin geçtiği anlamına gelmez.

Önceden kapatılmış daha yüksek riskli bir kural yeniden ortaya çıkarsa dur.

## Kapanış durumları

- `PASS`: Hedef sayı sağlandı ve gerekli doğrulamalar geçti.
- `FAIL`: Doğrulama çalıştı fakat kabul ölçütü sağlanmadı.
- `OPEN`: Kanıt eksik, sonuç karşılaştırılamıyor veya doğrulama tamamlanmadı.

Hedefli bir kapının geçmesi tüm projenin temiz olduğu anlamına gelmez.

Örnek:
`F601 PASS; genel kritik lint kapısı OPEN.`

## Git ve raporlama

- Başlangıç HEAD'ini ve önce/sonra sayılarını kaydet.
- Yalnız atanmış dosyaların değiştiğini doğrula.
- Kullanıcı veya koordinatör açıkça istemeden commit, tag, merge veya push yapma.
- Hata oluşursa kapsamı daraltarak hatayı gizleme.
- Sonuçta değişen dosyaları, testleri, kalan borcu ve bir sonraki tek önceliği bildir.

## Zorunlu durdurma koşulları

Şunlardan biri gerçekleşirse değişiklik yapmayı bırak:

- yanlış dal veya worktree
- beklenmeyen kirli başlangıç
- aynı dosyada başka ajan değişikliği
- aday gövdeleri veya davranışları farklı
- ilgisiz dosya değişikliği
- compile veya test hatası
- önceki kapalı kapının gerilemesi
- canlıya, veritabanına veya korunan dosyaya erişme gereksinimi
- raporlanan sayıların aynı komutla yeniden üretilememesi

Durdurulduğunda mevcut kanıtı koru ve sonucu `OPEN` veya `FAIL` olarak bildir.
