"""BYS360 P0 wave (Agent 3) -- genuinely behavioral tests for
``app/services/message_service.py``.

This module is the highest fan-in file in the communication domain (16
importers) and owns the most security-relevant surface in that domain:
user-uploaded message attachments. Before this file, the module sat at
20.3% line / 0% branch coverage; the handful of test files that already
referenced it (``tests/architecture/test_message_live_contract.py``,
``tests/critical/test_claude_phase5_critical_contracts.py``,
``tests/security/test_csp_wave9_messages_thread_contract.py``,
``tests/services/test_settings_user_context_phase4da.py``) never actually
called its functions with real inputs.

Coverage focus, in order of security/behavioral importance:

1. ``_validate_message_attachment`` / ``_peek_bytes`` / ``_file_size`` --
   size limits and magic-byte content sniffing that guard every uploaded
   file before it ever touches disk.
2. ``save_message_attachment`` / ``resolve_message_attachment_abspath`` --
   the real filesystem write and the path-traversal guard on download.
3. ``get_message_attachment_for_user`` -- the access-control query that
   gates attachment downloads by thread membership.
4. ``get_or_create_direct_thread`` -- the thread creation/reuse state
   machine (self-thread vs. direct-thread, style application, real DB
   writes for MessageThread + MessageThreadParticipant).
5. ``normalize_incoming_message_files`` / ``notify_user`` /
   ``resolve_message_attachment_download`` -- request-shaped input
   handling and the notification write path.

DB-write tests follow this repo's established lightweight pattern (see
``tests/behavior/test_feedback_campaign_behavior.py``): a small
``FakeSession`` monkeypatched onto ``message_service.db.session`` records
``.add()``/``.flush()`` calls so real business logic (which fields get
set, which objects get added, in what order) can be asserted without a
live database. The one function that is a genuine SQL join
(``get_message_attachment_for_user``) is instead tested against the real
session-scoped ``app``/db fixtures from ``tests/conftest.py`` (real
Flask app factory + real SQLite test DB), because faking a 4-table join
would not actually prove the access-control contract holds.
"""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace

import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    Message,
    MessageAttachment,
    MessageThread,
    MessageThreadParticipant,
    Notification,
    User,
)
from app.services import message_service as svc

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _FakeFiles:
    """Minimal stand-in for ``werkzeug``'s ``request.files`` multi-dict."""

    def __init__(self, mapping: dict[str, list[FileStorage]]) -> None:
        self._mapping = mapping

    def getlist(self, key: str) -> list[FileStorage]:
        return self._mapping.get(key, [])


class _FakeThreadSession:
    """Records ``.add()`` calls and assigns fake primary keys on ``.flush()``,
    mirroring this repo's house FakeSession pattern (see
    ``tests/behavior/test_feedback_campaign_behavior.py``)."""

    def __init__(self) -> None:
        self.added: list = []
        self._next_id = 9001

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def _seed_user(suffix: str) -> User:
    user = User(
        sicil_no=f"msgsvc{suffix}",
        email=f"msgsvc{suffix}@ktb.gov.tr",
        ad="Test",
        soyad="User",
        role="personel",
        is_active=True,
        must_change_password=False,
        must_set_security_question=False,
    )
    user.set_password("TestPassw0rd!23")
    db.session.add(user)
    return user


# ---------------------------------------------------------------------------
# _validate_message_attachment / _peek_bytes / _file_size
# ---------------------------------------------------------------------------


def test_validate_message_attachment_accepts_valid_pdf_with_matching_magic_bytes():
    payload = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj"
    file_storage = FileStorage(stream=io.BytesIO(payload), filename="rapor.pdf")

    ok, message, original_name, file_size = svc._validate_message_attachment(file_storage)

    assert ok is True
    assert message == "ok"
    assert original_name == "rapor.pdf"
    assert file_size == len(payload)
    # Stream must be left ready for a downstream .save() call.
    assert file_storage.stream.tell() == 0


def test_validate_message_attachment_rejects_empty_filename():
    file_storage = FileStorage(stream=io.BytesIO(b"data"), filename="")

    ok, message, original_name, file_size = svc._validate_message_attachment(file_storage)

    assert ok is False
    assert message == "Dosya adı boş."
    assert original_name == ""
    assert file_size == 0


def test_validate_message_attachment_rejects_disallowed_extension():
    file_storage = FileStorage(stream=io.BytesIO(b"MZ fake windows binary"), filename="virus.exe")

    ok, message, original_name, file_size = svc._validate_message_attachment(file_storage)

    assert ok is False
    assert "Desteklenmeyen dosya türü" in message
    assert original_name == "virus.exe"


def test_validate_message_attachment_rejects_spoofed_content_extension_mismatch():
    # Real JPEG magic bytes smuggled in under a .png extension: the
    # extension allow-list alone would let this through, only the
    # content-sniff branch catches it.
    fake_jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 16
    file_storage = FileStorage(stream=io.BytesIO(fake_jpeg_bytes), filename="photo.png")

    ok, message, original_name, file_size = svc._validate_message_attachment(file_storage)

    assert ok is False
    assert "içerik tipi uyuşmuyor" in message
    assert original_name == "photo.png"


def test_validate_message_attachment_boundary_size_exact_limit_passes_one_byte_over_fails():
    header = b"%PDF-1.4"
    small_max = 12
    payload_at_limit = header + b"\x00" * (small_max - len(header))
    assert len(payload_at_limit) == small_max

    fs_ok = FileStorage(stream=io.BytesIO(payload_at_limit), filename="a.pdf")
    ok, _msg, _name, size = svc._validate_message_attachment(fs_ok, max_bytes=small_max)
    assert ok is True
    assert size == small_max

    payload_over_limit = payload_at_limit + b"\x00"
    fs_over = FileStorage(stream=io.BytesIO(payload_over_limit), filename="a.pdf")
    ok2, msg2, _name2, size2 = svc._validate_message_attachment(fs_over, max_bytes=small_max)
    assert ok2 is False
    assert "MB sınırını aşıyor" in msg2
    assert size2 == small_max + 1


def test_file_size_and_peek_bytes_restore_original_stream_position():
    content = b"%PDF-1.4 rest-of-content-for-position-check"

    stream = io.BytesIO(content)
    stream.seek(3)
    size = svc._file_size(SimpleNamespace(stream=stream))
    assert size == len(content)
    assert stream.tell() == 3  # restored, not left at EOF

    stream2 = io.BytesIO(content)
    stream2.seek(5)
    header = svc._peek_bytes(SimpleNamespace(stream=stream2), size=4)
    assert header == b"%PDF"
    assert stream2.tell() == 5  # restored, not left at offset 4


# ---------------------------------------------------------------------------
# save_message_attachment (real tmp_path filesystem write + FakeSession)
# ---------------------------------------------------------------------------


def test_save_message_attachment_happy_path_writes_file_and_builds_record(tmp_path, monkeypatch):
    flask_app = Flask(__name__, root_path=str(tmp_path))
    flask_app.config["PRIVATE_UPLOAD_FOLDER"] = str(tmp_path / "private_uploads")

    captured_adds: list = []

    class FakeSession:
        def add(self, obj):
            captured_adds.append(obj)

    monkeypatch.setattr(svc.db, "session", FakeSession())

    payload = b"%PDF-1.4\n%mock pdf body for message attachment test\n"
    file_storage = FileStorage(stream=io.BytesIO(payload), filename="rapor.pdf", content_type="application/pdf")
    message = SimpleNamespace(id=42)

    with flask_app.app_context():
        attachment = svc.save_message_attachment(file_storage, message, uploaded_by_user_id=7)

    assert isinstance(attachment, MessageAttachment)
    assert attachment.message_id == 42
    assert attachment.original_filename == "rapor.pdf"
    assert attachment.stored_filename.endswith(".pdf")
    assert attachment.file_path == f"uploads/messages/{attachment.stored_filename}"
    assert attachment.file_ext == ".pdf"
    assert attachment.mime_type == "application/pdf"
    assert attachment.file_size == len(payload)
    assert attachment.uploaded_by_user_id == 7
    assert captured_adds == [attachment]

    # B2-F06: the attachment is stored outside the static folder, never under /static.
    saved_path = tmp_path / "private_uploads" / "messages" / attachment.stored_filename
    assert saved_path.exists()
    assert saved_path.read_bytes() == payload
    assert not (tmp_path / "static" / "uploads" / "messages" / attachment.stored_filename).exists()


def test_save_message_attachment_rejects_invalid_extension_without_side_effects(tmp_path, monkeypatch):
    flask_app = Flask(__name__, root_path=str(tmp_path))
    flask_app.config["PRIVATE_UPLOAD_FOLDER"] = str(tmp_path / "private_uploads")

    captured_adds: list = []

    class FakeSession:
        def add(self, obj):
            captured_adds.append(obj)

    monkeypatch.setattr(svc.db, "session", FakeSession())

    file_storage = FileStorage(stream=io.BytesIO(b"MZ\x90\x00fake exe body"), filename="virus.exe")
    message = SimpleNamespace(id=1)

    with flask_app.app_context(), pytest.raises(ValueError, match="Desteklenmeyen dosya türü"):
        svc.save_message_attachment(file_storage, message, uploaded_by_user_id=1)

    assert captured_adds == []
    # Rejection must happen before any upload directory is even created.
    upload_dir = tmp_path / "static" / "uploads" / "messages"
    assert not upload_dir.exists()
    assert not (tmp_path / "private_uploads" / "messages").exists()


def test_save_message_attachment_returns_none_without_file():
    assert svc.save_message_attachment(None, SimpleNamespace(id=1), uploaded_by_user_id=1) is None

    empty_file = FileStorage(stream=io.BytesIO(b""), filename="")
    assert svc.save_message_attachment(empty_file, SimpleNamespace(id=1), uploaded_by_user_id=1) is None


# ---------------------------------------------------------------------------
# resolve_message_attachment_abspath (path-traversal guard)
# ---------------------------------------------------------------------------


def test_resolve_message_attachment_abspath_rejects_path_traversal_filename():
    with pytest.raises(ValueError, match="güvenli değil"):
        svc.resolve_message_attachment_abspath("../../etc/passwd")
    with pytest.raises(ValueError, match="güvenli değil"):
        svc.resolve_message_attachment_abspath("..\\..\\windows\\win.ini")


def test_resolve_message_attachment_abspath_resolves_existing_file_and_rejects_missing(tmp_path):
    flask_app = Flask(__name__, root_path=str(tmp_path))
    flask_app.config["PRIVATE_UPLOAD_FOLDER"] = str(tmp_path / "private_uploads")

    with flask_app.app_context():
        upload_dir = svc.message_upload_dir()
        stored_name = f"{uuid.uuid4().hex}.pdf"
        (upload_dir / stored_name).write_bytes(b"%PDF-1.4 test")

        resolved = svc.resolve_message_attachment_abspath(stored_name)
        assert resolved == (upload_dir / stored_name).resolve()
        assert resolved.is_file()

        with pytest.raises(ValueError, match="bulunamadı"):
            svc.resolve_message_attachment_abspath("does-not-exist.pdf")


# ---------------------------------------------------------------------------
# get_message_attachment_for_user (real DB access-control query)
# ---------------------------------------------------------------------------


def _seed_thread_and_attachment(*, is_active: bool, left_at) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:10]
    owner = _seed_user(suffix)
    db.session.commit()

    thread = MessageThread(thread_type="direct", created_by_user_id=owner.id, is_active=is_active)
    db.session.add(thread)
    db.session.commit()

    db.session.add(MessageThreadParticipant(thread_id=thread.id, user_id=owner.id, left_at=left_at))
    db.session.commit()

    message = Message(thread_id=thread.id, sender_user_id=owner.id, body="merhaba", message_type="text")
    db.session.add(message)
    db.session.commit()

    stored_filename = f"{suffix}.pdf"
    attachment = MessageAttachment(
        message_id=message.id,
        original_filename="rapor.pdf",
        stored_filename=stored_filename,
        file_path=f"uploads/messages/{stored_filename}",
        file_ext=".pdf",
        mime_type="application/pdf",
        file_size=100,
        uploaded_by_user_id=owner.id,
    )
    db.session.add(attachment)
    db.session.commit()

    return owner, stored_filename


def test_get_message_attachment_for_user_allows_active_participant(app):
    with app.app_context():
        owner, stored_filename = _seed_thread_and_attachment(is_active=True, left_at=None)

        result = svc.get_message_attachment_for_user(stored_filename, owner.id)

        assert result is not None
        assert result.stored_filename == stored_filename


def test_get_message_attachment_for_user_denies_non_participant(app):
    with app.app_context():
        owner, stored_filename = _seed_thread_and_attachment(is_active=True, left_at=None)
        outsider = _seed_user(uuid.uuid4().hex[:10])
        db.session.commit()

        result = svc.get_message_attachment_for_user(stored_filename, outsider.id)

        assert result is None


def test_get_message_attachment_for_user_denies_departed_participant(app):
    with app.app_context():
        owner, stored_filename = _seed_thread_and_attachment(is_active=True, left_at=utc_now())

        result = svc.get_message_attachment_for_user(stored_filename, owner.id)

        assert result is None


def test_get_message_attachment_for_user_denies_inactive_thread(app):
    with app.app_context():
        owner, stored_filename = _seed_thread_and_attachment(is_active=False, left_at=None)

        result = svc.get_message_attachment_for_user(stored_filename, owner.id)

        assert result is None


def test_get_message_attachment_for_user_returns_none_for_empty_stored_filename(app):
    with app.app_context():
        assert svc.get_message_attachment_for_user("", 1) is None


# ---------------------------------------------------------------------------
# resolve_message_attachment_download (public download alias contract)
# ---------------------------------------------------------------------------


def test_resolve_message_attachment_download_delegates_to_get_for_user(monkeypatch):
    calls: list = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return "sentinel-attachment"

    monkeypatch.setattr(svc, "get_message_attachment_for_user", fake)

    result = svc.resolve_message_attachment_download("abc.pdf", 5)

    assert result == "sentinel-attachment"
    assert calls == [(("abc.pdf", 5), {})]


# ---------------------------------------------------------------------------
# normalize_incoming_message_files
# ---------------------------------------------------------------------------


def test_normalize_incoming_message_files_rejects_more_than_max_attachments():
    files = [
        FileStorage(stream=io.BytesIO(b"x"), filename=f"file{i}.txt")
        for i in range(svc.MAX_MESSAGE_ATTACHMENTS + 1)
    ]
    request_obj = SimpleNamespace(files=_FakeFiles({"attachments": files}))

    with pytest.raises(ValueError, match="en fazla"):
        svc.normalize_incoming_message_files(request_obj)


def test_normalize_incoming_message_files_rejects_oversized_total(monkeypatch):
    monkeypatch.setattr(svc, "MAX_MESSAGE_TOTAL_SIZE", 20)
    files = [
        FileStorage(stream=io.BytesIO(b"x" * 15), filename="a.txt"),
        FileStorage(stream=io.BytesIO(b"x" * 15), filename="b.txt"),
    ]
    request_obj = SimpleNamespace(files=_FakeFiles({"attachments": files}))

    with pytest.raises(ValueError, match="MB sınırını aşıyor"):
        svc.normalize_incoming_message_files(request_obj)


def test_normalize_incoming_message_files_merges_keys_and_filters_unnamed():
    file1 = FileStorage(stream=io.BytesIO(b"hello"), filename="a.txt")
    file2 = FileStorage(stream=io.BytesIO(b"world"), filename="b.txt")
    unnamed = FileStorage(stream=io.BytesIO(b""), filename="")
    request_obj = SimpleNamespace(files=_FakeFiles({"attachments": [file1, unnamed], "attachment": [file2]}))

    result = svc.normalize_incoming_message_files(request_obj)

    assert result == [file1, file2]


# ---------------------------------------------------------------------------
# get_or_create_direct_thread (thread creation/reuse state machine)
# ---------------------------------------------------------------------------


def test_get_or_create_direct_thread_creates_new_direct_thread_with_both_participants(monkeypatch):
    monkeypatch.setattr(svc, "get_direct_thread_between", lambda a, b: None)
    fake_session = _FakeThreadSession()
    monkeypatch.setattr(svc.db, "session", fake_session)

    thread = svc.get_or_create_direct_thread(
        11, 22, badge_label="Onemli", icon_name="fa-solid fa-star", accent_color="#123abc"
    )

    assert isinstance(thread, MessageThread)
    assert thread.thread_type == "direct"
    assert thread.created_by_user_id == 11
    assert thread.is_active is True
    assert thread.badge_label == "Onemli"
    assert thread.icon_name == "fa-solid fa-star"
    assert thread.accent_color == "#123ABC"  # normalized to uppercase hex

    participants = [o for o in fake_session.added if isinstance(o, MessageThreadParticipant)]
    assert len(participants) == 2
    assert {p.user_id for p in participants} == {11, 22}
    assert all(p.thread_id == thread.id for p in participants)


def test_get_or_create_direct_thread_creates_new_self_thread_with_single_participant(monkeypatch):
    monkeypatch.setattr(svc, "get_direct_thread_between", lambda a, b: None)
    fake_session = _FakeThreadSession()
    monkeypatch.setattr(svc.db, "session", fake_session)

    thread = svc.get_or_create_direct_thread(9, 9)

    assert thread.thread_type == "self"
    assert thread.subject == svc._SELF_THREAD_SUBJECT
    assert thread.badge_label == svc._SELF_THREAD_BADGE
    assert thread.icon_name == svc._SELF_THREAD_ICON
    assert thread.accent_color == svc._SELF_THREAD_COLOR

    participants = [o for o in fake_session.added if isinstance(o, MessageThreadParticipant)]
    assert len(participants) == 1
    assert participants[0].user_id == 9
    assert participants[0].thread_id == thread.id


def test_get_or_create_direct_thread_reuses_existing_self_thread_and_fills_missing_subject(monkeypatch):
    existing = SimpleNamespace(
        id=77,
        thread_type="self",
        subject=None,
        badge_label=None,
        icon_name=None,
        accent_color=None,
    )
    monkeypatch.setattr(svc, "get_direct_thread_between", lambda a, b: existing)
    fake_session = _FakeThreadSession()
    monkeypatch.setattr(svc.db, "session", fake_session)

    thread = svc.get_or_create_direct_thread(4, 4)

    assert thread is existing
    assert thread.subject == svc._SELF_THREAD_SUBJECT
    assert thread.badge_label == svc._SELF_THREAD_BADGE
    assert thread.icon_name == svc._SELF_THREAD_ICON
    assert thread.accent_color == svc._SELF_THREAD_COLOR
    # A reused thread is not re-added/re-persisted.
    assert fake_session.added == []


def test_get_or_create_direct_thread_reuses_existing_direct_thread_and_overwrites_style(monkeypatch):
    existing = SimpleNamespace(
        id=88,
        thread_type="direct",
        subject="Eski Konu",
        badge_label="Eski",
        icon_name="fa-solid fa-bell",
        accent_color="#000000",
    )
    monkeypatch.setattr(svc, "get_direct_thread_between", lambda a, b: existing)
    fake_session = _FakeThreadSession()
    monkeypatch.setattr(svc.db, "session", fake_session)

    thread = svc.get_or_create_direct_thread(4, 5, badge_label="Yeni", icon_name="fa-solid fa-flag", accent_color="#ffaa00")

    assert thread is existing
    assert thread.badge_label == "Yeni"
    assert thread.icon_name == "fa-solid fa-flag"
    assert thread.accent_color == "#FFAA00"
    assert thread.subject == "Eski Konu"  # non-self reuse path never touches subject
    assert fake_session.added == []


# ---------------------------------------------------------------------------
# notify_user
# ---------------------------------------------------------------------------


def test_notify_user_creates_notification_trims_fields_and_invalidates_cache(monkeypatch):
    captured_adds: list = []

    class FakeSession:
        def add(self, obj):
            captured_adds.append(obj)

    monkeypatch.setattr(svc.db, "session", FakeSession())

    invalidated: list = []
    monkeypatch.setattr(svc, "_cache_invalidate", lambda key: invalidated.append(key))

    notification = svc.notify_user(
        user_id=42,
        title="   Yeni Mesaj   ",
        body="  Icerik  ",
        notification_type="message",
        source_type="message_thread",
        source_id=7,
        link_url="/messages/7",
        priority="high",
    )

    assert isinstance(notification, Notification)
    assert notification.user_id == 42
    assert notification.title == "Yeni Mesaj"
    assert notification.body == "Icerik"
    assert notification.notification_type == "message"
    assert notification.source_type == "message_thread"
    assert notification.source_id == 7
    assert notification.link_url == "/messages/7"
    assert notification.priority == "high"
    assert notification.is_read is False
    assert captured_adds == [notification]
    assert invalidated == ["notification_unread_count:42"]


def test_notify_user_defaults_empty_title_and_normal_priority(monkeypatch):
    captured_adds: list = []

    class FakeSession:
        def add(self, obj):
            captured_adds.append(obj)

    monkeypatch.setattr(svc.db, "session", FakeSession())
    monkeypatch.setattr(svc, "_cache_invalidate", lambda key: None)

    notification = svc.notify_user(user_id=3, title="   ", body="", priority="")

    assert notification.title == "BYS360 Bildirimi"
    assert notification.body is None
    assert notification.priority == "normal"
    assert notification.notification_type == "system"
