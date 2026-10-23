"""BYS360 UX pilot -- Destek -> Yeni Talep Aç (`/support/new`) sözleşme testleri.

Kapsam (proje sahibinin 16 Ekim 2026 Kapı A onayı, "BYS360 Pilot Uygulama
Planı" sürüm 2, Bölüm 3 kabul matrisi):

    E1-E5, E9 : erişilebilir form (etiket, açıklama, hata özeti, odak, kontrast)
    D1-D8     : hata sonrası değer koruma, sızıntı yok, XSS kaçışı, mevcut
                kayıt/yetki/CSRF davranışı değişmedi
    K2, K5    : pilot şablonu CSP temiz; yeni CSS başka ekranlara sızmıyor

Bu dosya yalnız otomatik doğrulanabilen ölçütleri kapsar. Görsel, klavye,
ekran okuyucu ve gerçek cihaz ölçütleri (E6-E8, E10-E12 render kısmı, K5
görüntü karşılaştırması) test ortamında elle/Playwright ile doğrulanır ve
bu dosyada "geçti" sayılmaz.

Tüm kullanıcılar ve veriler sahtedir; veritabanı her test için ayrı, geçici
bir SQLite dosyasıdır. Ağ, e-posta veya gerçek dosya sistemi yüklemesi yoktur
(dosya yükleme testlerinde yükleme doğrulaması bilerek reddedilir).
"""
from __future__ import annotations

import inspect
import io
import re
import tempfile
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "app/templates/support/new.html"
MACROS = REPO_ROOT / "app/templates/_ui_form.html"
TOKENS_CSS = REPO_ROOT / "app/static/css/bys360_tokens.css"
COMPONENTS_CSS = REPO_ROOT / "app/static/css/bys360_components.css"
UI_FORM_JS = REPO_ROOT / "app/static/js/bys360_ui_form.js"

FORM_ID = "supportNewForm"
VISIBLE_FIELD_IDS = (
    "ticket-type",
    "ticket-module",
    "ticket-priority",
    "ticket-title",
    "ticket-description",
    "ticket-page-url",
    "ticket-attachment",
    "ticket-private",
)
GENERIC_ERROR = "Talebiniz kaydedilemedi. Girdiğiniz bilgiler korundu; lütfen tekrar deneyin. Sorun sürerse sistem yöneticisine bildirin."
RESELECT_MESSAGE = "Güvenlik nedeniyle seçtiğiniz dosya korunamadı. Gönderirken dosyayı yeniden seçin."
UPLOAD_RESELECT_MESSAGE = (
    "Dosya talebe eklenmedi. Göndermek için izin verilen türde bir dosyayı yeniden seçin "
    "veya dosya alanını boş bırakın."
)

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "ux_pilot_support_new" / "test_dbs"


# ---------------------------------------------------------------------------
# Uygulama, sahte kullanıcı ve oturum yardımcıları (mevcut CSP Style-2A
# sözleşme dosyasındaki çalışan desenle aynı).
# ---------------------------------------------------------------------------
def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-ux-pilot-support-new")
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
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, email, password, role="personel"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Sahte",
            soyad="Kullanici",
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
    assert response.status_code == 302, f"Giriş başarısız (302 bekleniyordu): {response.status_code}"


def _logged_in(app, client, *, sicil_no="TEST-PER-01", role="personel"):
    password = "UxPilotSahte1!"
    _create_user(app, sicil_no=sicil_no, email=f"{sicil_no.lower()}@bys360.test", password=password, role=role)
    _login(client, sicil_no, password)


def _ticket_counts(app):
    from app.extensions import db
    from app.models import SupportTicket, SupportTicketMessage, SupportTicketStatusHistory

    with app.app_context():
        return (
            db.session.query(SupportTicket).count(),
            db.session.query(SupportTicketStatusHistory).count(),
            db.session.query(SupportTicketMessage).count(),
        )


def _valid_form(**overrides):
    data = {
        "ticket_type": "bug",
        "module_name": "Performans Yönetimi",
        "priority": "high",
        "title": "Sahte konu: karne ekranında tarih görünmüyor",
        "description": "Sahte açıklama: test ortamında dönem filtresi seçildikten sonra tarih alanı boş geliyor.",
        "page_url": "/performance/dashboard",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Küçük, bağımlılıksız HTML ayrıştırıcı: form denetimleri ve etiketleri.
# ---------------------------------------------------------------------------
_VOID = {"input", "br", "hr", "img", "meta", "link", "source", "wbr", "col", "area", "base", "embed", "param", "track"}


class _FormScan(HTMLParser):
    def __init__(self, form_id: str):
        super().__init__(convert_charrefs=True)
        self.form_id = form_id
        self.form_depth = 0
        self.depth = 0
        self.label_stack: list[dict[str, Any]] = []
        self.controls: list[dict[str, Any]] = []
        self.labels_for: dict[str, str] = {}
        self.ids: set[str] = set()
        self.elements: list[tuple[str, dict[str, Any]]] = []
        self._label_text: list[list[str]] = []

    def handle_starttag(self, tag, attrs_list):
        attrs: dict[str, Any] = {k: (v if v is not None else "") for k, v in attrs_list}
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "form" and attrs.get("id") == self.form_id:
            self.form_depth = 1
            self.elements.append((tag, attrs))
            return
        if self.form_depth:
            self.elements.append((tag, attrs))
            if tag not in _VOID:
                self.form_depth += 1
            if tag == "label":
                self.label_stack.append(attrs)
                self._label_text.append([])
            if tag in {"input", "select", "textarea"}:
                if (attrs.get("type") or "").lower() in {"hidden", "submit", "button", "reset"}:
                    return
                attrs = dict(attrs)
                attrs["_tag"] = tag
                attrs["_wrapped_by_label"] = bool(self.label_stack)
                self.controls.append(attrs)

    def handle_startendtag(self, tag, attrs_list):
        self.handle_starttag(tag, attrs_list)
        if self.form_depth and tag not in _VOID:
            self.form_depth -= 1

    def handle_endtag(self, tag):
        if not self.form_depth:
            return
        if tag == "label" and self.label_stack:
            attrs = self.label_stack.pop()
            text = " ".join(self._label_text.pop()).strip()
            if attrs.get("for"):
                self.labels_for[attrs["for"]] = text
        if tag not in _VOID:
            self.form_depth -= 1

    def handle_data(self, data):
        for bucket in self._label_text:
            bucket.append(data.strip())


def _scan(html: str) -> _FormScan:
    scanner = _FormScan(FORM_ID)
    scanner.feed(html)
    assert scanner.elements, f"#{FORM_ID} formu yanıtta bulunamadı"
    return scanner


def _control(scan: _FormScan, control_id: str) -> dict[str, Any]:
    for control in scan.controls:
        if control.get("id") == control_id:
            return control
    raise AssertionError(f"#{control_id} denetimi formda yok")


# ---------------------------------------------------------------------------
# E1-E4: etiket, açıklama, hata özeti, aria-invalid
# ---------------------------------------------------------------------------
def test_e1_every_visible_control_has_programmatic_label(app, client) -> None:
    _logged_in(app, client)
    response = client.get("/support/new")
    assert response.status_code == 200
    scan = _scan(response.get_data(as_text=True))

    ids = [str(c.get("id") or "") for c in scan.controls]
    assert sorted(ids) == sorted(VISIBLE_FIELD_IDS), f"Beklenmeyen görünür denetim kümesi: {ids!r}"
    unlabeled = [
        c.get("id")
        for c in scan.controls
        if not (c.get("id") in scan.labels_for or c.get("_wrapped_by_label") or c.get("aria-label"))
    ]
    assert unlabeled == [], f"Programatik etiketi olmayan alanlar: {unlabeled!r}"
    for control_id in VISIBLE_FIELD_IDS:
        if control_id in scan.labels_for:
            assert scan.labels_for[control_id], f"#{control_id} etiketi boş"


def test_e2_help_text_is_linked_with_aria_describedby(app, client) -> None:
    _logged_in(app, client)
    scan = _scan(client.get("/support/new").get_data(as_text=True))
    for control_id in VISIBLE_FIELD_IDS:
        described = _control(scan, control_id).get("aria-describedby", "").split()
        assert described, f"#{control_id} aria-describedby taşımıyor"
        missing = [ref for ref in described if ref not in scan.ids]
        assert missing == [], f"#{control_id} var olmayan öğelere işaret ediyor: {missing!r}"


def test_e2_required_fields_are_marked_visually_and_programmatically(app, client) -> None:
    _logged_in(app, client)
    html = client.get("/support/new").get_data(as_text=True)
    scan = _scan(html)
    for control_id in ("ticket-title", "ticket-description"):
        control = _control(scan, control_id)
        assert "required" in control, f"#{control_id} required değil"
        assert control.get("aria-required") == "true"
        assert "(zorunlu)" in scan.labels_for[control_id]
    assert "Zorunlu alanlar" in html
    assert _control(scan, "ticket-title").get("maxlength") == "255"
    assert _control(scan, "ticket-description").get("maxlength") == "4000"


def test_e3_e4_error_summary_and_invalid_fields_after_empty_submit(app, client) -> None:
    _logged_in(app, client)
    response = client.post("/support/new", data=_valid_form(title="   ", description=""))
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    scan = _scan(html)

    summary = re.search(r'<div[^>]*id="bysErrorSummary"[^>]*>', html)
    assert summary, "Hata özeti yok"
    assert 'role="alert"' in summary.group(0)
    assert 'tabindex="-1"' in summary.group(0)
    assert "Talep kaydedilemedi: 2 alanı düzeltin" in html
    assert 'href="#ticket-title"' in html
    assert 'href="#ticket-description"' in html
    assert "Konu alanını doldurun." in html
    assert "Açıklama alanını doldurun." in html

    for control_id in VISIBLE_FIELD_IDS:
        control = _control(scan, control_id)
        if control_id in {"ticket-title", "ticket-description"}:
            assert control.get("aria-invalid") == "true", f"#{control_id} aria-invalid değil"
            assert f"{control_id}-error" in control.get("aria-describedby", "").split()
            assert f"{control_id}-error" in scan.ids
        else:
            assert "aria-invalid" not in control, f"#{control_id} hatasız olduğu halde aria-invalid"


def test_no_error_summary_on_first_visit(app, client) -> None:
    _logged_in(app, client)
    html = client.get("/support/new").get_data(as_text=True)
    assert 'id="bysErrorSummary"' not in html
    assert 'aria-invalid="true"' not in html


# ---------------------------------------------------------------------------
# E5: odak yönetimi (statik + davranış altyapısı)
# ---------------------------------------------------------------------------
def test_e5_focus_management_script_is_loaded_and_targets_summary(app, client) -> None:
    _logged_in(app, client)
    html = client.post("/support/new", data=_valid_form(title="", description="")).get_data(as_text=True)
    assert "js/bys360_ui_form.js" in html
    js = UI_FORM_JS.read_text(encoding="utf-8")
    assert "bysErrorSummary" in js
    assert ".focus(" in js
    assert "pageshow" in js  # geri gelindiğinde gönderim düğmesi yeniden etkin
    # Hata özeti ana içerikte formdan önce gelir (JS kapalıyken de ilk okunan hata bilgisi).
    assert html.index('id="bysErrorSummary"') < html.index(f'id="{FORM_ID}"')


# ---------------------------------------------------------------------------
# D1-D5: doğrulama, değer koruma, dosya mesajı, sızıntı yok, kaçış
# ---------------------------------------------------------------------------
def test_d1_invalid_submit_writes_nothing(app, client) -> None:
    _logged_in(app, client)
    before = _ticket_counts(app)
    client.post("/support/new", data=_valid_form(title="  ", description="   "))
    assert _ticket_counts(app) == before


def test_d2_all_seven_values_survive_a_validation_error(app, client) -> None:
    _logged_in(app, client)
    data = _valid_form(
        title="",
        description="Sahte açıklama korunmalı: satır 1\nsatır 2",
        ticket_type="permission",
        module_name="İletişim ve Anket",
        priority="critical",
        page_url="/communication/sahte",
        is_private="1",
    )
    before = _ticket_counts(app)
    html = client.post("/support/new", data=data).get_data(as_text=True)
    scan = _scan(html)

    assert _ticket_counts(app) == before
    assert _control(scan, "ticket-page-url").get("value") == "/communication/sahte"
    assert _control(scan, "ticket-private").get("checked") is not None
    assert "Sahte açıklama korunmalı: satır 1\nsatır 2</textarea>" in html
    assert re.search(r'<option value="permission"\s+selected', html)
    assert re.search(r'<option value="İletişim ve Anket"\s+selected', html)
    assert re.search(r'<option value="critical"\s+selected', html)


def test_d2_title_value_survives_when_description_is_missing(app, client) -> None:
    _logged_in(app, client)
    scan = _scan(client.post("/support/new", data=_valid_form(description="")).get_data(as_text=True))
    assert _control(scan, "ticket-title").get("value") == "Sahte konu: karne ekranında tarih görünmüyor"


def test_d2_unknown_choice_is_not_reflected_as_selected(app, client) -> None:
    _logged_in(app, client)
    html = client.post("/support/new", data=_valid_form(title="", priority="hacked")).get_data(as_text=True)
    assert 'value="hacked"' not in html


def test_d3_reselect_message_when_a_file_was_chosen(app, client) -> None:
    _logged_in(app, client)
    data = _valid_form(title="")
    data["attachment"] = (io.BytesIO(b"%PDF-1.4 sahte"), "sahte-ek.pdf")
    html = client.post("/support/new", data=data, content_type="multipart/form-data").get_data(as_text=True)
    assert html.count(RESELECT_MESSAGE) >= 2, "Dosya yeniden seçim mesajı hem özette hem alanda olmalı"
    assert "sahte-ek.pdf" in html


def _summary_html(html: str) -> str:
    match = re.search(r'<div[^>]*id="bysErrorSummary".*?</ul>', html, re.DOTALL)
    assert match, "Hata özeti yok"
    return match.group(0)


def _field_paragraph(html: str, paragraph_id: str) -> str:
    match = re.search(rf'<p[^>]*id="{paragraph_id}"[^>]*>.*?</p>', html, re.DOTALL)
    assert match, f"#{paragraph_id} alan mesajı yok"
    return match.group(0)


def test_d3_reselect_message_is_in_summary_and_linked_on_the_field(app, client) -> None:
    _logged_in(app, client)
    data = _valid_form(title="")
    data["attachment"] = (io.BytesIO(b"%PDF-1.4 sahte"), "sahte-ek.pdf")
    html = client.post("/support/new", data=data, content_type="multipart/form-data").get_data(as_text=True)
    scan = _scan(html)

    summary = _summary_html(html)
    assert RESELECT_MESSAGE in summary
    assert 'href="#ticket-attachment"' in summary
    assert RESELECT_MESSAGE in _field_paragraph(html, "ticket-attachment-reselect")
    control = _control(scan, "ticket-attachment")
    assert "ticket-attachment-reselect" in control.get("aria-describedby", "").split()
    # Dosyanın kendisi hatalı değil; yalnız konu alanı hatalı.
    assert "aria-invalid" not in control
    assert "ticket-attachment-error" not in scan.ids
    assert "Talep kaydedilemedi: 1 alanı düzeltin" in html


def test_d3_upload_rejection_keeps_security_message_and_asks_to_reselect(app, client) -> None:
    _logged_in(app, client)
    before = _ticket_counts(app)
    data = _valid_form()
    data["attachment"] = (io.BytesIO(b"MZ sahte"), "sahte.exe")
    html = client.post("/support/new", data=data, content_type="multipart/form-data").get_data(as_text=True)
    assert _ticket_counts(app) == before
    scan = _scan(html)

    security_message = "Riskli dosya uzantısı kabul edilmedi: .exe"
    # Alan altında: güvenlik hatası ve yeniden seçim talimatı ayrı, ikisi de bağlı.
    assert security_message in _field_paragraph(html, "ticket-attachment-error")
    assert UPLOAD_RESELECT_MESSAGE in _field_paragraph(html, "ticket-attachment-reselect")
    control = _control(scan, "ticket-attachment")
    described_by = control.get("aria-describedby", "").split()
    assert described_by == ["ticket-attachment-help", "ticket-attachment-error", "ticket-attachment-reselect"]
    assert control.get("aria-invalid") == "true"

    # Hata özetinde: tek madde, ikisi birlikte, dosya alanına bağlı.
    summary = _summary_html(html)
    assert summary.count('href="#ticket-attachment"') == 1
    assert security_message in summary
    assert UPLOAD_RESELECT_MESSAGE in summary
    assert "Talep kaydedilemedi: 1 alanı düzeltin" in html
    # Genel tarayıcı mesajı bu durumda kullanılmaz; dosya adı kullanıcıya geri gösterilir (kaçışlı).
    assert RESELECT_MESSAGE not in html
    assert "Önceki seçim: sahte.exe" in html


def test_d3_no_reselect_message_without_file(app, client) -> None:
    _logged_in(app, client)
    html = client.post("/support/new", data=_valid_form(title="")).get_data(as_text=True)
    assert RESELECT_MESSAGE not in html
    assert UPLOAD_RESELECT_MESSAGE not in html
    assert "ticket-attachment-reselect" not in html


def test_d3_upload_validation_message_is_shown_on_the_file_field(app, client) -> None:
    _logged_in(app, client)
    before = _ticket_counts(app)
    data = _valid_form()
    data["attachment"] = (io.BytesIO(b"MZ sahte"), "sahte.exe")
    html = client.post("/support/new", data=data, content_type="multipart/form-data").get_data(as_text=True)
    assert _ticket_counts(app) == before
    scan = _scan(html)
    assert _control(scan, "ticket-attachment").get("aria-invalid") == "true"
    assert "ticket-attachment-error" in scan.ids
    assert _control(scan, "ticket-title").get("value") == _valid_form()["title"]


def test_d4_unexpected_failure_shows_only_the_generic_message(app, client, monkeypatch) -> None:
    import app.support.routes as support_routes

    _logged_in(app, client)
    secret_detail = "psycopg2.errors.UndefinedTable: SELECT secret_col FROM users_hidden -- /srv/bys360/app/hidden_module.py line 42"

    def _boom(*_args, **_kwargs):
        raise RuntimeError(secret_detail)

    logged: list[str] = []

    class _SpyLogger:
        def exception(self, msg, *args, **_kwargs):
            logged.append(msg % args if args else msg)

        def __getattr__(self, name):
            return getattr(support_routes.logging.getLogger(support_routes.__name__), name)

    monkeypatch.setattr(support_routes, "notify_support_ticket_created", _boom)
    monkeypatch.setattr(support_routes, "logger", _SpyLogger())

    before = _ticket_counts(app)
    response = client.post("/support/new", data=_valid_form())
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert GENERIC_ERROR in html
    for leaked in ("RuntimeError", "psycopg2", "secret_col", "users_hidden", "/srv/bys360", "hidden_module", "Traceback"):
        assert leaked not in html, f"Kullanıcıya iç ayrıntı sızdı: {leaked!r}"
    assert _ticket_counts(app) == before
    assert any(secret_detail in entry for entry in logged), "İstisna sunucu log'una yazılmadı"
    # Metin korunur.
    assert _valid_form()["description"] in html


def test_d5_reflected_values_are_escaped(app, client) -> None:
    _logged_in(app, client)
    payload = '<script>alert("x")</script>'
    html = client.post("/support/new", data=_valid_form(title=payload, description="")).get_data(as_text=True)
    assert payload not in html
    assert "&lt;script&gt;alert(" in html


# ---------------------------------------------------------------------------
# Rol matrisi: pilot yalnız personel ile değil, birim sorumlusu ve admin ile de
# aynı davranır; rol bazlı sekmeler ve diğer destek ekranları değişmedi.
# Menü izinleri bu PR'da değişmez; testler yalnız mevcut davranışı sabitler.
# ---------------------------------------------------------------------------
PILOT_ROLES = ("personel", "birim_sorumlusu", "admin")


def _support_tabs(html: str) -> list[str]:
    match = re.search(r'<div class="support-tabs">(.*?)</div>', html, re.DOTALL)
    assert match, "Destek sekmeleri yok"
    return re.findall(r"</i> ([^<]+)</a>", match.group(1))


@pytest.mark.parametrize("role", PILOT_ROLES)
def test_role_matrix_form_renders_validates_and_submits(app, client, role) -> None:
    _logged_in(app, client, sicil_no=f"TEST-{role.upper()}-01", role=role)

    response = client.get("/support/new")
    assert response.status_code == 200
    scan = _scan(response.get_data(as_text=True))
    assert {c.get("id") for c in scan.controls} == set(VISIBLE_FIELD_IDS)

    invalid = client.post("/support/new", data=_valid_form(title=""))
    assert invalid.status_code == 200
    invalid_html = invalid.get_data(as_text=True)
    assert "Konu alanını doldurun." in _summary_html(invalid_html)
    assert _control(_scan(invalid_html), "ticket-title").get("aria-invalid") == "true"

    rejected = _valid_form()
    rejected["attachment"] = (io.BytesIO(b"MZ sahte"), "sahte.exe")
    rejected_html = client.post("/support/new", data=rejected, content_type="multipart/form-data").get_data(as_text=True)
    assert UPLOAD_RESELECT_MESSAGE in _summary_html(rejected_html)

    before = _ticket_counts(app)
    created = client.post("/support/new", data=_valid_form())
    assert created.status_code == 302
    assert re.fullmatch(r"/support/\d+", created.headers["Location"])
    assert _ticket_counts(app) == (before[0] + 1, before[1] + 1, before[2] + 1)


@pytest.mark.parametrize(
    ("role", "assigned_visible"),
    (("personel", False), ("birim_sorumlusu", True), ("admin", True)),
)
def test_role_matrix_support_tabs_and_neighbour_screens_are_unchanged(app, client, role, assigned_visible) -> None:
    _logged_in(app, client, sicil_no=f"TEST-{role.upper()}-02", role=role)
    tabs = _support_tabs(client.get("/support/new").get_data(as_text=True))
    assert tabs[:3] == ["Yardım Merkezi", "Yeni Talep Aç", "Taleplerim"]
    assert ("Bana Atananlar" in tabs) is assigned_visible

    # Rehber arama ekranı henüz tasarım sistemine geçmedi: pilot varlıkları sızmamalı.
    # (/support -- Yardım Merkezi -- dalga 4'te geçti; aşağıda ayrıca denetlenir.)
    neighbour = client.get("/support/help/search?q=talep")
    assert neighbour.status_code == 200
    neighbour_html = neighbour.get_data(as_text=True)
    assert "bys360_components.css" not in neighbour_html
    assert "bys360_ui_form.js" not in neighbour_html
    help_center = client.get("/support")
    assert help_center.status_code == 200
    help_center_html = help_center.get_data(as_text=True)
    assert "bys360_components.css" in help_center_html
    assert "bys360_ui_form.js" not in help_center_html
    # /support/my-tickets dalga 2'de tasarım sistemine geçti (DESIGN_SYSTEM_TEMPLATES);
    # form betiği yine yalnız pilot formunda yüklenir.
    my_tickets = client.get("/support/my-tickets")
    assert my_tickets.status_code == 200
    my_tickets_html = my_tickets.get_data(as_text=True)
    assert "bys360_components.css" in my_tickets_html
    assert "bys360_ui_form.js" not in my_tickets_html
    assert client.get("/support/assigned").status_code == (200 if assigned_visible else 403)


def test_role_matrix_personel_cannot_reach_staff_support_screens(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-PERSONEL-03", role="personel")
    tabs = _support_tabs(client.get("/support/new").get_data(as_text=True))
    assert tabs == ["Yardım Merkezi", "Yeni Talep Aç", "Taleplerim"]
    for path in ("/support/assigned", "/support/all", "/support/help-admin"):
        assert client.get(path).status_code == 403, path


# ---------------------------------------------------------------------------
# D6-D8: mevcut kayıt, CSRF ve yetki davranışı değişmedi
# ---------------------------------------------------------------------------
def test_d6_valid_submit_still_creates_ticket_and_redirects(app, client) -> None:
    _logged_in(app, client)
    before = _ticket_counts(app)
    response = client.post("/support/new", data=_valid_form(is_private="1"), follow_redirects=False)
    assert response.status_code == 302
    assert re.search(r"/support/\d+", response.headers["Location"])
    after = _ticket_counts(app)
    assert after == (before[0] + 1, before[1] + 1, before[2] + 1)

    from app.extensions import db
    from app.models import SupportTicket

    with app.app_context():
        ticket = db.session.query(SupportTicket).order_by(SupportTicket.id.desc()).first()
        assert ticket is not None
        assert ticket.title == _valid_form()["title"]
        assert ticket.ticket_type == "bug"
        assert ticket.priority == "high"
        assert ticket.is_private is True

    followed = client.get(response.headers["Location"])
    assert "Talebiniz kaydedildi." in followed.get_data(as_text=True)


def test_d7_form_still_carries_csrf_token_and_csrf_protection_is_registered(app, client) -> None:
    _logged_in(app, client)
    scan = _scan(client.get("/support/new").get_data(as_text=True))
    hidden = [attrs for tag, attrs in scan.elements if tag == "input" and attrs.get("name") == "csrf_token"]
    assert len(hidden) == 1 and hidden[0].get("value"), "Formda CSRF belirteci yok"
    assert "csrf" in app.extensions, "CSRFProtect uygulamaya kayıtlı değil"


def test_d8_anonymous_user_is_redirected_to_login(client) -> None:
    response = client.get("/support/new", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_d8_route_guards_are_unchanged() -> None:
    import app.support.routes as support_routes

    source = inspect.getsource(support_routes)
    block = source[source.index('@main_bp.route("/support/new"'):source.index("def support_new(")]
    assert "@login_required" in block
    assert '@menu_key_required("support_new")' in block


# ---------------------------------------------------------------------------
# K2: pilot şablonu CSP temiz
# ---------------------------------------------------------------------------
def test_k2_pilot_templates_have_no_inline_style_style_block_or_handler() -> None:
    for path in (TEMPLATE, MACROS):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\sstyle\s*=", text), f"{path.name}: satır içi style var"
        assert "<style" not in text.lower(), f"{path.name}: <style> bloğu var"
        assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE), f"{path.name}: satır içi olay işleyici var"
        assert "|safe" not in text, f"{path.name}: |safe kullanımı var"


def test_k2_existing_style2a_contract_markers_are_preserved() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'class="privacy-box section-spacing-bottom-md"' in text
    assert text.count('class="field-helper-text"') == 2
    assert 'class="checkbox-inline checkbox-inline--emphasis"' in text
    assert "css/faz4_support_account_mobile.css" in text


# ---------------------------------------------------------------------------
# K5 (statik kısım): yeni CSS başka ekranlara sızmaz; yalnız pilot yükler
# ---------------------------------------------------------------------------
def _css_rules(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    selectors: list[str] = []
    for match in re.finditer(r"([^{}]+)\{", text):
        head = match.group(1).strip()
        if not head or head.startswith("@"):
            continue
        selectors.extend(part.strip() for part in head.split(","))
    return selectors


def test_k5_token_css_is_scoped_and_never_touches_root() -> None:
    text = TOKENS_CSS.read_text(encoding="utf-8")
    assert ":root" not in text
    assert "!important" not in text
    for selector in _css_rules(text):
        assert selector.startswith(".bys-ui"), f"Kapsam dışı token seçicisi: {selector!r}"


def test_k5_component_css_selectors_are_all_bys_prefixed_and_scoped() -> None:
    text = COMPONENTS_CSS.read_text(encoding="utf-8")
    assert ":root" not in text
    assert "!important" not in text
    for selector in _css_rules(text):
        assert selector.startswith(".bys-ui"), f"Kapsam dışı bileşen seçicisi: {selector!r}"


# Tasarım sistemi dalga dalga yayılır; her yeni şablon burada açıkça listelenir
# ve kendi sözleşme testini taşır (dalga 2: tests/behavior/test_ux_wave2_support_list_contract.py,
# dalga 3: tests/behavior/test_ux_wave3_support_detail_contract.py,
# dalga 4: tests/behavior/test_ux_wave4_help_center_contract.py).
DESIGN_SYSTEM_TEMPLATES = {
    TEMPLATE,
    MACROS,
    REPO_ROOT / "app/templates/support/list.html",
    REPO_ROOT / "app/templates/support/detail.html",
    REPO_ROOT / "app/templates/support/index.html",
}


def test_k5_new_assets_are_loaded_only_by_the_pilot_template() -> None:
    names = ("bys360_tokens.css", "bys360_components.css", "bys360_ui_form.js", "_ui_form.html")
    offenders: list[str] = []
    for path in (REPO_ROOT / "app" / "templates").rglob("*.html"):
        if path in DESIGN_SYSTEM_TEMPLATES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders.extend(f"{path.relative_to(REPO_ROOT)}:{name}" for name in names if name in text)
    assert offenders == [], f"Pilot varlıkları başka şablonlarda kullanılıyor: {offenders!r}"


# ---------------------------------------------------------------------------
# E9: token kontrastı (WCAG göreli parlaklık formülü)
# ---------------------------------------------------------------------------
def _token(text: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}\s*:\s*(#[0-9A-Fa-f]{{6}})", text)
    assert match, f"{name} tokenı bulunamadı"
    return match.group(1)


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize(
    ("foreground", "background", "minimum"),
    [
        ("--bys-text", "--bys-surface", 4.5),
        ("--bys-text-secondary", "--bys-surface", 4.5),
        ("--bys-text-muted", "--bys-surface", 4.5),
        ("--bys-brand", "--bys-surface", 4.5),
        ("--bys-on-brand", "--bys-brand", 4.5),
        ("--bys-on-brand", "--bys-brand-hover", 4.5),
        ("--bys-danger", "--bys-danger-bg", 4.5),
        ("--bys-danger", "--bys-surface", 4.5),
        ("--bys-success", "--bys-success-bg", 4.5),
        ("--bys-warning", "--bys-warning-bg", 4.5),
        ("--bys-info", "--bys-info-bg", 4.5),
        ("--bys-border-control", "--bys-surface", 3.0),
        ("--bys-focus", "--bys-surface", 3.0),
    ],
)
def test_e9_token_contrast(foreground: str, background: str, minimum: float) -> None:
    text = TOKENS_CSS.read_text(encoding="utf-8")
    ratio = _contrast(_token(text, foreground), _token(text, background))
    assert ratio >= minimum, f"{foreground} / {background} kontrastı {ratio:.2f}:1 (< {minimum}:1)"


def test_brand_color_is_the_existing_corporate_bordo() -> None:
    text = TOKENS_CSS.read_text(encoding="utf-8")
    assert _token(text, "--bys-brand").upper() == "#8B0000"
    assert _token(text, "--bys-brand-hover").upper() == "#690000"


# ---------------------------------------------------------------------------
# TR: Zorunlu Türkçe arayüz standardı (proje sahibi kuralı, 16 Ekim 2026).
# Kullanıcıya görünen hiçbir metin İngilizce kelime içermez. Kapsam: pilot
# şablonun ürettiği alan (.support-learning-shell), metin düğümleri ve
# kullanıcıya görünen/okunan öznitelikler. Kod adları, URL'ler, alan adları ve
# kayıtlı değerler (option value) denetlenmez ve değiştirilmez.
#
# Tarayıcıya ait yerel dosya seçme düğmesinin yazısı ("Dosya Seç") HTML'de
# yoktur; kullanıcının tarayıcı/işletim sistemi diline göre çizilir ve bu
# testin kapsamı dışındadır.
# ---------------------------------------------------------------------------
UI_ENGLISH_DENYLIST = frozenset(
    (
        "about", "account", "accounts", "action", "actions", "add", "admin", "ai", "alert", "all", "analytics",
        "and", "apply", "approval", "approve", "archive", "archived", "assistant", "attachment", "attachments",
        "back", "browse", "button", "cancel", "card", "category", "change", "chat", "checkbox", "choose", "chosen",
        "clear", "click", "close", "confirm", "copy", "create", "dashboard", "date", "delete", "description",
        "detail", "details", "download", "draft", "drop", "dropdown", "edit", "email", "error", "event", "events",
        "export", "faq", "favorites", "feedback", "field", "fields", "file", "files", "filter", "filters", "for",
        "goal", "goals", "guide", "help", "history", "home", "info", "import", "invalid", "label", "learn",
        "learning", "list", "loading", "log", "login", "logout", "logs", "manager", "menu", "message", "messages",
        "meeting", "meetings", "modal", "module", "name", "new", "next", "notification", "notifications", "open",
        "optional", "overview", "page", "password", "pending", "performance", "placeholder", "please", "poll",
        "popup", "preview", "previous", "print", "priority", "profile", "publish", "published", "pulse", "reject",
        "report", "reports", "required", "reset", "result", "results", "role", "save", "score", "search", "select",
        "send", "settings", "share", "status", "submit", "success", "summary", "support", "survey", "surveys",
        "table", "target", "task", "tasks", "team", "teams", "the", "this", "ticket", "tickets", "time", "title",
        "toast", "toggle", "tooltip", "training", "tutorial", "type", "update", "upload", "url", "user", "username",
        "users", "valid", "view", "warning", "welcome", "widget", "with", "you", "your",
    )
)

# Büyük harfli kısaltmalar yalnız burada gerekçesiyle listelenirse kabul edilir.
UI_ACRONYM_EXCEPTIONS: dict[str, str] = {
    "BYS360": "Ürün adı (Bütünleşik Yönetim Sistemi 360).",
    "KPI": "Kurumda yerleşik kısaltma; pilotta Türkçe açıklamasıyla birlikte gösterilir: 'Performans Göstergesi (KPI)'.",
    "PNG": "Dosya biçimi adı; kullanıcı dosyasının uzantısında aynen görür.",
    "JPG": "Dosya biçimi adı; kullanıcı dosyasının uzantısında aynen görür.",
    "WEBP": "Dosya biçimi adı; kullanıcı dosyasının uzantısında aynen görür.",
    "PDF": "Dosya biçimi adı; Türkçede de aynen kullanılır.",
    "DOCX": "Dosya biçimi adı; yanında Türkçe açıklama/ürün adı (Word) verilir.",
    "XLSX": "Dosya biçimi adı; yanında Türkçe açıklama/ürün adı (Excel) verilir.",
    "TXT": "Dosya biçimi adı; yanında 'metin' açıklaması verilir.",
    "DTY": "Destek talebi başvuru numarasının Türkçe öneki (DTY-YYYYAAGG-XXXXXX); kaydın kimliğidir.",
}

_UI_TEXT_ATTRS = ("placeholder", "title", "aria-label", "alt", "data-bys-busy-text")
_UI_WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû0-9]+")
_UI_ACRONYM = re.compile(r"^[A-Z]{2,}[0-9]*$")
# Talep numarası bir veri kimliğidir (DTY-YYYYMMDD-XXXXXX, son kısım rastgele onaltılık):
# "DTY-20261017-DB7034" gibi bir numaranın "DB7034" parçası kısaltma sanılmamalı.
_UI_TICKET_NO = re.compile(r"\bDTY-\d{8}-[0-9A-F]{6}\b")
_UI_URL_PATH = re.compile(r"(?<![\w.])/[a-z][a-z0-9_-]*/[a-z0-9_/-]+", re.IGNORECASE)


class _VisibleUiText(HTMLParser):
    """Kök sınıfın altındaki görünür metin ve kullanıcıya okunan öznitelikler."""

    def __init__(self, root_class: str):
        super().__init__(convert_charrefs=True)
        self.root_class = root_class
        self.depth = 0
        self.skip = 0
        self.strings: list[str] = []

    def handle_starttag(self, tag, attrs_list):
        attrs = {k: (v or "") for k, v in attrs_list}
        if not self.depth:
            if self.root_class in attrs.get("class", "").split():
                self.depth = 1
            return
        if tag not in _VOID:
            self.depth += 1
        if tag in {"script", "style", "template"}:
            self.skip += 1
        for name in _UI_TEXT_ATTRS:
            if attrs.get(name):
                self.strings.append(attrs[name])
        if tag == "input" and attrs.get("type", "").lower() in {"submit", "button", "reset"} and attrs.get("value"):
            self.strings.append(attrs["value"])

    def handle_endtag(self, tag):
        if not self.depth or tag in _VOID:
            return
        if tag in {"script", "style", "template"}:
            self.skip -= 1
        self.depth -= 1

    def handle_data(self, data):
        if self.depth and not self.skip and data.strip():
            self.strings.append(" ".join(data.split()))


def _english_ui_findings(strings: list[str]) -> list[str]:
    findings: list[str] = []
    for text in strings:
        for path in _UI_URL_PATH.findall(text):
            findings.append(f"URL yolu görünür metinde: {path!r} <- {text!r}")
        for word in _UI_WORD.findall(_UI_TICKET_NO.sub(" ", text)):
            if word.lower() in UI_ENGLISH_DENYLIST:
                findings.append(f"İngilizce kelime: {word!r} <- {text!r}")
            elif _UI_ACRONYM.match(word) and word not in UI_ACRONYM_EXCEPTIONS:
                findings.append(f"Gerekçesiz kısaltma: {word!r} <- {text!r}")
    return findings


def test_tr_checker_ignores_random_ticket_number_suffix_but_not_real_acronyms() -> None:
    assert _english_ui_findings(["Destek talebi · DTY-20261017-DB7034"]) == []
    assert _english_ui_findings(["DTY-20261017-0A1B2C · Raporlama"]) == []
    assert _english_ui_findings(["Hata kodu DB7034"]) != [], "Talep numarası dışında kısaltma yine yakalanmalı"


def _pilot_ui_strings(html: str) -> list[str]:
    scanner = _VisibleUiText("support-learning-shell")
    scanner.feed(html)
    assert scanner.strings, "Pilot alanı (.support-learning-shell) yanıtta yok"
    return scanner.strings


def test_tr_language_checker_detects_english_and_unlisted_acronyms() -> None:
    """Denetleyici boş geçmesin: bilinen İngilizce örnekleri yakalamalı."""
    sample = (
        '<div class="support-learning-shell"><h2>Dashboard</h2><button>Save</button>'
        '<input placeholder="Search"><p>İlgili Sayfa URL</p><p>örn. /performance/dashboard</p>'
        '<span aria-label="AI destekli">x</span><p>Talebi Kaydet</p></div>'
    )
    findings = _english_ui_findings(_pilot_ui_strings(sample))
    joined = "\n".join(findings)
    for expected in ("'Dashboard'", "'Save'", "'Search'", "'URL'", "/performance/dashboard", "'AI'"):
        assert expected in joined, f"Denetleyici {expected} örneğini yakalamadı:\n{joined}"
    assert not _english_ui_findings(["Talebi Kaydet", "Gösterge Paneli", "PDF, Word (DOCX)"])


def test_tr_language_exceptions_are_justified() -> None:
    for acronym, reason in UI_ACRONYM_EXCEPTIONS.items():
        assert _UI_ACRONYM.match(acronym), f"{acronym!r} kısaltma biçiminde değil"
        assert len(reason.strip()) >= 15, f"{acronym!r} için gerekçe yok veya yetersiz"
    assert not (set(map(str.lower, UI_ACRONYM_EXCEPTIONS)) & UI_ENGLISH_DENYLIST)


@pytest.mark.parametrize("state", ["normal", "validation", "upload_rejected", "unexpected_error"])
def test_tr_pilot_screen_has_no_english_ui_text(app, client, monkeypatch, state) -> None:
    _logged_in(app, client)
    if state == "normal":
        html = client.get("/support/new").get_data(as_text=True)
    elif state == "validation":
        html = client.post("/support/new", data=_valid_form(title="", description="")).get_data(as_text=True)
    elif state == "upload_rejected":
        data = _valid_form()
        data["attachment"] = (io.BytesIO(b"MZ sahte"), "ornek.exe")
        html = client.post("/support/new", data=data, content_type="multipart/form-data").get_data(as_text=True)
    else:
        import app.support.routes as support_routes

        def _boom(*_args, **_kwargs):
            raise RuntimeError("OperationalError: no such table users_hidden")

        monkeypatch.setattr(support_routes, "notify_support_ticket_created", _boom)
        html = client.post("/support/new", data=_valid_form()).get_data(as_text=True)
        assert GENERIC_ERROR in html
    findings = _english_ui_findings(_pilot_ui_strings(html))
    assert findings == [], "Kullanıcıya görünen İngilizce metin:\n" + "\n".join(findings)


def test_tr_document_title_and_busy_text_are_turkish(app, client) -> None:
    _logged_in(app, client)
    html = client.get("/support/new").get_data(as_text=True)
    title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert title and not _english_ui_findings([title.group(1)]), title
    assert "'Kaydediliyor…'" in UI_FORM_JS.read_text(encoding="utf-8")


def test_tr_upload_security_messages_shown_on_the_pilot_are_turkish() -> None:
    source = (REPO_ROOT / "app/security/upload_security.py").read_text(encoding="utf-8")
    messages = re.findall(r'UploadValidationError\(\s*f?"([^"]+)"', source)
    assert len(messages) >= 10, "UploadValidationError mesajları bulunamadı"
    findings = _english_ui_findings([re.sub(r"\{[^}]*\}", "", m) for m in messages])
    assert findings == [], "\n".join(findings)


def test_tr_module_display_labels_keep_stored_values(app, client) -> None:
    """Görünen ad Türkçeleşir; kayıtlı değer ve mevcut veriler değişmez."""
    _logged_in(app, client)
    html = client.get("/support/new").get_data(as_text=True)
    assert re.search(r'<option value="Raporlama ve Dashboard">Raporlama ve Gösterge Paneli</option>', html)
    assert re.search(r'<option value="KPI / Hedef Yönetimi">Performans Göstergesi \(KPI\) / Hedef Yönetimi</option>', html)

    response = client.post("/support/new", data=_valid_form(module_name="Raporlama ve Dashboard"))
    assert response.status_code == 302

    from app.extensions import db
    from app.models import SupportTicket

    with app.app_context():
        ticket = db.session.query(SupportTicket).order_by(SupportTicket.id.desc()).first()
        assert ticket is not None
        assert ticket.module_name == "Raporlama ve Dashboard"

    invalid = client.post("/support/new", data=_valid_form(title="", module_name="Raporlama ve Dashboard")).get_data(as_text=True)
    assert re.search(r'<option value="Raporlama ve Dashboard"\s+selected>Raporlama ve Gösterge Paneli</option>', invalid)
