"""v2.7.47 — Manual link matrix: every platform × referer mode × wrapper safety."""
from __future__ import annotations

import importlib
from urllib.parse import parse_qs, urlparse

import pytest

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_ANDROID_MOBILE = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
_INAPP_UAS = {
    "facebook": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
        "Safari/537.36 [FB_IAB/FB4A;FBAV/450.0.0.0.0;]"
    ),
    "instagram": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
        "Safari/537.36 Instagram 312.0.0.0 Android"
    ),
    "tiktok": (
        "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 "
        "musical_ly_202310905 AppName/musical_ly ByteLocale/en"
    ),
    "twitter": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
        "Safari/537.36 TwitterAndroid"
    ),
    "linkedin": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
        "Safari/537.36 [LinkedInApp]"
    ),
    "snapchat": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
        "Safari/537.36 Snapchat/12.0.0"
    ),
    "pinterest": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
        "Safari/537.36 Pinterest/11.0 Android"
    ),
}
_DEST = "https://offer.example.com/lp"
_LANDING = "https://mylanding.com/promo?cid=abc"
_CUSTOM_HOP = "https://mylanding.com/out?dest={offer_url}"

_POOL_PLATFORMS = (
    "facebook", "instagram", "tiktok", "twitter", "linkedin",
    "google", "bing", "youtube", "snapchat", "pinterest", "reddit", "email",
)
_COLD_NO_WRAPPER = frozenset({"facebook", "instagram", "messenger", "tiktok"})
_INAPP_WRAPPER_OK = frozenset({"twitter", "linkedin", "pinterest", "reddit", "youtube", "snapchat"})


def _rp():
    return importlib.import_module("referrer_pro")


def _base_link(**overrides):
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_referer_mode": "platform_pool",
        "referrer_pro_platform_pool": "facebook:100",
        "referrer_pro_wrapper_redirect": True,
        "referrer_pro_social_wrapper": True,
        "referrer_pro_inapp_deep_path": True,
        "referrer_pro_traffic_type": "paid",
        "referrer_pro_campaign_type": "video_ad",
    }
    link.update(overrides)
    return link


@pytest.mark.parametrize("platform", _POOL_PLATFORMS)
def test_platform_pool_produces_referer_and_platform(platform):
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(referrer_pro_platform_pool=f"{platform}:100"),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
        country="US",
    )
    plat = prep.get("platform") or (prep.get("pro_result") or {}).get("platform")
    assert plat == platform or (platform == "twitter" and plat in ("twitter", "x"))
    if platform not in ("email",):
        assert (prep.get("referer") or "").strip() or platform == "email"


@pytest.mark.parametrize("platform", _POOL_PLATFORMS)
def test_platform_pool_no_wrapper_on_cold_chrome(platform):
    """Desktop Chrome must not HTTP-bounce through FB/TikTok warning shims."""
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(referrer_pro_platform_pool=f"{platform}:100"),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
        country="US",
    )
    wt = str(prep.get("wrapper_target") or "").lower()
    if platform in _COLD_NO_WRAPPER or platform in ("instagram",):
        assert "l.facebook.com" not in wt
        assert "link/v2" not in wt
        assert "flx/warn" not in wt


@pytest.mark.parametrize("platform", tuple(_INAPP_UAS.keys()))
def test_custom_landing_plus_inapp_preset(platform):
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(
            referrer_pro_referer_mode="custom",
            referrer_pro_custom_referer=_LANDING,
            referrer_pro_inapp_preset=platform,
            referrer_pro_wrapper_redirect=False,
        ),
        user_agent=_ANDROID_MOBILE,
        destination_url=_DEST,
        country="US",
    )
    assert prep.get("referer") == _LANDING
    assert prep.get("platform") == platform


@pytest.mark.parametrize("platform", tuple(_INAPP_UAS.keys()))
def test_inapp_ua_unlocks_wrapper_where_safe(platform):
    rp = _rp()
    if platform not in _INAPP_WRAPPER_OK:
        pytest.skip(f"{platform} wrapper not expected on manual links")
    prep = rp.prepare_link_pro_click(
        _base_link(
            referrer_pro_platform_pool=f"{platform}:100",
            referrer_pro_referer_mode="platform_pool",
        ),
        user_agent=_INAPP_UAS[platform],
        destination_url=_DEST,
        country="US",
    )
    wt = str(prep.get("wrapper_target") or "")
    if platform == "twitter":
        assert wt == "" or "redirect" in wt.lower()
    else:
        assert wt == "" or rp._referer_is_bounce_capable(wt)


def test_random_list_picks_from_pool():
    rp = _rp()
    urls = (
        "https://www.facebook.com/groups/a/\n"
        "https://www.instagram.com/p/abc/\n"
        "https://www.tiktok.com/@u/video/1"
    )
    prep = rp.prepare_link_pro_click(
        _base_link(
            referrer_pro_referer_mode="random_list",
            referrer_pro_custom_referer=urls,
        ),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
    )
    ref = prep.get("referer") or ""
    assert any(h in ref for h in ("facebook.com", "instagram.com", "tiktok.com"))


def test_google_search_mode_builds_serp():
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(
            referrer_pro_referer_mode="google_search",
            referrer_pro_custom_referer="best vpn 2026\nfree trial",
            referrer_pro_search_engine="google",
        ),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
        country="us",
    )
    ref = (prep.get("referer") or "").lower()
    assert "google" in ref
    assert "q=" in ref or "search" in ref


def test_direct_mode_empty_referer():
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(referrer_pro_referer_mode="direct"),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
    )
    assert not (prep.get("referer") or "").strip()


def test_auto_mode_uses_inapp_ua_when_present():
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(referrer_pro_referer_mode="auto"),
        user_agent=_INAPP_UAS["tiktok"],
        destination_url=_DEST,
    )
    assert prep.get("platform") == "tiktok"
    assert (prep.get("referer") or "").strip()


def test_custom_hop_macro_expanded():
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(
            referrer_pro_referer_mode="custom",
            referrer_pro_custom_referer=_CUSTOM_HOP,
            referrer_pro_pass_to_offer=True,
        ),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
    )
    hop = prep.get("custom_referer_hop") or ""
    assert hop.startswith("https://mylanding.com/")
    assert "offer.example.com" in hop


def test_offer_url_never_gets_ua_query_param():
    """v2.7.45 — manual links must NOT inject ua/referer/platform on offer URL."""
    rp = _rp()
    for plat in ("facebook", "tiktok", "google"):
        url = rp.enrich_destination_link_realism(
            _DEST,
            user_agent="Mozilla/5.0 TikTok musical_ly",
            referer="https://www.tiktok.com/",
            accept_language="en-US",
            platform=plat,
        )
        qs = parse_qs(urlparse(url).query)
        assert "ua" not in qs
        assert "referer" not in qs
        assert "platform" not in qs


def test_desktop_ua_not_coerced_to_inapp_for_logging_only():
    """Coerced UA in prep is for analytics — real browser keeps its own UA on 302."""
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(referrer_pro_platform_pool="tiktok:100"),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
    )
    assert prep.get("raw_user_agent") == _DESKTOP_UA
    coerced = prep.get("user_agent") or ""
    if coerced and coerced != _DESKTOP_UA:
        assert "musical_ly" in coerced.lower() or "tiktok" in coerced.lower()


def test_inapp_preset_does_not_fake_inapp_on_desktop_wrapper():
    """Preset alone cannot unlock TikTok link/v2 on cold Chrome — needs real in-app UA."""
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(
            referrer_pro_platform_pool="tiktok:100",
            referrer_pro_inapp_preset="tiktok",
            referrer_pro_allow_risky_wrapper=True,
        ),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
    )
    wt = str(prep.get("wrapper_target") or "").lower()
    assert "link/v2" not in wt


@pytest.mark.parametrize("platform", ("facebook", "tiktok", "google"))
def test_platform_pool_does_not_override_custom_http_url(platform):
    """Custom URL in pool mode must NOT replace weighted referer (regression)."""
    rp = _rp()
    prep = rp.prepare_link_pro_click(
        _base_link(
            referrer_pro_referer_mode="platform_pool",
            referrer_pro_platform_pool=f"{platform}:100",
            referrer_pro_custom_referer="https://mylanding.com/only-for-hop",
        ),
        user_agent=_DESKTOP_UA,
        destination_url=_DEST,
    )
    ref = prep.get("referer") or ""
    assert "mylanding.com" not in ref
