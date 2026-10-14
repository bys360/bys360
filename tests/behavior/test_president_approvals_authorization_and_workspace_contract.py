"""BYS360_PHASE5_COVERAGE_WAVE3_AGENT2_AUTHORIZATION_CONTRACT

Behavioral contract tests for
app/services/performance/process_engine_phase6_president_approvals.py,
focused specifically on the gap left by the existing test suite:

- tests/services/test_president_approval_decision_transaction_safety.py
  proves commit/rollback exception-safety around `decide_president_approval`.
- tests/services/test_performance_exception_narrowing_wave2.py proves the
  same kind of exception-safety around `delete_president_approval_record`.

Both of those files monkeypatch `can_view_president_approvals` /
`can_delete_president_approval_records` to hardcoded True/False -- they never
exercise the *real* role-matching logic in `is_president_user`,
`is_admin_user`, or the fact that "can view" and "can delete" are genuinely
different authorities. This file closes exactly that gap: every
authorization assertion below calls the real functions against real
user-like objects with real role/title fields, never a mock of the
authorization decision itself.

Per source (`is_admin_user`, `is_president_user`,
`can_view_president_approvals`, `can_delete_president_approval_records`),
verified by direct reading:
  - `is_admin_user`: True if `is_admin` / `is_superuser` is truthy, OR the
    normalized value of `role` / `role_name` / `user_type` is one of
    {"admin", "super_admin", "system_admin", "sistem_yoneticisi"}.
  - `is_president_user`: True only if the normalized value of `role` /
    `role_name` / `user_type` / `unvan` / `title` is exactly "baskan" or
    "president" (the function's own comment: institution name or
    "Başkanlığı" text does not grant authority).
  - `can_view_president_approvals` = admin OR president.
  - `can_delete_president_approval_records` = admin ONLY (the function's own
    docstring: a Başkan may view/decide but record cleanup is
    Admin/Sistem Yöneticisi-only).

No Flask app or database is used anywhere in this file. All four target
read/write functions (`build_president_approval_workspace`,
`decide_president_approval`, `delete_president_approval_record`, and their
authorization gates) either short-circuit before touching persistence for an
unauthorized/invalid call, or talk to `db.session` through raw
`sqlalchemy.text(...)` statements executed one at a time -- so the module's
own `db` name is replaced with a tiny fake session object that records what
was sent and returns queued fixture results. This avoids any dependency on
the shared `tests/conftest.py` `app` fixture (a separate, already-flagged
risk) and avoids needing `Config`/`create_app()` at all, since these
functions never touch `current_app`/`db.engine` directly -- only
`db.session`.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.performance import (
    process_engine_phase6_president_approvals as approvals,
)

# ---------------------------------------------------------------------------
# Fake persistence layer: replaces the module's `db` name entirely (a tiny
# stand-in object with just `.session.execute/.commit/.rollback`), so no real
# Flask-SQLAlchemy engine, app context, or `tests/conftest.py` fixture is
# ever involved. `table_exists`/`_table_columns` (schema-introspection
# helpers, not authorization or business logic) are monkeypatched per-test
# where needed to keep the DB-touching functions' control flow deterministic
# without hand-rolling `information_schema` fakes.
# ---------------------------------------------------------------------------


class _FakeExecResult:
    """Stand-in for a SQLAlchemy `CursorResult`. Supports whichever subset
    of `.scalar()` / `.mappings().first()` / `.mappings()` (iterated via
    `list(...)`) / `.rowcount` the production code actually calls."""

    def __init__(
        self,
        *,
        scalar: Any = None,
        first: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
        rowcount: int = 0,
    ) -> None:
        self._scalar = scalar
        self._first = first
        self._rows = rows if rows is not None else []
        self.rowcount = rowcount

    def scalar(self) -> Any:
        return self._scalar

    def mappings(self) -> _FakeExecResult:
        return self

    def first(self) -> dict[str, Any] | None:
        return self._first

    def __iter__(self):
        return iter(self._rows)


class _SequencedExecute:
    """Returns one queued `_FakeExecResult` per call, in order, and records
    the exact SQL text + params sent -- so a test can assert precisely what
    a function tried to persist without any real database underneath."""

    def __init__(self, results: list[_FakeExecResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeExecResult:
        sql = str(stmt)
        self.calls.append((sql, dict(params or {})))
        if not self._results:
            raise AssertionError(
                f"Unexpected extra db.session.execute call (no more queued results):\n{sql}\nparams={params}"
            )
        return self._results.pop(0)


class _FakeSession:
    def __init__(self, execute: Any) -> None:
        self._execute = execute
        self.commit_calls = 0
        self.rollback_calls = 0

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        return self._execute(stmt, params)

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


class _FakeDb:
    def __init__(self, execute: Any) -> None:
        self.session = _FakeSession(execute)


def _install_fake_db(monkeypatch: pytest.MonkeyPatch, execute: Any) -> _FakeDb:
    fake_db = _FakeDb(execute)
    monkeypatch.setattr(approvals, "db", fake_db)
    return fake_db


def _forbid_db_execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
    raise AssertionError(f"db.session.execute must not be called here; got:\n{stmt}\nparams={params}")


def _forbid_table_exists(name: str) -> bool:
    raise AssertionError(f"table_exists must not be called here; got table {name!r}")


# ---------------------------------------------------------------------------
# is_admin_user / is_president_user: real role/title classification, no app,
# no db, no mocking of the functions under test.
# ---------------------------------------------------------------------------


def test_is_admin_user_recognizes_is_admin_flag() -> None:
    user = SimpleNamespace(is_admin=True, is_superuser=False)
    assert approvals.is_admin_user(user) is True


def test_is_admin_user_recognizes_is_superuser_flag() -> None:
    user = SimpleNamespace(is_admin=False, is_superuser=True)
    assert approvals.is_admin_user(user) is True


def test_is_admin_user_recognizes_admin_role_value() -> None:
    user = SimpleNamespace(is_admin=False, is_superuser=False, role="admin", role_name=None, user_type=None)
    assert approvals.is_admin_user(user) is True


def test_is_admin_user_recognizes_turkish_system_admin_role_with_spacing_and_diacritics() -> None:
    # normalize_role lowercases, maps Turkish diacritics (ö -> o) and turns
    # spaces into underscores, so "Sistem Yöneticisi" must normalize to
    # exactly "sistem_yoneticisi" -- one of the four admin-family keys.
    user = SimpleNamespace(is_admin=False, is_superuser=False, role="Sistem Yöneticisi", role_name=None, user_type=None)
    assert approvals.is_admin_user(user) is True


def test_is_admin_user_rejects_plain_employee() -> None:
    user = SimpleNamespace(is_admin=False, is_superuser=False, role="calisan", role_name=None, user_type=None)
    assert approvals.is_admin_user(user) is False


def test_is_admin_user_recognizes_all_caps_turkish_capital_i_role_value() -> None:
    # BYS360 DEFECT AQ: normalize_role() used to call .lower() before
    # .translate(); Python's 'İ'.lower() (capital dotted I, U+0130) produces
    # the two-codepoint sequence 'i' + COMBINING DOT ABOVE (U+0307), not
    # plain 'i', so the translate table's 'İ' entry was dead code and a
    # realistic all-caps HR value like "SİSTEM YÖNETİCİSİ" failed to
    # normalize to "sistem_yoneticisi", silently denying a real admin.
    user = SimpleNamespace(is_admin=False, is_superuser=False, role="SİSTEM YÖNETİCİSİ", role_name=None, user_type=None)
    assert approvals.is_admin_user(user) is True


def test_is_president_user_recognizes_role_field_with_turkish_diacritic() -> None:
    user = SimpleNamespace(role="Başkan", role_name=None, user_type=None, unvan=None, title=None)
    assert approvals.is_president_user(user) is True


def test_is_president_user_recognizes_english_value_in_a_stored_role_field() -> None:
    # The stored role fields (role/role_name/user_type) can carry the English value.
    user = SimpleNamespace(role="calisan", role_name="President", user_type=None, unvan=None, title=None)
    assert approvals.is_president_user(user) is True


def test_is_president_user_ignores_the_job_title_fields() -> None:
    # D3 (HUMAN_POLICY_APPROVED) / R05: a job title (unvan/title) never creates authority; an
    # editor could otherwise set "Başkan" as a title and open the president approvals.
    for unvan, title in (("Başkan", None), (None, "President"), ("BAŞKAN", "president")):
        user = SimpleNamespace(role="calisan", role_name=None, user_type=None, unvan=unvan, title=title)
        assert approvals.is_president_user(user) is False, (unvan, title)


def test_is_president_user_rejects_organization_title_text_containing_but_not_equal_to_baskan() -> None:
    # Source's own comment: "Sadece kesin rol/unvan alanları yetki verir;
    # kurum adı veya 'Başkanlığı' metni yetki vermez." A specialist whose
    # job title merely *mentions* the presidency office must not be granted
    # president authority -- normalize_role treats the whole field as one
    # token, so "Başkanlığı Uzmanı" normalizes to "baskanligi_uzmani", which
    # is not "baskan".
    user = SimpleNamespace(role="calisan", role_name=None, user_type=None, unvan="Başkanlığı Uzmanı", title=None)
    assert approvals.is_president_user(user) is False


def test_is_president_user_rejects_plain_employee() -> None:
    user = SimpleNamespace(role="calisan", role_name=None, user_type=None, unvan=None, title=None)
    assert approvals.is_president_user(user) is False


def test_can_view_president_approvals_true_for_real_president_and_real_admin() -> None:
    president = SimpleNamespace(role="baskan", role_name=None, user_type=None, unvan=None, title=None)
    admin = SimpleNamespace(is_admin=True, is_superuser=False, role=None, role_name=None, user_type=None)
    assert approvals.can_view_president_approvals(president) is True
    assert approvals.can_view_president_approvals(admin) is True


def test_can_view_president_approvals_false_for_real_plain_employee() -> None:
    employee = SimpleNamespace(
        is_admin=False, is_superuser=False, role="calisan", role_name=None, user_type=None, unvan=None, title=None
    )
    assert approvals.can_view_president_approvals(employee) is False


def test_can_delete_president_approval_records_is_admin_only_not_president() -> None:
    # The key distinct-permission proof: a real Başkan passes view but must
    # NOT pass delete; a real admin passes both.
    president = SimpleNamespace(id=2, role="baskan", role_name=None, user_type=None, unvan=None, title=None)
    admin = SimpleNamespace(id=1, is_admin=True, is_superuser=False, role=None, role_name=None, user_type=None)

    assert approvals.can_view_president_approvals(president) is True
    assert approvals.can_delete_president_approval_records(president) is False

    assert approvals.can_view_president_approvals(admin) is True
    assert approvals.can_delete_president_approval_records(admin) is True


# ---------------------------------------------------------------------------
# build_president_approval_workspace: real authorization gate + the low-score
# (< 70) filter, including the exact 70.0 boundary.
# ---------------------------------------------------------------------------


def test_build_workspace_unauthorized_viewer_returns_unauthorized_shape_without_touching_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_db(monkeypatch, _forbid_db_execute)
    monkeypatch.setattr(approvals, "table_exists", _forbid_table_exists)

    employee = SimpleNamespace(
        id=7, is_admin=False, is_superuser=False, role="calisan", role_name=None, user_type=None, unvan=None, title=None
    )

    result = approvals.build_president_approval_workspace(employee, status_filter="pending")

    assert result == {
        "authorized": False,
        "rows": [],
        "summary": {},
        "status_filter": "pending",
        "filter_label": "Onay Bekleyenler",
        "can_delete_president_records": False,
    }


def test_build_workspace_authorized_admin_includes_only_low_score_rows_and_excludes_boundary_70(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_rows: list[dict[str, Any]] = [
        {
            "approval_id": 1, "flow_id": None, "evaluation_id": None, "final_score": 69.99,
            "approval_status": "pending", "employee_ad": "Ada", "employee_soyad": "Yilmaz",
        },
        {
            # Exact boundary: 70.0 is NOT "< 70", so this row must be
            # excluded from both the row list and the summary counts.
            "approval_id": 2, "flow_id": None, "evaluation_id": None, "final_score": 70.0,
            "approval_status": "pending", "employee_ad": "Boundary", "employee_soyad": "Case",
        },
        {
            "approval_id": 3, "flow_id": None, "evaluation_id": None, "final_score": 45.0,
            "approval_status": "approved", "employee_ad": "Can", "employee_soyad": "Demir",
        },
        {
            "approval_id": 4, "flow_id": None, "evaluation_id": None, "final_score": 85.0,
            "approval_status": "pending", "employee_ad": "High", "employee_soyad": "Scorer",
        },
        {
            "approval_id": 5, "flow_id": None, "evaluation_id": None, "final_score": None,
            "approval_status": "pending", "employee_ad": "No", "employee_soyad": "Score",
        },
    ]

    def execute(stmt: Any, params: dict[str, Any] | None = None) -> _FakeExecResult:
        sql = str(stmt)
        assert "FROM performance_president_approvals pa" in sql
        return _FakeExecResult(rows=fixture_rows)

    _install_fake_db(monkeypatch, execute)
    # Every fixture row has flow_id=evaluation_id=None, so `_scoring_history`
    # short-circuits on `evaluation_id` alone; `_flow_steps` still calls
    # `table_exists(...)` unconditionally as its first line, so this is
    # forced False to keep the test scoped to authorization + the
    # low-score-boundary contract rather than the unrelated
    # history/flow-steps rendering helpers.
    monkeypatch.setattr(approvals, "table_exists", lambda name: False)

    admin = SimpleNamespace(id=1, is_admin=True, is_superuser=False, role=None, role_name=None, user_type=None)

    result = approvals.build_president_approval_workspace(admin, status_filter="all")

    assert result["authorized"] is True
    assert result["can_delete_president_records"] is True
    assert result["status_filter"] == "all"
    assert result["filter_label"] == "Tüm Kayıtlar"

    returned_ids = [row["approval_id"] for row in result["rows"]]
    assert returned_ids == [1, 3]

    low_row = result["rows"][0]
    assert low_row["final_score"] == "69.99"
    assert low_row["score_class"] == "score-low"

    critical_row = result["rows"][1]
    assert critical_row["final_score"] == "45.00"
    assert critical_row["score_class"] == "score-critical"

    # Summary counts must also exclude the 70.0 boundary row and the
    # None-score row, exactly like the row list does.
    assert result["summary"] == {"total": 2, "pending": 1, "approved": 1, "returned": 0}


def test_build_workspace_authorized_president_viewer_cannot_delete_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_rows = [
        {
            "approval_id": 10, "flow_id": None, "evaluation_id": None, "final_score": 60.0,
            "approval_status": "pending", "employee_ad": "Only", "employee_soyad": "Row",
        },
    ]

    def execute(stmt: Any, params: dict[str, Any] | None = None) -> _FakeExecResult:
        return _FakeExecResult(rows=fixture_rows)

    _install_fake_db(monkeypatch, execute)
    monkeypatch.setattr(approvals, "table_exists", lambda name: False)

    president = SimpleNamespace(id=99, role="baskan", role_name=None, user_type=None, unvan=None, title=None)

    result = approvals.build_president_approval_workspace(president, status_filter="all")

    assert result["authorized"] is True
    # A real president can view the workspace but must not be granted
    # record-deletion capability -- distinct from the admin case above.
    assert result["can_delete_president_records"] is False
    assert [row["approval_id"] for row in result["rows"]] == [10]


# ---------------------------------------------------------------------------
# decide_president_approval: real authorization gate, invalid-action guard
# with zero mutation, and a genuine state mutation + audit-step call on a
# valid decision.
# ---------------------------------------------------------------------------


def test_decide_president_approval_rejects_unauthorized_real_employee_without_db_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_db(monkeypatch, _forbid_db_execute)
    employee = SimpleNamespace(
        id=3, is_admin=False, is_superuser=False, role="calisan", role_name=None, user_type=None, unvan=None, title=None
    )

    result = approvals.decide_president_approval(1, employee, "approved")

    assert result.ok is False
    assert result.message == "Bu işlem için Başkan veya yetkili yönetici rolü gerekir."
    assert result.approval_id == 1


def test_decide_president_approval_rejects_invalid_action_without_any_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Authorization passes (real president) but the action value is invalid
    # -- the source checks this BEFORE ever touching the database, so no
    # db.session.execute call should happen at all.
    _install_fake_db(monkeypatch, _forbid_db_execute)
    president = SimpleNamespace(id=42, role="baskan", role_name=None, user_type=None, unvan=None, title=None)

    result = approvals.decide_president_approval(7, president, "deleted")

    assert result.ok is False
    assert result.message == "Geçersiz işlem."
    assert result.approval_id == 7


def test_decide_president_approval_approved_by_real_president_updates_status_and_writes_history_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval_id = 55
    row = {"id": approval_id, "flow_id": None, "evaluation_id": None, "status": "pending"}
    execute = _SequencedExecute(
        [
            _FakeExecResult(first=row),  # initial SELECT of the approval row
            _FakeExecResult(),  # the UPDATE statement (return value unused)
        ]
    )
    fake_db = _install_fake_db(monkeypatch, execute)
    # BYS360 DEFECT AN: decide_president_approval() now gates its optional
    # UPDATE columns (decision_status/decision_action/decided_by_name/...)
    # through _table_columns(), which this fake db cannot answer (no real
    # engine); _table_columns is mocked directly, matching real production
    # schema truth -- none of those columns exist under any migration -- so
    # only the always-real status/president_user_id/decided_at/
    # decision_note/updated_at columns are asserted below.
    monkeypatch.setattr(approvals, "_table_columns", lambda name: set())

    insert_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(approvals, "_insert_step_for_decision", lambda **kw: insert_calls.append(kw))

    president = SimpleNamespace(
        id=42, role="baskan", role_name=None, user_type=None, unvan=None, title=None, full_name="Ayşe Başkan"
    )

    result = approvals.decide_president_approval(approval_id, president, "approved", note="Onaylandı")

    assert result.ok is True
    assert result.message == "Başkan onayı kaydedildi."
    assert result.approval_id == approval_id
    assert fake_db.session.commit_calls == 1
    assert fake_db.session.rollback_calls == 0

    assert len(execute.calls) == 2
    update_sql, update_params = execute.calls[1]
    assert "UPDATE performance_president_approvals" in update_sql
    assert update_params["approval_id"] == approval_id
    assert update_params["status"] == "approved"
    assert update_params["actor_id"] == 42
    assert update_params["note"] == "Onaylandı"

    # The audit/history side effect the source actually performs on a valid
    # decision: it calls `_insert_step_for_decision` with the real actor and
    # action -- proving the write is genuinely wired to the real decision,
    # not skipped.
    assert insert_calls == [
        {
            "approval_id": approval_id,
            "flow_id": None,
            "evaluation_id": None,
            "actor": president,
            "action": "approved",
            "note": "Onaylandı",
        }
    ]


def test_decide_president_approval_returned_by_real_admin_updates_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval_id = 56
    row = {"id": approval_id, "flow_id": None, "evaluation_id": None, "status": "pending"}
    execute = _SequencedExecute(
        [
            _FakeExecResult(first=row),
            _FakeExecResult(),
        ]
    )
    fake_db = _install_fake_db(monkeypatch, execute)
    monkeypatch.setattr(approvals, "_table_columns", lambda name: set())
    monkeypatch.setattr(approvals, "_insert_step_for_decision", lambda **kw: None)

    admin = SimpleNamespace(
        id=8, is_admin=True, is_superuser=False, role=None, role_name=None, user_type=None,
        full_name="Sistem Yöneticisi",
    )

    result = approvals.decide_president_approval(approval_id, admin, "returned", note="İade")

    assert result.ok is True
    assert result.message == "Süreç iade edildi."
    assert fake_db.session.commit_calls == 1

    update_sql, update_params = execute.calls[1]
    assert "UPDATE performance_president_approvals" in update_sql
    assert update_params["status"] == "returned"
    assert update_params["note"] == "İade"


# ---------------------------------------------------------------------------
# delete_president_approval_record: real authorization gate (admin-only,
# distinct from view), enforced with a real president to prove the
# view/delete distinction end-to-end on this function too.
# ---------------------------------------------------------------------------


def test_delete_president_approval_record_rejects_real_president_viewer_without_db_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_db(monkeypatch, _forbid_db_execute)
    monkeypatch.setattr(approvals, "table_exists", _forbid_table_exists)

    president = SimpleNamespace(id=42, role="baskan", role_name=None, user_type=None, unvan=None, title=None)

    result = approvals.delete_president_approval_record(9, president)

    assert result.ok is False
    assert result.message == "Bu kayıt yalnızca Admin/Sistem Yöneticisi tarafından silinebilir."
    assert result.approval_id == 9


def test_delete_president_approval_record_succeeds_for_real_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval_id = 12
    row = {
        "id": approval_id, "flow_id": None, "evaluation_id": None,
        "employee_id": None, "status": "pending", "decision_status": "pending",
    }
    execute = _SequencedExecute(
        [
            _FakeExecResult(first=row),  # initial SELECT of the approval row
            _FakeExecResult(rowcount=1),  # the DELETE statement
        ]
    )
    fake_db = _install_fake_db(monkeypatch, execute)
    # Only the main approvals table "exists"; the flow-steps cleanup branch
    # is skipped, keeping this test scoped to the authorization + delete
    # mutation contract rather than the step-cleanup helper.
    monkeypatch.setattr(approvals, "table_exists", lambda name: name == "performance_president_approvals")

    admin = SimpleNamespace(id=1, is_admin=True, is_superuser=False, role=None, role_name=None, user_type=None)

    result = approvals.delete_president_approval_record(approval_id, admin)

    assert result.ok is True
    assert result.message == "Başkan onayı kaydı silindi."
    assert result.approval_id == approval_id
    assert fake_db.session.commit_calls == 1
    assert fake_db.session.rollback_calls == 0

    assert len(execute.calls) == 2
    delete_sql, delete_params = execute.calls[1]
    assert "DELETE FROM performance_president_approvals" in delete_sql
    assert delete_params == {"approval_id": approval_id}
