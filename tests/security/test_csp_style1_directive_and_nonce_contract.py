"""CSP "Style-1" dalgasi - style-src-elem/style-src-attr direktif + nonce
enjeksiyon kontrati (gercek Flask test client + gercek HTTP yanit dogrulamasi).

BAGLAM: Style-1, davranis-koruyan (behavior-preserving), no-op bir alt-yapi
dalgasidir. Bu dosya, ucuncu (test-yazan) ajan olarak, Agent 1 (nonce
mekanizmasi konsolidasyonu) ve Agent 2'nin (CSP config + style-tag nonce
enjeksiyonu) PARALEL calisan degisikliklerini SIYAH KUTU (black-box) olarak,
kaynak kodlarini okumadan, yalnizca gercek HTTP yanitlari uzerinden dogrular:

    - CSP header'i artik `style-src-elem` ve `style-src-attr` direktiflerini
      de icerir (mevcut `style-src` yaninda).
    - Uc direktifin HICBIRINDE `'nonce-...'` token'i YOKTUR (bu dalganin
      bilincli kapsam-disi biraktigi bir konu -- unsafe-inline + nonce ayni
      direktifte birlikte bulunursa modern tarayicilar unsafe-inline'i
      YOK SAYAR, bu da nonce'suz butun <style> bloklarini KIRAR).
    - Flask-render edilen HTML yanitlarinda `<style>` etiketleri de artik
      `<script>` etiketleriyle AYNI nonce degerini paylasir.
    - script-src'nin mevcut nonce davranisi DEGISMEMISTIR.

Bu dosyadaki testler PARALEL calisan Agent 1/2'nin degisiklikleri henuz repo
icinde yokken calistirilirsa BEKLENEN sekilde FAIL verebilir -- bu, bu test
dosyasindaki bir hata DEGILDIR; koordinator butun ajanlar bitince yeniden
calistiracaktir. Bu dosya YALNIZCA yeni bir test dosyasidir; hicbir
uygulama/config/template/CSS/JS dosyasina DOKUNULMAMISTIR.

Kapsam disi (bilincli): CSP ihlal-raporlama (report-to/report-uri) ucu
eklenmedi/test edilmedi (bkz. `test_csp_style1_repo_wide_zero_inventory_
contract.py`daki `test_no_csp_violation_report_route_exists`).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.fixture
def client(app):
    """Fresh anonymous client. These contracts render public pages (/login,
    /forgot-password, /offline); the session-scoped shared client may still be
    logged in by an earlier module, and /login then redirects (302)."""
    return app.test_client()


REPO_ROOT = Path(__file__).resolve().parents[2]

STYLE_DIRECTIVES = ["style-src", "style-src-elem", "style-src-attr"]

_SCRIPT_NONCE_RE = re.compile(r'<script\b[^>]*\bnonce="([^"]+)"', re.IGNORECASE)
_STYLE_NONCE_RE = re.compile(r'<style\b[^>]*\bnonce="([^"]+)"', re.IGNORECASE)
_HEADER_NONCE_TOKEN_RE = re.compile(r"'nonce-([A-Za-z0-9_\-]+)'")


def _csp_header_value(response) -> str:
    """Report-Only VEYA enforce header'inin hangisi varsa onu doner.

    `tests/conftest.py` `CSP_REPORT_ONLY`'yi varsayilan olarak "true" yapar
    (bkz. `os.environ.setdefault("CSP_REPORT_ONLY", "true")`), bu yuzden bu
    test suit'inde tipik olarak `Content-Security-Policy-Report-Only`
    beklenir -- ama bu dosya iki header adini da kontrol ederek hangisinin
    fiilen emit edildigine baglanmaz (spesifikasyonun kendi ifadesi:
    "Report-Only or enforced, whichever the app emits")."""
    value = response.headers.get("Content-Security-Policy")
    if value is None:
        value = response.headers.get("Content-Security-Policy-Report-Only")
    assert value, (
        "Yanitta ne 'Content-Security-Policy' ne de "
        "'Content-Security-Policy-Report-Only' header'i bulundu."
    )
    return value


def _parse_csp_directives(policy_text: str) -> dict[str, str]:
    directives: dict[str, str] = {}
    for chunk in policy_text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(None, 1)
        name = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        directives[name] = value
    return directives


# ---------------------------------------------------------------------------
# 1-3) style-src / style-src-elem / style-src-attr header'da MEVCUT.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("directive", STYLE_DIRECTIVES)
def test_style_directive_present_in_csp_header(client, directive: str) -> None:
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert directive in directives, (
        f"'{directive}' CSP header'inda bulunamadi. Mevcut direktifler: "
        f"{sorted(directives)!r}"
    )


# ---------------------------------------------------------------------------
# 4-6) Uc direktif de 'unsafe-inline' iceriyor (no-op-safe).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("directive", STYLE_DIRECTIVES)
def test_style_directive_contains_unsafe_inline(client, directive: str) -> None:
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert directive in directives, f"'{directive}' CSP header'inda bulunamadi."
    assert "'unsafe-inline'" in directives[directive].split(), (
        f"'{directive}' 'unsafe-inline' icermiyor: {directives[directive]!r}"
    )


# ---------------------------------------------------------------------------
# 7-9) Uc direktifin HICBIRINDE 'nonce-' token'i YOK (bilincli non-goal).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("directive", STYLE_DIRECTIVES)
def test_style_directive_contains_no_nonce_token(client, directive: str) -> None:
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert directive in directives, f"'{directive}' CSP header'inda bulunamadi."
    assert "'nonce-" not in directives[directive], (
        f"'{directive}' beklenmedik bir 'nonce-' token'i iceriyor: "
        f"{directives[directive]!r}. Style-1'in bilincli non-goal'u: nonce + "
        "unsafe-inline AYNI direktifte birlikte olursa modern tarayicilar "
        "unsafe-inline'i YOK SAYAR."
    )


def test_style_related_directive_default_values_match_no_op_safe_spec(client) -> None:
    """Ek saglamlik: uc direktifin TAM deger dizesi de spesifikasyondaki
    no-op-safe varsayilanlarla birebir eslesiyor (yalniz alt-string/token
    kontrolu degil)."""
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert directives.get("style-src") == "'self' 'unsafe-inline' https:"
    assert directives.get("style-src-elem") == "'self' 'unsafe-inline' https:"
    assert directives.get("style-src-attr") == "'unsafe-inline'"


# ---------------------------------------------------------------------------
# 10) script-src'nin mevcut nonce davranisi DEGISMEMIS.
# ---------------------------------------------------------------------------


def test_script_src_gets_nonce_token_when_nonce_enabled(app, client, monkeypatch) -> None:
    monkeypatch.setitem(app.config, "CSP_NONCE_ENABLED", True)
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert "script-src" in directives
    assert _HEADER_NONCE_TOKEN_RE.search(directives["script-src"]), (
        f"CSP_NONCE_ENABLED=True iken script-src'de 'nonce-...' token'i "
        f"bulunamadi: {directives['script-src']!r}"
    )


def test_script_src_has_no_bare_unsafe_inline_by_default(app, client, monkeypatch) -> None:
    monkeypatch.setitem(app.config, "CSP_ALLOW_UNSAFE_INLINE_SCRIPT", False)
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert "'unsafe-inline'" not in directives["script-src"].split(), (
        f"CSP_ALLOW_UNSAFE_INLINE_SCRIPT=False iken script-src'de ciplak "
        f"'unsafe-inline' bulundu: {directives['script-src']!r}"
    )


def test_script_src_strips_unsafe_inline_when_present_but_not_allowed(app, client, monkeypatch) -> None:
    """`build_csp_header` yalniz -- yapilandirilmis script-src degerinde
    ZATEN 'unsafe-inline' varsa ve `CSP_ALLOW_UNSAFE_INLINE_SCRIPT=False`
    ise -- onu CIKARIR (asla kendiliginden EKLEMEZ). Bu, gercek gating
    davranisini dogru sekilde tetiklemek icin CSP_SCRIPT_SRC'i BILEREK
    'unsafe-inline' iceren bir degere ayarlar."""
    monkeypatch.setitem(app.config, "CSP_SCRIPT_SRC", "'self' 'unsafe-inline' https:")
    monkeypatch.setitem(app.config, "CSP_ALLOW_UNSAFE_INLINE_SCRIPT", False)
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert "'unsafe-inline'" not in directives["script-src"].split(), (
        f"CSP_ALLOW_UNSAFE_INLINE_SCRIPT=False iken, yapilandirilmis script-src'de "
        f"'unsafe-inline' bulundugunda bile CIKARILMASI bekleniyordu: "
        f"{directives['script-src']!r}"
    )


def test_script_src_preserves_unsafe_inline_when_explicitly_allowed(app, client, monkeypatch) -> None:
    """Ayni senaryonun tersi: `CSP_ALLOW_UNSAFE_INLINE_SCRIPT=True` iken
    yapilandirilmis script-src'deki 'unsafe-inline' KORUNUR (silinmez).
    NOT: `build_csp_header` script-src icin 'unsafe-inline' degerini asla
    KENDILIGINDEN eklemez -- yalniz zaten yapilandirilmis degerdeyse silip
    silmeyecegine bu bayrakla karar verir; bu yuzden bu test de CSP_SCRIPT_SRC'i
    acikca 'unsafe-inline' iceren bir degere ayarlar."""
    monkeypatch.setitem(app.config, "CSP_SCRIPT_SRC", "'self' 'unsafe-inline' https:")
    monkeypatch.setitem(app.config, "CSP_ALLOW_UNSAFE_INLINE_SCRIPT", True)
    response = client.get("/login")
    directives = _parse_csp_directives(_csp_header_value(response))
    assert "'unsafe-inline'" in directives["script-src"].split(), (
        f"CSP_ALLOW_UNSAFE_INLINE_SCRIPT=True iken, yapilandirilmis script-src'deki "
        f"'unsafe-inline' KORUNMASI bekleniyordu, bulunamadi: {directives['script-src']!r}"
    )


# ---------------------------------------------------------------------------
# 11, 13, 14) Gercek render edilmis HTML yanitinda script/style nonce
# paylasimi, istek-basi tazelik ve HTML<->header tutarliligi.
# ---------------------------------------------------------------------------


def test_login_page_script_and_style_tags_share_identical_nonce(app, client, monkeypatch) -> None:
    monkeypatch.setitem(app.config, "CSP_NONCE_ENABLED", True)
    response = client.get("/login")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    script_nonces = set(_SCRIPT_NONCE_RE.findall(html))
    style_nonces = set(_STYLE_NONCE_RE.findall(html))

    assert script_nonces, "Render edilen /login sayfasinda nonce'lu <script> etiketi bulunamadi."
    assert style_nonces, "Render edilen /login sayfasinda nonce'lu <style> etiketi bulunamadi."
    assert len(script_nonces) == 1, f"Ayni istekte birden fazla farkli script nonce degeri bulundu: {script_nonces!r}"
    assert len(style_nonces) == 1, f"Ayni istekte birden fazla farkli style nonce degeri bulundu: {style_nonces!r}"
    assert script_nonces == style_nonces, (
        f"script nonce'lari ({script_nonces!r}) ve style nonce'lari "
        f"({style_nonces!r}) AYNI istekte AYNI degeri paylasmiyor."
    )


def test_two_separate_requests_produce_different_nonce_values(app, client, monkeypatch) -> None:
    monkeypatch.setitem(app.config, "CSP_NONCE_ENABLED", True)
    first = client.get("/login")
    second = client.get("/login")

    first_nonces = set(_SCRIPT_NONCE_RE.findall(first.get_data(as_text=True)))
    second_nonces = set(_SCRIPT_NONCE_RE.findall(second.get_data(as_text=True)))

    assert first_nonces, "Ilk istekte nonce'lu <script> etiketi bulunamadi."
    assert second_nonces, "Ikinci istekte nonce'lu <script> etiketi bulunamadi."
    assert first_nonces != second_nonces, (
        f"Iki ayri istek AYNI nonce degerini uretti ({first_nonces!r}) -- "
        "istek-basi tazelik (per-request freshness) bekleniyordu."
    )


def test_html_body_nonce_matches_csp_header_nonce_token(app, client, monkeypatch) -> None:
    monkeypatch.setitem(app.config, "CSP_NONCE_ENABLED", True)
    response = client.get("/login")
    html = response.get_data(as_text=True)

    body_nonces = set(_SCRIPT_NONCE_RE.findall(html)) | set(_STYLE_NONCE_RE.findall(html))
    directives = _parse_csp_directives(_csp_header_value(response))
    header_nonces = set(_HEADER_NONCE_TOKEN_RE.findall(directives.get("script-src", "")))

    assert body_nonces, "HTML govdesinde hic nonce degeri bulunamadi."
    assert header_nonces, "script-src header'inda hic 'nonce-...' token'i bulunamadi."
    assert body_nonces == header_nonces, (
        f"HTML govdesindeki nonce deger(ler)i ({body_nonces!r}) header'daki "
        f"'nonce-...' token deger(ler)iyle ({header_nonces!r}) birebir eslesmiyor."
    )


# ---------------------------------------------------------------------------
# 12) Zaten nonce tasiyan bir <style> etiketi IKINCI kez nonce'lanmiyor.
# Bu, HTTP uzerinden degil, dogrudan enjeksiyon fonksiyonu cagrilarak
# (spesifikasyonun acikca istedigi gibi) sentetik bir Response nesnesi
# uzerinde test edilir.
# ---------------------------------------------------------------------------


def test_style_tag_with_pre_existing_nonce_is_not_double_nonced() -> None:
    from flask import Response

    from app.security.headers import inject_csp_nonce_into_html

    original_html = (
        "<!doctype html><html><head>"
        '<style nonce="pre-existing-nonce-value">body{color:red}</style>'
        "</head><body>"
        "<script>console.log('style1 idempotency probe');</script>"
        "</body></html>"
    )
    response = Response(original_html, content_type="text/html; charset=utf-8")

    result = inject_csp_nonce_into_html(response, csp_nonce="freshly-generated-nonce")
    html = result.get_data(as_text=True)

    style_nonces = _STYLE_NONCE_RE.findall(html)
    assert style_nonces == ["pre-existing-nonce-value"], (
        f"Zaten nonce tasiyan <style> etiketine ikinci bir nonce EKLENMEMELI/"
        f"mevcut deger DEGISTIRILMEMELI. Bulunan style nonce(lar)i: {style_nonces!r}"
    )
    assert html.count('nonce="pre-existing-nonce-value"') == 1, (
        "Mevcut nonce degeri tekrarlanmis/coklanmis olabilir."
    )
    assert "freshly-generated-nonce" not in html.split("<style", 1)[1].split("</style>", 1)[0], (
        "Yeni uretilen nonce degeri, zaten nonce'lu <style> etiketinin ICINE sizmis."
    )

    # nonce'suz <script> etiketi ise YENI nonce degeriyle enjekte edilmis olmali
    # (fonksiyonun script tarafi bu senaryoda etkilenmemis olmali).
    script_nonces = _SCRIPT_NONCE_RE.findall(html)
    assert script_nonces == ["freshly-generated-nonce"], (
        f"Nonce'suz <script> etiketi beklenen YENI nonce degerini almadi: {script_nonces!r}"
    )


# ---------------------------------------------------------------------------
# 15-16) PWA statik rotalari: gercek davranis GOZLEMLENIR ve PIN'lenir
# (varsayim yapilmaz). CSP header'i (unsafe-inline dahil) her durumda hala
# uygulanir.
# ---------------------------------------------------------------------------


def test_pwa_offline_template_route_responds_without_error(app, client, monkeypatch) -> None:
    """`/offline` -- `app/pwa/routes.py::pwa_offline` -- `render_template()`
    ile donduruluyor (statik dosya passthrough'u DEGIL, bkz. kaynak kodu),
    bu yuzden CSP after_request hook'undan GECER. Bu test yalniz rotanin hata
    vermedigini ve GERCEKTEN GOZLEMLENEN nonce-enjeksiyon davranisini
    (varsayim yapmadan) PIN'ler."""
    monkeypatch.setitem(app.config, "CSP_NONCE_ENABLED", True)
    response = client.get("/offline")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    # GOZLEMLENEN GERCEK DURUM (bu ajanin elle dogruladigi calisma-zamani
    # davranisi): app/templates/pwa/offline.html <script> ETIKETI ICERMEZ
    # (Dalga 9A'nin JS-free cozumu) ama <style> ICERIR; enjeksiyon
    # fonksiyonu artik <style> varligini da ayrica kontrol ettigi icin
    # (`html_lower` kontrolu hem '<script' hem '<style' arar) style etiketi
    # nonce ALIR. Bu test bu GERCEK davranisi kilitler; eger enjeksiyon
    # fonksiyonu tekrar YALNIZCA <script varligina bakacak sekilde
    # degistirilirse (regresyon) bu test FAIL verir.
    assert "<script" not in html, (
        "PIN varsayimi bozuldu: app/templates/pwa/offline.html artik <script "
        "iceriyor gibi gorunuyor (Dalga 9A JS-free durumu degismis olabilir)."
    )
    style_nonces = _STYLE_NONCE_RE.findall(html)
    assert style_nonces, (
        "GOZLEMLENEN/PIN'lenen davranis: /offline yanitindaki <style> etiketi "
        "nonce almiyor. Eger bu KASITLI bir degisiklikse (orn. static/passthrough "
        "olmayan ama script'siz sayfalarda enjeksiyonun bilinçli atlanmasi), bu "
        "test guncellenmelidir -- aksi halde bu bir regresyon olabilir."
    )


@pytest.mark.parametrize(
    "static_path",
    ["/static/pwa/offline.html", "/static/pwa/offline-static.html"],
)
def test_pwa_static_offline_asset_route_responds_without_error(client, static_path: str) -> None:
    """Flask'in varsayilan statik dosya rotasi uzerinden servis edilen
    `app/static/pwa/offline.html` ve `app/static/pwa/offline-static.html`
    icin: hic hata/exception atmadan yanit doner. Nonce enjeksiyonu
    davranisi (varsa/yoksa) ayri asagidaki testte GOZLEMLENIR/PIN'lenir --
    burada sadece "hata vermiyor" dogrulanir."""
    response = client.get(static_path)
    assert response.status_code == 200, f"{static_path} beklenmedik durum kodu dondurdu: {response.status_code}"


def test_pwa_static_offline_asset_nonce_injection_behavior_is_pinned(app, client, monkeypatch) -> None:
    """GOZLEMLENEN GERCEK DURUM: `app/static/pwa/offline.html`, Flask'in
    statik dosya rotasi (`send_from_directory` tabanli) uzerinden servis
    edilir; bu yanit `is_streamed`/`direct_passthrough` bayraklarindan en az
    birini tasir, bu yuzden `inject_csp_nonce_into_html` erken cikar ve
    GOVDEYE HICBIR nonce enjekte EDILMEZ (bkz. `app/security/headers.py::
    inject_csp_nonce_into_html` -- statik/passthrough guard'i). Bu test bu
    GERCEK/GOZLEMLENEN davranisi kilitler; varsayim yapmaz."""
    monkeypatch.setitem(app.config, "CSP_NONCE_ENABLED", True)
    response = client.get("/static/pwa/offline.html")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "nonce=" not in html, (
        "PIN varsayimi bozuldu: /static/pwa/offline.html govdesinde artik "
        "'nonce=' bulundu -- statik dosya passthrough guard'i degismis olabilir "
        "(bu KASITLI bir iyilestirme olabilir, ama coordinator'a raporlanmali)."
    )


def test_pwa_offline_route_csp_header_style_directives_still_permit_inline_style(
    app, client, monkeypatch
) -> None:
    """Madde 16: /offline yanitinin CSP header'indaki style direktifleri
    (nonce enjekte edilsin ya da edilmesin) hala 'unsafe-inline' icerir --
    yani gercek bir tarayici, sayfanin mevcut inline <style> icerigine
    (nonce'lu olsun olmasin) izin vermeye devam eder."""
    monkeypatch.setitem(app.config, "CSP_NONCE_ENABLED", True)
    response = client.get("/offline")
    directives = _parse_csp_directives(_csp_header_value(response))
    for directive in STYLE_DIRECTIVES:
        assert directive in directives, f"/offline yanitinda '{directive}' CSP direktifi eksik."
        assert "'unsafe-inline'" in directives[directive].split(), (
            f"/offline yanitinda '{directive}' 'unsafe-inline' icermiyor: "
            f"{directives[directive]!r}"
        )


def test_pwa_static_offline_asset_csp_header_style_directives_still_permit_inline_style(client) -> None:
    """Madde 16 (statik varlik varyanti): `/static/pwa/offline.html` yaniti
    da -- govdesine nonce enjekte edilmese BILE -- after_request hook'undan
    gectigi icin ayni CSP header'ini tasir ve style direktifleri hala
    'unsafe-inline' icerir (statik dosyanin kendi inline <style> blogu
    calismaya devam eder)."""
    response = client.get("/static/pwa/offline.html")
    directives = _parse_csp_directives(_csp_header_value(response))
    for directive in STYLE_DIRECTIVES:
        assert directive in directives, f"/static/pwa/offline.html yanitinda '{directive}' CSP direktifi eksik."
        assert "'unsafe-inline'" in directives[directive].split(), (
            f"/static/pwa/offline.html yanitinda '{directive}' 'unsafe-inline' "
            f"icermiyor: {directives[directive]!r}"
        )


# ---------------------------------------------------------------------------
# 18) Jinja baglamina enjekte edilen `csp_nonce` degeri TEK ve TUTARLI bir
# tip -- callable DEGIL (`{{ csp_nonce }}` olarak kullanilan duz bir deger).
# ---------------------------------------------------------------------------


def test_csp_nonce_jinja_context_value_is_not_callable(app) -> None:
    from flask import g, render_template_string

    with app.test_request_context("/"):
        g.csp_nonce = "sabit-test-nonce-degeri-style1"
        rendered = render_template_string("{{ csp_nonce is callable }}|{{ csp_nonce }}")

    is_callable_text, value_text = rendered.split("|", 1)
    assert is_callable_text.strip() == "False", (
        f"Jinja baglaminda 'csp_nonce is callable' True donuyor -- csp_nonce "
        f"callable bir fonksiyon/metod olarak enjekte edilmis olabilir (beklenen: "
        f"duz/plain bir deger). Render ciktisi: {rendered!r}"
    )
    assert value_text.strip() == "sabit-test-nonce-degeri-style1", (
        f"{{ csp_nonce }} beklenen degeri render etmedi: {rendered!r}"
    )


def test_csp_nonce_jinja_context_value_is_none_or_str_not_other_types(app) -> None:
    """Ek tip-tutarliligi kontrolu: context processor'un dondurdugu deger
    ya `None` ya da bir `str` olmali -- baska bir tip (int, dict, callable
    wrapper vb.) OLMAMALI. Context processor'a dogrudan erisilerek (Flask'in
    kayitli `app.template_context_processors[None]` listesi uzerinden)
    dogrulanir.

    NOT: Uygulamada `csp_nonce` disinda baska app-seviyesi context
    processor'lar da kayitlidir (orn. `app/template_safety.py`,
    `app/services/assistant_role_matrix_v10.py`); bunlarin bazilari gercek
    bir istek/oturum baglaminda calismasi beklenen ek durum gerektirebilir.
    Bu test yalniz `csp_nonce` anahtarini ureten processor(lar)i ilgilendirir
    -- ilgisiz bir processor kendi ic hatasiyla basarisiz olursa (orn. eksik
    oturum/DB context'i) bu, `csp_nonce` degerlendirmesini ENGELLEMEMELIDIR;
    bu yuzden her processor ayri ayri, hata toleransli cagrilir."""
    with app.test_request_context("/"):
        from flask import g

        g.csp_nonce = None
        processors = app.template_context_processors.get(None, [])
        assert processors, "Uygulamada kayitli hicbir app-seviyesi context processor bulunamadi."

        found_csp_nonce = False
        value = None
        for processor in processors:
            try:
                result = processor()
            except Exception:  # noqa: BLE001 - ilgisiz processor hatasi bu testi engellememeli
                continue
            if isinstance(result, dict) and "csp_nonce" in result:
                found_csp_nonce = True
                value = result["csp_nonce"]

        assert found_csp_nonce, "Hicbir app-seviyesi context processor 'csp_nonce' anahtarini uretmedi."
        assert value is None or isinstance(value, str), (
            f"csp_nonce beklenmedik bir tipte: {type(value)!r} (deger: {value!r})"
        )
        assert not callable(value), f"csp_nonce callable bir deger: {value!r}"
