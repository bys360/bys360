from __future__ import annotations

from dataclasses import dataclass

from app.extensions import db
from app.models import OrganizationUnit, User
from app.route_support import bool_from_form
from app.security.email_policy import corporate_email_error_message, is_allowed_corporate_email

# --- BYS360 third-manager Excel import compatibility patch ---


THIRD_MANAGER_STANDARD_KEY = "ucuncu_yonetici_sicil"
THIRD_MANAGER_HEADER_ALIASES = [
    "ucuncu_yonetici_sicil",
    "üçüncü yönetici sicil",
    "ucuncu yonetici sicil",
    "3. amir sicil",
    "3 amir sicil",
    "new_y3",
]


@dataclass(slots=True)
class AdminUserFormPayload:
    ad: str
    soyad: str
    sicil_no: str
    email: str
    unvan: str
    role: str
    birim: str
    ust_birim: str
    yonetici_sicil: str | None
    ikinci_yonetici_sicil: str | None
    ucuncu_yonetici_sicil: str | None
    is_active: bool

    @property
    def manager_values(self) -> list[str]:
        return [
            value
            for value in [
                self.yonetici_sicil,
                self.ikinci_yonetici_sicil,
                self.ucuncu_yonetici_sicil,
            ]
            if value
        ]


def build_admin_user_form_context(*, exclude_user_id: int | None = None) -> dict:
    unit_name_options = [
        item[0]
        for item in db.session.query(OrganizationUnit.name)
        .filter(OrganizationUnit.name.isnot(None), OrganizationUnit.name != "")
        .distinct()
        .order_by(OrganizationUnit.name.asc())
        .all()
    ]

    parent_unit_options = [
        item[0]
        for item in db.session.query(User.ust_birim)
        .filter(User.ust_birim.isnot(None), User.ust_birim != "")
        .distinct()
        .order_by(User.ust_birim.asc())
        .all()
    ]

    manager_query = User.query.filter(User.is_active.is_(True), User.role != "admin")
    if exclude_user_id:
        manager_query = manager_query.filter(User.id != exclude_user_id)

    manager_candidates = (
        manager_query
        .order_by(User.ust_birim.asc(), User.birim.asc(), User.ad.asc(), User.soyad.asc())
        .all()
    )

    return {
        "unit_name_options": unit_name_options,
        "parent_unit_options": parent_unit_options,
        "manager_candidates": manager_candidates,
    }


def parse_admin_user_form(form) -> AdminUserFormPayload:
    return AdminUserFormPayload(
        ad=(form.get("ad") or "").strip(),
        soyad=(form.get("soyad") or "").strip(),
        sicil_no=(form.get("sicil_no") or "").strip(),
        email=(form.get("email") or "").strip().lower(),
        unvan=(form.get("unvan") or "").strip(),
        role=(form.get("role") or "").strip() or "personel",
        birim=(form.get("birim") or "").strip(),
        ust_birim=(form.get("ust_birim") or "").strip(),
        yonetici_sicil=((form.get("yonetici_sicil") or "").strip() or None),
        ikinci_yonetici_sicil=((form.get("ikinci_yonetici_sicil") or "").strip() or None),
        ucuncu_yonetici_sicil=((form.get("ucuncu_yonetici_sicil") or "").strip() or None),
        is_active=bool_from_form(form.get("is_active")),
    )


def validate_admin_user_payload(
    payload: AdminUserFormPayload,
    *,
    current_user_id: int | None = None,
) -> tuple[str, str] | None:
    if not payload.ad or not payload.soyad or not payload.sicil_no or not payload.email or not payload.unvan or not payload.birim or not payload.ust_birim:
        return "Ad, soyad, sicil no, e-posta, unvan, birim ve üst birim zorunludur.", "warning"

    sicil_query = User.query.filter(User.sicil_no == payload.sicil_no)
    email_query = User.query.filter(User.email == payload.email)
    if current_user_id:
        sicil_query = sicil_query.filter(User.id != current_user_id)
        email_query = email_query.filter(User.id != current_user_id)

    if sicil_query.first():
        if current_user_id:
            return "Bu sicil numarası başka bir kullanıcıda kayıtlı.", "danger"
        return "Bu sicil numarası zaten kayıtlı.", "danger"

    if email_query.first():
        if current_user_id:
            return "Bu e-posta adresi başka bir kullanıcıda kayıtlı.", "danger"
        return "Bu e-posta adresi zaten kayıtlı.", "danger"

    if not is_allowed_corporate_email(payload.email):
        return corporate_email_error_message(), "warning"

    if payload.sicil_no in payload.manager_values:
        return "Personel kendisini amir olarak seçemez.", "warning"

    if len(payload.manager_values) != len(set(payload.manager_values)):
        return "Aynı kişi birden fazla amir seviyesinde seçilemez.", "warning"

    return None


def apply_admin_user_payload(user: User, payload: AdminUserFormPayload, organization_unit_id: int | None) -> None:
    user.ad = payload.ad
    user.soyad = payload.soyad
    user.sicil_no = payload.sicil_no
    user.email = payload.email
    user.unvan = payload.unvan
    user.role = payload.role
    user.organization_unit_id = organization_unit_id
    user.birim = payload.birim
    user.ust_birim = payload.ust_birim
    user.yonetici_sicil = payload.yonetici_sicil
    user.ikinci_yonetici_sicil = payload.ikinci_yonetici_sicil
    user.ucuncu_yonetici_sicil = payload.ucuncu_yonetici_sicil
    user.is_active = payload.is_active
    if hasattr(user, "full_name_cache"):
        user.full_name_cache = f"{payload.ad} {payload.soyad}".strip()