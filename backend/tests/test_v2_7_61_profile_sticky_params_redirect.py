"""v2.7.62 — Sticky session params + 302 redirect enrich (Everflow Parameters fix)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_version_is_2_7_61():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.66"


def test_email_referrer_enriches_everflow_aliases():
    from referrer_pro import enrich_profile_offer_url

    out = enrich_profile_offer_url(
        "https://network.evyy.net/aff_c?offer_id=3291",
        platform="email",
        referer_url="https://mail.google.com/",
    )
    assert "utm_source=" in out
    assert "clickid=" in out
    assert "sub1=" in out
    assert "aff_sub=" in out
    assert "source_id=" in out


def test_instagram_params_include_igshid():
    from referrer_pro import enrich_profile_offer_url

    out = enrich_profile_offer_url(
        "https://tracker.example/aff_c?offer_id=1",
        platform="instagram",
    )
    assert "igshid=" in out
    assert "utm_source=" in out


def test_sticky_params_same_clickid_twice():
    from browser_profile_launcher import (
        _ProfileReferrerState,
        _ensure_sticky_profile_params,
        _profile_enrich_nav_url,
    )

    st = _ProfileReferrerState(
        enabled=True,
        platform="email",
        referer_url="https://mail.google.com/",
        session_id="sess-abc-123",
        click_id="sticky999",
        pro_extras={"click_id": "sticky999", "clickid": "sticky999"},
    )
    p1 = _ensure_sticky_profile_params(st)
    p2 = _ensure_sticky_profile_params(st)
    assert p1["clickid"] == p2["clickid"] == "sticky999"
    u1 = _profile_enrich_nav_url("https://tracker.example/aff_c?offer_id=3291", st)
    u2 = _profile_enrich_nav_url("https://tracker.example/aff_c?offer_id=3291", st)
    assert "clickid=sticky999" in u1
    assert u1 == u2


def test_launcher_uses_302_redirect_enrich():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "route.continue_(url=nav_url" in src
    assert "install_profile_cdp_fetch_enricher" in src
    handler = src.split("make_profile_referrer_route_handler")[1].split("return _handler")[0]
    assert "route.continue_(url=nav_url" in handler


def test_generic_platform_still_gets_clickid():
    from referrer_pro import build_profile_platform_params

    p = build_profile_platform_params("generic", session_id="abc")
    assert p.get("clickid")
    assert p.get("sub1")
