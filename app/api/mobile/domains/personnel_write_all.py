from __future__ import annotations

# BYS360 V1E: emergency runtime recovery for the Phase2Y wildcard-import regression.
# This deliberately restores the shared mobile contract first; explicit imports can be
# reintroduced later only after a per-file F821 gate and smoke test.
from app.api.mobile.shared import (
    Any,
    IntegrityError,
    User,
    _full_name,
    _role_key,
    current_app,
    db,
    get_default_first_login_password,
    jsonify,
    mobile_api_bp,
    request,
    require_mobile_user,
)
from app.route_support import ADMIN_FAMILY_ROLES, is_admin_family_user, normalize_role_name

# Admin family plus the admin aliases the code treats as admin-level (routes_president_scorecard_v2.py,
# feedback_aftercare_phase7.py, account_communication_helpers.py required_roles).
_ADMIN_LEVEL_ROLES = {normalize_role_name(v) for v in ADMIN_FAMILY_ROLES} | {
    "super_admin", "system_admin", "sistem_yoneticisi", "administrator", "president",
}


@mobile_api_bp.get("/personnel/all")
@require_mobile_user
def mobile_personnel_all(user: User):
    from app.api.mobile.services import personnel_service as _bys360_personnel_service
    return _bys360_personnel_service.mobile_personnel_all(user)

# BYS360_MOBILE_V2_8_62_PERSONNEL_CREATE_BEGIN
_PERSONNEL_CREATE_ROLES = {
    "admin",
    "sistem_yoneticisi",
    "system_admin",
    "personel_yonetimi",
    "personel yönetimi yetkilisi",
    "ik",
    "insan kaynaklari",
    "insan kaynakları",
}


# BYS360 DEFECT AQ: "admin" in role / "personel_yonetimi" in role /
# "personel yönetimi" in label alt dize kontrolleri kaldırıldı -- her üçü
# de zaten _PERSONNEL_CREATE_ROLES kümesinin birer TAM üyesiydi
# ("admin", "personel_yonetimi", "personel yönetimi yetkilisi"), bu yüzden
# alt dize hâlleri hiçbir meşru değeri ek olarak kapsamıyordu, yalnızca
# "birim_admin_full" gibi ilgisiz roller için yanlışlıkla personel oluşturma
# yetkisi açıyordu. role == "ik" / label == "ik" zaten tam eşleşme.
def _can_mobile_create_personnel(user: User) -> bool:
    role = _role_key(user)
    label = ((getattr(user, "role_label", "") or "").strip().lower())
    return bool(
        role in _PERSONNEL_CREATE_ROLES
        or label in _PERSONNEL_CREATE_ROLES
    )


def _mobile_clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"none", "null"} else text


def _mobile_role_label(role: str) -> str:
    labels = {
        "personel": "Personel",
        "personel_yonetimi": "Personel Yönetimi Yetkilisi",
        "ik": "İK Yetkilisi",
        "performans_yetkilisi": "Performans Yetkilisi",
        "koordinator": "Koordinatör",
        "grup_baskani": "Grup Başkanı",
        "admin": "Admin",
    }
    return labels.get((role or "personel").strip(), (role or "Personel").strip())

# BYS360 P1.7 service delegation - legacy implementation preserved
def _bys360_legacy__mobile_created_personnel_row(u: User) -> dict[str, Any]:
    full_name = _full_name(u)
    active = bool(getattr(u, "is_active", False))
    return {
        "id": getattr(u, "id", None),
        "user_id": getattr(u, "id", None),
        "full_name": full_name,
        "display_name": full_name,
        "ad_soyad": full_name,
        "first_name": getattr(u, "ad", "") or "",
        "last_name": getattr(u, "soyad", "") or "",
        "registry_no": getattr(u, "sicil_no", "") or "",
        "sicil_no": getattr(u, "sicil_no", "") or "",
        "unit_name": getattr(u, "birim", "") or "",
        "birim": getattr(u, "birim", "") or "",
        "upper_unit_name": getattr(u, "ust_birim", "") or "",
        "ust_birim": getattr(u, "ust_birim", "") or "",
        "title_name": getattr(u, "unvan", "") or "",
        "unvan": getattr(u, "unvan", "") or "",
        "duty_name": getattr(u, "gorev", "") if hasattr(u, "gorev") else "",
        "gorev": getattr(u, "gorev", "") if hasattr(u, "gorev") else "",
        "manager_name": getattr(u, "yonetici_sicil", "") or "",
        "personnel_category": getattr(u, "personnel_category", "") or "Diğer",
        "category": getattr(u, "personnel_category", "") or "Diğer",
        "role_label": getattr(u, "role_label", None) or getattr(u, "role", "") or "",
        "role": getattr(u, "role", "") or "",
        "status_label": "Aktif" if active else "Pasif",
        "status": "Aktif" if active else "Pasif",
        "is_active": active,
    }

def _mobile_created_personnel_row(u: User) -> dict[str, Any]:
    from app.api.mobile.services import personnel_service as _bys360_personnel_service
    return _bys360_personnel_service._mobile_created_personnel_row(u)

# BYS360 P1.7 service delegation - legacy implementation preserved
def _bys360_legacy_mobile_personnel_create(user: User):
    if not _can_mobile_create_personnel(user):
        return jsonify({"message": "Bu işlem için personel ekleme yetkiniz bulunmamaktadır."}), 403

    data = request.get_json(silent=True) or {}
    sicil_no = _mobile_clean_text(data.get("sicil_no") or data.get("registry_no"))
    ad = _mobile_clean_text(data.get("ad") or data.get("first_name"))
    soyad = _mobile_clean_text(data.get("soyad") or data.get("last_name"))
    unvan = _mobile_clean_text(data.get("unvan") or data.get("title"))
    birim = _mobile_clean_text(data.get("birim") or data.get("unit_name"))
    ust_birim = _mobile_clean_text(data.get("ust_birim") or data.get("upper_unit_name"))
    yonetici_sicil = _mobile_clean_text(data.get("yonetici_sicil") or data.get("manager_sicil") or data.get("manager_registry"))
    role = _mobile_clean_text(data.get("role") or data.get("role_value")) or "personel"
    category = _mobile_clean_text(data.get("personnel_category") or data.get("category")) or "Diğer"
    email = _mobile_clean_text(data.get("email")) or f"{sicil_no}@bys360.local"
    is_active = bool(data.get("is_active", True))

    missing = []
    for label, value in (
        ("Sicil No", sicil_no),
        ("Ad", ad),
        ("Soyad", soyad),
        ("Unvan", unvan),
        ("Birim", birim),
        ("Üst Birim", ust_birim),
        ("Yönetici Sicil No", yonetici_sicil),
        ("Rol", role),
    ):
        if not value:
            missing.append(label)
    if missing:
        return jsonify({"message": "Zorunlu alanları doldurun: " + ", ".join(missing)}), 400
    # Web account creation (/personnel/add) is admin_required: only the admin family grants admin-level roles.
    if normalize_role_name(role) in _ADMIN_LEVEL_ROLES and not is_admin_family_user(user):
        return jsonify({"message": "Bu rolü atama yetkiniz bulunmamaktadır."}), 403

    if User.query.filter(User.sicil_no == sicil_no).first():
        return jsonify({"message": "Bu Sicil No ile kayıtlı personel zaten bulunmaktadır."}), 400
    if email and User.query.filter(User.email == email).first():
        return jsonify({"message": "Bu e-posta adresiyle kayıtlı personel zaten bulunmaktadır."}), 400
    if yonetici_sicil and not User.query.filter(User.sicil_no == yonetici_sicil).first():
        return jsonify({"message": "Yönetici Sicil No sistemde bulunamadı."}), 400

    try:
        new_user = User(
            sicil_no=sicil_no,
            email=email,
            ad=ad,
            soyad=soyad,
            full_name_cache=f"{ad} {soyad}".strip(),
            unvan=unvan,
            role=role,
            role_label=_mobile_role_label(role),
            personnel_category=category,
            birim=birim,
            ust_birim=ust_birim,
            yonetici_sicil=yonetici_sicil,
            is_active=is_active,
        )
        if hasattr(new_user, "set_password"):
            new_user.set_password(get_default_first_login_password())
        if hasattr(new_user, "must_change_password"):
            new_user.must_change_password = True
        if hasattr(new_user, "must_set_security_question"):
            new_user.must_set_security_question = True
        if hasattr(new_user, "is_first_login"):
            new_user.is_first_login = True
        if hasattr(new_user, "failed_login_attempts"):
            new_user.failed_login_attempts = 0
        if hasattr(new_user, "captcha_required"):
            new_user.captcha_required = False
        try:
            from app.services.personnel.categories import assign_user_performance_category
            assign_user_performance_category(new_user, category, db_session=db.session)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/routes.py:1511)")
        db.session.add(new_user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "Personel kaydı oluşturulamadı. Sicil veya e-posta bilgisi daha önce kullanılmış olabilir."}), 400
    except Exception as exc:
        db.session.rollback()
        try:
            current_app.logger.exception("Mobil personel kaydı oluşturulamadı: %s", exc)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/api/mobile/routes.py:1522)")
        return jsonify({"message": "Personel kaydı şu anda oluşturulamadı. Lütfen bilgileri kontrol edip tekrar deneyin."}), 500

    return jsonify({
        "ok": True,
        "success": True,
        "message": "Personel kaydı oluşturuldu. Başlangıç şifresi sistem tarafından otomatik atanmıştır.",
        "can_create_personnel": True,
        "personnel": _mobile_created_personnel_row(new_user),
    }), 201

@mobile_api_bp.post("/personnel/create")
@require_mobile_user
def mobile_personnel_create(user: User):
    from app.api.mobile.services import personnel_service as _bys360_personnel_service
    return _bys360_personnel_service.mobile_personnel_create(user)


@mobile_api_bp.post("/personnel/add")
@require_mobile_user
def mobile_personnel_add_alias(user: User):
    from app.api.mobile.services import personnel_service as _bys360_personnel_service
    return _bys360_personnel_service.mobile_personnel_create(user)
# BYS360_MOBILE_V2_8_62_PERSONNEL_CREATE_END

