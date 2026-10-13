"""PR68 F1 RED/GREEN cases; synthetic legacy files and public-root aliases only."""
from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from app.security import private_uploads as private


@pytest.fixture
def tiny_app(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    app = Flask("closure", static_folder=str(static), static_url_path="/static",
                instance_path=str(tmp_path / "instance"))
    app.config["PRIVATE_UPLOAD_FOLDER"] = str(tmp_path / "private")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    return app


@pytest.mark.parametrize("name", ["hr/personnel_documents/x.pdf", "support_tickets/1/x.pdf",
                                    "publications/2026/10/x.pdf", "profile_photos/x.png"])
@pytest.mark.parametrize("prefix", ["", "./", "css/../"])
def test_static_root_legacy_upload_configuration_fails_closed(tiny_app, name, prefix):
    root = Path(tiny_app.static_folder)
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"PRIVATE-LEGACY")
    tiny_app.config["UPLOAD_FOLDER"] = str(root)
    private.install_private_static_guard(tiny_app)
    response = tiny_app.test_client().get("/static/" + prefix + name)
    assert response.status_code == 404
    assert b"PRIVATE-LEGACY" not in response.data


def test_f1_legacy_external_public_alias_prevents_startup(tiny_app, tmp_path):
    public = tmp_path / "iis_public"
    public.mkdir()
    tiny_app.config["PUBLIC_UPLOAD_ROOTS"] = [str(public)]
    tiny_app.config["UPLOAD_FOLDER"] = str(public / "legacy")
    with pytest.raises(RuntimeError, match="PRIVATE_UPLOAD_LEGACY_PUBLIC_ROOT"):
        private.install_private_static_guard(tiny_app)


def test_f1_upload_root_ancestor_of_static_fails_closed(tiny_app):
    root = Path(tiny_app.static_folder)
    (root / "legacy.pdf").write_bytes(b"PRIVATE-LEGACY")
    tiny_app.config["UPLOAD_FOLDER"] = str(root.parent)
    private.install_private_static_guard(tiny_app)
    response = tiny_app.test_client().get("/static/legacy.pdf")
    assert response.status_code == 404 and b"PRIVATE-LEGACY" not in response.data


@pytest.mark.parametrize("layout", ["same_static_alias", "public_child_of_legacy"])
def test_f1_additional_public_alias_overlap_prevents_startup(tiny_app, tmp_path, layout):
    if layout == "same_static_alias":
        tiny_app.config["UPLOAD_FOLDER"] = str(Path(tiny_app.static_folder) / "uploads")
        tiny_app.config["PUBLIC_UPLOAD_ROOTS"] = [tiny_app.static_folder]
    else:
        tiny_app.config["UPLOAD_FOLDER"] = str(tmp_path / "legacy")
        tiny_app.config["PUBLIC_UPLOAD_ROOTS"] = [str(tmp_path / "legacy" / "public")]
    with pytest.raises(RuntimeError, match="PRIVATE_UPLOAD_LEGACY_PUBLIC_ROOT"):
        private.install_private_static_guard(tiny_app)


@pytest.mark.parametrize("name", ["files/hr/x.pdf", "FILES/hr/x.pdf", "files./hr/x.pdf",
                                  "files /hr/x.pdf", "files\\hr\\x.pdf", "./files/hr/x.pdf",
                                  "css/../files/hr/x.pdf", "files/hr/x.pdf::$DATA"])
def test_f1_custom_legacy_path_variants_are_blocked(tiny_app, name):
    root = Path(tiny_app.static_folder)
    target = root / "files" / "hr" / "x.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"PRIVATE-LEGACY")
    tiny_app.config["UPLOAD_FOLDER"] = str(root / "files")
    private.install_private_static_guard(tiny_app)
    response = tiny_app.test_client().get("/static/" + name)
    assert response.status_code == 404 and b"PRIVATE-LEGACY" not in response.data


def test_f1_public_assets_work_with_safe_legacy_configuration(tiny_app):
    root = Path(tiny_app.static_folder)
    (root / "public.css").write_bytes(b"PUBLIC-CONTROL")
    tiny_app.config["UPLOAD_FOLDER"] = str(root / "uploads")
    private.install_private_static_guard(tiny_app)
    response = tiny_app.test_client().get("/static/public.css")
    assert response.status_code == 200 and response.data == b"PUBLIC-CONTROL"
