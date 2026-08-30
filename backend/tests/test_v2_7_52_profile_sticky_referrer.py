"""v2.7.52 — Browser profile sticky referer (one platform per launch)."""
from __future__ import annotations

from unittest.mock import patch

from browser_profile_launcher import (
    _ProfileReferrerState,
    _coerce_profile_ua,
    _resolve_profile_referrer_state,
)

ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)


def test_coerce_ua_uses_preresolved_platform_without_second_resolve():
    sticky = _ProfileReferrerState(
        enabled=True,
        platform="tiktok",
        referer_url="https://www.tiktok.com/",
    )
    profile = {
        "referrer": {
            "enabled": True,
            "match_ua_to_platform": True,
            "platform_weights": {"facebook": 100},
        },
    }
    with patch(
        "browser_profile_launcher._resolve_profile_referrer_state",
        side_effect=AssertionError("must not re-resolve when state provided"),
    ):
        out = _coerce_profile_ua(ANDROID_UA, profile, referrer_state=sticky)
    assert "musical_ly" in out.lower() or "tiktok" in out.lower() or out != ANDROID_UA


def test_resolve_once_produces_consistent_platform():
    profile = {
        "country": "us",
        "referrer": {
            "enabled": True,
            "pro_mode": True,
            "platform_weights": {"facebook": 50, "tiktok": 50},
            "pass_to_offer": True,
        },
    }
    state = _resolve_profile_referrer_state(ANDROID_UA, profile, "https://offer.test/")
    assert state.enabled is True
    assert state.platform in ("facebook", "tiktok")
    coerced = _coerce_profile_ua(ANDROID_UA, profile, referrer_state=state)
    assert coerced
