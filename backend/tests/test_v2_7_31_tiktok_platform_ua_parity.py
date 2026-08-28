"""v2.7.31 — TikTok pool must not leak Facebook in-app browser identity."""
from __future__ import annotations

import real_user_traffic as rut
from referrer_pro import coerce_ua_for_platform, is_inapp_browser_ua, resolve_pro_visit


def test_infer_dominant_pro_platform_tiktok_only():
    cfg = {"platform_weights": '{"tiktok": 100}'}
    assert rut._infer_dominant_pro_platform(cfg) == "tiktok"


def test_infer_dominant_ignores_mixed_pool():
    cfg = {"platform_weights": '{"tiktok": 50, "facebook": 50}'}
    assert rut._infer_dominant_pro_platform(cfg) == ""


def test_resolve_pro_visit_tiktok_uses_pool_not_ua_sniff():
    fb_ua = (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/119.0 "
        "Mobile Safari/537.36 [FBAN/FB4A;FBAV/443.0]"
    )
    out = resolve_pro_visit(
        ua=fb_ua,
        platform_pool_value="tiktok:100",
        inapp_deep_path_enabled=True,
        traffic_type="paid",
    )
    assert out.get("platform") == "tiktok"
    assert out.get("utm_source") in ("tiktok", "tiktok_ads", "tt", "tiktok_for_business")
    assert "facebook.com" not in (out.get("referer") or "").lower()


def test_pro_pool_auto_scrubs_facebook_marker_for_tiktok():
    fb_ua = (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/119.0 "
        "Mobile Safari/537.36 [FBAN/FB4A;FBAV/443.0]"
    )
    scrubbed = rut._apply_inapp_preset_to_uas([fb_ua], 1, preset_platform="tiktok")
    assert scrubbed
    coerced = coerce_ua_for_platform(scrubbed[0], "tiktok")
    assert coerced
    assert is_inapp_browser_ua(coerced) in ("", "tiktok")
    assert "fban" not in coerced.lower()
