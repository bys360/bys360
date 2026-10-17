"""BYS360 UX dalga 9 -- Gösterge paneli (dashboard.html) sözleşme testleri.

Sunum ve bilgi mimarisi değişti; veri, hesaplama, kapsam ve yetki kuralları
(app/services/dashboard_rebuild_service.py) aynı kaldı. CSP sözleşmesi
(tests/security/test_csp_wave2_dashboard_contract.py) ve stil ratchet'i aynen geçerli:
şablon base.html'i genişletir, include içermez, JSON veri bloğu ve dashboard_rebuild.js
korunur; 6 dinamik genişlik/renk özniteliği sayıca korunur (yerinde düzenleme dalgası
dinamik öznitelik ekleyip kaldıramaz).

Sabitlenen gerçek hatalar: lejant renkleri halka dilimleriyle eşleşmiyordu; tamamlanma
çubukları yüzde değil en büyük değere göre çiziliyordu; hızlı geçişlerde web'de
karşılığı olmayan /support/tickets, /communication/surveys ve
/admin/ai/decision-dashboard bağlantıları vardı; birim başlığında personel sayısı
"kişi" diye birim sayısının yerine yazılıyordu.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_pilot_support_new_ux_contract import (
    _english_ui_findings,
    _logged_in,
    _make_app,
    _VisibleUiText,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "app/templates/dashboard.html"
DASH_CSS = REPO_ROOT / "app/static/css/bys360_dashboard.css"
SERVICE = REPO_ROOT / "app/services/dashboard_rebuild_service.py"


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _seed_evaluations(app) -> None:
    """Aktif dönem + 3 sahte değerlendirme (60, 80, 95) + 4 görev (2 tamamlanan, 2 bekleyen)."""
    from datetime import date

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models import EvaluationAssignment, PerformanceEvaluation, PerformancePeriod, User

    now = utc_now().replace(tzinfo=None)
    with app.app_context():
        period = PerformancePeriod(title="Sahte Dönem", period_type="semi_annual", start_date=date(2026, 7, 1),
                                   end_date=date(2026, 12, 31), is_active=True)
        db.session.add(period)
        db.session.flush()
        staff = []
        for i, score in enumerate((60, 80, 95, 85)):
            user = User(sicil_no=f"D9-P{i}", email=f"d9-p{i}@bys360.test", ad="Sahte", soyad=f"Personel {i}", role="personel",
                        is_active=True, must_change_password=False, must_set_security_question=False, birim="Sahte Birim")
            user.set_password("UxPilotSahte1!")
            db.session.add(user)
            db.session.flush()
            staff.append(user)
            if i < 3:
                db.session.add(PerformanceEvaluation(period_id=period.id, employee_id=user.id, level_1_total_100=score,
                                                     level_2_total_100=score, level_3_total_100=0, final_total_100=score,
                                                     level_1_completed=True, level_2_completed=True, level_3_completed=False,
                                                     status="tamamlandi", workflow_status="completed", is_published_to_employee=False,
                                                     feedback_request_allowed=False, evaluation_exempted=False,
                                                     employee_leave_days_in_period=0, employee_absence_days_in_period=0,
                                                     employee_available_days_in_period=180))
        for i, user in enumerate(staff):
            done = i < 2
            db.session.add(EvaluationAssignment(period_id=period.id, employee_id=user.id, evaluator_id=staff[-1].id,
                                                assignment_source="test", manager_level=1,
                                                status="tamamlandi" if done else "bekliyor", assigned_at=now,
                                                completed_at=now if done else None))
        db.session.commit()


# ---------------------------------------------------------------------------
# Statik: CSP, ratchet, kapsam
# ---------------------------------------------------------------------------
def test_template_keeps_csp_contract_and_dynamic_attribute_count() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.lstrip().startswith('{% extends "base.html" %}')
    assert "{% include" not in text
    assert "<style" not in text.lower()
    assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE)
    assert "|safe" not in text
    style_attrs = re.findall(r'\sstyle="([^"]*)"', text)
    assert len(style_attrs) == 6 and all("{{" in value for value in style_attrs), style_attrs
    assert 'data-dashboard-rebuild="BYS360_DASHBOARD_REBUILD_V1_OK"' in text
    assert '<script id="dashboard-rebuild-payload" type="application/json">{{ d|tojson }}</script>' in text
    assert "js/dashboard_rebuild.js" in text
    for asset in ("css/bys360_tokens.css", "css/bys360_components.css", "css/bys360_dashboard.css"):
        assert asset in text, asset
    assert 'class="bys-ui bys-page dash-page skip-mobile-normalize"' in text


def test_dashboard_css_is_scoped_and_has_no_important() -> None:
    css = re.sub(r"/\*.*?\*/", "", DASH_CSS.read_text(encoding="utf-8"), flags=re.S)
    assert "!important" not in css and ":root" not in css
    selectors = [s.strip() for block in re.findall(r"([^{}]+)\{", css) for s in block.split(",")
                 if s.strip() and not s.strip().startswith("@")]
    assert selectors and all(s.startswith(".bys-ui") for s in selectors), [s for s in selectors if not s.startswith(".bys-ui")]


def test_legend_swatches_match_the_service_donut_palette() -> None:
    match = re.search(r'colors = \[([^\]]+)\]', SERVICE.read_text(encoding="utf-8"))
    assert match, "Servisteki halka grafiği paleti bulunamadı."
    colors = [c.strip().strip('"').lower() for c in match.group(1).split(",")]
    css = DASH_CSS.read_text(encoding="utf-8").lower()
    for index, color in enumerate(colors, start=1):
        assert f".bys-ui .dash-swatch--{index} {{ background: {color}; }}" in css, (index, color)


def test_service_has_no_dead_web_links() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    for dead in ("/support/tickets", "/communication/surveys", "/admin/ai/decision-dashboard"):
        assert dead not in source, dead


# ---------------------------------------------------------------------------
# Canlı sayfa
# ---------------------------------------------------------------------------
def _hrefs(html: str, css_class: str) -> list[str]:
    block = html.split(f'class="{css_class}"', 1)[1].split("</ul>", 1)[0]
    return re.findall(r'href="([^"]+)"', block)


def test_admin_sees_global_view_with_true_percentages(app, client) -> None:
    _seed_evaluations(app)
    _logged_in(app, client, sicil_no="90901", role="admin")
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Kurumsal genel bakış" in html and "Genel yönetim kapsamı" in html
    assert "<b>3</b><small>kayıt</small>" in html  # 60, 80, 95 → 3 değerlendirme
    # Dönem tamamlanma: 2 tamamlanan / 2 bekleyen → %50 + %50 (eskiden en büyüğe göre %100 çiziliyordu)
    assert html.count('style="width: 50.0%"') == 2
    assert "2 görev · %50.0" in html


def test_every_shortcut_and_action_points_to_an_existing_route(app, client) -> None:
    _seed_evaluations(app)
    _logged_in(app, client, sicil_no="90902", role="admin")
    html = client.get("/dashboard").get_data(as_text=True)
    hrefs = _hrefs(html, "dash-shortcuts") + _hrefs(html, "dash-links")
    assert hrefs
    adapter = app.url_map.bind("localhost")
    for href in hrefs:
        adapter.match(href, method="GET")  # 404 ise NotFound fırlatır


def test_personel_sees_personal_view_without_manager_shortcuts(app, client) -> None:
    _logged_in(app, client, sicil_no="90903", role="personel")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Bana özel genel bakış" in html
    shortcuts = _hrefs(html, "dash-shortcuts")
    assert shortcuts and not {"/survey-manage", "/admin/ai-center", "/personnel", "/performance/reports"} & set(shortcuts)
    # Boş veri: sahte sayı/grafik üretilmez, açıklayıcı boş durum gösterilir.
    assert "Aktif dönemde henüz değerlendirme kaydı yok." in html
    assert "Ortalama üretecek performans kaydı henüz yok." in html
    assert "Görebildiğiniz destek talebi yok." in html


def test_tr_dashboard_has_no_english_ui_text(app, client) -> None:
    _seed_evaluations(app)
    _logged_in(app, client, sicil_no="90904", role="admin")
    html = client.get("/dashboard").get_data(as_text=True)
    scanner = _VisibleUiText("dash-page")
    scanner.feed(html)
    assert scanner.strings
    findings = _english_ui_findings(scanner.strings)
    assert findings == [], "Kullanıcıya görünen İngilizce metin:\n" + "\n".join(findings)
