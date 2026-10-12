"""BYS360 test ortamı güvenli başlangıç ve CI-safe kapsam disiplini.

Bu dosya yalnızca pytest çalışırken devreye girer. Canlı uygulama ayarlarını
ve üretim SECRET_KEY politikasını gevşetmez; test sürecinde terminalde kalmış
APP_ENV=production gibi değerlerin unit testleri gereksiz yere durdurmasını engeller.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from flask_sqlalchemy import SQLAlchemy

# Testler uygulama paketini import etmeden önce güvenli test bağlamı kurulmalıdır.
os.environ["APP_ENV"] = "testing"
os.environ["FLASK_ENV"] = "testing"
os.environ["TESTING"] = "true"
os.environ["BYS360_TESTING"] = "true"

# Bu değer canlı anahtar değildir; yalnızca pytest import zincirinde Config'in
# güçlü anahtar kontrolünü test ortamı için güvenli biçimde geçmek içindir.
os.environ["SECRET_KEY"] = "bys360-pytest-only-secret-key-2026-minimum-strong"

# Test sırasında canlı davranışı etkileyebilecek yan etkiler kapalı tutulur.
os.environ.setdefault("MAINTENANCE_MODE", "false")
os.environ.setdefault("CSP_REPORT_ONLY", "true")
os.environ.setdefault("WTF_CSRF_ENABLED", "false")
os.environ.setdefault("MAIL_SUPPRESS_SEND", "true")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

# BYS360_B2F06_PRIVATE_UPLOAD_TEST_ROOT: özel yüklemeler (mesaj/destek/portal/İK/profil
# fotoğrafı) varsayılan olarak <proje>/instance/private_uploads altına yazılır. Testler
# gerçek instance klasörüne dosya bırakmasın diye süreç başına geçici bir kök kullanılır
# (klasör yalnızca bir test dosya yazdığında oluşturulur ve oturum sonunda silinir).
_PRIVATE_UPLOAD_TEST_ROOT = Path(tempfile.gettempdir()) / f"bys360_pytest_private_uploads_{os.getpid()}"
os.environ["PRIVATE_UPLOAD_FOLDER"] = str(_PRIVATE_UPLOAD_TEST_ROOT)


def pytest_sessionfinish(session, exitstatus):
    """B2-F06: süreç başına geçici özel yükleme kökünü test oturumu bitince temizler."""
    shutil.rmtree(_PRIVATE_UPLOAD_TEST_ROOT, ignore_errors=True)

# BYS360_PHASE5_PYTEST_TEMP_CONTRACT_START
# Tam pytest paketi (özellikle tests/quality -m ci_safe ve tests/critical)
# çalıştırılırken, bu makinede pytest'in yerleşik `tmp_path` fixture'ı
# Windows kullanıcı adındaki Türkçe karakterler (ör. "Çağla Öztürk") ile
# `%LOCALAPPDATA%\Temp` altındaki derin/uzun varsayılan yol birleşimi
# yüzünden `PermissionError` ile başarısız olabilir. Bu davranış bu
# dosyadaki hiçbir koddan kaynaklanmaz ve burada otomatik olarak
# düzeltilmez (bilinçli tercih: TEMP/TMP'yi kalıcı olarak burada veya
# kullanıcının global ortamında değiştirmek, worktree dışı bir yan etki
# olur).
#
# Sözleşme: tam paket çalıştırılırken TEMP/TMP, şu üç koşulu birden
# sağlayan kısa bir dizine ayarlanmalıdır -- yalnızca test process'i için
# (örn. `set TEMP=C:\bys360_pytest_tmp` / `$env:TEMP = "C:\bys360_pytest_tmp"`
# çalıştırma öncesinde, kalıcı `setx` DEĞİL):
#   1) worktree'nin (bu repo kökünün) DIŞINDA olmalı -- worktree içine
#      koymak farklı testleri kırar (git-repo tespiti, `.gitignore`
#      kapsamı vb. karışır);
#   2) `AppData\Local\Temp` altındaki derin/varsayılan yoldan kaçınmalı;
#   3) git-dışı olmalı (git repository OLMAMALI).
# Doğrulanmış örnek: `C:\bys360_pytest_tmp`. Bununla tests/quality -m
# ci_safe 214/214 ve tests/critical 29/29 PASS elde edilmiştir (BYS360
# Phase 5 Bölüm 3C Ajan 3 doğrulaması, 2026-08-02). Bu not, koordinatörün
# ve gelecekteki turların bu ortam kısıtını her seferinde yeniden
# keşfetmesini önlemek için buraya kaydedilmiştir.
# BYS360_PHASE5_PYTEST_TEMP_CONTRACT_END

# BYS360_QUALITY9_CI_SAFE_SCOPE_DISCIPLINE_START
# CI-safe kapsamı artık burada ayrıca zorlanmıyor: `-m ci_safe` doğrudan
# pytest'in kendi marker ifadesi (bkz. pytest.ini `markers = ci_safe: ...`,
# `--strict-markers`) tarafından seçiliyor. Önceki sürümde bu dosyada bir
# `pytest_collection_modifyitems` override'ı, `-m ci_safe` aktifken toplanan
# testleri item path'ine göre (yalnızca tests/quality altındakiler) ayrıca
# zorla filtreliyordu — bu, "ci_safe" adını taşımasına rağmen fiilen marker'a
# değil path'e bakan, adıyla çelişen bir davranıştı. Bugün gerçekte tüm
# @pytest.mark.ci_safe testleri zaten tests/quality altında olduğu için o
# path-zorlaması davranışsal olarak no-op'tu: hem eski hem bu yeni (path
# filtresi olmayan, saf marker tabanlı) mekanizma `pytest --collect-only -q
# -m ci_safe` çalıştırıldığında aynı 5/1257 testi seçiyor (BYS360 Agent 2
# coverage/test-gate denetimi, 2026-07-24). Yeni bir @pytest.mark.ci_safe
# testi ileride tests/quality dışına eklenirse artık burada sessizce
# elenmeyecek (pytest_deselected ile path'e göre atılmayacak); pytest
# çekirdeğinin native markexpr seçimi geçerli olacak. Bu blok artık yalnızca
# belgeleme amaçlıdır; ayrık bir collection-modifyitems override'ı yoktur.
# BYS360_QUALITY9_CI_SAFE_SCOPE_DISCIPLINE_END

# BYS360_G3A_INTERIM_NOTES_ALEMBIC_SCHEMA_START
# performance_interim_notes Alembic'e aittir (migrations/versions/x1f3a9c5e7b2) ve ORM
# modeli yoktur; db.create_all() onu oluşturmaz, istek kodu da artık oluşturmaz. Test
# veritabanları tabloyu üretimdeki gibi migration'ın kendi upgrade() adımıyla alır.
_INTERIM_NOTES_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "x1f3a9c5e7b2_adopt_performance_interim_notes_into_alembic.py"
)


def install_interim_notes_schema(engine) -> None:
    """Run revision x1f3a9c5e7b2's upgrade() against ``engine`` (creates or adopts the table)."""
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("x1f3a9c5e7b2_test_install", _INTERIM_NOTES_MIGRATION)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()


@pytest.fixture(name="install_interim_notes_schema")
def install_interim_notes_schema_fixture():
    return install_interim_notes_schema
# BYS360_G3A_INTERIM_NOTES_ALEMBIC_SCHEMA_END

# BYS360_DEVELOPMENT_RECOMMENDATIONS_ALEMBIC_SCHEMA_START
# performance_development_recommendations tek kanonik sözleşmeye sahiptir: Alembic revision
# 29fee38a97e1'in 47 kolonluk Phase-10 şeması. ORM modeli yoktur; test veritabanları tabloyu
# migration'ın kendi upgrade() adımıyla alır.
_DEVELOPMENT_RECOMMENDATIONS_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "29fee38a97e1_adopt_performance_development_.py"
)


def install_development_recommendations_schema(engine) -> None:
    """Run revision 29fee38a97e1's upgrade() against ``engine`` (creates the canonical table)."""
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location(
        "rev_29fee38a97e1_test_install", _DEVELOPMENT_RECOMMENDATIONS_MIGRATION
    )
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()


@pytest.fixture(name="install_development_recommendations_schema")
def install_development_recommendations_schema_fixture():
    return install_development_recommendations_schema
# BYS360_DEVELOPMENT_RECOMMENDATIONS_ALEMBIC_SCHEMA_END

# BYS360_A5_P2C_TEST_DB_FIX_START
# Test-only app/client fixtures. Runtime uygulama koduna dokunmaz.
# Ama?: route smoke testlerinde g?venli, yerel ve bo? SQLite test DB yolu sa?lamak.


@pytest.fixture(scope="session")
def app():
    test_runtime = Path("reports/quality/a5_p2c_test_runtime").resolve()
    test_runtime.mkdir(parents=True, exist_ok=True)

    db_path = test_runtime / "bys360_a5_test.sqlite3"
    db_uri = "sqlite:///" + db_path.as_posix()

    os.environ["BYS360_TESTING"] = "1"
    os.environ["FLASK_ENV"] = "testing"
    os.environ["APP_ENV"] = "testing"
    os.environ["DATABASE_URL"] = db_uri
    os.environ["SQLALCHEMY_DATABASE_URI"] = db_uri

    from app import create_app

    app_obj = create_app()
    app_obj.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        DATABASE_URL=db_uri,
    )

    db: SQLAlchemy | None
    try:
        from app.extensions import db
    except Exception:
        db = None

    if db is not None:
        with app_obj.app_context(), contextlib.suppress(Exception):
            # Baz? statik/contract testlerinde schema gerekmeyebilir.
            # Runtime hatas?n? gizlememek i?in route testleri yine sonucu g?sterecek.
            db.create_all()
        with app_obj.app_context():
            install_interim_notes_schema(db.engine)

    yield app_obj


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def runner(app):
    return app.test_cli_runner()
# BYS360_A5_P2C_TEST_DB_FIX_END
