"""F-09 required race test: two concurrent finalize requests of one chunked upload session.

Run explicitly against a disposable local PostgreSQL database (``BYS360_R05C_PG_URL``, see
scripts/quality/bys360_postgres_race_gate.py). Missing PostgreSQL is an error, never a passing
SQLite substitute or a skip.

Before: both requests read the session as "uploading", both joined the parts and each created a
FileStorageItem, so one upload became two stored files. Now finalize reads the session row with
FOR UPDATE: the second request waits until the first has committed, then sees the finalized
session and returns the same file.
"""
from __future__ import annotations

import io
import threading
from types import SimpleNamespace

from tests.security import test_r05c_settings_authority_and_admin_continuity_contract as previous

MIB = 1024 * 1024


def test_concurrent_finalize_stores_the_upload_once(monkeypatch, tmp_path, install_interim_notes_schema):
    assert previous.PG_URL, "BYS360_R05C_PG_URL must identify a disposable localhost database"
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")
    pg = previous._pg_env(monkeypatch, install_interim_notes_schema)
    pg.app.config["FILE_CENTER_STORAGE_ROOT"] = str(tmp_path)
    from sqlalchemy import text

    from app.extensions import db
    from app.file_center import services
    from app.models.file_center_models import FileStorageItem

    owner = pg.ids["admin"]
    data = b"f09-race-" * (2 * MIB // 9 + 1)
    data = data[: 2 * MIB]
    with pg.app.test_request_context():
        session, _token = services.create_chunk_upload_session(
            owner_user_id=owner, original_filename="sentetik.bin", total_size_bytes=len(data), chunk_size_bytes=MIB)
        for index in range(2):
            services.upload_chunk_part(session_id=session.id, owner_user_id=owner, chunk_index=index,
                                       file_storage=SimpleNamespace(stream=io.BytesIO(data[index * MIB:(index + 1) * MIB])))
        session_id = session.id
        db.session.commit()
        db.session.remove()

    first_inside = threading.Event()
    second_inside = threading.Event()
    real_quota_check = services.check_user_quota_for_upload

    def quota_check(user_id, *, estimated_bytes=0):
        # Called by finalize after it has read the session and the parts.
        if threading.current_thread().name == "first":
            first_inside.set()
            second_inside.wait(3)  # without the row lock the second request gets here too
        else:
            second_inside.set()
        return real_quota_check(user_id, estimated_bytes=estimated_bytes)

    monkeypatch.setattr(services, "check_user_quota_for_upload", quota_check)
    results: dict[str, int] = {}
    pids: dict[str, int] = {}
    errors: list[BaseException] = []

    def run(name):
        try:
            with pg.app.test_request_context():
                pids[name] = db.session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                item = services.finalize_chunk_upload_session(session_id=session_id, owner_user_id=owner)
                results[name] = int(item.id)
                db.session.commit()
                db.session.remove()
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=run, args=("first",), name="first")
    second = threading.Thread(target=run, args=("second",), name="second")
    first.start()
    assert first_inside.wait(10)
    second.start()
    first.join(30)
    second.join(30)
    assert not first.is_alive() and not second.is_alive(), "deadlock or unbounded lock wait"
    assert not errors, errors
    assert len(set(pids.values())) == 2, pids
    with pg.app.app_context():
        stored = FileStorageItem.query.filter_by(owner_user_id=owner).all()
        assert len(stored) == 1, f"one upload stored {len(stored)} times: {results}"
        assert results["first"] == results["second"] == stored[0].id
        assert int(stored[0].size_bytes) == len(data)
        db.session.rollback()
    print(f"PostgreSQL concurrent finalize: backend_pids={pids}, file_ids={results}")
