"""BYS360 DEFECT AR: admin_org_unit_create()/admin_org_unit_edit() detected
duplicate organization-unit names via
``func.lower(OrganizationUnit.name) == name.lower()``. SQLite's SQL LOWER()
only folds ASCII, so a unit named with a Turkish capital İ (e.g. "İnsan
Kaynakları") and a duplicate attempt typed as "insan kaynakları" were not
recognized as the same name -- the duplicate would have been silently
created. The fix compares via app.utils.turkish_text.turkish_casefold in
Python instead of trusting either database's native LOWER().

End-to-end proof through the real HTTP route: creating the same
Turkish-cased unit name a second time (different case) under the same
parent must now be rejected.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TMP_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "defect_ar_org_unit" / "test_dbs"


def _make_app(monkeypatch: pytest.MonkeyPatch):
    _TMP_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TMP_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-defect-ar-org-unit-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "defect-ar-first-login-test-pw")
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

    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.extensions import db

    with flask_app.app_context():
        db.create_all()
    return flask_app


def _create_admin(app, *, sicil_no, email):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Defect",
            soyad="AR",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("DefectArTestKey1!")
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": "DefectArTestKey1!"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_turkish_cased_duplicate_org_unit_name_is_rejected(monkeypatch, request):
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_admin(app, sicil_no="ar020", email="ar.admin@ktb.gov.tr")

    client = app.test_client()
    _login(client, "ar020")

    first = client.post(
        "/admin/org-units/create",
        data={"name": "İnsan Kaynakları", "unit_type": "diger", "sort_order": "0"},
        follow_redirects=False,
    )
    assert first.status_code == 302

    # Same word, different case, typed with a plain lowercase dotted-i --
    # the correct lowercase form of the Turkish capital İ used above.
    second = client.post(
        "/admin/org-units/create",
        data={"name": "insan kaynakları", "unit_type": "diger", "sort_order": "0"},
        follow_redirects=True,
    )
    assert second.status_code == 200
    assert b"zaten mevcut" in second.data

    from app.extensions import db
    from app.models import OrganizationUnit

    with app.app_context():
        count = db.session.query(OrganizationUnit).filter(
            OrganizationUnit.name.in_(["İnsan Kaynakları", "insan kaynakları"]),
        ).count()
    assert count == 1


def test_genuinely_different_org_unit_names_are_both_created(monkeypatch, request):
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_admin(app, sicil_no="ar021", email="ar.admin2@ktb.gov.tr")

    client = app.test_client()
    _login(client, "ar021")

    for name in ("İnsan Kaynakları", "Bilgi İşlem"):
        response = client.post(
            "/admin/org-units/create",
            data={"name": name, "unit_type": "diger", "sort_order": "0"},
            follow_redirects=False,
        )
        assert response.status_code == 302

    from app.extensions import db
    from app.models import OrganizationUnit

    with app.app_context():
        count = db.session.query(OrganizationUnit).filter(
            OrganizationUnit.name.in_(["İnsan Kaynakları", "Bilgi İşlem"]),
        ).count()
    assert count == 2
