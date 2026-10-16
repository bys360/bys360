"""BYS360 Asistanı mobil düğme ve ekran klavyesi düzeltmesi -- sözleşme testleri.

Sorun (2026-10-16, mobil emülasyonla ölçüldü):
  * bys360_assistant_chatgpt_like_v31.css içindeki medya sorgusuz
    ``min-width: 244px !important`` kuralı, 620 px ve altında etiket gizlenince
    düğmeyi 244x64 px boş kırmızı hap olarak bırakıyordu; düğmenin aria-label'ı
    yoktu ve sayfadaki düğmeleri örtüyordu.
  * Panel mobilde en az 520 px yükseklikte sabitti; ekran klavyesi açılınca
    görünür alan ~360 px'e düşüyor ve mesaj alanı / "Gönder" düğmesi
    klavyenin arkasında kalıyordu.
  * Panel kapanınca odak kayboluyordu.

Bu dosya CI'da tarayıcı olmadan çalışabilen statik sözleşmeleri sabitler.
Tarayıcıdaki ölçümler (Playwright, sahte veri, klavye simülasyonu) PR
açıklamasında; gerçek iPhone/Android ve ekran okuyucu testleri ayrıca
yapılmalıdır, bu dosya onların yerine geçmez.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
V31_CSS = REPO_ROOT / "app/static/css/bys360_assistant_chatgpt_like_v31.css"
MODULE_CSS = REPO_ROOT / "app/static/css/bys360_assistant_module.css"
MODULE_JS = REPO_ROOT / "app/static/js/bys360_assistant_module.js"
OPEN_FIX_JS = REPO_ROOT / "app/static/js/bys360_assistant_no_chat_intro_open_fix_v34.js"
BASE_HTML = REPO_ROOT / "app/templates/base.html"

FIX_START = "BYS360_ASSISTANT_MOBILE_LAUNCHER_FIX_2026_10_START"
FIX_END = "BYS360_ASSISTANT_MOBILE_LAUNCHER_FIX_2026_10_END"


def _media_blocks(css: str) -> list[tuple[str, str]]:
    """(medya koşulu, gövde) çiftleri; iç içe parantez sayılarak ayrıştırılır."""
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(r"@media([^{]+)\{", css):
        depth, i = 1, match.end()
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        blocks.append((match.group(1).strip(), css[match.end(): i - 1]))
    return blocks


def _fix_section() -> str:
    css = MODULE_CSS.read_text(encoding="utf-8")
    assert FIX_START in css and FIX_END in css, "Mobil düzeltme bölümü bys360_assistant_module.css içinde yok"
    return css[css.index(FIX_START): css.index(FIX_END)]


def test_wide_launcher_min_width_applies_only_above_620px() -> None:
    css = V31_CSS.read_text(encoding="utf-8")
    without_media = css
    for condition, body in _media_blocks(css):
        if "244px" in body:
            assert "min-width: 621px" in condition, f"244 px kuralı yanlış medya koşulunda: {condition!r}"
        without_media = without_media.replace(body, "")
    assert "244px" not in without_media, "244 px genişlik kuralı medya sorgusu dışında kaldı (mobilde boş hap)"


def test_mobile_launcher_is_a_compact_round_button_and_hidden_while_open() -> None:
    section = _fix_section()
    mobile = [body for condition, body in _media_blocks(section) if "max-width: 620px" in condition]
    assert mobile, "620 px ve altı için medya bloğu yok"
    body = mobile[0]
    assert re.search(r"\.bys360-am-launcher\s*\{[^}]*min-width:\s*56px", body)
    assert re.search(r"\.bys360-am-launcher\[aria-expanded=\"true\"\]\s*\{[^}]*display:\s*none", body)
    assert "!important" not in section_without_comments(), "Düzeltme bölümü yeni önem bayrağı eklememeli"
    assert "env(safe-area-inset-bottom" in body and "env(safe-area-inset-right" in body


def section_without_comments() -> str:
    return re.sub(r"/\*.*?\*/", "", _fix_section(), flags=re.S)


def test_mobile_panel_fits_the_visible_area_above_the_keyboard() -> None:
    section = _fix_section()
    mobile = [body for condition, body in _media_blocks(section) if "max-width: 620px" in condition][0]
    panel = re.search(r"\.bys360-am-panel\s*\{([^}]*)\}", mobile)
    assert panel and re.search(r"min-height:\s*0", panel.group(1)), "Panelin 520 px alt sınırı kaldırılmadı"
    assert "var(--bys360-am-kb" in mobile, "Klavye payı kök konumuna eklenmiyor"
    v31 = V31_CSS.read_text(encoding="utf-8")
    narrow = [body for condition, body in _media_blocks(v31) if "max-width: 720px" in condition]
    heights = [m.group(1) for body in narrow for m in re.finditer(r"\.bys360-am-panel\s*\{[^}]*height:\s*([^;]+);", body)]
    assert any("var(--bys360-am-vvh" in h for h in heights), f"Mobil panel yüksekliği görünür alanı kullanmıyor: {heights!r}"


def test_wide_screen_panel_never_exceeds_the_viewport() -> None:
    section = _fix_section()
    wide = [body for condition, body in _media_blocks(section) if "min-width: 621px" in condition]
    assert wide and re.search(r"max-height:\s*calc\(100vh - \d+px\)", wide[0])


def test_launcher_has_an_accessible_name_independent_of_the_hidden_label() -> None:
    js = MODULE_JS.read_text(encoding="utf-8")
    launcher = re.search(r"<button class=\"bys360-am-launcher\"[^']*'", js)
    assert launcher, "Düğme şablonu bulunamadı"
    start = js.index('<button class="bys360-am-launcher"')
    template = js[start: js.index(">'", start)]
    assert "aria-label=\"' + MODULE_NAME + '\"" in template
    assert "MODULE_NAME = 'BYS360 Asistanı'" in js or 'MODULE_NAME = "BYS360 Asistanı"' in js


def test_visual_viewport_tracking_is_bound_on_init() -> None:
    js = MODULE_JS.read_text(encoding="utf-8")
    assert "function bindVisualViewport(root)" in js
    body = js[js.index("function bindVisualViewport(root)"): js.index("function setOpen(root, open)")]
    for needle in ("window.visualViewport", "'--bys360-am-vvh'", "'--bys360-am-kb'", "addEventListener('resize'", "scrollIntoView"):
        assert needle in body, f"bindVisualViewport içinde {needle} yok"
    init = js[js.index("function init() {"):]
    assert init.index("bindVisualViewport(root);") < init.index("setOpen(root, opened);")


def test_closing_the_panel_returns_focus_to_the_launcher() -> None:
    for path in (MODULE_JS, OPEN_FIX_JS):
        js = path.read_text(encoding="utf-8")
        assert "focusWasInside" in js and "launcher.focus()" in js, f"{path.name}: kapanışta odak düğmeye dönmüyor"


def test_fix_is_loaded_through_the_existing_assets_only() -> None:
    """base.html değişmedi: düzeltme mevcut CSS/JS dosyalarının içinde."""
    html = BASE_HTML.read_text(encoding="utf-8")
    for asset in ("css/bys360_assistant_chatgpt_like_v31.css", "css/bys360_assistant_module.css",
                  "js/bys360_assistant_module.js", "js/bys360_assistant_no_chat_intro_open_fix_v34.js"):
        assert asset in html, f"{asset} base.html'de yüklenmiyor"
    assert html.index("bys360_assistant_chatgpt_like_v31.css") < html.index("bys360_assistant_module.css")
