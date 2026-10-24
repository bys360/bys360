"""BYS360_PHASE5_3B_A2_ACCOUNT_CHANGE_PHOTO_OPEN_REDIRECT_HARDENING

`app/main_handlers/account_handlers.py::account_change_photo` eskiden kendi
başına, zayıf bir "next" denetimi yapıyordu:

    next_url.startswith("/") and not next_url.startswith("//")

Bu; backslash ("/\\evil.example") ve percent-encode edilmiş ayraç
("/%2Fevil.example", "%5cevil.example") tabanlı open-redirect bypass'larına
karşı savunmasızdı. Düzeltme, aynı satır-içi kontrolü kaldırıp merkezi,
framework'ten bağımsız `app.security.redirect_guard.is_safe_redirect_target`
üzerine kurulu `app.route_support.is_safe_redirect_target`'ı kullanıyor.

`tests/security/test_redirect_guard_open_redirect_hardening.py` zaten saf
guard'ı (redirect_guard + route_support) onlarca saldırı deseniyle kapsamlı
biçimde test ediyor. BU dosyanın amacı FARKLI: account_handlers'ın gerçekten
o korumayı çağırdığını, gerçek `/account/photo` POST akışı (giriş yapmış
kullanıcı, gerçek route, gerçek form verisi) üzerinden kanıtlamak -- yalnızca
saf fonksiyon çağrısıyla değil.

İzole, tek-testlik Flask app kurulum deseni `tests/security/test_phase13b_csrf_and_scope.py`
ile aynıdır (paylaşılan session-scope `app`/`client` fixture'larına bağımlı
olmadan, her testin kendi SQLite DB'sini kurması).
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "phase5_3b" / "test_dbs"

CANONICAL_HOST = "bys360.canakkaletarihialan.gov.tr"
CANONICAL_BASE_URL = f"https://{CANONICAL_HOST}"


def _make_app(monkeypatch, **config_overrides):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase5-3b-account-photo-redirect-guard")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
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

    # BYS360_P13B_CONFIG_ISOLATION deseniyle aynı gerekçe: app.config
    # değişikliği db.init_app sonrasında yapılırsa SQLAlchemy motorunu
    # değiştirmez. Test DB ayarlarını create_app öncesinde doğrudan Config
    # sınıfına uygula.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    # Kanonik taban URL, redirect_guard'ın GÜVEN KÖKÜ -- test client'ın asıl
    # servis ettiği host (localhost) ile BİLİNÇLİ olarak farklı tutulur ki
    # "karar request.host'a mı yoksa APP_BASE_URL'e mi dayanıyor" sorusu her
    # testte örtük biçimde de sınansın (bkz. aşağıdaki host-header testleri).
    # NOT: `Config.APP_BASE_URL` create_app() sırasında zaten env'den (veya
    # varsayılan 'http://127.0.0.1:8000'den) dolu geliyor, bu yüzden
    # `setdefault` burada YANLIŞ olurdu (anahtar zaten var demek, hiçbir şey
    # değiştirmez) -- doğrudan atama kullanılıyor.
    app.config["APP_BASE_URL"] = CANONICAL_BASE_URL
    app.config["REDIRECT_ALLOWED_HOSTS"] = []
    app.config.update(config_overrides)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


def _create_user(app, *, sicil_no, email, role="personel", password="Phase5b3bTestKey1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Phase5b3b",
            soyad="Test",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password="Phase5b3bTestKey1!"):
    payload = {"sicil_or_email": sicil_no, "password": password}
    if client.application.config.get("WTF_CSRF_ENABLED"):
        payload["csrf_token"] = _harvest_csrf_token(client)
    response = client.post("/login", data=payload, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _harvest_csrf_token(client) -> str:
    response = client.get("/pwa/csrf-refresh")
    assert response.status_code == 200
    token = response.get_json().get("csrf_token")
    assert token
    return token


# ---------------------------------------------------------------------------
# 1) Negatif: `/account/photo` POST akışı, çeşitli kötü niyetli `next`
#    değerlerini reddetmeli ve daima `main.account` ("/account") fallback'ine
#    düşmeli.
# ---------------------------------------------------------------------------

MALICIOUS_NEXT_TARGETS = [
    pytest.param("\\evil.example", id="bare-backslash"),
    pytest.param("/\\evil.example", id="slash-backslash-scheme-relative"),
    pytest.param("//evil.example", id="protocol-relative"),
    pytest.param("%2f%2fevil.example", id="percent-encoded-double-slash"),
    pytest.param("%5cevil.example", id="percent-encoded-backslash"),
    pytest.param(f"https://{CANONICAL_HOST}@evil.example/steal", id="userinfo-prefix-trick"),
    pytest.param(f"https://{CANONICAL_HOST}.evil.example/", id="subdomain-suffix-trick"),
    pytest.param("JaVaScript:alert(1)", id="mixed-case-dangerous-scheme"),
    pytest.param("/\r\n/evil.example", id="crlf-control-char-obfuscated-protocol-relative"),
]


@pytest.mark.parametrize("malicious_next", MALICIOUS_NEXT_TARGETS)
def test_account_change_photo_rejects_malicious_next_and_falls_back_to_account(monkeypatch, malicious_next, request):
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="p5b3b001", email=f"p5b3b.neg.{uuid.uuid4().hex[:8]}@ktb.gov.tr")
    client = app.test_client()
    _login(client, "p5b3b001")

    response = client.post(
        "/account/photo",
        data={"next": malicious_next},
        follow_redirects=False,
    )

    assert response.status_code in {301, 302, 303, 307, 308}
    location = response.headers.get("Location", "")
    assert location == "/account"
    assert "evil.example" not in location


# ---------------------------------------------------------------------------
# 2) Pozitif: güvenli hedefler onurlandırılmalı.
# ---------------------------------------------------------------------------


def test_account_change_photo_honors_safe_relative_next(monkeypatch, request):
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="p5b3b010", email="p5b3b.posrel@ktb.gov.tr")
    client = app.test_client()
    _login(client, "p5b3b010")

    response = client.post("/account/photo", data={"next": "/dashboard"}, follow_redirects=False)

    assert response.status_code in {301, 302, 303, 307, 308}
    assert response.headers["Location"] == "/dashboard"


def test_account_change_photo_honors_safe_relative_next_with_query_string(monkeypatch, request):
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="p5b3b011", email="p5b3b.posrelq@ktb.gov.tr")
    client = app.test_client()
    _login(client, "p5b3b011")

    response = client.post(
        "/account/photo", data={"next": "/dashboard?tab=security&x=1"}, follow_redirects=False
    )

    assert response.status_code in {301, 302, 303, 307, 308}
    assert response.headers["Location"] == "/dashboard?tab=security&x=1"


def test_account_change_photo_honors_canonical_absolute_next(monkeypatch, request):
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_user(app, sicil_no="p5b3b012", email="p5b3b.poscanon@ktb.gov.tr")
    client = app.test_client()
    _login(client, "p5b3b012")

    target = f"{CANONICAL_BASE_URL}/dashboard?tab=security"
    response = client.post("/account/photo", data={"next": target}, follow_redirects=False)

    assert response.status_code in {301, 302, 303, 307, 308}
    assert response.headers["Location"] == target


def test_account_change_photo_real_state_change_then_safe_redirect(monkeypatch, request):
    """Gerçek durum değişikliği (profil fotoğrafı kaldırma) + güvenli next
    birlikte doğrulanır: giriş sonrası güvenli iç yönlendirme, sahte bir
    çağrı değil, DB'yi gerçekten değiştiren tam akış üzerinden kanıtlanır.
    """
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    user_id = _create_user(app, sicil_no="p5b3b013", email="p5b3b.statechange@ktb.gov.tr")
    client = app.test_client()
    _login(client, "p5b3b013")

    response = client.post(
        "/account/photo",
        data={"remove_profile_photo": "1", "next": "/account?tab=photo"},
        follow_redirects=False,
    )

    assert response.status_code in {301, 302, 303, 307, 308}
    assert response.headers["Location"] == "/account?tab=photo"

    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user is not None
        assert user.profile_photo_path is None
        assert user.profile_photo_updated_at is not None


# ---------------------------------------------------------------------------
# 3) Sahte/farklı Host: karar `request.host`'a değil kanonik APP_BASE_URL'e
#    dayanmalı.
# ---------------------------------------------------------------------------


# NOT: "next"in test client'ın kendi o anki servis host'unu (localhost)
# hedeflediği bir HTTP round-trip senaryosu buraya BİLİNÇLİ olarak eklenmedi.
# `_redirect_guard_settings()` (app/route_support.py) TESTING=True iken dar
# bir localhost/127.0.0.1 istisnası açar (bkz. redirect_guard.py
# `allow_local_dev` sözleşmesi, zaten `test_pure_guard_local_dev_exception_is_opt_in_only`
# ile ayrıca kilitli) -- bu KASITLI bir tasarım kararıdır, host-header'a
# güvenme açığı DEĞİLDİR. "Karar request.host'a değil kanonik APP_BASE_URL'e
# dayanıyor" özelliği, aşağıdaki iki testte localhost/127.0.0.1 DIŞINDA bir
# sahte host (evil.attacker.example) ile doğrudan kanıtlanıyor.


def test_account_change_photo_direct_call_ignores_forged_host_header(monkeypatch, request):
    """Werkzeug test client'ın çerez kavanozu (cookie jar), oturumu asıl giriş
    yapılan host'a bağlar; bu yüzden gerçek bir `Host:` başlığı sahteciliğini
    hem giriş yapmış bir oturumla hem de tam bir HTTP round-trip ile aynı anda
    kanıtlamak (test-tooling kısıtı nedeniyle) mümkün değil. Bunun yerine,
    gerçek `account_change_photo` view fonksiyonunu -- mock'lanmamış, gerçek
    DB kullanıcısıyla `login_user()` ile giriş yapılmış -- sahte bir `Host`
    başlığı taşıyan gerçek bir `test_request_context` içinde doğrudan çağırıp
    aynı sonucu (host header'ın karara hiç girmediğini) kanıtlıyoruz.
    """
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    user_id = _create_user(app, sicil_no="p5b3b021", email="p5b3b.forgedhost@ktb.gov.tr")

    from flask_login import login_user

    from app.extensions import db
    from app.main_handlers import account_handlers as handlers
    from app.models import User

    with app.test_request_context(
        "/account/photo",
        method="POST",
        data={"next": "https://evil.attacker.example/steal"},
        headers={"Host": "evil.attacker.example"},
        base_url="http://evil.attacker.example",
    ):
        from flask import request

        assert request.host == "evil.attacker.example"  # sahte Host gerçekten set edildi
        user = db.session.get(User, user_id)
        login_user(user)

        response = handlers.account_change_photo()

        assert response.status_code in {301, 302, 303, 307, 308}
        location = response.headers["Location"]
        assert location == "/account"
        assert "evil.attacker.example" not in location


def test_account_change_photo_direct_call_still_honors_relative_next_under_forged_host(monkeypatch, request):
    """Yukarıdaki testin pozitif eşleniği: sahte Host başlığı meşru göreli
    yönlendirmeleri de ETKİLEMEMELİ (yanlış negatif olmamalı)."""
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    user_id = _create_user(app, sicil_no="p5b3b022", email="p5b3b.forgedhostpos@ktb.gov.tr")

    from flask_login import login_user

    from app.extensions import db
    from app.main_handlers import account_handlers as handlers
    from app.models import User

    with app.test_request_context(
        "/account/photo",
        method="POST",
        data={"next": "/dashboard"},
        headers={"Host": "evil.attacker.example"},
        base_url="http://evil.attacker.example",
    ):
        user = db.session.get(User, user_id)
        login_user(user)

        response = handlers.account_change_photo()

        assert response.headers["Location"] == "/dashboard"
