# BYS360 ARCHITECTURE

## Current Architecture Overview

- Flask/Python tabanlı web uygulaması, modüler servis katmanlarını (`app/services/`)
  yaygın olarak kullanır. Route/servis ayrımı mimari yönelimdir ve birçok alanda
  uygulanır. Bazı alan route'ları ile eski/uyumluluk adaptörleri; doğrulama,
  yetkilendirme/politika kontrolleri, sorgular, işlem (transaction) sınırları,
  yanıt oluşturma, orkestrasyon veya uyumluluk delegasyonu sorumluluklarını hâlâ
  taşır. Bu sınırlar kademeli konsolidasyon kapsamında ele alınır.
- Kalıcılık: PostgreSQL (production), Alembic tabanlı migration'lar (`migrations/`); local
  geliştirme için SQLite desteklenir.
- Rol/yetki uygulaması: menü görünürlüğü tek başına yetki değildir, her backend route ayrıca
  kendi yetki kontrolünü uygular; rol tabanlı görünürlük merkezi, kapalı bir rol sözlüğü
  üzerinden yönetilir.
- BYS360 Sanal Asistan (Assistant V2): deterministik akış -- güvenlik/kapsam sınıflandırması
  -> niyet yönlendirme -> yetenek kaydı -> yetkilendirme dispatcher'ı -> yanıt sunum katmanı;
  harici bir büyük dil modeli servisine bağımlılığı yoktur.
- Mobil API katmanı (`app/api/mobile/`) ve Flutter istemci altyapısı.
- CI/güvenlik/release doğrulaması: zorunlu kalite işleri, secret tarama, deterministik
  release builder ve bağımsız doğrulama modu.
- Exact-SHA release kimliği: canlıya alınan her paket, üretildiği tam Git commit SHA'sı ile
  iz sürülür (bkz. README.md "Mevcut Doğrulanmış Canlı Kaynak" bölümü).

Aşağıdaki kayıtlar, iz sürülebilirlik için saklanan tarihsel mimari/teknik borç kararlarıdır;
güncel proje fazının bir beyanı değildir.

<!-- PHASE2C6_ARCHITECTURE_20260613 -->

## Mimari Karar Kaydı - 2026-06-13 - Faz 2C Wildcard Import Temizliği

### Bağlam

Faz 2C boyunca wildcard import borcu kontrollü ve test kapılı şekilde azaltılmıştır. Mobil API alanında `app.api.mobile.shared` kaynaklı wildcard importlar domain dosyalarında açık importa dönüştürülmüş, `app/api/mobile/routes.py` ise facade/aggregator rolü nedeniyle bilinçli istisna olarak bırakılmıştır.

### Alınan Kararlar

- `app/api/mobile/routes.py` içindeki `from app.api.mobile.shared import *` satırı bilinçli facade istisnasıdır.
- Bu dosya doğrudan açık importa çevrildiğinde mobil route map ve auth guard testleri kırıldığı için mevcut hali korunmuştur.
- Faz 2C5 ile düşük riskli 4 ek wildcard import kalıcı olarak temizlenmiştir.
- `app/institutional/hr_scope_helpers.py` otomatik açık import için güvenli değildir; manuel refactor gerektirir.
- Kalan wildcard importlar artık “toplu otomatik temizlik” yerine “dosya bazlı refactor” olarak ele alınacaktır.

### Yeni Geliştirme Disiplini

Bundan sonra:

- Yeni kalite scripti üretmek yerine mevcut kalite modülleri güncellenecek.
- Yeni README/manifest üretmek yerine ARCHITECTURE.md ve STATUS.md güncellenecek.
- V_SAFE_NN, HOTFIX_V..., OVERLAY... adlandırma kültürü bırakılacak.
- Değişiklikler normal git commit / PR analizi mantığıyla takip edilecek.
- Deploy ve migration yardımcıları korunacak; eski kalite/onarım scriptleri Faz 2Y kapsamında arşive alınacaktır.

### Faz 2Y İçin Bekleyen Temizlik

- scripts/quality envanteri çıkarılacak.
- Aktif kullanılan kalite/deploy/migration yardımcıları ayrılacak.
- Kullanılmayan scriptler scripts/archive/quality/ altına taşınacak.
- Dağınık rapor ve dokümanlar `docs/archive/` ve `reports/archive/` altında toplanacak.
- Güncel mimari bilgi ARCHITECTURE.md, güncel durum bilgisi STATUS.md içinde tutulacak.


<!-- PHASE2Y_ARCHITECTURE_DECISION_20260613 -->

## Mimari Karar Kaydı - 2026-06-13 - Faz 2Y Repo Sadeleştirme

### Bağlam

Faz 2 boyunca proje içinde çok sayıda tek kullanımlık kalite/onarım scripti, SAFE/HOTFIX/OVERLAY dokümanı ve manifest oluşmuştur. Bu yapı teknik borcu azaltırken repo okunabilirliğini ve devredilebilirliği zorlaştırmaya başlamıştır.

### Karar

Repo artık iki ana doküman üzerinden yönetilecektir:

- STATUS.md: güncel faz durumu, kapanış kararları, test sonuçları
- ARCHITECTURE.md: mimari karar kayıtları, istisnalar, kalıcı geliştirme disiplini

Geçici README / manifest / tek kullanımlık onarım scriptleri archive altına alınacaktır.

### scripts/quality Politikası

scripts/quality/ altında sadece aktif veya korunması gereken gate/kanıt dosyaları kalacaktır.

Kalan ana sınıflar:

- Security gate
- Quality gate
- Architecture gate
- Mobile gate
- Release / ops gate
- Security hygiene evidence
- Manuel review gerektiren geçiş dosyaları

### Yasaklanan Eski Alışkanlık

Aşağıdaki yaklaşım terk edilmiştir:

- Her değişiklik için yeni repair scripti
- Her küçük düzeltme için yeni SAFE/HOTFIX/OVERLAY paketi
- Her işlem için yeni README veya manifest
- Sürüm numarası şişiren V_SAFE_NN kültürü

### Yeni Standart

Bundan sonra geliştirmeler normal Git akışıyla yapılacaktır:

1. Küçük ve açıklanabilir değişiklik
2. Mevcut modül üzerinde düzenleme
3. Mevcut testin güncellenmesi veya ilgili yeni testin doğrudan test dizinine eklenmesi
4. STATUS.md / ARCHITECTURE.md güncellemesi
5. Test kapıları
6. Commit / PR özeti

