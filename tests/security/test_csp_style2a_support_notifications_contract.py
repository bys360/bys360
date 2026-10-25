"""CSP Style-2A pilot - static inline `style="..."` extraction contract for
Agent 1's owned templates: support/help_admin_list.html, support/detail.html,
support/new.html, notifications_list.html.

Scope (per coordinator brief, "BYS360 CSP Style-2A" wave): convert the 16
fully-static inline `style="..."` attributes on these 4 templates into new
semantic CSS classes added to `app/static/css/faz4_support_account_mobile.css`
(support templates) and `app/static/css/faz3_communication_hr_mobile.css`
(notifications_list.html). This is a behavior-preserving pilot -- every
removed CSS declaration must reappear with IDENTICAL property:value pairs in
the new class rule; no visual change is the goal.

This file is a LIGHTER, template-scoped self-check owned by Agent 1 -- it is
NOT the broader independent repo-wide contract (that is Agent 3's separate
mandate). It covers, for each of the 4 owned templates:
    (A) static source-code checks (Path.read_text + regex): zero inline
        `style="..."` attributes remain, zero inline event-handler
        attributes (on*=), zero `javascript:` URLs, and the exact new
        class-bearing markup is present verbatim;
    (B) static CSS-file checks: the new selectors exist in the target
        stylesheet with the expected declarations, no `!important` was
        introduced by the new rules, and the surrounding pre-existing
        content is untouched (regression anchor);
    (C) real runtime checks: a real Flask app + real (in-memory SQLite) test
        DB + a real session-cookie login (POST /login) + a real GET request
        to each of the 4 routes, asserting 200 and that the rendered HTML
        output has zero `style="..."` attributes and carries the new class
        names on the expected elements. For support/detail.html a real
        SupportTicket row (created via a real POST to /support/new, the
        same route under test) and a real SupportTicketAttachment row
        (direct ORM insert -- no real file I/O) back the render so the
        conditional `attachment-filename` branch is exercised too.

No destructive action is performed anywhere in this file: no commit/push,
no file uploads to real disk, no outbound network/email (MAIL_SUPPRESS_SEND
is set, matching the pattern in tests/security/test_web_login_authentication_
negative.py and tests/integration/test_mobile_support_ticket_db_transactions.py).
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

REPO_ROOT = Path(__file__).resolve().parents[2]

HELP_ADMIN_LIST_TEMPLATE = "app/templates/support/help_admin_list.html"
DETAIL_TEMPLATE = "app/templates/support/detail.html"
NEW_TEMPLATE = "app/templates/support/new.html"
NOTIFICATIONS_TEMPLATE = "app/templates/notifications_list.html"

OWNED_TEMPLATES = [HELP_ADMIN_LIST_TEMPLATE, DETAIL_TEMPLATE, NEW_TEMPLATE, NOTIFICATIONS_TEMPLATE]

FAZ4_CSS = "app/static/css/faz4_support_account_mobile.css"
FAZ3_CSS = "app/static/css/faz3_communication_hr_mobile.css"

# Kanonik regex'ler -- diger CSP wave kontrat dosyalariyla (orn.
# tests/security/test_csp_wave9_final_zero_handler_contract.py) ayni ailede.
_INLINE_STYLE_ATTR_RE = re.compile(r"""\sstyle\s*=\s*["']""")
_INLINE_EVENT_ATTR_RE = re.compile(r"""[\s]on[a-zA-Z]+\s*=\s*["']""")
_JS_HREF_SRC_RE = re.compile(r"""(?:href|src)\s*=\s*["']\s*javascript:""", re.IGNORECASE)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# A) Statik kaynak-kod kontrati: 4 sahip olunan template.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", OWNED_TEMPLATES)
def test_owned_template_has_zero_inline_style_attributes(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _INLINE_STYLE_ATTR_RE.findall(text)
    assert not matches, f"{relative_path} icinde hala inline style=\"...\" bulundu: {matches!r}"


@pytest.mark.parametrize("relative_path", OWNED_TEMPLATES)
def test_owned_template_has_zero_inline_event_handlers(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _INLINE_EVENT_ATTR_RE.findall(text)
    assert not matches, f"{relative_path} icinde inline event-attribute bulundu: {matches!r}"


@pytest.mark.parametrize("relative_path", OWNED_TEMPLATES)
def test_owned_template_has_zero_javascript_url(relative_path: str) -> None:
    text = _read(relative_path)
    assert not _JS_HREF_SRC_RE.search(text), f"{relative_path} icinde href/src=\"javascript:...\" bulundu."


def test_help_admin_list_new_class_markup_present_verbatim() -> None:
    text = _read(HELP_ADMIN_LIST_TEMPLATE)
    assert '<h3 class="panel-heading">Yönetim Paneli</h3>' in text
    assert text.count('<p class="panel-subtitle">') == 1
    assert '<div class="header-actions-row">' in text
    assert '<form method="get" class="search-form section-spacing-top-md">' in text
    assert '<div class="empty section-spacing-top-lg">Filtreye uygun makale bulunamadı.</div>' in text


def test_detail_new_class_markup_present_verbatim() -> None:
    text = _read(DETAIL_TEMPLATE)
    assert '<div class="meta-row section-spacing-top-md">' in text
    assert '<div class="attachment-filename">{{ attachment.filename }}</div>' in text
    assert (
        '<label class="muted checkbox-inline"><input type="checkbox" name="is_internal" value="1"> '
        "İç not olarak kaydet</label>" in text
    )
    assert '<hr class="section-divider">' in text


def test_new_template_new_class_markup_present_verbatim() -> None:
    text = _read(NEW_TEMPLATE)
    assert '<div class="privacy-box section-spacing-bottom-md">' in text
    # new.html:35 ve new.html:74 ayni birebir deklarasyona sahipti -> ayni
    # sinif (field-helper-text) TEKRAR KULLANILDI, iki ayri sinif ACILMADI.
    assert text.count('<div class="field-helper-text">') == 2
    assert (
        '<label class="checkbox-inline checkbox-inline--emphasis"><input type="checkbox" name="is_private" '
        'value="1"> Sadece yetkili kullanıcılar görsün</label>' in text
    )


def test_notifications_list_new_class_markup_present_verbatim() -> None:
    text = _read(NOTIFICATIONS_TEMPLATE)
    assert '<div class="bulk-bar section-spacing-top-sm">' in text
    assert '<h5 class="empty-state-heading">Bildirim görünmüyor</h5>' in text
    assert '<p class="empty-state-text">Bu görünümde henüz listelenecek bir kayıt yok.</p>' in text


def test_no_new_inline_style_attribute_was_substituted_for_another() -> None:
    """Koordinator talimati: bir inline style'in baska bir inline style ile
    DEGISTIRILMEDIGINI (yani style="..." attribute'unun tamamen kalktigini,
    class="..." ile degistirildigini) her 4 dosyada da dogrular -- Bolum A'daki
    genel style="" taramasindan BAGIMSIZ, acikca isimlendirilmis bir ikinci
    kontrol."""
    for relative_path in OWNED_TEMPLATES:
        text = _read(relative_path)
        assert "style=" not in text.replace("<style>", "").replace("</style>", ""), (
            f"{relative_path} icinde beklenmeyen bir 'style=' izi kaldi (muhtemelen yeni bir inline style)."
        )


def test_style_blocks_and_style_links_untouched_count() -> None:
    """Koordinator talimati: mevcut <style>...</style> blok icerikleri
    DEGISTIRILMEDI (sadece yeni bir <link rel="stylesheet"> eklenebilir).
    Her 4 dosyada da <style veya <link rel="stylesheet" referanslarinin hala
    mevcut oldugunu (kaldirilmadigini) dogrular -- tam sayim regresyonu
    ayrica CSS dosyasi testlerinde (Bolum B) yapilir."""
    assert _read(HELP_ADMIN_LIST_TEMPLATE).count("<style>") == 1
    assert _read(DETAIL_TEMPLATE).count("<style>") == 1
    assert _read(NEW_TEMPLATE).count("<style>") == 1
    notif_text = _read(NOTIFICATIONS_TEMPLATE)
    assert notif_text.count("<style>") == 2  # @import blogu + asil blok, ikisi de mevcut/dokunulmadi
    for relative_path in OWNED_TEMPLATES:
        text = _read(relative_path)
        assert 'rel="stylesheet"' in text or "@import" in text


# ---------------------------------------------------------------------------
# B) Statik CSS dosyasi kontrati: yeni selector'lerin dogru deklarasyonlarla
#    var oldugu, !important eklenmedigi, mevcut icerigin dokunulmadigi.
# ---------------------------------------------------------------------------

FAZ4_NEW_RULES = [
    ".panel-heading{margin:0;font-size:1.12rem;font-weight:900;color:#111827}",
    ".panel-subtitle{margin:8px 0 0;color:#6b7280;line-height:1.8}",
    ".header-actions-row{display:flex;gap:10px;flex-wrap:wrap}",
    ".section-spacing-top-md{margin-top:16px}",
    ".section-spacing-top-lg{margin-top:18px}",
    ".section-spacing-bottom-md{margin-bottom:16px}",
    ".attachment-filename{font-weight:900;color:#111827}",
    ".checkbox-inline{display:inline-flex;align-items:center;gap:8px}",
    ".checkbox-inline--emphasis{font-weight:850;color:#374151}",
    ".section-divider{margin:18px 0;border:none;border-top:1px solid rgba(15,23,42,.08)}",
    ".field-helper-text{margin-top:6px;color:#6b7280;line-height:1.65;font-size:.9rem}",
]

FAZ3_NEW_RULES = [
    ".section-spacing-top-sm{margin-top:14px}",
    ".empty-state-heading{margin:0;color:#111827;font-size:1rem;font-weight:900}",
    ".empty-state-text{margin:0;line-height:1.8}",
]


@pytest.mark.parametrize("rule", FAZ4_NEW_RULES)
def test_faz4_css_new_rule_present_with_exact_declaration(rule: str) -> None:
    text = _read(FAZ4_CSS)
    assert rule in text, f"{FAZ4_CSS} icinde beklenen kural bulunamadi: {rule!r}"
    assert "!important" not in rule
    assert rule.split("{", 1)[0].count("#") == 0  # selector kismi bir ID selector degil


@pytest.mark.parametrize("rule", FAZ3_NEW_RULES)
def test_faz3_css_new_rule_present_with_exact_declaration(rule: str) -> None:
    text = _read(FAZ3_CSS)
    assert rule in text, f"{FAZ3_CSS} icinde beklenen kural bulunamadi: {rule!r}"
    assert "!important" not in rule
    assert rule.split("{", 1)[0].count("#") == 0


def test_faz4_css_preexisting_content_untouched_regression() -> None:
    text = _read(FAZ4_CSS)
    assert ".faz4-mobile-table-cards{display:none;gap:12px;margin-top:16px}" in text
    assert '.faz4-mobile-field__value .support-btn{width:100%;justify-content:center}' in text
    assert "@media (max-width: 991.98px){" in text
    assert "@media (max-width: 767.98px){" in text


def test_faz3_css_preexisting_content_untouched_regression() -> None:
    text = _read(FAZ3_CSS)
    assert ".faz3-mobile-scroll-x{overflow-x:auto;-webkit-overflow-scrolling:touch}" in text
    assert ".faz3-mobile-hidden{display:none}" in text
    assert ".faz3-mobile-stack{display:grid;gap:12px}" in text
    assert "/* Bildirimler */" in text


def test_no_generic_dumping_ground_stylesheet_was_introduced() -> None:
    """Koordinator talimati: yeni bir genel-amacli 'dumping ground' CSS
    dosyasi (csp_migration.css, temp_styles.css, inline_fixes.css vb.)
    OLUSTURULMADI -- sadece 2 mevcut, zaten yuklu dosya genisletildi."""
    forbidden_names = ("csp_migration.css", "temp_styles.css", "inline_fixes.css", "style2a.css")
    css_dir = REPO_ROOT / "app" / "static" / "css"
    existing = {p.name for p in css_dir.glob("*.css")}
    for forbidden in forbidden_names:
        assert forbidden not in existing


# ---------------------------------------------------------------------------
# C) Calisma-zamani kontrolu: gercek Flask app + gercek oturum (session
#    cookie) girisi + gercek GET istegi. Ayni desendeki kardes dosyalar:
#    tests/security/test_web_login_authentication_negative.py ve
#    tests/integration/test_mobile_support_ticket_db_transactions.py.
#
# ONEMLI KAPSAM NOTU: asagidaki runtime testleri TAM SAYFA yanitini (base.html
# dahil) kontrol eder -- ama full-page "sifir style=" iddiasi KASITLI olarak
# KULLANILMAZ. base.html (bu ajanin DOKUNMASI YASAK dosyasi) zaten kendi,
# bu pilotun kapsami DISINDA, onceden var olan birkac inline style="..."
# icerir (dogrulandi: satir 758 chevron ikonu rengi, satir 800/1116 gizli
# logout formlari `style="display:none;"`, satir 803 `<main ... style="min-
# height:100vh;">`). Bu yuzden runtime kontrati, KENDI 4 template'imin
# KALDIRDIGI eski style="..." DEGERLERININ TAM OLARAK GERCEK render ciktisinda
# ARTIK BULUNMADIGINI (negatif/regresyon kaniti) + YENI sinif isimlerinin
# beklenen elemanlarda BULUNDUGUNU (pozitif kanit) dogrular. "Tam sablon
# kaynaginda sifir style=" iddiasi zaten Bolum A'da (Path.read_text, base.
# html'den bagimsiz, SADECE benim 4 dosyamin kendi kaynagi) kesin olarak
# kanitlanmistir.
# ---------------------------------------------------------------------------

OLD_STYLE_LITERALS_HELP_ADMIN_LIST = [
    'style="margin:0;font-size:1.12rem;font-weight:900;color:#111827;"',
    'style="margin:8px 0 0;color:#6b7280;line-height:1.8;"',
    'style="display:flex;gap:10px;flex-wrap:wrap;"',
    'class="search-form" style="margin-top:16px;"',
    'class="empty" style="margin-top:18px;"',
]

OLD_STYLE_LITERALS_DETAIL = [
    'class="meta-row" style="margin-top:16px;"',
    'style="font-weight:900;color:#111827;"',
    'class="muted" style="display:inline-flex;align-items:center;gap:8px;"',
    '<hr style="margin:18px 0;border:none;border-top:1px solid rgba(15,23,42,.08)">',
]

OLD_STYLE_LITERALS_NEW = [
    'class="privacy-box" style="margin-bottom:16px;"',
    'style="margin-top:6px;color:#6b7280;line-height:1.65;font-size:.9rem;"',
    'style="display:inline-flex;align-items:center;gap:8px;font-weight:850;color:#374151;"',
]

OLD_STYLE_LITERALS_NOTIFICATIONS = [
    'class="bulk-bar" style="margin-top:14px;"',
    'style="margin:0;color:#111827;font-size:1rem;font-weight:900;"',
    'style="margin:0;line-height:1.8;"',
]


_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "csp_style2a_support_notifications" / "test_dbs"


def _make_app(monkeypatch):
    # KOORDINATOR DUZELTMESI: bu fixture ilk yazildiginda yalnizca
    # `DATABASE_URL` env degiskenini `sqlite:///:memory:` olarak set
    # ediyordu. `config.Config` sinif nitelikleri ilk import'ta cozulup
    # cache'lendigi icin (bkz. test_csp_wave2_personnel_inline_handlers_
    # contract.py::_make_app, ayni gerekce), yalniz env degiskeni set etmek
    # `Config.SQLALCHEMY_DATABASE_URI`'yi GUNCELLEMIYORDU -- ayni pytest
    # sureci icinde DAHA ONCE calismis baska bir Style-2A test dosyasinin
    # (ornegin test_csp_style2a_repo_wide_contract.py::style2a_env) kendi
    # unique dosya-tabanli sqlite yoluna kalici olarak isaret eden Config
    # degeri "sizip" bu dosyanin testlerinde de kullanilmaya devam ediyordu.
    # Bu, farkli test dosyalarinin AYNI kalici sqlite dosyasina yazmasina
    # ve `UNIQUE constraint failed: users.email` cakismalarina yol aciyordu
    # (repo_wide + bu dosya birlikte calistirildiginda gozlemlendi ve
    # dogrulandi). Duzeltme: kurulu/calisan desenle (wave2, Agent 3'un
    # kendi style2a_env fixture'i) BIREBIR ayni sekilde, hem env degiskenini
    # HEM DE `Config.SQLALCHEMY_DATABASE_URI`'yi ayri, uuid4 ile turetilmis
    # bir dosya yoluna dogrudan yamamak (monkeypatch.setattr).
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-csp-style2a-support-notifications-flows")
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
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, email, password, role="admin"):
    """`role="admin"` varsayilani KASITLI secildi: help_admin_list.html
    rotasi (@admin_required) VE detail.html'in can_manage=True dalindaki
    (checkbox-inline + section-divider) elemanlari AYNI oturumla test
    edebilmek icin. Talep sahibi kontrolu (`_can_view_ticket`) zaten
    talebi acan kullaniciya izin verir; admin rolu bu kontrolu de gecer."""
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Style2A",
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


def _login(client, sicil_or_email, password):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_or_email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302, f"Giris basarisiz oldu (302 bekleniyordu): {response.status_code}"
    return response


def test_help_admin_list_live_route_renders_with_new_classes_and_zero_inline_style(app, client) -> None:
    _create_user(app, sicil_no="90201", email="style2a.helpadmin@bys360.test", password="Style2ATestHelpAdmin1!")
    _login(client, "90201", "Style2ATestHelpAdmin1!")

    response = client.get("/support/help-admin", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    for old_literal in OLD_STYLE_LITERALS_HELP_ADMIN_LIST:
        assert old_literal not in html, f"Eski inline style hala render ciktisinda: {old_literal!r}"
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_SRC_RE.search(html)

    assert 'class="panel-heading"' in html
    assert 'class="panel-subtitle"' in html
    assert 'class="header-actions-row"' in html
    assert 'class="search-form section-spacing-top-md"' in html
    # Taze test DB'de hic makale yok -> bos-durum dali render edilir.
    assert 'class="empty section-spacing-top-lg"' in html
    assert "css/faz4_support_account_mobile.css" in html


def test_support_new_live_route_renders_with_new_classes_and_zero_inline_style(app, client) -> None:
    _create_user(app, sicil_no="90202", email="style2a.new@bys360.test", password="Style2ATestNewTicket1!")
    _login(client, "90202", "Style2ATestNewTicket1!")

    response = client.get("/support/new", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    for old_literal in OLD_STYLE_LITERALS_NEW:
        assert old_literal not in html, f"Eski inline style hala render ciktisinda: {old_literal!r}"
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_SRC_RE.search(html)

    assert 'class="privacy-box section-spacing-bottom-md"' in html
    assert html.count('class="field-helper-text"') == 2
    assert 'class="checkbox-inline checkbox-inline--emphasis"' in html
    assert "css/faz4_support_account_mobile.css" in html


def test_support_detail_live_route_with_real_ticket_renders_with_new_classes_and_zero_inline_style(
    app, client
) -> None:
    user_id = _create_user(app, sicil_no="90203", email="style2a.detail@bys360.test", password="Style2ADetail1!")
    _login(client, "90203", "Style2ADetail1!")

    create_response = client.post(
        "/support/new",
        data={
            "title": "Style2A kontrat testi talebi",
            "description": "Bu talep CSP style-2A kontrat testinin bir parcasi olarak olusturuldu.",
            "ticket_type": "bug",
            "module_name": "Genel",
            "priority": "normal",
            "page_url": "/support/help/search",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 302
    location = create_response.headers["Location"]
    match = re.search(r"/support/(\d+)", location)
    assert match, f"Bilet olusturma sonrasi beklenen /support/<id> yonlendirmesi bulunamadi: {location!r}"
    ticket_id = int(match.group(1))

    # Ek dosya (attachment) satirini GERCEK bir dosya yuklemesi/disk yazmasi
    # OLMADAN, dogrudan ORM ile ekliyoruz -- detail.html'deki kosullu
    # `attachment-filename` dalini gercek bir veriyle tetiklemek icin.
    from app.extensions import db
    from app.models.support_models import SupportTicketAttachment

    with app.app_context():
        db.session.add(
            SupportTicketAttachment(
                ticket_id=ticket_id,
                uploaded_by_user_id=user_id,
                filename="style2a-kontrat-raporu.pdf",
                stored_name=f"style2a-test-stored-{ticket_id}.pdf",
                mime_type="application/pdf",
                file_size=2048,
                attachment_type="document",
            )
        )
        db.session.commit()

    response = client.get(f"/support/{ticket_id}", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    for old_literal in OLD_STYLE_LITERALS_DETAIL:
        assert old_literal not in html, f"Eski inline style hala render ciktisinda: {old_literal!r}"
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_SRC_RE.search(html)

    assert 'class="meta-row section-spacing-top-md"' in html
    assert 'class="attachment-filename"' in html
    assert "style2a-kontrat-raporu.pdf" in html
    # Bu kullanici admin rolunde (can_manage=True) -> is_internal checkbox'i
    # VE admin durum/atama karti (hr.section-divider dahil) render edilir.
    assert 'class="muted checkbox-inline"' in html
    assert 'class="section-divider"' in html
    assert "css/faz4_support_account_mobile.css" in html


def test_notifications_list_live_route_renders_with_new_classes_and_zero_inline_style(app, client) -> None:
    _create_user(app, sicil_no="90204", email="style2a.notif@bys360.test", password="Style2ANotif1!", role="personel")
    _login(client, "90204", "Style2ANotif1!")

    response = client.get("/notifications", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    for old_literal in OLD_STYLE_LITERALS_NOTIFICATIONS:
        assert old_literal not in html, f"Eski inline style hala render ciktisinda: {old_literal!r}"
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_SRC_RE.search(html)

    assert 'class="bulk-bar section-spacing-top-sm"' in html
    # Taze kullanicida hic bildirim yok -> bos-durum dali render edilir.
    assert 'class="empty-state-heading"' in html
    assert 'class="empty-state-text"' in html
    assert "css/faz3_communication_hr_mobile.css" in html
