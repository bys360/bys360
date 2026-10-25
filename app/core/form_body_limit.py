"""urlencoded form bodies stay limited to MAX_FORM_MEMORY_SIZE.

Werkzeug 3.1.9 stopped applying ``max_form_memory_size`` to
``application/x-www-form-urlencoded`` bodies (its parser reads the whole body at once), leaving
only ``MAX_CONTENT_LENGTH``. BYS360 raises that to 150 MB for publication and e-book uploads, so
every POST -- /login included, before authentication and before the CSRF check reads the form --
would parse up to 150 MB in memory. This parser restores the Werkzeug 3.1.8 rule: a declared
body larger than ``MAX_FORM_MEMORY_SIZE`` (Flask default 500 000 bytes) is refused with 413
before it is read. A body without Content-Length is read only up to the same limit.
Multipart uploads are unchanged.
"""
from __future__ import annotations

import io
import typing as t

from flask import Request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.formparser import FormDataParser


class BoundedUrlencodedFormDataParser(FormDataParser):
    def _parse_urlencoded(
        self,
        stream: t.IO[bytes],
        mimetype: str,
        content_length: int | None,
        options: dict[str, str],
    ) -> t.Any:
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


class BYS360Request(Request):
    form_data_parser_class = BoundedUrlencodedFormDataParser


__all__ = ["BYS360Request", "BoundedUrlencodedFormDataParser"]
