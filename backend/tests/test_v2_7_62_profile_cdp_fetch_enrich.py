"""v2.7.62 — CDP Fetch network-layer param injection (permanent Everflow fix)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_version_is_2_7_62():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.66"


def test_profile_network_enrich_module_exists():
    src = (ROOT / "profile_network_enrich.py").read_text(encoding="utf-8")
    assert "Fetch.continueRequest" in src
    assert "install_profile_cdp_fetch_enricher" in src
    assert "_url_already_enriched" in src


def test_launcher_wires_cdp_fetch_and_ua_platform():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "install_profile_cdp_fetch_enricher" in src
    assert "ua_platform" in src
    assert "_install_profile_cdp_ua_all_pages" in src
    assert "route.continue_(url=nav_url" in src


def test_ua_coerce_prefers_ua_platform():
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
        platform="discord",
        ua_platform="tiktok",
        referer_url="https://discord.com/",
    )
    out = _coerce_profile_ua(base, cfg, referrer_state=st, locale="en-US")
    assert "TikTok/" in out or "musical_ly" in out


def test_discord_params():
    from referrer_pro import build_profile_platform_params

    p = build_profile_platform_params("discord")
    assert p.get("utm_source") in ("discord", "discord_ads")
    assert p.get("clickid")
