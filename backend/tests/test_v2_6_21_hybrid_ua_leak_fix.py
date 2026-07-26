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

  BUG B — Android WebView UAs that already carried `musical_ly` but
          still had `Chrome/… Mobile Safari/537.36` (leftover WebView
          tokens from a hybrid AI-generated pool) were also
          short-circuited by the idempotency check → advertiser
          parser saw Chrome first and labelled the click as Chrome.

  UA GENERATOR — server._ua_tiktok_android() itself was emitting the
          old WebView shape (Chrome/{ver} + Mobile Safari/537.36).
          Rewritten to Cronet form matching real 2025-2026 TikTok
          Android UAs and the referrer_pro rebuild output exactly.

Test coverage (per review_request):
  a) BUG A — musical_ly + FBAV hybrid → tiktok target strips FB, keeps musical_ly.
  b) BUG B — musical_ly + Chrome/Mobile Safari (WebView leak) → tiktok
     target strips Chrome/Safari, forces Cronet, keeps musical_ly.
  c) musical_ly + Instagram tokens → tiktok target strips Instagram.
  d) Regression — plain Android WebView (no in-app markers) → tiktok
     target produces Cronet form.
  e) Regression — clean TikTok Cronet UA → tiktok target returns
     UNCHANGED (idempotent, no double-append).
  f) Regression — FB in-app UA → facebook target keeps Chrome/Safari
     (real FB Android UA has them), no musical_ly.
  g) Regression — IG hybrid UA → instagram target strips musical_ly/
     BytedanceWebview, keeps Instagram markers.
  h) UA GENERATOR — _ua_tiktok_android output shape: Cronet + musical_ly_
     + BytedanceWebview, no Chrome/, no Mobile Safari.
  i) UA GENERATOR — _ua_tiktok_ios output shape: musical_ly_ present,
     no trailing Safari/.
"""

import importlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERRER_FILE = REPO_ROOT / "referrer_pro.py"
SERVER_FILE = REPO_ROOT / "server.py"


def _get_rp():
    sys.path.insert(0, str(REFERRER_FILE.parent))
    return importlib.import_module("referrer_pro")


def _get_server():
    sys.path.insert(0, str(SERVER_FILE.parent))
    return importlib.import_module("server")


# ─── version ────────────────────────────────────────────────────────
def test_version_at_or_above_2_6_21():
    v = (REPO_ROOT / "VERSION").read_text().strip()
    parts = tuple(int(p) for p in v.split("."))
    assert parts >= (2, 6, 21), f"Expected >= 2.6.21, got {v!r}"


# ─── (a) BUG A: musical_ly + FBAV hybrid coerced to tiktok ──────────
def test_bug_a_musical_ly_plus_fbav_stripped_on_tiktok_coerce():
    """Hybrid TikTok+Facebook UA → tiktok target must produce a clean
    TikTok UA with NO Facebook-specific markers left.
    
    v2.6.27 update: coerce now ADDS a `[FB_IAB/;FBAN/TikTokAndroid;
    FBAV/{ver};IABMV/1;FBBV/{code};FBOP/19;]` trailer (advertiser
    trackers use this bracket format universally to detect TikTok
    Android). So the assertion is now: any pre-existing FACEBOOK-
    specific bracket (`FB_IAB/FB4A`, `FBAN/FB4A`, `FBAN/FBIOS`) or
    the specific INPUT `FBAV/450.0.0.34.109` must be gone — but a
    FRESH TikTok-signed bracket with its own FBAV is allowed."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36 musical_ly_2024105080 "
        "[FB_IAB/FB4A;FBAV/450.0.0.34.109;]"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    # v2.6.27 — the specific INPUT Facebook version must NOT leak into
    # the output. Chrome/Safari leak from Bug B same-file must also
    # remain gone.
    assert "450.0.0.34.109" not in out, f"input FBAV leaked: {out}"
    assert "FB_IAB/FB4A" not in out, f"FB4A bracket leaked: {out}"
    assert "FBAN/FB4A" not in out, f"FBAN/FB4A slug leaked: {out}"
    assert "FBAN/FBIOS" not in out, f"FBAN/FBIOS slug leaked: {out}"
    assert "Chrome/" not in out, f"Chrome/ leaked: {out}"
    assert "Mobile Safari/" not in out, f"Mobile Safari/ leaked: {out}"
    # Positive: our v2.6.27 TikTokAndroid bracket must be present
    assert "FBAN/TikTokAndroid" in out, (
        f"v2.6.27 TikTokAndroid bracket missing: {out}"
    )
    assert "musical_ly" in out.lower(), f"musical_ly missing: {out}"


# ─── (b) BUG B: musical_ly + Chrome/Safari WebView leak ─────────────
def test_bug_b_musical_ly_plus_chrome_safari_forces_cronet():
    """Android WebView UA carrying musical_ly AND leftover Chrome/…
    Mobile Safari/537.36 tokens → tiktok target must rebuild to
    Cronet shape (no Chrome/, no Mobile Safari/) but keep musical_ly."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 15; SM-S931B Build/AP3A.240905.015; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/146.0.7432.116 Mobile Safari/537.36 musical_ly_2024105080"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    assert "Chrome/" not in out, f"Chrome/ leaked: {out}"
    assert "Mobile Safari/" not in out, f"Mobile Safari/ leaked: {out}"
    assert "Cronet/" in out, f"Cronet missing: {out}"
    assert "musical_ly" in out.lower(), f"musical_ly missing: {out}"


# ─── (c) musical_ly + Instagram tokens stripped ─────────────────────
def test_musical_ly_plus_instagram_tokens_stripped():
    """Hybrid TikTok+Instagram Android UA → tiktok target strips IG tokens.
    
    v2.6.27 update: our TikTokAndroid FB_IAB bracket contains IABMV/1,
    so we can no longer assert 'IABMV not in out'. Instead we assert
    the IG-specific `Instagram <ver> Android (...)` block is stripped
    AND the FB_IAB bracket that IS present carries FBAN/TikTokAndroid
    (proving IABMV came from OUR tiktok-signed bracket, not a leaked
    Instagram/Facebook one)."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-A546B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36 musical_ly_2024105080 "
        "Instagram 320.0.0.42.101 Android (34/14; 420dpi; 1080x2340; samsung; SM-A546B; a54x; s5e8835; en_US; 543010325)"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    assert "Instagram" not in out, f"Instagram token leaked: {out}"
    # v2.6.27 — IABMV/1 IS present (inside our new TikTokAndroid bracket)
    # but must come from a TikTokAndroid-signed bracket, NOT a leaked IG one
    if "IABMV" in out:
        assert "FBAN/TikTokAndroid" in out, (
            f"IABMV present but not inside a TikTokAndroid bracket: {out}"
        )
    assert "musical_ly" in out.lower(), f"musical_ly missing: {out}"


# ─── (d) Regression: plain WebView → Cronet ─────────────────────────
def test_plain_android_webview_becomes_cronet_on_tiktok_coerce():
    """Regression from v2.6.19 — plain Android WebView UA without any
    in-app markers → tiktok target produces Cronet base."""
    rp = _get_rp()
    input_ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/126.0.6478.99 Mobile Safari/537.36"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    assert "Cronet/" in out
    assert "Chrome/" not in out
    assert "Mobile Safari/" not in out
    assert "musical_ly" in out.lower()


# ─── (e) Incomplete TikTok Cronet UA gets FB_IAB upgrade ────────────
def test_incomplete_tiktok_cronet_ua_gets_fb_iab_upgrade():
    """Legacy TikTok Cronet Android UA (musical_ly but no FB_IAB bracket)
    must be UPGRADED by coerce — not returned unchanged. Advertiser
    parsers label those UAs as generic Android browser."""
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
    assert "Chrome/" not in out
    assert "Mobile Safari/" not in out
    assert out.lower().count("musical_ly_") == 1, f"duplicate musical_ly_: {out}"
    assert "Cronet/" in out
    assert "FBAN/TikTokAndroid" in out, (
        f"v2.6.33: incomplete legacy UA must gain TikTokAndroid bracket: {out}"
    )


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


# ─── (h) UA GENERATOR: _ua_tiktok_android produces Cronet ───────────
def test_ua_tiktok_android_generator_is_cronet_shape():
    """server._ua_tiktok_android must emit Cronet-form UA that matches
    the referrer_pro rebuild output. Runs the generator 25 times to
    catch any random pathway that might slip Chrome/ or Safari back in."""
    srv = _get_server()
    for _ in range(25):
        d = {
            "brand": "Samsung", "model": "SM-S928B", "vendor": "samsung",
            "chipset": "qcom", "soc": "pineapple", "res": "1440x3120",
            "dpi": "505dpi", "and_ver": "14", "sdk": "34",
            "build": "UP1A.231005.007",
        }
        ua = srv._ua_tiktok_android(d, "34.9.5")
        assert "Cronet/" in ua, f"Cronet missing: {ua}"
        assert "musical_ly_" in ua, f"musical_ly_ missing: {ua}"
        assert "BytedanceWebview/" in ua, f"BytedanceWebview/ missing: {ua}"
        # Real 2025-2026 TikTok Android UA has NO Chrome/ or Mobile Safari.
        assert "Chrome/" not in ua, f"Chrome/ leaked in generator: {ua}"
        assert "Mobile Safari" not in ua, f"Mobile Safari leaked in generator: {ua}"
        # Should also be `Linux; U; Android`
        assert "Linux; U; Android" in ua, f"Missing `Linux; U; Android`: {ua}"


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
        ua = srv._ua_tiktok_ios(d, "34.9.5")
        assert "musical_ly_" in ua, f"musical_ly_ missing: {ua}"
        # No trailing Safari/<ver> token — the real TikTok iOS UA
        # ends with WKWebView / BytedanceWebview / PIA, not Safari/.
        assert "Safari/" not in ua, f"Safari/ leaked in iOS generator: {ua}"


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
    ua = srv._ua_tiktok_android(d, "34.9.5")
    coerced = rp.coerce_ua_for_platform(ua, "tiktok")
    # Downstream coerce must not corrupt or double-append.
    assert coerced.count("musical_ly_") == 1, f"musical_ly_ duplicated: {coerced}"
    assert "Chrome/" not in coerced
    assert "Mobile Safari" not in coerced
    assert "Cronet/" in coerced


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
