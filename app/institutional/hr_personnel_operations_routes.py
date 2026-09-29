from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

from flask import current_app, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect
from werkzeug.utils import secure_filename

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    OrganizationUnit,
    PersonnelDocument,
    PersonnelDocumentUploadBatch,
    PersonnelPositionHistory,
    PersonnelProcessNote,
    PersonnelStatusHistory,
    User,
)
from app.models.hr_models import (
    PersonnelSelfServiceRequest,
    PersonnelSelfServiceRequestAttachment,
    PersonnelSelfServiceRequestLog,
    PersonnelSelfServiceRequestTemplate,
)
from app.route_registry import main_bp
from app.route_support import (
    consume_form_token,
    issue_form_token,
    manager_required,
    menu_key_required,
    safe_db_rollback,
    safe_render,
)

from .routes import _all_personnel, _filter_users_in_scope, _hr_scope_context, _scope_user_ids

logger = logging.getLogger(__name__)

ALLOWED_PERSONNEL_DOC_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".txt",
}

REQUEST_TYPE_LABELS = {
    "bilgi_guncelleme": "Bilgi Güncelleme",
    "belge_talebi": "Belge Talebi",
    "ozluk_duzeltme": "Özlük Düzeltme",
    "gorev_talebi": "Görev / Unvan Talebi",
    "diger": "Diğer",
}

REQUEST_PRIORITY_LABELS = {
    "normal": "Normal",
    "high": "Yüksek",
    "critical": "Kritik",
}

REQUEST_STATUS_LABELS = {
    "draft": "Taslak",
    "submitted": "Gönderildi",
    "in_review": "İncelemede",
    "returned": "İade Edildi",
    "approved": "Onaylandı",
    "rejected": "Reddedildi",
}


def _parse_date(value: str | None):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/institutional/hr_personnel_operations_routes.py:78")
        return None


def _normalize_text(value: str | None, limit: int = 255) -> str:
    return (str(value or "").strip())[:limit]


def _normalize_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "on", "yes", "evet"}


def _safe_int(value: str | None) -> int | None:
    try:
        raw = str(value or "").strip()
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _full_name(user: User | None) -> str:
    if not user:
        return "-"
    full_name = (getattr(user, "full_name", "") or "").strip()
    if full_name:
        return full_name
    return f"{(getattr(user, 'ad', '') or '').strip()} {(getattr(user, 'soyad', '') or '').strip()}".strip() or "-"


def _request_type_label(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return REQUEST_TYPE_LABELS.get(raw, "Bilinmiyor" if raw else "-")


def _request_priority_label(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return REQUEST_PRIORITY_LABELS.get(raw, "Bilinmiyor" if raw else "-")


def _request_status_label(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return REQUEST_STATUS_LABELS.get(raw, "Bilinmiyor" if raw else "-")


def _table_exists(table_name: str) -> bool:
    try:
        return table_name in set(inspect(db.engine).get_table_names())
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/institutional/hr_personnel_operations_routes.py:125")
        return False


def _current_scope_bundle() -> tuple[dict[str, Any], list[User], set[int]]:
    hr_scope = _hr_scope_context()
    scope_users = _filter_users_in_scope(_all_personnel(), hr_scope)
    return hr_scope, scope_users, set(_scope_user_ids(hr_scope))


def _redirect_operations(*, hr_scope: dict[str, Any] | None = None, user_id: int | None = None) -> object:
    scope_value = (request.form.get("scope") or request.args.get("scope") or (hr_scope or {}).get("scope_mode") or "").strip()
    params: dict[str, Any] = {}
    if scope_value:
        params["scope"] = scope_value
    if user_id:
        params["user_id"] = int(user_id)
    return redirect(url_for("main.hr_personnel_operations", **params))


def _redirect_self_service_requests(request_id: int | None = None) -> object:
    params: dict[str, Any] = {}
    if request_id:
        params["request_id"] = int(request_id)
    return redirect(url_for("main.hr_self_service_requests", **params))


def _redirect_request_review(*, hr_scope: dict[str, Any] | None = None, request_id: int | None = None) -> object:
    scope_value = (request.form.get("scope") or request.args.get("scope") or (hr_scope or {}).get("scope_mode") or "").strip()
    params: dict[str, Any] = {}
    if scope_value:
        params["scope"] = scope_value
    if request_id:
        params["request_id"] = int(request_id)
    return redirect(url_for("main.hr_personnel_request_review_index", **params))


def _require_user_in_scope(user_id: int | None, scope_user_ids: set[int]) -> User:
    if not user_id or user_id not in scope_user_ids:
        raise ValueError("Seçilen personel bu kapsam içinde görünmüyor.")
    user = db.session.get(User, int(user_id))
    if not user:
        raise ValueError("Personel kaydı bulunamadı.")
    return user


def _upload_root() -> str:
    base_dir = current_app.config.get("UPLOAD_FOLDER")
    if not base_dir:
        base_dir = os.path.join(current_app.root_path, "uploads")
    target = os.path.join(base_dir, "hr", "personnel_documents")
    os.makedirs(target, exist_ok=True)
    return target


def _remove_file(path: str | None) -> None:
    raw = (path or "").strip()
    if not raw:
        return
    try:
        if os.path.exists(raw):
            os.remove(raw)
    except Exception:
        current_app.logger.warning("Personel belge dosyasi silinemedi: %s", raw)


def _save_file(file_storage, *, prefix: str = "personnel") -> dict[str, Any]:
    filename = secure_filename(getattr(file_storage, "filename", "") or "")
    if not filename:
        raise ValueError("Belge dosyası seçilmedi.")
    _, ext = os.path.splitext(filename)
    ext = (ext or "").lower()
    if ext not in ALLOWED_PERSONNEL_DOC_EXTENSIONS:
        raise ValueError("Yalnızca PDF, Office belgeleri, metin ve görsel dosyaları yüklenebilir.")
    stored_filename = f"{prefix}_{uuid.uuid4().hex}{ext}"
    folder = _upload_root()
    full_path = os.path.join(folder, stored_filename)
    file_storage.save(full_path)
    try:
        file_size = os.path.getsize(full_path)
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/institutional/hr_personnel_operations_routes.py:205")
        file_size = 0
    return {
        "original_filename": filename,
        "stored_filename": stored_filename,
        "storage_path": full_path,
        "mime_type": getattr(file_storage, "mimetype", None),
        "file_size": file_size,
    }


def _document_in_scope(document_id: int | None, scope_user_ids: set[int]) -> PersonnelDocument:
    if not document_id:
        raise ValueError("Belge kaydı bulunamadı.")
    row = PersonnelDocument.query.filter(PersonnelDocument.id == int(document_id), PersonnelDocument.user_id.in_(list(scope_user_ids))).first()
    if not row:
        raise ValueError("Belge kaydı bu kapsam içinde bulunamadı.")
    return row


def _note_in_scope(note_id: int | None, scope_user_ids: set[int]) -> PersonnelProcessNote:
    if not note_id:
        raise ValueError("İşlem notu kaydı bulunamadı.")
    row = PersonnelProcessNote.query.filter(PersonnelProcessNote.id == int(note_id), PersonnelProcessNote.user_id.in_(list(scope_user_ids))).first()
    if not row:
        raise ValueError("İşlem notu bu kapsam içinde bulunamadı.")
    return row


def _status_in_scope(status_id: int | None, scope_user_ids: set[int]) -> PersonnelStatusHistory:
    if not status_id:
        raise ValueError("Durum geçmişi kaydı bulunamadı.")
    row = PersonnelStatusHistory.query.filter(PersonnelStatusHistory.id == int(status_id), PersonnelStatusHistory.user_id.in_(list(scope_user_ids))).first()
    if not row:
        raise ValueError("Durum geçmişi bu kapsam içinde bulunamadı.")
    return row


def _template_rows() -> list[PersonnelSelfServiceRequestTemplate]:
    if not _table_exists("personnel_self_service_request_templates"):
        return []
    return (
        PersonnelSelfServiceRequestTemplate.query
        .filter_by(is_active=True)
        .order_by(PersonnelSelfServiceRequestTemplate.sort_order.asc(), PersonnelSelfServiceRequestTemplate.id.asc())
        .all()
    )


def _template_by_id(template_id: int | None) -> PersonnelSelfServiceRequestTemplate | None:
    if not template_id or not _table_exists("personnel_self_service_request_templates"):
        return None
    return PersonnelSelfServiceRequestTemplate.query.filter_by(id=int(template_id), is_active=True).first()


def _serialize_template_card(template: PersonnelSelfServiceRequestTemplate) -> dict[str, Any]:
    return {
        "id": int(template.id),
        "code": template.code,
        "title": template.title,
        "request_type": template.request_type,
        "request_type_label": _request_type_label(template.request_type),
        "priority": template.priority,
        "priority_label": _request_priority_label(template.priority),
        "description_hint": template.description_hint or "",
        "sla_target_days": int(template.sla_target_days or 0) if template.sla_target_days is not None else None,
        "requires_attachment": bool(template.requires_attachment),
    }


def _request_attachment_rows(row: PersonnelSelfServiceRequest | None) -> list[dict[str, Any]]:
    if not row or not _table_exists("personnel_self_service_request_attachments"):
        return []
    query_rows = (
        PersonnelSelfServiceRequestAttachment.query
        .filter_by(request_id=row.id)
        .order_by(PersonnelSelfServiceRequestAttachment.created_at.desc(), PersonnelSelfServiceRequestAttachment.id.desc())
        .all()
    )
    result = []
    for attachment in query_rows:
        result.append({
            "id": int(attachment.id),
            "name": attachment.original_filename,
            "size": int(getattr(attachment, "file_size", 0) or 0),
            "note": getattr(attachment, "note", None) or "",
            "uploaded_at": getattr(attachment, "created_at", None),
            "uploaded_by_name": _full_name(getattr(attachment, "uploaded_by", None)),
        })
    return result


def _attachment_in_own_request(request_id: int, attachment_id: int) -> PersonnelSelfServiceRequestAttachment:
    row = (
        PersonnelSelfServiceRequestAttachment.query
        .join(PersonnelSelfServiceRequest, PersonnelSelfServiceRequest.id == PersonnelSelfServiceRequestAttachment.request_id)
        .filter(
            PersonnelSelfServiceRequestAttachment.id == int(attachment_id),
            PersonnelSelfServiceRequestAttachment.request_id == int(request_id),
            PersonnelSelfServiceRequest.user_id == getattr(current_user, "id", None),
        )
        .first()
    )
    if not row:
        raise ValueError("Talep eki bulunamadı.")
    return row


def _attachment_in_scope(request_id: int, attachment_id: int, scope_user_ids: set[int]) -> PersonnelSelfServiceRequestAttachment:
    row = (
        PersonnelSelfServiceRequestAttachment.query
        .join(PersonnelSelfServiceRequest, PersonnelSelfServiceRequest.id == PersonnelSelfServiceRequestAttachment.request_id)
        .filter(
            PersonnelSelfServiceRequestAttachment.id == int(attachment_id),
            PersonnelSelfServiceRequestAttachment.request_id == int(request_id),
            PersonnelSelfServiceRequest.user_id.in_(list(scope_user_ids)),
        )
        .first()
    )
    if not row:
        raise ValueError("Talep eki bu kapsam içinde bulunamadı.")
    return row


def _own_request_or_404(request_id: int | None) -> PersonnelSelfServiceRequest:
    if not request_id:
        raise ValueError("Talep kaydı bulunamadı.")
    row = PersonnelSelfServiceRequest.query.filter_by(id=int(request_id), user_id=getattr(current_user, "id", None)).first()
    if not row:
        raise ValueError("Talep kaydı bulunamadı.")
    return row


def _request_in_scope(request_id: int | None, scope_user_ids: set[int]) -> PersonnelSelfServiceRequest:
    if not request_id:
        raise ValueError("Talep kaydı bulunamadı.")
    row = PersonnelSelfServiceRequest.query.filter(
        PersonnelSelfServiceRequest.id == int(request_id),
        PersonnelSelfServiceRequest.user_id.in_(list(scope_user_ids)),
    ).first()
    if not row:
        raise ValueError("Talep kaydı bu kapsam içinde bulunamadı.")
    return row


def _write_request_log(row: PersonnelSelfServiceRequest, *, action: str, from_status: str | None = None, to_status: str | None = None, note: str | None = None) -> None:
    if not _table_exists("personnel_self_service_request_logs"):
        return
    db.session.add(
        PersonnelSelfServiceRequestLog(
            request_id=row.id,
            actor_user_id=getattr(current_user, "id", None),
            action=(action or "islem")[:50],
            from_status=from_status or None,
            to_status=to_status or None,
            note=(str(note or "").strip() or None),
        )
    )


def _compute_due_at(*, base_dt: datetime | None, sla_target_days: int | None, desired_completion_date) -> datetime | None:
    if desired_completion_date:
        return datetime.combine(desired_completion_date, datetime.max.time().replace(microsecond=0))
    if base_dt and sla_target_days:
        return base_dt + timedelta(days=int(sla_target_days))
    return None


def _sla_payload(row: PersonnelSelfServiceRequest | None) -> dict[str, Any] | None:
    if not row:
        return None
    due_at = getattr(row, "due_at", None)
    if not due_at and getattr(row, "desired_completion_date", None):
        due_at = _compute_due_at(base_dt=None, sla_target_days=None, desired_completion_date=row.desired_completion_date)
    if not due_at:
        return None
    now = utc_now()
    remaining_days = (due_at.date() - now.date()).days
    if remaining_days < 0 and (getattr(row, "status", "") or "") not in {"approved", "rejected"}:
        tone = "bad"
        label = f"{abs(remaining_days)} gün gecikti"
    elif remaining_days == 0 and (getattr(row, "status", "") or "") not in {"approved", "rejected"}:
        tone = "warn"
        label = "Bugün"
    elif (getattr(row, "status", "") or "") in {"approved", "rejected"}:
        tone = "good"
        label = "Kapandı"
    else:
        tone = "soft"
        label = f"{remaining_days} gün kaldı"
    return {
        "due_at": due_at,
        "days_remaining": remaining_days,
        "tone": tone,
        "label": label,
    }


def _request_review_payload(hr_scope: dict[str, Any], scope_user_ids: set[int]) -> dict[str, Any]:
    selected_request_id = _safe_int(request.args.get("request_id"))
    rows: list[dict[str, Any]] = []
    if _table_exists("personnel_self_service_requests") and scope_user_ids:
        query_rows = (
            PersonnelSelfServiceRequest.query
            .filter(PersonnelSelfServiceRequest.user_id.in_(list(scope_user_ids)))
            .order_by(PersonnelSelfServiceRequest.updated_at.desc(), PersonnelSelfServiceRequest.id.desc())
            .all()
        )
        for row in query_rows:
            template = getattr(row, "template", None)
            sla = _sla_payload(row)
            rows.append({
                "id": int(row.id),
                "user_id": int(row.user_id),
                "user_name": _full_name(getattr(row, "user", None)),
                "title": getattr(row, "title", None) or "Talep",
                "template_title": getattr(template, "title", None) or "-",
                "request_type_label": _request_type_label(getattr(row, "request_type", None)),
                "priority": getattr(row, "priority", None) or "normal",
                "priority_label": _request_priority_label(getattr(row, "priority", None)),
                "status": getattr(row, "status", None) or "draft",
                "status_label": _request_status_label(getattr(row, "status", None)),
                "submitted_at": getattr(row, "submitted_at", None),
                "desired_completion_date": getattr(row, "desired_completion_date", None),
                "handler_name": _full_name(getattr(row, "current_handler", None)),
                "attachment_count": row.attachments.count() if hasattr(row, "attachments") else 0,
                "sla": sla,
            })
    rows.sort(key=lambda item: (
        0 if item["priority"] == "critical" else (1 if item["priority"] == "high" else 2),
        0 if item["status"] in {"submitted", "in_review", "returned"} else 1,
        (item.get("sla") or {}).get("days_remaining", 999999),
        item["user_name"].lower(),
    ))

    selected_request = None
    if selected_request_id:
        selected_request = _request_in_scope(selected_request_id, scope_user_ids)
    elif rows:
        first_id = next((row["id"] for row in rows if row["status"] in {"submitted", "in_review", "returned"}), rows[0]["id"])
        selected_request = _request_in_scope(first_id, scope_user_ids)

    log_rows = []
    if selected_request and _table_exists("personnel_self_service_request_logs"):
        logs = (
            PersonnelSelfServiceRequestLog.query
            .filter_by(request_id=selected_request.id)
            .order_by(PersonnelSelfServiceRequestLog.created_at.desc(), PersonnelSelfServiceRequestLog.id.desc())
            .limit(20)
            .all()
        )
        for log in logs:
            log_rows.append({
                "created_at": getattr(log, "created_at", None),
                "actor_name": _full_name(getattr(log, "actor", None)),
                "action": getattr(log, "action", None) or "İşlem",
                "from_status": _request_status_label(getattr(log, "from_status", None)),
                "to_status": _request_status_label(getattr(log, "to_status", None)),
                "note": getattr(log, "note", None) or "",
            })

    overdue_count = sum(1 for row in rows if row.get("sla") and row["sla"].get("days_remaining", 0) < 0 and row["status"] not in {"approved", "rejected"})
    return {
        "request_rows": rows,
        "selected_request": selected_request,
        "selected_request_logs": log_rows,
        "selected_request_sla": _sla_payload(selected_request),
        "selected_request_attachment_rows": _request_attachment_rows(selected_request),
        "selected_request_type_label": _request_type_label(getattr(selected_request, "request_type", None)),
        "selected_request_priority_label": _request_priority_label(getattr(selected_request, "priority", None)),
        "request_review_token": issue_form_token("hr_personnel_request_review", scope="hr_personnel_operations"),
        "queue_summary": {
            "submitted": sum(1 for row in rows if row["status"] == "submitted"),
            "in_review": sum(1 for row in rows if row["status"] == "in_review"),
            "returned": sum(1 for row in rows if row["status"] == "returned"),
            "approved": sum(1 for row in rows if row["status"] == "approved"),
            "overdue": overdue_count,
        },
    }


def _self_service_request_payload(user: User) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    selected_request_id = _safe_int(request.args.get("request_id"))
    template_cards = [_serialize_template_card(item) for item in _template_rows()]
    if _table_exists("personnel_self_service_requests"):
        query_rows = (
            PersonnelSelfServiceRequest.query
            .filter_by(user_id=user.id)
            .order_by(PersonnelSelfServiceRequest.updated_at.desc(), PersonnelSelfServiceRequest.id.desc())
            .all()
        )
        for row in query_rows:
            status = (getattr(row, "status", None) or "draft").strip().lower()
            rows.append({
                "id": int(row.id),
                "title": getattr(row, "title", None) or "Talep",
                "template_title": getattr(getattr(row, "template", None), "title", None) or "-",
                "request_type_label": _request_type_label(getattr(row, "request_type", None)),
                "priority_label": _request_priority_label(getattr(row, "priority", None)),
                "status": status,
                "status_label": _request_status_label(status),
                "submitted_at": getattr(row, "submitted_at", None),
                "desired_completion_date": getattr(row, "desired_completion_date", None),
                "handler_name": _full_name(getattr(row, "current_handler", None)),
                "is_deletable": status in {"draft", "returned"},
                "attachment_count": row.attachments.count() if hasattr(row, "attachments") else 0,
                "sla": _sla_payload(row),
            })
    selected_request = None
    if selected_request_id:
        selected_request = PersonnelSelfServiceRequest.query.filter_by(id=selected_request_id, user_id=user.id).first()
    elif _table_exists("personnel_self_service_requests"):
        selected_request = (
            PersonnelSelfServiceRequest.query
            .filter_by(user_id=user.id)
            .order_by(PersonnelSelfServiceRequest.updated_at.desc(), PersonnelSelfServiceRequest.id.desc())
            .first()
        )

    logs = []
    if selected_request and _table_exists("personnel_self_service_request_logs"):
        query_logs = (
            PersonnelSelfServiceRequestLog.query
            .filter_by(request_id=selected_request.id)
            .order_by(PersonnelSelfServiceRequestLog.created_at.desc(), PersonnelSelfServiceRequestLog.id.desc())
            .limit(20)
            .all()
        )
        for log in query_logs:
            logs.append({
                "created_at": getattr(log, "created_at", None),
                "actor_name": _full_name(getattr(log, "actor", None)),
                "action": getattr(log, "action", None) or "İşlem",
                "from_status": _request_status_label(getattr(log, "from_status", None)),
                "to_status": _request_status_label(getattr(log, "to_status", None)),
                "note": getattr(log, "note", None) or "",
            })
    selected_template_id = getattr(selected_request, "template_id", None) if selected_request else None
    return {
        "requests_ready": _table_exists("personnel_self_service_requests"),
        "request_rows": rows,
        "selected_request": selected_request,
        "request_log_rows": logs,
        "selected_request_sla": _sla_payload(selected_request),
        "selected_request_attachment_rows": _request_attachment_rows(selected_request),
        "selected_request_type_label": _request_type_label(getattr(selected_request, "request_type", None)),
        "selected_request_priority_label": _request_priority_label(getattr(selected_request, "priority", None) or "normal"),
        "queue_counts": {
            "submitted": sum(1 for row in rows if row["status"] == "submitted"),
            "in_review": sum(1 for row in rows if row["status"] == "in_review"),
            "returned": sum(1 for row in rows if row["status"] == "returned"),
            "overdue": sum(1 for row in rows if row.get("sla") and row["sla"].get("days_remaining", 0) < 0 and row["status"] not in {"approved", "rejected"}),
        },
        "request_type_options": list(REQUEST_TYPE_LABELS.items()),
        "request_priority_options": list(REQUEST_PRIORITY_LABELS.items()),
        "template_cards": template_cards,
        "selected_template_id": selected_template_id,
        "request_form_token": issue_form_token("hr_self_service_request_save", scope="hr_self_service_requests"),
        "request_delete_token": issue_form_token("hr_self_service_request_delete", scope="hr_self_service_requests"),
        "request_attachment_delete_token": issue_form_token("hr_self_service_request_attachment_delete", scope="hr_self_service_requests"),
    }


@main_bp.route("/hr-management/self-service/requests")
@login_required
def hr_self_service_requests():
    payload = _self_service_request_payload(current_user)
    return safe_render("hr_self_service_requests.html", **payload)


@main_bp.route("/hr-management/self-service/requests/save", methods=["POST"])
@login_required
def hr_self_service_request_save():
    if not consume_form_token("hr_self_service_request_save", request.form.get("form_token"), scope="hr_self_service_requests"):
        flash("Talep formu güvenlik doğrulaması başarısız oldu. Sayfayı yenileyip tekrar deneyin.", "danger")
        return _redirect_self_service_requests(_safe_int(request.form.get("request_id")))

    saved_paths: list[str] = []
    try:
        request_id = _safe_int(request.form.get("request_id"))
        action_mode = (request.form.get("action_mode") or "draft").strip().lower()
        row = _own_request_or_404(request_id) if request_id else PersonnelSelfServiceRequest(user_id=current_user.id, created_by_id=current_user.id)
        previous_status = (getattr(row, "status", None) or "draft").strip().lower()
        if request_id and previous_status not in {"draft", "returned"}:
            raise ValueError("Sadece taslak veya iade edilen talepler düzenlenebilir.")

        template = _template_by_id(_safe_int(request.form.get("template_id")))
        row.template_id = getattr(template, "id", None)
        row.request_type = _normalize_text(request.form.get("request_type") or getattr(template, "request_type", None) or "bilgi_guncelleme", 50).lower() or "bilgi_guncelleme"
        row.title = _normalize_text(request.form.get("title") or getattr(template, "title", None), 255)
        row.description = _normalize_text(request.form.get("description"), 5000)
        row.priority = _normalize_text(request.form.get("priority") or getattr(template, "priority", None) or "normal", 20).lower() or "normal"
        row.requested_effective_date = _parse_date(request.form.get("requested_effective_date"))
        row.desired_completion_date = _parse_date(request.form.get("desired_completion_date"))
        row.last_action_by_id = current_user.id
        row.hr_visible = True
        row.sla_target_days = int(getattr(template, "sla_target_days", 0) or 0) or None
        row.requires_attachment = bool(getattr(template, "requires_attachment", False))

        if not row.title:
            raise ValueError("Talep başlığı zorunludur.")
        if not row.description:
            raise ValueError("Talep açıklaması zorunludur.")
        if row.desired_completion_date and row.requested_effective_date and row.desired_completion_date < row.requested_effective_date:
            raise ValueError("Hedef tamamlanma tarihi, talep edilen yürürlük tarihinden önce olamaz.")

        db.session.add(row)
        db.session.flush()

        uploads = [item for item in request.files.getlist("request_files") if getattr(item, "filename", "")]
        for upload in uploads:
            payload = _save_file(upload, prefix="personnel_request")
            saved_paths.append(str(payload["storage_path"]))
            db.session.add(
                PersonnelSelfServiceRequestAttachment(
                    request_id=row.id,
                    uploaded_by_id=getattr(current_user, "id", None),
                    original_filename=str(payload["original_filename"]),
                    stored_filename=str(payload["stored_filename"]),
                    storage_path=str(payload["storage_path"]),
                    mime_type=str(payload.get("mime_type") or "") or None,
                    file_size=int(payload.get("file_size") or 0),
                    note=_normalize_text(request.form.get("attachment_note"), 255) or None,
                )
            )

        existing_attachment_count = row.attachments.count() if hasattr(row, "attachments") else 0
        if action_mode == "submit":
            if row.requires_attachment and existing_attachment_count == 0:
                raise ValueError("Bu talep şablonu için en az bir destekleyici belge eki yüklemek zorunludur.")
            now = utc_now()
            row.status = "submitted"
            row.submitted_at = now
            row.reviewed_at = None
            row.closed_at = None
            row.current_handler_id = None
            row.due_at = _compute_due_at(base_dt=now, sla_target_days=row.sla_target_days, desired_completion_date=row.desired_completion_date)
            message = "Talep incelemeye gönderildi."
            log_action = "submitted"
        else:
            row.status = "draft"
            row.current_handler_id = None
            row.closed_at = None
            row.reviewed_at = None if previous_status == "returned" else row.reviewed_at
            row.due_at = _compute_due_at(base_dt=utc_now(), sla_target_days=row.sla_target_days, desired_completion_date=row.desired_completion_date) if row.desired_completion_date else row.due_at
            message = "Talep taslak olarak kaydedildi."
            log_action = "saved"

        _write_request_log(row, action=log_action, from_status=previous_status if request_id else None, to_status=row.status, note=("Personel talebi güncelledi" if request_id else "Yeni personel talebi"))
        db.session.commit()
        flash(message, "success")
        return _redirect_self_service_requests(row.id)
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        for path in saved_paths:
            _remove_file(path)
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
        return _redirect_self_service_requests(_safe_int(request.form.get("request_id")))


@main_bp.route("/hr-management/self-service/requests/<int:request_id>/delete", methods=["POST"])
@login_required
def hr_self_service_request_delete(request_id: int):
    if not consume_form_token("hr_self_service_request_delete", request.form.get("form_token"), scope="hr_self_service_requests"):
        flash("Talep silme güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_self_service_requests(request_id)

    try:
        row = _own_request_or_404(request_id)
        if (getattr(row, "status", None) or "draft") not in {"draft", "returned"}:
            raise ValueError("Sadece taslak veya iade edilen talepler silinebilir.")
        for attachment in row.attachments.all() if hasattr(row, "attachments") else []:
            _remove_file(getattr(attachment, "storage_path", None))
        db.session.delete(row)
        db.session.commit()
        flash("Talep kaydı kaldırıldı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_self_service_requests()


@main_bp.route("/hr-management/self-service/request/<int:request_id>/attachment/<int:attachment_id>/download")
@login_required
def hr_self_service_request_attachment_download(request_id: int, attachment_id: int):
    try:
        row = _attachment_in_own_request(request_id, attachment_id)
        path = (getattr(row, "storage_path", None) or "").strip()
        if not path or not os.path.exists(path):
            raise ValueError("Ek dosyası bulunamadı.")
        return send_file(path, as_attachment=True, download_name=getattr(row, "original_filename", None) or os.path.basename(path))
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
        return _redirect_self_service_requests(request_id)


@main_bp.route("/hr-management/self-service/request/<int:request_id>/attachment/<int:attachment_id>/delete", methods=["POST"])
@login_required
def hr_self_service_request_attachment_delete(request_id: int, attachment_id: int):
    if not consume_form_token("hr_self_service_request_attachment_delete", request.form.get("form_token"), scope="hr_self_service_requests"):
        flash("Talep eki silme güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_self_service_requests(request_id)
    try:
        request_row = _own_request_or_404(request_id)
        if (getattr(request_row, "status", None) or "draft") not in {"draft", "returned"}:
            raise ValueError("Sadece taslak veya iade edilen taleplerin ekleri silinebilir.")
        row = _attachment_in_own_request(request_id, attachment_id)
        _remove_file(getattr(row, "storage_path", None))
        db.session.delete(row)
        db.session.commit()
        flash("Talep eki kaldırıldı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_self_service_requests(request_id)


@main_bp.route("/hr-management/personnel-operations/requests")
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_request_review_index():
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    payload = _request_review_payload(hr_scope, scope_user_ids)
    return safe_render(
        "hr_personnel_request_review.html",
        hr_scope=hr_scope,
        selected_scope_mode=(hr_scope or {}).get("scope_mode") or "personal",
        scope_label=(hr_scope or {}).get("scope_label") or "Kapsam",
        **payload,
    )


@main_bp.route("/hr-management/personnel-operations/request/<int:request_id>/review", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_request_review(request_id: int):
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_request_review", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("Talep inceleme güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_request_review(hr_scope=hr_scope, request_id=request_id)

    try:
        row = _request_in_scope(request_id, scope_user_ids)
        action = _normalize_text(request.form.get("review_action") or "in_review", 30).lower() or "in_review"
        decision_note = _normalize_text(request.form.get("decision_note"), 4000) or None
        previous_status = (getattr(row, "status", None) or "submitted").strip().lower()

        status_map = {
            "in_review": "in_review",
            "approve": "approved",
            "reject": "rejected",
            "return": "returned",
        }
        if action not in status_map:
            raise ValueError("Geçersiz talep işlemi.")

        now = utc_now()
        row.status = status_map[action]
        row.current_handler_id = current_user.id
        row.last_action_by_id = current_user.id
        row.reviewed_at = now
        if row.first_response_at is None:
            row.first_response_at = now
        row.closed_at = now if row.status in {"approved", "rejected"} else None
        row.decision_note = decision_note
        db.session.add(row)
        _write_request_log(row, action=action, from_status=previous_status, to_status=row.status, note=decision_note)
        db.session.commit()
        flash("Talep akışı güncellendi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_request_review(hr_scope=hr_scope, request_id=request_id)


@main_bp.route("/hr-management/personnel-operations/request/<int:request_id>/attachment/<int:attachment_id>/download")
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_request_attachment_download(request_id: int, attachment_id: int):
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    try:
        row = _attachment_in_scope(request_id, attachment_id, scope_user_ids)
        path = (getattr(row, "storage_path", None) or "").strip()
        if not path or not os.path.exists(path):
            raise ValueError("Ek dosyası bulunamadı.")
        return send_file(path, as_attachment=True, download_name=getattr(row, "original_filename", None) or os.path.basename(path))
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
        return _redirect_request_review(hr_scope=hr_scope, request_id=request_id)


@main_bp.route("/hr-management/personnel-operations/document/save", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_document_save():
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_document_save", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("Belge formu güvenlik doğrulaması başarısız oldu. Sayfayı yenileyip tekrar deneyin.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)

    try:
        user_id = int(request.form.get("user_id") or 0)
        user = _require_user_in_scope(user_id, scope_user_ids)
        document_id = int(request.form.get("document_id") or 0) or None
        row = _document_in_scope(document_id, scope_user_ids) if document_id else PersonnelDocument(user_id=user.id, uploaded_by_id=getattr(current_user, "id", None))

        row.category = _normalize_text(request.form.get("category") or "ozluk", 50).lower() or "ozluk"
        row.title = _normalize_text(request.form.get("title"), 255)
        row.document_no = _normalize_text(request.form.get("document_no"), 120) or None
        row.status = _normalize_text(request.form.get("status") or "aktif", 30).lower() or "aktif"
        row.issue_date = _parse_date(request.form.get("issue_date"))
        row.expiry_date = _parse_date(request.form.get("expiry_date"))
        row.is_confidential = _normalize_bool(request.form.get("is_confidential"))
        row.description = _normalize_text(request.form.get("description"), 2000) or None

        if not row.title:
            raise ValueError("Belge başlığı zorunludur.")
        if row.expiry_date and row.issue_date and row.expiry_date < row.issue_date:
            raise ValueError("Bitiş tarihi düzenlenme tarihinden önce olamaz.")

        upload = request.files.get("document_file")
        if upload and upload.filename:
            file_payload = _save_file(upload)
            old_path = getattr(row, "storage_path", None)
            row.original_filename = str(file_payload["original_filename"])
            row.stored_filename = str(file_payload["stored_filename"])
            row.storage_path = str(file_payload["storage_path"])
            row.mime_type = str(file_payload.get("mime_type") or "") or None
            row.file_size = int(file_payload.get("file_size") or 0)
            if old_path and old_path != row.storage_path:
                _remove_file(old_path)
        elif not document_id:
            raise ValueError("Yeni belge kaydı için dosya yüklemek zorunludur.")

        db.session.add(row)
        db.session.commit()
        flash(f"{user.full_name} için personel belgesi kaydedildi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)


@main_bp.route("/hr-management/personnel-operations/document/bulk-upload", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_document_bulk_upload():
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_document_bulk_upload", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("Toplu belge yükleme güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)

    try:
        user_id = int(request.form.get("user_id") or 0)
        user = _require_user_in_scope(user_id, scope_user_ids)
        files = [item for item in request.files.getlist("document_files") if getattr(item, "filename", "")]
        if not files:
            raise ValueError("Toplu yükleme için en az bir dosya seçin.")

        category = _normalize_text(request.form.get("category") or "ozluk", 50).lower() or "ozluk"
        status = _normalize_text(request.form.get("status") or "aktif", 30).lower() or "aktif"
        issue_date = _parse_date(request.form.get("issue_date"))
        expiry_date = _parse_date(request.form.get("expiry_date"))
        is_confidential = _normalize_bool(request.form.get("is_confidential"))
        title_prefix = _normalize_text(request.form.get("title_prefix"), 120)
        description = _normalize_text(request.form.get("description"), 2000) or None

        success_count = 0
        skipped: list[str] = []
        saved_paths: list[str] = []
        batch = None
        if _table_exists("personnel_document_upload_batches"):
            batch = PersonnelDocumentUploadBatch(
                user_id=user.id,
                uploaded_by_id=getattr(current_user, "id", None),
                category_code=category,
                status="isleniyor",
                source_name=f"{len(files)} dosya",
                total_file_count=len(files),
                success_count=0,
                note=description,
            )
            db.session.add(batch)
            db.session.flush()

        for upload in files:
            try:
                payload = _save_file(upload)
                saved_paths.append(str(payload["storage_path"]))
                base_name = os.path.splitext(str(payload["original_filename"]))[0].replace("_", " ").replace("-", " ").strip()
                title = f"{title_prefix} {base_name}".strip() if title_prefix else base_name
                row = PersonnelDocument(
                    user_id=user.id,
                    uploaded_by_id=getattr(current_user, "id", None),
                    category=category,
                    title=title[:255] or "Belge",
                    status=status,
                    issue_date=issue_date,
                    expiry_date=expiry_date,
                    is_confidential=is_confidential,
                    description=description,
                    original_filename=str(payload["original_filename"]),
                    stored_filename=str(payload["stored_filename"]),
                    storage_path=str(payload["storage_path"]),
                    mime_type=str(payload.get("mime_type") or "") or None,
                    file_size=int(payload.get("file_size") or 0),
                )
                db.session.add(row)
                success_count += 1
            except ValueError as exc:
                skipped.append(str(exc))
            except Exception as exc:
                logger.exception("Toplu belge yükleme sırasında beklenmeyen hata: %s", exc)
                skipped.append("Dosya işlenirken beklenmeyen bir hata oluştu.")

        if success_count <= 0:
            raise ValueError(skipped[0] if skipped else "Hiçbir dosya işlenemedi.")

        if batch is not None:
            batch.success_count = success_count
            batch.status = "tamamlandi" if not skipped else "kismi"
            note_parts = []
            if description:
                note_parts.append(description)
            if skipped:
                note_parts.append("; ".join(skipped[:4]))
            batch.note = "\n".join(note_parts) if note_parts else None
            db.session.add(batch)

        db.session.commit()
        if skipped:
            flash(f"{user.full_name} için {success_count} belge yüklendi. {len(skipped)} dosya atlandı.", "warning")
        else:
            flash(f"{user.full_name} için {success_count} belge toplu olarak yüklendi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)


@main_bp.route("/hr-management/personnel-operations/document/<int:document_id>/delete", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_document_delete(document_id: int):
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_document_delete", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("Belge silme güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)

    try:
        row = _document_in_scope(document_id, scope_user_ids)
        user_id: int | None = int(row.user_id)
        old_path = getattr(row, "storage_path", None)
        db.session.delete(row)
        db.session.commit()
        _remove_file(old_path)
        flash("Personel belge kaydı kaldırıldı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
        user_id = _safe_int(request.form.get("user_id")) or None
    return _redirect_operations(hr_scope=hr_scope, user_id=user_id)


@main_bp.route("/hr-management/personnel-operations/document/<int:document_id>/download")
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_document_download(document_id: int):
    _, _, scope_user_ids = _current_scope_bundle()
    try:
        row = _document_in_scope(document_id, scope_user_ids)
        path = (getattr(row, "storage_path", None) or "").strip()
        if not path or not os.path.exists(path):
            raise ValueError("Belge dosyası sunucuda bulunamadı.")
        return send_file(path, as_attachment=True, download_name=(getattr(row, "original_filename", None) or "personel-belgesi"))
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
        return redirect(url_for("main.hr_personnel_operations", user_id=int(request.args.get("user_id") or 0) or None, scope=(request.args.get("scope") or "").strip() or None))


@main_bp.route("/hr-management/personnel-operations/note/save", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_note_save():
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_note_save", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("İşlem notu formu güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)

    try:
        user_id = int(request.form.get("user_id") or 0)
        user = _require_user_in_scope(user_id, scope_user_ids)
        note_id = int(request.form.get("note_id") or 0) or None
        row = _note_in_scope(note_id, scope_user_ids) if note_id else PersonnelProcessNote(user_id=user.id, created_by_id=getattr(current_user, "id", None))
        row.note_type = _normalize_text(request.form.get("note_type") or "ozluk", 50).lower() or "ozluk"
        row.priority = _normalize_text(request.form.get("priority") or "normal", 20).lower() or "normal"
        row.subject = _normalize_text(request.form.get("subject"), 255)
        row.note = _normalize_text(request.form.get("note"), 5000)
        row.status = _normalize_text(request.form.get("status") or "open", 30).lower() or "open"
        row.due_date = _parse_date(request.form.get("due_date"))
        row.is_private = _normalize_bool(request.form.get("is_private"))
        if row.status == "closed":
            row.resolved_at = utc_now()
        elif note_id and getattr(row, "status", None) != "closed":
            row.resolved_at = None
        if not row.subject or not row.note:
            raise ValueError("Konu ve not alanı zorunludur.")
        db.session.add(row)
        db.session.commit()
        flash(f"{user.full_name} için işlem notu kaydedildi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)


@main_bp.route("/hr-management/personnel-operations/note/<int:note_id>/toggle", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_note_toggle(note_id: int):
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_note_close", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("İşlem notu kapatma güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)

    try:
        row = _note_in_scope(note_id, scope_user_ids)
        user_id: int | None = int(row.user_id)
        if (getattr(row, "status", None) or "open") == "closed":
            row.status = "open"
            row.resolved_at = None
            message = "İşlem notu tekrar açıldı."
        else:
            row.status = "closed"
            row.resolved_at = utc_now()
            message = "İşlem notu kapatıldı."
        db.session.add(row)
        db.session.commit()
        flash(message, "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
        user_id = _safe_int(request.form.get("user_id")) or None
    return _redirect_operations(hr_scope=hr_scope, user_id=user_id)


@main_bp.route("/hr-management/personnel-operations/note/<int:note_id>/delete", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_note_delete(note_id: int):
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_note_delete", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("İşlem notu silme güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)

    try:
        row = _note_in_scope(note_id, scope_user_ids)
        user_id: int | None = int(row.user_id)
        db.session.delete(row)
        db.session.commit()
        flash("İşlem notu kaldırıldı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
        user_id = _safe_int(request.form.get("user_id")) or None
    return _redirect_operations(hr_scope=hr_scope, user_id=user_id)


@main_bp.route("/hr-management/personnel-operations/status/save", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_status_save():
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_status_save", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("Durum geçmişi formu güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)

    try:
        user_id = int(request.form.get("user_id") or 0)
        user = _require_user_in_scope(user_id, scope_user_ids)
        status_id = int(request.form.get("status_id") or 0) or None
        row = _status_in_scope(status_id, scope_user_ids) if status_id else PersonnelStatusHistory(user_id=user.id, recorded_by_id=getattr(current_user, "id", None))
        row.event_type = _normalize_text(request.form.get("event_type") or "durum", 50).lower() or "durum"
        row.event_date = _parse_date(request.form.get("event_date"))
        row.effective_start_date = _parse_date(request.form.get("effective_start_date"))
        row.effective_end_date = _parse_date(request.form.get("effective_end_date"))
        row.previous_value = _normalize_text(request.form.get("previous_value"), 255) or None
        row.new_value = _normalize_text(request.form.get("new_value"), 255) or None
        row.summary = _normalize_text(request.form.get("summary"), 255)
        row.description = _normalize_text(request.form.get("description"), 5000) or None
        if not row.summary or not row.event_date:
            raise ValueError("Olay tarihi ve özet alanı zorunludur.")
        db.session.add(row)
        db.session.commit()
        flash(f"{user.full_name} için durum geçmişi kaydedildi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)


@main_bp.route("/hr-management/personnel-operations/status/<int:status_id>/delete", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_status_delete(status_id: int):
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_status_delete", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("Durum geçmişi silme güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")) or None)

    try:
        row = _status_in_scope(status_id, scope_user_ids)
        user_id: int | None = int(row.user_id)
        db.session.delete(row)
        db.session.commit()
        flash("Durum geçmişi kaydı kaldırıldı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
        user_id = _safe_int(request.form.get("user_id")) or None
    return _redirect_operations(hr_scope=hr_scope, user_id=user_id)


@main_bp.route("/hr-management/personnel-operations/validity-center")
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_validity_center():
    from app.services.hr_operations_enhancements import build_hr_document_validity_center_context

    hr_scope, scope_users, _ = _current_scope_bundle()
    payload = build_hr_document_validity_center_context(hr_scope, scope_users)
    return safe_render("hr_personnel_validity_center.html", **payload)


@main_bp.route("/hr-management/personnel-operations/position/save", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_position_save():
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_position_save", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("Pozisyon geçmişi güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")))
    try:
        user = _require_user_in_scope(_safe_int(request.form.get("user_id")), scope_user_ids)
        row_id = _safe_int(request.form.get("position_id"))
        row = None
        if row_id:
            row = PersonnelPositionHistory.query.filter(
                PersonnelPositionHistory.id == int(row_id),
                PersonnelPositionHistory.user_id.in_(list(scope_user_ids)),
            ).first()
            if not row:
                raise ValueError("Pozisyon geçmişi kaydı bu kapsam içinde bulunamadı.")
        if row is None:
            row = PersonnelPositionHistory(user_id=user.id, created_by_id=getattr(current_user, "id", None))

        position_title = _normalize_text(request.form.get("position_title"), 150)
        if not position_title:
            raise ValueError("Pozisyon / görev başlığı zorunludur.")

        start_date = _parse_date(request.form.get("start_date"))
        end_date = _parse_date(request.form.get("end_date"))
        if start_date and end_date and end_date < start_date:
            raise ValueError("Bitiş tarihi başlangıç tarihinden önce olamaz.")

        organization_unit = None
        organization_unit_id = _safe_int(request.form.get("organization_unit_id"))
        if organization_unit_id:
            organization_unit = db.session.get(OrganizationUnit, int(organization_unit_id))

        manager_user = None
        manager_user_id = _safe_int(request.form.get("manager_user_id"))
        if manager_user_id:
            manager_user = db.session.get(User, int(manager_user_id))

        row.position_title = position_title
        row.position_grade = _normalize_text(request.form.get("position_grade"), 50) or None
        row.assignment_type = _normalize_text(request.form.get("assignment_type"), 50).lower() or "atama"
        row.appointment_kind = _normalize_text(request.form.get("appointment_kind"), 50).lower() or None
        row.decision_no = _normalize_text(request.form.get("decision_no"), 120) or None
        row.start_date = start_date
        row.end_date = end_date
        row.reason = _normalize_text(request.form.get("reason"), 2000) or None
        row.organization_unit_id = organization_unit.id if organization_unit else None
        row.manager_user_id = manager_user.id if manager_user else None
        row.unit_name_snapshot = getattr(organization_unit, "name", None) if organization_unit else (_normalize_text(request.form.get("unit_name_snapshot"), 255) or None)
        row.parent_unit_name_snapshot = getattr(getattr(organization_unit, "parent", None), "name", None) if organization_unit else (_normalize_text(request.form.get("parent_unit_name_snapshot"), 255) or None)
        row.is_current = _normalize_bool(request.form.get("is_current"))

        if row.is_current:
            PersonnelPositionHistory.query.filter(
                PersonnelPositionHistory.user_id == user.id,
                PersonnelPositionHistory.id != getattr(row, "id", 0),
                PersonnelPositionHistory.is_current.is_(True),
            ).update({"is_current": False}, synchronize_session=False)
            if not row.end_date:
                row.end_date = None

        db.session.add(row)
        db.session.commit()
        flash("Pozisyon / görev geçmişi kaydı kaydedildi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")))


@main_bp.route("/hr-management/personnel-operations/position/<int:position_id>/delete", methods=["POST"])
@login_required
@manager_required
@menu_key_required("hr_leave_tracking")
def hr_personnel_position_delete(position_id: int):
    hr_scope, _, scope_user_ids = _current_scope_bundle()
    if not consume_form_token("hr_personnel_position_delete", request.form.get("form_token"), scope="hr_personnel_operations"):
        flash("Pozisyon geçmişi silme güvenlik doğrulaması başarısız oldu.", "danger")
        return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")))
    try:
        row = PersonnelPositionHistory.query.filter(
            PersonnelPositionHistory.id == int(position_id),
            PersonnelPositionHistory.user_id.in_(list(scope_user_ids)),
        ).first()
        if not row:
            raise ValueError("Pozisyon geçmişi kaydı bu kapsam içinde bulunamadı.")
        db.session.delete(row)
        db.session.commit()
        flash("Pozisyon / görev geçmişi kaydı silindi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("İşlem sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return _redirect_operations(hr_scope=hr_scope, user_id=_safe_int(request.form.get("user_id")))
