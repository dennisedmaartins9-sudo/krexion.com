"""
v2.6.26 — TikTok Android UA — advertiser browser detection fix
================================================================

Bug report source: customer's clicks (4).csv (Jan 2026)
Sample: 106 rows / 23 TikTok-referred Android clicks

Observation:
   iOS TikTok clicks     → Browser column correctly reads "TikTok for iOS"
   Android TikTok clicks → Browser column reads <empty> (100% failure rate)

Root cause:
   A legacy native-stack TikTok Android UA only carried
   `musical_ly_<10digit_build>` as the TikTok identifier. Modern
   advertiser UA parsers (ua-parser-js, uap-core / ua-parser-cpp,
   Everflow / Voluum / RedTrack) use the regex `TikTok/([0-9.]+)`
   as the primary "TikTok" browser detection rule. Without an
   explicit `TikTok/{app_ver}` slug in the UA, they fall through
   to the generic Android rule and emit Browser="" on the report.

Current contract:
   Keep `TikTok/{app_ver}` in the browser-page WebView identity:
     - server.py::_ua_tiktok_android
     - referrer_pro.py::build_inapp_ua_suffix (tiktok/android branch)
   Coercing away from TikTok rebuilds a clean single-app browser shell.
"""
import ast
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import referrer_pro  # noqa: E402
from ua_profile_contract import APP_RELEASES_BY_PLATFORM  # noqa: E402


def _server_templates():
    server_file = Path(__file__).resolve().parents[1] / "server.py"
    tree = ast.parse(server_file.read_text(encoding="utf-8"))
    wanted = {"_ua_android_webview", "_ua_tiktok_android"}
    nodes = [
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
            "code": "US", "byte_locale": "en-US",
            "posix_locale": "en_US", "lang_tag": "en-US",
        },
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(server_file), "exec"), ns)
    return SimpleNamespace(**ns)


server = _server_templates()


# ─── 1. `_ua_tiktok_android` generator carries `TikTok/{ver}` ─────────
def test_ua_tiktok_android_carries_tiktok_slash_ver_marker():
    d = {
        "and_ver": "14", "model": "SM-S928B",
        "build": "UP1A.231005.007", "sdk": "34",
    }
    for _ in range(30):
        ua = server._ua_tiktok_android(d, "45.8.2")
        assert "; wv)" in ua and "Chrome/" in ua
        assert "Cronet/" not in ua
        # v2.6.26 explicit TikTok marker
        assert re.search(r"\bTikTok/45\.8\.2\b", ua), (
            f"Missing TikTok/{{app_ver}} marker: {ua!r}"
        )
        # Legacy `musical_ly_` marker still present (fraud-scanner shape)
        assert re.search(r"\bmusical_ly_\d+\b", ua), (
            f"Missing musical_ly_ marker: {ua!r}"
        )
        # Position: TikTok/ must appear BEFORE musical_ly_ (real captures
        # and ua-parser rule priority both require this order)
        pos_tt = ua.find("TikTok/45.8.2")
        pos_ml = ua.find("musical_ly_")
        assert 0 <= pos_tt < pos_ml, (
            f"TikTok/ must precede musical_ly_: {ua!r}"
        )
        assert "Mobile Safari/" in ua
        assert "FBAN/TikTokAndroid" not in ua


# ─── 2. `build_inapp_ua_suffix('tiktok', android_base)` carries it ────
def test_build_inapp_ua_suffix_tiktok_android_carries_tiktok_ver():
    base = "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv)"
    for _ in range(30):
        suf = referrer_pro.build_inapp_ua_suffix("tiktok", base)
        assert suf, "Empty suffix"
        assert re.search(r"^TikTok/\d+\.\d+", suf), (
            f"Suffix must start with TikTok/{{ver}}: {suf!r}"
        )
        assert "musical_ly_" in suf, f"musical_ly_ missing: {suf!r}"
        assert "BytedanceWebview/" not in suf


# ─── 3. iOS suffix remains a valid WKWebView app identity ─────────────
def test_build_inapp_ua_suffix_tiktok_ios_is_contract_valid():
    base = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    for _ in range(20):
        suf = referrer_pro.build_inapp_ua_suffix("tiktok", base)
        assert suf, "Empty suffix"
        assert "musical_ly_" in suf
        assert "AppId/1233" in suf


# ─── 4. Coerce-away strip: TikTok/{ver} removed when target != tiktok ─
def test_strip_foreign_tiktok_markers_removes_TikTok_slash_ver_too():
    ua = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "TikTok/34.5.1 musical_ly_2034050010 JsSdk/1.0 NetType/WIFI "
        "Channel/googleplay AppName/musical_ly app_version/34.5.1 "
        "ByteLocale/en_US Region/US BytedanceWebview/abc1234"
    )
    for target in ("facebook", "instagram", "snapchat", "twitter", "google", "youtube"):
        stripped = referrer_pro._strip_foreign_inapp_markers(ua, target)
        assert "TikTok/34.5.1" not in stripped, (
            f"TikTok/{{ver}} leaked into {target}-coerced UA: {stripped!r}"
        )
        assert "musical_ly_" not in stripped, (
            f"musical_ly_ leaked into {target}-coerced UA: {stripped!r}"
        )


# ─── 5. Idempotency: coerce back to tiktok preserves the new marker ───
def test_coerce_ua_for_platform_tiktok_preserves_TikTok_slash_ver():
    # A stale native identity is rebuilt as one validated page WebView.
    ua_in = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "TikTok/34.9.5 musical_ly_2034090050 JsSdk/1.0 NetType/WIFI "
        "Channel/googleplay AppName/musical_ly app_version/34.9.5 "
        "ByteLocale/en_US Region/US BytedanceWebview/abc1234 "
        "com.zhiliaoapp.musically/2034090050"
    )
    out = referrer_pro.coerce_ua_for_platform(ua_in, "tiktok")
    assert "TikTok/45.8.2" in out
    assert "musical_ly_" in out
    assert "Cronet/" not in out


# ─── 6. Non-Samsung brands still get TikTok/{ver} marker ──────────────
def test_ua_tiktok_android_non_samsung_brands_still_get_marker():
    """v2.6.26 fix must apply regardless of device brand — the bug in the
    original CSV showed Motorola / OnePlus / Xiaomi / Google Pixel /
    DOOGEE clicks all with empty Browser. All these should now get
    detected."""
    for brand_model in [
        ("Motorola", "motorola-edge-30-pro"),
        ("OnePlus",  "PJZ110"),
        ("Xiaomi",   "23049PCD8G"),
        ("Google",   "Pixel 8 Pro"),
        ("DOOGEE",   "S110"),
    ]:
        d = {
            "and_ver": "14", "model": brand_model[1],
            "build": "UP1A.231005.007", "sdk": "34",
        }
        ua = server._ua_tiktok_android(d, "45.8.2")
        assert re.search(r"\bTikTok/45\.8\.2\b", ua), (
            f"[{brand_model[0]}] Missing TikTok/ marker: {ua!r}"
        )
        assert re.search(r"\bmusical_ly_\d+\b", ua), (
            f"[{brand_model[0]}] Missing musical_ly_ marker: {ua!r}"
        )
        assert brand_model[1] in ua, (
            f"[{brand_model[0]}] Device model missing: {ua!r}"
        )
