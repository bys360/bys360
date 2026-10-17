"""Gösterge paneli kurumsal veri kapsamı sözleşmesi.

Kök neden: dashboard_rebuild_service içindeki _participation (anket ve geri bildirim
katılımı) ile _count_open_surveys ("Açık Anket" göstergesi) kapsam kimliği almadan
bütün tabloyu sayıyordu. Servisin kendi kuralı ise açıktır: _resolve_scope_ids
None döndürürse (GLOBAL_ROLES) kurum geneli, liste döndürürse yalnız o kişiler.
Diğer bütün göstergeler bu kurala uyuyordu; bu ikisi uymuyordu ve sonuç HTML'e,
sayfadaki JSON veri bloğuna, /dashboard/rebuild-data ve /dashboard/rebuild-chart/<anahtar>
uçlarına aynen gidiyordu.

Düzeltme yeni kural tanımlamaz: kurum geneli katılım ve açık anket sayısı yalnız
kurum geneli kapsamı olan rollere üretilir. Kısıtlı kapsamda bu değerler hiç
hesaplanmaz; sahte sıfır yerine açıklayıcı boş durum gösterilir. Ekip kapsamında
katılım hesaplamak yeni bir iş kuralı olduğundan proje sahibi kararına bırakıldı.
"""
from __future__ import annotations

import json

import pytest
from test_pilot_support_new_ux_contract import _logged_in, _make_app

RESTRICTED_NOTE = "Kurum geneli anket ve geri bildirim katılımı yalnız kurum geneli yetkisi olan yöneticilere gösterilir."


@pytest.fixture
def app(monkeypatch):
    from app.services.runtime_cache import invalidate_prefix

    app = _make_app(monkeypatch)
    # Sayfa bağlamı kullanıcı kimliğine göre 45 sn önbelleklenir; testler arası kimlik çakışmasını önle.
    with app.app_context():
        invalidate_prefix("dashboard:")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _seed_surveys(app) -> None:
    """İki yayında anket, üç atama, iki tamamlanmış yanıt (kurum geneli: %66,7)."""
    from app.extensions import db
    from app.models import Survey, SurveyAssignment, SurveyResponse, User

    with app.app_context():
        owner = User(sicil_no="DS-OWNER", email="ds-owner@bys360.test", ad="Sahte", soyad="Anket Sahibi", role="admin",
                     is_active=True, must_change_password=False, must_set_security_question=False, birim="Sahte Yönetim")
        owner.set_password("UxPilotSahte1!")
        respondents = [User(sicil_no=f"DS-P{i}", email=f"ds-p{i}@bys360.test", ad="Sahte", soyad=f"Yanıtlayan {i}",
                            role="personel", is_active=True, must_change_password=False, must_set_security_question=False,
                            birim="Sahte Birim Z") for i in range(2)]
        for user in respondents:
            user.set_password("UxPilotSahte1!")
        db.session.add_all([owner, *respondents])
        db.session.flush()
        surveys = [Survey(title=f"Sahte anket {i}", created_by_user_id=owner.id, status="active") for i in range(2)]
        db.session.add_all(surveys)
        db.session.flush()
        assignments = [SurveyAssignment(survey_id=surveys[0].id, target_type="all"),
                       SurveyAssignment(survey_id=surveys[1].id, target_type="unit", target_value="Sahte Birim Z"),
                       SurveyAssignment(survey_id=surveys[1].id, target_type="user", target_value=str(respondents[0].id))]
        db.session.add_all(assignments)
        db.session.flush()
        for user, assignment in zip(respondents, assignments[:2], strict=True):
            db.session.add(SurveyResponse(survey_id=assignment.survey_id, user_id=user.id, assignment_id=assignment.id, is_completed=True))
        db.session.commit()


def _payload(client) -> dict:
    response = client.get("/dashboard/rebuild-data")
    assert response.status_code == 200
    return response.get_json()["dashboard"]


def _assert_no_institution_wide_participation(dashboard: dict) -> None:
    assert "open_surveys" not in dashboard["metrics"]
    assert "open_surveys" not in {card["key"] for card in dashboard["kpi_cards"]}
    participation = dashboard["charts"]["participation"]
    assert participation["restricted"] is True
    assert participation["rows"] == [] and participation["values"] == []
    # Gizlenen veri başka bir alandan da taşınmaz.
    assert "Anket katılımı" not in json.dumps(dashboard, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Kısıtlı kapsam: personel ve ekip yöneticisi
# ---------------------------------------------------------------------------
def test_personel_json_payload_carries_no_institution_wide_survey_data(app, client) -> None:
    _seed_surveys(app)
    _logged_in(app, client, sicil_no="DS-PER", role="personel")
    _assert_no_institution_wide_participation(_payload(client))


def test_team_manager_json_payload_carries_no_institution_wide_survey_data(app, client) -> None:
    _seed_surveys(app)
    _logged_in(app, client, sicil_no="DS-BS", role="birim_sorumlusu")
    dashboard = _payload(client)
    assert dashboard["scope"]["is_global"] is False
    _assert_no_institution_wide_participation(dashboard)


def test_chart_endpoint_does_not_leak_participation(app, client) -> None:
    _seed_surveys(app)
    _logged_in(app, client, sicil_no="DS-PER2", role="personel")
    chart = client.get("/dashboard/rebuild-chart/participation").get_json()["chart"]
    assert chart["restricted"] is True and chart["rows"] == [] and "totals" not in chart


def test_personel_html_and_embedded_json_show_an_honest_empty_state(app, client) -> None:
    _seed_surveys(app)
    _logged_in(app, client, sicil_no="DS-PER3", role="personel")
    html = client.get("/dashboard").get_data(as_text=True)
    assert RESTRICTED_NOTE in html
    assert "Açık Anket" not in html
    embedded = html.split('<script id="dashboard-rebuild-payload" type="application/json">', 1)[1].split("</script>", 1)[0]
    _assert_no_institution_wide_participation(json.loads(embedded))


# ---------------------------------------------------------------------------
# Kurum geneli kapsam: mevcut davranış korunur
# ---------------------------------------------------------------------------
def test_global_role_keeps_institution_wide_participation_and_open_surveys(app, client) -> None:
    _seed_surveys(app)
    _logged_in(app, client, sicil_no="DS-ADM", role="admin")
    dashboard = _payload(client)
    assert dashboard["scope"]["is_global"] is True
    assert dashboard["metrics"]["open_surveys"] == 2
    survey_row = dashboard["charts"]["participation"]["rows"][0]
    assert (survey_row["label"], survey_row["count"], survey_row["total"]) == ("Anket katılımı", 2, 3)
    assert not dashboard["charts"]["participation"].get("restricted")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Açık Anket" in html and "2 / 3" in html and RESTRICTED_NOTE not in html


def test_personal_survey_counter_still_reports_the_users_own_pending_surveys(app, client) -> None:
    """Bana özel anket sayısı kişisel kapsamdadır ve korunur (target_type='all' ataması)."""
    _seed_surveys(app)
    _logged_in(app, client, sicil_no="DS-PER4", role="personel")
    assert _payload(client)["personal"]["surveys"] == 1
