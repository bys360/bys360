"""F4: canonical roots and real Windows junctions in synthetic directories."""
from __future__ import annotations

import io
import os
import stat
import subprocess
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

from app.security import private_uploads as private


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("PRIVATE_UPLOAD_FOLDER", raising=False)
    static = tmp_path / "static"
    static.mkdir()
    app = Flask("f4", static_folder=str(static), instance_path=str(tmp_path / "instance"))
    app.config.update(PRIVATE_UPLOAD_FOLDER=str(tmp_path / "private"), PUBLIC_UPLOAD_ROOTS=())
    return app


@pytest.mark.parametrize("configured", ["empty", "static", "static-child", "dot-static"])
@pytest.mark.parametrize("public", ["static", "alias"])
def test_unsafe_fallback_fails_before_any_public_write(app, tmp_path, configured, public):
    root = Path(app.static_folder) if public == "static" else tmp_path / "iis-public"
    root.mkdir(exist_ok=True)
    if public == "alias":
        app.config["PUBLIC_UPLOAD_ROOTS"] = [str(root)]
    app.instance_path = str(root / "instance")
    values = {"empty": "", "static": str(Path(app.static_folder)),
              "static-child": str(Path(app.static_folder) / "private"),
              "dot-static": str(Path(app.static_folder) / "nested" / ".." / "private")}
    app.config["PRIVATE_UPLOAD_FOLDER"] = values[configured]
    sentinel = root / "existing-private-file"
    sentinel.write_bytes(b"KEEP")
    with app.app_context(), pytest.raises(private.PrivateUploadError, match="PRIVATE_UPLOAD"):
        private.private_upload_dir("messages")
    assert sentinel.read_bytes() == b"KEEP"
    assert not (root / "instance" / "private_uploads").exists()


def test_public_root_nested_inside_private_and_fallback_fails_closed(app, tmp_path):
    shared = tmp_path / "shared"
    app.config["PRIVATE_UPLOAD_FOLDER"] = str(shared)
    app.instance_path = str(shared)
    app.config["PUBLIC_UPLOAD_ROOTS"] = [str(shared / "private_uploads" / "public")]
    with app.app_context(), pytest.raises(private.PrivateUploadError, match="PRIVATE_UPLOAD"):
        private.private_upload_dir("messages")
    assert not shared.exists()


def test_safe_fallback_is_canonical_and_keeps_existing_files(app):
    root = Path(app.static_folder)
    sentinel = root / "private" / "existing.png"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"KEEP")
    app.config["PRIVATE_UPLOAD_FOLDER"] = str(sentinel.parent)
    with app.app_context():
        result = private.private_upload_dir("messages")
    assert result == (Path(app.instance_path) / "private_uploads" / "messages").resolve()
    assert sentinel.read_bytes() == b"KEEP"


def test_safe_configured_root_is_returned_canonical(app, tmp_path):
    app.config["PRIVATE_UPLOAD_FOLDER"] = str(tmp_path / "unused" / ".." / "private")
    with app.app_context():
        assert private.private_upload_root() == (tmp_path / "private").resolve()


def test_relative_private_root_is_rejected(app):
    app.config["PRIVATE_UPLOAD_FOLDER"] = "relative-private"
    with app.app_context(), pytest.raises(private.PrivateUploadError, match="PRIVATE_UPLOAD"):
        private.private_upload_root()


@pytest.mark.parametrize("parts", [("..", "escaped"), ("../static", "private"), ("/absolute-escape",)])
def test_private_child_cannot_escape_validated_root(app, parts):
    with app.app_context(), pytest.raises(private.PrivateUploadError, match="PRIVATE_UPLOAD"):
        private.private_upload_path(*parts)


def junction(alias, target):
    if os.name != "nt":
        alias.symlink_to(target, target_is_directory=True)
        return
    # mklink /J requires no symlink privilege; both paths are test temp dirs.
    subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                   check=True, capture_output=True)


@pytest.mark.parametrize("location", ["configured", "fallback", "child", "ancestor"])
@pytest.mark.parametrize("destination", ["safe", "static"])
def test_real_junction_roots_and_children_are_fail_closed(app, tmp_path, location, destination):
    target = tmp_path / "junction-target" if destination == "safe" else Path(app.static_folder)
    target.mkdir(exist_ok=True)
    alias = tmp_path / "junction"
    if location == "child":
        private_root = tmp_path / "private"
        private_root.mkdir()
        alias = private_root / "junction"
    junction(alias, target)
    if location == "configured":
        app.config["PRIVATE_UPLOAD_FOLDER"] = str(alias)
    elif location == "fallback":
        app.config["PRIVATE_UPLOAD_FOLDER"] = str(Path(app.static_folder) / "private")
        app.instance_path = str(alias)
    elif location == "ancestor":
        app.config["PRIVATE_UPLOAD_FOLDER"] = str(alias / "nested")
    parts = ("junction", "nested") if location == "child" else ("messages",)
    with app.app_context(), pytest.raises(private.PrivateUploadError, match="PRIVATE_UPLOAD"):
        private.private_upload_dir(*parts)
    assert not (target / "messages").exists()
    assert not (target / "private_uploads").exists()
    assert not (target / "nested").exists()


def test_declared_public_junction_alias_to_default_private_is_rejected(app, tmp_path):
    root = Path(app.instance_path) / "private_uploads"
    root.mkdir(parents=True)
    alias = tmp_path / "iis-alias"
    junction(alias, root)
    app.config["PUBLIC_UPLOAD_ROOTS"] = [str(alias)]
    app.config["PRIVATE_UPLOAD_FOLDER"] = str(root)
    with app.app_context(), pytest.raises(private.PrivateUploadError, match="PRIVATE_UPLOAD"):
        private.private_upload_dir("messages")
    assert not (root / "messages").exists()


def test_legacy_read_fallback_rejects_junction_without_deleting_bytes(app, tmp_path):
    target = tmp_path / "old-store"
    target.mkdir()
    (target / "file.pdf").write_bytes(b"KEEP")
    alias = tmp_path / "old-alias"
    junction(alias, target)
    with app.app_context():
        assert private.locate_upload("file.pdf", (alias,)) is None
        assert private.locate_upload("file.pdf", (target,)) == (target.resolve(), "file.pdf")
    assert (target / "file.pdf").read_bytes() == b"KEEP"


def test_write_rechecks_root_after_directory_creation(app, tmp_path):
    with app.app_context():
        root = private.private_upload_dir("messages")
        root.rmdir()
        junction(root, Path(app.static_folder))
        file = FileStorage(stream=io.BytesIO(b"PRIVATE"), filename="key.pdf")
        with pytest.raises(private.PrivateUploadError, match="PRIVATE_UPLOAD"):
            private.store_private_upload(file, root / "key.pdf")
    assert not (Path(app.static_folder) / "key.pdf").exists()


def test_symlink_stat_mode_is_rejected_without_windows_symlink_privilege(app, monkeypatch):
    root = Path(app.config["PRIVATE_UPLOAD_FOLDER"])
    root.mkdir()
    lstat = Path.lstat

    def symlink_info(path):
        if path == root:
            return os.stat_result((stat.S_IFLNK | 0o777, 0, 0, 1, 0, 0, 0, 0, 0, 0))
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", symlink_info)
    with app.app_context(), pytest.raises(private.PrivateUploadError, match="PRIVATE_UPLOAD_REPARSE_POINT"):
        private.private_upload_root()


def test_canonical_resolution_error_fails_closed_without_path_disclosure(app, monkeypatch):
    root = Path(app.config["PRIVATE_UPLOAD_FOLDER"])
    resolve = Path.resolve

    def denied(path, *args, **kwargs):
        if path == root:
            raise PermissionError(13, "sensitive-key", str(path))
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", denied)
    with app.app_context(), pytest.raises(private.PrivateUploadError) as caught:
        private.private_upload_root()
    assert str(caught.value) == "PRIVATE_UPLOAD_PATH_CHECK_FAILED"
    assert caught.value.__suppress_context__
