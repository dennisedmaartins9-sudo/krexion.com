"""
v2.6.33 — TikTok Android in-app UA completeness fix
====================================================

Customer bug: RUT job with TikTok in-app preset + iOS+Android device
batches + paid/video ad showed TikTok browser on iOS but generic
"Android browser" on Android visits.

Root cause: marker-only idempotency accepted native/partial identities.
Completeness now requires strict validation of a browser-page WebView.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _rp():
    return importlib.import_module("referrer_pro")


def _rut():
    return importlib.import_module("real_user_traffic")


def _srv():
    return importlib.import_module("server")


def test_android_musical_ly_without_fban_is_not_complete():
    rp = _rp()
    ua = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "musical_ly_2024105080 JsSdk/1.0 BytedanceWebview/d8a21c6"
    )
    assert not rp._is_tiktok_android_ua_complete(ua)
    assert not rp._ua_has_inapp_marker(ua, "tiktok")


def test_native_android_with_fabricated_fban_is_not_complete():
    rp = _rp()
    ua = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "TikTok/34.9.5 musical_ly_2024105080 JsSdk/1.0 NetType/WIFI "
        "Channel/googleplay AppName/musical_ly app_version/34.9.5 "
        "BytedanceWebview/d8a21c6 com.zhiliaoapp.musically/3495000000 "
        "[FB_IAB/;FBAN/TikTokAndroid;FBAV/34.9.5;IABMV/1;FBBV/3495000000;FBOP/19;]"
    )
    assert not rp._is_tiktok_android_ua_complete(ua)
    assert not rp._ua_has_inapp_marker(ua, "tiktok")


def test_coerce_upgrades_legacy_android_tiktok_ua():
    rp = _rp()
    legacy = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36 musical_ly_2024105080 "
        "BytedanceWebview/d8a21c6"
    )
    out = rp.coerce_ua_for_platform(legacy, "tiktok")
    assert "FBAN/TikTokAndroid" not in out
    assert "Chrome/" in out
    assert "Mobile Safari/" in out
    assert "Cronet/" not in out


def test_native_tiktok_android_is_incomplete_for_page_navigation():
    legacy = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "musical_ly_2024105080 BytedanceWebview/d8a21c6"
    )
    assert not _rp()._is_tiktok_android_ua_complete(legacy)


def test_facebook_shaped_tiktok_bracket_is_removed():
    ua = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "TikTok/34.9.5 musical_ly_2024105080 "
        "[FB_IAB/;FBAN/TikTokAndroid;FBAV/34.9.5;IABMV/1;FBBV/3495000000;FBOP/19;]"
    )
    out = _rp().coerce_ua_for_platform(ua, "tiktok")
    assert "FBAN/TikTokAndroid" not in out
    assert "[FB_IAB/" not in out
    assert "TikTok/46.4.1" in out


def test_ios_musical_ly_still_idempotent_for_tiktok():
    rp = _rp()
    ios = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "musical_ly_2024105080 JsSdk/1.0 NetType/WIFI AppName/musical_ly "
        "app_version/34.9.5 BytedanceWebview/d8a21c6"
    )
    out = rp.coerce_ua_for_platform(ios, "tiktok")
    assert out.lower().count("musical_ly_") == 1
    assert "FBAN/TikTokAndroid" not in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
