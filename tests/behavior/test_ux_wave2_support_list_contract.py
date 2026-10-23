"""BYS360 UX dalga 2 -- Destek talep listesi (support/list.html) sözleşme testleri.

Şablon üç rotada kullanılır: /support/my-tickets (Taleplerim), /support/assigned
(Bana Atananlar), /support/all (Tüm Talepler). Bu dalgada yalnız sunum değişti:
rotalar, yetki dekoratörleri, sorgular ve görünürlük kapsamı aynı kaldı.

Testler sahte kullanıcı ve sahte veriyle, her test için ayrı geçici SQLite
veritabanında çalışır (pilot test dosyasıyla aynı yardımcılar).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_pilot_support_new_ux_contract import (
    _english_ui_findings,
    _logged_in,
    _make_app,
    _valid_form,
    _VisibleUiText,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIST_TEMPLATE = REPO_ROOT / "app/templates/support/list.html"


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_ticket(client, title: str, **overrides) -> None:
    response = client.post("/support/new", data=_valid_form(title=title, **overrides))
    assert response.status_code == 302, response.status_code


def _list_strings(html: str) -> list[str]:
    scanner = _VisibleUiText("support-shell")
    scanner.feed(html)
    assert scanner.strings, "Liste alanı (.support-shell) yanıtta yok"
    return scanner.strings


# ---------------------------------------------------------------------------
# Statik: CSP ve tasarım sistemi
# ---------------------------------------------------------------------------
def test_list_template_has_no_inline_style_block_or_handler() -> None:
    text = LIST_TEMPLATE.read_text(encoding="utf-8")
    assert "<style" not in text.lower()
    assert not re.search(r"\sstyle\s*=", text)
    assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE)
    assert "|safe" not in text
    assert "css/bys360_tokens.css" in text and "css/bys360_components.css" in text
    assert "css/faz4_support_account_mobile.css" in text
    assert "bys-ui" in text


# ---------------------------------------------------------------------------
# Taleplerim: içerik, kapsam, tablo erişilebilirliği, mobil kart
# ---------------------------------------------------------------------------
def test_my_tickets_lists_only_own_tickets_with_table_and_cards(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W2-B", role="personel")
    _create_ticket(client, "Başka kullanıcının sahte talebi")
    client.get("/logout")
    client.post("/logout")

    other = app.test_client()
    _logged_in(app, other, sicil_no="TEST-W2-A", role="personel")
    _create_ticket(other, "Sahte talep: rapor ekranı boş geliyor")
    _create_ticket(other, "Sahte talep: bildirim gelmiyor", priority="critical")

    response = other.get("/support/my-tickets")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Sahte talep: rapor ekranı boş geliyor" in html
    assert "Sahte talep: bildirim gelmiyor" in html
    assert "Başka kullanıcının sahte talebi" not in html, "Taleplerim başka kullanıcının kaydını gösterdi"

    table = re.search(r'<table class="bys-table">.*?</table>', html, re.DOTALL)
    assert table, "Masaüstü tablosu yok"
    assert "<caption" in table.group(0)
    headers = re.findall(r'<th scope="col">([^<]+)</th>', table.group(0))
    assert headers == ["Başvuru", "Öncelik", "Durum", "Atanan", "Son güncelleme"], headers
    assert len(re.findall(r'href="/support/\d+"', table.group(0))) == 2

    cards = re.search(r'<ul class="bys-ticket-cards".*?</ul>', html, re.DOTALL)
    assert cards and cards.group(0).count('<li class="bys-ticket-card">') == 2
    assert "Kritik" in html
    assert re.search(r'<label class="bys-field__label" for="support-search">Talep ara</label>', html)
    assert "Taleplerim görünümü hazırlandı" not in html


def test_my_tickets_empty_state_offers_new_ticket(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W2-E", role="personel")
    html = client.get("/support/my-tickets").get_data(as_text=True)
    assert "Henüz talebiniz yok." in html
    assert 'href="/support/new"' in html
    assert '<table class="bys-table">' not in html


def test_search_without_results_explains_and_offers_clear(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W2-S", role="personel")
    _create_ticket(client, "Sahte talep: karne tarihi")
    html = client.get("/support/my-tickets?q=bulunmayan-ifade-xyz").get_data(as_text=True)
    assert "Aramanıza uygun talep bulunamadı." in html
    assert "Aramayı temizle" in html
    assert 'value="bulunmayan-ifade-xyz"' in html
    found = client.get("/support/my-tickets?q=karne").get_data(as_text=True)
    assert "Sahte talep: karne tarihi" in found
    assert "Arama sonuçları" in found


def test_titles_are_escaped_in_table_and_cards(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W2-X", role="personel")
    payload = '<img src=x onerror="alert(1)">'
    _create_ticket(client, "Sahte " + payload)
    html = client.get("/support/my-tickets").get_data(as_text=True)
    assert payload not in html
    assert html.count("&lt;img src=x onerror=") >= 2


# ---------------------------------------------------------------------------
# Bana Atananlar: başvuru sahibi sütunu, yetki
# ---------------------------------------------------------------------------
def test_assigned_view_shows_requester_column_for_unit_manager(app, client) -> None:
    from app.extensions import db
    from app.models import SupportTicket, User

    requester = app.test_client()
    _logged_in(app, requester, sicil_no="TEST-W2-REQ", role="personel")
    _create_ticket(requester, "Sahte atanan talep")

    _logged_in(app, client, sicil_no="TEST-W2-BS", role="birim_sorumlusu")
    with app.app_context():
        manager = db.session.query(User).filter_by(sicil_no="TEST-W2-BS").one()
        ticket = db.session.query(SupportTicket).filter_by(title="Sahte atanan talep").one()
        ticket.assigned_to_user_id = manager.id
        ticket.status = "assigned"
        db.session.commit()

    response = client.get("/support/assigned")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Sahte atanan talep" in html
    headers = re.findall(r'<th scope="col">([^<]+)</th>', html)
    assert headers[:2] == ["Başvuru", "Başvuru sahibi"], headers
    assert "TEST-W2-REQ" in html
    assert "Atandı" in html


def test_personel_still_cannot_open_staff_lists(app, client) -> None:
    _logged_in(app, client, sicil_no="TEST-W2-P", role="personel")
    assert client.get("/support/assigned").status_code == 403
    assert client.get("/support/all").status_code == 403


# ---------------------------------------------------------------------------
# Türkçe arayüz standardı
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("state", ["empty", "filled", "no_result"])
def test_tr_list_screen_has_no_english_ui_text(app, client, state) -> None:
    _logged_in(app, client, sicil_no="TEST-W2-TR", role="personel")
    if state != "empty":
        _create_ticket(client, "Sahte talep: rapor ekranı", module_name="Raporlama ve Dashboard")
    url = "/support/my-tickets" + ("?q=bulunmayan-ifade" if state == "no_result" else "")
    html = client.get(url).get_data(as_text=True)
    findings = _english_ui_findings(_list_strings(html))
    assert findings == [], "Kullanıcıya görünen İngilizce metin:\n" + "\n".join(findings)
    if state == "filled":
        # Kayıtlı değer aynen kalır, ekranda Türkçe adı görünür.
        assert "Raporlama ve Gösterge Paneli" in html
        assert "Raporlama ve Dashboard" not in html


def test_tab_row_layout_does_not_depend_on_the_help_center_stylesheet() -> None:
    """Liste ve detay şablonları bys360_support_learning.css'i yüklemez; sekme satırının
    esnek düzeni tasarım sistemi CSS'inde tanımlı olmalı (768 px'te 5+ sekmede satır
    içi akışa düşüp 22 px yüksekliğe inmesini önler)."""
    css = (REPO_ROOT / "app/static/css/bys360_components.css").read_text(encoding="utf-8")
    tabs = re.search(r"^\.bys-ui \.support-tabs \{([^}]*)\}", css, re.MULTILINE)
    tab = re.search(r"^\.bys-ui \.support-tab \{([^}]*)\}", css, re.MULTILINE)
    assert tabs and "display: flex" in tabs.group(1) and "flex-wrap: wrap" in tabs.group(1)
    assert tab and "display: inline-flex" in tab.group(1) and "align-items: center" in tab.group(1)
    assert "bys360_support_learning.css" not in LIST_TEMPLATE.read_text(encoding="utf-8")
