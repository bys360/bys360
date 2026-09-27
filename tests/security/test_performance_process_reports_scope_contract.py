"""P0-01 regression contract: performance process reports data isolation.

Final pre-live audit (2026-09-27) proved that /performance/process-reports and
its Turkish alias /performans/surec-raporlari were protected by
``@login_required`` only, and that ``_bys360_process_reports_advanced_context``
ignored its ``viewer`` argument (``WHERE 1=1``). Any authenticated personnel
could therefore read another employee's name, process status and
``final_score`` (including below-70 / president-approval rows).

The report reads the same ``performance_process_flows`` table as the sibling
"Süreç Takibi" page, so it must follow that page's canonical rules
(``app/services/performance/process_engine_phase8_tracking.py``):

* route gate: ``can_view_process_tracking`` (same role set as the menu
  registry entry for ``performance_process_reports``);
* data scope: ``process_flow_scope_clause`` -- admin / başkan / başkan
  yardımcısı unrestricted, everyone else only flows they own or that are
  their own, unresolved viewer matches nothing (fail closed).
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

ALIASES = ("/performance/process-reports", "/performans/surec-raporlari")
_TEST_PASSWORD = "TestProcessReportsScope-2026!x"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield from _build_app(monkeypatch, tmp_path_factory.mktemp("p0_01"))


def _build_app(monkeypatch: pytest.MonkeyPatch, tmp_path):
    for key, value in {
        "APP_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-p0-01-process-reports-scope",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "p0-01-first-login-test-pw",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
    }.items():
        monkeypatch.setenv(key, value)

    db_path = os.path.join(str(tmp_path), f"p0_01_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
    )
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        db.session.commit()
    yield flask_app


def _user(db, sicil: str, ad: str, role: str):
    from app.models import User

    user = User(
        ad=ad,
        soyad="Scope",
        sicil_no=sicil,
        email=f"{sicil.lower()}@example.gov.tr",
        unvan="Uzman",
        role=role,
        birim="Birim",
        is_active=True,
    )
    user.set_password(_TEST_PASSWORD)
    for flag in ("must_change_password", "must_set_security_question", "is_first_login"):
        if hasattr(user, flag):
            setattr(user, flag, False)
    db.session.add(user)
    return user


@pytest.fixture(scope="module")
def seeded(app):
    from app.extensions import db
    from app.models.performance_process_engine_models import PerformanceProcessFlow

    with app.app_context():
        users = {
            "admin": _user(db, "P01ADM", "AdminViewer", "admin"),
            "a": _user(db, "P01PRA", "PersonelAlfa", "personel"),
            "b": _user(db, "P01PRB", "PersonelBeta", "personel"),
            "c": _user(db, "P01PRC", "PersonelGama", "personel"),
            "coord": _user(db, "P01KOR", "KoordinatorDelta", "koordinator"),
        }
        db.session.commit()
        # B's flow is owned by the coordinator; C's flow by the admin.
        db.session.add(
            PerformanceProcessFlow(
                evaluation_id=910001,
                period_id=1,
                employee_id=users["b"].id,
                current_owner_id=users["coord"].id,
                current_status="president_pending",
                final_score=Decimal("55.50"),
                is_low_score=True,
                president_approval_required=True,
                president_approval_status="pending",
            )
        )
        db.session.add(
            PerformanceProcessFlow(
                evaluation_id=910002,
                period_id=1,
                employee_id=users["c"].id,
                current_owner_id=users["admin"].id,
                current_status="president_pending",
                final_score=Decimal("61.25"),
                is_low_score=True,
                president_approval_required=True,
                president_approval_status="pending",
            )
        )
        db.session.commit()
        data = {key: SimpleNamespace(id=u.id, sid=u.get_id(), role=u.role, unvan=u.unvan) for key, u in users.items()}
    # Return outside the app context: a lingering context would be reused by
    # every test-client request and leak Flask-Login's cached user between them.
    return data


def _client_for(app, session_id: str):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = session_id
        sess["_fresh"] = True
    return client


@pytest.mark.parametrize("path", ALIASES)
@pytest.mark.parametrize("query", ["", "?status=president", "?status_filter=pending"])
def test_ordinary_personnel_cannot_read_other_employee_process_data(app, seeded, path, query) -> None:
    response = _client_for(app, seeded["a"].sid).get(path + query)
    body = response.get_data(as_text=True)

    assert response.status_code == 403
    assert "PersonelBeta" not in body
    assert "PersonelGama" not in body
    assert "55.5" not in body
    assert "61.25" not in body


@pytest.mark.parametrize("path", ALIASES)
def test_employee_cannot_open_report_even_with_own_flow(app, seeded, path) -> None:
    """Plain personnel are outside the canonical process-tracking role set
    (menu registry does not offer this page to them); a direct URL must not
    bypass that gate even for the employee whose own flow exists."""
    response = _client_for(app, seeded["b"].sid).get(path)
    body = response.get_data(as_text=True)

    assert response.status_code == 403
    assert "PersonelGama" not in body
    assert "61.25" not in body


@pytest.mark.parametrize("path", ALIASES)
def test_scoped_coordinator_sees_only_owned_flows(app, seeded, path) -> None:
    response = _client_for(app, seeded["coord"].sid).get(path + "?status=president")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "PersonelBeta" in body
    assert "PersonelGama" not in body
    assert "61.25" not in body


@pytest.mark.parametrize("path", ALIASES)
def test_admin_keeps_institution_wide_report(app, seeded, path) -> None:
    response = _client_for(app, seeded["admin"].sid).get(path + "?status=president")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "PersonelBeta" in body
    assert "PersonelGama" in body


def test_both_aliases_render_identically_for_each_viewer(app, seeded) -> None:
    for key in ("a", "coord", "admin"):
        first = _client_for(app, seeded[key].sid).get(ALIASES[0])
        second = _client_for(app, seeded[key].sid).get(ALIASES[1])
        assert first.status_code == second.status_code, key


def test_context_builder_scopes_to_viewer_and_keeps_own_data(app, seeded) -> None:
    from app.performance.process_engine_phase10_reports_routes import (
        _bys360_process_reports_advanced_context,
    )

    with app.app_context():
        own = _bys360_process_reports_advanced_context(viewer=seeded["b"], status_filter="")
        coord = _bys360_process_reports_advanced_context(viewer=seeded["coord"], status_filter="")
        admin = _bys360_process_reports_advanced_context(viewer=seeded["admin"], status_filter="")

    assert own["summary"]["total"] == 1
    assert [row["employee_name"] for row in own["recent_rows"]] == ["PersonelBeta Scope"]
    assert coord["summary"]["total"] == 1
    assert [row["employee_name"] for row in coord["recent_rows"]] == ["PersonelBeta Scope"]
    assert admin["summary"]["total"] == 2


@pytest.mark.parametrize(
    "viewer",
    [None, SimpleNamespace(id=None, role="koordinator", unvan=""), SimpleNamespace(id=0, role="", unvan="")],
)
def test_context_builder_fails_closed_for_unresolved_viewer(app, seeded, viewer) -> None:
    from app.performance.process_engine_phase10_reports_routes import (
        _bys360_process_reports_advanced_context,
    )

    with app.app_context():
        context = _bys360_process_reports_advanced_context(viewer=viewer, status_filter="")

    assert context["summary"]["total"] == 0
    assert context["recent_rows"] == []
    assert context["president_rows"] == []
    assert context["owner_rows"] == []
    assert context["status_rows"] == []
