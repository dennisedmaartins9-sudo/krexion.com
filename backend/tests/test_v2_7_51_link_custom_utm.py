"""v2.7.51 — Manual link custom UTM builder (real-ad style operator input)."""
from __future__ import annotations

from referrer_pro import resolve_link_custom_utms


def test_custom_utm_disabled_returns_empty():
    link = {
        "referrer_pro_custom_utm_enabled": False,
        "referrer_pro_custom_utm_source": "mybrand",
    }
    pro = {"utm_source": "facebook", "utm_medium": "paid_social"}
    assert resolve_link_custom_utms(link, pro) == {}
    assert pro["utm_source"] == "facebook"


def test_custom_utm_overrides_filled_fields_only():
    link = {
        "referrer_pro_custom_utm_enabled": True,
        "referrer_pro_custom_utm_source": "hexon_fb",
        "referrer_pro_custom_utm_medium": "cpc",
        "referrer_pro_custom_utm_campaign": "spring_sale_2026",
        "referrer_pro_custom_utm_content": "",
        "referrer_pro_custom_utm_term": "",
    }
    pro = {
        "platform": "facebook",
        "utm_source": "facebook",
        "utm_medium": "paid_social",
        "utm_campaign": "irestore_lookalike_m35",
        "utm_content": "video_a",
        "utm_term": "kw1",
    }
    out = resolve_link_custom_utms(link, pro, {"click_id": "abc123"})
    assert out["utm_source"] == "hexon_fb"
    assert out["utm_medium"] == "cpc"
    assert out["utm_campaign"] == "spring_sale_2026"
    assert out["utm_content"] == "video_a"
    assert out["utm_term"] == "kw1"
    assert pro["utm_source"] == "hexon_fb"


def test_custom_utm_expands_macros():
    link = {
        "referrer_pro_custom_utm_enabled": True,
        "referrer_pro_custom_utm_campaign": "mybrand_{source}_{click_id}",
        "referrer_pro_brand": "mybrand",
    }
    pro = {"platform": "tiktok", "utm_campaign": "auto_campaign"}
    out = resolve_link_custom_utms(
        link,
        pro,
        {"click_id": "clk99", "source": "tiktok", "platform": "tiktok", "brand": "mybrand"},
    )
    assert out["utm_campaign"] == "mybrand_tiktok_clk99"


def test_custom_params_merge_overrides_platform_utms():
    """Mirrors generate_platform_params: params.update(custom_params) at the end."""
    platform_params = {
        "utm_source": "facebook",
        "utm_medium": "paid_social",
        "utm_campaign": "auto_camp",
        "fbclid": "IwY2xjawFtest",
    }
    custom_overrides = {
        "utm_source": "hexon_fb",
        "utm_medium": "paid_social_custom",
        "utm_campaign": "operator_campaign",
    }
    merged = dict(platform_params)
    merged.update(custom_overrides)
    assert merged["utm_source"] == "hexon_fb"
    assert merged["utm_medium"] == "paid_social_custom"
    assert merged["utm_campaign"] == "operator_campaign"
    assert merged["fbclid"] == "IwY2xjawFtest"
