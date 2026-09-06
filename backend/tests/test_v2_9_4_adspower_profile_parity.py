"""v2.9.4 — AdsPower-class Browser Profiles parity lock."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_at_least_2_9_4():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.4")


def test_soft_disabled_shows_interstitial_not_auto_nav():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "NEVER auto-navigate on real IP" in src
    assert "Proxy soft-disabled — interstitial shown" in src
    soft = src.split('elif proxy_diag.get("soft_disabled"):')[1].split("elif proxy_diag")[0]
    assert "set_content" in soft or "interstitial" in soft.lower()
    assert "page.goto" not in soft


def test_stealth_degrade_emits_launch_warning():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "Stealth degraded — full anti-detect inject failed" in src


def test_sync_blocks_webkit_and_tracks_slave_errors():
    mod = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "Synchronizer does not support Krexion Safari / WebKit" in mod
    sync = (ROOT / "browser_profile_sync.py").read_text(encoding="utf-8")
    assert "slave_errors" in sync
    assert "slave_error_count" in sync


def test_mobile_shell_frame_retry_still_present():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "try_frame_engine_into_shell" in src
    assert "engine_visually_framed_in_shell" in src


def test_fe_parse_api_error_and_reopen():
    fe = ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    text = fe.read_text(encoding="utf-8")
    assert "function parseApiError" in text
    assert "Open again" in text
    assert "bp-row-err-" in text


def test_health_scores_last_error_and_stealth():
    src = (ROOT / "browser_profile_health.py").read_text(encoding="utf-8")
    assert "stealth degraded on last Open" in src
    assert "last Open error:" in src
