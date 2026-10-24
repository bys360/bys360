"""CSP Dalga 2 - Ajan 1 (Dashboard) kontrat testi.

BYS360 `app/security/headers.py` uygular:
    script-src: 'self' https:  (unsafe-inline YOK)

Bu dosyanın sahiplik alanı yalnızca:
    - app/templates/dashboard.html
    - app/static/js/dashboard_rebuild.js

Koordinatör grep taraması bu iki dosyada inline event-attribute (onclick=
vb.) veya `javascript:` URL bulunmadığını, `dashboard_rebuild.js` içindeki
`.onclick = function(){}` atamalarının DOM property assignment olduğunu
(HTML string üretimi değil, CSP açısından zararsız) tespit etmişti. Bu test
o tespiti önce bağımsız statik regex taramasıyla, sonra da gerçek bir
Flask test client + gerçek login + gerçek `/dashboard` render'ı ile
KİLİTLER: ileride biri bu iki dosyaya inline handler eklerse hem kaynak
metin hem de üretilen HTML testi kırılır.

Statik testler `tests/security/test_csp_wave1_inline_handlers_contract.py`
ile aynı desendedir (Path.read_text() + regex). Bu dosya ayrıca
`dashboard_rebuild.js` için HTML-string tabanlı onclick üretimi
(`innerHTML`/`insertAdjacentHTML` içine `on*=` yazma) ihtimalini de ayrıca
kontrol eder.
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

REPO_ROOT = Path(__file__).resolve().parents[2]

DASHBOARD_TEMPLATE = "app/templates/dashboard.html"
DASHBOARD_JS = "app/static/js/dashboard_rebuild.js"

WAVE2_DASHBOARD_FILES = [DASHBOARD_TEMPLATE, DASHBOARD_JS]

# HTML attribute syntax: bosluk + on<harfler> + '=' + tirnak. CSS/JS icindeki
# "javascript:" gibi metinsel string literal'leri yanlislikla yakalamaz.
_INLINE_EVENT_ATTR_RE = re.compile(r"""[\s]on[a-zA-Z]+\s*=\s*["']""")
_JS_HREF_RE = re.compile(r"""href\s*=\s*["']\s*javascript:""", re.IGNORECASE)
# JS dosyasi icinde HTML-string uretimi yoluyla inline handler yazilmasi
# (orn. `'<button onclick="..."' ` gibi template-string/concat kaliplari).
_JS_STRING_ONCLICK_RE = re.compile(r"""on[a-zA-Z]+\s*=\s*["']""")


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1) Statik kaynak-kod kontrati (Path.read_text + regex, tarayici calisma
#    zamani davranisini kanitlamaz).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", WAVE2_DASHBOARD_FILES)
def test_dashboard_file_has_no_inline_event_attributes(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _INLINE_EVENT_ATTR_RE.findall(text)
    assert not matches, (
        f"{relative_path} icinde inline event-attribute (on*=) bulundu: {matches!r}. "
        "CSP script-src 'self' https: (unsafe-inline yok) altinda bunlar calismaz; "
        "data-* attribute + addEventListener kalibina cevrilmeli."
    )


@pytest.mark.parametrize("relative_path", WAVE2_DASHBOARD_FILES)
def test_dashboard_file_has_no_javascript_href(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _JS_HREF_RE.findall(text)
    assert not matches, (
        f"{relative_path} icinde href=\"javascript:...\" bulundu: {matches!r}. "
        "Gercek <a>/<button> + addEventListener kalibina cevrilmeli."
    )


@pytest.mark.parametrize("relative_path", WAVE2_DASHBOARD_FILES)
def test_dashboard_file_introduces_no_dangerous_js_sinks(relative_path: str) -> None:
    """Duzeltme sirasinda eval/new Function/document.write eklenmedigini dogrular."""
    text = _read(relative_path)
    for forbidden in ("eval(", "new Function(", "document.write("):
        assert forbidden not in text, f"{relative_path} icinde yasakli sink bulundu: {forbidden}"


def test_dashboard_js_has_no_html_string_based_inline_handlers() -> None:
    """`dashboard_rebuild.js` gercekten HTML string uretmiyor (innerHTML /
    insertAdjacentHTML / outerHTML atamasi yok); bu nedenle icinde
    on*="..." iceren bir HTML parcasi olusturma yolu da yok. Bu test hem
    tehlikeli DOM sink'lerinin yoklugunu hem de (varsayimsal olarak
    eklenirse) icindeki on*= desenini ayri ayri kilitler.
    """
    text = _read(DASHBOARD_JS)
    for sink in (".innerHTML", "insertAdjacentHTML", ".outerHTML"):
        assert sink not in text, (
            f"{DASHBOARD_JS} icinde HTML-string sink'i bulundu: {sink}. "
            "Bu, HTML-string tabanli inline onclick uretimine kapi acabilir; "
            "DOM property assignment + addEventListener kalibi korunmali."
        )
    assert not _JS_STRING_ONCLICK_RE.search(text), (
        f"{DASHBOARD_JS} icinde beklenmedik bir on*= metin deseni bulundu."
    )


def test_dashboard_js_onclick_assignments_are_dom_property_not_html_string() -> None:
    """Koordinatorun tespiti: `dashboard_rebuild.js` icinde `.onclick = ` gibi
    HTML-attribute-benzeri bir DOM property assignment YOK (dosyada boyle
    bir atama bulunmuyor); bu test o durumu pozitif olarak dogrular ve
    ileride biri boyle bir atama eklerse en azindan CSP acisindan zararsiz
    (string degil, fonksiyon referansi) oldugunu zorunlu kilar.
    """
    text = _read(DASHBOARD_JS)
    onclick_prop_assignments = re.findall(r"""\.onclick\s*=\s*(.+)""", text)
    for assignment in onclick_prop_assignments:
        stripped = assignment.strip().rstrip(";")
        assert not (stripped.startswith('"') or stripped.startswith("'")), (
            f"{DASHBOARD_JS} icinde `.onclick = <string>` bulundu: {assignment!r}. "
            "String atama HTML-attribute'a esdeger davranabilir; fonksiyon "
            "referansi / addEventListener kullanilmali."
        )


def test_dashboard_template_extends_base_and_has_no_other_includes() -> None:
    """Koordinatorun tespiti: dashboard.html sadece base.html'i extend eder,
    baska bir partial include etmez -- yani bu dosyanin kapsam disina
    (personel/performans ajanlarinin dosyalarina) sizinti riski yok."""
    text = _read(DASHBOARD_TEMPLATE)
    assert text.lstrip().startswith('{% extends "base.html" %}')
    assert "{% include" not in text


# ---------------------------------------------------------------------------
# 2) Calisma-zamani render kontrolu: gercek Flask app + gercek DB kullanici +
#    gercek POST /login + gercek GET /dashboard. Izole tek-dosyalik kurulum
#    deseni `tests/security/test_account_change_photo_redirect_guard.py` ile
#    aynidir (paylasilan session-scope app/client fixture'larina bagimli
#    olmadan). Bu HALA gercek bir tarayici testi DEGILDIR: CSP enforce
#    edilmis bir tarayicida script'lerin fiilen calistigini kanitlamaz,
#    yalnizca uretilen HTML'de inline event-attribute / javascript: href
#    kalmadigini ve dashboard_rebuild.js'in dogru sekilde <script src=...>
#    ile (harici dosya, inline degil) baglandigini dogrular.
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "phase5_csp_wave2" / "test_dbs"


def _make_app(monkeypatch, **config_overrides):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-csp-wave2-dashboard-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    app.config.update(config_overrides)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


def _create_user(app, *, sicil_no, email, role="personel", password="CspWave2TestKey1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="CspWave2",
            soyad="Test",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password="CspWave2TestKey1!"):
    payload = {"sicil_or_email": sicil_no, "password": password, "next": "/dashboard"}
    response = client.post("/login", data=payload, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def test_dashboard_page_render_has_no_inline_handlers(monkeypatch, request) -> None:
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="cspw2001", email=f"cspw2.{uuid.uuid4().hex[:8]}@ktb.gov.tr")
    client = app.test_client()
    _login(client, "cspw2001")

    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 200, (
        f"/dashboard 200 donmedi (status={response.status_code}); "
        "beklenmedik bir render hatasi olabilir."
    )
    html = response.get_data(as_text=True)

    assert not _INLINE_EVENT_ATTR_RE.findall(html), (
        "Gercek /dashboard render ciktisinda inline event-attribute bulundu."
    )
    assert not _JS_HREF_RE.search(html), (
        "Gercek /dashboard render ciktisinda javascript: href bulundu."
    )
    for forbidden in ("eval(", "new Function(", "document.write("):
        assert forbidden not in html, f"/dashboard render ciktisinda yasakli sink bulundu: {forbidden}"

    # dashboard_rebuild.js harici <script src=...> ile baglaniyor olmali
    # (inline script DEGIL) -- CSP script-src 'self' https: bunu kapsar.
    assert 'src="/static/js/dashboard_rebuild.js"' in html
    # Veri payload'u inline ama type="application/json" oldugu icin
    # tarayici tarafindan JS olarak YORUMLANMAZ/CALISTIRILMAZ (inert data
    # block); CSP script-src bu elemente uygulanmaz.
    assert 'id="dashboard-rebuild-payload"' in html
    assert 'type="application/json"' in html


def test_dashboard_page_render_marker_present(monkeypatch, request) -> None:
    """dashboard.html'nin dogru template oldugunu (yanlislikla baska bir
    fallback/hata sayfasinin render edilmedigini) dogrulayan duz-anlamli
    kontrol -- render testinin sessizce yanlis sayfayi 200 ile onaylamasini
    engeller."""
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="cspw2002", email=f"cspw2.{uuid.uuid4().hex[:8]}@ktb.gov.tr")
    client = app.test_client()
    _login(client, "cspw2002")

    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "BYS360_DASHBOARD_REBUILD_V1_OK" in html
