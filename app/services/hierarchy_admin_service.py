from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, cast

from flask import current_app
from sqlalchemy import inspect as sa_inspect, or_, text

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    AssignmentCoverageLog,
    AttendanceException,
    DelegationAssignment,
    EmployeeOrgAssignmentHistory,
    EvaluationAssignment,
    EvaluationPublishLog,
    FeedbackMeeting,
    FeedbackRequest,
    LeaveBalance,
    MailLog,
    Message,
    MessageAttachment,
    MessageThread,
    MessageThreadParticipant,
    Notification,
    OrganizationUnit,
    OrganizationUnitVersion,
    PerformanceEvaluation,
    PerformanceEvaluationItem,
    PerformanceImportBatch,
    PerformanceImportBatchRow,
    PerformancePublishLog,
    PerformanceResultSnapshot,
    PersonnelLeave,
    SupportFeedbackRating,
    SupportHelpArticle,
    SupportTicket,
    SupportTicketAttachment,
    SupportTicketMessage,
    SupportTicketStatusHistory,
    Survey,
    SurveyAnswer,
    SurveyAssignment,
    SurveyQuestion,
    SurveyQuestionOption,
    SurveyResponse,
    User,
    UserMenuPermission,
)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text_value = unicodedata.normalize("NFKD", str(value).strip())
    text_value = text_value.replace("ı", "i").replace("İ", "i")
    text_value = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    text_value = text_value.lower()
    replacements = {
        "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c",
    }
    for old, new in replacements.items():
        text_value = text_value.replace(old, new)
    text_value = re.sub(r"\s+", " ", text_value)
    return text_value.strip()


def norm_unit(value: Any) -> str:
    return normalize_text(value)


def parse_date(date_str: str):
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def infer_unit_type(unit_name: str, role: str = "") -> str:
    unit_n = norm_unit(unit_name)
    role_n = norm_unit(role)

    if unit_n == "baskanlik":
        return "baskanlik"
    if "baskan yardimci" in unit_n:
        return "baskan_yardimciligi"
    if "grup baskanligi" in unit_n:
        return "grup_baskanligi"
    if "calisma grubu" in unit_n:
        return "calisma_grubu"
    if role_n == "koordinator":
        return "calisma_grubu"
    if role_n in {"grup_baskani", "mali_musavir"}:
        return "grup_baskanligi"
    if "koordinator" in unit_n:
        return "koordinatorluk"
    return "diger"


def find_unit_match_strict(
    birim_name: str,
    ust_birim_name: str | None = None,
    unit_type: str | None = None,
):
    target_name = norm_unit(birim_name)
    target_parent = norm_unit(ust_birim_name)
    target_type = norm_unit(unit_type)
    if not target_name:
        return None

    units = OrganizationUnit.query.order_by(OrganizationUnit.id.asc()).all()
    for unit in units:
        unit_name = norm_unit(unit.name)
        parent_name = norm_unit(unit.parent.name if getattr(unit, "parent", None) else "")
        current_type = norm_unit(unit.unit_type)

        if unit_name != target_name:
            continue
        if target_parent and parent_name != target_parent:
            continue
        if target_type and current_type != target_type:
            continue
        if not target_parent and getattr(unit, "parent", None) is not None:
            continue
        return unit
    return None


def ensure_unit_exists_strict(
    birim_name: str,
    ust_birim_name: str | None = None,
    role: str = "",
):
    birim_name = (birim_name or "").strip()
    ust_birim_name = (ust_birim_name or "").strip()
    if not birim_name:
        return None

    unit_type = infer_unit_type(birim_name, role)

    if not ust_birim_name or norm_unit(birim_name) == norm_unit(ust_birim_name):
        existing_root = find_unit_match_strict(birim_name, None, unit_type)
        if existing_root:
            return existing_root
        root = OrganizationUnit(
            name=birim_name,
            unit_type=unit_type,
            parent_id=None,
            is_active=True,
        )
        db.session.add(root)
        db.session.flush()
        return root

    parent_type = infer_unit_type(ust_birim_name, "")
    parent = find_unit_match_strict(ust_birim_name, None, parent_type)
    if not parent:
        parent = OrganizationUnit(
            name=ust_birim_name,
            unit_type=parent_type,
            parent_id=None,
            is_active=True,
        )
        db.session.add(parent)
        db.session.flush()

    existing_child = find_unit_match_strict(birim_name, ust_birim_name, unit_type)
    if existing_child:
        return existing_child

    child = OrganizationUnit(
        name=birim_name,
        unit_type=unit_type,
        parent_id=parent.id,
        is_active=True,
    )
    db.session.add(child)
    db.session.flush()
    return child


def sync_organization_units_from_users_if_stale(*, commit: bool = False, force: bool = False, cache_seconds: int | None = None):
    """GET ekranlarinda gereksiz tekrar calisan senkronu kisar.

    Varsayilan davranis: ayni surecte son basarili senkron uzerinden belli bir
    sure gecmediyse yeniden DB yazimi yapma. ``force=True`` verilirse her zaman
    calisir.
    """
    try:
        cache_seconds = int(cache_seconds or current_app.config.get("ORG_UNIT_SYNC_CACHE_SECONDS", 300) or 300)
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/hierarchy_admin_service.py:197")
        cache_seconds = 300

    bucket = current_app.extensions.setdefault("bys360_hierarchy_sync", {})
    last_run = bucket.get("last_run")
    now = utc_now()

    if not force and last_run is not None:
        delta = (now - last_run).total_seconds()
        if delta < max(cache_seconds, 0):
            return 0

    affected = sync_organization_units_from_users(commit=commit)
    bucket["last_run"] = now
    bucket["last_count"] = affected
    return affected


def sync_organization_units_from_users(commit: bool = False):
    """Kullanıcı kartlarındaki birim / üst birim verisinden organizasyon ağacını toparlar."""
    created_or_linked = 0
    users = (
        User.query
        .filter(User.role != "admin")
        .order_by(User.id.asc())
        .all()
    )

    for user in users:
        birim_name = (getattr(user, "birim", None) or "").strip()
        ust_birim_name = (getattr(user, "ust_birim", None) or "").strip()
        if not birim_name:
            continue

        role_value = getattr(user, "role", "") or ""
        unit = ensure_unit_exists_strict(birim_name, ust_birim_name, role_value)
        if not unit:
            continue

        if hasattr(user, "organization_unit_id") and user.organization_unit_id != unit.id:
            user.organization_unit_id = unit.id
            created_or_linked += 1

    db.session.flush()
    if commit:
        db.session.commit()
    return created_or_linked


def get_manager_scope_users(user: User):
    if not user:
        return []

    role = user.role or ""

    if role in {"admin", "baskan", "baskan_yardimcisi"}:
        return (
            User.query
            .filter(User.role != "admin")
            .order_by(User.ad.asc(), User.soyad.asc())
            .all()
        )

    if role in {"grup_baskani", "mali_musavir"}:
        return (
            User.query
            .filter(
                User.role != "admin",
                or_(
                    User.birim == user.birim,
                    User.ust_birim == user.birim,
                ),
            )
            .order_by(User.ad.asc(), User.soyad.asc())
            .all()
        )

    if role in {"koordinator", "birim_sorumlusu"}:
        return (
            User.query
            .filter(
                User.role != "admin",
                or_(
                    User.yonetici_sicil == user.sicil_no,
                    User.ikinci_yonetici_sicil == user.sicil_no,
                    User.birim == user.birim,
                ),
            )
            .order_by(User.ad.asc(), User.soyad.asc())
            .all()
        )

    return [user]


def get_hierarchy_scope_users(user: User):
    if not user:
        return []

    role = (user.role or "").strip().lower()

    if role in {"admin", "baskan", "baskan_yardimcisi"}:
        return (
            User.query
            .filter(User.role != "admin")
            .order_by(User.ust_birim.asc(), User.birim.asc(), User.ad.asc(), User.soyad.asc())
            .all()
        )

    if role in {"grup_baskani", "mali_musavir"}:
        return (
            User.query
            .filter(
                User.role != "admin",
                or_(
                    User.birim == user.birim,
                    User.ust_birim == user.birim,
                    User.birim == user.ust_birim,
                    User.ust_birim == user.ust_birim,
                )
            )
            .order_by(User.ust_birim.asc(), User.birim.asc(), User.ad.asc(), User.soyad.asc())
            .all()
        )

    if role in {"koordinator", "birim_sorumlusu"}:
        return (
            User.query
            .filter(
                User.role != "admin",
                or_(
                    User.sicil_no == user.sicil_no,
                    User.birim == user.birim,
                    User.ust_birim == user.birim,
                    User.yonetici_sicil == user.sicil_no,
                    User.ikinci_yonetici_sicil == user.sicil_no,
                    User.ucuncu_yonetici_sicil == user.sicil_no,
                )
            )
            .order_by(User.ust_birim.asc(), User.birim.asc(), User.ad.asc(), User.soyad.asc())
            .all()
        )

    return (
        User.query
        .filter(
            User.role != "admin",
            or_(
                User.sicil_no == user.sicil_no,
                User.birim == user.birim,
            )
        )
        .order_by(User.ust_birim.asc(), User.birim.asc(), User.ad.asc(), User.soyad.asc())
        .all()
    )

def _existing_table_names() -> set[str]:
    try:
        return set(sa_inspect(db.engine).get_table_names())
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/hierarchy_admin_service.py:359")
        return set()


def _model_table_exists(model: Any, existing_tables: set[str] | None = None) -> bool:
    table_name = getattr(model, "__tablename__", None)
    if not table_name:
        return False
    tables = existing_tables if existing_tables is not None else _existing_table_names()
    return table_name in tables


def _safe_model_delete(model: Any, existing_tables: set[str] | None = None) -> None:
    if not _model_table_exists(model, existing_tables):
        return
    model.query.delete(synchronize_session=False)


def _safe_user_reference_nullify(model: Any, *columns: str) -> None:
    existing_tables = _existing_table_names()
    if not _model_table_exists(model, existing_tables):
        return
    updates: dict[Any, Any] = {}
    for column in columns:
        attr = getattr(model, column, None)
        if attr is not None:
            updates[attr] = None
    if updates:
        model.query.update(updates, synchronize_session=False)

def _q(identifier: str) -> str:
    """SQL identifier icin guvenli cift tirnaklama."""
    return '"' + str(identifier).replace('"', '""') + '"'


def _user_fk_references_to_existing_tables() -> list[dict[str, Any]]:
    """DB'de gercekten var olan tablolardan users.id alanina FK veren kolonlari bulur."""
    try:
        inspector = sa_inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V5: sessiz except loglandi: app/services/hierarchy_admin_service.py:401")
        return []

    refs: list[dict[str, Any]] = []
    for table_name in sorted(existing_tables):
        if table_name == "users":
            continue
        try:
            columns = {col["name"]: col for col in inspector.get_columns(table_name)}
            foreign_keys = inspector.get_foreign_keys(table_name)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/hierarchy_admin_service.py:409)")
            continue

        for fk in foreign_keys:
            if fk.get("referred_table") != "users":
                continue
            if "id" not in (fk.get("referred_columns") or []):
                continue
            for column_name in fk.get("constrained_columns") or []:
                column_info = cast("dict[str, Any]", columns.get(column_name, {}))
                refs.append({
                    "table": table_name,
                    "column": column_name,
                    "nullable": bool(column_info.get("nullable", True)),
                })
    return refs


def _detach_non_admin_user_fk_references() -> list[dict[str, Any]]:
    """Admin disindaki kullanicilar silinmeden once users.id baglantilarini temizler."""
    touched: list[dict[str, Any]] = []
    for ref in _user_fk_references_to_existing_tables():
        table_name = ref["table"]
        column_name = ref["column"]
        if ref["nullable"]:
            sql = text(
                f"UPDATE {_q(table_name)} "
                f"SET {_q(column_name)} = NULL "
                f"WHERE {_q(column_name)} IN ("
                f"SELECT id FROM {_q('users')} WHERE lower(trim(role)) != :admin_role"
                f")"
            )
            action = "null"
        else:
            sql = text(
                f"DELETE FROM {_q(table_name)} "
                f"WHERE {_q(column_name)} IN ("
                f"SELECT id FROM {_q('users')} WHERE lower(trim(role)) != :admin_role"
                f")"
            )
            action = "delete"
        result = db.session.execute(sql, {"admin_role": "admin"})
        rowcount = int(result.rowcount or 0)  # type: ignore[attr-defined]
        if rowcount:
            touched.append({"table": table_name, "column": column_name, "action": action, "rowcount": rowcount})
    if touched:
        current_app.logger.info("BYS360 reset FK temizligi tamamlandi: %s", touched)
    return touched

def _delete_models_in_dependency_order(*models) -> None:
    model_by_table = {model.__tablename__: model for model in models}
    for table in reversed(db.metadata.sorted_tables):
        model = model_by_table.get(table.name)
        if model is not None:
            model.query.delete(synchronize_session=False)

def reset_all_personnel_and_related_data() -> None:
    _delete_models_in_dependency_order(
        PerformanceEvaluationItem,
        PerformanceEvaluation,
        EvaluationAssignment,
        AssignmentCoverageLog,
        PerformanceResultSnapshot,
        PerformanceImportBatchRow,
        PerformanceImportBatch,
        PerformancePublishLog,
        FeedbackMeeting,
        FeedbackRequest,
        EvaluationPublishLog,
        SupportFeedbackRating,
        SupportTicketStatusHistory,
        SupportTicketAttachment,
        SupportTicketMessage,
        SupportTicket,
        UserMenuPermission,
        LeaveBalance,
        PersonnelLeave,
        AttendanceException,
        DelegationAssignment,
        MessageAttachment,
        Message,
        MessageThreadParticipant,
        MessageThread,
        Notification,
        MailLog,
        SurveyAnswer,
        SurveyResponse,
        SurveyAssignment,
        SurveyQuestionOption,
        SurveyQuestion,
        Survey,
        EmployeeOrgAssignmentHistory,
        OrganizationUnitVersion,
    )

    User.query.update(
        {
            User.yonetici_sicil: None,
            User.ikinci_yonetici_sicil: None,
            User.ucuncu_yonetici_sicil: None,
            User.organization_unit_id: None,
        },
        synchronize_session=False,
    )

    OrganizationUnit.query.update(
        {
            OrganizationUnit.manager_user_id: None,
            OrganizationUnit.parent_id: None,
        },
        synchronize_session=False,
    )

    if _model_table_exists(SupportHelpArticle):
        SupportHelpArticle.query.update(
            {
                SupportHelpArticle.created_by_user_id: None,
                SupportHelpArticle.updated_by_user_id: None,
            },
            synchronize_session=False,
        )

    _detach_non_admin_user_fk_references()

    db.session.execute(
        # R05c / K4: every spelling of the admin role ("Admin ", "ADMIN") is kept.
        text('DELETE FROM "users" WHERE lower(trim(role)) != :admin_role'),
        {"admin_role": "admin"},
    )
    OrganizationUnit.query.delete(synchronize_session=False)
