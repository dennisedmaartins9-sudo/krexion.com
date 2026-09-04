"""v2.7.20 — CreepJS-class Fingerprint WIN pack."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fingerprint_win_module_builds_js():
    from fingerprint_win import build_fingerprint_win_js, should_use_quiet_mode

    js = build_fingerprint_win_js(
        {
            "platform": "Win32",
            "hardware_concurrency": 8,
            "device_memory": 8,
            "webgl_vendor": "Google Inc. (Intel)",
            "webgl_renderer": "ANGLE (Intel)",
            "canvas_seed": 12345,
        },
        cloak_mode=False,
        fp_hash=42,
    )
    assert "__KRX_FP_WIN__" in js
    assert "OffscreenCanvas" in js
    assert "contentWindow" in js
    assert "chrome.runtime" in js or "chrome.runtime" in js.replace(" ", "")
    assert "getClientRects" in js
    assert "Worker" in js

    quiet = build_fingerprint_win_js({}, cloak_mode=True, fp_hash=1)
    assert "C.quiet" in quiet or '"quiet": true' in quiet or "quiet\": true" in quiet

    assert should_use_quiet_mode(reduce_js_fingerprint_noise=True) is True
    assert should_use_quiet_mode(
        canvas_mode="real", webgl_mode="real", audio_mode="real", font_mode="off"
    ) is True
    assert should_use_quiet_mode(canvas_mode="noise") is False


def test_antidetect_config_fingerprint_win_defaults():
    from browser_profile_module import AntiDetectConfig

    cfg = AntiDetectConfig()
    assert cfg.fingerprint_win is True
    assert cfg.fingerprint_win_prefer_real is True


def test_rut_stealth_wires_fingerprint_win():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "fingerprint_win" in src
    assert "build_fingerprint_win_js" in src
    assert "cloak_quiet" in src


def test_launcher_prefer_real_and_salt():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "fingerprint_win_prefer_real" in src
    assert "fingerprint_salt" in src
    assert "should_use_quiet_mode" in src
    assert "fingerprint_win=" in src


def test_fingerprint_refresh_route_exists():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '"/{profile_id}/fingerprint/refresh"' in src
    assert "fingerprint_refresh" in src
    assert "fingerprint_salt" in src


def test_frontend_fingerprint_win_ui():
    fe = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "pages"
        / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "bp-fingerprint-win" in fe
    assert "fingerprint/refresh" in fe
    assert "Fingerprint WIN pack" in fe


def test_version_2_7_20_or_newer():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.20")
