"""v2.7.58 — Browser profile UA must match referrer platform (Everflow parity)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_version_is_2_7_58():
    assert _read("VERSION").strip() == "2.7.94"


def test_generic_mobile_browser_uses_real_device_not_k():
    from referrer_pro import _generic_mobile_browser

    ua = _generic_mobile_browser(
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Mobile Safari/537.36"
    )
    assert " Android 10; K)" not in ua
    assert "Build/" in ua
    assert "Chrome/" in ua
    assert " wv)" not in ua


def test_youtube_fallback_has_pixel_like_device():
    from referrer_pro import coerce_ua_for_platform

    ua = coerce_ua_for_platform(
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Mobile Safari/537.36",
        "youtube",
    )
    assert " K)" not in ua
    assert "Build/" in ua


def test_facebook_profile_coerce_adds_fb_iab():
    from browser_profile_launcher import _ProfileReferrerState, _coerce_profile_ua

    cfg = {
        "referrer": {
            "enabled": True,
            "match_ua_to_platform": True,
            "platform_weights": '{"facebook": 100}',
        }
    }
    state = _ProfileReferrerState(enabled=True, platform="facebook")
    base = (
        "Mozilla/5.0 (Linux; Android 15; Pixel 9 Build/AP3A.240905.015; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/136.0.0.0 Mobile Safari/537.36"
    )
    out = _coerce_profile_ua(base, cfg, referrer_state=state, locale="en-US")
    assert "FB_IAB" in out or "FBAN" in out


def test_launcher_coerce_uses_ensure_inapp():
    src = _read("browser_profile_launcher.py")
    block = src.split("def _coerce_profile_ua")[1].split("def _compute_fingerprint_hash")[0]
    assert "ensure_inapp_platform_ua" in block
    assert "_mobile_ua_for_inapp" in block
    assert "align_ua_to_chromium" in src.split("ua = _coerce_profile_ua")[1][:800]
