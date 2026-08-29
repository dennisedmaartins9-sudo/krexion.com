"""v2.7.35 — Pro-Referrer: no blank referers when wrapper/pool enabled."""
from __future__ import annotations

import importlib


def _rp():
    return importlib.import_module("referrer_pro")


def test_tiktok_preview_never_empty_referer_with_wrapper():
    rp = _rp()
    for _ in range(30):
        out = rp.resolve_pro_visit(
            ua=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Safari/604.1"
            ),
            platform_pool_value="tiktok:100",
            target_url="https://example.com/offer",
            traffic_type="paid",
            campaign_type="video_ad",
            require_non_empty_referer=True,
            wrapper_redirect=True,
        )
        assert out.get("platform") == "tiktok"
        assert (out.get("referer") or "").strip(), "referer must not be blank"


def test_tiktok_wrapper_bounce_url_no_link_v2():
    rp = _rp()
    dest = "https://offer.example.com/?clickid=abc"
    bounce = rp.build_wrapper_bounce_url("tiktok", dest, is_paid=True)
    assert bounce == "", "TikTok must not HTTP-bounce through link/v2"
    assert not rp.is_safe_http_wrapper_bounce(
        "https://www.tiktok.com/link/v2?aid=1988&lang=en&u=https%3A%2F%2Fx.com"
    )
    assert not rp.platform_supports_http_wrapper_bounce("tiktok")
    ensure = rp.ensure_wrapper_bounce_url("", "tiktok", dest, is_paid=True)
    assert ensure == ""


def test_ensure_non_empty_falls_back_to_homepage():
    rp = _rp()
    ref = rp.ensure_non_empty_referer("", "tiktok", "https://x.com", is_paid=True)
    assert ref
    assert "tiktok" in ref.lower()


def test_coerce_tiktok_mobile_ua_from_iphone_safari():
    rp = _rp()
    base = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
    )
    ua = rp.coerce_ua_for_platform(base, "tiktok")
    low = ua.lower()
    assert "musical_ly" in low or "trill" in low or "tiktok" in low
