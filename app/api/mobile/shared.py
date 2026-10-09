from __future__ import annotations

import hashlib

# BYS360_P1B_MOBILE_ROUTES_SHARED_SPLIT
# BYS360_MOBILE_V2_8_50_ASSISTANT_ASCII_GATEFIX
from datetime import (
    UTC,
    datetime,
    timezone,
)
from functools import wraps
from statistics import mean
from typing import Any

from flask import current_app, jsonify, make_response, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    AIRecommendation,
    AIRequestLog,
    EvaluationAssignment,
    FeedbackCampaign,
    MessageThread,
    MessageThreadParticipant,
    ModuleSetting,
    Notification,
    PerformanceEvaluation,
    PerformancePeriod,
    PerformancePresidentApproval,
    PerformanceResultSnapshot,
    RoleMenuDefault,
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
    SystemSetting,
    User,
)
from app.security import get_default_first_login_password
from app.services.bys360_notification_bridge import (
    notify_support_ticket_comment,
    notify_support_ticket_created,
)
from app.services.support_ticket_access import can_view_private_support_ticket

try:  # SP-1 KPI/Hedef motoru varsa gerçek hedef verisi buradan okunur.
    from app.modules.strategic_performance.models import PerformanceTarget
except Exception:  # pragma: no cover
    __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:53")
    PerformanceTarget = None  # type: ignore

from app.api.mobile.services.auth_service import (
    mobile_login_response,
    mobile_me_response,
    mobile_refresh_response,
)

from . import mobile_api_bp

_TOKEN_SALT = "bys360-mobile-api-v1"
_REFRESH_TOKEN_SALT = "bys360-mobile-refresh-v1"
_MOBILE_ACCESS_MAX_AGE_SECONDS = 60 * 60 * 24
_MOBILE_REFRESH_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
# B1-F1 (approved least-privilege policy, 2026-10-09): ik, personel_yonetimi and
# performans_yetkilisi are not institution-wide roles. They fall to the scoped
# branches (self / evaluator / owner); institution-wide personnel reads need the
# explicit personnel_read_all grant (app/services/personnel_read_grant.py).
# Decision 2: sistem_yoneticisi / system_admin are technical roles; technical
# administration does not open everyone's personal or performance data.
_GLOBAL_ROLES = {
    "admin",
    "başkan",
    "baskan",
    "baskanlik",
    "başkan_yardımcısı",
    "baskan_yardimcisi",
}


def _serializer() -> URLSafeTimedSerializer:
    secret = current_app.config.get("SECRET_KEY") or current_app.config.get("WTF_CSRF_SECRET_KEY") or "bys360-mobile-local-secret"
    return URLSafeTimedSerializer(str(secret))


def _role_key(user: User) -> str:
    return ((getattr(user, "role", "") or getattr(user, "role_label", "") or "").strip().lower())


def _authorization_role_key(user: User) -> str:
    # B1-F1 decision 3: authorization reads the stored role only; role_label is display text.
    return ((getattr(user, "role", "") or "").strip().lower())


def _has_global_scope(user: User) -> bool:
    return _authorization_role_key(user) in _GLOBAL_ROLES


def _full_name(user: User | None) -> str:
    if not user:
        return "BYS360 Kullanıcısı"
    return (getattr(user, "full_name", "") or f"{getattr(user, 'ad', '')} {getattr(user, 'soyad', '')}".strip() or "BYS360 Kullanıcısı")


def _safe_count(query: Any) -> int:
    try:
        return int(query.count())
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:102")
        return 0


def _safe_scalar(query: Any) -> int:
    try:
        value = query.scalar()
        return int(value or 0)
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:110")
        return 0


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:117")
        return default


def _item(id_: Any, title: str, subtitle: str = "", status: str = "", meta: str = "", value: str = "", progress: int | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(id_ or ""),
        "title": str(title or "Kayıt"),
        "subtitle": str(subtitle or ""),
        "status": str(status or ""),
        "meta": str(meta or ""),
        "value": str(value or ""),
    }
    if progress is not None:
        data["progress"] = max(0, min(100, _as_int(progress)))
    return data


def _metric(title: str, value: Any, subtitle: str = "", tone: str = "red", icon: str = "insights") -> dict[str, Any]:
    return {"title": title, "value": str(value), "subtitle": subtitle, "tone": tone, "icon": icon}


def _module_payload(metrics: list[dict[str, Any]], items: list[dict[str, Any]], source: str = "real_api"):
    return jsonify({"source": source, "metrics": metrics, "items": items})


def _dt_label(value: Any) -> str:
    if not value:
        return "-"
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:148")
        return str(value)


def _size_label(value: Any) -> str:
    size = _as_int(value, 0)
    if size <= 0:
        return "-"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, size // 1024)} KB"


def _clean_mobile_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = "\n".join(line.strip() for line in text.splitlines())
    text = "\n".join(line for line in text.splitlines() if line)
    return text[:limit]

def _generate_mobile_ticket_no(user: User) -> str:
    base = datetime.now(UTC).strftime("MOB-%Y%m%d-%H%M%S")
    suffix = int(getattr(user, "id", 0) or 0)
    candidate = f"{base}-{suffix}"
    counter = 2
    while SupportTicket.query.filter_by(ticket_no=candidate).first() is not None:
        candidate = f"{base}-{suffix}-{counter}"
        counter += 1
    return candidate


def _user_unit_name(user: User) -> str:
    return (
        getattr(user, "birim", None)
        or getattr(user, "unit_name", None)
        or getattr(user, "ust_birim", None)
        or "-"
    )


def _user_org_unit_id(user: User) -> int | None:
    for attr in ("organization_unit_id", "org_unit_id", "unit_id"):
        value = getattr(user, attr, None)
        try:
            if value:
                return int(value)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/api/mobile/routes.py:186)")
            continue
    return None

def _can_mobile_view_ticket(user: User, ticket: SupportTicket) -> bool:
    if int(getattr(ticket, "created_by_user_id", 0) or 0) == int(getattr(user, "id", 0) or 0):
        return True
    # Phase 13B private-ticket unit scope, shared with /support/* and Faz 3 (can_view_private_support_ticket).
    return _has_global_scope(user) and can_view_private_support_ticket(ticket, user)


def _can_mobile_reply_ticket(user: User, ticket: SupportTicket) -> bool:
    if not _can_mobile_view_ticket(user, ticket):
        return False
    status = (getattr(ticket, "status", "") or "").strip().lower()
    return status not in {"closed", "kapalı", "kapali", "resolved", "rejected"}


def _ticket_detail_payload(ticket: SupportTicket, user: User) -> dict[str, Any]:
    can_manage = _has_global_scope(user)
    messages = []
    for row in getattr(ticket, "messages", []) or []:
        if getattr(row, "is_internal", False) and not can_manage:
            continue
        messages.append({
            "id": str(getattr(row, "id", "") or ""),
            "author": _full_name(getattr(row, "user", None)),
            "message": getattr(row, "message", "") or "",
            "message_type": getattr(row, "message_type", "") or "comment",
            "is_internal": bool(getattr(row, "is_internal", False)),
            "created_at": _dt_label(getattr(row, "created_at", None)),
        })

    status_history = []
    for row in getattr(ticket, "status_history", []) or []:
        status_history.append({
            "id": str(getattr(row, "id", "") or ""),
            "changed_by": _full_name(getattr(row, "changed_by", None)),
            "old_status": getattr(row, "old_status", None) or "İlk kayıt",
            "new_status": getattr(row, "new_status", "") or "-",
            "note": getattr(row, "note", "") or "",
            "created_at": _dt_label(getattr(row, "created_at", None)),
        })

    attachments = []
    for row in getattr(ticket, "attachments", []) or []:
        attachments.append({
            "id": str(getattr(row, "id", "") or ""),
            "filename": getattr(row, "filename", "") or "Dosya",
            "size_label": _size_label(getattr(row, "file_size", None)),
            "mime_type": getattr(row, "mime_type", "") or "-",
            "attachment_type": getattr(row, "attachment_type", "") or "document",
        })

    assigned_to = getattr(ticket, "assigned_to", None)
    return {
        "source": "real_api",
        "can_manage": can_manage,
        "can_reply": _can_mobile_reply_ticket(user, ticket),
        "ticket": {
            "id": str(getattr(ticket, "id", "") or ""),
            "ticket_no": getattr(ticket, "ticket_no", "") or "-",
            "title": getattr(ticket, "title", "") or "Destek talebi",
            "description": getattr(ticket, "description", "") or "",
            "ticket_type": getattr(ticket, "ticket_type", "") or "-",
            "module_name": getattr(ticket, "module_name", "") or "Genel",
            "priority": getattr(ticket, "priority", "") or "normal",
            "priority_label": getattr(ticket, "priority_label", None) or getattr(ticket, "priority", "") or "-",
            "status": getattr(ticket, "status", "") or "open",
            "status_label": getattr(ticket, "status_label", None) or getattr(ticket, "status", "") or "-",
            "requester_name": getattr(ticket, "full_name_snapshot", "") or _full_name(getattr(ticket, "created_by", None)),
            "sicil_no": getattr(ticket, "sicil_no_snapshot", "") or "-",
            "unit_name": getattr(ticket, "unit_name_snapshot", "") or "-",
            "assigned_to": _full_name(assigned_to) if assigned_to else "Atanmadı",
            "created_at": _dt_label(getattr(ticket, "created_at", None)),
            "updated_at": _dt_label(getattr(ticket, "updated_at", None)),
            "elapsed_label": getattr(ticket, "elapsed_label", "-") or "-",
            "sub_status_text": getattr(ticket, "sub_status_text", "-") or "-",
            "resolution_text": getattr(ticket, "resolution_text", "-") or "-",
        },
        "messages": messages,
        "status_history": status_history,
        "attachments": attachments,
    }

_SURVEY_ACTIVE_STATUSES = {"active", "published", "yayinda", "yayında", "open", "aktif"}
_SURVEY_QUESTION_TYPE_LABELS = {
    "text": "Kısa metin",
    "single_choice": "Tek seçenek",
    "multiple_choice": "Çoklu seçenek",
    "rating_5": "1-5 puan",
    "rating_10": "1-10 puan",
    "yes_no": "Evet / Hayır",
}


def _survey_status_label(value: Any) -> str:
    raw = (str(value or "").strip().lower())
    mapping = {
        "active": "Yayında",
        "published": "Yayında",
        "yayinda": "Yayında",
        "yayında": "Yayında",
        "draft": "Taslak",
        "closed": "Kapalı",
        "kapali": "Kapalı",
        "kapalı": "Kapalı",
        "archived": "Arşiv",
    }
    return mapping.get(raw, str(value or "-") or "-")


def _survey_is_active(survey: Survey) -> bool:
    status = (getattr(survey, "status", "") or "").strip().lower()
    if status and status not in _SURVEY_ACTIVE_STATUSES:
        return False
    now = datetime.now(UTC).replace(tzinfo=None)
    start_at = getattr(survey, "start_at", None)
    end_at = getattr(survey, "end_at", None)
    if start_at and start_at > now:
        return False
    return not (end_at and end_at < now)


def _survey_user_target_values(user: User) -> dict[str, set[str]]:
    role_values = {str(getattr(user, "role", "") or "").strip(), str(getattr(user, "role_label", "") or "").strip()}
    unit_values = {
        str(getattr(user, "birim", "") or "").strip(),
        str(getattr(user, "ust_birim", "") or "").strip(),
        str(getattr(user, "unit_name", "") or "").strip(),
    }
    org_id = _user_org_unit_id(user)
    if org_id:
        unit_values.add(str(org_id))
    return {
        "user": {str(getattr(user, "id", "") or "").strip()},
        "role": {v for v in role_values if v},
        "unit": {v for v in unit_values if v},
    }


def _mobile_survey_assignments_for_user(user: User, survey_id: int | None = None) -> list[SurveyAssignment]:
    q = SurveyAssignment.query
    if survey_id is not None:
        q = q.filter(SurveyAssignment.survey_id == int(survey_id))
    rows = q.all()
    targets = _survey_user_target_values(user)
    matched: list[SurveyAssignment] = []
    for row in rows:
        target_type = (getattr(row, "target_type", "") or "").strip().lower()
        target_value = str(getattr(row, "target_value", "") or "").strip()
        if target_type == "all" or target_type == "user" and target_value in targets["user"] or target_type == "role" and target_value in targets["role"] or target_type == "unit" and target_value in targets["unit"]:
            matched.append(row)
    return matched


def _mobile_survey_assignment_for_user(user: User, survey: Survey) -> SurveyAssignment | None:
    rows = _mobile_survey_assignments_for_user(user, int(getattr(survey, "id", 0) or 0))
    return rows[0] if rows else None


def _mobile_survey_visible(user: User, survey: Survey) -> bool:
    if _has_global_scope(user):
        return True
    return _mobile_survey_assignment_for_user(user, survey) is not None


def _mobile_survey_anonymous_token(user: User, survey: Survey) -> str:
    secret = current_app.config.get("SECRET_KEY") or "bys360-mobile-local-secret"
    raw = f"mobile-survey:{getattr(survey, 'id', '')}:{getattr(user, 'id', '')}:{secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


def _mobile_survey_completed(user: User, survey: Survey) -> bool:
    try:
        q = SurveyResponse.query.filter(
            SurveyResponse.survey_id == int(getattr(survey, "id", 0) or 0),
            SurveyResponse.is_completed.is_(True),
        )
        if getattr(survey, "is_anonymous", False):
            q = q.filter(SurveyResponse.anonymous_token == _mobile_survey_anonymous_token(user, survey))
        else:
            q = q.filter(SurveyResponse.user_id == int(getattr(user, "id", 0) or 0))
        return q.first() is not None
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:391")
        return False


def _mobile_survey_options(question: SurveyQuestion) -> list[dict[str, Any]]:
    options = getattr(question, "options", None)
    try:
        rows = options.order_by(SurveyQuestionOption.sort_order.asc(), SurveyQuestionOption.id.asc()).all() if hasattr(options, "order_by") else list(options or [])  # type: ignore[union-attr]
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:399")
        rows = []
    return [
        {"id": str(getattr(option, "id", "") or ""), "text": getattr(option, "option_text", "") or "Seçenek"}
        for option in rows
    ]


def _mobile_survey_questions(survey: Survey) -> list[SurveyQuestion]:
    questions = getattr(survey, "questions", None)
    try:
        return questions.order_by(SurveyQuestion.sort_order.asc(), SurveyQuestion.id.asc()).all() if hasattr(questions, "order_by") else list(questions or [])  # type: ignore[union-attr]
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:411")
        return []


def _mobile_survey_question_payload(question: SurveyQuestion) -> dict[str, Any]:
    qtype = (getattr(question, "question_type", "") or "text").strip().lower() or "text"
    max_value = 5 if qtype == "rating_5" else 10 if qtype == "rating_10" else None
    return {
        "id": str(getattr(question, "id", "") or ""),
        "text": getattr(question, "question_text", "") or "Anket sorusu",
        "type": qtype,
        "type_label": _SURVEY_QUESTION_TYPE_LABELS.get(qtype, "Metin"),
        "is_required": bool(getattr(question, "is_required", True)),
        "sort_order": _as_int(getattr(question, "sort_order", 0), 0),
        "max_value": max_value,
        "options": _mobile_survey_options(question),
    }


def _mobile_survey_detail_payload(survey: Survey, user: User) -> dict[str, Any]:
    assignment = _mobile_survey_assignment_for_user(user, survey)
    completed = _mobile_survey_completed(user, survey)
    active = _survey_is_active(survey)
    questions = _mobile_survey_questions(survey)
    # Same assignment requirement as the mobile and web submit; visibility (read) is unchanged.
    can_submit = active and (bool(getattr(survey, "allow_multiple_submissions", False)) or not completed) and assignment is not None
    return {
        "source": "real_api",
        "can_submit": can_submit,
        "completed": completed,
        "assignment_id": str(getattr(assignment, "id", "") or "") if assignment else "",
        "survey": {
            "id": str(getattr(survey, "id", "") or ""),
            "title": getattr(survey, "title", "") or "Anket",
            "description": getattr(survey, "description", "") or "",
            "survey_type": getattr(survey, "survey_type", "") or "kurum_ici",
            "status": getattr(survey, "status", "") or "-",
            "status_label": _survey_status_label(getattr(survey, "status", "")),
            "is_anonymous": bool(getattr(survey, "is_anonymous", False)),
            "allow_multiple_submissions": bool(getattr(survey, "allow_multiple_submissions", False)),
            "start_at": _dt_label(getattr(survey, "start_at", None)),
            "end_at": _dt_label(getattr(survey, "end_at", None)),
            "question_count": len(questions),
        },
        "questions": [_mobile_survey_question_payload(q) for q in questions],
    }


def _mobile_survey_answer_value(raw: Any) -> Any:
    if isinstance(raw, str):
        return raw.strip()
    return raw


def _mobile_survey_validate_answers(survey: Survey, questions: list[SurveyQuestion], answers: dict[str, Any]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for question in questions:
        qid = str(getattr(question, "id", "") or "")
        qtype = (getattr(question, "question_type", "") or "text").strip().lower() or "text"
        label = (getattr(question, "question_text", "") or "Anket sorusu").strip()
        required = bool(getattr(question, "is_required", True))
        value = _mobile_survey_answer_value(answers.get(qid))
        options = _mobile_survey_options(question)
        option_ids = {int(opt["id"]) for opt in options if str(opt.get("id", "")).isdigit()}

        if qtype in {"single_choice", "yes_no"}:
            selected = None
            try:
                if value not in (None, ""):
                    selected = int(value)
            except Exception:
                __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:480")
                selected = None
            if required and not selected:
                raise ValueError(f'"{label}" sorusu zorunludur.')
            if selected and selected not in option_ids:
                raise ValueError(f'"{label}" için geçersiz seçenek gönderildi.')
            if selected:
                prepared.append({"question_id": int(qid), "selected_option_id": selected})
        elif qtype == "multiple_choice":
            raw_values = value if isinstance(value, list) else ([] if value in (None, "") else [value])
            selected_ids: list[int] = []
            for item in raw_values:
                try:
                    selected_ids.append(int(item))
                except Exception:
                    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/api/mobile/routes.py:487)")
                    continue
            selected_ids = sorted(set(selected_ids))
            if required and not selected_ids:
                raise ValueError(f'"{label}" sorusu zorunludur.')
            invalid = [sid for sid in selected_ids if sid not in option_ids]
            if invalid:
                raise ValueError(f'"{label}" için geçersiz seçenek gönderildi.')
            for sid in selected_ids:
                prepared.append({"question_id": int(qid), "selected_option_id": sid})
        elif qtype in {"rating_5", "rating_10"}:
            number = None
            try:
                if value not in (None, ""):
                    number = float(value)
            except Exception:
                __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/api/mobile/shared.py:510")
                number = None
            max_value = 5 if qtype == "rating_5" else 10
            if required and number is None:
                raise ValueError(f'"{label}" sorusu zorunludur.')
            if number is not None and not (0 <= number <= max_value):
                raise ValueError(f'"{label}" için puan aralığı 0 ile {max_value} arasında olmalıdır.')
            if number is not None:
                prepared.append({"question_id": int(qid), "answer_number": number})
        else:
            text = str(value or "").strip()
            if required and not text:
                raise ValueError(f'"{label}" sorusu zorunludur.')
            prepared.append({"question_id": int(qid), "answer_text": text or None})
    return prepared

# BYS360_MOBILE_TOKEN_SECURITY_STAMP: web oturumu gibi (User.get_id / load_user)
# token'a hesabin security_stamp degeri gomulur; parola sifirlama stamp'i
# degistirdiginde eski mobil access/refresh token'lari reddedilir. Stamp
# tasimayan eski token'lar web'deki eski cerezler gibi kabul edilir ve kendi
# sureleri (24 saat / 30 gun) dolunca biter.
def _token_stamp_matches(data: dict, user: User) -> bool:
    stamp = data.get("stamp")
    return stamp is None or stamp == (getattr(user, "security_stamp", None) or "")


def _issue_token(user: User, max_age: int | None = None) -> str:
    return _serializer().dumps(
        {"uid": user.id, "kind": "access", "stamp": getattr(user, "security_stamp", None) or ""},
        salt=_TOKEN_SALT,
    )


def _issue_refresh_token(user: User) -> str:
    return _serializer().dumps(
        {"uid": user.id, "kind": "refresh", "stamp": getattr(user, "security_stamp", None) or ""},
        salt=_REFRESH_TOKEN_SALT,
    )


def _load_refresh_token_user(refresh_token: str | None) -> User | None:
    token = (refresh_token or "").strip()
    if not token:
        return None
    try:
        data = _serializer().loads(token, salt=_REFRESH_TOKEN_SALT, max_age=_MOBILE_REFRESH_MAX_AGE_SECONDS)
        if data.get("kind") not in {None, "refresh"}:
            return None
        user_id = int(data.get("uid"))
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
    user = db.session.get(User, user_id)
    if not user or not getattr(user, "is_active", True) or not _token_stamp_matches(data, user):
        return None
    return user


def _load_token_user() -> User | None:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        data = _serializer().loads(token, salt=_TOKEN_SALT, max_age=_MOBILE_ACCESS_MAX_AGE_SECONDS)
        user_id = int(data.get("uid"))
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
    user = db.session.get(User, user_id)
    if not user or not getattr(user, "is_active", True) or not _token_stamp_matches(data, user):
        return None
    return user


def require_mobile_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = _load_token_user()
        if not user:
            return jsonify({"message": "Mobil oturum bulunamadı veya süresi doldu."}), 401
        return fn(user, *args, **kwargs)
    return wrapper

# BYS360_MOBILE_V2_8_57_IOS_SAFARI_WEB_PREVIEW_CORS
def _bys360_mobile_preview_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return False
    origin = origin.strip()
    allowed_prefixes = (
        "http://localhost",
        "http://127.0.0.1",
        "http://192.168.",
        "http://10.",
        "http://172.16.", "http://172.17.", "http://172.18.", "http://172.19.",
        "http://172.20.", "http://172.21.", "http://172.22.", "http://172.23.",
        "http://172.24.", "http://172.25.", "http://172.26.", "http://172.27.",
        "http://172.28.", "http://172.29.", "http://172.30.", "http://172.31.",
    )
    return origin.startswith(allowed_prefixes)


def _bys360_mobile_preview_apply_cors(response):
    origin = request.headers.get("Origin")
    if _bys360_mobile_preview_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-Requested-With, X-CSRFToken"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["Vary"] = "Origin"
    return response


@mobile_api_bp.before_request
def _bys360_mobile_preview_preflight():
    if request.method == "OPTIONS":
        return _bys360_mobile_preview_apply_cors(make_response("", 204))
    return None


@mobile_api_bp.after_request
def _bys360_mobile_preview_after_request(response):
    return _bys360_mobile_preview_apply_cors(response)


# BYS360 P11-B2: mobile_health utility route app/api/mobile/utility_routes.py modülüne taşındı.


# Import-star bu dosyada bilinçli kullanılır: routes.py içinde eski yardımcı isimlerin
# tamamı aynı adlarla görünür kalır; URL/endpoint sözleşmesi değişmez.
__all__ = [
    "annotations",
    "hashlib",
    "UTC",
    "datetime",
    "timezone",
    "wraps",
    "mean",
    "Any",
    "current_app",
    "jsonify",
    "make_response",
    "request",
    "BadSignature",
    "SignatureExpired",
    "URLSafeTimedSerializer",
    "func",
    "or_",
    "IntegrityError",
    "db",
    "AIRecommendation",
    "AIRequestLog",
    "EvaluationAssignment",
    "FeedbackCampaign",
    "MessageThread",
    "MessageThreadParticipant",
    "ModuleSetting",
    "Notification",
    "PerformanceEvaluation",
    "PerformancePeriod",
    "PerformancePresidentApproval",
    "PerformanceResultSnapshot",
    "RoleMenuDefault",
    "SupportTicket",
    "SupportTicketAttachment",
    "SupportTicketMessage",
    "SupportTicketStatusHistory",
    "Survey",
    "SurveyAnswer",
    "SurveyAssignment",
    "SurveyQuestion",
    "SurveyQuestionOption",
    "SurveyResponse",
    "SystemSetting",
    "User",
    "get_default_first_login_password",
    "notify_support_ticket_comment",
    "notify_support_ticket_created",
    "PerformanceTarget",
    "mobile_login_response",
    "mobile_me_response",
    "mobile_refresh_response",
    "mobile_api_bp",
    "_TOKEN_SALT",
    "_REFRESH_TOKEN_SALT",
    "_MOBILE_ACCESS_MAX_AGE_SECONDS",
    "_MOBILE_REFRESH_MAX_AGE_SECONDS",
    "_GLOBAL_ROLES",
    "_serializer",
    "_role_key",
    "_authorization_role_key",
    "_has_global_scope",
    "_full_name",
    "_safe_count",
    "_safe_scalar",
    "_as_int",
    "_item",
    "_metric",
    "_module_payload",
    "_dt_label",
    "_size_label",
    "_clean_mobile_text",
    "_generate_mobile_ticket_no",
    "_user_unit_name",
    "_user_org_unit_id",
    "_can_mobile_view_ticket",
    "_can_mobile_reply_ticket",
    "_ticket_detail_payload",
    "_SURVEY_ACTIVE_STATUSES",
    "_SURVEY_QUESTION_TYPE_LABELS",
    "_survey_status_label",
    "_survey_is_active",
    "_survey_user_target_values",
    "_mobile_survey_assignments_for_user",
    "_mobile_survey_assignment_for_user",
    "_mobile_survey_visible",
    "_mobile_survey_anonymous_token",
    "_mobile_survey_completed",
    "_mobile_survey_options",
    "_mobile_survey_questions",
    "_mobile_survey_question_payload",
    "_mobile_survey_detail_payload",
    "_mobile_survey_answer_value",
    "_mobile_survey_validate_answers",
    "_issue_token",
    "_issue_refresh_token",
    "_load_refresh_token_user",
    "_load_token_user",
    "require_mobile_user",
    "_bys360_mobile_preview_allowed_origin",
    "_bys360_mobile_preview_apply_cors",
    "_bys360_mobile_preview_preflight",
    "_bys360_mobile_preview_after_request",
]
