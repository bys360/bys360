"""BYS360 UX dalga 3 -- Destek talep detayı (support/detail.html) sözleşme testleri.

Şablon /support/<id> rotasında kullanılır. Bu dalgada yalnız sunum değişti:
rota, yetki dekoratörleri, görünürlük (iç notu yalnız yönetici görür), form
alan adları ve form hedefleri aynı kaldı. Satır içi <style> bloğu ve satır içi
betik dış dosyalara taşındı (CSP).

Testler sahte kullanıcı ve sahte veriyle, her test için ayrı geçici SQLite
veritabanında çalışır (pilot test dosyasıyla aynı yardımcılar).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_pilot_support_new_ux_contract import (
    _english_ui_findings,
    _FormScan,
    _logged_in,
    _make_app,
    _valid_form,
    _VisibleUiText,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DETAIL_TEMPLATE = REPO_ROOT / "app/templates/support/detail.html"
DETAIL_JS = REPO_ROOT / "app/static/js/bys360_support_detail.js"


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_ticket(client, title: str, **overrides) -> int:
    response = client.post("/support/new", data=_valid_form(title=title, **overrides))
    assert response.status_code == 302, response.status_code
    match = re.search(r"/support/(\d+)", response.headers["Location"])
    assert match, response.headers["Location"]
    return int(match.group(1))


def _add_message(app, ticket_id: int, sicil_no: str, text: str, *, internal: bool = False) -> None:
    from app.extensions import db
    from app.models import SupportTicketMessage, User

    with app.app_context():
        user = db.session.query(User).filter_by(sicil_no=sicil_no).one()
        db.session.add(
            SupportTicketMessage(
                ticket_id=ticket_id,
                user_id=user.id,
                message_type="internal_note" if internal else "comment",
                message=text,
                is_internal=internal,
            )
        )
        db.session.commit()


def _unlabelled_controls(html: str, form_id: str) -> list[str]:
    scan = _FormScan(form_id)
    scan.feed(html)
    assert scan.controls, f"#{form_id} formunda denetim yok"
    return [
        str(control.get("name"))
        for control in scan.controls
        if not control["_wrapped_by_label"] and control.get("id") not in scan.labels_for
    ]


def _detail_strings(html: str) -> list[str]:
    scanner = _VisibleUiText("support-shell")
    scanner.feed(html)
    assert scanner.strings, "Detay alanı (.support-shell) yanıtta yok"
    return scanner.strings


# ---------------------------------------------------------------------------
# Statik: CSP, tasarım sistemi ve korunan sözleşme işaretleri
# ---------------------------------------------------------------------------
# Sayfanın eski stil bloğu bu dalgada AYNEN korunur: bloğu taşımak, şablonu ikinci kez
# sahiplenen bir ratchet istisnası (DISJOINT_RECLAIMS) gerektirir ve o istisna yalnız
# proje sahibinin onayıyla genişletilir (bkz. test_csp_style_migration_cumulative_
# inventory_contract.py::test_disjoint_reclaims_is_pinned_to_the_single_reviewed_exception).
# Bloğun ilk 120 karakteri; içerik değişirse bu test kırılır.
ORIGINAL_STYLE_BLOCK_PREFIX = (
    "<style>.support-shell{display:grid;gap:18px}.support-tabs{display:flex;flex-wrap:wrap;gap:10px}"
    ".support-tab{display:inline-flex;align-items:center;"
)
ORIGINAL_STYLE_BLOCK_SHA256 = "bac1429464f770c7a1fed287f0600c56229e0a50be27b1ac24b28133722a05f5"


def test_detail_template_keeps_its_original_style_block_byte_for_byte() -> None:
    import hashlib

    text = DETAIL_TEMPLATE.read_text(encoding="utf-8")
    assert text.lower().count("<style") == 1
    blocks = [line for line in text.splitlines() if line.startswith("<style>")]
    assert len(blocks) == 1 and blocks[0].startswith(ORIGINAL_STYLE_BLOCK_PREFIX)
    assert hashlib.sha256(blocks[0].encode("utf-8")).hexdigest() == ORIGINAL_STYLE_BLOCK_SHA256


def test_detail_template_has_no_inline_style_attribute_script_or_handler() -> None:
    text = DETAIL_TEMPLATE.read_text(encoding="utf-8")
    assert not re.search(r"\sstyle\s*=", text)
    assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE)
    assert "|safe" not in text
    scripts = re.findall(r"<script\b[^>]*>", text)
    assert scripts and all("src=" in tag for tag in scripts), f"Satır içi betik kaldı: {scripts!r}"
    for asset in ("css/bys360_tokens.css", "css/bys360_components.css", "css/faz4_support_account_mobile.css",
                  "js/bys360_ui_form.js", "js/bys360_support_detail.js", "js/faz4_support_account_mobile.js"):
        assert asset in text, asset


def test_detail_script_writes_text_only_and_hides_browser_errors() -> None:
    js = DETAIL_JS.read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert ".style." not in js, "Betik satır içi stil yazmamalı; durum sınıfla gösterilir"
    assert "data-triage-url" in js
    assert "err.fromServer" in js, "Ağ hatasında tarayıcının İngilizce iletisi gösterilmemeli"


# ---------------------------------------------------------------------------
# Talep sahibi (personel): içerik, iç not gizliliği, formlar
# ---------------------------------------------------------------------------
def test_owner_sees_ticket_and_public_notes_but_not_internal_notes(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W3-OWN", role="personel")
    ticket_id = _create_ticket(client, "Sahte talep: karne tarihi görünmüyor")
    _add_message(app, ticket_id, "TEST-W3-OWN", "Sahte açık not: ekran görüntüsü eklendi")
    _add_message(app, ticket_id, "TEST-W3-OWN", "Sahte iç not: yalnız destek ekibi", internal=True)

    response = client.get(f"/support/{ticket_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Sahte talep: karne tarihi görünmüyor" in html
    assert "Sahte açık not: ekran görüntüsü eklendi" in html
    assert "Sahte iç not: yalnız destek ekibi" not in html, "İç not talep sahibine gösterildi"
    assert "Durum ve atama" not in html
    assert 'name="is_internal"' not in html
    assert f'action="/support/{ticket_id}/status"' not in html
    assert f'action="/support/{ticket_id}/assign"' not in html
    assert f'action="/support/{ticket_id}/rate"' in html
    assert "Destek deneyimini değerlendirin" in html
    rating = re.search(r'<select [^>]*id="ticket-rating" name="rating"[^>]*>(.*?)</select>', html, re.DOTALL)
    assert rating and 'required aria-required="true"' in rating.group(0)
    assert rating.group(1).strip().startswith('<option value="">Puan seçin</option>'), "Puan, sahip seçmeden 1 olarak gelmemeli"
    assert " selected" not in rating.group(1)
    assert "Yüksek" in html and "Açıldı" in html


def test_comment_form_controls_are_labelled_and_keep_field_names(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W3-FRM", role="personel")
    ticket_id = _create_ticket(client, "Sahte talep: form alanları")
    html = client.get(f"/support/{ticket_id}").get_data(as_text=True)

    form = re.search(rf'<form [^>]*action="/support/{ticket_id}/comment"[^>]*>.*?</form>', html, re.DOTALL)
    assert form, "Not formu yok"
    body = form.group(0)
    assert 'enctype="multipart/form-data"' in body and 'name="csrf_token"' in body
    assert re.search(r'<textarea [^>]*id="ticket-comment" name="message"[^>]*required', body)
    assert 'maxlength="2000"' in body
    assert re.search(r'<input [^>]*type="file" id="ticket-comment-attachment" name="attachment"', body)
    for control_id in ("ticket-comment", "ticket-comment-attachment"):
        assert f'<label class="bys-field__label" for="{control_id}">' in body, control_id

    assert _unlabelled_controls(html, "ticketCommentForm") == []
    assert _unlabelled_controls(html, "ticketRatingForm") == []


def test_adding_a_note_still_works_and_redirects_back(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W3-ADD", role="personel")
    ticket_id = _create_ticket(client, "Sahte talep: not ekleme")
    response = client.post(f"/support/{ticket_id}/comment", data={"message": "Sahte yeni not"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/support/{ticket_id}")
    html = client.get(f"/support/{ticket_id}").get_data(as_text=True)
    assert "Sahte yeni not" in html
    assert "Henüz yazışma yok." not in html


def test_user_text_is_escaped_in_title_description_and_notes(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W3-XSS", role="personel")
    payload = '<img src=x onerror="alert(1)">'
    ticket_id = _create_ticket(client, "Sahte " + payload, description="Sahte açıklama " + payload)
    _add_message(app, ticket_id, "TEST-W3-XSS", "Sahte not " + payload)
    html = client.get(f"/support/{ticket_id}").get_data(as_text=True)
    assert payload not in html
    assert html.count("&lt;img src=x onerror=") >= 3


def test_saved_rating_is_preselected(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W3-RTG", role="personel")
    ticket_id = _create_ticket(client, "Sahte talep: puan")
    response = client.post(f"/support/{ticket_id}/rate", data={"rating": "4", "feedback_note": "Sahte görüş"})
    assert response.status_code == 302
    html = client.get(f"/support/{ticket_id}").get_data(as_text=True)
    assert '<option value="4" selected>4 / 5 · İyi</option>' in html
    assert "Sahte görüş</textarea>" in html


def test_other_personel_still_gets_403(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W3-A", role="personel")
    ticket_id = _create_ticket(client, "Sahte başkasının talebi")
    other = app.test_client()
    _logged_in(app, other, sicil_no="TEST-W3-B", role="personel")
    assert other.get(f"/support/{ticket_id}").status_code == 403


# ---------------------------------------------------------------------------
# Yönetici görünümü (can_manage): iç not, durum ve atama formları
# ---------------------------------------------------------------------------
def _grant_support_all(app, sicil_no: str) -> None:
    """Ayarlar'daki kişi bazlı support_all izniyle aynı satır (K5-Q1); sahte kullanıcı, geçici veritabanı."""
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        db.create_all()  # izin tablosu pilot veritabanında henüz yoksa oluşturulur
        user = db.session.query(User).filter_by(sicil_no=sicil_no).one()
        db.session.add(UserMenuPermission(user_id=user.id, menu_key="support_all", is_visible=True,
                                          source_type="user_override"))
        db.session.commit()


def test_manager_sees_internal_notes_and_management_forms(app, client) -> None:
    requester = app.test_client()
    _logged_in(app, requester, sicil_no="TEST-W3-REQ", role="personel")
    ticket_id = _create_ticket(requester, "Sahte yönetilen talep")
    _add_message(app, ticket_id, "TEST-W3-REQ", "Sahte iç not: kök neden araştırılıyor", internal=True)

    _logged_in(app, client, sicil_no="TEST-W3-MGR", role="admin")
    _grant_support_all(app, "TEST-W3-MGR")
    response = client.get(f"/support/{ticket_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Sahte iç not: kök neden araştırılıyor" in html
    assert "bys-timeline__item--internal" in html
    assert '<label class="muted checkbox-inline"><input type="checkbox" name="is_internal" value="1"> İç not olarak kaydet</label>' in html
    status_form = re.search(rf'<form [^>]*action="/support/{ticket_id}/status".*?</form>', html, re.DOTALL)
    assign_form = re.search(rf'<form [^>]*action="/support/{ticket_id}/assign".*?</form>', html, re.DOTALL)
    assert status_form and assign_form
    assert re.search(r'<select [^>]*id="ticket-status" name="status"', status_form.group(0))
    assert '<option value="open" selected>Açıldı</option>' in status_form.group(0)
    assert 'name="status_note"' in status_form.group(0)
    assert re.search(r'<select [^>]*id="ticket-assignee" name="assigned_to_user_id"', assign_form.group(0))
    assert '<option value="">Atama kaldır</option>' in assign_form.group(0)
    assert '<hr class="section-divider">' in html
    for form_id in ("ticketCommentForm", "ticketStatusForm", "ticketAssignForm"):
        assert _unlabelled_controls(html, form_id) == [], form_id
    # Yönetici talebin sahibi değil: puan formu görünmez.
    assert f'action="/support/{ticket_id}/rate"' not in html


# ---------------------------------------------------------------------------
# Dosyalar ve boyut gösterimi
# ---------------------------------------------------------------------------
def test_attachment_list_shows_human_readable_size_and_named_download(app, client) -> None:
    from app.extensions import db
    from app.models import User
    from app.models.support_models import SupportTicketAttachment

    _logged_in(app, client, sicil_no="TEST-W3-ATT", role="personel")
    ticket_id = _create_ticket(client, "Sahte talep: ekler")
    with app.app_context():
        user = db.session.query(User).filter_by(sicil_no="TEST-W3-ATT").one()
        for name, size in (("kucuk.txt", 300), ("rapor.pdf", 5 * 1024), ("goruntu.png", 3 * 1024 * 1024 // 2)):
            db.session.add(SupportTicketAttachment(ticket_id=ticket_id, uploaded_by_user_id=user.id, filename=name,
                                                   stored_name=f"w3-{name}", mime_type="application/octet-stream",
                                                   file_size=size, attachment_type="document"))
        db.session.commit()
    html = client.get(f"/support/{ticket_id}").get_data(as_text=True)
    assert "300 bayt" in html and "5 KB" in html and "1,5 MB" in html
    assert "0 KB" not in html
    assert '<span class="visually-hidden">: rapor.pdf</span>' in html
    assert '<div class="attachment-filename">rapor.pdf</div>' in html


# ---------------------------------------------------------------------------
# Türkçe arayüz standardı
# ---------------------------------------------------------------------------
def test_tr_detail_screen_has_no_english_ui_text(app, client) -> None:
    _logged_in(app, client, sicil_no="90931", role="personel")  # sayısal sahte sicil: ekranda veri olarak görünür
    ticket_id = _create_ticket(client, "Sahte talep: rapor ekranı", module_name="Raporlama ve Dashboard")
    _add_message(app, ticket_id, "90931", "Sahte not")
    html = client.get(f"/support/{ticket_id}").get_data(as_text=True)
    findings = _english_ui_findings(_detail_strings(html))
    assert findings == [], "Kullanıcıya görünen İngilizce metin:\n" + "\n".join(findings)
    assert "AI triage" not in html and "AI ile" not in html
    assert "Raporlama ve Gösterge Paneli" in html
    assert "Raporlama ve Dashboard" not in html
