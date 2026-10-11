"""Contract F06b (D2): the feedback integration page gives the technical roles no institution view.

Approved decision D2 (HUMAN_POLICY_APPROVED, 2026-10-09; restated 2026-10-10): ``sistem_yoneticisi``
/ ``system_admin`` keep their technical administration but get no automatic access to personnel
data, performance data or private notes; technical admin is not access to personal data.

GET /performance/feedback-integration (also /performans/gorusme-entegrasyonu; login only) treated
both technical roles as global: the route's ``_is_admin`` and the service's ``GLOBAL_ROLES``. A
technical administrator got the picker of every active user (name, sicil, title, unit) and, for
everyone, the scorecard rows and the in-period (private) interim notes; ``?employee_id=`` opened any
single person.

Rule now: the technical roles are neither global nor managers on this page. They see their own
records; a line manager keeps its reports; admin and başkan keep the institution-wide view.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text

PASSWORD = "F06bIntegrationTest1!"
NOTE = "F06B-PRIVATE-INTERIM-NOTE"
EMPLOYEE_NAME = "Gizlicalisan F6BEMP"
SCORE = 43.875

# sicil -> (role, yonetici_sicil)
USERS = {
    "F6BEMP": ("personel", "F6BMGR"),
    "F6BMGR": ("birim_sorumlusu", None),
    "F6BTEC": ("sistem_yoneticisi", None),
    "F6BSYS": ("system_admin", None),
    "F6BADM": ("admin", None),
    "F6BBSK": ("baskan", None),
}
TECHNICAL = ["F6BTEC", "F6BSYS"]


@pytest.mark.parametrize("role", ["sistem_yoneticisi", "system_admin"])
@pytest.mark.parametrize("flags", [{}, {"is_admin": True}, {"is_superuser": True},
                                  {"is_admin": True, "is_superuser": True}])
def test_technical_role_remains_self_only_despite_administration_flags(role, flags):
    from app.services.performance.feedback_integration import is_global_user, is_manager_user

    assert is_global_user(role, **flags) is False
    assert is_manager_user(role, **flags) is False


@pytest.fixture
def env(monkeypatch, install_interim_notes_schema):
    for key, value in {
        "APP_ENV": "testing", "FLASK_ENV": "testing", "SECRET_KEY": "test-secret-key-f06b-integration",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "f06b-integration-first-login", "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false", "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    uri = "sqlite:///:memory:"
    monkeypatch.setenv("DATABASE_URL", uri)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod, User
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        install_interim_notes_schema(db.engine)
        ids = {}
        for sicil, (role, manager) in USERS.items():
            first, last = ("Gizlicalisan", sicil) if sicil == "F6BEMP" else ("Kullanici", sicil)
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@bys360.test", ad=first, soyad=last, role=role,
                        yonetici_sicil=manager, birim="Birim A", is_active=True, must_change_password=False,
                        must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[sicil] = int(user.id)
        period = PerformancePeriod(title="F06b Donemi", period_type="quarterly", start_date=date(2026, 1, 1),
                                   end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.flush()
        db.session.add(PerformanceEvaluation(period_id=period.id, employee_id=ids["F6BEMP"], final_total_100=SCORE))
        db.session.execute(text("INSERT INTO performance_interim_notes (employee_id, period_id, note, note_type) "
                                "VALUES (:e, :p, :n, 'olumsuz')"), {"e": ids["F6BEMP"], "p": period.id, "n": NOTE})
        db.session.commit()
    return SimpleNamespace(app=flask_app, ids=ids)


def _client(env, sicil):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), sicil
    return client


def _page(env, sicil, query="", *, refused_ok=False):
    response = _client(env, sicil).get(f"/performance/feedback-integration{query}")
    assert response.status_code in ((200, 403) if refused_ok else (200,)), response.status_code
    return response.get_data(as_text=True)


@pytest.mark.parametrize("sicil", TECHNICAL)
@pytest.mark.parametrize("query", ["", "?employee_id={emp}"])
def test_technical_roles_see_no_other_persons_notes_scores_or_name(env, sicil, query):
    # Asking for another person is refused (403); the plain page shows only the user's own records.
    body = _page(env, sicil, query.format(emp=env.ids["F6BEMP"]), refused_ok=bool(query))
    assert NOTE not in body
    assert EMPLOYEE_NAME not in body
    assert str(SCORE) not in body


@pytest.mark.parametrize("sicil", TECHNICAL)
def test_technical_roles_get_only_their_own_records_from_the_service(env, sicil):
    from app.services.performance.feedback_integration import build_integration_context

    role = USERS[sicil][0]
    with env.app.app_context():
        ctx = build_integration_context(current_user_id=env.ids[sicil], current_user_role=role, is_admin=False)
        assert {int(p["id"]) for p in ctx["people"]} == {env.ids[sicil]}
        assert ctx["interim_notes"] == [] and ctx["scorecards"] == []
        denied = build_integration_context(current_user_id=env.ids[sicil], current_user_role=role,
                                           employee_id=env.ids["F6BEMP"])
        assert denied["access_denied"] is True and denied["interim_notes"] == []


@pytest.mark.parametrize("sicil", ["F6BMGR", "F6BADM", "F6BBSK"])
def test_line_manager_admin_and_baskan_keep_the_employee(env, sicil):
    body = _page(env, sicil, f"?employee_id={env.ids['F6BEMP']}")
    assert NOTE in body
    assert str(SCORE) in body


@pytest.mark.parametrize("uid", [None, 0, -1])
@pytest.mark.parametrize("role", ["sistem_yoneticisi", "system_admin", "manager", "admin"])
def test_missing_viewer_fails_closed(monkeypatch, uid, role):
    from app.services.performance import feedback_integration as integration

    monkeypatch.setattr(integration, "list_periods", lambda: [])
    def forbidden_query(**kwargs):
        pytest.fail("Unscoped personal data query must not run")
    monkeypatch.setattr(integration, "scorecard_rows", forbidden_query)
    monkeypatch.setattr(integration, "interim_note_rows", forbidden_query)
    monkeypatch.setattr(integration, "list_people", forbidden_query)
    ctx = integration.build_integration_context(current_user_id=uid, current_user_role=role)
    assert ctx["access_denied"] is True
    assert ctx["people"] == []
    assert ctx["scorecards"] == [] and ctx["interim_notes"] == []


def test_empty_personnel_scope_fails_closed(monkeypatch):
    from app.services.performance import feedback_integration as integration

    monkeypatch.setattr(integration, "list_people", lambda **kwargs: [])
    monkeypatch.setattr(integration, "list_periods", lambda: [])
    def forbidden_query(**kwargs):
        pytest.fail("Unscoped personal data query must not run")
    monkeypatch.setattr(integration, "scorecard_rows", forbidden_query)
    monkeypatch.setattr(integration, "interim_note_rows", forbidden_query)
    ctx = integration.build_integration_context(current_user_id=123, current_user_role="manager")
    assert ctx["access_denied"] is True


@pytest.mark.parametrize("sicil", TECHNICAL)
@pytest.mark.parametrize("flags", [{"is_admin": True}, {"is_superuser": True},
                                  {"is_admin": True, "is_superuser": True}])
def test_technical_administration_flags_do_not_grant_personal_data(env, sicil, flags):
    from app.services.performance.feedback_integration import build_integration_context

    with env.app.app_context():
        ctx = build_integration_context(current_user_id=env.ids[sicil],
                                        current_user_role=USERS[sicil][0], **flags)
        assert {int(p["id"]) for p in ctx["people"]} == {env.ids[sicil]}
        assert ctx["scorecards"] == [] and ctx["interim_notes"] == []
        denied = build_integration_context(current_user_id=env.ids[sicil],
                                           current_user_role=USERS[sicil][0],
                                           employee_id=env.ids["F6BEMP"], **flags)
        assert denied["access_denied"] is True
        assert denied["scorecards"] == [] and denied["interim_notes"] == []


@pytest.mark.parametrize("sicil", TECHNICAL)
@pytest.mark.parametrize("path", ["/performance/feedback-integration",
                                  "/performans/gorusme-entegrasyonu"])
def test_technical_role_with_admin_flags_cannot_open_other_employee(env, monkeypatch, sicil, path):
    from app.models import User

    monkeypatch.setattr(User, "is_admin", True, raising=False)
    monkeypatch.setattr(User, "is_superuser", True, raising=False)
    client = _client(env, sicil)
    response = client.get(f"{path}?employee_id={env.ids['F6BEMP']}")
    assert response.status_code == 403
    assert NOTE not in response.get_data(as_text=True)
    assert EMPLOYEE_NAME not in response.get_data(as_text=True)


@pytest.mark.parametrize("sicil", TECHNICAL)
def test_technical_roles_keep_their_own_records(env, sicil):
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod

    own_note = "F06B-OWN-NOTE"
    with env.app.app_context():
        period = db.session.query(PerformancePeriod).first()
        db.session.add(PerformanceEvaluation(period_id=period.id, employee_id=env.ids[sicil],
                                            final_total_100=84.125))
        db.session.execute(text("INSERT INTO performance_interim_notes (employee_id, period_id, note, note_type) "
                                "VALUES (:e, :p, :n, 'genel')"),
                           {"e": env.ids[sicil], "p": period.id, "n": own_note})
        db.session.commit()
    body = _page(env, sicil)
    assert own_note in body and "84.125" in body
    assert NOTE not in body and str(SCORE) not in body and EMPLOYEE_NAME not in body
