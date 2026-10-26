"""M-1 on PostgreSQL: the hierarchy/personnel record and its task sync commit together or not at all.

The M-1 contract (tests/security/test_m1_hierarchy_assignment_sync_contract.py) runs on SQLite. These
are the same tests, imported unchanged, with ``env`` pointing at a disposable local PostgreSQL
database (``BYS360_R05C_PG_URL``): a failed or failing sync leaves neither tasks nor the hierarchy
change behind, a frozen period is not changed indirectly, and a real admin's change is saved with its
sync. Missing PostgreSQL is an error, never a passing SQLite substitute or a skip.
"""
from __future__ import annotations

import pytest

from tests.security import test_r05c_settings_authority_and_admin_continuity_contract as previous
from tests.security.test_m1_hierarchy_assignment_sync_contract import (  # noqa: F401  (collected here)
    test_a_frozen_period_is_not_changed_indirectly_even_by_the_real_admin,
    test_a_sync_that_fails_midway_rolls_back_tasks_and_hierarchy_together,
    test_a_sync_that_reports_failure_writes_nothing_and_is_not_shown_as_success,
    test_real_admin_chain_change_is_saved_with_its_task_sync,
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
