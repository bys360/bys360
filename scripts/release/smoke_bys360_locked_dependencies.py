"""Runtime smoke test of an environment installed from requirements.lock.

Run it with the interpreter of a venv that was installed with
``pip install --no-index --find-links <wheelhouse> --require-hashes -r requirements.lock``
(CI does this on windows-latest, the production platform). It checks that:

* every installed distribution of the lock has exactly the pinned version;
* Pillow opens PNG and JPEG and refuses PNGs with truncated cHRM/gAMA/tRNS chunks;
* openpyxl round-trips a workbook with embedded PNG and JPEG pictures;
* reportlab draws PNG and JPEG into a PDF and XlsxWriter embeds them;
* app/services/excel_workbook_reader.py (loaded from its file, without the app
  package) returns rows for a valid workbook and refuses one with a truncated PNG.

Exceptions are not caught: any failure ends the run with a traceback and a non-zero exit.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import io
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_bys360_wheelhouse import parse_lock  # noqa: E402


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png(extra: bytes = b"", color_type: int = 2) -> bytes:
    channels = {0: 1, 2: 3}[color_type]
    raw = b"".join(b"\x00" + b"\x80" * (2 * channels) for _ in range(2))
    header = struct.pack(">IIBBBBB", 2, 2, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + extra + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")


def check_versions(lock: Path) -> int:
    mismatches = []
    pins = parse_lock(lock)
    for pin in pins:
        installed = importlib.metadata.version(pin.name)
        if installed != pin.version:
            mismatches.append(f"{pin.name}: installed {installed}, lock {pin.version}")
    if mismatches:
        raise SystemExit("installed versions differ from requirements.lock: " + "; ".join(mismatches))
    return len(pins)


def check_pillow() -> tuple[dict[str, object], bytes]:
    from PIL import Image

    jpeg = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 120, 200)).save(jpeg, format="JPEG")
    opened = {fmt: Image.open(io.BytesIO(data)).format for fmt, data in (("png", _png()), ("jpeg", jpeg.getvalue()))}
    refused = []
    for name, extra, color_type in (("cHRM", _chunk(b"cHRM", b""), 2), ("gAMA", _chunk(b"gAMA", b"\x00\x01"), 2),
                                    ("tRNS", _chunk(b"tRNS", b""), 0)):
        try:
            Image.open(io.BytesIO(_png(extra, color_type)))
        except ValueError as exc:
            if "Truncated" not in str(exc):
                raise
            refused.append(name)
        else:
            raise SystemExit(f"Pillow accepted a PNG with a truncated {name} chunk")
    return {"pillow": importlib.metadata.version("pillow"), "opened": opened, "refused_truncated": refused}, jpeg.getvalue()


def _workbook_with_images(png: bytes, jpeg: bytes) -> bytes:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XImage

    workbook = Workbook()
    workbook.active.append(["Sicil No", "Ad"])
    workbook.active.append(["SMOKE01", "Deneme"])
    workbook.active.add_image(XImage(io.BytesIO(png)), "D2")
    workbook.active.add_image(XImage(io.BytesIO(jpeg)), "G2")
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _replace_media(raw: bytes, data: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, data if item.filename.startswith("xl/media/") else source.read(item.filename))
    return out.getvalue()


def _load_reader() -> ModuleType:
    path = ROOT / "app" / "services" / "excel_workbook_reader.py"
    spec = importlib.util.spec_from_file_location("bys360_excel_workbook_reader_smoke", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_office_and_pdf(jpeg: bytes) -> dict[str, object]:
    from openpyxl import load_workbook
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from xlsxwriter import Workbook as XlsxWorkbook

    raw = _workbook_with_images(_png(), jpeg)
    images = len(load_workbook(io.BytesIO(raw)).active._images)
    if images != 2:
        raise SystemExit(f"openpyxl reloaded {images} pictures, expected 2")

    pdf = io.BytesIO()
    page = canvas.Canvas(pdf)
    for offset, data in enumerate((_png(), jpeg)):
        page.drawImage(ImageReader(io.BytesIO(data)), 50 + 60 * offset, 700, width=40, height=40)
    page.save()
    if not pdf.getvalue().startswith(b"%PDF"):
        raise SystemExit("reportlab did not produce a PDF")

    xlsx = io.BytesIO()
    book = XlsxWorkbook(xlsx, {"in_memory": True})
    sheet = book.add_worksheet()
    sheet.insert_image("B2", "a.png", {"image_data": io.BytesIO(_png())})
    sheet.insert_image("E2", "b.jpg", {"image_data": io.BytesIO(jpeg)})
    book.close()
    media = sorted(n for n in zipfile.ZipFile(io.BytesIO(xlsx.getvalue())).namelist() if n.startswith("xl/media/"))
    if len(media) != 2:
        raise SystemExit(f"XlsxWriter embedded {media}, expected 2 pictures")

    reader = _load_reader()
    rows = reader.read_active_sheet_rows(io.BytesIO(raw))
    if rows != [("Sicil No", "Ad"), ("SMOKE01", "Deneme")]:
        raise SystemExit(f"excel_workbook_reader returned {rows!r}")
    try:
        reader.read_active_sheet_rows(io.BytesIO(_replace_media(raw, _png(_chunk(b"cHRM", b"")))))
    except reader.ExcelWorkbookReadError:
        refused = True
    else:
        raise SystemExit("excel_workbook_reader accepted a workbook with a truncated PNG")
    return {"openpyxl_images": images, "pdf_bytes": len(pdf.getvalue()), "xlsxwriter_media": media,
            "reader_rows": len(rows), "reader_refused_truncated_png": refused}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lock", default=str(ROOT / "requirements.lock"))
    args = parser.parse_args(argv)
    packages = check_versions(Path(args.lock))
    pillow, jpeg = check_pillow()
    office = check_office_and_pdf(jpeg)
    print(json.dumps({"ok": True, "python": sys.version.split()[0], "platform": sys.platform,
                      "lock_packages_matched": packages, **pillow, **office}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
