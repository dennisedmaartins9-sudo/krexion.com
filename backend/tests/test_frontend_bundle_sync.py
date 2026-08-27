"""Tests for native frontend bundle stamp + stale detection."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import frontend_bundle as fb


def _write_bundle(tmp_path: Path, version: str, *, fresh: bool = True) -> Path:
    fe_dir = tmp_path / "frontend"
    js_dir = fe_dir / "static" / "js"
    js_dir.mkdir(parents=True)
    marker = "Krexion Browser Profiles" if fresh else "AdsPower/GoLogin-style manual browsing profiles"
    (js_dir / "main.test.js").write_text(marker, encoding="utf-8")
    (fe_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    (fe_dir / fb.BUILD_VERSION_FILENAME).write_text(
        json.dumps({"version": version}),
        encoding="utf-8",
    )
    return fe_dir


def test_frontend_bundle_is_stale_when_version_mismatch(tmp_path, monkeypatch):
    vf = tmp_path / "VERSION"
    vf.write_text("2.7.22", encoding="utf-8")
    monkeypatch.setattr(fb, "VERSION_FILE", vf)
    fe_dir = _write_bundle(tmp_path, "2.7.21", fresh=True)
    assert fb.frontend_bundle_is_stale(fe_dir, "2.7.22") is True


def test_frontend_bundle_is_stale_when_marker_old(tmp_path, monkeypatch):
    vf = tmp_path / "VERSION"
    vf.write_text("2.7.22", encoding="utf-8")
    monkeypatch.setattr(fb, "VERSION_FILE", vf)
    fe_dir = _write_bundle(tmp_path, "2.7.22", fresh=False)
    assert fb.frontend_bundle_is_stale(fe_dir, "2.7.22") is True


def test_frontend_bundle_fresh_when_version_and_marker_match(tmp_path, monkeypatch):
    vf = tmp_path / "VERSION"
    vf.write_text("2.7.22", encoding="utf-8")
    monkeypatch.setattr(fb, "VERSION_FILE", vf)
    fe_dir = _write_bundle(tmp_path, "2.7.22", fresh=True)
    assert fb.frontend_bundle_is_stale(fe_dir, "2.7.22") is False


def test_cloud_ui_bundle_url_uses_cloud_env(monkeypatch):
    monkeypatch.setenv("KREXION_CLOUD_URL", "https://krexion.com")
    assert fb.cloud_ui_bundle_url("2.7.22") == "https://krexion.com/downloads/ui/krexion-ui-2.7.22.zip"
