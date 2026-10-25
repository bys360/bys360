"""Behavior contract for the Portal composer's YouTube/Vimeo link pipeline.

Locks in CURRENT, already-shipped end-to-end behavior for the feature that
lets a user paste a YouTube/Vimeo link into the Portal post composer for
inline feed playback. This pipeline previously had ZERO automated test
coverage anywhere in the repo. Chain covered:

    composer field name="video_url" (app/templates/portal/_composer.html,
    id="portal-video-url")
      -> POST /portal/posts, route portal_post_create
         (app/portal/routes.py; decorators @login_required +
         @menu_key_required("portal_feed"), plus an in-body
         _portal_has_permission("portal_post_create") check)
      -> reads request.form.get("video_url")
      -> _save_portal_video_link -> _portal_video_embed_url -> _youtube_video_id
      -> persisted as a PortalPostAttachment
         (app/models/portal_models.py) with mime_type="text/x-portal-video",
         stored_path=canonical embed URL
      -> feed retrieval via portal_service
      -> rendered in app/templates/portal/_post_card.html as
         <iframe src="{{ attachment.stored_path }}" ...>.

Deliberately uses a per-test, file-backed SQLite app (see _make_app) rather
than the shared session-scoped app/client fixtures in tests/conftest.py,
since tests D/E/F below do real DB mutation (post + attachment creation) --
same isolation rationale, and the same _make_app/_create_user/_login shape,
as tests/behavior/test_settings_page_behavior_contract.py.

Out of scope by design: negative security/XSS/host-spoofing cases
(javascript:, data:, fake host lookalikes, raw iframe injection) are covered
in tests/security/test_portal_video_link_host_validation_negative.py.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.portal.routes import _portal_video_embed_url, _youtube_video_id
from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "portal_video_url_behavior_tmp" / "test_dbs"
DEFAULT_PASSWORD = "PortalVideoBehaviorTest1!"

# Realistic-looking, deterministic 11-char YouTube video id.
YOUTUBE_ID = "dQw4w9WgXcQ"
EXPECTED_YOUTUBE_EMBED = f"https://www.youtube-nocookie.com/embed/{YOUTUBE_ID}"

# Realistic-looking numeric Vimeo video id (8 digits, within the {5,20} regex).
VIMEO_ID = "76979871"
EXPECTED_VIMEO_EMBED = f"https://player.vimeo.com/video/{VIMEO_ID}"


# ---------------------------------------------------------------------------
# Fixtures / helpers (mirrors tests/behavior/test_settings_page_behavior_contract.py)
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, **env_overrides):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-portal-video-url-behavior-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)

    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch, request):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, email, role="admin", birim=None, password=DEFAULT_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Portal",
            soyad="Video",
            role=role,
            birim=birim,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=DEFAULT_PASSWORD):
    response = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def _post_id_by_body(app, body):
    with app.app_context():
        from app.models import PortalPost

        row = PortalPost.query.filter_by(body=body).order_by(PortalPost.id.desc()).first()
        return None if row is None else row.id


def _video_attachment_stored_path(app, post_id):
    with app.app_context():
        from app.models import PortalPostAttachment

        row = PortalPostAttachment.query.filter_by(
            post_id=post_id, mime_type="text/x-portal-video"
        ).first()
        return None if row is None else row.stored_path


def _attachment_count(app, post_id):
    with app.app_context():
        from app.models import PortalPostAttachment

        return PortalPostAttachment.query.filter_by(post_id=post_id).count()


# ---------------------------------------------------------------------------
# A) Feature presence: composer page exposes the video_url control
# ---------------------------------------------------------------------------


def test_composer_page_exposes_video_url_field_exactly_once(app, client):
    _create_user(app, sicil_no="pv001", email="pv001@ktb.gov.tr", role="admin")
    _login(client, "pv001")

    response = client.get("/portal")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Stable selectors: id + name attribute, not brittle Turkish text matching.
    assert 'id="portal-video-url"' in html
    assert html.count('name="video_url"') == 1


@pytest.mark.parametrize("role", ["personel", "admin"], ids=["normal_role", "admin_role"])
def test_composer_page_exposes_video_url_field_for_any_portal_role(app, client, role):
    """Regression proof for a real live-visibility report: the field itself
    was never gated by role/permission/config in the template (confirmed by
    direct source inspection -- .portal-media-tools has zero {% if %}/role/
    permission conditionals around any of its three media fields), so any
    user with portal_feed access must see it identically regardless of role.
    The actual root cause of the live report was a CSS Grid sizing bug (see
    test_media_tools_grid_uses_minmax_to_prevent_track_overflow below) -- this
    test guards the template/permission side of that investigation."""
    _create_user(app, sicil_no=f"pvrole_{role}", email=f"pvrole_{role}@ktb.gov.tr", role=role)
    _login(client, f"pvrole_{role}")

    response = client.get("/portal")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="video_url"' in html
    assert 'id="portal-video-url"' in html


def test_media_tools_grid_uses_minmax_to_prevent_track_overflow():
    """Real live-visibility bug, root-caused via actual rendered DOM geometry
    (getBoundingClientRect), not string presence: .portal-media-tools /
    .bys360-v2121-media-tools used bare `1fr` grid tracks. CSS Grid's `1fr`
    alone resolves to `minmax(auto, 1fr)` -- a track will NOT shrink below
    its content's min-content size. The two <input type="file"> fields
    (photo, video file) have wide intrinsic min-content width, so their
    tracks refused to shrink, and the computed track widths (measured
    403px + 403px + 138.89px = 945px) exceeded the actual grid container's
    rendered width (429px in the reproduction). The third (video-url) field
    was consequently laid out far outside the container and the viewport
    (measured x=1494 in a 1440px-wide window) and clipped by the composer
    card's own `overflow:hidden` -- present in the DOM, `display:block`,
    `visibility:visible`, yet genuinely invisible to a real user. Confirmed
    fixed empirically: switching to `minmax(0, 1fr)` tracks (which explicitly
    allow shrinking below content size) put the field back at x=938,
    fully within the viewport, with three equal 125px columns.

    This test guards the CSS source pattern only (real layout verification
    requires a browser, exercised separately, not by this pytest suite) --
    it exists so this exact bug class cannot silently regress unnoticed."""
    css_path = Path(__file__).resolve().parents[2] / "app" / "static" / "css" / "bys360_portal.css"
    css = css_path.read_text(encoding="utf-8")

    assert ".portal-media-tools{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);" in css
    assert ".bys360-v2121-media-tools{grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)}" in css

    # The unsafe bare-1fr multi-track pattern that caused the overflow must
    # not reappear for these two selectors specifically (single-column `1fr`
    # in the responsive breakpoints is fine -- a lone track has nothing to
    # compete with, so it cannot blow out its container).
    assert ".portal-media-tools{display:grid;grid-template-columns:1fr 1fr;" not in css
    assert ".bys360-v2121-media-tools{grid-template-columns:1fr 1fr 1fr}" not in css


def test_composer_page_exposes_video_url_live_preview_container(app, client):
    """The composer field alone (no client-side feedback) previously gave a
    user zero visual confirmation that pasting a link did anything until
    after publishing -- easy to mistake for "this doesn't work." A
    data-portal-video-preview container, wired by
    app/static/js/bys360_portal.js, must be present next to the field."""
    _create_user(app, sicil_no="pv002", email="pv002@ktb.gov.tr", role="admin")
    _login(client, "pv002")

    response = client.get("/portal")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "data-portal-video-preview" in html
    assert "data-portal-video-url" in html
    assert "bys360_portal.js" in html


def test_video_link_preview_js_mirrors_backend_provider_allowlist() -> None:
    """The client-side preview must recognize exactly the providers the
    server accepts (YouTube incl. youtu.be/shorts/embed, Vimeo) and must
    never render arbitrary/raw user HTML -- it only ever builds an iframe
    src from a value it extracted and validated itself, exactly like the
    server's _portal_video_embed_url()."""
    js_path = Path(__file__).resolve().parents[2] / "app" / "static" / "js" / "bys360_portal.js"
    js_source = js_path.read_text(encoding="utf-8")

    assert "BYS360_PORTAL_VIDEO_LINK_PREVIEW_V1_BEGIN" in js_source
    assert "portalVideoEmbedUrl" in js_source
    assert "youtube-nocookie.com/embed/" in js_source
    assert "player.vimeo.com/video/" in js_source
    # Never trusts raw HTML/innerHTML assignment of user-controlled text --
    # iframe.src is always assigned from the function's own return value,
    # and error/preview content is built via createElement/textContent.
    assert ".innerHTML = raw" not in js_source
    assert ".innerHTML = input.value" not in js_source


# ---------------------------------------------------------------------------
# B) YouTube URL normalization (pure unit tests, no network, no DB)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_url",
    [
        f"https://www.youtube.com/watch?v={YOUTUBE_ID}",
        f"https://youtu.be/{YOUTUBE_ID}",
        f"https://www.youtube.com/embed/{YOUTUBE_ID}",
    ],
    ids=["watch_v_param", "youtu_be_short_link", "already_embed_url"],
)
def test_youtube_url_variants_normalize_to_same_canonical_nocookie_embed(raw_url):
    assert _portal_video_embed_url(raw_url) == EXPECTED_YOUTUBE_EMBED


@pytest.mark.parametrize(
    "raw_url",
    [
        f"https://www.youtube.com/watch?v={YOUTUBE_ID}",
        f"https://youtu.be/{YOUTUBE_ID}",
        f"https://www.youtube.com/embed/{YOUTUBE_ID}",
    ],
    ids=["watch_v_param", "youtu_be_short_link", "already_embed_url"],
)
def test_youtube_video_id_helper_extracts_raw_id_from_each_parsed_variant(raw_url):
    assert _youtube_video_id(urlparse(raw_url)) == YOUTUBE_ID


# ---------------------------------------------------------------------------
# C) Vimeo URL normalization (pure unit test, no network, no DB)
# ---------------------------------------------------------------------------


def test_vimeo_url_normalizes_to_player_embed_url():
    assert _portal_video_embed_url(f"https://vimeo.com/{VIMEO_ID}") == EXPECTED_VIMEO_EMBED


# ---------------------------------------------------------------------------
# D) Create + persist + feed render (full integration, real client, no network)
# ---------------------------------------------------------------------------


def test_create_post_with_youtube_link_persists_attachment_and_renders_in_feed(app, client):
    _create_user(app, sicil_no="pv010", email="pv010@ktb.gov.tr", role="admin")
    _login(client, "pv010")
    body = "PV010 - YouTube linkli portal paylasimi"

    response = client.post(
        "/portal/posts",
        data={
            "body": body,
            "video_url": f"https://www.youtube.com/watch?v={YOUTUBE_ID}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    post_id = _post_id_by_body(app, body)
    assert post_id is not None

    stored_path = _video_attachment_stored_path(app, post_id)
    assert stored_path == EXPECTED_YOUTUBE_EMBED

    feed_response = client.get("/portal")
    assert feed_response.status_code == 200
    html = feed_response.get_data(as_text=True)
    assert f'<iframe src="{EXPECTED_YOUTUBE_EMBED}"' in html


def test_create_post_with_vimeo_link_persists_attachment_and_renders_in_feed(app, client):
    _create_user(app, sicil_no="pv011", email="pv011@ktb.gov.tr", role="admin")
    _login(client, "pv011")
    body = "PV011 - Vimeo linkli portal paylasimi"

    response = client.post(
        "/portal/posts",
        data={
            "body": body,
            "video_url": f"https://vimeo.com/{VIMEO_ID}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    post_id = _post_id_by_body(app, body)
    assert post_id is not None
    assert _video_attachment_stored_path(app, post_id) == EXPECTED_VIMEO_EMBED

    feed_response = client.get("/portal")
    assert feed_response.status_code == 200
    assert f'<iframe src="{EXPECTED_VIMEO_EMBED}"' in feed_response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# E) Historical / pre-existing stored post (ORM-direct, bypasses the URL-paste
#    flow entirely -- proves compatibility with rows written before today,
#    without requiring any DB migration).
# ---------------------------------------------------------------------------


def test_historical_stored_video_attachment_still_renders_iframe(app, client):
    admin_id = _create_user(app, sicil_no="pv020", email="pv020@ktb.gov.tr", role="admin")
    historical_embed_url = "https://www.youtube-nocookie.com/embed/legacyPreExistingId"

    with app.app_context():
        from app.extensions import db
        from app.models import PortalPost, PortalPostAttachment

        post = PortalPost(
            author_user_id=admin_id,
            wall_owner_user_id=admin_id,
            body="PV020 - tarihsel/onceden var olan video kaydi",
            post_type="normal",
            visibility_scope="public",
        )
        db.session.add(post)
        db.session.flush()
        db.session.add(
            PortalPostAttachment(
                post_id=post.id,
                filename="legacy-video-link.txt",
                stored_path=historical_embed_url,
                mime_type="text/x-portal-video",
                size_bytes=0,
                uploaded_by_user_id=admin_id,
            )
        )
        db.session.commit()

    _login(client, "pv020")
    response = client.get("/portal")

    assert response.status_code == 200
    assert f'<iframe src="{historical_embed_url}"' in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# F) Invalid / empty video_url: never blocks the post, never 500s, never
#    creates a bogus video attachment.
# ---------------------------------------------------------------------------


def test_empty_video_url_creates_post_without_video_attachment(app, client):
    _create_user(app, sicil_no="pv030", email="pv030@ktb.gov.tr", role="admin")
    _login(client, "pv030")
    body = "PV030 - video linki olmadan normal paylasim"

    response = client.post(
        "/portal/posts",
        data={"body": body, "video_url": ""},
        follow_redirects=False,
    )

    assert response.status_code == 302
    post_id = _post_id_by_body(app, body)
    assert post_id is not None
    assert _attachment_count(app, post_id) == 0


def test_unsupported_but_well_formed_video_url_is_ignored_without_error(app, client):
    _create_user(app, sicil_no="pv031", email="pv031@ktb.gov.tr", role="admin")
    _login(client, "pv031")
    body = "PV031 - desteklenmeyen video linki ile paylasim"

    response = client.post(
        "/portal/posts",
        data={"body": body, "video_url": "https://example.com/video"},
        follow_redirects=False,
    )

    # Must redirect normally (never a 500), and the post itself must still
    # be created -- only the unsupported video link is silently dropped.
    assert response.status_code == 302
    post_id = _post_id_by_body(app, body)
    assert post_id is not None
    assert _attachment_count(app, post_id) == 0
