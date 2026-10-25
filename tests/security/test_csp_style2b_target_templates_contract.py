"""CSP "Style-2B" dalgasi -- 8 sablonluk tam-statik `style="..."` -> CSS
sinifi donusumu, dalganin KENDI kontrat testi.

BAGLAM: Style-2A pilotunun ("dusuk riskli, sabit 8 sablon" -- bkz.
`test_csp_style2a_repo_wide_contract.py`) ardindan calisan ikinci dalga.
Bu dosya, o dalganin YAZDIGI style verilerine/CSS dosyalarina DOKUNMADAN,
sadece YENI bir test dosyasi ekleyerek Style-2B'nin KENDI 8 hedef
sablonunu ve 8 yeni CSS dosyasini kilitler. Hicbir uygulama/sablon/CSS/
config dosyasina yazmaz -- yalniz `Path.read_text()`, `git show`/`git
diff` (salt-okunur) ve gercek Flask test client GET/POST istekleri
(kendi izole, gecici SQLite DB'li app'i uzerinden) kullanir.

Style-2B'nin 8 hedef sablonu (dalga oncesi -- 649f4530 = Style-2A'nin
bitis commit'i -- statik `style="..."` sayisi, olcum
`tests/security/_bys360_style_inventory.py::count_static_style_attrs_in_text`
ile TEK TEK dogrulanmistir; bkz. asagidaki
`test_measured_pre_wave_count_matches_documented_constant_per_template` --
bu tablo korle GUVENILMEZ, testin kendisi `git show 649f4530:<path>`
uzerinden BAGIMSIZ olarak yeniden olcer):

    app/templates/communication/phase1_bulletin_form.html      : 9
    app/templates/feedback/quick_feedback.html                 : 9
    app/templates/feedback_executive_summary_dashboard.html    : 8
    app/templates/assignment_recommendations.html              : 7
    app/templates/hr_personnel_lifecycle_center.html            : 7
    app/templates/admin_ai_center.html                          : 6
    app/templates/feedback_meeting_detail.html                  : 6
    app/templates/performance_v2_phase1.html                    : 6
                                                        TOPLAM   = 58

Her sablon icin yeni CSS dosyasi (`app/static/css/*.css`) ve rota/view
fonksiyonu asagidaki `TARGET_TEMPLATES` sozlugunde eslenmistir; her satir
ayrica `app/`icindeki gercek kaynak koda (route decorator'lari, view
fonksiyonu govdesi, render_template/safe_render cagrisi) grep ile
dogrulanmistir -- varsayimla degil.

GERCEK BULGU, SONRADAN DUZELTILDI (bu dosyanin yazarinin, gorev tanimindaki
8 rotayi canli Flask test client ile GERCEKTEN denerken bulup -- Style-2B
kapsaminda degil, kapsamli olarak belgeleyip -- ayri bir bugfix dalgasinda
KAPATILAN bir hata): `/performance/feedback-executive-summary`
(`feedback_executive_summary_dashboard` view fonksiyonu,
app/performance/engagement_feedback_routes.py) Style-2B'nin ORIJINAL
calismasi sirasinda admin olarak GET edildiginde 500 donuyordu. Kok neden:
view govdesi `build_feedback_executive_summary(...)`'in dondurdugu
`dashboard` dict'ini `**dashboard` ile `safe_render(..., preset=preset,
**dashboard)` cagrisina aciyordu; ancak `build_feedback_executive_summary`
(app/services/performance/feedback_executive_summary_service.py:224)
donus sozlugune KENDI `"preset"` anahtarini da koyuyordu -- bu da
`safe_render()` cagrisinda `preset` icin CIFT deger (`TypeError:
app.route_support.safe_render() got multiple values for keyword argument
'preset'`) hatasina yol aciyordu. Bu, Style-2B'nin DOKUNMADIGI
`app/performance/engagement_feedback_routes.py` dosyasinda onceden var
olan bir hataydi (bkz. `test_engagement_feedback_routes_file_was_untouched_
by_style2b_itself` -- Style-2B'nin KENDI kapanis commit'inin bu dosyayi
degistirmedigi, sabit bir tarihsel commit araligina kilitlenerek ayrica
dogrulanir); Style-2B'nin sablon/CSS degisikligiyle ILGISI YOKTU ve o dalga
kapsaminda DUZELTILMEDI (yalniz test-only bir dosya yazma izni vardi).
Hata artik DUZELTILDI (ayri bir "BYS360 Performans Feedback Executive
Summary 500 Hatasi" bugfix dalgasinda, app/performance/
engagement_feedback_routes.py:305'teki fazladan `preset=preset` kwarg'i
kaldirilarak) -- kapsamli regresyon testleri
tests/performance/test_feedback_executive_summary_preset_context_regression.py
dosyasinda. Bu yuzden bu rota artik asagidaki "canli render" testlerinde
(bolum 7) GENEL donguye DAHIL (eskiden haric tutuluyordu); ayrica bkz.
`test_feedback_executive_summary_dashboard_route_preset_kwarg_collision_bug_is_fixed`.
Tum 8 rota canli olarak 200 doner ve tam render (base.html sarmali +
hicbir safe_render exception-fallback izi) uretir.

KAPSAM DISI/DOKUNULMAYAN: Bu dosya HICBIR uygulama/sablon/CSS/config
dosyasina yazmaz.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "security"))

from _bys360_style_inventory import count_static_style_attrs_in_text  # noqa: E402

PRE_WAVE_REF = "649f4530"

# ---------------------------------------------------------------------------
# Ortak sabitler / regex'ler (Style-2A ile BIREBIR ayni kanonik desenler --
# bkz. test_csp_style2a_repo_wide_contract.py basi docstring, bu desenlerin
# gecmisi/duzeltmeleri orada belgeli).
# ---------------------------------------------------------------------------

_STYLE_ATTR_RE = re.compile(r'style\s*=\s*"([^"]*)"', re.IGNORECASE)
_STYLE_BLOCK_RE = re.compile(r"<style\b", re.IGNORECASE)
_INLINE_EVENT_ATTR_RE = re.compile(r"""[\s]on[a-zA-Z]+\s*=\s*["']""")
_JS_HREF_SRC_RE = re.compile(r"""(?:href|src)\s*=\s*["']\s*javascript:""", re.IGNORECASE)
_LINK_STYLESHEET_RE_PREFIX = (
    r"""<link\s+rel=["']stylesheet["']\s+href=["']\{\{\s*url_for\(\s*"""
    r"""["']static["']\s*,\s*filename=["']css/"""
)
_LINK_STYLESHEET_RE_SUFFIX = r"""\.css["']\s*\)\s*\}\}["']\s*>"""
_CSS_CLASS_SELECTOR_RE = re.compile(r"\.([A-Za-z0-9_-]+)\s*\{")
_CLASS_ATTR_RE = re.compile(r'class\s*=\s*"([^"]*)"')

# relative_path -> (pre-wave static count @649f4530, css filename stem, route, view function name)
TARGET_TEMPLATES: dict[str, dict[str, str | int]] = {
    "app/templates/communication/phase1_bulletin_form.html": {
        "pre_wave": 9,
        "css": "communication_phase1_bulletin_workspace",
        "route": "/communication/faz1/bulletins/new",
        "view": "communication_phase1_bulletin_new",
        "view_file": "app/communication/phase1_routes.py",
    },
    "app/templates/feedback/quick_feedback.html": {
        "pre_wave": 9,
        "css": "feedback_quick_feedback_workspace",
        "route": "/feedback/gonder",
        "view": "bys360_feedback_new",
        "view_file": "app/communication/user_feedback_routes.py",
    },
    "app/templates/feedback_executive_summary_dashboard.html": {
        "pre_wave": 8,
        "css": "feedback_executive_summary_workspace",
        "route": "/performance/feedback-executive-summary",
        "view": "feedback_executive_summary_dashboard",
        "view_file": "app/performance/engagement_feedback_routes.py",
    },
    "app/templates/assignment_recommendations.html": {
        "pre_wave": 7,
        "css": "performance_assignment_recommendations_workspace",
        "route": "/performance/task-management/recommendations",
        "view": "performance_task_management_recommendations",
        "view_file": "app/performance/task_routes.py",
    },
    "app/templates/hr_personnel_lifecycle_center.html": {
        "pre_wave": 7,
        "css": "hr_personnel_lifecycle_workspace",
        "route": "/hr-management/personnel-operations/lifecycle",
        "view": "hr_personnel_lifecycle_center",
        "view_file": "app/institutional/hr_personnel_phase11_routes.py",
    },
    "app/templates/admin_ai_center.html": {
        "pre_wave": 6,
        "css": "admin_ai_center_workspace",
        "route": "/admin/ai-center",
        "view": "admin_ai_center",
        "view_file": "app/admin/ai_routes.py",
    },
    "app/templates/feedback_meeting_detail.html": {
        "pre_wave": 6,
        "css": "feedback_meeting_detail_workspace",
        "route": "/performance/feedback-meetings/<int:meeting_id>",
        "view": "feedback_meeting_detail",
        "view_file": "app/performance/engagement_feedback_routes.py",
    },
    "app/templates/performance_v2_phase1.html": {
        "pre_wave": 6,
        "css": "performance_v2_phase1_workspace",
        "route": "/performans/v2/faz1",
        "view": "performance_v2_phase1_dashboard",
        "view_file": "app/performance/v2_routes.py",
    },
}
TOTAL_PRE_WAVE_ATTRS = sum(int(v["pre_wave"]) for v in TARGET_TEMPLATES.values())  # 58

# Bu 8 rotanin TAMAMI gercekten calisir (200) VE tam render uretir.
# BYS360 PERFORMANS BUGFIX KOORDINATOR NOTU: feedback_executive_summary_dashboard
# eskiden burada -- pre-existing/out-of-scope bir "preset" cift-kwarg
# TypeError'i yuzunden -- haric tutuluyordu (bkz. dosya basi docstring). O hata
# app/performance/engagement_feedback_routes.py:305'teki fazladan `preset=preset`
# kwarg'i kaldirilarak ayri bir bugfix dalgasinda duzeltildi (bkz.
# tests/performance/test_feedback_executive_summary_preset_context_regression.py);
# rota artik 200 doner, exclude kaldirildi.
LIVE_RENDER_ROUTES: dict[str, str] = {
    relative_path: str(meta["route"]) for relative_path, meta in TARGET_TEMPLATES.items()
}


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _git_show(ref: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (
        f"'git show {ref}:{relative_path}' basarisiz oldu: {result.stderr!r}"
    )
    return result.stdout


def _git_diff_text(relative_path: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--", relative_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.stdout


def _parse_declarations(value: str) -> dict[str, str]:
    """`"a:1;b:2;"` -> `{"a": "1", "b": "2"}`. Bosluk-duyarsiz, sira-bagimsiz."""
    declarations: dict[str, str] = {}
    for chunk in value.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            continue
        prop, _, val = chunk.partition(":")
        declarations[prop.strip().lower()] = val.strip()
    return declarations


# ---------------------------------------------------------------------------
# 1) Rota/view kaniti: her sablon gercekten bir @bp.route(...) dekoratorune
#    ve render_template/safe_render cagrisina bagli bir view fonksiyonuna
#    sahip mi -- kaynak koddan grep ile dogrulanir (varsayim degil).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_has_real_route_and_view_function_evidence(relative_path: str) -> None:
    meta = TARGET_TEMPLATES[relative_path]
    view_file = REPO_ROOT / str(meta["view_file"])
    text = view_file.read_text(encoding="utf-8")
    view_name = str(meta["view"])

    def_match = re.search(rf"^def {re.escape(view_name)}\(", text, re.MULTILINE)
    assert def_match, f"{meta['view_file']} icinde 'def {view_name}(' bulunamadi."

    # Fonksiyon govdesini (bir sonraki ust-seviye 'def '/dosya sonuna kadar) al.
    body_start = def_match.end()
    next_def = re.search(r"^def ", text[body_start:], re.MULTILINE)
    body_end = body_start + next_def.start() if next_def else len(text)
    body = text[body_start:body_end]

    template_basename = Path(relative_path).name
    assert template_basename in body, (
        f"{meta['view']}() govdesinde '{template_basename}' render cagrisi bulunamadi."
    )
    assert "render_template(" in body or "safe_render(" in body, (
        f"{meta['view']}() govdesinde render_template()/safe_render() cagrisi bulunamadi."
    )

    # Dekorator bloğu: 'def <view_name>(' oncesindeki en yakin '@main_bp.route'/
    # '@bp.route' satirlarini icerir (ara decoratorler dahil, bosluk/yeni-satir
    # ile ayrilmis olabilir).
    pre_text = text[: def_match.start()]
    decorator_block_match = re.search(r"((?:@\S.*\n)+)$", pre_text)
    assert decorator_block_match, f"{meta['view']}() oncesinde dekorator bloğu bulunamadi."
    decorator_block = decorator_block_match.group(1)
    assert re.search(r"@main_bp\.route\(|@\w+\.route\(", decorator_block), (
        f"{meta['view']}() dekorator blogunda bir '.route(...)' cagrisi bulunamadi: {decorator_block!r}"
    )


# ---------------------------------------------------------------------------
# 2) Sablonun KENDI kaynagi (Path.read_text) -- 0 statik style="..." attribute.
#    HEM kaba regex HEM kanonik HTMLParser-tabanli sayac (_bys360_style_inventory)
#    AYNI ANDA dogrulanir (ikisi de 0 demeli).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_source_has_zero_style_attribute_regex_and_canonical_agree(
    relative_path: str,
) -> None:
    text = _read(relative_path)
    regex_matches = _STYLE_ATTR_RE.findall(text)
    canonical_count = count_static_style_attrs_in_text(text, relative_path)
    assert regex_matches == [], (
        f"{relative_path} regex ile hala style=\"...\" iceriyor: {regex_matches!r}"
    )
    assert canonical_count == 0, (
        f"{relative_path} kanonik HTMLParser sayaciyla hala {canonical_count} statik "
        "style attribute iceriyor."
    )


# ---------------------------------------------------------------------------
# 3) Toplam kaldirilan statik sayi == 58, git'ten TURETILEREK dogrulanir
#    (yalniz dosya basi tablodaki sabitlere degil, `git show 649f4530:<path>`
#    ile KENDI olcumune dayanir -- kor guven yok).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_measured_pre_wave_count_matches_documented_constant_per_template(
    relative_path: str,
) -> None:
    meta = TARGET_TEMPLATES[relative_path]
    pre_wave_text = _git_show(PRE_WAVE_REF, relative_path)
    measured = count_static_style_attrs_in_text(pre_wave_text, relative_path)
    assert measured == meta["pre_wave"], (
        f"{relative_path}: {PRE_WAVE_REF} anindaki OLCULEN statik sayi ({measured}) "
        f"dosya basi belgelenen sabitle ({meta['pre_wave']}) uyusmuyor -- belge yanlis "
        "olabilir, koru korune guvenilmemeli."
    )


def test_total_removed_static_style_attrs_across_8_templates_equals_58_derived_from_git() -> None:
    """En guvenilir olcum: her sablon icin (649f4530'daki kanonik statik sayi) -
    (guncel kanonik statik sayi) farkini TOPLAR -- 58'i KOR biçimde varsaymaz,
    iki gercek olculmus durumdan turetir."""
    total_removed = 0
    per_template: dict[str, int] = {}
    for relative_path in TARGET_TEMPLATES:
        before = count_static_style_attrs_in_text(
            _git_show(PRE_WAVE_REF, relative_path), relative_path
        )
        after = count_static_style_attrs_in_text(_read(relative_path), relative_path)
        removed = before - after
        per_template[relative_path] = removed
        total_removed += removed

    assert total_removed == TOTAL_PRE_WAVE_ATTRS, (
        f"Git'ten TURETILEN toplam kaldirilan statik style sayisi ({total_removed}) "
        f"beklenen 58'e ({TOTAL_PRE_WAVE_ATTRS}) esit degil. Sablon-bazli detay: {per_template!r}"
    )


# ---------------------------------------------------------------------------
# 4) Temsili orneklem: en az 3 (ya da daha azsa hepsi) eski->yeni deklarasyon
#    eslemesi, gercek diff'ten alinan deger cifti uzerinden, order/whitespace-
#    duyarsiz sozluk karsilastirmasiyla dogrulanir.
# ---------------------------------------------------------------------------

# (relative_path, old style value, new css class name) -- degerler `git diff`
# cikisindan BIREBIR alinmistir (bkz. bu dosyanin yazilis surecinde calistirilan
# `git diff -- <template>`).
DECLARATION_MAPPING_SAMPLES: list[tuple[str, str, str]] = [
    # communication/phase1_bulletin_form.html (9 statik -> 7 sinif, bazi sinif
    # birden fazla eski deger tarafindan paylasilir; en az 3 farkli sinif ornekleniyor)
    (
        "app/templates/communication/phase1_bulletin_form.html",
        "min-height:110px;",
        "bulletin-target-textarea",
    ),
    (
        "app/templates/communication/phase1_bulletin_form.html",
        "padding:18px;background:#f8fafc;box-shadow:none;",
        "bulletin-preset-panel",
    ),
    (
        "app/templates/communication/phase1_bulletin_form.html",
        "font-weight:900;color:#111827;margin-bottom:8px;",
        "bulletin-preset-title",
    ),
    (
        "app/templates/communication/phase1_bulletin_form.html",
        "display:inline-block;margin:0 10px 8px 0;padding:6px 10px;border-radius:999px;"
        "background:#fff;border:1px solid rgba(15,23,42,.08);",
        "bulletin-preset-chip",
    ),
    # feedback/quick_feedback.html
    (
        "app/templates/feedback/quick_feedback.html",
        "margin-top:5px;line-height:1.7;",
        "quick-feedback-setup-note",
    ),
    (
        "app/templates/feedback/quick_feedback.html",
        "font-size:1.04rem;",
        "quick-feedback-panel-heading-lg",
    ),
    (
        "app/templates/feedback/quick_feedback.html",
        "min-height:36px;padding:0 12px;font-size:.78rem;",
        "quick-feedback-btn-compact",
    ),
    # feedback_executive_summary_dashboard.html
    (
        "app/templates/feedback_executive_summary_dashboard.html",
        "color:#6b7280;font-size:.82rem;",
        "feedback-exec-summary-scope-note",
    ),
    (
        "app/templates/feedback_executive_summary_dashboard.html",
        "display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;",
        "feedback-exec-summary-chip-row",
    ),
    (
        "app/templates/feedback_executive_summary_dashboard.html",
        "display:grid;gap:18px;align-content:start;",
        "feedback-exec-summary-col-stack-start",
    ),
    # assignment_recommendations.html
    (
        "app/templates/assignment_recommendations.html",
        "margin-top:14px",
        "assignment-rec-spacing-top-md",
    ),
    (
        "app/templates/assignment_recommendations.html",
        "margin-left:auto;",
        "assignment-rec-pill-align-end",
    ),
    (
        "app/templates/assignment_recommendations.html",
        "margin-left:8px",
        "assignment-rec-pill-inline-gap",
    ),
    # hr_personnel_lifecycle_center.html
    (
        "app/templates/hr_personnel_lifecycle_center.html",
        "display:flex;justify-content:space-between;gap:10px;align-items:center",
        "hr-lifecycle-row-between",
    ),
    ("app/templates/hr_personnel_lifecycle_center.html", "margin:0", "hr-lifecycle-heading-flush"),
    (
        "app/templates/hr_personnel_lifecycle_center.html",
        "grid-column:1/-1",
        "hr-lifecycle-field-full",
    ),
    # admin_ai_center.html
    (
        "app/templates/admin_ai_center.html",
        "margin-top:16px",
        "admin-ai-center-spacing-top-md",
    ),
    (
        "app/templates/admin_ai_center.html",
        "margin-top:14px",
        "admin-ai-center-spacing-top-sm",
    ),
    # feedback_meeting_detail.html
    (
        "app/templates/feedback_meeting_detail.html",
        "display:flex;align-items:center;justify-content:space-between;gap:12px;"
        "flex-wrap:wrap;padding:14px 16px;border:1px solid rgba(15,23,42,.08);"
        "border-radius:18px;background:#f8fafc;",
        "feedback-meeting-scope-bar",
    ),
    (
        "app/templates/feedback_meeting_detail.html",
        "margin-top:16px;",
        "feedback-meeting-spacing-top-md",
    ),
    (
        "app/templates/feedback_meeting_detail.html",
        "display:grid; gap:18px;",
        "feedback-meeting-main-grid",
    ),
    # performance_v2_phase1.html
    (
        "app/templates/performance_v2_phase1.html",
        "margin-top:10px;",
        "perf-v2-phase1-spacing-top-xs",
    ),
    (
        "app/templates/performance_v2_phase1.html",
        "margin-top:18px;",
        "perf-v2-phase1-spacing-top-sm",
    ),
    (
        "app/templates/performance_v2_phase1.html",
        "margin-bottom:10px;",
        "perf-v2-phase1-spacing-bottom-xs",
    ),
]


# Per-template, ONE (new_class, old_value) cifti -- kaynak koddan MANUEL olarak
# dogrulanmis sekilde HICBIR {% if %}/{% for %} blogunun ICINDE OLMAYAN, yani
# bos veri (bos liste/None secili donem vb.) ile bile HER ZAMAN render edilen
# bir konumdan secilmistir. Bolum 16'nin canli-render "yeni sinif govdede var"
# kontrolu icin kullanilir -- DECLARATION_MAPPING_SAMPLES'daki digger ornekler
# (for-loop/if icindeki, veri olmadan render edilmeyen elemanlar) bu amaç icin
# guvenilir DEGILDIR (bkz. bu dosyanin ilk yazilisinda bulunan gercek false-
# positive: bos test DB'sinde shortcut_rows/recommendation_rows/meeting_timeline/
# preview bos oldugu icin o elemanlar hic render edilmiyordu -- app'in bir
# HATASI degil, testin YANLIS varsayimiydi, duzeltildi).
UNCONDITIONAL_LIVE_CLASS_SAMPLE: dict[str, tuple[str, str]] = {
    "app/templates/communication/phase1_bulletin_form.html": (
        "bulletin-preset-panel",
        "padding:18px;background:#f8fafc;box-shadow:none;",
    ),
    "app/templates/feedback/quick_feedback.html": (
        "quick-feedback-panel-heading-lg",
        "font-size:1.04rem;",
    ),
    "app/templates/feedback_executive_summary_dashboard.html": (
        "feedback-exec-summary-scope-note",
        "color:#6b7280;font-size:.82rem;",
    ),
    "app/templates/assignment_recommendations.html": (
        "assignment-rec-spacing-top-md",
        "margin-top:14px",
    ),
    "app/templates/hr_personnel_lifecycle_center.html": (
        "hr-lifecycle-row-between",
        "display:flex;justify-content:space-between;gap:10px;align-items:center",
    ),
    "app/templates/admin_ai_center.html": (
        "admin-ai-center-spacing-top-md",
        "margin-top:16px",
    ),
    "app/templates/feedback_meeting_detail.html": (
        "feedback-meeting-scope-bar",
        "display:flex;align-items:center;justify-content:space-between;gap:12px;"
        "flex-wrap:wrap;padding:14px 16px;border:1px solid rgba(15,23,42,.08);"
        "border-radius:18px;background:#f8fafc;",
    ),
    "app/templates/performance_v2_phase1.html": (
        "perf-v2-phase1-spacing-top-xs",
        "margin-top:10px;",
    ),
}


def test_declaration_mapping_samples_cover_at_least_3_or_all_per_template() -> None:
    """'En az 3 (ya da daha azsa hepsi)' olcutu, HAM statik attribute
    sayisina (pre_wave -- birden fazla ozdes deger tek bir sinifa
    birlestirilmis olabilir, orn. admin_ai_center.html'de 6 statik attribute
    yalniz 2 FARKLI deklarasyona/sinifa indirgenmistir) degil, o sablonun
    yeni CSS dosyasinda tanimli DISTINCT sinif sayisina gore olculur --
    cunku orneklenebilecek "farkli deklarasyon" sayisi budur."""
    counts: dict[str, int] = {}
    sampled_classes: dict[str, set[str]] = {}
    for relative_path, _old, new_class in DECLARATION_MAPPING_SAMPLES:
        counts[relative_path] = counts.get(relative_path, 0) + 1
        sampled_classes.setdefault(relative_path, set()).add(new_class)
    for relative_path, meta in TARGET_TEMPLATES.items():
        css_stem = str(meta["css"])
        css_path = REPO_ROOT / "app" / "static" / "css" / f"{css_stem}.css"
        distinct_classes = len(set(_CSS_CLASS_SELECTOR_RE.findall(css_path.read_text(encoding="utf-8"))))
        expected_min = min(3, distinct_classes)
        actual = counts.get(relative_path, 0)
        actual_distinct = len(sampled_classes.get(relative_path, set()))
        assert actual >= expected_min, (
            f"{relative_path}: yalniz {actual} orneklem eslemesi var, en az "
            f"{expected_min} bekleniyordu (o sablonun CSS dosyasinda {distinct_classes} "
            "distinct sinif var)."
        )
        assert actual_distinct >= expected_min, (
            f"{relative_path}: yalniz {actual_distinct} FARKLI sinif orneklenmis, en az "
            f"{expected_min} farkli sinif bekleniyordu."
        )


@pytest.mark.parametrize(
    "relative_path,old_value,new_class",
    DECLARATION_MAPPING_SAMPLES,
    ids=[f"{p.split('/')[-1]}::{c}" for p, _v, c in DECLARATION_MAPPING_SAMPLES],
)
def test_old_inline_style_declarations_are_preserved_in_new_css_class(
    relative_path: str, old_value: str, new_class: str
) -> None:
    css_stem = str(TARGET_TEMPLATES[relative_path]["css"])
    css_path = REPO_ROOT / "app" / "static" / "css" / f"{css_stem}.css"
    css_text = css_path.read_text(encoding="utf-8")

    rule_match = re.search(
        r"\." + re.escape(new_class) + r"\s*\{([^}]*)\}", css_text
    )
    assert rule_match, f"{css_path} icinde '.{new_class} {{...}}' kurali bulunamadi."

    old_decls = _parse_declarations(old_value)
    new_decls = _parse_declarations(rule_match.group(1))
    assert old_decls == new_decls, (
        f"{relative_path} -> .{new_class}: eski deklarasyonlar {old_decls!r} ile "
        f"yeni CSS kurali {new_decls!r} birebir eslesmiyor."
    )


# ---------------------------------------------------------------------------
# 5) Her sablon kendi yeni CSS dosyasina bir <link rel="stylesheet"> ile
#    baglaniyor mu?
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_links_its_own_new_stylesheet(relative_path: str) -> None:
    css_stem = str(TARGET_TEMPLATES[relative_path]["css"])
    text = _read(relative_path)
    pattern = re.compile(_LINK_STYLESHEET_RE_PREFIX + re.escape(css_stem) + _LINK_STYLESHEET_RE_SUFFIX)
    assert pattern.search(text), (
        f"{relative_path} icinde 'css/{css_stem}.css' icin bir "
        "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='css/...') }}\"> "
        "etiketi bulunamadi."
    )
    css_path = REPO_ROOT / "app" / "static" / "css" / f"{css_stem}.css"
    assert css_path.is_file(), f"{css_path} bulunamadi."


# ---------------------------------------------------------------------------
# 6) Sablonda kullanilan (bu dalganin tanittigi) her class= sinifi, kendi
#    yeni CSS dosyasinda bir `.class-name { ... }` tanimina sahip mi?
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_new_semantic_classes_used_in_template_are_defined_in_its_own_css_file(
    relative_path: str,
) -> None:
    css_stem = str(TARGET_TEMPLATES[relative_path]["css"])
    css_path = REPO_ROOT / "app" / "static" / "css" / f"{css_stem}.css"
    css_text = css_path.read_text(encoding="utf-8")
    defined_classes = set(_CSS_CLASS_SELECTOR_RE.findall(css_text))
    assert defined_classes, f"{css_path} icinde hic '.class {{ }}' tanimi bulunamadi."

    template_text = _read(relative_path)
    used_classes: set[str] = set()
    for class_attr_value in _CLASS_ATTR_RE.findall(template_text):
        for token in class_attr_value.split():
            if "{{" in token or "{%" in token or "}}" in token or "%}" in token:
                continue
            used_classes.add(token)

    # Bu dalganin TANITTIGI (defined_classes icinde olan) siniflar, kullanildiklari
    # sablonda da MUTLAKA gecmeli (aksi halde CSS dosyasi olu/kullanilmayan kod
    # icerir -- ki bu olculebilir, esas kontrol budur).
    for class_name in defined_classes:
        assert class_name in used_classes, (
            f"{css_path} icinde tanimli '.{class_name}' sinifi {relative_path} "
            "icinde hicbir class=\"...\" attribute'unda kullanilmiyor."
        )


# ---------------------------------------------------------------------------
# 7) Sinif adi carpismasi: bu 8 yeni CSS dosyasindaki HICBIR sinif adi,
#    repodaki BASKA hicbir .css dosyasinda tanimli olmamali.
# ---------------------------------------------------------------------------


def _all_css_files() -> list[Path]:
    return sorted((REPO_ROOT / "app" / "static" / "css").rglob("*.css"))


def test_new_css_classes_do_not_collide_with_any_other_css_file_in_repo() -> None:
    new_css_paths = {
        REPO_ROOT / "app" / "static" / "css" / f"{meta['css']}.css" for meta in TARGET_TEMPLATES.values()
    }
    new_classes_by_file: dict[Path, set[str]] = {}
    for css_path in new_css_paths:
        text = css_path.read_text(encoding="utf-8")
        new_classes_by_file[css_path] = set(_CSS_CLASS_SELECTOR_RE.findall(text))

    all_new_classes: set[str] = set()
    for classes in new_classes_by_file.values():
        all_new_classes |= classes
    assert all_new_classes, "Style-2B'nin 8 yeni CSS dosyasinda hic sinif bulunamadi."

    collisions: dict[str, list[str]] = {}
    for css_path in _all_css_files():
        if css_path in new_css_paths:
            continue
        text = css_path.read_text(encoding="utf-8", errors="replace")
        other_classes = set(_CSS_CLASS_SELECTOR_RE.findall(text))
        hit = other_classes & all_new_classes
        for class_name in hit:
            collisions.setdefault(class_name, []).append(
                str(css_path.relative_to(REPO_ROOT))
            )
    assert collisions == {}, (
        f"Style-2B'nin yeni sinif adlari BASKA .css dosyalarinda da tanimli: {collisions!r}"
    )


# ---------------------------------------------------------------------------
# 8) 8 sablonun HICBIRINDE dinamik (Jinja icerikli) style="..." YOK -- ne
#    dalga oncesinde (649f4530) ne de simdi. Bu, gercek bir regresyon
#    kontrolu: dalga oncesinde de 0 oldugunu ayrica dogrulayarak, "zaten
#    hicbir zaman yoktu" varsayimini KOR biçimde kabul etmez.
# ---------------------------------------------------------------------------


def _dynamic_style_attr_count(text: str) -> int:
    count = 0
    for value in _STYLE_ATTR_RE.findall(text):
        if "{{" in value or "{%" in value:
            count += 1
    return count


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_had_and_still_has_zero_dynamic_style_attribute(
    relative_path: str,
) -> None:
    before_dynamic = _dynamic_style_attr_count(_git_show(PRE_WAVE_REF, relative_path))
    after_dynamic = _dynamic_style_attr_count(_read(relative_path))
    assert before_dynamic == 0, (
        f"{relative_path}: {PRE_WAVE_REF} aninda BILE {before_dynamic} dinamik style "
        "attribute varmis -- dosya basi varsayim ('hic yoktu') yanlis."
    )
    assert after_dynamic == 0, (
        f"{relative_path}: guncel halde {after_dynamic} dinamik style attribute var -- "
        "Style-2B (ya da sonraki bir dalga) yeni bir dinamik style eklemis olabilir."
    )


# ---------------------------------------------------------------------------
# 9) <style> blok sayisi, dalga oncesi (649f4530) ile guncel arasinda AYNI.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_style_block_count_is_unchanged_since_pre_wave(
    relative_path: str,
) -> None:
    before_blocks = len(_STYLE_BLOCK_RE.findall(_git_show(PRE_WAVE_REF, relative_path)))
    after_blocks = len(_STYLE_BLOCK_RE.findall(_read(relative_path)))
    assert before_blocks == after_blocks, (
        f"{relative_path}: <style> blok sayisi degisti ({before_blocks} -> {after_blocks})."
    )


# ---------------------------------------------------------------------------
# 10) Form/CSRF byte-identical kontrolu -- phase1_bulletin_form.html ve
#     feedback_executive_summary_dashboard.html.
# ---------------------------------------------------------------------------

FORM_CSRF_CHECK_TEMPLATES = (
    "app/templates/communication/phase1_bulletin_form.html",
    "app/templates/feedback_executive_summary_dashboard.html",
)

_FORM_OPEN_TAG_RE = re.compile(r"<form\b[^>]*>")
_CSRF_HIDDEN_INPUT_RE = re.compile(r'<input[^>]*name="csrf_token"[^>]*>')


def _extract_attr(tag_text: str, attr_name: str) -> str | None:
    match = re.search(rf'{attr_name}\s*=\s*"([^"]*)"', tag_text)
    return match.group(1) if match else None


@pytest.mark.parametrize("relative_path", FORM_CSRF_CHECK_TEMPLATES)
def test_form_tag_and_csrf_hidden_input_are_byte_identical_before_and_after(
    relative_path: str,
) -> None:
    """Formun `method`/`action` attribute DEGERLERI (tam tag metni DEGIL --
    cunku feedback_executive_summary_dashboard.html'deki ikinci <form>
    etiketinin KENDI style="..." attribute'u da bu dalga tarafindan bilerek
    class="..."'e tasindi, bu yuzden TAM tag metni artik byte-identical
    olamaz; gorev tanimindaki asil niyet method/action'in DEGISMEMESI) ve
    CSRF hidden input satiri, dalga oncesi (649f4530) ile guncel arasinda
    AYNI kalmali. Form sayisi da degismemis olmali."""
    before_text = _git_show(PRE_WAVE_REF, relative_path)
    after_text = _read(relative_path)

    before_forms = _FORM_OPEN_TAG_RE.findall(before_text)
    after_forms = _FORM_OPEN_TAG_RE.findall(after_text)
    assert before_forms, f"{relative_path}: {PRE_WAVE_REF} aninda <form ...> etiketi bulunamadi."
    assert len(before_forms) == len(after_forms), (
        f"{relative_path}: <form ...> etiket SAYISI degisti: "
        f"{len(before_forms)} -> {len(after_forms)}"
    )
    for index, (before_tag, after_tag) in enumerate(zip(before_forms, after_forms, strict=True)):
        before_method = _extract_attr(before_tag, "method")
        after_method = _extract_attr(after_tag, "method")
        before_action = _extract_attr(before_tag, "action")
        after_action = _extract_attr(after_tag, "action")
        assert before_method == after_method, (
            f"{relative_path}: form[{index}] method attribute degisti: "
            f"{before_method!r} -> {after_method!r}"
        )
        assert before_action == after_action, (
            f"{relative_path}: form[{index}] action attribute degisti (ya da yoklugu "
            f"degisti): {before_action!r} -> {after_action!r}"
        )

    before_csrf = _CSRF_HIDDEN_INPUT_RE.findall(before_text)
    after_csrf = _CSRF_HIDDEN_INPUT_RE.findall(after_text)
    assert before_csrf, f"{relative_path}: {PRE_WAVE_REF} aninda csrf_token hidden input bulunamadi."
    assert before_csrf == after_csrf, (
        f"{relative_path}: csrf_token hidden input(lar) degismis:\n"
        f"  once: {before_csrf!r}\n  simdi: {after_csrf!r}"
    )


# ---------------------------------------------------------------------------
# 11) Inline event-handler (on*=) sayisi -- bu 8 sablon icinde 0.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_has_zero_inline_event_handlers(relative_path: str) -> None:
    matches = _INLINE_EVENT_ATTR_RE.findall(_read(relative_path))
    assert matches == [], f"{relative_path} icinde inline event-handler bulundu: {matches!r}"


# ---------------------------------------------------------------------------
# 12) javascript: URL sayisi -- bu 8 sablon icinde 0.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", sorted(TARGET_TEMPLATES))
def test_target_template_has_zero_javascript_url(relative_path: str) -> None:
    matches = _JS_HREF_SRC_RE.findall(_read(relative_path))
    assert matches == [], f"{relative_path} icinde javascript: URL bulundu: {matches!r}"


# ---------------------------------------------------------------------------
# 13) CSP header'inin uc style direktifi Style-1'in son durumuyla birebir
#     ayni, hicbirinde nonce- tokeni yok (Style-2A ile ayni wave-agnostik
#     mantik -- bkz. test_csp_style2a_repo_wide_contract.py bolum 4).
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
# 14) PWA offline sayfalari -- bu dalga tarafindan DOKUNULMAMIS olmali
#     (649f4530 ile byte-identical).
# ---------------------------------------------------------------------------

PWA_OFFLINE_FILES = (
    "app/static/pwa/offline.html",
    "app/static/pwa/offline-static.html",
)


@pytest.mark.parametrize("relative_path", PWA_OFFLINE_FILES)
def test_pwa_offline_html_is_byte_identical_to_pre_wave_state(relative_path: str) -> None:
    before_text = _git_show(PRE_WAVE_REF, relative_path)
    after_text = _read(relative_path)
    assert before_text == after_text, (
        f"{relative_path} {PRE_WAVE_REF}'dan bu yana degismis -- Style-2B bu dosyaya "
        "DOKUNMAMALIYDI."
    )


# ---------------------------------------------------------------------------
# 15/16) Gercek route + kimlik dogrulamali test client kontrolleri.
#
# feedback_meeting_detail rotasi GERCEK bir FeedbackMeeting kaydi gerektirir;
# bu da GERCEK bir PerformancePeriod + PerformanceEvaluation + FeedbackRequest
# zincirini (modeller FK ile birbirine bagli) sart kosar -- bu dosya bu
# zinciri, model tanimlarindan (app/models/performance_models.py,
# app/models/communication_models.py) okunan MINIMAL zorunlu alanlarla
# GERCEKTEN kurar (sahte/atlanmis bir fixture DEGIL).
#
# feedback_executive_summary_dashboard rotasi CANLI dongude YOKTUR -- bkz.
# dosya basi docstring (pre-existing 500 hatasi); kendi ozel testi vardir.
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "csp_style2b" / "test_dbs"
_SAFE_RENDER_FALLBACK_MARKERS = ("şablonunda hata var", "şablonu hatalı")
_BASE_TEMPLATE_MARKER = "topbarNotificationBadge"


@pytest.fixture(scope="module")
def style2b_env(request):
    """Izole, gecici SQLite DB'li bagimsiz bir Flask app + admin kullanici +
    (feedback_meeting_detail icin) gercek bir geri bildirim gorusme zinciri +
    giris yapilmis test client kurar. Wave2/phase13b/Style-2A dosyalarindaki
    KURULU desenle ayni (bkz. test_csp_style2a_repo_wide_contract.py::
    style2a_env). Module-scoped: rota testleri arasinda TEK app kurulumu
    paylasilir, ama bu dosyanin DISINDAKI hicbir teste sizmaz (mp.undo())."""
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-csp-style2b-contract-min-length-ok")
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
    mp.setenv("FILE_CENTER_ENABLED", "true")

    from app import create_app
    from config import Config

    mp.setattr(Config, "APP_ENV", "testing")
    mp.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    mp.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    request.addfinalizer(lambda: release_sqlite_app(app))
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db
    from app.models import User

    with app.app_context():
        db.create_all()
        user = User(
            sicil_no="style2b001",
            email="style2b.contract@ktb.gov.tr",
            ad="Style2B",
            soyad="Kontrat",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("Style2BTestContractKey1!")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        # feedback_meeting_detail icin gercek FK zinciri: PerformancePeriod ->
        # PerformanceEvaluation -> FeedbackRequest -> FeedbackMeeting. Admin
        # kullanicinin kendisi hem employee_id hem manager_id -- boylece
        # rotadaki erisim kontrolu (current_user.id in allowed_ids) gercekten
        # saglanir, sahte bir bypass degil.
        from datetime import date, time

        from app.models.communication_models import FeedbackMeeting, FeedbackRequest
        from app.models.performance_models import PerformanceEvaluation, PerformancePeriod

        period = PerformancePeriod(
            title="Style2B Kontrat Donemi",
            period_type="yillik",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        db.session.add(period)
        db.session.commit()

        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=user_id)
        db.session.add(evaluation)
        db.session.commit()

        feedback_request = FeedbackRequest(
            evaluation_id=evaluation.id,
            period_id=period.id,
            employee_id=user_id,
            reason="Style2B kontrat testi icin sahte olmayan gercek satir.",
            status="bekliyor",
        )
        db.session.add(feedback_request)
        db.session.commit()

        meeting = FeedbackMeeting(
            feedback_request_id=feedback_request.id,
            employee_id=user_id,
            manager_id=user_id,
            meeting_date=date(2026, 8, 10),
            meeting_start=time(10, 0),
            meeting_end=time(10, 30),
        )
        db.session.add(meeting)
        db.session.commit()
        meeting_id = meeting.id

    client = app.test_client()
    login_response = client.post(
        "/login",
        data={"sicil_or_email": "style2b001", "password": "Style2BTestContractKey1!"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302, (
        f"Test admin kullanicisi ile giris basarisiz oldu: status={login_response.status_code}"
    )
    assert "/login" not in (login_response.headers.get("Location") or ""), (
        "Giris sonrasi hala /login'e yonlendiriliyor -- kimlik dogrulama basarisiz olmus olabilir."
    )

    yield client, meeting_id

    mp.undo()


def _live_route_for(relative_path: str, meeting_id: int) -> str:
    if relative_path == "app/templates/feedback_meeting_detail.html":
        return f"/performance/feedback-meetings/{meeting_id}"
    return LIVE_RENDER_ROUTES[relative_path]


@pytest.mark.parametrize("relative_path", sorted(LIVE_RENDER_ROUTES))
def test_target_template_route_renders_successfully_when_authenticated(
    style2b_env, relative_path: str
) -> None:
    client, meeting_id = style2b_env
    route = _live_route_for(relative_path, meeting_id)
    response = client.get(route, follow_redirects=True)
    assert response.status_code == 200, (
        f"{route} ({relative_path} rotasi) beklenmedik durum kodu dondurdu: "
        f"{response.status_code}"
    )
    body = response.get_data(as_text=True)
    assert _BASE_TEMPLATE_MARKER in body, (
        f"{route} yanitinda base.html'in kendi '{_BASE_TEMPLATE_MARKER}' isaretcisi "
        "bulunamadi -- tam sayfa render gerceklesmemis olabilir."
    )
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body, (
            f"{route} yaniti safe_render() exception-fallback stub'u iceriyor gibi "
            f"gorunuyor ('{marker}' bulundu) -- gercek sablon render edilmemis olabilir."
        )


@pytest.mark.parametrize("relative_path", sorted(LIVE_RENDER_ROUTES))
def test_target_template_route_response_contains_new_css_classes_and_not_old_removed_style_values(
    style2b_env, relative_path: str
) -> None:
    """16) Kismi/kirik migrasyon regresyon kontrolu: yaniti govdesinde bu
    dalganin TANITTIGI, KOSULSUZ render edilen (bos test verisiyle bile her
    zaman goruntulenen -- bkz. UNCONDITIONAL_LIVE_CLASS_SAMPLE'in yukaridaki
    aciklamasi) bir yeni sinif GERCEKTEN var mi, VE ona karsilik gelen
    kaldirilmis eski inline style degeri ARTIK YOK mu? (base.html'in KENDI
    style="..." attribute'lari kapsam disi -- yalniz bu sablona ozgu,
    kaldirilmis DEGERLER kontrol edilir, "style=" genel metni degil).

    NOT: burada TUM CSS-tanimli siniflarin govdede bulunmasi ARANMAZ --
    bircok sinif ({% for %} ile veri satirlarina, {% if %} ile secili
    donem/gorusme gecmisi gibi kosullu bloklara bagli elemanlarda) bos test
    DB'sinde hic render edilmez; bu App'in bir HATASI degildir (production'da
    gercek veriyle render edilirler), bu dosyanin ilk yazilisinda bu ayrim
    yapilmadigi icin yanlis-pozitif ("EKSIK sinif") bulgulari alinmis ve
    duzeltilmistir."""
    client, meeting_id = style2b_env
    route = _live_route_for(relative_path, meeting_id)
    response = client.get(route, follow_redirects=True)
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    new_class, old_value = UNCONDITIONAL_LIVE_CLASS_SAMPLE[relative_path]
    assert new_class in body, (
        f"{route} yanitinda kosulsuz render edilmesi gereken '.{new_class}' sinifi "
        "govdede bulunamadi."
    )
    leftover_attr = f'style="{old_value}"'
    assert leftover_attr not in body, (
        f"{route} yanitinda kaldirilmis olmasi gereken eski inline style degeri hala "
        f"mevcut: {leftover_attr!r}"
    )


def test_feedback_executive_summary_dashboard_route_preset_kwarg_collision_bug_is_fixed(
    style2b_env,
) -> None:
    """BYS360 PERFORMANS BUGFIX KOORDINATOR NOTU: bu test eskiden -- dogru
    sekilde -- bir 500 durumunu kilitliyordu (bkz. git history/bu dosyanin
    onceki hali): `feedback_executive_summary_dashboard` view fonksiyonu
    (Style-2B'nin KENDISI DOKUNMAMIS oldugu app/performance/
    engagement_feedback_routes.py icinde) admin olarak GET edildiginde 500
    donuyordu -- `build_feedback_executive_summary()`'in dondurdugu dict
    kendi 'preset' anahtarini icerdigi icin `safe_render(..., preset=preset,
    **dashboard)` cagrisinda CIFT deger hatasi olusuyordu.

    O hata, ayri bir bugfix dalgasinda, route dosyasindaki fazladan
    `preset=preset` kwarg'i kaldirilarak duzeltildi (`dashboard["preset"]`
    zaten ayni degeri **dashboard uzerinden tasidigi icin). Kapsamli
    regresyon kanit/testleri artik
    tests/performance/test_feedback_executive_summary_preset_context_regression.py
    dosyasinda; bu test SADECE Style-2B'nin kendi companion contract
    dosyasinda bu rotanin artik gercekten CALISTIGINI (200) dogrulayan hafif
    bir kontrol olarak kalir -- LIVE_RENDER_ROUTES/route disi birakma
    mantigi da bu yuzden kaldirildi (rota artik genel donguye dahil)."""
    client, _meeting_id = style2b_env
    response = client.get("/performance/feedback-executive-summary", follow_redirects=True)
    assert response.status_code == 200, (
        f"feedback_executive_summary_dashboard rotasi 200 DONMEDI (bulunan: "
        f"{response.status_code}) -- 'preset' cift-kwarg TypeError'i geri gelmis "
        "olabilir."
    )


STYLE2B_CLOSURE_REF = "54ccf908c937bd06d0146e11b16ecd71dd569c51"


def test_engagement_feedback_routes_file_was_untouched_by_style2b_itself() -> None:
    """feedback_executive_summary_dashboard'daki 500 hatasinin kok nedeni
    Style-2B'nin DOKUNMADIGI bir dosyadaydi (app/performance/
    engagement_feedback_routes.py) -- bu, Style-2B'nin KENDI kapanis commit'i
    (STYLE2B_CLOSURE_REF) ile onun bir onceki dalganin kapanis commit'i
    (PRE_WAVE_REF) arasindaki SABIT/tarihsel `git diff`'in bu dosya icin BOS
    oldugunu dogrulayarak kanitlanir.

    BYS360 PERFORMANS BUGFIX KOORDINATOR NOTU: bu test ONCEDEN calisan
    worktree'nin GUNCEL/commit'lenmemis diff'ine (`git diff` -- HEAD'e karsi)
    bakiyordu; bu, Style-2B'nin test_csp_style2a_repo_wide_contract.py'de
    tam olarak duzelttigi ayni ileri-uyumsuzluk hatasini tasiyordu -- bir
    SONRAKI dalga (burada: ayri, mesru bir bugfix dalgasi, preset kwarg
    cakismasini duzelten) bu dosyaya dokunur dokunmaz FAIL verecekti. Artik
    SABIT bir tarihsel commit araligina (649f4530..54ccf908) kilitlendi: bu,
    Style-2B'nin KENDI committinin bu dosyaya dokunmadigini SONSUZA KADAR
    dogru kalacak sekilde kanitlar -- sonraki (bu dahil) hicbir dalgadan
    etkilenmez."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", f"{PRE_WAVE_REF}..{STYLE2B_CLOSURE_REF}", "--", "app/performance/engagement_feedback_routes.py"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"git diff basarisiz oldu (exit={result.returncode}).")
    assert result.stdout == "", (
        "Style-2B'nin KENDI kapanis commit'i (649f4530..54ccf908) "
        "app/performance/engagement_feedback_routes.py'yi degistirmis gorunuyor -- "
        "dosya basi docstring'deki 'Style-2B bu dosyaya dokunmadi' iddiasi yanlis "
        f"olabilir, yeniden degerlendirin:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# 17) Bu dosyanin KENDISI hicbir uygulama/sablon/CSS kaynagina YAZMIYOR --
#     yalniz okuma + izole kendi gecici test DB'sine yaziyor.
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
        f"Bu dosyada beklenmedik dosya-yazma/degistirme cagrisi izi bulundu: {hits!r}"
    )
