"""Contract: a group-scoped portal post notifies the group's active members.

POST /portal/posts with visibility_scope=group calls notify_portal_post_created(), whose
_portal_audience_user_ids (app/services/bys360_notification_bridge.py) filtered
PortalGroupMember by ``is_active=True``. PortalGroupMember has no ``is_active``; membership
state is the ``status`` column. The InvalidRequestError was swallowed by the function's
broad except, so the audience was empty and no group member was ever notified.

Rule reused: portal_service.is_group_member() and list_active_groups_for_user() treat a
membership as valid only when ``status == "active"``, and can_user_view_post() lets exactly
those members see a group post. Notified users are therefore the active members, minus the
author (unchanged exclusion).

Real Flask app, real test client and login, file-backed SQLite only.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

PASSWORD = "PortalGroupNotifyTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "portal_group_post_notification" / "dbs"


@pytest.fixture
def portal_app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-portal-group-notify", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "portal-group-notify-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import PortalGroup, PortalGroupMember, User

    with flask_app.app_context():
        db.create_all()
        ids = {}
        for sicil, role in (("PGN01", "admin"), ("PGN02", "personel"), ("PGN03", "personel"), ("PGN04", "personel")):
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Portal", soyad=sicil, role=role,
                        birim="Birim A", is_active=True, must_change_password=False, must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[sicil] = user.id
        group = PortalGroup(name="Proje Grubu", slug="proje-grubu", owner_user_id=ids["PGN01"], is_active=True)
        db.session.add(group)
        db.session.flush()
        db.session.add_all([
            PortalGroupMember(group_id=group.id, user_id=ids["PGN01"], member_role="owner", status="active"),
            PortalGroupMember(group_id=group.id, user_id=ids["PGN02"], member_role="member", status="active"),
            PortalGroupMember(group_id=group.id, user_id=ids["PGN03"], member_role="member", status="pending"),
            # PGN04 is not a member.
        ])
        db.session.commit()
        ids["group"] = group.id
        flask_app.config["_IDS"] = ids
    return flask_app


def _login(client, sicil):
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")


def _post_to_group(app):
    client = app.test_client()
    _login(client, "PGN01")
    response = client.post(
        "/portal/posts",
        data={"body": "Grup duyurusu", "visibility_scope": "group", "target_group_id": str(app.config["_IDS"]["group"])},
        follow_redirects=False,
    )
    assert response.status_code == 302
    from app.models import PortalPost

    with app.app_context():
        post = PortalPost.query.filter_by(body="Grup duyurusu").one()
        assert post.visibility_scope == "group"
        return post.id


def _notified_user_ids(app, post_id):
    from app.models import Notification

    with app.app_context():
        rows = Notification.query.filter_by(source_type="portal_post", source_id=post_id).all()
        return sorted(row.user_id for row in rows)


def test_group_post_notifies_active_members_only(portal_app):
    ids = portal_app.config["_IDS"]
    post_id = _post_to_group(portal_app)

    # The active member is notified; the pending member, the non-member and the author are not.
    assert _notified_user_ids(portal_app, post_id) == [ids["PGN02"]]


def test_notified_members_are_exactly_the_members_who_can_view_the_post(portal_app):
    from app.extensions import db
    from app.models import PortalPost, User
    from app.services.portal_service import can_user_view_post

    ids = portal_app.config["_IDS"]
    post_id = _post_to_group(portal_app)
    notified = set(_notified_user_ids(portal_app, post_id))

    with portal_app.app_context():
        post = db.session.get(PortalPost, post_id)
        assert post is not None
        for sicil in ("PGN02", "PGN03", "PGN04"):
            user = db.session.get(User, ids[sicil])
            assert can_user_view_post(user, post) is (ids[sicil] in notified), sicil
