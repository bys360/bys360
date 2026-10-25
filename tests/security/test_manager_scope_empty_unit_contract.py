"""Contract: an empty organisation field never grants scope over other people.

get_manager_scope_users / get_hierarchy_scope_users built their filters straight from the
manager's own fields: ``User.birim == user.birim`` (and ust_birim, and the manager's sicil
for the yonetici_sicil links). When the manager's value was NULL, '' or whitespace, the
comparison became ``IS NULL`` / ``= ''`` / ``= '   '`` and pulled in every user whose field
was empty in the same way. Through build_user_scope_context this widened performance
reports and exports, HR leave/attendance writes, comparisons, archive and the dashboard.
The HR helpers had two more fail-open paths: an empty scope id list returned everyone,
and the exception fallback gave grup_baskani / mali_musavir the whole institution and
put every user without a unit into one "Belirsiz birim".

Expected (owner-approved) behaviour: empty or whitespace-only fields produce no scope; a
manager without a verified unit sees only themselves plus people linked to a valid sicil;
an empty scope or a scope error never becomes institution-wide; top management
(admin, baskan, baskan_yardimcisi) keeps full access.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest

PASSWORD = "ScopeEmptyUnitTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "scope_empty_unit" / "dbs"
EMPTY_VALUES = pytest.mark.parametrize("empty", [None, "", "   "], ids=["null", "bos", "bosluk"])
UNIT_MANAGERS = pytest.mark.parametrize("role", ["grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"])


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-scope-empty-unit", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "scope-empty-unit-first-login",
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

    with flask_app.app_context():
        db.create_all()
    return flask_app


def _user(sicil, role="personel", birim=None, ust_birim=None, manager=None):
    from app.extensions import db
    from app.models import User

    row = User(sicil_no=sicil, email=f"{(sicil.strip() or 'bos').lower()}-{uuid.uuid4().hex[:6]}@example.gov.tr",
               ad="Sahte", soyad=sicil.strip() or "Bos", role=role, birim=birim, ust_birim=ust_birim,
               yonetici_sicil=manager, is_active=True, must_change_password=False, must_set_security_question=False)
    row.set_password(PASSWORD)
    db.session.add(row)
    return row


def _others(empty):
    """Başka birimlerdeki personel: alanları kendi boş biçiminde (NULL / '' / '   ')."""
    _user("OT_BIRIM", birim=empty, ust_birim="Sahte Üst X")
    _user("OT_UST", birim="Sahte Birim Y", ust_birim=empty)
    _user("OT_YON", birim="Sahte Birim Z", ust_birim="Sahte Üst Z", manager=empty)


def _sicils(rows):
    return sorted(u.sicil_no for u in rows)


# ---------------------------------------------------------------------------
# Kaynak fonksiyonlar
# ---------------------------------------------------------------------------
@EMPTY_VALUES
@UNIT_MANAGERS
def test_manager_without_a_unit_sees_only_themselves(app, role, empty):
    from app.extensions import db
    from app.services.hierarchy_admin_service import (
        get_hierarchy_scope_users,
        get_manager_scope_users,
    )

    with app.app_context():
        _others(empty)
        manager = _user("MGR", role=role, birim=empty, ust_birim=empty)
        db.session.commit()
        assert _sicils(get_manager_scope_users(manager)) in ([], ["MGR"])
        assert _sicils(get_hierarchy_scope_users(manager)) in ([], ["MGR"])


@EMPTY_VALUES
@pytest.mark.parametrize("role", ["grup_baskani", "mali_musavir"])
def test_group_president_with_unit_but_empty_upper_unit_keeps_only_unit_scope(app, role, empty):
    from app.extensions import db
    from app.services.hierarchy_admin_service import (
        get_hierarchy_scope_users,
        get_manager_scope_users,
    )

    with app.app_context():
        _others(empty)
        _user("IN_A", birim="Sahte Birim A", ust_birim="Sahte Üst A")
        _user("IN_SUB", birim="Sahte Alt Birim", ust_birim="Sahte Birim A")
        manager = _user("MGR", role=role, birim="Sahte Birim A", ust_birim=empty)
        db.session.commit()
        expected = ["IN_A", "IN_SUB", "MGR"]
        assert _sicils(get_manager_scope_users(manager)) == expected
        assert _sicils(get_hierarchy_scope_users(manager)) == expected


@EMPTY_VALUES
def test_personel_without_a_unit_sees_only_themselves_in_hierarchy_scope(app, empty):
    from app.extensions import db
    from app.services.hierarchy_admin_service import (
        get_hierarchy_scope_users,
        get_manager_scope_users,
    )

    with app.app_context():
        _others(empty)
        person = _user("PER", birim=empty, ust_birim=empty)
        db.session.commit()
        assert _sicils(get_manager_scope_users(person)) == ["PER"]
        assert _sicils(get_hierarchy_scope_users(person)) == ["PER"]


@pytest.mark.parametrize("bad_sicil", ["", "   "], ids=["bos", "bosluk"])
@pytest.mark.parametrize("role", ["koordinator", "birim_sorumlusu"])
def test_invalid_manager_sicil_does_not_link_people_with_the_same_empty_manager_field(app, role, bad_sicil):
    from app.extensions import db
    from app.services.hierarchy_admin_service import (
        get_hierarchy_scope_users,
        get_manager_scope_users,
    )

    with app.app_context():
        _user("OT_LINK", birim="Sahte Birim Z", manager=bad_sicil)
        manager = _user(bad_sicil, role=role, birim="Sahte Birim K")
        db.session.commit()
        assert "OT_LINK" not in _sicils(get_manager_scope_users(manager))
        assert "OT_LINK" not in _sicils(get_hierarchy_scope_users(manager))


@pytest.mark.parametrize("role", ["koordinator", "birim_sorumlusu"])
def test_coordinator_without_a_unit_keeps_verified_sicil_links(app, role):
    from app.extensions import db
    from app.services.hierarchy_admin_service import (
        get_hierarchy_scope_users,
        get_manager_scope_users,
    )

    with app.app_context():
        _others(None)
        _user("DIRECT", birim="Sahte Birim D", manager="MGR")
        manager = _user("MGR", role=role, birim=None)
        db.session.commit()
        assert _sicils(get_manager_scope_users(manager)) == ["DIRECT"]  # mevcut davranış: kendisi listede yok
        assert _sicils(get_hierarchy_scope_users(manager)) == ["DIRECT", "MGR"]


@pytest.mark.parametrize("role", ["admin", "baskan", "baskan_yardimcisi"])
def test_top_management_keeps_institution_wide_scope(app, role):
    from app.extensions import db
    from app.services.hierarchy_admin_service import (
        get_hierarchy_scope_users,
        get_manager_scope_users,
    )

    with app.app_context():
        _others(None)
        manager = _user("TOP", role=role, birim=None)
        db.session.commit()
        for rows in (get_manager_scope_users(manager), get_hierarchy_scope_users(manager)):
            assert {"OT_BIRIM", "OT_UST", "OT_YON"} <= set(_sicils(rows))


# ---------------------------------------------------------------------------
# İK yardımcıları: boş kapsam ve hata yolu kurum geneline dönüşmez
# ---------------------------------------------------------------------------
def test_hr_filter_with_an_empty_scope_returns_nobody(app):
    from app.extensions import db
    from app.institutional.hr_scope_helpers import _filter_users_in_scope
    from app.models import User

    with app.app_context():
        _others(None)
        db.session.commit()
        users = User.query.all()
        assert _filter_users_in_scope(users, {"scope_user_ids": []}) == []
        assert _filter_users_in_scope(users, None) == []


@pytest.mark.parametrize("role, unit", [("grup_baskani", "Sahte Birim A"), ("mali_musavir", "Sahte Birim A"),
                                        ("grup_baskani", None), ("birim_sorumlusu", None), ("personel", None)])
def test_hr_exception_fallback_never_grants_the_whole_institution(app, role, unit):
    from flask_login import login_user

    from app.extensions import db
    from app.institutional.hr_scope_helpers import _fallback_scope_context

    with app.app_context():
        _others(None)
        _user("OT_BOTH", birim=None, ust_birim=None)  # eski kodda "Belirsiz birim" altında toplanırdı
        same_unit = _user("SAME_A", birim="Sahte Birim A")
        me = _user("ME", role=role, birim=unit)
        db.session.commit()
        allowed = {me.id, same_unit.id} if unit and role != "personel" else {me.id}
        for requested in ("all", "unit", "personal"):
            with app.test_request_context(f"/hr-management?scope={requested}"):
                login_user(me)
                ids = set(_fallback_scope_context()["scope_user_ids"])
            assert me.id in ids and ids <= allowed, (requested, ids)


@pytest.mark.parametrize("role", ["admin", "baskan", "baskan_yardimcisi"])
def test_hr_exception_fallback_keeps_top_management_institution_view(app, role):
    from flask_login import login_user

    from app.extensions import db
    from app.institutional.hr_scope_helpers import _fallback_scope_context
    from app.models import User

    with app.app_context():
        _others(None)
        me = _user("TOP", role=role, birim=None)
        db.session.commit()
        with app.test_request_context("/hr-management?scope=all"):
            login_user(me)
            ids = set(_fallback_scope_context()["scope_user_ids"])
        assert ids == {u.id for u in User.query.filter(User.is_active.is_(True)).all()}


# ---------------------------------------------------------------------------
# Uçtan uca: yazma işlemi ve okuma ekranı
# ---------------------------------------------------------------------------
def _login(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", "")
    return client


@pytest.mark.parametrize("role", ["birim_sorumlusu", "grup_baskani"])
def test_manager_without_a_unit_cannot_approve_another_units_leave(app, role):
    from app.extensions import db
    from app.models import PersonnelLeave

    with app.app_context():
        target = _user("LV_TARGET", birim=None, ust_birim=None)  # başka biriminden, alanları boş personel
        _user("LV_MGR", role=role, birim=None)
        db.session.flush()
        db.session.add(PersonnelLeave(user_id=target.id, leave_type="yillik", status="beklemede",
                                      start_date=date(2026, 10, 5), end_date=date(2026, 10, 9)))
        db.session.commit()
        leave_id = PersonnelLeave.query.one().id
    _login(app, "LV_MGR").post(f"/hr-management/leave/{leave_id}/status", data={"status": "onaylandi"})
    with app.app_context():
        assert PersonnelLeave.query.one().status == "beklemede"


def test_manager_with_a_unit_still_approves_leave_in_their_unit(app):
    from app.extensions import db
    from app.models import PersonnelLeave

    with app.app_context():
        target = _user("LV_OWN", birim="Sahte Birim A")
        _user("LV_BS", role="birim_sorumlusu", birim="Sahte Birim A")
        db.session.flush()
        db.session.add(PersonnelLeave(user_id=target.id, leave_type="yillik", status="beklemede",
                                      start_date=date(2026, 10, 5), end_date=date(2026, 10, 9)))
        db.session.commit()
        leave_id = PersonnelLeave.query.one().id
    _login(app, "LV_BS").post(f"/hr-management/leave/{leave_id}/status", data={"status": "onaylandi"})
    with app.app_context():
        assert PersonnelLeave.query.one().status == "onaylandi"
