"""v2.7.48 — Browser Profile + Manual Link perfect referrer bridge."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_profile_launcher import (
    _ProfileReferrerState,
    _resolve_profile_referrer_state,
    _should_profile_wrapper_bounce,
    make_profile_referrer_route_handler,
)
from referrer_pro import (
    KREXION_PROFILE_SESSION_HEADER,
    is_krexion_short_link_url,
    should_link_wrapper_bounce,
)


ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

TIKTOK_INAPP_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 "
    "musical_ly_2023209030 JsSdk/1.0 NetType/WIFI Channel/googleplay AppName/"
    "musical_ly app_version/32.9.3 ByteLocale/en ByteFullLocale/en Region/US "
    "AppId/1233 Spark/1.4.7-alpha.8 AppVersion/32.9.3 PIA/1.4.3 RevealType/Dialog"
)


def test_is_krexion_short_link_url():
    assert is_krexion_short_link_url("https://krexion.com/r/abc123")
    assert is_krexion_short_link_url("https://krexion.com/t/xyz")
    assert is_krexion_short_link_url("https://krexion.com/api/t/abc123")
    assert not is_krexion_short_link_url("https://krexion.com/admin")
    assert not is_krexion_short_link_url("https://offer.example/lp")


def test_pass_to_offer_skips_profile_wrapper_bounce():
    state = _ProfileReferrerState(
        enabled=True,
        wrapper_redirect=True,
        wrapper_template="https://l.facebook.com/l.php?u=https%3A%2F%2Fexample.com",
        pass_to_offer=True,
    )
    assert not _should_profile_wrapper_bounce("https://offer.test/lp", state, ANDROID_UA)


def test_profile_wrapper_uses_link_bounce_rules_when_pass_to_offer_off():
    state = _ProfileReferrerState(
        enabled=True,
        wrapper_redirect=True,
        wrapper_template="https://l.facebook.com/l.php?u=https%3A%2F%2Fexample.com",
        platform="facebook",
        pass_to_offer=False,
    )
    # Cold desktop Chrome — manual-link rules block Meta wrapper.
    cold = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    assert not _should_profile_wrapper_bounce("https://offer.test/lp", state, cold)
    # In-app FB UA — wrapper allowed (profile session, not cold).
    fb_inapp = (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 "
        "[FB_IAB/FB4A;FBAV/450.0.0.0.0;]"
    )
    assert _should_profile_wrapper_bounce("https://offer.test/lp", state, fb_inapp)


def test_resolve_state_pass_to_offer_not_broken_by_typo_regression():
    """Regression: pass_to_offer must not reference undefined `ref` variable."""
    profile = {
        "country": "us",
        "referrer": {
            "enabled": True,
            "pro_mode": True,
            "platform_weights": {"tiktok": 100},
            "pass_to_offer": True,
            "allow_risky_wrapper": False,
        },
    }
    state = _resolve_profile_referrer_state(ANDROID_UA, profile, "https://offer.test/")
    assert state.enabled is True
    assert state.pass_to_offer is True
    assert state.platform == "tiktok" or "tiktok" in (state.referer_url or "").lower()


def test_route_handler_adds_profile_session_header_on_krexion_link():
    state = _ProfileReferrerState(
        enabled=True,
        referer_url="https://www.tiktok.com/@user/video/1",
        session_id="sess-abc-123",
        pass_to_offer=True,
    )
    handler = make_profile_referrer_route_handler(state)
    route = AsyncMock()
    request = MagicMock()
    request.resource_type = "document"
    request.url = "https://krexion.com/r/office01"
    request.headers = {"user-agent": TIKTOK_INAPP_UA}

    asyncio.run(handler(route, request))

    route.continue_.assert_awaited_once()
    headers = route.continue_.await_args.kwargs.get("headers") or {}
    assert headers.get(KREXION_PROFILE_SESSION_HEADER.lower()) == "sess-abc-123"
    # Playwright continues with canonical "Referer" casing
    assert (headers.get("Referer") or headers.get("referer")) == state.referer_url


def test_validate_profile_perfect_session():
    from browser_profile_module import validate_profile_perfect_session

    class _SessCol:
        async def find_one(self, q):
            if q.get("id") == "good-session":
                return {"id": "good-session", "profile_id": "prof-1", "status": "running"}
            return None

    class _ProfCol:
        async def find_one(self, q):
            if q.get("id") == "prof-1":
                return {
                    "id": "prof-1",
                    "referrer": {"enabled": True, "pass_to_offer": True, "preset_platform": "tiktok"},
                }
            return None

    class _FakeDb:
        browser_profile_sessions = _SessCol()
        browser_profiles = _ProfCol()

    ok = asyncio.run(validate_profile_perfect_session(_FakeDb(), "good-session"))
    assert ok["ok"] is True
    assert ok["profile_id"] == "prof-1"

    bad = asyncio.run(validate_profile_perfect_session(_FakeDb(), "missing"))
    assert bad["ok"] is False


def test_cold_chrome_blocks_link_wrapper_consistent():
    cold = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    fb_wrap = "https://l.facebook.com/l.php?u=https%3A%2F%2Foffer.com"
    assert not should_link_wrapper_bounce(
        cold, "facebook", fb_wrap, wrapper_redirect_enabled=True,
    )
