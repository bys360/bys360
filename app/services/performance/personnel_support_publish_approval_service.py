"""BYS360 Faz 1.4.B Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı.

Bu servis, performans karnesi personele açılmadan önce Admin/İK nihai yayınının
hemen önüne eklenen kurumsal ön onay adımını yönetir.

Akış:
    Değerlendirmeler tamamlandı
    → varsa 70 altı Başkan/onay süreci tamamlandı
    → Personel ve Destek Hizmetleri Grup Başkanı ön onayı
    → Admin/İK nihai yayın

Önemli sınır:
    Bu adım Başkan onayı yerine geçmez; Başkan onayından sonra ve Admin/İK
    yayından önce çalışır.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text

from app.extensions import db

logger = logging.getLogger(__name__)

PHASE1_4B_RULE_VERSION = "phase1.4b-personnel-support-publish-approval-v1"
APPROVAL_TABLE = "performance_personnel_support_publish_approvals"
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_RETURNED = "returned"
FINAL_STATUSES = {"tamamlandi", "tamamlandı", "completed", "published"}
LOW_SCORE_THRESHOLD = 70.0

STATUS_LABELS = {
    "pending": "Personel ve Destek Hizmetleri Grup Başkanı Onayı Bekliyor",
    "approved": "Personel ve Destek Hizmetleri Grup Başkanı Tarafından Onaylandı",
    "returned": "Personel ve Destek Hizmetleri Grup Başkanı Tarafından İade Edildi",
    "ready_for_hr_publish": "Admin/İK Yayınına Hazır",
    "published": "Yayınlandı",
}

PHASE1_4B_SCHEMA_REVISION = "7c4e1a9b2d60"
_PHASE14B_REQUIRED_COLUMNS = frozenset(
    {
        "id",
        "evaluation_id",
        "period_id",
        "employee_id",
        "final_score",
        "status",
        "requested_at",
        "requested_by_user_id",
        "decided_at",
        "decided_by_user_id",
        "decision_note",
        "return_note",
        "rule_version",
        "created_at",
        "updated_at",
    }
)
_PHASE14B_REQUIRED_INDEXES = frozenset(
    {
        "ix_phase14b_publish_approval_status",
        "ix_phase14b_publish_approval_period_status",
        "ix_phase14b_publish_approval_employee",
    }
)


class PersonnelSupportPublishSchemaNotReadyError(RuntimeError):
    """Raised when the Phase 1.4B schema migration has not been applied."""


@dataclass(frozen=True)
class Phase14BActionResult:
    ok: bool
    message: str
    approval_id: int | None = None


def _now() -> datetime:
    return datetime.utcnow()


def _normalize(value: Any) -> str:
    # BYS360 DEFECT AQ: 'İ'.lower() Python'da tek bir 'i' değil, 'i' +
    # COMBINING DOT ABOVE (U+0307) olmak üzere İKİ kod noktası üretir --
    # bu yüzden .lower() önce çalışırsa aşağıdaki tr_map'teki 'İ' anahtarı
    # asla eşleşmez. 'İ' burada .lower() çağrılmadan ÖNCE, tek kod noktalı
    # haldeyken ayrı olarak 'i'ye çevrilir.
    raw = str(value or "").strip().replace("İ", "i").lower()
    tr_map = str.maketrans("çğıöşüâîû", "cgiosuaiu")
    return raw.translate(tr_map).replace(" ", "_").replace("-", "_")


def _display_name_from_user(user: Any) -> str:
    if user is None:
        return ""
    full = str(getattr(user, "full_name", "") or "").strip()
    if full:
        return full
    ad = str(getattr(user, "ad", "") or "").strip()
    soyad = str(getattr(user, "soyad", "") or "").strip()
    name = f"{ad} {soyad}".strip()
    return name or str(getattr(user, "email", "") or "").strip() or "Kullanıcı"


def _actor_id(actor_or_id: Any | None) -> int | None:
    value = getattr(actor_or_id, "id", actor_or_id)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _scalar(sql: str, params: dict[str, Any] | None = None) -> Any:
    return db.session.execute(text(sql), params or {}).scalar()


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    return list(db.session.execute(text(sql), params or {}).mappings())


def table_exists(table_name: str = APPROVAL_TABLE) -> bool:
    try:
        return bool(inspect(db.engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/personnel_support_publish_approval_service.py | line=102")
        return False


def _phase1_4b_schema_gaps() -> list[str]:
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if APPROVAL_TABLE not in table_names:
        return [f"{APPROVAL_TABLE}: <tablo eksik>"]

    columns = {
        column["name"]
        for column in inspector.get_columns(APPROVAL_TABLE)
    }
    indexes = {
        index["name"]
        for index in inspector.get_indexes(APPROVAL_TABLE)
        if index.get("name")
    }

    gaps: list[str] = []
    missing_columns = sorted(_PHASE14B_REQUIRED_COLUMNS - columns)
    if missing_columns:
        gaps.append(f"{APPROVAL_TABLE}: {', '.join(missing_columns)}")

    missing_indexes = sorted(_PHASE14B_REQUIRED_INDEXES - indexes)
    if missing_indexes:
        gaps.append(
            f"{APPROVAL_TABLE} indeksleri: {', '.join(missing_indexes)}"
        )
    return gaps


def assert_phase1_4b_schema_ready() -> None:
    """Validate the Alembic-owned schema without mutating the database."""
    try:
        gaps = _phase1_4b_schema_gaps()
    except Exception as exc:
        raise PersonnelSupportPublishSchemaNotReadyError(
            "Personel/Destek yayın ön onayı şeması doğrulanamadı. "
            f"Alembic revision {PHASE1_4B_SCHEMA_REVISION} uygulanmalıdır."
        ) from exc

    if gaps:
        details = "; ".join(gaps)
        raise PersonnelSupportPublishSchemaNotReadyError(
            "Personel/Destek yayın ön onayı şeması hazır değil. "
            f"Alembic revision {PHASE1_4B_SCHEMA_REVISION} uygulanmalıdır. "
            f"Eksikler: {details}"
        )


def apply_phase1_4b_schema() -> None:
    """Compatibility entry point; validate schema readiness without writes."""
    assert_phase1_4b_schema_ready()


def is_admin_user(user: Any) -> bool:
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
        return True
    role_values = {_normalize(getattr(user, attr, None)) for attr in ("role", "role_name", "user_type")}
    return bool(role_values & {"admin", "super_admin", "system_admin", "sistem_yoneticisi"})


def is_hr_publish_user(user: Any) -> bool:
    role_values = {_normalize(getattr(user, attr, None)) for attr in ("role", "role_name", "user_type", "unvan", "title")}
    return is_admin_user(user) or bool(role_values & {"ik", "insan_kaynaklari", "personel_yonetimi", "performans_yetkilisi"})


def is_personnel_support_group_chair_user(user: Any) -> bool:
    # BYS360 DEFECT AQ: burada önceden, tam eşleşme kümesi (explicit)
    # başarısız olduğunda, TÜM rol/unvan alanları birleştirilip "personel",
    # ("destek" veya "idari"), "grup", "baskan" alt dizelerinin HER BİRİNİN
    # (dağınık biçimde, farklı alanlarda) metinde geçip geçmediğine bakan bir
    # substring-kombinasyon fallback'i vardı. Bu, ör. Grup Başkan
    # YARDIMCISI'nı (role="personel", unvan="destek hizmetleri",
    # title="grup başkan yardımcısı") gerçek Grup Başkanı ile karıştırıp
    # yayın onay yetkisi veriyordu ("başkan" alt dizesi "başkan yardımcısı"
    # içinde de geçiyor). explicit küme zaten bilinen tüm yazım
    # varyasyonlarını numaralandırdığı için fallback tamamen kaldırıldı --
    # yeni bir substring/allowlist icat edilmedi.
    role_values = {
        _normalize(getattr(user, attr, None))
        for attr in ("role", "role_name", "user_type", "unvan", "title", "position", "gorev")
    }
    explicit = {
        "personel_ve_destek_hizmetleri_grup_baskani",
        "personel_destek_hizmetleri_grup_baskani",
        "personel_ve_idari_isler_grup_baskani",
        "personel_idari_isler_grup_baskani",
    }
    return bool(role_values & explicit)


def can_view_personnel_support_publish_approvals(user: Any) -> bool:
    return is_admin_user(user) or is_hr_publish_user(user) or is_personnel_support_group_chair_user(user)


def can_decide_personnel_support_publish_approval(user: Any) -> bool:
    # Kural gereği bu onay Admin/İK yayını öncesinde Personel ve Destek Hizmetleri Grup Başkanı tarafından verilir.
    return is_personnel_support_group_chair_user(user)


def status_key(status: Any) -> str:
    key = str(status or "pending").strip().lower()
    if key in {APPROVAL_APPROVED, "onaylanan", "onaylandi", "onaylandı"}:
        return APPROVAL_APPROVED
    if key in {APPROVAL_RETURNED, "iade", "iade_edildi", "returned_to_hr"}:
        return APPROVAL_RETURNED
    return APPROVAL_PENDING


def status_label(status: Any) -> str:
    return STATUS_LABELS.get(status_key(status), "Yayın Ön Onayı Bekliyor")


def score_level_label(score: Any) -> str:
    if score is None:
        return "Puan bilgisi bekleniyor"
    value = _safe_float(score, 0.0)
    if value < LOW_SCORE_THRESHOLD:
        return "Düşük performans onay süreci tamamlanmış kayıt"
    if value >= 90:
        return "Yüksek başarı düzeyi"
    return "Standart başarı aralığı"


def _is_completed_evaluation(evaluation: Any) -> bool:
    status = _normalize(getattr(evaluation, "status", ""))
    workflow = _normalize(getattr(evaluation, "workflow_status", ""))
    if status in FINAL_STATUSES or workflow in FINAL_STATUSES or "tamam" in workflow or "completed" in workflow:
        return True
    return bool(getattr(evaluation, "level_1_completed", False))


def _is_published_to_employee(evaluation: Any) -> bool:
    return bool(getattr(evaluation, "is_published_to_employee", False) or getattr(evaluation, "published_to_employee_at", None))


def _low_score_predecessor_is_ready(evaluation: Any) -> bool:
    final_score = _safe_float(getattr(evaluation, "final_total_100", 0.0), 0.0)
    if final_score >= LOW_SCORE_THRESHOLD:
        return True
    from app.performance.services import performance_rule_engine as _rule_engine

    # Ayar 70 altı için Başkan onayı istemiyorsa bu adımın bekleyeceği önceki onay
    # yoktur (yayın ön kontrolüyle aynı kural motoru kararı); ön onay yine zorunludur.
    if not _rule_engine.requires_president_approval(final_score):
        return True
    try:
        from app.services.performance.low_score_process_service import (
            get_low_score_publish_block_reason,
        )
        return not bool(get_low_score_publish_block_reason(evaluation, ensure=False))
    except Exception:
        logger.exception("BYS360 V6C guarded exception | file=app/services/performance/personnel_support_publish_approval_service.py | line=248")
        # Savunmacı davranış: düşük performans ön koşulu doğrulanamıyorsa bu adıma düşürme.
        return False


def should_require_personnel_support_publish_approval(evaluation: Any, *, predecessor_blocked: bool = False) -> bool:
    if predecessor_blocked:
        return False
    if not evaluation or not getattr(evaluation, "id", None):
        return False
    if _is_published_to_employee(evaluation):
        return False
    if not _is_completed_evaluation(evaluation):
        return False
    return _low_score_predecessor_is_ready(evaluation)


def _approval_row(evaluation_id: int) -> Any | None:
    if not table_exists():
        return None
    rows = _rows(f"SELECT * FROM {APPROVAL_TABLE} WHERE evaluation_id = :evaluation_id LIMIT 1", {"evaluation_id": int(evaluation_id)})
    return rows[0] if rows else None


def ensure_personnel_support_publish_approval_for_evaluation(evaluation: Any, *, actor: Any = None) -> Any | None:
    if not should_require_personnel_support_publish_approval(evaluation):
        return None
    if not table_exists():
        return None

    evaluation_id = int(evaluation.id)
    existing = _approval_row(evaluation_id)
    params = {
        "evaluation_id": evaluation_id,
        "period_id": getattr(evaluation, "period_id", None),
        "employee_id": getattr(evaluation, "employee_id", None),
        "final_score": round(_safe_float(getattr(evaluation, "final_total_100", None), 0.0), 2),
        "actor_id": _actor_id(actor),
        "version": PHASE1_4B_RULE_VERSION,
    }
    if existing is None:
        db.session.execute(text(f"""
            INSERT INTO {APPROVAL_TABLE}
                (evaluation_id, period_id, employee_id, final_score, status, requested_by_user_id, rule_version, created_at, updated_at)
            VALUES
                (:evaluation_id, :period_id, :employee_id, :final_score, 'pending', :actor_id, :version, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), params)
        db.session.flush()
    else:
        db.session.execute(text(f"""
            UPDATE {APPROVAL_TABLE}
               SET period_id = :period_id,
                   employee_id = :employee_id,
                   final_score = :final_score,
                   rule_version = COALESCE(rule_version, :version),
                   updated_at = CURRENT_TIMESTAMP
             WHERE evaluation_id = :evaluation_id
        """), params)
        db.session.flush()
    return _approval_row(evaluation_id)


def get_personnel_support_publish_block_reason(evaluation: Any, *, ensure: bool = False, predecessor_blocked: bool = False, actor: Any = None) -> str:
    """Yayın ön kontrolünde kullanılacak blokaj nedenini döndürür."""
    if predecessor_blocked:
        return ""
    if not should_require_personnel_support_publish_approval(evaluation):
        return ""
    if not table_exists():
        return "Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı hazır olmadan karne personele açılamaz."

    row = ensure_personnel_support_publish_approval_for_evaluation(evaluation, actor=actor) if ensure else _approval_row(int(evaluation.id))
    if row is None:
        return "Personel ve Destek Hizmetleri Grup Başkanı yayın ön onayı oluşturulmadan karne personele açılamaz."
    status = str(row.get("status") or "pending").strip().lower()
    if status == APPROVAL_APPROVED:
        return ""
    if status == APPROVAL_RETURNED:
        note = str(row.get("return_note") or row.get("decision_note") or "").strip()
        suffix = f" İade notu: {note}" if note else ""
        return "Personel ve Destek Hizmetleri Grup Başkanı karneyi iade ettiği için Admin/İK yayını yapılamaz." + suffix
    return "Personel ve Destek Hizmetleri Grup Başkanı ön onayı tamamlanmadan karne personele açılamaz."


def _date_label(value: Any) -> str:
    if value is None:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def _full_name_from_row(row: Any, prefix: str) -> str:
    full = str(row.get(prefix + "_full_name") or "").strip()
    if full:
        return full
    ad = str(row.get(prefix + "_ad") or "").strip()
    soyad = str(row.get(prefix + "_soyad") or "").strip()
    name = f"{ad} {soyad}".strip()
    return name or str(row.get(prefix + "_email") or "").strip() or "-"


def build_personnel_support_publish_approval_workspace(viewer: Any, *, status_filter: str = "pending", limit: int = 200) -> dict[str, Any]:
    if not table_exists():
        return {
            "schema_missing": True,
            "rows": [],
            "counts": {"pending": 0, "approved": 0, "returned": 0, "all": 0},
            "status_filter": status_key(status_filter),
            "can_decide": can_decide_personnel_support_publish_approval(viewer),
            "rule_version": PHASE1_4B_RULE_VERSION,
        }
    normalized = str(status_filter or "pending").strip().lower()
    where = ""
    params: dict[str, Any] = {"limit": int(limit)}
    if normalized not in {"all", "tum", "tumu"}:
        if normalized in {"approved", "onaylanan"}:
            where = "WHERE LOWER(COALESCE(ps.status, 'pending')) = 'approved'"
        elif normalized in {"returned", "iade"}:
            where = "WHERE LOWER(COALESCE(ps.status, 'pending')) = 'returned'"
        else:
            where = "WHERE LOWER(COALESCE(ps.status, 'pending')) = 'pending'"
            normalized = "pending"
    else:
        normalized = "all"

    rows = _rows(f"""
        SELECT
            ps.*,
            pp.title AS period_title,
            u.full_name AS employee_full_name,
            u.ad AS employee_ad,
            u.soyad AS employee_soyad,
            u.email AS employee_email,
            u.sicil_no AS employee_sicil_no,
            dec.full_name AS decided_by_full_name,
            dec.ad AS decided_by_ad,
            dec.soyad AS decided_by_soyad,
            dec.email AS decided_by_email
        FROM {APPROVAL_TABLE} ps
        LEFT JOIN performance_periods pp ON pp.id = ps.period_id
        LEFT JOIN users u ON u.id = ps.employee_id
        LEFT JOIN users dec ON dec.id = ps.decided_by_user_id
        {where}
        ORDER BY ps.requested_at DESC, ps.id DESC
        LIMIT :limit
    """, params)

    counts_rows = _rows(f"SELECT LOWER(COALESCE(status, 'pending')) AS status, COUNT(*) AS count FROM {APPROVAL_TABLE} GROUP BY LOWER(COALESCE(status, 'pending'))")
    counts = {"pending": 0, "approved": 0, "returned": 0, "all": 0}
    for item in counts_rows:
        key = str(item.get("status") or "pending").lower()
        val = int(item.get("count") or 0)
        counts[key] = val
        counts["all"] += val

    result_rows = []
    for row in rows:
        data = dict(row)
        data["employee_name"] = _full_name_from_row(row, "employee")
        data["decided_by_name"] = _full_name_from_row(row, "decided_by") if row.get("decided_by_user_id") else "-"
        data["status_key"] = status_key(row.get("status"))
        data["status_label"] = status_label(row.get("status"))
        data["score_level_label"] = score_level_label(row.get("final_score"))
        data["requested_at_label"] = _date_label(row.get("requested_at"))
        data["decided_at_label"] = _date_label(row.get("decided_at"))
        result_rows.append(data)

    return {
        "schema_missing": False,
        "rows": result_rows,
        "counts": counts,
        "status_filter": normalized,
        "can_decide": can_decide_personnel_support_publish_approval(viewer),
        "rule_version": PHASE1_4B_RULE_VERSION,
    }


def decide_personnel_support_publish_approval(approval_id: int, actor: Any, action: str, *, note: str | None = None) -> Phase14BActionResult:
    if not can_decide_personnel_support_publish_approval(actor):
        return Phase14BActionResult(False, "Bu onay işlemi yalnızca Personel ve Destek Hizmetleri Grup Başkanı tarafından yapılabilir.", approval_id)
    if not table_exists():
        return Phase14BActionResult(False, "Yayın ön onayı listesi henüz hazır değil. Sistem yöneticinizle iletişime geçiniz.", approval_id)

    action_norm = str(action or "").strip().lower()
    if action_norm not in {APPROVAL_APPROVED, APPROVAL_RETURNED}:
        return Phase14BActionResult(False, "Geçersiz işlem.", approval_id)

    row = _rows(f"SELECT * FROM {APPROVAL_TABLE} WHERE id = :id LIMIT 1", {"id": int(approval_id)})
    if not row:
        return Phase14BActionResult(False, "Ön onay kaydı bulunamadı.", approval_id)

    current_status = str(row[0].get("status") or "pending").lower()
    if current_status == APPROVAL_APPROVED and action_norm == APPROVAL_APPROVED:
        return Phase14BActionResult(True, "Bu kayıt daha önce onaylanmış.", approval_id)

    status_value = APPROVAL_APPROVED if action_norm == APPROVAL_APPROVED else APPROVAL_RETURNED
    message = "Personel ve Destek Hizmetleri Grup Başkanı ön onayı verildi. Karne nihai yayına hazır."
    if status_value == APPROVAL_RETURNED:
        message = "Karne Personel ve Destek Hizmetleri Grup Başkanı tarafından iade edildi. Düzeltme tamamlanmadan personele açılamaz."

    db.session.execute(text(f"""
        UPDATE {APPROVAL_TABLE}
           SET status = :status,
               decided_at = CURRENT_TIMESTAMP,
               decided_by_user_id = :actor_id,
               decision_note = :note,
               return_note = CASE WHEN :status = 'returned' THEN :note ELSE return_note END,
               rule_version = :version,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = :id
    """), {
        "id": int(approval_id),
        "status": status_value,
        "actor_id": _actor_id(actor),
        "note": (note or "").strip() or None,
        "version": PHASE1_4B_RULE_VERSION,
    })
    db.session.commit()
    return Phase14BActionResult(True, message, approval_id)


__all__ = [
    "APPROVAL_APPROVED",
    "APPROVAL_PENDING",
    "APPROVAL_RETURNED",
    "APPROVAL_TABLE",
    "PHASE1_4B_RULE_VERSION",
    "PHASE1_4B_SCHEMA_REVISION",
    "PersonnelSupportPublishSchemaNotReadyError",
    "Phase14BActionResult",
    "apply_phase1_4b_schema",
    "assert_phase1_4b_schema_ready",
    "build_personnel_support_publish_approval_workspace",
    "can_decide_personnel_support_publish_approval",
    "can_view_personnel_support_publish_approvals",
    "decide_personnel_support_publish_approval",
    "ensure_personnel_support_publish_approval_for_evaluation",
    "get_personnel_support_publish_block_reason",
    "is_personnel_support_group_chair_user",
    "score_level_label",
    "status_key",
    "status_label",
]
