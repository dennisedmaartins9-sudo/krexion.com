"""v2.7.39 — TikTok link clicks must not bounce through link/v2 shim."""
from __future__ import annotations

import importlib


def test_prepare_link_pro_click_no_tiktok_wrapper_target():
    rp = importlib.import_module("referrer_pro")
    link = {
        "referrer_pro_enabled": True,
        "referrer_pro_platform_pool": "tiktok:100",
        "referrer_pro_wrapper_redirect": True,
        "referrer_pro_social_wrapper": True,
        "referrer_pro_inapp_deep_path": True,
        "referrer_pro_traffic_type": "paid",
        "referrer_pro_device_mode": "mobile_only",
    }
    prep = rp.prepare_link_pro_click(
        link,
        user_agent=(
            "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
        destination_url="https://offer.example.com/lp?clickid=test123",
        country="us",
    )
    wt = str(prep.get("wrapper_target") or "")
    assert "link/v2" not in wt.lower()
    assert prep.get("simulate_platform") == "tiktok" or prep.get("platform") == "tiktok"


def test_tiktok_social_wrapper_pool_excludes_link_v2():
    rp = importlib.import_module("referrer_pro")
    templates = rp._SOCIAL_WRAPPER_REFERERS.get("tiktok") or []
    urls = [t[1] for t in templates if len(t) > 1]
    assert not any("link/v2" in (u or "") for u in urls)
