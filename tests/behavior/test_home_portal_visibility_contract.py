"""Ana sayfa ve portal deneyim alanlarında portal veri görünürlüğü sözleşmesi.

Kök neden: portal_experience_v2_service (öne çıkan duyurular, takdir/başarı
vurguları, topluluk nabzı, "Kurumdan kişiler") ve portal_experience_service
(takdir listesi, son 30 gün sayaçları) PortalPost ve User tablolarını doğrudan
sorguluyordu. Portalın kendi akışı ise her gönderiyi portal_service.can_user_view_post
ile süzer ve kişi listesini portal_permission_allowed(user, "portal_people") iznine
bağlar. Ana sayfa bu iki kuralı atlıyordu: birime, gruba, role veya seçili kişilere
açılmış bir gönderi, kapsam dışındaki personelin ana sayfasında görünüyordu.

Düzeltme yeni kural tanımlamaz; ana sayfa alanlarını portal akışının mevcut
kurallarına bağlar. Testler sahte kullanıcı ve sahte veriyle, her test için ayrı
geçici SQLite veritabanında çalışır.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from test_pilot_support_new_ux_contract import _login, _make_app

PASSWORD = "UxPilotSahte1!"

HIDDEN_RECOGNITION = "SAHTE-GIZLI-TAKDIR-BIRIM-B"
HIDDEN_ANNOUNCEMENT = "SAHTE-GIZLI-DUYURU-SECILI-KISI"
PUBLIC_RECOGNITION = "SAHTE-ACIK-BASARI"
PUBLIC_ANNOUNCEMENT = "SAHTE-ACIK-DUYURU"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("WEATHER_ENABLED", "false")
    return _make_app(monkeypatch)


def _user(sicil_no: str, *, role: str = "personel", birim: str = "Sahte Birim A", ad: str = "Sahte"):
    from app.models import User

    user = User(sicil_no=sicil_no, email=f"{sicil_no.lower()}@bys360.test", ad=ad, soyad=f"Kişi {sicil_no}",
                role=role, birim=birim, unvan="Sahte Unvan", is_active=True,
                must_change_password=False, must_set_security_question=False)
    user.set_password(PASSWORD)
    return user


def _seed(app) -> dict[str, int]:
    """Birim A'daki izleyici, birim B'deki yazar, yönetici ve dört gönderi."""
    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import PortalPost, PortalPostComment, PortalPostReaction

    now = utc_now().replace(tzinfo=None)
    with app.app_context():
        viewer = _user("SV-A1", birim="Sahte Birim A")
        author = _user("SV-B1", birim="Sahte Birim B", ad="Yazar")
        same_unit = _user("SV-B2", birim="Sahte Birim B")
        admin = _user("SV-AD", role="admin", birim="Sahte Yönetim")
        reactors = [_user(f"SV-R{i}", birim="Sahte Birim B") for i in range(3)]
        db.session.add_all([viewer, author, same_unit, admin, *reactors])
        db.session.flush()

        def post(title: str, post_type: str, scope: str, **extra) -> PortalPost:
            row = PortalPost(author_user_id=author.id, title=title, body=f"{title} metni.", post_type=post_type,
                             visibility_scope=scope, status="published", comments_enabled=True,
                             published_at=now - timedelta(hours=1), **extra)
            db.session.add(row)
            db.session.flush()
            return row

        hidden_rec = post(HIDDEN_RECOGNITION, "thanks", "unit", target_unit_name="Sahte Birim B")
        hidden_ann = post(HIDDEN_ANNOUNCEMENT, "corporate_announcement", "selected_users")
        public_rec = post(PUBLIC_RECOGNITION, "success", "public")
        post(PUBLIC_ANNOUNCEMENT, "corporate_announcement", "public")
        for reactor in reactors:
            db.session.add(PortalPostReaction(post_id=hidden_rec.id, user_id=reactor.id, reaction_type="like"))
        db.session.add(PortalPostReaction(post_id=public_rec.id, user_id=reactors[0].id, reaction_type="like"))
        db.session.add(PortalPostComment(post_id=hidden_ann.id, author_user_id=reactors[0].id, body="Sahte yorum", status="published"))
        db.session.add(PortalPostComment(post_id=hidden_ann.id, author_user_id=reactors[1].id, body="Sahte yorum", status="published"))
        db.session.commit()
        return {"viewer": viewer.id, "same_unit": same_unit.id, "admin": admin.id}


def _v2_for(app, user_id: int) -> dict:
    from app.extensions import db
    from app.models import User
    from app.services.portal_experience_v2_service import portal_experience_v2_context

    with app.test_request_context("/home"):
        return portal_experience_v2_context(db.session.get(User, user_id))["portal_v2"]


def _px_for(app, user_id: int) -> dict:
    from app.extensions import db
    from app.models import User
    from app.services.portal_experience_service import portal_experience_context

    with app.test_request_context("/home"):
        return portal_experience_context(db.session.get(User, user_id))["portal_experience"]


def _texts(rows: list[dict]) -> str:
    return " | ".join(f"{row.get('title', '')} {row.get('body', '')}" for row in rows)


# ---------------------------------------------------------------------------
# Servis düzeyi: veri kapsam dışı kullanıcıya hiç üretilmez
# ---------------------------------------------------------------------------
def test_v2_hub_lists_only_posts_the_user_may_view(app) -> None:
    ids = _seed(app)
    v2 = _v2_for(app, ids["viewer"])
    recognitions = _texts(v2["recognition_highlights"])
    announcements = _texts(v2["featured_announcements"])
    assert HIDDEN_RECOGNITION not in recognitions
    assert HIDDEN_ANNOUNCEMENT not in announcements
    assert PUBLIC_RECOGNITION in recognitions
    assert PUBLIC_ANNOUNCEMENT in announcements


def test_v2_community_pulse_counts_only_visible_posts(app) -> None:
    ids = _seed(app)
    pulse = _v2_for(app, ids["viewer"])["pulse"]
    # Görünür: 1 başarı + 1 duyuru; gizli takdirin 3 tepkisi ve gizli duyurunun 2 yorumu sayılmaz.
    assert (pulse["post_count"], pulse["recognition_count"], pulse["announcement_count"]) == (2, 1, 1)
    assert (pulse["reaction_count"], pulse["comment_count"]) == (1, 0)


def test_legacy_recognition_and_30_day_counters_follow_the_same_rule(app) -> None:
    ids = _seed(app)
    px = _px_for(app, ids["viewer"])
    assert HIDDEN_RECOGNITION not in _texts(px["recognition_items"])
    assert PUBLIC_RECOGNITION in _texts(px["recognition_items"])
    assert px["culture_stats"] == {"recognitions": 1, "comments": 0, "reactions": 1}


def test_users_inside_the_audience_and_portal_managers_still_see_restricted_posts(app) -> None:
    ids = _seed(app)
    same_unit = _v2_for(app, ids["same_unit"])
    assert HIDDEN_RECOGNITION in _texts(same_unit["recognition_highlights"])
    assert HIDDEN_ANNOUNCEMENT not in _texts(same_unit["featured_announcements"])  # seçili kişi değil
    admin = _v2_for(app, ids["admin"])  # can_manage_portal: mevcut kural her gönderiyi açar
    assert HIDDEN_RECOGNITION in _texts(admin["recognition_highlights"])
    assert HIDDEN_ANNOUNCEMENT in _texts(admin["featured_announcements"])
    assert _px_for(app, ids["admin"])["culture_stats"] == {"recognitions": 2, "comments": 2, "reactions": 4}


def test_people_spotlight_follows_the_portal_people_permission(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    ids = _seed(app)
    assert _v2_for(app, ids["viewer"])["people_spotlight"], "Varsayılan rol matrisi personel listesini açar."
    with app.app_context():
        db.session.add(UserMenuPermission(user_id=ids["viewer"], menu_key="portal_people", is_visible=False))
        db.session.commit()
    assert _v2_for(app, ids["viewer"])["people_spotlight"] == []
    spotlight_fields = {key for row in _v2_for(app, ids["admin"])["people_spotlight"] for key in row}
    # Personel Duvarları sayfasının zaten gösterdiği alanlar; e-posta, sicil veya rol taşınmaz.
    assert spotlight_fields == {"name", "title", "unit", "photo_url"}


# ---------------------------------------------------------------------------
# Uçtan uca: ana sayfa HTML'i
# ---------------------------------------------------------------------------
def test_home_page_does_not_render_restricted_portal_content(app) -> None:
    ids = _seed(app)
    client = app.test_client()
    _login(client, "SV-A1", PASSWORD)
    response = client.get("/home")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert ids["viewer"]
    assert HIDDEN_RECOGNITION not in html
    assert HIDDEN_ANNOUNCEMENT not in html
    assert PUBLIC_ANNOUNCEMENT in html
    assert "Son 30 günde 1 takdir, 1 tepki." in html


def test_home_page_hides_people_spotlight_when_permission_is_closed(app) -> None:
    from app.extensions import db
    from app.models import UserMenuPermission

    ids = _seed(app)
    with app.app_context():
        db.session.add(UserMenuPermission(user_id=ids["viewer"], menu_key="portal_people", is_visible=False))
        db.session.commit()
    client = app.test_client()
    _login(client, "SV-A1", PASSWORD)
    html = client.get("/home").get_data(as_text=True)
    assert "Kurumdan kişiler" not in html
    assert "Kişi SV-R2" not in html  # vitrinde yer alırdı (en son eklenen etkin kullanıcı)


def test_portal_page_v2_hub_uses_the_same_rule(app) -> None:
    _seed(app)
    client = app.test_client()
    _login(client, "SV-A1", PASSWORD)
    response = client.get("/portal")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert HIDDEN_RECOGNITION not in html
    assert HIDDEN_ANNOUNCEMENT not in html
    assert PUBLIC_ANNOUNCEMENT in html
