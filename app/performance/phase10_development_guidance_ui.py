"""BYS360 Gelişim Rehberi - gelişmiş gelişim planı, karne yayın onayı ve karne görünürlüğü yardımcıları.

v8:
- Kullanıcı arayüzünde "Aşama 10" ifadesi gösterilmez.
- Karne Yayın Onayı basit checkbox olmaktan çıkarıldı:
  onay akışı, yayın kilidi, yetkili onay, İK/Admin kontrolü, onay notu, yayın kararı.
- Karne Görünürlüğü basit radio olmaktan çıkarıldı:
  görünürlük düzeyi, içerik seviyesi, personel bilgilendirme, PDF/karne geçmişi,
  personel onay okudu işareti ve görünürlük gerekçesi eklendi.
- Gelişim planları Başkan Onayına düşmez; yetkili amir / Grup Başkanı onayıyla yürür.
- Hata halinde session rollback yapılır; beyaz ekran zinciri engellenir.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from flask import current_app, flash, request
from sqlalchemy import inspect, text

from app.services import runtime_schema

if TYPE_CHECKING:
    from flask_sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

try:
    from flask_login import current_user
except Exception:  # pragma: no cover
    logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
    current_user = None

db: SQLAlchemy | None
try:
    from app.extensions import db
except Exception:  # pragma: no cover
    logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
    db = None


STATUS_LABELS = {
    "draft": "Taslak",
    "supervisor_review": "Yetkili Amir Onayı Bekliyor",
    "group_head_review": "Grup Başkanı Onayı Bekliyor",
    "hr_review": "İK/Admin Yayın Kontrolünde",
    "ready_to_publish": "Yayına Hazır",
    "published": "Yayınlandı",
    "locked": "Yayın Kilidi",
    "internal": "Sadece İç Not",
    "scorecard": "Karne Altında Gösterilecek",
    "approved": "Onaylandı",
    "rejected": "İade Edildi",
    "completed": "Tamamlandı",
    "needs_review": "Kontrol Gerekli",
}

PUBLICATION_STATUS_OPTIONS = [
    {"value": key, "label": label}
    for key, label in STATUS_LABELS.items()
    if key in {
        "draft",
        "supervisor_review",
        "group_head_review",
        "hr_review",
        "ready_to_publish",
        "published",
    }
]


TYPE_LABELS = {
    "development": "Gelişim Önerisi",
    "improvement_plan": "Gelişim Planı",
    "strength": "Güçlü Yön / Başarıyı Sürdürme",
    "warning": "Düşük Performans Gelişim Planı",
    "guidance": "Rehberlik Notu",
    "followup": "Takip Aksiyonu",
}

AREA_LABELS = {
    "job_quality": "İş Kalitesi",
    "communication": "İletişim",
    "teamwork": "Ekip Çalışması",
    "time_management": "Zaman Yönetimi",
    "responsibility": "Sorumluluk ve Takip",
    "institutional_compliance": "Kurumsal Uyum",
    "technical_skill": "Teknik / Mesleki Beceri",
    "leadership": "Liderlik ve Yönlendirme",
    "service_quality": "Hizmet Kalitesi",
    "other": "Diğer",
}

PRIORITY_LABELS = {
    "low": "Düşük",
    "normal": "Normal",
    "high": "Yüksek",
    "critical": "Kritik",
}

FOLLOW_STATUS_LABELS = {
    "not_started": "Başlamadı",
    "in_progress": "Takipte",
    "completed": "Tamamlandı",
    "deferred": "Sonraki Döneme Aktarıldı",
}

FOLLOW_FREQUENCY_LABELS = {
    "weekly": "Haftalık",
    "biweekly": "İki Haftada Bir",
    "monthly": "Aylık",
    "period_end": "Dönem Sonu",
    "as_needed": "İhtiyaca Göre",
}

APPROVAL_ROLE_LABELS = {
    "supervisor": "Yetkili Amir",
    "group_head": "Grup Başkanı",
    "hr_admin": "İK/Admin",
    "none": "Onay Gerektirmez",
}

APPROVAL_FLOW_LABELS = {
    "author_only": "Hazırlayan Kaydı",
    "supervisor_then_hr": "Yetkili Amir → İK/Admin",
    "group_head_then_hr": "Grup Başkanı → İK/Admin",
    "hr_publish_only": "İK/Admin Yayın Kontrolü",
    "direct_publish": "Doğrudan Yayın",
}

VISIBILITY_MODE_LABELS = {
    "internal_only": "Personele Gösterme",
    "after_publish": "Karne Yayınlandıktan Sonra Göster",
    "after_ack": "Personel Bilgilendirmesiyle Göster",
    "manager_only": "Yalnızca Yönetici/İK Görsün",
}

VISIBILITY_DETAIL_LABELS = {
    "summary": "Kısa Özet",
    "goal_action": "Hedef + Aksiyon",
    "full_plan": "Tam Gelişim Planı",
    "guidance_only": "Yalnızca Rehber Notu",
}


def _rollback_safely() -> None:
    try:
        if db is not None:
            db.session.rollback()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/performance/phase10_development_guidance_ui.py)")


def _safe(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value if value else default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "evet", "published", "approved"}


def _has_table(table_name: str) -> bool:
    if db is None:
        return False
    try:
        return inspect(db.engine).has_table(table_name)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _rollback_safely()
        return False


def _cols(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    try:
        return {c["name"] for c in inspect(db.engine).get_columns(table_name)}  # type: ignore[union-attr]
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        _rollback_safely()
        return set()


def _current_user_id() -> int | None:
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            return getattr(current_user, "id", None)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None
    return None


def _current_user_name() -> str:
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            for attr in ("full_name", "full_name_cache", "ad_soyad", "name", "email"):
                val = getattr(current_user, attr, None)
                if val:
                    return str(val)
            ad = getattr(current_user, "ad", None)
            soyad = getattr(current_user, "soyad", None)
            if ad or soyad:
                return f"{ad or ''} {soyad or ''}".strip()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/performance/phase10_development_guidance_ui.py)")
    return ""


def provision_phase10_recommendation_table() -> bool:
    """Create/complete the table (explicit maintenance only: flask runtime-schema provision)."""
    if db is None:
        return False

    try:
        dialect = db.engine.dialect.name
        if dialect == "postgresql":
            create_sql = """
            CREATE TABLE IF NOT EXISTS performance_development_recommendations (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NULL,
                employee_name TEXT NULL,
                period_id INTEGER NULL,
                period_name TEXT NULL,
                recommendation_type VARCHAR(40) NOT NULL DEFAULT 'development',
                development_area VARCHAR(80) NOT NULL DEFAULT 'job_quality',
                priority VARCHAR(30) NOT NULL DEFAULT 'normal',
                follow_status VARCHAR(40) NOT NULL DEFAULT 'not_started',
                follow_frequency VARCHAR(40) NOT NULL DEFAULT 'monthly',
                visibility_scope VARCHAR(40) NOT NULL DEFAULT 'internal',
                publication_status VARCHAR(40) NOT NULL DEFAULT 'draft',
                show_on_scorecard BOOLEAN NOT NULL DEFAULT FALSE,
                is_published BOOLEAN NOT NULL DEFAULT FALSE,
                approved_by_hr BOOLEAN NOT NULL DEFAULT FALSE,
                supervisor_approval_required BOOLEAN NOT NULL DEFAULT TRUE,
                supervisor_approved BOOLEAN NOT NULL DEFAULT FALSE,
                approval_role VARCHAR(40) NOT NULL DEFAULT 'group_head',
                approval_flow VARCHAR(60) NOT NULL DEFAULT 'group_head_then_hr',
                approver_name TEXT NULL,
                approval_note TEXT NULL,
                publish_lock BOOLEAN NOT NULL DEFAULT FALSE,
                publish_lock_reason TEXT NULL,
                hr_publish_required BOOLEAN NOT NULL DEFAULT TRUE,
                hr_publish_approved BOOLEAN NOT NULL DEFAULT FALSE,
                scorecard_visibility_mode VARCHAR(60) NOT NULL DEFAULT 'internal_only',
                scorecard_detail_level VARCHAR(60) NOT NULL DEFAULT 'summary',
                show_in_pdf BOOLEAN NOT NULL DEFAULT TRUE,
                show_in_scorecard_history BOOLEAN NOT NULL DEFAULT TRUE,
                employee_notification_required BOOLEAN NOT NULL DEFAULT FALSE,
                employee_ack_required BOOLEAN NOT NULL DEFAULT FALSE,
                visibility_reason TEXT NULL,
                employee_message TEXT NULL,
                owner_name TEXT NULL,
                target_date DATE NULL,
                basis_note TEXT NULL,
                current_state TEXT NULL,
                target_outcome TEXT NULL,
                smart_goal TEXT NULL,
                action_steps TEXT NULL,
                support_needs TEXT NULL,
                success_criteria TEXT NULL,
                evidence_plan TEXT NULL,
                recommendation_text TEXT NOT NULL,
                created_by INTEGER NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
            alter_defs = {
                "employee_id": "INTEGER NULL",
                "employee_name": "TEXT NULL",
                "period_id": "INTEGER NULL",
                "period_name": "TEXT NULL",
                "recommendation_type": "VARCHAR(40) NOT NULL DEFAULT 'development'",
                "development_area": "VARCHAR(80) NOT NULL DEFAULT 'job_quality'",
                "priority": "VARCHAR(30) NOT NULL DEFAULT 'normal'",
                "follow_status": "VARCHAR(40) NOT NULL DEFAULT 'not_started'",
                "follow_frequency": "VARCHAR(40) NOT NULL DEFAULT 'monthly'",
                "visibility_scope": "VARCHAR(40) NOT NULL DEFAULT 'internal'",
                "publication_status": "VARCHAR(40) NOT NULL DEFAULT 'draft'",
                "show_on_scorecard": "BOOLEAN NOT NULL DEFAULT FALSE",
                "is_published": "BOOLEAN NOT NULL DEFAULT FALSE",
                "approved_by_hr": "BOOLEAN NOT NULL DEFAULT FALSE",
                "supervisor_approval_required": "BOOLEAN NOT NULL DEFAULT TRUE",
                "supervisor_approved": "BOOLEAN NOT NULL DEFAULT FALSE",
                "approval_role": "VARCHAR(40) NOT NULL DEFAULT 'group_head'",
                "approval_flow": "VARCHAR(60) NOT NULL DEFAULT 'group_head_then_hr'",
                "approver_name": "TEXT NULL",
                "approval_note": "TEXT NULL",
                "publish_lock": "BOOLEAN NOT NULL DEFAULT FALSE",
                "publish_lock_reason": "TEXT NULL",
                "hr_publish_required": "BOOLEAN NOT NULL DEFAULT TRUE",
                "hr_publish_approved": "BOOLEAN NOT NULL DEFAULT FALSE",
                "scorecard_visibility_mode": "VARCHAR(60) NOT NULL DEFAULT 'internal_only'",
                "scorecard_detail_level": "VARCHAR(60) NOT NULL DEFAULT 'summary'",
                "show_in_pdf": "BOOLEAN NOT NULL DEFAULT TRUE",
                "show_in_scorecard_history": "BOOLEAN NOT NULL DEFAULT TRUE",
                "employee_notification_required": "BOOLEAN NOT NULL DEFAULT FALSE",
                "employee_ack_required": "BOOLEAN NOT NULL DEFAULT FALSE",
                "visibility_reason": "TEXT NULL",
                "employee_message": "TEXT NULL",
                "owner_name": "TEXT NULL",
                "target_date": "DATE NULL",
                "basis_note": "TEXT NULL",
                "current_state": "TEXT NULL",
                "target_outcome": "TEXT NULL",
                "smart_goal": "TEXT NULL",
                "action_steps": "TEXT NULL",
                "support_needs": "TEXT NULL",
                "success_criteria": "TEXT NULL",
                "evidence_plan": "TEXT NULL",
                "recommendation_text": "TEXT NULL",
                "created_by": "INTEGER NULL",
                "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
            }
        else:
            create_sql = """
            CREATE TABLE IF NOT EXISTS performance_development_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NULL,
                employee_name TEXT NULL,
                period_id INTEGER NULL,
                period_name TEXT NULL,
                recommendation_type TEXT NOT NULL DEFAULT 'development',
                development_area TEXT NOT NULL DEFAULT 'job_quality',
                priority TEXT NOT NULL DEFAULT 'normal',
                follow_status TEXT NOT NULL DEFAULT 'not_started',
                follow_frequency TEXT NOT NULL DEFAULT 'monthly',
                visibility_scope TEXT NOT NULL DEFAULT 'internal',
                publication_status TEXT NOT NULL DEFAULT 'draft',
                show_on_scorecard INTEGER NOT NULL DEFAULT 0,
                is_published INTEGER NOT NULL DEFAULT 0,
                approved_by_hr INTEGER NOT NULL DEFAULT 0,
                supervisor_approval_required INTEGER NOT NULL DEFAULT 1,
                supervisor_approved INTEGER NOT NULL DEFAULT 0,
                approval_role TEXT NOT NULL DEFAULT 'group_head',
                approval_flow TEXT NOT NULL DEFAULT 'group_head_then_hr',
                approver_name TEXT NULL,
                approval_note TEXT NULL,
                publish_lock INTEGER NOT NULL DEFAULT 0,
                publish_lock_reason TEXT NULL,
                hr_publish_required INTEGER NOT NULL DEFAULT 1,
                hr_publish_approved INTEGER NOT NULL DEFAULT 0,
                scorecard_visibility_mode TEXT NOT NULL DEFAULT 'internal_only',
                scorecard_detail_level TEXT NOT NULL DEFAULT 'summary',
                show_in_pdf INTEGER NOT NULL DEFAULT 1,
                show_in_scorecard_history INTEGER NOT NULL DEFAULT 1,
                employee_notification_required INTEGER NOT NULL DEFAULT 0,
                employee_ack_required INTEGER NOT NULL DEFAULT 0,
                visibility_reason TEXT NULL,
                employee_message TEXT NULL,
                owner_name TEXT NULL,
                target_date TEXT NULL,
                basis_note TEXT NULL,
                current_state TEXT NULL,
                target_outcome TEXT NULL,
                smart_goal TEXT NULL,
                action_steps TEXT NULL,
                support_needs TEXT NULL,
                success_criteria TEXT NULL,
                evidence_plan TEXT NULL,
                recommendation_text TEXT NOT NULL,
                created_by INTEGER NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
            alter_defs = {
                "employee_id": "INTEGER NULL",
                "employee_name": "TEXT NULL",
                "period_id": "INTEGER NULL",
                "period_name": "TEXT NULL",
                "recommendation_type": "TEXT NOT NULL DEFAULT 'development'",
                "development_area": "TEXT NOT NULL DEFAULT 'job_quality'",
                "priority": "TEXT NOT NULL DEFAULT 'normal'",
                "follow_status": "TEXT NOT NULL DEFAULT 'not_started'",
                "follow_frequency": "TEXT NOT NULL DEFAULT 'monthly'",
                "visibility_scope": "TEXT NOT NULL DEFAULT 'internal'",
                "publication_status": "TEXT NOT NULL DEFAULT 'draft'",
                "show_on_scorecard": "INTEGER NOT NULL DEFAULT 0",
                "is_published": "INTEGER NOT NULL DEFAULT 0",
                "approved_by_hr": "INTEGER NOT NULL DEFAULT 0",
                "supervisor_approval_required": "INTEGER NOT NULL DEFAULT 1",
                "supervisor_approved": "INTEGER NOT NULL DEFAULT 0",
                "approval_role": "TEXT NOT NULL DEFAULT 'group_head'",
                "approval_flow": "TEXT NOT NULL DEFAULT 'group_head_then_hr'",
                "approver_name": "TEXT NULL",
                "approval_note": "TEXT NULL",
                "publish_lock": "INTEGER NOT NULL DEFAULT 0",
                "publish_lock_reason": "TEXT NULL",
                "hr_publish_required": "INTEGER NOT NULL DEFAULT 1",
                "hr_publish_approved": "INTEGER NOT NULL DEFAULT 0",
                "scorecard_visibility_mode": "TEXT NOT NULL DEFAULT 'internal_only'",
                "scorecard_detail_level": "TEXT NOT NULL DEFAULT 'summary'",
                "show_in_pdf": "INTEGER NOT NULL DEFAULT 1",
                "show_in_scorecard_history": "INTEGER NOT NULL DEFAULT 1",
                "employee_notification_required": "INTEGER NOT NULL DEFAULT 0",
                "employee_ack_required": "INTEGER NOT NULL DEFAULT 0",
                "visibility_reason": "TEXT NULL",
                "employee_message": "TEXT NULL",
                "owner_name": "TEXT NULL",
                "target_date": "TEXT NULL",
                "basis_note": "TEXT NULL",
                "current_state": "TEXT NULL",
                "target_outcome": "TEXT NULL",
                "smart_goal": "TEXT NULL",
                "action_steps": "TEXT NULL",
                "support_needs": "TEXT NULL",
                "success_criteria": "TEXT NULL",
                "evidence_plan": "TEXT NULL",
                "recommendation_text": "TEXT NULL",
                "created_by": "INTEGER NULL",
                "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            }

        db.session.execute(text(create_sql))
        db.session.commit()

        existing = _cols("performance_development_recommendations")
        for col, ddl in alter_defs.items():
            if col not in existing:
                try:
                    db.session.execute(text(f"ALTER TABLE performance_development_recommendations ADD COLUMN {col} {ddl}"))
                    db.session.commit()
                except Exception as exc:
                    _rollback_safely()
                    current_app.logger.warning("Gelişim rehberi kolon ekleme atlandı: %s | %s", col, exc)

        return True
    except Exception as exc:
        _rollback_safely()
        try:
            current_app.logger.warning("Gelişim rehberi tablo hazırlığı atlandı: %s", exc)
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/performance/phase10_development_guidance_ui.py)")
        return False


# Owned by Alembic revision 29fee38a97e1, which creates exactly these columns.
DEVELOPMENT_RECOMMENDATIONS_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.development_recommendations",
    tables=("performance_development_recommendations",),
    columns=(
        ("performance_development_recommendations", "employee_id"),
        ("performance_development_recommendations", "employee_name"),
        ("performance_development_recommendations", "period_id"),
        ("performance_development_recommendations", "period_name"),
        ("performance_development_recommendations", "recommendation_type"),
        ("performance_development_recommendations", "development_area"),
        ("performance_development_recommendations", "priority"),
        ("performance_development_recommendations", "follow_status"),
        ("performance_development_recommendations", "follow_frequency"),
        ("performance_development_recommendations", "visibility_scope"),
        ("performance_development_recommendations", "publication_status"),
        ("performance_development_recommendations", "show_on_scorecard"),
        ("performance_development_recommendations", "is_published"),
        ("performance_development_recommendations", "approved_by_hr"),
        ("performance_development_recommendations", "supervisor_approval_required"),
        ("performance_development_recommendations", "supervisor_approved"),
        ("performance_development_recommendations", "approval_role"),
        ("performance_development_recommendations", "approval_flow"),
        ("performance_development_recommendations", "approver_name"),
        ("performance_development_recommendations", "approval_note"),
        ("performance_development_recommendations", "publish_lock"),
        ("performance_development_recommendations", "publish_lock_reason"),
        ("performance_development_recommendations", "hr_publish_required"),
        ("performance_development_recommendations", "hr_publish_approved"),
        ("performance_development_recommendations", "scorecard_visibility_mode"),
        ("performance_development_recommendations", "scorecard_detail_level"),
        ("performance_development_recommendations", "show_in_pdf"),
        ("performance_development_recommendations", "show_in_scorecard_history"),
        ("performance_development_recommendations", "employee_notification_required"),
        ("performance_development_recommendations", "employee_ack_required"),
        ("performance_development_recommendations", "visibility_reason"),
        ("performance_development_recommendations", "employee_message"),
        ("performance_development_recommendations", "owner_name"),
        ("performance_development_recommendations", "target_date"),
        ("performance_development_recommendations", "basis_note"),
        ("performance_development_recommendations", "current_state"),
        ("performance_development_recommendations", "target_outcome"),
        ("performance_development_recommendations", "smart_goal"),
        ("performance_development_recommendations", "action_steps"),
        ("performance_development_recommendations", "support_needs"),
        ("performance_development_recommendations", "success_criteria"),
        ("performance_development_recommendations", "evidence_plan"),
        ("performance_development_recommendations", "recommendation_text"),
        ("performance_development_recommendations", "created_by"),
        ("performance_development_recommendations", "created_at"),
        ("performance_development_recommendations", "updated_at"),
    ),
    provision=provision_phase10_recommendation_table,
))


def ensure_phase10_recommendation_table() -> bool:
    """Verify the recommendations table and its columns exist; never alters it."""
    if db is None:
        return False
    try:
        runtime_schema.require(DEVELOPMENT_RECOMMENDATIONS_SCHEMA)
    except runtime_schema.RuntimeSchemaMissing as exc:
        current_app.logger.error("Gelişim rehberi tablosu hazır değil; eksik: %s", ", ".join(exc.missing))
        return False
    return True

def _derive_publication_status(form: Any, show_on_scorecard: bool, is_published: bool) -> tuple[str, bool]:
    publication_status = _safe(form.get("publication_status"), "draft")
    approval_role = _safe(form.get("approval_role"), "group_head")
    supervisor_required = _bool(form.get("supervisor_approval_required"))
    supervisor_approved = _bool(form.get("supervisor_approved"))
    hr_required = _bool(form.get("hr_publish_required"))
    hr_approved = _bool(form.get("hr_publish_approved"))
    publish_lock = _bool(form.get("publish_lock"))

    if publish_lock:
        return "locked", False

    if show_on_scorecard:
        if supervisor_required and not supervisor_approved:
            if approval_role == "group_head":
                return "group_head_review", False
            if approval_role == "supervisor":
                return "supervisor_review", False
            return "hr_review", False
        if hr_required and not hr_approved:
            return "hr_review", False
        if publication_status == "published":
            return "published", True
        if supervisor_approved and (not hr_required or hr_approved):
            return "ready_to_publish", False

    return publication_status, is_published


def save_phase10_recommendation_from_request() -> bool:
    """Gelişim rehberi formundan gelen gelişim planını kaydeder."""
    if db is None:
        return False

    if not ensure_phase10_recommendation_table():
        flash("Gelişim rehberi tablosu hazırlanamadı. Veritabanı bağlantısı kontrol edilmeli.", "danger")
        return False

    form = request.form
    recommendation_text = _safe(form.get("recommendation_text"))
    if not recommendation_text:
        flash("Gelişim önerisi metni boş bırakılamaz.", "warning")
        return False

    scorecard_visibility_mode = _safe(form.get("scorecard_visibility_mode"), "internal_only")
    visibility_scope = "scorecard" if scorecard_visibility_mode in {"after_publish", "after_ack"} else "internal"
    show_on_scorecard = visibility_scope == "scorecard"
    is_published = _safe(form.get("publication_status"), "draft") == "published"
    publication_status, is_published = _derive_publication_status(form, show_on_scorecard, is_published)

    payload = {
        "employee_id": form.get("employee_id") or None,
        "employee_name": _safe(form.get("employee_name")),
        "period_id": form.get("period_id") or None,
        "period_name": _safe(form.get("period_name")),
        "recommendation_type": _safe(form.get("recommendation_type"), "improvement_plan"),
        "development_area": _safe(form.get("development_area"), "job_quality"),
        "priority": _safe(form.get("priority"), "normal"),
        "follow_status": _safe(form.get("follow_status"), "not_started"),
        "follow_frequency": _safe(form.get("follow_frequency"), "monthly"),
        "visibility_scope": visibility_scope,
        "publication_status": publication_status,
        "show_on_scorecard": show_on_scorecard,
        "is_published": is_published,
        "approved_by_hr": _bool(form.get("hr_publish_approved")),
        "supervisor_approval_required": _bool(form.get("supervisor_approval_required")),
        "supervisor_approved": _bool(form.get("supervisor_approved")),
        "approval_role": _safe(form.get("approval_role"), "group_head"),
        "approval_flow": _safe(form.get("approval_flow"), "group_head_then_hr"),
        "approver_name": _safe(form.get("approver_name")),
        "approval_note": _safe(form.get("approval_note")),
        "publish_lock": _bool(form.get("publish_lock")),
        "publish_lock_reason": _safe(form.get("publish_lock_reason")),
        "hr_publish_required": _bool(form.get("hr_publish_required")),
        "hr_publish_approved": _bool(form.get("hr_publish_approved")),
        "scorecard_visibility_mode": scorecard_visibility_mode,
        "scorecard_detail_level": _safe(form.get("scorecard_detail_level"), "summary"),
        "show_in_pdf": _bool(form.get("show_in_pdf")),
        "show_in_scorecard_history": _bool(form.get("show_in_scorecard_history")),
        "employee_notification_required": _bool(form.get("employee_notification_required")),
        "employee_ack_required": _bool(form.get("employee_ack_required")),
        "visibility_reason": _safe(form.get("visibility_reason")),
        "employee_message": _safe(form.get("employee_message")),
        "owner_name": _safe(form.get("owner_name")) or _current_user_name(),
        "target_date": form.get("target_date") or None,
        "basis_note": _safe(form.get("basis_note")),
        "current_state": _safe(form.get("current_state")),
        "target_outcome": _safe(form.get("target_outcome")),
        "smart_goal": _safe(form.get("smart_goal")),
        "action_steps": _safe(form.get("action_steps")),
        "support_needs": _safe(form.get("support_needs")),
        "success_criteria": _safe(form.get("success_criteria")),
        "evidence_plan": _safe(form.get("evidence_plan")),
        "recommendation_text": recommendation_text,
        "created_by": _current_user_id(),
    }

    sql = text("""
        INSERT INTO performance_development_recommendations (
            employee_id, employee_name, period_id, period_name,
            recommendation_type, development_area, priority, follow_status, follow_frequency,
            visibility_scope, publication_status, show_on_scorecard, is_published,
            approved_by_hr, supervisor_approval_required, supervisor_approved,
            approval_role, approval_flow, approver_name, approval_note,
            publish_lock, publish_lock_reason, hr_publish_required, hr_publish_approved,
            scorecard_visibility_mode, scorecard_detail_level, show_in_pdf, show_in_scorecard_history,
            employee_notification_required, employee_ack_required, visibility_reason, employee_message,
            owner_name, target_date, basis_note, current_state, target_outcome,
            smart_goal, action_steps, support_needs, success_criteria, evidence_plan,
            recommendation_text, created_by, created_at, updated_at
        ) VALUES (
            :employee_id, :employee_name, :period_id, :period_name,
            :recommendation_type, :development_area, :priority, :follow_status, :follow_frequency,
            :visibility_scope, :publication_status, :show_on_scorecard, :is_published,
            :approved_by_hr, :supervisor_approval_required, :supervisor_approved,
            :approval_role, :approval_flow, :approver_name, :approval_note,
            :publish_lock, :publish_lock_reason, :hr_publish_required, :hr_publish_approved,
            :scorecard_visibility_mode, :scorecard_detail_level, :show_in_pdf, :show_in_scorecard_history,
            :employee_notification_required, :employee_ack_required, :visibility_reason, :employee_message,
            :owner_name, :target_date, :basis_note, :current_state, :target_outcome,
            :smart_goal, :action_steps, :support_needs, :success_criteria, :evidence_plan,
            :recommendation_text, :created_by, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
    """)

    try:
        db.session.execute(sql, payload)
        db.session.commit()
        if payload["show_on_scorecard"] and payload["is_published"]:
            flash("Gelişim planı kaydedildi ve karne altında gösterilecek şekilde yayınlandı.", "success")
        elif payload["show_on_scorecard"]:
            flash("Gelişim planı kaydedildi. Karneye düşmesi için seçilen onay/yayın kapıları tamamlanmalıdır.", "info")
        else:
            flash("Gelişim planı iç değerlendirme kaydı olarak kaydedildi.", "success")
        return True
    except Exception as exc:
        _rollback_safely()
        current_app.logger.exception("Gelişim rehberi kaydedilemedi: %s", exc)
        flash("Gelişim planı kaydedilemedi. Veritabanı şeması veya yetki kontrolü incelenmelidir.", "danger")
        return False


def normalize_recommendation(row: dict[str, Any]) -> dict[str, Any]:
    publication_status = _safe(row.get("publication_status"), "draft")
    show_on_scorecard = _bool(row.get("show_on_scorecard"))
    is_published = _bool(row.get("is_published"))
    supervisor_required = _bool(row.get("supervisor_approval_required"))
    supervisor_approved = _bool(row.get("supervisor_approved"))
    hr_required = _bool(row.get("hr_publish_required"))
    hr_approved = _bool(row.get("hr_publish_approved"))
    publish_lock = _bool(row.get("publish_lock"))
    scorecard_visibility_mode = _safe(row.get("scorecard_visibility_mode"), "internal_only")
    detail_level = _safe(row.get("scorecard_detail_level"), "summary")

    visible_to_employee = (
        show_on_scorecard
        and is_published
        and not publish_lock
        and (not supervisor_required or supervisor_approved)
        and (not hr_required or hr_approved)
        and scorecard_visibility_mode in {"after_publish", "after_ack"}
    )

    if visible_to_employee:
        visibility_label = "Personel Karnesinde Görünür"
        visibility_badge = "green"
    elif show_on_scorecard and publish_lock:
        visibility_label = "Yayın Kilidinde"
        visibility_badge = "red"
    elif show_on_scorecard:
        visibility_label = "Yayın Kapıları Tamamlanınca Görünecek"
        visibility_badge = "amber"
    else:
        visibility_label = "Sadece İç Değerlendirme"
        visibility_badge = "gray"

    created = row.get("updated_at") or row.get("created_at")
    created_label = created.strftime("%d.%m.%Y %H:%M") if isinstance(created, datetime) else _safe(created, "Tarih yok")

    return {
        "id": row.get("id"),
        "employee_id": row.get("employee_id"),
        "employee_name": _safe(row.get("employee_name"), "Personel seçilmedi"),
        "period_name": _safe(row.get("period_name"), "Dönem belirtilmedi"),
        "recommendation_type": _safe(row.get("recommendation_type"), "improvement_plan"),
        "recommendation_type_label": TYPE_LABELS.get(_safe(row.get("recommendation_type"), "improvement_plan"), "Gelişim Planı"),
        "development_area": _safe(row.get("development_area"), "job_quality"),
        "development_area_label": AREA_LABELS.get(_safe(row.get("development_area"), "job_quality"), "İş Kalitesi"),
        "priority": _safe(row.get("priority"), "normal"),
        "priority_label": PRIORITY_LABELS.get(_safe(row.get("priority"), "normal"), "Normal"),
        "follow_status": _safe(row.get("follow_status"), "not_started"),
        "follow_status_label": FOLLOW_STATUS_LABELS.get(_safe(row.get("follow_status"), "not_started"), "Başlamadı"),
        "follow_frequency": _safe(row.get("follow_frequency"), "monthly"),
        "follow_frequency_label": FOLLOW_FREQUENCY_LABELS.get(_safe(row.get("follow_frequency"), "monthly"), "Aylık"),
        "publication_status": publication_status,
        "publication_label": STATUS_LABELS.get(publication_status, "Taslak"),
        "visibility_label": visibility_label,
        "visibility_badge": visibility_badge,
        "show_on_scorecard": show_on_scorecard,
        "is_published": is_published,
        "supervisor_approval_required": supervisor_required,
        "supervisor_approved": supervisor_approved,
        "hr_publish_required": hr_required,
        "hr_publish_approved": hr_approved,
        "publish_lock": publish_lock,
        "publish_lock_reason": _safe(row.get("publish_lock_reason")),
        "approval_role": _safe(row.get("approval_role"), "group_head"),
        "approval_role_label": APPROVAL_ROLE_LABELS.get(_safe(row.get("approval_role"), "group_head"), "Grup Başkanı"),
        "approval_flow": _safe(row.get("approval_flow"), "group_head_then_hr"),
        "approval_flow_label": APPROVAL_FLOW_LABELS.get(_safe(row.get("approval_flow"), "group_head_then_hr"), "Grup Başkanı → İK/Admin"),
        "approver_name": _safe(row.get("approver_name"), ""),
        "approval_note": _safe(row.get("approval_note")),
        "scorecard_visibility_mode": scorecard_visibility_mode,
        "scorecard_visibility_label": VISIBILITY_MODE_LABELS.get(scorecard_visibility_mode, "Personele Gösterme"),
        "scorecard_detail_level": detail_level,
        "scorecard_detail_label": VISIBILITY_DETAIL_LABELS.get(detail_level, "Kısa Özet"),
        "show_in_pdf": _bool(row.get("show_in_pdf")),
        "show_in_scorecard_history": _bool(row.get("show_in_scorecard_history")),
        "employee_notification_required": _bool(row.get("employee_notification_required")),
        "employee_ack_required": _bool(row.get("employee_ack_required")),
        "visibility_reason": _safe(row.get("visibility_reason")),
        "employee_message": _safe(row.get("employee_message")),
        "visible_to_employee": visible_to_employee,
        "owner_name": _safe(row.get("owner_name"), "Sorumlu belirtilmedi"),
        "target_date": _safe(row.get("target_date"), "Hedef tarih yok"),
        "basis_note": _safe(row.get("basis_note")),
        "current_state": _safe(row.get("current_state")),
        "target_outcome": _safe(row.get("target_outcome")),
        "smart_goal": _safe(row.get("smart_goal")),
        "action_steps": _safe(row.get("action_steps")),
        "support_needs": _safe(row.get("support_needs")),
        "success_criteria": _safe(row.get("success_criteria")),
        "evidence_plan": _safe(row.get("evidence_plan")),
        "recommendation_text": _safe(row.get("recommendation_text"), "Gelişim önerisi metni bulunamadı."),
        "created_label": created_label,
    }


def _fetch_recommendations(limit: int = 120) -> list[dict[str, Any]]:
    if not ensure_phase10_recommendation_table():
        return []
    try:
        sql = text("""
            SELECT *
            FROM performance_development_recommendations
            ORDER BY updated_at DESC, created_at DESC, id DESC
            LIMIT :limit
        """)
        rows = db.session.execute(sql, {"limit": limit}).all()  # type: ignore[union-attr]
        return [dict(r._mapping) for r in rows]
    except Exception as exc:
        _rollback_safely()
        current_app.logger.warning("Gelişim rehberi kayıtları okunamadı: %s", exc)
        return []


_SCORECARD_SAFE_CLAUSES = (
    "show_on_scorecard = :true_value",
    "is_published = :true_value",
    "publish_lock = :false_value",
    "(supervisor_approval_required = :false_value OR supervisor_approved = :true_value)",
    "(hr_publish_required = :false_value OR hr_publish_approved = :true_value)",
    "scorecard_visibility_mode IN ('after_publish', 'after_ack')",
    "employee_id = :employee_id",
)


def fetch_scorecard_safe_recommendations(employee_id: Any, period_id: Any = None, limit: int = 10) -> list[dict[str, Any]]:
    """Karnede gösterilmesi güvenli kanonik gelişim önerileri (tek kaynak).

    Karne detayı, karne PDF'i ve 70 altı yayın kapısı aynı kümeyi buradan okur: karneye
    gösterilecek, yayınlanmış, kilitsiz, onayları tamamlanmış ve yayın sonrası görünür
    kayıtlar; aynı personel, aynı dönem ya da döneme bağlı olmayan kayıtlar. Personel
    belirtilmezse hiçbir kayıt döndürülmez (başka personelin önerisi sızmaz).
    """
    if db is None or employee_id in (None, "", "None") or not ensure_phase10_recommendation_table():
        return []
    clauses = list(_SCORECARD_SAFE_CLAUSES)
    params: dict[str, Any] = {"true_value": True, "false_value": False, "employee_id": employee_id, "limit": limit}
    if period_id not in (None, "", "None"):
        clauses.append("(period_id = :period_id OR period_id IS NULL)")
        params["period_id"] = period_id
    sql = text(f"""
        SELECT *
        FROM performance_development_recommendations
        WHERE {' AND '.join(clauses)}
        ORDER BY updated_at DESC, created_at DESC, id DESC
        LIMIT :limit
    """)
    rows = db.session.execute(sql, params).all()
    return [normalize_recommendation(dict(r._mapping)) for r in rows]


def has_scorecard_safe_recommendation(employee_id: Any, period_id: Any = None) -> bool:
    """70 altı yayın kapısı: karnede gösterilebilir en az bir kanonik öneri var mı?"""
    return bool(fetch_scorecard_safe_recommendations(employee_id, period_id, limit=1))


def get_scorecard_development_guidance(employee_id: Any = None, period_id: Any = None, limit: int = 10) -> list[dict[str, Any]]:
    """Karne altında sadece personele görünmesi güvenli kayıtları döndürür."""
    return fetch_scorecard_safe_recommendations(employee_id, period_id, limit)


def _concat_name_expr(cols: set[str]) -> str:
    fallback_exprs: list[str] = []

    if "ad" in cols and "soyad" in cols:
        fallback_exprs.append("NULLIF(TRIM(COALESCE(ad, '') || ' ' || COALESCE(soyad, '')), '')")
    elif "ad" in cols:
        fallback_exprs.append("NULLIF(TRIM(COALESCE(ad, '')), '')")
    elif "soyad" in cols:
        fallback_exprs.append("NULLIF(TRIM(COALESCE(soyad, '')), '')")

    # BYS360 DEFECT FS (Final Sweep FS-R2): the PostgreSQL-only `::text` cast
    # broke on SQLite ("unrecognized token: ':'"), silently swallowed by
    # _fetch_people_options()'s broad except into an empty personnel picker.
    # Every column listed here is already a text/string column (users.email,
    # users.sicil_no, users.full_name_cache, users._full_name_compat, etc.),
    # so the cast was also functionally redundant -- removed outright rather
    # than reformulated as a portable CAST(... AS TEXT).
    for c in ("full_name", "full_name_cache", "ad_soyad", "name", "display_name", "email", "sicil_no"):
        if c in cols:
            fallback_exprs.append(f"NULLIF(TRIM(COALESCE({c}, '')), '')")

    fallback_exprs.append("CAST(id AS TEXT)")
    return "COALESCE(" + ", ".join(fallback_exprs) + ")"


def _fetch_people_options(limit: int = 300) -> list[dict[str, Any]]:
    if db is None or not _has_table("users"):
        return []

    cols = _cols("users")
    if "id" not in cols:
        return []

    name_expr = _concat_name_expr(cols)
    status_clause = ""
    if "is_active" in cols:
        status_clause = "WHERE is_active = true" if db.engine.dialect.name == "postgresql" else "WHERE is_active = 1"

    try:
        rows = db.session.execute(text(f"""
            SELECT id, {name_expr} AS label
            FROM users
            {status_clause}
            ORDER BY label ASC
            LIMIT :limit
        """), {"limit": limit}).all()
        return [{"id": r._mapping["id"], "label": r._mapping["label"]} for r in rows]
    except Exception as exc:
        _rollback_safely()
        current_app.logger.warning("Gelişim rehberi personel listesi okunamadı: %s", exc)
        return []


def _fetch_period_options(limit: int = 100) -> list[dict[str, Any]]:
    if db is None or not _has_table("performance_periods"):
        return []

    cols = _cols("performance_periods")
    if "id" not in cols:
        return []

    name_col = None
    for c in ("name", "title", "period_name", "label"):
        if c in cols:
            name_col = c
            break

    if not name_col:
        return []

    try:
        rows = db.session.execute(text(f"""
            SELECT id, {name_col} AS label
            FROM performance_periods
            ORDER BY id DESC
            LIMIT :limit
        """), {"limit": limit}).all()
        return [{"id": r._mapping["id"], "label": r._mapping["label"]} for r in rows]
    except Exception as exc:
        _rollback_safely()
        current_app.logger.warning("Gelişim rehberi dönem listesi okunamadı: %s", exc)
        return []


def build_phase10_meeting_development_context() -> dict[str, Any]:
    recommendations = [normalize_recommendation(r) for r in _fetch_recommendations()]
    visible_count = sum(1 for r in recommendations if r["visible_to_employee"])
    preparing_count = sum(1 for r in recommendations if r["show_on_scorecard"] and not r["visible_to_employee"])
    internal_count = sum(1 for r in recommendations if not r["show_on_scorecard"])
    approval_pending_count = sum(
        1 for r in recommendations
        if r["show_on_scorecard"]
        and (
            (r["supervisor_approval_required"] and not r["supervisor_approved"])
            or (r["hr_publish_required"] and not r["hr_publish_approved"])
        )
    )
    locked_count = sum(1 for r in recommendations if r["publish_lock"])

    return {
        "page_title": "Gelişim Rehberi Merkezi",
        "page_subtitle": "Performans sonucunu gelişim planı, çok aşamalı yayın onayı, karne görünürlüğü ve takip aksiyonuyla bağlayan kurumsal ekran.",
        "recommendations": recommendations,
        "people_options": _fetch_people_options(),
        "period_options": _fetch_period_options(),
        "stats": {
            "total_records": len(recommendations),
            "visible_count": visible_count,
            "preparing_count": preparing_count,
            "internal_count": internal_count,
            "approval_pending_count": approval_pending_count,
            "locked_count": locked_count,
        },
        "type_labels": TYPE_LABELS,
        "area_labels": AREA_LABELS,
        "priority_labels": PRIORITY_LABELS,
        "follow_status_labels": FOLLOW_STATUS_LABELS,
        "follow_frequency_labels": FOLLOW_FREQUENCY_LABELS,
        "approval_role_labels": APPROVAL_ROLE_LABELS,
        "approval_flow_labels": APPROVAL_FLOW_LABELS,
        "visibility_mode_labels": VISIBILITY_MODE_LABELS,
        "visibility_detail_labels": VISIBILITY_DETAIL_LABELS,
        "publication_status_options": PUBLICATION_STATUS_OPTIONS,
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }

# BYS360_PHASE11_DEVELOPMENT_GUIDANCE_FINAL_MARKERS
PHASE11_DEVELOPMENT_GUIDANCE_VERSION = "2026-05-03-phase11-development-guidance-final-v1"
PHASE11_LOW_SCORE_GUIDANCE_LABEL = "70 altı gelişim önerisi"
PHASE11_HIGH_SCORE_STRENGTH_LABEL = "90 üstü güçlü yön notu"
PHASE11_EMPLOYEE_VISIBLE_RULE = "Personel yalnızca yayınlanan gelişim önerisini görür"
PHASE11_NO_AUTO_SCORE_RULE = "Gelişim önerisi otomatik puan veya idari karar üretmez"

