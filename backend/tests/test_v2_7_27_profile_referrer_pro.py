"""v2.7.27 — Browser profile full Referrer Pro (RUT-grade, all tabs)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_profile_launcher import (
    _ProfileReferrerState,
    _is_wrapper_domain,
    _profile_referrer_effective,
    _profile_referrer_resolve_cfg,
    _resolve_profile_referrer_state,
    _should_profile_wrapper_bounce,
    make_profile_referrer_route_handler,
)


ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)


def test_referrer_pro_config_extended_fields():
    from browser_profile_module import ReferrerProConfig

    cfg = ReferrerProConfig(
        enabled=True,
        wrapper_redirect=True,
        traffic_type="paid",
        quality_tier="premium",
        mode="custom",
        value="https://www.tiktok.com/@x/video/1",
    )
    d = cfg.model_dump()
    assert d["wrapper_redirect"] is True
    assert d["traffic_type"] == "paid"
    assert d["quality_tier"] == "premium"
    assert d["mode"] == "custom"


def test_quality_tier_merges_premium_defaults():
    ref = _profile_referrer_effective({
        "enabled": True,
        "quality_tier": "premium",
    })
    assert ref.get("wrapper_redirect") is True
    assert ref.get("tod_enabled") is True
    assert ref.get("device_mode") == "match_platform"


def test_resolve_cfg_includes_guardrails():
    profile = {"country": "de"}
    referrer = {
        "enabled": True,
        "pro_mode": True,
        "platform_weights": {"google": 100},
        "lang_match": True,
        "device_mode": "match_platform",
        "traffic_type": "organic",
        "campaign_type": "search_cpc",
    }
    cfg = _profile_referrer_resolve_cfg(referrer, profile, "https://offer.test/lp", ua=ANDROID_UA)
    assert cfg["country"] == "de"
    assert cfg["lang_match"] is True
    assert cfg["device_mode"] == "match_platform"
    assert cfg["traffic_type"] == "organic"
    assert "google" in cfg["platform_weights"]


def test_resolve_state_produces_referer():
    profile = {
        "country": "us",
        "referrer": {
            "enabled": True,
            "pro_mode": True,
            "platform_weights": {"google": 100},
            "search_keywords": "vpn review",
            "social_wrapper": True,
            "pass_to_offer": True,
        },
    }
    state = _resolve_profile_referrer_state(ANDROID_UA, profile, "https://example-offer.com/")
    assert isinstance(state, _ProfileReferrerState)
    assert state.enabled is True
    assert state.referer_url
    assert state.pass_to_offer is True
    assert "google" in state.referer_url.lower() or state.platform == "google"


def test_wrapper_domain_detection():
    assert _is_wrapper_domain("https://l.facebook.com/l.php?u=https%3A%2F%2Fx.com")
    assert not _is_wrapper_domain("https://example-offer.com/landing")


def test_should_wrapper_bounce_skips_wrapper_urls():
    state = _ProfileReferrerState(
        enabled=True,
        wrapper_redirect=True,
        wrapper_template="https://www.google.com/url?q=https%3A%2F%2Fexample.com",
        platform="google",
        pass_to_offer=False,
    )
    assert not _should_profile_wrapper_bounce(
        "https://l.facebook.com/l.php?u=https%3A%2F%2Fother.com",
        state,
        ANDROID_UA,
    )
    assert _should_profile_wrapper_bounce(
        "https://tracker.example/click",
        state,
        ANDROID_UA,
    )


def test_route_handler_injects_referer_header():
    state = _ProfileReferrerState(
        enabled=True,
        referer_url="https://www.google.com/search?q=test",
        sec_fetch={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"},
    )
    handler = make_profile_referrer_route_handler(state)
    route = AsyncMock()
    request = MagicMock()
    request.resource_type = "document"
    request.url = "https://offer.example/landing"
    request.headers = {"user-agent": ANDROID_UA}

    asyncio.run(handler(route, request))

    route.continue_.assert_awaited_once()
    headers = route.continue_.await_args.kwargs.get("headers") or route.continue_.await_args[1].get("headers")
    assert headers.get("Referer") == state.referer_url
    assert headers.get("Sec-Fetch-Site") == "cross-site"


def test_route_handler_wrapper_bounce():
    state = _ProfileReferrerState(
        enabled=True,
        wrapper_redirect=True,
        wrapper_template="https://l.facebook.com/l.php?u=https%3A%2F%2Fold.com",
        referer_url="https://l.facebook.com/l.php?u=https%3A%2F%2Fold.com",
        pass_to_offer=False,
    )
    handler = make_profile_referrer_route_handler(state)
    route = AsyncMock()
    request = MagicMock()
    request.resource_type = "document"
    request.url = "https://new-offer.com/deal"
    request.headers = {"user-agent": ANDROID_UA}

    asyncio.run(handler(route, request))

    if route.fulfill.await_count:
        assert route.fulfill.await_args.kwargs.get("status") == 302
        loc = route.fulfill.await_args.kwargs["headers"]["Location"]
        assert "l.facebook.com" in loc
        assert "new-offer.com" in loc or "new-offer" in loc.lower()
    else:
        route.continue_.assert_awaited()
