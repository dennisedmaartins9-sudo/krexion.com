"""v2.7.40 — All platforms: no broken HTTP wrapper bounce on cold link clicks."""
from __future__ import annotations

import importlib

import pytest

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
_DEST = "https://offer.example.com/lp?clickid=test123"

_SOCIAL_PLATFORMS = (
    "facebook", "instagram", "tiktok", "twitter", "x", "linkedin",
    "reddit", "youtube", "snapchat", "pinterest", "messenger",
)


def _rp():
    return importlib.import_module("referrer_pro")


@pytest.mark.parametrize("platform", _SOCIAL_PLATFORMS)
def test_social_platforms_never_build_http_bounce(platform):
    rp = _rp()
    bounce = rp.build_wrapper_bounce_url(platform, _DEST, is_paid=True)
    assert bounce == "", f"{platform} must not HTTP-bounce through platform shim"


@pytest.mark.parametrize("platform", _SOCIAL_PLATFORMS)
def test_prepare_link_pro_click_no_wrapper_on_cold_social(platform):
    rp = _rp()
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_platform_pool": f"{platform}:100",
        "referrer_pro_wrapper_redirect": True,
        "referrer_pro_social_wrapper": True,
        "referrer_pro_inapp_deep_path": True,
        "referrer_pro_traffic_type": "paid",
    }
    prep = rp.prepare_link_pro_click(
        link,
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
        country="US",
    )
    wt = str(prep.get("wrapper_target") or "")
    assert not wt, f"{platform} cold click must not set wrapper_target"
    assert (prep.get("referer") or "").strip(), f"{platform} referer must still be set"


def test_google_cold_click_allows_safe_bounce():
    rp = _rp()
    bounce = rp.build_wrapper_bounce_url("google", _DEST, is_paid=True)
    assert bounce.startswith("https://www.google.com/url?")
    assert rp.is_safe_http_wrapper_bounce(bounce)
    assert rp.should_http_wrapper_bounce(_DESKTOP_UA, "google", bounce)


def test_bing_cold_click_allows_safe_bounce():
    rp = _rp()
    bounce = rp.build_wrapper_bounce_url("bing", _DEST, is_paid=True)
    assert bounce.startswith("https://www.bing.com/aclick?")
    assert rp.should_http_wrapper_bounce(_DESKTOP_UA, "bing", bounce)


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://www.tiktok.com/link/v2?u=https%3A%2F%2Foffer.example.com",
        "https://l.facebook.com/l.php?u=https%3A%2F%2Foffer.example.com",
        "https://l.instagram.com/?u=https%3A%2F%2Foffer.example.com",
        "https://www.youtube.com/redirect?q=https%3A%2F%2Foffer.example.com",
        "https://x.com/i/redirect?url=https%3A%2F%2Foffer.example.com",
        "https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Foffer.example.com",
        "https://out.reddit.com/?url=https%3A%2F%2Foffer.example.com",
        "https://www.pinterest.com/offsite/?url=https%3A%2F%2Foffer.example.com",
    ],
)
def test_warning_trigger_urls_blocked_on_cold_click(bad_url):
    rp = _rp()
    assert rp.is_warning_trigger_wrapper_url(bad_url)
    assert not rp.is_safe_http_wrapper_bounce(bad_url)
    assert not rp.should_http_wrapper_bounce(_DESKTOP_UA, "facebook", bad_url)
    assert not rp.should_http_wrapper_bounce(_MOBILE_UA, "tiktok", bad_url)


def test_tiktok_platform_no_http_wrapper_support():
    rp = _rp()
    assert not rp.platform_supports_http_wrapper_bounce("tiktok")
    assert not rp.platform_supports_http_wrapper_bounce("facebook")
    assert rp.platform_supports_http_wrapper_bounce("google")


def test_is_cold_external_detects_desktop_and_mismatch_inapp():
    rp = _rp()
    assert rp.is_cold_external_link_click(_DESKTOP_UA, "facebook")
    fb_inapp = (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
        "Safari/537.36 [FB_IAB/FB4A;FBAV/450.0.0.0.0;]"
    )
    assert not rp.is_cold_external_link_click(fb_inapp, "facebook")
    assert rp.is_cold_external_link_click(fb_inapp, "tiktok")
