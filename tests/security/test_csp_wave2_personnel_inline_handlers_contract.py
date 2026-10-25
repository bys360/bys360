"""CSP strict migration -- Wave 2, Agent 2 (Personnel screens) contract.

`app/security/headers.py` script-src varsayilani `'self' https:` -- unsafe-inline
YOK. Her `<script>` etiketine (nonce'u olmayanlara) `app/bootstrap/response_hardening.py`
+ `app/security/headers.py::inject_csp_nonce_into_html` uzerinden otomatik
`nonce="..."` ekleniyor, bu yuzden dosya-ici `<script>...</script>` bloklari
zaten korunuyor. Asil risk inline EVENT ATTRIBUTE'lardi (`onclick=`, `onsubmit=`,
`onerror=` vb.) -- CSP script-src nonce/host tabanli oldugu icin bunlara nonce
uygulanmiyor ve enforce modda tarayici tarafindan calistirilmiyorlardi.

Bu dosya, Wave 2 - Ajan 2 kapsamindaki 3 personel ekraninda
(`personnel_list.html`, `personnel_edit.html`, `personnel_profile.html`) bu
deseni kaldirip data-* attribute + addEventListener kalibina tasidigini
dogrular:

  - personnel_list.html: 5 inline event-attribute (2x onclick bulk aksiyon,
    2x onsubmit confirm, 1x onerror avatar fallback) -> data-bulk-target /
    data-bulk-confirm / data-confirm-submit / data-fallback-src.
  - personnel_edit.html: 1 inline onerror -> data-fallback-src (base.html'in
    zaten var olan `img[data-fallback-src]` global dinleyicisi kullanilir).
  - personnel_profile.html: 1 inline onerror -> data-fallback-src (ayni
    mekanizma).

ONEMLI BULGU (bu dosyanin regresyon kilidi olarak da davrandigi nokta):
personnel_list.html'nin kendi `<script>` blogu, duzeltmeden once
`{% block content %}...{% endblock %}` KAPANDIKTAN SONRA, herhangi bir
named block'un DISINDA duruyordu. Jinja2 `{% extends %}` kullanan bir child
template'te, named block disinda kalan govde metni parent template'in
ciktisina HIC yansitilmaz -- yani bu script (ve icindeki `fillBulkIds`
fonksiyonu) CSP'den BAGIMSIZ olarak zaten render edilmiyordu (bu, canli
Flask test client render'i ile ampirik olarak dogrulanmistir). Duzeltme,
script'i base.html'in zaten var olan `{% block extra_scripts %}{% endblock %}`
kancasina tasir; bu olmadan yeni data-*/addEventListener kablolamasi da ayni
sekilde sessizce hicbir yere render olmazdi. Asagidaki render-tabanli testler
ozellikle bunu (kaynak kodda degil, GERCEK render edilmis HTML'de fillBulkIds
ve addEventListener'in var oldugunu) dogrular.

Bu bir static/kaynak-kod + Flask test client render kontrat testidir; gercek
bir tarayicida CSP enforce edilmis haliyle calisma zamani davranisini
DOGRULAMAZ (bkz. dosya sonundaki "Kalan riskler" notu asagida, rapor
metninde).
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

REPO_ROOT = Path(__file__).resolve().parents[2]

WAVE2_AGENT2_TEMPLATES = [
    "app/templates/personnel_list.html",
    "app/templates/personnel_edit.html",
    "app/templates/personnel_profile.html",
]

# HTML attribute syntax: bosluk + on<harfler> + '=' + tirnak. CSS/JS icindeki
# metinsel string literal'leri yanlislikla yakalamaz.
_INLINE_EVENT_ATTR_RE = re.compile(r"""[\s]on[a-zA-Z]+\s*=\s*["']""")
_JS_HREF_RE = re.compile(r"""href\s*=\s*["']\s*javascript:""", re.IGNORECASE)
_EXTRA_SCRIPTS_WRAPS_FILLBULKIDS_RE = re.compile(
    r"""\{%\s*block\s+extra_scripts\s*%\}[\s\S]*?function\s+fillBulkIds[\s\S]*?\{%\s*endblock\s*%\}"""
)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1) Statik kaynak-kod kontratlari (Path.read_text) -- ham template kaynaginda
#    inline event-attribute / javascript: href / tehlikeli JS sink kalmadigini
#    dogrular.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative_path", WAVE2_AGENT2_TEMPLATES)
def test_wave2_personnel_template_has_no_inline_event_attributes(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _INLINE_EVENT_ATTR_RE.findall(text)
    assert not matches, (
        f"{relative_path} icinde inline event-attribute (on*=) bulundu: {matches!r}. "
        "CSP script-src 'self' https: (unsafe-inline yok) altinda bunlar calismaz; "
        "data-* attribute + addEventListener kalibina cevrilmeli."
    )


@pytest.mark.parametrize("relative_path", WAVE2_AGENT2_TEMPLATES)
def test_wave2_personnel_template_has_no_javascript_href(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _JS_HREF_RE.findall(text)
    assert not matches, (
        f"{relative_path} icinde href=\"javascript:...\" bulundu: {matches!r}."
    )


@pytest.mark.parametrize("relative_path", WAVE2_AGENT2_TEMPLATES)
def test_wave2_personnel_template_has_no_javascript_url_anywhere(relative_path: str) -> None:
    """href-spesifik regex'ten bagimsiz, genel bir 'javascript:' metin taramasi.
    Bu 3 dosyanin hicbirinde (base.html'deki gibi meshru bir string-filtre
    kullanim deseni de dahil) hicbir bicimde javascript: bulunmamasi beklenir.
    """
    text = _read(relative_path)
    assert "javascript:" not in text.lower()


@pytest.mark.parametrize("relative_path", WAVE2_AGENT2_TEMPLATES)
def test_wave2_personnel_template_introduces_no_dangerous_js_sinks(relative_path: str) -> None:
    """Duzeltme sirasinda eval/new Function/document.write eklenmedigini dogrular."""
    text = _read(relative_path)
    for forbidden in ("eval(", "new Function(", "document.write("):
        assert forbidden not in text, f"{relative_path} icinde yasakli sink bulundu: {forbidden}"


def test_personnel_list_bulk_actions_use_data_attributes_not_onclick() -> None:
    text = _read("app/templates/personnel_list.html")
    assert 'data-bulk-target="bulkArchiveIds"' in text
    assert 'data-bulk-confirm="Seçili personeller arşivlensin mi?"' in text
    assert 'data-bulk-target="bulkDeleteIds"' in text
    assert 'data-bulk-confirm="Seçili personeller silinsin mi?"' in text
    assert "onclick=" not in text
    assert "querySelectorAll('[data-bulk-target]')" in text
    assert "addEventListener('click'" in text
    # fillBulkIds fonksiyonunun kendisi (dogrulama/confirm mantigi) AYNEN korunmali;
    # sadece cagrildigi yer inline attribute'tan addEventListener'a tasindi.
    assert "function fillBulkIds(targetId, confirmText)" in text


def test_personnel_list_confirm_forms_use_data_confirm_submit_not_onsubmit() -> None:
    text = _read("app/templates/personnel_list.html")
    assert text.count('data-confirm-submit="') == 2
    assert 'data-confirm-submit="Tüm personel verileri ve bağlı kayıtlar sıfırlansın mı?"' in text
    assert 'data-confirm-submit="Bu personel kaydını silmek istediğinize emin misiniz?"' in text
    assert "onsubmit=" not in text
    assert "querySelectorAll('form[data-confirm-submit]')" in text
    assert "addEventListener('submit'" in text


def test_personnel_list_script_is_inside_a_rendering_block() -> None:
    """Regresyon kilidi: script, `{% block content %}` kapandiktan sonra
    herhangi bir named block'un DISINDA birakilirsa Jinja2 onu render
    CIKTISINA HIC YANSITMAZ (bu proje icin ampirik olarak dogrulanmis bir
    davranis -- bkz. dosya basligindaki not). Script artik base.html'in
    `{% block extra_scripts %}{% endblock %}` kancasi icinde olmali."""
    text = _read("app/templates/personnel_list.html")
    assert _EXTRA_SCRIPTS_WRAPS_FILLBULKIDS_RE.search(text), (
        "personnel_list.html icindeki fillBulkIds/addEventListener script'i "
        "{% block extra_scripts %}...{% endblock %} icinde degil; bu durumda "
        "Jinja2 bu icerigi render etmez ve bulk aksiyon/onay JS'i sessizce "
        "hic calismaz."
    )


@pytest.mark.parametrize("relative_path", WAVE2_AGENT2_TEMPLATES)
def test_wave2_personnel_template_avatar_uses_data_fallback_src(relative_path: str) -> None:
    text = _read(relative_path)
    assert "onerror=" not in text
    assert "data-fallback-src=" in text
    # Mekanizma bu 3 dosyada YENIDEN tanimlanmiyor; base.html'deki mevcut
    # `img[data-fallback-src]` global dinleyicisine (Wave 1'de eklenen) guveniyor.
    assert "img[data-fallback-src]" not in text


def test_base_html_still_provides_the_shared_fallback_src_listener() -> None:
    """personnel_* sablonlarinin guvendigi paylasilan mekanizmanin base.html'de
    hala mevcut oldugunu dogrular (bu dosyanin sahiplik alani DISINDA, salt
    okunur bir on-kosul kontrolu)."""
    text = _read("app/templates/base.html")
    assert "img[data-fallback-src]" in text
    assert "addEventListener('error'" in text


# ---------------------------------------------------------------------------
# 2) Calisma-zamani render kontrolleri (gercek Flask test client + gercek admin
#    oturumu + gercek route). Bu, yalnizca kaynak kodu degil GERCEKTEN
#    RENDER EDILEN HTML'i dogrular -- yukaridaki "script named block disinda
#    kalirsa render edilmez" bulgusunu yakalayabilecek tek katmandir.
#    HALA bir gercek tarayici testi DEGILDIR: CSP enforce edilmis bir
#    tarayicida script'lerin fiilen calistigini kanitlamaz.
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "csp_wave2_personnel" / "test_dbs"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-csp-wave2-personnel-contract-min-len")
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

    # BYS360_P13B_CONFIG_ISOLATION deseniyle ayni gerekce (bkz.
    # test_account_change_photo_redirect_guard.py): Config sinif nitelikleri
    # ilk import'ta donuyor, create_app() ONCESINDE dogrudan Config'e uygulanmali.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


def _create_admin_user(app, *, sicil_no, email, password="Phase5CspWave2TestKey1!"):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="CspWave2",
            soyad="Admin",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password="Phase5CspWave2TestKey1!"):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def test_personnel_list_page_render_has_no_inline_handlers_and_renders_wired_script(monkeypatch, request) -> None:
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_admin_user(app, sicil_no="cspw2001", email="cspw2.list@ktb.gov.tr")
    client = app.test_client()
    _login(client, "cspw2001")

    response = client.get("/personnel")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_RE.search(html)

    # Regresyon kanitlamasi: bulk aksiyon data-* kancalari VE onlari kablolayan
    # script gercekten RENDER EDILMIS HTML'de mevcut (yalnizca kaynakta degil).
    assert 'data-bulk-target="bulkArchiveIds"' in html
    assert 'data-bulk-target="bulkDeleteIds"' in html
    assert 'data-confirm-submit="Tüm personel verileri ve bağlı kayıtlar sıfırlansın mı?"' in html
    assert "function fillBulkIds(targetId, confirmText)" in html
    assert "querySelectorAll('[data-bulk-target]')" in html
    assert "addEventListener('click'" in html
    assert "querySelectorAll('form[data-confirm-submit]')" in html
    assert "addEventListener('submit'" in html
    assert "data-fallback-src=" in html


def test_personnel_list_render_includes_per_row_delete_confirm_when_rows_exist(monkeypatch, request) -> None:
    """`user_rows` bos olmayan bir listede, dongu-ici Sil formunun da
    data-confirm-submit'e tasindigini (yalnizca toplu-islem alaninin degil)
    render edilmis HTML uzerinden dogrular."""
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    _create_admin_user(app, sicil_no="cspw2002", email="cspw2.list2@ktb.gov.tr")

    from app.extensions import db
    from app.models import User

    with app.app_context():
        other = User(
            sicil_no="cspw2003",
            email="cspw2.other@ktb.gov.tr",
            ad="Digger",
            soyad="Row",
            role="personel",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        other.set_password("Phase5CspWave2TestKey2!")
        db.session.add(other)
        db.session.commit()

    client = app.test_client()
    _login(client, "cspw2002")

    response = client.get("/personnel")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    # 1x toplu-sifirlama formu + en az 1x satir-ici sil formu.
    assert html.count('data-confirm-submit="') >= 2
    assert 'data-confirm-submit="Bu personel kaydını silmek istediğinize emin misiniz?"' in html


def test_personnel_edit_page_render_has_no_inline_handlers(monkeypatch, request) -> None:
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    user_id = _create_admin_user(app, sicil_no="cspw2010", email="cspw2.edit@ktb.gov.tr")
    client = app.test_client()
    _login(client, "cspw2010")

    response = client.get(f"/personnel/{user_id}/edit")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_RE.search(html)
    assert "data-fallback-src=" in html


def test_personnel_profile_page_render_has_no_inline_handlers(monkeypatch, request) -> None:
    app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(app))
    user_id = _create_admin_user(app, sicil_no="cspw2020", email="cspw2.profile@ktb.gov.tr")
    client = app.test_client()
    _login(client, "cspw2020")

    response = client.get(f"/personnel/{user_id}/profile")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_RE.search(html)
    assert "data-fallback-src=" in html
