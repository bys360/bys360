# BYS360 Geliştirici Katkı Rehberi

## Temel kurallar

- Gerçek `.env`, parola, token, anahtar veya bağlantı dizesi repoya eklenmez.
- Geliştirme yedekleri `.bak`, `.orig`, `.old` olarak kaynak kod ağacında tutulmaz; git branch/stash kullanılır.
- Route dosyaları iş mantığı taşımaz; servis katmanı çağırır.
- Kullanıcı ekranında teknik faz, debug, endpoint, raw exception veya geliştirici notu gösterilmez.
- Her değişiklik tek amaçlı, geri alınabilir, açıklanabilir ve doğrulanabilir olmalıdır.

## Kalite kontrol

```powershell
python -m compileall -q app config.py wsgi.py run.py scripts
python scripts\quality\bys360_secret_repo_gate.py --root .
python -m ruff check app config.py wsgi.py run.py scripts --select E9,F63,F7,F82
python -m pytest tests/quality -m "ci_safe" --tb=short -q
```

## Devir teslim paketi

Temiz kaynak paketinde şunlar bulunmamalıdır:

- `.env`, `.env.*` gerçek dosyaları
- `.venv`, `venv`, `env`
- `backups`, `archive`, `payload`, `overlay_payload`
- `.bak`, `.backup`, `.orig`, `.tmp`
- veritabanı dump, log, upload veya runtime dosyaları

## Yeni geliştirici başlangıç akışı

Bu bölüm, projeyi ilk kez devralan geliştiricinin yerel ortamı güvenli ve tekrarlanabilir şekilde ayağa kaldırması için kullanılır.

### 1. Projeyi hazırlama

Desteklenen Python sürümü: **3.12** (bkz. `.github/workflows/bys360-ci.yml` ve `bys360-score100-quality-gate-v1.yml` içindeki `actions/setup-python@v5` adımları, `pyproject.toml` `[tool.mypy] python_version` ve `[tool.ruff] target-version = "py312"`).

```powershell
cd C:\bys360\project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt`, CI'nin kullandığı kalite araçlarının (ruff, mypy, pytest, pytest-cov, pip-audit) tam olarak aynı, pinlenmiş sürümlerini kurar; production çalışma zamanı bağımlılıklarından (`requirements.txt`) kasıtlı olarak ayrı tutulur, böylece local kalite koşumları CI ile aynı araç sürümlerini kullanır.

### 2. Ortam dosyasını oluşturma

Gerçek `.env` dosyası repoya veya release zipine konulmaz. Yerelde örnek dosyadan kopyalanır ve değerler kurum ortamına göre doldurulur.

```powershell
Copy-Item .env.example .env -ErrorAction SilentlyContinue
```

Dikkat: Gerçek `DATABASE_URL`, parola, token veya gizli anahtar yalnızca yerel `.env` içinde kalır.

### 3. Docker ile hızlı başlatma

Docker kullanılacaksa önce örnek ortam değerleri hazırlanır, sonra servisler ayağa kaldırılır.

```powershell
docker-compose up -d --build
```

Yerel Python ile çalışılacaksa proje içindeki mevcut Flask/Waitress başlatma komutları ve `DEPLOYMENT.md` izlenir.

### 4. Demo veri yükleme

Demo veri veya sahte kullanıcı ihtiyacı varsa seed dosyası kontrollü çalıştırılır.

```powershell
python seeds\fake_seed.py
```

Seed işlemi canlı veritabanında çalıştırılmaz. Önce ortamın geliştirme/test olduğundan emin olun.

### 5. İlk kalite kontrol koşumu

Yeni geliştirici kod yazmadan önce mevcut durumun yeşil olduğunu görmelidir. Aşağıdaki komutlar CI'da (`.github/workflows/bys360-ci.yml`) gerçekten çalışan adımların birebir veya (açıkça belirtilen yerlerde) sadeleştirilmiş karşılıklarıdır. Adımların tam ve güncel listesi için tek doğru kaynak her zaman o dosyadır -- CI değiştikçe burası drift edebilir.

```powershell
# Hızlı gündelik sağlık kontrolü: derleme + syntax/import sanity + secret gate + hızlı test alt kümesi
python -m compileall -q app config.py wsgi.py run.py scripts
python scripts\quality\bys360_secret_repo_gate.py --root .
python -m ruff check app config.py wsgi.py run.py scripts --select E9,F63,F7,F82
python -m pytest tests/quality -m "ci_safe" --tb=short -q
```

```powershell
# CI'daki asil ruff gate'i ("Ruff full-select gate" adimi; pyproject.toml [tool.ruff.lint]
# select = E,F,I,UP,B,SIM kapsamini uygular -- yukaridaki --select E9,F63,F7,F82 komutundan
# daha genis kapsamlidir)
python -m ruff check app config.py wsgi.py run.py scripts tests

# CI'daki asil mypy komutu ("Type check service layer" adimi)
python -m mypy app tests scripts --ignore-missing-imports --no-error-summary

# Coverage ile calistirma (CI'daki "Run quality tests" adiminin sadelestirilmis yerel karsiligi;
# CI ayrica --cov-report=xml uretir ve sonucu scripts\quality\bys360_coverage_ratchet.py ile
# bir coverage baseline'ina karsi denetler)
python -m pytest tests/quality -m "ci_safe" --cov=app --cov-report=term-missing --tb=short -q

# Entegrasyon/mimari testleri (sadelestirilmis alt kume; CI'daki "Run integration and
# architecture tests" adimi onlarca ek dosya/dizin ile cok daha genis kapsamlidir -- birebir
# guncel komut icin bys360-ci.yml'e bakin)
python -m pytest tests/integration tests/architecture tests/security tests/critical --tb=short -q
```

### 6. Modül haritası

- `app/admin/`: yönetim, ayar, operasyon ve karar destek yönetim ekranları.
- `app/api/mobile/`: mobil API katmanı ve mobil domain servisleri.
- `app/institutional/`: personel, organizasyon ve kurumsal süreç yardımcıları.
- `app/services/`: iş kurallarının ve servis mantığının ana yeri.
- `tests/quality/`: CI-safe kalite testleri.
- `tests/integration/`: gerçek akışa yakın entegrasyon testleri.
- `tests/architecture/`: mimari sözleşme ve dosya/bağımlılık testleri.
- `scripts/security/`: güvenlik ve release hijyeni araçları.
- `scripts/release/`: güvenli kaynak paket üretim araçları.

### 7. Yeni iş geliştirme kuralı

Yeni özellik için önce mevcut servis, test ve script altyapısı aranır. Zorunlu olmadıkça yeni script açılmaz; mevcut script parametreyle genişletilir veya servis fonksiyonu eklenir. Script sayısını artıran her değişiklik PR açıklamasında gerekçelendirilmelidir.

### 8. Temiz release üretimi

Teslim edilecek zip elle sıkıştırılmaz. Tek yetkili (canonical) release builder
`scripts\release\build_bys360_safe_release.py`'dir; üretim ve doğrulama birlikte çalıştırılır.

```powershell
python scripts\release\build_bys360_safe_release.py --root . --output "C:\bys360\dist\bys360_release.zip"
python scripts\release\build_bys360_safe_release.py --verify "C:\bys360\dist\bys360_release.zip"
```

`--verify` PASS vermeden zip paylaşılmaz.
(`scripts\windows\build_bys360_secure_release_and_preflight_v1.ps1` DEPRECATED'dır.)

