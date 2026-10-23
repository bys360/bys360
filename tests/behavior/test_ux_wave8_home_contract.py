"""BYS360 UX dalga 8 -- Ana sayfa (home.html) günlük çalışma merkezi sözleşme testleri.

Bu dalgada sunum ve bilgi mimarisi değişti; veri kaynakları ve kapsam kuralları aynı:
home_dashboard_service, portal_service, portal_experience_service ve
portal_experience_v2_service. Düzeltilen gerçek hatalar da burada sabitlenir:
web'de karşılığı olmayan /support/tickets* bağlantıları, /portal/profile bağlantısı,
olmayan #portal-body çapası, ham UTC güncelleme saati ve kullanıcıya gösterilen
WEATHER_ENABLED yapılandırma adı.

Testler sahte kullanıcı ve sahte veriyle, her test için ayrı geçici SQLite
veritabanında çalışır; hava durumu kapalıdır (ağ erişimi yok).
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from test_pilot_support_new_ux_contract import (
    _english_ui_findings,
    _logged_in,
    _make_app,
    _VisibleUiText,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "app/templates/home.html"
HOME_CSS = REPO_ROOT / "app/static/css/bys360_home.css"
HOME_JS = REPO_ROOT / "app/static/js/bys360_home.js"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("WEATHER_ENABLED", "false")
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _user_id(app, sicil_no: str) -> int:
    from app.extensions import db
    from app.models import User

    with app.app_context():
        return db.session.query(User).filter_by(sicil_no=sicil_no).one().id


def _seed_for(app, user_id: int, other_user_id: int) -> None:
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import Notification, PortalPost

    now = utc_now().replace(tzinfo=None)
    with app.app_context():
        db.session.add(Notification(user_id=user_id, title="Sahte: değerlendirme görevi atandı", body="Sahte bildirim metni.",
                                    notification_type="system", priority="normal", is_read=False, link_url="/notifications"))
        db.session.add(Notification(user_id=other_user_id, title="Sahte: başkasının bildirimi", body="Gizli kalmalı.",
                                    notification_type="system", priority="normal", is_read=False, link_url="/notifications"))
        db.session.add(PortalPost(author_user_id=other_user_id, title="Sahte duyuru: bayram mesaisi planı", body="Sahte duyuru metni.",
                                  post_type="corporate_announcement", visibility_scope="public", status="published",
                                  comments_enabled=True, is_pinned=True, is_featured_home=True, published_at=now - timedelta(hours=2)))
        db.session.commit()


# ---------------------------------------------------------------------------
# Statik: CSP, tasarım sistemi ve kapsam
# ---------------------------------------------------------------------------
def test_template_has_no_inline_style_script_or_handler() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "<style" not in text.lower()
    assert not re.search(r"\sstyle\s*=", text)
    assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE)
    assert "|safe" not in text
    assert all("src=" in tag for tag in re.findall(r"<script[^>]*>", text)), "Satır içi betik olmamalı"
    for asset in ("css/bys360_tokens.css", "css/bys360_components.css", "css/bys360_home.css",
                  "js/bys360_home.js", "js/announcement_popup.js", "communication/_announcement_popup_runtime.html"):
        assert asset in text, asset
    assert 'class="bys-ui bys-page home-page skip-mobile-normalize"' in text
    # Kaldırılan basın haberi bloğu için artık yüklenmeyen ölü CSS ve süs animasyonu.
    assert "bys360_portal_experience_v3a_press_news.css" not in text
    assert "bys360_home_festival_portal_v2_5.js" not in text


def test_home_css_is_scoped_and_has_no_important() -> None:
    css = re.sub(r"/\*.*?\*/", "", HOME_CSS.read_text(encoding="utf-8"), flags=re.S)
    assert "!important" not in css
    assert ":root" not in css
    selectors = [s.strip() for block in re.findall(r"([^{}]+)\{", css)
                 for s in block.split(",") if s.strip() and not s.strip().startswith("@")]
    assert selectors and all(s.startswith(".bys-ui") for s in selectors), [s for s in selectors if not s.startswith(".bys-ui")]


def test_home_js_does_not_write_html() -> None:
    js = HOME_JS.read_text(encoding="utf-8")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "document.write"):
        assert banned not in js, banned


# ---------------------------------------------------------------------------
# Canlı sayfa: işlevler korunur, gerçek hatalar düzeltilir
# ---------------------------------------------------------------------------
def test_home_renders_priorities_with_working_links(app, client) -> None:
    _logged_in(app, client, sicil_no="90801", role="personel")
    response = client.get("/home")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Gün Özeti" in html and "Aktif dönem" in html
    from flask import url_for

    with app.test_request_context():
        hrefs = [url_for(e) for e in ("main.performance_tasks", "main.notifications_list", "main.messages_inbox",
                                      "main.support_my_tickets", "main.surveys_list", "main.support_new", "main.dashboard")]
    for href in hrefs:
        assert f'href="{href}"' in html, href
    for label in ("Görevlerim", "Bildirimler", "Mesajlar", "Destek", "Anketler", "Günün öncelikleri"):
        assert label in html, label
    assert 'id="bys-announcement-popup-root"' in html


def test_broken_links_are_gone(app, client) -> None:
    _logged_in(app, client, sicil_no="90802", role="personel")
    html = client.get("/home").get_data(as_text=True)
    assert "/support/tickets" not in html
    assert 'href="/portal/profile"' not in html
    assert 'href="/portal#portal-body"' in html  # Hızlı paylaşım, paylaşım formunun bulunduğu sayfaya gider


def test_portal_experience_support_links_point_to_web_routes() -> None:
    from app.services import portal_experience_service as pes

    source = Path(pes.__file__).read_text(encoding="utf-8")
    assert "/support/tickets" not in source
    assert '"href": "/support/my-tickets"' in source and '"href": "/support/new"' in source
    assert 'f"/support/{getattr(ticket, \'id\', \'\')}"' in source


def test_attention_list_shows_only_my_items(app, client) -> None:
    _logged_in(app, client, sicil_no="90803", role="personel")
    other = app.test_client()
    _logged_in(app, other, sicil_no="90804", role="personel")
    _seed_for(app, _user_id(app, "90803"), _user_id(app, "90804"))
    html = client.get("/home").get_data(as_text=True)
    assert "Sahte: değerlendirme görevi atandı" in html
    assert "Sahte: başkasının bildirimi" not in html
    assert "Sahte duyuru: bayram mesaisi planı" in html


def test_empty_states_are_explained(app, client) -> None:
    _logged_in(app, client, sicil_no="90805", role="personel")
    html = client.get("/home").get_data(as_text=True)
    assert "Şu an dikkat gerektiren bir işiniz yok." in html
    assert "Portalda henüz paylaşım yok." in html


def test_personnel_count_only_for_managerial_roles(app, client) -> None:
    _logged_in(app, client, sicil_no="90806", role="personel")
    assert "Personel sayısı" not in client.get("/home").get_data(as_text=True)
    admin = app.test_client()
    _logged_in(app, admin, sicil_no="90807", role="admin")
    assert "Personel sayısı" in admin.get("/home").get_data(as_text=True)
    # Eski etiket, yönetici olmayanlara da yöneticiye de yanıltıcı "Yetkili görünüm" yazıyordu.
    assert "Yetkili görünüm" not in admin.get("/home").get_data(as_text=True)


def test_weather_disabled_text_has_no_config_name(app, client) -> None:
    _logged_in(app, client, sicil_no="90808", role="personel")
    html = client.get("/home").get_data(as_text=True)
    assert "WEATHER_ENABLED" not in html
    assert "Hava durumu bilgisi bu ortamda kapalı" in html


def test_updated_time_is_local_not_raw_utc() -> None:
    from app.services.home_dashboard_service import _local_time_label

    assert _local_time_label("2026-10-17T09:30+00:00") == "12:30"
    assert _local_time_label("bozuk") == ""
    assert _local_time_label(None) == ""


def test_tr_home_has_no_english_ui_text(app, client) -> None:
    _logged_in(app, client, sicil_no="90809", role="admin")
    _seed_for(app, _user_id(app, "90809"), _user_id(app, "90809"))
    html = client.get("/home").get_data(as_text=True)
    scanner = _VisibleUiText("home-page")
    scanner.feed(html)
    assert scanner.strings
    findings = _english_ui_findings(scanner.strings)
    assert findings == [], "Kullanıcıya görünen İngilizce metin:\n" + "\n".join(findings)
