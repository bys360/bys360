"""Contract F06d (D2/D3): the Faz 3 performance visibility scope gives no technical role a global view.

Approved decision D2 (HUMAN_POLICY_APPROVED, 2026-10-09; restated 2026-10-10): ``sistem_yoneticisi``
/ ``system_admin`` keep their technical administration but get no automatic access to personnel or
performance data; technical admin is not access to personal data; least privilege; when there is
no reliable duty relation, restrict rather than guess.

``app/services/performance/completion_phase3_visibility_scope.ADMIN_ROLES`` put ``system_admin``,
``sistem_yoneticisi`` and the generic ``yonetici`` next to ``admin``. Each resolved to the "admin"
visibility key, so ``phase3_allowed_employee_ids`` returned every non-admin user. That set guards
the scorecard detail and PDF (``/performance/scorecard/<evaluation_id>``, where a second
published-scorecard check still stopped them), the performance reports' person scope and the
scorecard archive's manager scope: a user with the stored role ``yonetici`` (an archive manager
role) listed and opened every person's archived scorecard results.

Rule now: only ``admin`` / ``super_admin`` (and başkan, as before) are global. The technical roles
and ``yonetici`` are scope-limited like the other managers; their scope comes from the existing
hierarchy helper, which gives them their own record only.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "F06dPhase3VisibilityTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "f06d_phase3_visibility" / "dbs"
NOT_GLOBAL = ["sistem_yoneticisi", "sistem_yöneticisi", "system_admin", "yonetici", "yönetici"]
GLOBAL = ["admin", "super_admin", "baskan"]
ARCHIVE = {"owner": "F06D-ARSIV-OWNER-ROW", "yon": "F06D-ARSIV-YONETICI-OWN-ROW"}


@pytest.fixture
def env(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-f06d-phase3-visibility", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "f06d-phase3-visibility-first-login",
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
    from app.models import PerformanceEvaluation, PerformancePeriod, User
    from app.models.performance_archive_models import PerformanceArchivedResult

    with flask_app.app_context():
        db.create_all()
        ids = {}
        for key, role in (("owner", "personel"), ("tech", "sistem_yoneticisi"), ("sysadm", "system_admin"),
                          ("yon", "yonetici"), ("admin", "admin"), ("baskan", "baskan")):
            sicil = f"F6D{key.upper()}"
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Gorunurluk", soyad=key,
                        role=role, birim="Birim-A", is_active=True, must_change_password=False,
                        must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[key] = int(user.id)
        period = PerformancePeriod(title="F06d Donemi", period_type="quarterly", start_date=date(2026, 1, 1),
                                   end_date=date(2026, 3, 31), is_active=True)
        db.session.add(period)
        db.session.flush()
        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=ids["owner"])
        db.session.add(evaluation)
        db.session.flush()
        ids["evaluation"] = int(evaluation.id)
        for key in ("owner", "yon"):
            row = PerformanceArchivedResult(employee_id=ids[key], result_year=2024, period_label=ARCHIVE[key],
                                            score=Decimal("88.00"), description="F06d archive row",
                                            source_type="manual", created_by_user_id=ids["admin"])
            db.session.add(row)
            db.session.flush()
            ids[f"archive_{key}"] = int(row.id)
        db.session.commit()
    return SimpleNamespace(app=flask_app, ids=ids)


def _client(env, key):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": f"F6D{key.upper()}", "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), key
    return client


@pytest.mark.parametrize("role", NOT_GLOBAL)
def test_technical_roles_and_yonetici_are_not_global(role):
    from app.services.performance.completion_phase3_visibility_scope import build_visibility_profile

    profile = build_visibility_profile(SimpleNamespace(id=1, role=role))
    assert profile.can_view_global is False
    assert profile.role_key != "admin"


@pytest.mark.parametrize("role", GLOBAL)
def test_admin_and_baskan_stay_global(role):
    from app.services.performance.completion_phase3_visibility_scope import build_visibility_profile

    assert build_visibility_profile(SimpleNamespace(id=1, role=role)).can_view_global is True


@pytest.mark.parametrize("key", ["tech", "sysadm", "yon"])
def test_technical_roles_and_yonetici_reach_only_their_own_record(env, key):
    from app.extensions import db
    from app.models import User
    from app.services.performance.completion_phase3_visibility_scope import (
        phase3_allowed_employee_ids,
    )

    with env.app.app_context():
        assert phase3_allowed_employee_ids(db.session.get(User, env.ids[key])) == {env.ids[key]}


@pytest.mark.parametrize("key", ["tech", "sysadm", "yon"])
@pytest.mark.parametrize("suffix", ["", "/pdf"], ids=["detail", "pdf"])
def test_technical_roles_and_yonetici_cannot_open_another_persons_scorecard(env, key, suffix):
    response = _client(env, key).get(f"/performance/scorecard/{env.ids['evaluation']}{suffix}")
    assert response.status_code == 403


@pytest.mark.parametrize("key", ["tech", "sysadm", "yon"])
def test_technical_roles_and_yonetici_see_no_other_persons_archive(env, key):
    client = _client(env, key)
    listed = client.get("/performance/archive?no_cache=1")
    assert listed.status_code in (200, 403)
    assert ARCHIVE["owner"] not in listed.get_data(as_text=True)
    detail = client.get(f"/performance/archive/{env.ids['archive_owner']}")
    assert detail.status_code in (302, 403)
    assert ARCHIVE["owner"] not in detail.get_data(as_text=True)


def test_yonetici_keeps_its_own_archive_history(env):
    listed = _client(env, "yon").get("/performance/archive?no_cache=1")
    assert listed.status_code == 200 and ARCHIVE["yon"] in listed.get_data(as_text=True)


@pytest.mark.parametrize("key", ["admin", "baskan"])
def test_admin_and_baskan_keep_the_whole_archive(env, key):
    listed = _client(env, key).get("/performance/archive?no_cache=1")
    assert listed.status_code == 200 and ARCHIVE["owner"] in listed.get_data(as_text=True)


@pytest.mark.parametrize("key", ["admin", "baskan"])
def test_admin_and_baskan_keep_the_institution_scope(env, key):
    from app.extensions import db
    from app.models import User
    from app.services.performance.completion_phase3_visibility_scope import (
        phase3_allowed_employee_ids,
    )

    with env.app.app_context():
        assert env.ids["owner"] in phase3_allowed_employee_ids(db.session.get(User, env.ids[key]))
