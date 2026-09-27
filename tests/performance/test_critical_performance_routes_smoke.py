from __future__ import annotations

import pytest


class Row(dict):
    """Jinja'da hem dict hem dot erişimi için küçük yardımcı."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


@pytest.fixture(autouse=True)
def _disable_login(app):
    app.config["LOGIN_DISABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["CSRF_ENABLED"] = False


def test_feedback_pipeline_loads_without_500(client, monkeypatch):
    import app.performance.feedback_pipeline_routes as routes

    monkeypatch.setattr(
        routes,
        "build_feedback_pipeline_context",
        lambda user: {
            "steps": [],
            "summary": {"total": 0, "ready": 0, "missing": 0, "attention": 0, "readiness_percent": 100},
            "warnings": [],
            "state_machine": {"nodes": []},
            "access_denied": False,
            "pipeline_note": "Test görünümü",
        },
    )
    response = client.get("/performance/feedback-pipeline")
    assert response.status_code != 500


def test_feedback_corporate_cleanup_no_500(client, monkeypatch):
    import app.performance.feedback_corporate_cleanup_phase6_routes as routes

    monkeypatch.setattr(
        routes,
        "build_phase6_context",
        lambda include_database=True: {
            "summary": {"total": 0, "ready": 0, "attention": 0, "missing": 0},
            "items": [],
            "checks": [],
            "warnings": [],
        },
    )
    response = client.get("/performance/feedback-corporate-cleanup")
    assert response.status_code in (200, 403)


def test_process_tracking_no_500(client, monkeypatch):
    import app.performance.process_engine_phase8_tracking_routes as routes

    monkeypatch.setattr(routes, "can_view_process_tracking", lambda user: True)
    monkeypatch.setattr(
        routes,
        "build_process_tracking_workspace",
        lambda user, status_filter="all", search="": {
            "counts": {"total": 0, "waiting": 0, "overdue": 0, "president_pending": 0, "completed": 0},
            "items": [],
            "status_filter": status_filter,
            "search": search,
        },
    )
    response = client.get("/performance/process-tracking")
    assert response.status_code != 500


def test_process_reports_no_500(client, monkeypatch):
    import app.performance.process_engine_phase10_reports_routes as routes

    monkeypatch.setattr(routes, "can_view_process_tracking", lambda user: True)
    monkeypatch.setattr(
        routes,
        "_bys360_process_reports_advanced_context",
        lambda viewer=None, status_filter=None: {
            "summary": {"total": 0, "pending": 0, "overdue": 0, "president_required": 0, "finalized": 0},
            "status_rows": [],
            "owner_rows": [],
            "recent_rows": [],
            "president_rows": [],
            "status_filter": status_filter or "",
        },
    )
    response = client.get("/performance/process-reports")
    assert response.status_code != 500


def test_president_approval_card_no_500(client, monkeypatch):
    import app.performance.process_engine_phase6_president_approvals_routes as routes

    monkeypatch.setattr(routes, "can_view_president_approvals", lambda user: True)
    monkeypatch.setattr(
        routes,
        "build_president_card_review_context",
        lambda approval_id, viewer=None: {
            "approval": Row(
                approval_id=approval_id,
                employee_name="Test Personel",
                sicil_no="TEST-1",
                birim="Test Birim",
                unit="Test Birim",
                title="Personel",
                period_title="Test Dönemi",
                final_score="65.00",
                approval_status="Başkan Onayı Bekliyor",
                process_stage="Başkan Onayı Bekliyor",
                publish_lock_status="Başkan Onayı Yayın Kilidi",
                requested_at="-",
                publish_lock_reason="Test yayın kilidi",
            ),
            "scorecard_items": [],
            "manager_totals": [],
            "scoring_history": [],
            "flow_steps": [],
            "scorecard_interpretation": {},
        },
    )
    response = client.get("/performance/president-approvals/1/card")
    assert response.status_code != 500
