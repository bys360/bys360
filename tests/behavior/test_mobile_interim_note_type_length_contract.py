"""Real service calls against reflected 40/80-column types; rejection preserves data."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from flask import Flask, jsonify

from scripts.quality.bys360_postgres_migration_integrity_gate import (
    HISTORICAL_PRODUCTION_PG_DDL,
    HISTORICAL_PRODUCTION_PG_INDEXES,
)


@pytest.fixture(params=[40, 80])
def note_app(request, install_interim_notes_schema):
    from app.extensions import db

    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://")
    db.init_app(flask_app)
    with flask_app.app_context():
        if request.param == 80:
            install_interim_notes_schema(db.engine)
        else:
            with db.engine.begin() as conn:
                conn.execute(sa.text(HISTORICAL_PRODUCTION_PG_DDL.replace("id SERIAL PRIMARY KEY", "id INTEGER PRIMARY KEY")))
                for name, cols in HISTORICAL_PRODUCTION_PG_INDEXES.items():
                    conn.execute(sa.text(f"CREATE INDEX {name} ON performance_interim_notes ({cols})"))
        yield flask_app, request.param
        db.session.remove()
        db.engine.dispose()


def _create(flask_app, note_type):
    from app.api.mobile.services.performance_note_route_services import (
        phase3c_mobile_performance_create_in_period_note_v2853_service,
    )
    from app.extensions import db
    from app.services.performance.interim_notes_runtime import ensure_interim_notes_table

    with flask_app.test_request_context("/", method="POST", json={"note": "Synthetic note", "note_type": note_type}):
        return phase3c_mobile_performance_create_in_period_note_v2853_service(SimpleNamespace(id=77), {
            "_has_global_scope": lambda user: False,
            "_v2853_ensure_interim_notes_table": ensure_interim_notes_table,
            "_v2853_note_bool": lambda value, default: default if value is None else bool(value),
            "_v2853_note_type_label": lambda value: value,
            "db": db, "jsonify": jsonify, "logger": logging.getLogger(__name__),
        })


def test_reflected_maximum_is_saved_exactly(note_app):
    from app.extensions import db

    flask_app, limit = note_app
    response = _create(flask_app, "ş" * limit)
    assert response.status_code == 200
    assert db.session.execute(sa.text("SELECT note_type FROM performance_interim_notes")).scalar_one() == "ş" * limit


def test_historical_41_characters_is_rejected_before_any_write(note_app):
    from app.extensions import db

    flask_app, limit = note_app
    response = _create(flask_app, "x" * 41)
    if limit == 40:
        assert response[1] == 400
        assert db.session.execute(sa.text("SELECT count(*) FROM performance_interim_notes")).scalar_one() == 0
    else:
        assert response.status_code == 200
        assert db.session.execute(sa.text("SELECT note_type FROM performance_interim_notes")).scalar_one() == "x" * 41


def test_canonical_truncation_contract_and_historical_no_truncation(note_app):
    from app.extensions import db

    flask_app, limit = note_app
    response = _create(flask_app, "x" * 81)
    if limit == 40:
        assert response[1] == 400
        assert db.session.execute(sa.text("SELECT count(*) FROM performance_interim_notes")).scalar_one() == 0
    else:
        assert response.status_code == 200
        assert db.session.execute(sa.text("SELECT note_type FROM performance_interim_notes")).scalar_one() == "x" * 80
