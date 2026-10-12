"""Contract K5 F4: support ticket counters and statistics follow the ticket access rule.

Owner decision (2026-10-12, F4): technical management grants no right to see how many support
tickets exist institution-wide. Every counter, status breakdown, risk score, stored metric, report
and export uses the same object scope as the tickets themselves: ``support_ticket_visibility_clause``
(own tickets, plus every ticket the private-ticket rule opens to an explicit ``support_all`` holder).

Before: ``/settings-center/support`` counted every ticket; the Faz 5 health and retention screens,
the Faz 8/9/9A/9C/9D readiness, release and stabilization snapshots and their Markdown/JSON exports
counted (and the Faz 9C JSON export listed) every ticket; Faz 4 stored institution-wide daily support
metrics and showed them as a trend to every ``reports`` holder; a stored executive report showed its
author's support figures to every reader; the main dashboard gave every role in ``GLOBAL_ROLES``
(including ``sistem_yoneticisi``) the institution-wide count and a manager the count of the team's
tickets.
"""
from __future__ import annotations

import json
import re
import secrets
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = f"K5qF4-{secrets.token_hex(8)}-aA1!"  # synthetic test users only; generated per run
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "k5q_f4_counters" / "dbs"
OTHER_TICKETS = 9  # created by "creator" in Birim-A; one of them private
OLD_TICKETS = 3  # of those, older than one year

# key -> (role, birim, explicit support_all grant, own ticket)
USERS = {
    "creator": ("personel", "Birim-A", False, False),
    "sysadm": ("sistem_yoneticisi", "Birim-S", False, True),
    "baskan": ("baskan", "Birim-C", False, False),
    "colleague": ("personel", "Birim-A", False, False),
    "holder": ("personel", "Birim-A", True, False),
    "admin_holder": ("admin", "Birim-Y", True, False),
}
# Expected open-ticket count per viewer under the access rule.
EXPECTED = {"sysadm": 1, "baskan": 0, "colleague": 0, "holder": OTHER_TICKETS, "admin_holder": OTHER_TICKETS + 1}
MENUS = ("settings_center_support", "settings", "reports", "dashboard")
SUPPORT_CHECKS = {"Açık destek talebi", "Atanmamış destek", "Duran talepler"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-k5q-f4-counters", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "k5q-f4-counters-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri,
                            UPLOAD_FOLDER=str(tmp_path / "uploads"))
    from app.extensions import db
    from app.models import SupportTicket, User, UserMenuPermission
    from app.services import runtime_schema

    with flask_app.app_context():
        db.create_all()
        runtime_schema.provision_all()
        users = {}
        for index, (key, (role, birim, _grant, _own)) in enumerate(USERS.items()):
            user = User(sicil_no=f"K5QF{index:02d}", email=f"k5qf{index:02d}@example.gov.tr", ad="Sayac", soyad=key,
                        role=role, birim=birim, is_active=True, must_change_password=False,
                        must_set_security_question=False)
            user.set_password(PASSWORD)
            db.session.add(user)
            users[key] = user
        db.session.flush()
        for key, (_role, _birim, grant, _own) in USERS.items():
            for menu_key in MENUS + (("support_all",) if grant else ()):
                db.session.add(UserMenuPermission(user_id=users[key].id, menu_key=menu_key, is_visible=True,
                                                  source_type="user_override"))
        stale = datetime.utcnow() - timedelta(days=10)  # open, unassigned, stale and past every SLA target
        old = datetime.utcnow() - timedelta(days=400)
        ticket_nos = []
        for index in range(OTHER_TICKETS):
            created = old if index < OLD_TICKETS else stale
            ticket_no = f"K5QF-OTHER-{index:02d}"
            ticket_nos.append(ticket_no)
            db.session.add(SupportTicket(
                ticket_no=ticket_no, title=f"K5QF-BASLIK-{index:02d}", description="baskasinin talebi",
                ticket_type="other", module_name="test", status="open", priority="critical",
                created_by_user_id=users["creator"].id, is_private=index == 0, unit_name_snapshot="Birim-A",
                created_at=created, updated_at=created))
        db.session.add(SupportTicket(
            ticket_no="K5QF-OWN-SYS", title="K5QF-KENDI-TALEBI", description="kendi talebi", ticket_type="other",
            module_name="test", status="open", priority="normal", created_by_user_id=users["sysadm"].id,
            is_private=True, unit_name_snapshot="Birim-S", created_at=stale, updated_at=stale))
        db.session.commit()
        ids = {key: user.id for key, user in users.items()}
        sicils = {key: user.sicil_no for key, user in users.items()}

    return SimpleNamespace(app=flask_app, ids=ids, sicils=sicils, other_ticket_nos=ticket_nos)


def _web(env, who):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": env.sicils[who], "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), who
    return client


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _user(env, who):
    from app.extensions import db
    from app.models import User

    user = db.session.get(User, env.ids[who])
    assert user is not None
    return user


def _call(fn, viewer, *args):
    """Call a snapshot builder for ``viewer``; builders that cannot take a viewer count everything."""
    try:
        return fn(*args, viewer=viewer)
    except TypeError as exc:
        if "viewer" not in str(exc):
            raise
        return fn(*args)


SCOPED = ["sysadm", "baskan", "colleague", "holder", "admin_holder"]


# --- U1: /settings-center/support ------------------------------------------------------------


@pytest.mark.parametrize("who", SCOPED)
def test_settings_center_support_counts_only_the_viewers_tickets(env, who):
    response = _web(env, who).get("/settings-center/support")
    assert response.status_code == 200
    match = re.search(r"Toplam destek talebi\s+(\d+)", _text(response.get_data(as_text=True)))
    assert match is not None
    assert int(match.group(1)) == EXPECTED[who]


# --- U2/U3: Faz 5 health and retention ----------------------------------------------------------


@pytest.mark.parametrize("who", SCOPED)
def test_health_snapshot_counts_only_the_viewers_tickets(env, who):
    from app.services.communication_phase5_service import health_snapshot

    with env.app.app_context():
        snapshot = _call(health_snapshot, _user(env, who))
    assert snapshot["summary"]["tickets_open"] == EXPECTED[who]
    metrics = {item["check_name"]: item["metric"] for item in snapshot["synthetic_checks"]}
    assert metrics["Açık destek talebi"] == EXPECTED[who]
    assert metrics["Duran talepler"] == EXPECTED[who]
    assert snapshot["support_ops"]["summary"]["open_total"] == EXPECTED[who]


@pytest.mark.parametrize("who", SCOPED)
def test_retention_snapshot_counts_only_the_viewers_tickets(env, who):
    from app.services.communication_phase5_service import retention_snapshot

    with env.app.app_context():
        stats = {row["scope"]: row for row in _call(retention_snapshot, _user(env, who))["stats"]}
    old_in_scope = {"holder": OLD_TICKETS, "admin_holder": OLD_TICKETS}.get(who, 0)
    assert stats["support"]["total"] == EXPECTED[who]
    assert stats["support"]["older_than_1y"] == old_in_scope


# --- U4: stored health checks --------------------------------------------------------------------


def test_a_refreshed_health_check_stores_and_shows_no_support_metric(env):
    from app.models.communication_phase5_models import CommunicationOperationHealth
    from app.services.communication_phase5_service import health_snapshot, refresh_operation_health

    with env.app.app_context():
        refresh_operation_health(_user(env, "admin_holder"))
        stored = {row.check_name for row in CommunicationOperationHealth.query.all()}
        assert stored and not stored & SUPPORT_CHECKS
        recent = {row["check_name"] for row in _call(health_snapshot, _user(env, "sysadm"))["recent_checks"]}
    assert not recent & SUPPORT_CHECKS


def test_legacy_stored_support_health_rows_are_not_shown(env):
    from app.extensions import db
    from app.models.communication_phase5_models import CommunicationOperationHealth
    from app.services.communication_phase5_service import health_snapshot

    with env.app.app_context():
        db.session.add(CommunicationOperationHealth(check_name="Açık destek talebi", status="ok", metric_value="10",
                                                    details="eski kayit", checked_at=datetime.utcnow()))
        db.session.commit()
        recent = {row["check_name"] for row in _call(health_snapshot, _user(env, "sysadm"))["recent_checks"]}
    assert not recent & SUPPORT_CHECKS


# --- U5-U11: Faz 8 / 9 / 9A / 9C / 9D snapshots and exports -------------------------------------


@pytest.mark.parametrize("who", SCOPED)
def test_readiness_snapshot_counts_only_the_viewers_tickets(env, who):
    from app.services.communication_phase8_service import pilot_readiness_snapshot

    with env.app.app_context():
        snapshot = _call(pilot_readiness_snapshot, _user(env, who))
    assert snapshot["health"]["summary"]["tickets_open"] == EXPECTED[who]
    assert snapshot["escalation"]["summary"]["breach_count"] == EXPECTED[who]


@pytest.mark.parametrize("who", SCOPED)
def test_release_center_snapshot_counts_only_the_viewers_tickets(env, who):
    from app.services.communication_phase9_service import phase9_release_center_snapshot

    with env.app.app_context():
        snapshot = _call(phase9_release_center_snapshot, _user(env, who))
    assert snapshot["support_ops"]["summary"]["open_total"] == EXPECTED[who]
    assert snapshot["escalations"]["summary"]["breach_count"] == EXPECTED[who]
    assert snapshot["health"]["summary"]["tickets_open"] == EXPECTED[who]


@pytest.mark.parametrize("who", SCOPED)
def test_pilot_opening_and_stabilization_count_only_the_viewers_tickets(env, who):
    from app.services.communication_phase9c_service import phase9c_pilot_opening_snapshot
    from app.services.communication_phase9d_service import phase9d_stabilization_snapshot

    with env.app.app_context():
        pilot = _call(phase9c_pilot_opening_snapshot, _user(env, who))
        stabilization = _call(phase9d_stabilization_snapshot, _user(env, who))
    assert pilot["support"]["open_total"] == EXPECTED[who]
    assert pilot["support"]["stale_total"] == EXPECTED[who]
    assert stabilization["support"]["open_total"] == EXPECTED[who]
    assert stabilization["support"]["stale_total"] == EXPECTED[who]


@pytest.mark.parametrize("path", [
    "/communication/faz9/export/json", "/communication/faz9/export/md",
    "/communication/faz9c/export/json", "/communication/faz9c/export/md",
    "/communication/faz9d/export/json", "/communication/faz9d/export/md",
    "/communication/faz9a/export/md",
])
@pytest.mark.parametrize("who", ["sysadm", "baskan", "colleague"])
def test_exports_carry_no_ticket_outside_the_viewers_scope(env, path, who):
    response = _web(env, who).get(path)
    assert response.status_code == 200, (path, response.status_code)
    body = response.get_data(as_text=True)
    assert [no for no in env.other_ticket_nos if no in body] == []
    assert "K5QF-BASLIK" not in body


def test_json_exports_count_only_the_viewers_tickets(env):
    client = _web(env, "sysadm")
    pilot = json.loads(client.get("/communication/faz9c/export/json").get_data(as_text=True))
    assert pilot["support"]["open_total"] == EXPECTED["sysadm"]
    stabilization = json.loads(client.get("/communication/faz9d/export/json").get_data(as_text=True))
    cards = {card["label"]: card["value"] for card in stabilization["summary_cards"]}
    assert cards["Açık destek"] == EXPECTED["sysadm"]


@pytest.mark.parametrize("path", [
    "/communication/faz5", "/communication/faz5/health", "/communication/faz5/retention",
    "/communication/faz8", "/communication/faz8/readiness", "/communication/faz9", "/communication/faz9/release-center",
    "/communication/faz9/first-72", "/communication/faz9a", "/communication/faz9c", "/communication/faz9d",
])
def test_snapshot_pages_still_render_for_a_scoped_viewer(env, path):
    response = _web(env, "sysadm").get(path)
    assert response.status_code == 200, (path, response.status_code)
    assert [no for no in env.other_ticket_nos if no in response.get_data(as_text=True)] == []


# --- U12: Faz 4 stored daily metrics -------------------------------------------------------------


def test_daily_metrics_store_no_support_figure_and_show_none_to_others(env):
    from app.models.communication_phase4_models import CommunicationDailyMetric
    from app.services.communication_phase4_service import (
        executive_summary_snapshot,
        export_rows_csv,
        refresh_daily_metrics,
    )

    with env.app.app_context():
        refresh_daily_metrics(_user(env, "admin_holder"))
        assert CommunicationDailyMetric.query.filter_by(metric_group="support").count() == 0
        for row in CommunicationDailyMetric.query.all():
            assert not {"open_tickets", "overdue_first_response", "overdue_resolution"} & set(row.snapshot_json or {})
        trend = _call(executive_summary_snapshot, _user(env, "sysadm"), 30)["trends"]["open_tickets"]["values"]
        _name, data, _count = export_rows_csv(_user(env, "sysadm"), "daily_metrics", 90)
    assert max(trend or [0]) <= EXPECTED["sysadm"]
    assert b"support" not in data


def test_legacy_stored_support_daily_metrics_are_not_shown_or_exported(env):
    from datetime import date

    from app.extensions import db
    from app.models.communication_phase4_models import CommunicationDailyMetric
    from app.services.communication_phase4_service import (
        executive_summary_snapshot,
        export_rows_csv,
    )

    with env.app.app_context():
        db.session.add(CommunicationDailyMetric(metric_date=date.today(), metric_group="support",
                                                metric_name="open_count", metric_value=10))
        db.session.commit()
        trend = _call(executive_summary_snapshot, _user(env, "sysadm"), 30)["trends"]["open_tickets"]["values"]
        _name, data, _count = export_rows_csv(_user(env, "sysadm"), "daily_metrics", 90)
    assert max(trend or [0]) <= EXPECTED["sysadm"]
    assert b"support" not in data


# --- U13: a stored executive report shows its author's support figures only to the author ---------


def _report_for(env, author):
    """A report by ``author``; returns its id and the open-ticket figure stored in it (author's scope)."""
    from app.services.communication_phase4_service import create_executive_report

    with env.app.app_context():
        row = create_executive_report(_user(env, author), "weekly_summary", 30)
        open_tickets = int(row.metrics_json["headline"]["headline"]["open_tickets"])
        return row.id, open_tickets


def test_a_readers_report_view_hides_the_authors_support_figures(env):
    report_id, figure = _report_for(env, "holder")
    assert figure > 0  # the author's scope holds tickets the reader cannot see
    text = _text(_web(env, "colleague").get(f"/communication/faz4/reports/{report_id}").get_data(as_text=True))
    assert not re.search(rf"Açık Destek {figure}\b", text)
    assert f"{figure} açık destek talebi" not in text
    assert "destek kaydı" not in text
    assert not re.search(rf"Toplam kayıt {figure}\b", text)


def test_the_author_still_sees_their_own_support_figures(env):
    report_id, figure = _report_for(env, "holder")
    text = _text(_web(env, "holder").get(f"/communication/faz4/reports/{report_id}").get_data(as_text=True))
    assert re.search(rf"Açık Destek {figure}\b", text)
    assert f"{figure} açık destek talebi" in text


def test_an_unrestricted_holder_reads_the_support_figures_of_any_report(env):
    report_id, figure = _report_for(env, "holder")
    text = _text(_web(env, "admin_holder").get(f"/communication/faz4/reports/{report_id}").get_data(as_text=True))
    assert re.search(rf"Açık Destek {figure}\b", text)


# --- U14: main dashboard ------------------------------------------------------------------------


@pytest.mark.parametrize("who", SCOPED)
def test_main_dashboard_counts_only_the_viewers_tickets(env, who):
    from app.services.dashboard_rebuild_service import build_dashboard_rebuild_context

    with env.app.app_context():
        context = build_dashboard_rebuild_context(_user(env, who))
    assert context["metrics"]["open_support"] == EXPECTED[who]
    assert sum(context["charts"]["support_status"]["values"]) == EXPECTED[who]


def test_a_team_scope_does_not_count_the_team_members_tickets(env, monkeypatch):
    from app.services import dashboard_rebuild_service as dashboard

    monkeypatch.setattr(dashboard, "_resolve_scope_ids", lambda user: [env.ids["creator"], env.ids["colleague"]])
    with env.app.app_context():
        context = dashboard.build_dashboard_rebuild_context(_user(env, "colleague"))
    assert context["metrics"]["open_support"] == 0
    assert sum(context["charts"]["support_status"]["values"]) == 0


# --- review F-1: a stored digest job carries its owner's open-ticket count --------------------------


def _digest_for(env, who):
    from app.extensions import db
    from app.services.communication_phase5_service import create_digest_job

    with env.app.app_context():
        create_digest_job(_user(env, who), "daily")
        db.session.commit()


@pytest.mark.parametrize("path", ["/communication/faz5/automation-center", "/communication/faz5",
                                  "/communication/faz9c/export/json", "/communication/faz9/export/json"])
@pytest.mark.parametrize("who", ["sysadm", "baskan", "colleague"])
def test_another_users_digest_summary_is_not_shown(env, path, who):
    _digest_for(env, "creator")
    body = _web(env, who).get(path).get_data(as_text=True)
    assert f"Açık destek talebi: {OTHER_TICKETS}" not in body


def test_the_digest_owner_still_sees_their_own_summary(env):
    from app.services.communication_phase5_service import automation_center_snapshot

    _digest_for(env, "sysadm")
    with env.app.app_context():
        jobs = _call(automation_center_snapshot, _user(env, "sysadm"))["recent_jobs"]
    assert any(f"Açık destek talebi: {EXPECTED['sysadm']}" in (job["result_summary"] or "") for job in jobs)


# --- review F-2: a report stored before F4 holds figures from an unscoped count ---------------------


def _legacy_report(env, author):
    """A report as stored before F4: no scope marker, institution-wide support figures."""
    from app.extensions import db
    from app.models.communication_phase4_models import CommunicationExecutiveReport

    with env.app.app_context():
        row = CommunicationExecutiveReport(
            title="Eski rapor", report_type="weekly_summary", period_label="Son 30 Gün", status="draft",
            summary_text=f"0 yayımlanmış duyuru, 0 anket ve {OTHER_TICKETS + 1} açık destek talebi bulunmaktadır.",
            metrics_json={"headline": {"headline": {"open_tickets": OTHER_TICKETS + 1},
                                       "trends": {"open_tickets": {"labels": ["x"], "values": [OTHER_TICKETS + 1]}}},
                          "support": {"totals": {"ticket_count": OTHER_TICKETS + 1}}},
            recommendations_json=[f"İlk geri dönüş SLA’sı aşılmış {OTHER_TICKETS + 1} destek kaydı var."],
            created_by_user_id=env.ids[author])
        db.session.add(row)
        db.session.commit()
        return row.id


def test_a_legacy_report_hides_unscoped_figures_even_from_its_author(env):
    report_id = _legacy_report(env, "sysadm")
    text = _text(_web(env, "sysadm").get(f"/communication/faz4/reports/{report_id}").get_data(as_text=True))
    assert f"{OTHER_TICKETS + 1} açık destek talebi" not in text
    assert not re.search(rf"Açık Destek {OTHER_TICKETS + 1}\b", text)
    assert "destek kaydı" not in text


def test_an_unrestricted_holder_still_reads_a_legacy_report(env):
    report_id = _legacy_report(env, "sysadm")
    text = _text(_web(env, "admin_holder").get(f"/communication/faz4/reports/{report_id}").get_data(as_text=True))
    assert f"{OTHER_TICKETS + 1} açık destek talebi" in text
