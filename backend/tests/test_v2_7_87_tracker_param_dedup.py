"""v2.7.87 — Dedupe affiliate tracker params + single Referer header."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _qs(url: str) -> dict:
    return parse_qs(urlparse(url).query)


def test_version_at_least_2_7_87():
    from packaging.version import Version

    assert Version((ROOT / "VERSION").read_text(encoding="utf-8").strip()) >= Version("2.7.87")


def test_everflow_facebook_minimal_params():
    from referrer_pro import enrich_profile_offer_url

    out = enrich_profile_offer_url(
        "https://network.evyy.net/aff_c?offer_id=3290",
        platform="facebook",
        brand="insightsnest",
        pro_extras={"utm_source": "facebook", "utm_campaign": "insightsnest"},
    )
    q = _qs(out)
    assert "clickid" in q
    assert "click_id" not in q
    assert "cid" not in q
    assert "transaction_id" not in q
    assert "source_id" not in q
    assert "aff_sub" in q
    assert "sub1" not in q
    assert "s1" not in q
    assert "aff_sub3" in q
    assert "sub3" not in q
    assert "s3" not in q
    assert "fbclid" in q
    assert "fbc" not in q
    assert "utm_source" not in q or q.get("utm_source") != q.get("aff_sub3")


def test_android_youtube_standard_params():
    from referrer_pro import enrich_profile_offer_url

    out = enrich_profile_offer_url(
        "https://tracker.example/landing?offer=1",
        platform="youtube",
        brand="brandx",
    )
    q = _qs(out)
    assert "click_id" in q
    assert "clickid" not in q
    assert "sub1" in q
    assert "aff_sub" not in q
    assert "gclid" in q
    assert "utm_source" in q


def test_compact_respects_existing_url_keys():
    from referrer_pro import compact_tracker_params_for_url

    url = "https://network.evyy.net/aff_c?offer_id=1&transaction_id="
    out = compact_tracker_params_for_url(
        url,
        {
            "clickid": "aaa",
            "click_id": "aaa",
            "transaction_id": "aaa",
            "aff_sub": "bbb",
            "sub1": "bbb",
        },
    )
    assert "transaction_id" in out
    assert "clickid" not in out
    assert "click_id" not in out
    assert out["aff_sub"] == "bbb"


def test_route_handler_single_referer_header():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    block = src.split("make_profile_referrer_route_handler")[1].split("return _handler")[0]
    assert 'headers.pop("referer", None)' in block
    assert 'headers["Referer"] = state.referer_url' in block
    assert 'headers["referer"] = state.referer_url' not in block


def test_sticky_params_still_one_click_id():
    from browser_profile_launcher import (
        _ProfileReferrerState,
        _ensure_sticky_profile_params,
    )

    st = _ProfileReferrerState(
        enabled=True,
        platform="facebook",
        referer_url="https://www.facebook.com/share/p/1Lrvs8XS3g/",
        session_id="sess-ios-1",
        pro_extras={"click_id": "sticky999"},
    )
    p = _ensure_sticky_profile_params(st)
    from referrer_pro import compact_tracker_params_for_url

    compact = compact_tracker_params_for_url(
        "https://network.evyy.net/aff_c?offer_id=3290", p
    )
    click_keys = [k for k in compact if k in ("clickid", "click_id", "cid", "transaction_id", "source_id")]
    assert len(click_keys) == 1
    sub_keys = [k for k in compact if k in ("sub1", "s1", "aff_sub")]
    assert len(sub_keys) == 1
