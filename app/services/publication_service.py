from __future__ import annotations

import re
import uuid
from types import ModuleType

from app.core.datetime_utils import utc_now

try:
    pymupdf: ModuleType | None = None
    import pymupdf as _pymupdf
except Exception:  # pragma: no cover
    pass
else:
    pymupdf = _pymupdf
from pathlib import Path

from flask import abort
from sqlalchemy import extract, or_
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import PublicationIssue
from app.security.private_uploads import private_upload_root

PUBLICATION_TYPE_LABELS = {
    "bulletin": "Kurumsal Bülten",
    "internal_magazine": "İçses Dergisi",
    "annual_report": "Faaliyet / Yıllık Yayın",
    "special_publication": "Özel Yayın",
}

STATUS_LABELS = {
    "draft": "Taslak",
    "published": "Yayında",
    "archived": "Arşiv",
}


def publication_type_label(value: str | None) -> str:
    key = str(value or "bulletin").strip().lower() or "bulletin"
    return PUBLICATION_TYPE_LABELS.get(key, "Kurumsal Yayın")


def publication_status_label(value: str | None) -> str:
    key = str(value or "published").strip().lower() or "published"
    return STATUS_LABELS.get(key, "Yayında")


def _extract_pdf_page_count(abs_path: str | None) -> int | None:
    if not abs_path:
        return None
    try:
        data = Path(abs_path).read_bytes()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None
    try:
        matches = re.findall(rb"/Type\s*/Page(?!s)\b", data)
        total = len(matches)
        return total or None
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _storage_root() -> Path:
    # B2-F06: yayınlar static dışındaki özel depoya yazılır; kayıtlar mutlak
    # storage_path tuttuğu için eski UPLOAD_FOLDER konumundaki dosyalar okunmaya devam eder.
    return private_upload_root()


def _next_sort_order() -> int:
    current = db.session.query(db.func.max(PublicationIssue.sort_order)).scalar()
    try:
        return int(current or 0) + 1
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return 1


def _normalize_status(value: str | None, can_manage: bool) -> str:
    raw = str(value or "published").strip().lower() or "published"
    allowed = {"draft", "published", "archived"} if can_manage else {"published"}
    return raw if raw in allowed else "published"


def _normalize_type(value: str | None) -> str:
    raw = str(value or "bulletin").strip().lower() or "bulletin"
    return raw if raw in PUBLICATION_TYPE_LABELS else "bulletin"


def upload_publication_issue(*, file_storage, title: str, subtitle: str | None, summary: str | None,
                             publication_type: str | None, issue_no: str | None, publication_period: str | None,
                             publication_date, allow_download: bool = True, is_featured: bool = False,
                             status: str | None = None, uploaded_by_id: int | None = None) -> PublicationIssue:
    filename = (getattr(file_storage, "filename", "") or "").strip()
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Kurumsal yayın yükleme için yalnızca PDF dosyası kullanılabilir.")
    if not title.strip():
        raise ValueError("Yayın başlığı zorunludur.")

    root = _storage_root() / "publications" / utc_now().strftime("%Y/%m")
    root.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(filename) or "yayin.pdf"
    stored_filename = f"{utc_now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}_{safe_name}"
    abs_path = root / stored_filename
    file_storage.save(abs_path)

    row = PublicationIssue(
        title=title.strip(),
        subtitle=(subtitle or "").strip() or None,
        summary=(summary or "").strip() or None,
        publication_type=_normalize_type(publication_type),
        issue_no=(issue_no or "").strip() or None,
        publication_period=(publication_period or "").strip() or None,
        publication_date=publication_date,
        status=_normalize_status(status, True),
        is_featured=bool(is_featured),
        sort_order=_next_sort_order(),
        original_filename=filename,
        stored_filename=stored_filename,
        storage_path=str(abs_path),
        mime_type="application/pdf",
        file_size=int(abs_path.stat().st_size if abs_path.exists() else 0),
        page_count=_extract_pdf_page_count(str(abs_path)),
        allow_download=bool(allow_download),
        created_by_id=uploaded_by_id,
        updated_by_id=uploaded_by_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def get_publication_issue_or_404(publication_id: int, *, include_archived: bool = False) -> PublicationIssue:
    row = PublicationIssue.query.get_or_404(publication_id)
    if not include_archived and (row.status == "archived" or getattr(row, "is_archived", False)):
        abort(404)
    if row.status != "published" and not include_archived:
        abort(404)
    return row


def archive_publication_issue(*, publication_id: int, user_id: int | None) -> PublicationIssue:
    row = PublicationIssue.query.get_or_404(publication_id)
    row.status = "archived"
    row.is_archived = True
    row.is_active = False
    row.updated_by_id = user_id
    db.session.add(row)
    db.session.flush()
    return row


def toggle_featured_publication(*, publication_id: int, user_id: int | None) -> PublicationIssue:
    row = PublicationIssue.query.get_or_404(publication_id)
    row.is_featured = not bool(row.is_featured)
    row.updated_by_id = user_id
    db.session.add(row)
    db.session.flush()
    return row


def update_publication_status(*, publication_id: int, status: str, user_id: int | None) -> PublicationIssue:
    row = PublicationIssue.query.get_or_404(publication_id)
    row.status = _normalize_status(status, True)
    row.is_archived = row.status == "archived"
    row.is_active = row.status != "archived"
    row.updated_by_id = user_id
    db.session.add(row)
    db.session.flush()
    return row


def build_publication_library_context(*, q: str | None = None, publication_type: str | None = None,
                                      selected_year: int | None = None, status_filter: str | None = None,
                                      can_manage: bool = False) -> dict:
    query = PublicationIssue.query
    if not can_manage:
        query = query.filter(PublicationIssue.status == "published", PublicationIssue.is_archived.is_(False))
    else:
        query = query.filter(PublicationIssue.is_archived.is_(False))

    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                PublicationIssue.title.ilike(like),
                PublicationIssue.subtitle.ilike(like),
                PublicationIssue.summary.ilike(like),
                PublicationIssue.issue_no.ilike(like),
                PublicationIssue.publication_period.ilike(like),
            )
        )

    normalized_type = _normalize_type(publication_type) if publication_type else ""
    if normalized_type:
        query = query.filter(PublicationIssue.publication_type == normalized_type)

    if selected_year:
        query = query.filter(extract("year", PublicationIssue.publication_date) == int(selected_year))

    normalized_status = str(status_filter or "").strip().lower()
    if can_manage and normalized_status in {"draft", "published", "archived"}:
        query = query.filter(PublicationIssue.status == normalized_status)

    rows = query.order_by(
        PublicationIssue.is_featured.desc(),
        PublicationIssue.publication_date.desc().nullslast(),
        PublicationIssue.sort_order.asc(),
        PublicationIssue.id.desc(),
    ).all()

    items = []
    for row in rows:
        year_value = row.publication_date.year if row.publication_date else None
        items.append({
            "row": row,
            "type_label": publication_type_label(row.publication_type),
            "status_label": publication_status_label(row.status),
            "date_label": row.publication_date.strftime("%d.%m.%Y") if row.publication_date else (row.publication_period or "Tarih belirtilmedi"),
            "year_value": year_value,
        })

    all_visible = PublicationIssue.query.filter(PublicationIssue.is_archived.is_(False))
    if not can_manage:
        all_visible = all_visible.filter(PublicationIssue.status == "published")
    all_visible = all_visible.all()

    featured_items = [item for item in items if item["row"].is_featured][:4]
    year_options = sorted({row.publication_date.year for row in all_visible if row.publication_date}, reverse=True)

    stats_source = all_visible if can_manage else [row for row in all_visible if row.status == "published"]
    stats = {
        "total_count": len(stats_source),
        "featured_count": len([row for row in stats_source if row.is_featured]),
        "magazine_count": len([row for row in stats_source if row.publication_type == "internal_magazine"]),
        "bulletin_count": len([row for row in stats_source if row.publication_type == "bulletin"]),
        "published_count": len([row for row in all_visible if row.status == "published"]),
        "draft_count": len([row for row in all_visible if row.status == "draft"]),
    }

    type_summary = []
    for key, label in PUBLICATION_TYPE_LABELS.items():
        total = len([row for row in stats_source if row.publication_type == key])
        if total:
            type_summary.append({"key": key, "label": label, "count": total})

    return {
        "publication_search_query": search,
        "publication_filter_type": normalized_type,
        "publication_filter_status": normalized_status,
        "publication_selected_year": selected_year,
        "publication_items": items,
        "publication_featured_items": featured_items,
        "publication_year_options": year_options,
        "publication_type_summary": type_summary,
        "publication_stats": stats,
        "publication_type_labels": PUBLICATION_TYPE_LABELS,
        "can_manage_publications": can_manage,
    }


def _published_publication_query():
    return PublicationIssue.query.filter(
        PublicationIssue.status == "published",
        PublicationIssue.is_archived.is_(False),
    )


def _publication_card_payload(row: PublicationIssue) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "summary": row.summary or row.subtitle or "Kurumsal yayın PDF görünümünde sunulur.",
        "type_label": publication_type_label(row.publication_type),
        "date_label": row.publication_date.strftime("%d.%m.%Y") if row.publication_date else (row.publication_period or "Tarih belirtilmedi"),
        "issue_no": row.issue_no,
        "allow_download": bool(row.allow_download),
    }


def build_publication_portal_spotlight(*, limit: int = 4) -> dict:
    base_rows = _published_publication_query().order_by(
        PublicationIssue.is_featured.desc(),
        PublicationIssue.publication_date.desc().nullslast(),
        PublicationIssue.sort_order.asc(),
        PublicationIssue.id.desc(),
    ).all()

    featured_rows = [row for row in base_rows if row.is_featured][:limit]
    spotlight_rows = featured_rows or base_rows[:limit]

    latest_magazine = next((row for row in base_rows if row.publication_type == "internal_magazine"), None)
    latest_bulletin = next((row for row in base_rows if row.publication_type == "bulletin"), None)

    return {
        "enabled": bool(base_rows),
        "total_count": len(base_rows),
        "featured_count": len([row for row in base_rows if row.is_featured]),
        "items": [_publication_card_payload(row) for row in spotlight_rows],
        "latest_magazine": _publication_card_payload(latest_magazine) if latest_magazine else None,
        "latest_bulletin": _publication_card_payload(latest_bulletin) if latest_bulletin else None,
    }

def publication_renderer_available() -> bool:
    return pymupdf is not None


def get_publication_page_count(publication: PublicationIssue) -> int:
    stored = int(getattr(publication, "page_count", 0) or 0)
    if stored > 0:
        return stored
    if pymupdf is None:
        return 0
    try:
        doc = pymupdf.open(str(publication.storage_path or ""))
        total = int(doc.page_count or 0)
        doc.close()
        return total
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return 0


def _publication_cache_root(publication_id: int, width: int) -> Path:
    root = _storage_root() / "publications" / "_spread_cache" / str(publication_id) / str(width)
    root.mkdir(parents=True, exist_ok=True)
    return root


def render_publication_page_image(*, publication: PublicationIssue, page_number: int, width: int = 1400) -> Path:
    if pymupdf is None:
        raise RuntimeError("PyMuPDF kurulu değil. Yerel spread görünümü için pymupdf kurulmalıdır.")

    pdf_path = Path(str(publication.storage_path or ""))
    if not pdf_path.is_file():
        raise FileNotFoundError("PDF dosyası bulunamadı.")

    page_number = int(page_number)
    width = max(320, min(int(width or 1400), 2200))
    cache_dir = _publication_cache_root(publication.id, width)
    target = cache_dir / f"page_{page_number:04d}.png"
    if target.is_file():
        return target

    doc = pymupdf.open(pdf_path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise IndexError("Sayfa bulunamadı.")
        page = doc.load_page(page_number - 1)
        rect = page.rect
        base_width = max(float(rect.width), 1.0)
        scale = width / base_width
        matrix = pymupdf.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(target)
    finally:
        doc.close()
    return target

def _remove_path_quietly(path_value: str | Path | None) -> None:
    if not path_value:
        return
    try:
        path = Path(path_value)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return
    try:
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            for child in sorted(path.rglob('*'), reverse=True):
                try:
                    if child.is_file() or child.is_symlink():
                        child.unlink(missing_ok=True)
                    elif child.is_dir():
                        child.rmdir()
                except Exception:
                    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/publication_service.py:379)")
                    continue
            try:
                path.rmdir()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/publication_service.py")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return


def permanent_delete_publication_issue(*, publication_id: int, user_id: int | None = None) -> dict:
    row = PublicationIssue.query.get_or_404(publication_id)
    title = row.title
    storage_path = str(row.storage_path or '').strip() or None
    cache_root = _storage_root() / 'publications' / '_spread_cache' / str(row.id)

    row.updated_by_id = user_id
    db.session.delete(row)
    db.session.flush()

    _remove_path_quietly(storage_path)
    _remove_path_quietly(cache_root)

    return {
        'id': publication_id,
        'title': title,
        'storage_path': storage_path,
        'cache_root': str(cache_root),
    }