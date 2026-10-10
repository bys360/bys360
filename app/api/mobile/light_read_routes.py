from __future__ import annotations

# ruff: noqa: F821 - mobile bridge routes resolve legacy names from route_globals at registration time.

# BYS360 mobile light read route bridge module.
# P11-B3 kapsamında küçük ve düşük riskli mobil GET/read endpointleri ayrılmıştır.
# URL path ve JSON cevap davranışı değiştirilmemelidir.

def register_mobile_light_read_routes_v1(mobile_bp, route_globals) -> None:
    """Register small read-only mobile routes on the existing mobile blueprint."""
    if route_globals.get("_BYS360_P11_B3_LIGHT_READ_ROUTES_REGISTERED"):
        return

    route_globals['mobile_bp'] = mobile_bp
    route_globals.setdefault('mobile_api_bp', mobile_bp)
    globals().update(route_globals)

    @mobile_api_bp.get("/ai/insights")
    @require_mobile_user
    def mobile_ai_insights(user: User):
        global_scope = _has_global_scope(user)
        q = AIRecommendation.query.order_by(AIRecommendation.created_at.desc())
        if not global_scope:
            q = q.filter(AIRecommendation.created_by_user_id == user.id) if hasattr(AIRecommendation, "created_by_user_id") else q.limit(0)
        items = []
        for r in q.limit(30).all():
            items.append(_item(r.id, getattr(r, "title", None) or getattr(r, "recommendation_text", "AI önerisi")[:80], getattr(r, "summary", "") or getattr(r, "recommendation_text", ""), getattr(r, "status", ""), getattr(r, "module_type", "AI"), "", 70))
        return _module_payload([
            _metric("Dikkat Notu", _safe_count(q), "Yetki kapsamındaki AI kayıtları", "purple", "psychology"),
            _metric("AI Log", _safe_count(AIRequestLog.query), "İşlem ve analiz kayıtları", "purple", "history"),
            _metric("Sınır", "Kontrollü", "AI karar vermez, özet sunar", "purple", "shield"),
        ], items)

    @mobile_api_bp.get("/assistant/suggestions")
    @require_mobile_user
    def mobile_assistant_suggestions(user: User):
        items = [
            _item("performance_period", "Performans dönemi oluşturma", "Dönem Yönetimi > Yeni Dönem Oluştur", "Rehber", "Performans", "", 100),
            _item("personnel_add", "Personel kaydı kontrolü", "Sicil, birim, üst birim ve yönetici alanlarını kontrol edin", "Rehber", "Personel", "", 100),
            _item("support", "Destek talebi oluşturma", "Yardım ve talepler ekranından kayıt açılır", "Rehber", "Destek", "", 100),
        ]
        return _module_payload([
            _metric("Rehber Konu", len(items), "Kurumsal işlem yönlendirmesi", "red", "route"),
            _metric("Yetki Sınırı", "Aktif", "Hassas veri gösterilmez", "red", "lock"),
            _metric("Kullanıcı", _full_name(user), "Oturuma göre rehberlik", "red", "person"),
        ], items)

    @mobile_api_bp.get("/settings/summary")
    @require_mobile_user
    def mobile_settings_summary(user: User):
        # B1-F1 decision 2: technical roles keep these technical counters (no personal data).
        if not (_has_global_scope(user) or _authorization_role_key(user) in _TECHNICAL_ROLES):
            return _module_payload([
                _metric("Rol", getattr(user, "role_label", None) or getattr(user, "role", "-"), "Kendi oturum yetkiniz", "red", "badge"),
                _metric("Erişim", "Sınırlı", "Ayar detayları yetkiye bağlıdır", "red", "lock"),
                _metric("Güvenlik", "Aktif", "Mobil yetki sınırı uygulanır", "red", "shield"),
            ], [_item("scope", "Yetki kontrollü görünüm", "Ayar detayları yalnızca yetkili roller için açılır", "Sınırlı", "Ayarlar", "", 100)])
        return _module_payload([
            _metric("Rol Profili", _safe_count(RoleMenuDefault.query), "Tanımlı rol ve menü varsayımları", "red", "admin"),
            _metric("Modül Ayarı", _safe_count(ModuleSetting.query), "Merkezi modül parametresi", "red", "settings"),
            _metric("Sistem Ayarı", _safe_count(SystemSetting.query), "Genel sistem parametresi", "red", "tune"),
        ], [
            _item("roles", "Rol matrisi", "Kişi, rol ve birim bazlı görünürlük", "Kontrollü", "Yetki", str(_safe_count(RoleMenuDefault.query)), 100),
            _item("module_settings", "Modül ayarları", "Performans, iletişim, AI ve bildirim ayarları", "Aktif", "Ayarlar", str(_safe_count(ModuleSetting.query)), 100),
        ])

    route_globals["_BYS360_P11_B3_LIGHT_READ_ROUTES_REGISTERED"] = True
