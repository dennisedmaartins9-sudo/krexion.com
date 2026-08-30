"""v2.7.49 — Manual link max-perfect: cold referer shim + HTML hop."""
from __future__ import annotations

from referrer_pro import (
    build_cold_click_referer_wrapper,
    build_perfect_manual_hop_html,
    is_cold_external_link_click,
)


COLD_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def test_cold_facebook_uses_google_shim():
    dest = "https://tracker.example/click?fbclid=abc"
    wrap = build_cold_click_referer_wrapper(COLD_CHROME, "facebook", dest)
    assert wrap.startswith("https://www.google.com/url?q=")
    assert "tracker.example" in wrap


def test_inapp_facebook_skips_cold_shim():
    fb_inapp = (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 "
        "[FB_IAB/FB4A;FBAV/450.0.0.0.0;]"
    )
    assert is_cold_external_link_click(fb_inapp, "facebook") is False
    wrap = build_cold_click_referer_wrapper(fb_inapp, "facebook", "https://offer.test/")
    assert wrap == ""


def test_cold_google_uses_google_wrapper():
    wrap = build_cold_click_referer_wrapper(
        COLD_CHROME, "google", "https://offer.test/lp",
    )
    assert "google.com/url" in wrap


def test_perfect_hop_html_contains_policy_and_target():
    html = build_perfect_manual_hop_html(
        "https://www.google.com/url?q=https%3A%2F%2Foffer.test",
        referer_policy="unsafe-url",
    )
    assert 'content="unsafe-url"' in html
    assert "google.com/url" in html
    assert "window.location.replace" in html
    assert "kx-continue" in html


def test_hop_html_encodes_plus_in_utm_for_meta_refresh():
    """UTM values with spaces/plus must not break meta refresh (Redirecting… hang)."""
    html = build_perfect_manual_hop_html(
        "https://tracker.example/click?utm_source=facebook+test&utm_content=video+ad",
    )
    assert "facebook+test" not in html or "facebook%20test" in html or "facebook%2Btest" in html
    assert "video+ad" not in html or "video%20ad" in html or "video%2Bad" in html
    assert "Continue to offer" in html
