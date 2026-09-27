
"""BYS360 canlı P0 HR endpoint shimleri.

Bu dosya blueprint'e dekoratörle route eklemez. Önceki sürümde aynı endpoint
iki kez register edildiğinde Flask açılışını durduran hata oluşabiliyordu:
"View function mapping is overwriting an existing endpoint function".

Bu sürüm yalnızca uygulama tamamen oluşturulduktan sonra eksik endpoint varsa
app.add_url_rule ile güvenli fallback ekler. Mevcut gerçek endpoint varsa dokunmaz.
"""
from __future__ import annotations

from collections.abc import Callable

from flask import render_template, url_for
from flask_login import login_required


def _safe_target() -> str:
    """HR fallback için güvenli hedef belirle."""
    # Önce kurum/personel sayfalarına, yoksa ana sayfaya dön.
    for endpoint in (
        "main.personnel",
        "main.personnel_list",
        "main.admin_users",
        "main.home",
        "main.index",
    ):
        try:
            return url_for(endpoint)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/institutional/hr_live_p0_shims.py:30)")
            continue
    return "/home"


def _fallback_page(title: str, message: str):
    try:
        return render_template(
            "errors/access_denied.html",
            title=title,
            message=message,
        )
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/institutional/hr_live_p0_shims.py:43")
        return (
            f"<html><head><meta charset='utf-8'><title>{title}</title></head>"
            f"<body style='font-family:Arial;padding:32px'>"
            f"<h2>{title}</h2><p>{message}</p>"
            f"<p><a href='{_safe_target()}'>Ana sayfaya dön</a></p>"
            f"</body></html>"
        )


def _make_redirect_view(title: str, message: str) -> Callable:
    def _view():
        # Gerçek sayfa yoksa beyaz ekran yerine güvenli kurumsal mesaj göster.
        return _fallback_page(title, message)

    _view.__name__ = "bys360_hr_live_p0_fallback_" + re_safe_name(title)
    # The real institutional HR pages require login; the fallback must not be
    # the only anonymous page in this area (final pre-live audit P3).
    return login_required(_view)


def re_safe_name(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "view"


def _add_if_missing(app, rule: str, endpoint: str, view_func: Callable) -> bool:
    """Endpoint zaten varsa asla yeniden ekleme; yoksa fallback ekle."""
    if endpoint in app.view_functions:
        return False
    # Aynı URL zaten varsa endpoint farklı bile olsa canlı açılışı riske atmayalım.
    for existing_rule in app.url_map.iter_rules():
        if str(existing_rule.rule) == rule:
            return False
    app.add_url_rule(rule, endpoint=endpoint, view_func=view_func, methods=["GET"])
    return True


def register_hr_live_p0_missing_shims(app) -> dict:
    """Canlıda template linklerinin 500 üretmemesi için eksik HR endpointlerini tamamlar."""
    added: list[str] = []
    skipped: list[str] = []

    candidates = [
        (
            "/institutional/hr/personnel-operations",
            "main.hr_personnel_operations",
            "Personel Operasyonları",
            "Bu alan canlı kapsamda güvenli yönlendirme modundadır. Personel işlemleri için Personel Yönetimi ekranını kullanın.",
        ),
        (
            "/institutional/hr/career-planning",
            "main.hr_career_planning",
            "Kariyer Planlama",
            "Bu alan canlı kapsamda aktif bir işlem ekranı değildir. Yetkili personel işlemleri için Personel Yönetimi ekranını kullanın.",
        ),
        (
            "/institutional/hr/reward-discipline",
            "main.hr_reward_discipline",
            "Ödül ve Disiplin",
            "Bu alan canlı kapsamda aktif bir işlem ekranı değildir. Yetkili süreçler için ilgili kurumsal ekranları kullanın.",
        ),
    ]

    for rule, endpoint, title, message in candidates:
        view = _make_redirect_view(title, message)
        if _add_if_missing(app, rule, endpoint, view):
            added.append(endpoint)
        else:
            skipped.append(endpoint)

    app.config["BYS360_HR_LIVE_P0_SHIMS"] = {"added": added, "skipped": skipped}
    return app.config["BYS360_HR_LIVE_P0_SHIMS"]
