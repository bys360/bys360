from __future__ import annotations

import logging
from typing import Any

from flask import abort, render_template, render_template_string, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text

from app.extensions import db
from app.routes import main
from app.security.sql_identifiers import (
    quote_sql_identifier,
    validate_sql_identifier,
)

logger = logging.getLogger(__name__)

PHASE12_PRESIDENT_APPROVALS_MENU_CARD_ACCESS = True


def _table_exists(table_name: str) -> bool:
    """BYS360 DEFECT AL: raw PostgreSQL-only ``information_schema.tables``
    query replaced with SQLAlchemy's ``inspect()``, which is dialect-neutral
    by construction.

    BYS360 DEFECT AR: previously raised straight through on any inspect()
    failure, unlike ~20 other table-existence helpers doing the identical
    conceptual check elsewhere in this codebase, which all log and return
    False. Aligned to that dominant convention."""
    try:
        return bool(inspect(db.engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 president low score card _table_exists guvenli fallback | table=%s", table_name)
        return False


def _columns(table_name: str) -> set[str]:
    if not _table_exists(table_name):
        return set()
    return {str(column["name"]) for column in inspect(db.engine).get_columns(table_name)}


def _display_name(user_id: Any) -> str:
    if not user_id or not _table_exists("users"):
        return "-"
    cols = _columns("users")
    select_parts = ["id"] + [c for c in ("full_name", "ad", "soyad", "name", "username", "email", "sicil_no") if c in cols]
    try:
        row = db.session.execute(
            text(f"SELECT {', '.join(select_parts)} FROM users WHERE id = :uid LIMIT 1"),
            {"uid": user_id},
        ).mappings().first()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        db.session.rollback()
        row = None
    if not row:
        return f"Personel #{user_id}"
    if row.get("full_name"):
        return str(row.get("full_name"))
    name = " ".join(str(row.get(k) or "").strip() for k in ("ad", "soyad") if k in row).strip()
    if name:
        return name
    for key in ("name", "username", "email", "sicil_no"):
        if row.get(key):
            return str(row.get(key))
    return f"Personel #{user_id}"


def _normalize_role_value(value: Any) -> str:
    raw = str(value or "").strip().lower()
    tr_map = str.maketrans("çğıöşüâîûİ", "cgiosuaiui")
    return raw.translate(tr_map).replace(" ", "_").replace("-", "_")


def _can_view_president_approvals() -> bool:
    if not getattr(current_user, "is_authenticated", False):
        return False
    if bool(getattr(current_user, "is_admin", False)) or bool(getattr(current_user, "is_superuser", False)):
        return True
    # D3/R05: the job title (unvan/title) never grants president approvals.
    role_values = {
        _normalize_role_value(getattr(current_user, attr, ""))
        for attr in ("role", "role_name", "user_type")
    }
    return bool(role_values & {"admin", "super_admin", "system_admin", "sistem_yoneticisi", "baskan", "president"})


def _access_denied_response():
    return render_template(
        "errors/403.html",
        title="Erişim Yetkiniz Bulunmamaktadır",
        message="Bu sayfa yalnızca Başkan ve yetkili sistem yöneticileri tarafından görüntülenebilir.",
        back_url="/",
    ), 403


def _fetch_approvals(limit: int = 250) -> list[dict[str, Any]]:
    if not _table_exists("performance_president_approvals"):
        return []
    cols = _columns("performance_president_approvals")
    select_cols = ["id"] + [c for c in (
        "flow_id", "evaluation_id", "period_id", "employee_id", "score", "final_score",
        "president_user_id", "president_name", "status", "decision_status", "visible_status",
        "requested_at", "created_at", "updated_at", "process_version",
    ) if c in cols]
    order_col = "requested_at" if "requested_at" in cols else ("created_at" if "created_at" in cols else "id")
    rows = db.session.execute(
        text(f"SELECT {', '.join(select_cols)} FROM performance_president_approvals ORDER BY {order_col} DESC NULLS LAST, id DESC LIMIT :limit"),
        {"limit": limit},
    ).mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["employee_name"] = _display_name(item.get("employee_id"))
        item["score_display"] = item.get("final_score") if item.get("final_score") is not None else item.get("score")
        item["card_url"] = url_for("main.president_low_score_report_card", approval_id=item.get("id"))
        items.append(item)
    return items


def _fetch_one_approval(approval_id: int) -> dict[str, Any] | None:
    for row in _fetch_approvals(limit=1000):
        if int(row.get("id") or 0) == int(approval_id):
            return row
    return None


_HISTORY_TABLES = frozenset(
    {
        "performance_process_flow_steps",
        "performance_scoring_history",
    }
)

_HISTORY_SELECT_COLUMNS = (
    "id",
    "flow_id",
    "evaluation_id",
    "period_id",
    "employee_id",
    "event_key",
    "step_key",
    "step_code",
    "step_title",
    "description",
    "status",
    "owner_user_id",
    "actor_user_id",
    "scorer_user_id",
    "scorer_name",
    "manager_level",
    "score_value",
    "action_status",
    "next_stage",
    "next_owner_name",
    "tracking_label",
    "tracking_group",
    "action_at",
    "created_at",
)

_HISTORY_ORDER_COLUMNS = frozenset(
    {
        "action_at",
        "created_at",
        "id",
    }
)


def _fetch_history(
    table_name: str,
    evaluation_id: Any,
    order_col: str = "action_at",
) -> list[dict[str, Any]]:
    safe_table_name = validate_sql_identifier(
        table_name,
        allowed=_HISTORY_TABLES,
    )
    safe_requested_order = validate_sql_identifier(
        order_col,
        allowed=_HISTORY_ORDER_COLUMNS,
    )

    if (
        not evaluation_id
        or not _table_exists(
            safe_table_name
        )
    ):
        return []

    cols = _columns(
        safe_table_name
    )

    if "evaluation_id" not in cols:
        return []

    selected_columns = [
        column_name
        for column_name in _HISTORY_SELECT_COLUMNS
        if column_name in cols
    ]

    if not selected_columns:
        return []

    if safe_requested_order in cols:
        actual_order = safe_requested_order
    elif "created_at" in cols:
        actual_order = "created_at"
    elif "id" in cols:
        actual_order = "id"
    else:
        return []

    quoted_table_name = quote_sql_identifier(
        safe_table_name,
        dialect=db.engine.dialect,
        allowed=_HISTORY_TABLES,
    )

    quoted_columns = [
        quote_sql_identifier(
            column_name,
            dialect=db.engine.dialect,
            allowed=cols,
        )
        for column_name in selected_columns
    ]

    quoted_evaluation_id = quote_sql_identifier(
        "evaluation_id",
        dialect=db.engine.dialect,
        allowed=cols,
    )

    quoted_order = quote_sql_identifier(
        actual_order,
        dialect=db.engine.dialect,
        allowed=cols,
    )

    order_clause = (
        f"{quoted_order} ASC NULLS LAST"
    )

    if (
        "id" in cols
        and actual_order != "id"
    ):
        quoted_id = quote_sql_identifier(
            "id",
            dialect=db.engine.dialect,
            allowed=cols,
        )
        order_clause += (
            f", {quoted_id} ASC"
        )

    sql = (
        f"SELECT {', '.join(quoted_columns)} "
        f"FROM {quoted_table_name} "
        f"WHERE {quoted_evaluation_id} = :evaluation_id "
        f"ORDER BY {order_clause} "
        "LIMIT 200"
    )

    try:
        rows = db.session.execute(
            text(
                sql
            ),
            {
                "evaluation_id": (
                    evaluation_id
                )
            },
        ).mappings().all()

        return [
            dict(
                row
            )
            for row in rows
        ]
    except Exception:
        logger.exception(
            "BYS360 performans mod??l??nde "
            "beklenmeyen hata yakaland??."
        )
        db.session.rollback()
        return []


LIST_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-4 bys360-process-page bys360-president-approvals-page">
  <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-4">
    <div>
      <div class="text-uppercase small text-muted fw-semibold">Performans Yönetimi</div>
      <h1 class="h3 mb-1">Başkan Onayları</h1>
      <p class="text-muted mb-0">70 altı nihai performans sonuçları, Başkan onayı tamamlanmadan kesinleşmez.</p>
    </div>
    <a class="btn btn-outline-secondary btn-sm" href="/performans/surec-takibi">Süreç Takibi</a>
  </div>
  <div class="row g-3 mb-4">
    <div class="col-md-4"><div class="card shadow-sm border-0 rounded-4"><div class="card-body"><div class="text-muted small">Toplam Kayıt</div><div class="display-6 fw-bold">{{ approvals|length }}</div></div></div></div>
    <div class="col-md-4"><div class="card shadow-sm border-0 rounded-4"><div class="card-body"><div class="text-muted small">Onay Bekleyen</div><div class="display-6 fw-bold">{{ pending_count }}</div></div></div></div>
    <div class="col-md-4"><div class="card shadow-sm border-0 rounded-4"><div class="card-body"><div class="text-muted small">Karne Erişimi</div><div class="h5 mb-0">Başkan görüntüleyebilir</div></div></div></div>
  </div>
  <div class="card shadow-sm border-0 rounded-4">
    <div class="card-header bg-white border-0 pt-4 px-4"><h2 class="h5 mb-0">Başkan Onayı Kayıtları</h2></div>
    <div class="card-body p-0">
      {% if approvals %}<div class="table-responsive"><table class="table align-middle mb-0"><thead class="table-light"><tr><th>Personel</th><th>Dönem</th><th>Nihai Puan</th><th>Durum</th><th>Başkana Gönderim</th><th class="text-end">İşlem</th></tr></thead><tbody>
      {% for item in approvals %}<tr><td><div class="fw-semibold">{{ item.employee_name }}</div><div class="small text-muted">Personel ID: {{ item.employee_id or '-' }}</div></td><td>{{ item.period_id or '-' }}</td><td><span class="badge rounded-pill bg-danger-subtle text-danger border border-danger-subtle">{{ item.score_display or '-' }}</span></td><td>{{ item.status or item.decision_status or item.visible_status or 'Bekliyor' }}</td><td>{{ item.requested_at or item.created_at or '-' }}</td><td class="text-end"><a class="btn btn-sm btn-outline-danger" href="{{ item.card_url }}">Karneye Bak</a></td></tr>{% endfor %}
      </tbody></table></div>{% else %}<div class="p-4 text-muted">Başkan onayı kapsamında gösterilecek kayıt bulunmuyor.</div>{% endif %}
    </div>
  </div>
</div>
{% endblock %}
"""

CARD_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-4 bys360-process-page bys360-president-card-page">
  <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-4">
    <div><div class="text-uppercase small text-muted fw-semibold">Başkan Onayları</div><h1 class="h3 mb-1">70 Altı Performans Karnesi</h1><p class="text-muted mb-0">Bu görünüm Başkan onayı için hazırlanmış süreç ve puanlama özetidir.</p></div>
    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('main.president_low_score_approvals_center') }}">Başkan Onaylarına Dön</a>
  </div>
  <div class="row g-3 mb-4">
    <div class="col-lg-4"><div class="card shadow-sm border-0 rounded-4"><div class="card-body"><div class="text-muted small">Personel</div><div class="h5 mb-1">{{ approval.employee_name }}</div><div class="small text-muted">ID: {{ approval.employee_id or '-' }}</div></div></div></div>
    <div class="col-lg-4"><div class="card shadow-sm border-0 rounded-4"><div class="card-body"><div class="text-muted small">Nihai Puan</div><div class="display-6 fw-bold text-danger">{{ approval.score_display or '-' }}</div></div></div></div>
    <div class="col-lg-4"><div class="card shadow-sm border-0 rounded-4"><div class="card-body"><div class="text-muted small">Başkan Onayı</div><div class="h5 mb-1">{{ approval.status or approval.decision_status or approval.visible_status or 'Bekliyor' }}</div><div class="small text-muted">{{ approval.president_name or 'Başkan' }}</div></div></div></div>
  </div>
  <div class="row g-4">
    <div class="col-xl-6"><div class="card shadow-sm border-0 rounded-4 h-100"><div class="card-header bg-white border-0 pt-4 px-4"><h2 class="h5 mb-0">Puanlama Geçmişi</h2></div><div class="card-body">{% if scoring_history %}<div class="list-group list-group-flush">{% for row in scoring_history %}<div class="list-group-item px-0"><div class="d-flex justify-content-between gap-3"><div><div class="fw-semibold">{{ row.scorer_name or row.manager_level or 'Puanlama' }}</div><div class="small text-muted">{{ row.next_stage or row.action_status or '-' }}</div></div><div class="text-end"><div class="fw-bold">{{ row.score_value or '-' }}</div><div class="small text-muted">{{ row.action_at or row.created_at or '-' }}</div></div></div></div>{% endfor %}</div>{% else %}<div class="text-muted">Puanlama geçmişi kaydı bulunamadı.</div>{% endif %}</div></div></div>
    <div class="col-xl-6"><div class="card shadow-sm border-0 rounded-4 h-100"><div class="card-header bg-white border-0 pt-4 px-4"><h2 class="h5 mb-0">Süreç Akışı</h2></div><div class="card-body">{% if flow_steps %}{% for row in flow_steps %}<div class="mb-3 ps-3 border-start border-3"><div class="fw-semibold">{{ row.step_title or row.tracking_label or row.step_code or 'Süreç Adımı' }}</div><div class="small text-muted">{{ row.description or row.status or '-' }}</div><div class="small text-muted mt-1">{{ row.action_at or row.created_at or '-' }}</div></div>{% endfor %}{% else %}<div class="text-muted">Süreç akışı kaydı bulunamadı.</div>{% endif %}</div></div></div>
  </div>
</div>
{% endblock %}
"""

# BYS360 DEFECT AQ: bu URL, app/performance/__init__.py'nin import
# sırası nedeniyle her zaman process_engine_phase6_president_approvals_
# routes.py'deki performance_president_approvals tarafından
# karşılanıyordu (Flask/Werkzeug aynı statik yola birden fazla Rule
# eklenmesine izin verir; ilk kaydedilen, o yolu isteyen her HTTP
# metodunda kazanır). Bu fonksiyon hiçbir zaman gerçek bir istek
# karşılamadı -- kendi route kaydı, tespit edilen ve
# tests/quality/test_route_conflict_runtime_contract.py ile önceden
# kilitlenen çakışmayı kaldırmak için buradan çıkarıldı. Fonksiyonun
# kendisi ve yardımcıları (bazıları ayrı testlerle doğrudan test
# ediliyor) korunuyor.
@login_required
def president_low_score_approvals_center():
    if not _can_view_president_approvals():
        return _access_denied_response()
    approvals = _fetch_approvals()
    pending_count = sum(1 for item in approvals if str(item.get("status") or item.get("decision_status") or "pending").lower() in {"pending", "bekliyor", "president_pending"})
    return render_template_string(LIST_TEMPLATE, approvals=approvals, pending_count=pending_count)

@main.route("/performans/baskan-onaylari/<int:approval_id>/karne", methods=["GET"])
@login_required
def president_low_score_report_card(approval_id: int):
    if not _can_view_president_approvals():
        return _access_denied_response()
    approval = _fetch_one_approval(approval_id)
    if not approval:
        abort(404)
    evaluation_id = approval.get("evaluation_id")
    scoring_history = _fetch_history("performance_scoring_history", evaluation_id, "action_at")
    flow_steps = _fetch_history("performance_process_flow_steps", evaluation_id, "action_at")
    return render_template_string(CARD_TEMPLATE, approval=approval, scoring_history=scoring_history, flow_steps=flow_steps)
