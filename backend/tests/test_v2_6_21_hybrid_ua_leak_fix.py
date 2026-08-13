"""
Regression tests — v2.6.21 hybrid-UA "mixed browser leak" fix pack.

Customer bug report: RUT job with TikTok in-app preset + TikTok UA
still produced clicks that advertiser trackers labelled as MIXED
browsers (Facebook, Chrome, Safari, …) instead of only TikTok.

Root causes fixed in v2.6.21:

  BUG A — referrer_pro.coerce_ua_for_platform() short-circuited on
          idempotency BEFORE stripping foreign in-app markers. Hybrid
          UAs carrying both `musical_ly` (target) AND `FBAV`/`FB_IAB`
          (foreign) passed through unchanged → advertiser parser
          latched on the first (Facebook) bracket.

  BUG B — Android TikTok page-navigation UAs must retain a complete,
          coherent Chromium WebView shell.

  UA GENERATOR — server._ua_tiktok_android() emits a browser-page
          WebView identity; Cronet is native-network-only.

Test coverage (per review_request):
  a) BUG A — musical_ly + FBAV hybrid → tiktok target strips FB, keeps musical_ly.
  b) BUG B — musical_ly WebView → coherent WebView, keeps musical_ly.
  c) musical_ly + Instagram tokens → tiktok target strips Instagram.
  d) Regression — plain Android WebView gains TikTok page markers.
  e) Regression — external Cronet input is converted for page navigation.
  f) Regression — FB in-app UA → facebook target keeps Chrome/Safari
     (real FB Android UA has them), no musical_ly.
  g) Regression — IG hybrid UA → instagram target strips musical_ly/
     BytedanceWebview, keeps Instagram markers.
  h) UA GENERATOR — Android WebView + TikTok identity, no Cronet.
  i) UA GENERATOR — _ua_tiktok_ios output shape: musical_ly_ present,
     no trailing Safari/.
"""

import ast
import importlib
import random
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ua_profile_contract import (
    APP_RELEASES_BY_PLATFORM,
    client_hint_headers_for_ua,
    validate_header_coherence,
    validate_user_agent,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERRER_FILE = REPO_ROOT / "referrer_pro.py"
SERVER_FILE = REPO_ROOT / "server.py"


def _get_rp():
    sys.path.insert(0, str(REFERRER_FILE.parent))
    return importlib.import_module("referrer_pro")


def _get_server():
    tree = ast.parse(SERVER_FILE.read_text(encoding="utf-8"))
    wanted = {"_ua_android_webview", "_ua_tiktok_android", "_ua_tiktok_ios"}
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    ns = {
        "random": random,
        "Optional": Optional,
        "_APP_RELEASES_RUNTIME": APP_RELEASES_BY_PLATFORM,
        "_CHROME_VERSIONS": ["149.0.7827.114"],
        "_ANDROID_WEBVIEW_VERSIONS": ["151.0.7922.83"],
        "_pick_region": lambda _code: {
            "code": "US", "country": "United States",
            "byte_locale": "en-US", "posix_locale": "en_US", "lang_tag": "en-US",
        },
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SERVER_FILE), "exec"), ns)
    return SimpleNamespace(**ns)


def _assert_tiktok_android_page_ua(ua: str):
    for token in (
        "; wv)", "AppleWebKit/537.36", "Version/4.0",
        "Chrome/", "Mobile Safari/537.36", "TikTok/", "musical_ly_",
    ):
        assert token in ua, f"{token} missing: {ua}"
    assert "Cronet/" not in ua
    profile = validate_user_agent(ua, expected_app="tiktok")
    assert profile["engine"] == "android_webview"
    assert profile["runtime_compatible"] is True
    assert profile["issues"] == []
    # v2.6.88 — in-app TikTok must not emit Chromium Client Hints
    assert client_hint_headers_for_ua(ua) == {}
    assert validate_header_coherence(ua, {}) == []


# ─── version ────────────────────────────────────────────────────────
def test_version_at_or_above_2_6_21():
    v = (REPO_ROOT / "VERSION").read_text().strip()
    parts = tuple(int(p) for p in v.split("."))
    assert parts >= (2, 6, 21), f"Expected >= 2.6.21, got {v!r}"


# ─── (a) BUG A: musical_ly + FBAV hybrid coerced to tiktok ──────────
def test_bug_a_musical_ly_plus_fbav_stripped_on_tiktok_coerce():
    """Hybrid TikTok+Facebook UA → tiktok target must produce a clean
    TikTok UA with NO Facebook-specific markers left.
    
    Foreign Facebook brackets must be removed; TikTok keeps only its
    verified release markers in a browser-page WebView shell."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36 musical_ly_2024105080 "
        "[FB_IAB/FB4A;FBAV/450.0.0.34.109;]"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    # The specific input Facebook identity must not leak.
    assert "450.0.0.34.109" not in out, f"input FBAV leaked: {out}"
    assert "FB_IAB/FB4A" not in out, f"FB4A bracket leaked: {out}"
    assert "FBAN/FB4A" not in out, f"FBAN/FB4A slug leaked: {out}"
    assert "FBAN/FBIOS" not in out, f"FBAN/FBIOS slug leaked: {out}"
    assert "FBAN/TikTokAndroid" not in out
    assert "musical_ly" in out.lower(), f"musical_ly missing: {out}"
    _assert_tiktok_android_page_ua(out)


# ─── (b) BUG B: musical_ly + Chrome/Safari WebView leak ─────────────
def test_bug_b_musical_ly_webview_stays_browser_compatible():
    """TikTok page navigation remains a complete Android WebView."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 15; SM-S931B Build/AP3A.240905.015; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/146.0.7432.116 Mobile Safari/537.36 musical_ly_2024105080"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    _assert_tiktok_android_page_ua(out)


# ─── (c) musical_ly + Instagram tokens stripped ─────────────────────
def test_musical_ly_plus_instagram_tokens_stripped():
    """Hybrid TikTok+Instagram Android UA → tiktok target strips IG tokens.
    
    The IG-specific block and all Facebook-shaped markers are stripped."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-A546B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36 musical_ly_2024105080 "
        "Instagram 320.0.0.42.101 Android (34/14; 420dpi; 1080x2340; samsung; SM-A546B; a54x; s5e8835; en_US; 543010325)"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    assert "Instagram" not in out, f"Instagram token leaked: {out}"
    assert "IABMV" not in out
    assert "FBAN/TikTokAndroid" not in out
    assert "musical_ly" in out.lower(), f"musical_ly missing: {out}"


# ─── (d) Regression: plain WebView → TikTok WebView ─────────────────
def test_plain_android_webview_gains_tiktok_page_identity():
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    _assert_tiktok_android_page_ua(out)


# ─── (e) External Cronet input becomes page WebView ─────────────────
def test_external_tiktok_cronet_converts_to_page_webview():
    rp = _get_rp()
    clean = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "musical_ly_2024105080 JsSdk/1.0 NetType/WIFI Channel/googleplay "
        "AppName/musical_ly app_version/34.9.5 ByteLocale/en_US "
        "ByteFullLocale/en_US Region/US "
        "BytedanceWebview/d8a21c6 ttwebview/05080411"
    )
    out = rp.coerce_ua_for_platform(clean, "tiktok")
    assert out.lower().count("musical_ly_") == 1, f"duplicate musical_ly_: {out}"
    assert "FBAN/TikTokAndroid" not in out
    assert "BytedanceWebview" not in out
    _assert_tiktok_android_page_ua(out)


# ─── (f) Regression: FB in-app coerce keeps Chrome/Safari ───────────
def test_facebook_inapp_ua_keeps_chrome_and_safari_and_no_musical_ly():
    """Real FB Android in-app UA has Chrome + Mobile Safari + FBAN bracket.
    coerce_ua_for_platform(ua, 'facebook') must NOT strip Chrome/Safari and
    must NOT inject any musical_ly."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36 "
        "[FB_IAB/FB4A;FBAV/450.0.0.34.109;]"
    )
    out = rp.coerce_ua_for_platform(input_ua, "facebook")
    assert "Chrome/" in out, f"Chrome/ dropped for FB (should stay): {out}"
    assert "Mobile Safari/" in out, f"Mobile Safari/ dropped for FB: {out}"
    assert "[FB_IAB/FB4A" in out or "FBAV/" in out, f"FBAN/FBAV bracket lost: {out}"
    assert "musical_ly" not in out.lower(), f"musical_ly injected on facebook: {out}"
    assert "Cronet/" not in out, f"Cronet leaked into FB UA: {out}"


# ─── (g) Regression: IG hybrid coerced to instagram strips TT markers ─
def test_instagram_target_strips_tiktok_markers():
    """Hybrid TT+IG UA → instagram target must strip musical_ly and
    BytedanceWebview and keep Instagram markers."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "musical_ly_2024105080 JsSdk/1.0 NetType/WIFI Channel/googleplay "
        "AppName/musical_ly app_version/34.9.5 BytedanceWebview/d8a21c6"
    )
    out = rp.coerce_ua_for_platform(input_ua, "instagram")
    assert "musical_ly" not in out.lower(), f"musical_ly leaked: {out}"
    assert "BytedanceWebview" not in out, f"BytedanceWebview leaked: {out}"
    # Instagram appends an Instagram marker (via build_inapp_ua_suffix).
    assert "Instagram" in out, f"Instagram marker missing: {out}"


# ─── (h) UA GENERATOR: Android browser-page shape ───────────────────
def test_ua_tiktok_android_generator_is_webview_shape():
    srv = _get_server()
    for _ in range(25):
        d = {
            "brand": "Samsung", "model": "SM-S928B", "vendor": "samsung",
            "chipset": "qcom", "soc": "pineapple", "res": "1440x3120",
            "dpi": "505dpi", "and_ver": "14", "sdk": "34",
            "build": "UP1A.231005.007",
        }
        ua = srv._ua_tiktok_android(d, "45.8.2")
        assert "BytedanceWebview/" not in ua
        _assert_tiktok_android_page_ua(ua)


# ─── (i) UA GENERATOR: _ua_tiktok_ios has musical_ly, no Safari ─────
def test_ua_tiktok_ios_generator_has_musical_ly_and_no_safari():
    """server._ua_tiktok_ios must emit a UA with musical_ly_ and
    without a trailing `Safari/<ver>` token (real TikTok iOS drops
    the Safari token)."""
    srv = _get_server()
    for _ in range(15):
        d = {
            "brand": "iPhone", "model": "iPhone15,2", "name": "iPhone 14 Pro",
            "ios": "18_6", "res": "1179x2556", "scale": "3.00",
        }
        ua = srv._ua_tiktok_ios(d, "44.7.0")
        assert "musical_ly_" in ua, f"musical_ly_ missing: {ua}"
        # No trailing Safari/<ver> token — the real TikTok iOS UA
        # ends with WKWebView / BytedanceWebview / PIA, not Safari/.
        assert "Safari/" not in ua, f"Safari/ leaked in iOS generator: {ua}"
        profile = validate_user_agent(ua, expected_app="tiktok")
        assert profile["profile_type"] == "ios_wkwebview"
        assert profile["issues"] == []


# ─── (j) End-to-end: generator output survives coerce unchanged ─────
def test_generator_output_is_idempotent_through_coerce():
    """Composition: generator → coerce(tiktok) must be a no-op.
    Confirms the two units are aligned (v2.6.21 goal)."""
    srv = _get_server()
    rp = _get_rp()
    d = {
        "brand": "Samsung", "model": "SM-S928B", "vendor": "samsung",
        "chipset": "qcom", "soc": "pineapple", "res": "1440x3120",
        "dpi": "505dpi", "and_ver": "14", "sdk": "34",
        "build": "UP1A.231005.007",
    }
    ua = srv._ua_tiktok_android(d, "45.8.2")
    coerced = rp.coerce_ua_for_platform(ua, "tiktok")
    # Downstream coerce must not corrupt or double-append.
    assert coerced.count("musical_ly_") == 1, f"musical_ly_ duplicated: {coerced}"
    _assert_tiktok_android_page_ua(coerced)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
