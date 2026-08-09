"""Iteration 20 regressions aligned with the strict shared UA contract."""
import ast
import random
import re
import sys
import pathlib
from types import SimpleNamespace
from typing import Optional

# Ensure backend on path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import referrer_pro
import visual_recorder
from ua_profile_contract import APP_RELEASES_BY_PLATFORM


SERVER_FILE = pathlib.Path(__file__).resolve().parents[1] / "server.py"
REGION = {
    "code": "US",
    "byte_locale": "en",
    "posix_locale": "en_US",
    "lang_tag": "en-US",
}


def _templates():
    """AST-load generator helpers without importing server dependencies."""
    names = {
        "_ua_android_webview",
        "_ua_ios_wkwebview",
        "_ua_tiktok_android",
        "_ua_facebook_android",
        "_ua_facebook_ios",
    }
    tree = ast.parse(SERVER_FILE.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    runtime_releases = {
        app: {
            platform: [dict(record) for record in records]
            for platform, records in platforms.items()
        }
        for app, platforms in APP_RELEASES_BY_PLATFORM.items()
    }
    namespace = {
        "random": random,
        "Optional": Optional,
        "APP_RELEASES_BY_PLATFORM": APP_RELEASES_BY_PLATFORM,
        "_APP_RELEASES_RUNTIME": runtime_releases,
        "_CHROME_VERSIONS": ["149.0.7827.114"],
        "_ANDROID_WEBVIEW_VERSIONS": ["151.0.7922.83"],
        "_pick_region": lambda _code: REGION,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER_FILE), "exec"), namespace)
    return SimpleNamespace(**namespace)


DEV = {"and_ver": "14", "model": "SM-S928B", "build": "UP1A.231005.007", "sdk": "34"}
TEMPLATES = _templates()


class TestTikTokAndroidWebView:
    def test_ua_tiktok_android_canonical_30_iterations(self):
        for _ in range(30):
            ua = TEMPLATES._ua_tiktok_android(DEV, "45.8.2")
            assert "; wv)" in ua and "Version/4.0" in ua
            assert "Chrome/151.0.7922.83" in ua
            assert "TikTok/45.8.2" in ua
            assert "musical_ly_2024508020" in ua
            assert "app_version/45.8.2" in ua
            assert "com.zhiliaoapp.musically/2024508020" in ua
            assert "Cronet/" not in ua
            assert "FBAN/TikTokAndroid" not in ua
            assert "BytedanceWebview/" not in ua
            assert "ttwebview/" not in ua

    def test_build_inapp_ua_suffix_tiktok_20_iters(self):
        android_base = (
            "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
            "Chrome/149.0.7827.114 Mobile Safari/537.36"
        )
        for _ in range(25):
            out = referrer_pro.build_inapp_ua_suffix("tiktok", android_base)
            assert out.startswith("TikTok/45.8.2 ")
            assert "musical_ly_2024508020" in out
            assert "app_version/45.8.2" in out
            assert "com.zhiliaoapp.musically/2024508020" in out
            assert not any(token in out for token in (
                "FBAN/TikTokAndroid", "BytedanceWebview/", "ttwebview/",
            ))


class TestFacebookUAs:
    def test_fb_android_preserves_full_verified_release(self):
        ua = TEMPLATES._ua_facebook_android(
            DEV, "556.0.0.59.68", "149.0.7827.114"
        )
        assert ua.count("[FB_IAB/FB4A;") == 1
        assert "FBAV/556.0.0.59.68;IABMV/1;FBBV/681204512;" in ua
        assert "FBAN/FB4A;" not in ua
        assert "FBAV/556.0.0;" not in ua

    def test_fb_ios_keeps_audited_release(self):
        ios_dev = {"brand": "iPhone", "ios": "17_5", "model": "iPhone15,3", "scale": "3"}
        ua = TEMPLATES._ua_facebook_ios(ios_dev, "557.0")
        assert "FBAV/557.0;" in ua
        assert "FBAN/FBIOS;" in ua
        assert re.search(r"FBSN/iOS;FBSV/\d", ua)


class TestCoerceIdempotency:
    def test_coerce_tiktok_preserves_own_signature(self):
        ua = TEMPLATES._ua_tiktok_android(DEV, "45.8.2")
        out = referrer_pro.coerce_ua_for_platform(ua, "tiktok")
        assert out == ua
        assert "musical_ly_2024508020" in out
        assert "FBAN/TikTokAndroid" not in out

    def test_coerce_fb_preserves_fb_signature(self):
        ua = TEMPLATES._ua_facebook_android(
            DEV, "556.0.0.59.68", "149.0.7827.114"
        )
        out = referrer_pro.coerce_ua_for_platform(ua, "facebook")
        assert out == ua
        assert "FB_IAB/FB4A" in out
        assert "FBAN/FB4A" not in out
        assert "FBAV/556.0.0.59.68" in out


class TestCoerceCrossPlatform:
    def test_strip_tiktok_when_coercing_away(self):
        ua = TEMPLATES._ua_tiktok_android(DEV, "45.8.2")
        for target in ["facebook", "instagram", "snapchat", "twitter", "linkedin", "pinterest"]:
            out = referrer_pro.coerce_ua_for_platform(ua, target)
            assert "FBAN/TikTokAndroid" not in out, f"[{target}] TikTokAndroid bracket leaked: {out}"
            assert "TikTok/" not in out, f"[{target}] TikTok/ leaked: {out}"
            assert not re.search(r"musical_ly_\d+", out), f"[{target}] musical_ly leaked: {out}"
            assert "BytedanceWebview" not in out
            assert "com.zhiliaoapp.musically" not in out

    def test_fb_to_tiktok_strips_fb_slugs(self):
        ua = TEMPLATES._ua_facebook_android(
            DEV, "556.0.0.59.68", "149.0.7827.114"
        )
        out = referrer_pro.coerce_ua_for_platform(ua, "tiktok")
        assert "FB_IAB/FB4A" not in out, f"FB4A leaked: {out}"
        assert "FBAN/FB4A" not in out, f"FBAN/FB4A leaked: {out}"
        assert "TikTok/45.8.2" in out
        assert "musical_ly_2024508020" in out
        assert "FBAN/TikTokAndroid" not in out


class TestBuildFallbacksIframePath:
    def _call(self, info):
        # _build_fallbacks is module-level in visual_recorder
        return visual_recorder._build_fallbacks(info)

    def test_empty_list_omitted(self):
        fb = self._call({"iframe_path": []})
        assert "iframe_path" not in fb

    def test_populated_list_included(self):
        paths = ["iframe#a", "iframe.b"]
        fb = self._call({"iframe_path": paths})
        assert fb.get("iframe_path") == paths

    def test_junk_entries_filtered(self):
        fb = self._call({"iframe_path": ["iframe#a", None, 42, "x" * 5000, "iframe.b"]})
        got = fb.get("iframe_path", [])
        # Legit entries preserved
        assert "iframe#a" in got
        assert "iframe.b" in got
        # Junk stripped
        assert None not in got
        assert 42 not in got
        assert all(isinstance(x, str) and len(x) <= 5000 for x in got)

    def test_non_list_ignored(self):
        fb = self._call({"iframe_path": "iframe#a"})
        assert "iframe_path" not in fb


class TestUserAgentsLibParse:
    """The canonical WebView UA remains parseable by user_agents."""

    def test_parse_no_exception(self):
        try:
            from user_agents import parse
        except Exception:
            import pytest
            pytest.skip("user_agents not installed")
        ua = TEMPLATES._ua_tiktok_android(DEV, "45.8.2")
        p = parse(ua)
        assert p.is_mobile or p.is_tablet
