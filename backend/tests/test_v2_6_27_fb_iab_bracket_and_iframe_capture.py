"""
TikTok Android and Facebook marker regression coverage
=======================================================

Bug follow-up from customer's second CSV report (screenshots of Everflow
click details in Session 4):

  1. TikTok Android page identities are standard Chromium WebViews with
     verified TikTok release markers, never Facebook-shaped brackets.

  2. Facebook uses the exact audited platform release and matching build.

The visual-recorder iframe regression coverage below is intentionally retained.
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
from ua_profile_contract import APP_RELEASES_BY_PLATFORM, validate_user_agent  # noqa: E402


def _server_templates():
    server_file = Path(__file__).resolve().parents[1] / "server.py"
    tree = ast.parse(server_file.read_text(encoding="utf-8"))
    wanted = {
        "_ua_android_webview", "_ua_tiktok_android",
        "_ua_facebook_android", "_ua_facebook_ios",
    }
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


# ─── 1. TikTok Android uses a browser-page WebView without FB bracket ─
def test_ua_tiktok_android_has_no_facebook_shaped_bracket():
    d = {"and_ver": "14", "model": "SM-S928B",
         "build": "UP1A.231005.007", "sdk": "34"}
    for _ in range(30):
        ua = server._ua_tiktok_android(d, "45.8.2")
        assert "FBAN/TikTokAndroid" not in ua
        assert "[FB_IAB/" not in ua
        assert re.search(r"\bTikTok/45\.8\.2\b", ua)
        assert re.search(r"\bmusical_ly_\d+\b", ua)
        assert "com.zhiliaoapp.musically/" in ua
        assert "; wv)" in ua and "Chrome/" in ua and "Mobile Safari/" in ua


def test_build_inapp_ua_suffix_tiktok_android_has_no_fb_bracket():
    base = "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv)"
    for _ in range(20):
        suf = referrer_pro.build_inapp_ua_suffix("tiktok", base)
        assert "FBAN/TikTokAndroid" not in suf
        assert "[FB_IAB/" not in suf
        assert suf.startswith("TikTok/")


# ─── 2. Facebook FBAV uses the audited full release ───────────────────
def test_ua_facebook_android_uses_release_and_matching_build():
    d = {"and_ver": "14", "model": "SM-S928B",
         "build": "UP1A.231005.007", "sdk": "34"}
    ua = server._ua_facebook_android(d, "556.0.0.59.68", "149.0.7827.114")
    assert "FBAV/556.0.0.59.68;" in ua
    assert "FBBV/681204512;" in ua
    assert "FBAN/FB4A;" not in ua
    assert validate_user_agent(ua, expected_app="facebook")["issues"] == []


def test_ua_facebook_ios_uses_audited_release():
    d = {"ios": "18_3", "brand": "iPhone", "model": "iPhone15,3",
         "build": "22D63", "sdk": "18", "scale": "3.0"}
    ua = server._ua_facebook_ios(d, "557.0")
    assert "FBAV/557.0;" in ua
    assert "FBAN/FBIOS;" in ua
    assert validate_user_agent(ua, expected_app="facebook")["issues"] == []


# ─── 3. Coercion removes all fabricated/foreign bracket markers ──────
def test_coerce_to_tiktok_removes_tiktokandroid_bracket():
    ua = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "TikTok/44.7.0 musical_ly_4470000000 JsSdk/1.0 NetType/WIFI "
        "Channel/googleplay AppName/musical_ly app_version/44.7.0 "
        "ByteLocale/en_US Region/US BytedanceWebview/abc1234 "
        "ttwebview/05080411 com.zhiliaoapp.musically/4470000000 "
        "[FB_IAB/;FBAN/TikTokAndroid;FBAV/44.7.0;IABMV/1;FBBV/4470000000;FBOP/19;]"
    )
    back = referrer_pro.coerce_ua_for_platform(ua, "tiktok")
    assert "FBAN/TikTokAndroid" not in back
    assert "[FB_IAB/" not in back
    assert "TikTok/45.8.2" in back
    assert "musical_ly_" in back


def test_coerce_away_from_tiktok_strips_the_new_bracket():
    """Cross-platform coerce (TT → FB / IG / etc.) must strip both the
    v2.6.26 `TikTok/{ver}` slug AND the v2.6.27 FB_IAB TikTokAndroid
    trailer."""
    ua = (
        "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
        "Build/UP1A.231005.007; Cronet/58.0.2991.0) "
        "TikTok/44.7.0 musical_ly_4470000000 JsSdk/1.0 NetType/WIFI "
        "Channel/googleplay AppName/musical_ly app_version/44.7.0 "
        "ByteLocale/en_US Region/US BytedanceWebview/abc1234 "
        "ttwebview/05080411 com.zhiliaoapp.musically/4470000000 "
        "[FB_IAB/;FBAN/TikTokAndroid;FBAV/44.7.0;IABMV/1;FBBV/4470000000;FBOP/19;]"
    )
    for target in ("facebook", "instagram", "snapchat", "twitter", "google", "youtube"):
        stripped = referrer_pro._strip_foreign_inapp_markers(ua, target)
        assert "FBAN/TikTokAndroid" not in stripped, (
            f"[{target}] TikTokAndroid bracket leaked: {stripped!r}"
        )
        assert "TikTok/44.7.0" not in stripped, (
            f"[{target}] TikTok/{{ver}} slug leaked: {stripped!r}"
        )
        assert "musical_ly_" not in stripped
        assert "BytedanceWebview" not in stripped
        assert "com.zhiliaoapp" not in stripped


def test_coerce_fb_to_fb_preserves_fb_bracket():
    """A stale FB identity is rebuilt to the one audited bracket."""
    ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.127 "
        "Mobile Safari/537.36 "
        "[FB_IAB/FB4A;FBAN/FB4A;FBAV/550.0.0;IABMV/1;FBBV/620000000;FBOP/19;]"
    )
    out = referrer_pro.coerce_ua_for_platform(ua, "facebook")
    assert "[FB_IAB/FB4A;" in out
    assert "FBAN/FB4A;" not in out
    assert "FBAV/556.0.0.59.68;" in out
    assert "FBBV/681204512;" in out


def test_coerce_fb_to_tiktok_strips_fb_bracket_and_adds_tt_markers():
    """A Facebook UA is rebuilt as the strict canonical TikTok WebView."""
    ua = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.127 "
        "Mobile Safari/537.36 "
        "[FB_IAB/FB4A;FBAN/FB4A;FBAV/550.0.0;IABMV/1;FBBV/620000000;FBOP/19;]"
    )
    out = referrer_pro.coerce_ua_for_platform(ua, "tiktok")
    assert "[FB_IAB/FB4A;" not in out, f"FB bracket leaked: {out!r}"
    assert "FBAN/FB4A" not in out
    assert "musical_ly_2024508020" in out
    assert "FBAN/TikTokAndroid" not in out
    assert "[FB_IAB/" not in out
    assert "TikTok/45.8.2" in out


# ─── 4. Visual Recorder — iframe_path capture surface exists ─────────
def test_visual_recorder_captures_iframe_path_field():
    """Smoke-test: the rich element-capture JS now yields an
    `iframe_path` key (empty list for top-level clicks, list of iframe
    selectors for popup drilling). The Python helper `_build_fallbacks`
    forwards it into `step.fallbacks.iframe_path` for the replay engine.
    """
    from visual_recorder import _build_fallbacks

    # Top-level click → no iframe_path in fallbacks
    fb1 = _build_fallbacks({
        "xpath_stable": "//*[@id='login']",
        "xpath_abs": "/html/body/div[1]/button",
        "text": "Login",
        "tag": "button",
        "nth_of_type": 1,
        "iframe_path": [],
    })
    assert "iframe_path" not in fb1

    # Iframe-drilled click → iframe_path preserved
    fb2 = _build_fallbacks({
        "xpath_stable": "//*[@id='submit']",
        "text": "Submit",
        "iframe_path": ["iframe#exit-intent-modal", "iframe.nested"],
    })
    assert fb2.get("iframe_path") == ["iframe#exit-intent-modal", "iframe.nested"]

    # Junk iframe_path values are filtered out
    fb3 = _build_fallbacks({
        "iframe_path": [None, "iframe#ok", 42, "iframe#also-ok"],
    })
    assert fb3.get("iframe_path") == ["iframe#ok", "iframe#also-ok"]

    # Non-list value ignored
    fb4 = _build_fallbacks({"iframe_path": "iframe#not-a-list"})
    assert "iframe_path" not in fb4
