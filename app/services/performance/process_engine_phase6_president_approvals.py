from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

logger = logging.getLogger(__name__)

PHASE6_VERSION = "2026-04-29-process-president-approvals-phase6"


@dataclass(frozen=True)
class Phase6ActionResult:
    ok: bool
    message: str
    approval_id: int | None = None


def _scalar(sql: str, params: dict[str, Any] | None = None) -> Any:
    return db.session.execute(text(sql), params or {}).scalar()


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    return list(db.session.execute(text(sql), params or {}).mappings())


def table_exists(table_name: str) -> bool:
    """BYS360 DEFECT AJ: raw PostgreSQL-only ``information_schema.tables``
    query replaced with SQLAlchemy's ``inspect()``, which is dialect-neutral
    by construction -- the same proven pattern already used elsewhere in
    this codebase (process_engine_phase3_history.py, process_engine_
    phase4_flow.py, process_engine_phase8_tracking.py).

    BYS360 DEFECT AR: previously raised straight through on any inspect()
    failure, unlike ~20 other table-existence helpers doing the identical
    conceptual check elsewhere in this codebase (including this module's
    own claimed sibling, process_engine_phase8_tracking.py), which all log
    and return False. Aligned to that dominant convention."""
    try:
        return bool(inspect(db.engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 phase6 president approvals table_exists guvenli fallback | table=%s", table_name)
        return False


def _table_columns(table_name: str) -> set[str]:
    """BYS360 DEFECT AJ: dialect-neutral via SQLAlchemy ``inspect()``,
    replacing the prior raw PostgreSQL-only ``information_schema.columns``
    query."""
    if not table_exists(table_name):
        return set()
    return {col["name"] for col in inspect(db.engine).get_columns(table_name)}


def column_exists(table_name: str, column_name: str) -> bool:
    return column_name in _table_columns(table_name)


def _add_column(table_name: str, column_name: str, ddl_type: str) -> None:
    """BYS360 DEFECT AJ: ``ADD COLUMN IF NOT EXISTS`` is PostgreSQL-only --
    SQLite raises ``sqlite3.OperationalError: near "EXISTS": syntax error``
    on it unconditionally (confirmed empirically, identical to Defect AI's
    finding in process_engine_phase8_tracking.py). Existence is checked
    first via ``column_exists`` (now dialect-neutral), then a plain
    ``ADD COLUMN`` (portable to both dialects) runs only when the column is
    actually missing."""
    if column_exists(table_name, column_name):
        return
    db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}"))


def _create_index(index_name: str, ddl: str) -> None:
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} {ddl}"))


def apply_phase6_schema() -> None:
    required_tables = [
        "performance_process_flows",
        "performance_process_flow_steps",
        "performance_scoring_history",
        "performance_president_approvals",
    ]
    missing = [name for name in required_tables if not table_exists(name)]
    if missing:
        raise RuntimeError("Faz 6 icin once Faz 2-5 altyapisi gerekli: " + ", ".join(missing))

    approval_columns = {
        "decision_status": "VARCHAR(80)",
        "decision_action": "VARCHAR(80)",
        "decided_by_user_id": "INTEGER",
        "decided_by_name": "VARCHAR(255)",
        "visible_status": "VARCHAR(120)",
        "action_required": "BOOLEAN DEFAULT TRUE",
        "action_url": "VARCHAR(500)",
        "process_version": "VARCHAR(120)",
        "updated_by_phase6_at": "TIMESTAMP",
    }
    for column_name, ddl_type in approval_columns.items():
        _add_column("performance_president_approvals", column_name, ddl_type)

    flow_columns = {
        "president_approval_status": "VARCHAR(80)",
        "current_stage": "VARCHAR(120)",
        "current_owner_user_id": "INTEGER",
        "current_owner_name": "VARCHAR(255)",
        "last_action_title": "VARCHAR(255)",
        "last_action_at": "TIMESTAMP",
        "flow_summary": "TEXT",
        "process_version": "VARCHAR(120)",
        "updated_by_engine_at": "TIMESTAMP",
    }
    for column_name, ddl_type in flow_columns.items():
        _add_column("performance_process_flows", column_name, ddl_type)

    db.session.execute(
        text(
            """
            UPDATE performance_president_approvals
               SET decision_status = COALESCE(decision_status, status, 'bekliyor'),
                   visible_status = CASE
                        WHEN LOWER(COALESCE(status, '')) IN ('approved', 'onaylandi', 'onaylandı') THEN 'Onaylandı'
                        WHEN LOWER(COALESCE(status, '')) IN ('returned', 'iade', 'iade_edildi') THEN 'İade edildi'
                        ELSE 'Başkan onayı bekliyor'
                   END,
                   action_required = CASE
                        WHEN LOWER(COALESCE(status, '')) IN ('approved', 'onaylandi', 'onaylandı', 'returned', 'iade', 'iade_edildi') THEN FALSE
                        ELSE TRUE
                   END,
                   action_url = COALESCE(action_url, '/performans/baskan-onaylari'),
                   process_version = COALESCE(process_version, :version),
                   updated_by_phase6_at = COALESCE(updated_by_phase6_at, CURRENT_TIMESTAMP)
            """
        ),
        {"version": PHASE6_VERSION},
    )

    _create_index(
        "ix_perf_pres_approval_decision_status_phase6",
        "ON performance_president_approvals(decision_status)",
    )
    _create_index(
        "ix_perf_pres_approval_action_required_phase6",
        "ON performance_president_approvals(action_required)",
    )
    _create_index(
        "ix_perf_pres_approval_president_phase6",
        "ON performance_president_approvals(president_user_id, decision_status)",
    )
    db.session.commit()


def normalize_role(value: Any) -> str:
    # BYS360 DEFECT AQ: 'İ'.lower() Python'da tek bir 'i' değil, 'i' +
    # COMBINING DOT ABOVE (U+0307) olmak üzere İKİ kod noktası üretir --
    # bu yüzden .lower() önce çalışırsa aşağıdaki tr_map'teki 'İ' anahtarı
    # asla eşleşmez ve normalize edilmiş sonuçta artık nokta işareti kalır
    # (ör. "Sİstem Yöneticisi" -> "si̇stem_yoneti̇ci̇si̇", beklenen
    # "sistem_yoneticisi" değil). 'İ' burada .lower() çağrılmadan ÖNCE,
    # tek kod noktalı haldeyken ayrı olarak 'i'ye çevrilir.
    raw = str(value or "").strip().replace("İ", "i").lower()
    tr_map = str.maketrans("çğıöşüâîû", "cgiosuaiu")
    return raw.translate(tr_map).replace(" ", "_").replace("-", "_")


def user_display_name(user: Any) -> str:
    if user is None:
        return ""
    full = str(getattr(user, "full_name", "") or "").strip()
    if full:
        return full
    name = " ".join(
        part.strip()
        for part in [str(getattr(user, "ad", "") or ""), str(getattr(user, "soyad", "") or "")]
        if part and part.strip()
    ).strip()
    return name or str(getattr(user, "email", "") or "").strip() or "Kullanıcı"


def is_admin_user(user: Any) -> bool:
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
        return True
    role_values = {
        normalize_role(getattr(user, attr, None))
        for attr in ("role", "role_name", "user_type")
    }
    return bool(role_values & {"admin", "super_admin", "system_admin", "sistem_yoneticisi"})


def is_president_user(user: Any) -> bool:
    # D3/R05: yalnız saklanan rol alanları yetki verir; unvan ve serbest metin (ör. "Başkan") yetki vermez.
    role_values = {
        normalize_role(getattr(user, attr, None))
        for attr in ("role", "role_name", "user_type")
    }
    return bool(role_values & {"baskan", "president"})


def can_view_president_approvals(user: Any) -> bool:
    return is_admin_user(user) or is_president_user(user)


def can_delete_president_approval_records(user: Any) -> bool:
    """Başkan onayı kayıt temizliği yalnızca sistem yöneticisi/admin ailesine açıktır.

    Başkan onayı vermek ile kayıt silmek farklı yetkidir. Bu nedenle Başkan rolü
    kayıtları inceleyebilir ve onaylayabilir; fakat eski/sıfırlama sonrası kalan
    kayıt temizliği sistem yöneticisi/admin tarafından yapılır.
    """
    return is_admin_user(user)


def _delete_from_table_where(table_name: str, where_sql: str, params: dict[str, Any]) -> int:
    if not table_exists(table_name):
        return 0
    result = db.session.execute(text(f"DELETE FROM {table_name} WHERE {where_sql}"), params)
    return int(getattr(result, "rowcount", 0) or 0)


def delete_president_approval_record(approval_id: int, actor: Any) -> Phase6ActionResult:
    """Eski/sıfırlama sonrası ekranda kalan Başkan onayı kaydını güvenli temizler.

    Bu işlem personel, değerlendirme veya karne verisini silmez. Yalnızca
    performance_president_approvals kaydını ve doğrudan bu onay kaydına bağlı
    karar/süreç adımlarını kaldırır. Böylece personel özlük sıfırlaması sonrası
    ekranda kalan yetim onay kayıtları temizlenebilir.
    """
    if not can_delete_president_approval_records(actor):
        return Phase6ActionResult(False, "Bu kayıt yalnızca Admin/Sistem Yöneticisi tarafından silinebilir.", approval_id)
    if not table_exists("performance_president_approvals"):
        return Phase6ActionResult(False, "Başkan onayı tablosu bulunamadı.", approval_id)

    # BYS360 DEFECT AN: this SELECT also listed pa.decision_status, a column
    # that no migration and no reachable runtime schema path ever creates --
    # confirmed against a real, migration-built database. The value was
    # never read anywhere below, so it is dropped rather than gated.
    row = db.session.execute(
        text(
            """
            SELECT id, flow_id, evaluation_id, employee_id, status
            FROM performance_president_approvals
            WHERE id = :approval_id
            LIMIT 1
            """
        ),
        {"approval_id": approval_id},
    ).mappings().first()
    if not row:
        return Phase6ActionResult(False, "Silinecek Başkan onayı kaydı bulunamadı.", approval_id)

    try:
        deleted_steps = 0
        if table_exists("performance_process_flow_steps"):
            step_cols = _table_columns("performance_process_flow_steps")
            if {"source_table", "source_id"}.issubset(step_cols):
                deleted_steps += _delete_from_table_where(
                    "performance_process_flow_steps",
                    "source_table = 'performance_president_approvals' AND source_id = :approval_id",
                    {"approval_id": approval_id},
                )

        _delete_from_table_where(
            "performance_president_approvals",
            "id = :approval_id",
            {"approval_id": approval_id},
        )
        db.session.commit()
    except SQLAlchemyError as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        return Phase6ActionResult(False, "Kayıt silinemedi.", approval_id)

    detail = f" Bağlı {deleted_steps} süreç adımı da temizlendi." if deleted_steps else ""
    return Phase6ActionResult(True, "Başkan onayı kaydı silindi." + detail, approval_id)


def _status_filter_sql(status_filter: str, decision_status_expr: str = "pa.decision_status") -> tuple[str, dict[str, Any]]:
    """BYS360 DEFECT AN: this WHERE fragment referenced pa.decision_status
    directly; the only caller now passes the same column-presence-gated
    expression it already uses for the SELECT list, so the filter degrades
    to the real pa.status column when decision_status is absent, the same
    way the rest of _approval_base_rows() does."""
    normalized = str(status_filter or "pending").strip().lower()
    if normalized in {"all", "tum", "tumu"}:
        return "", {}
    if normalized in {"approved", "onaylanan"}:
        return f"AND LOWER(COALESCE(pa.status, {decision_status_expr}, '')) IN ('approved', 'onaylandi', 'onaylandı')", {}
    if normalized in {"returned", "iade"}:
        return f"AND LOWER(COALESCE(pa.status, {decision_status_expr}, '')) IN ('returned', 'iade', 'iade_edildi')", {}
    return f"AND LOWER(COALESCE(pa.status, {decision_status_expr}, 'bekliyor')) IN ('pending', 'bekliyor', 'baskan_onayi_bekliyor', 'başkan_onayı_bekliyor')", {}


# BYS360_PRESIDENT_APPROVALS_CORPORATE_UI_V3
# Canlı kullanıcı ekranında teknik durum kodu gösterilmemesi için tek güvenli çeviri katmanı.
_STATUS_LABELS = {
    "pending": "Başkan Onayı Bekliyor",
    "bekliyor": "Başkan Onayı Bekliyor",
    "baskan_onayi_bekliyor": "Başkan Onayı Bekliyor",
    "baskan_onayi_yayin_kilidi": "Başkan Onayı Yayın Kilidi",
    "blocked_president_pending": "Başkan Onayı Yayın Kilidi",
    "president_pending": "Başkan Onayı Bekliyor",
    "approved": "Başkan Tarafından Onaylandı",
    "onaylandi": "Başkan Tarafından Onaylandı",
    "returned": "Başkan Tarafından İade Edildi",
    "iade": "Başkan Tarafından İade Edildi",
    "iade_edildi": "Başkan Tarafından İade Edildi",
    "rejected": "Başkan Tarafından İade Edildi",
    "kesinlesme_bekliyor": "Yayın Hazırlığı Bekliyor",
    "publish_ready": "Yayın Hazırlığı Bekliyor",
    "hr_precheck": "Süreç Kontrolünde",
    "first_low_warning": "Düşük Performans Uyarısı Oluşturuldu",
    "second_low_repeat": "Tekrarlayan Düşük Performans Süreci",
    "completed": "Süreç Tamamlandı",
    "done": "Süreç Tamamlandı",
    "cancelled": "İşlemden Kaldırıldı",
}

_FORBIDDEN_PUBLIC_HINTS = (
    "workflow", "phase", "sync", "debug", "test", "dummy", "todo",
    "authorized_scope", "president_pending", "blocked_president_pending",
)


def _approval_filter_key(value: Any) -> str:
    key = normalize_role(value)
    if key in {"all", "tum", "tumu"}:
        return "all"
    if key in {"approved", "onaylanan", "onaylandi"}:
        return "approved"
    if key in {"returned", "iade", "iade_edildi"}:
        return "returned"
    return "pending"


def _approval_status_key(value: Any) -> str:
    key = normalize_role(value)
    if key in {"approved", "onaylandi"}:
        return "approved"
    if key in {"returned", "iade", "iade_edildi", "rejected"}:
        return "returned"
    return "pending"


def _public_status_label(value: Any, fallback: str = "Başkan Onayı Bekliyor") -> str:
    key = normalize_role(value)
    return _STATUS_LABELS.get(key, fallback)


def _public_text(value: Any, fallback: str = "-") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    key = normalize_role(raw)
    if key in _STATUS_LABELS:
        return _STATUS_LABELS[key]
    lower = raw.lower()
    if any(hint in lower for hint in _FORBIDDEN_PUBLIC_HINTS):
        if "president" in lower or "baskan" in lower:
            return "Başkan Onayı Bekliyor"
        if "publish" in lower or "yayin" in lower:
            return "Yayın Hazırlığı Bekliyor"
        return "Süreç kaydı izleniyor"
    return raw.replace("_", " ").strip()


def _is_low_score_value(value: Any) -> bool:
    try:
        return value is not None and float(value) < 70
    except (TypeError, ValueError):
        return False


def _score_state(value: Any) -> tuple[str, str]:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "score-muted", "Puan Bekleniyor"
    if score < 50:
        return "score-critical", "Kritik Düşük Performans"
    if score < 70:
        return "score-low", "Başkan Onayı Gerektirir"
    return "score-normal", "İzleme Kaydı"


def _waiting_label(value: Any) -> str:
    try:
        days = int(value or 0)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return "Bugün işlemde"
    if days == 1:
        return "1 gündür bekliyor"
    return f"{days} gündür bekliyor"


def _base_row_final_score(row: Any) -> Any:
    return row.get("final_score") if row.get("final_score") is not None else row.get("evaluation_final_score")


def _summary_from_rows(raw_rows: list[Any]) -> dict[str, int]:
    summary = {"total": 0, "pending": 0, "approved": 0, "returned": 0}
    for row in raw_rows:
        if not _is_low_score_value(_base_row_final_score(row)):
            continue
        key = _approval_status_key(row.get("approval_status") or row.get("decision_status"))
        summary["total"] += 1
        summary[key] = summary.get(key, 0) + 1
    return summary


def _filter_label(status_filter: str) -> str:
    key = _approval_filter_key(status_filter)
    return {
        "pending": "Onay Bekleyenler",
        "approved": "Onaylananlar",
        "returned": "İade Edilenler",
        "all": "Tüm Kayıtlar",
    }.get(key, "Onay Bekleyenler")


def _safe_score(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _safe_date(value: Any) -> str:
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


def _approval_base_rows(*, viewer: Any, status_filter: str = "pending", limit: int = 200) -> list[Any]:
    """BYS360 DEFECT AN: the SELECT referenced eight columns
    (pa.decision_status, pa.visible_status, f.current_stage,
    f.current_owner_name, f.last_action_title, f.waiting_since,
    f.waiting_days, f.flow_summary) that no migration and no reachable
    runtime schema path ever creates -- confirmed against a real,
    migration-built database. This 500'd every request to the Başkan
    Onayları screen. Read with the same column-presence gating this file
    already uses in _insert_step_for_decision()/the flow UPDATE below;
    every caller of these fields already had its own fallback for a
    missing value (raw_status already falls back to the real pa.status
    column; current_stage/last_action_title/flow_summary already fall
    back to visible_status or a fixed default text). f.current_owner_id is
    real (the model's current_owner_id) and is now selected directly so
    the owner's display name can be resolved via this file's own
    _display_user_name() instead of a nonexistent name column.
    """
    pa_cols = _table_columns("performance_president_approvals")
    flow_cols = _table_columns("performance_process_flows") if table_exists("performance_process_flows") else set()
    decision_status_expr = "pa.decision_status" if "decision_status" in pa_cols else "NULL"
    visible_status_expr = "pa.visible_status" if "visible_status" in pa_cols else "NULL"

    status_sql, params = _status_filter_sql(status_filter, decision_status_expr)
    params["limit"] = int(limit)
    where_parts = ["1=1", status_sql.replace("AND ", "", 1) if status_sql else ""]
    if is_president_user(viewer) and not is_admin_user(viewer):
        where_parts.append("(pa.president_user_id IS NULL OR pa.president_user_id = :viewer_id)")
        params["viewer_id"] = int(getattr(viewer, "id", 0) or 0)
    where_sql = " AND ".join(part for part in where_parts if part)

    current_stage_expr = "f.current_stage" if "current_stage" in flow_cols else "NULL"
    current_owner_id_expr = "f.current_owner_id" if "current_owner_id" in flow_cols else "NULL"
    last_action_title_expr = "f.last_action_title" if "last_action_title" in flow_cols else "NULL"
    waiting_days_expr = "f.waiting_days" if "waiting_days" in flow_cols else "NULL"
    flow_summary_expr = "f.flow_summary" if "flow_summary" in flow_cols else "NULL"

    return _rows(
        f"""
        SELECT
            pa.id AS approval_id,
            pa.flow_id,
            pa.evaluation_id,
            pa.period_id,
            pa.employee_id,
            pa.final_score,
            pa.status AS approval_status,
            {decision_status_expr} AS decision_status,
            {visible_status_expr} AS visible_status,
            pa.president_user_id,
            pa.requested_at,
            pa.decided_at,
            pa.decision_note,
            f.current_status AS flow_status,
            {current_stage_expr} AS current_stage,
            {current_owner_id_expr} AS current_owner_id,
            {last_action_title_expr} AS last_action_title,
            f.last_action_at,
            {waiting_days_expr} AS waiting_days,
            {flow_summary_expr} AS flow_summary,
            e.final_total_100 AS evaluation_final_score,
            e.status AS evaluation_status,
            e.workflow_status,
            p.title AS period_title,
            u.ad AS employee_ad,
            u.soyad AS employee_soyad,
            u.email AS employee_email,
            u.sicil_no AS employee_sicil_no,
            u.birim AS employee_birim,
            u.ust_birim AS employee_ust_birim
        FROM performance_president_approvals pa
        LEFT JOIN performance_process_flows f ON f.id = pa.flow_id
        LEFT JOIN performance_evaluations e ON e.id = pa.evaluation_id
        LEFT JOIN performance_periods p ON p.id = COALESCE(pa.period_id, e.period_id, f.period_id)
        LEFT JOIN users u ON u.id = COALESCE(pa.employee_id, e.employee_id, f.employee_id)
        WHERE {where_sql}
        ORDER BY COALESCE(pa.requested_at, pa.created_at, f.last_action_at, CURRENT_TIMESTAMP) DESC, pa.id DESC
        LIMIT :limit
        """,
        params,
    )


def _score_label(value: Any) -> str:
    """Başkan karne ekranı için puanı sade ve güvenli biçimde gösterir."""
    return _safe_score(value)


def _history_from_evaluation_items(evaluation_id: int | None) -> list[dict[str, Any]]:
    """Faz 3 geçmiş tablosu boşsa puanlama özetini canlı değerlendirme kalemlerinden üretir.

    Bu fonksiyon veri yazmaz; yalnızca Başkan onayı ekranında boş geçmiş görünmesini
    engelleyen güvenli okuma katmanıdır. Böylece canlı kullanıcıya teknik faz/senkron
    metni gösterilmez.
    """
    if not evaluation_id:
        return []
    if not table_exists("performance_evaluation_items") or not table_exists("performance_evaluations"):
        return []

    item_cols = _table_columns("performance_evaluation_items")
    eval_cols = _table_columns("performance_evaluations")
    if "evaluation_id" not in item_cols or "manager_level" not in item_cols:
        return []

    # BYS360 DEFECT AN: ::numeric is PostgreSQL-only syntax with no SQLite
    # equivalent (raised "unrecognized token: :", crashing this reachable
    # dependency of build_president_approval_workspace() on every request).
    # The cast was dropped; "/ 4.0" (a real literal) keeps the same
    # non-truncating division on both dialects that "::numeric" gave on
    # PostgreSQL alone.
    # BYS360 DEFECT AR: bare ROUND(<float agregat>, N) PostgreSQL'de
    # calismiyor (round(double precision, integer) imzasi yok, sadece
    # round(numeric, integer) var); CAST(...AS NUMERIC) her iki dialect'te
    # de gecerli ve PostgreSQL'in imza gereksinimini karsiliyor.
    if "score_100" in item_cols:
        score_expr = "ROUND(CAST(AVG(NULLIF(i.score_100, 0)) AS NUMERIC), 2)"
        score_filter = "i.score_100 IS NOT NULL AND i.score_100 > 0"
    elif "score" in item_cols:
        score_expr = "ROUND(CAST(AVG(((i.score - 1) / 4.0) * 100) AS NUMERIC), 2)"
        score_filter = "i.score IS NOT NULL"
    else:
        return []

    evaluator_case_parts = []
    if "level_1_evaluator_id" in eval_cols:
        evaluator_case_parts.append("WHEN 1 THEN e.level_1_evaluator_id")
    if "level_2_evaluator_id" in eval_cols:
        evaluator_case_parts.append("WHEN 2 THEN e.level_2_evaluator_id")
    if "level_3_evaluator_id" in eval_cols:
        evaluator_case_parts.append("WHEN 3 THEN e.level_3_evaluator_id")
    evaluator_expr = "CASE i.manager_level " + " ".join(evaluator_case_parts) + " ELSE NULL END" if evaluator_case_parts else "NULL"

    time_candidates = []
    for alias, cols in (("i", item_cols), ("e", eval_cols)):
        if "updated_at" in cols:
            time_candidates.append(f"{alias}.updated_at")
        if "created_at" in cols:
            time_candidates.append(f"{alias}.created_at")
    time_expr = "COALESCE(" + ", ".join(time_candidates + ["CURRENT_TIMESTAMP"]) + ")"

    rows = _rows(
        f"""
        WITH item_summary AS (
            SELECT
                i.evaluation_id,
                e.period_id,
                e.employee_id,
                i.manager_level,
                {evaluator_expr} AS scorer_user_id,
                {score_expr} AS score_value,
                MAX({time_expr}) AS action_at
            FROM performance_evaluation_items i
            JOIN performance_evaluations e ON e.id = i.evaluation_id
            WHERE i.evaluation_id = :evaluation_id
              AND {score_filter}
            GROUP BY i.evaluation_id, e.period_id, e.employee_id, i.manager_level, scorer_user_id
        )
        SELECT
            s.*,
            NULLIF(TRIM(COALESCE(u.ad, '') || ' ' || COALESCE(u.soyad, '')), '') AS scorer_full_name,
            u.email AS scorer_email
        FROM item_summary s
        LEFT JOIN users u ON u.id = s.scorer_user_id
        ORDER BY s.manager_level ASC
        """,
        {"evaluation_id": evaluation_id},
    )

    history: list[dict[str, Any]] = []
    for row in rows:
        level = row.get("manager_level") or "-"
        scorer_name = row.get("scorer_full_name") or row.get("scorer_email") or f"{level}. amir"
        history.append(
            {
                "scorer_name": scorer_name,
                "manager_level": level,
                "score": _score_label(row.get("score_value")),
                "status": "Puanlama kaydedildi",
                "next_stage": "Değerlendirme zinciri izlendi",
                "next_owner_name": "-",
                "action_at": _safe_date(row.get("action_at")),
            }
        )
    return history


def _history_from_evaluation_totals(evaluation_id: int | None) -> list[dict[str, Any]]:
    """Kalem tablosu okunamazsa değerlendirme toplamlarından son güvenli özet üretir."""
    if not evaluation_id or not table_exists("performance_evaluations"):
        return []
    cols = _table_columns("performance_evaluations")
    if "id" not in cols:
        return []

    select_parts = ["id"]
    for name in (
        "level_1_total_100", "level_2_total_100", "level_3_total_100",
        "level_1_completed", "level_2_completed", "level_3_completed",
        "level_1_evaluator_id", "level_2_evaluator_id", "level_3_evaluator_id",
        "updated_at", "created_at",
    ):
        if name in cols:
            select_parts.append(name)
    row = db.session.execute(
        text(f"SELECT {', '.join(select_parts)} FROM performance_evaluations WHERE id = :evaluation_id LIMIT 1"),
        {"evaluation_id": evaluation_id},
    ).mappings().first()
    if not row:
        return []

    history: list[dict[str, Any]] = []
    for level in (1, 2, 3):
        score_key = f"level_{level}_total_100"
        completed_key = f"level_{level}_completed"
        evaluator_key = f"level_{level}_evaluator_id"
        score_value = row.get(score_key) if score_key in row else None
        completed = bool(row.get(completed_key)) if completed_key in row else score_value not in (None, 0)
        if not completed and score_value in (None, 0):
            continue
        history.append(
            {
                "scorer_name": _display_user_name(row.get(evaluator_key)) if evaluator_key in row else f"{level}. amir",
                "manager_level": level,
                "score": _score_label(score_value),
                "status": "Puanlama kaydedildi" if completed else "Puanlama özeti",
                "next_stage": "Değerlendirme toplamı",
                "next_owner_name": "-",
                "action_at": _safe_date(row.get("updated_at") or row.get("created_at")),
            }
        )
    return history


def _display_user_name(user_id: Any) -> str:
    if not user_id or not table_exists("users"):
        return "-"
    try:
        # BYS360 DEFECT AN: CONCAT_WS is PostgreSQL-only with no SQLite
        # equivalent -- always raised here on SQLite (silently caught below,
        # degrading every owner-name lookup to "Kullanıcı #<id>"). Replaced
        # with the ANSI-portable TRIM(COALESCE(...) || ' ' || COALESCE(...))
        # already used elsewhere in this file/wave.
        row = db.session.execute(
            text("""
                SELECT NULLIF(TRIM(COALESCE(ad, '') || ' ' || COALESCE(soyad, '')), '') AS full_name, email
                FROM users
                WHERE id = :user_id
                LIMIT 1
            """),
            {"user_id": user_id},
        ).mappings().first()
    except SQLAlchemyError:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        row = None
    if not row:
        return f"Kullanıcı #{user_id}"
    return row.get("full_name") or row.get("email") or f"Kullanıcı #{user_id}"


def _scoring_history(evaluation_id: int | None) -> list[dict[str, Any]]:
    if not evaluation_id:
        return []

    history: list[dict[str, Any]] = []
    if table_exists("performance_scoring_history"):
        cols = _table_columns("performance_scoring_history")
        if "evaluation_id" in cols:
            safe_cols = [
                c for c in (
                    "id", "scorer_user_id", "scorer_id", "scorer_name", "scorer_label",
                    "manager_level", "scorer_level", "score_value", "score_100", "raw_score",
                    "action_status", "next_stage", "next_owner_name", "action_at", "created_at"
                ) if c in cols
            ]
            if safe_cols:
                order_col = "action_at" if "action_at" in cols else ("created_at" if "created_at" in cols else "id")
                rows = _rows(
                    f"""
                    SELECT {', '.join(safe_cols)}
                    FROM performance_scoring_history
                    WHERE evaluation_id = :evaluation_id
                    ORDER BY {order_col} ASC NULLS LAST, id ASC
                    """,
                    {"evaluation_id": evaluation_id},
                )
                for row in rows:
                    scorer_name = row.get("scorer_name") or row.get("scorer_label") or "-"
                    score_value = row.get("score_value") if row.get("score_value") is not None else row.get("score_100")
                    if score_value is None:
                        score_value = row.get("raw_score")
                    history.append(
                        {
                            "scorer_name": scorer_name,
                            "manager_level": row.get("manager_level") or row.get("scorer_level") or "-",
                            "score": _safe_score(score_value),
                            "status": _public_status_label(row.get("action_status"), "Puanlama kaydedildi"),
                            "next_stage": _public_text(row.get("next_stage"), "-"),
                            "next_owner_name": row.get("next_owner_name") or "-",
                            "action_at": _safe_date(row.get("action_at") or row.get("created_at")),
                        }
                    )

    if history:
        return history

    fallback = _history_from_evaluation_items(evaluation_id)
    if fallback:
        return fallback
    return _history_from_evaluation_totals(evaluation_id)


def _flow_steps(flow_id: int | None, evaluation_id: int | None) -> list[dict[str, Any]]:
    """BYS360 DEFECT AN: the SELECT referenced visible_title/visible_status/
    waiting_owner_name/action_at, none of which are real columns on
    performance_process_flow_steps under any migration or reachable
    runtime schema path. Every caller already falls back to the real
    step_title/step_status/owner_label/occurred_at columns when these are
    absent, so they are now read with this file's own column-presence
    gating."""
    if not table_exists("performance_process_flow_steps"):
        return []
    if flow_id:
        where_sql = "flow_id = :flow_id"
        params = {"flow_id": flow_id}
    elif evaluation_id:
        where_sql = "evaluation_id = :evaluation_id"
        params = {"evaluation_id": evaluation_id}
    else:
        return []
    step_cols = _table_columns("performance_process_flow_steps")
    visible_title_expr = "visible_title" if "visible_title" in step_cols else "NULL"
    visible_status_expr = "visible_status" if "visible_status" in step_cols else "NULL"
    waiting_owner_name_expr = "waiting_owner_name" if "waiting_owner_name" in step_cols else "NULL"
    action_at_expr = "action_at" if "action_at" in step_cols else "NULL"
    rows = _rows(
        f"""
        SELECT
            id,
            step_order,
            step_title,
            {visible_title_expr} AS visible_title,
            step_status,
            {visible_status_expr} AS visible_status,
            actor_label,
            owner_label,
            {waiting_owner_name_expr} AS waiting_owner_name,
            action_summary,
            occurred_at,
            {action_at_expr} AS action_at,
            created_at
        FROM performance_process_flow_steps
        WHERE {where_sql}
        ORDER BY COALESCE(step_order, 0), COALESCE({action_at_expr}, occurred_at, created_at, CURRENT_TIMESTAMP), id
        """,
        params,
    )
    timeline: list[dict[str, Any]] = []
    for row in rows:
        status = _public_status_label(row.get("visible_status") or row.get("step_status"), "Süreçte")
        timeline.append(
            {
                "title": _public_text(row.get("visible_title") or row.get("step_title"), "Süreç adımı"),
                "status": status,
                "actor": _public_text(row.get("actor_label"), "-"),
                "owner": _public_text(row.get("waiting_owner_name") or row.get("owner_label"), "-"),
                "summary": _public_text(row.get("action_summary"), ""),
                "date": _safe_date(row.get("action_at") or row.get("occurred_at") or row.get("created_at")),
            }
        )
    return timeline


def build_president_approval_workspace(viewer: Any, status_filter: str = "pending") -> dict[str, Any]:
    active_filter = _approval_filter_key(status_filter)
    can_delete_records = can_delete_president_approval_records(viewer)
    if not can_view_president_approvals(viewer):
        return {
            "authorized": False,
            "rows": [],
            "summary": {},
            "status_filter": active_filter,
            "filter_label": _filter_label(active_filter),
            "can_delete_president_records": False,
        }

    all_raw_rows = _approval_base_rows(viewer=viewer, status_filter="all")
    summary = _summary_from_rows(all_raw_rows)

    rows = []
    raw_rows = all_raw_rows if active_filter == "all" else _approval_base_rows(viewer=viewer, status_filter=active_filter)
    for row in raw_rows:
        final_score = _base_row_final_score(row)
        # BYS360_PHASE5_FINAL_GATE_LOW_SCORE_LIST_FILTER
        # Başkan Onayları sekmesi yalnızca gerçek 70 altı düşük performans kayıtlarını gösterir.
        if not _is_low_score_value(final_score):
            continue
        flow_id = row.get("flow_id")
        evaluation_id = row.get("evaluation_id")
        raw_status = row.get("approval_status") or row.get("decision_status") or "bekliyor"
        status_key = _approval_status_key(raw_status)
        score_class, score_label = _score_state(final_score)
        visible_status = _public_status_label(row.get("visible_status") or raw_status)
        current_stage = _public_text(row.get("current_stage"), visible_status)
        last_action_title = _public_text(row.get("last_action_title"), visible_status)
        current_owner_name = _display_user_name(row.get("current_owner_id")) if row.get("current_owner_id") else "Başkan"
        rows.append(
            {
                "approval_id": row.get("approval_id"),
                "flow_id": flow_id,
                "evaluation_id": evaluation_id,
                "period_title": _public_text(row.get("period_title"), "Dönem bilgisi yok"),
                "employee_name": _public_text(_full_name_from_row(row, "employee"), "Personel bilgisi yok"),
                "sicil_no": row.get("employee_sicil_no") or "-",
                "birim": _public_text(row.get("employee_birim") or row.get("employee_ust_birim"), "Birim bilgisi yok"),
                "final_score": _safe_score(final_score),
                "score_class": score_class,
                "score_label": score_label,
                "approval_status": raw_status,
                "approval_status_key": status_key,
                "visible_status": visible_status,
                "status_badge_class": "ok" if status_key == "approved" else ("returned" if status_key == "returned" else "pending"),
                "requested_at": _safe_date(row.get("requested_at")),
                "decided_at": _safe_date(row.get("decided_at")),
                "decision_note": _public_text(row.get("decision_note"), ""),
                "current_stage": current_stage,
                "current_owner_name": current_owner_name,
                "last_action_title": last_action_title,
                "last_action_at": _safe_date(row.get("last_action_at")),
                "waiting_days": row.get("waiting_days") if row.get("waiting_days") is not None else 0,
                "waiting_label": _waiting_label(row.get("waiting_days")),
                "flow_summary": _public_text(row.get("flow_summary"), "70 altı nihai performans sonucu için Başkan onayı bekleniyor."),
                "scoring_history": _scoring_history(evaluation_id),
                "flow_steps": _flow_steps(flow_id, evaluation_id),
            }
        )

    return {
        "authorized": True,
        "rows": rows,
        "summary": summary,
        "status_filter": active_filter,
        "filter_label": _filter_label(active_filter),
        "can_delete_president_records": can_delete_records,
    }


def _insert_step_for_decision(*, approval_id: int, flow_id: int | None, evaluation_id: int | None, actor: Any, action: str, note: str | None) -> None:
    """BYS360 DEFECT AN: performance_process_flow_steps.flow_id is NOT NULL
    (see PerformanceProcessFlowStep in performance_process_engine_models.py),
    but performance_president_approvals.flow_id is nullable and legacy
    flow-less approval records genuinely exist (_approval_base_rows()'s own
    LEFT JOIN already anticipates this). Deciding such a record always
    raised IntegrityError here, which the caller's broad except swallowed
    as a generic "could not save" failure -- silently blocking every
    approve/return decision on a flow-less record. There is no flow to
    attach a timeline step to, so this now skips the insert instead of
    crashing; the decision itself (status/decided_at/decision_note) is
    still recorded by the caller."""
    if flow_id is None:
        return
    if not table_exists("performance_process_flow_steps"):
        return
    actor_name = user_display_name(actor)
    status = "onaylandı" if action == "approved" else "iade edildi"
    title = "Başkan onayı verildi" if action == "approved" else "Başkan tarafından iade edildi"
    now = datetime.utcnow()
    available = _table_columns("performance_process_flow_steps")
    payload = {
        "flow_id": flow_id,
        "evaluation_id": evaluation_id,
        "step_order": 900,
        "step_key": "president_approval_decision",
        "step_code": "president_approval_decision",
        "step_title": title,
        "visible_title": title,
        "step_status": status,
        "visible_status": status,
        "actor_id": getattr(actor, "id", None),
        "actor_user_id": getattr(actor, "id", None),
        "actor_label": actor_name,
        "action_summary": title,
        "action_note": note,
        "description": note or title,
        "occurred_at": now,
        "action_at": now,
        "created_at": now,
        "source_table": "performance_president_approvals",
        "source_id": approval_id,
        "process_version": PHASE6_VERSION,
        "rule_version": PHASE6_VERSION,
    }
    filtered = {key: value for key, value in payload.items() if key in available}
    if not filtered:
        return
    columns = ", ".join(filtered.keys())
    values = ", ".join(f":{key}" for key in filtered)
    db.session.execute(text(f"INSERT INTO performance_process_flow_steps ({columns}) VALUES ({values})"), filtered)


def decide_president_approval(approval_id: int, actor: Any, action: str, note: str | None = None) -> Phase6ActionResult:
    if not can_view_president_approvals(actor):
        return Phase6ActionResult(False, "Bu işlem için Başkan veya yetkili yönetici rolü gerekir.", approval_id)
    if action not in {"approved", "returned"}:
        return Phase6ActionResult(False, "Geçersiz işlem.", approval_id)

    row = db.session.execute(
        text(
            """
            SELECT id, flow_id, evaluation_id, status
            FROM performance_president_approvals
            WHERE id = :approval_id
            """
        ),
        {"approval_id": approval_id},
    ).mappings().first()
    if not row:
        return Phase6ActionResult(False, "Başkan onayı kaydı bulunamadı.", approval_id)

    now = datetime.utcnow()
    actor_id = int(getattr(actor, "id", 0) or 0)
    actor_name = user_display_name(actor)
    visible_status = "Onaylandı" if action == "approved" else "İade edildi"
    decision_action = "onay" if action == "approved" else "iade"

    try:
        # BYS360 DEFECT AN: this UPDATE referenced eight columns
        # (decision_status, decision_action, decided_by_user_id,
        # decided_by_name, visible_status, action_required, process_version,
        # updated_by_phase6_at) that no migration and no reachable runtime
        # schema path ever creates -- confirmed against a real,
        # migration-built database. Every approve/return decision silently
        # failed. Gated the same way the flow UPDATE just below this one
        # already does; status/president_user_id/decided_at/decision_note/
        # updated_at are the real, canonical columns and are always written.
        optional_payload = {
            "decision_status": action,
            "decision_action": decision_action,
            "decided_by_user_id": actor_id,
            "decided_by_name": actor_name,
            "visible_status": visible_status,
            "action_required": False,
            "process_version": PHASE6_VERSION,
            "updated_by_phase6_at": now,
        }
        available_approval_cols = _table_columns("performance_president_approvals")
        filtered_optional = {key: value for key, value in optional_payload.items() if key in available_approval_cols}
        assignments = ", ".join(
            [
                "status = :status",
                "president_user_id = COALESCE(president_user_id, :actor_id)",
                "decided_at = :now",
                "decision_note = :note",
                "updated_at = :now",
                *(f"{key} = :{key}" for key in filtered_optional),
            ]
        )
        db.session.execute(
            text(f"UPDATE performance_president_approvals SET {assignments} WHERE id = :approval_id"),
            {
                "approval_id": approval_id,
                "status": action,
                "actor_id": actor_id,
                "now": now,
                "note": note,
                **filtered_optional,
            },
        )

        flow_id = row.get("flow_id")
        evaluation_id = row.get("evaluation_id")
        if flow_id and table_exists("performance_process_flows"):
            if action == "approved":
                flow_payload = {
                    "current_status": "kesinlesme_bekliyor",
                    "current_stage": "Başkan onayı tamamlandı",
                    "current_owner_user_id": None,
                    "current_owner_name": None,
                    "last_action_title": "Başkan onayı verildi",
                    "last_action_at": now,
                    "president_approval_status": "approved",
                    "flow_summary": "Başkan onayı tamamlandı. Süreç kesinleşme/yayın kontrolüne hazır.",
                    "process_version": PHASE6_VERSION,
                    "updated_by_engine_at": now,
                }
            else:
                flow_payload = {
                    "current_status": "iade_edildi",
                    "current_stage": "Başkan tarafından iade edildi",
                    "last_action_title": "Başkan tarafından iade edildi",
                    "last_action_at": now,
                    "president_approval_status": "returned",
                    "flow_summary": note or "Başkan değerlendirme sürecini inceleme için iade etti.",
                    "process_version": PHASE6_VERSION,
                    "updated_by_engine_at": now,
                }
            available = _table_columns("performance_process_flows")
            filtered = {key: value for key, value in flow_payload.items() if key in available}
            if filtered:
                assignments = ", ".join(f"{key} = :{key}" for key in filtered)
                filtered["flow_id"] = flow_id
                db.session.execute(text(f"UPDATE performance_process_flows SET {assignments} WHERE id = :flow_id"), filtered)

        _insert_step_for_decision(
            approval_id=approval_id,
            flow_id=flow_id,
            evaluation_id=evaluation_id,
            actor=actor,
            action=action,
            note=note,
        )
        db.session.commit()
    except SQLAlchemyError:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        return Phase6ActionResult(False, "Karar kaydedilemedi; lütfen tekrar deneyin.", approval_id)

    return Phase6ActionResult(True, "Başkan onayı kaydedildi." if action == "approved" else "Süreç iade edildi.", approval_id)


def phase6_required_columns() -> dict[str, list[str]]:
    return {
        "performance_president_approvals": [
            "flow_id",
            "evaluation_id",
            "period_id",
            "employee_id",
            "final_score",
            "president_user_id",
            "requested_at",
            "status",
            "decision_status",
            "visible_status",
            "action_required",
            "action_url",
        ],
        "performance_process_flows": [
            "id",
            "evaluation_id",
            "current_status",
            "current_stage",
            "president_approval_status",
        ],
        "performance_process_flow_steps": [
            "id",
            "evaluation_id",
            "step_title",
        ],
        "performance_scoring_history": [
            "id",
            "evaluation_id",
        ],
    }
