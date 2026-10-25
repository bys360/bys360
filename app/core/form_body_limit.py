"""Request body limits, chosen per request before the body is read (issue #105).

Every POST body is parsed before authentication: the CSRF check reads ``request.form`` and the
mobile auth endpoints read JSON without a session. With a single global ``MAX_CONTENT_LENGTH`` of
150 MB (needed only by uploads), an anonymous client could make the app hold ~118 MB of
multipart text fields on /login, or ~400 MB for a 100 MB JSON body on /api/mobile/auth/login.

``BYS360Request.max_content_length`` now picks the limit from the endpoint, the session and the
body type, so Werkzeug refuses an oversized body with 413 before reading it:

* login, password reset and mobile login/refresh: ``AUTH_ENDPOINT_MAX_CONTENT_LENGTH`` (64 KiB);
* any request without a logged-in web session (mobile Bearer clients included):
  ``ANONYMOUS_MAX_CONTENT_LENGTH`` (1 MiB), except the guest upload link, a public upload;
* a logged-in user on an endpoint that accepts files (``UPLOAD_ENDPOINTS``):
  ``UPLOAD_MAX_CONTENT_LENGTH`` (150 MB, the former global value);
* every other request: ``MAX_CONTENT_LENGTH`` (16 MiB);
* a JSON body never exceeds ``JSON_MAX_CONTENT_LENGTH`` (1 MiB).

The form parser keeps three memory limits Werkzeug does not have: an urlencoded body larger than
``MAX_FORM_MEMORY_SIZE`` is refused before it is read (Werkzeug 3.1.9 dropped that rule); the
text fields of a multipart body may total at most ``MAX_FORM_TEXT_BYTES`` (2 MiB); and file parts
of a body larger than that budget go straight to temporary files on disk. Werkzeug keeps every
file part under 500 KB in memory, so 290 parts of 499 KB held ~150 MB without this rule.

A view may still set ``request.max_content_length`` itself; that value wins.
"""
from __future__ import annotations

import io
import tempfile
import typing as t

from flask import Request, current_app, has_app_context, has_request_context, session
from werkzeug.datastructures import FileStorage, MultiDict
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.formparser import FormDataParser, MultiPartParser
from werkzeug.sansio.multipart import Data, Epilogue, Field, File, MultipartDecoder, NeedData

KIB = 1024
MIB = 1024 * KIB

# Defaults used when the app config does not set a key (config.py sets all of them).
DEFAULT_LIMITS: dict[str, int] = {
    "MAX_CONTENT_LENGTH": 16 * MIB,
    "UPLOAD_MAX_CONTENT_LENGTH": 150 * MIB,
    "ANONYMOUS_MAX_CONTENT_LENGTH": 1 * MIB,
    "AUTH_ENDPOINT_MAX_CONTENT_LENGTH": 64 * KIB,
    "JSON_MAX_CONTENT_LENGTH": 1 * MIB,
    "MAX_FORM_TEXT_BYTES": 2 * MIB,
}

# Reached before anyone is authenticated; their bodies are a few fields or a small JSON object.
AUTH_ENDPOINTS: frozenset[str] = frozenset({
    "main.login",
    "main.forgot_password",
    "mobile_api.mobile_login",
    "mobile_api.mobile_refresh",
})

# Public by design: a guest posts a file to a file-center request link (token checked by the view).
PUBLIC_UPLOAD_ENDPOINTS: frozenset[str] = frozenset({"main.file_center_guest_upload"})

# Every registered view that reads request.files, directly or through its helper (messages,
# announcements, profile photos, Excel imports, file center, HR documents, portal, support,
# feedback, settings template import). Kept in step with the code by
# tests/security/test_request_body_limits_contract.py.
UPLOAD_ENDPOINTS: frozenset[str] = frozenset({
    "main.account_change_photo",
    "main.admin_analysis_center_excel_preview",
    "main.admin_user_change_photo",
    "main.admin_user_create",
    "main.admin_user_edit",
    "main.admin_user_import",
    "main.announcement_popup_edit",
    "main.announcement_popup_new",
    "main.bys360_feedback_new",
    "main.corporate_information_center_celebration_excel_upload",
    "main.file_center_chunk_upload_part",
    "main.file_center_upload",
    "main.hr_personnel_document_bulk_upload",
    "main.hr_personnel_document_save",
    "main.hr_self_service_request_save",
    "main.messages_new",
    "main.messages_send",
    "main.performance_archive_import",
    "main.performance_history_import",
    "main.personnel_add",
    "main.personnel_edit",
    "main.personnel_excel_upload",
    "main.portal_post_create",
    "main.settings_page",
    "main.support_comment",
    "main.support_new",
}) | PUBLIC_UPLOAD_ENDPOINTS


def configured_limit(config: t.Mapping[str, t.Any], key: str) -> int:
    value = config.get(key)
    return int(value) if value else DEFAULT_LIMITS[key]


def body_limit_for(endpoint: str | None, *, authenticated: bool, is_json: bool,
                   config: t.Mapping[str, t.Any]) -> int:
    """The largest body (bytes) accepted for one request; see the module docstring."""
    if endpoint in AUTH_ENDPOINTS:
        limit = configured_limit(config, "AUTH_ENDPOINT_MAX_CONTENT_LENGTH")
    elif endpoint in PUBLIC_UPLOAD_ENDPOINTS or (authenticated and endpoint in UPLOAD_ENDPOINTS):
        limit = configured_limit(config, "UPLOAD_MAX_CONTENT_LENGTH")
    elif not authenticated:
        limit = configured_limit(config, "ANONYMOUS_MAX_CONTENT_LENGTH")
    else:
        limit = configured_limit(config, "MAX_CONTENT_LENGTH")
    if is_json:
        limit = min(limit, configured_limit(config, "JSON_MAX_CONTENT_LENGTH"))
    return limit


def _has_web_login() -> bool:
    # Flask-Login keeps the user id in the signed session cookie; reading it touches neither the
    # database nor the request body (current_user could, through a user loader).
    return bool(session.get("_user_id"))


class TextBoundedMultiPartParser(MultiPartParser):
    """Werkzeug 3.1.9's MultiPartParser.parse plus a cap on the total size of the text fields.

    Werkzeug limits each text field (max_form_memory_size) and the number of parts, so the text
    kept in memory could still reach parts x field size (250 x 490 KB = 118 MB on /login).
    """

    def __init__(self, *args: t.Any, max_form_text_bytes: int | None = None, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_form_text_bytes = max_form_text_bytes

    def parse(
        self, stream: t.IO[bytes], boundary: bytes, content_length: int | None
    ) -> tuple[MultiDict[str, str], MultiDict[str, FileStorage]]:
        current_part: Field | File
        field_size: int | None = None
        text_total = 0
        container: t.IO[bytes] | list[bytes]
        _write: t.Callable[[bytes], t.Any]

        parser = MultipartDecoder(boundary, max_form_memory_size=self.max_form_memory_size,
                                  max_parts=self.max_form_parts)
        fields = []
        files = []

        for data in _chunk_iter(stream.read, self.buffer_size):
            parser.receive_data(data)
            event = parser.next_event()
            while not isinstance(event, (Epilogue, NeedData)):
                if isinstance(event, Field):
                    current_part = event
                    field_size = 0
                    container = []
                    _write = container.append
                elif isinstance(event, File):
                    current_part = event
                    field_size = None
                    container = self.start_file_streaming(event, content_length)
                    _write = container.write
                elif isinstance(event, Data):
                    if field_size is not None:
                        field_size += len(event.data)
                        text_total += len(event.data)
                        if self.max_form_memory_size is not None and field_size > self.max_form_memory_size:
                            raise RequestEntityTooLarge()
                        if self.max_form_text_bytes is not None and text_total > self.max_form_text_bytes:
                            raise RequestEntityTooLarge()
                    _write(event.data)
                    if not event.more_data:
                        if isinstance(current_part, Field):
                            value = b"".join(t.cast(list[bytes], container)).decode(
                                self.get_part_charset(current_part.headers), "replace"
                            )
                            fields.append((current_part.name, value))
                        else:
                            file_container = t.cast(t.IO[bytes], container)
                            file_container.seek(0)
                            files.append((current_part.name, FileStorage(
                                file_container, current_part.filename, current_part.name,
                                headers=current_part.headers,
                            )))
                event = parser.next_event()

        return self.cls(fields), self.cls(files)


def _chunk_iter(read: t.Callable[[int], bytes], size: int) -> t.Iterator[bytes | None]:
    while True:
        data = read(size)
        if not data:
            break
        yield data
    yield None


class BoundedFormDataParser(FormDataParser):
    """Form parser with an urlencoded size limit and a multipart text-total limit."""

    max_form_text_bytes: int | None = None

    def _parse_urlencoded(
        self,
        stream: t.IO[bytes],
        mimetype: str,
        content_length: int | None,
        options: dict[str, str],
    ) -> t.Any:
        # Werkzeug 3.1.9 reads an urlencoded body whole and no longer applies max_form_memory_size.
        limit = self.max_form_memory_size
        if limit is not None:
            if content_length is not None:
                if content_length > limit:
                    raise RequestEntityTooLarge()
            else:
                body = stream.read(limit + 1)
                if len(body) > limit:
                    raise RequestEntityTooLarge()
                stream = io.BytesIO(body)
        return super()._parse_urlencoded(stream, mimetype, content_length, options)

    def _parse_multipart(
        self,
        stream: t.IO[bytes],
        mimetype: str,
        content_length: int | None,
        options: dict[str, str],
    ) -> t.Any:
        parser = TextBoundedMultiPartParser(
            stream_factory=self.stream_factory,
            max_form_memory_size=self.max_form_memory_size,
            max_form_parts=self.max_form_parts,
            cls=self.cls,
            max_form_text_bytes=self.max_form_text_bytes,
        )
        boundary = options.get("boundary", "").encode("ascii")
        if not boundary:
            raise ValueError("Missing boundary")
        form, files = parser.parse(stream, boundary, content_length)
        return stream, form, files


# Former name (PR #102); same parser.
BoundedUrlencodedFormDataParser = BoundedFormDataParser


class BYS360Request(Request):
    form_data_parser_class = BoundedFormDataParser

    @property
    def max_content_length(self) -> int | None:
        if self._max_content_length is not None:
            return self._max_content_length
        if not has_request_context():
            return DEFAULT_LIMITS["MAX_CONTENT_LENGTH"]
        return body_limit_for(self.endpoint, authenticated=_has_web_login(), is_json=self.is_json,
                              config=current_app.config)

    @max_content_length.setter
    def max_content_length(self, value: int | None) -> None:
        self._max_content_length = value

    def make_form_data_parser(self) -> FormDataParser:
        parser = super().make_form_data_parser()
        if isinstance(parser, BoundedFormDataParser):
            parser.max_form_text_bytes = _form_text_budget()
        return parser

    def _get_file_stream(
        self,
        total_content_length: int | None,
        content_type: str | None,
        filename: str | None = None,
        content_length: int | None = None,
    ) -> t.IO[bytes]:
        # Small bodies may keep file parts in memory (at most the text budget in total); larger or
        # unsized bodies write every file part to disk, however small the part.
        if total_content_length is None or total_content_length > _form_text_budget():
            return t.cast(t.IO[bytes], tempfile.TemporaryFile("rb+"))
        return super()._get_file_stream(total_content_length, content_type, filename, content_length)


def _form_text_budget() -> int:
    if has_app_context():
        return configured_limit(current_app.config, "MAX_FORM_TEXT_BYTES")
    return DEFAULT_LIMITS["MAX_FORM_TEXT_BYTES"]


__all__ = [
    "AUTH_ENDPOINTS",
    "BYS360Request",
    "BoundedFormDataParser",
    "BoundedUrlencodedFormDataParser",
    "DEFAULT_LIMITS",
    "PUBLIC_UPLOAD_ENDPOINTS",
    "TextBoundedMultiPartParser",
    "UPLOAD_ENDPOINTS",
    "body_limit_for",
    "configured_limit",
]
