"""v2.7.60 — Profile enrich via route.fetch + CDP UA + platform inference."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_version_is_2_7_60():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.66"


def test_enrich_when_referrer_enabled_skips_only_neutral_home():
    from browser_profile_launcher import _should_enrich_profile_offer_url

    assert _should_enrich_profile_offer_url("https://www.google.com/", referrer_enabled=True) is False
    assert _should_enrich_profile_offer_url(
        "https://tracker.example/aff_c?offer_id=3291", referrer_enabled=True
    ) is True
    assert _should_enrich_profile_offer_url(
        "https://offer-landing.example/quiz", referrer_enabled=True
    ) is True


def test_profile_enrich_platform_from_referer():
    from browser_profile_launcher import _ProfileReferrerState, _profile_enrich_platform

    st = _ProfileReferrerState(
        enabled=True,
        referer_url="https://www.tiktok.com/@user/video/123",
    )
    assert _profile_enrich_platform(st) == "tiktok"


def test_enrich_profile_offer_url_infers_platform_from_referer():
    from referrer_pro import enrich_profile_offer_url

    out = enrich_profile_offer_url(
        "https://tracker.example/aff_c?offer_id=3291",
        referer_url="https://www.tiktok.com/@x/video/1",
    )
    assert "ttclid=" in out
    assert "utm_source=" in out
    assert "clickid=" in out


def test_tiktok_params_use_long_ttclid():
    from referrer_pro import build_profile_platform_params

    p = build_profile_platform_params("tiktok")
    assert len(p.get("ttclid", "")) >= 60


def test_launcher_uses_route_fetch_for_enrich():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "302" in src.split("make_profile_referrer_route_handler")[1].split("return _handler")[0]
    assert "_profile_enrich_platform" in src


def test_tiktok_coerce_adds_marker():
    from browser_profile_launcher import _ProfileReferrerState, _coerce_profile_ua
    from referrer_pro import _android_webview_base, _verified_android_parts

    cfg = {
        "referrer": {
            "enabled": True,
            "match_ua_to_platform": True,
            "platform_weights": {"tiktok": 100},
        }
    }
    base = _android_webview_base(_verified_android_parts())
    st = _ProfileReferrerState(
        enabled=True,
        platform="tiktok",
        referer_url="https://www.tiktok.com/@u/video/1",
    )
    out = _coerce_profile_ua(base, cfg, referrer_state=st, locale="en-US")
    assert "TikTok/" in out or "musical_ly" in out
