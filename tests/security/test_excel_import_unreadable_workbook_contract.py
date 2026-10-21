"""Corrupt or hostile .xlsx uploads on /admin/users/import and /personnel/excel-upload.

Every case goes through the real route with a web session from ``POST /login`` on a temporary
SQLite database (R05 fixture). A workbook that openpyxl/Pillow cannot parse must end with the
fixed Turkish validation message and the route's normal validation response (admin import:
200 page render, personnel upload: 302 back to the upload page), never a 500. No user, unit or
audit row (which would include the http_5xx security event) may be written, and the log may
carry only a fixed code and the exception class name: no parser text, archive member name or
traceback.

Before this change Pillow 13.0.0 made openpyxl raise ValueError for a PNG with a truncated
cHRM/gAMA/tRNS chunk: /admin/users/import answered 500, /personnel/excel-upload logged the raw
parser message with a traceback.
"""
from __future__ import annotations

import io
import logging
import resource
import struct
import time
import zipfile
import zlib

import pytest

from tests.security import test_r05_account_change_authority_contract as _r05
from tests.security.test_r05_account_change_authority_contract import _web, _xlsx, _xlsx_row

env = _r05.env  # seeded accounts on a temporary SQLite database

IMPORT_PATHS = ("/admin/users/import", "/personnel/excel-upload")
LEAK_MARKERS = (
    "Truncated",
    "There is no item named",
    "Unknown relationship",
    "unclosed token",
    "Image size",
    "exceeds limit",
    "Unable to read workbook",
    "is encrypted",
    "Traceback",
)


@pytest.fixture(autouse=True)
def _logging_enabled():
    previous = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    yield
    logging.disable(previous)


# ------------------------------------------------------------------ synthetic workbooks


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png(extra: bytes = b"", color_type: int = 2) -> bytes:
    channels = {0: 1, 2: 3}[color_type]
    raw = b"".join(b"\x00" + b"\x80" * (2 * channels) for _ in range(2))
    header = struct.pack(">IIBBBBB", 2, 2, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + extra
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


def _jpeg() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _gif_bomb() -> bytes:
    """A ~40-byte GIF declaring 65535 x 65535 pixels (2 x Pillow's bomb limit)."""
    w = h = 65535
    return (b"GIF89a" + struct.pack("<HH", w, h) + bytes([0x80, 0, 0]) + b"\x00\x00\x00\xff\xff\xff"
            + b"\x2c" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00" + b"\x02\x02\x4c\x01\x00" + b"\x3b")


def _tiff_bomb() -> bytes:
    """A tiny little-endian TIFF header declaring 60000 x 60000 RGB pixels."""
    entries = [
        (256, 4, 1, 60000), (257, 4, 1, 60000), (258, 3, 1, 8), (259, 3, 1, 1), (262, 3, 1, 1),
        (273, 4, 1, 8), (277, 3, 1, 1), (278, 4, 1, 60000), (279, 4, 1, 1),
    ]
    ifd = struct.pack("<H", len(entries)) + b"".join(struct.pack("<HHII", *e) for e in entries) + b"\x00" * 4
    return b"II*\x00" + struct.pack("<I", 9) + b"\x00" + ifd


def _rewrite(raw: bytes, replace: dict[str, bytes] | None = None, drop: tuple[str, ...] = ()) -> bytes:
    replace = replace or {}
    source = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename in drop:
                continue
            payload = source.read(item.filename)
            for match, new in replace.items():
                if item.filename == match or (match.endswith("/") and item.filename.startswith(match)):
                    payload = new
            target.writestr(item, payload)
    return out.getvalue()


def _workbook_with_images(sicil: str, images: tuple[bytes, ...]) -> bytes:
    from openpyxl import load_workbook
    from openpyxl.drawing.image import Image as XImage

    workbook = load_workbook(_xlsx([_xlsx_row(sicil, "personel")]))
    for column, image in zip(("J2", "M2"), images, strict=False):
        workbook.active.add_image(XImage(io.BytesIO(image)), column)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _hostile(case: str) -> bytes:
    base = _workbook_with_images("R5BAD01", (_png(),))
    if case == "malformed_sheet_xml":
        return _rewrite(base, {"xl/worksheets/sheet1.xml": b"<worksheet><sheetData><row><c r='A1'"})
    if case == "missing_workbook_xml":
        return _rewrite(base, drop=("xl/workbook.xml",))
    if case == "no_worksheet":
        workbook_xml = zipfile.ZipFile(io.BytesIO(base)).read("xl/workbook.xml")
        return _rewrite(base, {"xl/workbook.xml": workbook_xml.replace(b'activeTab="0"', b'activeTab="7"')})
    if case == "gif_bomb":
        return _rewrite(base, {"xl/media/": _gif_bomb()})
    if case == "tiff_bomb":
        return _rewrite(base, {"xl/media/": _tiff_bomb()})
    if case == "png_truncated_cHRM":
        return _rewrite(base, {"xl/media/": _png(_chunk(b"cHRM", b""))})
    if case == "png_truncated_gAMA":
        return _rewrite(base, {"xl/media/": _png(_chunk(b"gAMA", b"\x00\x01"))})
    if case == "png_truncated_tRNS":
        return _rewrite(base, {"xl/media/": _png(_chunk(b"tRNS", b""), color_type=0)})
    raise AssertionError(case)


def _counts(env):
    from sqlalchemy import func

    from app.extensions import db
    from app.models import AuditLog, OrganizationUnit, User

    with env.app.app_context():
        return (
            db.session.query(func.count(User.id)).scalar(),
            db.session.query(func.count(OrganizationUnit.id)).scalar(),
            db.session.query(func.count(AuditLog.id)).scalar(),
        )


def _post(client, path, payload: bytes):
    return client.post(
        path,
        data={"excel_file": (io.BytesIO(payload), "personel.xlsx"), "activate_new_users": "on"},
        content_type="multipart/form-data",
    )


def _assert_rejected(env, client, path, response, before, caplog):
    from markupsafe import escape

    from app.services.excel_workbook_reader import EXCEL_WORKBOOK_UNREADABLE_MESSAGE

    body = response.get_data(as_text=True)
    if path == "/admin/users/import":
        assert response.status_code == 200
        assert str(escape(EXCEL_WORKBOOK_UNREADABLE_MESSAGE)) in body
    else:
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/personnel/excel-upload")
        with client.session_transaction() as session:
            assert ("danger", EXCEL_WORKBOOK_UNREADABLE_MESSAGE) in session.get("_flashes", [])
    assert _counts(env) == before  # no user, unit, audit or 5xx security-event row
    assert "EXCEL_WORKBOOK_" in caplog.text
    assert not any(record.exc_info for record in caplog.records if record.name.startswith("app"))
    for marker in LEAK_MARKERS:
        assert marker not in caplog.text
        assert marker not in body


# ------------------------------------------------------------------ tests


@pytest.mark.parametrize(
    "case",
    ["malformed_sheet_xml", "missing_workbook_xml", "no_worksheet",
     "png_truncated_cHRM", "png_truncated_gAMA", "png_truncated_tRNS"],
)
@pytest.mark.parametrize("path", IMPORT_PATHS)
def test_unreadable_workbook_is_rejected_without_writes_or_leaks(env, caplog, path, case):
    client = _web(env, "admin")
    before = _counts(env)
    caplog.set_level(logging.DEBUG)
    response = _post(client, path, _hostile(case))
    _assert_rejected(env, client, path, response, before, caplog)


def test_truncated_png_chunks_are_what_pillow_13_rejects():
    """Premise of the three png_truncated_* cases: the pinned Pillow refuses these images."""
    from PIL import Image

    for extra, color_type in ((_chunk(b"cHRM", b""), 2), (_chunk(b"gAMA", b"\x00\x01"), 2), (_chunk(b"tRNS", b""), 0)):
        with pytest.raises(ValueError, match="Truncated"):
            Image.open(io.BytesIO(_png(extra, color_type)))


@pytest.mark.parametrize("case", ["gif_bomb", "tiff_bomb"])
@pytest.mark.parametrize("path", IMPORT_PATHS)
def test_decompression_bomb_image_is_rejected_cheaply(env, caplog, path, case):
    """The header alone declares billions of pixels; the check must not allocate them."""
    client = _web(env, "admin")
    before = _counts(env)
    caplog.set_level(logging.DEBUG)
    payload = _hostile(case)
    assert len(payload) < 20_000
    peak_before_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.monotonic()
    response = _post(client, path, payload)
    elapsed = time.monotonic() - started
    peak_growth_mib = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - peak_before_kib) / 1024
    _assert_rejected(env, client, path, response, before, caplog)
    assert elapsed < 10, elapsed
    assert peak_growth_mib < 256, peak_growth_mib  # decoding would need gigabytes


def test_admin_import_rejects_a_non_zip_upload_with_the_validation_message(env, caplog):
    """/admin/users/import has no pre-upload validator; a plain non-Excel file used to answer 500."""
    client = _web(env, "admin")
    before = _counts(env)
    caplog.set_level(logging.DEBUG)
    response = _post(client, "/admin/users/import", b"bu bir excel dosyasi degil\n" * 20)
    _assert_rejected(env, client, "/admin/users/import", response, before, caplog)


@pytest.mark.parametrize("path", IMPORT_PATHS)
def test_valid_workbook_with_png_and_jpeg_still_imports(env, path):
    from app.models import User

    sicil = "R5IMG01" if path == "/admin/users/import" else "R5IMG02"
    client = _web(env, "admin")
    users_before = _counts(env)[0]
    response = _post(client, path, _workbook_with_images(sicil, (_png(), _jpeg())))
    assert response.status_code == 302
    with env.app.app_context():
        user = User.query.filter_by(sicil_no=sicil).first()
        assert user is not None
        assert user.email == f"{sicil.lower()}@example.gov.tr"
    assert _counts(env)[0] == users_before + 1
