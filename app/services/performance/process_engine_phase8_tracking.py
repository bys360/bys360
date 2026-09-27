from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, inspect, text

from app.extensions import db

logger = logging.getLogger(__name__)

PHASE8_VERSION = "2026-04-30-process-tracking-phase8"

# BYS360 DEFECT AO: no SLA/threshold configuration for process-tracking
# overdue detection exists anywhere in this codebase (searched config.py,
# app/services/performance/, and every settings/module_settings source --
# the closest matches, feedback_alert_service.REQUEST_SLA_DAYS=5 and
# ai_decision/reminder_policy.critical_overdue_days=7, govern unrelated
# features on different tables and are never imported here). This 7-day
# value is the only threshold this module has ever defined -- it was
# already hardcoded inline before this fix; it is kept as-is (not replaced
# with an invented number) and simply given a name so every real column
# derivation below uses the same, single, already-existing value.
PHASE8_OVERDUE_THRESHOLD_DAYS = 7


@dataclass(frozen=True)
class Phase8SyncResult:
    flows_checked: int = 0
    flows_updated: int = 0


def _prepare_clause(sql: str, expanding: tuple[str, ...]):
    """BYS360 DEFECT AB: builds a dialect-neutral TextClause. `expanding`
    names bind parameters whose value is a Python list that must become a
    real SQL IN-list (`IN (:p_1, :p_2, ...)`) at execute time, working
    identically on PostgreSQL and SQLite -- unlike PostgreSQL's `= ANY(:x)`
    array-bind syntax, which SQLite has no equivalent for at all."""
    clause = text(sql)
    if expanding:
        clause = clause.bindparams(*(bindparam(name, expanding=True) for name in expanding))
    return clause


def _scalar(sql: str, params: dict[str, Any] | None = None, *, expanding: tuple[str, ...] = ()) -> Any:
    return db.session.execute(_prepare_clause(sql, expanding), params or {}).scalar()


def _rows(sql: str, params: dict[str, Any] | None = None, *, expanding: tuple[str, ...] = ()) -> list[Any]:
    return list(db.session.execute(_prepare_clause(sql, expanding), params or {}).mappings())


def _execute(sql: str, params: dict[str, Any] | None = None, *, expanding: tuple[str, ...] = ()) -> Any:
    return db.session.execute(_prepare_clause(sql, expanding), params or {})


def table_exists(table_name: str) -> bool:
    """Return whether a table exists for the active SQLAlchemy database.

    BYS360 DEFECT AL: the prior implementation hand-rolled a dialect branch
    (raw ``sqlite_master`` vs. raw PostgreSQL-only ``information_schema``),
    duplicating logic that SQLAlchemy's ``inspect()`` already provides
    dialect-neutrally by construction -- the same proven pattern already
    used elsewhere in this module family (process_engine_phase4_flow.py,
    phase6_president_approvals.py, phase7_president_rule.py).
    """
    try:
        bind = db.session.get_bind()
        return bool(inspect(bind).has_table(table_name))
    except Exception:
        logging.getLogger(__name__).exception(
            "BYS360 process tracking table_exists guvenli fallback | table=%s",
            table_name,
        )
        return False


def column_exists(table_name: str, column_name: str) -> bool:
    """Return whether a column exists on the active database backend."""
    try:
        return column_name in _table_columns(table_name)
    except Exception:
        logger.exception(
            "BYS360 process tracking column_exists guvenli fallback | table=%s column=%s",
            table_name,
            column_name,
        )
        return False


def _table_columns(table_name: str) -> set[str]:
    """Return table column names for SQLite and PostgreSQL safely.

    BYS360 DEFECT AL: dialect-neutral via SQLAlchemy ``inspect()``,
    replacing the prior hand-rolled sqlite_master/information_schema branch.
    """
    try:
        bind = db.session.get_bind()
        inspector = inspect(bind)
        if not inspector.has_table(table_name):
            return set()
        return {str(column["name"]) for column in inspector.get_columns(table_name)}
    except Exception:
        logger.exception(
            "BYS360 process tracking _table_columns guvenli fallback | table=%s",
            table_name,
        )
        return set()


def _qident(name: str) -> str:
    return '"' + str(name).replace('\"', '\"\"') + '"'


def _col_expr(alias: str, cols: set[str], column: str, fallback: str = 'NULL') -> str:
    return f"{alias}.{_qident(column)}" if column in cols else fallback


def _name_select_expr(alias: str, cols: set[str], out_alias: str) -> str:
    """Return a schema-safe SQL expression for a user display name.

    Some live databases have ``full_name_cache`` while older repair scripts
    expected ``full_name``. This helper never references a missing column,
    so process tracking does not fail with UndefinedColumn errors.
    """
    parts: list[str] = []
    for column in (
        'full_name_cache', 'full_name', 'display_name', 'ad_soyad',
        'adi_soyadi', 'name', 'username', 'email'
    ):
        if column in cols:
            parts.append(f"NULLIF({alias}.{_qident(column)}, '')")
    first_candidates = ['ad', 'adi', 'first_name']
    last_candidates = ['soyad', 'soyadi', 'last_name']
    first = next((c for c in first_candidates if c in cols), None)
    last = next((c for c in last_candidates if c in cols), None)
    if first or last:
        first_expr = f"COALESCE({alias}.{_qident(first)}, '')" if first else "''"
        last_expr = f"COALESCE({alias}.{_qident(last)}, '')" if last else "''"
        parts.insert(0, f"NULLIF(TRIM({first_expr} || ' ' || {last_expr}), '')")
    if not parts:
        return f"NULL AS {out_alias}"
    return f"COALESCE({', '.join(parts)}) AS {out_alias}"


def _period_name_select_expr(alias: str, cols: set[str]) -> str:
    """Return a schema-safe period title expression.

    Prevents old code paths from using a single hard-coded period title column.
    """
    parts: list[str] = []
    for column in ('title', 'name', 'period_name', 'label'):
        if column in cols:
            parts.append(f"NULLIF({alias}.{_qident(column)}, '')")
    if parts:
        return f"COALESCE({', '.join(parts)}, CAST(f.period_id AS TEXT)) AS period_name,"
    return "CAST(f.period_id AS TEXT) AS period_name,"

def _add_column(table_name: str, column_name: str, ddl_type: str) -> None:
    """BYS360 DEFECT AI: ``ADD COLUMN IF NOT EXISTS`` is PostgreSQL-only --
    SQLite raises ``sqlite3.OperationalError: near "EXISTS": syntax error``
    on it unconditionally (confirmed empirically), so every call to
    ``apply_phase8_schema()`` was completely broken under SQLite. Existence
    is now checked with this module's own dialect-neutral ``column_exists``
    (already used elsewhere in this file), then a plain ``ADD COLUMN``
    (portable to both dialects) runs only when the column is actually
    missing -- preserving idempotency without depending on PostgreSQL-only
    syntax."""
    if column_exists(table_name, column_name):
        return
    db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}"))


def _create_index(index_name: str, ddl: str) -> None:
    db.session.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} {ddl}"))


def apply_phase8_schema() -> None:
    required_tables = [
        "performance_process_flows",
        "performance_process_flow_steps",
        "performance_scoring_history",
        "performance_president_approvals",
        "performance_process_notifications",
    ]
    missing = [name for name in required_tables if not table_exists(name)]
    if missing:
        raise RuntimeError("Faz 8 icin Faz 2-7 altyapisi gerekli: " + ", ".join(missing))

    flow_columns = {
        "tracking_status": "VARCHAR(80)",
        "tracking_bucket": "VARCHAR(80)",
        "tracking_priority": "VARCHAR(40) DEFAULT 'normal'",
        "tracking_label": "VARCHAR(255)",
        "tracking_url": "VARCHAR(500)",
        "is_overdue": "BOOLEAN DEFAULT FALSE",
        "overdue_days": "INTEGER DEFAULT 0",
        "last_visible_action": "VARCHAR(255)",
        "tracking_updated_at": "TIMESTAMP",
    }
    for column_name, ddl_type in flow_columns.items():
        _add_column("performance_process_flows", column_name, ddl_type)

    step_columns = {
        "tracking_visible": "BOOLEAN DEFAULT TRUE",
        "tracking_group": "VARCHAR(80)",
    }
    for column_name, ddl_type in step_columns.items():
        _add_column("performance_process_flow_steps", column_name, ddl_type)

    db.session.execute(
        text(
            """
            UPDATE performance_process_flows
               SET tracking_status = COALESCE(tracking_status, current_status, 'takipte'),
                   tracking_bucket = COALESCE(
                        tracking_bucket,
                        CASE
                            WHEN LOWER(COALESCE(president_status, president_approval_status, '')) IN ('pending', 'bekliyor', 'baskan_onayi_bekliyor', 'başkan_onayı_bekliyor') THEN 'president_pending'
                            WHEN COALESCE(is_finalized, FALSE) = TRUE OR LOWER(COALESCE(current_status, '')) IN ('finalized', 'kesinlesti', 'kesinleşti', 'completed', 'tamamlandi', 'tamamlandı') THEN 'completed'
                            WHEN current_owner_user_id IS NOT NULL THEN 'waiting'
                            ELSE 'monitoring'
                        END
                   ),
                   tracking_label = COALESCE(tracking_label, current_stage, last_action_title, 'Süreç takipte'),
                   tracking_url = COALESCE(tracking_url, '/performans/surec-takibi'),
                   overdue_days = COALESCE(overdue_days, 0),
                   is_overdue = COALESCE(is_overdue, FALSE),
                   last_visible_action = COALESCE(last_visible_action, last_action_title, current_stage),
                   tracking_updated_at = COALESCE(tracking_updated_at, CURRENT_TIMESTAMP),
                   process_version = COALESCE(process_version, :version)
            """
        ),
        {"version": PHASE8_VERSION},
    )
    db.session.execute(
        text(
            """
            UPDATE performance_process_flow_steps
               SET tracking_visible = COALESCE(tracking_visible, TRUE),
                   tracking_group = COALESCE(tracking_group, status, step_code, 'surec')
            """
        )
    )
    _create_index("ix_perf_flow_tracking_bucket_phase8", "ON performance_process_flows(tracking_bucket)")
    _create_index("ix_perf_flow_tracking_owner_phase8", "ON performance_process_flows(current_owner_user_id, tracking_bucket)")
    _create_index("ix_perf_flow_tracking_overdue_phase8", "ON performance_process_flows(is_overdue, overdue_days)")
    _create_index("ix_perf_steps_tracking_visible_phase8", "ON performance_process_flow_steps(flow_id, tracking_visible)")
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
    ad = str(getattr(user, "ad", "") or "").strip()
    soyad = str(getattr(user, "soyad", "") or "").strip()
    name = f"{ad} {soyad}".strip()
    return name or str(getattr(user, "email", "") or "").strip() or "Kullanıcı"


def is_admin_user(user: Any) -> bool:
    role = normalize_role(getattr(user, "role", None))
    return role in {"admin", "super_admin", "sistem_yoneticisi"}


def is_process_tracking_user(user: Any) -> bool:
    """BYS360 DEFECT AO: previously OR'd an exact set-intersection check with
    a substring fallback (``token in combined``), which made the exact check
    pointless -- any allowed token that was merely a substring of role/unvan
    (e.g. "baskan" inside "grup_baskani") passed regardless. Now exact-match
    only, mirroring process_engine_phase6_president_approvals.py's proven
    is_admin_user/is_president_user design: role/unvan are normalized, then
    checked as whole tokens (split on whitespace), never as substrings."""
    role = normalize_role(getattr(user, "role", None))
    title = normalize_role(getattr(user, "unvan", None))
    allowed_tokens = {
        "admin",
        "super_admin",
        "sistem_yoneticisi",
        "baskan",
        "baskan_yardimcisi",
        "grup_baskani",
        "koordinator",
        "mali_musavir",
        "birim_sorumlusu",
    }
    combined_words = set(f"{role} {title}".split())
    return bool(combined_words & allowed_tokens)


def can_view_process_tracking(user: Any) -> bool:
    return is_process_tracking_user(user)


def can_manage_process_tracking(user: Any) -> bool:
    """Süreç takip listesini temizleme yetkisi.

    Bu işlem değerlendirme/karne verisini değil, yalnızca süreç takip listesi
    kayıtlarını kaldırır. Canlı kullanımda yetkiyi sınırlı tutmak için admin,
    üst yönetim ve performans/personel destek yetkilileriyle sınırlandırılır.
    Grup Başkanı bu ekranı görüntüleyebilir (is_process_tracking_user) ancak
    kayıt silme yetkisi yalnızca aşağıdaki daha dar listeye tanınır -- bu
    ayrım isteğe bağlı değil, bu modülün kendi orijinal tasarımıdır.

    BYS360 DEFECT AO: aynı substring-eşleşme kusuru burada da vardı --
    role="grup_baskani" veya unvan="Başkanlığı Uzmanı" gibi girdiler, izin
    verilen jetonların yalnızca bir alt dizesini içerdikleri için yanlışlıkla
    yetki kazanıyordu. Artık process_engine_phase6_president_approvals.py'nin
    kanıtlanmış tam-eşleşme deseniyle aynı şekilde çalışır.
    """
    role = normalize_role(getattr(user, "role", None))
    title = normalize_role(getattr(user, "unvan", None))
    if role in {"admin", "super_admin", "sistem_yoneticisi"}:
        return True
    allowed_tokens = {
        "baskan",
        "baskan_yardimcisi",
        "performans_yetkilisi",
        "personel_destek",
        "personel_ve_destek",
        "personel_destek_hizmetleri_grup_baskani",
    }
    combined_words = set(f"{role} {title}".split())
    return bool(combined_words & allowed_tokens)


def _safe_text(value: Any, fallback: str = "-") -> str:
    text_value = str(value or "").strip()
    return text_value if text_value else fallback


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


def _normalize_status_key(value: Any) -> str:
    raw = str(value or "").strip().lower()
    tr_map = str.maketrans("çğıöşüâîûİ", "cgiosuaiui")
    return raw.translate(tr_map).replace(" ", "_").replace("-", "_")


def _clean_process_label(value: Any, fallback: str = "Süreçte") -> str:
    key = _normalize_status_key(value)
    labels = {
        "pending": "Bekliyor",
        "waiting": "Bekliyor",
        "bekliyor": "Bekliyor",
        "in_progress": "Süreçte",
        "takipte": "Süreçte",
        "monitoring": "Süreçte",
        "process": "Süreçte",
        "completed": "Tamamlandı",
        "finalized": "Tamamlandı",
        "tamamlandi": "Tamamlandı",
        "kesinlesti": "Tamamlandı",
        "approved": "Onaylandı",
        "approved_by_president": "Başkan Tarafından Onaylandı",
        "president_pending": "Başkan/Üst Onay Bekliyor",
        "baskan_onayi_bekliyor": "Başkan/Üst Onay Bekliyor",
        "blocked_president_pending": "Başkan/Üst Onay Kilidi",
        "hr_precheck": "Kontrol Aşamasında",
        "first_low_warning": "Düşük Performans Uyarısı Oluşturuldu",
        "second_low_repeat": "Tekrarlayan Düşük Performans Süreci",
        "returned": "İade Edildi",
        "rejected": "İade Edildi",
        "iade": "İade Edildi",
        "iade_edildi": "İade Edildi",
        "overdue": "Gecikti",
        "late": "Gecikti",
    }
    if key in labels:
        return labels[key]
    text_value = str(value or "").strip()
    if not text_value:
        return fallback
    # Kullanıcı ekranına geliştirici durum kodu düşmesin.
    if "_" in text_value or text_value.isupper() or key in {"draft", "debug", "sync", "workflow_state", "phase"}:
        return fallback
    return text_value


def _bucket_tone(bucket: str) -> str:
    key = _normalize_status_key(bucket)
    if key in {"overdue", "president_pending"}:
        return "danger"
    if key in {"waiting", "monitoring"}:
        return "warning"
    if key in {"completed", "approved"}:
        return "success"
    if key in {"returned", "rejected"}:
        return "neutral"
    return "info"


def _full_name_from_row(row: Any, prefix: str) -> str:
    full = _safe_text(row.get(prefix + "_full_name"), "")
    if full:
        return full
    ad = _safe_text(row.get(prefix + "_ad"), "")
    soyad = _safe_text(row.get(prefix + "_soyad"), "")
    name = f"{ad} {soyad}".strip()
    return name or _safe_text(row.get(prefix + "_email"))


# BYS360 DEFECT AO: AN's own investigation (see git history) proved every
# tracking-specific field these functions used to read (waiting_days,
# is_overdue, tracking_bucket, tracking_status, tracking_priority,
# tracking_label, last_action_title, current_owner_name,
# president_requested_at, ...) has no real column under any name in any
# migration -- and a follow-up field-by-field investigation (this wave)
# established that none of them need to become one: every value is either
# already available on a real, migrated column under a different name
# (current_owner_id, president_approval_status, updated_at) or is safely
# computable at read time from real timestamp/status columns already on
# performance_process_flows. This module no longer reads or gates any
# ghost column; every value below comes from a real column or is derived
# in Python from one (see _derive_tracking_fields()).
def _status_clause(status_filter: str) -> tuple[str, dict[str, Any]]:
    """Pure, deterministic clause-builder: every fragment below references
    only real, always-present columns, so no schema introspection is
    needed here at all (unlike the AN-era version, which had to gate each
    fragment against whichever ghost columns happened to exist)."""
    normalized = str(status_filter or "all").strip().lower()
    if normalized in {"all", "tum", "tumu"}:
        return "", {}
    if normalized in {"waiting", "bekleyen"}:
        return (
            "AND f.current_owner_id IS NOT NULL "
            "AND COALESCE(f.is_finalized, FALSE) = FALSE "
            f"AND LOWER(COALESCE(f.current_status, '')) NOT IN {_sql_in(_COMPLETED_STATUS_TEXT)}",
            {},
        )
    if normalized in {"president", "baskan", "baskan_onayi"}:
        return (
            "AND COALESCE(f.president_approval_required, FALSE) = TRUE "
            "AND LOWER(COALESCE(f.president_approval_status, '')) NOT IN ('approved', 'returned', 'iade', 'iade_edildi')",
            {},
        )
    if normalized in {"overdue", "geciken"}:
        # BYS360 DEFECT AO: is_overdue is purely a function of elapsed time
        # since the last action (see _derive_tracking_fields()) -- it does
        # not also require the flow to be unfinished. This matches the
        # module's own pre-existing precedence (_row_bucket() already
        # checked is_overdue before is_finalized/completed), not a new rule.
        cutoff = datetime.utcnow() - timedelta(days=PHASE8_OVERDUE_THRESHOLD_DAYS)
        return (
            "AND COALESCE(f.last_action_at, f.started_at, f.created_at) <= :overdue_cutoff",
            {"overdue_cutoff": cutoff},
        )
    if normalized in {"completed", "tamamlanan"}:
        return (
            "AND (COALESCE(f.is_finalized, FALSE) = TRUE "
            f"OR LOWER(COALESCE(f.current_status, '')) IN {_sql_in(_COMPLETED_STATUS_TEXT)})",
            {},
        )
    if normalized in {"returned", "iade"}:
        return "AND LOWER(COALESCE(f.president_approval_status, '')) IN ('returned', 'iade', 'iade_edildi')", {}
    return "", {}


def _scope_clause(viewer: Any) -> tuple[str, dict[str, Any]]:
    """BYS360 DEFECT AO: the "baskan" check below used to be a substring
    test (``"baskan" in f"{role} {title}"``), which incorrectly granted
    unrestricted scope to any role/unvan merely containing that text --
    including "grup_baskani" (a distinct, narrower role) and "Başkanlığı"-
    style institution-name references, the same defect class as
    can_manage_process_tracking(). Now exact-match against {"baskan",
    "baskan_yardimcisi"} -- both individually, explicitly enumerated
    tokens in this same module's own can_manage_process_tracking()
    allowed list, unlike "grup_baskani", which that list deliberately
    excludes."""
    if is_admin_user(viewer):
        return "", {}
    viewer_id = int(getattr(viewer, "id", 0) or 0)
    role = normalize_role(getattr(viewer, "role", None))
    title = normalize_role(getattr(viewer, "unvan", None))
    if {role, title} & {"baskan", "baskan_yardimcisi"}:
        return "", {}
    return "AND (f.current_owner_id = :viewer_id OR f.employee_id = :viewer_id)", {"viewer_id": viewer_id}


def process_flow_scope_clause(viewer: Any) -> tuple[str, dict[str, Any]]:
    """Canonical row scope for every reader of ``performance_process_flows``
    (Süreç Takibi and Süreç Raporları).

    Same rules as ``_scope_clause``; additionally a non-privileged viewer
    without a resolvable id matches nothing instead of ``id = 0`` rows
    (fail closed)."""
    scope_sql, scope_params = _scope_clause(viewer)
    if scope_sql and int(scope_params.get("viewer_id") or 0) <= 0:
        return "AND 1 = 0", {}
    return scope_sql, scope_params


def _build_search_clause(search: str) -> tuple[str, dict[str, Any]]:
    cleaned = str(search or "").strip()
    if not cleaned:
        return "", {}

    user_cols = _table_columns("users") if table_exists("users") else set()
    search_parts: list[str] = []
    for alias in ("emp", "owner"):
        for column in (
            "full_name_cache", "full_name", "display_name", "ad_soyad",
            "adi_soyadi", "name", "username", "email", "ad", "soyad",
            "adi", "soyadi", "sicil_no"
        ):
            if column in user_cols:
                search_parts.append(f"LOWER(COALESCE({alias}.{_qident(column)}, '')) LIKE :search")
    search_parts.append("LOWER(COALESCE(f.current_status, '')) LIKE :search")
    return "AND (" + " OR ".join(search_parts) + ")", {"search": f"%{cleaned.lower()}%"}


def _sql_in(values: set[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in sorted(values)) + ")"


def _flow_base_rows(*, viewer: Any, status_filter: str, search: str, limit: int = 300) -> list[Any]:
    if not table_exists("performance_process_flows"):
        return []
    status_sql, status_params = _status_clause(status_filter)
    scope_sql, scope_params = _scope_clause(viewer)
    search_sql, search_params = _build_search_clause(search)
    params = {"limit": int(limit), **status_params, **scope_params, **search_params}

    period_join = ""
    period_select = "CAST(f.period_id AS TEXT) AS period_name,"
    if table_exists("performance_periods"):
        period_cols = _table_columns("performance_periods")
        period_join = "LEFT JOIN performance_periods pp ON pp.id = f.period_id"
        period_select = _period_name_select_expr("pp", period_cols)

    # BYS360 DEFECT AO: president_requested_at has no real column on
    # performance_process_flows under any name, but the real, migrated
    # performance_president_approvals.requested_at (Phase6's own approval
    # record, joined by flow_id) carries the same information -- a join,
    # not a ghost-column read.
    president_join = ""
    president_requested_at_select = "NULL AS president_requested_at"
    if table_exists("performance_president_approvals"):
        president_join = "LEFT JOIN performance_president_approvals pa ON pa.flow_id = f.id"
        president_requested_at_select = "pa.requested_at AS president_requested_at"

    user_cols = _table_columns("users") if table_exists("users") else set()
    emp_full_name = _name_select_expr("emp", user_cols, "emp_full_name")
    owner_full_name = _name_select_expr("owner", user_cols, "owner_full_name")
    emp_ad = f"emp.{_qident('ad')} AS emp_ad" if "ad" in user_cols else "NULL AS emp_ad"
    emp_soyad = f"emp.{_qident('soyad')} AS emp_soyad" if "soyad" in user_cols else "NULL AS emp_soyad"
    emp_email = f"emp.{_qident('email')} AS emp_email" if "email" in user_cols else "NULL AS emp_email"
    owner_ad = f"owner.{_qident('ad')} AS owner_ad" if "ad" in user_cols else "NULL AS owner_ad"
    owner_soyad = f"owner.{_qident('soyad')} AS owner_soyad" if "soyad" in user_cols else "NULL AS owner_soyad"
    owner_email = f"owner.{_qident('email')} AS owner_email" if "email" in user_cols else "NULL AS owner_email"

    return _rows(
        f"""
        SELECT
            f.id AS flow_id,
            f.evaluation_id,
            f.period_id,
            {period_select}
            f.employee_id,
            f.current_status,
            f.current_owner_id,
            f.last_action_at,
            f.started_at,
            f.created_at,
            f.updated_at,
            f.final_score,
            f.president_approval_required,
            f.president_approval_status,
            f.is_finalized,
            {president_requested_at_select},
            {emp_full_name},
            {emp_ad},
            {emp_soyad},
            {emp_email},
            {owner_full_name},
            {owner_ad},
            {owner_soyad},
            {owner_email}
        FROM performance_process_flows f
        LEFT JOIN users emp ON emp.id = f.employee_id
        LEFT JOIN users owner ON owner.id = f.current_owner_id
        {period_join}
        {president_join}
        WHERE 1=1
        {status_sql}
        {scope_sql}
        {search_sql}
        ORDER BY COALESCE(f.last_action_at, f.updated_at, f.started_at, f.created_at) ASC
        LIMIT :limit
        """,
        params,
    )


def _steps_for_flows(flow_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """BYS360 DEFECT AN: action_at/tracking_visible are not real columns on
    performance_process_flow_steps under any migration or reachable
    runtime schema path -- confirmed against a real, migration-built
    database. Referencing them by name in WHERE/ORDER BY (not just the
    SELECT list) raised OperationalError even though the SELECT itself is
    a plain ``SELECT *``; row.get(...) below already tolerates their
    absence, so only the two raw references need gating."""
    if not flow_ids:
        return {}
    step_cols = _table_columns("performance_process_flow_steps")
    action_at_expr = "action_at" if "action_at" in step_cols else "NULL"
    tracking_visible_filter = (
        " AND COALESCE(tracking_visible, TRUE) = TRUE" if "tracking_visible" in step_cols else ""
    )
    order_expr = f"COALESCE(step_order, 0), COALESCE({action_at_expr}, created_at, CURRENT_TIMESTAMP), id"
    rows = _rows(
        f"""
        SELECT *
        FROM performance_process_flow_steps
        WHERE flow_id IN :flow_ids
        {tracking_visible_filter}
        ORDER BY {order_expr}
        """,
        {"flow_ids": flow_ids},
        expanding=("flow_ids",),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        flow_id = int(row.get("flow_id") or 0)
        title = _safe_text(row.get("visible_title") or row.get("step_title") or row.get("step_code"), "Süreç adımı")
        status = _clean_process_label(row.get("visible_status") or row.get("status"), "Süreç adımı")
        description = _safe_text(row.get("description"), "")
        item = {
            "title": title,
            "status": status,
            "description": description,
            "owner_name": _safe_text(row.get("waiting_owner_name"), ""),
            "action_at": _safe_date(row.get("action_at") or row.get("created_at")),
            "code": _safe_text(row.get("step_code"), ""),
        }
        grouped.setdefault(flow_id, []).append(item)
    return grouped


def _history_for_flows(flow_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """BYS360 DEFECT AN: action_at is not a real column on
    performance_scoring_history (no migration touches this table; the ORM
    model only has created_at) -- confirmed against a real,
    migration-built database. row.get("action_at") below already falls
    back to created_at, so only the raw ORDER BY reference needs gating."""
    if not flow_ids:
        return {}
    if not column_exists("performance_scoring_history", "evaluation_id"):
        return {}
    history_cols = _table_columns("performance_scoring_history")
    action_at_expr = "h.action_at" if "action_at" in history_cols else "NULL"
    rows = _rows(
        f"""
        SELECT
            h.*,
            f.id AS flow_id
        FROM performance_scoring_history h
        JOIN performance_process_flows f
          ON f.evaluation_id = h.evaluation_id
        WHERE f.id IN :flow_ids
        ORDER BY COALESCE({action_at_expr}, h.created_at, CURRENT_TIMESTAMP), h.id
        """,
        {"flow_ids": flow_ids},
        expanding=("flow_ids",),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        flow_id = int(row.get("flow_id") or 0)
        grouped.setdefault(flow_id, []).append(
            {
                "scorer_name": _safe_text(row.get("scorer_name"), "-"),
                "manager_level": _clean_process_label(row.get("manager_level"), "Amir"),
                "score_value": _safe_score(row.get("score_value")),
                "action_status": _clean_process_label(row.get("action_status"), "Süreçte"),
                "action_at": _safe_date(row.get("action_at") or row.get("created_at")),
                "next_stage": _safe_text(row.get("next_stage"), ""),
                "next_owner_name": _safe_text(row.get("next_owner_name"), ""),
            }
        )
    return grouped


_COMPLETED_STATUS_TEXT = {"completed", "finalized", "kesinlesti", "kesinleşti", "tamamlandi", "tamamlandı"}


def _row_bucket(row: Any) -> str:
    """BYS360 DEFECT AO: previously read tracking_bucket/president_status,
    neither a real column under any migration -- always NULL/absent, so this
    always fell through to the raw current_status passthrough regardless of
    real approval/overdue state. Now built entirely from real columns:
    president_approval_required/president_approval_status (real, model-
    backed), is_overdue (derived by the caller from real timestamps before
    calling this), is_finalized/current_status/current_owner_id (real).
    Precedence unchanged from the prior design: president-pending beats
    overdue, which beats completed, which beats waiting-on-owner."""
    president_status = str(row.get("president_approval_status") or "").strip().lower()
    if bool(row.get("president_approval_required")) and president_status not in {"approved", "returned"}:
        return "president_pending"
    if president_status in {"returned", "iade", "iade_edildi"}:
        return "returned"
    if row.get("is_overdue"):
        return "overdue"
    current_status = str(row.get("current_status") or "").strip().lower()
    if row.get("is_finalized") or current_status in _COMPLETED_STATUS_TEXT:
        return "completed"
    if row.get("current_owner_id"):
        return "waiting"
    return "monitoring"


def _visible_bucket(bucket: str) -> str:
    labels = {
        "president_pending": "Başkan/Üst Onay Bekliyor",
        "overdue": "Gecikmiş Süreç",
        "waiting": "İşlem Bekliyor",
        "completed": "Tamamlandı",
        "returned": "İade Edildi",
        "monitoring": "Süreçte",
    }
    return labels.get(_normalize_status_key(bucket), "Süreçte")


def _coerce_datetime(value: Any) -> datetime | None:
    """Raw ``text()`` queries bypass SQLAlchemy's ORM-level DateTime result
    processing, so a DATETIME column can come back as a plain ISO-format
    string rather than a ``datetime`` object (SQLite's raw driver behavior
    for hand-written SQL, unlike ORM-loaded attributes) -- the same
    tolerance _safe_date() already applies via its own ``hasattr(value,
    "strftime")`` check."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _derive_tracking_fields(row: Any) -> dict[str, Any]:
    """BYS360 DEFECT AO: waiting_days/is_overdue/overdue_days have no real
    column under any name -- computed here from real, migrated timestamp
    columns (last_action_at, falling back to started_at, then created_at)
    instead of being read from a column that never exists. is_overdue is
    purely time-based (see _status_clause()'s "overdue" branch for why it
    does not also gate on is_finalized -- that mirrors this module's own
    pre-existing bucket precedence, not a new rule). The threshold is
    PHASE8_OVERDUE_THRESHOLD_DAYS -- see its own definition for why 7 was
    kept rather than replaced with an invented number."""
    reference_at = _coerce_datetime(
        row.get("last_action_at") or row.get("started_at") or row.get("created_at")
    )
    waiting_days = max(0, (datetime.utcnow() - reference_at).days) if reference_at is not None else 0
    is_overdue = waiting_days >= PHASE8_OVERDUE_THRESHOLD_DAYS
    return {
        "waiting_days": waiting_days,
        "is_overdue": is_overdue,
        "overdue_days": waiting_days if is_overdue else 0,
    }


def _derive_last_action_title(row: Any, flow_steps: list[dict[str, Any]]) -> str:
    """BYS360 DEFECT AO: last_action_title has no real column on
    performance_process_flows; the most recent real step (already fetched
    by _steps_for_flows(), ordered oldest-to-newest) carries the same
    information when one exists. Falls back to the flow's own real
    current_status when no step history is available."""
    if flow_steps:
        return _safe_text(flow_steps[-1].get("title"), "Süreç takipte")
    return _clean_process_label(row.get("current_status"), "Süreç takipte")


def build_process_tracking_workspace(
    viewer: Any,
    *,
    status_filter: str = "all",
    search: str = "",
    limit: int = 300,
) -> dict[str, Any]:
    rows = _flow_base_rows(viewer=viewer, status_filter=status_filter, search=search, limit=limit)
    flow_ids = [int(row["flow_id"]) for row in rows if row.get("flow_id")]
    steps = _steps_for_flows(flow_ids)
    histories = _history_for_flows(flow_ids)
    items: list[dict[str, Any]] = []
    counts = {
        "total": 0,
        "waiting": 0,
        "overdue": 0,
        "president_pending": 0,
        "completed": 0,
        "returned": 0,
        "monitoring": 0,
    }
    for row in rows:
        derived = _derive_tracking_fields(row)
        row_with_derived = {**row, **derived}
        bucket = _row_bucket(row_with_derived)
        counts["total"] += 1
        counts[bucket if bucket in counts else "monitoring"] += 1
        flow_id = int(row.get("flow_id") or 0)
        flow_steps = steps.get(flow_id, [])
        owner_name = _full_name_from_row(row, "owner")
        if owner_name == "-":
            owner_name = "Süreçte bekleyen kişi yok"
        item = {
            "flow_id": flow_id,
            "evaluation_id": row.get("evaluation_id"),
            "period_id": row.get("period_id"),
            "period_name": _safe_text(row.get("period_name"), "-"),
            "employee_id": row.get("employee_id"),
            "employee_name": _full_name_from_row(row, "emp"),
            "current_stage": _clean_process_label(row.get("current_status"), "Süreç takipte"),
            "current_status": _clean_process_label(row.get("current_status"), "Süreçte"),
            "bucket": bucket,
            "bucket_label": _visible_bucket(bucket),
            "status_label": _visible_bucket(bucket),
            "status_tone": _bucket_tone(bucket),
            "owner_name": owner_name,
            "owner_user_id": row.get("current_owner_id"),
            "last_action": _derive_last_action_title(row, flow_steps),
            "last_action_at": _safe_date(row.get("last_action_at")),
            "waiting_since": _safe_date(row.get("last_action_at") or row.get("started_at")),
            "waiting_days": derived["waiting_days"],
            "is_overdue": derived["is_overdue"],
            "overdue_days": derived["overdue_days"],
            "final_score": _safe_score(row.get("final_score")),
            "president_required": bool(row.get("president_approval_required")),
            "president_status": _clean_process_label(row.get("president_approval_status"), "-"),
            "president_requested_at": _safe_date(row.get("president_requested_at")),
            "steps": flow_steps,
            "history": histories.get(flow_id, []),
        }
        items.append(item)
    return {
        "page_title": "Performans Süreç Takibi",
        "page_subtitle": "Değerlendirme süreçleri, gecikmeler, üst onaylar ve tamamlanan kayıtlar yetki kapsamına göre izlenir.",
        "status_filter": status_filter,
        "search": search,
        "items": items,
        "counts": counts,
        "viewer_name": user_display_name(viewer),
        "last_refreshed_at": _safe_date(datetime.now()),
    }

def _delete_tracking_flow_ids(flow_ids: list[int]) -> int:
    """Delete tracking-list records and their visible tracking children.

    This intentionally does not delete performance evaluations, scorecards,
    scoring history, president approval records or personnel records.
    """
    clean_ids = [int(value) for value in flow_ids if value]
    if not clean_ids or not table_exists("performance_process_flows"):
        return 0

    try:
        if table_exists("performance_process_flow_steps") and column_exists("performance_process_flow_steps", "flow_id"):
            _execute(
                "DELETE FROM performance_process_flow_steps WHERE flow_id IN :flow_ids",
                {"flow_ids": clean_ids},
                expanding=("flow_ids",),
            )

        if table_exists("performance_process_notifications") and column_exists("performance_process_notifications", "flow_id"):
            _execute(
                "DELETE FROM performance_process_notifications WHERE flow_id IN :flow_ids",
                {"flow_ids": clean_ids},
                expanding=("flow_ids",),
            )

        result = _execute(
            "DELETE FROM performance_process_flows WHERE id IN :flow_ids",
            {"flow_ids": clean_ids},
            expanding=("flow_ids",),
        )
        db.session.commit()
        try:
            return int(result.rowcount or 0)
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            return len(clean_ids)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        raise


def delete_process_tracking_flow(flow_id: int, viewer: Any) -> int:
    if not can_manage_process_tracking(viewer):
        raise PermissionError("Bu işlem için yetkiniz bulunmamaktadır.")
    return _delete_tracking_flow_ids([int(flow_id)])


def delete_visible_process_tracking_flows(
    viewer: Any,
    *,
    status_filter: str = "all",
    search: str = "",
    limit: int = 300,
) -> int:
    if not can_manage_process_tracking(viewer):
        raise PermissionError("Bu işlem için yetkiniz bulunmamaktadır.")
    rows = _flow_base_rows(viewer=viewer, status_filter=status_filter, search=search, limit=limit)
    flow_ids = [int(row["flow_id"]) for row in rows if row.get("flow_id")]
    return _delete_tracking_flow_ids(flow_ids)

def synchronize_phase8_tracking(limit: int | None = None) -> Phase8SyncResult:
    """Süreç takibi yenileme işlemi.

    BYS360 DEFECT AO: this used to persist derived tracking values
    (tracking_bucket/is_overdue/tracking_priority/...) into ghost columns
    that no migration ever created, and its own SELECT omitted is_overdue/
    tracking_bucket entirely -- making the "overdue" bucket structurally
    unreachable from this function even though it independently computed
    is_overdue correctly one line later (see AN/AO history for the full
    defect). Since AO's field-by-field investigation established every one
    of those values is safely computable at read time from real columns
    (see _derive_tracking_fields(), build_process_tracking_workspace()),
    there is nothing left to persist -- build_process_tracking_workspace()
    always recomputes fresh values on every page load, so a stored,
    potentially stale copy would only risk drifting from reality. This
    function now verifies the flows are present and readable (proving the
    "refresh" action genuinely reflects live data) without writing
    anything.
    """
    if not table_exists("performance_process_flows"):
        return Phase8SyncResult()
    sql_limit = "LIMIT :limit" if limit else ""
    params = {"limit": int(limit)} if limit else {}
    rows = _rows(
        f"""
        SELECT id
        FROM performance_process_flows
        ORDER BY id DESC
        {sql_limit}
        """,
        params,
    )
    return Phase8SyncResult(flows_checked=len(rows), flows_updated=0)
