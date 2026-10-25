"""urlencoded form bodies are refused above MAX_FORM_MEMORY_SIZE (Werkzeug 3.1.9 dropped the limit).

Werkzeug 3.1.8 answered a urlencoded body declared larger than ``max_form_memory_size`` with 413;
3.1.9 applies only ``MAX_CONTENT_LENGTH``, which BYS360 raises to 150 MB for uploads. Measured
on the real app: a 2 MB and a 20 MB urlencoded POST to /login were 413 on 3.1.8 and parsed on
3.1.9. ``app.core.form_body_limit.BYS360Request`` restores the 3.1.8 rule; uploads keep their
150 MB limit.
"""
from __future__ import annotations

import io

import pytest
from flask import Flask, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.core.form_body_limit import BYS360Request

LIMIT = 500_000  # Flask's default MAX_FORM_MEMORY_SIZE; BYS360 does not override it


def _bare_app() -> Flask:
    app = Flask(__name__)
    app.request_class = BYS360Request
    return app


def _urlencoded(size: int) -> bytes:
    prefix = b"field="
    return prefix + b"a" * (size - len(prefix))


def test_a_declared_body_over_the_limit_is_refused_before_it_is_parsed():
    app = _bare_app()
    with (
        app.test_request_context(
            "/", method="POST", data=_urlencoded(LIMIT + 1), content_type="application/x-www-form-urlencoded"
        ),
        pytest.raises(RequestEntityTooLarge),
    ):
        request.form  # noqa: B018 - parsing is the point


def test_a_body_at_the_limit_is_parsed():
    app = _bare_app()
    with app.test_request_context(
        "/", method="POST", data=_urlencoded(LIMIT), content_type="application/x-www-form-urlencoded"
    ):
        assert len(request.form["field"]) == LIMIT - len("field=")


def test_a_body_without_content_length_is_read_only_up_to_the_limit():
    app = _bare_app()
    environ = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "HTTP_TRANSFER_ENCODING": "chunked",
        "wsgi.input": io.BytesIO(_urlencoded(LIMIT + 1)),
        "wsgi.input_terminated": True,
    }
    with app.request_context({**app.test_request_context("/").request.environ, **environ}):
        assert request.content_length is None
        with pytest.raises(RequestEntityTooLarge):
            request.form  # noqa: B018 - parsing is the point

    small = {**environ, "wsgi.input": io.BytesIO(b"a=1&b=2")}
    with app.request_context({**app.test_request_context("/").request.environ, **small}):
        assert request.form.to_dict() == {"a": "1", "b": "2"}


def test_multipart_file_uploads_keep_the_content_length_limit_only():
    app = _bare_app()
    payload = b"x" * (2 * LIMIT)
    with app.test_request_context(
        "/", method="POST", data={"note": "ok", "file": (io.BytesIO(payload), "big.pdf")}, content_type="multipart/form-data"
    ):
        assert request.form["note"] == "ok"
        assert request.files["file"].read() == payload


@pytest.fixture
def real_app(monkeypatch):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-urlencoded-form-limit",
        "DATABASE_URL": "sqlite:///:memory:",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "urlencoded-limit-test-first-login",
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "SCHEDULER_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    return flask_app


@pytest.mark.parametrize("csrf_enabled", (True, False))
def test_an_oversized_urlencoded_login_post_is_413_on_the_real_app(real_app, csrf_enabled):
    real_app.config["WTF_CSRF_ENABLED"] = csrf_enabled
    assert real_app.request_class is BYS360Request
    assert real_app.config.get("MAX_FORM_MEMORY_SIZE", LIMIT) == LIMIT
    assert real_app.config["MAX_CONTENT_LENGTH"] >= 150 * 1024 * 1024  # uploads keep their limit

    response = real_app.test_client().post(
        "/login", data=_urlencoded(2 * 1024 * 1024), content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 413
