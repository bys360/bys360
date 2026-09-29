"""Contract: the unauthenticated /health/deep endpoint never echoes dependency exception text.

A PostgreSQL or Redis connection error message carries internal host names,
ports and database user names. The endpoint is public (load balancer probe), so
it reports only ok/unavailable per dependency; the full error stays in the
server log.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

DB_ERROR = 'connection to server at "10.20.30.40", port 5432 failed: FATAL: password authentication failed for user "bys_app"'
REDIS_ERROR = "Error 10061 connecting to 10.9.9.9:6399. Connection refused."
SECRET_FRAGMENTS = ("10.20.30.40", "bys_app", "5432", "10.9.9.9", "6399", "OperationalError", "ConnectionError", "password")


@pytest.fixture
def client(monkeypatch):
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-health-deep-contract", "DATABASE_URL": "sqlite:///:memory:",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "SCHEDULER_ENABLED": "false", "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_database_failure_is_reported_without_exception_text(client, monkeypatch):
    from app.extensions import db

    def fail(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception(DB_ERROR))

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("CACHE_REDIS_URL", raising=False)
    monkeypatch.setattr(db.session, "execute", fail)
    response = client.get("/health/deep")
    body = response.get_data(as_text=True)
    assert response.status_code == 503
    assert response.get_json()["checks"]["db"] == {"ok": False, "message": "unavailable"}
    assert not [fragment for fragment in SECRET_FRAGMENTS if fragment in body]


def test_redis_failure_is_reported_without_exception_text(client, monkeypatch):
    import redis

    class _FailingRedis:
        def ping(self):
            raise redis.exceptions.ConnectionError(REDIS_ERROR)

    monkeypatch.setenv("REDIS_URL", "redis://:not-a-real-password@10.9.9.9:6399/0")
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, *a, **k: _FailingRedis()))
    response = client.get("/health/deep")
    body = response.get_data(as_text=True)
    assert response.get_json()["checks"]["redis"] == {"ok": False, "message": "unavailable"}
    assert not [fragment for fragment in SECRET_FRAGMENTS if fragment in body]
    assert "not-a-real-password" not in body


def test_healthy_dependencies_still_report_ok(client, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("CACHE_REDIS_URL", raising=False)
    response = client.get("/health/deep")
    assert response.status_code == 200
    assert response.get_json()["checks"] == {"db": {"ok": True, "message": "ok"}, "redis": {"ok": None, "message": "not_configured"}}
