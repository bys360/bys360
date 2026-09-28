from __future__ import annotations

from typing import Any, TypedDict

from flask import Flask
from jinja2 import ChainableUndefined


class _AboutModalDefaults(TypedDict):
    title: str
    badges: list[str]
    description: str
    application_name: str
    developer_name: str
    co_developer_name: str
    institution_name: str
    release_info: str


def _build_about_modal_context() -> dict[str, Any]:
    """Sağ üst avatar menüsündeki Hakkında penceresini ayarlardan besler.

    Bu yardımcı veritabanı hazır değilse veya ayar kayıtları henüz tohumlanmadıysa
    canlı omurgaya uygun güvenli varsayılanlarla çalışır. Böylece ana sayfa ve
    login sonrası ekranlar ayar tablosu kaynaklı bir problemde bozulmaz.
    """
    defaults: _AboutModalDefaults = {
        "title": "BYS360 Hakkında",
        "badges": ["Kurumsal Yayın", "Canlı Ortam"],
        "description": (
            "BYS360; kimlik, yetki, personel, performans, izin-vekalet, iletişim, "
            "anket, destek, raporlama ve AI karar destek alanlarını aynı kurumsal "
            "kullanım dili içinde bir araya getirir."
        ),
        "application_name": "BYS360 – Bütünleşik Yönetim Sistemi",
        "developer_name": "Havva Gülsen Özden",
        "co_developer_name": "Mustafa Bektaş",
        "institution_name": "Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı",
        "release_info": "Sürüm 1.0.0\nYapı 2026.04",
    }

    try:
        from sqlalchemy import inspect

        from app.extensions import db
        from app.models import SystemSetting

        if not inspect(db.engine).has_table("system_settings"):
            return dict(defaults)

        wanted_keys = [
            "about.modal_title",
            "about.modal_badges",
            "about.modal_description",
            "about.application_name",
            "about.developer_name",
            "about.co_developer_name",
            "about.institution_name",
            "about.release_info",
            "about.hero_subtitle",
            "general.system_name",
            "general.institution_name",
        ]
        rows = (
            db.session.query(SystemSetting)
            .filter(SystemSetting.setting_key.in_(wanted_keys), SystemSetting.is_active.is_(True))
            .all()
        )
        values = {row.setting_key: (row.value_text or "").strip() for row in rows if (row.value_text or "").strip()}

        def pick(*keys: str, fallback: str) -> str:
            for key in keys:
                value = values.get(key)
                if value:
                    return value
            return fallback

        badge_text = pick("about.modal_badges", fallback="\n".join(defaults["badges"]))
        badges = [line.strip() for line in badge_text.replace(",", "\n").splitlines() if line.strip()]
        if not badges:
            badges = defaults["badges"]

        return {
            "title": pick("about.modal_title", fallback=defaults["title"]),
            "badges": badges[:4],
            "description": pick("about.modal_description", "about.hero_subtitle", fallback=defaults["description"]),
            "application_name": pick("about.application_name", "general.system_name", fallback=defaults["application_name"]),
            "developer_name": pick("about.developer_name", fallback=defaults["developer_name"]),
            "co_developer_name": pick("about.co_developer_name", fallback=defaults["co_developer_name"]),
            "institution_name": pick("about.institution_name", "general.institution_name", fallback=defaults["institution_name"]),
            "release_info": pick("about.release_info", fallback=defaults["release_info"]),
        }
    except Exception:
        try:
            from app.extensions import db
            db.session.rollback()
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/template_safety.py)")
        return dict(defaults)


def register_template_safety(app: Flask) -> None:
    """Jinja guvenli render yardimcilarini ve AI etiket filtrelerini kaydeder."""
    app.jinja_env.undefined = ChainableUndefined
    app.jinja_env.finalize = lambda value: "" if value is None else value

    def or_dash(value: Any, fallback: str = "-") -> Any:
        if value in (None, "", [], {}, ()):  # noqa: PLC1901 - template fallback davranisi bilincli.
            return fallback
        return value

    def safe_len(value: Any) -> int:
        try:
            return len(value)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/template_safety.py:118")
            return 0

    from app.services.ai.localization import (
        ai_feature_label,
        ai_feedback_label,
        ai_module_label,
        ai_plain_label,
        ai_provider_mode_label,
        ai_recommendation_label,
        ai_redaction_type_label,
        ai_risk_label,
        ai_severity_label,
        ai_source_label,
        ai_status_label,
        ai_target_label,
        ai_tone_label,
    )
    from app.services.performance.phase5_4_status_language import (
        phase5_4_register_filters,  # BYS360_PHASE5_4_STATUS_LANGUAGE_FILTERS
    )

    app.jinja_env.filters.setdefault("or_dash", or_dash)
    app.jinja_env.filters.setdefault("safe_len", safe_len)
    phase5_4_register_filters(app)  # BYS360_PHASE5_4_STATUS_LANGUAGE_FILTERS
    app.jinja_env.filters.setdefault("ai_module_label", ai_module_label)
    app.jinja_env.filters.setdefault("ai_feature_label", ai_feature_label)
    app.jinja_env.filters.setdefault("ai_target_label", ai_target_label)
    app.jinja_env.filters.setdefault("ai_status_label", ai_status_label)
    app.jinja_env.filters.setdefault("ai_severity_label", ai_severity_label)
    app.jinja_env.filters.setdefault("ai_source_label", ai_source_label)
    app.jinja_env.filters.setdefault("ai_provider_mode_label", ai_provider_mode_label)
    app.jinja_env.filters.setdefault("ai_feedback_label", ai_feedback_label)
    app.jinja_env.filters.setdefault("ai_recommendation_label", ai_recommendation_label)
    app.jinja_env.filters.setdefault("ai_tone_label", ai_tone_label)
    app.jinja_env.filters.setdefault("ai_plain_label", ai_plain_label)
    app.jinja_env.filters.setdefault("ai_risk_label", ai_risk_label)
    app.jinja_env.filters.setdefault("ai_redaction_type_label", ai_redaction_type_label)

    app.jinja_env.globals.setdefault("or_dash", or_dash)
    app.jinja_env.globals.setdefault("safe_len", safe_len)
    app.jinja_env.globals.setdefault("ai_module_label", ai_module_label)
    app.jinja_env.globals.setdefault("ai_feature_label", ai_feature_label)
    app.jinja_env.globals.setdefault("ai_target_label", ai_target_label)
    app.jinja_env.globals.setdefault("ai_status_label", ai_status_label)
    app.jinja_env.globals.setdefault("ai_severity_label", ai_severity_label)
    app.jinja_env.globals.setdefault("ai_source_label", ai_source_label)
    app.jinja_env.globals.setdefault("ai_provider_mode_label", ai_provider_mode_label)
    app.jinja_env.globals.setdefault("ai_feedback_label", ai_feedback_label)
    app.jinja_env.globals.setdefault("ai_recommendation_label", ai_recommendation_label)
    app.jinja_env.globals.setdefault("ai_tone_label", ai_tone_label)
    app.jinja_env.globals.setdefault("ai_plain_label", ai_plain_label)
    app.jinja_env.globals.setdefault("ai_risk_label", ai_risk_label)
    app.jinja_env.globals.setdefault("ai_redaction_type_label", ai_redaction_type_label)

    # BYS360_PHASE4_4_THIRD_SUPERVISOR_SCREEN_COLUMN_CONTEXT
    try:
        from app.services.performance.third_supervisor_column_visibility import (
            has_third_supervisor_data,
            should_show_third_supervisor_column,
        )
        app.jinja_env.globals.setdefault("phase4_4_has_third_supervisor_data", has_third_supervisor_data)
        app.jinja_env.globals.setdefault("phase4_4_should_show_third_supervisor_column", should_show_third_supervisor_column)
    except Exception:
        def _phase4_4_false(*args: Any, **kwargs: Any) -> bool:
            return False
        app.jinja_env.globals.setdefault("phase4_4_has_third_supervisor_data", _phase4_4_false)
        app.jinja_env.globals.setdefault("phase4_4_should_show_third_supervisor_column", _phase4_4_false)


    @app.context_processor
    def inject_about_modal_context() -> dict[str, Any]:
        return {"about_modal_context": _build_about_modal_context()}
