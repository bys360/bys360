"""BYS360 UX dalga 6 -- rehber formu (support/help_admin_form.html) ve destek kurulumu
(support/setup.html) sözleşme testleri.

İki ekran da yalnız yöneticiye açıktır (@admin_required). Bu dalgada yalnız sunum
değişti: alan adları, form hedefleri (aynı adres, POST), CSRF, hata durumunda girilen
değerlerin korunması ve kurulum davranışı aynı kaldı. 7 statik style="..." özniteliği
ve iki sayfa içi <style> bloğu dış CSS'e taşındı
(STYLE_MIGRATION_WAVES["ux_wave6_help_form_setup"]).

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
    _VisibleUiText,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FORM_TEMPLATE = REPO_ROOT / "app/templates/support/help_admin_form.html"
SETUP_TEMPLATE = REPO_ROOT / "app/templates/support/setup.html"
FIELD_NAMES = ("title", "slug", "category_slug", "summary", "sort_order", "content_text", "steps_text",
               "notes_text", "role_slugs", "tags_text", "related_slugs_text", "is_published", "is_featured")


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _form_data(**overrides):
    data = {
        "title": "Sahte rehber: izin talebi nasıl açılır",
        "slug": "",
        "category_slug": "baslarken",
        "summary": "Sahte özet.",
        "sort_order": "5",
        "content_text": "Sahte genel bilgi.",
        "steps_text": "Adım 1\nAdım 2",
        "notes_text": "",
        "role_slugs": ["personel"],
        "tags_text": "izin, onay",
        "related_slugs_text": "",
        "is_published": "1",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Statik: CSP ve tasarım sistemi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [FORM_TEMPLATE, SETUP_TEMPLATE], ids=["form", "setup"])
def test_template_has_no_inline_style_block_script_or_handler(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "<style" not in text.lower()
    assert not re.search(r"\sstyle\s*=", text)
    assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE)
    assert "|safe" not in text
    assert "<script>" not in text
    assert "css/bys360_tokens.css" in text and "css/bys360_components.css" in text
    assert "bys-ui bys-page" in text


def test_form_keeps_every_field_name_and_loads_the_form_script() -> None:
    text = FORM_TEMPLATE.read_text(encoding="utf-8")
    for name in FIELD_NAMES:
        assert f"'{name}'" in text or f'name="{name}"' in text, name
    assert 'name="csrf_token"' in text
    assert "js/bys360_ui_form.js" in text


# ---------------------------------------------------------------------------
# Rehber formu
# ---------------------------------------------------------------------------
def test_new_form_controls_are_labelled_and_grouped(app, client) -> None:
    _logged_in(app, client, sicil_no="90981", role="admin")
    response = client.get("/support/help-admin/new")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    scan = _FormScan("helpArticleForm")
    scan.feed(html)
    names = {control.get("name") for control in scan.controls}
    assert set(FIELD_NAMES) <= names, set(FIELD_NAMES) - names
    unlabelled = [c.get("name") for c in scan.controls if not c["_wrapped_by_label"] and c.get("id") not in scan.labels_for]
    assert unlabelled == [], unlabelled
    assert html.count('<fieldset class="bys-section">') == 4
    assert re.search(r'<input [^>]*id="help-title" name="title"[^>]*required', html)
    assert "Kısa Bağlantı (slug)" not in html and "Slugları" not in html


def test_creating_an_article_still_works(app, client) -> None:
    from app.extensions import db
    from app.models import SupportHelpArticle

    _logged_in(app, client, sicil_no="90982", role="admin")
    response = client.post("/support/help-admin/new", data=_form_data())
    assert response.status_code == 302 and response.headers["Location"].endswith("/support/help-admin")
    with app.app_context():
        article = db.session.query(SupportHelpArticle).filter_by(title="Sahte rehber: izin talebi nasıl açılır").one()
        assert article.slug and article.is_published and not article.is_featured
        assert article.sort_order == 5
        assert article.role_slugs == ["personel"]


def test_edit_form_shows_saved_values_including_zero_sort_order(app, client) -> None:
    from app.extensions import db
    from app.models import SupportHelpArticle

    _logged_in(app, client, sicil_no="90983", role="admin")
    assert client.post("/support/help-admin/new", data=_form_data(sort_order="0", is_featured="1")).status_code == 302
    with app.app_context():
        article_id = db.session.query(SupportHelpArticle).one().id
    html = client.get(f"/support/help-admin/{article_id}/edit").get_data(as_text=True)
    assert 'value="Sahte rehber: izin talebi nasıl açılır"' in html
    assert re.search(r'<input [^>]*id="help-sort" name="sort_order" value="0"', html), "Sıra 0 boş görünmemeli"
    assert re.search(r'<input type="checkbox" id="help-featured" name="is_featured" value="1" checked>', html)
    assert re.search(r'<input type="checkbox" id="help-role-personel" name="role_slugs" value="personel" checked>', html)
    assert "Yayındaki hâli" in html


def test_failed_save_keeps_what_the_admin_typed(app, client) -> None:
    _logged_in(app, client, sicil_no="90984", role="admin")
    response = client.post("/support/help-admin/new", data=_form_data(title="", summary="Sahte yazılmış özet korunmalı"))
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Sahte yazılmış özet korunmalı" in html
    assert "Makale oluşturulamadı." in html


def test_personel_still_cannot_open_admin_screens(app, client) -> None:
    _logged_in(app, client, sicil_no="90985", role="personel")
    for path in ("/support/help-admin/new", "/support/setup"):
        assert client.get(path).status_code in (302, 403), path


# ---------------------------------------------------------------------------
# Kurulum
# ---------------------------------------------------------------------------
def test_setup_lists_tables_and_shows_state(app, client) -> None:
    _logged_in(app, client, sicil_no="90986", role="admin")
    html = client.get("/support/setup").get_data(as_text=True)
    assert "<code>support_tickets</code>" in html
    assert "Kurulum tamamlandı" in html  # test veritabanında tablolar hazır
    assert 'href="/support"' in html
    response = client.post("/support/setup", data={})
    assert response.status_code == 302 and response.headers["Location"].endswith("/support")


# ---------------------------------------------------------------------------
# Türkçe arayüz standardı
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/support/help-admin/new", "/support/setup"])
def test_tr_screen_has_no_english_ui_text(app, client, path) -> None:
    _logged_in(app, client, sicil_no="90987", role="admin")
    html = client.get(path).get_data(as_text=True)
    scanner = _VisibleUiText("bys-page")
    scanner.feed(html)
    assert scanner.strings
    # Tablo adları teknik tanımlayıcıdır (görünen ad değil); <code> içinde gösterilir.
    strings = [text for text in scanner.strings if not re.fullmatch(r"[a-z_]+", text)]
    # Kategori ve rol adları rehber içerik verisindendir (ör. "Raporlama ve Dashboard"); terim kararı
    # #80'de bekliyor. Şablonun kendi metninde İngilizce olmamalı.
    from app.support.help_center_content import HELP_CATEGORIES, HELP_ROLES

    content = {item["title"] for item in HELP_CATEGORIES + HELP_ROLES}
    findings = [f for f in _english_ui_findings(strings) if f.split(" <- ", 1)[1].strip("'") not in content]
    assert findings == [], "Şablonun kendi metninde İngilizce:\n" + "\n".join(findings)
