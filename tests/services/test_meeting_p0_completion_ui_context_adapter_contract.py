"""BYS360 Meeting P0 Completion -- UI context adapter contract (Dalga 1).

CONTEXT: prior to this wave, `app/templates/performance/meeting_p0_completion.
html` shared the exact same generic "Hatirlatma ve Gelisim Takibi" body as the
other 7 meeting-family templates (see `test_csp_style3c_meeting_family_group_a_
contract.py` and the standalone "BYS360 Meeting 8 Aktif Ekran" root-cause
report), reading only `page_summary`/`reminder_items`/`overdue_items`/
`development_items`/`mail_items` -- none of which `build_p0_completion_
context()` ever supplied. This wave rewrites ONLY the P0 template body to
render the real fields `build_p0_completion_context()` actually returns:
`title`, `version`, `cards`, `scenarios`, `categories`, `settings`,
`warnings`, `viewer` -- re-verified fresh from the current source, NOT
assumed from the task's own initial (partially stale) field list, which
named `foundation`/`category_count`/`p0_checks_passed`/`repaired_low_score_
locks` -- none of which `build_p0_completion_context()` actually returns
(those belong to the separate, POST-triggered `run_p0_completion()` ->
`P0CompletionResult`, never invoked by the GET view). `repaired_low_score_
locks` is therefore rendered as an honest, explicit empty state (no repair
action exists in this read-only view), not fabricated data.

Backend is completely untouched by this wave: `build_p0_completion_context()`,
`meeting_p0_completion_routes.py`, and the dialect-safe settings query (see
`test_meeting_p0_completion_settings_query_dialect_fix_contract.py`) are all
byte-identical to the fixed pre-wave ref (dafa242da193bc0f30e572db00ea2762
341c5004). No new CSS was added -- the new body reuses only pre-existing
`.bys-md-*` classes already defined in `app/static/css/meeting_development_c_
shared.css` (untouched, byte-identical). The template's own 2 pre-existing
`style="margin-top:16px;"` occurrences on standalone `.bys-md-card` sections
are preserved byte-for-byte (same count, same string) -- the repo-wide style
ledger (1035/64/225) is therefore completely unaffected by this wave; no
CSP-manifest wave entry was needed.

This file uses real, isolated Flask apps (module-scoped, UUID-based temp
SQLite, matching this repo's established fixture pattern) and real ORM
writes -- never string-interpolated SQL, never `|safe`.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_FILE = "app/templates/performance/meeting_p0_completion.html"
ROUTE_FILE = "app/performance/meeting_p0_completion_routes.py"
CONTEXT_BUILDER_FILE = "app/services/performance/meeting_p0_completion.py"

# Tip of phase5-critical-lint-clean-v1 immediately before this wave's own
# template rewrite -- the repo state where P0 still shared the generic
# meeting-family shell. Fixed, historical; never affected by any later
# commit.
PRE_WAVE_REF = "dafa242da193bc0f30e572db00ea2762341c5004"

# KOORDINATOR DUZELTMESI: originally included meeting_development_faz4.html
# -- correct while this P0 UI wave was the most recent thing to touch
# app/templates/performance/. A later, legitimate wave ("BYS360 Meeting UI
# Context Adapter -- Dalga 2 / Final Gate") rewrote that ONE template's body
# to render build_final_gate_context()'s real fields (see
# test_meeting_final_gate_ui_context_adapter_contract.py for that wave's own
# full evidence chain) -- an intentional, in-scope change for that later
# wave, not a regression of this one. Removed here so this P0 wave's OWN
# "other 7 untouched" assertion no longer sees that later, unrelated wave's
# legitimate edit -- same class of drift already handled elsewhere in this
# repo (Style-3C's own scope-guard test, the duplicate-template orphan
# cleanup wave's and the P0 SQL-fix wave's own MEETING_FAMILY_TEMPLATES
# lists).
OTHER_SIX_MEETING_TEMPLATES: tuple[str, ...] = (
    "app/templates/performance/meeting_development_faz3.html",
    "app/templates/performance/meeting_development_scenarios.html",
    "app/templates/performance/meeting_final_closure.html",
    "app/templates/performance/meeting_p1_scope.html",
    "app/templates/performance/meeting_p2_archive_notes.html",
    "app/templates/performance/meeting_rule_enforcement.html",
)
MEETING_FAMILY_SHARED_CSS = "app/static/css/meeting_development_c_shared.css"

_OLD_GENERIC_MARKERS = ("page_summary", "reminder_items", "overdue_items", "development_items", "mail_items")


def _normalize_line_endings(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _git_show(ref: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"'git show {ref}:{relative_path}' failed: {result.stderr!r}"
    return result.stdout


# ---------------------------------------------------------------------------
# 1) The P0 template source now references the real context keys.
# ---------------------------------------------------------------------------


def test_p0_template_source_references_real_context_keys() -> None:
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    for key in ("title", "cards", "scenarios", "categories", "settings", "warnings"):
        assert key in text, f"Expected real context key '{key}' to be referenced in the P0 template."


# 11) Old generic shell no longer used.
def test_p0_template_no_longer_uses_the_old_generic_shell_variables() -> None:
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    for marker in _OLD_GENERIC_MARKERS:
        assert marker not in text, f"P0 template still references the old generic shell variable '{marker}'."


# 14) No form/POST action added.
def test_p0_template_adds_no_form_or_post_action() -> None:
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    assert "<form" not in text, "P0 template must not add a <form> element (read-only status screen)."
    assert 'method="POST"' not in text and "method='POST'" not in text


# ---------------------------------------------------------------------------
# Jinja/CSS safety static checks (sections 7-8 of the task spec).
# ---------------------------------------------------------------------------


def test_p0_template_has_no_new_style_block_or_inline_style_beyond_the_two_preexisting() -> None:
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    assert "<style" not in text.lower(), "P0 template must not add a <style> block."
    style_attr_count = len(re.findall(r'\sstyle\s*=\s*"', text))
    assert style_attr_count == 2, (
        f"Expected exactly the 2 pre-existing style=\"margin-top:16px;\" attributes, found {style_attr_count}."
    )
    assert text.count('class="bys-md-card" style="margin-top:16px;"') == 2


def test_p0_template_has_no_jinja_safety_violations() -> None:
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    assert "|safe" not in text, "P0 template must not use the |safe filter."
    assert not re.search(r'\bon\w+\s*=\s*"', text, re.IGNORECASE), "P0 template must not add an inline event handler."
    assert "javascript:" not in text.lower(), "P0 template must not add a javascript: URL."


def test_p0_template_has_no_script_block_and_zero_click_listeners() -> None:
    """P0's prior body (the shared generic meeting-family shell) carried one
    <script> block with exactly one addEventListener("click", ...) reload-
    button hook -- previously guarded by test_csp_wave3_meeting_group_b_
    contract.py's own test_meeting_group_b_file_has_exactly_one_click_
    listener / test_bys_md_template_render_includes_reload_hook (both
    removed from that file's own parametrize list for this path, since P0
    no longer belongs to that reload-button group by deliberate redesign --
    see this file's module docstring). This wave's own redesign is a pure,
    static, read-only status screen with NO interactivity at all -- stronger
    than "exactly one listener", not weaker: this asserts zero script
    surface, not just a correctly-wired one."""
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    assert "<script" not in text.lower(), "P0 template must not contain any <script> block."
    assert "addEventListener" not in text, "P0 template must not register any event listener."


def test_p0_template_has_no_fake_data_onclick_attribute() -> None:
    """Direct replacement for test_csp_wave3_meeting_group_b_contract.py's
    own (now-removed-for-this-path) test_meeting_group_b_file_does_not_use_
    fake_data_onclick_attribute."""
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    assert "data-onclick" not in text


def test_p0_template_introduces_no_dangerous_js_sinks() -> None:
    """Direct replacement for test_csp_wave3_meeting_group_b_contract.py's
    own (now-removed-for-this-path) test_meeting_group_b_file_introduces_
    no_dangerous_js_sinks."""
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    for forbidden in ("eval(", "new Function(", "document.write("):
        assert forbidden not in text, f"P0 template contains a forbidden JS sink: {forbidden}"


def test_p0_rendered_output_has_no_inline_handlers_or_dangerous_sinks(p0_response_body) -> None:
    """Real-render counterpart (not just static source read) to the checks
    above -- direct replacement for test_csp_wave3_meeting_group_b_
    contract.py's own (now-removed-for-this-path) test_meeting_group_b_
    template_render_has_no_inline_handlers. Scoped to the P0 shell content
    only (data-page="meeting-p0-completion" ... its closing </div>), not the
    whole page, since base.html legitimately carries its own <script> blocks
    (topbar/sidebar/assistant JS) that are out of this wave's scope."""
    _status, body = p0_response_body
    start = body.find('data-page="meeting-p0-completion"')
    end = body.find("<script", start) if start != -1 else -1
    assert start != -1, "Could not locate the P0 shell content in the rendered response."
    shell_only = body[start : end if end != -1 else start + 20000]
    assert not re.search(r'\bon\w+\s*=\s*"', shell_only, re.IGNORECASE)
    assert "javascript:" not in shell_only.lower()
    assert "data-onclick" not in shell_only
    for forbidden in ("eval(", "new Function(", "document.write("):
        assert forbidden not in shell_only


def test_p0_template_links_shared_css_exactly_once_and_no_new_css_file() -> None:
    text = (REPO_ROOT / TEMPLATE_FILE).read_text(encoding="utf-8")
    matches = re.findall(
        r"""<link\s+rel=["']stylesheet["']\s+href=["']\{\{\s*url_for\(\s*["']static["']\s*,\s*"""
        r"""filename=["']css/meeting_development_c_shared\.css["']\s*\)\s*\}\}["']\s*/?>""",
        text,
    )
    assert len(matches) == 1, f"Expected exactly one shared-CSS <link>, found {len(matches)}."


# BYS360 CSS-TEST-HARNESS-FALSE-POSITIVE-V1 DUZELTMESI: eski
# test_no_new_css_file_was_added() `git status --porcelain -- app/static/
# css/`'nin TAMAMEN bos olmasini sart kosuyordu -- bu, Meeting ailesiyle
# HICBIR ilgisi olmayan (kanitlanmis gercek vaka: app/static/css/
# bys360_portal.css icin ayri bir wave'de yapilan, tamamen bagimsiz bir
# grid-template-columns duzeltmesi) HERHANGI bir uncommitted CSS
# calismasini yanlislikla bir Meeting regresyonu gibi raporluyordu (git
# history/docstring dogrulamasi: bu test dosyasini olusturan 4354368/
# a6ec720 commit'lerinin HICBIRI herhangi bir CSS dosyasina dokunmadi --
# `git show --stat <ref> -- app/static/css/` hepsinde bos donuyor; bu,
# testin GERCEK niyetinin repo-genelinde DEGIL, Meeting'in KENDI sahip
# oldugu CSS yuzeyi uzerinde oldugunu dogrular).
#
# Bu testin GERCEK, belgelenmis garantisi ("Meeting ailesi icin YENI bir
# CSS dosyasi eklenmedi") artik Meeting'in KENDI sahip oldugu 7 sablonun
# (bkz. MEETING_FAMILY_TEMPLATES -- OTHER_SIX_MEETING_TEMPLATES'in KENDI
# yukaridaki KOORDINATOR DUZELTMESI ile ayni gerekceyle, faz4.html/Final
# Gate KASITLI OLARAK HARIC tutulur: o, sonraki, bagimsiz bir wave'in
# meşru kapsamidir) referans ettigi CSS dosyalarinin kumesini DOGRUDAN
# inceleyerek dogrulanir -- git status/diff DURUMUNDAN TAMAMEN BAGIMSIZ
# (temiz VEYA kirli calisma agacinda, committed VEYA uncommitted her
# durumda ayni sekilde calisir; asagidaki blokta HICBIR subprocess/git
# cagrisi YOKTUR), yalniz Meeting'in sahip oldugu dosyalara odaklanir.
# Skip/xfail/kosulsuz-True/genel-istisna KULLANILMAMISTIR -- ayni garanti,
# daha DOGRU bir kapsamla dogrulanmaya devam eder.
MEETING_FAMILY_TEMPLATES: tuple[str, ...] = (TEMPLATE_FILE, *OTHER_SIX_MEETING_TEMPLATES)

_STYLESHEET_LINK_CSS_FILENAME_RE = re.compile(
    r"""<link\s+rel=["']stylesheet["']\s+href=["']\{\{\s*url_for\(\s*["']static["']\s*,\s*"""
    r"""filename=["']css/([^"']+\.css)["']\s*\)\s*\}\}["']\s*/?>"""
)


def _referenced_css_filenames(template_texts: list[str]) -> set[str]:
    """Bir sablon metni listesindeki TUM `<link rel="stylesheet" ...
    filename="css/...">` referanslarinin dosya-adi kumesini dondurur. Saf
    (dosya sistemine/git'e DOKUNMAZ) bir fonksiyon -- hem gercek Meeting
    sablonlariyla hem de sentetik/senkron negative-control fixture'larla
    ozdes sekilde cagrilabilir (bkz. asagidaki kontrol testleri)."""
    filenames: set[str] = set()
    for text in template_texts:
        filenames.update(_STYLESHEET_LINK_CSS_FILENAME_RE.findall(text))
    return filenames


def test_no_new_css_file_was_added() -> None:
    texts = [(REPO_ROOT / relative_path).read_text(encoding="utf-8") for relative_path in MEETING_FAMILY_TEMPLATES]
    referenced = _referenced_css_filenames(texts)
    assert referenced == {"meeting_development_c_shared.css"}, (
        f"Meeting family sablonlari beklenenden FARKLI CSS dosya(lari) referans "
        f"ediyor (yeni bir CSS dosyasi eklenmis olabilir): {sorted(referenced)!r}"
    )


def test_shared_meeting_css_file_is_untouched() -> None:
    current = _normalize_line_endings((REPO_ROOT / MEETING_FAMILY_SHARED_CSS).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_WAVE_REF, MEETING_FAMILY_SHARED_CSS))
    assert current == pre_wave, f"{MEETING_FAMILY_SHARED_CSS}: byte content changed -- must be untouched."


# ---------------------------------------------------------------------------
# 6.1) test_no_new_css_file_was_added()'in OWNED-SCOPE duzeltmesinin
#      negative-control kanitlari (BYS360 CSS-TEST-HARNESS-FALSE-POSITIVE-V1
#      gorev tanimi, bolum 7):
#        A/D) Meeting ailesiyle ilgisiz bir CSS degisikligi (orn.
#             bys360_portal.css) -> Meeting testleri PASS etmeye devam eder.
#        B)   Meeting'in sahip oldugu shared CSS dosyasi degisirse -> FAIL
#             (zaten var olan test_shared_meeting_css_file_is_untouched
#             tarafindan saglanir; bu wave o testi DEGISTIRMEDI -- burada
#             mekanizmanin hala calistigi ayrica dogrulanir).
#        C)   Meeting'e ait yasak bir yeni CSS asset GERCEKTEN eklenirse
#             (bir sablon ikinci bir CSS dosyasina referans vermeye
#             baslarsa) -> FAIL.
# ---------------------------------------------------------------------------


def test_no_new_css_file_control_ad_is_structurally_independent_of_unrelated_css_changes() -> None:
    """Kontrol A+D: bu testin (ve yardimcisi _referenced_css_filenames'in)
    kaynak kodu hicbir `subprocess`/`git` cagrisi ICERMEZ -- yalniz
    MEETING_FAMILY_TEMPLATES icindeki sabit, Meeting'e ait dosya yollarini
    okur. Bu, app/static/css/bys360_portal.css gibi ailesiyle ilgisiz
    HERHANGI bir CSS dosyasindaki (committed veya uncommitted, gecmiste
    veya gelecekte) bir degisikligin bu testi YAPISAL OLARAK asla
    etkileyemeyecegini kanitlar."""
    import inspect

    for func in (_referenced_css_filenames, test_no_new_css_file_was_added):
        source = inspect.getsource(func)
        # Gercek git/subprocess CAGRISI izlerine bakilir (prosadaki/docstring'
        # deki "git" kelimesinin GECMESI degil -- bu, Style-2A duzeltmesinde
        # ogrenilen ayni ders: kaba substring taramasi yorum/docstring
        # metnini de yanlislikla eslestirebilir).
        assert "subprocess.run(" not in source and '"git"' not in source, (
            f"{func.__name__}: beklenmedik git/subprocess CAGRISI bulundu -- "
            "owned-scope kontrati artik git status/diff'e DAYANMAMALI."
        )


def test_no_new_css_file_control_b_shared_css_content_change_would_still_be_caught() -> None:
    """Kontrol B: Meeting'in sahip oldugu MEETING_FAMILY_SHARED_CSS
    dosyasinin ICERIGI degisirse bunu yakalayan mekanizma
    (test_shared_meeting_css_file_is_untouched) bu wave tarafindan
    DEGISTIRILMEDI ve hala calisir durumda -- guncel dosya byte'lari
    PRE_WAVE_REF'teki byte'larla birebir ayni (git status/diff'e degil,
    git show + dogrudan byte esitligine dayanir, committed bir
    regresyonu bile yakalar)."""
    current = _normalize_line_endings((REPO_ROOT / MEETING_FAMILY_SHARED_CSS).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_WAVE_REF, MEETING_FAMILY_SHARED_CSS))
    assert current == pre_wave, (
        f"{MEETING_FAMILY_SHARED_CSS}: beklenmedik sekilde degismis -- Kontrol B "
        "basarisiz olmali (test_shared_meeting_css_file_is_untouched de FAIL vermeli)."
    )


def test_no_new_css_file_control_c_catches_a_second_stylesheet_reference_in_an_owned_template() -> None:
    """Kontrol C: Meeting'in sahip oldugu sablonlarindan biri GERCEKTEN
    ikinci bir CSS dosyasina referans vermeye baslarsa (orn. yeni,
    varsayimsal bir 'meeting_extra_hypothetical.css'), bu YAKALANMALIDIR.
    Gercek sablon dosyalarina DOKUNMADAN, gercek 7 sablonun metnine
    sentetik/senkron bir ekstra referans EKLEYEREK dogrudan
    _referenced_css_filenames uzerinde dogrulanir."""
    real_texts = [(REPO_ROOT / relative_path).read_text(encoding="utf-8") for relative_path in MEETING_FAMILY_TEMPLATES]
    synthetic_new_file_reference = (
        "<link rel=\"stylesheet\" href=\"{{ url_for('static', "
        "filename='css/meeting_extra_hypothetical.css') }}\">"
    )
    referenced = _referenced_css_filenames([*real_texts, synthetic_new_file_reference])
    assert referenced == {"meeting_development_c_shared.css", "meeting_extra_hypothetical.css"}, (
        f"Kontrol C basarisiz: yeni eklenen CSS dosyasi referansi beklendigi gibi "
        f"YAKALANAMADI: {referenced!r}"
    )


# ---------------------------------------------------------------------------
# 6) Backend untouched: route file and context builder byte-identical to
#    the fixed pre-wave ref.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", [ROUTE_FILE])
def test_p0_backend_files_are_untouched_by_this_wave(relative_path: str) -> None:
    current = _normalize_line_endings((REPO_ROOT / relative_path).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_WAVE_REF, relative_path))
    assert current == pre_wave, f"{relative_path}: byte content changed since pre-wave ref -- backend must be untouched."


# A later, legitimate wave (BYS360 H1F -- user-visible technical exception
# leak hardening) made a narrow, documented change to CONTEXT_BUILDER_FILE:
# `ensure_p0_foundation()` and `run_p0_completion()` used to append the raw
# `str(exc)` of an unexpected internal exception straight into a `warnings`
# list that this same P0 workflow route flashes verbatim to a real manager
# (see tests/behavior/test_h1f_final_audit_route_layer_exception_leak_
# contract.py::test_meeting_p0_completion_apply_failure_never_leaks_raw_
# exception). Both call sites now append a fixed, safe Turkish message
# instead and log the original exception server-side. This is the same
# "later wave makes a narrow, substitution-verified change" pattern already
# established below for the other 6 meeting templates' stale-endpoint fix.
_H1F_EXCEPTION_SAFETY_FIX_SUBSTITUTIONS: tuple[tuple[bytes, bytes], ...] = (
    (
        b'logger.exception("BYS360 performans mod\xc3\xbcl\xc3\xbcnde beklenmeyen hata yakaland\xc4\xb1.")\n        db.session.rollback()\n        warnings.append(f"P0 temel veri haz\xc4\xb1rl\xc4\xb1\xc4\x9f\xc4\xb1 tamamlanamad\xc4\xb1: {exc}")',
        b'logger.exception("BYS360 performans mod\xc3\xbcl\xc3\xbcnde beklenmeyen hata yakaland\xc4\xb1. | exc=%s", exc)\n        db.session.rollback()\n        warnings.append("P0 temel veri haz\xc4\xb1rl\xc4\xb1\xc4\x9f\xc4\xb1 tamamlanamad\xc4\xb1.")',
    ),
    (
        b'logger.exception("BYS360 performans mod\xc3\xbcl\xc3\xbcnde beklenmeyen hata yakaland\xc4\xb1.")\n        warnings.append(f"Kural uygulama servisi \xc3\xa7al\xc4\xb1\xc5\x9ft\xc4\xb1r\xc4\xb1lamad\xc4\xb1: {exc}")',
        b'logger.exception("BYS360 performans mod\xc3\xbcl\xc3\xbcnde beklenmeyen hata yakaland\xc4\xb1. | exc=%s", exc)\n        warnings.append("Kural uygulama servisi \xc3\xa7al\xc4\xb1\xc5\x9ft\xc4\xb1r\xc4\xb1lamad\xc4\xb1.")',
    ),
)


def test_p0_context_builder_file_only_has_the_h1f_exception_safety_fix() -> None:
    current = _normalize_line_endings((REPO_ROOT / CONTEXT_BUILDER_FILE).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_WAVE_REF, CONTEXT_BUILDER_FILE))
    expected = pre_wave
    for old, new in _H1F_EXCEPTION_SAFETY_FIX_SUBSTITUTIONS:
        assert old in expected, f"{CONTEXT_BUILDER_FILE}: expected pre-wave pattern {old!r} not found."
        expected = expected.replace(old, new)
    assert current == expected, f"{CONTEXT_BUILDER_FILE}: byte content changed beyond the known, tested H1F exception-safety fix."


# 19) Other 6 meeting templates untouched (was 7 -- see
#     OTHER_SIX_MEETING_TEMPLATES's own KOORDINATOR DUZELTMESI comment).
# A later, legitimate wave (the stale-endpoint navigation fix -- see
# tests/services/test_meeting_stale_navigation_endpoint_fix_contract.py)
# corrected exactly two safe_url_for() endpoint strings per file in these
# same 6 templates: main.performance_development_guidance and main.
# performance_interim_notes_manager never existed as real Flask endpoints
# anywhere in this repo's git history -- corrected to their live,
# independently-confirmed successors.
_STALE_ENDPOINT_FIX_SUBSTITUTIONS: tuple[tuple[bytes, bytes], ...] = (
    (
        b"safe_url_for('main.performance_interim_notes_manager')",
        b"safe_url_for('main.performance_interim_notes_tr')",
    ),
    (
        b"safe_url_for('main.performance_development_guidance')",
        b"safe_url_for('main.performance_meeting_p4_development_guidance')",
    ),
)


@pytest.mark.parametrize("relative_path", OTHER_SIX_MEETING_TEMPLATES)
def test_other_six_meeting_templates_are_untouched(relative_path: str) -> None:
    current = _normalize_line_endings((REPO_ROOT / relative_path).read_bytes())
    pre_wave = _normalize_line_endings(_git_show(PRE_WAVE_REF, relative_path))
    expected = pre_wave
    for old, new in _STALE_ENDPOINT_FIX_SUBSTITUTIONS:
        assert old in expected, f"{relative_path}: expected pre-wave stale pattern {old!r} not found."
        expected = expected.replace(old, new)
    assert current == expected, f"{relative_path}: byte content changed -- other 6 meeting templates must be untouched."


# ---------------------------------------------------------------------------
# Real, isolated, authenticated Flask app with distinguishable fixture data.
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "p0_ui_contract" / "test_dbs"
_SAFE_RENDER_FALLBACK_MARKERS = ("\u015fablonunda hata var", "\u015fablonu hatal\u0131")

# A distinguishable value_text ("false") on the FIRST required setting, all
# others "true" -- lets tests assert both the "Acik"/"Kapali" badge paths are
# genuinely driven by real per-row data, not a hardcoded template guess.
_TOGGLED_OFF_SETTING_KEY = "require_criterion_comment_for_score_1_5"


@pytest.fixture(scope="module")
def p0_ui_env():
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-p0-ui-contract-min-length-ok")
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
    from app.models.settings_models import ModuleSetting
    from app.services import runtime_schema
    from app.services.performance.meeting_p0_completion import P0_REQUIRED_SETTINGS

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has
        for key, meta in P0_REQUIRED_SETTINGS.items():
            value = "false" if key == _TOGGLED_OFF_SETTING_KEY else "true"
            db.session.add(
                ModuleSetting(
                    module_key="performance",
                    setting_key=key,
                    label=meta["label"],
                    value_text=value,
                    description=meta["description"],
                )
            )
        user = User(
            sicil_no="p0uicontract1",
            email="p0uicontract@ktb.gov.tr",
            ad="P0UI",
            soyad="Kontrat",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("P0UiContractTestKey1!")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    login_response = client.post(
        "/login",
        data={"sicil_or_email": "p0uicontract1", "password": "P0UiContractTestKey1!"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302, f"Test admin login failed: status={login_response.status_code}"
    assert "/login" not in (login_response.headers.get("Location") or ""), (
        "Still redirected to /login after POST -- authentication may have failed."
    )

    yield app, client

    mp.undo()


@pytest.fixture(scope="module")
def p0_response_body(p0_ui_env):
    _app, client = p0_ui_env
    response = client.get("/performance/meeting-development/p0", follow_redirects=True)
    return response.status_code, response.get_data(as_text=True)


# 12) Authenticated GET 200.
def test_p0_route_returns_200(p0_response_body) -> None:
    status, body = p0_response_body
    assert status == 200
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body, "Response looks like a safe_render() fallback stub."


# 2/10-real-http) title visible, H1 P0-specific.
def test_p0_title_and_h1_are_p0_specific(p0_response_body) -> None:
    _status, body = p0_response_body
    assert "P0 Tamamlama" in body
    h1_match = re.search(r'<h1[^>]*class="bys-md-title"[^>]*>([^<]*)</h1>', body)
    assert h1_match, "Expected a <h1 class='bys-md-title'> in the response."
    assert h1_match.group(1).strip() == "P0 Tamamlama"


# 10-real-http) old generic body is no longer this route's main content.
def test_p0_old_generic_shell_heading_is_not_the_main_content(p0_response_body) -> None:
    _status, body = p0_response_body
    # base.html legitimately carries unrelated nav/menu text; what matters is
    # that the page's own H1 (checked above) is no longer the old generic
    # meeting-family title.
    h1_match = re.search(r'<h1[^>]*class="bys-md-title"[^>]*>([^<]*)</h1>', body)
    assert h1_match
    assert h1_match.group(1).strip() != "Hatırlatma ve Gelişim Takibi"


# 3) category_count-equivalent (real categories list) visible.
def test_p0_category_count_visible(p0_response_body) -> None:
    _status, body = p0_response_body
    assert "kategori" in body.lower()
    assert "Güvenlik" in body  # one of the seeded default category names
    assert "Temizlik" in body


# 4) p0_checks_passed-equivalent (scenario pass/total) visible.
def test_p0_checks_result_visible(p0_response_body) -> None:
    _status, body = p0_response_body
    assert re.search(r"\d+/10\s*ge[çc]ti", body, re.IGNORECASE), "Expected an 'N/10 geçti' style summary in the response."


# 5) 6/6 settings fixture data rendered.
def test_all_six_settings_fixture_rows_are_rendered(p0_response_body) -> None:
    from app.services.performance.meeting_p0_completion import P0_REQUIRED_SETTINGS

    _status, body = p0_response_body
    for _key, meta in P0_REQUIRED_SETTINGS.items():
        assert meta["label"] in body, f"Expected setting label '{meta['label']}' in the response body."


# 6) Each setting's value/state visible (Açık/Kapalı badges driven by real data).
def test_each_setting_value_state_is_shown_and_reflects_real_data(p0_response_body) -> None:
    _status, body = p0_response_body
    assert "Açık" in body, "Expected at least one 'Açık' (on) badge for a true-valued setting."
    assert "Kapalı" in body, "Expected the 'Kapalı' (off) badge for the fixture's one false-valued setting."


# 7) foundation-equivalent (categories) data visible -- already covered by
#    test_p0_category_count_visible; add explicit check for category
#    descriptions too.
def test_foundation_category_descriptions_visible(p0_response_body) -> None:
    _status, body = p0_response_body
    assert "P0 karar" in body  # substring shared by all P0_CATEGORY_NAMES seed descriptions


# 8) repaired_low_score_locks "populated" scenario: N/A in this GET context
#    by design (see module docstring) -- covered by test 9's empty-state
#    check, which IS the correct, honest behavior for this read-only view.
def test_repair_section_present_as_honest_readonly_notice(p0_response_body) -> None:
    _status, body = p0_response_body
    assert "Onarım Durumu" in body or "onarım" in body.lower()
    assert "Bu ekrandan onarım işlemi başlatılmaz" in body


# 9) Empty-state safety when repair data absent -- no crash, no raw dump.
def test_repair_section_shows_safe_empty_state_not_raw_dump(p0_response_body) -> None:
    _status, body = p0_response_body
    assert ">None<" not in body
    assert "{'ok'" not in body and '{"ok"' not in body, "Raw P0CompletionResult dict/JSON must not leak into HTML."
    assert "repaired_low_score_locks" not in body, "Raw context-key name must not leak into HTML as text."


# 10) None/0/False correctly parsed -- no literal "None" anywhere, and a
#     real False-valued setting renders as "Kapalı", not blank/0/False.
def test_none_zero_false_render_correctly(p0_response_body) -> None:
    _status, body = p0_response_body
    assert re.search(r">\s*None\s*<", body) is None, "Literal 'None' must never appear as rendered text."
    assert "Kapalı" in body


# 13) Context fixture values genuinely present in the body (cross-check via
#     a category description string unique to the seeded fixture data).
def test_fixture_context_values_are_genuinely_in_response_body(p0_response_body) -> None:
    _status, body = p0_response_body
    assert "Toplantı P0 kararı kapsamında varsayılan personel/grup kategorisi: Güvenlik" in body


# ---------------------------------------------------------------------------
# 15) url_map unchanged.
# ---------------------------------------------------------------------------

# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 DEFECT AQ): an unrelated later
# wave (AQ-2) removed the /performans/baskan-onaylari route registration
# that always lost that URL's dispatch conflict anyway (see
# tests/quality/test_route_conflict_runtime_contract.py's KNOWN_CONFLICTS
# update), dropping the real url_map route count from 985 to 984.
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): 11 new
# GET-only /settings-center/* routes raised the count 984->995 -- mechanically
# re-verified against a fresh app.url_map, unrelated to this wave.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 ASSISTANT V2, seal-fix wave): one
# new, additive route (POST /ai-agent/api/v2/ask) raised the count 995->996
# -- mechanically re-verified against a fresh app.url_map, unrelated to
# this wave.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 B2-F06 private uploads): one new,
# additive route (GET /portal/attachments/<int:attachment_id>) raised the
# count 996->997 -- mechanically re-verified against a fresh app.url_map,
# unrelated to this wave.
EXPECTED_URL_MAP_TOTAL = 997


def test_url_map_route_count_is_unchanged(p0_ui_env) -> None:
    app, _client = p0_ui_env
    total = len(list(app.url_map.iter_rules()))
    assert total == EXPECTED_URL_MAP_TOTAL, f"url_map route count is {total}; expected {EXPECTED_URL_MAP_TOTAL}."


# ---------------------------------------------------------------------------
# 16-17) Style inventory does not worsen; handler/javascript stay 0/0.
#
#        FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): an
#        unrelated later wave added 4 new templates (app/templates/
#        settings_center/*.html), but their CSS is an external stylesheet
#        (app/static/css/settings_center.css) with no inline style="..."
#        attributes or <style> blocks -- 0 contribution, totals remain
#        1032/64/222 -- see test_csp_style_migration_cumulative_inventory_
#        contract.py's FORWARD-COMPATIBILITY FOLLOW-UP 9.
# ---------------------------------------------------------------------------

EXPECTED_ACTIVE_STYLE_TOTAL = 1032
EXPECTED_DYNAMIC_STYLE_TOTAL = 64
EXPECTED_STYLE_BLOCK_TOTAL = 221


def test_repo_wide_style_and_handler_inventory_is_unchanged() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL, (
        f"active_static_total is {inventory.active_static_total}; expected {EXPECTED_ACTIVE_STYLE_TOTAL} (unchanged)."
    )
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL, (
        f"style_block_total is {inventory.style_block_total}; expected {EXPECTED_STYLE_BLOCK_TOTAL} (must not worsen)."
    )
    assert inventory.inline_handler_total == 0
    assert inventory.javascript_url_total == 0


# ---------------------------------------------------------------------------
# 18) CSP header/nonce unchanged.
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
    assert value, "No CSP header found in the response."
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
        assert directive in directives
        assert directives[directive] == expected_value


@pytest.mark.parametrize("directive", STYLE_DIRECTIVES)
def test_csp_style_directives_contain_no_nonce_token(client, directive: str) -> None:
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert "'nonce-" not in directives.get(directive, "")


# ---------------------------------------------------------------------------
# 20) No new xfail introduced by this file.
# ---------------------------------------------------------------------------

_XFAIL_CALL_RE = re.compile(r"pytest" + r"\.xfail\(")
_XFAIL_MARK_RE = re.compile(r"@pytest" + r"\.mark\.xfail")


def test_this_file_introduces_no_xfail_usage() -> None:
    own_text = Path(__file__).read_text(encoding="utf-8")
    call_count = len(_XFAIL_CALL_RE.findall(own_text))
    mark_count = len(_XFAIL_MARK_RE.findall(own_text))
    assert call_count + mark_count == 0


# ---------------------------------------------------------------------------
# This file never writes to any application/template/CSS source path.
# ---------------------------------------------------------------------------


def test_this_file_never_writes_to_application_or_template_or_css_source_paths() -> None:
    forbidden_write_markers = (
        "write_text(",
        "write_bytes(",
        "shutil.copy",
        "shutil.move",
        "shutil.rmtree",
        "os.rename(",
        "os.remove(",
        "os.unlink(",
    )
    own_text = Path(__file__).read_text(encoding="utf-8")
    marker_def_start = own_text.index("forbidden_write_markers = (")
    marker_def_end = own_text.index(")\n", marker_def_start) + 1
    scan_text = own_text[:marker_def_start] + own_text[marker_def_end:]
    hits = [marker for marker in forbidden_write_markers if marker in scan_text]
    assert hits == []
