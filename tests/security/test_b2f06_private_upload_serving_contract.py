"""B2-F06 contract: private uploads are never served through ``/static``.

Before this contract every upload kind below was written under the Flask static
folder -- directly, or through the ``UPLOAD_FOLDER`` default ``app/static/uploads``
-- so the built-in ``static`` endpoint answered anyone who knew the stored name,
anonymous visitors included, and bypassed the object-level checks of the
authorized download routes:

=================  =============================================  ==========================================
kind               legacy location (under app/static)             authorized route (object-level check)
=================  =============================================  ==========================================
messages           uploads/messages/<name>                        /messages/attachments/<name> (participant)
support tickets    uploads/support_tickets/<ticket>/<name>        /support/<ticket>/attachments/<id>
                   (``UPLOAD_FOLDER`` default)                    (creator / assignee / support scope)
portal media       uploads/portal/<name>                          /portal/attachments/<id> (post audience;
                                                                  new -- the feed linked /static before)
HR documents       uploads/hr/personnel_documents/<name>          /hr-management/self-service/request/...
                   (``UPLOAD_FOLDER`` default)                    (own request) and the HR scope routes
publications       uploads/publications/YYYY/MM/<name>            none live: the publication routes belong
                   (``UPLOAD_FOLDER`` default)                    to the removed education bucket, so only
                                                                  legacy files can exist (guard only)
profile photos     uploads/profile_photos/<name>                  /uploads/profile_photos/<name> (login;
                                                                  every signed-in user sees avatars)
=================  =============================================  ==========================================

Contract pinned here:

1. A direct ``/static`` request for a private upload subpath answers 404 without the
   file bytes, for legacy files already under the static folder (``uploads/`` and a
   ``UPLOAD_FOLDER`` configured inside static) and for normalised spellings of the
   same path -- also for web-session and mobile-bearer callers.
2. New uploads land under ``PRIVATE_UPLOAD_FOLDER`` -- outside the static folder -- even
   when that setting is pointed inside the static folder by mistake.
3. The permitted user still downloads both newly stored and legacy-located files
   through the authorized route (200, identical bytes); anonymous and unauthorized
   users get a redirect / 403 / 404 without the bytes.
4. Templates and model URLs link to the authorized routes; public static assets
   (css, img, pwa) are still served.
5. Support attachments follow the ticket rule (``can_view_support_ticket``: creator,
   assignee, or ``support_all`` within the private-ticket unit rule), and a failed
   clean-up of a private file is logged without its stored name or path.

The legacy files live in a throwaway static folder (``tmp_path``) laid out like
``app/static``; nothing is written into the checkout's ``app/static`` or ``instance``.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "PrivateUploadServingTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "b2f06_private_uploads" / "dbs"
_STATIC_UPLOAD_SUBDIRS = (
    ("uploads", "messages"),
    ("uploads", "support_tickets"),
    ("uploads", "portal"),
    ("uploads", "hr", "personnel_documents"),
    ("uploads", "publications"),
    ("uploads", "profile_photos"),
)
_PNG_HEADER = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
# Every kind that has (or had) files under app/static/uploads -- the /static guard covers all of them.
KINDS = ("messages", "support", "portal", "hr", "publications", "profile_photos")
# Kinds with a live authorized download route.
ROUTE_KINDS = ("messages", "support", "portal", "hr", "profile_photos")
PUBLIC_ASSETS = ("img/default-avatar.svg", "pwa/bys360-pwa.css", "img/favicon.png")


def _marker(label: str) -> bytes:
    return f"BYS360-B2F06-{label}-{uuid.uuid4().hex}".encode()


def _pdf(label: str) -> tuple[bytes, bytes]:
    marker = _marker(label)
    return b"%PDF-1.4\n%" + marker + b"\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n", marker


def _png(label: str) -> tuple[bytes, bytes]:
    marker = _marker(label)
    return _PNG_HEADER + marker, marker


def _snapshot(root: Path) -> tuple[set[Path], set[Path]]:
    files: set[Path] = set()
    dirs: set[Path] = set()
    for parts in _STATIC_UPLOAD_SUBDIRS:
        for depth in range(1, len(parts) + 1):
            candidate = root.joinpath(*parts[:depth])
            if candidate.is_dir():
                dirs.add(candidate)
        base = root.joinpath(*parts)
        if base.is_dir():
            for path in base.rglob("*"):
                (files if path.is_file() else dirs).add(path)
    return files, dirs


def _restore(root: Path, before: tuple[set[Path], set[Path]]) -> None:
    """Safety net: drop anything code under test wrote into the checkout's static/uploads."""
    before_files, before_dirs = before
    after_files, after_dirs = _snapshot(root)
    for path in after_files - before_files:
        path.unlink(missing_ok=True)
    for path in sorted(after_dirs - before_dirs, key=lambda item: len(item.parts), reverse=True):
        with contextlib.suppress(OSError):
            path.rmdir()


@pytest.fixture
def env(monkeypatch, tmp_path):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    uri = "sqlite:///" + db_file.as_posix()
    private_root = tmp_path / "private_uploads"
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-b2f06-private-uploads",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "b2f06-private-uploads-first-login",
        "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "PRIVATE_UPLOAD_FOLDER": str(private_root),
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    app = create_app()
    real_static = Path(str(app.static_folder)).resolve()
    # A throwaway static folder laid out like app/static holds the legacy files.
    app_root = tmp_path / "app_root"
    static_root = app_root / "static"
    static_root.mkdir(parents=True)
    app.static_folder = str(static_root)
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=uri,
        # The shipped default: UPLOAD_FOLDER is <static folder>/uploads (config.py).
        UPLOAD_FOLDER=str(static_root / "uploads"),
        PRIVATE_UPLOAD_FOLDER=str(private_root),
    )
    before = _snapshot(real_static)

    from app.extensions import db
    from app.models import (
        Message,
        MessageAttachment,
        MessageThread,
        MessageThreadParticipant,
        PersonnelSelfServiceRequest,
        PersonnelSelfServiceRequestAttachment,
        PortalPost,
        PortalPostAttachment,
        PortalPostAudience,
        PublicationIssue,
        SupportTicket,
        SupportTicketAttachment,
        User,
    )
    from app.services import runtime_schema

    ids: dict[str, int] = {}
    legacy: dict[str, SimpleNamespace] = {}
    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        for key, role in (("owner", "personel"), ("peer", "personel"), ("intruder", "personel"), ("manager", "admin")):
            sicil = f"B2F06{key.upper()}"
            user = User(
                sicil_no=sicil,
                email=f"{sicil.lower()}@example.gov.tr",
                ad="Dosya",
                soyad=key.title(),
                role=role,
                birim="Birim-A",
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            ids[key] = int(user.id)

        def _write(relative_parts: tuple[str, ...], payload: bytes) -> Path:
            target = static_root.joinpath(*relative_parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            return target

        # messages: owner <-> peer thread with a legacy attachment
        thread = MessageThread(thread_type="direct", created_by_user_id=ids["owner"], is_active=True)
        db.session.add(thread)
        db.session.flush()
        for member in ("owner", "peer"):
            db.session.add(MessageThreadParticipant(thread_id=thread.id, user_id=ids[member]))
        message = Message(thread_id=thread.id, sender_user_id=ids["owner"], body="Ekli belge")
        db.session.add(message)
        db.session.flush()
        payload, marker = _pdf("legacy-message")
        name = f"{uuid.uuid4().hex}.pdf"
        _write(("uploads", "messages", name), payload)
        db.session.add(MessageAttachment(
            message_id=message.id, original_filename="eski-ek.pdf", stored_filename=name,
            file_path=f"uploads/messages/{name}", file_ext=".pdf", mime_type="application/pdf",
            file_size=len(payload), uploaded_by_user_id=ids["owner"],
        ))
        legacy["messages"] = SimpleNamespace(
            static_rel=f"uploads/messages/{name}", payload=payload, marker=marker,
            route=f"/messages/attachments/{name}", permitted="peer", intruder="intruder",
        )

        # support: ticket created by owner, assigned to peer, legacy attachment under UPLOAD_FOLDER
        ticket = SupportTicket(
            ticket_no=f"B2F06-{uuid.uuid4().hex[:6]}", title="Eski ekli talep", description="Talep", ticket_type="other",
            module_name="test", status="open", created_by_user_id=ids["owner"], assigned_to_user_id=ids["peer"],
            is_private=False, unit_name_snapshot="Birim-A",
        )
        db.session.add(ticket)
        db.session.flush()
        payload, marker = _pdf("legacy-support")
        name = f"{uuid.uuid4().hex}.pdf"
        _write(("uploads", "support_tickets", str(ticket.id), name), payload)
        support_attachment = SupportTicketAttachment(
            ticket_id=ticket.id, uploaded_by_user_id=ids["owner"], filename="eski-talep.pdf", stored_name=name,
            mime_type="application/pdf", file_size=len(payload), attachment_type="document",
        )
        db.session.add(support_attachment)
        db.session.flush()
        legacy["support"] = SimpleNamespace(
            static_rel=f"uploads/support_tickets/{ticket.id}/{name}", payload=payload, marker=marker,
            route=f"/support/{ticket.id}/attachments/{support_attachment.id}", permitted="peer", intruder="intruder",
            ticket_id=int(ticket.id),
        )

        # portal: post by owner visible to the selected peer only
        post = PortalPost(
            author_user_id=ids["owner"], wall_owner_user_id=ids["owner"], body="Seçili kişilere paylaşım",
            post_type="normal", visibility_scope="selected_users", status="published",
            published_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.session.add(post)
        db.session.flush()
        db.session.add(PortalPostAudience(post_id=post.id, audience_type="user", audience_value=str(ids["peer"])))
        payload, marker = _png("legacy-portal")
        name = f"post_{post.id}_{uuid.uuid4().hex}.png"
        _write(("uploads", "portal", name), payload)
        portal_attachment = PortalPostAttachment(
            post_id=post.id, filename="eski-foto.png", stored_path=f"uploads/portal/{name}", mime_type="image/png",
            size_bytes=len(payload), uploaded_by_user_id=ids["owner"],
        )
        db.session.add(portal_attachment)
        db.session.flush()
        legacy["portal"] = SimpleNamespace(
            static_rel=f"uploads/portal/{name}", payload=payload, marker=marker,
            route=f"/portal/attachments/{portal_attachment.id}", permitted="peer", intruder="intruder",
        )

        # HR self-service request attachment (absolute storage_path, UPLOAD_FOLDER default)
        hr_request = PersonnelSelfServiceRequest(
            user_id=ids["owner"], created_by_id=ids["owner"], request_type="bilgi_guncelleme",
            title="Eski belge talebi", description="Talep", priority="normal", status="draft",
        )
        db.session.add(hr_request)
        db.session.flush()
        payload, marker = _pdf("legacy-hr")
        name = f"personnel_request_{uuid.uuid4().hex}.pdf"
        hr_path = _write(("uploads", "hr", "personnel_documents", name), payload)
        hr_attachment = PersonnelSelfServiceRequestAttachment(
            request_id=hr_request.id, uploaded_by_id=ids["owner"], original_filename="eski-belge.pdf",
            stored_filename=name, storage_path=str(hr_path), mime_type="application/pdf", file_size=len(payload),
        )
        db.session.add(hr_attachment)
        db.session.flush()
        legacy["hr"] = SimpleNamespace(
            static_rel=f"uploads/hr/personnel_documents/{name}", payload=payload, marker=marker,
            route=f"/hr-management/self-service/request/{hr_request.id}/attachment/{hr_attachment.id}/download",
            permitted="owner", intruder="intruder",
        )

        # publications: draft (manager-only) PDF under UPLOAD_FOLDER/publications
        payload, marker = _pdf("legacy-publication")
        name = f"20261010101010_{uuid.uuid4().hex[:10]}_taslak.pdf"
        pub_path = _write(("uploads", "publications", "2026", "10", name), payload)
        publication = PublicationIssue(
            title="Taslak yayın", publication_type="bulletin", status="draft", original_filename="taslak.pdf",
            stored_filename=name, storage_path=str(pub_path), mime_type="application/pdf", file_size=len(payload),
            allow_download=True,
        )
        db.session.add(publication)
        db.session.flush()
        legacy["publications"] = SimpleNamespace(
            static_rel=f"uploads/publications/2026/10/{name}", payload=payload, marker=marker,
            route=f"/publications/{publication.id}/download", permitted="manager", intruder="owner",
        )

        # profile photo of the owner (authenticated audience by design: avatars)
        payload, marker = _png("legacy-photo")
        name = f"user_{ids['owner']}_{uuid.uuid4().hex}.png"
        _write(("uploads", "profile_photos", name), payload)
        owner = db.session.get(User, ids["owner"])
        assert owner is not None
        owner.profile_photo_path = f"uploads/profile_photos/{name}"
        legacy["profile_photos"] = SimpleNamespace(
            static_rel=f"uploads/profile_photos/{name}", payload=payload, marker=marker,
            route=f"/uploads/profile_photos/{name}", permitted="peer", intruder=None,
        )
        db.session.commit()

    try:
        yield SimpleNamespace(
            app=app, ids=ids, legacy=legacy, app_root=app_root, static_root=static_root,
            real_static=real_static, private_root=private_root,
        )
    finally:
        _restore(real_static, before)
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        db_file.unlink(missing_ok=True)


def _client(env, who: str | None = None):
    client = env.app.test_client()
    if who is not None:
        response = client.post("/login", data={"sicil_or_email": f"B2F06{who.upper()}", "password": PASSWORD})
        assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), who
    return client


def _bearer(env, who: str) -> dict[str, str]:
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[who])
        assert user is not None
        return {"Authorization": f"Bearer {_issue_token(user)}"}


def _assert_refused(response, marker: bytes) -> None:
    assert response.status_code in {302, 403, 404}, response.status_code
    assert marker not in response.get_data()
    if response.status_code == 302:
        assert "/static/" not in response.headers.get("Location", "")


def _assert_anonymous_route_redirects_to_login(response, marker: bytes) -> None:
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")
    assert marker not in response.get_data()


def _assert_outside_static(env, name: str) -> Path:
    """The stored file exists exactly once, under PRIVATE_UPLOAD_FOLDER and in no static folder."""
    for static in (env.static_root, env.real_static):
        in_static = [path for path in static.rglob(name) if path.is_file()]
        assert in_static == [], [str(path.relative_to(static)) for path in in_static]
    in_private = [path for path in env.private_root.rglob(name) if path.is_file()] if env.private_root.exists() else []
    assert len(in_private) == 1, name
    return in_private[0]


# ---------------------------------------------------------------------------
# 1. /static guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_anonymous_static_request_for_a_legacy_private_file_is_404(env, kind):
    item = env.legacy[kind]
    assert (env.static_root / item.static_rel).is_file()  # precondition: the legacy file is really there
    response = _client(env).get(f"/static/{item.static_rel}")
    assert response.status_code == 404
    assert item.marker not in response.get_data()


@pytest.mark.parametrize("kind", KINDS)
def test_logged_in_static_request_for_a_legacy_private_file_is_404(env, kind):
    item = env.legacy[kind]
    response = _client(env, "intruder").get(f"/static/{item.static_rel}")
    assert response.status_code == 404
    assert item.marker not in response.get_data()


def test_mobile_bearer_cannot_fetch_private_files_via_static_or_web_routes(env):
    headers = _bearer(env, "intruder")
    client = env.app.test_client()
    for kind in KINDS:
        item = env.legacy[kind]
        response = client.get(f"/static/{item.static_rel}", headers=headers)
        assert response.status_code == 404, kind
        assert item.marker not in response.get_data()
    for kind in ROUTE_KINDS:
        item = env.legacy[kind]
        # A mobile bearer is not a web session: the authorized routes still demand a login.
        _assert_anonymous_route_redirects_to_login(client.get(item.route, headers=headers), item.marker)


def test_mobile_ticket_detail_does_not_link_attachments_through_static(env):
    item = env.legacy["support"]
    response = env.app.test_client().get(f"/api/mobile/support/tickets/{item.ticket_id}", headers=_bearer(env, "owner"))
    assert response.status_code == 200
    body = json.dumps(response.get_json(), ensure_ascii=False)
    assert "eski-talep.pdf" in body
    assert "/static/" not in body
    assert item.marker.decode() not in body


@pytest.mark.parametrize(
    "template",
    ["/static/css/../{rel}", "/static/./{rel}", "/static/{rel_dotted}"],
)
def test_static_guard_covers_normalised_spellings(env, template):
    item = env.legacy["messages"]
    rel = item.static_rel
    url = template.format(rel=rel, rel_dotted=rel.replace("uploads/", "uploads/./", 1))
    response = _client(env).get(url)
    assert item.marker not in response.get_data()
    assert response.status_code in {404, 308}


def test_static_guard_covers_an_upload_folder_configured_inside_static(env):
    env.app.config["UPLOAD_FOLDER"] = str(env.static_root / "files")
    payload, marker = _pdf("custom-upload-folder")
    target = env.static_root / "files" / "support_tickets" / "1" / f"{uuid.uuid4().hex}.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    response = _client(env).get(f"/static/{target.relative_to(env.static_root).as_posix()}")
    assert response.status_code == 404
    assert marker not in response.get_data()


def test_private_static_path_matcher_handles_windows_and_traversal_spellings(env):
    from app.security.private_uploads import is_private_static_path

    static_folder = str(env.static_root)
    for filename in (
        "uploads/messages/x.pdf",
        "UPLOADS/Messages/x.pdf",
        "uploads./messages/x.pdf",
        "uploads /messages/x.pdf",
        "uploads::$INDEX_ALLOCATION/messages/x.pdf",
        "css/../uploads/portal/x.png",
        "./uploads/profile_photos/x.png",
        "uploads\\support_tickets\\1\\x.pdf",
        "uploads",
    ):
        assert is_private_static_path(filename, static_folder), filename
    for filename in ("css/bys360-pwa.css", "img/default-avatar.svg", "pwa/bys360-sw.js", "uploads-guide.txt"):
        assert not is_private_static_path(filename, static_folder), filename


def test_private_static_path_matcher_widens_only_to_an_upload_folder_strictly_inside_static(env):
    from app.security.private_uploads import is_private_static_path

    static_folder = str(env.static_root)
    inside = str(env.static_root / "files")
    assert is_private_static_path("files/support_tickets/1/x.pdf", static_folder, inside)
    assert not is_private_static_path("css/site.css", static_folder, inside)
    # UPLOAD_FOLDER equal to the static folder itself, or outside it, never hides public assets.
    assert not is_private_static_path("css/site.css", static_folder, static_folder)
    assert not is_private_static_path("files/x.pdf", static_folder, str(env.private_root))


@pytest.mark.parametrize("asset", PUBLIC_ASSETS)
def test_public_static_assets_are_still_served(env, monkeypatch, asset):
    monkeypatch.setattr(env.app, "static_folder", str(env.real_static))
    assert (env.real_static / asset).is_file()
    response = _client(env).get(f"/static/{asset}")
    assert response.status_code == 200
    assert response.get_data() == (env.real_static / asset).read_bytes()


# ---------------------------------------------------------------------------
# 2./3. legacy-located files: only the authorized route serves them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ROUTE_KINDS)
def test_legacy_located_file_is_served_to_the_permitted_user_through_the_route(env, kind):
    item = env.legacy[kind]
    response = _client(env, item.permitted).get(item.route)
    assert response.status_code == 200, (kind, response.status_code, response.headers.get("Location"))
    assert response.get_data() == item.payload


@pytest.mark.parametrize("kind", [kind for kind in ROUTE_KINDS if kind != "profile_photos"])
def test_legacy_located_file_is_refused_to_an_unauthorized_user(env, kind):
    item = env.legacy[kind]
    _assert_refused(_client(env, item.intruder).get(item.route), item.marker)


@pytest.mark.parametrize("kind", ROUTE_KINDS)
def test_legacy_located_file_route_redirects_anonymous_users_to_login(env, kind):
    item = env.legacy[kind]
    _assert_anonymous_route_redirects_to_login(_client(env).get(item.route), item.marker)


def test_support_attachment_download_follows_the_ticket_view_rule(env):
    """The attachment route applies the ticket rule (K5 ``can_view_support_ticket``) itself."""
    from app.extensions import db
    from app.models import SupportTicket, SupportTicketAttachment, User, UserMenuPermission
    from app.services.support_ticket_access import can_view_support_ticket

    people = ("owner", "peer", "helpdesk", "remote", "intruder")
    cases: dict[bool, tuple[str, bytes, bytes, dict[str, bool]]] = {}
    with env.app.app_context():
        # support_all granted explicitly in Settings: one holder in the ticket unit, one in another unit.
        for key, birim in (("helpdesk", "Birim-A"), ("remote", "Birim-B")):
            sicil = f"B2F06{key.upper()}"
            user = User(
                sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Dosya", soyad=key.title(), role="personel",
                birim=birim, is_active=True, must_change_password=False, must_set_security_question=False,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            env.ids[key] = int(user.id)
            db.session.add(UserMenuPermission(user_id=user.id, menu_key="support_all", is_visible=True,
                                              source_type="user_override"))
        for private in (False, True):
            ticket = SupportTicket(
                ticket_no=f"B2F06-{uuid.uuid4().hex[:6]}", title="Kapsam talebi", description="Talep", ticket_type="other",
                module_name="test", status="open", created_by_user_id=env.ids["owner"],
                assigned_to_user_id=env.ids["peer"], is_private=private, unit_name_snapshot="Birim-A",
            )
            db.session.add(ticket)
            db.session.flush()
            payload, marker = _pdf(f"support-scope-{private}")
            name = f"{uuid.uuid4().hex}.pdf"
            target = env.static_root / "uploads" / "support_tickets" / str(ticket.id) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            attachment = SupportTicketAttachment(
                ticket_id=ticket.id, uploaded_by_user_id=env.ids["owner"], filename="kapsam.pdf", stored_name=name,
                mime_type="application/pdf", file_size=len(payload), attachment_type="document",
            )
            db.session.add(attachment)
            db.session.flush()
            rule = {who: can_view_support_ticket(ticket, db.session.get(User, env.ids[who])) for who in people}
            cases[private] = (f"/support/{ticket.id}/attachments/{attachment.id}", payload, marker, rule)
        db.session.commit()

    # Creator and assignee always; support_all of the ticket unit always; support_all of another
    # unit only when the ticket is not private; an unrelated user never.
    assert cases[False][3] == {"owner": True, "peer": True, "helpdesk": True, "remote": True, "intruder": False}
    assert cases[True][3] == {"owner": True, "peer": True, "helpdesk": True, "remote": False, "intruder": False}
    for private, (route, payload, marker, rule) in cases.items():
        for who, allowed in rule.items():
            response = _client(env, who).get(route)
            if allowed:
                assert response.status_code == 200, (private, who, response.status_code)
                assert response.get_data() == payload
            else:
                _assert_refused(response, marker)


# ---------------------------------------------------------------------------
# 2./3. new uploads go to PRIVATE_UPLOAD_FOLDER and through the route only
# ---------------------------------------------------------------------------


def _check_new_upload(env, *, name: str, static_rel: str, payload: bytes, marker: bytes, route: str,
                      permitted: str, intruder: str | None) -> None:
    _assert_outside_static(env, name)
    _assert_refused(_client(env).get(f"/static/{static_rel}"), marker)
    _assert_anonymous_route_redirects_to_login(_client(env).get(route), marker)
    if intruder is not None:
        _assert_refused(_client(env, intruder).get(route), marker)
    response = _client(env, permitted).get(route)
    assert response.status_code == 200, (route, response.status_code, response.headers.get("Location"))
    assert response.get_data() == payload


def test_new_message_attachment_is_private(env):
    from app.extensions import db
    from app.models import MessageAttachment

    payload, marker = _pdf("new-message")
    client = _client(env, "owner")
    with client.session_transaction() as session:
        session[f"form_token:messages_new:{env.ids['owner']}"] = "b2f06-message-token"
    response = client.post(
        "/messages/new",
        data={
            "recipient_user_id": str(env.ids["peer"]),
            "body": "Yeni ekli mesaj",
            "_form_token": "b2f06-message-token",
            "attachments": (io.BytesIO(payload), "yeni-rapor.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.status_code
    with env.app.app_context():
        row = db.session.query(MessageAttachment).filter_by(original_filename="yeni-rapor.pdf").one()
        name = row.stored_filename
    _check_new_upload(
        env, name=name, static_rel=f"uploads/messages/{name}", payload=payload, marker=marker,
        route=f"/messages/attachments/{name}", permitted="peer", intruder="intruder",
    )


def test_new_support_attachment_is_private(env):
    from app.extensions import db
    from app.models import SupportTicketAttachment

    payload, marker = _pdf("new-support")
    response = _client(env, "owner").post(
        "/support/new",
        data={
            "title": "Yeni ekli talep",
            "description": "Ekli açıklama",
            "attachment": (io.BytesIO(payload), "yeni-talep.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.status_code
    with env.app.app_context():
        row = db.session.query(SupportTicketAttachment).filter_by(filename="yeni-talep.pdf").one()
        name, ticket_id, attachment_id = row.stored_name, int(row.ticket_id), int(row.id)
    _check_new_upload(
        env, name=name, static_rel=f"uploads/support_tickets/{ticket_id}/{name}", payload=payload, marker=marker,
        route=f"/support/{ticket_id}/attachments/{attachment_id}", permitted="owner", intruder="intruder",
    )


def test_new_portal_image_is_private(env):
    from app.extensions import db
    from app.models import PortalPostAttachment

    payload, marker = _png("new-portal")
    # ``personel`` has no ``portal_post_create`` by default; the manager posts for the selected peer.
    response = _client(env, "manager").post(
        "/portal/posts",
        data={
            "body": "Yeni görselli paylaşım",
            "visibility_scope": "selected_users",
            "target_user_ids": str(env.ids["peer"]),
            "portal_images": (io.BytesIO(payload), "yeni-foto.png", "image/png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.status_code
    with env.app.app_context():
        row = db.session.query(PortalPostAttachment).filter_by(filename="yeni-foto.png").one()
        name, attachment_id = Path(row.stored_path).name, int(row.id)
    _check_new_upload(
        env, name=name, static_rel=f"uploads/portal/{name}", payload=payload, marker=marker,
        route=f"/portal/attachments/{attachment_id}", permitted="peer", intruder="intruder",
    )


def test_new_hr_request_attachment_is_private(env):
    from app.extensions import db
    from app.models import PersonnelSelfServiceRequestAttachment

    payload, marker = _pdf("new-hr")
    client = _client(env, "owner")
    with client.session_transaction() as session:
        session["form_token:hr_self_service_request_save:hr_self_service_requests"] = "b2f06-hr-token"
    response = client.post(
        "/hr-management/self-service/requests/save",
        data={
            "form_token": "b2f06-hr-token",
            "title": "Yeni belge talebi",
            "description": "Ekli belge",
            "request_files": (io.BytesIO(payload), "yeni-belge.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.status_code
    with env.app.app_context():
        row = db.session.query(PersonnelSelfServiceRequestAttachment).filter_by(original_filename="yeni-belge.pdf").one()
        name, request_id, attachment_id = row.stored_filename, int(row.request_id), int(row.id)
    _check_new_upload(
        env, name=name, static_rel=f"uploads/hr/personnel_documents/{name}", payload=payload, marker=marker,
        route=f"/hr-management/self-service/request/{request_id}/attachment/{attachment_id}/download",
        permitted="owner", intruder="intruder",
    )


def test_new_profile_photo_is_private(env):
    from app.extensions import db
    from app.models import User

    payload, marker = _png("new-photo")
    response = _client(env, "peer").post(
        "/account/photo",
        data={"profile_photo": (io.BytesIO(payload), "yeni-profil.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.status_code
    with env.app.app_context():
        user = db.session.get(User, env.ids["peer"])
        assert user is not None and user.profile_photo_path
        name = Path(user.profile_photo_path).name
    _check_new_upload(
        env, name=name, static_rel=f"uploads/profile_photos/{name}", payload=payload, marker=marker,
        route=f"/uploads/profile_photos/{name}", permitted="owner", intruder=None,
    )


def test_publication_service_stores_new_pdfs_outside_static(env):
    """The publication routes are not registered (removed education bucket), so the
    writer is exercised directly: a re-enabled module must not write under /static."""
    from werkzeug.datastructures import FileStorage

    from app.extensions import db
    from app.services.publication_service import upload_publication_issue

    assert not any(rule.rule.startswith("/publications") for rule in env.app.url_map.iter_rules())
    payload, _marker = _pdf("service-publication")
    with env.app.test_request_context():
        row = upload_publication_issue(
            file_storage=FileStorage(stream=io.BytesIO(payload), filename="servis-yayin.pdf"),
            title="Servis yayını", subtitle=None, summary=None, publication_type="bulletin", issue_no=None,
            publication_period=None, publication_date=None, status="draft", uploaded_by_id=env.ids["manager"],
        )
        stored = Path(row.storage_path)
        db.session.rollback()
    assert stored.read_bytes() == payload
    _assert_outside_static(env, stored.name)


def test_private_upload_folder_pointing_into_static_is_not_used(env, monkeypatch, tmp_path):
    from app.extensions import db
    from app.models import SupportTicketAttachment

    instance_dir = tmp_path / "instance"
    monkeypatch.setattr(env.app, "instance_path", str(instance_dir))
    env.app.config["PRIVATE_UPLOAD_FOLDER"] = str(env.static_root / "uploads" / "private")
    payload, marker = _pdf("misconfigured-root")
    response = _client(env, "owner").post(
        "/support/new",
        data={"title": "Hatalı kök", "description": "Ekli", "attachment": (io.BytesIO(payload), "hatali-kok.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with env.app.app_context():
        row = db.session.query(SupportTicketAttachment).filter_by(filename="hatali-kok.pdf").one()
        name, ticket_id, attachment_id = row.stored_name, int(row.ticket_id), int(row.id)
    for static in (env.static_root, env.real_static):
        assert [path for path in static.rglob(name) if path.is_file()] == []
    # Falls back to <instance>/private_uploads, outside the static folder.
    assert (instance_dir / "private_uploads" / "support_tickets" / str(ticket_id) / name).read_bytes() == payload
    _assert_refused(_client(env).get(f"/static/uploads/private/support_tickets/{ticket_id}/{name}"), marker)
    response = _client(env, "owner").get(f"/support/{ticket_id}/attachments/{attachment_id}")
    assert response.status_code == 200
    assert response.get_data() == payload


# ---------------------------------------------------------------------------
# 4. links point to the authorized routes
# ---------------------------------------------------------------------------


def test_portal_feed_links_post_media_through_the_authorized_route(env):
    item = env.legacy["portal"]
    page = _client(env, "peer").get("/portal")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert item.route in body
    assert "/static/uploads/portal/" not in body


def test_profile_photo_url_uses_the_authorized_route(env, monkeypatch):
    from app.extensions import db
    from app.models import User

    item = env.legacy["profile_photos"]
    # Production layout: <root_path>/static is the static folder holding the legacy photo.
    monkeypatch.setattr(env.app, "root_path", str(env.app_root))
    with env.app.test_request_context():
        owner = db.session.get(User, env.ids["owner"])
        assert owner is not None
        url = owner.profile_photo_url
    assert url.split("?", 1)[0] == item.route
    assert "/static/" not in url


# ---------------------------------------------------------------------------
# 5. logs carry no file token or private path
# ---------------------------------------------------------------------------


def test_failed_cleanup_logs_carry_no_file_token_or_path(env, monkeypatch, caplog):
    """The stored name is the download key of the message route; neither it nor a path is logged."""
    import logging
    import os

    from app.institutional import hr_personnel_operations_routes as hr_routes
    from app.services import message_service
    from app.services.personnel.profile_photo import delete_personnel_profile_photo
    from app.services.profile_photo_service import delete_profile_photo_file

    message_name = env.legacy["messages"].static_rel.rsplit("/", 1)[1]
    hr_path = env.static_root / env.legacy["hr"].static_rel
    photo_rel = env.legacy["profile_photos"].static_rel

    def _denied(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", str(hr_path))

    # Production layout: <root_path>/static is the static folder holding the legacy files.
    monkeypatch.setattr(env.app, "root_path", str(env.app_root))
    photo_owner = SimpleNamespace(profile_photo_path=photo_rel, profile_photo_updated_at=None)
    caplog.set_level(logging.DEBUG)
    with env.app.app_context(), monkeypatch.context() as patched:
        patched.setattr(Path, "unlink", _denied)
        patched.setattr(os, "remove", _denied)
        message_service.remove_message_attachment_file(message_name)
        hr_routes._remove_file(str(hr_path))
        result = delete_personnel_profile_photo(photo_owner, app_root_path=env.app_root, logger=logging.getLogger("b2f06"))
        delete_profile_photo_file(photo_rel)  # replacing a photo: its old file is removed first

    assert result.warning.startswith("profile_photo_delete_failed")
    assert len([record for record in caplog.records if record.levelno >= logging.WARNING]) >= 4
    assert not any(record.exc_info for record in caplog.records)  # no traceback carrying the OSError path
    logged = caplog.text + result.warning
    for sensitive in (message_name, hr_path.name, Path(photo_rel).name, str(env.static_root), str(env.private_root)):
        assert sensitive not in logged
    for item in (env.legacy["messages"], env.legacy["hr"], env.legacy["profile_photos"]):
        assert (env.static_root / item.static_rel).is_file()  # nothing was deleted behind the patch
