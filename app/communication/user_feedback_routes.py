from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_hex

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import (
    SupportCategory,
    SupportTicket,
    SupportTicketMessage,
    SupportTicketStatusHistory,
)
from app.route_registry import main_bp
from app.route_support import safe_db_rollback, safe_render, sanitize_free_text
from app.security.upload_security import UploadValidationError
from app.services.bys360_notification_bridge import notify_user_feedback_created
from app.support.routes import (
    SUPPORT_MODULE_CHOICES,
    _store_ticket_attachment,
    _support_tables_ready,
)

logger = logging.getLogger(__name__)

"""BYS360 kullanıcı geri bildirim merkezi.

Bu route ailesi, ekran hatası, eksik/geliştirme önerisi, tebrik ve teşekkür
kayıtlarını mevcut Destek & Talep Yönetimi omurgasına güvenli biçimde bağlar.
Ayrı ve kopuk bir veri adası oluşturmaz; kayıtlar destek tablolarında izlenebilir,
atanabilir ve kapatılabilir kalır.
"""


@dataclass(frozen=True)
class FeedbackKind:
    key: str
    label: str
    description: str
    icon: str
    ticket_type: str
    priority: str
    category_name: str


BYS360_FEEDBACK_KIND_CHOICES: tuple[FeedbackKind, ...] = (
    FeedbackKind(
        key="screen_error",
        label="Ekran Hatası",
        description="Açılmayan sayfa, bozuk görünüm, yanlış çalışan buton veya hata mesajı.",
        icon="fa-solid fa-triangle-exclamation",
        ticket_type="bug",
        priority="high",
        category_name="Hata Bildirimi",
    ),
    FeedbackKind(
        key="missing_feature",
        label="Eksik / Geliştirme Önerisi",
        description="Eksik görülen alan, yeni ihtiyaç veya iyileştirme fikri.",
        icon="fa-solid fa-lightbulb",
        ticket_type="enhancement",
        priority="normal",
        category_name="Geliştirme Talebi",
    ),
    FeedbackKind(
        key="usability",
        label="Kullanım Kolaylığı",
        description="Daha sade, daha anlaşılır veya daha hızlı kullanılmasını istediğiniz alan.",
        icon="fa-solid fa-wand-magic-sparkles",
        ticket_type="ui",
        priority="normal",
        category_name="Geliştirme Talebi",
    ),
    FeedbackKind(
        key="praise",
        label="Tebrik",
        description="Beğendiğiniz ekran, çalışma veya katkı için tebrik mesajı.",
        icon="fa-solid fa-award",
        ticket_type="other",
        priority="low",
        category_name="Kullanıcı Geri Bildirimi",
    ),
    FeedbackKind(
        key="thanks",
        label="Teşekkür",
        description="Destek, çözüm, kolaylık veya katkı için teşekkür mesajı.",
        icon="fa-solid fa-heart",
        ticket_type="other",
        priority="low",
        category_name="Kullanıcı Geri Bildirimi",
    ),
    FeedbackKind(
        key="idea",
        label="Fikir / Öneri",
        description="BYS360’ın daha faydalı olması için paylaşmak istediğiniz genel öneri.",
        icon="fa-solid fa-seedling",
        ticket_type="enhancement",
        priority="normal",
        category_name="Geliştirme Talebi",
    ),
)


def _feedback_kind_map() -> dict[str, FeedbackKind]:
    return {item.key: item for item in BYS360_FEEDBACK_KIND_CHOICES}


def _feedback_kind_label(key: str | None) -> str:
    item = _feedback_kind_map().get((key or "").strip())
    return item.label if item else "Geri Bildirim"


def _feedback_ticket_no() -> str:
    stamp = datetime.now(UTC).replace(tzinfo=None).strftime("%Y%m%d")
    return f"GBD-{stamp}-{token_hex(3).upper()}"


FEEDBACK_SCHEMA_MIGRATION_REQUIRED_MESSAGE = (
    "Geri bildirim altyapısı hazır değil: destek tabloları için veritabanı migration/hazırlık işlemi "
    "tamamlanmalıdır. Kaydınız alınmadı; lütfen sistem yöneticinize bildirin."
)


def _feedback_tables_ready() -> bool:
    # G2: destek tablolarını Alembic a3d8f1c9b6e2 kurar; bu istek yalnız hazır olup olmadığını okur.
    return _support_tables_ready()


def _category_id_for_feedback(kind: FeedbackKind) -> int | None:
    category = SupportCategory.query.filter_by(name=kind.category_name).first()
    if not category:
        category = SupportCategory(
            name=kind.category_name,
            description="BYS360 kullanıcı geri bildirimleri, tebrik ve teşekkür kayıtları.",
            sort_order=90,
            is_active=True,
        )
        db.session.add(category)
        db.session.flush()
    return int(category.id) if category and category.id else None


def _my_recent_feedback(limit: int = 5) -> list[SupportTicket]:
    if not _support_tables_ready():
        return []
    return (
        SupportTicket.query
        .filter(SupportTicket.created_by_user_id == current_user.id)
        .filter(SupportTicket.ticket_no.ilike("GBD-%"))
        .order_by(SupportTicket.created_at.desc())
        .limit(limit)
        .all()
    )


@main_bp.route("/feedback/gonder", methods=["GET", "POST"])
@login_required
def bys360_feedback_new():
    """Kullanıcıların kurumsal ve sade geri bildirim bırakacağı ana sayfa.

    BYS360_FEEDBACK_EXECUTIVE_UI_V2_17_72 route uyum notu:
    Kullanıcıya ham teknik hata gösterilmez; kayıt destek/talep omurgasına bağlanır.
    """

    is_ready = _feedback_tables_ready()
    if request.method == "POST":
        if not is_ready:
            flash(FEEDBACK_SCHEMA_MIGRATION_REQUIRED_MESSAGE, "warning")
            return redirect(url_for("main.bys360_feedback_new"))
        try:
            kind_key = sanitize_free_text(request.form.get("feedback_kind"), limit=40) or "idea"
            kind = _feedback_kind_map().get(kind_key) or _feedback_kind_map()["idea"]
            module_name = sanitize_free_text(request.form.get("module_name"), limit=120) or "Genel"
            title = sanitize_free_text(request.form.get("title"), limit=180)
            description = sanitize_free_text(request.form.get("description"), limit=4000)
            page_url = sanitize_free_text(request.form.get("page_url"), limit=255)
            priority = sanitize_free_text(request.form.get("priority"), limit=20) or kind.priority
            if kind.key in {"praise", "thanks"}:
                priority = "low"
            if priority not in {"low", "normal", "high", "critical"}:
                priority = kind.priority
            if not title:
                raise ValueError("Kısa konu başlığı yazmanız gerekir.")
            if not description:
                raise ValueError("Geri bildirim açıklaması boş bırakılamaz.")

            full_title = f"[{kind.label}] {title}"
            detail_lines = [
                f"Geri bildirim türü: {kind.label}",
                f"İlgili modül/ekran: {module_name}",
            ]
            if page_url:
                detail_lines.append(f"Sayfa bağlantısı: {page_url}")
            detail_lines.extend(["", description])
            detail_text = "\n".join(detail_lines).strip()

            ticket = SupportTicket(
                ticket_no=_feedback_ticket_no(),
                title=full_title,
                description=detail_text,
                ticket_type=kind.ticket_type,
                module_name=module_name,
                page_url=page_url or None,
                priority=priority,
                status="open",
                category_id=_category_id_for_feedback(kind),
                created_by_user_id=current_user.id,
                organization_unit_id=getattr(current_user, "organization_unit_id", None),
                sicil_no_snapshot=getattr(current_user, "sicil_no", None),
                full_name_snapshot=getattr(current_user, "full_name", None),
                unit_name_snapshot=(getattr(current_user, "birim", None) or getattr(current_user, "ust_birim", None)),
                is_private=bool(request.form.get("is_private")),
            )
            db.session.add(ticket)
            db.session.flush()

            db.session.add(
                SupportTicketStatusHistory(
                    ticket=ticket,
                    old_status=None,
                    new_status="open",
                    changed_by_user_id=current_user.id,
                    note=f"{kind.label} kaydı oluşturuldu.",
                )
            )
            db.session.add(
                SupportTicketMessage(
                    ticket=ticket,
                    user_id=current_user.id,
                    message_type="feedback_note",
                    message=detail_text,
                    is_internal=False,
                )
            )

            upload = request.files.get("attachment")
            if upload and upload.filename:
                _store_ticket_attachment(ticket, upload, attachment_type="feedback")

            notify_user_feedback_created(ticket, current_user, kind_label=kind.label)
            db.session.commit()
            flash("Geri bildiriminiz kaydedildi. Katkınız için teşekkür ederiz.", "success")
            return redirect(url_for("main.bys360_feedback_success", ticket_id=ticket.id))
        except UploadValidationError as exc:
            safe_db_rollback()
            flash(str(exc), "danger")
        except Exception:
            logger.exception("BYS360 V6C guarded exception | file=app/communication/user_feedback_routes.py | line=251")
            safe_db_rollback()
            flash("Geri bildirim kaydedilemedi. Lütfen zorunlu alanları ve ek dosya türünü kontrol edip tekrar deneyin.", "danger")

    return safe_render(
        "feedback/quick_feedback.html",
        "<h3>Geri bildirim ekranı yüklenemedi.</h3>",
        feedback_kinds=BYS360_FEEDBACK_KIND_CHOICES,
        modules=SUPPORT_MODULE_CHOICES,
        recent_feedback=_my_recent_feedback(),
        is_feedback_ready=is_ready,
    )


@main_bp.route("/feedback/gonderildi/<int:ticket_id>")
@login_required
def bys360_feedback_success(ticket_id: int):
    if not _support_tables_ready():
        flash("Geri bildirim kaydı şu anda görüntülenemedi.", "warning")
        return redirect(url_for("main.bys360_feedback_new"))
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if int(ticket.created_by_user_id or 0) != int(current_user.id or 0):
        return redirect(url_for("main.bys360_feedback_new"))
    return safe_render(
        "feedback/quick_feedback_success.html",
        "<h3>Geri bildirim sonucu yüklenemedi.</h3>",
        ticket=ticket,
        feedback_kind_label=_feedback_kind_label,
    )
