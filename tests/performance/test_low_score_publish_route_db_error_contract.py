"""BYS360 PERFORMANCE P0.2G-R1: publish route contract for block-reason DB errors.

Route: POST /performance/publish/evaluation/<id>
(main.performance_publish_evaluation, app/performance/engagement_publish_routes.py).

Call chain to the P0.2G failure point:

    performance_publish_evaluation
    -> publish_service.publish_evaluation (app/services/publish/operations.py)
       -> ensure_low_score_process_for_evaluation(evaluation, actor)   # flushed
       -> is_evaluation_publishable (visibility_guard)
          -> publish_preflight_rules.validate_evaluation_for_publish
             -> get_low_score_publish_block_reason(evaluation, ensure=True)
                -> ensure_low_score_process_for_evaluation(evaluation)  # failure here

Route contract (unchanged by P0.2G): a not-publishable result flashes the
reason as "warning" and redirects without committing; any exception is
logged, rolled back and flashed as "Tekil yayın sırasında hata oluştu."
("danger"), then redirected; success commits and flashes
"Sonuç personele yayımlandı.".

Before P0.2G the ensure call's database errors were swallowed inside
get_low_score_publish_block_reason and the route showed the generic
"Başkan onayı bekliyor..." lock reason as a business warning. Since P0.2G the
SQLAlchemyError reaches the route's exception handler.

Test-only boundaries, both unrelated to P0.2G: can_access_menu (the live
menu matrix, same bypass as tests/behavior/test_h1f_route_exception_leak_contract.py)
and the personnel support pre-approval gate, whose Alembic-owned table is not
created by db.create_all() (same bypass as
tests/test_performance_publish_preflight_rules_behavior.py::
test_true_happy_path_publishes_when_every_real_rule_and_gate_clears).

Real Flask app, real test client and login, file-backed SQLite test database only.
"""
from __future__ import annotations

import importlib
import logging
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

_SERVICE_MODULE = "app.services.performance.low_score_process_service"
_PREFLIGHT_MODULE = "app.services.performance.publish_preflight_rules"
_ROUTE_MODULE = "app.performance.engagement_publish_routes"
_PUBLISH_ERROR_FLASH = ("danger", "Tekil yayın sırasında hata oluştu.")
_PUBLISH_SUCCESS_FLASH = ("success", "Sonuç personele yayımlandı.")
# Reason returned when no process could be resolved (also the non-DB error fallback).
_GENERIC_LOCK_REASON = "Başkan onayı bekliyor. Başkan/Üst Onay tamamlanmadan 70 altı karne yayınlanamaz. Başkan/Üst Onay Yayın Kilidi"
# Reason computed from an existing, not yet approved process.
_PRESIDENT_PENDING_REASON = "Başkan onayı bekliyor. Başkan/Üst Onay şartı tamamlanmadan yayın yapılamaz. Başkan/Üst Onay Yayın Kilidi"
_GENERAL_COMMENT = "Dönem boyunca hedeflere göre ayrıntılı genel görüş ve gelişim notu."
_PASSWORD = "TestPublishRouteContract1!"
_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_p02g_r1_route")
_counter = 0


# ---------------------------------------------------------------------------
# Real Flask app + file-backed SQLite (same pattern as
# tests/behavior/test_low_score_process_service_workflow_contract.py::_make_app).
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    import os
    import uuid

    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-p02g-r1-route-contract",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "test-password",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
    }.items():
        monkeypatch.setenv(key, value)
    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_uri = "sqlite:///" + os.path.join(_TMP_DB_DIR, f"p02g_r1_{uuid.uuid4().hex}.sqlite3").replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=db_uri)

    from sqlalchemy import event

    from app.extensions import db

    with flask_app.app_context():

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
    return flask_app


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _user(flask_app, *, role: str) -> tuple[int, str]:
    from app.extensions import db
    from app.models import User

    with flask_app.app_context():
        n = _next()
        sicil_no = f"P2GR{n:06d}"
        user = User(
            sicil_no=sicil_no,
            email=f"p02g-r1-route-{n}@bys360.test",
            ad="P02GR1",
            soyad=f"User{n}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return int(user.id), sicil_no


@pytest.fixture
def publish_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """App + logged-in admin test client; only the two unrelated gates are bypassed."""
    flask_app = _make_app(monkeypatch)
    monkeypatch.setattr(importlib.import_module("app.route_support"), "can_access_menu", lambda user, key: True)
    monkeypatch.setattr(
        importlib.import_module(_PREFLIGHT_MODULE),
        "get_personnel_support_publish_block_reason",
        lambda evaluation, **kwargs: "",
    )
    admin_id, admin_sicil = _user(flask_app, role="admin")
    client = flask_app.test_client()
    login = client.post("/login", data={"sicil_or_email": admin_sicil, "password": _PASSWORD}, follow_redirects=False)
    assert login.status_code == 302
    assert "/login" not in login.headers.get("Location", "")
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)  # the login's own "Giriş başarılı." flash
    return SimpleNamespace(app=flask_app, client=client, admin_id=admin_id)


def _seed_evaluation(flask_app, score: float) -> tuple[int, int]:
    """A completed, not yet published evaluation that passes every non-low-score
    preflight rule: level 1 completed, one level 1 criteria score, general comment."""
    from app.extensions import db
    from app.models import (
        PerformanceCriteria,
        PerformanceEvaluation,
        PerformanceEvaluationItem,
        PerformancePeriod,
    )

    employee_id, _sicil = _user(flask_app, role="personel")
    with flask_app.app_context():
        n = _next()
        criteria = PerformanceCriteria(name=f"P0.2G-R1 Kriter {n}", weight=100.0)
        period = PerformancePeriod(
            title=f"P0.2G-R1 Dönem {n}",
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
        )
        db.session.add_all([criteria, period])
        db.session.flush()
        evaluation = PerformanceEvaluation(
            period_id=period.id,
            employee_id=employee_id,
            final_total_100=score,
            status="completed",
            workflow_status="tamamlandi",
            level_1_completed=True,
            level_1_general_comment=_GENERAL_COMMENT,
            is_published_to_employee=False,
        )
        db.session.add(evaluation)
        db.session.flush()
        db.session.add(
            PerformanceEvaluationItem(
                evaluation_id=evaluation.id,
                criteria_id=criteria.id,
                manager_level=1,
                score=4.0,
                score_100=80.0,
                justification="Hedeflerin büyük bölümü karşılandı.",
            )
        )
        db.session.commit()
        return period.id, evaluation.id


def _release(flask_app, evaluation_id: int) -> None:
    """President approval of a first low score also records the warning, so the card is released."""
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc

    president_id, _sicil = _user(flask_app, role="baskan")
    with flask_app.app_context():
        process = svc.ensure_low_score_process_for_evaluation(db.session.get(PerformanceEvaluation, evaluation_id), actor_user_id=president_id)
        assert process is not None
        svc.president_approve_process(process, actor=president_id)
        db.session.commit()


def _state(flask_app, evaluation_id: int) -> dict[str, Any]:
    """Committed state as a fresh transaction sees it."""
    from app.extensions import db

    params = {"e": evaluation_id}
    with flask_app.app_context():
        db.session.remove()
        published, published_at, period_published = db.session.execute(
            text(
                "SELECT e.is_published_to_employee, e.published_to_employee_at, p.results_published "
                "FROM performance_evaluations e JOIN performance_periods p ON p.id = e.period_id WHERE e.id = :e"
            ),
            params,
        ).one()
        state = {
            "published": bool(published),
            "published_at_set": published_at is not None,
            "period_published": bool(period_published),
            "processes": db.session.execute(text("SELECT COUNT(*) FROM performance_low_score_processes WHERE evaluation_id = :e"), params).scalar(),
            "events": db.session.execute(
                text(
                    "SELECT COUNT(*) FROM performance_low_score_process_events ev "
                    "JOIN performance_low_score_processes p ON p.id = ev.process_id WHERE p.evaluation_id = :e"
                ),
                params,
            ).scalar(),
            "publish_logs": db.session.execute(text("SELECT COUNT(*) FROM performance_publish_logs WHERE evaluation_id = :e"), params).scalar(),
        }
        db.session.remove()
    return state


def _publish(env: SimpleNamespace, evaluation_id: int) -> tuple[Any, list[tuple[str, str]]]:
    """POST the real route; returns the response and the flashes it queued."""
    response = env.client.post(f"/performance/publish/evaluation/{evaluation_id}", data={}, follow_redirects=False)
    with env.client.session_transaction() as sess:
        flashes = [tuple(item) for item in sess.pop("_flashes", [])]
    return response, flashes


def _assert_redirect_to_dashboard(response, period_id: int) -> None:
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/performance/publish?period_id={period_id}")


def _inject_in_block_reason_ensure(monkeypatch: pytest.MonkeyPatch, fail) -> dict[str, Any]:
    """Make ``fail(evaluation)`` run at the start of the ensure call made from
    inside get_low_score_publish_block_reason; the preceding direct ensure call
    in publish_evaluation passes through untouched. publish_preflight_rules
    binds get_low_score_publish_block_reason at import, so both bindings are
    wrapped; the wrapper calls the real function."""
    svc = importlib.import_module(_SERVICE_MODULE)
    real_ensure = svc.ensure_low_score_process_for_evaluation
    real_block_reason = svc.get_low_score_publish_block_reason
    seen: dict[str, Any] = {"inside_block_reason": False, "calls": 0}

    def _block_reason(*args, **kwargs):
        seen["inside_block_reason"] = True
        try:
            return real_block_reason(*args, **kwargs)
        finally:
            seen["inside_block_reason"] = False

    def _ensure(evaluation, *args, **kwargs):
        if seen["inside_block_reason"]:
            seen["calls"] += 1
            if seen["calls"] == 1:
                fail(evaluation)
        return real_ensure(evaluation, *args, **kwargs)

    monkeypatch.setattr(svc, "get_low_score_publish_block_reason", _block_reason)
    monkeypatch.setattr(importlib.import_module(_PREFLIGHT_MODULE), "get_low_score_publish_block_reason", _block_reason)
    monkeypatch.setattr(svc, "ensure_low_score_process_for_evaluation", _ensure)
    return seen


def _add_duplicate_process(evaluation) -> None:
    """A real flush error inside the real ensure: a second process row for the
    same evaluation (UNIQUE evaluation_id) is autoflushed by ensure's own query."""
    from app.extensions import db
    from app.models import PerformanceLowScoreProcess

    db.session.add(
        PerformanceLowScoreProcess(
            period_id=evaluation.period_id,
            evaluation_id=evaluation.id,
            employee_id=evaluation.employee_id,
            calendar_year=2026,
        )
    )


def _execute_invalid_statement(evaluation) -> None:
    """A real driver error from a statement."""
    from app.extensions import db

    db.session.execute(text("SELECT no_such_column FROM performance_evaluations"))


def _raise_runtime(evaluation) -> None:
    raise RuntimeError("simulated policy runtime failure")


def _logged_errors(caplog: pytest.LogCaptureFixture, module: str) -> list[str]:
    """Exception class names logged (logger.exception) by ``module``, in order."""
    names = []
    for record in caplog.records:
        exc_type = record.exc_info[0] if record.exc_info else None
        if record.name == module and exc_type is not None:
            names.append(exc_type.__name__)
    return names


_UNCHANGED = {"published": False, "published_at_set": False, "period_published": False, "processes": 0, "events": 0, "publish_logs": 0}


# ---------------------------------------------------------------------------
# Database errors in the block reason's ensure -> route error contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fail", "expected"),
    [(_add_duplicate_process, "IntegrityError"), (_execute_invalid_statement, "OperationalError")],
    ids=["integrity_error", "operational_error"],
)
def test_publish_route_block_reason_database_error_is_rolled_back_and_reported(publish_env, monkeypatch, caplog, fail, expected) -> None:
    """The process + events flushed by publish_evaluation's own ensure call
    are rolled back with everything else; the user sees the route's existing
    generic publish error, not a fabricated "Başkan onayı bekliyor" reason; no
    500. The same client then publishes another card successfully."""
    period_id, evaluation_id = _seed_evaluation(publish_env.app, 57.0)
    seen = _inject_in_block_reason_ensure(monkeypatch, fail)

    with caplog.at_level(logging.ERROR):
        response, flashes = _publish(publish_env, evaluation_id)
    assert seen["calls"] == 1
    _assert_redirect_to_dashboard(response, period_id)
    assert flashes == [_PUBLISH_ERROR_FLASH]
    assert _logged_errors(caplog, _SERVICE_MODULE) == []  # not swallowed into a reason
    assert _logged_errors(caplog, _ROUTE_MODULE) == [expected]  # reached the route's handler
    assert _state(publish_env.app, evaluation_id) == _UNCHANGED

    # Session and app are clean afterwards: a normal publish on the same client
    # succeeds (the injection fires only once; a 70+ card never reaches it).
    other_period_id, other_id = _seed_evaluation(publish_env.app, 82.0)
    response, flashes = _publish(publish_env, other_id)
    _assert_redirect_to_dashboard(response, other_period_id)
    assert _PUBLISH_SUCCESS_FLASH in flashes
    assert _state(publish_env.app, other_id)["published"] is True


# ---------------------------------------------------------------------------
# Unchanged paths: non-DB error, business block, normal publish
# ---------------------------------------------------------------------------


def test_publish_route_block_reason_runtime_error_keeps_fail_closed_warning(publish_env, monkeypatch, caplog) -> None:
    period_id, evaluation_id = _seed_evaluation(publish_env.app, 57.0)
    _inject_in_block_reason_ensure(monkeypatch, _raise_runtime)

    with caplog.at_level(logging.ERROR):
        response, flashes = _publish(publish_env, evaluation_id)
    _assert_redirect_to_dashboard(response, period_id)
    assert flashes == [("warning", _GENERIC_LOCK_REASON)]
    assert _logged_errors(caplog, _SERVICE_MODULE) == ["RuntimeError"]
    assert _logged_errors(caplog, _ROUTE_MODULE) == []
    assert _state(publish_env.app, evaluation_id) == _UNCHANGED


def test_publish_route_low_score_without_president_approval_shows_business_reason(publish_env) -> None:
    period_id, evaluation_id = _seed_evaluation(publish_env.app, 57.0)
    response, flashes = _publish(publish_env, evaluation_id)
    _assert_redirect_to_dashboard(response, period_id)
    assert flashes == [("warning", _PRESIDENT_PENDING_REASON)]
    assert _state(publish_env.app, evaluation_id) == _UNCHANGED


def test_publish_route_normal_publish_succeeds(publish_env) -> None:
    period_id, evaluation_id = _seed_evaluation(publish_env.app, 82.0)
    response, flashes = _publish(publish_env, evaluation_id)
    _assert_redirect_to_dashboard(response, period_id)
    assert _PUBLISH_SUCCESS_FLASH in flashes
    assert not [flash for flash in flashes if flash[0] == "danger"]
    assert _state(publish_env.app, evaluation_id) == {
        "published": True,
        "published_at_set": True,
        "period_published": True,
        "processes": 0,
        "events": 0,
        "publish_logs": 1,
    }


def test_publish_route_released_low_score_publish_succeeds(publish_env) -> None:
    """Goes through get_low_score_publish_block_reason(ensure=True) with a
    released process: no block reason, the card is published."""
    period_id, evaluation_id = _seed_evaluation(publish_env.app, 57.0)
    _release(publish_env.app, evaluation_id)
    before = _state(publish_env.app, evaluation_id)

    response, flashes = _publish(publish_env, evaluation_id)
    _assert_redirect_to_dashboard(response, period_id)
    assert _PUBLISH_SUCCESS_FLASH in flashes
    assert not [flash for flash in flashes if flash[0] == "danger"]
    after = _state(publish_env.app, evaluation_id)
    assert (after["published"], after["period_published"], after["publish_logs"]) == (True, True, 1)
    assert (after["processes"], after["events"]) == (before["processes"], before["events"]) == (1, 5)


# ---------------------------------------------------------------------------
# Visibility (ensure=False) is untouched by P0.2G: DB error stays fail-closed
# ---------------------------------------------------------------------------


def test_visibility_lookup_database_error_stays_fail_closed(publish_env, monkeypatch, caplog) -> None:
    """The read-only ensure=False lookup used by visibility_guard still turns a
    database error into the generic lock reason (card hidden), as before P0.2G."""
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance import low_score_process_service as svc, visibility_guard

    _period_id, evaluation_id = _seed_evaluation(publish_env.app, 57.0)
    _release(publish_env.app, evaluation_id)
    assert _publish(publish_env, evaluation_id)[1][0] == _PUBLISH_SUCCESS_FLASH

    with publish_env.app.app_context():
        assert visibility_guard.is_employee_visible(db.session.get(PerformanceEvaluation, evaluation_id)) is True

    def _broken_filter_by(**kwargs):
        _execute_invalid_statement(None)

    monkeypatch.setattr(svc, "PerformanceLowScoreProcess", SimpleNamespace(query=SimpleNamespace(filter_by=_broken_filter_by)))
    with caplog.at_level(logging.ERROR), publish_env.app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, evaluation_id)
        assert svc.get_low_score_publish_block_reason(evaluation, ensure=False) == _GENERIC_LOCK_REASON
        assert visibility_guard.is_employee_visible(evaluation) is False
    assert _logged_errors(caplog, _SERVICE_MODULE) == ["OperationalError", "OperationalError"]
