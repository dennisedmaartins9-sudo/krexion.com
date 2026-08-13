"""
Historical regression coverage updated for the offer-page browser contract.

RUT drives Chromium page navigation, so TikTok Android must use:
    Mozilla/5.0 (Linux; Android 15; SM-S931B Build/…; wv)
                AppleWebKit/537.36 (KHTML, like Gecko)
                Version/4.0 Chrome/146.0.7432.116 Mobile Safari/537.36
                musical_ly_…
Standalone Cronet remains valid only as an external native-network identity.
"""

import importlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERRER_FILE = REPO_ROOT / "referrer_pro.py"
sys.path.insert(0, str(REPO_ROOT))
from ua_profile_contract import (  # noqa: E402
    client_hint_headers_for_ua,
    validate_header_coherence,
    validate_user_agent,
)


def _assert_chromium_hints_match(ua: str):
    """v2.6.88 — TikTok Android in-app emits no Sec-CH-UA (Everflow Chrome leak fix)."""
    hints = client_hint_headers_for_ua(ua)
    assert hints == {}
    assert validate_header_coherence(ua, {}) == []
    assert "TikTok/" in ua


def test_version_bumped_to_2_6_19_or_higher():
    v = (REPO_ROOT / "VERSION").read_text().strip()
    parts = tuple(int(p) for p in v.split("."))
    assert parts >= (2, 6, 19), f"Expected >= 2.6.19, got {v!r}"


def _get_rp():
    sys.path.insert(0, str(REFERRER_FILE.parent))
    return importlib.import_module("referrer_pro")


def test_tiktok_android_ua_uses_page_navigation_webview():
    """Coercion must preserve a coherent Chromium WebView page identity."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 15; SM-S931B Build/AP3A.240905.015; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/146.0.7432.116 Mobile Safari/537.36"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    for token in ("; wv)", "AppleWebKit/537.36", "Version/4.0", "Chrome/", "Mobile Safari/537.36"):
        assert token in out, f"{token} missing: {out}"
    assert "Cronet/" not in out
    assert "TikTok/" in out
    assert "musical_ly_" in out, f"TikTok suffix missing: {out}"
    profile = validate_user_agent(out, expected_app="tiktok")
    assert profile["engine"] == "android_webview"
    assert profile["runtime_compatible"] is True
    assert profile["issues"] == []
    _assert_chromium_hints_match(out)


def test_tiktok_android_preserves_device_and_version():
    """Rebuild must preserve the Android version + device model from
    the input UA so the fingerprint stays internally consistent."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-A556B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/145.0.7632.99 Mobile Safari/537.36"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    assert "Android 14" in out
    assert "SM-A556B" in out
    assert "UP1A.231005.007" in out


def test_facebook_android_keeps_chrome_webview():
    """Facebook Android IS a real Chrome WebView — the FBAN/FBAV bracket
    sits AFTER Chrome/Safari. This behaviour must NOT change (unlike
    TikTok Android)."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36"
    )
    out = rp.coerce_ua_for_platform(input_ua, "facebook")
    assert "Chrome/" in out, f"Facebook must keep Chrome/ (real WebView): {out}"
    assert "Mobile Safari/" in out, f"Facebook must keep Mobile Safari/: {out}"
    assert "[FB_IAB/FB4A" in out, f"FBAN/FBAV bracket missing: {out}"
    assert "Cronet/" not in out, f"Cronet must NOT appear for Facebook: {out}"


def test_tiktok_ios_still_uses_webkit_no_safari():
    """iOS in-app UAs keep AppleWebKit + Mobile/xxx but strip Safari/xxx.
    This behaviour was correct in v2.6.18 and must be preserved."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 "
        "Mobile/15E148 Safari/604.1"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    assert "AppleWebKit/" in out
    assert "Mobile/" in out
    assert "Safari/604.1" not in out, f"Safari must be stripped on iOS in-app: {out}"
    assert "Version/26.3" not in out, f"Version/xxx must be stripped: {out}"
    assert "musical_ly_" in out
    profile = validate_user_agent(out, expected_app="tiktok")
    assert profile["profile_type"] == "ios_wkwebview"
    assert profile["issues"] == []


def test_wechat_ua_gets_webview_after_scrub_and_tiktok_coerce():
    """End-to-end: WeChat mobile UA + tiktok platform → no WeChat marker
    AND a coherent Android WebView base."""
    rp = _get_rp()
    # WeChat Android UA
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-A556B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36 MicroMessenger/8.0.42(0x28002A2F)"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    assert "MicroMessenger" not in out
    assert "musical_ly_" in out
    assert "Cronet/" not in out
    for token in ("; wv)", "AppleWebKit/537.36", "Version/4.0", "Chrome/", "Mobile Safari/537.36"):
        assert token in out
    _assert_chromium_hints_match(out)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
