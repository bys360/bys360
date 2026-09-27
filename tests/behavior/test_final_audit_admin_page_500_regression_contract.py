"""P2-01 regression contract: admin pages the final pre-live audit (2026-09-27)
reproduced as HTTP 500 on a scratch database, each from a deterministic code
defect (not from schema drift):

A) /performance/operations-center (+ /performans/operasyon-merkezi) and
   /performance/core-health (+ /performans/cekirdek-saglik): ``safe_render``
   received ``period`` / ``periods`` both explicitly and through ``**snapshot``
   -> "got multiple values for keyword argument".
B) /admin/ai-requests(/export) and /admin/ai-feedback(/export): called a
   non-existent ``User.display_name()``; the canonical name is the
   ``User.full_name`` property.
C) /performance/interim-notes (admin branch): bound an expanding
   ``scope_ids`` parameter to SQL that has no ``:scope_ids`` placeholder.
D) /performance/hierarchy-tree-live: its lazy scope-context shim called
   itself (RecursionError on every request). The page must also terminate
   with self-referencing / cyclic manager data (setup_admin makes the first
   admin its own manager).
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

_TEST_PASSWORD = "TestAdminPage500Regression-2026!x"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield from _build_app(monkeypatch, tmp_path_factory.mktemp("p2_01"))


def _build_app(monkeypatch: pytest.MonkeyPatch, tmp_path):
    for key, value in {
        "APP_ENV": "testing",
        "SECRET_KEY": "test-secret-key-for-p2-01-admin-page-regressions",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "p2-01-first-login-test-pw",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
    }.items():
        monkeypatch.setenv(key, value)

    db_path = os.path.join(str(tmp_path), f"p2_01_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={"poolclass": StaticPool, "connect_args": {"check_same_thread": False}},
    )
    with flask_app.app_context():
        from app.extensions import db

        db.create_all()
        db.session.commit()
    yield flask_app


def _user(db, sicil: str, ad: str, role: str, manager_sicil: str | None):
    from app.models import User

    user = User(
        ad=ad,
        soyad="Regresyon",
        sicil_no=sicil,
        email=f"{sicil.lower()}@example.gov.tr",
        unvan="Uzman",
        role=role,
        birim="Bilgi İşlem",
        ust_birim="Destek",
        yonetici_sicil=manager_sicil,
        is_active=True,
    )
    user.set_password(_TEST_PASSWORD)
    for flag in ("must_change_password", "must_set_security_question", "is_first_login"):
        if hasattr(user, flag):
            setattr(user, flag, False)
    db.session.add(user)
    return user


@pytest.fixture(scope="module")
def seeded(app):
    from app.extensions import db
    from app.models.ai_models import AIFeedbackLog, AIRequestLog

    with app.app_context():
        # setup_admin makes the first admin its own manager; add an A <-> B cycle too.
        admin = _user(db, "P21ADM", "AdminRegresyon", "admin", "P21ADM")
        _user(db, "P21CYA", "DonguAlfa", "personel", "P21CYB")
        _user(db, "P21CYB", "DonguBeta", "koordinator", "P21CYA")
        db.session.commit()
        request_log = AIRequestLog(module_type="performance", feature_type="summary", user_id=admin.id, status="completed")
        db.session.add(request_log)
        db.session.commit()
        db.session.add(AIFeedbackLog(ai_request_log_id=request_log.id, user_id=admin.id, feedback_type="useful"))
        db.session.commit()
        data = SimpleNamespace(admin_sid=admin.get_id(), admin_name=admin.full_name)
    # Return outside the app context so Flask-Login's per-context user cache
    # is not shared between test-client requests.
    return data


def _admin_get(app, seeded, path: str):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = seeded.admin_sid
        sess["_fresh"] = True
    return client.get(path)


@pytest.mark.parametrize(
    "path",
    [
        "/performance/operations-center",
        "/performans/operasyon-merkezi",
        "/performance/core-health",
        "/performans/cekirdek-saglik",
    ],
)
def test_a_operation_and_core_health_pages_render(app, seeded, path) -> None:
    assert _admin_get(app, seeded, path).status_code == 200


@pytest.mark.parametrize("path", ["/admin/ai-requests/export", "/admin/ai-feedback/export"])
def test_b_ai_log_exports_use_canonical_user_name(app, seeded, path) -> None:
    response = _admin_get(app, seeded, path)
    assert response.status_code == 200
    assert seeded.admin_name in response.get_data(as_text=True)


@pytest.mark.parametrize("path", ["/admin/ai-requests", "/admin/ai-feedback"])
def test_b_ai_log_lists_use_canonical_user_name(app, seeded, path) -> None:
    response = _admin_get(app, seeded, path)
    assert response.status_code == 200
    assert seeded.admin_name in response.get_data(as_text=True)


def test_c_interim_notes_admin_branch_renders(app, seeded) -> None:
    assert _admin_get(app, seeded, "/performance/interim-notes").status_code == 200


def test_d_hierarchy_tree_live_terminates_with_self_and_cyclic_managers(app, seeded) -> None:
    response = _admin_get(app, seeded, "/performance/hierarchy-tree-live")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "DonguAlfa" in body
    assert "DonguBeta" in body


def test_d_hierarchy_scope_shim_delegates_to_view_helpers(app, seeded) -> None:
    from app.performance import hierarchy_ui_routes

    with app.test_request_context("/performance/hierarchy-tree-live"):
        context = hierarchy_ui_routes._build_surface_scope_context(SimpleNamespace(id=0, role="admin"), None)

    assert isinstance(context, dict)
