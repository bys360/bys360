"""Contract: every registered route is authenticated unless it is an intentional public endpoint.

Built from scripts/quality/bys360_authorization_matrix.py (the generator of
reports/quality/BYS360_AUTHORIZATION_MATRIX_V1.json). A new anonymous route must be
added to that script's public hints on purpose; the endpoints fixed on 2026-09-28
must stay gated.
"""
from __future__ import annotations

import pytest

from scripts.quality import bys360_authorization_matrix as matrix


@pytest.fixture(scope="module")
def rows():
    app = matrix._app()
    with app.app_context():
        return matrix.build(app)["routes"]


def test_no_unauthenticated_route_outside_the_intentional_public_set(rows):
    anonymous = sorted(r["endpoint"] for r in rows if not r["authenticated"] and r["classification"] != "PUBLIC_INTENTIONAL")
    assert anonymous == []


def test_fixed_endpoints_stay_gated(rows):
    by_endpoint = {r["endpoint"]: r for r in rows}
    fixed = {e: review for e, (_, review) in matrix.MANUAL_REVIEW.items() if review.startswith("FIXED")}
    assert fixed, "the manual review list lost its fixed entries"
    for endpoint in fixed:
        row = by_endpoint[endpoint]
        if row["classification"] == "PUBLIC_INTENTIONAL":
            continue
        assert row["authenticated"], endpoint
        assert row["classification"] in {"ROLE_GATED", "OBJECT_GATED"}, endpoint


def test_manual_review_entries_name_real_endpoints(rows):
    endpoints = {r["endpoint"] for r in rows}
    assert sorted(set(matrix.MANUAL_REVIEW) - endpoints) == []
