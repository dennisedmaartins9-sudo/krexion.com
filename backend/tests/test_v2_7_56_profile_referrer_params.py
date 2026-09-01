"""v2.7.56 — Browser profile referer + UTM/fbclid/clickid on offer navigations."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_version_is_2_7_56():
    from packaging.version import Version

    assert Version(_read("VERSION").strip()) >= Version("2.7.56")


def test_normalize_referer_url_adds_https():
    from referrer_pro import normalize_referer_url

    assert normalize_referer_url("www.test.com") == "https://www.test.com"
    assert normalize_referer_url("https://fb.com/x") == "https://fb.com/x"


def test_dominant_platform_from_weights():
    from referrer_pro import dominant_platform_from_weights

    assert dominant_platform_from_weights({"facebook": 100, "tiktok": 0}) == "facebook"


def test_custom_mode_uses_platform_weights_for_utms():
    import real_user_traffic as rut

    cfg = {
        "enabled": True,
        "mode": "custom",
        "value": "www.test.com",
        "pro_mode": True,
        "platform_weights": '{"facebook": 100}',
        "brand": "your-brand",
        "traffic_type": "paid",
        "campaign_type": "video_ad",
    }
    ref, plat, _esp, extras = rut._resolve_visit_referer(
        "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/136.0.0.0 Mobile Safari/537.36",
        cfg,
    )
    assert ref == "https://www.test.com"
    assert plat == "facebook"
    assert extras.get("utm_source")


def test_enrich_profile_offer_url_adds_fbclid():
    from referrer_pro import enrich_profile_offer_url

    out = enrich_profile_offer_url(
        "https://tracker.example/aff_c?offer_id=3294",
        platform="youtube",
        brand="test",
    )
    assert "gclid=" in out
    assert "utm_medium=" in out
    assert "clickid=" in out
    assert "aff_sub=" in out
    assert "aff_sub3=youtube" in out
    assert "source_id=" not in out


def test_enrich_does_not_import_server():
    src = (ROOT / "referrer_pro.py").read_text(encoding="utf-8")
    block = src.split("def enrich_profile_offer_url")[1].split("def enrich_destination")[0]
    assert "from server import" not in block


def test_profile_launcher_has_enrich_helpers():
    src = _read("browser_profile_launcher.py")
    assert "_profile_enrich_nav_url" in src
    assert "_should_enrich_profile_offer_url" in src
    assert "_ensure_sticky_profile_params" in src
    assert "status=302" in src
    assert "normalize_referer_url" in src


def test_neutral_google_start_not_enriched():
    from browser_profile_launcher import (
        _ProfileReferrerState,
        _should_enrich_profile_offer_url,
    )

    assert _should_enrich_profile_offer_url("https://www.google.com/") is False
    assert _should_enrich_profile_offer_url(
        "https://tracker.example/click?offer_id=3303"
    ) is True
    st = _ProfileReferrerState(enabled=True, platform="facebook")
    from browser_profile_launcher import _profile_enrich_nav_url

    assert _profile_enrich_nav_url("https://www.google.com/", st) == "https://www.google.com/"
