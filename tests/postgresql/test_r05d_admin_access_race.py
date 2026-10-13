"""Required acceptance test: run explicitly against the disposable local PR70 database.

Missing PostgreSQL is an error, never a passing SQLite substitute or a skip.
"""
from __future__ import annotations

import threading
import time

import pytest

from tests.security import test_r05c_settings_authority_and_admin_continuity_contract as previous


@pytest.mark.parametrize("first_operation", ["revoke", "demote"])
def test_revocation_and_demotion_leave_usable_admin(monkeypatch, install_interim_notes_schema, first_operation):
    assert previous.PG_URL, "BYS360_R05C_PG_URL must identify a disposable localhost database"
    pg = previous._pg_env(monkeypatch, install_interim_notes_schema)
    from sqlalchemy import text

    from app.extensions import db
    from app.models import User, UserMenuPermission
    from app.services import account_change_guard as guard

    first_locked = threading.Event()
    second_waiting = threading.Event()
    real_lock = guard.lock_active_admin_ids
    outcomes = {}
    pids = {}
    errors = []

    def lock():
        if threading.current_thread().name == "second":
            assert first_locked.wait(10)
            second_waiting.set()
        result = real_lock()
        if threading.current_thread().name == "first":
            first_locked.set()
            assert second_waiting.wait(10)
            time.sleep(0.3)
        return result

    monkeypatch.setattr(guard, "lock_active_admin_ids", lock)

    def run(name, operation):
        try:
            with pg.app.app_context():
                pids[name] = db.session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                actor_key, target_key = ("admin", "admin2") if operation == "revoke" else ("admin2", "admin")
                actor = db.session.get(User, pg.ids[actor_key])
                target = db.session.get(User, pg.ids[target_key])
                assert actor is not None and target is not None
                if operation == "revoke":
                    refusal = guard.lockout_revocation_refusal(actor, target, revoked_keys={"settings"})
                    if refusal is None:
                        db.session.add(UserMenuPermission(user_id=target.id, menu_key="settings", is_visible=False, source_type="user_override"))
                else:
                    refusal = guard.admin_continuity_refusal(actor, target, new_role="personel", new_active=True)
                    if refusal is None:
                        target.role = "personel"
                outcomes[operation] = refusal
                db.session.commit()
                db.session.remove()
        except BaseException as exc:
            errors.append(exc)

    second_operation = "demote" if first_operation == "revoke" else "revoke"
    threads = [threading.Thread(target=run, args=(name, operation), name=name) for name, operation in (("first", first_operation), ("second", second_operation))]
    threads[0].start()
    assert first_locked.wait(10)
    threads[1].start()
    for thread in threads:
        thread.join(20)
    assert not any(thread.is_alive() for thread in threads), "deadlock or unbounded lock wait"
    assert not errors, errors
    assert len(set(pids.values())) == 2, pids
    with pg.app.app_context():
        active = guard.lock_active_admin_ids()
        revoked = {row.user_id for row in UserMenuPermission.query.filter(UserMenuPermission.menu_key.in_(guard.LOCKOUT_CRITICAL_ADMIN_KEYS), UserMenuPermission.is_visible.is_(False)).all()}
        assert active - revoked, f"lost every usable administrator: {outcomes}, backend pids={pids}"
        db.session.rollback()
    assert outcomes[first_operation] is None
    assert outcomes[second_operation] == "last_admin_with_access"
    print(f"PostgreSQL overlap order={first_operation}, backend_pids={pids}, outcomes={outcomes}")
