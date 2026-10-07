
"""Gelişim rehberi template yardımcıları.

BYS360_MAINTENANCE_V13_P1_TEMPLATE_HELPERS
"""
from __future__ import annotations

from flask import Flask


def register_development_guidance_helpers(app: Flask) -> None:
    """Karne ve PDF şablonları için Gelişim Rehberi yardımcılarını güvenli bağlar."""
    if getattr(app, "_bys360_phase11_development_guidance_helpers_registered", False):
        return

    @app.context_processor
    def _bys360_phase11_development_guidance_context() -> dict[str, object]:
        def _get_scorecard_development_guidance(employee_id: object = None, period_id: object = None, limit: int = 10) -> list[dict[str, object]]:
            # Kanonik okuyucu geçerli sorgu üretir; beklenmeyen veritabanı hatası boş liste ile
            # gizlenmez (PostgreSQL'de işlemi bozuk bırakıp sonraki sorguları düşürürdü).
            from app.performance.phase10_development_guidance_ui import (
                get_scorecard_development_guidance,
            )

            return get_scorecard_development_guidance(employee_id=employee_id, period_id=period_id, limit=limit)

        return {"get_scorecard_development_guidance": _get_scorecard_development_guidance}

    app._bys360_phase11_development_guidance_helpers_registered = True  # type: ignore[attr-defined]
