"""Unit tests for Local PC Dashboard update detection.

Bug this covers: after publishing a release, cloud VERSION == latest,
so comparing latest vs cloud VERSION always made update_available=False
even when the customer's PC was still on an older Setup.exe.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releases_module import is_newer, _parse  # noqa: E402


def test_is_newer_basic():
    assert is_newer("2.6.65", "2.6.63") is True
    assert is_newer("2.6.63", "2.6.65") is False
    assert is_newer("2.6.65", "2.6.65") is False
    assert is_newer("v2.7.0", "2.6.99") is True


def test_client_behind_even_when_cloud_matches_latest():
    """Simulate the real bug: published == cloud file, customer older."""
    published = "2.6.65"
    cloud_file = "2.6.65"  # after deploy / publish
    customer = "2.6.63"
    # Wrong baseline (old public-latest): compare vs cloud → no update
    assert is_newer(published, cloud_file) is False
    # Correct baseline: compare vs customer → update available
    assert is_newer(published, customer) is True


def test_parse_strips_noise():
    assert _parse("2.6.65") == (2, 6, 65)
    assert _parse("v2.6.65-beta") == (2, 6, 65)
    assert _parse("") == (0, 0, 0)


def test_updater_prefers_native_cdn_constant():
    """desktop.updater must point at native Setup-latest, not Electron."""
    import importlib.util

    upd_path = Path(__file__).resolve().parents[2] / "desktop" / "updater.py"
    spec = importlib.util.spec_from_file_location("krexion_updater_test", upd_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    url = (mod.NATIVE_CDN_URL or "").lower()
    assert "krexion-setup-latest.exe" in url
    assert "desktop-setup" not in url
