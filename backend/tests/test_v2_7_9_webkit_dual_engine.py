"""v2.7.9 — Dual-engine: iOS → Playwright WebKit, Android → Chromium."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault(
    "playwright.async_api",
    MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    ),
)
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 "
    "Mobile/15E148 Safari/604.1"
)
CRIOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/136.0.7103.125 "
    "Mobile/15E148 Safari/604.1"
)
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.7103.125 Mobile Safari/537.36"
)


def test_version_is_2_7_9():
    assert _read("VERSION").strip() == "2.7.66"


def test_ua_prefers_webkit_safari_and_crios():
    import real_user_traffic as rut

    assert rut._ua_prefers_webkit(SAFARI) is True
    assert rut._ua_prefers_webkit(CRIOS) is True
    assert rut._ua_prefers_webkit(ANDROID_CHROME) is False


def test_normalize_visit_keeps_ios_when_webkit_available():
    import real_user_traffic as rut

    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        with patch.object(rut, "_webkit_runtime_available", return_value=True):
            out, meta = rut._normalize_mobile_ua_for_visit(SAFARI)
        assert out == SAFARI.strip() or "iPhone" in out
        assert "iPhone" in out
        assert meta["engine"] == "webkit"
        assert meta["os"] == "ios"
        assert meta["swapped_ios"] is False
        assert "WebKit" in (meta.get("note") or "")
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev


def test_normalize_visit_swaps_when_webkit_missing():
    import real_user_traffic as rut

    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        with patch.object(rut, "_webkit_runtime_available", return_value=False):
            out, meta = rut._normalize_mobile_ua_for_visit(SAFARI)
        assert meta["engine"] == "chromium"
        assert meta["swapped_ios"] is True
        assert meta["os"] == "android"
        assert "Android" in out
        assert "WebKit" in (meta.get("note") or "") or "fallback" in (
            meta.get("note") or ""
        ).lower()
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev


def test_launch_webkit_and_engine_browser_exist_in_source():
    src = _read("real_user_traffic.py")
    assert "async def _launch_webkit_browser" in src
    assert "async def _launch_engine_browser" in src
    assert "pw.webkit.launch" in src
    assert '"chromium": None' in src or "'chromium': None" in src
    assert '"webkit": None' in src or "'webkit': None" in src


def test_profile_launcher_references_webkit_launch():
    src = _read("browser_profile_launcher.py")
    assert "webkit.launch" in src
    assert "_normalize_mobile_ua_for_visit" in src


def test_frontend_note_mentions_mobile_engines():
    fe = (
        Path(__file__).resolve().parent.parent.parent
        / "frontend"
        / "src"
        / "pages"
        / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "Safari" in fe
    assert "Chromium" in fe


def test_mobile_ua_for_inapp_can_emit_ios_when_webkit():
    import real_user_traffic as rut

    with patch.object(rut, "_webkit_runtime_available", return_value=True):
        with patch.object(rut.random, "random", return_value=0.1):
            ua = rut._mobile_ua_for_inapp()
    assert rut._ua_prefers_webkit(ua) is True


def test_inapp_preset_keeps_ios_when_webkit_available():
    import real_user_traffic as rut

    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        with patch.object(rut, "_webkit_runtime_available", return_value=True):
            out = rut._apply_inapp_preset_to_uas(
                [SAFARI, ANDROID_CHROME],
                want_count=2,
                preset_platform="tiktok",
            )
        assert any(rut._is_ios_webkit_ua(u) for u in out)
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev
