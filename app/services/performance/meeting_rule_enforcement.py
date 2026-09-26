from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

"""BYS360 Toplantı Kararları — kural uygulama servisi.

Bu servis Faz 1-4'te eklenen toplantı kararlarını yalnızca açıklama/kart
seviyesinde bırakmaz; yayın ön kontrol, görünürlük ve grup ortalaması tarafında
çalışan tekil bir kural yüzeyi sağlar.
"""

logger = logging.getLogger(__name__)

RULE_ENFORCEMENT_VERSION = "2026-04-30-meeting-rules-faz5"
LOW_SCORE_THRESHOLD = 70.0

SETTING_EDGE_COMMENT = "require_criterion_comment_for_score_1_5"
SETTING_EMPLOYEE_GROUP_AVERAGE = "employee_can_see_own_group_average"
SETTING_MANAGER_SCOPE_LIMIT = "manager_performance_scope_limited"
SETTING_OBSERVATION_REMINDER = "show_observation_notes_in_evaluation"
SETTING_LEGACY_ARCHIVE_ENABLED = "legacy_scorecard_archive_enabled"

TRUE_VALUES = {"1", "true", "on", "yes", "evet", "aktif", "active"}
FALSE_VALUES = {"0", "false", "off", "no", "hayir", "hayır", "pasif", "inactive"}


@dataclass(slots=True)
class RuleEnforcementResult:
    ok: bool
    version: str
    period_id: int | None = None
    repaired_low_score_locks: int = 0
    generated_low_score_processes: int = 0
    settings_seeded: int = 0
    message: str = ""
    warnings: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "version": self.version,
            "period_id": self.period_id,
            "repaired_low_score_locks": self.repaired_low_score_locks,
            "generated_low_score_processes": self.generated_low_score_processes,
            "settings_seeded": self.settings_seeded,
            "message": self.message,
            "warnings": list(self.warnings or []),
        }


def _has_table(table_name: str) -> bool:
    try:
        return bool(inspect(db.engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _bool_raw(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    raw = str(value).strip().lower()
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    return bool(default)


def _role(user: Any | None) -> str:
    return str(getattr(user, "role", "") or "").strip().lower()


def _user_id(user: Any | None) -> int | None:
    return _safe_int(getattr(user, "id", None))


def is_admin_or_president(user: Any | None) -> bool:
    return _role(user) in {"admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan"}


def is_manager_like(user: Any | None) -> bool:
    return _role(user) in {
        "admin", "baskan", "baskan_yardimcisi", "grup_baskani", "mali_musavir", "koordinator", "birim_sorumlusu"
    }


def read_performance_setting(setting_key: str, default: bool = False) -> bool:
    if not _has_table("module_settings"):
        return bool(default)
    try:
        row = db.session.execute(
            text("""
                SELECT value_text
                FROM module_settings
                WHERE module_key='performance'
                  AND setting_key=:setting_key
                  AND COALESCE(is_active, true)=true
                ORDER BY id DESC
                LIMIT 1
            """),
            {"setting_key": setting_key},
        ).first()
        if not row:
            return bool(default)
        return _bool_raw(row[0], default=default)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return bool(default)


def require_edge_score_comment_enabled() -> bool:
    return read_performance_setting(SETTING_EDGE_COMMENT, True)


def employee_group_average_enabled() -> bool:
    return read_performance_setting(SETTING_EMPLOYEE_GROUP_AVERAGE, True)


def manager_scope_limit_enabled() -> bool:
    return read_performance_setting(SETTING_MANAGER_SCOPE_LIMIT, True)


def observation_reminder_enabled() -> bool:
    return read_performance_setting(SETTING_OBSERVATION_REMINDER, True)


def score_requires_meeting_rule_comment(raw_score: Any) -> bool:
    try:
        score = int(float(raw_score))
    except (TypeError, ValueError):
        return False
    return score in {1, 5} and require_edge_score_comment_enabled()


def _scalar(sql: str, params: dict[str, Any] | None = None, default: Any = None) -> Any:
    try:
        return db.session.execute(text(sql), params or {}).scalar()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


def _rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in db.session.execute(text(sql), params or {}).mappings().all()]
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return []


def ensure_meeting_rule_foundation(seed_categories: bool = True) -> int:
    seeded = 0
    try:
        from app.services.performance.meeting_development import (
            DEFAULT_CATEGORIES,
            DEFAULT_SETTINGS,
            add_category,
            ensure_meeting_foundation_schema,
        )
        ensure_meeting_foundation_schema(seed_categories=seed_categories)
        if _has_table("module_settings"):
            for key, payload in DEFAULT_SETTINGS.items():
                existing = _scalar(
                    "SELECT id FROM module_settings WHERE module_key='performance' AND setting_key=:key LIMIT 1",
                    {"key": key},
                )
                if not existing:
                    db.session.execute(
                        text("""
                            INSERT INTO module_settings
                                (module_key, setting_key, label, value_text, value_type, description, is_active, created_at, updated_at)
                            VALUES
                                ('performance', :key, :label, :value, 'boolean', :description, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """),
                        {
                            "key": key,
                            "label": payload.get("label") or key,
                            "value": str(payload.get("value", "true")).lower(),
                            "description": payload.get("description") or "Toplantı kararına bağlı performans ayarı.",
                        },
                    )
                    seeded += 1
            db.session.flush()
        if seed_categories:
            for idx, item in enumerate(DEFAULT_CATEGORIES, start=10):
                try:
                    add_category(item[0], item[1], idx, commit=False)
                except TypeError:
                    add_category(item[0], item[1], idx)
        db.session.commit()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        raise
    return seeded


def build_allowed_employee_ids_for_viewer(viewer: Any | None) -> set[int]:
    uid = _user_id(viewer)
    if not viewer or not uid:
        return set()
    if is_admin_or_president(viewer):
        return set()
    if _role(viewer) in {"personel", "employee", "standart", "standard"}:
        return {uid}
    if not manager_scope_limit_enabled():
        return set()
    try:
        from app.view_helpers import build_surface_scope_context
        ctx = build_surface_scope_context(viewer, None)
        return {int(x) for x in (ctx.get("employee_ids") or []) if x is not None}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return {uid}


def can_view_employee_detail(viewer: Any | None, employee_id: Any) -> bool:
    employee_id = _safe_int(employee_id)
    if not employee_id or not viewer:
        return False
    if is_admin_or_president(viewer):
        return True
    allowed = build_allowed_employee_ids_for_viewer(viewer)
    return bool(employee_id in allowed)


def get_employee_active_category(employee_id: Any) -> dict[str, Any] | None:
    employee_id = _safe_int(employee_id)
    if not employee_id or not (_has_table("performance_employee_category_assignments") and _has_table("performance_employee_categories")):
        return None
    rows = _rows(
        """
        SELECT c.id AS category_id, c.category_name, c.description
        FROM performance_employee_category_assignments a
        JOIN performance_employee_categories c ON c.id=a.category_id
        WHERE a.employee_id=:employee_id
          AND COALESCE(a.is_active, true)=true
          AND COALESCE(c.is_active, true)=true
        ORDER BY a.id DESC
        LIMIT 1
        """,
        {"employee_id": employee_id},
    )
    return rows[0] if rows else None


def build_employee_group_average_context(employee_id: Any, period_id: Any | None = None) -> dict[str, Any]:
    employee_id = _safe_int(employee_id)
    period_id = _safe_int(period_id)
    base = {
        "enabled": employee_group_average_enabled(),
        "employee_id": employee_id,
        "category_name": "Kategori atanmadı",
        "period_id": period_id,
        "record_count": 0,
        "average_score": None,
        "visibility_note": "Bu alan kişi detayı göstermez; yalnızca kendi kategori/grup ortalaması olarak hesaplanır.",
    }
    if not base["enabled"] or not employee_id:
        return base
    category = get_employee_active_category(employee_id)
    if not category:
        return base
    category_name = category.get("category_name") or "Kategori atanmadı"
    base["category_name"] = category_name

    parts: list[str] = []
    params: dict[str, Any] = {"category_name": category_name}
    if _has_table("performance_legacy_scorecards"):
        # BYS360 DEFECT FS (Final Sweep A1-01): `score_100::numeric` is
        # PostgreSQL-only cast syntax (breaks on SQLite: "unrecognized token:
        # ':'"). CAST(x AS NUMERIC) is ANSI-portable and behaves identically
        # on both supported dialects -- still the required fix for
        # PostgreSQL's ROUND(AVG(double precision)) incompatibility, but
        # without the non-portable `::` shorthand.
        parts.append("""
            SELECT CAST(score_100 AS NUMERIC) AS score_100
            FROM performance_legacy_scorecards
            WHERE category_name=:category_name
              AND score_100 IS NOT NULL
              AND COALESCE(is_visible_to_employee, true)=true
        """)
    if _has_table("performance_evaluations") and _has_table("performance_employee_category_assignments"):
        where_period = ""
        if period_id:
            where_period = "AND e.period_id=:period_id"
            params["period_id"] = period_id
        parts.append(f"""
            SELECT CAST(e.final_total_100 AS NUMERIC) AS score_100
            FROM performance_evaluations e
            JOIN performance_employee_category_assignments a ON a.employee_id=e.employee_id AND COALESCE(a.is_active, true)=true
            JOIN performance_employee_categories c ON c.id=a.category_id
            WHERE c.category_name=:category_name
              {where_period}
              AND e.final_total_100 IS NOT NULL
              AND COALESCE(e.is_published_to_employee, false)=true
        """)
    if not parts:
        return base
    row = _rows(
        f"SELECT COUNT(*) AS record_count, ROUND(AVG(score_100), 2) AS average_score FROM ({' UNION ALL '.join(parts)}) x",
        params,
    )
    if row:
        base["record_count"] = int(row[0].get("record_count") or 0)
        avg = row[0].get("average_score")
        base["average_score"] = float(avg) if avg is not None else None
    return base


def list_observation_notes_for_evaluation(evaluation: Any, viewer: Any | None = None, limit: int = 20) -> list[dict[str, Any]]:
    if not observation_reminder_enabled() or not _has_table("performance_period_observation_notes"):
        return []
    employee_id = _safe_int(getattr(evaluation, "employee_id", None))
    period_id = _safe_int(getattr(evaluation, "period_id", None))
    if not employee_id or not period_id:
        return []
    if not can_view_employee_detail(viewer, employee_id):
        return []
    return _rows(
        """
        SELECT id, note_type, title, note, occurred_at, remind_in_evaluation
        FROM performance_period_observation_notes
        WHERE employee_id=:employee_id
          AND period_id=:period_id
          AND COALESCE(remind_in_evaluation, true)=true
        ORDER BY occurred_at DESC NULLS LAST, id DESC
        LIMIT :limit
        """,
        {"employee_id": employee_id, "period_id": period_id, "limit": int(limit)},
    )


def decorate_period_scorecard_context(scorecard: dict[str, Any], *, viewer: Any | None = None, period: Any | None = None) -> dict[str, Any]:
    payload = dict(scorecard or {})
    role = _role(viewer)
    uid = _user_id(viewer)
    period_id = _safe_int(getattr(period, "id", None))
    payload["meeting_rule_version"] = RULE_ENFORCEMENT_VERSION
    payload["meeting_rule_scope_limited"] = manager_scope_limit_enabled()
    payload["meeting_rule_group_average_enabled"] = employee_group_average_enabled()
    if role in {"personel", "employee", "standart", "standard"} and uid:
        payload["own_group_average"] = build_employee_group_average_context(uid, period_id=period_id)
        rows = []
        for row in payload.get("rows") or []:
            employee = row.get("employee") if isinstance(row, dict) else None
            if _safe_int(getattr(employee, "id", None)) == uid:
                rows.append(row)
        payload["rows"] = rows
        payload["count"] = len(rows)
    elif viewer is not None and is_manager_like(viewer):
        allowed = build_allowed_employee_ids_for_viewer(viewer)
        payload["manager_scope_employee_count"] = len(allowed) if allowed else 0
        payload["manager_scope_note"] = "Yönetici görünürlüğü kendi yetki kapsamıyla sınırlıdır."
    return payload


def repair_published_low_score_locks(period_id: Any | None = None) -> int:
    if not _has_table("performance_evaluations"):
        return 0
    try:
        from app.models import PerformanceEvaluation
        from app.services.performance.low_score_process_service import (
            ensure_low_score_process_for_evaluation,
            get_low_score_publish_block_reason,
        )
    except Exception:
        # Onarım hiç başlayamadı; sonuç "onarılacak kayıt yok" (0) gibi
        # görünmesin diye hata çağırana iletilir. run_meeting_rule_enforcement
        # bunu kullanıcıya uyarı olarak gösterir.
        logger.exception(
            "BYS360_LOW_SCORE_LOCK_REPAIR_UNAVAILABLE | Düşük performans yayın kilidi onarımı "
            "başlatılamadı: politika servisi yüklenemedi; hiçbir kayıt onarılmadı."
        )
        raise
    query = PerformanceEvaluation.query.filter(PerformanceEvaluation.final_total_100 < LOW_SCORE_THRESHOLD)
    if period_id:
        query = query.filter(PerformanceEvaluation.period_id == int(period_id))
    changed = 0
    # Onarım atomiktir: tek bir SAVEPOINT içinde çalışır. Herhangi bir kayıtta
    # hata olursa bu adımın yaptığı süreç/olay/yayın değişikliklerinin tamamı
    # geri alınır ve hata çağırana iletilir; çağıranın aynı transaction'daki
    # önceki değişiklikleri etkilenmez.
    with db.session.begin_nested():
        for evaluation in query.all():
            ensure_low_score_process_for_evaluation(evaluation, flush=True)
            reason = get_low_score_publish_block_reason(evaluation, ensure=True)
            if reason and bool(getattr(evaluation, "is_published_to_employee", False)):
                evaluation.is_published_to_employee = False
                if hasattr(evaluation, "published_to_employee_at"):
                    evaluation.published_to_employee_at = None
                changed += 1
        db.session.flush()
    return changed


def run_meeting_rule_enforcement(period_id: Any | None = None, actor_user_id: Any | None = None) -> RuleEnforcementResult:
    warnings: list[str] = []
    generated = 0
    repaired = 0
    seeded = 0
    try:
        seeded = ensure_meeting_rule_foundation(seed_categories=True)
        try:
            from app.models import PerformancePeriod
            from app.services.performance.low_score_process_service import (
                ensure_low_score_processes_for_period,
            )
            period = db.session.get(PerformancePeriod, int(period_id)) if period_id else PerformancePeriod.query.filter_by(is_active=True).order_by(PerformancePeriod.id.desc()).first()
            resolved_period_id = _safe_int(getattr(period, "id", None))
            if period:
                result = ensure_low_score_processes_for_period(period, actor_user_id=_safe_int(actor_user_id))
                generated = int(result.get("created_or_updated") or 0)
                repaired = repair_published_low_score_locks(resolved_period_id)
            else:
                resolved_period_id = None
                warnings.append("Aktif dönem bulunamadı; yalnızca ayar ve kategori omurgası kontrol edildi.")
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
            resolved_period_id = _safe_int(period_id)
            warnings.append("Düşük performans süreç kontrolü uygulanamadı.")
            if isinstance(exc, SQLAlchemyError):
                # Veritabanı hatası uyarıya indirgenmez: dış blok düşük performans
                # transaction'ını tamamen geri alır ve sonuç ok=False olur.
                raise
        db.session.commit()
        return RuleEnforcementResult(True, RULE_ENFORCEMENT_VERSION, resolved_period_id, repaired, generated, seeded, "Toplantı kararları çalışan kural olarak uygulandı.", warnings)
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        return RuleEnforcementResult(False, RULE_ENFORCEMENT_VERSION, _safe_int(period_id), message="Kural uygulama sırasında hata oluştu.", warnings=warnings)


def build_rule_enforcement_context(period_id: Any | None = None, viewer: Any | None = None) -> dict[str, Any]:
    settings = {
        "1 ve 5 puan açıklama ayarı": require_edge_score_comment_enabled(),
        "Personel kendi grup ortalaması": employee_group_average_enabled(),
        "Yönetici kapsam sınırı": manager_scope_limit_enabled(),
        "Ara dönem not hatırlatması": observation_reminder_enabled(),
        "Geçmiş karne arşivi": read_performance_setting(SETTING_LEGACY_ARCHIVE_ENABLED, True),
    }
    own_group_average = None
    if _role(viewer) in {"personel", "employee", "standart", "standard"}:
        own_group_average = build_employee_group_average_context(_user_id(viewer), period_id=period_id)
    return {
        "rule_version": RULE_ENFORCEMENT_VERSION,
        "settings": settings,
        "own_group_average": own_group_average,
        "scope_employee_count": len(build_allowed_employee_ids_for_viewer(viewer)) if viewer else 0,
        "rules": [
            {"title": "1 ve 5 puan açıklama kuralı", "status": "Ayar aktifse zorunlu, kapalıysa zorunlu değil."},
            {"title": "70 altı kesinleşme kuralı", "status": "Başkan onayı + İK/Admin ön kontrolü + süreç kaydı olmadan yayınlanmaz."},
            {"title": "Personel görünürlüğü", "status": "Personel yalnızca kendi karnesini ve kişi detayı içermeyen kendi grup ortalamasını görür."},
            {"title": "Yönetici görünürlüğü", "status": "Koordinatör ve grup başkanı kendi kapsamı dışındaki detayları görmez."},
            {"title": "Ara dönem notları", "status": "Yetkili kapsamda puanlama sırasında hatırlatılabilir."},
        ],
    }
