"""
v2.6.34 — RUT referrer + in-app detection completeness fixes
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _rp():
    return importlib.import_module("referrer_pro")


def test_messenger_inapp_detected_before_facebook():
    rp = _rp()
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "[FB_IAB/MESSENGER;FBAV/500.0.0.45.102;IABMV/1;]"
    )
    assert rp.is_inapp_browser_ua(ua) == "messenger"


def test_twitter_ios_coercion_uses_canonical_marker():
    rp = _rp()
    base = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 "
        "Mobile/15E148 Safari/604.1"
    )
    ua = rp.coerce_ua_for_platform(base, "twitter")
    assert "Twitter for iPhone/10.98.0" in ua
    assert "TwitterIOS/" not in ua


def test_linkedin_android_inapp_detected():
    rp = _rp()
    ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "com.linkedin.android/4.1.900"
    )
    assert rp.is_inapp_browser_ua(ua) == "linkedin"


def test_messenger_social_wrapper_pool_exists():
    rp = _rp()
    assert "messenger" in rp._SOCIAL_WRAPPER_REFERERS
    ref = rp.build_social_wrapper_referer("messenger", "https://example.com/offer")
    assert ref == "" or "messenger" in ref.lower()


def test_baidu_resolve_pro_visit_uses_search_branch():
    rp = _rp()
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.7432.116 Safari/537.36"
    )
    out = rp.resolve_pro_visit(
        ua=ua,
        platform_pool_value="baidu:100",
        target_url="https://example.com/offer",
        traffic_type="organic",
    )
    assert out.get("platform") == "baidu"
    assert "baidu.com" in (out.get("referer") or "")


def test_naver_resolve_pro_visit_uses_search_branch():
    rp = _rp()
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.7432.116 Safari/537.36"
    )
    out = rp.resolve_pro_visit(
        ua=ua,
        platform_pool_value="naver:100",
        target_url="https://example.com/offer",
        traffic_type="organic",
    )
    assert out.get("platform") == "naver"
    assert "naver.com" in (out.get("referer") or "")


def test_ecosia_build_search_referer():
    rp = _rp()
    ref = rp.build_search_referer("ecosia", "krexion offer")
    assert "ecosia.org" in ref
    assert "krexion" in ref


def test_brave_build_search_referer():
    rp = _rp()
    ref = rp.build_search_referer("brave", "affiliate traffic")
    assert "brave.com" in ref
    assert "affiliate" in ref


def test_youtube_ios_coerce_uses_clean_safari_fallback():
    rp = _rp()
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 "
        "Mobile/15E148 Safari/604.1"
    )
    out = rp.coerce_ua_for_platform(ua, "youtube")
    assert "Safari/" in out
    assert "Version/" in out
    assert "com.google.ios.youtube" not in out


def test_messenger_deep_referer_legacy():
    rp = _rp()
    ref = rp.build_inapp_deep_referer(
        "messenger", "https://example.com/landing", is_paid=None
    )
    assert ref == "" or "messenger" in ref.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
