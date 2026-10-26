"""F-09 / P1: limits and integrity of the File Center chunked upload.

The single-file upload enforces ``max_file_gb``. The chunked upload (session -> parts -> finalize)
did not: the session accepted any declared total and any client-chosen part size, the last part
had no size limit at all, every write of a part went through the same ``.part.tmp`` file, a user
could keep any number of sessions open, and an abandoned session kept its temporary files for ever.

Now (app/file_center/services.py, settings in app/file_center/settings_service.py):
- the declared total may not exceed ``max_file_gb`` (the single-file limit applies to both paths);
- the part size lies between ``chunk_min_mb`` and ``chunk_max_mb`` (a file smaller than the
  minimum is one part), and a session has at most ``chunk_max_parts`` parts;
- every part must have exactly its expected size (``chunk_size`` bytes, the remainder for the
  last one); the write stops there, so no more than that is ever on disk for a part;
- a user has at most ``chunk_max_open_sessions`` unfinished sessions; expired ones release their
  temporary files and no longer count;
- each part write goes to its own temporary file and replaces the part atomically, so two writes of
  the same part cannot mix; finalize locks the session row, refuses a session that is already
  being finalized and checks every part file's size before it joins them.

Real create_app() on a temporary SQLite file (R05 fixture), synthetic bytes only, storage in
pytest's tmp_path. The concurrent finalize race needs PostgreSQL: tests/postgresql/.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.security import test_r05_account_change_authority_contract as _r05
from tests.security.test_r05_account_change_authority_contract import _web

env = _r05.env

MIB = 1024 * 1024
GIB = 1024 * MIB
SINGLE_FILE_LIMIT = 4 * MIB  # max_file_gb for these tests


@pytest.fixture
def fc(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")
    monkeypatch.setenv("FILE_CENTER_MAX_FILE_GB", repr(SINGLE_FILE_LIMIT / GIB))
    monkeypatch.setitem(env.app.config, "FILE_CENTER_STORAGE_ROOT", str(tmp_path))
    return SimpleNamespace(env=env, client=_web(env, "admin"), root=tmp_path)


def _create(fc, total: int, chunk: int, sha: str = "", client=None):
    client = client or fc.client
    return client.post("/file-center/chunk-upload/session-json", data={
        "original_filename": "sentetik.bin", "total_size_bytes": str(total),
        "chunk_size_bytes": str(chunk), "sha256_hash": sha,
    })


def _session_id(response) -> int:
    assert response.status_code == 200 and response.get_json()["ok"], response.get_data(as_text=True)[:300]
    return int(response.get_json()["session"]["id"])


def _send(fc, session_id: int, index: int, data: bytes, client=None):
    client = client or fc.client
    return client.post(f"/file-center/chunk-upload/session/{session_id}/chunk/{index}",
                       data={"chunk": (io.BytesIO(data), f"sentetik.bin.part{index}")},
                       content_type="multipart/form-data")


def _finalize(fc, session_id: int, client=None):
    return (client or fc.client).post(f"/file-center/chunk-upload/session/{session_id}/finalize")


def _temp_bytes(fc) -> int:
    root = fc.root / "temp" / "chunk_sessions"
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0


def _stored_files(fc) -> list:
    from app.models.file_center_models import FileStorageItem

    with fc.env.app.app_context():
        return [(row.id, row.size_bytes, row.storage_path) for row in FileStorageItem.query.order_by(FileStorageItem.id).all()]


def _refused(response) -> None:
    assert response.status_code == 400, (response.status_code, response.get_data(as_text=True)[:300])
    assert response.get_json()["ok"] is False


def _payload(size: int, seed: int = 7) -> bytes:
    block = hashlib.sha256(str(seed).encode()).digest()
    return (block * (size // len(block) + 1))[:size]


# --------------------------------------------------------------------------- total size


def test_the_single_upload_enforces_the_file_limit(fc):
    """Baseline: the normal upload refuses a file above max_file_gb."""
    data = _payload(SINGLE_FILE_LIMIT + MIB)
    fc.client.post("/file-center/upload", data={"file": (io.BytesIO(data), "sentetik.bin")},
                   content_type="multipart/form-data")
    assert _stored_files(fc) == []


def test_a_chunked_session_cannot_declare_more_than_the_file_limit(fc):
    from app.models.file_center_models import FileUploadSession

    _refused(_create(fc, SINGLE_FILE_LIMIT + 1, MIB))
    assert _temp_bytes(fc) == 0
    with fc.env.app.app_context():
        assert FileUploadSession.query.count() == 0
    _session_id(_create(fc, SINGLE_FILE_LIMIT, MIB))  # exactly the limit is allowed


def test_splitting_into_parts_cannot_exceed_the_file_limit(fc):
    """Declare a small total, then send more data than declared: the extra bytes are refused."""
    sid = _session_id(_create(fc, 2 * MIB + MIB // 2, MIB))  # parts: 1 MiB, 1 MiB, 0.5 MiB
    assert _send(fc, sid, 0, _payload(MIB)).status_code == 200
    assert _send(fc, sid, 1, _payload(MIB)).status_code == 200
    _refused(_send(fc, sid, 2, _payload(5 * MIB)))  # the last part is 0.5 MiB, not 5 MiB
    assert _temp_bytes(fc) <= 2 * MIB + MIB // 2 + 1
    _refused(_finalize(fc, sid))  # part 3 is still missing
    assert _stored_files(fc) == []


# --------------------------------------------------------------------------- part size and count


@pytest.mark.parametrize("chunk", [1, 64 * 1024], ids=["1-byte", "64-KiB"])
def test_a_part_size_below_the_minimum_is_refused(fc, chunk):
    _refused(_create(fc, 3 * MIB, chunk))


def test_a_file_smaller_than_the_minimum_part_is_one_part(fc):
    sid = _session_id(_create(fc, 1000, 1000))
    data = _payload(1000)
    assert _send(fc, sid, 0, data).status_code == 200
    assert _finalize(fc, sid).get_json()["ok"] is True


def test_a_part_size_above_the_maximum_is_refused(fc, monkeypatch):
    monkeypatch.setenv("FILE_CENTER_MAX_FILE_GB", "5")
    _refused(_create(fc, 300 * MIB, 200 * MIB))  # default chunk_max_mb is 100


def test_the_part_count_is_limited(fc, monkeypatch):
    monkeypatch.setenv("FILE_CENTER_CHUNK_MAX_PARTS", "3")
    _refused(_create(fc, 4 * MIB, MIB))
    _session_id(_create(fc, 3 * MIB, MIB))


def test_every_part_must_have_its_exact_size(fc):
    sid = _session_id(_create(fc, 3 * MIB, MIB))
    _refused(_send(fc, sid, 0, _payload(MIB // 2)))  # short non-last part
    _refused(_send(fc, sid, 1, _payload(MIB + 1)))  # one byte too many
    _refused(_send(fc, sid, 3, _payload(MIB)))  # no such part
    from app.models.file_center_models import FileUploadChunk

    with fc.env.app.app_context():
        assert FileUploadChunk.query.count() == 0
    assert _temp_bytes(fc) == 0


# --------------------------------------------------------------------------- temporary disk


def test_open_sessions_per_user_are_limited(fc, monkeypatch):
    monkeypatch.setenv("FILE_CENTER_CHUNK_MAX_OPEN_SESSIONS", "2")
    first = _session_id(_create(fc, MIB, MIB))
    _session_id(_create(fc, MIB, MIB))
    _refused(_create(fc, MIB, MIB))
    fc.client.post(f"/file-center/chunk-upload/session/{first}/cancel")
    _session_id(_create(fc, MIB, MIB))  # a cancelled session no longer counts
    other = _web(fc.env, "admin2")
    _session_id(_create(fc, MIB, MIB, client=other))  # the limit is per user


def test_a_finished_session_does_not_count_as_open(fc, monkeypatch):
    monkeypatch.setenv("FILE_CENTER_CHUNK_MAX_OPEN_SESSIONS", "1")
    sid = _session_id(_create(fc, MIB, MIB))
    assert _send(fc, sid, 0, _payload(MIB)).status_code == 200
    assert _finalize(fc, sid).get_json()["ok"] is True
    _session_id(_create(fc, MIB, MIB))


def test_an_expired_session_releases_its_temporary_files(fc, monkeypatch):
    from datetime import timedelta

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.file_center_models import FileUploadSession

    monkeypatch.setenv("FILE_CENTER_CHUNK_MAX_OPEN_SESSIONS", "1")
    sid = _session_id(_create(fc, 2 * MIB, MIB))
    assert _send(fc, sid, 0, _payload(MIB)).status_code == 200
    assert _temp_bytes(fc) == MIB
    with fc.env.app.app_context():
        row = db.session.get(FileUploadSession, sid)
        assert row is not None
        temp_dir = Path(row.temp_dir)
        row.expires_at = utc_now() - timedelta(minutes=1)
        db.session.commit()
    _session_id(_create(fc, MIB, MIB))  # the expired one neither blocks nor keeps its files
    assert not temp_dir.exists()
    with fc.env.app.app_context():
        expired = db.session.get(FileUploadSession, sid)
        assert expired is not None and expired.status == "expired"
    _refused(_send(fc, sid, 1, _payload(MIB)))


# --------------------------------------------------------------------------- integrity


def test_a_complete_upload_is_joined_verified_and_cleaned_up(fc):
    data = _payload(2 * MIB + 12345, seed=11)
    sid = _session_id(_create(fc, len(data), MIB, hashlib.sha256(data).hexdigest()))
    for index in (2, 0, 1):  # any order
        part = data[index * MIB:(index + 1) * MIB]
        assert _send(fc, sid, index, part).status_code == 200
    assert _send(fc, sid, 1, data[MIB:2 * MIB]).status_code == 200  # a retried part replaces itself
    response = _finalize(fc, sid)
    assert response.get_json()["ok"] is True
    [(file_id, size, path)] = _stored_files(fc)
    assert size == len(data) and Path(path).read_bytes() == data
    assert _temp_bytes(fc) == 0
    again = _finalize(fc, sid)  # finalizing twice returns the same file
    assert again.get_json()["file_id"] == file_id and len(_stored_files(fc)) == 1
    from app.models.file_center_models import FileSecurityScan

    with fc.env.app.app_context():
        assert FileSecurityScan.query.filter_by(file_id=file_id).count() == 1  # still queued for scanning


def test_two_writes_of_the_same_part_cannot_mix(fc, monkeypatch):
    """The second write of a part starts while the first is still copying (a client retry)."""
    from app.extensions import db
    from app.file_center import services
    from app.models.file_center_models import FileUploadChunk

    sid = _session_id(_create(fc, 2 * MIB, MIB))
    first, second = _payload(MIB, seed=1), _payload(MIB, seed=2)

    class InterleavedStream(io.BytesIO):
        started = False

        def read(self, size=-1):
            data = super().read(min(size, 256 * 1024) if size and size > 0 else size)
            if not InterleavedStream.started:
                InterleavedStream.started = True
                services.upload_chunk_part(session_id=sid, owner_user_id=fc.env.ids["admin"], chunk_index=0,
                                           file_storage=SimpleNamespace(stream=io.BytesIO(second)))
            return data

    with fc.env.app.test_request_context():
        try:
            services.upload_chunk_part(session_id=sid, owner_user_id=fc.env.ids["admin"], chunk_index=0,
                                       file_storage=SimpleNamespace(stream=InterleavedStream(first)))
        except Exception:
            db.session.rollback()
            raise
        db.session.commit()
        row = FileUploadChunk.query.filter_by(session_id=sid, chunk_index=0).one()
        on_disk = Path(row.storage_path).read_bytes()
    assert on_disk in (first, second)  # one whole write, never a mix
    assert hashlib.sha256(on_disk).hexdigest() == row.sha256_hash and row.size_bytes == len(on_disk)


def test_an_oversized_part_never_takes_more_disk_than_its_expected_size(fc):
    """The write stops at the expected size; it does not first store the whole oversized part."""
    from app.extensions import db
    from app.file_center import services

    sid = _session_id(_create(fc, 2 * MIB + MIB // 2, MIB))
    expected_last = MIB // 2
    peak = {"bytes": 0}

    class MeasuringStream(io.BytesIO):
        def read(self, size=-1):
            peak["bytes"] = max(peak["bytes"], _temp_bytes(fc))
            return super().read(size)

    with fc.env.app.test_request_context():
        with pytest.raises(ValueError):
            services.upload_chunk_part(session_id=sid, owner_user_id=fc.env.ids["admin"], chunk_index=2,
                                       file_storage=SimpleNamespace(stream=MeasuringStream(_payload(8 * MIB))))
        db.session.rollback()
    assert peak["bytes"] <= expected_last
    assert _temp_bytes(fc) == 0


def test_finalize_refuses_parts_whose_sizes_shifted_with_the_same_total(fc):
    """Part 1 shrank and part 2 grew by the same amount: the total still matches, the parts do not."""
    from app.models.file_center_models import FileUploadChunk

    sid = _session_id(_create(fc, 2 * MIB, MIB))
    assert _send(fc, sid, 0, _payload(MIB)).status_code == 200
    assert _send(fc, sid, 1, _payload(MIB)).status_code == 200
    with fc.env.app.app_context():
        rows = FileUploadChunk.query.filter_by(session_id=sid).order_by(FileUploadChunk.chunk_index).all()
        first, second = Path(rows[0].storage_path), Path(rows[1].storage_path)
    first.write_bytes(_payload(MIB - 10))
    second.write_bytes(_payload(MIB + 10))
    _refused(_finalize(fc, sid))
    assert _stored_files(fc) == []


def test_finalize_refuses_a_part_whose_file_changed_on_disk(fc):
    from app.models.file_center_models import FileUploadChunk

    sid = _session_id(_create(fc, 2 * MIB, MIB))
    assert _send(fc, sid, 0, _payload(MIB)).status_code == 200
    assert _send(fc, sid, 1, _payload(MIB)).status_code == 200
    with fc.env.app.app_context():
        path = Path(FileUploadChunk.query.filter_by(session_id=sid, chunk_index=1).one().storage_path)
    path.write_bytes(_payload(3 * MIB))
    _refused(_finalize(fc, sid))
    assert _stored_files(fc) == []


def test_a_session_being_finalized_accepts_no_parts_and_no_second_finalize(fc):
    from app.extensions import db
    from app.file_center import services
    from app.models.file_center_models import FileUploadSession

    sid = _session_id(_create(fc, MIB, MIB))
    assert _send(fc, sid, 0, _payload(MIB)).status_code == 200
    with fc.env.app.test_request_context():
        row = db.session.get(FileUploadSession, sid)
        assert row is not None
        row.status = "finalizing"
        with pytest.raises(ValueError):
            services.upload_chunk_part(session_id=sid, owner_user_id=fc.env.ids["admin"], chunk_index=0,
                                       file_storage=SimpleNamespace(stream=io.BytesIO(_payload(MIB))))
        with pytest.raises(ValueError):
            services.finalize_chunk_upload_session(session_id=sid, owner_user_id=fc.env.ids["admin"])
        db.session.rollback()


# --------------------------------------------------------------------------- rights unchanged


def test_another_user_cannot_use_someone_elses_session(fc):
    sid = _session_id(_create(fc, MIB, MIB))
    other = _web(fc.env, "plain")
    _refused(_send(fc, sid, 0, _payload(MIB), client=other))
    _refused(_finalize(fc, sid, client=other))
    assert other.get(f"/file-center/chunk-upload/session/{sid}/status").status_code == 403


def test_the_limits_are_settings_with_documented_defaults(fc, monkeypatch):
    from app.file_center import services
    from app.file_center.settings_service import SETTING_DEFINITIONS

    for key in ("FILE_CENTER_CHUNK_MIN_MB", "FILE_CENTER_CHUNK_MAX_MB", "FILE_CENTER_CHUNK_MAX_PARTS",
                "FILE_CENTER_CHUNK_MAX_OPEN_SESSIONS"):
        monkeypatch.delenv(key, raising=False)
    defined = {item.key: item.value for item in SETTING_DEFINITIONS}
    assert defined["chunk_min_mb"] == "1" and defined["chunk_max_mb"] == "100"
    assert defined["chunk_max_parts"] == "10000" and defined["chunk_max_open_sessions"] == "3"
    with fc.env.app.app_context():
        assert services.chunk_min_size_bytes() == MIB
        assert services.chunk_max_size_bytes() == 100 * MIB
        assert services.chunk_max_parts() == 10000
        assert services.chunk_max_open_sessions() == 3
