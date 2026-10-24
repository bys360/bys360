"""BYS360_PHASE5_COVERAGE_WAVE5_AGENT1_PERSONNEL_SUPPORT_PUBLISH_APPROVAL_CONTRACT

Behavioral contract for
app/services/performance/personnel_support_publish_approval_service.py --
the Phase 1.4B "Personel ve Destek Hizmetleri Grup Başkanı" pre-publish
approval gate that sits between a completed evaluation (and, when it applies,
a finished low-score Başkan process) and the final Admin/İK publish-to-
employee step.

Covers every public function in the module's real logic: is_admin_user,
is_hr_publish_user, is_personnel_support_group_chair_user,
can_view_personnel_support_publish_approvals,
can_decide_personnel_support_publish_approval, status_key, status_label,
score_level_label, should_require_personnel_support_publish_approval,
ensure_personnel_support_publish_approval_for_evaluation,
get_personnel_support_publish_block_reason,
build_personnel_support_publish_approval_workspace,
decide_personnel_support_publish_approval. The pure predicates are exercised
against SimpleNamespace fakes; the SQL-backed functions are exercised
against a real Flask app context + real file-backed SQLite database.

Table strategy: no ORM model backs
`performance_personnel_support_publish_approvals` (confirmed via grep across
app/models) -- the table is Alembic-owned (migration
7c4e1a9b2d60_adopt_personnel_support_publish_approval_schema.py) and the
service's own module docstring/tests forbid runtime schema mutation SQL
inside the service itself. So `db.create_all()` never creates it; this file
creates it directly with raw DDL matching
`_PHASE14B_REQUIRED_COLUMNS`/`_PHASE14B_REQUIRED_INDEXES` (mirroring the
migration's own column list) via `_create_approval_schema()`, called only in
tests that need the table -- tests that want to prove the table-missing
path simply never call it.

DB fixture: proven pattern (Config class-attribute patch BEFORE
create_app(), StaticPool, pysqlite dual-connection fix) copied from
tests/behavior/test_admin_ops_user_actions_destructive_operations_contract.py
lines 110-183, with its own dedicated tmp DB directory so this file shares
no state with any other Wave 5 agent running concurrently.

DEFECT A BOUNDARY: `_low_score_predecessor_is_ready` only calls
`app.services.performance.low_score_process_service.get_low_score_publish_block_reason`
when `final_total_100 < 70.0`. Every test in this file that reaches that
branch monkeypatches that function AT ITS SOURCE MODULE (the consumer does a
local `from ... import ...` inside the function body on every call, so there
is no consumer-side module attribute to patch) with a deterministic fake --
never exercising the real dependency's resolution logic here (see
tests/services/test_low_score_process_service_workflow_contract.py for
direct coverage of that function itself). The score>=70.0 short-circuit
tests use a raising stub to prove the dependency is never even invoked.

BYS360 DEFECT AR update: `get_low_score_publish_block_reason`'s `ensure=False`
path previously never looked up an already-persisted
`PerformanceLowScoreProcess` row, so a finalized low-score evaluation stayed
permanently reported as publish-locked even after full President approval
and administrative-process completion. That has since been FIXED (the
`ensure=False` branch now does a read-only lookup of any existing process
before falling through to the "blocked" default) -- this file's tests were
never affected either way, since they always monkeypatch the dependency.

BYS360 DEFECT AQ update: two separate, non-Defect-A production defects that
were found empirically while implementing the group-chair "scattered
substring fallback" contract (a live authorization-overgrant substring bug,
and the `_normalize` 'İ'.lower() two-codepoint Unicode bug) have both since
been FIXED -- see the docstrings around
`test_is_personnel_support_group_chair_user_false_for_scattered_fields_no_longer_matches`
and `test_is_personnel_support_group_chair_user_true_for_correctly_capitalized_single_field_title`
below for the corrected, locked-in behavior.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_wave5_agent1_pspaw")

_APPROVAL_TABLE = "performance_personnel_support_publish_approvals"

_APPROVAL_TABLE_DDL = f"""
    CREATE TABLE {_APPROVAL_TABLE} (
        id INTEGER PRIMARY KEY,
        evaluation_id INTEGER NOT NULL,
        period_id INTEGER,
        employee_id INTEGER,
        final_score NUMERIC(6, 2),
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        requested_by_user_id INTEGER,
        decided_at DATETIME,
        decided_by_user_id INTEGER,
        decision_note TEXT,
        return_note TEXT,
        rule_version VARCHAR(120) NOT NULL DEFAULT 'phase1.4b-personnel-support-publish-approval-v1',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""

_user_counter = 0


# ---------------------------------------------------------------------------
# App / DB fixture -- proven pattern, see module docstring.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-pspaw-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "pspaw-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"agent1_pspaw_{uuid.uuid4().hex}.sqlite3")
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
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )

    from app.extensions import db

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _import_service():
    from app.services.performance import personnel_support_publish_approval_service as svc

    return svc


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _seed_user(app, *, role="personel", sicil_no=None, email=None, unvan=None):
    from app.extensions import db
    from app.models import User

    suffix = _next_suffix()
    sicil = sicil_no or f"PSPA{suffix:06d}"
    mail = email or f"pspaw-{suffix}@bys360.test"
    with app.app_context():
        user = User(
            sicil_no=sicil,
            email=mail,
            ad="Test",
            soyad=f"User{suffix}",
            role=role,
            unvan=unvan,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("PersonnelSupportPublishTest1!")
        db.session.add(user)
        db.session.commit()
        return user.id


def _expected_full_name(app, user_id):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user is not None
        return f"{user.ad} {user.soyad}".strip()


def _seed_period(app, *, title="2026 Ops Q1"):
    from app.extensions import db
    from app.models import PerformancePeriod

    with app.app_context():
        period = PerformancePeriod(
            title=title,
            period_type="quarterly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def _create_approval_schema(app):
    from app.extensions import db

    with app.app_context():
        db.session.execute(text(_APPROVAL_TABLE_DDL))
        db.session.execute(
            text(
                f"CREATE INDEX ix_phase14b_publish_approval_status "
                f"ON {_APPROVAL_TABLE}(status)"
            )
        )
        db.session.execute(
            text(
                f"CREATE INDEX ix_phase14b_publish_approval_period_status "
                f"ON {_APPROVAL_TABLE}(period_id, status)"
            )
        )
        db.session.execute(
            text(
                f"CREATE INDEX ix_phase14b_publish_approval_employee "
                f"ON {_APPROVAL_TABLE}(employee_id)"
            )
        )
        db.session.commit()


def _insert_approval_row(
    app,
    *,
    evaluation_id,
    period_id=None,
    employee_id=None,
    final_score=None,
    status="pending",
    requested_by_user_id=None,
    decided_at=None,
    decided_by_user_id=None,
    decision_note=None,
    return_note=None,
    rule_version=None,
    updated_at=None,
):
    from app.extensions import db

    svc = _import_service()
    with app.app_context():
        params: dict[str, Any] = {
            "evaluation_id": evaluation_id,
            "period_id": period_id,
            "employee_id": employee_id,
            "final_score": final_score,
            "status": status,
            "requested_by_user_id": requested_by_user_id,
            "decided_at": decided_at,
            "decided_by_user_id": decided_by_user_id,
            "decision_note": decision_note,
            "return_note": return_note,
            "rule_version": rule_version or svc.PHASE1_4B_RULE_VERSION,
        }
        if updated_at is not None:
            params["updated_at"] = updated_at
        columns = ", ".join(params.keys())
        placeholders = ", ".join(f":{key}" for key in params)
        db.session.execute(
            text(f"INSERT INTO {_APPROVAL_TABLE} ({columns}) VALUES ({placeholders})"),
            params,
        )
        db.session.commit()
        row = (
            db.session.execute(
                text(
                    f"SELECT id FROM {_APPROVAL_TABLE} "
                    "WHERE evaluation_id = :evaluation_id ORDER BY id DESC LIMIT 1"
                ),
                {"evaluation_id": evaluation_id},
            )
            .mappings()
            .first()
        )
        assert row is not None
        return row["id"]


def _read_approval_row(app, approval_id):
    from app.extensions import db

    with app.app_context():
        row = (
            db.session.execute(
                text(f"SELECT * FROM {_APPROVAL_TABLE} WHERE id = :id"),
                {"id": approval_id},
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None


def _read_approval_row_by_evaluation(app, evaluation_id):
    from app.extensions import db

    with app.app_context():
        row = (
            db.session.execute(
                text(
                    f"SELECT * FROM {_APPROVAL_TABLE} "
                    "WHERE evaluation_id = :evaluation_id LIMIT 1"
                ),
                {"evaluation_id": evaluation_id},
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None


def _count_approval_rows(app):
    from app.extensions import db

    with app.app_context():
        return db.session.execute(text(f"SELECT COUNT(*) FROM {_APPROVAL_TABLE}")).scalar()


def _make_evaluation(
    *,
    id=1,
    status="tamamlandi",
    workflow_status=None,
    level_1_completed=False,
    is_published_to_employee=False,
    published_to_employee_at=None,
    final_total_100=50.0,
    period_id=10,
    employee_id=20,
):
    return SimpleNamespace(
        id=id,
        status=status,
        workflow_status=workflow_status,
        level_1_completed=level_1_completed,
        is_published_to_employee=is_published_to_employee,
        published_to_employee_at=published_to_employee_at,
        final_total_100=final_total_100,
        period_id=period_id,
        employee_id=employee_id,
    )


def _patch_low_score_reason(monkeypatch, *, block_reason="", raise_exc=None):
    def _fake(evaluation, *, ensure=False):  # noqa: ARG001
        if raise_exc is not None:
            raise raise_exc
        return block_reason

    monkeypatch.setattr(
        "app.services.performance.low_score_process_service.get_low_score_publish_block_reason",
        _fake,
    )


def _forbid_low_score_call(monkeypatch):
    def _fail(evaluation, *, ensure=False):  # noqa: ARG001
        raise AssertionError(
            "get_low_score_publish_block_reason must not be called for this scenario"
        )

    monkeypatch.setattr(
        "app.services.performance.low_score_process_service.get_low_score_publish_block_reason",
        _fail,
    )


# ---------------------------------------------------------------------------
# is_admin_user / is_hr_publish_user
# ---------------------------------------------------------------------------


def test_is_admin_user_true_via_is_admin_flag(app):
    svc = _import_service()
    assert svc.is_admin_user(SimpleNamespace(is_admin=True)) is True


def test_is_admin_user_true_via_role_admin(app):
    svc = _import_service()
    assert svc.is_admin_user(SimpleNamespace(role="admin")) is True


def test_is_admin_user_false_for_plain_personnel(app):
    svc = _import_service()
    assert svc.is_admin_user(SimpleNamespace(role="personel")) is False


def test_is_hr_publish_user_true_via_admin_or_branch(app):
    svc = _import_service()
    assert svc.is_hr_publish_user(SimpleNamespace(is_admin=True)) is True


def test_is_hr_publish_user_true_via_direct_role_ik(app):
    svc = _import_service()
    assert svc.is_hr_publish_user(SimpleNamespace(role="ik")) is True


def test_is_hr_publish_user_false_for_plain_personnel(app):
    svc = _import_service()
    assert svc.is_hr_publish_user(SimpleNamespace(role="personel")) is False


# ---------------------------------------------------------------------------
# is_personnel_support_group_chair_user
# ---------------------------------------------------------------------------


def test_is_personnel_support_group_chair_user_true_via_explicit_role_string(app):
    svc = _import_service()
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")
    assert svc.is_personnel_support_group_chair_user(chair) is True


# BYS360 DEFECT AQ: both production defects this test file's own docstring
# and the test below used to document have been FIXED:
#
# 1. The substring-composite fallback (required tokens "personel",
#    "idari"/"destek", "grup", "baskan" scattered across DIFFERENT fields,
#    combined-then-substring-matched) has been REMOVED entirely --
#    is_personnel_support_group_chair_user now only ever grants via the
#    `explicit` exact-match set. A real exploit example: a Grup Başkan
#    YARDIMCISI (Deputy Group Chair, role="personel", unvan="destek
#    hizmetleri", title="grup başkan yardımcısı") satisfied all four
#    scattered substrings ("başkan" appears inside "başkan yardımcısı")
#    and was incorrectly granted publish-approval decision authority.
#
# 2. `_normalize`'s 'İ'.lower() two-codepoint bug (documented at length
#    below in test_is_personnel_support_group_chair_user_true_for_correctly_
#    capitalized_single_field_title) is also fixed -- 'İ' is now folded to
#    'i' BEFORE .lower() runs, so it no longer needs an ASCII-only
#    workaround to exercise the explicit exact-match set correctly.
def test_is_personnel_support_group_chair_user_false_for_scattered_fields_no_longer_matches():
    svc = _import_service()
    chair = SimpleNamespace(role="personel", unvan="idari isler", title="grup baskani")
    assert svc.is_personnel_support_group_chair_user(chair) is False


def test_is_personnel_support_group_chair_user_denies_deputy_lookalike():
    # BYS360 DEFECT AQ adversarial case: the confirmed live exploit -- a
    # deputy/assistant group chair is NOT the group chair.
    svc = _import_service()
    deputy = SimpleNamespace(role="personel", unvan="destek hizmetleri", title="grup başkan yardımcısı")
    assert svc.is_personnel_support_group_chair_user(deputy) is False


def test_is_personnel_support_group_chair_user_true_for_correctly_capitalized_single_field_title():
    # BYS360 DEFECT AQ: this closes the NEW_PRODUCTION_DEFECT this file
    # itself previously documented -- with the Unicode ordering fix, the
    # orthographically-correct Turkish capitalization (capital dotted İ,
    # U+0130), entered as one real, single unvan field value (as an HR
    # system realistically would store a full official title), now
    # correctly normalizes to and exactly matches an `explicit` set member.
    svc = _import_service()
    chair = SimpleNamespace(role="personel", unvan="Personel ve İdari İşler Grup Başkanı", title=None)
    assert svc.is_personnel_support_group_chair_user(chair) is True


def test_is_personnel_support_group_chair_user_false_for_plain_personnel_role(app):
    svc = _import_service()
    assert svc.is_personnel_support_group_chair_user(SimpleNamespace(role="personel")) is False


# ---------------------------------------------------------------------------
# can_view_personnel_support_publish_approvals / can_decide_...
# ---------------------------------------------------------------------------


def test_can_view_true_for_admin_hr_and_chair_false_for_plain_personnel(app):
    svc = _import_service()
    admin = SimpleNamespace(is_admin=True)
    hr = SimpleNamespace(role="ik")
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")
    plain = SimpleNamespace(role="personel")

    assert svc.can_view_personnel_support_publish_approvals(admin) is True
    assert svc.can_view_personnel_support_publish_approvals(hr) is True
    assert svc.can_view_personnel_support_publish_approvals(chair) is True
    assert svc.can_view_personnel_support_publish_approvals(plain) is False


def test_can_decide_rejects_admin_who_can_view_but_cannot_decide(app):
    """The specific, easy-to-miss authorization gap: admin can VIEW (via
    can_view_personnel_support_publish_approvals) but decision authority is
    chair-only, by explicit design comment in the source."""
    svc = _import_service()
    admin = SimpleNamespace(is_admin=True)

    assert svc.can_view_personnel_support_publish_approvals(admin) is True
    assert svc.can_decide_personnel_support_publish_approval(admin) is False


def test_can_decide_true_only_for_chair(app):
    svc = _import_service()
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")
    plain = SimpleNamespace(role="personel")

    assert svc.can_decide_personnel_support_publish_approval(chair) is True
    assert svc.can_decide_personnel_support_publish_approval(plain) is False


def test_can_view_and_decide_both_false_for_plain_personel_role(app):
    svc = _import_service()
    plain = SimpleNamespace(role="personel")

    assert svc.can_view_personnel_support_publish_approvals(plain) is False
    assert svc.can_decide_personnel_support_publish_approval(plain) is False


# ---------------------------------------------------------------------------
# decide_personnel_support_publish_approval -- authorization, DB-backed
# ---------------------------------------------------------------------------


def test_decide_admin_actor_rejected_with_zero_mutation(app):
    svc = _import_service()
    _create_approval_schema(app)
    admin_id = _seed_user(app, role="admin", sicil_no="pspaw_decide_admin")
    approval_id = _insert_approval_row(app, evaluation_id=9001, status="pending")
    admin_actor = SimpleNamespace(id=admin_id, is_admin=True)

    result = svc.decide_personnel_support_publish_approval(approval_id, admin_actor, "approved")

    assert result.ok is False
    assert result.message == (
        "Bu onay işlemi yalnızca Personel ve Destek Hizmetleri Grup Başkanı "
        "tarafından yapılabilir."
    )
    assert result.approval_id == approval_id
    row = _read_approval_row(app, approval_id)
    assert row["status"] == "pending"
    assert row["decided_at"] is None
    assert row["decided_by_user_id"] is None


def test_decide_plain_personnel_actor_rejected_with_zero_mutation(app):
    svc = _import_service()
    _create_approval_schema(app)
    approval_id = _insert_approval_row(app, evaluation_id=9002, status="pending")
    plain_actor = SimpleNamespace(id=1, role="personel")

    result = svc.decide_personnel_support_publish_approval(approval_id, plain_actor, "approved")

    assert result.ok is False
    assert result.message == (
        "Bu onay işlemi yalnızca Personel ve Destek Hizmetleri Grup Başkanı "
        "tarafından yapılabilir."
    )
    row = _read_approval_row(app, approval_id)
    assert row["status"] == "pending"
    assert row["decided_at"] is None
    assert row["decided_by_user_id"] is None


# ---------------------------------------------------------------------------
# status_key / status_label / score_level_label boundaries
# ---------------------------------------------------------------------------


def test_status_key_and_label_boundaries(app):
    svc = _import_service()

    assert svc.status_key("approved") == "approved"
    assert svc.status_key("onaylandı") == "approved"
    assert svc.status_key("returned") == "returned"
    assert svc.status_key("iade") == "returned"
    assert svc.status_key(None) == "pending"
    assert svc.status_key("some_unrecognized_value") == "pending"

    assert svc.status_label("approved") == svc.STATUS_LABELS["approved"]
    assert svc.status_label("returned") == svc.STATUS_LABELS["returned"]
    assert svc.status_label(None) == svc.STATUS_LABELS["pending"]
    assert svc.status_label("garbage") == svc.STATUS_LABELS["pending"]


def test_score_level_label_boundaries(app):
    svc = _import_service()

    assert svc.score_level_label(None) == "Puan bilgisi bekleniyor"
    assert svc.score_level_label(69.99) == "Düşük performans onay süreci tamamlanmış kayıt"
    assert svc.score_level_label(70.0) == "Standart başarı aralığı"
    assert svc.score_level_label(89.99) == "Standart başarı aralığı"
    assert svc.score_level_label(90) == "Yüksek başarı düzeyi"


# ---------------------------------------------------------------------------
# should_require_personnel_support_publish_approval
# ---------------------------------------------------------------------------


def test_should_require_false_when_evaluation_not_completed(app):
    svc = _import_service()
    evaluation = _make_evaluation(
        status="taslak", workflow_status="beklemede", level_1_completed=False, final_total_100=50.0
    )
    assert svc.should_require_personnel_support_publish_approval(evaluation) is False


def test_should_require_false_when_already_published_to_employee(app):
    svc = _import_service()
    evaluation = _make_evaluation(is_published_to_employee=True, final_total_100=50.0)
    assert svc.should_require_personnel_support_publish_approval(evaluation) is False


def test_should_require_false_when_predecessor_blocked_kwarg_is_unconditional(app, monkeypatch):
    svc = _import_service()
    _forbid_low_score_call(monkeypatch)
    evaluation = _make_evaluation(final_total_100=50.0)

    result = svc.should_require_personnel_support_publish_approval(
        evaluation, predecessor_blocked=True
    )

    assert result is False


def test_should_require_true_when_score_at_threshold_short_circuits_without_dependency(
    app, monkeypatch
):
    svc = _import_service()
    _forbid_low_score_call(monkeypatch)
    evaluation = _make_evaluation(final_total_100=70.0)

    assert svc.should_require_personnel_support_publish_approval(evaluation) is True


def test_should_require_true_when_score_below_threshold_and_predecessor_ready(app, monkeypatch):
    svc = _import_service()
    _patch_low_score_reason(monkeypatch, block_reason="")
    evaluation = _make_evaluation(final_total_100=45.0)

    assert svc.should_require_personnel_support_publish_approval(evaluation) is True


def test_should_require_false_when_score_below_threshold_and_predecessor_blocked(app, monkeypatch):
    svc = _import_service()
    _patch_low_score_reason(monkeypatch, block_reason="Başkan onayı tamamlanmadı.")
    evaluation = _make_evaluation(final_total_100=45.0)

    assert svc.should_require_personnel_support_publish_approval(evaluation) is False


def test_should_require_false_when_low_score_dependency_raises_defensive_fail_closed(
    app, monkeypatch
):
    """Tests THIS file's own except/return-False defensive wrapper around
    the Defect-A call site -- Defect A's real (buggy) ensure=False
    resolution is never invoked here; the mock raises instead."""
    svc = _import_service()
    _patch_low_score_reason(monkeypatch, raise_exc=RuntimeError("boom"))
    evaluation = _make_evaluation(final_total_100=45.0)

    assert svc.should_require_personnel_support_publish_approval(evaluation) is False


# ---------------------------------------------------------------------------
# ensure_personnel_support_publish_approval_for_evaluation
# ---------------------------------------------------------------------------


def test_ensure_creates_new_pending_row_when_absent(app, monkeypatch):
    svc = _import_service()
    _create_approval_schema(app)
    _patch_low_score_reason(monkeypatch, block_reason="")
    actor_id = _seed_user(app, role="ik", sicil_no="pspaw_ensure_actor")
    evaluation = _make_evaluation(id=7001, final_total_100=40.0, period_id=11, employee_id=22)

    with app.app_context():
        result = svc.ensure_personnel_support_publish_approval_for_evaluation(
            evaluation, actor=SimpleNamespace(id=actor_id)
        )

    assert result is not None
    assert result["evaluation_id"] == 7001
    assert result["status"] == "pending"
    assert result["period_id"] == 11
    assert result["employee_id"] == 22
    assert float(result["final_score"]) == 40.0
    assert result["requested_by_user_id"] == actor_id
    assert result["rule_version"] == svc.PHASE1_4B_RULE_VERSION


def test_ensure_update_preserves_nonnull_rule_version_but_refreshes_other_fields(
    app, monkeypatch
):
    svc = _import_service()
    _create_approval_schema(app)
    _patch_low_score_reason(monkeypatch, block_reason="")
    approval_id = _insert_approval_row(
        app,
        evaluation_id=7002,
        period_id=1,
        employee_id=2,
        final_score=10.0,
        status="pending",
        rule_version="legacy-rule-v0",
    )
    evaluation = _make_evaluation(id=7002, final_total_100=55.5, period_id=99, employee_id=88)

    with app.app_context():
        result = svc.ensure_personnel_support_publish_approval_for_evaluation(evaluation, actor=None)

    assert result["id"] == approval_id
    assert result["period_id"] == 99
    assert result["employee_id"] == 88
    assert float(result["final_score"]) == 55.5
    # Non-null rule_version is preserved (COALESCE only backfills NULL).
    assert result["rule_version"] == "legacy-rule-v0"
    # ensure_'s UPDATE never touches status.
    assert result["status"] == "pending"


def test_ensure_returns_none_when_table_missing(app, monkeypatch):
    svc = _import_service()
    _patch_low_score_reason(monkeypatch, block_reason="")
    evaluation = _make_evaluation(id=7003, final_total_100=40.0)

    assert svc.ensure_personnel_support_publish_approval_for_evaluation(evaluation) is None


# ---------------------------------------------------------------------------
# get_personnel_support_publish_block_reason
# ---------------------------------------------------------------------------


def test_get_block_reason_predecessor_blocked_short_circuits_without_table_check(app):
    svc = _import_service()
    # No schema created at all -- proves this path never even reaches
    # table_exists().
    evaluation = _make_evaluation(id=8001, final_total_100=40.0)
    assert svc.get_personnel_support_publish_block_reason(evaluation, predecessor_blocked=True) == ""


def test_get_block_reason_empty_when_should_not_require(app):
    svc = _import_service()
    evaluation = _make_evaluation(id=8002, status="taslak", final_total_100=40.0)
    assert svc.get_personnel_support_publish_block_reason(evaluation) == ""


def test_get_block_reason_table_missing_returns_exact_message(app, monkeypatch):
    svc = _import_service()
    _patch_low_score_reason(monkeypatch, block_reason="")
    evaluation = _make_evaluation(id=8003, final_total_100=40.0)

    reason = svc.get_personnel_support_publish_block_reason(evaluation)

    assert reason == (
        "Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı hazır olmadan "
        "karne personele açılamaz."
    )


def test_get_block_reason_ensure_false_no_row_returns_exact_message(app, monkeypatch):
    svc = _import_service()
    _create_approval_schema(app)
    _patch_low_score_reason(monkeypatch, block_reason="")
    evaluation = _make_evaluation(id=8004, final_total_100=40.0)

    with app.app_context():
        reason = svc.get_personnel_support_publish_block_reason(evaluation, ensure=False)

    assert reason == (
        "Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı oluşturulmadan "
        "karne personele açılamaz."
    )
    assert _read_approval_row_by_evaluation(app, 8004) is None


def test_get_block_reason_ensure_true_creates_row_and_returns_pending_message(app, monkeypatch):
    svc = _import_service()
    _create_approval_schema(app)
    _patch_low_score_reason(monkeypatch, block_reason="")
    evaluation = _make_evaluation(id=8005, final_total_100=40.0)

    # get_personnel_support_publish_block_reason -> ensure_...() only flushes,
    # never commits (the real caller, a Flask route, commits after the
    # request) -- without an explicit commit here, the flushed-but-uncommitted
    # INSERT is rolled back when this app_context tears down, so a
    # durability re-read via a fresh app_context would see nothing.
    from app.extensions import db

    with app.app_context():
        reason = svc.get_personnel_support_publish_block_reason(evaluation, ensure=True)
        db.session.commit()

    assert reason == (
        "Personel ve Destek Hizmetleri Grup Başkanı ön onayı tamamlanmadan "
        "karne personele açılamaz."
    )
    created = _read_approval_row_by_evaluation(app, 8005)
    assert created is not None
    assert created["status"] == "pending"


def test_get_block_reason_approved_row_returns_empty(app, monkeypatch):
    svc = _import_service()
    _create_approval_schema(app)
    _patch_low_score_reason(monkeypatch, block_reason="")
    _insert_approval_row(app, evaluation_id=8006, status="approved")
    evaluation = _make_evaluation(id=8006, final_total_100=40.0)

    with app.app_context():
        assert svc.get_personnel_support_publish_block_reason(evaluation, ensure=False) == ""


def test_get_block_reason_returned_row_includes_note_suffix(app, monkeypatch):
    svc = _import_service()
    _create_approval_schema(app)
    _patch_low_score_reason(monkeypatch, block_reason="")
    _insert_approval_row(app, evaluation_id=8007, status="returned", return_note="Eksik belge var.")
    evaluation = _make_evaluation(id=8007, final_total_100=40.0)

    with app.app_context():
        reason = svc.get_personnel_support_publish_block_reason(evaluation, ensure=False)

    assert reason == (
        "Personel ve Destek Hizmetleri Grup Başkanı karneyi iade ettiği için "
        "Admin/İK yayını yapılamaz. İade notu: Eksik belge var."
    )


# ---------------------------------------------------------------------------
# build_personnel_support_publish_approval_workspace
# ---------------------------------------------------------------------------


def test_build_workspace_schema_missing_returns_empty_shell(app):
    svc = _import_service()
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")

    workspace = svc.build_personnel_support_publish_approval_workspace(chair)

    assert workspace["schema_missing"] is True
    assert workspace["rows"] == []
    assert workspace["counts"] == {"pending": 0, "approved": 0, "returned": 0, "all": 0}
    assert workspace["status_filter"] == "pending"
    assert workspace["can_decide"] is True
    assert workspace["rule_version"] == svc.PHASE1_4B_RULE_VERSION


def _seed_workspace_fixture(app):
    _create_approval_schema(app)
    period_id = _seed_period(app)
    employee_id = _seed_user(app, role="personel", sicil_no="pspaw_ws_employee")
    chair_id = _seed_user(
        app, role="personel_ve_destek_hizmetleri_grup_baskani", sicil_no="pspaw_ws_chair"
    )
    pending1 = _insert_approval_row(
        app, evaluation_id=9101, period_id=period_id, employee_id=employee_id,
        final_score=45.0, status="pending",
    )
    pending2 = _insert_approval_row(
        app, evaluation_id=9102, period_id=period_id, employee_id=employee_id,
        final_score=60.0, status="pending",
    )
    approved = _insert_approval_row(
        app, evaluation_id=9103, period_id=period_id, employee_id=employee_id,
        final_score=95.0, status="approved", decided_at="2026-01-15 10:00:00",
        decided_by_user_id=chair_id, decision_note="Uygun.",
    )
    returned = _insert_approval_row(
        app, evaluation_id=9104, period_id=period_id, employee_id=employee_id,
        final_score=30.0, status="returned", decided_at="2026-01-16 11:00:00",
        decided_by_user_id=chair_id, decision_note="Eksik.", return_note="Eksik belge.",
    )
    return {
        "period_id": period_id,
        "employee_id": employee_id,
        "chair_id": chair_id,
        "pending1": pending1,
        "pending2": pending2,
        "approved": approved,
        "returned": returned,
    }


def test_build_workspace_default_pending_filter_and_counts(app):
    svc = _import_service()
    ids = _seed_workspace_fixture(app)
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")

    with app.app_context():
        workspace = svc.build_personnel_support_publish_approval_workspace(chair)

    assert workspace["schema_missing"] is False
    assert workspace["status_filter"] == "pending"
    row_ids = {row["id"] for row in workspace["rows"]}
    assert row_ids == {ids["pending1"], ids["pending2"]}
    assert workspace["counts"] == {"pending": 2, "approved": 1, "returned": 1, "all": 4}
    assert workspace["can_decide"] is True


def test_build_workspace_approved_filter(app):
    svc = _import_service()
    ids = _seed_workspace_fixture(app)
    admin = SimpleNamespace(is_admin=True)

    with app.app_context():
        workspace = svc.build_personnel_support_publish_approval_workspace(
            admin, status_filter="approved"
        )

    assert workspace["status_filter"] == "approved"
    row_ids = {row["id"] for row in workspace["rows"]}
    assert row_ids == {ids["approved"]}
    assert workspace["can_decide"] is False  # admin can view, cannot decide


def test_build_workspace_returned_filter(app):
    svc = _import_service()
    ids = _seed_workspace_fixture(app)
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")

    with app.app_context():
        workspace = svc.build_personnel_support_publish_approval_workspace(
            chair, status_filter="returned"
        )

    row_ids = {row["id"] for row in workspace["rows"]}
    assert row_ids == {ids["returned"]}
    assert workspace["status_filter"] == "returned"


def test_build_workspace_all_filter_variants(app):
    svc = _import_service()
    ids = _seed_workspace_fixture(app)
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")
    expected_all = {ids["pending1"], ids["pending2"], ids["approved"], ids["returned"]}

    for variant in ("all", "tum", "tumu"):
        with app.app_context():
            workspace = svc.build_personnel_support_publish_approval_workspace(
                chair, status_filter=variant
            )
        row_ids = {row["id"] for row in workspace["rows"]}
        assert row_ids == expected_all
        assert workspace["status_filter"] == "all"


def test_build_workspace_unrecognized_filter_falls_back_to_pending(app):
    svc = _import_service()
    ids = _seed_workspace_fixture(app)
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")

    with app.app_context():
        workspace = svc.build_personnel_support_publish_approval_workspace(
            chair, status_filter="totally-bogus-filter"
        )

    assert workspace["status_filter"] == "pending"
    row_ids = {row["id"] for row in workspace["rows"]}
    assert row_ids == {ids["pending1"], ids["pending2"]}


def test_build_workspace_computed_display_fields(app):
    svc = _import_service()
    ids = _seed_workspace_fixture(app)
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")
    expected_employee_name = _expected_full_name(app, ids["employee_id"])
    expected_chair_name = _expected_full_name(app, ids["chair_id"])

    with app.app_context():
        workspace = svc.build_personnel_support_publish_approval_workspace(chair, status_filter="all")
    rows_by_id = {row["id"]: row for row in workspace["rows"]}

    pending_row = rows_by_id[ids["pending1"]]
    assert pending_row["employee_name"] == expected_employee_name
    assert pending_row["decided_by_name"] == "-"
    assert pending_row["status_label"] == svc.STATUS_LABELS["pending"]
    assert pending_row["score_level_label"] == "Düşük performans onay süreci tamamlanmış kayıt"
    assert pending_row["requested_at_label"] != "-"
    assert pending_row["decided_at_label"] == "-"

    approved_row = rows_by_id[ids["approved"]]
    assert approved_row["decided_by_name"] == expected_chair_name
    assert approved_row["decided_at_label"] != "-"
    assert approved_row["status_label"] == svc.STATUS_LABELS["approved"]
    assert approved_row["score_level_label"] == "Yüksek başarı düzeyi"

    returned_row = rows_by_id[ids["returned"]]
    assert returned_row["status_label"] == svc.STATUS_LABELS["returned"]
    assert returned_row["score_level_label"] == "Düşük performans onay süreci tamamlanmış kayıt"


# ---------------------------------------------------------------------------
# decide_personnel_support_publish_approval -- state machine
# ---------------------------------------------------------------------------


def test_decide_approve_fresh_pending_row_mutates_and_commits(app):
    svc = _import_service()
    _create_approval_schema(app)
    chair_id = _seed_user(
        app, role="personel_ve_destek_hizmetleri_grup_baskani", sicil_no="pspaw_decide_approve"
    )
    approval_id = _insert_approval_row(app, evaluation_id=9201, status="pending")
    chair = SimpleNamespace(id=chair_id, role="personel_ve_destek_hizmetleri_grup_baskani")

    with app.app_context():
        result = svc.decide_personnel_support_publish_approval(
            approval_id, chair, "approved", note="Uygun bulundu."
        )

    assert result.ok is True
    assert result.message == (
        "Personel ve Destek Hizmetleri Grup Başkanı ön onayı verildi. Karne nihai yayına hazır."
    )
    assert result.approval_id == approval_id
    row = _read_approval_row(app, approval_id)
    assert row["status"] == "approved"
    assert row["decided_at"] is not None
    assert row["decided_by_user_id"] == chair_id
    assert row["decision_note"] == "Uygun bulundu."
    assert row["return_note"] is None
    assert row["rule_version"] == svc.PHASE1_4B_RULE_VERSION


def test_decide_return_action_sets_return_note_and_status(app):
    svc = _import_service()
    _create_approval_schema(app)
    chair_id = _seed_user(
        app, role="personel_ve_destek_hizmetleri_grup_baskani", sicil_no="pspaw_decide_return"
    )
    approval_id = _insert_approval_row(app, evaluation_id=9202, status="pending")
    chair = SimpleNamespace(id=chair_id, role="personel_ve_destek_hizmetleri_grup_baskani")

    with app.app_context():
        result = svc.decide_personnel_support_publish_approval(
            approval_id, chair, "returned", note="Eksik belge var."
        )

    assert result.ok is True
    assert result.message == (
        "Karne Personel ve Destek Hizmetleri Grup Başkanı tarafından iade edildi. "
        "Düzeltme tamamlanmadan personele açılamaz."
    )
    row = _read_approval_row(app, approval_id)
    assert row["status"] == "returned"
    assert row["decision_note"] == "Eksik belge var."
    assert row["return_note"] == "Eksik belge var."


def test_decide_invalid_action_string_zero_mutation(app):
    svc = _import_service()
    _create_approval_schema(app)
    chair_id = _seed_user(
        app, role="personel_ve_destek_hizmetleri_grup_baskani", sicil_no="pspaw_decide_invalid"
    )
    approval_id = _insert_approval_row(app, evaluation_id=9203, status="pending")
    chair = SimpleNamespace(id=chair_id, role="personel_ve_destek_hizmetleri_grup_baskani")

    with app.app_context():
        result = svc.decide_personnel_support_publish_approval(approval_id, chair, "banana")

    assert result.ok is False
    assert result.message == "Geçersiz işlem."
    row = _read_approval_row(app, approval_id)
    assert row["status"] == "pending"
    assert row["decided_at"] is None


def test_decide_unknown_approval_id_zero_mutation(app):
    svc = _import_service()
    _create_approval_schema(app)
    chair_id = _seed_user(
        app, role="personel_ve_destek_hizmetleri_grup_baskani", sicil_no="pspaw_decide_unknown"
    )
    chair = SimpleNamespace(id=chair_id, role="personel_ve_destek_hizmetleri_grup_baskani")
    before = _count_approval_rows(app)

    with app.app_context():
        result = svc.decide_personnel_support_publish_approval(999999, chair, "approved")

    assert result.ok is False
    assert result.message == "Ön onay kaydı bulunamadı."
    assert result.approval_id == 999999
    assert _count_approval_rows(app) == before


def test_decide_reapprove_already_approved_row_is_idempotent_zero_mutation(app):
    """The distinct idempotent short-circuit, explicitly established in the
    source: re-approving an already-approved row returns ok=True with the
    "already approved" message and performs ZERO additional UPDATE. Proven
    robustly (not by relying on CURRENT_TIMESTAMP second-resolution
    collisions) by pre-seeding fixed sentinel values -- decided_at,
    decided_by_user_id, decision_note, updated_at, rule_version -- that a
    real re-execution of the UPDATE would necessarily overwrite (decided_at
    to "now" in 2026, decided_by_user_id to the NEW actor, decision_note to
    the new note, rule_version unconditionally to PHASE1_4B_RULE_VERSION),
    then asserting the row is byte-identical to the pre-seeded values after
    the second decide call."""
    svc = _import_service()
    _create_approval_schema(app)
    original_actor_id = _seed_user(
        app, role="personel_ve_destek_hizmetleri_grup_baskani", sicil_no="pspaw_reapprove_orig"
    )
    new_actor_id = _seed_user(
        app, role="personel_ve_destek_hizmetleri_grup_baskani", sicil_no="pspaw_reapprove_new"
    )
    approval_id = _insert_approval_row(
        app,
        evaluation_id=9204,
        status="approved",
        decided_at="2020-01-01 00:00:00",
        decided_by_user_id=original_actor_id,
        decision_note="original note",
        rule_version="legacy-rule-v0",
        updated_at="2020-01-01 00:00:00",
    )
    new_chair = SimpleNamespace(id=new_actor_id, role="personel_ve_destek_hizmetleri_grup_baskani")

    with app.app_context():
        result = svc.decide_personnel_support_publish_approval(
            approval_id, new_chair, "approved", note="attempted new note"
        )

    assert result.ok is True
    assert result.message == "Bu kayıt daha önce onaylanmış."
    assert result.approval_id == approval_id
    row = _read_approval_row(app, approval_id)
    assert row["status"] == "approved"
    assert row["decided_at"] == "2020-01-01 00:00:00"
    assert row["decided_by_user_id"] == original_actor_id
    assert row["decision_note"] == "original note"
    assert row["updated_at"] == "2020-01-01 00:00:00"
    assert row["rule_version"] == "legacy-rule-v0"


def test_decide_table_missing_returns_clean_failure(app):
    svc = _import_service()
    chair = SimpleNamespace(role="personel_ve_destek_hizmetleri_grup_baskani")

    result = svc.decide_personnel_support_publish_approval(1, chair, "approved")

    assert result.ok is False
    assert result.message == (
        "Yayın ön onayı listesi henüz hazır değil. Sistem yöneticinizle iletişime geçiniz."
    )
    assert result.approval_id == 1
