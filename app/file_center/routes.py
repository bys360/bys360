from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast

from flask import Response, flash, jsonify, redirect, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.file_center.mail_service import (
    mail_purpose_label,
    mail_status_label,
    send_file_request_email,
)
from app.file_center.maintenance_service import (
    build_admin_summary,
    expire_due_links_and_requests,
    maintenance_checklist,
    recalculate_quotas,
)
from app.file_center.permissions import (
    can_create_guest_links,
    can_create_guest_upload_requests,
    can_manage_file_center_admin,
    can_manage_file_center_quota_policy,
    can_manage_file_center_settings,
    can_read_other_users_files,
    can_use_chunk_upload,
    can_use_file_center,
    menu_context,
)
from app.file_center.services import (
    auto_scan_on_upload_enabled,
    block_file_item,
    can_download_file,
    cancel_chunk_upload_session,
    chunk_session_status_label,
    chunk_upload_enabled,
    chunk_upload_session_to_dict,
    clamav_enabled,
    create_chunk_upload_session,
    create_file_request,
    create_guest_link,
    create_or_update_quota_policy,
    create_transfer_package,
    deactivate_quota_policy,
    download_status_label,
    file_center_enabled,
    file_security_status_label,
    finalize_chunk_upload_session,
    find_file_request_by_token,
    find_share_link_by_token,
    format_bytes,
    guest_links_enabled,
    guest_uploads_enabled,
    is_admin_like,
    link_status_label,
    list_user_upload_sessions,
    log_access,
    log_audit,
    quarantine_file_item,
    quota_dashboard_summary,
    quota_policy_enabled,
    quota_scope_label,
    quota_status_label,
    record_guest_download,
    record_guest_request_upload,
    release_quarantined_file,
    request_max_bytes,
    request_status_label,
    run_security_scan,
    save_uploaded_file,
    scan_label,
    scan_pending_files,
    secure_file_path,
    security_scan_enabled,
    security_summary,
    soft_delete_file,
    upload_chunk_part,
    user_quota_summary,
    validate_upload_request,
    verify_share_password,
)
from app.file_center.settings_service import (
    ensure_file_center_settings_defaults,
    setting_to_display_value,
    settings_grouped,
    update_settings_from_form,
)
from app.models.file_center_models import (
    FileAccessLog,
    FileAuditLog,
    FileCenterMailLog,
    FileDownloadLog,
    FileQuotaUsage,
    FileRequest,
    FileRequestUpload,
    FileSecurityScan,
    FileShareLink,
    FileStorageItem,
    FileTransfer,
    FileTransferItem,
    FileUploadSession,
)
from app.route_registry import main_bp
from app.route_support import safe_db_rollback, safe_render

logger = logging.getLogger(__name__)


def _access_denied_response():
    try:
        from app.route_support import render_access_denied

        return render_access_denied()
    except Exception:
        logger.exception("Beklenmeyen hata")
        flash("Bu işlem için yetkiniz bulunmamaktadır.", "danger")
        return redirect(url_for("main.home"))


def _enabled_or_message():
    if not can_use_file_center(current_user):
        flash("Dosya Merkezi için yetkiniz bulunmamaktadır.", "danger")
        return False
    if file_center_enabled():
        return True
    flash("Dosya Merkezi şu anda kapalı. Sistem yöneticisi tarafından açıldığında kullanılabilir.", "warning")
    return False


def _can_manage_file(item: FileStorageItem) -> bool:
    return bool(current_user.is_authenticated and (item.owner_user_id == current_user.id or is_admin_like(current_user)))


def _can_read_file(item: FileStorageItem) -> bool:
    # F07b / D2: içerik (indirme, misafir bağlantısı) teknik rollere kapalı; bkz. can_read_other_users_files.
    return bool(current_user.is_authenticated and (item.owner_user_id == current_user.id or can_read_other_users_files(current_user)))


def _can_manage_request(row: FileRequest) -> bool:
    return bool(current_user.is_authenticated and (row.owner_user_id == current_user.id or is_admin_like(current_user)))


def _build_file_request_message(row: FileRequest) -> str:
    upload_url = url_for("main.file_center_guest_upload", token=row.public_token, _external=True) if row.public_token else "Bağlantı bulunamadı"
    recipient = row.recipient_name or "İlgili kişi"
    deadline = row.expires_at.strftime("%d.%m.%Y %H:%M") if row.expires_at else "Belirtilmedi"
    allowed = row.allowed_extensions or "Güvenlik nedeniyle engellenen dosya türleri dışındaki dosyalar"
    description = (row.description or "").strip()
    lines = [
        f"Sayın {recipient},",
        "",
        "BYS360 Dosya Merkezi üzerinden tarafınızdan dosya yüklemeniz istenmektedir.",
        "",
        f"Talep başlığı: {row.title}",
    ]
    if description:
        lines.extend(["", f"Açıklama: {description}"])
    lines.extend([
        "",
        f"Yükleme bağlantısı: {upload_url}",
        f"Son yükleme tarihi: {deadline}",
        f"Kabul edilen dosya türleri: {allowed}",
        "",
        "Lütfen yükleme şifresini bu bağlantıdan ayrı olarak size iletilen kanaldan kullanınız.",
        "Bağlantı süreli ve kayıtlıdır; yüklenen dosya BYS360 Dosya Merkezi’ne güvenli şekilde alınacaktır.",
        "",
        "İyi çalışmalar."
    ])
    return "\n".join(lines)



@main_bp.get("/file-center")
@login_required
def file_center_home():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    files = (
        FileStorageItem.query.filter_by(owner_user_id=current_user.id, is_deleted=False)
        .order_by(FileStorageItem.created_at.desc())
        .limit(100)
        .all()
    )
    quota = FileQuotaUsage.query.filter_by(user_id=current_user.id).one_or_none()
    links = (
        FileShareLink.query.join(FileStorageItem, FileShareLink.file_id == FileStorageItem.id)
        .filter(FileStorageItem.owner_user_id == current_user.id)
        .order_by(FileShareLink.created_at.desc())
        .limit(20)
        .all()
    )
    transfers = (
        FileTransfer.query.filter_by(owner_user_id=current_user.id)
        .order_by(FileTransfer.created_at.desc())
        .limit(10)
        .all()
    )
    request_count = FileRequest.query.filter_by(owner_user_id=current_user.id).count()
    return safe_render(
        "file_center/index.html",
        files=files,
        quota=quota,
        quota_summary=user_quota_summary(current_user),
        links=links,
        transfers=transfers,
        request_count=request_count,
        guest_links_enabled=guest_links_enabled(),
        format_bytes=format_bytes,
        scan_label=scan_label,
        link_status_label=link_status_label,
    )


@main_bp.post("/file-center/upload")
@login_required
def file_center_upload():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    uploaded = request.files.get("file")
    ok, message = validate_upload_request(uploaded)
    if not ok:
        flash(message, "danger")
        return redirect(url_for("main.file_center_home"))
    try:
        item = save_uploaded_file(uploaded, int(current_user.id))
        if security_scan_enabled() and auto_scan_on_upload_enabled():
            run_security_scan(item, actor_user_id=int(current_user.id), force=True)
        db.session.commit()
        flash(f"Dosya yüklendi ve güvenlik kontrolüne alındı: {item.original_filename}", "success")
    except ValueError as exc:
        safe_db_rollback()
        flash(str(exc), "danger")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        # BYS360 DEFECT AR: log_audit() yalnizca db.session.add() yapar,
        # commit etmez -- bu satirdan sonra bir commit yoktu, bu yuzden
        # basarisiz yukleme/indirme denemeleri (parola tahmini gibi
        # guvenlik-ilgili olaylar dahil) denetim kaydina hic yazilmiyordu.
        log_audit("file_upload_failed", message="Dosya yükleme sırasında teknik bir hata oluştu.", actor_user_id=int(current_user.id))
        db.session.commit()
        flash("Dosya yükleme sırasında beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    return redirect(url_for("main.file_center_home"))


@main_bp.get("/file-center/download/<int:file_id>")
@login_required
def file_center_download(file_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    item = FileStorageItem.query.get_or_404(file_id)
    if not _can_read_file(item):
        return _access_denied_response()
    try:
        ok, security_message = can_download_file(item)
        if not ok:
            flash(security_message, "danger")
            return redirect(url_for("main.file_center_home"))
        path = secure_file_path(item)
        log_access("file_download", file_id=item.id)
        db.session.add(FileDownloadLog(file_id=item.id, downloaded_by_user_id=current_user.id, status="success"))
        db.session.commit()
        return send_file(str(path), as_attachment=True, download_name=item.original_filename, mimetype=item.content_type or "application/octet-stream")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        # BYS360 DEFECT AR: bkz. file_center_upload() ayni not.
        log_audit("file_download_failed", file_id=item.id, message="Dosya indirme sırasında teknik bir hata oluştu.", actor_user_id=int(current_user.id))
        db.session.commit()
        flash("Dosya indirilemedi. Lütfen daha sonra tekrar deneyin veya sistem yöneticisine başvurun.", "danger")
        return redirect(url_for("main.file_center_home"))


@main_bp.post("/file-center/delete/<int:file_id>")
@login_required
def file_center_delete(file_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    item = FileStorageItem.query.get_or_404(file_id)
    if not _can_manage_file(item):
        return _access_denied_response()
    try:
        soft_delete_file(item, int(current_user.id))
        db.session.commit()
        flash("Dosya silindi. Aktif misafir bağlantıları kapatıldı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Dosya silinemedi.", "danger")
    return redirect(url_for("main.file_center_home"))


@main_bp.post("/file-center/share/<int:file_id>")
@login_required
def file_center_create_guest_link(file_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not guest_links_enabled():
        flash("Misafir indirme bağlantıları şu anda kapalı.", "warning")
        return redirect(url_for("main.file_center_home"))
    if not can_create_guest_links(current_user):
        return _access_denied_response()
    item = FileStorageItem.query.get_or_404(file_id)
    if not _can_read_file(item):
        return _access_denied_response()
    password = (request.form.get("password") or "").strip()
    if len(password) < 6:
        flash("Misafir link için en az 6 karakterli şifre girin.", "danger")
        return redirect(url_for("main.file_center_home"))
    try:
        days = int(request.form.get("days") or 7)
        max_downloads = int(request.form.get("max_downloads") or 5)
        link, token = create_guest_link(item, password, days=days, max_downloads=max_downloads)
        db.session.commit()
        guest_url = url_for("main.file_center_guest_download", token=token, _external=True)
        flash(f"Misafir bağlantısı oluşturuldu. Bağlantı: {guest_url} | Şifreyi ayrı kanaldan paylaşın.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Misafir bağlantısı oluşturulamadı.", "danger")
    return redirect(url_for("main.file_center_home"))


@main_bp.post("/file-center/share/<int:link_id>/revoke")
@login_required
def file_center_revoke_guest_link(link_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    link = FileShareLink.query.get_or_404(link_id)
    if not _can_manage_file(link.file):
        return _access_denied_response()
    link.is_active = False
    link.revoked_at = datetime.utcnow()
    link.revoked_by_user_id = current_user.id
    log_audit("guest_link_revoked", file_id=link.file_id, message="Misafir bağlantısı iptal edildi.")
    db.session.commit()
    flash("Misafir bağlantısı iptal edildi.", "success")
    return redirect(url_for("main.file_center_home"))


@main_bp.get("/file-center/transfers")
@login_required
def file_center_transfers():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    files = (
        FileStorageItem.query.filter_by(owner_user_id=current_user.id, is_deleted=False)
        .order_by(FileStorageItem.created_at.desc())
        .limit(100)
        .all()
    )
    transfers = (
        FileTransfer.query.filter_by(owner_user_id=current_user.id)
        .order_by(FileTransfer.created_at.desc())
        .limit(50)
        .all()
    )
    transfer_items: dict[int, list[Any]] = {}
    if transfers:
        ids = [x.id for x in transfers]
        rows = FileTransferItem.query.filter(FileTransferItem.transfer_id.in_(ids)).all()
        for row in rows:
            transfer_items.setdefault(row.transfer_id, []).append(row.file)
    return safe_render("file_center/transfers.html", files=files, transfers=transfers, transfer_items=transfer_items, format_bytes=format_bytes)


@main_bp.post("/file-center/transfers/create")
@login_required
def file_center_create_transfer():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    try:
        transfer = create_transfer_package(
            owner_user_id=int(current_user.id),
            title=request.form.get("title") or "Dosya Transferi",
            message=request.form.get("message"),
            file_ids=[int(x) for x in request.form.getlist("file_ids") if str(x).strip()],
            recipient_emails=request.form.get("recipient_emails"),
        )
        db.session.commit()
        flash(f"Transfer paketi oluşturuldu: {transfer.title}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Transfer paketi oluşturulamadı.", "danger")
    return redirect(url_for("main.file_center_transfers"))


@main_bp.get("/file-center/requests")
@login_required
def file_center_requests():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    requests = (
        FileRequest.query.filter_by(owner_user_id=current_user.id)
        .order_by(FileRequest.created_at.desc())
        .limit(100)
        .all()
    )
    uploads_by_request: dict[int, list[FileRequestUpload]] = {}
    mail_logs_by_request: dict[int, list[FileCenterMailLog]] = {}
    if requests:
        ids = [x.id for x in requests]
        rows = FileRequestUpload.query.filter(FileRequestUpload.request_id.in_(ids)).order_by(FileRequestUpload.created_at.desc()).all()
        for row in rows:
            uploads_by_request.setdefault(row.request_id, []).append(row)
        mail_rows = FileCenterMailLog.query.filter(FileCenterMailLog.request_id.in_(ids)).order_by(FileCenterMailLog.created_at.desc()).limit(200).all()
        for row in mail_rows:
            mail_logs_by_request.setdefault(row.request_id, []).append(row)
    return safe_render(
        "file_center/requests.html",
        requests=requests,
        uploads_by_request=uploads_by_request,
        mail_logs_by_request=mail_logs_by_request,
        request_status_label=request_status_label,
        mail_status_label=mail_status_label,
        mail_purpose_label=mail_purpose_label,
        format_bytes=format_bytes,
    )


@main_bp.post("/file-center/requests/create")
@login_required
def file_center_create_request():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not guest_uploads_enabled():
        flash("Misafir dosya yükleme bağlantıları şu anda kapalı.", "warning")
        return redirect(url_for("main.file_center_requests"))
    if not can_create_guest_upload_requests(current_user):
        return _access_denied_response()
    password = (request.form.get("password") or "").strip()
    if len(password) < 6:
        flash("Dosya isteği için en az 6 karakterli şifre girin.", "danger")
        return redirect(url_for("main.file_center_requests"))
    try:
        req, token = create_file_request(
            owner_user_id=int(current_user.id),
            title=request.form.get("title") or "Dosya Talebi",
            description=request.form.get("description"),
            recipient_name=request.form.get("recipient_name"),
            recipient_email=request.form.get("recipient_email"),
            password=password,
            days=int(request.form.get("days") or 7),
            max_file_gb=float(request.form.get("max_file_gb") or 5),
            allowed_extensions=request.form.get("allowed_extensions"),
        )
        db.session.commit()
        upload_url = url_for("main.file_center_guest_upload", token=token, _external=True)
        flash(f"Dosya isteği oluşturuldu. Yükleme bağlantısı: {upload_url} | Şifreyi ayrı kanaldan paylaşın.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Dosya isteği oluşturulamadı.", "danger")
    return redirect(url_for("main.file_center_requests"))


@main_bp.post("/file-center/requests/<int:request_id>/close")
@login_required
def file_center_close_request(request_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    row = FileRequest.query.get_or_404(request_id)
    if not _can_manage_request(row):
        return _access_denied_response()
    row.status = "closed"
    row.closed_at = datetime.utcnow()
    log_audit("file_request_closed", message=f"Dosya talebi kapatıldı: {row.title}")
    db.session.commit()
    flash("Dosya talebi kapatıldı.", "success")
    return redirect(url_for("main.file_center_requests"))


@main_bp.post("/file-center/requests/<int:request_id>/revoke")
@login_required
def file_center_revoke_request(request_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    row = FileRequest.query.get_or_404(request_id)
    if not _can_manage_request(row):
        return _access_denied_response()
    row.status = "revoked"
    row.revoked_at = datetime.utcnow()
    row.revoked_by_user_id = current_user.id
    log_audit("file_request_revoked", message=f"Dosya talebi iptal edildi: {row.title}")
    db.session.commit()
    flash("Dosya talebi iptal edildi.", "success")
    return redirect(url_for("main.file_center_requests"))


@main_bp.get("/file-center/requests/<int:request_id>/message.txt")
@login_required
def file_center_request_message(request_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    row = FileRequest.query.get_or_404(request_id)
    if not _can_manage_request(row):
        return _access_denied_response()
    text = _build_file_request_message(row)
    return Response(text, mimetype="text/plain; charset=utf-8")


@main_bp.post("/file-center/requests/<int:request_id>/reminder")
@login_required
def file_center_prepare_request_reminder(request_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    row = FileRequest.query.get_or_404(request_id)
    if not _can_manage_request(row):
        return _access_denied_response()
    if row.status != "open":
        flash("Kapalı veya iptal edilmiş dosya isteği için hatırlatma hazırlanamaz.", "warning")
        return redirect(url_for("main.file_center_requests"))
    _build_file_request_message(row)
    log_audit("file_request_reminder_prepared", message=f"Dosya isteği hatırlatma metni hazırlandı: {row.title}")
    db.session.commit()
    flash("Dosya isteği hatırlatma metni hazırlandı. Metni açıp e-posta veya mesaj olarak paylaşabilirsiniz.", "success")
    return redirect(url_for("main.file_center_requests", reminder_request_id=row.id))


@main_bp.post("/file-center/requests/<int:request_id>/send-email")
@login_required
def file_center_send_request_email_route(request_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    row = FileRequest.query.get_or_404(request_id)
    if not _can_manage_request(row):
        return _access_denied_response()
    if row.status != "open":
        flash("Kapalı veya iptal edilmiş dosya isteği için e-posta gönderilemez.", "warning")
        return redirect(url_for("main.file_center_requests"))
    if not row.recipient_email:
        flash("Bu dosya isteğinde alıcı e-posta adresi bulunmadığı için gönderim yapılamadı.", "warning")
        return redirect(url_for("main.file_center_requests"))
    purpose = request.form.get("purpose") or "request_invitation"
    if purpose not in {"request_invitation", "manual_reminder"}:
        purpose = "request_invitation"
    upload_url = url_for("main.file_center_guest_upload", token=row.public_token, _external=True) if row.public_token else ""
    try:
        mail_log = send_file_request_email(row, upload_url=upload_url, purpose=purpose, actor_user_id=int(current_user.id))
        log_audit(
            "file_request_email_sent" if mail_log.status == "sent" else "file_request_email_not_sent",
            message=f"Dosya isteği e-posta gönderimi: {row.title} / {mail_log.status}",
            actor_user_id=int(current_user.id),
        )
        db.session.commit()
        if mail_log.status == "sent":
            flash("E-posta gönderildi ve mail log kaydı oluşturuldu.", "success")
        elif mail_log.status == "skipped":
            flash(f"E-posta gönderilmedi; log kaydı oluşturuldu. Neden: {mail_log.error_message}", "warning")
        else:
            flash(f"E-posta gönderimi başarısız oldu; log kaydı oluşturuldu. Hata: {mail_log.error_message}", "danger")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("E-posta işlemi sırasında hata oluştu.", "danger")
    return redirect(url_for("main.file_center_requests"))




@main_bp.get("/file-center/security")
@login_required
def file_center_security():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    pending_files = (
        FileStorageItem.query.filter_by(is_deleted=False, scan_status="pending")
        .order_by(FileStorageItem.created_at.asc())
        .limit(50)
        .all()
    )
    quarantine_files = (
        FileStorageItem.query.filter(FileStorageItem.is_deleted.is_(False), FileStorageItem.scan_status.in_(["quarantined", "blocked", "failed"]))
        .order_by(FileStorageItem.updated_at.desc())
        .limit(50)
        .all()
    )
    recent_scans = FileSecurityScan.query.order_by(FileSecurityScan.created_at.desc()).limit(100).all()
    return safe_render(
        "file_center/security.html",
        summary=security_summary(),
        pending_files=pending_files,
        quarantine_files=quarantine_files,
        recent_scans=recent_scans,
        format_bytes=format_bytes,
        file_security_status_label=file_security_status_label,
        clamav_enabled=clamav_enabled,
    )


@main_bp.post("/file-center/security/scan-pending")
@login_required
def file_center_security_scan_pending():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    try:
        result = scan_pending_files(limit=200, actor_user_id=int(current_user.id))
        db.session.commit()
        flash(f"Güvenlik taraması tamamlandı. Toplam: {result['total']} · Güvenli: {result['clean']} · Karantina: {result['quarantined']} · Başarısız: {result['failed']}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Güvenlik taraması tamamlanamadı.", "danger")
    return redirect(url_for("main.file_center_security"))


@main_bp.post("/file-center/security/scan/<int:file_id>")
@login_required
def file_center_security_scan_file(file_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    item = FileStorageItem.query.get_or_404(file_id)
    try:
        scan = run_security_scan(item, actor_user_id=int(current_user.id), force=True)
        db.session.commit()
        flash(f"Dosya tarandı: {item.original_filename} · Durum: {file_security_status_label(scan.status)}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Dosya taranamadı.", "danger")
    return redirect(url_for("main.file_center_security"))


@main_bp.post("/file-center/security/quarantine/<int:file_id>")
@login_required
def file_center_security_quarantine_file(file_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    item = FileStorageItem.query.get_or_404(file_id)
    try:
        reason = request.form.get("reason") or "Manuel güvenlik incelemesi için karantinaya alındı."
        quarantine_file_item(item, actor_user_id=int(current_user.id), reason=reason)
        db.session.commit()
        flash("Dosya karantinaya alındı ve aktif misafir bağlantıları kapatıldı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Dosya karantinaya alınamadı.", "danger")
    return redirect(url_for("main.file_center_security"))


@main_bp.post("/file-center/security/release/<int:file_id>")
@login_required
def file_center_security_release_file(file_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    item = FileStorageItem.query.get_or_404(file_id)
    try:
        reason = request.form.get("reason") or "Manuel inceleme sonrası güvenli kabul edildi."
        release_quarantined_file(item, actor_user_id=int(current_user.id), reason=reason)
        db.session.commit()
        flash("Dosya karantinadan çıkarıldı ve güvenli olarak işaretlendi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Dosya karantinadan çıkarılamadı.", "danger")
    return redirect(url_for("main.file_center_security"))


@main_bp.post("/file-center/security/block/<int:file_id>")
@login_required
def file_center_security_block_file(file_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    item = FileStorageItem.query.get_or_404(file_id)
    try:
        reason = request.form.get("reason") or "Manuel inceleme sonrası engellendi."
        block_file_item(item, actor_user_id=int(current_user.id), reason=reason)
        db.session.commit()
        flash("Dosya engellendi ve aktif misafir bağlantıları kapatıldı.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Dosya engellenemedi.", "danger")
    return redirect(url_for("main.file_center_security"))


@main_bp.get("/file-center/logs")
@login_required
def file_center_logs():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    file_ids = [x.id for x in FileStorageItem.query.with_entities(FileStorageItem.id).filter_by(owner_user_id=current_user.id).all()]
    downloads = []
    audits = []
    accesses = []
    if file_ids:
        downloads = FileDownloadLog.query.filter(FileDownloadLog.file_id.in_(file_ids)).order_by(FileDownloadLog.created_at.desc()).limit(100).all()
        audits = FileAuditLog.query.filter(FileAuditLog.file_id.in_(file_ids)).order_by(FileAuditLog.created_at.desc()).limit(100).all()
        accesses = FileAccessLog.query.filter(FileAccessLog.file_id.in_(file_ids)).order_by(FileAccessLog.created_at.desc()).limit(100).all()
    return safe_render("file_center/logs.html", downloads=downloads, audits=audits, accesses=accesses, download_status_label=download_status_label)


@main_bp.get("/file-center/admin")
@login_required
def file_center_admin_dashboard():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    summary = build_admin_summary()
    checklist = maintenance_checklist()
    return safe_render(
        "file_center/admin.html",
        summary=summary,
        checklist=checklist,
        format_bytes=format_bytes,
        mail_status_label=mail_status_label,
    )


@main_bp.get("/file-center/maintenance")
@login_required
def file_center_maintenance():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    return safe_render(
        "file_center/maintenance.html",
        summary=build_admin_summary(),
        checklist=maintenance_checklist(),
        format_bytes=format_bytes,
    )


@main_bp.post("/file-center/maintenance/recalculate-quotas")
@login_required
def file_center_maintenance_recalculate_quotas():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    try:
        result = recalculate_quotas(actor_user_id=int(current_user.id))
        db.session.commit()
        flash(f"Kota bilgileri güncellendi. Kullanıcı: {result['users']} · Dosya: {result['files']}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Kota güncelleme işlemi tamamlanamadı.", "danger")
    return redirect(url_for("main.file_center_maintenance"))


@main_bp.post("/file-center/maintenance/expire")
@login_required
def file_center_maintenance_expire():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_admin(current_user):
        return _access_denied_response()
    try:
        result = expire_due_links_and_requests(actor_user_id=int(current_user.id))
        db.session.commit()
        flash(f"Süresi dolan kayıtlar kapatıldı. Link: {result['links']} · İstek: {result['requests']}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Bakım işlemi tamamlanamadı.", "danger")
    return redirect(url_for("main.file_center_maintenance"))



@main_bp.get("/file-center/quota")
@login_required
def file_center_quota():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    summary = user_quota_summary(current_user)
    admin_summary = quota_dashboard_summary() if is_admin_like(current_user) else None
    return safe_render(
        "file_center/quota.html",
        summary=summary,
        admin_summary=admin_summary,
        format_bytes=format_bytes,
        quota_scope_label=quota_scope_label,
        quota_status_label=quota_status_label,
        quota_policy_enabled=quota_policy_enabled(),
        is_admin=is_admin_like(current_user),
    )


@main_bp.post("/file-center/quota/policy")
@login_required
def file_center_quota_policy_save():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_quota_policy(current_user):
        return _access_denied_response()
    try:
        create_or_update_quota_policy(
            scope_type=request.form.get("scope_type") or "global",
            scope_value=request.form.get("scope_value"),
            label=request.form.get("label") or "Dosya Merkezi Kota Politikası",
            max_storage_gb=float(request.form.get("max_storage_gb") or 25),
            max_single_file_gb=float(request.form.get("max_single_file_gb") or 5),
            max_transfer_gb=float(request.form.get("max_transfer_gb") or 20),
            warning_threshold_percent=int(request.form.get("warning_threshold_percent") or 80),
            hard_stop_enabled=bool(request.form.get("hard_stop_enabled")),
            actor_user_id=int(current_user.id),
            notes=request.form.get("notes"),
        )
        db.session.commit()
        flash("Kota politikası kaydedildi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Kota politikası kaydedilemedi.", "danger")
    return redirect(url_for("main.file_center_quota"))


@main_bp.post("/file-center/quota/policy/<int:policy_id>/deactivate")
@login_required
def file_center_quota_policy_deactivate(policy_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_quota_policy(current_user):
        return _access_denied_response()
    try:
        deactivate_quota_policy(policy_id, actor_user_id=int(current_user.id))
        db.session.commit()
        flash("Kota politikası pasifleştirildi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Kota politikası pasifleştirilemedi.", "danger")
    return redirect(url_for("main.file_center_quota"))


@main_bp.get("/file-center/chunk-upload")
@login_required
def file_center_chunk_upload():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_use_chunk_upload(current_user):
        return _access_denied_response()
    sessions = list_user_upload_sessions(int(current_user.id))
    return safe_render(
        "file_center/chunk_upload.html",
        sessions=sessions,
        quota_summary=user_quota_summary(current_user),
        chunk_upload_enabled=chunk_upload_enabled(),
        chunk_session_status_label=chunk_session_status_label,
        format_bytes=format_bytes,
    )


@main_bp.post("/file-center/chunk-upload/session")
@login_required
def file_center_chunk_upload_session_create():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_use_chunk_upload(current_user):
        return _access_denied_response()
    try:
        total_size_mb = float(request.form.get("total_size_mb") or 0)
        chunk_size_mb = float(request.form.get("chunk_size_mb") or 10)
        session, _token = create_chunk_upload_session(
            owner_user_id=int(current_user.id),
            original_filename=request.form.get("original_filename") or "büyük_dosya",
            total_size_bytes=int(total_size_mb * 1024 * 1024),
            chunk_size_bytes=int(chunk_size_mb * 1024 * 1024),
            sha256_hash=request.form.get("sha256_hash"),
        )
        db.session.commit()
        flash(f"Parçalı yükleme oturumu hazırlandı. Parça sayısı: {session.total_chunks}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Parçalı yükleme oturumu oluşturulamadı.", "danger")
    return redirect(url_for("main.file_center_chunk_upload"))


@main_bp.post("/file-center/chunk-upload/session/<int:session_id>/cancel")
@login_required
def file_center_chunk_upload_session_cancel(session_id: int):
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    session = FileUploadSession.query.get_or_404(session_id)
    if session.owner_user_id != current_user.id and not is_admin_like(current_user):
        return _access_denied_response()
    try:
        cancel_chunk_upload_session(session_id, actor_user_id=int(current_user.id))
        db.session.commit()
        flash("Parçalı yükleme oturumu iptal edildi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Parçalı yükleme oturumu iptal edilemedi.", "danger")
    return redirect(url_for("main.file_center_chunk_upload"))



@main_bp.post("/file-center/chunk-upload/session-json")
@login_required
def file_center_chunk_upload_session_create_json():
    if not _enabled_or_message():
        return jsonify({"ok": False, "message": "Dosya Merkezi kapalı."}), 403
    if not can_use_chunk_upload(current_user):
        return jsonify({"ok": False, "message": "Bu işlem için yetkiniz bulunmamaktadır."}), 403
    try:
        total_size_bytes = int(request.form.get("total_size_bytes") or 0)
        chunk_size_bytes = int(request.form.get("chunk_size_bytes") or 10485760)
        session, _token = create_chunk_upload_session(
            owner_user_id=int(current_user.id),
            original_filename=request.form.get("original_filename") or "büyük_dosya",
            total_size_bytes=total_size_bytes,
            chunk_size_bytes=chunk_size_bytes,
            sha256_hash=request.form.get("sha256_hash"),
        )
        db.session.commit()
        return jsonify({"ok": True, "session": chunk_upload_session_to_dict(session)})
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "message": "Parçalı yükleme oturumu oluşturulamadı."}), 400


@main_bp.get("/file-center/chunk-upload/session/<int:session_id>/status")
@login_required
def file_center_chunk_upload_session_status(session_id: int):
    if not _enabled_or_message():
        return jsonify({"ok": False, "message": "Dosya Merkezi kapalı."}), 403
    session = FileUploadSession.query.get_or_404(session_id)
    if session.owner_user_id != current_user.id and not is_admin_like(current_user):
        return jsonify({"ok": False, "message": "Bu yükleme oturumuna erişim yetkiniz bulunmamaktadır."}), 403
    return jsonify({"ok": True, "session": chunk_upload_session_to_dict(session)})


@main_bp.post("/file-center/chunk-upload/session/<int:session_id>/chunk/<int:chunk_index>")
@login_required
def file_center_chunk_upload_part(session_id: int, chunk_index: int):
    if not _enabled_or_message():
        return jsonify({"ok": False, "message": "Dosya Merkezi kapalı."}), 403
    try:
        part = request.files.get("chunk")
        upload_chunk_part(session_id=session_id, owner_user_id=int(current_user.id), chunk_index=chunk_index, file_storage=part)
        db.session.commit()
        session = FileUploadSession.query.get_or_404(session_id)
        return jsonify({"ok": True, "session": chunk_upload_session_to_dict(session)})
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "message": "Parça yüklenemedi."}), 400


@main_bp.post("/file-center/chunk-upload/session/<int:session_id>/finalize")
@login_required
def file_center_chunk_upload_finalize(session_id: int):
    if not _enabled_or_message():
        return jsonify({"ok": False, "message": "Dosya Merkezi kapalı."}), 403
    try:
        item = finalize_chunk_upload_session(session_id=session_id, owner_user_id=int(current_user.id))
        db.session.commit()
        return jsonify({"ok": True, "file_id": item.id, "message": "Dosya başarıyla birleştirildi ve doğrulandı."})
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        return jsonify({"ok": False, "message": "Dosya birleştirme ve doğrulama tamamlanamadı."}), 400





@main_bp.get("/file-center/settings")
@login_required
def file_center_settings():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_settings(current_user):
        return _access_denied_response()
    ensure_file_center_settings_defaults(actor_user_id=int(current_user.id))
    db.session.commit()
    return safe_render(
        "file_center/settings.html",
        grouped=settings_grouped(),
        setting_to_display_value=setting_to_display_value,
        menu=menu_context(current_user),
    )


@main_bp.post("/file-center/settings")
@login_required
def file_center_settings_save():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_settings(current_user):
        return _access_denied_response()
    try:
        changed = update_settings_from_form(request.form, actor_user_id=int(current_user.id))
        log_audit("file_center_settings_updated", message=f"Dosya Merkezi ayarları güncellendi. Değişen alan: {changed}", actor_user_id=int(current_user.id))
        db.session.commit()
        flash(f"Dosya Merkezi ayarları güncellendi. Değişen alan: {changed}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Dosya Merkezi ayarları kaydedilemedi.", "danger")
    return redirect(url_for("main.file_center_settings"))


@main_bp.post("/file-center/settings/defaults")
@login_required
def file_center_settings_defaults():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    if not can_manage_file_center_settings(current_user):
        return _access_denied_response()
    try:
        result = ensure_file_center_settings_defaults(actor_user_id=int(current_user.id))
        log_audit("file_center_settings_defaults", message=f"Varsayılan ayarlar kontrol edildi: {result}", actor_user_id=int(current_user.id))
        db.session.commit()
        flash(f"Varsayılan ayarlar kontrol edildi. Yeni: {result['created']} · Güncellenen: {result['updated']}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Varsayılan ayarlar oluşturulamadı.", "danger")
    return redirect(url_for("main.file_center_settings"))


@main_bp.route("/guest/files/<token>", methods=["GET", "POST"])
def file_center_guest_download(token: str):
    if not guest_links_enabled():
        return safe_render("file_center/guest_download.html", error="Misafir indirme bağlantıları şu anda kapalı.", link=None, format_bytes=format_bytes)
    link = find_share_link_by_token(token)
    if link is None or not link.is_available():
        return safe_render("file_center/guest_download.html", error="Bağlantı geçersiz, süresi dolmuş veya indirme limiti dolmuş.", link=None, format_bytes=format_bytes)
    if request.method == "POST":
        password = request.form.get("password") or ""
        if not verify_share_password(link, password):
            record_guest_download(link, status="wrong_password")
            db.session.commit()
            flash("Şifre hatalı.", "danger")
            return safe_render("file_center/guest_download.html", error=None, link=link, format_bytes=format_bytes)
        try:
            ok, security_message = can_download_file(cast(FileStorageItem, link.file))
            if not ok:
                record_guest_download(link, status="blocked_by_security")
                db.session.commit()
                return safe_render("file_center/guest_download.html", error=security_message, link=None, format_bytes=format_bytes)
            path = secure_file_path(cast(FileStorageItem, link.file))
            record_guest_download(link, status="success")
            db.session.commit()
            return send_file(str(path), as_attachment=True, download_name=link.file.original_filename, mimetype=link.file.content_type or "application/octet-stream")
        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            safe_db_rollback()
            # BYS360 DEFECT AR: bkz. file_center_upload() ayni not -- bu
            # yol, tekrarlanan hatali misafir indirme denemeleri (parola
            # tahmini olasi gostergesi) icin ozellikle onemlidir.
            log_audit("guest_file_download_failed", file_id=link.file_id, message="Misafir indirme sırasında teknik bir hata oluştu.", actor_user_id=None)
            db.session.commit()
            return safe_render("file_center/guest_download.html", error="Dosya şu anda indirilemedi. Lütfen bağlantıyı gönderen birimle iletişime geçin.", link=None, format_bytes=format_bytes)
    return safe_render("file_center/guest_download.html", error=None, link=link, format_bytes=format_bytes)


@main_bp.route("/guest/upload/<token>", methods=["GET", "POST"])
def file_center_guest_upload(token: str):
    if not guest_uploads_enabled():
        return safe_render("file_center/guest_upload.html", error="Misafir dosya yükleme bağlantıları şu anda kapalı.", request_row=None, format_bytes=format_bytes)
    row = find_file_request_by_token(token)
    if row is None or not row.is_available():
        return safe_render("file_center/guest_upload.html", error="Yükleme bağlantısı geçersiz, kapalı veya süresi dolmuş.", request_row=None, format_bytes=format_bytes)
    if request.method == "POST":
        try:
            file_storage = request.files.get("file")
            item = record_guest_request_upload(
                row,
                file_storage,
                password=request.form.get("password") or "",
                guest_name=request.form.get("guest_name"),
                guest_email=request.form.get("guest_email"),
            )
            if security_scan_enabled() and auto_scan_on_upload_enabled():
                run_security_scan(item, actor_user_id=None, force=True)
            db.session.commit()
            flash(f"Dosya başarıyla yüklendi: {item.original_filename}", "success")
            return safe_render("file_center/guest_upload.html", error=None, request_row=row, uploaded=True, format_bytes=format_bytes, request_max_bytes=request_max_bytes)
        except ValueError as exc:
            safe_db_rollback()
            flash(str(exc), "danger")
            return safe_render("file_center/guest_upload.html", error=None, request_row=row, uploaded=False, format_bytes=format_bytes, request_max_bytes=request_max_bytes)
        except Exception as exc:
            logger.exception("Beklenmeyen hata: %s", exc)
            safe_db_rollback()
            # BYS360 DEFECT AR: bkz. file_center_upload() ayni not.
            log_audit("guest_file_upload_failed", message="Misafir yükleme sırasında teknik bir hata oluştu.", actor_user_id=None)
            db.session.commit()
            flash("Dosya şu anda yüklenemedi. Lütfen tekrar deneyin veya bağlantıyı gönderen birimle iletişime geçin.", "danger")
            return safe_render("file_center/guest_upload.html", error=None, request_row=row, uploaded=False, format_bytes=format_bytes, request_max_bytes=request_max_bytes)
    return safe_render("file_center/guest_upload.html", error=None, request_row=row, uploaded=False, format_bytes=format_bytes, request_max_bytes=request_max_bytes)

# BYS360_FILE_CENTER_ROLE_MATRIX_V1KD_BEGIN
@main_bp.get("/file-center/settings/roles")
@login_required
def file_center_role_matrix():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    from app.file_center.permissions import (
        PERMISSION_FIELDS,
        can_manage_file_center_role_matrix,
        ensure_file_center_role_matrix_defaults,
        role_matrix_rows,
    )
    if not can_manage_file_center_role_matrix(current_user):
        return _access_denied_response()
    ensure_file_center_role_matrix_defaults(actor_user_id=int(current_user.id))
    db.session.commit()
    return safe_render(
        "file_center/role_matrix.html",
        rows=role_matrix_rows(),
        permission_fields=PERMISSION_FIELDS,
        menu=menu_context(current_user),
    )


@main_bp.post("/file-center/settings/roles")
@login_required
def file_center_role_matrix_save():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    from app.file_center.permissions import (
        can_manage_file_center_role_matrix,
        update_role_matrix_from_form,
    )
    if not can_manage_file_center_role_matrix(current_user):
        return _access_denied_response()
    try:
        changed = update_role_matrix_from_form(request.form, actor_user_id=int(current_user.id))
        log_audit("file_center_role_matrix_updated", message=f"Dosya Merkezi rol matrisi güncellendi. Değişen alan: {changed}", actor_user_id=int(current_user.id))
        db.session.commit()
        flash(f"Dosya Merkezi rol matrisi güncellendi. Değişen alan: {changed}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Rol matrisi kaydedilemedi.", "danger")
    return redirect(url_for("main.file_center_role_matrix"))


@main_bp.post("/file-center/settings/roles/defaults")
@login_required
def file_center_role_matrix_defaults():
    if not _enabled_or_message():
        return redirect(url_for("main.home"))
    from app.file_center.permissions import (
        can_manage_file_center_role_matrix,
        ensure_file_center_role_matrix_defaults,
    )
    if not can_manage_file_center_role_matrix(current_user):
        return _access_denied_response()
    try:
        result = ensure_file_center_role_matrix_defaults(actor_user_id=int(current_user.id))
        log_audit("file_center_role_matrix_defaults", message=f"Varsayılan rol matrisi kontrol edildi: {result}", actor_user_id=int(current_user.id))
        db.session.commit()
        flash(f"Varsayılan rol matrisi kontrol edildi. Yeni: {result['created']} · Güncellenen: {result['updated']}", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        safe_db_rollback()
        flash("Varsayılan rol matrisi oluşturulamadı.", "danger")
    return redirect(url_for("main.file_center_role_matrix"))
# BYS360_FILE_CENTER_ROLE_MATRIX_V1KD_END

