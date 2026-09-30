from __future__ import annotations

from app.services.support_ticket_access import can_view_private_support_ticket

# ruff: noqa: F821 - mobile bridge routes resolve legacy names from route_globals at registration time.

# BYS360 mobile support/survey read route bridge module.
# P11-B5 kapsamında destek ve anket GET listeleme endpointleri ayrılmıştır.
# URL path ve JSON cevap davranışı değiştirilmemelidir.

def _listed_description(ticket, user) -> str:
    """Phase 13B private-ticket rule, as on the ticket detail: another unit's private body stays hidden."""
    if int(getattr(ticket, "created_by_user_id", 0) or 0) == int(getattr(user, "id", 0) or 0):
        return getattr(ticket, "description", "") or ""
    if not can_view_private_support_ticket(ticket, user):
        return ""
    return getattr(ticket, "description", "") or ""


def register_mobile_support_survey_read_routes_v1(mobile_bp, route_globals) -> None:
    """Register support/survey read mobile routes on the existing mobile blueprint."""
    if route_globals.get("_BYS360_P11_B5_SUPPORT_SURVEY_READ_ROUTES_REGISTERED"):
        return

    route_globals['mobile_bp'] = mobile_bp
    route_globals.setdefault('mobile_api_bp', mobile_bp)
    globals().update(route_globals)

    @mobile_api_bp.get("/support/tickets")
    @require_mobile_user
    def mobile_support_tickets(user: User):
        q_base = SupportTicket.query.order_by(SupportTicket.created_at.desc())
        if not _has_global_scope(user):
            q_base = q_base.filter(SupportTicket.created_by_user_id == user.id)

        rows = q_base.limit(80).all()
        items = []
        for t in rows:
            status = getattr(t, "status", "") or "open"
            status_label = _mobile_support_status_label(status)
            priority = getattr(t, "priority", "") or "normal"
            progress = 100 if str(status).lower() in {"closed", "kapalı", "kapali", "resolved"} else 45
            item = _item(
                getattr(t, "id", ""),
                getattr(t, "title", "") or "Destek talebi",
                _clean_mobile_text(_listed_description(t, user), limit=180),
                status_label,
                _dt_label(getattr(t, "updated_at", None) or getattr(t, "created_at", None)),
                getattr(t, "ticket_no", "") or _mobile_support_priority_label(priority),
                progress,
            )
            item["tone"] = "green" if progress == 100 else "blue"
            item["icon"] = "support"
            items.append(item)

        open_count = sum(1 for t in rows if str(getattr(t, "status", "") or "open").lower() not in {"closed", "kapalı", "kapali", "resolved"})
        closed_count = sum(1 for t in rows if str(getattr(t, "status", "") or "open").lower() in {"closed", "kapalı", "kapali", "resolved"})
        return _module_payload([
            _metric("Açık Talep", open_count, "İşlemde olan destek kaydı", "blue", "support"),
            _metric("Sonuçlanan", closed_count, "Tamamlanan destek kaydı", "green", "done"),
            _metric("Toplam", len(rows), "Size ait destek kaydı", "blue", "list"),
        ], items)

    @mobile_api_bp.get("/surveys")
    @require_mobile_user
    def mobile_surveys(user: User):
        q = Survey.query.order_by(Survey.created_at.desc())
        rows = q.limit(80).all()
        items = []
        visible_count = 0
        completed_count = 0
        waiting_count = 0
        for survey in rows:
            if not _mobile_survey_visible(user, survey):
                continue
            visible_count += 1
            completed = _mobile_survey_completed(user, survey)
            active = _survey_is_active(survey)
            if completed:
                completed_count += 1
            elif active:
                waiting_count += 1
            status_label = "Cevaplandı" if completed else _survey_status_label(getattr(survey, "status", ""))
            progress = 100 if completed else 35 if active else 0
            items.append(_item(
                getattr(survey, "id", ""),
                getattr(survey, "title", "Anket"),
                getattr(survey, "description", "") or getattr(survey, "survey_type", ""),
                status_label,
                "Anonim" if getattr(survey, "is_anonymous", False) else "Kurum içi",
                "",
                progress,
            ))
        # value alanı bilinçli boş bırakılır; mobil kartta yanlış sayı gösterilmez.
        for item in items:
            item["value"] = ""
        return _module_payload([
            _metric("Yanıt Bekleyen", waiting_count, "Yetkinize atanmış aktif anket", "yellow", "poll"),
            _metric("Cevaplanan", completed_count, "Mobil/kullanıcı tamamlanan", "yellow", "verified_user"),
            _metric("Geri Bildirim", _safe_count(FeedbackCampaign.query.filter_by(is_active=True)), "Aktif kampanya", "yellow", "feedback"),
        ], items)

    route_globals["_BYS360_P11_B5_SUPPORT_SURVEY_READ_ROUTES_REGISTERED"] = True
