from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

"""BYS360 Sistem Künyesi ayar okuma servisi.

Künye sayfası içeriği mevcut system_settings tablosundan okunur.
Yeni tablo veya migrasyon gerektirmez. Ayar yoksa güvenli varsayılan
kurumsal metinlerle çalışır.
"""

KUNYE_SETTING_PREFIX = "kunye."

KUNYE_DEFAULTS: dict[str, str] = {
    "eyebrow": "BYS360 Bütünleşik Yönetim Sistemi",
    "page_title": "Sistem Künyesi",
    "subtitle": "Bu sayfa, BYS360’ın kurumsal sahiplik bilgisini, proje sorumluluğunu ve sistem/yazılım yönetimi bilgisini sade, izlenebilir ve kurumsal bir çerçevede sunar.",
    "corporate_section_title": "Kurumsal Sahiplik",
    "institution_authority_label": "İmtiyaz Sahibi / Kurum Yetkilisi",
    "institution_authority_prefix": "Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı adına",
    "chair_name": "İsmail KAŞDEMİR",
    "chair_title": "Başkan",
    "system_owner_label": "Sistem Sahibi Kurum",
    "system_owner_value": "Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı",
    "corporate_responsibility_label": "Kurumsal Sorumluluk",
    "corporate_responsibility_value": "Kurum içi dijital yönetim süreçlerinin kontrollü, güvenli ve izlenebilir yürütülmesi",
    "project_section_title": "Proje Bilgileri",
    "project_owner_label": "Proje Yürütücüsü",
    "project_owner_name": "Mustafa BEKTAŞ",
    "project_owner_title": "Personel ve İdari İşler Grup Başkanı",
    "developer_label": "Geliştirici",
    "developer_name": "Havva Gülsen ÖZDEN",
    "co_developer_label": "Eş Geliştirici (Co-developer)",
    "co_developer_name": "Mustafa BEKTAŞ",
    "software_management_label": "Sistem ve Yazılım Yönetimi",
    "software_management_value": "BYS360 Proje Ekibi",
    "security_section_title": "Güvenlik ve Kullanım İlkesi",
    "security_text": "BYS360, kurum içi dijital yönetim süreçlerinin rol bazlı yetkilendirme, kayıt altına alma, denetlenebilirlik ve insan denetimli karar destek ilkeleriyle yürütülmesi amacıyla geliştirilmiştir. Sistem, idari karar yerine geçmez; yetkili kullanıcıların süreçleri daha kontrollü, güvenli ve izlenebilir biçimde yürütmesine destek olur.",
    "copyright_section_title": "Telif ve Kullanım",
    "copyright_text": "© 2026 Çanakkale Savaşları Gelibolu Tarihi Alan Başkanlığı. Her hakkı saklıdır. BYS360 yalnızca kurum içi yetkili kullanım amacıyla geliştirilmiş kurumsal dijital yönetim sistemidir.",
}


def _setting_rows() -> dict[str, str]:
    try:
        from app.models import SystemSetting
        rows = SystemSetting.query.filter(SystemSetting.setting_key.like(f"{KUNYE_SETTING_PREFIX}%")).all()
        return {
            str(row.setting_key).replace(KUNYE_SETTING_PREFIX, "", 1): str(row.value_text or "")
            for row in rows
            if getattr(row, "is_active", True)
        }
    except (SQLAlchemyError, RuntimeError, AttributeError):
        try:
            db.session.rollback()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/kunye_settings_service.py")
        return {}


def _clean_value(value: Any, fallback: str) -> str:
    text = str(value if value is not None else "").strip()
    return text if text else fallback


def build_kunye_context() -> dict[str, str]:
    rows = _setting_rows()
    context = dict(KUNYE_DEFAULTS)
    for key, default_value in KUNYE_DEFAULTS.items():
        context[key] = _clean_value(rows.get(key), default_value)
    context["settings_url"] = "/settings#system-group-kunye"
    context["settings_group_key"] = "kunye"
    return context


__all__ = ["KUNYE_DEFAULTS", "KUNYE_SETTING_PREFIX", "build_kunye_context"]
