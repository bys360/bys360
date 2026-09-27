"""CSP "Style-1" dalgasi - repo-genelinde sifir-envanter + temizlik
kapatma kontrati.

Bu dosya `test_csp_style1_directive_and_nonce_contract.py`'nin (HTTP/CSP
header + nonce enjeksiyon davranisi) TAMAMLAYICISIDIR; burada SADECE
kaynak-kod/statik envanter ve rota-enumerasyonu duzeyinde dogrulanan
maddeler yer alir:

    - Eski, kullanilmayan nonce mekanizmasi (`app/security/csp_nonce.py`,
      `init_csp_nonce`) repo genelinde SIFIR referansa sahip ve dosya
      olarak da MEVCUT DEGIL.
    - Hicbir CSP-ihlal-raporlama (violation-report) rotasi EKLENMEMIS.
    - Hicbir sayfada `<meta name="csp-nonce">` YOK.
    - `tests/security/test_csp_wave8_task_mail_guard_contract.py` icindeki
      bilinen xfail kullanim SAYISI bu dalgada DEGISMEMIS (Dalga 9'un kendi
      dosyasindaki -- `test_csp_wave9_final_zero_handler_contract.py` --
      ayni sayimin KUCUK OLCEKLI, Style-1'e ozgu bir aynasi).
    - Onceki dalgalarin (1-9A) kurdugu inline-handler/`javascript:`-URL
      SIFIR envanteri, Style-1'e ozgu, BAGIMSIZ bir kapi olarak burada da
      ayrica dogrulanir (yalniz wave9'un dosyasinin PASS etmesine ORTuk
      olarak guvenilmez).

ONEMLI: Bu dosyadaki HICBIR test gercek bir yazma/silme/ag/SMTP/surec yan
etkisi URETMEZ -- yalniz `Path.read_text()`, (opsiyonel salt-okunur)
`subprocess`/`git grep` ve gercek Flask `app.url_map`/test-client GET
istekleri kullanilir.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def client(app):
    """Fresh anonymous client. These contracts render public pages (/login,
    /forgot-password, /offline); the session-scoped shared client may still be
    logged in by an earlier module, and /login then redirects (302)."""
    return app.test_client()


REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 17) Eski nonce mekanizmasi tamamen kaldirilmis: sifir referans + dosya yok.
# ---------------------------------------------------------------------------


def test_csp_nonce_module_file_no_longer_exists() -> None:
    stale_module = REPO_ROOT / "app" / "security" / "csp_nonce.py"
    assert not stale_module.exists(), (
        f"{stale_module} hala repoda mevcut -- eski/dead nonce mekanizmasi "
        "kaldirilmis olmaliydi."
    )


def test_init_csp_nonce_has_zero_references_in_app_python_files() -> None:
    """Spesifikasyonun birebir istedigi kapsam: `app/**/*.py`, `__pycache__`
    haric, Python dosya-sistemi taramasiyla (subprocess grep DEGIL)."""
    offenders: dict[str, int] = {}
    app_root = REPO_ROOT / "app"
    for py_file in sorted(app_root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        text = py_file.read_text(encoding="utf-8", errors="replace")
        count = text.count("init_csp_nonce")
        if count:
            offenders[str(py_file.relative_to(REPO_ROOT))] = count
    assert offenders == {}, f"'init_csp_nonce' hala referans ediliyor (app/**/*.py): {offenders!r}"


def test_init_csp_nonce_has_zero_references_repo_wide_via_git_grep() -> None:
    """Ek/genisletilmis kapsam (spesifikasyonun onerdigi 'subprocess grep'
    alternatifi): `app/**/*.py` disinda da (tests/, scripts/, docs/ vb.)
    hicbir yerde 'init_csp_nonce' metni gecmemeli. `git grep` kullanilir
    (salt-okunur, hicbir dosyayi degistirmez); git bulunamazsa veya calisma
    kopyasi git deposu degilse test atlanir (ortam kisitlamasi, hata degil).

    ONEMLI KENDI-KENDINI-HARIC-TUTMA: bu KONTROLU ACIKLAYAN Style-1 test
    dosyalarinin KENDISI (bu dosya + kardes dosya), "init_csp_nonce" metnini
    fonksiyon adlari/docstring/yorum icinde VERI olarak dogal bicimde icerir
    (gercek bir kod referansi/import DEGIL). Bu yuzden git grep sonucundan bu
    iki dosyaya ait satirlar programatik olarak FILTRELENIR; geriye baska
    hicbir dosyadan satir kalmamasi beklenir."""
    exe = None
    for candidate in ("git",):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=False, timeout=10)
            exe = candidate
        except OSError:
            exe = None
    if exe is None:
        pytest.skip("git CLI bulunamadi; repo-genelinde ek grep dogrulama atlandi.")

    result = subprocess.run(
        [exe, "-C", str(REPO_ROOT), "grep", "-n", "init_csp_nonce"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    # `git grep` hic esleme bulamazsa exit code 1 doner (hata degil) -- bu
    # BEKLENEN/basarili durumdur. exit code >1 gercek bir git hatasidir.
    if result.returncode not in (0, 1):
        pytest.skip(f"git grep beklenmedik sekilde basarisiz oldu (exit={result.returncode}); dogrulama atlandi.")

    self_referential_paths = (
        "tests/security/test_csp_style1_repo_wide_zero_inventory_contract.py",
        "tests/security/test_csp_style1_directive_and_nonce_contract.py",
    )
    remaining_lines = [
        line
        for line in result.stdout.splitlines()
        if not any(line.replace("\\", "/").startswith(p) for p in self_referential_paths)
    ]
    assert remaining_lines == [], (
        "'init_csp_nonce' repo genelinde (Style-1'in kendi test dosyalari haric) "
        "hala esleme(ler) uretiyor:\n" + "\n".join(remaining_lines)
    )


# ---------------------------------------------------------------------------
# 19) Hicbir CSP-ihlal-raporlama rotasi eklenmemis.
# ---------------------------------------------------------------------------


def test_no_csp_violation_report_route_exists(app) -> None:
    offenders = []
    for rule in app.url_map.iter_rules():
        rule_text = rule.rule.lower()
        endpoint_text = (rule.endpoint or "").lower()
        if "csp" in rule_text and "report" in rule_text:
            offenders.append(rule.rule)
        elif "csp" in endpoint_text and "report" in endpoint_text:
            offenders.append(f"{rule.rule} (endpoint={rule.endpoint})")
    assert offenders == [], (
        f"CSP ihlal-raporlama ucuna benzeyen rota(lar) bulundu (Style-1 boyle bir "
        f"uc EKLEMEMELIYDI): {offenders!r}"
    )


# ---------------------------------------------------------------------------
# 20) Hicbir sayfada <meta name="csp-nonce"> yok.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/login", "/forgot-password", "/offline"])
def test_no_csp_nonce_meta_tag_in_rendered_pages(client, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200, f"{path} beklenmedik durum kodu dondurdu: {response.status_code}"
    html = response.get_data(as_text=True)
    lowered = html.lower()
    assert '<meta name="csp-nonce"' not in lowered
    assert "<meta name='csp-nonce'" not in lowered
    assert "csp-nonce" not in lowered, (
        f"{path} render ciktisinda beklenmedik 'csp-nonce' metni bulundu -- "
        "meta tag olarak eklenmis olabilir."
    )


def test_no_csp_nonce_meta_tag_in_error_page_render(app) -> None:
    from flask import render_template

    with app.test_request_context("/"):
        html = render_template("errors/403.html")
    assert "csp-nonce" not in html.lower()


# ---------------------------------------------------------------------------
# 22) tests/security/test_csp_wave8_task_mail_guard_contract.py icindeki
# bilinen xfail kullanim sayisi bu dalgada DEGISMEMIS.
#
# NOT (yapilan gercek olcum): gorev tanimi bu sayinin "2" olmasini
# bekliyordu; bu dosya yazilirken yapilan GERCEK statik regex sayimi
# (tests/security/test_csp_wave8_task_mail_guard_contract.py icinde tam
# olarak 1 xfail-cagrisi (asagidaki _XFAIL_CALL_RE deseni), 0 xfail-mark
# dekoratoru (asagidaki _XFAIL_MARK_RE deseni) --
# `tests/security/test_csp_wave9_final_zero_handler_contract.py` icindeki
# `EXPECTED_XFAIL_CALL_COUNT_IN_WAVE8_TASK_MAIL_GUARD_FILE = 1` sabitiyle
# BIREBIR tutarli) "2" DEGIL "1" sonucunu verdi. Asagidaki sabit GERCEK/
# OLCULEN degeri (1) kilitler -- "2" yazilsaydi bu test SUREKLI FAIL verir
# ve gercek bir regresyonu sinyallemeyen gurultulu bir test olurdu. Bu fark
# koordinatore ayrica raporlanmistir (bkz. gorev raporu).
# ---------------------------------------------------------------------------

WAVE8_TASK_MAIL_GUARD_FILE = "tests/security/test_csp_wave8_task_mail_guard_contract.py"
EXPECTED_XFAIL_USAGE_COUNT_IN_WAVE8_TASK_MAIL_GUARD_FILE = 1

_XFAIL_CALL_RE = re.compile(r"pytest\.xfail\(")
_XFAIL_MARK_RE = re.compile(r"@pytest\.mark\.xfail")


def test_wave8_task_mail_guard_xfail_usage_count_is_unchanged_by_style1() -> None:
    text = (REPO_ROOT / WAVE8_TASK_MAIL_GUARD_FILE).read_text(encoding="utf-8")
    call_count = len(_XFAIL_CALL_RE.findall(text))
    mark_count = len(_XFAIL_MARK_RE.findall(text))
    total = call_count + mark_count
    assert total == EXPECTED_XFAIL_USAGE_COUNT_IN_WAVE8_TASK_MAIL_GUARD_FILE, (
        f"{WAVE8_TASK_MAIL_GUARD_FILE} icindeki xfail kullanim sayisi "
        f"{EXPECTED_XFAIL_USAGE_COUNT_IN_WAVE8_TASK_MAIL_GUARD_FILE} degil, {total} "
        f"bulundu (call={call_count}, mark-decorator={mark_count}). Style-1 bu "
        "dosyaya YENI bir xfail eklememeli/mevcut olani kaldirmamali."
    )


def test_style1_new_test_files_introduce_zero_new_xfail_usage() -> None:
    """Madde 23'un kendi-dosya kontrolu: bu Style-1 dalgasinin EKLEDIGI iki
    yeni test dosyasinin (bu dosya + kardes
    `test_csp_style1_directive_and_nonce_contract.py`) KENDI kaynaklarinda
    hic gercek bir xfail-cagrisi veya xfail-mark dekoratoru kullanimi
    (asagidaki `_XFAIL_CALL_RE`/`_XFAIL_MARK_RE` desenleriyle olculur) YOK."""
    style1_files = [
        REPO_ROOT / "tests" / "security" / "test_csp_style1_directive_and_nonce_contract.py",
        REPO_ROOT / "tests" / "security" / "test_csp_style1_repo_wide_zero_inventory_contract.py",
    ]
    offenders: dict[str, int] = {}
    for path in style1_files:
        text = path.read_text(encoding="utf-8")
        count = len(_XFAIL_CALL_RE.findall(text)) + len(_XFAIL_MARK_RE.findall(text))
        if count:
            offenders[str(path.relative_to(REPO_ROOT))] = count
    assert offenders == {}, f"Style-1 test dosyalari beklenmedik xfail kullanim(lar)i iceriyor: {offenders!r}"


# ---------------------------------------------------------------------------
# 24) Onceki dalgalarin (1-9A) kurdugu inline-handler / javascript:-URL
# SIFIR envanteri -- Style-1'e ozgu, bagimsiz bir kapi (wave9'un kendi
# dosyasina ORTUK olarak guvenmez).
# ---------------------------------------------------------------------------

# Kanonik desenler -- Wave1-9A ile birebir ayni (bkz.
# tests/security/test_csp_wave9_final_zero_handler_contract.py).
_INLINE_EVENT_ATTR_RE = re.compile(r"""[\s]on[a-zA-Z]+\s*=\s*["']""")
_JS_HREF_SRC_RE = re.compile(r"""(?:href|src)\s*=\s*["']\s*javascript:""", re.IGNORECASE)


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


def test_style1_own_gate_inline_event_handler_inventory_is_zero() -> None:
    templates_offenders = _scan_inline_handlers(REPO_ROOT / "app" / "templates")
    static_offenders = _scan_inline_handlers(REPO_ROOT / "app" / "static")
    total = sum(templates_offenders.values()) + sum(static_offenders.values())
    assert total == 0, (
        "Style-1 kendi bagimsiz kapisi: app/templates + app/static genelinde "
        f"inline event-handler (on*=) sayisi 0 olmali. templates={templates_offenders!r}, "
        f"static={static_offenders!r}"
    )


def test_style1_own_gate_javascript_href_src_inventory_is_zero() -> None:
    templates_offenders = _scan_js_href_src(REPO_ROOT / "app" / "templates")
    static_offenders = _scan_js_href_src(REPO_ROOT / "app" / "static")
    total = sum(templates_offenders.values()) + sum(static_offenders.values())
    assert total == 0, (
        "Style-1 kendi bagimsiz kapisi: app/templates + app/static genelinde "
        f"href/src=javascript: sayisi 0 olmali. templates={templates_offenders!r}, "
        f"static={static_offenders!r}"
    )


# ---------------------------------------------------------------------------
# 21) Bu dalganin YENI test dosyalarinin, template/CSS/JS ICERIGININ
# degistigini iddia eden hicbir assertion ICERMEDIGININ hafif bir kaniti
# (koordinator ayrica kendi repo-genelindeki diff denetimini yapacak --
# burada yalniz bu iki YENI dosyanin kendisinin, `app/templates`,
# `app/static/js`, `app/static/css` gibi UYGULAMA yollarina YAZMA/DUZENLEME
# CAGRISI icermedigi statik olarak dogrulanir).
# ---------------------------------------------------------------------------


def test_style1_test_files_never_write_to_application_source_paths() -> None:
    """NOT: `forbidden_write_markers` tuple'i BILINCLI olarak "open(" veya
    ".write(" gibi asiri genel/gurultulu belirteçler ICERMEZ (bunlar
    docstring/degisken adi baglaminda yanlis-pozitif uretebilir). Kendi
    dosyasi (bu fonksiyonun tanimlandigi dosya) taranirken, asagidaki
    `forbidden_write_markers` tanim blogunun KENDISI (yasakli kelimeleri
    veri olarak dogal biçimde iceren TEK yer) taramadan HARIC tutulur --
    aksi halde bu fonksiyon kendi kendini yanlis-pozitif isaretlerdi."""
    style1_files = [
        REPO_ROOT / "tests" / "security" / "test_csp_style1_directive_and_nonce_contract.py",
        REPO_ROOT / "tests" / "security" / "test_csp_style1_repo_wide_zero_inventory_contract.py",
    ]
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
    offenders: dict[str, list[str]] = {}
    for path in style1_files:
        text = path.read_text(encoding="utf-8")
        if path.resolve() == own_file:
            marker_def_start = text.index("forbidden_write_markers = (")
            marker_def_end = text.index(")\n", marker_def_start) + 1
            text = text[:marker_def_start] + text[marker_def_end:]
        hits = [marker for marker in forbidden_write_markers if marker in text]
        if hits:
            offenders[str(path.relative_to(REPO_ROOT))] = hits
    assert offenders == {}, (
        f"Style-1 test dosyalarinda beklenmedik dosya-yazma/degistirme cagrisi "
        f"izi bulundu (bu dosyalar SADECE okuma yapmali): {offenders!r}"
    )
