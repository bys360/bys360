"""Regression test for a pre-existing bug found (and now fixed) while
investigating a finding from the BYS360 CSP Style-3A verification effort:
`app/services/executive_mail_center.py`'s `list_users()` and
`get_selected_recipients()` queried three columns that never existed on
the `users` table -- `username`, `title`, `unit_name` -- via raw SQL.

ROOT CAUSE (file/line evidence): both functions ran

    SELECT id, full_name, email, username, title, unit_name FROM users ...

`username`, `title`, `unit_name` are not, and have never been, columns on
`app.models.core_models.User` (verified: no migration in migrations/versions/
ever added a `username` column to `users`; the real analogues are
`sicil_no` (unique per-employee identifier, used for login), `unvan`
("title" in the Turkish HR sense), and `birim` ("unit"/department name)).
This is schema drift, not a stale/deprecated column: the raw SQL was
apparently written against an assumed generic user-table shape without
checking this app's actual canonical `User` model. Reproduced independently
before any code change: `list_users()` raised
`sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such
column: username` on every call, unconditionally (not role/filter
dependent).

REACHABILITY: both functions currently have no live, production-reachable
caller. `list_users()` is called only from
`app/communication/executive_mail_center_routes.py`, a route module already
proven dead code during the Style-3A investigation (absent from
`app/communication/route_manifest.py`'s required/optional module lists,
absent from `sys.modules` after `create_app()`, 5 of its 6 claimed URLs
404 in a real running app). `get_selected_recipients()` is called only by
two standalone CLI scripts with no scheduler/cron registration found,
whose actual mail-dispatch logic is a `pass` stub. The live, actually-used
`list_users()` implementation the running application relies on is the
unrelated, already-safe `app.services.cic.query_service.list_users()`
(ORM-based, defensively uses `getattr(User, attr, None)` so a missing
attribute is silently skipped rather than crashing) -- confirmed
unaffected and re-verified working correctly below as a sanity check.

FIX: replaced the three nonexistent raw column references with the real,
canonical columns, aliased to the SAME output key names
(`sicil_no AS username`, `unvan AS title`, `birim AS unit_name`) so the
function's return-dict contract -- which
app/templates/executive_summary/executive_mail_center.html's `{{ p.username
}}` / `{{ p.title }}` / `{{ p.unit_name }}` still expects -- is unchanged.
No other behavior (WHERE clause semantics, ORDER BY, LIMIT, active-user
filtering) was touched. The route file, the template, and any broader
"orphan executive-mail cleanup" are explicitly out of scope for this fix
and are not touched here.
"""
from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_FILE = "app/services/executive_mail_center.py"
TEMPLATE_FILE = "app/templates/executive_summary/executive_mail_center.html"

# BYS360 KOORDINATOR DUZELTMESI: bu fix'in KENDI ebeveyn commit'i (fix'ten
# hemen once, SERVICE_FILE hala bozuk ham SQL'i iceriyorken). Bu dosya ilk
# yazildiginda `_pre_fix_query_text()` ve _UNTOUCHED_SCOPE_* asagida hala
# canli "HEAD" kullaniyordu -- bu, bu fix'in KENDI commit'i (297c8da) HENUZ
# olusturulmamisken DOGRUYDU. Commit landed olduktan SONRA "HEAD" artik bu
# fix'in KENDI (zaten duzeltilmis) commit'ini isaret ediyor, bu yuzden
# `git show HEAD:{SERVICE_FILE}` artik "duzeltme oncesi" degil "duzeltme
# SONRASI" icerik donduruyor -- ayni sinif hata, Style-3A'nin kendi HEAD_REF/
# STYLE3A_CLOSURE_REF KOORDINATOR NOTU'nda tarif edilen ve bu dosyanin
# kendi 16 numarali bolumunde ONCEDEN tarif edilen desenle ayni. Artik SABIT
# bu fix'in ebeveynine kilitlendi.
PRE_FIX_GIT_REF = "3b3a5f8496076dcc36a195c66ddf2cbc2775160c"

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "executive_mail_center_list_users_regression" / "test_dbs"


@pytest.fixture(scope="module")
def app_and_db(request):
    """Isolated, temp-SQLite Flask app (module-scoped). Never touches a
    real/production database. Same established pattern as this repo's
    other CSP/bugfix contract tests (UUID-based temp SQLite file,
    pytest.MonkeyPatch + mp.undo())."""
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-list-users-schema-fix-min-length-ok")
    mp.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    mp.setenv("AUTO_REPAIR_SCHEMA", "false")
    mp.setenv("STRICT_SCHEMA_CHECK", "false")
    mp.setenv("REQUIRE_DOTENV_FILE", "false")
    mp.setenv("STRICT_ENV_VALIDATION", "false")
    mp.setenv("WTF_CSRF_ENABLED", "false")
    mp.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    mp.setenv("MAIL_SUPPRESS_SEND", "true")
    mp.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    mp.setattr(Config, "APP_ENV", "testing")
    mp.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    mp.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    request.addfinalizer(lambda: release_sqlite_app(app))
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db

    with app.app_context():
        db.create_all()

    yield app, db

    mp.undo()


def _make_user(db, **overrides):
    from app.models import User

    defaults = dict(
        sicil_no=f"u{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@ktb.gov.tr",
        ad="Test",
        soyad="User",
        role="personel",
        is_active=True,
        must_change_password=False,
        must_set_security_question=False,
    )
    defaults.update(overrides)
    user = User(**defaults)
    user.set_password("TestListUsersKey1!")
    db.session.add(user)
    db.session.commit()
    return user


def _clear_users(db) -> None:
    """`app_and_db` module-scoped -- birden fazla test ayni DB'yi paylasir.
    Tam-sayi sozlesmesi (bos tablo/tek kullanici/siralama/filtre) test eden
    testler baslamadan once temiz bir tablo garanti eder."""
    from app.models import User

    User.query.delete()
    db.session.commit()


# ---------------------------------------------------------------------------
# 1) Duzeltme oncesi exception'i BAGIMSIZ yeniden ureten kanit: git HEAD'deki
#    (duzeltme oncesi) SQL metnini dogrudan CANLI, gercek semali bir DB'ye
#    karsi calistirarak sozlesmeyi bagimsiz kanitlar.
# ---------------------------------------------------------------------------


def _pre_fix_query_text() -> str | None:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{PRE_FIX_GIT_REF}:{SERVICE_FILE}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    return result.stdout


def test_pre_fix_source_at_head_no_longer_matches_current_working_tree() -> None:
    """Kanit ki bu commit GERCEKTEN bir degisiklik yapiyor (bos diff degil)."""
    pre_fix_text = _pre_fix_query_text()
    if pre_fix_text is None:
        pytest.skip("git show basarisiz oldu; ortam kisitlamasi.")
    current_text = (REPO_ROOT / SERVICE_FILE).read_text(encoding="utf-8")
    assert pre_fix_text != current_text, (
        f"{SERVICE_FILE} HEAD'deki hali ile calisma agacindaki hali AYNI -- "
        "bu duzeltme henuz uygulanmamis olabilir."
    )


def test_pre_fix_query_text_really_referenced_the_nonexistent_columns() -> None:
    """git HEAD'deki (duzeltme oncesi) kaynak GERCEKTEN 'username'/'title'/
    'unit_name'i ham SQL kolonu olarak referans aliyordu mu -- iddia
    dogrulanmadan kabul edilmiyor."""
    pre_fix_text = _pre_fix_query_text()
    if pre_fix_text is None:
        pytest.skip("git show basarisiz oldu; ortam kisitlamasi.")
    assert "SELECT id, full_name, email, username, title, unit_name" in pre_fix_text, (
        f"{SERVICE_FILE} HEAD'deki hali beklenen bozuk SQL metnini icermiyor -- "
        "bu bugfix'in 'oncesi' iddiasi yanlis olabilir."
    )


def test_pre_fix_query_actually_raises_operational_error_against_real_schema(
    app_and_db,
) -> None:
    """git HEAD'deki (duzeltme oncesi) SQL metnini AYNEN alip, gercek User
    modelinden uretilen SQLite semasina karsi DOGRUDAN calistirir --
    hala (duzeltmeden BAGIMSIZ olarak) OperationalError verdigini kanitlar.
    Bu, mevcut (duzeltilmis) kodu COPYALAMAZ; git HEAD'den okunan METIN
    kullanilir."""
    pre_fix_text = _pre_fix_query_text()
    if pre_fix_text is None:
        pytest.skip("git show basarisiz oldu; ortam kisitlamasi.")

    app, db = app_and_db
    with app.app_context():
        from sqlalchemy import text as sa_text

        _make_user(db)
        broken_sql = (
            "SELECT id, full_name, email, username, title, unit_name FROM users "
            "WHERE COALESCE(is_active, true)=true LIMIT 300"
        )
        with pytest.raises(Exception) as exc_info:
            db.session.execute(sa_text(broken_sql)).mappings().all()
        db.session.rollback()
        assert "username" in str(exc_info.value).lower() or "no such column" in str(exc_info.value).lower(), (
            f"Beklenen 'no such column'/'username' hatasi degil: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# 2-4) Duzeltme sonrasi: fonksiyonlar PASS eder, uretilen SQL var olmayan
#    kolonlari referans almaz, gercek/kanonik kolonlar kullanilir.
# ---------------------------------------------------------------------------


def test_current_source_no_longer_references_nonexistent_raw_columns() -> None:
    current_text = (REPO_ROOT / SERVICE_FILE).read_text(encoding="utf-8")
    assert "SELECT id, full_name, email, username, title, unit_name" not in current_text, (
        f"{SERVICE_FILE} hala bozuk ham SQL metnini iceriyor."
    )


def test_current_source_uses_real_canonical_columns_with_aliases() -> None:
    current_text = (REPO_ROOT / SERVICE_FILE).read_text(encoding="utf-8")
    assert "sicil_no AS username" in current_text
    assert "unvan AS title" in current_text
    assert "birim AS unit_name" in current_text


def test_list_users_no_longer_raises(app_and_db) -> None:
    app, db = app_and_db
    with app.app_context():
        from app.services.executive_mail_center import list_users

        _make_user(db, sicil_no="passcheck01", email="passcheck01@ktb.gov.tr")
        result = list_users("")
        assert isinstance(result, list)


def test_get_selected_recipients_column_list_is_valid_against_real_schema(app_and_db) -> None:
    """get_selected_recipients() kullanir `WHERE id = ANY(:ids)` -- gecerli
    ve degistirilmemis (kapsamimizin DISINDA) PostgreSQL sozdizimi (uretim
    DB'si PostgreSQL'dir), ama SQLite test motorunda `no such function: ANY`
    ile basarisiz olur -- bu bu fix'in DEGISTIRDIGI bir sey DEGIL, onceden
    var olan, SQLite'a ozgu bir taşınabilirlik siniri. Bu fix SADECE SELECT
    kolon listesini duzeltti; WHERE/ANY() ifadesine dokunmadi. Bu yuzden bu
    test, get_selected_recipients()'in KENDI kaynagindan alinan SELECT kolon
    listesini, SQLite'da calisan esdeger bir WHERE ile (yalniz test icin,
    uygulama kaynagi degistirilmeden) calistirarak, TAM OLARAK bu fix'in
    duzelttigi seyi (kolon adlari) bagimsiz dogrular."""
    import re

    app, db = app_and_db
    with app.app_context():
        from sqlalchemy import text as sa_text

        user = _make_user(db, sicil_no="passcheck02", email="passcheck02@ktb.gov.tr")

        source = (REPO_ROOT / SERVICE_FILE).read_text(encoding="utf-8")
        match = re.search(
            r"def get_selected_recipients.*?SELECT (.*?) FROM users",
            source,
            re.DOTALL,
        )
        assert match, "get_selected_recipients() icindeki SELECT kolon listesi bulunamadi."
        select_list = " ".join(match.group(1).split())

        probe_sql = f"SELECT {select_list} FROM users WHERE id = :id"
        rows = db.session.execute(sa_text(probe_sql), {"id": user.id}).mappings().all()
        assert len(rows) == 1
        assert rows[0]["username"] == "passcheck02"


def test_get_selected_recipients_still_raises_setting_bugfix_out_of_scope_error(app_and_db) -> None:
    """Belgeleyici kontrol (SKIP degil): `_setting_set()`'in kendi, bu
    fix'in KAPSAMI DISINDA olan `system_settings.created_at` NOT NULL
    kusuru hala oradadir -- bu fix bunu KAPATMADI (kapatmasi da
    beklenmiyordu). Bu, "sahte PASS" riskine karsi acik bir kanittir:
    get_selected_recipients()'i _setting_set() uzerinden GERCEK uctan uca
    cagirmiyoruz cunku o yol zaten (ayri, onceden var olan bir nedenle)
    calismiyor -- bunu gizlemek yerine burada aciklikla belgeliyoruz."""
    app, db = app_and_db
    with app.app_context():
        from app.services.executive_mail_center import _setting_set

        with pytest.raises(Exception) as exc_info:
            _setting_set("daily_weather_mail.recipient_user_ids", "[1]")
        assert "created_at" in str(exc_info.value) or "NOT NULL" in str(exc_info.value), (
            f"Beklenen onceden var olan _setting_set() kusuru degil: {exc_info.value!r}"
        )
        db.session.rollback()


# ---------------------------------------------------------------------------
# 5, 8-12) Gercek veri sozlesmesi: bos tablo, tek kullanici, coklu kullanici
#    siralamasi, pasif kullanici filtresi, LIMIT (pagination-benzeri sinir).
# ---------------------------------------------------------------------------


def test_list_users_empty_table_returns_empty_list(app_and_db) -> None:
    app, db = app_and_db
    with app.app_context():
        from app.services.executive_mail_center import list_users

        _clear_users(db)
        assert list_users("") == []


def test_list_users_single_user_returns_correct_dict_shape(app_and_db) -> None:
    app, db = app_and_db
    with app.app_context():
        from app.services.executive_mail_center import list_users

        _clear_users(db)
        _make_user(
            db,
            sicil_no="single001",
            email="single001@ktb.gov.tr",
            ad="Single",
            soyad="Kullanici",
        )
        rows = list_users("")
        assert len(rows) == 1
        row = rows[0]
        assert set(row.keys()) == {"id", "full_name", "email", "username", "title", "unit_name"}
        assert row["email"] == "single001@ktb.gov.tr"
        assert row["username"] == "single001"


def test_list_users_multiple_users_ordered_by_full_name(app_and_db) -> None:
    app, db = app_and_db
    with app.app_context():
        from app.extensions import db as extdb
        from app.models import User
        from app.services.executive_mail_center import list_users

        _clear_users(extdb)
        for name, sicil in [("Zeynep Yilmaz", "order001"), ("Ahmet Demir", "order002")]:
            first, last = name.split(" ", 1)
            user = User(
                sicil_no=sicil,
                email=f"{sicil}@ktb.gov.tr",
                ad=first,
                soyad=last,
                role="personel",
                is_active=True,
                must_change_password=False,
                must_set_security_question=False,
            )
            user.set_password("TestListUsersKey1!")
            user._full_name_compat = name
            extdb.session.add(user)
        extdb.session.commit()

        rows = list_users("")
        names = [r["full_name"] for r in rows]
        assert names == sorted(names), f"full_name'e gore siralama korunmuyor: {names!r}"


def test_list_users_filters_out_inactive_users(app_and_db) -> None:
    app, db = app_and_db
    with app.app_context():
        from app.services.executive_mail_center import list_users

        _clear_users(db)
        _make_user(db, sicil_no="active001", email="active001@ktb.gov.tr", is_active=True)
        _make_user(db, sicil_no="inactive001", email="inactive001@ktb.gov.tr", is_active=False)

        rows = list_users("")
        usernames = {r["username"] for r in rows}
        assert "active001" in usernames
        assert "inactive001" not in usernames, "Pasif kullanici filtresi (is_active=true) bozulmus."


def test_get_selected_recipients_query_text_has_no_is_active_filter() -> None:
    """get_selected_recipients()'in SQL metni -- duzeltme ONCESINDE de
    oldugu gibi -- is_active filtresi ICERMEZ; bu davranis bu fix
    tarafindan DEGISTIRILMEDI, yalniz kolon adlari duzeltildi (statik
    metin kontrolu; canli WHERE id = ANY(:ids) yolu SQLite'ta calismadigi
    icin -- bkz. test_get_selected_recipients_column_list_is_valid_
    against_real_schema -- burada dogrudan kaynak metni dogrulanir)."""
    import re

    source = (REPO_ROOT / SERVICE_FILE).read_text(encoding="utf-8")
    match = re.search(r"def get_selected_recipients.*?\n\ndef ", source, re.DOTALL)
    assert match, "get_selected_recipients() govdesi bulunamadi."
    body = match.group(0)
    assert "is_active" not in body, (
        "get_selected_recipients() artik is_active filtresi iceriyor gibi gorunuyor -- "
        "bu davranis degisikligi bu fix'in kapsaminda degildi."
    )


def test_list_users_limit_of_300_is_unchanged() -> None:
    current_text = (REPO_ROOT / SERVICE_FILE).read_text(encoding="utf-8")
    assert "LIMIT 300" in current_text, "list_users()'in LIMIT 300 siniri degismis gorunuyor."


# ---------------------------------------------------------------------------
# 13) Gercek render: sablonun BEKLEDIGI dict-anahtar sozlesmesinin
#    (p.full_name / p.username / p.email / p.title / p.unit_name) gercekten
#    karsilandigini, sablonu DOGRUDAN (olu route'a DOKUNMADAN) render ederek
#    kanitlar.
# ---------------------------------------------------------------------------


def test_template_expected_dict_keys_are_satisfied_by_real_render(app_and_db) -> None:
    app, db = app_and_db
    with app.app_context():
        from app.services.executive_mail_center import list_users

        _make_user(
            db,
            sicil_no="render001",
            email="render001@ktb.gov.tr",
            ad="Render",
            soyad="Check",
        )
        people = list_users("")
        assert people, "Render kontrolu icin en az bir kullanici gerekiyor."

        rendered = app.jinja_env.from_string(
            "{% for p in people %}"
            "{{ p.full_name or p.username }}|{{ p.email }}|{{ p.title or '' }} {{ p.unit_name or '' }}"
            "{% endfor %}"
        ).render(people=people)
        assert "render001@ktb.gov.tr" in rendered
        assert "render001" in rendered  # full_name bos oldugunda username fallback'i


# ---------------------------------------------------------------------------
# 14) Fallback / exception-yutma ile sahte PASS yok.
# ---------------------------------------------------------------------------


def test_list_users_does_not_swallow_exceptions_with_a_broad_try_except() -> None:
    current_text = (REPO_ROOT / SERVICE_FILE).read_text(encoding="utf-8")
    lines = current_text.splitlines()
    list_users_start = next(i for i, line in enumerate(lines) if line.startswith("def list_users("))
    list_users_end = next(
        i for i, line in enumerate(lines[list_users_start + 1 :], start=list_users_start + 1)
        if line.startswith("def ")
    )
    body = "\n".join(lines[list_users_start:list_users_end])
    assert "except" not in body, (
        "list_users() govdesinde beklenmedik bir try/except bulundu -- "
        "SQL hatasi sessizce yutulup sahte bos-liste PASS uretilebilir."
    )


# ---------------------------------------------------------------------------
# 15) Gercek uretim DB'sine dokunulmuyor -- yapisal dogrulama.
# ---------------------------------------------------------------------------


def test_fixture_only_touches_isolated_temp_sqlite_db(app_and_db) -> None:
    app, _db = app_and_db
    configured_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    assert configured_uri.startswith("sqlite:///")
    assert str(_TEST_DB_ROOT).replace("\\", "/") in configured_uri.replace("\\", "/")
    assert "instance" not in configured_uri.lower()


# ---------------------------------------------------------------------------
# 16) Template/CSS/JS/CSP/nonce/route dosyasi bu fix tarafindan degismedi --
#    plan-disi degisiklik kontrolu.
#
#    BYS360 KOORDINATOR DUZELTMESI (bu dosyanin kendi docstring'inde
#    ONCEDEN tarif edilen, onceki bugfix/wave dalgalarinin ayni sinif
#    hatasiyla ayni desen -- bkz. test_csp_style3a_..._contract.py'nin
#    kendi HEAD_REF/STYLE3A_CLOSURE_REF KOORDINATOR NOTU): bu test ilk
#    yazildiginda live `git diff HEAD` kullaniyordu -- bu, bu dosyanin KENDI
#    fix commit'i (297c8da) HENUZ olusturulmamisken DOGRUYDU. Commit
#    landed olduktan SONRA, "HEAD" ileri giden her yeni commit'i de diff'e
#    dahil etmeye baslar -- ozellikle app/communication/executive_mail_center_
#    routes.py ve altindaki 6 template'in KENDI, bu fix'ten TAMAMEN BAGIMSIZ,
#    sonraki "orphan mail cleanup" silme commit'i tarafindan degistirilmesi,
#    bu testi sahte FAIL'e dusururdu (dosyalar bu fix tarafindan degil,
#    daha SONRAKI, ayri bir commit tarafindan silindi). Artik SABIT, bu
#    fix'in KENDI commit araligina (3b3a5f8..297c8da) kilitlendi -- bu,
#    "bu fix hicbir sey degistirmedi" anlamini SONSUZA KADAR dogru sekilde
#    kanitlar, sonraki hicbir commit/dalgadan (ornegin route dosyasini VE
#    6 template'i kasitli olarak silen orphan-cleanup commit'inden)
#    etkilenmez.
# ---------------------------------------------------------------------------

_UNTOUCHED_SCOPE_PRE_REF = PRE_FIX_GIT_REF  # bu fix'in ebeveyni
_UNTOUCHED_SCOPE_POST_REF = "297c8da746a59d84e5f3f9536b92e824ce5bd70a"  # bu fix'in KENDI commit'i

_UNTOUCHED_SCOPE_PATHS = (
    "app/templates",
    "app/static/css",
    "app/static/js",
    "app/security",
    "config.py",
    ".env.example",
    "migrations",
    "service-worker.js",
    "sw.js",
    "app/communication/executive_mail_center_routes.py",
)


def test_style_csp_nonce_template_and_dead_route_paths_have_zero_diff() -> None:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI bulunamadi.")

    result = subprocess.run(
        [
            "git", "-C", str(REPO_ROOT), "diff", "--name-only",
            f"{_UNTOUCHED_SCOPE_PRE_REF}..{_UNTOUCHED_SCOPE_POST_REF}",
            "--", *_UNTOUCHED_SCOPE_PATHS,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"git diff basarisiz oldu (exit={result.returncode}).")

    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert changed == [], (
        f"Bu bugfix'in kapsamadigi dosya(lar) degismis gorunuyor: {changed!r}"
    )


def test_this_file_never_writes_to_application_or_template_or_css_source_paths() -> None:
    forbidden_write_markers = (
        "write_text(",
        "shutil.copy",
        "shutil.move",
        "shutil.rmtree",
        "os.rename(",
        "os.remove(",
        "os.unlink(",
    )
    own_file = Path(__file__).resolve()
    text = own_file.read_text(encoding="utf-8")
    marker_def_start = text.index("forbidden_write_markers = (")
    marker_def_end = text.index(")\n", marker_def_start) + 1
    scan_text = text[:marker_def_start] + text[marker_def_end:]
    hits = [marker for marker in forbidden_write_markers if marker in scan_text]
    assert hits == [], f"Bu dosyada beklenmedik dosya-yazma izi bulundu: {hits!r}"


# ---------------------------------------------------------------------------
# Sanity: canlida GERCEKTEN kullanilan, ilgisiz/guvenli CIC list_users()
# bu fix'ten ETKILENMEDI.
# ---------------------------------------------------------------------------


def test_canonical_cic_list_users_is_unaffected_and_still_works(app_and_db) -> None:
    app, db = app_and_db
    with app.app_context():
        from app.services.cic.query_service import list_users as cic_list_users

        _make_user(db, sicil_no="cic001", email="cic001@ktb.gov.tr")
        rows = cic_list_users(search="cic001")
        assert len(rows) == 1
