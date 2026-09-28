from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from app.extensions import db
from app.services import runtime_schema

logger = logging.getLogger(__name__)

SETTING_EDGE_COMMENT = "require_criterion_comment_for_score_1_5"
SETTING_ALLOW_MULTI_PERIODS = "allow_multiple_parallel_periods"
SETTING_SHOW_LEVEL3_OPTIONAL = "show_level3_column_optional"
SETTING_EMPLOYEE_GROUP_AVERAGE = "employee_can_see_own_group_average"
SETTING_MANAGER_SCOPE_LIMIT = "manager_performance_scope_limited"
SETTING_OBSERVATION_REMINDER = "show_observation_notes_in_evaluation"
SETTING_LEGACY_ARCHIVE_ENABLED = "legacy_scorecard_archive_enabled"

DEFAULT_SETTINGS = {
    SETTING_EDGE_COMMENT: {
        "label": "1 ve 5 puan açıklaması zorunlu olsun",
        "value": "true",
        "description": "Toplantı kararına göre istenirse kapatılabilir; 70 altı genel açıklama ve Başkan onayı ayrı zorunlu kalır.",
    },
    SETTING_ALLOW_MULTI_PERIODS: {
        "label": "Birden fazla dönem/grup dönemi açılabilsin",
        "value": "true",
        "description": "Aylık, 3 aylık, 6 aylık veya özel grup dönemlerinin paralel yönetimi için hazırlık ayarıdır.",
    },
    SETTING_SHOW_LEVEL3_OPTIONAL: {
        "label": "3. amir sütunu opsiyonel yönetilsin",
        "value": "true",
        "description": "3. amir olmayan yapılarda ekran kalabalığını azaltır; 3. amir varsa akış korunur.",
    },
    SETTING_EMPLOYEE_GROUP_AVERAGE: {
        "label": "Personel kendi grup ortalamasını görebilsin",
        "value": "true",
        "description": "Personel yalnızca kendi karnesi ve kendi kategori/grup ortalamasını görür; başka personel detayı gösterilmez.",
    },
    SETTING_MANAGER_SCOPE_LIMIT: {
        "label": "Yönetici görünürlüğü kendi kapsamıyla sınırlı olsun",
        "value": "true",
        "description": "Koordinatör ve grup başkanı kendi birim/kategori kapsamı dışındaki detayları görmez.",
    },
    SETTING_OBSERVATION_REMINDER: {
        "label": "Ara dönem notları puanlama sırasında hatırlatılsın",
        "value": "true",
        "description": "Olumlu/olumsuz olay, başarı ve gelişim notları puanlama döneminde yetkili amire görünür.",
    },
    SETTING_LEGACY_ARCHIVE_ENABLED: {
        "label": "Geçmiş karne arşivi kullanılsın",
        "value": "true",
        "description": "Eski yıl performans puanları kurumsal hafıza için ayrı arşivde tutulur ve yetkiye göre gösterilir.",
    },
}

BACKLOG = [
    {"priority": "P0", "title": "70 altı Başkan onayı ve genel açıklama", "detail": "70 altı sonuç kesinleşmeden önce İK/Admin ön kontrolü ve Başkan onayı ister."},
    {"priority": "P0", "title": "1 ve 5 açıklama zorunluluğu ayara bağlandı", "detail": "Toplantıdaki esneklik için kriter açıklama zorunluluğu modül ayarından yönetilir."},
    {"priority": "P0", "title": "Grup/kategori görünürlüğü", "detail": "Güvenlik, temizlik vb. personel kategorileri ve grup bazlı dönem kapsamları tanımlanabilir."},
    {"priority": "P1", "title": "3. amir sütunu opsiyonel", "detail": "Dönem oluştururken 3. amir görünürlüğü, yorum/puan modu ve nihai tamamlama şartı seçilir."},
    {"priority": "P1", "title": "Geçmiş dönem karne arşivi", "detail": "Mevcut geçmiş aktarım ekranı korunur; dönem/yıl bazlı görünürlük genişletilir."},
    {"priority": "P2", "title": "Ara dönem performans notları", "detail": "Olumlu/olumsuz olay, başarı ve gelişim notları puan döneminde amire hatırlatılır."},
    {"priority": "P2", "title": "Eğitim/gelişim önerisi", "detail": "Canlı çekirdeği bozmadan sonraki fazda öneri ve gelişim aksiyonu mantığına bağlanır."},
]

DEFAULT_CATEGORIES = [
    ("Güvenlik", "Güvenlik personeli için ayrı dönem ve grup ortalaması takibi."),
    ("Temizlik", "Temizlik personeli için kategori bazlı izleme."),
    ("İdari Personel", "İdari görevlerde çalışan personel için genel kategori."),
    ("Teknik Personel", "Teknik işlerde görevli personel için genel kategori."),
    ("Deneme Süreli Personel", "Deneme süresi veya özel takip dönemi bulunan personel."),
    ("Diğer", "Standart kategorilere girmeyen kayıtlar."),
]

CATEGORY_LABELS = {
    "all": "Tüm Kurum",
    "unit": "Birim / Üst Birim",
    "category": "Personel Kategorisi",
    "user": "Seçilmiş Personel",
}

NOTE_TYPE_LABELS = {
    "positive": "Olumlu Olay / Başarı",
    "negative": "Gelişim Gerektiren Durum",
    "general": "Genel Not",
    "training": "Eğitim / Gelişim Önerisi",
}


def _has_table(name: str) -> bool:
    try:
        return inspect(db.engine).has_table(name)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return set()


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


def _bool_raw(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    raw = str(value).strip().lower()
    if raw in {"1", "true", "on", "yes", "evet", "aktif", "active"}:
        return True
    if raw in {"0", "false", "off", "no", "hayir", "hayır", "pasif", "inactive"}:
        return False
    return bool(default)


def _user_label_sql(alias: str = "u") -> str:
    cols = _columns("users")
    parts: list[str] = []
    if {"ad", "soyad"}.issubset(cols):
        parts.append(f"NULLIF(TRIM(COALESCE({alias}.ad,'') || ' ' || COALESCE({alias}.soyad,'')), '')")
    if "full_name" in cols:
        parts.append(f"NULLIF({alias}.full_name, '')")
    if "name" in cols:
        parts.append(f"NULLIF({alias}.name, '')")
    if "email" in cols:
        parts.append(f"NULLIF({alias}.email, '')")
    if "sicil_no" in cols:
        parts.append(f"NULLIF({alias}.sicil_no, '')")
    parts.append(f"CAST({alias}.id AS TEXT)")
    return "COALESCE(" + ", ".join(parts) + ")"


def _safe_select_columns(table_name: str, aliases: dict[str, str]) -> str:
    cols = _columns(table_name)
    select_parts = []
    for col, fallback in aliases.items():
        if col in cols:
            select_parts.append(f"{col}")
        else:
            select_parts.append(f"{fallback} AS {col}")
    return ", ".join(select_parts)


def _mtd_id_sql() -> str:
    # BYS360 DEFECT AR: bu dosyadaki 5 CREATE TABLE hicbir dialect dali
    # olmadan sabit "id SERIAL PRIMARY KEY" kullaniyordu -- SQLite bunu
    # rowid-alias/autoincrement olarak degil, taninmayan bir tip-affinity
    # tokeni olarak kabul eder, bu yuzden eklenen her satirin id'si SQLite'ta
    # kalici NULL kalirdi (interim_notes_manager_routes.py'deki ayni kusur
    # sinifi, bkz. app/services/performance/interim_notes_runtime.py::_id_sql()).
    try:
        dialect = db.session.get_bind().dialect.name
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        dialect = "postgresql"
    return "id INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == "sqlite" else "id SERIAL PRIMARY KEY"


def provision_meeting_foundation_schema() -> None:
    """Create the meeting-decision tables (explicit maintenance only: flask runtime-schema provision)."""
    id_sql = _mtd_id_sql()
    ddl = [
        f"""
        CREATE TABLE IF NOT EXISTS performance_employee_categories (
            {id_sql},
            category_name VARCHAR(120) NOT NULL UNIQUE,
            description TEXT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS performance_employee_category_assignments (
            {id_sql},
            employee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES performance_employee_categories(id) ON DELETE CASCADE,
            assigned_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            assigned_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_id, category_id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS performance_period_targets (
            {id_sql},
            period_id INTEGER NOT NULL REFERENCES performance_periods(id) ON DELETE CASCADE,
            target_type VARCHAR(40) NOT NULL DEFAULT 'all',
            target_value VARCHAR(255) NULL,
            notes TEXT NULL,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS performance_period_observation_notes (
            {id_sql},
            period_id INTEGER NOT NULL REFERENCES performance_periods(id) ON DELETE CASCADE,
            employee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            manager_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            note_type VARCHAR(40) NOT NULL DEFAULT 'general',
            title VARCHAR(255) NOT NULL,
            note TEXT NOT NULL,
            visibility_level VARCHAR(40) NOT NULL DEFAULT 'manager_scope',
            remind_in_evaluation BOOLEAN NOT NULL DEFAULT TRUE,
            occurred_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS performance_legacy_scorecards (
            {id_sql},
            employee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            period_year INTEGER NOT NULL,
            period_title VARCHAR(255) NOT NULL,
            score_100 NUMERIC(6,2) NULL,
            category_name VARCHAR(120) NULL,
            unit_name VARCHAR(255) NULL,
            general_comment TEXT NULL,
            source_note TEXT NULL,
            is_visible_to_employee BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_perf_category_assign_employee ON performance_employee_category_assignments(employee_id)",
        "CREATE INDEX IF NOT EXISTS ix_perf_period_targets_period ON performance_period_targets(period_id)",
        "CREATE INDEX IF NOT EXISTS ix_perf_observation_period_employee ON performance_period_observation_notes(period_id, employee_id)",
        "CREATE INDEX IF NOT EXISTS ix_perf_legacy_employee_year ON performance_legacy_scorecards(employee_id, period_year)",
    ]
    for item in ddl:
        db.session.execute(text(item))

    # Önceki overlay ile oluşmuş tablolarda yeni kolon yoksa güvenli ekle.
    if _has_table("performance_period_observation_notes") and "remind_in_evaluation" not in _columns("performance_period_observation_notes"):
        try:
            db.session.execute(text("ALTER TABLE performance_period_observation_notes ADD COLUMN remind_in_evaluation BOOLEAN NOT NULL DEFAULT TRUE"))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            db.session.rollback()
    db.session.commit()


MEETING_FOUNDATION_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="performance.meeting_foundation",
    tables=(
        "performance_employee_categories",
        "performance_employee_category_assignments",
        "performance_period_targets",
        "performance_period_observation_notes",
        "performance_legacy_scorecards",
    ),
    indexes=(
        ("performance_employee_category_assignments", "ix_perf_category_assign_employee"),
        ("performance_period_targets", "ix_perf_period_targets_period"),
        ("performance_period_observation_notes", "ix_perf_observation_period_employee"),
        ("performance_legacy_scorecards", "ix_perf_legacy_employee_year"),
    ),
    columns=(("performance_period_observation_notes", "remind_in_evaluation"),),
    provision=provision_meeting_foundation_schema,
))


def ensure_meeting_foundation_schema(seed_categories: bool = False) -> None:
    """Verify the meeting tables exist (never creates them), then seed default settings."""
    runtime_schema.require(MEETING_FOUNDATION_SCHEMA)
    _seed_default_settings(flush=True)
    if seed_categories:
        _seed_default_categories(flush=True)
    db.session.commit()


def _seed_default_settings(*, flush: bool = False) -> None:
    if not _has_table("module_settings"):
        return
    for key, payload in DEFAULT_SETTINGS.items():
        existing = _scalar(
            "SELECT id FROM module_settings WHERE module_key='performance' AND setting_key=:key LIMIT 1",
            {"key": key},
        )
        if existing:
            continue
        db.session.execute(
            text("""
                INSERT INTO module_settings (module_key, setting_key, label, value_text, value_type, description, is_active, created_at, updated_at)
                VALUES ('performance', :key, :label, :value, 'boolean', :description, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {"key": key, "label": payload["label"], "value": payload["value"], "description": payload["description"]},
        )
    if flush:
        db.session.flush()


def _seed_default_categories(*, flush: bool = False) -> None:
    if not _has_table("performance_employee_categories"):
        return
    for idx, (name, description) in enumerate(DEFAULT_CATEGORIES, start=10):
        add_category(name, description, idx, commit=False)
    if flush:
        db.session.flush()


def get_setting_bool(setting_key: str, default: bool = False) -> bool:
    if not _has_table("module_settings"):
        return bool(default)
    raw = _scalar(
        """
        SELECT value_text
        FROM module_settings
        WHERE module_key='performance' AND setting_key=:key AND is_active=true
        ORDER BY id DESC LIMIT 1
        """,
        {"key": setting_key},
        DEFAULT_SETTINGS.get(setting_key, {}).get("value", default),
    )
    return _bool_raw(raw, default)


def build_meeting_development_context() -> dict[str, Any]:
    ensure_meeting_foundation_schema()
    settings = _rows("""
        SELECT setting_key, label, value_text, description
        FROM module_settings
        WHERE module_key='performance'
          AND setting_key IN (
            'require_criterion_comment_for_score_1_5',
            'allow_multiple_parallel_periods',
            'show_level3_column_optional',
            'employee_can_see_own_group_average',
            'manager_performance_scope_limited',
            'show_observation_notes_in_evaluation',
            'legacy_scorecard_archive_enabled'
          )
        ORDER BY setting_key
    """) if _has_table("module_settings") else []
    if not settings:
        settings = [{"setting_key": k, "label": v["label"], "value_text": v["value"], "description": v["description"]} for k, v in DEFAULT_SETTINGS.items()]

    label_sql = _user_label_sql("u") if _has_table("users") else "CAST(NULL AS TEXT)"
    user_cols = _columns("users")
    birim_select = "u.birim" if "birim" in user_cols else "NULL"
    ust_birim_select = "u.ust_birim" if "ust_birim" in user_cols else "NULL"
    role_filter = "WHERE COALESCE(u.role,'') <> 'admin'" if "role" in user_cols else ""
    user_order = "ORDER BY full_name ASC"

    return {
        "settings": settings,
        "backlog": BACKLOG,
        "categories": _rows("SELECT * FROM performance_employee_categories ORDER BY sort_order ASC, category_name ASC LIMIT 100"),
        "targets": _rows("""
            SELECT t.*, p.title AS period_title
            FROM performance_period_targets t
            LEFT JOIN performance_periods p ON p.id = t.period_id
            ORDER BY t.id DESC
            LIMIT 100
        """),
        "notes": _rows(f"""
            SELECT n.*, p.title AS period_title,
                   {label_sql} AS employee_name
            FROM performance_period_observation_notes n
            LEFT JOIN performance_periods p ON p.id = n.period_id
            LEFT JOIN users u ON u.id = n.employee_id
            ORDER BY n.id DESC
            LIMIT 100
        """),
        "periods": _rows("SELECT id, title FROM performance_periods ORDER BY start_date DESC, id DESC LIMIT 100") if _has_table("performance_periods") else [],
        "users": _rows(f"""
            SELECT u.id, {label_sql} AS full_name, {birim_select} AS birim, {ust_birim_select} AS ust_birim
            FROM users u
            {role_filter}
            {user_order}
            LIMIT 500
        """) if _has_table("users") else [],
        "category_labels": CATEGORY_LABELS,
        "note_type_labels": NOTE_TYPE_LABELS,
    }


def build_meeting_faz3_context(current_user: Any | None = None) -> dict[str, Any]:
    ensure_meeting_foundation_schema(seed_categories=True)
    ctx = build_meeting_development_context()
    ctx.update(
        {
            "assignments": list_category_assignments(limit=200),
            "legacy_scorecards": list_legacy_scorecards(current_user=current_user, limit=200),
            "group_averages": build_group_average_preview(),
            "scope_rules": build_visibility_rule_cards(),
            "faz3_summary": build_meeting_development_summary(),
        }
    )
    return ctx


def build_meeting_development_summary() -> dict[str, Any]:
    ensure_meeting_foundation_schema()
    return {
        "categories_count": _scalar("SELECT COUNT(*) FROM performance_employee_categories", default=0),
        "assignments_count": _scalar("SELECT COUNT(*) FROM performance_employee_category_assignments WHERE COALESCE(is_active, true)=true", default=0),
        "targets_count": _scalar("SELECT COUNT(*) FROM performance_period_targets", default=0),
        "notes_count": _scalar("SELECT COUNT(*) FROM performance_period_observation_notes", default=0),
        "legacy_count": _scalar("SELECT COUNT(*) FROM performance_legacy_scorecards", default=0),
        "employee_group_average_enabled": get_setting_bool(SETTING_EMPLOYEE_GROUP_AVERAGE, True),
        "manager_scope_limited": get_setting_bool(SETTING_MANAGER_SCOPE_LIMIT, True),
    }


def build_visibility_rule_cards() -> list[dict[str, str]]:
    return [
        {"role": "Personel", "scope": "Kendi karnesi + kendi kategori/grup ortalaması", "blocked": "Başka personelin detay puanı, amir görüşü ve özel notları"},
        {"role": "Koordinatör", "scope": "Kendi çalışma grubu / kategori kapsamı", "blocked": "Yetkili olmadığı birim ve personel detayları"},
        {"role": "Grup Başkanı", "scope": "Kendi grup başkanlığı kapsamı", "blocked": "Diğer grup başkanlıklarının personel detayları"},
        {"role": "Başkan / Admin", "scope": "Kurumsal genel görünürlük ve onay bekleyen düşük performanslar", "blocked": "Yetki dışı teknik veya gizli sistem verisi"},
    ]


def update_setting(setting_key: str, value: bool, actor_id: int | None = None) -> None:
    if setting_key not in DEFAULT_SETTINGS or not _has_table("module_settings"):
        return
    payload = DEFAULT_SETTINGS[setting_key]
    raw = "true" if value else "false"
    existing = _scalar("SELECT id FROM module_settings WHERE module_key='performance' AND setting_key=:key LIMIT 1", {"key": setting_key})
    if existing:
        db.session.execute(
            text("""
                UPDATE module_settings
                SET value_text=:value, updated_by_user_id=:actor_id, updated_at=CURRENT_TIMESTAMP
                WHERE id=:id
            """),
            {"value": raw, "actor_id": actor_id, "id": existing},
        )
    else:
        db.session.execute(
            text("""
                INSERT INTO module_settings (module_key, setting_key, label, value_text, value_type, description, is_active, updated_by_user_id, created_at, updated_at)
                VALUES ('performance', :key, :label, :value, 'boolean', :description, true, :actor_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {"key": setting_key, "label": payload["label"], "value": raw, "description": payload["description"], "actor_id": actor_id},
        )
    db.session.commit()


def add_category(category_name: str, description: str = "", sort_order: int = 0, *, commit: bool = True) -> None:
    ensure_meeting_foundation_schema() if commit else None
    try:
        db.session.execute(
            text("""
                INSERT INTO performance_employee_categories (category_name, description, sort_order, is_active, created_at, updated_at)
                VALUES (:name, :description, :sort_order, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (category_name) DO UPDATE
                SET description=EXCLUDED.description, sort_order=EXCLUDED.sort_order, is_active=true, updated_at=CURRENT_TIMESTAMP
            """),
            {"name": category_name, "description": description or None, "sort_order": int(sort_order or 0)},
        )
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        existing = _scalar("SELECT id FROM performance_employee_categories WHERE category_name=:name", {"name": category_name})
        if existing:
            db.session.execute(text("UPDATE performance_employee_categories SET description=:description, sort_order=:sort_order, is_active=true, updated_at=CURRENT_TIMESTAMP WHERE id=:id"), {"id": existing, "description": description or None, "sort_order": int(sort_order or 0)})
        else:
            db.session.execute(text("INSERT INTO performance_employee_categories (category_name, description, sort_order, is_active, created_at, updated_at) VALUES (:name, :description, :sort_order, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"name": category_name, "description": description or None, "sort_order": int(sort_order or 0)})
    if commit:
        db.session.commit()


def assign_employee_category(employee_id: int, category_id: int, actor_id: int | None = None) -> None:
    ensure_meeting_foundation_schema()
    try:
        db.session.execute(
            text("""
                INSERT INTO performance_employee_category_assignments (employee_id, category_id, assigned_by_user_id, is_active, assigned_at, created_at, updated_at)
                VALUES (:employee_id, :category_id, :actor_id, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (employee_id, category_id) DO UPDATE
                SET is_active=true, assigned_by_user_id=EXCLUDED.assigned_by_user_id, updated_at=CURRENT_TIMESTAMP
            """),
            {"employee_id": int(employee_id), "category_id": int(category_id), "actor_id": actor_id},
        )
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        existing = _scalar(
            "SELECT id FROM performance_employee_category_assignments WHERE employee_id=:employee_id AND category_id=:category_id",
            {"employee_id": int(employee_id), "category_id": int(category_id)},
        )
        if existing:
            db.session.execute(text("UPDATE performance_employee_category_assignments SET is_active=true, assigned_by_user_id=:actor_id, updated_at=CURRENT_TIMESTAMP WHERE id=:id"), {"id": existing, "actor_id": actor_id})
        else:
            db.session.execute(text("INSERT INTO performance_employee_category_assignments (employee_id, category_id, assigned_by_user_id, is_active, assigned_at, created_at, updated_at) VALUES (:employee_id, :category_id, :actor_id, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"employee_id": int(employee_id), "category_id": int(category_id), "actor_id": actor_id})
    db.session.commit()


def list_category_assignments(limit: int = 100) -> list[dict[str, Any]]:
    if not _has_table("performance_employee_category_assignments"):
        return []
    label_sql = _user_label_sql("u")
    return _rows(f"""
        SELECT a.*, c.category_name, {label_sql} AS employee_name
        FROM performance_employee_category_assignments a
        LEFT JOIN performance_employee_categories c ON c.id = a.category_id
        LEFT JOIN users u ON u.id = a.employee_id
        WHERE COALESCE(a.is_active, true)=true
        ORDER BY a.id DESC
        LIMIT :limit
    """, {"limit": int(limit)})


def add_period_target(period_id: int, target_type: str, target_value: str = "", notes: str = "") -> None:
    ensure_meeting_foundation_schema()
    db.session.execute(
        text("""
            INSERT INTO performance_period_targets (period_id, target_type, target_value, notes, created_at, updated_at)
            VALUES (:period_id, :target_type, :target_value, :notes, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """),
        {"period_id": int(period_id), "target_type": target_type, "target_value": target_value or None, "notes": notes or None},
    )
    db.session.commit()


def add_observation_note(period_id: int, employee_id: int, manager_id: int | None, note_type: str, title: str, note: str, remind_in_evaluation: bool = True) -> None:
    ensure_meeting_foundation_schema()
    db.session.execute(
        text("""
            INSERT INTO performance_period_observation_notes (period_id, employee_id, manager_id, note_type, title, note, visibility_level, remind_in_evaluation, occurred_at, created_at, updated_at)
            VALUES (:period_id, :employee_id, :manager_id, :note_type, :title, :note, 'manager_scope', :remind, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """),
        {"period_id": int(period_id), "employee_id": int(employee_id), "manager_id": manager_id, "note_type": note_type, "title": title, "note": note, "remind": bool(remind_in_evaluation)},
    )
    db.session.commit()


def add_legacy_scorecard(employee_id: int, period_year: int, period_title: str, score_100: float | None, category_name: str = "", unit_name: str = "", general_comment: str = "", source_note: str = "", visible_to_employee: bool = True, actor_id: int | None = None) -> None:
    ensure_meeting_foundation_schema()
    db.session.execute(
        text("""
            INSERT INTO performance_legacy_scorecards
                (employee_id, period_year, period_title, score_100, category_name, unit_name, general_comment, source_note, is_visible_to_employee, created_by_user_id, created_at, updated_at)
            VALUES
                (:employee_id, :period_year, :period_title, :score_100, :category_name, :unit_name, :general_comment, :source_note, :visible, :actor_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """),
        {
            "employee_id": int(employee_id),
            "period_year": int(period_year),
            "period_title": period_title,
            "score_100": score_100,
            "category_name": category_name or None,
            "unit_name": unit_name or None,
            "general_comment": general_comment or None,
            "source_note": source_note or None,
            "visible": bool(visible_to_employee),
            "actor_id": actor_id,
        },
    )
    db.session.commit()


def _is_admin_like(current_user: Any | None) -> bool:
    role = str(getattr(current_user, "role", "") or "").lower()
    return role in {"admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan"}


def list_legacy_scorecards(current_user: Any | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if not _has_table("performance_legacy_scorecards"):
        return []
    label_sql = _user_label_sql("u")
    params: dict[str, Any] = {"limit": int(limit)}
    where = ""
    # Personel rolünde yalnızca kendi görünür kayıtları döner. Yönetici kapsam filtresi gerçek raporlama ekranlarında uygulanır.
    role = str(getattr(current_user, "role", "") or "").lower()
    uid = getattr(current_user, "id", None)
    if role in {"personel", "employee", "standart", "standard"} and uid:
        where = "WHERE l.employee_id=:uid AND COALESCE(l.is_visible_to_employee, true)=true"
        params["uid"] = int(uid)
    return _rows(f"""
        SELECT l.*, {label_sql} AS employee_name
        FROM performance_legacy_scorecards l
        LEFT JOIN users u ON u.id = l.employee_id
        {where}
        ORDER BY l.period_year DESC, l.id DESC
        LIMIT :limit
    """, params)


def build_group_average_preview() -> list[dict[str, Any]]:
    """Kategori bazlı geçmiş/aktif puan görünümü için hafif önizleme üretir."""
    if not _has_table("performance_employee_categories"):
        return []
    legacy_part = """
        SELECT category_name, COUNT(*) AS record_count, ROUND(AVG(score_100), 2) AS average_score
        FROM performance_legacy_scorecards
        WHERE score_100 IS NOT NULL AND category_name IS NOT NULL
        GROUP BY category_name
    """ if _has_table("performance_legacy_scorecards") else "SELECT NULL AS category_name, 0 AS record_count, NULL AS average_score WHERE 1=0"
    return _rows(f"""
        SELECT c.category_name,
               COALESCE(x.record_count, 0) AS record_count,
               x.average_score
        FROM performance_employee_categories c
        LEFT JOIN ({legacy_part}) x ON x.category_name = c.category_name
        WHERE COALESCE(c.is_active, true)=true
        ORDER BY c.sort_order ASC, c.category_name ASC
        LIMIT 100
    """)
