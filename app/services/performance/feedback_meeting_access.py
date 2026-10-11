"""One object rule for feedback meetings and feedback requests (#57).

Approved policy (HUMAN_POLICY_APPROVED, 2026-10-10):

* Normal staff see only their own feedback requests and the records they are entitled to.
* A manager role alone does not reveal other people's meeting notes or requests.
* Only explicitly authorised managers create meetings.
* Being a party to the meeting, or a defined duty relation, grants access.
* List, detail, search, export and report use the same object check.

Rules implemented here:

* A meeting (``feedback_meetings`` with its preparation, after-meeting note and action plans) is
  visible and editable only to its parties: the employee and the meeting's manager. No role, the
  technical administrator and ``admin`` included, widens that.
* A feedback request is visible to its employee and to the managers the request names
  (``level_1/2/3_manager_id``), the request's own duty relation.
* A meeting is created only by a manager role that also has a duty relation to the employee: one
  of the request's named managers, or (person and period form) a hierarchy manager of the employee
  (``users.yonetici_sicil`` / ``ikinci_yonetici_sicil`` / ``ucuncu_yonetici_sicil``).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

logger = logging.getLogger(__name__)

REQUEST_MANAGER_COLUMNS = ("level_1_manager_id", "level_2_manager_id", "level_3_manager_id")
HIERARCHY_SICIL_COLUMNS = ("yonetici_sicil", "ikinci_yonetici_sicil", "ucuncu_yonetici_sicil")
_NONE = "1=0"


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except SQLAlchemyError:
        logger.exception("BYS360 #57 guarded exception | file=app/services/performance/feedback_meeting_access.py | columns")
        return set()


def _user_id(user_id: Any) -> int:
    try:
        return int(user_id or 0)
    except (TypeError, ValueError):
        return 0


def meeting_party_where(alias: str, user_id: Any, *, param: str = "fma_party_uid") -> tuple[str, dict[str, Any]]:
    """SQL condition: the user is the meeting's employee or its manager."""
    uid = _user_id(user_id)
    if not uid:
        return _NONE, {}
    return f"({alias}.employee_id = :{param} OR {alias}.manager_id = :{param})", {param: uid}


def is_meeting_party(meeting: dict[str, Any] | None, user_id: Any) -> bool:
    uid = _user_id(user_id)
    if not uid or not meeting:
        return False
    return uid in {_user_id(meeting.get("employee_id")), _user_id(meeting.get("manager_id"))}


def request_manager_where(alias: str, user_id: Any, *, param: str = "fma_req_uid") -> tuple[str, dict[str, Any]]:
    """SQL condition: the user is one of the managers the feedback request names."""
    uid = _user_id(user_id)
    cols = [c for c in REQUEST_MANAGER_COLUMNS if c in _columns("feedback_requests")]
    if not uid or not cols:
        return _NONE, {}
    return "(" + " OR ".join(f"{alias}.{c} = :{param}" for c in cols) + ")", {param: uid}


def is_request_manager(request_row: dict[str, Any] | None, user_id: Any) -> bool:
    uid = _user_id(user_id)
    if not uid or not request_row:
        return False
    return uid in {_user_id(request_row.get(c)) for c in REQUEST_MANAGER_COLUMNS}


def _user_sicil(user_id: Any) -> str:
    uid = _user_id(user_id)
    if not uid or "sicil_no" not in _columns("users"):
        return ""
    try:
        value = db.session.execute(text("SELECT sicil_no FROM users WHERE id = :uid"), {"uid": uid}).scalar()
    except SQLAlchemyError:
        logger.exception("BYS360 #57 guarded exception | file=app/services/performance/feedback_meeting_access.py | sicil")
        return ""
    return str(value or "").strip()


def duty_report_where(alias: str, manager_user_id: Any, *, param: str = "fma_mgr_sicil") -> tuple[str, dict[str, Any]]:
    """SQL condition on ``users``: the row is a hierarchy report (level 1-3) of the manager."""
    sicil = _user_sicil(manager_user_id)
    cols = [c for c in HIERARCHY_SICIL_COLUMNS if c in _columns("users")]
    if not sicil or not cols:
        return _NONE, {}
    return "(" + " OR ".join(f"{alias}.{c} = :{param}" for c in cols) + ")", {param: sicil}


def is_duty_manager_of(manager_user_id: Any, employee_id: Any) -> bool:
    eid = _user_id(employee_id)
    if not eid or eid == _user_id(manager_user_id):
        return False
    where, params = duty_report_where("u", manager_user_id)
    if where == _NONE:
        return False
    params["fma_emp_id"] = eid
    try:
        found = db.session.execute(text(f"SELECT 1 FROM users u WHERE u.id = :fma_emp_id AND {where}"), params).scalar()
    except SQLAlchemyError:
        logger.exception("BYS360 #57 guarded exception | file=app/services/performance/feedback_meeting_access.py | duty")
        return False
    return bool(found)
