"""v2.7.46 — Manual link maximum referrer perfection."""
from __future__ import annotations

import importlib

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TT_INAPP_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 "
    "musical_ly_202310905 AppName/musical_ly ByteLocale/en"
)
_X_INAPP_UA = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
    "Safari/537.36 TwitterAndroid"
)
_DEST = "https://offer.example.com/lp?clickid=test123"
_CUSTOM_LANDING = "https://mylanding.com/out?dest={offer_url}"


def _rp():
    return importlib.import_module("referrer_pro")


def test_platform_from_referer_url_facebook():
    rp = _rp()
    assert rp.platform_from_referer_url("https://l.facebook.com/l.php?u=x") == "facebook"
    assert rp.platform_from_referer_url("https://www.tiktok.com/") == "tiktok"


def test_twitter_wrapper_blocked_on_cold_chrome():
    rp = _rp()
    bounce = rp.build_link_explicit_wrapper_url("twitter", _DEST, is_paid=True)
    assert "redirect" in bounce.lower()
    assert not rp.should_link_wrapper_bounce(
        _DESKTOP_UA, "twitter", bounce, wrapper_redirect_enabled=True
    )


def test_twitter_wrapper_allowed_on_inapp_ua():
    rp = _rp()
    bounce = rp.build_link_explicit_wrapper_url("twitter", _DEST, is_paid=True)
    assert rp.should_link_wrapper_bounce(
        _X_INAPP_UA, "twitter", bounce, wrapper_redirect_enabled=True
    )


def test_tiktok_link_v2_only_with_risky_and_inapp():
    rp = _rp()
    bounce = rp.build_link_explicit_wrapper_url(
        "tiktok", _DEST, is_paid=True, allow_risky=True
    )
    assert "link/v2" in bounce
    assert not rp.should_link_wrapper_bounce(
        _DESKTOP_UA, "tiktok", bounce,
        wrapper_redirect_enabled=True, allow_risky_wrapper=True,
    )
    assert rp.should_link_wrapper_bounce(
        _TT_INAPP_UA, "tiktok", bounce,
        wrapper_redirect_enabled=True, allow_risky_wrapper=True,
    )


def test_custom_referer_and_inapp_preset_in_prepare():
    rp = _rp()
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_referer_mode": "custom",
        "referrer_pro_custom_referer": "https://mybrand.com/promo",
        "referrer_pro_inapp_preset": "tiktok",
        "referrer_pro_social_wrapper": True,
        "referrer_pro_inapp_deep_path": True,
        "referrer_pro_traffic_type": "paid",
    }
    prep = rp.prepare_link_pro_click(
        link, user_agent=_TT_INAPP_UA, destination_url=_DEST, country="US"
    )
    assert prep.get("referer") == "https://mybrand.com/promo"
    assert prep.get("platform") == "tiktok"


def test_tiktok_risky_wrapper_never_on_desktop_chrome_even_if_coerced():
    """Desktop Chrome must never get link/v2 even with risky ON + tiktok pool."""
    rp = _rp()
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_platform_pool": "tiktok:100",
        "referrer_pro_referer_mode": "platform_pool",
        "referrer_pro_wrapper_redirect": True,
        "referrer_pro_allow_risky_wrapper": True,
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
    assert "link/v2" not in wt.lower(), "Cold Chrome must not use TikTok link/v2 wrapper"
    assert prep.get("platform") == "tiktok" or (prep.get("pro_result") or {}).get("platform") == "tiktok"


def test_custom_referer_hop_macro_expanded():
    rp = _rp()
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_platform_pool": "facebook:100",
        "referrer_pro_referer_mode": "platform_pool",
        "referrer_pro_wrapper_redirect": False,
        "referrer_pro_custom_referer": _CUSTOM_LANDING,
        "referrer_pro_pass_to_offer": True,
        "referrer_pro_traffic_type": "paid",
    }
    prep = rp.prepare_link_pro_click(
        link, user_agent=_DESKTOP_UA, destination_url=_DEST, country="US"
    )
    hop = str(prep.get("custom_referer_hop") or "")
    assert hop.startswith("https://mylanding.com/")
    assert "offer.example.com" in hop
    assert prep.get("pass_to_offer") is True


def test_link_custom_referer_mode():
    rp = _rp()
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_referer_mode": "custom",
        "referrer_pro_custom_referer": "https://www.facebook.com/groups/test123/",
        "referrer_pro_traffic_type": "paid",
    }
    prep = rp.prepare_link_pro_click(
        link, user_agent=_DESKTOP_UA, destination_url=_DEST, country="US"
    )
    assert "facebook.com/groups" in str(prep.get("referer") or "")
    assert prep.get("platform") == "facebook"


def test_link_google_search_mode():
    rp = _rp()
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_referer_mode": "google_search",
        "referrer_pro_custom_referer": "best vpn 2026",
        "referrer_pro_search_engine": "google",
    }
    prep = rp.prepare_link_pro_click(
        link, user_agent=_DESKTOP_UA, destination_url=_DEST, country="US"
    )
    ref = str(prep.get("referer") or "")
    assert "google" in ref.lower()
    assert "q=" in ref.lower() or "search" in ref.lower()


def test_facebook_wrapper_skipped_on_desktop_chrome():
    """Cold Chrome must not bounce through l.php → m.facebook.com/flx/warn."""
    rp = _rp()
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_platform_pool": "facebook:100",
        "referrer_pro_wrapper_redirect": True,
        "referrer_pro_social_wrapper": True,
        "referrer_pro_inapp_deep_path": True,
        "referrer_pro_traffic_type": "paid",
    }
    prep = rp.prepare_link_pro_click(
        link, user_agent=_DESKTOP_UA, destination_url=_DEST, country="US"
    )
    wt = str(prep.get("wrapper_target") or "")
    assert not wt
    assert "flx" not in str(prep.get("referer") or "").lower()


def test_linkedin_wrapper_inapp_only():
    rp = _rp()
    bounce = rp.build_link_explicit_wrapper_url("linkedin", _DEST, is_paid=True)
    assert "linkedin.com/redir" in bounce
    assert not rp.should_link_wrapper_bounce(
        _DESKTOP_UA, "linkedin", bounce, wrapper_redirect_enabled=True
    )
