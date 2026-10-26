"""Issue #105 contract: request bodies are limited before they are read, per endpoint and session.

Before: one global MAX_CONTENT_LENGTH of 150 MB. Every POST body is parsed before authentication
(the CSRF check reads the form, mobile auth reads JSON), so an anonymous client made the app hold
~118 MB with 250 x 490 KB multipart text fields on /login and ~300 MB for a 100 MB JSON body on
/api/mobile/auth/login or /refresh (measured with tracemalloc on the real app).

Now (app/core/form_body_limit.py):
- login, password reset, mobile login/refresh: 64 KiB;
- no logged-in web session (mobile Bearer clients included): 1 MiB, except the public guest upload;
- logged-in user on an endpoint that accepts files: 150 MB, the former global limit;
- everything else: 16 MiB; JSON bodies at most 1 MiB;
- multipart text fields at most 2 MiB in total; urlencoded bodies at most MAX_FORM_MEMORY_SIZE.

Upload validators keep their former limits (UPLOAD_MAX_CONTENT_LENGTH replaces MAX_CONTENT_LENGTH
as their fallback). End-to-end tests log in through POST /login (R05 fixture).
"""
from __future__ import annotations

import ast
import importlib.metadata
import io
import json
import tracemalloc
from pathlib import Path

import pytest
from flask import Flask, request, session
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.test import EnvironBuilder

from app.core import form_body_limit as limits
from app.core.form_body_limit import (
    AUTH_ENDPOINTS,
    PUBLIC_UPLOAD_ENDPOINTS,
    UPLOAD_ENDPOINTS,
    BYS360Request,
    body_limit_for,
)
from tests.security import test_r05_account_change_authority_contract as _r05
from tests.security.test_r05_account_change_authority_contract import _web

env = _r05.env  # seeded accounts on a temporary SQLite file

ROOT = Path(__file__).resolve().parents[2]
KIB, MIB = 1024, 1024 * 1024
EXPECTED = {
    "MAX_CONTENT_LENGTH": 16 * MIB,
    "UPLOAD_MAX_CONTENT_LENGTH": 150 * MIB,
    "ANONYMOUS_MAX_CONTENT_LENGTH": 1 * MIB,
    "AUTH_ENDPOINT_MAX_CONTENT_LENGTH": 64 * KIB,
    "JSON_MAX_CONTENT_LENGTH": 1 * MIB,
    "MAX_FORM_TEXT_BYTES": 2 * MIB,
}

# Every function in app/ that reads uploaded files, reviewed: the endpoint whose request reaches it,
# or None for modules the app does not register (route_manifest excludes them). A new reader fails
# test_every_upload_reader_is_reviewed until it is added here and its endpoint to UPLOAD_ENDPOINTS.
REVIEWED_UPLOAD_READERS: dict[str, tuple[str, ...] | None] = {
    "app/admin/ai_phase7_routes.py:admin_analysis_center_excel_preview": ("main.admin_analysis_center_excel_preview",),
    "app/admin/hierarchy_governance_routes.py:preview_excel": None,
    "app/admin/ops_import_services.py:admin_user_import_impl": ("main.admin_user_import",),
    "app/admin/ops_user_action_services.py:admin_user_change_photo_impl": ("main.admin_user_change_photo",),
    "app/admin/routes.py:admin_user_create": ("main.admin_user_create",),
    "app/admin/routes.py:admin_user_edit": ("main.admin_user_edit",),
    "app/admin/routes.py:personnel_add": ("main.personnel_add",),
    "app/admin/routes.py:personnel_edit": ("main.personnel_edit",),
    "app/admin/routes.py:personnel_excel_upload": ("main.personnel_excel_upload",),
    "app/communication/announcement_popup_routes.py:_normalize_payload_with_upload":
        ("main.announcement_popup_new", "main.announcement_popup_edit"),
    "app/communication/corporate_information_center_routes.py:corporate_information_center_celebration_excel_upload":
        ("main.corporate_information_center_celebration_excel_upload",),
    "app/communication/user_feedback_routes.py:bys360_feedback_new": ("main.bys360_feedback_new",),
    "app/file_center/routes.py:file_center_upload": ("main.file_center_upload",),
    "app/file_center/routes.py:file_center_chunk_upload_part": ("main.file_center_chunk_upload_part",),
    "app/file_center/routes.py:file_center_guest_upload": ("main.file_center_guest_upload",),
    "app/institutional/hr_personnel_operations_routes.py:hr_self_service_request_save": ("main.hr_self_service_request_save",),
    "app/institutional/hr_personnel_operations_routes.py:hr_personnel_document_save": ("main.hr_personnel_document_save",),
    "app/institutional/hr_personnel_operations_routes.py:hr_personnel_document_bulk_upload":
        ("main.hr_personnel_document_bulk_upload",),
    "app/institutional/publication_routes.py:publication_upload": None,
    "app/main_handlers/account_handlers.py:account_change_photo": ("main.account_change_photo",),
    "app/main_handlers/account_settings_helpers.py:_handle_import_visibility_template": ("main.settings_page",),
    "app/performance/history_import_routes.py:performance_history_import": ("main.performance_history_import",),
    "app/performance/performance_archive_routes.py:performance_archive_import": ("main.performance_archive_import",),
    "app/portal/routes.py:portal_post_create": ("main.portal_post_create",),
    "app/services/message_service.py:normalize_incoming_message_files": ("main.messages_new", "main.messages_send"),
    "app/support/routes.py:support_new": ("main.support_new",),
    "app/support/routes.py:support_comment": ("main.support_comment",),
}


def _upload_readers() -> set[str]:
    """module:function for every function in app/ whose body reads ``<something>.files``."""
    found = set()
    for path in sorted((ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            reads_files = any(
                isinstance(inner, ast.Attribute) and inner.attr == "files"
                and isinstance(inner.value, ast.Name) and inner.value.id in {"request", "request_obj", "req"}
                for inner in ast.walk(node)
            )
            if reads_files:
                found.add(f"{path.relative_to(ROOT).as_posix()}:{node.name}")
    return found


def _matched_limit(app, endpoint: str, *, logged_in: bool, content_type: str | None = None) -> tuple[str, int]:
    """(endpoint the request really reaches, its limit) for a POST to one of ``endpoint``'s paths."""
    rule = next(r for r in app.url_map.iter_rules() if r.endpoint == endpoint and "POST" in (r.methods or ()))
    path = rule.rule
    for argument in rule.arguments:
        path = path.replace(f"<int:{argument}>", "1").replace(f"<{argument}>", "x")
    with app.test_request_context(path, method="POST", content_type=content_type):
        if logged_in:
            session["_user_id"] = "1"
        limit = request.max_content_length
        assert limit is not None and request.endpoint is not None
        return request.endpoint, limit


def _limit(app, endpoint: str, *, logged_in: bool, content_type: str | None = None) -> int:
    matched, limit = _matched_limit(app, endpoint, logged_in=logged_in, content_type=content_type)
    assert matched == endpoint
    return limit


def _post_endpoints(app) -> set[str]:
    return {r.endpoint for r in app.url_map.iter_rules() if "POST" in (r.methods or ())}


# --------------------------------------------------------------------------- policy on the real app


def test_config_defaults_and_request_class(env):
    app = env.app
    assert app.request_class is BYS360Request
    for key, value in EXPECTED.items():
        assert app.config[key] == value, key
    assert app.config.get("MAX_FORM_MEMORY_SIZE", 500_000) == 500_000


def test_every_listed_endpoint_is_a_registered_post_endpoint(env):
    registered = _post_endpoints(env.app)
    assert sorted((UPLOAD_ENDPOINTS | AUTH_ENDPOINTS) - registered) == []


@pytest.mark.parametrize("endpoint", sorted(UPLOAD_ENDPOINTS))
def test_upload_endpoints_get_the_upload_limit_only_when_logged_in(env, endpoint):
    assert _limit(env.app, endpoint, logged_in=True) == EXPECTED["UPLOAD_MAX_CONTENT_LENGTH"]
    anonymous = EXPECTED["UPLOAD_MAX_CONTENT_LENGTH"] if endpoint in PUBLIC_UPLOAD_ENDPOINTS else EXPECTED["ANONYMOUS_MAX_CONTENT_LENGTH"]
    assert _limit(env.app, endpoint, logged_in=False) == anonymous


@pytest.mark.parametrize("endpoint", sorted(AUTH_ENDPOINTS))
def test_auth_endpoints_get_64_kib_with_or_without_a_session(env, endpoint):
    for logged_in in (False, True):
        assert _limit(env.app, endpoint, logged_in=logged_in) == 64 * KIB
        assert _limit(env.app, endpoint, logged_in=logged_in, content_type="application/json") == 64 * KIB


def test_every_other_post_endpoint_gets_16_mib_logged_in_and_1_mib_anonymous(env):
    others = sorted(_post_endpoints(env.app) - UPLOAD_ENDPOINTS - AUTH_ENDPOINTS)
    assert len(others) > 300
    for endpoint in others:
        for logged_in in (True, False):
            matched, limit = _matched_limit(env.app, endpoint, logged_in=logged_in)
            expected = body_limit_for(matched, authenticated=logged_in, is_json=False, config=EXPECTED)
            assert limit == expected, (endpoint, matched)
            if matched == endpoint:  # paths shared with another endpoint reach that one instead
                assert limit == (16 * MIB if logged_in else 1 * MIB), endpoint


@pytest.mark.parametrize("endpoint", ["main.file_center_upload", "main.messages_new", "ai_agent.ai_agent_ask"])
def test_json_bodies_are_capped_at_1_mib_everywhere(env, endpoint):
    assert _limit(env.app, endpoint, logged_in=True, content_type="application/json") == 1 * MIB
    assert _limit(env.app, endpoint, logged_in=False, content_type="application/json") == 1 * MIB


def test_a_view_can_still_set_its_own_limit(env):
    with env.app.test_request_context("/file-center/upload", method="POST"):
        request.max_content_length = 3
        assert request.max_content_length == 3


def test_upload_validators_keep_their_former_limit(env):
    from app.security import upload_security

    with env.app.app_context():
        assert upload_security._max_size() == 150 * MIB
        assert upload_security._max_size(5) == 5
    support_source = (ROOT / "app" / "support" / "routes.py").read_text(encoding="utf-8")
    assert 'max_size=current_app.config.get("UPLOAD_MAX_CONTENT_LENGTH")' in support_source


def test_policy_function_table():
    config = dict(EXPECTED)
    assert body_limit_for("main.login", authenticated=False, is_json=False, config=config) == 64 * KIB
    assert body_limit_for(None, authenticated=False, is_json=False, config=config) == 1 * MIB
    assert body_limit_for(None, authenticated=True, is_json=False, config=config) == 16 * MIB
    assert body_limit_for("main.support_new", authenticated=True, is_json=False, config=config) == 150 * MIB
    assert body_limit_for("main.support_new", authenticated=False, is_json=False, config=config) == 1 * MIB
    assert body_limit_for("main.file_center_guest_upload", authenticated=False, is_json=False, config=config) == 150 * MIB
    assert body_limit_for("main.support_new", authenticated=True, is_json=True, config=config) == 1 * MIB
    assert body_limit_for(None, authenticated=True, is_json=False, config={}) == 16 * MIB  # module defaults


# --------------------------------------------------------------------------- the list stays complete


def test_every_upload_reader_is_reviewed():
    assert sorted(_upload_readers() ^ set(REVIEWED_UPLOAD_READERS)) == []


def test_reviewed_readers_map_to_listed_upload_endpoints(env):
    view_modules = {getattr(view, "__module__", "") for view in env.app.view_functions.values()}
    mapped: set[str] = set()
    for reader, endpoints in REVIEWED_UPLOAD_READERS.items():
        if endpoints is None:  # an unregistered module: registering it needs a review of its uploads
            module = reader.split(":", 1)[0][:-3].replace("/", ".")
            assert module not in view_modules, reader
            continue
        mapped.update(endpoints)
    assert mapped == set(UPLOAD_ENDPOINTS)


def test_werkzeug_parser_copy_is_pinned():
    """TextBoundedMultiPartParser.parse copies Werkzeug 3.1.9's loop; an upgrade must re-check it."""
    assert importlib.metadata.version("werkzeug") == "3.1.9"


# --------------------------------------------------------------------------- end to end (real routes)
#
# The R05 app runs with CSRF off. In production the CSRF check reads the form of every POST before
# the view, so that is where an oversized body is refused; tests that prove a limit turn it on.


@pytest.fixture
def csrf_on(env):
    """Call after logging in (the test login posts without a CSRF token); reset at teardown."""
    def enable():
        env.app.config["WTF_CSRF_ENABLED"] = True

    yield enable
    env.app.config["WTF_CSRF_ENABLED"] = False


def _app_peak(app, path, **kwargs):
    environ = EnvironBuilder(path=path, method="POST", **kwargs).get_environ()
    status = {}

    def start_response(value, headers, exc_info=None):
        status["code"] = int(value.split()[0])

    tracemalloc.start()
    try:
        body = b"".join(app.wsgi_app(environ, start_response))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return status["code"], peak, body


def test_issue_105_login_multipart_text_flood_is_413_without_buffering(env):
    fields = {f"f{i}": "a" * 490_000 for i in range(250)}  # 122 MB of text fields
    code, peak, _body = _app_peak(env.app, "/login", data=fields, content_type="multipart/form-data")
    assert code == 413
    assert peak < 8 * MIB  # was ~118 MB


@pytest.mark.parametrize("path", ["/api/mobile/auth/login", "/api/mobile/auth/refresh"])
def test_issue_105_mobile_auth_json_flood_is_413_without_reading(env, path):
    payload = json.dumps({"sicil_or_email": "x", "password": "y", "refresh_token": "z", "pad": "a" * (20 * MIB)})
    code, peak, body = _app_peak(env.app, path, data=payload, content_type="application/json")
    assert code == 413
    assert peak < 4 * MIB  # was ~3x the body size
    assert "message" in json.loads(body)


def _small_file_parts(count: int = 60, size: int = 499_000) -> dict:
    """Many file parts just under Werkzeug's 500 KB in-memory spool size (review finding)."""
    return {f"f{i}": (io.BytesIO(b"x" * size), f"p{i}.bin") for i in range(count)}


def test_many_small_file_parts_on_the_guest_link_are_spooled_to_disk(env):
    code, peak, _body = _app_peak(env.app, "/guest/upload/no-such-token", data=_small_file_parts(),
                                  content_type="multipart/form-data")
    assert code not in {413, 500}  # the public upload link still takes 30 MB
    assert peak < 8 * MIB  # was ~30 MB here, ~150 MB with 290 parts


def test_many_small_file_parts_with_a_session_are_spooled_to_disk(env):
    client = _web(env, "admin")
    cookie = client.get_cookie("session")
    assert cookie is not None
    code, peak, _body = _app_peak(env.app, "/file-center/upload", data=_small_file_parts(),
                                  content_type="multipart/form-data", headers={"Cookie": f"session={cookie.value}"})
    assert code not in {413, 500}
    assert peak < 8 * MIB


def test_auth_endpoints_still_accept_normal_requests(env):
    client = env.app.test_client()
    small = client.post("/api/mobile/auth/login", json={"sicil_or_email": "nobody", "password": "x"})
    assert small.status_code != 413
    _web(env, "admin")  # a normal web login still succeeds
    over = client.post("/login", data={"sicil_or_email": "x", "password": "a" * (70 * KIB)})
    assert over.status_code == 413


def test_anonymous_upload_is_refused_before_the_file_is_spooled_and_nothing_is_written(env, csrf_on):
    from app.models import SupportTicket

    with env.app.app_context():
        before = SupportTicket.query.count()
    client = env.app.test_client()
    csrf_on()
    big = client.post("/support/new", data={"title": "x", "attachment": (io.BytesIO(b"%PDF-1.4" + b"x" * (2 * MIB)), "a.pdf")},
                      content_type="multipart/form-data")
    assert big.status_code == 413
    env.app.config["WTF_CSRF_ENABLED"] = False
    small = client.post("/support/new", data={"title": "x"})
    assert small.status_code == 302 and "/login" in small.headers["Location"]  # authorization unchanged
    with env.app.app_context():
        assert SupportTicket.query.count() == before


@pytest.mark.parametrize(
    ("path", "field"),
    [("/file-center/upload", "file"), ("/support/new", "attachment"), ("/messages/new", "attachments"),
     ("/portal/posts", "portal_video_file"), ("/file-center/chunk-upload/session/1/chunk/0", "chunk")],
)
def test_logged_in_uploads_above_16_mib_are_read_in_full(env, csrf_on, path, field):
    """The CSRF check parses the whole 17 MiB body, then handles the missing token (redirect), never 413."""
    client = _web(env, "admin")
    csrf_on()
    response = client.post(path, data={field: (io.BytesIO(b"%PDF-1.4" + b"x" * (17 * MIB)), "buyuk.pdf")},
                           content_type="multipart/form-data")
    assert response.status_code not in {413, 500}, response.status_code


def test_logged_in_upload_above_16_mib_reaches_the_view_without_csrf(env):
    client = _web(env, "admin")
    response = client.post("/file-center/upload", data={"file": (io.BytesIO(b"%PDF-1.4" + b"x" * (17 * MIB)), "buyuk.pdf")},
                           content_type="multipart/form-data")
    assert response.status_code not in {413, 500}, response.status_code


def test_logged_in_non_upload_endpoint_refuses_17_mib(env, csrf_on):
    client = _web(env, "plain")
    csrf_on()
    response = client.post("/account/change-password", data={"note": (io.BytesIO(b"x" * (17 * MIB)), "x.bin")},
                           content_type="multipart/form-data")
    assert response.status_code == 413


def test_logged_in_json_over_1_mib_is_refused(env):
    client = _web(env, "admin")
    assert client.post("/ai-agent/api/ask", json={"question": "a" * (2 * MIB)}).status_code == 413
    assert client.post("/ai-agent/api/ask", json={"question": "merhaba"}).status_code != 413


def test_multipart_text_fields_are_capped_in_total(env, csrf_on):
    client = _web(env, "admin")
    csrf_on()
    over = {f"f{i}": "a" * 490_000 for i in range(5)}  # 2.45 MB of text, each field under 500 KB
    assert client.post("/support/new", data=over, content_type="multipart/form-data").status_code == 413
    under = {f"f{i}": "a" * 490_000 for i in range(4)}  # 1.96 MB: parsed, then the CSRF token is missing
    assert client.post("/support/new", data=under, content_type="multipart/form-data").status_code not in {413, 500}


# --------------------------------------------------------------------------- parser unit tests


def _bare_app() -> Flask:
    app = Flask(__name__)
    app.request_class = BYS360Request
    app.config.update(MAX_CONTENT_LENGTH=16 * MIB, ANONYMOUS_MAX_CONTENT_LENGTH=16 * MIB, MAX_FORM_TEXT_BYTES=1 * MIB)
    return app


def test_text_total_counts_only_text_parts():
    app = _bare_app()
    data = {"a": "x" * 400_000, "b": "y" * 400_000, "file": (io.BytesIO(b"z" * (3 * MIB)), "f.bin")}
    with app.test_request_context("/", method="POST", data=data, content_type="multipart/form-data"):
        assert len(request.form["a"]) == 400_000 and len(request.files["file"].read()) == 3 * MIB
    data = {f"f{i}": "x" * 400_000 for i in range(3)}  # 1.2 MB > 1 MiB
    with app.test_request_context("/", method="POST", data=data, content_type="multipart/form-data"), \
            pytest.raises(RequestEntityTooLarge):
        request.form  # noqa: B018 - parsing is the point


def test_single_field_and_part_count_limits_still_apply():
    app = _bare_app()
    with app.test_request_context("/", method="POST", data={"a": "x" * 500_001}, content_type="multipart/form-data"), \
            pytest.raises(RequestEntityTooLarge):
        request.form  # noqa: B018
    app.config["MAX_FORM_PARTS"] = 3
    with app.test_request_context("/", method="POST", data={f"f{i}": "x" for i in range(4)}, content_type="multipart/form-data"), \
            pytest.raises(RequestEntityTooLarge):
        request.form  # noqa: B018


def test_multipart_values_parse_like_werkzeug():
    app = _bare_app()
    data = {"ad": "Ayşe", "liste": ["1", "2"], "bos": "", "dosya": (io.BytesIO(b"abc"), "a.txt")}
    with app.test_request_context("/", method="POST", data=data, content_type="multipart/form-data"):
        assert request.form["ad"] == "Ayşe" and request.form.getlist("liste") == ["1", "2"] and request.form["bos"] == ""
        assert request.files["dosya"].filename == "a.txt" and request.files["dosya"].read() == b"abc"


def test_small_bodies_may_keep_file_parts_in_memory_large_ones_may_not():
    app = _bare_app()
    with app.test_request_context("/", method="POST", data={"f": (io.BytesIO(b"abc"), "a.txt")},
                                  content_type="multipart/form-data"):
        assert request._get_file_stream(1000, "text/plain").__class__.__name__ == "SpooledTemporaryFile"
        assert request._get_file_stream(2 * MIB, "text/plain").__class__.__name__ != "SpooledTemporaryFile"
        assert request._get_file_stream(None, "text/plain").__class__.__name__ != "SpooledTemporaryFile"


def test_module_defaults_without_app_config():
    assert limits.DEFAULT_LIMITS == EXPECTED
