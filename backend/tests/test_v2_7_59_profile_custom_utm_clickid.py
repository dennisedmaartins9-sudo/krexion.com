"""v2.7.59 — Profile custom UTMs + sticky clickid + merge empty query keys."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_version_is_2_7_59():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.63"


def test_merge_url_query_params_fills_empty_existing():
    from referrer_pro import merge_url_query_params

    url = "https://tracker.example/aff_c?offer_id=3291&clickid="
    out = merge_url_query_params(url, {"clickid": "abc123", "utm_source": "facebook"})
    assert "clickid=abc123" in out
    assert "utm_source=facebook" in out


def test_resolve_profile_custom_utms():
    from referrer_pro import resolve_profile_custom_utms

    referrer = {
        "custom_utm_enabled": True,
        "custom_utm_source": "hexon_fb",
        "custom_utm_medium": "paid_social",
        "custom_utm_campaign": "sale_{click_id}",
        "brand": "mybrand",
    }
    out = resolve_profile_custom_utms(
        referrer,
        {"platform": "facebook", "utm_medium": "cpc"},
        {"click_id": "tok999"},
    )
    assert out["utm_source"] == "hexon_fb"
    assert out["utm_medium"] == "paid_social"
    assert "tok999" in out["utm_campaign"]


def test_build_profile_platform_params_sticky_click_from_extras():
    from referrer_pro import build_profile_platform_params

    params = build_profile_platform_params(
        "facebook",
        pro_extras={"click_id": "sticky42", "utm_source": "fbads"},
    )
    assert params["clickid"] == "sticky42"
    assert params["click_id"] == "sticky42"
    assert params["utm_source"] == "fbads"


def test_build_profile_custom_click_id_macro():
    from referrer_pro import build_profile_platform_params

    params = build_profile_platform_params(
        "youtube",
        pro_extras={
            "click_id": "baseid",
            "custom_click_id": "ef_{click_id}",
        },
    )
    assert params["clickid"] == "ef_baseid"


def test_referrer_pro_config_has_custom_utm_fields():
    from browser_profile_module import ReferrerProConfig

    cfg = ReferrerProConfig(
        custom_utm_enabled=True,
        custom_utm_source="x",
        custom_click_id="{click_id}",
    )
    assert cfg.custom_utm_enabled is True
    assert cfg.custom_utm_source == "x"


def test_profile_panel_source_has_custom_utm_ui():
    src = (ROOT.parent / "frontend" / "src" / "components" / "ReferrerProProfilePanel.js").read_text(
        encoding="utf-8"
    )
    assert "custom_utm_enabled" in src
    assert "custom_click_id" in src
    assert "CUSTOM_UTM_FIELDS" in src
