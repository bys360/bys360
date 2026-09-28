<#
.SYNOPSIS
  BYS360 canli release (uygulama kodu) rollback otomasyonu - TD-036.

.DESCRIPTION
  BACKUP_RUNBOOK.md bolum 3'te tarif edilen
      C:\bys360\backups\predeploy_<yyyyMMdd_HHmmss>\project\
  yedek dizinini kaynak alarak, canli "BYS360 Live Waitress 80" Scheduled
  Task'ini durdurup/baslatarak, canli kod kokunu (LiveProjectRoot) o yedege
  geri dondurur.

  KAPSAM SINIRI: Bu script SADECE UYGULAMA KODU (release) rollback'idir -
  yedek kod dizinini canli koke geri kopyalamak, servisi yeniden baslatmak
  ve /healthz ile dogrulamaktan ibarettir. VERITABANI rollback'i (Alembic
  downgrade, pg_restore) bu scriptin KAPSAMI DISINDADIR; otomatiklestirilmez.
  BACKUP_RUNBOOK.md bolum 4/6'daki manuel PostgreSQL restore prosedu ayri,
  bu scriptin disinda kalan bir operator adimidir - bu script onu ASLA
  cagirmaz.

  Varsayilan calisma modu DRY-RUN'dir: -Apply verilmedikce hicbir dosya
  kopyalanmaz, hicbir Scheduled Task cagrisi yapilmaz, hicbir HTTP istegi
  atilmaz. VERIFY asamasi -Apply olsun olmasin HER ZAMAN calisir ve tum on
  kosullar saglanmadan APPLY asamasina asla girilmez.

  Fazlar (sirayla): PREPARE -> VERIFY -> APPLY -> HEALTHCHECK -> FINALIZE.

  APPLY asamasi bir staging (hazirlik) dizini kullanir: once yedek, tum
  disarida-birakma kurallariyla filtrelenerek StagingRoot'a kopyalanir ve
  orada tekrar isaretci-dosya dogrulamasi yapilir; ancak bu dogrulama
  basarili olduktan SONRA canli koke (LiveProjectRoot) tek bir filtrelenmis
  kopyalama gecisi uygulanir. Boylece bozuk/eksik bir yedek canli koke HIC
  dokunmadan once yakalanir. Canli koke uygulanan son kopyalama adimi,
  BACKUP_RUNBOOK.md bolum 6'daki
      robocopy "...\predeploy_...\project" "C:\bys360\project" /E
  manuel restore komutuyla AYNI semantige sahiptir: sadece ekleme/uzerine-
  yazma yapar, canlida FAZLADAN bulunan (yedekte olmayan) dosyalari SILMEZ
  (robocopy /MIR veya /PURGE KULLANILMAZ - ne bu scriptte ne de dokumanda).

.PARAMETER BackupRoot
  BACKUP_RUNBOOK.md bolum 3'teki "predeploy_<timestamp>" klasorunun yolu.
  Bu klasorun icinde bir "project" alt klasoru bulunmasi beklenir
  (BackupRoot\project\...).

.PARAMETER LiveProjectRoot
  Geri yuklemenin hedefi olan canli proje kok dizini. Varsayilan
  "C:\bys360\project" (BACKUP_RUNBOOK.md ile ayni konum). Bu dizin onceden
  var olmalidir.

.PARAMETER Apply
  Verilmezse script sadece bir PLAN basar (dry-run): dosya kopyalama YOK,
  Scheduled Task cagrisi YOK, HTTP istegi YOK. Verilirse gercek rollback
  uygulanir. VERIFY asamasi her iki durumda da calisir.

.PARAMETER TaskName
  Durdurulup baslatilacak Scheduled Task adi. Varsayilan
  "BYS360 Live Waitress 80" (canli launcher ile ayni gorev).

.PARAMETER HealthUrl
  Yeniden baslatma sonrasi kontrol edilecek saglik ucu. Varsayilan
  "http://127.0.0.1/healthz" (bkz. app/routes.py icindeki /healthz).

.PARAMETER HealthCheckRetryCount
  Saglik kontrolu icin en fazla deneme sayisi (varsayilan 10).

.PARAMETER HealthCheckDelaySeconds
  Denemeler arasi bekleme, saniye (varsayilan 3).

.PARAMETER StagingRoot
  Kullanilacak gecici hazirlik (staging) dizini. Verilmezse
  LiveProjectRoot'un kardesi olarak, zaman damgali bir ad ile otomatik
  uretilir ve APPLY basarili tamamlaninca silinir.

.NOTES
  - ".env" HICBIR ZAMAN kopyalanmaz, okunmaz veya yazdirilmaz; bu davranis
    sabit kodlanmistir ve devre disi birakilamaz - bilerek gevsetilecek bir
    parametre YOKTUR (kasitli tasarim karari).
  - instance/, logs/, "uploads" adli her dizin (app\static\uploads,
    data\uploads, uploads\ - bkz. .releaseignore ve config.py UPLOAD_FOLDER),
    reports/ canli calisma zamani verisidir; rollback bunlara ASLA
    dokunmaz/silmez/uzerine yazmaz.
  - PostgreSQL/Alembic islemleri bu scriptin disindadir; script bunlari
    calistirmaz.
  - Gercek Stop-ScheduledTask/Start-ScheduledTask ve gercek HTTP cagrisi
    (Invoke-WebRequest) SADECE -Apply verildiginde ve gercek ortamda
    calisir; testlerde bu isimler fonksiyon-golgeleme (function shadowing)
    ile mock'lanabilir (tests/quality/test_installer_launcher_overwrite_
    guard_v1.py icindeki mock deseniyle aynidir).
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupRoot,

    [string]$LiveProjectRoot = "C:\bys360\project",

    [switch]$Apply,

    [string]$TaskName = "BYS360 Live Waitress 80",

    [string]$HealthUrl = "http://127.0.0.1/healthz",

    [int]$HealthCheckRetryCount = 10,

    [int]$HealthCheckDelaySeconds = 3,

    [string]$StagingRoot
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Sabit disarida-birakma listeleri.
#
# BACKUP_RUNBOOK.md bolum 3, canli kod yedegini alirken su robocopy'yi
# kullanir:
#   robocopy "C:\bys360\project" "$BackupRoot\project" /E
#            /XD .git .venv __pycache__ logs instance reports dist_secure
#            /XF *.pyc *.log *.sqlite *.sqlite3 *.db
#
# Bu script, YEDEKTEN CANLIYA geri kopyalarken AYNI /XD dizin-adi felsefesini
# ve AYNI /XF uzanti kumesini kullanir (icat edilmis farkli bir liste
# DEGILDIR):
#   .git .venv __pycache__ logs instance reports dist_secure
#   + *.pyc *.log *.sqlite *.sqlite3 *.db
#
# Buna ek olarak (yedek OLUSTURMA adiminda olmayan, ama APPLY/restore
# adiminda ZORUNLU iki ek koruma):
#   - "uploads" adli HERHANGI bir dizin (app\static\uploads - bkz.
#     config.py UPLOAD_FOLDER varsayilani -, legacy data\uploads\ ve
#     uploads\ - bkz. .releaseignore) canli calisma zamani veri dizinidir;
#     yedekte eski/farkli icerik olsa bile canliya ASLA yazilmaz.
#   - ".env" dosyasi isim olarak ayrik ve sabit sekilde disarida birakilir
#     (BACKUP_RUNBOOK.md: ".env guvenli kanalda saklanir, release zipine
#     konulmaz"). Bu, parametre ile GEVSETILEMEZ.
# ---------------------------------------------------------------------------
$Script:ExcludedDirNames = @(
    '.git', '.venv', '__pycache__', 'logs', 'instance', 'reports', 'dist_secure', 'uploads'
)
$Script:ExcludedFileNamesExact = @('.env')
$Script:ExcludedFileSuffixes = @('.pyc', '.log', '.sqlite', '.sqlite3', '.db')
$Script:RequiredMarkerFiles = @('run_server.py', 'config.py')
$Script:RequiredMarkerDirs = @('app')

function Split-BysRelativePathSegments {
    param([string]$RelativePath)
    return @($RelativePath -split '[\\/]' | Where-Object { $_ -ne '' })
}

function Test-BysPathExcluded {
    <# Verilen (kaynak koku baz alinarak hesaplanmis) goreli yol,
       ExcludedDirNames / ExcludedFileNamesExact / ExcludedFileSuffixes
       kurallarindan herhangi birine uyuyorsa $true doner. #>
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    # NOT: @() ile SARMALAMA burada zorunludur. PowerShell, bir fonksiyondan
    # `return @(...)` ile donen TEK ELEMANLI bir diziyi cagiran tarafta
    # skaler (array-olmayan) bir degere "acabilir" (unroll). Bu sarmalama
    # olmadan, tek segmentli (kok seviyesi) bir dosya icin $segments bir
    # STRING'e donusur ve $segments[0] dizinin ilk elemani yerine STRING'in
    # ilk KARAKTERINI dondurur - bu da ToLowerInvariant() cagrisinin
    # System.Char uzerinde patlamasina yol acar.
    $segments = @(Split-BysRelativePathSegments -RelativePath $RelativePath)
    if ($segments.Count -eq 0) { return $false }

    $leaf = $segments[$segments.Count - 1]

    if ($segments.Count -gt 1) {
        $dirSegments = $segments[0..($segments.Count - 2)]
        foreach ($seg in $dirSegments) {
            if ($Script:ExcludedDirNames -contains $seg.ToLowerInvariant()) {
                return $true
            }
        }
    }

    foreach ($name in $Script:ExcludedFileNamesExact) {
        if ($leaf.ToLowerInvariant() -eq $name.ToLowerInvariant()) {
            return $true
        }
    }

    $ext = [System.IO.Path]::GetExtension($leaf)
    if ($ext -and ($Script:ExcludedFileSuffixes -contains $ext.ToLowerInvariant())) {
        return $true
    }

    return $false
}

function Test-BysMarkerFiles {
    <# Bir proje dizininde run_server.py / config.py / app\ isaretcilerinin
       varligini dogrular. Eksikse ACIK bir throw ile durur. #>
    param(
        [Parameter(Mandatory = $true)][string]$ProjectDir,
        [string]$Label = "proje"
    )
    $missing = @()
    foreach ($m in $Script:RequiredMarkerFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir $m) -PathType Leaf)) {
            $missing += $m
        }
    }
    foreach ($d in $Script:RequiredMarkerDirs) {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir $d) -PathType Container)) {
            $missing += "$d\ (dizin)"
        }
    }
    if ($missing.Count -gt 0) {
        throw "BYS360 ROLLBACK: '$Label' dizininde beklenen isaretci dosya/dizinler eksik: $($missing -join ', ') (yol: $ProjectDir)"
    }
}

function Copy-BysFilteredTree {
    <# Source altindaki tum dosyalari, Test-BysPathExcluded'a uyanlar HARIC,
       Destination altina (goreli yapi korunarak) kopyalar. Destination
       yoksa olusturulur. Donus: @{ Copied = int; Skipped = int } #>
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    # NOT: Resolve-Path (ProviderPath) 8.3 kisa yol parcalarini (ornegin
    # "KULLAN~1") OLDUGU GIBI birakabilirken, Get-ChildItem -Recurse'un
    # dondurdugu FullName degerleri UZUN adi kullanir. Bu ikisini karistirmak
    # (birini Resolve-Path, digerini Get-ChildItem'dan almak) asagidaki
    # Substring tabanli goreli-yol hesabini BOZAR (yanlis yerden kesilmis
    # cop bir "goreli yol" uretir). Bu yuzden burada TUTARLI sekilde
    # Get-Item.FullName kullanilir - Get-ChildItem ile AYNI normalize
    # formu doner.
    $sourceFull = (Get-Item -LiteralPath $Source).FullName.TrimEnd('\', '/')

    if (-not (Test-Path -LiteralPath $Destination)) {
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    }
    $destFull = (Get-Item -LiteralPath $Destination).FullName.TrimEnd('\', '/')

    $copied = 0
    $skipped = 0
    $files = @(Get-ChildItem -LiteralPath $sourceFull -Recurse -File -Force)
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($sourceFull.Length).TrimStart('\', '/')
        if (Test-BysPathExcluded -RelativePath $rel) {
            $skipped++
            continue
        }
        $destPath = Join-Path $destFull $rel
        $destDir = Split-Path -Path $destPath -Parent
        if ($destDir -and -not (Test-Path -LiteralPath $destDir)) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        Copy-Item -LiteralPath $f.FullName -Destination $destPath -Force
        $copied++
    }

    return [PSCustomObject]@{ Copied = $copied; Skipped = $skipped }
}

# =============================================================================
# PREPARE - parametreleri coz, yollari kur, plani yazdir. Yan etkisi/throw'u
# YOKTUR (sadece string/hesaplama); dogrulama VERIFY asamasindadir.
# =============================================================================
Write-Host "===== PREPARE =====" -ForegroundColor Cyan
Write-Host "BackupRoot              : $BackupRoot"
Write-Host "LiveProjectRoot         : $LiveProjectRoot"
Write-Host "Apply                   : $($Apply.IsPresent)"
Write-Host "TaskName                : $TaskName"
Write-Host "HealthUrl               : $HealthUrl"
Write-Host "HealthCheckRetryCount   : $HealthCheckRetryCount"
Write-Host "HealthCheckDelaySeconds : $HealthCheckDelaySeconds"

$BackupProject = Join-Path $BackupRoot "project"

if ([string]::IsNullOrWhiteSpace($StagingRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $liveParentForStaging = Split-Path -Path $LiveProjectRoot -Parent
    $liveLeafForStaging = Split-Path -Path $LiveProjectRoot -Leaf
    if ([string]::IsNullOrWhiteSpace($liveParentForStaging)) {
        $liveParentForStaging = "."
    }
    $StagingRoot = Join-Path $liveParentForStaging "$($liveLeafForStaging)__rollback_staging_$stamp"
}

Write-Host "StagingRoot (hesaplandi): $StagingRoot"
Write-Host "Disarida birakilan dizin adlari : $($Script:ExcludedDirNames -join ', ')"
Write-Host "Disarida birakilan dosya adlari : $($Script:ExcludedFileNamesExact -join ', ')"
Write-Host "Disarida birakilan uzantilar    : $($Script:ExcludedFileSuffixes -join ', ')"

# =============================================================================
# VERIFY - HER ZAMAN calisir (dry-run dahil). Tum on kosullar saglanmadan
# APPLY asamasina asla girilmez. Herhangi bir kontrol basarisiz olursa
# ACIK bir throw ile durulur; sifir dosya islemi denenmis olur.
# =============================================================================
Write-Host "===== VERIFY =====" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $BackupRoot -PathType Container)) {
    throw "BYS360 ROLLBACK: BackupRoot bulunamadi: $BackupRoot"
}

if (-not (Test-Path -LiteralPath $BackupProject -PathType Container)) {
    throw "BYS360 ROLLBACK: Yedek 'project' alt klasoru bulunamadi: $BackupProject"
}
$BackupProjectFull = (Get-Item -LiteralPath $BackupProject).FullName.TrimEnd('\', '/')

$backupTopItems = @(Get-ChildItem -LiteralPath $BackupProjectFull -Force)
if ($backupTopItems.Count -eq 0) {
    throw "BYS360 ROLLBACK: Yedek 'project' klasoru bos: $BackupProjectFull"
}

if (-not (Test-Path -LiteralPath $LiveProjectRoot -PathType Container)) {
    throw "BYS360 ROLLBACK: LiveProjectRoot bulunamadi: $LiveProjectRoot"
}
$LiveProjectRootFull = (Get-Item -LiteralPath $LiveProjectRoot).FullName.TrimEnd('\', '/')

if ($BackupProjectFull -eq $LiveProjectRootFull) {
    throw "BYS360 ROLLBACK: BackupRoot\project ile LiveProjectRoot AYNI konuma cozumleniyor ($BackupProjectFull). Kaynak ve hedef ayni olamaz; rollback reddedildi."
}

Test-BysMarkerFiles -ProjectDir $BackupProjectFull -Label "yedek (BackupRoot\project)"

Write-Host "VERIFY OK: yedek gecerli, kaynak/hedef farkli, isaretci dosyalar mevcut." -ForegroundColor Green

# =============================================================================
# APPLY - SADECE -Apply verildiginde calisir. Varsayilan (dry-run) hicbir
# dosya kopyalamaz, hicbir Scheduled Task cagrisi yapmaz.
# =============================================================================
Write-Host "===== APPLY =====" -ForegroundColor Cyan

$stageCopy = $null
$liveCopy = $null

if ($Apply) {
    if (Test-Path -LiteralPath $StagingRoot) {
        throw "BYS360 ROLLBACK: StagingRoot zaten var, guvenlik icin durduruldu (elle temizleyin): $StagingRoot"
    }
    New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null

    Write-Host "1/4: Yedek -> Staging kopyalaniyor (disarida birakilanlar haric)..."
    $stageCopy = Copy-BysFilteredTree -Source $BackupProjectFull -Destination $StagingRoot
    Write-Host "     Kopyalanan: $($stageCopy.Copied)  Atlanan: $($stageCopy.Skipped)"

    Test-BysMarkerFiles -ProjectDir $StagingRoot -Label "staging (kopya sonrasi dogrulama)"

    Write-Host "2/4: Scheduled Task durduruluyor: $TaskName"
    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    } catch {
        Write-Host "     (Stop-ScheduledTask beklenmeyen durum verdi, devam ediliyor: $($_.Exception.Message))" -ForegroundColor Yellow
    }

    Write-Host "3/4: Staging -> Canli kopyalaniyor (disarida birakilanlar haric)..."
    $liveCopy = Copy-BysFilteredTree -Source $StagingRoot -Destination $LiveProjectRootFull
    Write-Host "     Kopyalanan: $($liveCopy.Copied)  Atlanan: $($liveCopy.Skipped)"

    Write-Host "4/4: Scheduled Task baslatiliyor: $TaskName"
    Start-ScheduledTask -TaskName $TaskName

    Remove-Item -LiteralPath $StagingRoot -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "APPLY OK: rollback uygulandi." -ForegroundColor Green
} else {
    Write-Host "DRY RUN: -Apply verilmedi. Hicbir dosya kopyalanmadi, hicbir Scheduled Task cagrisi yapilmadi." -ForegroundColor Yellow
    Write-Host "Uygulanacak plan: '$BackupProjectFull' -> (staging: $StagingRoot) -> '$LiveProjectRootFull'"
    Write-Host "                  TaskName='$TaskName' durdur -> kopyala -> baslat."
}

# =============================================================================
# HEALTHCHECK - SADECE -Apply sonrasinda anlamlidir (yeniden baslatma
# yapilmadan saglik kontrolu yaniltici olur). Basarisizlik otomatik bir
# tekrar-rollback TETIKLEMEZ; sadece operatore net bir sinyal olarak
# raporlanir (FINALIZE sonunda throw ile).
# =============================================================================
Write-Host "===== HEALTHCHECK =====" -ForegroundColor Cyan

$healthOk = $false
$healthDetail = "calistirilmadi (dry run)"

if ($Apply) {
    $healthDetail = "hicbir deneme basarili olmadi"
    for ($attempt = 1; $attempt -le $HealthCheckRetryCount; $attempt++) {
        try {
            $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                $healthOk = $true
                $healthDetail = "HTTP $($resp.StatusCode) ($attempt. denemede basarili)"
                break
            }
            $healthDetail = "HTTP $($resp.StatusCode) ($attempt. deneme)"
        } catch {
            $healthDetail = "istek hatasi ($attempt. deneme): $($_.Exception.Message)"
        }
        if ($attempt -lt $HealthCheckRetryCount) {
            Start-Sleep -Seconds $HealthCheckDelaySeconds
        }
    }
    if ($healthOk) {
        Write-Host "HEALTHCHECK OK: $HealthUrl -> $healthDetail" -ForegroundColor Green
    } else {
        Write-Host "HEALTHCHECK FAILED: $HealthUrl -> $healthDetail" -ForegroundColor Red
    }
} else {
    Write-Host "DRY RUN: healthcheck calistirilmadi. Gercek calistirmada hedef: $HealthUrl"
}

# =============================================================================
# FINALIZE - net bir ozet yazdirir. -Apply verildiyse VE saglik kontrolu
# basarisizsa, ozet basildiktan SONRA throw ile sinyal verilir (ek dosya
# islemi / otomatik tekrar-rollback YOKTUR).
# =============================================================================
Write-Host "===== FINALIZE =====" -ForegroundColor Cyan
Write-Host "VERIFY          : OK (yedek gecerli, kaynak/hedef farkli, isaretci dosyalar mevcut)"
if ($Apply) {
    Write-Host "APPLY           : UYGULANDI"
    Write-Host "  Yedek->Staging  : kopyalanan=$($stageCopy.Copied) atlanan=$($stageCopy.Skipped)"
    Write-Host "  Staging->Canli  : kopyalanan=$($liveCopy.Copied) atlanan=$($liveCopy.Skipped)"
    Write-Host "  Scheduled Task  : $TaskName durduruldu/baslatildi"
    if ($healthOk) {
        Write-Host "  Saglik kontrolu : OK ($healthDetail)" -ForegroundColor Green
    } else {
        Write-Host "  Saglik kontrolu : BASARISIZ ($healthDetail)" -ForegroundColor Red
    }
} else {
    Write-Host "APPLY           : DRY RUN (uygulanmadi; gercek uygulamak icin -Apply ile calistirin)"
    Write-Host "  Saglik kontrolu : atlandi (dry run)"
}
Write-Host "BYS360_LIVE_RELEASE_ROLLBACK_DONE" -ForegroundColor Green

if ($Apply -and -not $healthOk) {
    throw "BYS360 ROLLBACK: Kod geri yuklemesi uygulandi ANCAK saglik kontrolu basarisiz oldu ($healthDetail). Otomatik tekrar geri alma YAPILMAZ; operator manuel mudahale etmelidir (bkz. DEPLOYMENT.md bolum 9, BACKUP_RUNBOOK.md bolum 6-7)."
}
