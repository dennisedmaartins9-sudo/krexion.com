"""v2.6.88 — Organic traffic must not emit paid-ad URL params / UTMs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_detect_is_paid_organic_wins_over_video_ad():
    from referrer_pro import detect_is_paid

    assert detect_is_paid("organic", "video_ad", "tiktok") is False


def test_resolve_pro_organic_utm_not_paid_social():
    from referrer_pro import resolve_pro_visit

    and_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
    )
    r = resolve_pro_visit(
        ua=and_ua,
        platform_pool_value=json.dumps({"tiktok": 100}),
        brand="brand",
        target_url="https://offer.example/x",
        traffic_type="organic",
        campaign_type="video_ad",
        social_wrapper_enabled=True,
        inapp_deep_path_enabled=True,
    )
    assert r.get("is_paid") is False
    assert r.get("traffic_type") == "organic"
    assert (r.get("utm_medium") or "").lower() not in {
        "paid_social",
        "cpc",
        "ppc",
        "paid_search",
        "retargeting",
    }


def test_generate_platform_params_organic_strips_ttclid():
    from referrer_pro import apply_organic_platform_param_override

    paid = {
        "ttclid": "abc",
        "ttp": "xyz",
        "utm_source": "tiktok",
        "utm_medium": "paid_social",
        "utm_campaign": "tt_brand_x",
    }
    org = apply_organic_platform_param_override(dict(paid), "tiktok")
    assert "ttclid" not in org
    assert "ttp" not in org
    assert org.get("utm_source") == "tiktok"
    assert (org.get("utm_medium") or "").lower() in {"social", "organic", "referral"}


def test_android_tiktok_coerce_has_inapp_marker():
    from referrer_pro import coerce_ua_for_platform, is_inapp_browser_ua

    and_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
    )
    coerced = coerce_ua_for_platform(and_ua, "tiktok")
    assert coerced
    assert "TikTok/" in coerced or "musical_ly" in coerced
    assert is_inapp_browser_ua(coerced) == "tiktok"


def test_android_tiktok_emits_no_sec_ch_ua_so_everflow_sees_tiktok():
    """Mirror original-ad Everflow label: TikTok for Android (not Chrome).

    iOS already had empty Client Hints (wkwebview). Android previously
    emitted Android WebView/Chromium hints → Everflow Browser=Chrome.
    """
    import re
    from referrer_pro import ensure_inapp_platform_ua
    from ua_profile_contract import client_hint_headers_for_ua

    and_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
    )
    coerced = ensure_inapp_platform_ua(and_ua, "tiktok")
    assert client_hint_headers_for_ua(coerced) == {}
    m = re.search(r"TikTok/([\d.]+)", coerced or "")
    assert m, f"missing TikTok/ marker: {coerced!r}"
    major = m.group(1).split(".", 1)[0]
    # Everflow-style label from UA when Client Hints are absent
    assert major.isdigit()
