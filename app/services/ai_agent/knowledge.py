from __future__ import annotations

import re
from typing import Any

from app.services import runtime_schema


def _ag5_get_db():
    try:
        from app.extensions import db
        return db
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/knowledge.py)")
    try:
        from app import db
        return db
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _ag5_text():
    try:
        from sqlalchemy import text
        return text
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _ag5_normalize(value: Any) -> str:
    value = str(value or '').strip().lower()
    return (value.replace('ı','i').replace('İ','i').replace('ş','s').replace('ğ','g')
                 .replace('ü','u').replace('ö','o').replace('ç','c'))


def _ag5_tokens(value: str) -> set[str]:
    return {t for t in re.split(r'[^a-z0-9]+', _ag5_normalize(value)) if len(t) >= 3}


def can_manage_ai_knowledge(user: Any) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    values = []
    for attr in ('role','role_name','user_role','profile','authority_role'):
        raw = getattr(user, attr, None)
        if raw:
            values.append(raw)
    role_obj = getattr(user, 'role_obj', None) or getattr(user, 'role_record', None)
    if role_obj is not None:
        for attr in ('name','code','title'):
            raw = getattr(role_obj, attr, None)
            if raw:
                values.append(raw)
    normalized = {_ag5_normalize(v) for v in values}
    allowed = {'admin','administrator','sistem yoneticisi','sistem_yoneticisi','super_admin','baskan','başkan','ust yonetim','ust_yonetim','ai yoneticisi','ai_yoneticisi'}
    return bool(normalized & allowed)


def provision_knowledge_table() -> None:
    """Create the knowledge table (explicit maintenance only: flask runtime-schema provision)."""
    db = _ag5_get_db()
    text = _ag5_text()
    if db is None or text is None:
        return
    # BYS360 DEFECT AR: sabit "id SERIAL PRIMARY KEY" hicbir dialect dali
    # olmadan kullaniliyordu -- SQLite'ta bu, eklenen her satirin id'sinin
    # kalici NULL kalmasina yol acardi (bkz. interim_notes_runtime.py::_id_sql()
    # ayni kusur sinifi).
    try:
        dialect = db.session.get_bind().dialect.name
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        dialect = "postgresql"
    id_sql = "id INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == "sqlite" else "id SERIAL PRIMARY KEY"
    db.session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS ai_agent_knowledge_entries (
            {id_sql},
            title VARCHAR(240) NOT NULL,
            question_patterns TEXT NOT NULL,
            answer TEXT NOT NULL,
            tags VARCHAR(500),
            audience VARCHAR(80) DEFAULT 'all',
            priority INTEGER DEFAULT 50,
            is_active BOOLEAN DEFAULT TRUE,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    db.session.commit()


KNOWLEDGE_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="ai_agent.knowledge_entries",
    tables=("ai_agent_knowledge_entries",),
    provision=provision_knowledge_table,
))


def init_knowledge_table() -> None:
    """Verify the knowledge table exists; never creates it (see app.services.runtime_schema)."""
    runtime_schema.require(KNOWLEDGE_SCHEMA)


def list_knowledge_entries(include_inactive: bool = True) -> list[dict[str, Any]]:
    init_knowledge_table()
    db = _ag5_get_db()
    text = _ag5_text()
    if db is None or text is None:
        return []
    where = '' if include_inactive else 'WHERE is_active = TRUE'
    rows = db.session.execute(text(f"""
        SELECT id, title, question_patterns, answer, tags, audience, priority,
               is_active, created_by, created_at, updated_at
        FROM ai_agent_knowledge_entries
        {where}
        ORDER BY is_active DESC, priority DESC, updated_at DESC, id DESC
    """)).mappings().all()
    return [dict(r) for r in rows]


def create_knowledge_entry(*, title: str, question_patterns: str, answer: str, tags: str = '', audience: str = 'all', priority: int = 50, created_by: int | None = None) -> int | None:
    init_knowledge_table()
    db = _ag5_get_db()
    text = _ag5_text()
    if db is None or text is None:
        return None
    title = str(title or '').strip()
    question_patterns = str(question_patterns or '').strip()
    answer = str(answer or '').strip()
    tags = str(tags or '').strip()
    audience = str(audience or 'all').strip() or 'all'
    if not title or not question_patterns or not answer:
        raise ValueError('Başlık, soru kalıpları ve cevap metni zorunludur.')
    try:
        priority = int(priority)
    except Exception:
        priority = 50
    row = db.session.execute(text("""
        INSERT INTO ai_agent_knowledge_entries
        (title, question_patterns, answer, tags, audience, priority, is_active, created_by, created_at, updated_at)
        VALUES (:title, :question_patterns, :answer, :tags, :audience, :priority, TRUE, :created_by, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
    """), {'title': title, 'question_patterns': question_patterns, 'answer': answer, 'tags': tags, 'audience': audience, 'priority': priority, 'created_by': created_by}).first()
    db.session.commit()
    return int(row[0]) if row else None


def toggle_knowledge_entry(entry_id: int) -> None:
    init_knowledge_table()
    db = _ag5_get_db()
    text = _ag5_text()
    if db is None or text is None:
        return
    db.session.execute(text('UPDATE ai_agent_knowledge_entries SET is_active = NOT is_active, updated_at = CURRENT_TIMESTAMP WHERE id = :id'), {'id': int(entry_id)})
    db.session.commit()


def delete_knowledge_entry(entry_id: int) -> None:
    init_knowledge_table()
    db = _ag5_get_db()
    text = _ag5_text()
    if db is None or text is None:
        return
    db.session.execute(text('DELETE FROM ai_agent_knowledge_entries WHERE id = :id'), {'id': int(entry_id)})
    db.session.commit()


def _score_entry(question: str, entry: dict[str, Any]) -> int:
    q_norm = _ag5_normalize(question)
    q_tokens = _ag5_tokens(question)
    score = 0
    patterns = [p.strip() for p in re.split(r'[\n;|]+', str(entry.get('question_patterns') or '')) if p.strip()]
    for pattern in patterns:
        p_norm = _ag5_normalize(pattern)
        if p_norm == q_norm:
            score += 120
        elif p_norm and p_norm in q_norm:
            score += 85
        else:
            overlap = q_tokens & _ag5_tokens(pattern)
            score += len(overlap) * 14
            if len(overlap) >= 2:
                score += 12
    score += len(q_tokens & _ag5_tokens(entry.get('title') or '')) * 8
    score += len(q_tokens & _ag5_tokens(entry.get('tags') or '')) * 6
    try:
        score += max(0, min(int(entry.get('priority') or 0), 100)) // 10
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/knowledge.py)")
    return score


def search_knowledge_answer(question: str, *, audience: str = 'all', limit: int = 3) -> list[dict[str, Any]]:
    if not str(question or '').strip():
        return []
    scored = []
    for entry in list_knowledge_entries(include_inactive=False):
        score = _score_entry(question, entry)
        if score >= 24:
            enriched = dict(entry)
            enriched['match_score'] = score
            scored.append((score, enriched))
    scored.sort(key=lambda item: (item[0], int(item[1].get('priority') or 0), int(item[1].get('id') or 0)), reverse=True)
    return [entry for _, entry in scored[:limit]]


def build_knowledge_reply(user: Any, question: str) -> dict[str, Any] | None:
    matches = search_knowledge_answer(question, audience='all', limit=1)
    if not matches:
        return None
    entry = matches[0]
    return {
        'ok': True,
        'version': 'AG-5 Öğretilebilir Bilgi Bankası V1',
        'mode': 'Öğretilmiş kurumsal bilgi',
        'intent': 'learned_knowledge',
        'answer': entry.get('answer') or '',
        'knowledge_source': {'id': entry.get('id'), 'title': entry.get('title'), 'tags': entry.get('tags'), 'match_score': entry.get('match_score')},
        'actions': [{'label':'BYS360 Asistan Paneli','title':'BYS360 Asistan Paneli','route':'/ai-agent/panel','url':'/ai-agent/panel','description':'Asistan paneline dön'}],
        'notice': "Bu cevap BYS360 Asistan Öğretim Merkezi'nde tanımlanan kurumsal bilgiye göre hazırlanmıştır.",
        'security_notice': 'Asistan idari karar vermez, puan değiştirmez ve yetki dışı veri göstermez.'
    }
