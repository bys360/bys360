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

import os
import tempfile
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

PASSWORD = "F06bIntegrationTest1!"
NOTE = "F06B-PRIVATE-INTERIM-NOTE"
EMPLOYEE_NAME = "Gizlicalisan F6BEMP"
_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_f06b_integration")

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
    os.makedirs(_DB_DIR, exist_ok=True)
    uri = "sqlite:///" + os.path.join(_DB_DIR, f"f06b_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
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
        db.session.add(PerformanceEvaluation(period_id=period.id, employee_id=ids["F6BEMP"]))
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
