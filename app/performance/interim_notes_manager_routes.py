from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.route_registry import main_bp

# BYS360_STUB_AI_V60_INTERIM_IMPORT
from app.services.ai.stub_panel_bridge import build_interim_notes_ai_panel
from app.services.performance.interim_notes_runtime import _id_sql

logger = logging.getLogger(__name__)
# /BYS360_STUB_AI_V60_INTERIM_IMPORT

# BYS360_INTERIM_NOTES_MENU_REDESIGN_V3_ROUTE

NOTE_TYPES = [
    ('olumlu_olay', 'Olumlu Olay', 'fa-regular fa-face-smile', 'Güçlü davranış, katkı veya örnek uygulama'),
    ('olumsuz_olay', 'Olumsuz Olay', 'fa-regular fa-circle-xmark', 'Takip edilmesi gereken sorun veya aksama'),
    ('basari', 'Başarı', 'fa-solid fa-award', 'Somut başarı, tamamlanan iş veya olumlu çıktı'),
    ('gelisim_ihtiyaci', 'Gelişim İhtiyacı', 'fa-solid fa-seedling', 'Gelişim alanı, destek ihtiyacı veya öneri'),
    ('genel_gozlem', 'Genel Gözlem', 'fa-regular fa-note-sticky', 'Puan üretmeyen dönem içi gözlem notu'),
]
NOTE_LABELS = {k: v for k, v, *_ in NOTE_TYPES}
NOTE_ICONS = {k: icon for k, _, icon, *_ in NOTE_TYPES}
ALLOWED_ROLES = {
    'admin','super_admin','system_admin','sistem_yoneticisi','baskan','başkan','baskan_yardimcisi','başkan_yardımcısı',
    'grup_baskani','grup_başkanı','mali_musavir','mali_müşavir','koordinator','koordinatör','birim_sorumlusu'
}
ADMIN_ROLES = {'admin','super_admin','system_admin','sistem_yoneticisi','baskan','başkan'}

def _role():
    return str(getattr(current_user, 'role', '') or '').strip().lower()

def _is_admin_like():
    return bool(getattr(current_user, 'is_admin', False) or getattr(current_user, 'is_superuser', False) or _role() in ADMIN_ROLES)

def _can_access():
    return bool(getattr(current_user, 'is_authenticated', False) and (_is_admin_like() or _role() in ALLOWED_ROLES))

def _int(v):
    try:
        return int(v) if v not in (None, '', 'None') else None
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None

@lru_cache(maxsize=32)
def _cols(table):
    # BYS360 DEFECT AL: raw dialect-branched information_schema/PRAGMA query
    # replaced with SQLAlchemy's inspect(), which is dialect-neutral by
    # construction.
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table(table):
            return set()
        return {str(col["name"]) for col in inspector.get_columns(table)}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        return set()

def _first(cols, names):
    for n in names:
        if n in cols:
            return n
    return None

def _name_expr(alias, cols):
    parts = []
    for c in ['full_name_cache','full_name','name']:
        if c in cols:
            parts.append(f"NULLIF({alias}.{c}, '')")
    if 'ad' in cols or 'soyad' in cols:
        ad = f"COALESCE({alias}.ad, '')" if 'ad' in cols else "''"
        soyad = f"COALESCE({alias}.soyad, '')" if 'soyad' in cols else "''"
        parts.append(f"NULLIF(TRIM({ad} || ' ' || {soyad}), '')")
    if 'email' in cols:
        parts.append(f"NULLIF({alias}.email, '')")
    parts.append("'Personel'")
    return 'COALESCE(' + ', '.join(parts) + ')'

def _col(alias, cols, name, default="''"):
    return f"{alias}.{name}" if name in cols else default

def _periods():
    cols = _cols('performance_periods')
    if not cols or 'id' not in cols:
        return []
    title = _first(cols, ['title','name','period_name']) or 'id'
    order = _first(cols, ['start_date','created_at','id']) or 'id'
    try:
        return db.session.execute(text(f"SELECT id, {title} AS title FROM performance_periods ORDER BY {order} DESC NULLS LAST, id DESC LIMIT 100")).mappings().all()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        try:
            return db.session.execute(text(f"SELECT id, {title} AS title FROM performance_periods ORDER BY id DESC LIMIT 100")).mappings().all()
        except Exception:
            db.session.rollback()
            return []

def _people():
    cols = _cols('users')
    if not cols or 'id' not in cols:
        return []
    name = _name_expr('u', cols)
    select = [
        'u.id AS id', f'{name} AS full_name', _col('u', cols, 'sicil_no') + ' AS sicil_no',
        _col('u', cols, 'unvan') + ' AS unvan', _col('u', cols, 'birim') + ' AS birim', _col('u', cols, 'ust_birim') + ' AS ust_birim'
    ]
    where: list[str] = []
    params: dict[str, Any] = {}
    if 'is_active' in cols:
        where.append('COALESCE(u.is_active, TRUE)=TRUE')
    if not _is_admin_like():
        uid, sicil = getattr(current_user, 'id', None), str(getattr(current_user, 'sicil_no', '') or '').strip()
        scope = []
        for c in ['yonetici_sicil','ikinci_yonetici_sicil','ucuncu_yonetici_sicil','manager_sicil_no','supervisor_sicil_no']:
            if c in cols and sicil:
                scope.append(f'u.{c}=:sicil')
        for c in ['manager_id','supervisor_id','direct_manager_id','first_manager_id','second_manager_id','third_manager_id']:
            if c in cols and uid is not None:
                scope.append(f'u.{c}=:uid')
        if sicil:
            params['sicil'] = sicil
        if uid is not None:
            params['uid'] = int(uid)
        if scope:
            where.append('(' + ' OR '.join(scope) + ')')
        else:
            return []
    sql = 'SELECT ' + ', '.join(select) + ' FROM users u'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY full_name ASC LIMIT 1500'
    try:
        return db.session.execute(text(sql), params).mappings().all()
    except Exception:
        db.session.rollback()
        return []

def _allowed_employee(employee_id, people):
    if not employee_id:
        return False
    if _is_admin_like():
        return True
    return any(int(p.get('id')) == int(employee_id) for p in people if p.get('id') is not None)

def _notes(people, employee_id=None, period_id=None, note_type=None, query=None):
    cols, ucols, pcols = _cols('performance_interim_notes'), _cols('users'), _cols('performance_periods')
    if not cols or 'id' not in cols:
        return []
    emp = 'COALESCE(n.employee_id, n.employee_user_id)' if {'employee_id','employee_user_id'} <= cols else (f"n.{_first(cols, ['employee_id','employee_user_id'])}" if _first(cols, ['employee_id','employee_user_id']) else 'NULL')
    per = 'n.period_id' if 'period_id' in cols else 'NULL'
    typ = f"n.{_first(cols, ['note_type','type'])}" if _first(cols, ['note_type','type']) else "'genel_gozlem'"
    title = 'COALESCE(' + ', '.join([f"NULLIF(n.{c}, '')" for c in ['title','note_title'] if c in cols] + ["''"]) + ')'
    body = 'COALESCE(' + ', '.join([f"NULLIF(n.{c}, '')" for c in ['note_text','note_body','note','content','description'] if c in cols] + ["''"]) + ')'
    created = f"n.{_first(cols, ['created_at','occurred_at','updated_at'])}" if _first(cols, ['created_at','occurred_at','updated_at']) else 'NULL'
    include = f"COALESCE(n.{_first(cols, ['include_in_scorecard','visible_on_scorecard'])}, FALSE)" if _first(cols, ['include_in_scorecard','visible_on_scorecard']) else 'FALSE'
    active = _first(cols, ['is_active','active'])
    uname = _name_expr('u', ucols) if ucols else "'Personel'"
    period_title = f"p.{_first(pcols, ['title','name','period_name'])}" if pcols and _first(pcols, ['title','name','period_name']) else "''"
    cby = _first(cols, ['created_by_id','created_by','manager_id'])
    author_join, author = '', "''"
    if cby and ucols:
        author_join = f' LEFT JOIN users au ON au.id = n.{cby}'
        author = _name_expr('au', ucols)
    where: list[str] = []
    params: dict[str, Any] = {}
    if active:
        where.append(f'COALESCE(n.{active}, TRUE)=TRUE')
    ids = [int(p.get('id')) for p in people if p.get('id') is not None]
    if employee_id:
        where.append(f'{emp}=:employee_id')
        params['employee_id'] = int(employee_id)
    elif not _is_admin_like():
        if not ids:
            return []
        if db.engine.dialect.name == 'postgresql':
            where.append(f'{emp}=ANY(:scope_ids)')
            params['scope_ids'] = ids
        else:
            where.append(f'{emp} IN ({','.join(str(i) for i in ids)})')
    if period_id:
        where.append(f'({per}=:period_id OR {per} IS NULL)')
        params['period_id'] = int(period_id)
    if note_type:
        where.append(f'{typ}=:note_type')
        params['note_type'] = note_type
    if query:
        where.append(f'(LOWER({title}) LIKE :q OR LOWER({body}) LIKE :q OR LOWER({uname}) LIKE :q)')
        params['q'] = '%' + query.lower() + '%'
    sql = f"""
        SELECT n.id AS id, {emp} AS employee_id, {per} AS period_id, {typ} AS note_type,
               {title} AS title, {body} AS note_body, {include} AS include_in_scorecard,
               {created} AS created_at, {uname} AS employee_name, {_col('u', ucols, 'birim')} AS birim,
               {period_title} AS period_title, {author} AS created_by_name
        FROM performance_interim_notes n
        LEFT JOIN users u ON u.id = {emp}
        LEFT JOIN performance_periods p ON p.id = {per}
        {author_join}
    """
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY created_at DESC NULLS LAST, n.id DESC LIMIT 250'
    try:
        rows = db.session.execute(text(sql), params).mappings().all()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        try:
            rows = db.session.execute(text(sql.replace(' DESC NULLS LAST', ' DESC')), params).mappings().all()
        except Exception:
            db.session.rollback()
            return []
    out = []
    for r in rows:
        d = dict(r)
        key = d.get('note_type') or 'genel_gozlem'
        d['note_type_label'] = NOTE_LABELS.get(key, 'Bilinmiyor')
        d['note_type_icon'] = NOTE_ICONS.get(key, 'fa-regular fa-note-sticky')
        out.append(d)
    return out

def _summary(notes):
    counts = {k: 0 for k, *_ in NOTE_TYPES}
    scorecard = 0
    latest = None
    for n in notes:
        k = n.get('note_type') or 'genel_gozlem'
        if k in counts:
            counts[k] += 1
        if n.get('include_in_scorecard'):
            scorecard += 1
        if not latest and n.get('created_at'):
            latest = n.get('created_at')
    return {'total': len(notes), 'scorecard': scorecard, 'latest': latest, 'type_counts': counts}

def _access_denied():
    return render_template('performance/interim_notes_manager.html', access_denied=True, people=[], periods=[], notes=[], note_types=NOTE_TYPES, summary=_summary([]), selected_employee_id=None, selected_period_id=None, selected_note_type='', search_query='', is_admin_like=False), 403

@main_bp.route('/performance/interim-notes', endpoint='performance_interim_notes', methods=['GET', 'POST'])
@main_bp.route('/performans/donem-ici-notlar', endpoint='performance_interim_notes_tr')
@login_required
def performance_interim_notes():
    from flask import flash, redirect, render_template, request
    from flask_login import current_user
    from sqlalchemy import bindparam, text as _sql_text

    from app.extensions import db

    # BYS360_P13B_NEW13B01_FIX: bu view @login_required disinda hicbir
    # yetki/kapsam kontrolu yapmiyordu (Phase 13B, confirmed - birimi
    # ilgilendirmeyen bir personel, tum calisanlarin gizli olumsuz
    # performans notlarini okuyup baska bir calisan adina sahte not
    # ekleyebiliyordu; menu haritasi zaten bu anahtari o rol icin False
    # olarak isaretliyordu). Dosyadaki mevcut _can_access()/_people()/
    # _allowed_employee() kapsam yardimcilari (asagida kardes create
    # endpoint'inde de kullanilir) burada da zorunlu kilinir.
    if not _can_access():
        return _access_denied()

    scoped_people = _people()
    scoped_ids = [int(p.get('id')) for p in scoped_people if p.get('id') is not None]

    def _rows(sql, params=None, *, expanding=()):
        # BYS360 DEFECT AR: `expanding` bir IN listesinin ham string
        # birlestirme yerine gercek SQLAlchemy bind parametresi olarak
        # genisletilmesini saglar (bkz. process_engine_phase8_tracking.py
        # _prepare_clause, ayni desen).
        clause = _sql_text(sql)
        if expanding:
            clause = clause.bindparams(*(bindparam(name, expanding=True) for name in expanding))
        try:
            return list(db.session.execute(clause, params or {}).mappings())
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            return []

    def _scalar(sql, params=None, default=0):
        try:
            value = db.session.execute(_sql_text(sql), params or {}).scalar()
            return value if value is not None else default
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            return default

    def _ensure_table():
        # BYS360 DEFECT AR: id kolonu artik dialect'e gore uretiliyor; eskiden
        # sabit SERIAL kullanildigi icin SQLite'ta id her zaman NULL kaliyordu.
        db.session.execute(_sql_text(f"""
            CREATE TABLE IF NOT EXISTS performance_interim_notes_live (
                {_id_sql()},
                personnel_id INTEGER,
                period_id INTEGER,
                note_type VARCHAR(40) NOT NULL DEFAULT 'genel',
                title VARCHAR(180),
                note TEXT NOT NULL,
                scorecard_visible BOOLEAN NOT NULL DEFAULT FALSE,
                created_by_user_id INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.session.commit()

    def _type_label(value):
        labels = {
            "olumlu": "Olumlu Olay",
            "basari": "Başarı",
            "başarı": "Başarı",
            "gelisim": "Gelişim İhtiyacı",
            "gelişim": "Gelişim İhtiyacı",
            "olumsuz": "Olumsuz Olay",
            "genel": "Genel Gözlem",
        }
        return labels.get((value or "genel").strip().lower(), "Genel Gözlem")

    _ensure_table()

    if request.method == "POST":
        personnel_id_raw = (request.form.get("personnel_id") or "").strip()
        period_id_raw = (request.form.get("period_id") or "").strip()
        note_type = (request.form.get("note_type") or "genel").strip().lower()
        title = (request.form.get("title") or "").strip()
        note = (request.form.get("note") or "").strip()
        scorecard_visible = (request.form.get("scorecard_visible") or "0").strip() == "1"

        if not personnel_id_raw:
            flash("Lütfen personel seçiniz.", "warning")
            return redirect(request.path)

        if not note:
            flash("Not açıklaması boş bırakılamaz.", "warning")
            return redirect(request.path)

        try:
            personnel_id = int(personnel_id_raw)
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            flash("Personel seçimi geçerli değil.", "warning")
            return redirect(request.path)

        if not _allowed_employee(personnel_id, scoped_people):
            flash("Bu personel için dönem içi not ekleme yetkiniz bulunmamaktadır.", "warning")
            return redirect(request.path)

        period_id = None
        if period_id_raw:
            try:
                period_id = int(period_id_raw)
            except Exception:
                logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
                period_id = None

        if not title:
            title = _type_label(note_type)

        db.session.execute(
            _sql_text("""
                INSERT INTO performance_interim_notes_live
                    (personnel_id, period_id, note_type, title, note, scorecard_visible, created_by_user_id, created_at)
                VALUES
                    (:personnel_id, :period_id, :note_type, :title, :note, :scorecard_visible, :created_by_user_id, CURRENT_TIMESTAMP)
            """),
            {
                "personnel_id": personnel_id,
                "period_id": period_id,
                "note_type": note_type,
                "title": title,
                "note": note,
                "scorecard_visible": scorecard_visible,
                "created_by_user_id": getattr(current_user, "id", None),
            },
        )
        db.session.commit()

        flash("Dönem içi not başarıyla kaydedildi.", "success")
        return redirect(request.path)

    # BYS360_P13B_NEW13B01_FIX: personel secimi eskiden kapsam gozetmeksizin
    # kurumdaki TUM kullanicilari listeliyordu; artik _people() ile ayni
    # yonetici-hiyerarsisi kapsamini kullanir (admin benzeri roller icin
    # degismez, tam liste gorur).
    personnel_options = [
        {"id": p.get("id"), "label": p.get("full_name") or str(p.get("id"))}
        for p in scoped_people
        if p.get("id") is not None
    ]

    period_options = [
        dict(row)
        for row in _rows("""
            SELECT
                id,
                CONCAT('Dönem ', CAST(id AS TEXT)) AS label
            FROM performance_periods
            ORDER BY id DESC
            LIMIT 50
        """)
    ]

    # BYS360_P13B_NEW13B01_FIX: bu sorgu hicbir WHERE kosulu tasimiyordu; her
    # giris yapmis kullanici kurumdaki TUM calisanlarin dahil gizli olumsuz
    # notlarini goruyordu (Phase 13B, confirmed). Admin-benzeri roller disinda
    # sonuc _people() kapsamindaki personel kimlikleriyle sinirlanir.
    if _is_admin_like():
        scope_where = ""
    elif scoped_ids:
        scope_where = "WHERE n.personnel_id IN :scope_ids"
    else:
        scope_where = None

    if scope_where is None:
        note_items_raw = []
    else:
        note_items_raw = _rows(
            f"""
            SELECT
                n.id,
                n.personnel_id,
                n.period_id,
                n.note_type,
                n.title,
                n.note,
                n.scorecard_visible,
                n.created_at AS created_at_raw,
                COALESCE(NULLIF(TRIM(CONCAT_WS(' ', u.ad, u.soyad)), ''), u.email, CAST(n.personnel_id AS TEXT)) AS personnel_name,
                '' AS unit_name
            FROM performance_interim_notes_live n
            LEFT JOIN users u ON u.id = n.personnel_id
            {scope_where}
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT 300
        """,
            # Bind scope_ids only when the SQL uses it: the admin branch has no
            # :scope_ids placeholder and binding it raised "This text() construct
            # doesn't define a bound parameter named 'scope_ids'" (HTTP 500).
            {"scope_ids": scoped_ids} if scope_where else None,
            expanding=("scope_ids",) if scope_where else (),
        )

    # BYS360 DEFECT FS (Final Sweep A1-04): TO_CHAR(...) is PostgreSQL-only
    # (no SQLite version has it, unlike CONCAT_WS which SQLite 3.44+ added).
    # It previously failed on SQLite and was silently swallowed by _rows()'s
    # broad except, rendering an empty note list with no visible error.
    # Formatting the raw datetime in Python after fetch works identically on
    # both dialects and preserves the exact "DD.MM.YYYY HH24:MI" display
    # format already used elsewhere in this codebase (e.g. app/api/mobile/
    # shared.py, app/admin/ai_routes.py).
    def _format_created_at_label(raw_value):
        if raw_value is None:
            return None
        if isinstance(raw_value, str):
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                try:
                    raw_value = datetime.strptime(raw_value, fmt)
                    break
                except ValueError:
                    continue
            else:
                return raw_value
        try:
            return raw_value.strftime("%d.%m.%Y %H:%M")
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            return None

    note_items = []
    for row in note_items_raw:
        item = dict(row)
        item["created_at_label"] = _format_created_at_label(item.pop("created_at_raw", None))
        item["note_type_label"] = _type_label(item.get("note_type"))
        note_items.append(item)

    total = len(note_items)
    positive = sum(1 for n in note_items if (n.get("note_type") or "").lower() in ["olumlu", "basari", "başarı"])
    negative = sum(1 for n in note_items if (n.get("note_type") or "").lower() == "olumsuz")
    development = sum(1 for n in note_items if (n.get("note_type") or "").lower() in ["gelisim", "gelişim"])
    visible_on_scoring = sum(1 for n in note_items if bool(n.get("scorecard_visible")))

    page_summary = {
        "total": total,
        "positive": positive,
        "negative": negative,
        "development": development,
        "visible_on_scoring": visible_on_scoring,
    }

    return render_template(
        "performance/interim_notes_manager.html",
        page_summary=page_summary,
        note_items=note_items,
        interim_notes=note_items,
        notes=note_items,
        personnel_options=personnel_options,
        period_options=period_options,
        # BYS360_STUB_AI_V60_INTERIM_RENDER_PANEL
        ai_stub_panel=build_interim_notes_ai_panel(page_summary=page_summary, note_items=note_items),
        interim_notes_ai_panel=build_interim_notes_ai_panel(page_summary=page_summary, note_items=note_items),
        # /BYS360_STUB_AI_V60_INTERIM_RENDER_PANEL
    )

@main_bp.route('/performance/interim-notes/create', methods=['POST'], endpoint='performance_interim_notes_create')
@main_bp.route('/performans/donem-ici-notlar/kaydet', methods=['POST'], endpoint='performance_interim_notes_create_tr')
@login_required
def performance_interim_notes_create():
    if not _can_access():
        return _access_denied()
    people = _people()
    emp = _int(request.form.get('employee_id'))
    per = _int(request.form.get('period_id'))
    ntype = (request.form.get('note_type') or 'genel_gozlem').strip()
    title = (request.form.get('title') or NOTE_LABELS.get(ntype, 'Dönem İçi Not')).strip()[:255]
    body = (request.form.get('note') or request.form.get('note_text') or '').strip()
    include = bool(request.form.get('include_in_scorecard') or request.form.get('visible_on_scorecard'))
    if ntype not in NOTE_LABELS:
        ntype = 'genel_gozlem'
    if not _allowed_employee(emp, people):
        flash('Bu personel için dönem içi not ekleme yetkiniz bulunmamaktadır.', 'warning')
        return redirect(url_for('main.performance_interim_notes'))
    if not body:
        flash('Dönem içi not açıklaması boş bırakılamaz.', 'warning')
        return redirect(url_for('main.performance_interim_notes', employee_id=emp or '', period_id=per or ''))
    try:
        db.session.execute(text("""
            INSERT INTO performance_interim_notes
            (employee_id, employee_user_id, period_id, manager_id, created_by, created_by_id, note_type, title, note_title, note, note_body, note_text, visibility_level, visibility_scope, remind_in_evaluation, remind_during_scoring, include_in_scorecard, visible_on_scorecard, is_active, occurred_at, created_at, updated_at)
            VALUES
            (:emp, :emp, :per, :uid, :uid, :uid, :ntype, :title, :title, :body, :body, :body, 'manager_scope', 'manager_scope', FALSE, FALSE, :inc, :inc, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {'emp': emp, 'per': per, 'uid': getattr(current_user, 'id', None), 'ntype': ntype, 'title': title, 'body': body, 'inc': include})
        db.session.commit()
        flash('Dönem içi not kaydedildi. Bu kayıt puan üretmez; değerlendirme döneminde hatırlatma ve süreç hafızası için kullanılır.', 'success')
    except SQLAlchemyError as exc:
        logger.exception("Dönem içi not kaydedilirken veritabanı hatası: %s", exc)
        db.session.rollback()
        flash('Dönem içi not kaydedilemedi.', 'danger')
    return redirect(url_for('main.performance_interim_notes', employee_id=emp or '', period_id=per or ''))

# BYS360_PERFORMANCE_COMPLETION_PHASE10_INTERIM_GUIDANCE_BOUND
# Dönem içi not + gelişim önerisi bağı phase10_development_guidance_policy sözleşmesini kullanır.
