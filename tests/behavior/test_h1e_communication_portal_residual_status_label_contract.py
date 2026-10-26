"""BYS360 H1E residual closure -- communication + portal domains.

A final repo-wide residual scan (post H1E-A..G) found three more raw-value
leaks the earlier, domain-scoped H1E-A/B/C waves did not reach:

  - app/templates/survey_take.html (the top-level survey-answer page,
    NOT the already-fixed communication/phase3_survey_take.html) showed
    Survey.survey_type and SurveyAssignment.target_type via bare
    `|replace('_',' ')|title` Jinja filter chains -- e.g. "kurum_ici"
    displayed as "Kurum Ici" (missing diacritics) and "role" displayed
    as the raw English word "Role" instead of "Rol". Neither field had
    any dedicated label dict anywhere in the repo before this wave. Two
    new dicts (SURVEY_TYPE_LABELS, SURVEY_TARGET_TYPE_LABELS) were added
    to app/services/communication_phase2_service.py (extracted from the
    Turkish text already hardcoded in survey_create.html's <option>
    tags, so the wording matches what admins already see when creating
    a survey), wired into survey_take() via new
    survey_type_label/target_type_label context kwargs.
  - app/templates/communication/phase1_dashboard.html and
    phase2_dashboard.html's "Son anketler" widgets showed
    `row.survey_type` completely raw, right next to a correctly-mapped
    `Durum: ...survey_status_labels.get(row.status, 'Bilinmiyor')` on the
    SAME line -- reused the new SURVEY_TYPE_LABELS dict the same way.
  - app/templates/portal/_home_feed.html's featured-post showcase
    recomputed a post-type label from the raw `post.post_type` via
    `|replace('_',' ')|title` instead of using `item.post_type_label`,
    which app/services/portal_service.py's enrich_posts() already
    computes correctly (POST_TYPE_LABELS.get(post.post_type, "Paylaşım"))
    for the exact same `item` the template already has in scope --
    portal_home_posts/portal_home_featured are both built from
    enrich_posts() output.

app/services/communication_phase3_service.py's update_support_status()
notification body (`SUPPORT_STATUS_LABELS.get(new_status, new_status)`)
was also fixed to a safe "Bilinmiyor" fallback instead of an echo, but is
NOT separately tested here: new_status is validated against
SUPPORT_STATUS_LABELS earlier in the same function (raises
CommunicationPhase3Error for anything not in the dict), so the raw-echo
branch this fixes is currently unreachable via the only caller -- a
defensive/consistency fix, not an active leak, matching the same
reasoning already applied to app/services/performance_admin_service.py's
humanize_publish_log_action() in the prior performance-residual wave.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_comm_portal_residual_tmp" / "test_dbs"
_PASSWORD = "H1ECommPortalResidualTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required).
# ---------------------------------------------------------------------------


def test_survey_type_and_target_type_labels_never_leak_raw() -> None:
    from app.services.communication_phase2_service import (
        SURVEY_TARGET_TYPE_LABELS,
        SURVEY_TYPE_LABELS,
    )

    assert SURVEY_TYPE_LABELS.get("kurum_ici") == "Kurum İçi"
    assert SURVEY_TYPE_LABELS.get("nabiz") == "Nabız"
    assert SURVEY_TARGET_TYPE_LABELS.get("role") == "Rol"
    assert SURVEY_TARGET_TYPE_LABELS.get("unit") == "Birim"


# ---------------------------------------------------------------------------
# B: app/DB-backed contracts.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-comm-portal-residual-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-comm-portal-residual-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix())

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="H1E",
            soyad="CommPortalResidualContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _insert_published_survey(app, *, creator_id, survey_type, target_type, target_value=""):
    from app.extensions import db
    from app.models import Survey, SurveyAssignment

    with app.app_context():
        survey = Survey(
            title="H1E Comm/Portal Residual Test Survey",
            survey_type=survey_type,
            created_by_user_id=creator_id,
            status="published",
            start_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
        )
        db.session.add(survey)
        db.session.commit()
        db.session.add(SurveyAssignment(survey_id=survey.id, target_type=target_type, target_value=target_value))
        db.session.commit()
        return survey.id


def test_survey_take_page_shows_turkish_type_and_target(app, client) -> None:
    # target_type="role" only matches a user whose own .role equals
    # target_value (see app/services/surveys/targets.py's
    # assignment_matches_user_filter) -- the test user's role ("admin")
    # is used as target_value so matching_assignment_for_user() actually
    # finds this assignment and the route doesn't bounce to /surveys.
    creator_id = _create_user(app, sicil_no="h1e_cp_res_creator", role="admin")
    survey_id = _insert_published_survey(app, creator_id=creator_id, survey_type="geri_bildirim", target_type="role", target_value="admin")

    _login(client, "h1e_cp_res_creator")
    body = client.get(f"/surveys/{survey_id}/take").get_data(as_text=True)

    assert "Geri Bildirim" in body
    assert "Rol" in body
    assert "geri_bildirim" not in body


def test_survey_take_page_never_leaks_an_unmapped_survey_type(app, client) -> None:
    # target_type is a genuinely closed, fully-validated enum
    # (_SURVEY_ALLOWED_TARGET_TYPES at write time) -- an unrecognized
    # target_type can never match any user via
    # assignment_matches_user_filter, so the route safely bounces to
    # /surveys before rendering anything at all (no leak because no
    # access, not a display defect). survey_type has no such write-time
    # gate at the SurveyAssignment-matching layer, so it is the field
    # that can actually reach the template with an unexpected value
    # (e.g. a legacy/migrated row) -- target_type="all" here guarantees
    # the assignment always matches, isolating the survey_type fallback.
    creator_id = _create_user(app, sicil_no="h1e_cp_res_creator_b", role="admin")
    survey_id = _insert_published_survey(app, creator_id=creator_id, survey_type="future_survey_type_v9", target_type="all")

    _login(client, "h1e_cp_res_creator_b")
    body = client.get(f"/surveys/{survey_id}/take").get_data(as_text=True)

    assert "future_survey_type_v9" not in body
    assert "Bilinmiyor" in body


def test_communication_dashboards_show_turkish_survey_type(app, client) -> None:
    creator_id = _create_user(app, sicil_no="h1e_cp_res_dash", role="admin")
    _insert_published_survey(app, creator_id=creator_id, survey_type="nabiz", target_type="all")

    _login(client, "h1e_cp_res_dash")

    phase1_body = client.get("/communication/faz1").get_data(as_text=True)
    assert "Nabız" in phase1_body
    assert "nabiz" not in phase1_body

    phase2_body = client.get("/communication/faz2").get_data(as_text=True)
    assert "Nabız" in phase2_body
    assert "nabiz" not in phase2_body


def test_portal_home_feed_uses_precomputed_post_type_label_not_raw(app) -> None:
    """portal/_home_feed.html is a plain include (no {% extends %}), so it
    can be rendered directly with a hand-built `item` matching the shape
    enrich_posts() produces, without needing a full authenticated portal
    request. Proves the template now shows item.post_type_label instead
    of recomputing a raw|replace|title guess from post.post_type."""
    from types import SimpleNamespace

    from flask import render_template

    with app.test_request_context("/"):
        post = SimpleNamespace(id=1, post_type="best_practice", title="Test paylaşım", body="Test içerik")
        item = {"post": post, "post_type_label": "En İyi Uygulama"}
        body = render_template(
            "portal/_home_feed.html",
            portal_home_enabled=True,
            portal_home_posts=[item],
            portal_home_featured=[item],
            portal_home_stats={},
            portal_home_groups=[],
            portal_home_instagram_stories=[],
            portal_recent_interactions=[],
        )

    assert "En İyi Uygulama" in body
    assert "best_practice" not in body
    assert "Best Practice" not in body
