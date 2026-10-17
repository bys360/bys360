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
from test_pilot_support_new_ux_contract import _logged_in, _login, _make_app

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


# ---------------------------------------------------------------------------
# Rol matrisi: grup başkanı (MANAGER_ROLES, GLOBAL_ROLES değil) ve /dashboard/heavy-panels
# ---------------------------------------------------------------------------
def test_group_president_is_team_scoped_across_html_json_and_chart(app, client) -> None:
    _seed_surveys(app)
    _logged_in(app, client, sicil_no="DS-GB", role="grup_baskani")
    dashboard = _payload(client)
    assert dashboard["scope"]["is_global"] is False
    assert dashboard["user"]["manager_view"] is True  # yönetici kısayolları korunur
    _assert_no_institution_wide_participation(dashboard)
    assert client.get("/dashboard/rebuild-chart/participation").get_json()["chart"]["restricted"] is True
    html = client.get("/dashboard").get_data(as_text=True)
    assert RESTRICTED_NOTE in html and "Açık Anket" not in html


def test_restricted_roles_do_not_receive_other_staff_records(app, client) -> None:
    """Başka personelin değerlendirme kaydı kısıtlı kapsamdaki hiçbir uçta sayılmaz veya adlandırılmaz."""
    from test_ux_wave9_dashboard_contract import _seed_evaluations

    from app.extensions import db
    from app.models import User

    _seed_evaluations(app)  # "Sahte Birim"de 4 personel, 3 değerlendirme, 4 görev
    for sicil_no, role in (("DS-RP", "personel"), ("DS-RG", "grup_baskani")):
        with app.app_context():
            # Gerçekçi kayıt: yöneticinin kendi birimi dolu (boş birim ayrı bir bulgu, rapora bakın).
            user = User(sicil_no=sicil_no, email=f"{sicil_no.lower()}@bys360.test", ad="Sahte", soyad="Yönetici",
                        role=role, birim=f"Sahte Başka Birim {sicil_no}", is_active=True, must_change_password=False,
                        must_set_security_question=False)
            user.set_password("UxPilotSahte1!")
            db.session.add(user)
            db.session.commit()
        user_client = app.test_client()
        _login(user_client, sicil_no, "UxPilotSahte1!")
        dashboard = _payload(user_client)
        charts = dashboard["charts"]
        assert charts["performance_distribution"]["total"] == 0, role
        assert charts["period_completion"]["total"] == 0, role
        assert charts["unit_average"]["rows"] == [], role
        assert dashboard["metrics"]["total_personnel"] == 1, role
        payload_text = json.dumps(dashboard, ensure_ascii=False)
        assert "Sahte Personel" not in payload_text and "Sahte Birim" not in payload_text, role
        heavy = user_client.get("/dashboard/heavy-panels")
        assert heavy.status_code == 200, role
        heavy_html = heavy.get_data(as_text=True)
        assert "Sahte Personel" not in heavy_html and "Sahte Birim" not in heavy_html, role


def test_heavy_panels_require_login_and_open_for_global_role(app, client) -> None:
    anonymous = client.get("/dashboard/heavy-panels")
    assert anonymous.status_code in (301, 302) and "/login" in anonymous.headers["Location"]
    _logged_in(app, client, sicil_no="DS-HA", role="admin")
    assert client.get("/dashboard/heavy-panels").status_code == 200


@pytest.mark.parametrize("role", ["grup_baskani", "mali_musavir", "birim_sorumlusu", "koordinator"])
def test_manager_without_a_unit_does_not_see_staff_of_other_units(app, client, role) -> None:
    """Güvenlik regresyonu (açık): birimi tanımsız yönetici başka birimlerin kayıtlarını görmemeli.

    get_manager_scope_users, User.birim == user.birim karşılaştırmasını yönetici birimi
    boşken de kurar; SQLAlchemy bunu IS NULL'a çevirir ve birimi/üst birimi boş herkes
    kapsama girer. Bu test düzeltme onaylanıp uygulanana kadar kalır; gevşetilmez.
    """
    from test_ux_wave9_dashboard_contract import _seed_evaluations

    _seed_evaluations(app)  # "Sahte Birim"de 4 personel (üst birimi boş), 3 değerlendirme
    _logged_in(app, client, sicil_no=f"DS-NOUNIT-{role[:6]}", role=role)  # birim alanı boş
    dashboard = _payload(client)
    assert dashboard["charts"]["performance_distribution"]["total"] == 0
    assert dashboard["metrics"]["total_personnel"] == 1


@pytest.mark.parametrize("empty_unit", [None, "", "   "], ids=["null", "bos", "bosluk"])
@pytest.mark.parametrize("role", ["grup_baskani", "mali_musavir", "birim_sorumlusu", "koordinator"])
def test_manager_scope_with_empty_unit_contains_only_the_manager(app, role, empty_unit) -> None:
    """Güvenlik regresyonu (açık): kapsam kaynağı get_manager_scope_users, boş birim için yalnız yöneticiyi döndürmeli.

    Diğer personelin birimi/üst birimi de aynı biçimde boş (NULL, '' veya '   ') olduğunda
    bugün kapsama giriyorlar. Düzeltme onaylanıp uygulanana kadar bu test kalır.
    """
    from app.extensions import db
    from app.models import User
    from app.services.hierarchy_admin_service import get_manager_scope_users

    with app.app_context():
        def make(sicil_no: str, user_role: str, birim, ust_birim) -> User:
            user = User(sicil_no=sicil_no, email=f"{sicil_no.lower()}@bys360.test", ad="Sahte", soyad=sicil_no,
                        role=user_role, birim=birim, ust_birim=ust_birim, is_active=True,
                        must_change_password=False, must_set_security_question=False)
            user.set_password("UxPilotSahte1!")
            db.session.add(user)
            return user

        make("ES-P1", "personel", empty_unit, "Sahte Üst")   # birimi boş, başka üst birim
        make("ES-P2", "personel", "Sahte Birim Q", empty_unit)  # üst birimi boş
        manager = make("ES-MGR", role, empty_unit, None)
        db.session.commit()
        assert [u.sicil_no for u in get_manager_scope_users(manager)] in ([], ["ES-MGR"])


# ---------------------------------------------------------------------------
# /dashboard/heavy-panels: yapay zekâ yönetişim sayaçları ve sistem olgunluk verisi
# Politika: /admin/ai-center, /admin/ai-requests (maskelenmemiş içerik dahil) ve
# /admin/ai-operations-report = admin_required VE menu_key_required("ai_center").
# ---------------------------------------------------------------------------
AI_COUNTERS = "AI istekleri"


def _close_menu(app, sicil_no: str, menu_key: str) -> None:
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = db.session.query(User).filter_by(sicil_no=sicil_no).one()
        db.session.add(UserMenuPermission(user_id=user.id, menu_key=menu_key, is_visible=False))
        db.session.commit()


@pytest.mark.parametrize("role", ["personel", "birim_sorumlusu", "koordinator"])
def test_heavy_panels_hide_ai_governance_counters_from_non_admin_roles(app, client, role) -> None:
    _logged_in(app, client, sicil_no=f"HP-{role[:8]}", role=role)
    response = client.get("/dashboard/heavy-panels")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert AI_COUNTERS not in html and "Yönetişim uyarısı" not in html
    assert "AI operasyon paneli korumalı modda" in html


def test_heavy_panels_hide_ai_counters_from_admin_family_without_ai_center(app, client) -> None:
    _logged_in(app, client, sicil_no="HP-GB-NOAI", role="grup_baskani")
    _close_menu(app, "HP-GB-NOAI", "ai_center")
    assert AI_COUNTERS not in client.get("/dashboard/heavy-panels").get_data(as_text=True)


def test_heavy_panels_keep_ai_counters_for_admin_with_ai_center(app, client) -> None:
    _logged_in(app, client, sicil_no="HP-AD", role="admin")
    assert AI_COUNTERS in client.get("/dashboard/heavy-panels").get_data(as_text=True)


@pytest.mark.parametrize("role, expected", [("personel", False), ("koordinator", False), ("admin", True)])
def test_heavy_panel_context_builds_system_maturity_only_for_admin_family(app, role, expected) -> None:
    from flask_login import login_user

    from app.extensions import db
    from app.main_handlers.dashboard_handlers import _build_dashboard_heavy_context
    from app.models import User

    with app.app_context():
        user = User(sicil_no=f"HPC-{role[:6]}", email=f"hpc-{role[:6]}@bys360.test", ad="Sahte", soyad="Bağlam", role=role,
                    is_active=True, must_change_password=False, must_set_security_question=False)
        user.set_password("UxPilotSahte1!")
        db.session.add(user)
        db.session.commit()
        with app.test_request_context("/dashboard/heavy-panels"):
            login_user(user)
            context = _build_dashboard_heavy_context(user)
    assert bool(context.get("live_dashboard_surface")) is expected
    assert bool(context.get("ai_operations_bridge")) is expected
