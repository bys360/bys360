"""Below-threshold publish gate reads the canonical scorecard-safe recommendation set.

Approved rule: when a score below the configured threshold requires development guidance,
publication is allowed only if the same employee + period has at least one canonical Phase-10
recommendation that satisfies the scorecard-safe/published predicate. The legacy P4 columns
(is_required, evaluation_id, employee_user_id, P4 recommendation types) are not part of the
canonical schema and must not decide the gate.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "development_publish_gate_contract" / "dbs"
GATE_SETTING = "performance_development_recommendation_required_below_70"
BLOCK_MESSAGE = "70 altı sonuçlarda gelişim önerisi kaydı oluşturulmadan personele yayın açılamaz."


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-development-publish-gate",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "development-publish-gate-first-login",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "DATABASE_URL": uri,
        "MAIL_SUPPRESS_SEND": "true",
        "SCHEDULER_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=uri)
    return app


@pytest.fixture
def gate(monkeypatch, install_development_recommendations_schema):
    from app.extensions import db
    from app.models import ModuleSetting, PerformanceEvaluation, PerformancePeriod, User

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    ids: dict[str, int] = {}
    with app.app_context():
        db.create_all()
        install_development_recommendations_schema(db.engine)
        for key in ("employee", "other"):
            user = User(
                sicil_no=f"DPG{key.upper()}",
                email=f"dpg{key}@example.gov.tr",
                ad="Kapı",
                soyad=key.title(),
                role="personel",
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            user.set_password("DevelopmentPublishGate1!")
            db.session.add(user)
            db.session.flush()
            ids[key] = int(user.id)
        periods = []
        for title, start in (("Kapı Dönemi", date(2026, 1, 1)), ("Diğer Dönem", date(2025, 10, 1))):
            period = PerformancePeriod(title=title, period_type="quarterly", start_date=start, end_date=start.replace(month=start.month + 2, day=28), is_active=False)
            db.session.add(period)
            db.session.flush()
            periods.append(int(period.id))
        ids["period"], ids["other_period"] = periods
        for name, score in (("low", 60), ("high", 80)):
            evaluation = PerformanceEvaluation(period_id=ids["period"], employee_id=ids["employee"] if name == "low" else ids["other"], final_total_100=score)
            db.session.add(evaluation)
            db.session.flush()
            ids[name] = int(evaluation.id)
        db.session.add(
            ModuleSetting(
                module_key="performance",
                setting_key=GATE_SETTING,
                label="70 altı gelişim önerisi zorunlu",
                value_text="true",
                value_type="boolean",
            )
        )
        db.session.commit()
        db.session.remove()
    return SimpleNamespace(app=app, ids=ids)


def _add_recommendation(gate, *, employee, period, **overrides):
    from app.extensions import db

    row = {
        "employee_id": gate.ids[employee],
        "period_id": gate.ids[period] if period else None,
        "recommendation_type": "development",
        "recommendation_text": "Kanonik gelişim önerisi",
        "show_on_scorecard": True,
        "is_published": True,
        "publish_lock": False,
        "supervisor_approval_required": True,
        "supervisor_approved": True,
        "hr_publish_required": True,
        "hr_publish_approved": True,
        "scorecard_visibility_mode": "after_publish",
        "publication_status": "published",
    }
    row.update(overrides)
    with gate.app.app_context():
        db.session.execute(
            text(
                f"INSERT INTO performance_development_recommendations ({', '.join(row)}) "
                f"VALUES ({', '.join(':' + name for name in row)})"
            ),
            row,
        )
        db.session.commit()
        db.session.remove()


def _block_reason(gate, evaluation_key: str) -> str:
    from app.extensions import db
    from app.models import PerformanceEvaluation
    from app.services.performance.meeting_p4_development_guidance import (
        get_development_recommendation_publish_block_reason,
    )

    with gate.app.app_context():
        evaluation = db.session.get(PerformanceEvaluation, gate.ids[evaluation_key])
        reason = get_development_recommendation_publish_block_reason(evaluation)
        db.session.remove()
    return reason


def test_below_threshold_without_any_recommendation_is_blocked(gate):
    assert _block_reason(gate, "low") == BLOCK_MESSAGE


def test_below_threshold_with_only_a_draft_recommendation_is_blocked(gate):
    _add_recommendation(gate, employee="employee", period="period", show_on_scorecard=False, is_published=False, publication_status="draft")
    assert _block_reason(gate, "low") == BLOCK_MESSAGE


@pytest.mark.parametrize(
    "overrides",
    [
        {"publish_lock": True},
        {"supervisor_approved": False},
        {"hr_publish_approved": False},
        {"scorecard_visibility_mode": "internal_only"},
    ],
    ids=["locked", "supervisor-pending", "hr-pending", "internal-mode"],
)
def test_below_threshold_with_a_non_scorecard_safe_recommendation_is_blocked(gate, overrides):
    _add_recommendation(gate, employee="employee", period="period", **overrides)
    assert _block_reason(gate, "low") == BLOCK_MESSAGE


def test_below_threshold_with_one_scorecard_safe_recommendation_is_allowed(gate):
    _add_recommendation(gate, employee="employee", period="period")
    assert _block_reason(gate, "low") == ""


def test_recommendation_of_another_employee_does_not_satisfy_the_gate(gate):
    _add_recommendation(gate, employee="other", period="period")
    assert _block_reason(gate, "low") == BLOCK_MESSAGE


def test_recommendation_of_another_period_does_not_satisfy_the_gate(gate):
    _add_recommendation(gate, employee="employee", period="other_period")
    assert _block_reason(gate, "low") == BLOCK_MESSAGE


def test_period_agnostic_recommendation_counts_exactly_as_the_scorecard_shows_it(gate):
    """The canonical predicate shows period_id IS NULL rows on every period's scorecard."""
    _add_recommendation(gate, employee="employee", period=None)
    assert _block_reason(gate, "low") == ""


def test_above_threshold_is_never_blocked(gate):
    assert _block_reason(gate, "high") == ""


def test_gate_is_inactive_when_the_setting_is_off(gate):
    from app.extensions import db

    with gate.app.app_context():
        db.session.execute(text("UPDATE module_settings SET value_text='false' WHERE setting_key=:key"), {"key": GATE_SETTING})
        db.session.commit()
        db.session.remove()
    assert _block_reason(gate, "low") == ""


def test_gate_and_scorecard_share_one_canonical_reader(gate, monkeypatch):
    import app.performance.phase10_development_guidance_ui as phase10

    calls = []
    real = phase10.fetch_scorecard_safe_recommendations

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(phase10, "fetch_scorecard_safe_recommendations", _spy)
    _add_recommendation(gate, employee="employee", period="period")
    assert _block_reason(gate, "low") == ""
    assert calls, "the publish gate must use the canonical scorecard-safe reader"
