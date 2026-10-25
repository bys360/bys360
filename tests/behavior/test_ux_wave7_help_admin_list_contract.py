"""BYS360 UX dalga 7 -- Rehber Yönetimi listesi (support/help_admin_list.html) sözleşme testleri.

Yalnız yöneticiye açık (@admin_required). Bu dalgada yalnız sunum değişti: rotalar,
form hedefleri, CSRF girdileri, silme onayı (data-confirm + yerel betik) ve
Style-2A / Wave-7 sözleşmelerinin sabitlediği sınıf ve metinler aynı kaldı.

Sayfanın eski stil bloğu BAYT BAYT aynen korunur: Style-2A dalgası bu şablonu zaten
sahiplendiği için bloğu taşımak ratchet'te ikinci bir sahiplenme istisnası
(DISJOINT_RECLAIMS) gerektirir; bu istisna yalnız proje sahibinin onayıyla genişletilir
(bkz. dalga 3, support/detail.html).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from test_pilot_support_new_ux_contract import (
    _english_ui_findings,
    _logged_in,
    _make_app,
    _VisibleUiText,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "app/templates/support/help_admin_list.html"
ORIGINAL_STYLE_BLOCK_SHA256 = "8a3b9bcc8c2a0dc02a026d7aec288e08d3a976115a476dbdaebb1d995ec1713d"
CSRF = '<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">'
DELETE_CONFIRM = "Bu makaleyi silmek istediğinize emin misiniz?"


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _create_article(app, *, title: str, slug: str, published: bool, source_type: str = "manual") -> int:
    from app.extensions import db
    from app.models import SupportHelpArticle

    with app.app_context():
        article = SupportHelpArticle(slug=slug, title=title, summary="Sahte özet.", category_slug="baslarken",
                                     content_text="", steps_text="", notes_text="", sort_order=0,
                                     is_published=published, is_featured=False, source_type=source_type)
        db.session.add(article)
        db.session.commit()
        return article.id


# ---------------------------------------------------------------------------
# Statik: korunan sözleşme parçaları
# ---------------------------------------------------------------------------
def test_original_style_block_scripts_and_csrf_are_kept_verbatim() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    block = text[text.index("<style>"): text.index("</style>") + len("</style>")]
    assert text.lower().count("<style") == 1
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == ORIGINAL_STYLE_BLOCK_SHA256
    assert text.count(CSRF) == 4
    assert text.count("<script") == 2 and "querySelectorAll('form[data-confirm]')" in text
    assert f'class="inline" data-confirm="{DELETE_CONFIRM}"' in text
    assert not re.search(r"\sstyle\s*=", text)
    assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE)
    assert "|safe" not in text
    assert "css/bys360_tokens.css" in text and "css/bys360_components.css" in text


# ---------------------------------------------------------------------------
# Canlı rota
# ---------------------------------------------------------------------------
def test_list_shows_rows_with_turkish_source_labels_and_named_actions(app, client) -> None:
    _logged_in(app, client, sicil_no="90991", role="admin")
    first = _create_article(app, title="Sahte elle eklenen rehber", slug="sahte-elle", published=True)
    second = _create_article(app, title="Sahte hazır rehber", slug="sahte-hazir", published=False, source_type="seeded")
    response = client.get("/support/help-admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert html.count('<li class="bys-admin-row">') == 2
    assert "Elle eklendi" in html and "Hazır rehber" in html
    assert ">manual<" not in html and ">seeded<" not in html
    assert "Yayında" in html and "Taslak" in html
    for article_id in (first, second):
        assert f'href="/support/help-admin/{article_id}/edit"' in html
        assert f'action="/support/help-admin/{article_id}/toggle-publish" class="inline"' in html
        assert f'action="/support/help-admin/{article_id}/delete" class="inline" data-confirm="{DELETE_CONFIRM}"' in html
    assert '<span class="visually-hidden">: Sahte hazır rehber</span>' in html


def test_search_and_status_filter_are_labelled_and_still_filter(app, client) -> None:
    _logged_in(app, client, sicil_no="90992", role="admin")
    _create_article(app, title="Sahte yayındaki rehber", slug="sahte-yayinda", published=True)
    _create_article(app, title="Sahte taslak rehber", slug="sahte-taslak", published=False)
    html = client.get("/support/help-admin?status=draft").get_data(as_text=True)
    assert '<label class="bys-field__label" for="help-admin-search">Rehber ara</label>' in html
    assert '<label class="bys-field__label" for="help-admin-status">Yayın durumu</label>' in html
    assert '<option value="draft" selected>Taslak</option>' in html
    assert "Sahte taslak rehber" in html and "Sahte yayındaki rehber" not in html
    found = client.get("/support/help-admin?q=yayındaki").get_data(as_text=True)
    assert "Sahte yayındaki rehber" in found and "Sahte taslak rehber" not in found


def test_empty_state_and_personel_access(app, client) -> None:
    _logged_in(app, client, sicil_no="90993", role="admin")
    html = client.get("/support/help-admin").get_data(as_text=True)
    assert '<div class="empty section-spacing-top-lg">Filtreye uygun makale bulunamadı.</div>' in html
    other = app.test_client()
    _logged_in(app, other, sicil_no="90994", role="personel")
    assert other.get("/support/help-admin").status_code in (302, 403)


def test_tr_list_has_no_english_ui_text(app, client) -> None:
    _logged_in(app, client, sicil_no="90995", role="admin")
    _create_article(app, title="Sahte rehber", slug="sahte-rehber", published=True)
    html = client.get("/support/help-admin").get_data(as_text=True)
    scanner = _VisibleUiText("bys-page")
    scanner.feed(html)
    assert scanner.strings
    # Kısa bağlantı adı ve kategori anahtarı teknik tanımlayıcıdır (kod biçiminde gösterilir).
    strings = [text for text in scanner.strings if not re.fullmatch(r"[a-z0-9-]+", text)]
    findings = _english_ui_findings(strings)
    assert findings == [], "Kullanıcıya görünen İngilizce metin:\n" + "\n".join(findings)
