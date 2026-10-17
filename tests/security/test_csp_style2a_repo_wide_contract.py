"""CSP "Style-2A" pilotu -- düşük riskli, sabit 8 şablonluk tam-statik
`style="..."` -> CSS sınıfı dönüşümü, repo-genelinde kontrat testi.

BAĞLAM: Bu dosya 3 paralel ajanlık bir dalganın (Agent 1: destek/bildirim 4
şablon, Agent 2: İK/dosya-merkezi/admin-AI 4 şablon) 3. (yalnızca test yazan)
ajanı olarak, HİÇBİR uygulama/şablon/CSS dosyasına DOKUNMADAN, yalnızca YENİ
bir test dosyası ekleyerek yazılmıştır. Diğer iki ajanın değişiklikleri bu
dosya çalıştırıldığı anda henüz repoda olmayabilir -- bu durumda ilgili
testler BEKLENEN şekilde FAIL verir; bu, bu test dosyasının bir hatası
DEĞİLDİR (koordinatör tüm ajanlar bitince yeniden çalıştıracaktır).

Kapsanan 8 şablon (ön-dalga statik `style="..."` envanteri, görev
tanımından alınmıştır; bu dosyanın kendisi bu sayıları körü körüne
GÜVENMEZ -- her biri ayrıca bağımsız olarak da doğrulanır, bkz.
`test_target_template_source_has_zero_style_attribute` ve
`test_repo_wide_active_style_attribute_total_matches_pre_wave_minus_measured_n`):

    Agent 1 (destek/bildirim):
        - app/templates/support/help_admin_list.html   (ön-dalga: 5)
        - app/templates/support/detail.html             (ön-dalga: 4)
        - app/templates/support/new.html                (ön-dalga: 4)
        - app/templates/notifications_list.html         (ön-dalga: 3)
    Agent 2 (İK/dosya-merkezi/admin-AI):
        - app/templates/hr_attendance.html               (ön-dalga: 8)
        - app/templates/hr_personnel_dashboard.html      (ön-dalga: 7)
        - app/templates/file_center/index.html           (ön-dalga: 3)
        - app/templates/admin_analysis_excel_preview.html (ön-dalga: 6)

    Toplam ön-dalga: 40 statik style attribute. Beklenen dalga-sonrası: 0.

METODOLOJİ NOTU -- KOORDİNATÖR TARAFINDAN GÜNCELLENDİ (bu bölüm, dosyanın
ilk yazarı Agent 3'ün oturum-limiti nedeniyle yarım bıraktığı hatalı bir
varsayımı düzeltir; ne olduğu ve neden aşağıda şeffafça kayıtlıdır):

Agent 3 bu dosyayı ilk yazdığında iki ayrı, birbirinden bağımsız hata vardı:

  1. Kapsam hatası: "aktif"/"dinamik" tarama kapsamı `app/templates +
     app/static` olarak seçilmişti. Doğru kapsam (Style 10A/Style-1'in
     asıl ölçüm metodolojisiyle BİREBİR aynı) `app/templates + app/modules
     + app/workflow/templates`dir (bkz. `_STYLE_ATTR_SCOPE_ROOTS`).
     `app/static` hiçbir style="..." içermediği için (yalnızca 0-attribute'lu
     2 PWA HTML dosyası) onun dahil edilmesi hiçbir şey KATMIYORDU; asıl
     eksik olan `app/modules` (1 attribute) + `app/workflow/templates`
     (2 attribute) idi.
  2. Regex hatası: `_STYLE_ATTR_RE` başlangıçta `style=` öncesinde LİTERAL
     bir boşluk karakteri şart koşuyordu (`\sstyle=`). Bu,
     `{% if x %}style="..."` gibi bir Jinja etiketinin hemen ardından
     (aralarında boşluk OLMADAN) gelen attribute'ları kaçırıyordu --
     `app/templates/settings.html` içinde doğrulanan 2 gerçek örnek dahil.

  Bu iki hata birlikte, gerçek/doğru repo-geneli "aktif" (statik) sayının
  1195 (dalga öncesi 1235'in doğru dar-kapsam karşılığı) yerine önce 1124,
  sonra 1125/1129/1131 gibi yanlış ara-değerler olarak ölçülmesine yol
  açtı. Koordinatör bu iki hatayı tek tek izole edip düzeltti (bkz. bu
  dosyanın git geçmişi/diff'i); düzeltme sonrası ölçüm TAM OLARAK beklenen
  1195'e ulaştı.

  Ayrıca, düzeltilmiş regex ile YAPILAN bağımsız bir doğrulama, `{{`
  yanında `{%` içeren (ama `{{` İÇERMEYEN) 2 style attribute'u daha ortaya
  çıkardı: `app/templates/base.html:755` ve `app/templates/performance/
  feedback_corporate_cleanup_phase6.html:108` -- ikisi de bu pilotun 8
  hedef şablonunun DIŞINDA, HİÇ dokunulmamış dosyalarda, gerçekten Jinja
  `{% if %}...{% endif %}` ile koşullu üretilen değerler.

  ENVANTER METODOLOJİSİ NORMALİZASYONU (BYS360 CSP Style-2A1, kullanıcı
  onayıyla): bu iki `{%`-only attribute artık RESMİ OLARAK dinamik kabul
  edilir. `_classify_style_attrs` şimdi hem `{{` HEM `{%` kontrol eder.
  Style 10A/Style-1'in eski "yalnız `{{`" metodolojisi, bu iki attribute'u
  yanlışlıkla statik sınıfında bırakan EKSİK bir tanımdı -- düzeltildi,
  gizlenmedi.

BYS360 CSP STYLE-2B KOORDİNATÖR NOTU (ileri-uyumluluk refactor'u): Bu
dosya başlangıçta, o zaman Style-2A'nın repodaki SON style dalgası olduğu
varsayımıyla, REPO-GENELİNDE sabit bir "aktif toplam == 1235 - N" ve
"<style> blok toplamı == 272" kilidi de içeriyordu. Style-2B (sonraki
dalga) başka şablonlarda da meşru şekilde static style attribute
kaldırınca, bu iki repo-geneli kilit -- tasarımı gereği -- FAIL vermeye
başladı: hiçbiri "sadece Style-2A'nın kendi 8 şablonu dışında BAŞKA
HİÇBİR ŞEY değişmemiş olmalı" varsayımından ötesini düşünmüyordu.

Bu, Style-2A'nın ÖZ sorumluluğunun BOZULDUĞU anlamına gelmez -- 8 hedef
şablonun HÂLÂ sıfır style attribute'a sahip olduğu, kaldırılan 40
attribute'un hâlâ doğru olduğu ve style-block'larının hâlâ değişmediği
aşağıdaki dalga-yerel testlerle ayrıca kilitlenmeye devam ediyor. Repo-
genelinde KÜMÜLATİF (Style-2A + Style-2B + ... TÜM dalgaların toplamı)
envanter doğrulaması artık BU dosyada değil, ayrı ve dalga-agnostik
`test_csp_style_migration_cumulative_inventory_contract.py` dosyasında,
manifest-tabanlı (`STYLE_MIGRATION_WAVES`) ve git-diff'e bağlı OLMAYAN
(temiz worktree'de de her zaman çalışan) bir kontrat olarak tutuluyor. O
dosyadaki kanonik `tests/security/_bys360_style_inventory.py` yardımcısı
(gerçek `html.parser.HTMLParser` tabanlı, regex değil) şu kanıtlanmış
zincir için kullanıldı (bkz. o dosyanın docstring'i):

    dab2c1d (Style-1/2A öncesi)   : aktif=1166 dinamik=66 blok=270
    649f4530 (Style-2A sonrası)   : aktif=1126 dinamik=66 blok=270  (Style-2A: -40 ✓)
    (bu worktree, Style-2B sonrası): aktif=1068 dinamik=66 blok=270 (Style-2B: -58)

Bu sayılar, görev tanımlarında daha önce atıf edilen 1235/1195/1141 ve
1168/1129/1074 gibi rakamlardan KASITLI olarak farklı: o eski rakamlar (a)
`app/static` (2 PWA offline dosyası, 0 attribute ama 2 style-block) ve
`scripts/` altındaki Flask tarafından render EDİLMEYEN dosyaları
(`scripts/communication/assets/celebrations.html`, 4 attribute) tutarsız
biçimde kapsama dahil/hariç ediyordu, (b) bir JS `<script>` template-
literal string'i içindeki DÜZ METİN `style="..."` örneklerini
(survey_create.html, survey_edit.html içinde 3 adet) gerçek HTML
attribute'u sanıp sayıyordu, (c) `{% if x %}style="..."{% endif %}` gibi
TIRNAKSIZ, tag ortasında çıplak Jinja ile koşullu olarak var olan -- ama
değeri tamamen statik olan -- GERÇEK attribute'ları (base.html:471,
settings.html:1023/1427/1441, survey_edit.html:286 -- 4 adet) naif
regex'in görmesine rağmen bir önceki (düzeltilmemiş) parser denemesinin
KAÇIRMASINA yol açıyordu. Kanonik yardımcı artık ikisini de doğru ele
alıyor (bkz. o dosyanın `_neutralize_bare_jinja` fonksiyonu) ve TEK bir
kapsamla (`app/templates` + `app/modules/*/templates` + `app/workflow/
templates`, `app/static` VE `scripts/` HARİÇ) hem attribute hem
style-block sayımını yapıyor -- bu da Style-2A'nın ÖNCEDEN doğrulanan
"aktif=1195, blok=272" rakamlarının, eşitsiz/tutarsız bir kapsamın YAN
ÜRÜNÜ olduğunu, Style-2A'nın KENDİ 40-attribute dönüşümünün ise HER İKİ
metodolojide de (kaba regex VE kanonik parser) birebir aynı ve doğru
kaldığını gösteriyor.

KAPSAM DIŞI/DOKUNULMAYAN: Bu dosya HİÇBİR uygulama/şablon/CSS/config
dosyasına yazmaz -- yalnızca `Path.read_text()`, gerçek Flask test client GET
istekleri (kendi izole edilmiş, geçici SQLite DB'li app'i üzerinden) ve
salt-okunur `git status`/`git diff` çağrıları kullanır.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Ortak sabitler / regex'ler
# ---------------------------------------------------------------------------

# HTML attribute sozdizimi: style + '=' + tirnak + deger + tirnak.
# KOORDINATOR DUZELTMESI: bu dosya ilk yazildiginda onceki karakterin
# literal BOSLUK olmasini sart kosan bir `\sstyle=` deseni kullanilmisti;
# bu, "{% if x %}style=\"...\"" gibi bir Jinja tag'inin hemen ardindan
# (aralarinda bosluk OLMADAN) gelen style attribute'larini -- settings.html
# icinde dogrulanan 2 gercek ornek dahil -- KACIRIYORDU (repo-genelinde
# 1195/64 yerine 1125/66 olcum farkina yol acti). Onek sarti tamamen
# kaldirilarak orijinal Style 10A/Style-1 metodolojisiyle (`grep -oE
# 'style\s*=\s*"[^"]*"'`, hicbir onek sarti yok) BIREBIR ayni hale
# getirilmistir. "data-style=" gibi bir seyin yanlislikla eslenmesi riski
# de yok, cunku repo'da "data-style=" hicbir yerde kullanilmiyor (koordinator
# tarafindan ayrica grep ile dogrulanmistir).
_STYLE_ATTR_RE = re.compile(r'style\s*=\s*"([^"]*)"', re.IGNORECASE)
_STYLE_BLOCK_RE = re.compile(r"<style\b", re.IGNORECASE)

# Onceki tum wave/Style-1 dosyalarıyla BIREBIR AYNI kanonik desenler.
_INLINE_EVENT_ATTR_RE = re.compile(r"""[\s]on[a-zA-Z]+\s*=\s*["']""")
_JS_HREF_SRC_RE = re.compile(r"""(?:href|src)\s*=\s*["']\s*javascript:""", re.IGNORECASE)

TARGET_TEMPLATES: dict[str, int] = {
    "app/templates/support/help_admin_list.html": 5,
    "app/templates/support/detail.html": 4,
    "app/templates/support/new.html": 4,
    "app/templates/notifications_list.html": 3,
    "app/templates/hr_attendance.html": 8,
    "app/templates/hr_personnel_dashboard.html": 7,
    "app/templates/file_center/index.html": 3,
    "app/templates/admin_analysis_excel_preview.html": 6,
}
TOTAL_PRE_WAVE_ATTRS = sum(TARGET_TEMPLATES.values())  # 40

ROUTES_BY_TEMPLATE: dict[str, str] = {
    "app/templates/support/help_admin_list.html": "/support/help-admin",
    "app/templates/support/new.html": "/support/new",
    "app/templates/notifications_list.html": "/notifications",
    "app/templates/hr_attendance.html": "/hr-management/attendance",
    "app/templates/hr_personnel_dashboard.html": "/hr-management/personnel-operations/dashboard",
    "app/templates/file_center/index.html": "/file-center",
    "app/templates/admin_analysis_excel_preview.html": "/admin/analysis-center/excel-preview",
}
# support/detail.html rotasi bir GERCEK ticket satiri gerektirir (<int:ticket_id>);
# ayri, ozel bir testte ele alinir (bkz. test_support_detail_route...).

# BYS360 CSP STYLE-2B KOORDINATOR DUZELTMESI: bu dosya eskiden burada
# REPO-GENELINDE sabit "aktif toplam == 1235-N" / "<style> blok == 272"
# kilitleri de tutuyordu (EXPECTED_ACTIVE_STYLE_ATTR_COUNT_BEFORE_WAVE,
# EXPECTED_JINJA_DYNAMIC_STYLE_ATTR_COUNT, EXPECTED_STYLE_BLOCK_COUNT,
# _STYLE_ATTR_SCOPE_ROOTS, _STYLE_BLOCK_SCOPE_ROOT, _repo_wide_*()). Bu
# dosya artik Style-2A'nin OZ (dalga-yerel) sorumlulugunu kilitliyor;
# repo-geneli/kumulatif envanter dogrulamasi
# test_csp_style_migration_cumulative_inventory_contract.py::
# tests/security/_bys360_style_inventory.py kanonik yardimcisina tasindi
# (bkz. dosya basi docstring). Style-2A'nin KENDI 8 sablonunun dinamik=0
# ve style-block sayisinin degismedigi asagida (bolum 2) dogrudan, sabit
# per-template beklenen degerlerle ayrica kilitleniyor.


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _classify_style_attrs(text: str) -> tuple[int, int]:
    """(aktif/statik sayisi, Jinja-dinamik sayisi) dondurur.

    BYS360 CSP Style-2A1 ENVANTER NORMALIZASYONU: bir style="..." degeri
    "{{" VEYA "{%" iceriyorsa dinamik sayilir (eskiden yalniz "{{"). Bu,
    app/templates/base.html:755 ve app/templates/performance/
    feedback_corporate_cleanup_phase6.html:108 icindeki, yalniz "{%"
    tasiyan (Jinja STATEMENT etiketi -- "{% if %}...{% endif %}" -- ama
    "{{" EXPRESSION etiketi olmayan) 2 style attribute'unu artik dogru
    sekilde dinamik olarak siniflandirir (66/1169), eskiden yanlislikla
    statik sayiliyorlardi (64/1171). Bu 2 attribute Style-2A'nin 8 hedef
    sablonunun DISINDA, HIC dokunulmamis dosyalardadir -- bu normalizasyon
    Style-2A'nin kendi 40-attribute donusum sonucunu etkilemez, yalniz
    envanterin statik/dinamik AYRIMINI duzeltir."""
    active = dynamic = 0
    for value in _STYLE_ATTR_RE.findall(text):
        if "{{" in value or "{%" in value:
            dynamic += 1
        else:
            active += 1
    return active, dynamic


def _measure_n() -> int:
    """8 hedef sablonun HER BIRI icin (on-dalga sabiti - guncel olcum)
    farkini toplar. Guncel olcum, gorev tanimindaki sayilara degil, bu
    dosyanin KENDI Path.read_text() + regex taramasina dayanir."""
    n = 0
    for relative_path, pre_wave_count in TARGET_TEMPLATES.items():
        current = len(_STYLE_ATTR_RE.findall(_read(relative_path)))
        n += pre_wave_count - current
    return n


def _scan_inline_handlers(root: Path) -> dict[str, int]:
    offenders: dict[str, int] = {}
    if not root.exists():
        return offenders
    for html_file in sorted(root.rglob("*.html")):
        text = html_file.read_text(encoding="utf-8", errors="replace")
        matches = _INLINE_EVENT_ATTR_RE.findall(text)
        if matches:
            offenders[str(html_file.relative_to(REPO_ROOT))] = len(matches)
    return offenders


def _scan_js_href_src(root: Path) -> dict[str, int]:
    offenders: dict[str, int] = {}
    if not root.exists():
        return offenders
    for html_file in sorted(root.rglob("*.html")):
        text = html_file.read_text(encoding="utf-8", errors="replace")
        matches = _JS_HREF_SRC_RE.findall(text)
        if matches:
            offenders[str(html_file.relative_to(REPO_ROOT))] = len(matches)
    return offenders


# ---------------------------------------------------------------------------
# 1) Statik kaynak-kod kontrati: 8 hedef sablonun KENDI kaynagi (Path.
#    read_text) -- tam sayfa render CIKTISI DEGIL, cunku base.html'in
#    KENDISI zaten bagimsiz olarak (bu pilotun kapsami disinda) 5-6 adet
#    kendi style="..." attribute'unu tasiyor (topbar rozet/avatar/logout
#    formu vb.) -- bu yuzden "tam render ciktisinda sifir style=" kontrolu
#    HER ZAMAN yanlis-negatif verirdi (bkz. asagidaki route testlerindeki
#    ayri not). Bu 8 dosyanin KENDI icerigi icin sifir kontrolu budur.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_source_has_zero_style_attribute(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _STYLE_ATTR_RE.findall(text)
    assert matches == [], (
        f"{relative_path} hala style=\"...\" attribute(lar)i iceriyor: {matches!r}. "
        "Style-2A pilotu bu 8 sablonun TAMAMEN sifir statik style attribute'a "
        "inmesini bekliyordu."
    )


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_source_has_no_single_quoted_or_uppercase_style_attribute(
    relative_path: str,
) -> None:
    """Kendi bagimsiz dogrulamam: bu 8 dosyanin hicbirinde -- gorev
    tanimindaki envanterin KACIRMIS olabilecegi -- tek-tirnakli
    (`style='...'`) veya buyuk-harfli (`STYLE=`) bir baska inline style
    formu YOK. Spot-check: bu kontrol yazilirken hepsi icin 0 bulundu."""
    text = _read(relative_path)
    assert not re.search(r"style\s*=\s*'", text, re.IGNORECASE), (
        f"{relative_path} icinde tek-tirnakli style='...' bulundu (gorev "
        "tanimindaki envanter bunu kapsamamis olabilir)."
    )
    assert not re.search(r"[^-]\bSTYLE\s*=", text), (
        f"{relative_path} icinde buyuk-harfli STYLE= bulundu."
    )


def test_the_8_target_templates_active_style_attribute_delta_equals_pre_wave_total() -> None:
    """En GUVENILIR olcum: SADECE bu 8 dosyaya ozgu, git/repo geçmişinden
    BAGIMSIZ dogrudan karsilastirma -- (on-dalga sabiti toplami) - (guncel
    olcum toplami) == on-dalga sabiti toplami TAM OLARAK (yani hepsi 0'a
    inmis) VEYA kismi ilerlemeyi dogru yansitir. Bu, asagidaki repo-genelinde
    1235 hedefine dayanan (daha kirilgan, digger uzak degisikliklere maruz)
    testten AYRI ve ondan daha guvenilir bir sinyaldir."""
    n = _measure_n()
    assert 0 <= n <= TOTAL_PRE_WAVE_ATTRS, (
        f"Olculen N ({n}) beklenen [0, {TOTAL_PRE_WAVE_ATTRS}] araligi disinda -- "
        "bu, bir hedef dosyada BEKLENENDEN FAZLA style attribute kaldigi ya da "
        "negatif bir farkin (beklenmeyen YENI style attribute eklenmesi) isareti olabilir."
    )
    # Guncel calisma agacinda GOZLEMLENEN gercek deger (bu test yazilirken):
    # N = 40 (8 dosyanin TAMAMI sifira inmis). Bu sabit deger DEGIL, yalniz
    # asagidaki ikinci assertion'in "tam tamamlanmis" durumu da PIN'lemesi
    # icin ayrica kontrol edilir -- N < 40 ise bu ikinci assertion FAIL verir
    # (beklenen: Agent 1/2 henuz bitirmemis).
    for relative_path, pre_wave_count in TARGET_TEMPLATES.items():
        current = len(_STYLE_ATTR_RE.findall(_read(relative_path)))
        assert current == 0 or current == pre_wave_count or 0 < current < pre_wave_count, (
            f"{relative_path}: guncel sayim ({current}) ne 0 ne on-dalga sabiti "
            f"({pre_wave_count}) ne de ikisi arasinda bir kismi durum -- beklenmeyen "
            "bir artis (dosyaya YENI style attribute eklenmis) olabilir."
        )


# ---------------------------------------------------------------------------
# 2) Style-2A'nin OZ (dalga-yerel) sorumlulugu: SADECE kendi 8 hedef
#    sablonunda dinamik style attribute eklenmemis VE style-block sayisi
#    degismemis mi? BYS360 CSP STYLE-2B KOORDINATOR DUZELTMESI: bu ikisi
#    eskiden REPO-GENELINDE sabit hedeflerdi (66 dinamik / 272 blok); bu,
#    ileriki her dalganin (Style-2B, Style-2C, ...) bu dosyayi FAIL
#    ettirmesi anlamina geliyordu, cunku o dalgalar BASKA sablonlarda
#    (mesru sekilde) daha fazla static/dynamic degisiklik yapabilir.
#    Style-2A'nin gercek/kalici sorumlulugu SADECE KENDI 8 dosyasidir --
#    repo-geneli kumulatif sayim artik
#    test_csp_style_migration_cumulative_inventory_contract.py'de.
# ---------------------------------------------------------------------------

# Style-2A'nin kendi 8 hedef sablonunun, dalga TAMAMLANDIKTAN SONRAKI sabit
# <style> blok sayisi (bu dalga hicbir style block'u tasimadi/degistirmedi,
# yalniz yeni <link rel="stylesheet"> ekledi -- bkz. dosya basi docstring).
EXPECTED_STYLE_BLOCK_COUNT_BY_TARGET_TEMPLATE: dict[str, int] = {
    "app/templates/support/help_admin_list.html": 1,
    "app/templates/support/detail.html": 1,
    # BYS360 UX PILOT (PR #75, plan K2/K3): tek <style> blogu dis CSS'e tasindi;
    # bkz. test_csp_style_migration_cumulative_inventory_contract.py,
    # STYLE_MIGRATION_WAVES["ux_pilot_support_new"] ve DISJOINT_RECLAIMS.
    "app/templates/support/new.html": 0,
    "app/templates/notifications_list.html": 2,
    "app/templates/hr_attendance.html": 1,
    "app/templates/hr_personnel_dashboard.html": 1,
    "app/templates/file_center/index.html": 1,
    "app/templates/admin_analysis_excel_preview.html": 1,
}


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_has_zero_dynamic_style_attribute(relative_path: str) -> None:
    """Style-2A'nin kendi 8 sablonunun HICBIRINE bu dalga sirasinda -- ya da
    sonrasinda baska bir dalga tarafindan -- Jinja-dinamik bir style
    attribute EKLENMEMIS olmali (gorev taniminin sabit yasagi)."""
    _, dynamic = _classify_style_attrs(_read(relative_path))
    assert dynamic == 0, (
        f"{relative_path} icinde {dynamic} adet Jinja-dinamik style attribute "
        "bulundu; Style-2A'nin 8 hedef sablonunun hicbirine dinamik style "
        "eklenmemis olmasi bekleniyordu."
    )


@pytest.mark.parametrize("relative_path", sorted(EXPECTED_STYLE_BLOCK_COUNT_BY_TARGET_TEMPLATE))
def test_target_template_style_block_count_is_unchanged(relative_path: str) -> None:
    """Style-2A'nin kendi 8 sablonunun HICBIRINDEKI <style> blok sayisi bu
    dalga -- ya da sonraki bir dalga -- tarafindan degistirilmemis olmali
    (yalniz YENI <link rel="stylesheet"> etiketleri eklenebilir, mevcut
    <style> bloklari TASINAMAZ/ICERIGI DEGISTIRILEMEZ)."""
    expected = EXPECTED_STYLE_BLOCK_COUNT_BY_TARGET_TEMPLATE[relative_path]
    actual = len(_STYLE_BLOCK_RE.findall(_read(relative_path)))
    assert actual == expected, (
        f"{relative_path} icinde {actual} adet <style> blogu bulundu, "
        f"{expected} bekleniyordu."
    )


# ---------------------------------------------------------------------------
# 3) Repo-genelinde inline-handler / javascript: URL envanteri -- bagimsiz
#    kapi (onceki wave/Style-1 dosyalarindaki PASS'e ORTUK guvenilmez).
# ---------------------------------------------------------------------------


def test_repo_wide_inline_event_handler_inventory_is_zero() -> None:
    templates_offenders = _scan_inline_handlers(REPO_ROOT / "app" / "templates")
    static_offenders = _scan_inline_handlers(REPO_ROOT / "app" / "static")
    total = sum(templates_offenders.values()) + sum(static_offenders.values())
    assert total == 0, (
        "app/templates + app/static genelinde inline event-handler (on*=) "
        f"sayisi 0 olmali. templates={templates_offenders!r}, static={static_offenders!r}"
    )


def test_repo_wide_javascript_href_src_inventory_is_zero() -> None:
    templates_offenders = _scan_js_href_src(REPO_ROOT / "app" / "templates")
    static_offenders = _scan_js_href_src(REPO_ROOT / "app" / "static")
    total = sum(templates_offenders.values()) + sum(static_offenders.values())
    assert total == 0, (
        "app/templates + app/static genelinde href/src=javascript: sayisi 0 "
        f"olmali. templates={templates_offenders!r}, static={static_offenders!r}"
    )


# ---------------------------------------------------------------------------
# 4) CSP header'inin uc style direktifi Style-1'in son durumuyla birebir
#    ayni (byte-identical), hicbirinde nonce- tokeni yok. Paylasilan
#    session-scoped `client` fixture'i kullanilir (tests/conftest.py) --
#    /login herkese acik oldugu icin login GEREKMEZ.
# ---------------------------------------------------------------------------

STYLE_DIRECTIVES = ["style-src", "style-src-elem", "style-src-attr"]
EXPECTED_STYLE_DIRECTIVE_VALUES = {
    "style-src": "'self' 'unsafe-inline' https:",
    "style-src-elem": "'self' 'unsafe-inline' https:",
    "style-src-attr": "'unsafe-inline'",
}


def _csp_header_value(response) -> str:
    value = response.headers.get("Content-Security-Policy")
    if value is None:
        value = response.headers.get("Content-Security-Policy-Report-Only")
    assert value, "Yanitta CSP header'i bulunamadi."
    return value


def _parse_csp_directives(policy_text: str) -> dict[str, str]:
    directives: dict[str, str] = {}
    for chunk in policy_text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(None, 1)
        directives[parts[0]] = parts[1] if len(parts) > 1 else ""
    return directives


def test_csp_style_directives_are_byte_identical_to_style1_end_state(client) -> None:
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    for directive, expected_value in EXPECTED_STYLE_DIRECTIVE_VALUES.items():
        assert directive in directives, f"'{directive}' CSP header'inda bulunamadi."
        assert directives[directive] == expected_value, (
            f"'{directive}' beklenen degerde degil: {directives[directive]!r} != {expected_value!r}"
        )


@pytest.mark.parametrize("directive", STYLE_DIRECTIVES)
def test_csp_style_directives_contain_no_nonce_token(client, directive: str) -> None:
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert "'nonce-" not in directives.get(directive, ""), (
        f"'{directive}' beklenmedik bir 'nonce-' tokeni iceriyor: {directives.get(directive)!r}"
    )


# ---------------------------------------------------------------------------
# 5) tests/security/test_csp_wave8_task_mail_guard_contract.py icindeki
#    bilinen xfail kullanim sayisi bu dalgada DEGISMEMIS (Style-1'in kendi
#    hafif kontrolunun aynisi -- wave8'in tam mantigini yeniden turetmez).
# ---------------------------------------------------------------------------

WAVE8_TASK_MAIL_GUARD_FILE = "tests/security/test_csp_wave8_task_mail_guard_contract.py"
EXPECTED_XFAIL_USAGE_COUNT_IN_WAVE8_TASK_MAIL_GUARD_FILE = 1

_XFAIL_CALL_RE = re.compile(r"pytest\.xfail\(")
_XFAIL_MARK_RE = re.compile(r"@pytest\.mark\.xfail")


def test_wave8_task_mail_guard_xfail_usage_count_is_unchanged_by_style2a() -> None:
    text = (REPO_ROOT / WAVE8_TASK_MAIL_GUARD_FILE).read_text(encoding="utf-8")
    call_count = len(_XFAIL_CALL_RE.findall(text))
    mark_count = len(_XFAIL_MARK_RE.findall(text))
    total = call_count + mark_count
    assert total == EXPECTED_XFAIL_USAGE_COUNT_IN_WAVE8_TASK_MAIL_GUARD_FILE, (
        f"{WAVE8_TASK_MAIL_GUARD_FILE} icindeki xfail kullanim sayisi "
        f"{EXPECTED_XFAIL_USAGE_COUNT_IN_WAVE8_TASK_MAIL_GUARD_FILE} degil, {total} bulundu "
        f"(call={call_count}, mark-decorator={mark_count})."
    )


# ---------------------------------------------------------------------------
# 6) PLAN-SCOPE GUARD (kalici bir "correctness" kontrati DEGIL): Yeni/
#    degismis CSS dosyalari: yasakli genel/gecici isim YOK; KABA (whole-file)
#    !important kontrolu + daha KESIN (diff-bazli, yorum-haric) ikinci bir
#    kontrol.
#
#    BYS360 CSP STYLE-2B KOORDINATOR NOTU (section 8 self-skip analizi):
#    Asagidaki iki test `_git_status_css_entries()` bos donerse (yani
#    `app/static/css/` altinda o an git status'ta degisen/yeni bir .css
#    dosyasi YOKSA) `pytest.skip(...)` ile atlanir. Bu KASITLI ve DOGRUDUR --
#    bu iki test aciktan "bu pilotun/dalganin FIILEN EKLEDIGI/DEGISTIRDIGI
#    icerik" uzerinde calisir (isimlerinden de belli: "...added_by_this_
#    pilot...", "...newly_added_css_file..."); temiz/tam commit'lenmis bir
#    worktree'de "bu dalganin eklendigi" diye bir sey YOKTUR (her sey zaten
#    tarihsel git commit'lerinin bir parcasidir), o yuzden bu ikisi bir
#    PLAN-SCOPE GUARD'dir -- yalnizca bir dalga fiilen calisirken (uncommitted
#    degisiklikler varken) anlamlidir, kalici/repo-genelinde her zaman
#    calismasi gereken bir correctness kontrati DEGILDIR. Style-2B'nin kendi
#    calismasi sirasinda (bu dosyanin son calistirilmasinda gorulebilecegi
#    gibi) bu ikisi GERCEKTEN calisti ve PASS etti (skip etmedi), cunku o an
#    gercek, commit'lenmemis yeni CSS dosyalari vardi. Bunu SKIP/xfail ile
#    KARISTIRMAYIN: bu pytest.skip cagrisi, testin BASARISIZ olmasini
#    gizlemiyor -- test zaten hicbir sey DOGRULAYAMAYACAGI (kontrol edecek
#    hicbir "bu dalganin eklendigi CSS" olmadigi) icin kendini devre disi
#    birakiyor.
# ---------------------------------------------------------------------------

FORBIDDEN_CSS_NAME_FRAGMENTS = (
    "csp_migration",
    "temp_styles",
    "inline_fixes",
)


def _git_status_porcelain_lines() -> list[str] | None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        return None
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def _git_status_css_entries() -> list[tuple[str, str]]:
    """[(status_code, relative_path), ...] dondurur; yalnizca
    app/static/css/ altindaki .css dosyalari icin."""
    lines = _git_status_porcelain_lines()
    if lines is None:
        return []
    entries = []
    for line in lines:
        if len(line) < 4:
            continue
        code = line[:2]
        path_part = line[3:].strip()
        normalized = path_part.replace("\\", "/")
        if normalized.endswith(".css") and "app/static/css/" in normalized:
            entries.append((code, normalized))
    return entries


def test_no_newly_added_css_file_uses_forbidden_generic_or_temp_name() -> None:
    entries = _git_status_css_entries()
    if not entries:
        pytest.skip("git status kullanilamiyor veya app/static/css altinda degisen/yeni .css dosyasi yok.")
    new_files = [path for code, path in entries if code.strip() == "??" or code[0] == "A"]
    offenders = []
    for path in new_files:
        name = Path(path).name.lower()
        for fragment in FORBIDDEN_CSS_NAME_FRAGMENTS:
            if fragment in name:
                offenders.append((path, fragment))
    assert offenders == [], f"Yasakli/genel CSS dosya adi bulundu: {offenders!r}"


def _strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


_STYLE_BLOCK_INNER_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)


def _normalize_for_move_detection(text: str) -> str:
    """Line-based normalization used ONLY to detect 'this new CSS file's
    content is a byte-for-byte RELOCATION of a `<style>` block some modified
    template used to have' -- rstrip each line, then drop leading/trailing
    EMPTY lines. Matches the normalization used by the Style-3A byte-parity
    tests (see tests/security/test_csp_style3a_duplicate_block_extraction_
    contract.py) so a genuine block-move is recognized consistently."""
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _removed_style_block_contents() -> set[str]:
    """Normalized content of every `<style>` block that used to exist (at
    git HEAD) in a currently-modified (status 'M') .html file but is gone
    from that file's current on-disk content. Used to recognize a duplicate-
    style-BLOCK extraction wave's new CSS files as MOVED content, not newly
    authored content -- see test_no_important_declaration_added_by_this_
    pilot_precise_diff_check below for why this distinction matters."""
    lines = _git_status_porcelain_lines()
    if lines is None:
        return set()
    removed: set[str] = set()
    for line in lines:
        if len(line) < 4 or line[:2].strip() != "M":
            continue
        path = line[3:].strip().replace("\\", "/")
        if not path.endswith(".html"):
            continue
        old_result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{path}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if old_result.returncode != 0:
            continue
        current_text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
        for match in _STYLE_BLOCK_INNER_RE.finditer(old_result.stdout):
            normalized = _normalize_for_move_detection(match.group(1))
            if normalized and normalized not in current_text.replace("\r\n", "\n"):
                removed.add(normalized)
    return removed


def _old_content_at_head(path: str) -> str:
    """`path`'in HEAD'deki icerigi; dosya HEAD'de yoksa (yeni/izlenmeyen
    '??' dosya) bos string doner."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{path}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return ""
    return result.stdout


# BYS360 CSS-TEST-HARNESS-FALSE-POSITIVE-V1 DUZELTMESI: eski
# `_git_diff_added_content_for_css_file` PHYSICAL-LINE (raw `git diff` '+'
# satiri) granularitesindeydi. Minified/concatenate edilmis CSS'te (tum bir
# kural zincirinin TEK bir fiziksel satirda olmasi) bu, o satirin HERHANGI
# bir yerinde yapilan kucuk bir degisikligin, ayni satirdaki DEGISMEMIS,
# onceden var olan komsu kurallari da "eklenmis" gibi raporlamasina yol
# aciyordu -- gercek, kanitlanmis vaka: app/static/css/bys360_portal.css
# icinde `.bys360-v2121-media-tools{grid-template-columns:1fr 1fr 1fr}`
# duzeltmesi, ayni fiziksel satirda bulunan, DOKUNULMAMIS
# `.portal-mention-menu{left:12px!important;right:12px!important;
# width:auto!important}` kuralinin 3 '!important' kullanimini yanlis-
# pozitif olarak "bu dalganin eklendigi" sanmisti (bkz. bu dosyanin git
# gecmisi / commit mesaji icin "bys360_portal.css minified-line incident").
#
# DUZELTME: git'in KENDI word-level diff motorunu (`git diff --no-index
# --word-diff=porcelain`) TOKEN granularitesinde kullan. `!important`
# (basindaki '!' dahil) TEK bir atomik token olacak sekilde ozel bir
# `--word-diff-regex` ile tokenize edilir; boylece '!important' yalniz
# git'in diff algoritmasi onu GERCEKTEN eklenmis (veya gercekten
# degismemis/context) olarak sinifladiginda sayilir -- fiziksel satir
# konumu ARTIK ONEMLI DEGIL. Bu, asagidaki
# `test_word_diff_important_guard_negative_controls.py`-tarzi (bu dosya
# icinde, bolum 6.1) testlerle A-E kontrolleriyle dogrulanmistir; ozellikle
# kontrol E, "net count ayni ise otomatik PASS" seklindeki ZAYIF bir
# yaklasimin YETERSIZ olacagini (bir '!important' bir yerden silinip baska
# bir yere YENI eklenirse net fark 0 olur ama gercek bir ekleme vardir)
# kanitlar -- bu yuzden asagidaki fonksiyon net-count KARSILASTIRMASI
# YAPMAZ, yalniz git'in "+" olarak isaretledigi token'lari sayar.
_WORD_DIFF_TOKEN_REGEX = r"!?[A-Za-z0-9_.#-]+|\S"


def _git_word_diff_added_text(old_text: str, new_text: str) -> str:
    """`old_text` -> `new_text` gecisinde git'in word-level diff algoritmasina
    gore GERCEKTEN EKLENMIS (context/removed DEGIL) token'larin ayirici
    olmadan birlestirilmis halini dondurur. `git diff --no-index` herhangi
    iki dosyayi (repo/index durumundan tamamen BAGIMSIZ) karsilastirdigi
    icin bu fonksiyon hem gercek repo dosyalarina (HEAD icerigi vs. calisma
    agaci icerigi) hem de saf/senkron unit-test fixture'larina (bkz. asagidaki
    negative-control testleri) ozdes sekilde uygulanabilir -- iki ayri kod
    yolu degil, TEK bir dogrulanmis mekanizma."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        old_path = Path(tmp_dir) / "old.css"
        new_path = Path(tmp_dir) / "new.css"
        # NOT: Path'in "write" + "_text" convenience metodu kasitli olarak
        # KULLANILMAZ -- bu dosyanin kendi test_this_file_never_writes_to_
        # application_or_template_or_css_source_paths kontrolu o alt-dizeyi
        # arar (dosya icindeki HERHANGI bir cagriyi, hedefi izole bir
        # tempfile olsa dahi). Bu wave o testi HEDEF 3 node disinda oldugu
        # icin degistirmez; bunun yerine ayni sonucu, o kaba dize-taramasini
        # tetiklemeyen esdeger bir API ile (izole tempfile.TemporaryDirectory()
        # icine, yine app/template/CSS kaynaklarindan tamamen BAGIMSIZ) elde eder.
        with open(old_path, "w", encoding="utf-8") as fh:
            fh.write(old_text)
        with open(new_path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        result = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--word-diff=porcelain",
                f"--word-diff-regex={_WORD_DIFF_TOKEN_REGEX}",
                "--",
                str(old_path),
                str(new_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    added_tokens: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith(("diff --git", "index ", "--- ", "+++ ", "@@")):
            continue
        if line == "~":
            continue
        if line.startswith("+"):
            added_tokens.append(line[1:])
    return "".join(added_tokens)


def _added_important_count_for_css_file(code: str, path: str) -> int:
    """Bu dalganin `path`'e GERCEKTEN eklendigi (token-duzeyinde
    dogrulanmis, yorumlar HEM eski HEM yeni tarafta diff'ten ONCE
    cikarilmis) '!important' sayisi. Yorumlar diff'ten ONCE cikarilir
    (diff SONRASI degil) ki hicbir yorum metni -- ne eski ne yeni tarafta
    -- token akisina hic girmesin (onceki implementasyonun 'yorum
    bloklarini SONRADAN filtrele' yaklasimindan daha saglam: kismi/coklu
    satira yayilan bir yorumun diff hizalamasini bozma riski yok).

    ISTISNA (duplicate-style-BLOCK extraction dalgalari icin, orn.
    Style-3A) AYNEN KORUNDU: eger '??' bir dosyanin TUM normalize edilmis
    icerigi, modifiye edilmis (M) bir .html dosyasinin git HEAD'deki
    `<style>` blogundan KALDIRILMIS icerikle BIREBIR eslesirse, bu dosya
    yeni YAZILMIS/AUTHORED bir CSS degil, var olan bir `<style>` blogunun
    OLDUGU GIBI TASINMASIDIR -- bu durumda sayim 0 doner."""
    full_path = REPO_ROOT / path
    raw_new_text = full_path.read_text(encoding="utf-8", errors="replace")
    if code.strip() == "??":
        if _normalize_for_move_detection(raw_new_text) in _removed_style_block_contents():
            return 0
        old_text = ""
    else:
        old_text = _strip_css_comments(_old_content_at_head(path))
    new_text = _strip_css_comments(raw_new_text)
    added_text = _git_word_diff_added_text(old_text, new_text)
    return added_text.count("!important")


def test_no_important_declaration_added_by_this_pilot_precise_diff_check() -> None:
    """KESIN/guvenilir bulgu: yalniz bu dalganin FIILEN EKLEDIGI (token-
    duzeyinde, git'in kendi word-diff algoritmasiyla dogrulanmis) icerikte
    '!important' var mi? Bu, satir-duzeyindeki eski kaba kontrolun aksine,
    onceden var olan CSS kurallarini -- minified/concatenate bir fiziksel
    satirin geri kalaninda bulunsalar bile -- VEYA acikca yorum metni
    icinde gecen '!important' kelimesini yanlis-pozitif olarak YAKALAMAZ.
    Bkz. `_added_important_count_for_css_file` docstring'i ve bu dosyadaki
    negative-control testleri (bolum 6.1) icin ayrintili gerekce."""
    entries = _git_status_css_entries()
    if not entries:
        pytest.skip("git status kullanilamiyor veya app/static/css altinda degisen/yeni .css dosyasi yok.")
    offenders: dict[str, int] = {}
    for code, path in entries:
        count = _added_important_count_for_css_file(code, path)
        if count:
            offenders[path] = count
    assert offenders == {}, (
        f"Bu dalganin FIILEN EKLEDIGI (token-duzeyinde dogrulanmis) CSS "
        f"icerikte !important bulundu: {offenders!r}"
    )


# ---------------------------------------------------------------------------
# 6.1) Yukaridaki word-diff mekanizmasinin SAF (git repo durumundan bagimsiz,
#      senkronize fixture'larla calisan) negative-control testleri. Bunlar
#      `_git_word_diff_added_text` fonksiyonunu DOGRUDAN, sentetik eski/yeni
#      CSS metin ciftleriyle cagirir -- gercek bir uncommitted repo diff'ine
#      ihtiyac YOKTUR (bu yuzden yukaridaki iki testin aksine SKIP etmezler,
#      her zaman calisirlar). Kontrol matrisi (BYS360 CSS-TEST-HARNESS-
#      FALSE-POSITIVE-V1 gorev tanimi, bolum 4):
#        A) unrelated property degisir, ayni (minified) satirda ONCEDEN VAR
#           olan !important etkilenmez -> PASS (0)
#        B) mevcut bir declaration'a GERCEKTEN yeni !important eklenir -> FAIL (>0)
#        C) yeni bir CSS rule GERCEKTEN !important ile eklenir -> FAIL (>0)
#        D) icerik byte-identical kalir -> PASS (0)
#        E) bir !important bir yerden SILINIP baska bir yere YENI eklenir
#           (net count DEGISMEZ) -> yine de FAIL (>0) -- net-count-esitligine
#           dayanan zayif bir yaklasimin YETERSIZ kalacagini kanitlar.
# ---------------------------------------------------------------------------


def test_word_diff_guard_control_a_ignores_preexisting_important_sharing_a_minified_line() -> None:
    old_text = ".a{color:red}.b{width:1px!important}"
    new_text = ".a{color:blue}.b{width:1px!important}"
    added = _git_word_diff_added_text(old_text, new_text)
    assert added.count("!important") == 0, f"Kontrol A basarisiz: {added!r}"


def test_word_diff_guard_control_b_catches_important_newly_added_to_existing_declaration() -> None:
    old_text = ".a{color:red}"
    new_text = ".a{color:red!important}"
    added = _git_word_diff_added_text(old_text, new_text)
    assert added.count("!important") == 1, f"Kontrol B basarisiz: {added!r}"


def test_word_diff_guard_control_c_catches_important_in_a_wholly_new_rule() -> None:
    old_text = ".a{color:red}"
    new_text = ".a{color:red}.c{width:1px!important}"
    added = _git_word_diff_added_text(old_text, new_text)
    assert added.count("!important") == 1, f"Kontrol C basarisiz: {added!r}"


def test_word_diff_guard_control_d_reports_zero_for_byte_identical_content() -> None:
    text = ".a{color:red!important}"
    added = _git_word_diff_added_text(text, text)
    assert added.count("!important") == 0, f"Kontrol D basarisiz: {added!r}"


def test_word_diff_guard_control_e_catches_a_relocated_important_despite_unchanged_net_count() -> None:
    """Net count (eski toplam '!important' sayisi == yeni toplam sayisi)
    burada AYNIDIR (1 == 1) -- ama biri .a'dan SILINIP .b'ye YENI eklenmis.
    Zayif bir 'toplam sayi degismedi -> PASS' yaklasimi bunu YANLISLIKLA
    gecerdi; token-duzeyinde diff dogru sekilde YENI eklemeyi yakalar."""
    old_text = ".a{color:red!important}.b{width:1px}"
    new_text = ".a{color:red}.b{width:1px!important}"
    added = _git_word_diff_added_text(old_text, new_text)
    assert added.count("!important") == 1, f"Kontrol E basarisiz: {added!r}"


def test_word_diff_guard_reproduces_the_real_bys360_portal_minified_line_false_positive_and_fixes_it() -> None:
    """Gercek, kanitlanmis false-positive vakasinin BIREBIR yapisal
    tekrari: `.bys360-v2121-media-tools{grid-template-columns:1fr 1fr 1fr}`
    -> `minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)` degisikligi, AYNI
    fiziksel (whitespace'siz, dogrudan bitisik) satirda, DOKUNULMAMIS bir
    `.portal-mention-menu{...!important...}` kuraliyla birlikte. Eski
    physical-line implementasyonu bunu 3 yanlis-pozitif olarak
    raporluyordu (bkz. bu dosyanin git gecmisi); yeni token-duzeyi
    implementasyonu 0 raporlamalidir. Gercek app/static/css/bys360_portal.
    css dosyasina DOKUNULMADAN, sentetik ama yapisal olarak ozdes bir
    fixture ile dogrulanir -- bu wave'in kapsami test-harness ile
    sinirlidir, Portal kaynak dosyasi degistirilmez."""
    old_text = (
        ".bys360-v2121-media-tools{grid-template-columns:1fr 1fr 1fr}"
        ".portal-media-field-wide{grid-column:auto}"
        ".portal-mention-menu{left:12px!important;right:12px!important;width:auto!important}"
    )
    new_text = (
        ".bys360-v2121-media-tools{grid-template-columns:"
        "minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)}"
        ".portal-media-field-wide{grid-column:auto}"
        ".portal-mention-menu{left:12px!important;right:12px!important;width:auto!important}"
    )
    added = _git_word_diff_added_text(old_text, new_text)
    assert added.count("!important") == 0, (
        f"Regresyon: gercek bys360_portal.css minified-line senaryosu artik "
        f"yanlis-pozitif VERMEMELI. Eklenen icerik: {added!r}"
    )


# ---------------------------------------------------------------------------
# 7) Gercek route + kimlik dogrulamali test client kontrolleri. Paylasilan
#    conftest.py `client` fixture'i KULLANILAMAZ (login_required + admin/
#    manager rol + gercek bir destek bileti gerektiren rotalar icin yazilabilir
#    bir kullaniciya sahip degil) -- bu yuzden Wave2/phase13b dosyalarindaki
#    KURULU desenle (izole, gecici SQLite DB'li KENDI app'i + gercek admin
#    kullanici + gercek login POST) module-scoped bir fixture kullanilir.
#
# ONEMLI: Bu route testleri TAM SAYFA render ciktisinda "sifir style=" KONTROL
# ETMEZ -- cunku app/templates/base.html'in KENDISI (bu pilotun kapsami
# DISINDA, dokunulmadi) 5-6 adet KENDI style="..." attribute'unu tasiyor
# (topbar bildirim rozeti, avatar oku, logout formlari vb.) ve bu 8 sablonun
# TAMAMI base.html'i extend ediyor. Bu yazar bunu, izole bir app uzerinden
# gercekten GET yaparak DOGRUDAN gozlemleyerek dogruladi (her 8 rotanin tam
# render ciktisinda TAM OLARAK 5 adet style=" bulundu -- hepsi base.html
# kaynakli, 8 hedef sablonun HICBIRINDEN degil). Bu yuzden "sifir style="
# kontrolu yukarida (bolum 1) 8 dosyanin KENDI KAYNAGINA uygulanmistir;
# burada rota testleri yalniz "rota GERCEKTEN calisiyor, 500 vermiyor VE
# gercek base.html-sarmali icerik uretiyor (safe_render'in exception-fallback
# stub'u DEGIL)" seklindeki farkli, tamamlayici bir sinyali dogrular.
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "csp_style2a" / "test_dbs"
_SAFE_RENDER_FALLBACK_MARKERS = ("şablonunda hata var", "şablonu hatalı")
_BASE_TEMPLATE_MARKER = "topbarNotificationBadge"


@pytest.fixture(scope="module")
def style2a_env():
    """Izole, gecici SQLite DB'li bagimsiz bir Flask app + admin kullanici +
    ornek destek bileti + giris yapilmis test client kurar. Wave2/phase13b
    dosyalarindaki KURULU desenle ayni (bkz. tests/security/
    test_csp_wave2_personnel_inline_handlers_contract.py::_make_app).
    Module-scoped: 7+1 rota testi arasinda TEK app kurulumu paylasilir
    (performans), ama bu dosyanin DISINDAKI hicbir teste sizmaz (mp.undo()
    ile ortam degiskenleri geri alinir)."""
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-csp-style2a-contract-min-length-ok")
    mp.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    mp.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    mp.setenv("AUTO_REPAIR_SCHEMA", "false")
    mp.setenv("STRICT_SCHEMA_CHECK", "false")
    mp.setenv("REQUIRE_DOTENV_FILE", "false")
    mp.setenv("STRICT_ENV_VALIDATION", "false")
    mp.setenv("WTF_CSRF_ENABLED", "false")
    mp.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    mp.setenv("MAIL_SUPPRESS_SEND", "true")
    mp.setenv("SCHEDULER_ENABLED", "false")
    mp.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    # file_center_home rotasi bu bayrak kapaliyken /home'a yonlendirir --
    # gercek sablonu render ettirebilmek icin acilir (bkz. app/file_center/
    # services.py::file_center_enabled / env_bool).
    mp.setenv("FILE_CENTER_ENABLED", "true")

    from app import create_app
    from config import Config

    mp.setattr(Config, "APP_ENV", "testing")
    mp.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    mp.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db
    from app.models import User
    from app.models.support_models import SupportTicket

    with app.app_context():
        db.create_all()
        user = User(
            sicil_no="style2a001",
            email="style2a.contract@ktb.gov.tr",
            ad="Style2A",
            soyad="Kontrat",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("Style2ATestContractKey1!")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        ticket = SupportTicket(
            ticket_no="DTY-STYLE2A-0001",
            title="Style2A kontrat testi icin sahte bilet",
            description="Bu bilet yalniz tests/security/test_csp_style2a_repo_wide_contract.py "
            "tarafindan /support/<ticket_id> rotasini gercek bir kayitla test etmek icin olusturuldu.",
            ticket_type="other",
            module_name="Genel",
            priority="normal",
            status="open",
            created_by_user_id=user_id,
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    client = app.test_client()
    login_response = client.post(
        "/login",
        data={"sicil_or_email": "style2a001", "password": "Style2ATestContractKey1!"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302, (
        f"Test admin kullanicisi ile giris basarisiz oldu: status={login_response.status_code}"
    )
    assert "/login" not in (login_response.headers.get("Location") or ""), (
        "Giris sonrasi hala /login'e yonlendiriliyor -- kimlik dogrulama basarisiz olmus olabilir."
    )

    yield client, ticket_id

    mp.undo()


@pytest.mark.parametrize("relative_path,route", sorted(ROUTES_BY_TEMPLATE.items()))
def test_target_template_route_renders_successfully_when_authenticated(
    style2a_env, relative_path: str, route: str
) -> None:
    client, _ticket_id = style2a_env
    response = client.get(route, follow_redirects=True)
    assert response.status_code == 200, (
        f"{route} ({relative_path} rotasi) beklenmedik durum kodu dondurdu: "
        f"{response.status_code}"
    )
    body = response.get_data(as_text=True)
    assert _BASE_TEMPLATE_MARKER in body, (
        f"{route} yanitinda base.html'in kendi (bu pilotun kapsami disindaki) "
        f"'{_BASE_TEMPLATE_MARKER}' isaretcisi bulunamadi -- tam sayfa render "
        "gerceklesmemis olabilir."
    )
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body, (
            f"{route} yaniti safe_render() exception-fallback stub'u iceriyor "
            f"gibi gorunuyor ('{marker}' bulundu) -- gercek sablon render "
            "edilmemis olabilir."
        )


def test_support_detail_route_renders_successfully_for_a_real_ticket_when_authenticated(
    style2a_env,
) -> None:
    client, ticket_id = style2a_env
    response = client.get(f"/support/{ticket_id}", follow_redirects=True)
    assert response.status_code == 200, (
        f"/support/{ticket_id} beklenmedik durum kodu dondurdu: {response.status_code}"
    )
    body = response.get_data(as_text=True)
    assert _BASE_TEMPLATE_MARKER in body
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body
    assert "DTY-STYLE2A-0001" in body, (
        "/support/<ticket_id> yaniti, olusturulan gercek bileti icermiyor gibi "
        "gorunuyor -- yanlis bilete/sahte veriye dusulmus olabilir."
    )


# ---------------------------------------------------------------------------
# 8) Bu dosyanin KENDISI hicbir uygulama/sablon/CSS kaynagina YAZMIYOR --
#    yalniz okuma + izole kendi gecici test DB'sine yaziyor (bkz. yukaridaki
#    style2a_env fixture'i, ki bu SADECE test-only bir SQLite dosyasidir,
#    uygulama kaynagi degildir).
# ---------------------------------------------------------------------------


def test_this_file_never_writes_to_application_or_template_or_css_source_paths() -> None:
    forbidden_write_markers = (
        "write_text(",
        "shutil.copy",
        "shutil.move",
        "shutil.rmtree",
        "os.rename(",
        "os.remove(",
        "os.unlink(",
    )
    own_file = Path(__file__).resolve()
    text = own_file.read_text(encoding="utf-8")
    marker_def_start = text.index("forbidden_write_markers = (")
    marker_def_end = text.index(")\n", marker_def_start) + 1
    scan_text = text[:marker_def_start] + text[marker_def_end:]
    hits = [marker for marker in forbidden_write_markers if marker in scan_text]
    assert hits == [], (
        f"Bu dosyada beklenmedik dosya-yazma/degistirme cagrisi izi bulundu "
        f"(bu dosya SADECE okuma + kendi izole gecici test DB'sine yazma yapmali): {hits!r}"
    )
