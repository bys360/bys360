"""Bounded reading of uploaded .xlsx files for the Excel import screens (issue #104).

openpyxl sizes a worksheet from the farthest cell the file mentions, including an empty cell
that only carries a style, and ``ws.iter_rows()`` then builds every cell of that rectangle. A
5 KB upload with one cell at XFD1048576, or just a bold font on H1048576, therefore made the
import routes allocate gigabytes and run for minutes before any validation. openpyxl also
builds whole XML trees for the styles, the workbook part and the worksheet's trailing blocks
(merged cells, hyperlinks, validations), so a small compressed file could inflate those too.

``read_import_rows`` bounds every step:

1. the upload size, the number of archive members, their declared uncompressed size and the
   compression ratio (read from the zip directory; ``zipfile`` never inflates a member past its
   declared size);
2. while openpyxl loads the workbook it may not read any part larger than ``MAX_PART_BYTES``
   or any part with a DOCTYPE; the only exception is the shared string table named by the
   package manifest, which is first counted with a streaming parse;
3. the active worksheet is scanned with a streaming parse in constant memory: rows, cells and
   other elements are counted, and the farthest row and column that hold a value give the real
   extent. Empty styled cells and the ``<dimension>`` element do not extend it, so neither a
   forged dimension nor a formatted column inflates the read;
4. only then openpyxl streams the sheet (read-only mode), bounded to that extent.

Anything over a limit, and any structural damage, ends in ``ExcelImportRejected`` with a fixed
Turkish message, before any database work. Logs carry a code and the exception class only.
"""
from __future__ import annotations

import logging
import zipfile
import zlib
from dataclasses import dataclass
from typing import IO, Any
from xml.etree.ElementTree import Element, iterparse

from openpyxl.reader.excel import ExcelReader
from openpyxl.utils.cell import coordinate_to_tuple
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.xml.constants import SHARED_STRINGS
from PIL import Image
from PIL.Image import DecompressionBombError

logger = logging.getLogger(__name__)

# Import templates are one header row plus one row per person or result, in well under 64
# columns (the personnel template has 13). The limits leave a wide margin over real files while
# bounding the worst case to a grid of MAX_SHEET_ROWS x MAX_COLUMNS values.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 420
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MEMBER_RATIO = 100  # checked for members that inflate past RATIO_CHECK_MIN_BYTES
RATIO_CHECK_MIN_BYTES = 1024 * 1024
MAX_PART_BYTES = 4 * 1024 * 1024  # any part openpyxl parses whole while loading (styles, workbook, rels, ...)
MAX_DATA_ROWS = 20_000
MAX_SHEET_ROWS = MAX_DATA_ROWS + 1  # header row
MAX_COLUMNS = 64
MAX_SHEET_CELLS = MAX_SHEET_ROWS * MAX_COLUMNS  # every <c>, styled empty cells included
MAX_SHEET_ROW_ELEMENTS = 1_048_576  # Excel's row limit
MAX_ROW_CELLS = 16_384  # Excel's column limit; openpyxl builds a whole <row> before reading it
MAX_CELL_ELEMENTS = 1_000  # elements inside one <c> (value, formula, rich inline string)
MAX_SHEET_EXTRA_ELEMENTS = 100_000  # outside <sheetData>: merged cells, hyperlinks, validations ...
MAX_SHARED_STRINGS_BYTES = 16 * 1024 * 1024
MAX_SHARED_STRINGS = MAX_SHEET_CELLS
MAX_SHARED_STRING_EXTRA_ELEMENTS = 1_000  # elements outside <si>
EXCEL_MAX_ROW = 1_048_576
EXCEL_MAX_COLUMN = 16_384
_PROBE_CHUNK_BYTES = 1024 * 1024
_DOCTYPE_MARKERS = tuple("<!DOCTYPE".encode(codec) for codec in ("utf-8", "utf-16-le", "utf-16-be"))

_NO_WRITE = " Hiçbir kayıt veritabanına yazılmadı."
MESSAGES = {
    "EXCEL_UPLOAD_TOO_LARGE": f"Excel dosyası çok büyük: en fazla {MAX_UPLOAD_BYTES // (1024 * 1024)} MB yüklenebilir.{_NO_WRITE}",
    "EXCEL_ARCHIVE_LIMIT": "Excel dosyasının iç yapısı güvenli sınırları aşıyor (parça sayısı, açılmış boyut, "
                           f"sıkıştırma oranı veya biçim tablosu).{_NO_WRITE}",
    "EXCEL_SHEET_STRUCTURE_LIMIT": "Excel sayfasında güvenli sınırları aşan sayıda satır, hücre veya biçim öğesi var. "
                                   f"Verileri yeni bir şablona yalnız değer olarak kopyalayıp yeniden yükleyin.{_NO_WRITE}",
    "EXCEL_TOO_MANY_ROWS": f"Excel sayfasında veri {MAX_DATA_ROWS:,} satır sınırını aşıyor. Dosyayı bölerek "
                           f"yükleyin.{_NO_WRITE}".replace(",", "."),
    "EXCEL_TOO_MANY_COLUMNS": f"Excel sayfasında veri {MAX_COLUMNS} sütun sınırını aşıyor. Şablondaki sütunları "
                              f"kullanın.{_NO_WRITE}",
    "EXCEL_UNREADABLE": "Excel dosyası okunamadı: dosya bozuk, .xlsx biçiminde değil ya da güvenli boyut sınırını "
                        f"aşan bir resim içeriyor.{_NO_WRITE}",
}

# What zipfile, expat and openpyxl raise for a damaged or hostile workbook (openpyxl 3.1.5,
# Pillow 13): ParseError is a SyntaxError; LookupError covers missing parts and out-of-range
# string/style indexes; RuntimeError covers zip encryption and unsupported compression;
# ArithmeticError covers OverflowError from crafted numbers. MemoryError is deliberately absent.
_READ_ERRORS: tuple[type[BaseException], ...] = (
    zipfile.BadZipFile, zlib.error, InvalidFileException, DecompressionBombError, SyntaxError,
    LookupError, AttributeError, TypeError, ValueError, RuntimeError, ArithmeticError, EOFError, OSError,
)


class ExcelImportRejected(Exception):
    """Fixed user message plus a code; never parser text or file content.

    Not a ValueError on purpose: openpyxl re-wraps ValueErrors raised while it loads a workbook.
    """

    def __init__(self, code: str) -> None:
        super().__init__(MESSAGES[code])
        self.code = code
        self.user_message = MESSAGES[code]


@dataclass(frozen=True)
class SheetExtent:
    rows: int
    columns: int
    max_style: int = -1  # largest style index used by a cell, row or column


def _reject(code: str, kind: type[Any] | None = None) -> ExcelImportRejected:
    if kind is None:
        logger.warning("BYS360 Excel içe aktarma reddedildi | code=%s", code)
    else:
        logger.warning("BYS360 Excel içe aktarma reddedildi | code=%s | exc_type=%s.%s",
                       code, kind.__module__, kind.__qualname__)
    return ExcelImportRejected(code)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _probe(archive: zipfile.ZipFile, name: str) -> None:
    """Refuse a part that contains a DOCTYPE anywhere (UTF-8 or UTF-16, the encodings expat reads).

    OOXML parts never carry one; refusing it keeps entity tricks away from every parser, including
    openpyxl's own, which uses the standard library parser in production (no defusedxml).
    """
    overlap = max(len(marker) for marker in _DOCTYPE_MARKERS) - 1
    tail = b""
    with archive.open(name) as source:
        while chunk := source.read(_PROBE_CHUNK_BYTES):
            window = (tail + chunk).upper()
            if any(marker in window for marker in _DOCTYPE_MARKERS):
                raise _reject("EXCEL_UNREADABLE")
            tail = window[-overlap:]


def check_archive(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    total = sum(info.file_size for info in members)
    too_compressed = any(
        info.file_size > RATIO_CHECK_MIN_BYTES and info.file_size > MAX_MEMBER_RATIO * max(info.compress_size, 1)
        for info in members
    )
    if len(members) > MAX_ARCHIVE_MEMBERS or total > MAX_UNCOMPRESSED_BYTES or too_compressed:
        raise _reject("EXCEL_ARCHIVE_LIMIT")


class _BoundedSource:
    """A part stream that refuses to yield more than ``limit`` bytes."""

    def __init__(self, source: IO[bytes], limit: int) -> None:
        self._source = source
        self._left = limit

    def read(self, size: int | None = -1) -> bytes:
        want = self._left + 1 if size is None or size < 0 else min(size, self._left + 1)
        data = self._source.read(want)
        self._left -= len(data)
        if self._left < 0:
            raise _reject("EXCEL_ARCHIVE_LIMIT")
        return data

    def readable(self) -> bool:
        return True

    def close(self) -> None:
        self._source.close()

    def __enter__(self) -> _BoundedSource:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class _LoadGuard:
    """The archive as openpyxl sees it while loading the workbook.

    Every part openpyxl reads or opens is refused if it carries a DOCTYPE, and yields at most
    MAX_PART_BYTES (openpyxl also opens each worksheet here, only to find ``<dimension>``).
    The shared string table is exempt once count_shared_strings has bounded it.
    """

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self._archive = archive
        self.counted: set[str] = set()

    def read(self, name: str) -> bytes:
        if self._archive.getinfo(name).file_size > MAX_PART_BYTES and name not in self.counted:
            raise _reject("EXCEL_ARCHIVE_LIMIT")
        _probe(self._archive, name)
        return self._archive.read(name)

    def open(self, name: str, mode: str = "r") -> Any:
        if mode != "r":
            raise _reject("EXCEL_UNREADABLE")
        _probe(self._archive, name)
        source = self._archive.open(name)
        return source if name in self.counted else _BoundedSource(source, MAX_PART_BYTES)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._archive, attr)


def count_shared_strings(archive: zipfile.ZipFile, name: str) -> int:
    """Count ``<si>`` items in constant memory; refuses an oversized or padded table.

    openpyxl keeps every element outside an ``<si>`` until the end of the part, so those are
    capped tightly; elements inside one ``<si>`` (rich text runs) are capped like a cell's.
    """
    if archive.getinfo(name).file_size > MAX_SHARED_STRINGS_BYTES:
        raise _reject("EXCEL_ARCHIVE_LIMIT")
    _probe(archive, name)
    strings = extras = item_elements = 0
    root: Element | None = None
    item: Element | None = None
    with archive.open(name) as source:
        for event, element in iterparse(source, events=("start", "end")):
            if event == "start":
                if root is None:
                    root = element
                elif item is not None:
                    item_elements += 1
                    if item_elements > MAX_CELL_ELEMENTS:
                        raise _reject("EXCEL_ARCHIVE_LIMIT")
                elif _local(element.tag) == "si":
                    strings += 1
                    if strings > MAX_SHARED_STRINGS:
                        raise _reject("EXCEL_ARCHIVE_LIMIT")
                    item = element
                    item_elements = 0
                else:
                    extras += 1
                    if extras > MAX_SHARED_STRING_EXTRA_ELEMENTS:
                        raise _reject("EXCEL_ARCHIVE_LIMIT")
            elif item is not None and element is item and root is not None:
                item = None
                root.clear()  # drop finished items
    return strings


def check_pictures(archive: zipfile.ZipFile) -> None:
    """Open every embedded picture header with Pillow, as openpyxl's full load did.

    Read-only mode never touches pictures, but a damaged or hostile one still marks a damaged
    file: a picture declaring more pixels than Pillow allows raises DecompressionBombError and a
    zero-sized EMF raises ZeroDivisionError here, before any pixel is decoded. A format Pillow
    cannot identify (OSError) is tolerated, as openpyxl only drops such pictures.
    """
    for name in archive.namelist():
        if not name.startswith("xl/media/"):
            continue
        with archive.open(name) as source:
            try:
                Image.open(source).close()
            except OSError:
                continue


def _row_number(value: str | None, previous: int) -> int:
    """Row index as openpyxl's WorkSheetParser.parse_row computes it."""
    if value is None:
        return previous + 1
    try:
        return int(value)
    except ValueError:
        number = float(value)
        if not number.is_integer():
            raise
        return int(number)


def scan_sheet_extent(source: IO[bytes]) -> SheetExtent:
    """Farthest row/column holding a value, as openpyxl (data_only) reads it; raises past the limits.

    Rows are numbered like openpyxl's parser (``<row r>`` or +1) and columns from ``<c r>`` or +1.
    A cell holds a value when it has non-empty ``<v>`` text, or an ``<is>`` child for inline strings.
    Memory stays constant: every finished element is detached from its parent (a cell keeps its
    children until the cell itself is done).
    """
    max_row = max_col = 0
    max_style = -1
    row_index = col_index = 0
    rows = cells = row_cells = cell_elements = extras = 0
    stack: list[Element] = []
    in_sheet_data = False
    cell: Element | None = None
    for event, element in iterparse(source, events=("start", "end")):
        if event == "start":
            depth = len(stack) + 1
            name = _local(element.tag)
            stack.append(element)
            style = element.get("style") if name == "col" else element.get("s") if name in {"c", "row"} else None
            if style:
                max_style = max(max_style, int(style))
            if depth == 1:
                continue
            if depth == 2 and name == "sheetData":
                in_sheet_data = True
            elif cell is not None:
                cell_elements += 1
                if cell_elements > MAX_CELL_ELEMENTS:
                    raise _reject("EXCEL_SHEET_STRUCTURE_LIMIT")
            elif in_sheet_data and depth == 3 and name == "row":
                rows += 1
                if rows > MAX_SHEET_ROW_ELEMENTS:
                    raise _reject("EXCEL_SHEET_STRUCTURE_LIMIT")
                row_index = _row_number(element.get("r"), row_index)
                col_index = row_cells = 0
                if row_index > EXCEL_MAX_ROW:
                    raise _reject("EXCEL_SHEET_STRUCTURE_LIMIT")
            elif in_sheet_data and depth == 4 and name == "c" and _local(stack[-2].tag) == "row":
                cells += 1
                row_cells += 1
                if cells > MAX_SHEET_CELLS or row_cells > MAX_ROW_CELLS:
                    raise _reject("EXCEL_SHEET_STRUCTURE_LIMIT")
                cell = element
                cell_elements = 0
            else:
                extras += 1  # everything outside cells: merged cells, hyperlinks, validations, strays
                if extras > MAX_SHEET_EXTRA_ELEMENTS:
                    raise _reject("EXCEL_SHEET_STRUCTURE_LIMIT")
            continue

        stack.pop()
        if cell is not None and element is cell:
            cell = None
            ref = element.get("r")
            if ref:
                col_index = coordinate_to_tuple(ref)[1]  # raises on a malformed reference, like openpyxl
            else:
                col_index += 1
            if col_index > EXCEL_MAX_COLUMN:
                raise _reject("EXCEL_SHEET_STRUCTURE_LIMIT")
            if element.get("t") == "inlineStr":
                has_value = any(_local(child.tag) == "is" for child in element)
            else:
                has_value = any(_local(child.tag) == "v" and child.text for child in element)
            if has_value:
                if row_index > MAX_SHEET_ROWS:
                    raise _reject("EXCEL_TOO_MANY_ROWS")
                if col_index > MAX_COLUMNS:
                    raise _reject("EXCEL_TOO_MANY_COLUMNS")
                max_row = max(max_row, row_index)
                max_col = max(max_col, col_index)
        elif len(stack) == 1 and _local(element.tag) == "sheetData":
            in_sheet_data = False
        if stack and stack[-1] is not cell:
            stack[-1].remove(element)
    return SheetExtent(rows=max_row, columns=max_col, max_style=max_style)


def _upload_size(stream: IO[bytes]) -> int:
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    return size


def _read_rows(stream: IO[bytes]) -> list[tuple[Any, ...]]:
    reader = ExcelReader(stream, read_only=True, keep_vba=False, data_only=True, keep_links=False)
    archive: zipfile.ZipFile = reader.archive
    loaded = False
    try:
        check_archive(archive)
        check_pictures(archive)
        guard = _LoadGuard(archive)
        reader.archive = guard
        reader.read_manifest()
        strings = reader.package.find(SHARED_STRINGS)
        if strings is not None:
            name = strings.PartName[1:]
            count_shared_strings(archive, name)
            guard.counted.add(name)
        reader.read()
        workbook = reader.wb
        loaded = True
    finally:
        if not loaded:
            archive.close()
    workbook._archive = archive  # stream the active sheet from the real archive; closed by workbook.close()
    try:
        sheet = workbook.active
        if not isinstance(sheet, ReadOnlyWorksheet):
            raise _reject("EXCEL_UNREADABLE", type(sheet))
        _probe(archive, sheet._worksheet_path)
        with archive.open(sheet._worksheet_path) as source:
            extent = scan_sheet_extent(source)
        if extent.max_style >= len(workbook._cell_styles):
            raise _reject("EXCEL_UNREADABLE")  # the full openpyxl load failed on this with IndexError
        if extent.rows == 0:
            return []
        return list(sheet.iter_rows(min_row=1, max_row=extent.rows, min_col=1, max_col=extent.columns,
                                    values_only=True))
    finally:
        workbook.close()


def read_import_rows(upload: Any) -> list[tuple[Any, ...]]:
    """Rows of the active worksheet as value tuples, bounded to its real data extent.

    ``upload`` is a werkzeug FileStorage or a binary file object. Raises ExcelImportRejected.
    """
    stream: IO[bytes] = getattr(upload, "stream", upload)
    try:
        if _upload_size(stream) > MAX_UPLOAD_BYTES:
            raise _reject("EXCEL_UPLOAD_TOO_LARGE")
        return _read_rows(stream)
    except _READ_ERRORS as exc:
        raise _reject("EXCEL_UNREADABLE", type(exc)) from None
