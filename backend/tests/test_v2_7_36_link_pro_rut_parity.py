"""v2.7.36 — Link Pro-Referrer RUT parity helpers."""
from __future__ import annotations

import importlib


def _rp():
    return importlib.import_module("referrer_pro")


def test_normalize_clears_classic_conflicts_when_pro_on():
    rp = _rp()
    out = rp.normalize_link_pro_settings({
        "referrer_pro_enabled": True,
        "forced_source": "facebook",
        "simulate_platform": "tiktok",
        "referrer_mode": "no_referrer",
        "referrer_pro_platform_pool": "tiktok:100",
        "referrer_pro_wrapper_redirect": False,
    })
    assert out.get("forced_source") is None
    assert out.get("simulate_platform") is None
    assert out.get("referrer_mode") == "normal"
    assert out.get("referrer_pro_wrapper_redirect") is True


def test_prepare_link_pro_click_tiktok_coerces_ua_and_wrapper():
    rp = _rp()
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_platform_pool": "tiktok:100",
        "referrer_pro_wrapper_redirect": True,
        "referrer_pro_social_wrapper": True,
        "referrer_pro_inapp_deep_path": True,
        "referrer_pro_lang_match": True,
        "referrer_pro_traffic_type": "paid",
        "referrer_pro_campaign_type": "video_ad",
    }
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
    )
    dest = "https://offer.example.com/?clickid=abc"
    prep = rp.prepare_link_pro_click(link, user_agent=ua, destination_url=dest, country="US")
    assert prep.get("platform") == "tiktok" or (prep.get("pro_result") or {}).get("platform") == "tiktok"
    coerced = prep.get("user_agent") or ""
    low = coerced.lower()
    assert "musical_ly" in low or "trill" in low or "tiktok" in low
    assert (prep.get("referer") or "").strip()
    wt = str(prep.get("wrapper_target") or "")
    assert "link/v2" not in wt.lower()


def test_twitter_wrapper_no_http_bounce():
    rp = _rp()
    dest = "https://offer.example.com/landing"
    bounce = rp.build_wrapper_bounce_url("twitter", dest, is_paid=True)
    assert bounce == "", "Twitter/X i/redirect breaks on cold clicks — direct 302 only"


def test_enrich_destination_no_synthetic_query_params():
    """v2.7.45 — manual clicks must not inject ua/referer/platform/lang on the offer URL."""
    rp = _rp()
    base = "https://offer.example.com/?clickid=1"
    url = rp.enrich_destination_link_realism(
        base,
        user_agent="Mozilla/5.0 TikTok",
        referer="https://www.tiktok.com/",
        accept_language="en-US,en;q=0.9",
        platform="tiktok",
    )
    assert url == base
    for bad in ("ua=", "referer=", "lang=", "platform="):
        assert bad not in url
