"""D1 on PostgreSQL: a protected period is never relinked, and the relink check is race-safe.

The D1 contract (tests/security/test_d1_plan_relink_protected_period_contract.py) runs here unchanged
on a disposable local PostgreSQL database (``BYS360_P0_PG_URL``, read by the P0 fixture). On top of it,
two real two-connection races: the relink check holds the period row until its transaction ends (a
publication cannot commit between the check and the relink's writes), and a lock or publication that
is already in flight when the relink starts is waited for and then refuses the relink. Missing
PostgreSQL is an error, never a passing SQLite substitute or a skip.
"""
from __future__ import annotations

import threading

import pytest
import sqlalchemy as sa

from tests.security import test_p0_period_authority_contract as _p0
from tests.security.test_d1_plan_relink_protected_period_contract import (  # noqa: F401  (collected here)
    test_a_refused_relink_keeps_every_protection_of_the_period,
    test_an_open_unpublished_period_is_still_relinked_by_its_managers,
    test_the_plan_written_before_a_refused_link_is_rolled_back_with_it,
    test_the_president_never_unpublishes_or_relinks_a_protected_period,
    test_the_real_admin_never_relinks_a_protected_period,
    test_the_relink_service_refuses_a_protected_period_for_any_caller,
)
from tests.security.test_p0_period_authority_contract import _linked_plan_period

app = _p0.app


@pytest.fixture(autouse=True)
def _require_postgresql():
    assert _p0.PG_URL, "BYS360_P0_PG_URL must identify a disposable localhost PostgreSQL database"


def test_the_relink_check_holds_the_period_row_until_its_transaction_ends(app):
    from app.extensions import db
    from app.services.performance.v2_1_6_category_period_integration import (
        ensure_plan_relink_allowed,
    )

    plan_key, period_id = _linked_plan_period(app, is_locked=False, results_published=False)
    publish = sa.text("UPDATE performance_periods SET published_at = now() WHERE id = :id")
    other = sa.create_engine(_p0.PG_URL)
    try:
        with app.app_context():
            ensure_plan_relink_allowed(plan_key)  # open period: allowed; its row is now locked
            with other.connect() as connection:
                connection.execute(sa.text("SET lock_timeout = '300ms'"))
                with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
                    connection.execute(publish, {"id": period_id})
                connection.rollback()
            db.session.rollback()  # the relink transaction ends: the row is free again
            with other.begin() as connection:
                assert connection.execute(publish, {"id": period_id}).rowcount == 1
    finally:
        other.dispose()


@pytest.mark.parametrize("column", ["is_locked", "results_published"])
def test_a_lock_or_publication_in_flight_is_waited_for_and_refuses_the_relink(app, column):
    from app.extensions import db
    from app.services.performance.period_freeze import ProtectedPeriodRelinkError
    from app.services.performance.v2_1_6_category_period_integration import (
        ensure_plan_relink_allowed,
    )

    plan_key, period_id = _linked_plan_period(app, is_locked=False, results_published=False)
    other = sa.create_engine(_p0.PG_URL)
    outcome: dict[str, object] = {}
    started = threading.Event()

    def relink_check() -> None:
        with app.app_context():
            started.set()
            try:
                ensure_plan_relink_allowed(plan_key)
                outcome["result"] = "allowed"
            except ProtectedPeriodRelinkError as exc:
                outcome["result"] = ("refused", exc.period_id)
            finally:
                db.session.rollback()

    try:
        with other.connect() as connection:
            transaction = connection.begin()
            connection.execute(sa.text(f"UPDATE performance_periods SET {column} = true WHERE id = :id"), {"id": period_id})
            worker = threading.Thread(target=relink_check)
            worker.start()
            started.wait(5)
            worker.join(1.0)
            assert worker.is_alive(), "the relink check must wait for the row lock held by the in-flight change"
            transaction.commit()
        worker.join(10)
        assert not worker.is_alive()
    finally:
        other.dispose()

    assert outcome.get("result") == ("refused", period_id), outcome
