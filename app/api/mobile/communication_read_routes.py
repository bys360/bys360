from __future__ import annotations

# ruff: noqa: F821 - mobile bridge routes resolve legacy names from route_globals at registration time.

# BYS360 mobile communication read route bridge module.
# P11-B6 kapsamında iletişim/bildirim GET okuma endpointleri ayrılmıştır.
# URL path ve JSON cevap davranışı değiştirilmemelidir.

def register_mobile_communication_read_routes_v1(mobile_bp, route_globals) -> None:
    """Register communication read mobile routes on the existing mobile blueprint."""
    if route_globals.get("_BYS360_P11_B6_COMMUNICATION_READ_ROUTES_REGISTERED"):
        return

    route_globals['mobile_bp'] = mobile_bp
    route_globals.setdefault('mobile_api_bp', mobile_bp)
    globals().update(route_globals)

    @mobile_api_bp.get("/notifications")
    @require_mobile_user
    def mobile_notifications(user: User):
        q = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc())
        unread_q = Notification.query.filter_by(user_id=user.id, is_read=False)
        read_q = Notification.query.filter_by(user_id=user.id, is_read=True)
        items = []
        for n in q.limit(80).all():
            read = bool(getattr(n, "is_read", False))
            priority = (getattr(n, "priority", "") or "normal").strip()
            notification_type = (getattr(n, "notification_type", "") or "Bildirim").strip()
            title = getattr(n, "title", "") or "Bildirim"
            body = _clean_mobile_text(getattr(n, "body", "") or "", limit=600)
            item = _item(
                getattr(n, "id", ""),
                title,
                body,
                "Okundu" if read else "Okunmadı",
                _dt_label(getattr(n, "created_at", None)),
                notification_type,
                100 if read else 0,
            )
            item["tone"] = "blue" if read else "yellow"
            item["icon"] = "notifications"
            item["priority"] = priority
            items.append(item)
        unread_count = _safe_count(unread_q)
        read_count = _safe_count(read_q)
        total_count = _safe_count(Notification.query.filter_by(user_id=user.id))
        return _module_payload([
            _metric("Okunmamış", unread_count, "Henüz okunmamış bildirim", "yellow", "notifications"),
            _metric("Okunmuş", read_count, "Takip edilmiş bildirim", "blue", "done"),
            _metric("Toplam", total_count, "Size ait bildirim kaydı", "yellow", "list"),
        ], items)

    @mobile_api_bp.get("/communication/messages/threads")
    @require_mobile_user
    def mobile_b46_communication_message_threads(user: User):
        q = MessageThread.query.join(MessageThreadParticipant, MessageThreadParticipant.thread_id == MessageThread.id).filter(
            MessageThreadParticipant.user_id == user.id,
            MessageThread.is_active.is_(True),
        )
        try:
            q = q.filter(MessageThreadParticipant.left_at.is_(None), MessageThreadParticipant.is_archived.is_(False))
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/routes.py:1655)")
        total = _safe_count(q)
        try:
            rows = q.order_by(MessageThread.last_message_at.desc().nullslast(), MessageThread.id.desc()).limit(200).all()
        except Exception:
            rows = q.order_by(MessageThread.id.desc()).limit(200).all()
        threads = [_b46_thread_row(t, user) for t in rows]
        unread_total = sum(int(t.get("unread_count") or 0) for t in threads)
        return jsonify({
            "source": "real_message_threads",
            "source_label": "Canlı BYS360 mesajlaşma verisi",
            "total": total,
            "unread_total": unread_total,
            "threads": threads,
            "items": threads,
            "metrics": [
                _metric("Konuşma", total, "Katılımcı olduğunuz başlık", "blue", "forum"),
                _metric("Okunmamış", unread_total, "Size gelen yeni mesajlar", "blue", "mark_unread_chat_alt"),
                _metric("Kaynak", "Gerçek", "messages ve message_threads kayıtları", "blue", "api"),
            ],
        })

    @mobile_api_bp.get("/communication/messages/users")
    @require_mobile_user
    def mobile_b46_communication_users(user: User):
        query_text = _b46_txt(request.args.get("q") or request.args.get("search") or request.args.get("query")).lower()
        users = User.query.filter_by(is_active=True).order_by(User.ad.asc(), User.soyad.asc()).limit(1000).all()
        rows = []
        for u in users:
            if getattr(u, "id", None) == user.id:
                continue
            # R06 (approved policy, 2026-10-10): the recipient picker carries and searches the name and
            # the unit only; the sicil and title keys stay for client compatibility but are empty.
            haystack = " ".join([
                _full_name(u),
                _b46_txt(getattr(u, "birim", None) or getattr(u, "unit_name", None)),
            ]).lower()
            if query_text and query_text not in haystack:
                continue
            rows.append({
                "id": u.id,
                "user_id": u.id,
                "display_name": _full_name(u),
                "name": _full_name(u),
                "registry_no": "",
                "unit_name": _b46_txt(getattr(u, "birim", None) or getattr(u, "unit_name", None)),
                "title_name": "",
                "subtitle": _b46_txt(getattr(u, "birim", None) or getattr(u, "unit_name", None)),
            })
            if len(rows) >= 50:
                break
        return jsonify({"source": "real_active_users", "users": rows, "items": rows, "total": len(rows)})

    route_globals["_BYS360_P11_B6_COMMUNICATION_READ_ROUTES_REGISTERED"] = True
