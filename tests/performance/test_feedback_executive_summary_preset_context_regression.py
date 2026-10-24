"""Regression test for a pre-existing bug found (and locked, unfixed) during
the BYS360 CSP Style-2B verification effort: `GET /performance/feedback-
executive-summary` returned HTTP 500 for an authenticated admin.

ROOT CAUSE (file/line evidence): `feedback_executive_summary_dashboard`
(app/performance/engagement_feedback_routes.py) called

    return safe_render(
        "feedback_executive_summary_dashboard.html", "<h3>...</h3>",
        ...,
        preset=preset,          # <- explicit kwarg
        ...,
        **dashboard,            # <- dashboard["preset"] == preset (SAME value)
    )

where `dashboard = build_feedback_executive_summary(..., preset=preset, ...)`
(app/services/performance/feedback_executive_summary_service.py) already
returns a dict containing its own `"preset"` key (line 224 of that file) --
set to the exact same validated/resolved preset string the route already
computed. Passing the same keyword twice (once explicitly, once via
`**dashboard`) raises `TypeError: safe_render() got multiple values for
keyword argument 'preset'` at the Python call-binding step, before
`safe_render`'s own body ever runs.

FIX: remove the now-redundant explicit `preset=preset` kwarg at the call
site (Option A from the incident's own analysis) -- `dashboard["preset"]`
already supplies the identical value via `**dashboard`. This is the
smallest, least-collateral fix: `build_feedback_executive_summary` is also
called by `dispatch_feedback_executive_summary` (same service file), which
does not read `summary["preset"]` anywhere, and no other file in the repo
reads `dashboard["preset"]`/`summary["preset"]` (verified via
`grep -rn '\\["preset"\\]' app/`) -- so the shared service function's return
contract was deliberately left untouched.

This file does NOT touch app/templates/**, app/static/css/**,
app/static/js/**, app/security/**, config.py, or any CSP/nonce/PWA source --
only reads them (via git diff, read-only) to lock that this bugfix carries
zero collateral changes there.
"""
from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest import mock

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTE_FILE = "app/performance/engagement_feedback_routes.py"
ROUTE_URL = "/performance/feedback-executive-summary"

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "perf_feedback_exec_summary_regression" / "test_dbs"
_SAFE_RENDER_FALLBACK_MARKERS = ("şablonunda hata var", "şablonu hatalı")
_BASE_TEMPLATE_MARKER = "topbarNotificationBadge"


@pytest.fixture(scope="module")
def perf_bugfix_env(request):
    """Isolated, temp-SQLite Flask app + a real admin user (module-scoped,
    same established pattern as tests/security/test_csp_style2a_repo_wide_
    contract.py::style2a_env / test_csp_style2b_target_templates_contract.py
    ::style2b_env). Never touches a real/production database."""
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-perf-feedback-exec-summary-bugfix-min-ok")
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

        admin = User(
            sicil_no="perfbug001",
            email="perfbug.admin@ktb.gov.tr",
            ad="PerfBug",
            soyad="Admin",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        admin.set_password("PerfBugTestAdminKey1!")
        db.session.add(admin)

        low_priv = User(
            sicil_no="perfbug002",
            email="perfbug.lowpriv@ktb.gov.tr",
            ad="PerfBug",
            soyad="LowPriv",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        low_priv.set_password("PerfBugTestLowPrivKey1!")
        db.session.add(low_priv)
        db.session.commit()

    admin_client = app.test_client()
    admin_login = admin_client.post(
        "/login",
        data={"sicil_or_email": "perfbug001", "password": "PerfBugTestAdminKey1!"},
        follow_redirects=False,
    )
    assert admin_login.status_code == 302, (
        f"Admin test kullanicisi ile giris basarisiz oldu: status={admin_login.status_code}"
    )
    assert "/login" not in (admin_login.headers.get("Location") or ""), (
        "Giris sonrasi hala /login'e yonlendiriliyor -- kimlik dogrulama basarisiz olmus olabilir."
    )

    low_priv_client = app.test_client()
    low_priv_login = low_priv_client.post(
        "/login",
        data={"sicil_or_email": "perfbug002", "password": "PerfBugTestLowPrivKey1!"},
        follow_redirects=False,
    )
    assert low_priv_login.status_code == 302

    anon_client = app.test_client()

    yield app, admin_client, low_priv_client, anon_client

    mp.undo()


# ---------------------------------------------------------------------------
# 1) Yetkili kullanici GET -> 200, gercek render (fallback/500 degil).
# ---------------------------------------------------------------------------


def test_authenticated_admin_get_returns_200(perf_bugfix_env) -> None:
    _app, admin_client, _low_priv_client, _anon_client = perf_bugfix_env
    response = admin_client.get(ROUTE_URL, follow_redirects=True)
    assert response.status_code == 200, (
        f"{ROUTE_URL} yetkili admin icin 200 donmeli, {response.status_code} dondu."
    )


# ---------------------------------------------------------------------------
# 2) Duplicate keyword TypeError olusmaz -- gercek route govdesini (safe_render
#    dahil) calistirarak, hicbir exception yutulmadan dogrudan dogrulanir.
# ---------------------------------------------------------------------------


def test_no_duplicate_keyword_typeerror(perf_bugfix_env) -> None:
    _app, admin_client, _low_priv_client, _anon_client = perf_bugfix_env
    # PROPAGATE_EXCEPTIONS olmadan bile: eger TypeError hala olusuyorsa route
    # 500 doner VE app'in global error handler'i logluyor olsa da yanit kodu
    # kesin olarak 500'den FARKLI olmalidir -- asagidaki assert bunu net
    # sekilde yakalar (200 bekleniyor, 500 degil).
    response = admin_client.get(ROUTE_URL)
    assert response.status_code != 500, (
        f"{ROUTE_URL} hala 500 donuyor -- 'preset' duplicate-keyword TypeError'i "
        "geri gelmis olabilir."
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 3-4) Template context'i: preset degeri dogru VE dashboard'un diger
#    alanlari korunuyor. safe_render kontrollu monkeypatch ile gercek
#    cagrinin kwargs'larini yakalar (gercek render de ayrica asagida --
#    bolum 9 -- calisir, bu SADECE context sozlesmesini dogrulamak icin).
# ---------------------------------------------------------------------------


def _capture_safe_render_kwargs(app, client, url: str) -> dict[str, object]:
    import app.performance.engagement_feedback_routes as route_module

    captured: dict[str, object] = {}
    real_safe_render = route_module.safe_render

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_safe_render(*args, **kwargs)

    with mock.patch.object(route_module, "safe_render", side_effect=_spy):
        response = client.get(url)
    captured["_response_status_code"] = response.status_code
    return captured


def test_template_receives_correct_preset_value(perf_bugfix_env) -> None:
    app, admin_client, _low_priv_client, _anon_client = perf_bugfix_env
    captured = _capture_safe_render_kwargs(app, admin_client, f"{ROUTE_URL}?preset=weekly")
    assert captured["_response_status_code"] == 200
    assert captured.get("preset") == "weekly", (
        f"Template'e giden 'preset' degeri {captured.get('preset')!r}, 'weekly' bekleniyordu."
    )


def test_dashboard_context_fields_are_preserved(perf_bugfix_env) -> None:
    app, admin_client, _low_priv_client, _anon_client = perf_bugfix_env
    captured = _capture_safe_render_kwargs(app, admin_client, ROUTE_URL)
    assert captured["_response_status_code"] == 200
    # build_feedback_executive_summary()'in dondurdugu dict'in **dashboard
    # ile acilan, template'in gercekten kullandigi alanlari (bkz.
    # app/templates/feedback_executive_summary_dashboard.html) hala mevcut.
    for expected_key in (
        "preset",
        "preset_label",
        "cards",
        "request_status_rows",
        "request_age_buckets",
        "priority_requests",
        "priority_meetings",
        "manager_rows",
        "next_meetings",
        "recipient_rows",
        "digest_subject",
        "digest_body_plain",
    ):
        assert expected_key in captured, (
            f"'{expected_key}' artik safe_render'a gitmiyor -- dashboard context "
            "sozlesmesi bozulmus olabilir."
        )
    # Route'un kendi eklediği ek context alanlari da hala mevcut.
    for own_key in ("selected_scope", "preset_options", "scope_label", "scope_role_title"):
        assert own_key in captured, f"'{own_key}' route'un kendi context'inden kaybolmus."


# ---------------------------------------------------------------------------
# 5-6) preset None (query param yok) -> "daily" varsayilanina duser, route
#    calisir; preset doluyken de (orn. "weekly") route calisir.
# ---------------------------------------------------------------------------


def test_preset_none_defaults_to_daily_and_route_still_works(perf_bugfix_env) -> None:
    app, admin_client, _low_priv_client, _anon_client = perf_bugfix_env
    captured = _capture_safe_render_kwargs(app, admin_client, ROUTE_URL)
    assert captured["_response_status_code"] == 200
    assert captured.get("preset") == "daily", (
        f"preset query param verilmedigi icin 'daily' varsayilani bekleniyordu, "
        f"{captured.get('preset')!r} bulundu."
    )


def test_preset_provided_non_default_still_works(perf_bugfix_env) -> None:
    app, admin_client, _low_priv_client, _anon_client = perf_bugfix_env
    captured = _capture_safe_render_kwargs(app, admin_client, f"{ROUTE_URL}?preset=weekly")
    assert captured["_response_status_code"] == 200
    assert captured.get("preset") == "weekly"


# ---------------------------------------------------------------------------
# 7-8) Yetkilendirme davranisi degismedi: giris yapilmamis kullanici hala
#    /login'e yonlendirilir; menu erisimi olmayan (dusuk yetkili) kullanici
#    hala 403 (render_access_denied) alir -- bu fix'in dokunmadigi
#    @login_required / @menu_key_required decorator'lari gercekten calisiyor.
# ---------------------------------------------------------------------------


def test_unauthenticated_user_is_redirected_to_login(perf_bugfix_env) -> None:
    _app, _admin_client, _low_priv_client, anon_client = perf_bugfix_env
    response = anon_client.get(ROUTE_URL, follow_redirects=False)
    assert response.status_code in (302, 401), (
        f"Giris yapilmamis kullanici icin 302/401 bekleniyordu, {response.status_code} bulundu."
    )
    if response.status_code == 302:
        assert "/login" in (response.headers.get("Location") or ""), (
            "Giris yapilmamis kullanici /login'e yonlendirilmiyor."
        )


def test_low_privilege_role_without_menu_access_is_denied(perf_bugfix_env) -> None:
    _app, _admin_client, low_priv_client, _anon_client = perf_bugfix_env
    response = low_priv_client.get(ROUTE_URL, follow_redirects=True)
    assert response.status_code == 403, (
        f"Menu erisimi olmayan dusuk-yetkili kullanici icin 403 (render_access_denied) "
        f"bekleniyordu, {response.status_code} bulundu -- bu fix yetkilendirme "
        "davranisini degistirmis olabilir."
    )
    body = response.get_data(as_text=True)
    assert "preset" not in body.lower() or "yönetici özet" not in body.lower(), (
        "Dusuk-yetkili kullanici, erisim engeli yerine gercek dashboard icerigini "
        "gormus gibi gorunuyor."
    )


# ---------------------------------------------------------------------------
# 9-10) Gercek Flask/Jinja render gerceklesir; TemplateNotFound veya
#    safe_render'in exception-fallback stub'uyla sahte PASS uretilmez.
# ---------------------------------------------------------------------------


def test_real_render_happens_no_fallback_or_template_not_found(perf_bugfix_env) -> None:
    _app, admin_client, _low_priv_client, _anon_client = perf_bugfix_env
    response = admin_client.get(ROUTE_URL, follow_redirects=True)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert _BASE_TEMPLATE_MARKER in body, (
        f"{ROUTE_URL} yanitinda base.html'in '{_BASE_TEMPLATE_MARKER}' isaretcisi "
        "bulunamadi -- tam sayfa render gerceklesmemis olabilir."
    )
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body, (
            f"{ROUTE_URL} yaniti safe_render() exception-fallback stub'u iceriyor "
            f"gibi gorunuyor ('{marker}' bulundu) -- gercek sablon render edilmemis "
            "olabilir (sahte PASS)."
        )
    assert "Yönetici Özet Merkezi" in body or "Y\u00f6netici \u00d6zet Merkezi" in body, (
        "Beklenen sayfa basligi yanitta bulunamadi."
    )


# ---------------------------------------------------------------------------
# 11) Route gercek/uretim DB'sine dokunmaz -- izole, UUID tabanli gecici
#    SQLite dosyasi kullanildigi yapisal olarak dogrulanir.
# ---------------------------------------------------------------------------


def test_route_only_touches_isolated_temp_sqlite_db(perf_bugfix_env) -> None:
    app, _admin_client, _low_priv_client, _anon_client = perf_bugfix_env
    configured_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    assert configured_uri.startswith("sqlite:///"), (
        f"Test app'i sqlite disi bir DB'ye baglanmis gorunuyor: {configured_uri!r}"
    )
    assert str(_TEST_DB_ROOT).replace("\\", "/") in configured_uri.replace("\\", "/"), (
        "Test app'i beklenen izole gecici SQLite dizini disinda bir dosyaya "
        f"baglanmis: {configured_uri!r}"
    )
    assert "instance" not in configured_uri.lower(), (
        "Test app'i gercek 'instance/' uretim veritabani dizinine baglanmis gorunuyor."
    )


# ---------------------------------------------------------------------------
# 12) Style/CSP/nonce/PWA kapsamina bu bugfix'in DIFF'i sifir -- salt-okunur
#    git diff kontrolu. Yalniz git binary'si yoksa atlanir (ortam kisitlamasi).
#
#    BYS360 CSP STYLE-3A KOORDINATOR DUZELTMESI (ileri-uyumluluk): bu iki
#    test eskiden GUNCEL/commit'lenmemis calisma agacinin `HEAD`'e karsi
#    diff'ine bakiyordu. Bu, Style-2A'nin repo-genelinde tam olarak ayni
#    hatayi tasiyordu (bkz. test_csp_style2a_repo_wide_contract.py'nin "BYS360
#    CSP STYLE-2B KOORDINATOR NOTU" bolumu) ve Style-2B'nin kendi "dosya bu
#    dalga tarafindan dokunulmadi" testinde de (test_csp_style2b_target_
#    templates_contract.py::test_engagement_feedback_routes_file_was_
#    untouched_by_style2b_itself) ayni sekilde bulunup duzeltilmisti: bu
#    bugfix ARTIK commit'lendigi (54ccf908..e0340cb) icin `git diff HEAD --`
#    o degisikligi bir daha HICBIR ZAMAN gostermez (HEAD zaten iceriyor) --
#    VE bu bugfix'ten SONRAKI herhangi bir dalganin (orn. Style-3A, `app/
#    templates/errors/*.html` + `app/templates/strategic_performance/*.html`
#    dosyalarini MESRU sekilde degistiren) commit'lenmemis kendi calismasi
#    da bu "HEAD'e karsi genel diff" kontrolune YAKALANIRDI -- bu bugfix'in
#    kendisiyle hicbir ilgisi olmamasina ragmen. Artik SABIT bir tarihsel
#    commit araligina (BUGFIX_PRE_REF..BUGFIX_CLOSURE_REF) kilitlendi: bu,
#    bu bugfix'in KENDI commit'inin bu kapsamlara/dosyaya dokunmadigini
#    SONSUZA KADAR dogru kalacak sekilde kanitlar -- sonraki hicbir dalgadan
#    etkilenmez.
# ---------------------------------------------------------------------------

_UNTOUCHED_SCOPE_PATHS = (
    "app/templates",
    "app/static/css",
    "app/static/js",
    "app/security",
    "config.py",
    ".env.example",
    "migrations",
    "service-worker.js",
    "sw.js",
)

BUGFIX_PRE_REF = "54ccf908c937bd06d0146e11b16ecd71dd569c51"
BUGFIX_CLOSURE_REF = "e0340cbaba6f7fd439d4420b2c88bcdcc7031968"


def test_style_csp_nonce_and_pwa_paths_have_zero_diff_from_this_bugfix() -> None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI bulunamadi.")

    result = subprocess.run(
        [
            "git", "-C", str(REPO_ROOT), "diff", "--name-only",
            f"{BUGFIX_PRE_REF}..{BUGFIX_CLOSURE_REF}", "--", *_UNTOUCHED_SCOPE_PATHS,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"git diff beklenmedik sekilde basarisiz oldu (exit={result.returncode}).")

    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert changed == [], (
        f"Bu bugfix'in KENDI kapanis commit'i ({BUGFIX_PRE_REF}..{BUGFIX_CLOSURE_REF}) "
        f"kapsamadigi dosya(lar)i degistirmis gorunuyor: {changed!r} -- yalniz "
        "app/performance/engagement_feedback_routes.py ve regresyon test dosyasi "
        "degismeliydi."
    )


def test_route_file_diff_is_scoped_to_the_single_kwarg_removal() -> None:
    """Ekstra bir guvence: bu bugfix'in KENDI kapanis commit'indeki (SABIT
    tarihsel `BUGFIX_PRE_REF..BUGFIX_CLOSURE_REF` araligi) GERCEK diff'i
    beklenenden fazla bir seyi degistirmemis -- yalniz `preset=preset,`
    satirinin kaldirilmasi (+ aciklayici yorum) civarinda."""
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI bulunamadi.")

    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", f"{BUGFIX_PRE_REF}..{BUGFIX_CLOSURE_REF}", "--", ROUTE_FILE],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"git diff basarisiz oldu (exit={result.returncode}).")

    diff_text = result.stdout
    removed_lines = [
        line for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---")
    ]
    added_lines = [
        line for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++")
    ]
    assert any("preset=preset" in line for line in removed_lines), (
        "Beklenen 'preset=preset,' satiri diff'te kaldirilmis olarak bulunamadi."
    )
    assert not any(
        line.strip("+- \t") and "def " in line and "feedback_executive_summary_dashboard" not in line
        for line in removed_lines + added_lines
    ), "Diff, beklenenden farkli bir fonksiyon tanimini da degistirmis gorunuyor."


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
