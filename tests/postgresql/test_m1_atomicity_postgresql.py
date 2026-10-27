"""M-1 on PostgreSQL: the hierarchy/personnel record and its task sync commit together or not at all.

The M-1 contract (tests/security/test_m1_hierarchy_assignment_sync_contract.py) runs on SQLite. These
are the same tests, imported unchanged, with ``env`` pointing at a disposable local PostgreSQL
database (``BYS360_R05C_PG_URL``): a failed or failing sync leaves neither tasks nor the hierarchy
change behind, a frozen period is not changed indirectly or cleared (Q3-1), an open period is still
cleared, and a real admin's change is saved with its sync. Missing PostgreSQL is an error, never a
passing SQLite substitute or a skip.

Q3-1 (owner decision a) on PostgreSQL: period delete, clear and reset-all refuse a frozen or withdrawn
period as a whole, the services refuse it too, and the deletion check holds the period row until its
transaction ends, so no publication can commit between the check and the deletes.
"""
from __future__ import annotations

import pytest

from tests.security import test_r05c_settings_authority_and_admin_continuity_contract as previous
from tests.security.test_m1_hierarchy_assignment_sync_contract import (  # noqa: F401  (collected here)
    _setup,
    test_a_frozen_period_is_not_changed_indirectly_even_by_the_real_admin,
    test_a_frozen_periods_tasks_and_evaluations_are_not_cleared_even_by_the_real_admin,
    test_a_sync_that_fails_midway_rolls_back_tasks_and_hierarchy_together,
    test_a_sync_that_reports_failure_writes_nothing_and_is_not_shown_as_success,
    test_real_admin_chain_change_is_saved_with_its_task_sync,
    test_the_clear_service_refuses_a_frozen_period_for_any_caller,
    test_the_real_admin_still_clears_an_open_unpublished_period,
)
from tests.security.test_q31_frozen_period_destruction_contract import (  # noqa: F401  (collected here)
    test_a_frozen_period_is_neither_deleted_nor_reset_even_by_the_real_admin,
    test_reset_all_is_refused_as_a_whole_even_when_other_periods_are_open,
    test_the_delete_and_reset_services_refuse_for_any_caller,
    test_the_real_admin_still_deletes_an_open_never_published_period,
    test_the_real_admin_still_resets_everything_without_a_protected_period,
    test_withdrawing_the_publication_does_not_make_the_period_deletable,
)


@pytest.fixture
def env(monkeypatch, install_interim_notes_schema):
    assert previous.PG_URL, "BYS360_R05C_PG_URL must identify a disposable localhost database"
    data = previous._pg_env(monkeypatch, install_interim_notes_schema)
    yield data
    from app.extensions import db

    with data.app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.mark.parametrize("check", ["period_delete_or_clear", "reset_all"])
def test_the_deletion_check_holds_the_period_row_until_its_transaction_ends(env, check):
    """A publication writes the period row; it cannot commit between the check and the deletes."""
    import sqlalchemy as sa

    from app.extensions import db
    from app.services.performance.period_freeze import (
        delete_protected_period_ids,
        lock_period_for_deletion,
    )

    period_id = _setup(env)
    publish = sa.text("UPDATE performance_periods SET published_at = now() WHERE id = :id")
    other = sa.create_engine(previous.PG_URL)
    try:
        with env.app.app_context():
            if check == "reset_all":
                assert delete_protected_period_ids(lock=True) == []
            else:
                assert lock_period_for_deletion(period_id) is not None
            with other.connect() as connection:
                connection.execute(sa.text("SET lock_timeout = '300ms'"))
                with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
                    connection.execute(publish, {"id": period_id})
                connection.rollback()
            db.session.rollback()  # the check's transaction ends: the row is free again
            with other.begin() as connection:
                assert connection.execute(publish, {"id": period_id}).rowcount == 1
    finally:
        other.dispose()
