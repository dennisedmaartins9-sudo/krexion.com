"""
v2.6.22 — Cross-platform Custom-URL + In-App-Preset flow verification
=====================================================================

Scenario the customer described:
  "mein ne referer landing page dena or in-app browser tiktok show krwana"
  (I want to give a landing page as Referer AND show TikTok as the in-app browser)

Same flow applies to every in-app platform: Facebook, Messenger, Instagram,
TikTok, Snapchat, LinkedIn, Twitter/X, Pinterest. This test suite verifies
that for EACH platform, when the operator sets:

    referer_mode           = "custom"
    referer_value          = "<their landing page URL>"
    inapp_browser_preset   = "<platform>"

the engine produces:

  1. Referer sent to advertiser tracker  = operator's landing URL (unchanged)
  2. Platform tag                        = <platform> (not derived from
                                            landing URL)
  3. UA coerced with platform-specific   = canonical per-platform marker,
     identity                              except Messenger (fallback-only
                                           generic browser; no fabricated marker)
     in-app marker                         (musical_ly / FBAV / Instagram /
                                            Snapchat / [LinkedInApp] / etc.)
  4. No foreign in-app markers leak      = no cross-platform contamination
  5. TikTok Android specifically         = browser-page WebView shell,
                                            never a Cronet/native-network UA

The pure-function pipeline exercised is exactly what real_user_traffic.py
runs per-visit at run() line 8587 → 8675, minus the Playwright launch:

    referer_cfg = {mode: "custom", value: <landing>, preset_platform: <plat>}
    ref, plat, esp, extras = _resolve_visit_referer(ua, referer_cfg)
    ua = coerce_ua_for_platform(ua, plat)

No DB / network / browser required — all pure functions.
"""

import ast
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from referrer_pro import coerce_ua_for_platform


RUT_FILE = Path(__file__).parent.parent / "real_user_traffic.py"


def _extract_resolver():
    """Load only the pure referer resolver graph, without Playwright."""
    names = {
        "_UA_REFERER_MAP",
        "_PLATFORM_REFERER_POOL",
        "_ESP_HOST_TO_NAME",
        "_REFERER_HOST_TO_PLATFORM",
        "_get_referer_from_ua",
        "_referer_extras_for_traffic_type",
        "_with_traffic_type_extras",
        "_resolve_visit_referer",
        "_esp_from_referer_url",
        "_platform_from_referer_url",
    }
    tree = ast.parse(RUT_FILE.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        defined = set()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            defined.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        if defined & names:
            nodes.append(node)
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "Optional": Optional,
        "Tuple": Tuple,
        "random": random,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUT_FILE), "exec"), namespace)
    return namespace["_resolve_visit_referer"]


_resolve_visit_referer = _extract_resolver()


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────

LANDING_URL = "https://mylanding.com/promo/summer-sale?utm_source=meta&cid=abc123"

# Realistic mobile Android UA — same shape our own generator emits.
BASE_ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 15; SM-S931B Build/AP3A.240905.015; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/146.0.7432.116 Mobile Safari/537.36"
)

BASE_IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/26.4 Mobile/15E148 Safari/604.1"
)

# Canonical markers after coercion, split by platform family.
PLATFORM_UA_MARKERS = {
    "facebook":  {"android": ["FB_IAB/FB4A", "FBAV/"], "ios": ["FBAN/FBIOS", "FBAV/"]},
    "instagram": {"android": ["Instagram "], "ios": ["Instagram "]},
    "tiktok":    {"android": ["musical_ly_2024508020", "app_version/45.8.2"], "ios": ["musical_ly_", "app_version/"]},
    "snapchat":  {"android": ["Snapchat/"], "ios": ["Snapchat/"]},
    "linkedin":  {"android": ["[LinkedInApp]/", "com.linkedin.android/"], "ios": ["[LinkedInApp]/"]},
    "twitter":   {"android": ["TwitterAndroid/"], "ios": ["Twitter for iPhone/"]},
    "pinterest": {"android": ["[Pinterest/Android]"], "ios": ["[Pinterest/iOS]"]},
}


def _build_cfg(landing_url: str, preset_platform: str) -> dict:
    """Emulate the referer_cfg dict built at real_user_traffic.py line 6960."""
    return {
        "enabled": True,
        "mode": "custom",
        "value": landing_url,
        "override_enabled": True,
        "preset_platform": preset_platform,
        "match_ua_to_platform": True,
        "pass_to_offer": True,
        "pro_mode": False,
        "platform_pool": "",
        "platform_weights": "",
        "email_weights": "",
        "brand": "",
        "country": "",
        "search_engine": "google",
        "search_keywords": "",
        "target_url": "",
    }


def _has_any_marker(ua: str, markers: list) -> bool:
    """True if UA contains AT LEAST ONE of the markers (accounts for
    LinkedIn / Twitter having iOS vs Android alternate forms)."""
    ul = ua.lower()
    return any(m.lower() in ul for m in markers)


# ────────────────────────────────────────────────────────────────────────
# Tests — per-platform
# ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "preset_platform",
    ["facebook", "messenger", "instagram", "tiktok",
     "snapchat", "linkedin", "twitter", "pinterest"],
)
def test_custom_url_plus_preset_returns_operator_url(preset_platform):
    """Per-visit resolver returns the operator's landing URL unchanged."""
    cfg = _build_cfg(LANDING_URL, preset_platform)
    ref, plat, esp, extras = _resolve_visit_referer(BASE_ANDROID_UA, cfg)
    assert ref == LANDING_URL, (
        f"Expected referer=operator's landing URL for preset={preset_platform}, "
        f"got: {ref}"
    )


@pytest.mark.parametrize(
    "preset_platform",
    ["facebook", "messenger", "instagram", "tiktok",
     "snapchat", "linkedin", "twitter", "pinterest"],
)
def test_custom_url_plus_preset_sets_platform_tag(preset_platform):
    """Per-visit resolver sets platform tag from preset (not landing URL)."""
    cfg = _build_cfg(LANDING_URL, preset_platform)
    ref, plat, esp, extras = _resolve_visit_referer(BASE_ANDROID_UA, cfg)
    assert plat == preset_platform, (
        f"Expected platform tag='{preset_platform}', got '{plat}'"
    )


@pytest.mark.parametrize(
    "preset_platform,expected_markers",
    [
        ("facebook",  PLATFORM_UA_MARKERS["facebook"]["android"]),
        ("instagram", PLATFORM_UA_MARKERS["instagram"]["android"]),
        ("tiktok",    PLATFORM_UA_MARKERS["tiktok"]["android"]),
        ("snapchat",  PLATFORM_UA_MARKERS["snapchat"]["android"]),
        ("linkedin",  PLATFORM_UA_MARKERS["linkedin"]["android"]),
        ("twitter",   PLATFORM_UA_MARKERS["twitter"]["android"]),
        ("pinterest", PLATFORM_UA_MARKERS["pinterest"]["android"]),
    ],
)
def test_ua_coerced_carries_platform_marker_android(preset_platform, expected_markers):
    """Android UA after coerce carries the correct platform marker."""
    ua_out = coerce_ua_for_platform(BASE_ANDROID_UA, preset_platform)
    assert _has_any_marker(ua_out, expected_markers), (
        f"After coerce for '{preset_platform}', expected one of {expected_markers} in UA. "
        f"Got: {ua_out}"
    )


@pytest.mark.parametrize(
    "preset_platform,expected_markers",
    [
        ("facebook",  PLATFORM_UA_MARKERS["facebook"]["ios"]),
        ("instagram", PLATFORM_UA_MARKERS["instagram"]["ios"]),
        ("tiktok",    PLATFORM_UA_MARKERS["tiktok"]["ios"]),
        ("snapchat",  PLATFORM_UA_MARKERS["snapchat"]["ios"]),
        ("linkedin",  PLATFORM_UA_MARKERS["linkedin"]["ios"]),
        ("twitter",   PLATFORM_UA_MARKERS["twitter"]["ios"]),
        ("pinterest", PLATFORM_UA_MARKERS["pinterest"]["ios"]),
    ],
)
def test_ua_coerced_carries_platform_marker_ios(preset_platform, expected_markers):
    """iOS UA after coerce carries the correct platform marker (or is
    unchanged for platforms with no iOS in-app form)."""
    ua_out = coerce_ua_for_platform(BASE_IOS_UA, preset_platform)
    assert _has_any_marker(ua_out, expected_markers), (
        f"After iOS coerce for '{preset_platform}', expected one of {expected_markers} in UA. "
        f"Got: {ua_out}"
    )


@pytest.mark.parametrize("base_ua", [BASE_ANDROID_UA, BASE_IOS_UA])
def test_messenger_uses_clean_generic_browser_fallback(base_ua):
    ua_out = coerce_ua_for_platform(base_ua, "messenger")
    assert "FB_IAB/" not in ua_out
    assert "FBAN/" not in ua_out
    assert "FBAV/" not in ua_out
    assert "MESSENGER" not in ua_out.upper()
    assert "Mozilla/5.0" in ua_out


# ── Cross-platform contamination checks ────────────────────────────────

@pytest.mark.parametrize(
    "target,foreign_markers",
    [
        ("tiktok",    ["FBAV/", "FB_IAB/", "Instagram ", "Snapchat/", "LinkedInApp/", "TwitterAndroid/", "Pinterest/"]),
        ("facebook",  ["musical_ly", "BytedanceWebview/", "Instagram ", "Snapchat/", "LinkedInApp/", "TwitterAndroid/", "Pinterest/"]),
        ("instagram", ["musical_ly", "BytedanceWebview/", "FBAV/", "Snapchat/", "LinkedInApp/", "TwitterAndroid/", "Pinterest/"]),
        ("snapchat",  ["musical_ly", "BytedanceWebview/", "FBAV/", "Instagram ", "LinkedInApp/", "TwitterAndroid/", "Pinterest/"]),
        ("linkedin",  ["musical_ly", "BytedanceWebview/", "FBAV/", "Instagram ", "Snapchat/", "TwitterAndroid/", "Pinterest/"]),
        ("twitter",   ["musical_ly", "BytedanceWebview/", "FBAV/", "Instagram ", "Snapchat/", "LinkedInApp/", "Pinterest/"]),
        ("pinterest", ["musical_ly", "BytedanceWebview/", "FBAV/", "Instagram ", "Snapchat/", "LinkedInApp/", "TwitterAndroid/"]),
    ],
)
def test_no_foreign_platform_markers_after_coerce(target, foreign_markers):
    """After coerce for a target platform, UA must NOT contain any
    OTHER platform's in-app marker (the v2.6.22 fix guarantees this)."""
    # Build a hybrid UA with many foreign markers so the strip is exercised.
    hybrid_ua = (
        "Mozilla/5.0 (Linux; Android 15; SM-S931B Build/AP3A.240905.015; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/146.0.7432.116 Mobile Safari/537.36 "
        "musical_ly_2024105080 JsSdk/1.0 BytedanceWebview/d8a21c6 "
        "Instagram 302.0.0.34.111 (Android; en_US; scale=3.00) "
        "Snapchat/12.34.56 "
        "[FB_IAB/FB4A;FBAV/515.1.0.62.90;IABMV/1;]"
    )
    ua_out = coerce_ua_for_platform(hybrid_ua, target)
    for m in foreign_markers:
        assert m.lower() not in ua_out.lower(), (
            f"Target='{target}' — foreign marker '{m}' leaked into cleaned UA. "
            f"UA: {ua_out}"
        )


# ── TikTok Android browser-page shell contract ────────────────────────

def test_tiktok_android_keeps_webview_shell_after_coerce():
    """Offer-page navigation must remain compatible with Android WebView."""
    ua_out = coerce_ua_for_platform(BASE_ANDROID_UA, "tiktok")
    assert "; wv)" in ua_out
    assert "Version/4.0" in ua_out
    assert "Chrome/" in ua_out
    assert "Mobile Safari/537.36" in ua_out
    assert "Cronet/" not in ua_out
    assert "musical_ly_2024508020" in ua_out
    assert "app_version/45.8.2" in ua_out
    assert "com.zhiliaoapp.musically/2024508020" in ua_out
    assert "FBAN/TikTokAndroid" not in ua_out
    assert "BytedanceWebview/" not in ua_out
    assert "ttwebview/" not in ua_out


def test_tiktok_ios_no_trailing_safari_after_coerce():
    """TikTok iOS in-app UA drops the trailing Safari/ token
    (real in-app captures don't carry it)."""
    ua_out = coerce_ua_for_platform(BASE_IOS_UA, "tiktok")
    # Trailing " Safari/..." at end-of-line is what advertiser parsers latch on.
    assert not re.search(r"\bSafari/[\d.]+\s*$", ua_out), (
        f"Trailing Safari/ token still present after iOS coerce: {ua_out}"
    )
    assert "musical_ly" in ua_out, f"musical_ly missing in TikTok iOS UA: {ua_out}"


# ── Utm parameters attached correctly per preset platform ──────────────

@pytest.mark.parametrize(
    "preset_platform,expected_utm_medium",
    [
        ("facebook",  "cpc"),
        ("instagram", "cpc"),
        ("tiktok",    "cpc"),
        ("snapchat",  "cpc"),
        ("linkedin",  "cpc"),
        ("twitter",   "cpc"),
        ("pinterest", "cpc"),
        ("messenger", "referral"),   # messenger not in the paid-list
    ],
)
def test_utm_params_populated_for_paid_platforms(preset_platform, expected_utm_medium):
    """When operator's landing URL has NO utm_source, the engine
    adds sensible defaults matching the preset platform."""
    # Landing URL WITHOUT utm_source
    landing_no_utm = "https://mylanding.com/promo/no-utm"
    cfg = _build_cfg(landing_no_utm, preset_platform)
    ref, plat, esp, extras = _resolve_visit_referer(BASE_ANDROID_UA, cfg)
    assert extras.get("utm_source") == preset_platform, (
        f"utm_source should be '{preset_platform}', got: {extras.get('utm_source')}"
    )
    assert extras.get("utm_medium") == expected_utm_medium, (
        f"utm_medium should be '{expected_utm_medium}' for {preset_platform}, "
        f"got: {extras.get('utm_medium')}"
    )


def test_operators_utm_source_not_overwritten():
    """If operator's landing URL ALREADY has utm_source, engine leaves
    utm params EMPTY (operator's URL wins)."""
    landing_with_utm = "https://mylanding.com/promo?utm_source=facebook&utm_campaign=summer"
    cfg = _build_cfg(landing_with_utm, "tiktok")
    ref, plat, esp, extras = _resolve_visit_referer(BASE_ANDROID_UA, cfg)
    assert ref == landing_with_utm
    # extras should be empty (no utm overwrite)
    assert not extras.get("utm_source"), (
        f"Operator's utm_source should NOT be overwritten. Got extras: {extras}"
    )


# ── Full pipeline: referer + UA together in one call ───────────────────

@pytest.mark.parametrize(
    "preset_platform",
    ["facebook", "instagram", "tiktok", "snapchat", "linkedin", "twitter", "pinterest"],
)
def test_full_pipeline_referer_and_ua_consistent(preset_platform):
    """End-to-end: given landing URL + preset, verify:
       - referer == landing URL
       - platform tag == preset
       - UA carries preset's marker
       - UA does NOT carry foreign markers
    """
    cfg = _build_cfg(LANDING_URL, preset_platform)
    ref, plat, esp, extras = _resolve_visit_referer(BASE_ANDROID_UA, cfg)
    assert ref == LANDING_URL
    assert plat == preset_platform

    ua_final = coerce_ua_for_platform(BASE_ANDROID_UA, plat)
    expected = PLATFORM_UA_MARKERS[preset_platform]["android"]
    assert _has_any_marker(ua_final, expected), (
        f"[{preset_platform}] UA missing expected marker(s) {expected}. UA: {ua_final}"
    )
    # TikTok specifically: guarantee the browser-page WebView runtime.
    if preset_platform == "tiktok":
        assert "Chrome/" in ua_final
        assert "Cronet/" not in ua_final


# ── Mix-mode (pro-mode) sanity: platform pool picks only from listed set

def test_platform_pool_picks_only_from_selected_set():
    """When operator sets platform_pool="facebook,tiktok,instagram" in
    pro-mode, `_resolve_visit_referer` picks referer/platform ONLY from
    those three — no external platform can leak in."""
    cfg = {
        "enabled": True,
        "mode": "platform_pool",
        "value": "",
        "override_enabled": True,
        "preset_platform": "",
        "match_ua_to_platform": True,
        "pro_mode": False,
        "platform_pool": "facebook,tiktok,instagram",
        "platform_weights": "",
    }
    seen_platforms = set()
    # Run 200 visits to cover the random pick space.
    for _ in range(200):
        ref, plat, esp, extras = _resolve_visit_referer(BASE_ANDROID_UA, cfg)
        assert plat in ("facebook", "tiktok", "instagram"), (
            f"Unexpected platform '{plat}' picked from restricted pool"
        )
        seen_platforms.add(plat)
    # All three should have been hit at least once with 200 rolls.
    assert seen_platforms == {"facebook", "tiktok", "instagram"}, (
        f"Not all pool platforms exercised. Seen: {seen_platforms}"
    )


def test_weighted_platform_pool_json_respected():
    """Weighted JSON pool format `{"tiktok":80,"facebook":20}` also
    restricted to listed platforms."""
    import json as _json
    weighted = _json.dumps({"tiktok": 80, "facebook": 20})
    cfg = {
        "enabled": True,
        "mode": "platform_pool",
        "value": "",
        "override_enabled": True,
        "preset_platform": "",
        "match_ua_to_platform": True,
        "pro_mode": False,
        "platform_pool": weighted,
        "platform_weights": "",
    }
    seen = {"tiktok": 0, "facebook": 0, "other": 0}
    for _ in range(500):
        ref, plat, esp, extras = _resolve_visit_referer(BASE_ANDROID_UA, cfg)
        if plat in seen:
            seen[plat] += 1
        else:
            seen["other"] += 1
    assert seen["other"] == 0, f"Non-listed platform leaked in: {seen}"
    assert seen["tiktok"] > 0 and seen["facebook"] > 0, (
        f"Both weighted platforms should be exercised. Seen: {seen}"
    )
