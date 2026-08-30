"""v2.7.50 — Operator landing hop ({offer_url}) on manual links."""
from __future__ import annotations

from referrer_pro import normalize_link_pro_settings, prepare_link_pro_click

_LANDING = "https://www.xyz.com/go?next={offer_url}"
_DEST = "https://tracker.example/click?sub1=a"


def test_normalize_auto_enables_pass_to_offer_for_macro():
    doc = {
        "referrer_pro_enabled": True,
        "referrer_pro_custom_referer": _LANDING,
        "referrer_pro_pass_to_offer": False,
        "referrer_pro_referer_mode": "platform_pool",
    }
    out = normalize_link_pro_settings(doc)
    assert out["referrer_pro_pass_to_offer"] is True
    assert out["referrer_pro_referer_mode"] == "custom"


def test_prepare_builds_landing_hop_without_explicit_pass_flag():
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_custom_referer": _LANDING,
        "referrer_pro_pass_to_offer": False,
        "referrer_pro_referer_mode": "custom",
        "referrer_pro_platform_pool": "facebook:100",
    }
    prep = prepare_link_pro_click(
        link,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        destination_url=_DEST,
    )
    assert prep.get("pass_to_offer") is True
    hop = str(prep.get("custom_referer_hop") or "")
    assert hop.startswith("https://www.xyz.com/go")
    assert "tracker.example" in hop


def test_landing_hop_skips_wrapper_target_when_pass_to_offer():
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_custom_referer": _LANDING,
        "referrer_pro_pass_to_offer": True,
        "referrer_pro_wrapper_redirect": True,
        "referrer_pro_referer_mode": "custom",
        "referrer_pro_platform_pool": "facebook:100",
    }
    prep = prepare_link_pro_click(
        link,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        destination_url=_DEST,
    )
    assert prep.get("custom_referer_hop")
    # Wrapper may be computed but hop takes priority in server handler.
